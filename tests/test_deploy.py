"""Tests for the PythonAnywhere deploy helper.

The packaging logic is security-relevant: the local .env holds real provider
keys, so a regression that ships it would leak secrets to the host (and, via
extraction order, overwrite the generated one).
"""
from __future__ import annotations

import tarfile
from pathlib import Path

import pytest

from scripts import deploy_pythonanywhere as deploy


@pytest.fixture()
def fake_project(tmp_path, monkeypatch):
    """A miniature project tree covering every exclusion rule."""
    root = tmp_path / "proj"
    (root / "app").mkdir(parents=True)
    (root / "app" / "__init__.py").write_text("x = 1", encoding="utf-8")
    (root / "static" / "listening").mkdir(parents=True)
    (root / "static" / "listening" / "big.mp3").write_bytes(b"a" * 2048)
    (root / "static" / "styles.css").write_text("body{}", encoding="utf-8")
    (root / "materials").mkdir()
    (root / "materials" / "book.pdf").write_bytes(b"b" * 2048)
    (root / ".venv").mkdir()
    (root / ".venv" / "lib.py").write_text("x", encoding="utf-8")
    (root / "__pycache__").mkdir()
    (root / "__pycache__" / "m.pyc").write_bytes(b"c")
    (root / "portable_state").mkdir()
    (root / "portable_state" / "fce_trainer.db").write_bytes(b"tracked")
    (root / ".env").write_text("OPENAI_API_KEY=sk-secret", encoding="utf-8")
    (root / "fce_trainer.db").write_bytes(b"runtime")
    (root / "rag_examples.db").write_bytes(b"corpus")
    (root / "requirements-deploy.txt").write_text("Flask", encoding="utf-8")

    monkeypatch.setattr(deploy, "PROJECT_ROOT", root)
    return root


def _names(tarball: Path) -> set[str]:
    with tarfile.open(tarball) as tar:
        return set(tar.getnames())


def test_tarball_never_contains_the_local_env(fake_project, tmp_path):
    names = _names(deploy.build_tarball(tmp_path / "out.tar.gz"))
    assert ".env" not in names
    assert not any(n.endswith("/.env") for n in names)


def test_tarball_excludes_generated_and_machine_specific_paths(fake_project, tmp_path):
    names = _names(deploy.build_tarball(tmp_path / "out.tar.gz"))
    assert not any(n.startswith("materials/") for n in names)
    assert not any(n.startswith(".venv/") for n in names)
    assert not any("__pycache__" in n for n in names)
    assert not any(n.endswith(".pyc") for n in names)
    assert not any(n.startswith("static/listening/") for n in names)
    assert "fce_trainer.db" not in names


def test_tarball_keeps_source_and_tracked_snapshot(fake_project, tmp_path):
    names = _names(deploy.build_tarball(tmp_path / "out.tar.gz"))
    assert "app/__init__.py" in names
    assert "static/styles.css" in names
    assert "requirements-deploy.txt" in names
    # The tracked portable snapshot is what restores state on the host.
    assert "portable_state/fce_trainer.db" in names


def test_tarball_excludes_the_rag_corpus(fake_project, tmp_path):
    """Corpus vectors are backend-specific; shipping them would clobber the host."""
    names = _names(deploy.build_tarball(tmp_path / "out.tar.gz"))
    assert "rag_examples.db" not in names


# ── generated .env ───────────────────────────────────────────────────────────

class _Args:
    ai_provider = "google"


def test_env_file_has_a_fresh_64_char_secret_key():
    content = deploy.build_env_file(_Args(), {}).decode()
    line = next(line for line in content.splitlines() if line.startswith("SECRET_KEY="))
    assert len(line.split("=", 1)[1]) == 64


def test_env_file_selects_google_embeddings_for_the_host():
    """The host has no local model, so embeddings must not fall back to keywords."""
    content = deploy.build_env_file(_Args(), {}).decode()
    assert "RAG_EMBEDDING_BACKEND=google" in content
    assert "AI_PROVIDER=google" in content


def test_env_file_forwards_only_configured_keys():
    content = deploy.build_env_file(_Args(), {"GOOGLE_AI_API_KEY": "g-key"}).decode()
    assert "GOOGLE_AI_API_KEY=g-key" in content
    assert "OPENAI_API_KEY" not in content
    assert "DEEPSEEK_API_KEY" not in content


def test_env_file_is_regenerated_when_the_host_has_none():
    def secret_of(text: str) -> str:
        return next(line for line in text.splitlines() if line.startswith("SECRET_KEY="))

    first = deploy.build_env_file(_Args(), {}).decode()
    second = deploy.build_env_file(_Args(), {}).decode()
    assert secret_of(first) != secret_of(second)


def test_env_file_preserves_an_existing_secret_key():
    """Redeploying must not log every user out by rotating SECRET_KEY."""
    prior = {"SECRET_KEY": "a" * 64, "LOG_LEVEL": "DEBUG"}
    content = deploy.build_env_file(_Args(), {}, prior_remote=prior).decode()
    assert "SECRET_KEY=" + "a" * 64 in content


def test_env_file_keeps_host_specific_log_settings():
    prior = {"SECRET_KEY": "b" * 64, "LOG_LEVEL": "WARNING", "LOG_FILE": "logs/custom.log"}
    content = deploy.build_env_file(_Args(), {}, prior_remote=prior).decode()
    assert "LOG_LEVEL=WARNING" in content
    assert "LOG_FILE=logs/custom.log" in content


def test_env_file_defaults_log_file_for_a_new_host():
    content = deploy.build_env_file(_Args(), {}).decode()
    assert "LOG_FILE=logs/fce_trainer.log" in content
    assert "LOG_LEVEL=INFO" in content


def test_env_file_prefers_local_keys_over_stale_host_keys():
    content = deploy.build_env_file(
        _Args(), {"GOOGLE_AI_API_KEY": "new"}, prior_remote={"GOOGLE_AI_API_KEY": "old"}
    ).decode()
    assert "GOOGLE_AI_API_KEY=new" in content
    assert "GOOGLE_AI_API_KEY=old" not in content


def test_parse_env_ignores_comments_and_blanks():
    parsed = deploy.parse_env("# note\n\nA=1\nB = two \n")
    assert parsed == {"A": "1", "B": "two"}
    assert deploy.parse_env(None) == {}


# ── local .env parsing ───────────────────────────────────────────────────────

def test_read_local_env_parses_and_ignores_comments(fake_project):
    values = deploy.read_local_env()
    assert values["OPENAI_API_KEY"] == "sk-secret"
    assert all(not k.startswith("#") for k in values)


def test_wsgi_template_binds_both_app_and_application():
    """PythonAnywhere expects `application`; the app factory returns a Flask app."""
    body = deploy.WSGI_TEMPLATE.format(username="someone")
    assert "application = create_app()" in body
    assert "app = application" in body
    assert "/home/someone/fce_treining" in body
