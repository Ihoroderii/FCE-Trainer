"""Utilities for syncing tracked portable app state."""
from __future__ import annotations

import logging
import os
import shutil
import sqlite3
from pathlib import Path

logger = logging.getLogger("fce_trainer")

APP_ROOT = Path(__file__).resolve().parent
PORTABLE_STATE_DIR = APP_ROOT / "portable_state"
PORTABLE_DB_PATH = PORTABLE_STATE_DIR / "fce_trainer.db"
RUNTIME_LISTENING_DIR = APP_ROOT / "static" / "listening"
RUNTIME_TRANSCRIPTS_DIR = APP_ROOT / "static" / "transcripts"
PORTABLE_LISTENING_DIR = PORTABLE_STATE_DIR / "static" / "listening"
PORTABLE_TRANSCRIPTS_DIR = PORTABLE_STATE_DIR / "static" / "transcripts"


def runtime_db_path(db_path: Path | None = None) -> Path:
    if db_path is not None:
        return Path(db_path)
    raw = (os.environ.get("DB_PATH") or "").strip()
    return Path(raw).expanduser() if raw else APP_ROOT / "fce_trainer.db"


def _copy_file(source: Path, target: Path) -> bool:
    if not source.exists() or not source.is_file():
        return False
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source, target)
    return True


def _copy_tree(source_dir: Path, target_dir: Path, *, overwrite: bool) -> int:
    if not source_dir.exists():
        return 0
    copied = 0
    for source in sorted(source_dir.rglob("*")):
        if not source.is_file():
            continue
        relative = source.relative_to(source_dir)
        target = target_dir / relative
        if not overwrite and target.exists():
            continue
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, target)
        copied += 1
    return copied


def _replace_tree(source_dir: Path, target_dir: Path) -> int:
    if not source_dir.exists():
        return 0
    if target_dir.exists():
        shutil.rmtree(target_dir)
    return _copy_tree(source_dir, target_dir, overwrite=True)


def _prune_licensed_rag_from_snapshot() -> int:
    """Delete RAG example rows from the tracked snapshot copy.

    The RAG corpus normally lives in its own gitignored database (see
    ``app/rag/db.py``). If someone points ``RAG_DB_PATH`` at the main database,
    this guarantees imported (potentially copyrighted) example text still never
    reaches the committed ``portable_state`` snapshot. Returns rows removed.
    """
    if not PORTABLE_DB_PATH.exists():
        return 0
    conn = None
    try:
        conn = sqlite3.connect(PORTABLE_DB_PATH)
        has_table = conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name='rag_examples'"
        ).fetchone()
        if not has_table:
            return 0
        removed = conn.execute("SELECT COUNT(*) FROM rag_examples").fetchone()[0]
        if removed:
            conn.execute("DELETE FROM rag_examples")
            conn.commit()
            conn.execute("VACUUM")
            logger.warning(
                "portable_state snapshot: removed %d RAG example(s) before commit "
                "(licensed material must not be published).",
                removed,
            )
        return removed
    except sqlite3.Error:
        logger.warning("Could not prune rag_examples from portable_state snapshot", exc_info=True)
        return 0
    finally:
        if conn is not None:
            conn.close()


def sync_portable_state(db_path: Path | None = None) -> dict[str, int | bool]:
    """Copy current runtime state into the tracked portable snapshot."""
    copied_db = _copy_file(runtime_db_path(db_path), PORTABLE_DB_PATH)
    listening_files = _replace_tree(RUNTIME_LISTENING_DIR, PORTABLE_LISTENING_DIR)
    transcript_files = _replace_tree(RUNTIME_TRANSCRIPTS_DIR, PORTABLE_TRANSCRIPTS_DIR)
    rag_pruned = _prune_licensed_rag_from_snapshot() if copied_db else 0
    return {
        "db_copied": copied_db,
        "listening_files": listening_files,
        "transcript_files": transcript_files,
        "rag_examples_pruned": rag_pruned,
    }


def restore_portable_state_if_needed(force: bool = False, db_path: Path | None = None) -> dict[str, int | bool]:
    """Restore the tracked snapshot into runtime locations."""
    db_target = runtime_db_path(db_path)
    restored_db = False
    if PORTABLE_DB_PATH.exists() and (force or not db_target.exists()):
        restored_db = _copy_file(PORTABLE_DB_PATH, db_target)

    listening_files = _copy_tree(
        PORTABLE_LISTENING_DIR,
        RUNTIME_LISTENING_DIR,
        overwrite=force,
    )
    transcript_files = _copy_tree(
        PORTABLE_TRANSCRIPTS_DIR,
        RUNTIME_TRANSCRIPTS_DIR,
        overwrite=force,
    )
    return {
        "db_restored": restored_db,
        "listening_files": listening_files,
        "transcript_files": transcript_files,
    }
