"""RAG example storage — SQLite table + CRUD operations.

Each example represents one real FCE exam task (or a high-quality original)
with structured metadata and the full prompt/task text.
"""
from __future__ import annotations

import json
import logging

from app.rag.db import rag_connection

logger = logging.getLogger("fce_trainer")

# ── Schema ───────────────────────────────────────────────────────────────────

RAG_SCHEMA = """
CREATE TABLE IF NOT EXISTS rag_examples (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    paper         TEXT NOT NULL,          -- 'reading', 'use_of_english', 'writing', 'listening', 'speaking'
    part          INTEGER NOT NULL,       -- 1-7 (matches app part numbers)
    task_type     TEXT NOT NULL DEFAULT '', -- 'multiple_choice_cloze', 'open_cloze', 'essay', 'review', etc.
    topic         TEXT NOT NULL DEFAULT '',
    level         TEXT NOT NULL DEFAULT 'b2',
    search_text   TEXT NOT NULL,          -- combined text used for embedding
    prompt_text   TEXT NOT NULL,          -- full example task (the actual exam prompt/task)
    metadata_json TEXT NOT NULL DEFAULT '{}',  -- any extra metadata (target_reader, purpose, word_limit, etc.)
    embedding     BLOB,                   -- serialised float32 vector (numpy .tobytes())
    embedding_model TEXT NOT NULL DEFAULT '',  -- which model produced `embedding`
    created_at    TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_rag_paper_part ON rag_examples(paper, part);
CREATE INDEX IF NOT EXISTS idx_rag_task_type  ON rag_examples(task_type);

-- Query embeddings are cached because generation topics come from a small fixed
-- set of strings, so the same query vector is reused many times. This keeps
-- retrieval off the embedding provider at runtime (important on a host with a
-- tiny CPU quota or a rate-limited free tier).
CREATE TABLE IF NOT EXISTS rag_query_cache (
    query_hash TEXT NOT NULL,
    model      TEXT NOT NULL,
    embedding  BLOB NOT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (query_hash, model)
);
"""


def ensure_rag_tables() -> None:
    """Create RAG tables if they don't exist and apply lightweight migrations."""
    with rag_connection() as conn:
        conn.executescript(RAG_SCHEMA)
        # Vectors from different models have different widths and must not be
        # compared, so every row records the model that produced it.
        columns = {row["name"] for row in conn.execute("PRAGMA table_info(rag_examples)")}
        if "embedding_model" not in columns:
            conn.execute(
                "ALTER TABLE rag_examples ADD COLUMN embedding_model TEXT NOT NULL DEFAULT ''"
            )
        conn.commit()


# ── CRUD ─────────────────────────────────────────────────────────────────────

def add_example(
    *,
    paper: str,
    part: int,
    task_type: str,
    topic: str,
    prompt_text: str,
    level: str = "b2",
    metadata: dict | None = None,
    search_text: str | None = None,
) -> int:
    """Insert a new RAG example. Returns the new row id.

    If search_text is not provided, it is built automatically from the fields.
    Embedding is computed lazily on first retrieval (or via rebuild_index).
    """
    if not search_text:
        search_text = _build_search_text(paper, part, task_type, topic, level, prompt_text, metadata)

    meta_json = json.dumps(metadata or {})

    with rag_connection() as conn:
        cur = conn.execute(
            """INSERT INTO rag_examples
               (paper, part, task_type, topic, level, search_text, prompt_text, metadata_json)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (paper.lower(), part, task_type.lower(), topic.lower(), level.lower(),
             search_text, prompt_text, meta_json),
        )
        conn.commit()
        row_id = cur.lastrowid
    logger.info("RAG example added: id=%d paper=%s part=%d type=%s topic=%s", row_id, paper, part, task_type, topic)
    return row_id


def get_example(example_id: int) -> dict | None:
    with rag_connection() as conn:
        row = conn.execute("SELECT * FROM rag_examples WHERE id = ?", (example_id,)).fetchone()
    return _row_to_dict(row) if row else None


def list_examples(paper: str | None = None, part: int | None = None, task_type: str | None = None) -> list[dict]:
    """List examples, optionally filtered by paper/part/task_type."""
    clauses, params = [], []
    if paper:
        clauses.append("paper = ?")
        params.append(paper.lower())
    if part is not None:
        clauses.append("part = ?")
        params.append(part)
    if task_type:
        clauses.append("task_type = ?")
        params.append(task_type.lower())

    where = (" WHERE " + " AND ".join(clauses)) if clauses else ""
    with rag_connection() as conn:
        rows = conn.execute(f"SELECT * FROM rag_examples{where} ORDER BY id", params).fetchall()
    return [_row_to_dict(r) for r in rows]


def delete_example(example_id: int) -> bool:
    with rag_connection() as conn:
        conn.execute("DELETE FROM rag_examples WHERE id = ?", (example_id,))
        conn.commit()
        return conn.total_changes > 0


def count_examples(paper: str | None = None, part: int | None = None) -> int:
    clauses, params = [], []
    if paper:
        clauses.append("paper = ?")
        params.append(paper.lower())
    if part is not None:
        clauses.append("part = ?")
        params.append(part)
    where = (" WHERE " + " AND ".join(clauses)) if clauses else ""
    with rag_connection() as conn:
        row = conn.execute(f"SELECT COUNT(*) as cnt FROM rag_examples{where}", params).fetchone()
    return row["cnt"] if row else 0


# ── Helpers ──────────────────────────────────────────────────────────────────

def _build_search_text(paper: str, part: int, task_type: str, topic: str,
                       level: str, prompt_text: str, metadata: dict | None) -> str:
    """Build the combined search text used for embedding."""
    parts = [
        f"B2 First | {paper.replace('_', ' ').title()} | Part {part}",
        task_type.replace("_", " ") if task_type else "",
        f"topic: {topic}" if topic else "",
        f"level: {level}" if level else "",
    ]
    if metadata:
        if metadata.get("target_reader"):
            parts.append(f"target reader: {metadata['target_reader']}")
        if metadata.get("purpose"):
            parts.append(f"purpose: {metadata['purpose']}")
        if metadata.get("word_limit"):
            parts.append(f"{metadata['word_limit']} words")
    # Add first 300 chars of prompt for topic matching
    parts.append(prompt_text[:300])
    return " | ".join(p for p in parts if p)


def _row_to_dict(row) -> dict:
    d = dict(row)
    d.pop("embedding", None)  # Don't include raw bytes in dict
    if "metadata_json" in d:
        try:
            d["metadata"] = json.loads(d["metadata_json"])
        except (json.JSONDecodeError, TypeError):
            d["metadata"] = {}
    return d
