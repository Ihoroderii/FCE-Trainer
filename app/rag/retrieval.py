"""RAG retrieval — find similar examples for a generation request.

Two strategies:
1. Embedding similarity (when an embedding backend is available)
2. Keyword/metadata fallback (always works, no API needed)

Both first filter by paper+part metadata, then rank by relevance. Query vectors
are cached, so repeated generations for the same topic do not call the embedding
provider again.
"""
from __future__ import annotations

import hashlib
import logging
import random
import re
from typing import Any

from app.rag.db import rag_connection
from app.rag.embeddings import (
    active_model_name,
    bytes_to_embedding,
    cosine_similarity,
    embedding_to_bytes,
    get_embedding,
)

logger = logging.getLogger("fce_trainer")

# How many reference examples to include in the generation prompt
DEFAULT_TOP_K = 3


def retrieve_examples(
    *,
    paper: str,
    part: int,
    topic: str = "",
    task_type: str = "",
    k: int = DEFAULT_TOP_K,
) -> list[dict]:
    """Retrieve the top-k most relevant RAG examples for a generation request.

    Returns a list of dicts with keys: id, paper, part, task_type, topic,
    prompt_text, metadata, search_text. Returns [] if no examples exist.
    """
    # 1. Filter candidates by metadata
    candidates = _fetch_candidates(paper, part, task_type)
    if not candidates:
        return []

    # 2. Try embedding-based retrieval
    if topic:
        query_text = f"B2 First | {paper.replace('_', ' ').title()} | Part {part}"
        if task_type:
            query_text += f" | {task_type.replace('_', ' ')}"
        query_text += f" | topic: {topic}"

        results = _retrieve_by_embedding(query_text, candidates, k)
        if results:
            return results

    # 3. Fallback: keyword match on topic, then random
    return _retrieve_by_keywords(topic, candidates, k)


def format_examples_for_prompt(examples: list[dict]) -> str:
    """Format retrieved examples into a string block for injection into prompts.

    Returns empty string if no examples (so the prompt works without RAG).
    """
    if not examples:
        return ""

    lines = ["\n--- REFERENCE EXAMPLES (for style only — create an ORIGINAL task, do NOT copy) ---\n"]
    for i, ex in enumerate(examples, 1):
        lines.append(f"[Example {i}]")
        if ex.get("topic"):
            lines.append(f"Topic: {ex['topic']}")
        lines.append(ex["prompt_text"].strip())
        lines.append("")  # blank line separator
    lines.append("--- END REFERENCE EXAMPLES ---\n")
    lines.append(
        "IMPORTANT: Use the examples above ONLY as style/format references. "
        "Create a completely original task with different content. "
        "Do NOT copy sentences or wording from the examples.\n"
    )
    return "\n".join(lines)


# ── Internal ─────────────────────────────────────────────────────────────────

def _fetch_candidates(paper: str, part: int, task_type: str = "") -> list[dict]:
    """Fetch all examples matching paper+part (+ optional task_type) from DB."""
    clauses = ["paper = ?", "part = ?"]
    params: list[Any] = [paper.lower(), part]
    if task_type:
        clauses.append("task_type = ?")
        params.append(task_type.lower())

    where = " AND ".join(clauses)
    with rag_connection() as conn:
        rows = conn.execute(
            f"SELECT id, paper, part, task_type, topic, search_text, prompt_text, "
            f"metadata_json, embedding, embedding_model FROM rag_examples WHERE {where}",
            params,
        ).fetchall()
    return [dict(r) for r in rows]


def _cached_query_embedding(model: str, query_text: str):
    """Look up a previously computed query vector (None on a miss or any error)."""
    try:
        with rag_connection() as conn:
            row = conn.execute(
                "SELECT embedding FROM rag_query_cache WHERE query_hash = ? AND model = ?",
                (_query_hash(query_text), model),
            ).fetchone()
    except Exception:
        # Caching is an optimisation; a missing or broken cache must not stop
        # retrieval, so fall through and compute the vector normally.
        logger.debug("RAG: query cache unavailable", exc_info=True)
        return None
    return bytes_to_embedding(row["embedding"]) if row else None


