"""Shared test fixtures for FCE-Trainer."""
from __future__ import annotations

import os
import tempfile

import pytest

# Ensure we use a test database
os.environ.setdefault("SECRET_KEY", "test-secret-key-for-pytest")


@pytest.fixture()
def app(tmp_path):
    """Create a Flask app configured for testing with an isolated DB."""
    # Override DB path before importing app modules
    db_file = tmp_path / "test.db"
    import app.config as cfg

    original_db = cfg.DB_PATH
    cfg.DB_PATH = db_file
    try:
        from app import create_app

        test_app = create_app()
        test_app.config["TESTING"] = True
        test_app.config["WTF_CSRF_ENABLED"] = False
        yield test_app
    finally:
        cfg.DB_PATH = original_db


@pytest.fixture()
def client(app):
    """A Flask test client for sending requests."""
    return app.test_client()


@pytest.fixture()
def auth_client(app):
    """A Flask test client with a logged-in user session."""
    from app.services.user import create_email_user

    with app.app_context():
        uid = create_email_user("test@example.com", "password123", "Test User")

    client = app.test_client()
    with client.session_transaction() as sess:
        sess["user_id"] = uid
        sess["user_email"] = "test@example.com"
        sess["user_name"] = "Test User"
    return client
