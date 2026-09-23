"""Dedicated SQLite connection for the RAG example corpus.

The corpus is kept OUT of the main application database on purpose.

RAG examples are typically imported from third-party study material (e.g. a
published FCE student book). The main database is copied verbatim into
``portable_state/fce_trainer.db`` by ``sync_portable_state()``, and that file
IS tracked by git and pushed to a public repository. Storing imported,
copyrighted material there would effectively republish it.

Keeping the corpus in its own file (gitignored by default) means:
  * importing a book never puts licensed text into a commit, and
  * deleting the corpus is a single file removal.

Override the location with ``RAG_DB_PATH``. If you point it at the main
database you lose that protection, so ``sync_portable_state()`` also prunes
``rag_examples`` from the snapshot it writes.
"""
from __future__ import annotations

import contextlib
import logging
import os
import sqlite3
from pathlib import Path

logger = logging.getLogger("fce_trainer")

APP_ROOT = Path(__file__).resolve().parent.parent.parent
DEFAULT_RAG_DB_NAME = "rag_examples.db"


def rag_db_path() -> Path:
    """Resolve the RAG database path (``RAG_DB_PATH`` env var or project root)."""
    raw = (os.environ.get("RAG_DB_PATH") or "").strip()
    if raw:
        return Path(raw).expanduser()
    return APP_ROOT / DEFAULT_RAG_DB_NAME


def get_rag_db() -> sqlite3.Connection:
    """Open a connection to the RAG database, creating parent dirs as needed."""
    path = rag_db_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    return conn


@contextlib.contextmanager
def rag_connection():
    """Context manager yielding a RAG database connection, closed on exit."""
    conn = get_rag_db()
    try:
        yield conn
    finally:
        conn.close()