def _store_query_embedding(model: str, query_text: str, vector) -> None:
    """Remember a query vector so the provider is not called again for it."""
    try:
        with rag_connection() as conn:
            conn.execute(
                "INSERT OR REPLACE INTO rag_query_cache (query_hash, model, embedding) "
                "VALUES (?, ?, ?)",
                (_query_hash(query_text), model, embedding_to_bytes(vector)),
            )
            conn.commit()
    except Exception:
        # Caching is an optimisation; never fail a retrieval over it.
        logger.debug("RAG: could not cache query embedding", exc_info=True)


def _query_hash(query_text: str) -> str:
    return hashlib.sha256(query_text.encode("utf-8")).hexdigest()


def _retrieve_by_embedding(query_text: str, candidates: list[dict], k: int) -> list[dict]:
    """Rank candidates by cosine similarity to the query embedding.

    Only vectors produced by the currently active model are compared, since a
    different backend yields a different vector width and the scores would be
    meaningless.
    """
    active_model = active_model_name()

    query_vec = None
    if active_model:
        query_vec = _cached_query_embedding(active_model, query_text)
    cache_hit = query_vec is not None
    if query_vec is None:
        query_vec = get_embedding(query_text)
        if query_vec is not None and active_model:
            _store_query_embedding(active_model, query_text, query_vec)
    if query_vec is None:
        return []

    scored = []
    for c in candidates:
        if not c.get("embedding"):
            continue
        if active_model and c.get("embedding_model") != active_model:
            continue
        c_vec = bytes_to_embedding(c["embedding"])
        if c_vec.shape != query_vec.shape:
            continue
        scored.append((cosine_similarity(query_vec, c_vec), c))

    if not scored:
        return []

    scored.sort(key=lambda x: x[0], reverse=True)
    results = []
    for score, c in scored[:k]:
        clean = _clean_candidate(c)
        clean["retrieval"] = "embedding"
        clean["score"] = round(float(score), 4)
        results.append(clean)

    logger.debug(
        "RAG embedding retrieval: %d candidates, top %d (query cache %s)",
        len(scored), len(results), "hit" if cache_hit else "miss",
    )
    return results


# Words too common to indicate topical similarity. Without this, a natural
# language topic like "a sculptor's block of stone" scores 0 against every
# example (its words are all "a"/"of"/"the"), the sort becomes a no-op, and the
# fallback silently returns the same first rows in database order every time.
_STOPWORDS = {
    "a", "an", "the", "of", "and", "or", "in", "on", "at", "to", "for", "with",
    "about", "that", "this", "these", "those", "is", "are", "was", "were", "be",
    "been", "being", "it", "its", "as", "by", "from", "into", "your", "you",
    "my", "me", "i", "he", "she", "they", "we", "them", "his", "her", "their",
    "our", "who", "what", "when", "where", "how", "why", "not", "but", "very",
}


def _content_words(text: str) -> set[str]:
    """Lowercased words that carry topic meaning (stopwords and short words out).

    Apostrophes are treated as separators so "sculptor's" matches "sculptor".
    """
    return {
        w for w in re.findall(r"[a-z]+", (text or "").lower())
        if w not in _STOPWORDS and len(w) > 2
    }


def _retrieve_by_keywords(topic: str, candidates: list[dict], k: int) -> list[dict]:
    """Simple keyword-based fallback: score by topic word overlap, then random."""
    topic_words = set(topic.lower().split()) if topic else set()

    if topic_words:
        scored = []
        for c in candidates:
            c_words = _content_words(c.get("topic", "")) | _content_words(c.get("search_text", ""))
            scored.append((len(topic_words & c_words), c))
        scored.sort(key=lambda x: x[0], reverse=True)
        if scored and scored[0][0] == 0:
            logger.warning(
                "RAG: no keyword overlap for topic %r — falling back to arbitrary "
                "order. Retrieval quality is degraded until embeddings work.", topic,
            )
    else:
        scored = [(0, c) for c in candidates]
        random.shuffle(scored)

    results = []
    for overlap, c in scored[:k]:
        clean = _clean_candidate(c)
        clean["retrieval"] = "keyword"
        clean["score"] = overlap
        results.append(clean)

    logger.debug("RAG keyword retrieval: %d candidates, returning %d",
                 len(scored), len(results))
    return results


def _clean_candidate(c: dict) -> dict:
    """Remove embedding blob and parse metadata."""
    import json
    d = {k: v for k, v in c.items() if k != "embedding"}
    if "metadata_json" in d:
        try:
            d["metadata"] = json.loads(d["metadata_json"])
        except (json.JSONDecodeError, TypeError):
            d["metadata"] = {}
        del d["metadata_json"]
    return d
