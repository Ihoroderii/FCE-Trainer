"""RAG retrieval — find similar examples for a generation request.

Two strategies:
1. Embedding similarity (if OpenAI key available and examples have embeddings)
2. Keyword/metadata fallback (always works, no API needed)

Both first filter by paper+part metadata, then rank by relevance.
"""
from __future__ import annotations

import logging
import random
from typing import Any

from app.db import db_connection
from app.rag.embeddings import (
    bytes_to_embedding,
    cosine_similarity,
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
    with db_connection() as conn:
        rows = conn.execute(
            f"SELECT id, paper, part, task_type, topic, search_text, prompt_text, "
            f"metadata_json, embedding FROM rag_examples WHERE {where}",
            params,
        ).fetchall()
    return [dict(r) for r in rows]


def _retrieve_by_embedding(query_text: str, candidates: list[dict], k: int) -> list[dict]:
    """Rank candidates by cosine similarity to query embedding."""
    query_vec = get_embedding(query_text)
    if query_vec is None:
        return []

    scored = []
    for c in candidates:
        if not c.get("embedding"):
            continue
        c_vec = bytes_to_embedding(c["embedding"])
        score = cosine_similarity(query_vec, c_vec)
        scored.append((score, c))

    if not scored:
        return []

    scored.sort(key=lambda x: x[0], reverse=True)
    results = []
    for _, c in scored[:k]:
        results.append(_clean_candidate(c))

    logger.debug("RAG embedding retrieval: %d candidates, returning top %d", len(scored), len(results))
    return results


def _retrieve_by_keywords(topic: str, candidates: list[dict], k: int) -> list[dict]:
    """Simple keyword-based fallback: score by topic word overlap, then random."""
    topic_words = set(topic.lower().split()) if topic else set()

    if topic_words:
        scored = []
        for c in candidates:
            c_words = set(c.get("topic", "").lower().split()) | set(c.get("search_text", "").lower().split())
            overlap = len(topic_words & c_words)
            scored.append((overlap, c))
        scored.sort(key=lambda x: x[0], reverse=True)
        candidates_sorted = [c for _, c in scored]
    else:
        candidates_sorted = candidates[:]
        random.shuffle(candidates_sorted)

    results = [_clean_candidate(c) for c in candidates_sorted[:k]]
    logger.debug("RAG keyword retrieval: %d candidates, returning %d", len(candidates_sorted), len(results))
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
