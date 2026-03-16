"""Tests for database operations."""
from __future__ import annotations

from app.db import db_connection, get_task_by_id_for_part, init_db


class TestMigrations:
    """Test that the migration infrastructure works."""

    def test_migrations_table_created(self, app):
        with app.app_context():
            with db_connection() as conn:
                cur = conn.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='_migrations'")
                assert cur.fetchone() is not None

    def test_migrations_are_idempotent(self, app):
        """Running migrations twice should not fail."""
        with app.app_context():
            from app.db import _ensure_uoe_grammar_topic_column, _ensure_check_history_user_id, _ensure_users_password_column
            # These already ran during create_app; run them again
            _ensure_uoe_grammar_topic_column()
            _ensure_check_history_user_id()
            _ensure_users_password_column()
            # Should not raise


class TestIndexes:
    def test_check_history_indexes_exist(self, app):
        with app.app_context():
            with db_connection() as conn:
                cur = conn.execute("SELECT name FROM sqlite_master WHERE type='index'")
                indexes = {r["name"] for r in cur.fetchall()}
            assert "idx_check_history_user_id" in indexes
            assert "idx_check_history_created_at" in indexes
            assert "idx_check_history_user_part" in indexes


class TestTaskRetrieval:
    def test_get_nonexistent_task(self, app):
        with app.app_context():
            result = get_task_by_id_for_part(1, 99999)
            assert result is None

    def test_get_task_invalid_part(self, app):
        with app.app_context():
            result = get_task_by_id_for_part(99, 1)
            assert result is None
