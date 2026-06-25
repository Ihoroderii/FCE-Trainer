from __future__ import annotations

from pathlib import Path

import portable_state_sync as state_sync


def _configure_paths(monkeypatch, runtime_root: Path, portable_root: Path) -> Path:
    runtime_db = runtime_root / "fce_trainer.db"
    monkeypatch.setenv("DB_PATH", str(runtime_db))
    monkeypatch.setattr(state_sync, "PORTABLE_STATE_DIR", portable_root)
    monkeypatch.setattr(state_sync, "PORTABLE_DB_PATH", portable_root / "fce_trainer.db")
    monkeypatch.setattr(state_sync, "RUNTIME_LISTENING_DIR", runtime_root / "static" / "listening")
    monkeypatch.setattr(state_sync, "RUNTIME_TRANSCRIPTS_DIR", runtime_root / "static" / "transcripts")
    monkeypatch.setattr(state_sync, "PORTABLE_LISTENING_DIR", portable_root / "static" / "listening")
    monkeypatch.setattr(state_sync, "PORTABLE_TRANSCRIPTS_DIR", portable_root / "static" / "transcripts")
    return runtime_db


def test_sync_portable_state_copies_db_and_assets(tmp_path, monkeypatch):
    runtime_root = tmp_path / "runtime"
    portable_root = tmp_path / "portable"
    runtime_db = _configure_paths(monkeypatch, runtime_root, portable_root)

    runtime_db.parent.mkdir(parents=True, exist_ok=True)
    runtime_db.write_bytes(b"runtime-db")

    listening_file = state_sync.RUNTIME_LISTENING_DIR / "sample.mp3"
    listening_file.parent.mkdir(parents=True, exist_ok=True)
    listening_file.write_bytes(b"mp3-bytes")

    transcript_file = state_sync.RUNTIME_TRANSCRIPTS_DIR / "sample.txt"
    transcript_file.parent.mkdir(parents=True, exist_ok=True)
    transcript_file.write_text("hello transcript", encoding="utf-8")

    result = state_sync.sync_portable_state()

    assert result == {"db_copied": True, "listening_files": 1, "transcript_files": 1}
    assert state_sync.PORTABLE_DB_PATH.read_bytes() == b"runtime-db"
    assert (state_sync.PORTABLE_LISTENING_DIR / "sample.mp3").read_bytes() == b"mp3-bytes"
    assert (state_sync.PORTABLE_TRANSCRIPTS_DIR / "sample.txt").read_text(encoding="utf-8") == "hello transcript"


def test_restore_portable_state_if_needed_restores_missing_runtime_files(tmp_path, monkeypatch):
    runtime_root = tmp_path / "runtime"
    portable_root = tmp_path / "portable"
    runtime_db = _configure_paths(monkeypatch, runtime_root, portable_root)

    state_sync.PORTABLE_DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    state_sync.PORTABLE_DB_PATH.write_bytes(b"portable-db")

    portable_audio = state_sync.PORTABLE_LISTENING_DIR / "saved.mp3"
    portable_audio.parent.mkdir(parents=True, exist_ok=True)
    portable_audio.write_bytes(b"audio")

    portable_transcript = state_sync.PORTABLE_TRANSCRIPTS_DIR / "saved.txt"
    portable_transcript.parent.mkdir(parents=True, exist_ok=True)
    portable_transcript.write_text("saved transcript", encoding="utf-8")

    result = state_sync.restore_portable_state_if_needed()

    assert result == {"db_restored": True, "listening_files": 1, "transcript_files": 1}
    assert runtime_db.read_bytes() == b"portable-db"
    assert (state_sync.RUNTIME_LISTENING_DIR / "saved.mp3").read_bytes() == b"audio"
    assert (state_sync.RUNTIME_TRANSCRIPTS_DIR / "saved.txt").read_text(encoding="utf-8") == "saved transcript"
