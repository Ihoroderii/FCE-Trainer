"""Embedding + vector index for RAG retrieval.

Two interchangeable backends, selected by ``RAG_EMBEDDING_BACKEND``:

``auto`` (default)
    Prefer a local model when available, otherwise OpenAI, otherwise nothing.
``local``
    ``fastembed`` (ONNX, no PyTorch). Free, offline after the first download and
    needs no API key — the default for a self-hosted trainer.
``openai``
    ``text-embedding-3-small`` (1536-dim). Requires credits.

Whatever the backend, retrieval falls back to keyword matching when no
embeddings are available, so generation keeps working with an empty index.

Because backends produce different vector widths, each row records the model
that produced its vector (``embedding_model``). Vectors from different models
are never compared against each other.

No external vector DB — numpy cosine similarity over SQLite-stored vectors.
"""
from __future__ import annotations

import logging
import os
import time

import numpy as np
import requests

from app.rag.db import rag_connection

logger = logging.getLogger("fce_trainer")

DEFAULT_LOCAL_MODEL = "BAAI/bge-small-en-v1.5"
OPENAI_MODEL = "text-embedding-3-small"
DEFAULT_GOOGLE_MODEL = "gemini-embedding-001"
DEFAULT_GOOGLE_DIM = 768

_local_model = None


def _configured_backend() -> str:
    """Read ``RAG_EMBEDDING_BACKEND`` each time so it stays runtime-configurable."""
    return (os.environ.get("RAG_EMBEDDING_BACKEND") or "auto").strip().lower()


def local_model_name() -> str:
    return (os.environ.get("RAG_EMBEDDING_MODEL") or DEFAULT_LOCAL_MODEL).strip()


def google_model_name() -> str:
    return (os.environ.get("RAG_GOOGLE_EMBEDDING_MODEL") or DEFAULT_GOOGLE_MODEL).strip()


def google_dim() -> int:
    """Gemini supports Matryoshka truncation; a smaller width saves storage."""
    raw = (os.environ.get("RAG_GOOGLE_EMBEDDING_DIM") or str(DEFAULT_GOOGLE_DIM)).strip()
    try:
        dim = int(raw)
    except ValueError:
        return DEFAULT_GOOGLE_DIM
    return dim if dim > 0 else DEFAULT_GOOGLE_DIM


# ── Backend selection ────────────────────────────────────────────────────────

def _local_available() -> bool:
    try:
        import fastembed  # noqa: F401
    except ImportError:
        return False
    return True


def _openai_key() -> str:
    return (os.environ.get("OPENAI_API_KEY") or "").strip()


def _google_key() -> str:
    return (os.environ.get("GOOGLE_AI_API_KEY") or "").strip()


def active_backend() -> str | None:
    """Which embedding backend will be used, or None if unavailable."""
    configured = _configured_backend()
    if configured == "local":
        return "local" if _local_available() else None
    if configured == "openai":
        return "openai" if _openai_key() else None
    if configured in ("google", "gemini"):
        return "google" if _google_key() else None
    # auto
    if _local_available():
        return "local"
    if _openai_key():
        return "openai"
    if _google_key():
        return "google"
    return None


def active_model_name() -> str:
    """Identifier stored alongside each vector ('' when no backend is available).

    The Google entry includes the width because Matryoshka truncation means the
    same model can legitimately produce different-length vectors.
    """
    backend = active_backend()
    if backend == "local":
        return local_model_name()
    if backend == "openai":
        return OPENAI_MODEL
    if backend == "google":
        return f"{google_model_name()}@{google_dim()}"
    return ""


def _load_local_model():
    global _local_model
    if _local_model is None:
        from fastembed import TextEmbedding
        name = local_model_name()
        logger.info("RAG: loading local embedding model %s (first run downloads it)", name)
        _local_model = TextEmbedding(model_name=name)
    return _local_model


def _local_embed(texts: list[str], *, for_query: bool) -> list[np.ndarray]:
    """Embed with fastembed.

    bge models are trained with asymmetric prefixes, so queries and passages go
    through different methods when the installed version exposes them.
    """
    model = _load_local_model()
    method = None
    if not for_query and hasattr(model, "passage_embed"):
        method = model.passage_embed
    elif for_query and hasattr(model, "query_embed"):
        method = model.query_embed
    if method is None:
        method = model.embed
    return [np.asarray(v, dtype=np.float32) for v in method(texts)]


def _openai_embed(texts: list[str]) -> list[np.ndarray] | None:
    key = _openai_key()
    if not key:
        return None
    try:
        from openai import OpenAI
        client = OpenAI(api_key=key)
        resp = client.embeddings.create(model=OPENAI_MODEL, input=[t[:8000] for t in texts])
        vectors: list[np.ndarray | None] = [None] * len(texts)
        for item in resp.data:
            vectors[item.index] = np.array(item.embedding, dtype=np.float32)
        return [v for v in vectors if v is not None] or None
    except Exception:
        logger.exception("RAG: OpenAI embedding request failed")
        return None


def _google_batch_size() -> int:
    """How many texts to send per Gemini batch request.

    The free tier rate-limits by request, and a single large batch can trip a
    429, so batches stay modest and are paced.
    """
    raw = (os.environ.get("RAG_GOOGLE_BATCH_SIZE") or "25").strip()
    try:
        size = int(raw)
    except ValueError:
        return 25
    return size if size > 0 else 25


