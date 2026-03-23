"""Embedding + vector index for RAG retrieval.

Uses OpenAI text-embedding-3-small (cheap, fast, good enough for <1000 items).
Falls back to keyword matching if no OpenAI key is available.

No external vector DB needed — uses numpy cosine similarity over SQLite-stored vectors.
"""
from __future__ import annotations

import logging
import os
import struct
from typing import Any

import numpy as np

from app.db import db_connection

logger = logging.getLogger("fce_trainer")

EMBEDDING_MODEL = "text-embedding-3-small"
EMBEDDING_DIM = 1536  # text-embedding-3-small output dimension


def get_embedding(text: str) -> np.ndarray | None:
    """Get embedding vector for text using OpenAI API. Returns None if unavailable."""
    api_key = os.environ.get("OPENAI_API_KEY", "").strip()
    if not api_key:
        return None

    try:
        from openai import OpenAI
        client = OpenAI(api_key=api_key)
        resp = client.embeddings.create(model=EMBEDDING_MODEL, input=text[:8000])
        return np.array(resp.data[0].embedding, dtype=np.float32)
    except Exception:
        logger.exception("Failed to get embedding")
        return None


def get_embeddings_batch(texts: list[str]) -> list[np.ndarray | None]:
    """Get embeddings for multiple texts in one API call."""
    api_key = os.environ.get("OPENAI_API_KEY", "").strip()
    if not api_key:
        return [None] * len(texts)

    try:
        from openai import OpenAI
        client = OpenAI(api_key=api_key)
        # OpenAI batch limit is 2048 inputs — we'll never hit that with <1000 examples
        resp = client.embeddings.create(model=EMBEDDING_MODEL, input=[t[:8000] for t in texts])
        vectors = [None] * len(texts)
        for item in resp.data:
            vectors[item.index] = np.array(item.embedding, dtype=np.float32)
        return vectors
    except Exception:
        logger.exception("Failed to get batch embeddings")
        return [None] * len(texts)


def embedding_to_bytes(vec: np.ndarray) -> bytes:
    """Serialize numpy float32 vector to bytes for SQLite BLOB storage."""
    return vec.astype(np.float32).tobytes()


def bytes_to_embedding(data: bytes) -> np.ndarray:
    """Deserialize bytes back to numpy float32 vector."""
    return np.frombuffer(data, dtype=np.float32)


def cosine_similarity(a: np.ndarray, b: np.ndarray) -> float:
    """Cosine similarity between two vectors."""
    dot = np.dot(a, b)
    norm = np.linalg.norm(a) * np.linalg.norm(b)
    if norm == 0:
        return 0.0
    return float(dot / norm)


def rebuild_embeddings() -> int:
    """Compute and store embeddings for all examples that don't have one yet.

    Returns the number of examples updated.
    """
    with db_connection() as conn:
        rows = conn.execute(
            "SELECT id, search_text FROM rag_examples WHERE embedding IS NULL"
        ).fetchall()

    if not rows:
        logger.info("RAG: all examples already have embeddings")
        return 0

    texts = [r["search_text"] for r in rows]
    ids = [r["id"] for r in rows]

    logger.info("RAG: computing embeddings for %d examples...", len(texts))
    vectors = get_embeddings_batch(texts)

    updated = 0
    with db_connection() as conn:
        for eid, vec in zip(ids, vectors):
            if vec is not None:
                conn.execute(
                    "UPDATE rag_examples SET embedding = ? WHERE id = ?",
                    (embedding_to_bytes(vec), eid),
                )
                updated += 1
        conn.commit()

    logger.info("RAG: %d/%d embeddings computed and stored", updated, len(rows))
    return updated
