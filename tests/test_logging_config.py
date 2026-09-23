"""Tests for logging configuration (app/__init__._configure_logging).

Each case runs in a subprocess: _configure_logging calls logging.basicConfig
with force=True, which would otherwise replace handlers underneath the whole
test session.
"""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent


def _run(code: str, env: dict[str, str] | None = None) -> subprocess.CompletedProcess:
    merged = dict(os.environ)
    # Remove inherited overrides so each case starts from a known state.
    for key in ("LOG_LEVEL", "LOG_FILE", "FLASK_DEBUG"):
        merged.pop(key, None)
    merged.update(env or {})
    return subprocess.run(
        [sys.executable, "-c", code],
        capture_output=True, text=True, env=merged, cwd=PROJECT_ROOT, timeout=120,
    )


def test_default_level_is_info():
    result = _run("from app import _LOG_LEVEL_NAME; print(_LOG_LEVEL_NAME)")
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "INFO"


def test_flask_debug_turns_on_debug_level():
    result = _run("from app import _LOG_LEVEL_NAME; print(_LOG_LEVEL_NAME)",
                  {"FLASK_DEBUG": "1"})
    assert result.stdout.strip() == "DEBUG"


def test_explicit_log_level_wins_over_flask_debug():
    result = _run("from app import _LOG_LEVEL_NAME; print(_LOG_LEVEL_NAME)",
                  {"FLASK_DEBUG": "1", "LOG_LEVEL": "WARNING"})
    assert result.stdout.strip() == "WARNING"


def test_invalid_log_level_falls_back_to_default():
    result = _run("from app import _LOG_LEVEL_NAME; print(_LOG_LEVEL_NAME)",
                  {"LOG_LEVEL": "nonsense"})
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "INFO"


def test_log_file_is_created_and_receives_output(tmp_path):
    log_path = tmp_path / "app.log"
    # create_app() is what emits the startup line; importing alone logs nothing.
    result = _run(
        "import app; app.create_app(); print('imported')",
        {"LOG_FILE": str(log_path), "DB_PATH": str(tmp_path / "t.db")},
    )
    assert result.returncode == 0, result.stderr
    assert log_path.exists(), "LOG_FILE was not created"
    assert "fce_trainer" in log_path.read_text(encoding="utf-8")


def test_relative_log_file_resolves_inside_project(tmp_path):
    """A relative LOG_FILE must not depend on the process working directory."""
    result = _run(
        "import os, app; "
        "print(os.path.exists(os.path.join(os.getcwd(), 'logs_probe', 'x.log')))",
        {"LOG_FILE": "logs_probe/x.log"},
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "True"
    probe = PROJECT_ROOT / "logs_probe"
    if probe.exists():
        import shutil
        shutil.rmtree(probe)


def test_unwritable_log_file_does_not_break_startup():
    """A read-only path must degrade to stderr, not crash the app."""
    result = _run(
        "import app; print('still-ok')",
        {"LOG_FILE": "/proc/definitely/not/writable/app.log"},
    )
    assert result.returncode == 0, result.stderr
    assert "still-ok" in result.stdout