def _google_embed(texts: list[str]) -> list[np.ndarray] | None:
    """Embed with the Gemini REST API (batched when there is more than one text).

    Useful where a local model cannot be installed (e.g. small hosting quotas)
    because the free tier covers it and googleapis.com is widely allowlisted.
    Each batch is retried with backoff, since the free tier returns 429 when
    several requests land in the same minute.
    """
    key = _google_key()
    if not key:
        return None

    model = google_model_name()
    dim = google_dim()
    api_base = "https://generativelanguage.googleapis.com/v1beta"

    def _request(text_batch: list[str], *, batch: bool) -> list[np.ndarray]:
        if batch:
            url = f"{api_base}/models/{model}:batchEmbedContents"
            payload = {"requests": [
                {
                    "model": f"models/{model}",
                    "content": {"parts": [{"text": t[:8000]}]},
                    "outputDimensionality": dim,
                }
                for t in text_batch
            ]}
        else:
            url = f"{api_base}/models/{model}:embedContent"
            payload = {
                "model": f"models/{model}",
                "content": {"parts": [{"text": text_batch[0][:8000]}]},
                "outputDimensionality": dim,
            }

        last_error = ""
        for attempt in range(5):
            resp = requests.post(url, params={"key": key}, json=payload, timeout=60)
            if resp.status_code == 200:
                data = resp.json()
                if batch:
                    return [np.array(e["values"], dtype=np.float32) for e in data["embeddings"]]
                return [np.array(data["embedding"]["values"], dtype=np.float32)]
            try:
                last_error = str(resp.json().get("error", {}).get("message", resp.text))[:200]
            except Exception:
                last_error = resp.text[:200]
            # 429 (quota/rate) and 5xx are worth waiting out; anything else is not.
            if resp.status_code not in (429, 500, 502, 503, 504):
                break
            wait = min(30, 2 ** attempt)
            logger.warning("RAG: Gemini embeddings %s, retrying in %ss", resp.status_code, wait)
            time.sleep(wait)
        raise RuntimeError(f"Gemini embeddings failed: {last_error}")

    try:
        if len(texts) == 1:
            return _request(texts, batch=False)

        batch_size = _google_batch_size()
        out: list[np.ndarray] = []
        for start in range(0, len(texts), batch_size):
            if start:
                time.sleep(1)  # pace requests to stay under the per-minute limit
            out.extend(_request(texts[start:start + batch_size], batch=True))
        return out
    except Exception:
        logger.exception("RAG: Gemini embedding request failed")
        return None


# ── Public API ───────────────────────────────────────────────────────────────

def get_embedding(text: str) -> np.ndarray | None:
    """Embed a single query string. Returns None if no backend is available."""
    vectors = get_embeddings_batch([text], for_query=True)
    return vectors[0] if vectors else None


def get_embeddings_batch(texts: list[str], *, for_query: bool = False) -> list[np.ndarray] | None:
    """Embed several texts. Returns None (not a partial list) on failure."""
    if not texts:
        return []
    backend = active_backend()
    if backend == "local":
        try:
            return _local_embed(texts, for_query=for_query)
        except Exception:
            logger.exception("RAG: local embedding failed")
            return None
    if backend == "openai":
        return _openai_embed(texts)
    if backend == "google":
        return _google_embed(texts)
    return None


def embedding_to_bytes(vec: np.ndarray) -> bytes:
    """Serialize a float32 vector to bytes for SQLite BLOB storage."""
    return np.asarray(vec, dtype=np.float32).tobytes()


def bytes_to_embedding(data: bytes) -> np.ndarray:
    """Deserialize bytes back to a float32 vector."""
    return np.frombuffer(data, dtype=np.float32)


def cosine_similarity(a: np.ndarray, b: np.ndarray) -> float:
    """Cosine similarity between two vectors (0.0 for mismatched or empty vectors)."""
    if a is None or b is None or a.shape != b.shape:
        return 0.0
    norm = float(np.linalg.norm(a)) * float(np.linalg.norm(b))
    if norm == 0.0:
        return 0.0
    return float(np.dot(a, b) / norm)


def rebuild_embeddings(force: bool = False) -> int:
    """Compute and store embeddings for examples missing one.

    With ``force=True`` every example is re-embedded, which is required after
    switching backends because vector widths differ. Returns rows updated.
    """
    model_name = active_model_name()
    if not model_name:
        logger.warning(
            "RAG: no embedding backend available (install fastembed or set "
            "OPENAI_API_KEY) — retrieval will use keyword matching"
        )
        return 0

    with rag_connection() as conn:
        if force:
            rows = conn.execute("SELECT id, search_text FROM rag_examples").fetchall()
        else:
            rows = conn.execute(
                "SELECT id, search_text FROM rag_examples "
                "WHERE embedding IS NULL OR IFNULL(embedding_model, '') != ?",
                (model_name,),
            ).fetchall()

    if not rows:
        logger.info("RAG: all examples already embedded with %s", model_name)
        return 0

    texts = [r["search_text"] for r in rows]
    ids = [r["id"] for r in rows]

    logger.info("RAG: embedding %d example(s) with %s…", len(texts), model_name)
    vectors = get_embeddings_batch(texts)
    if not vectors or len(vectors) != len(ids):
        logger.error("RAG: embedding backend returned no usable vectors")
        return 0

    updated = 0
    with rag_connection() as conn:
        for eid, vec in zip(ids, vectors, strict=True):
            conn.execute(
                "UPDATE rag_examples SET embedding = ?, embedding_model = ? WHERE id = ?",
                (embedding_to_bytes(vec), model_name, eid),
            )
            updated += 1
        conn.commit()

    logger.info("RAG: %d/%d embeddings stored with %s", updated, len(rows), model_name)
    return updated
