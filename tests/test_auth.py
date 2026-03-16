"""Tests for authentication and route protection."""
from __future__ import annotations


class TestLoginRequired:
    """Test that protected routes redirect unauthenticated users."""

    def test_stats_requires_login(self, client):
        resp = client.get("/stats")
        assert resp.status_code == 302
        assert "/login" in resp.headers["Location"]

    def test_mock_exam_requires_login(self, client):
        resp = client.get("/mock-exam")
        assert resp.status_code == 302
        assert "/login" in resp.headers["Location"]

    def test_stats_accessible_when_logged_in(self, auth_client):
        resp = auth_client.get("/stats")
        assert resp.status_code == 200


class TestHealthEndpoint:
    def test_health(self, client):
        resp = client.get("/health")
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["status"] == "ok"


class TestHomeEndpoint:
    def test_home_accessible(self, client):
        resp = client.get("/")
        assert resp.status_code == 200


class TestRegistration:
    def test_register_page_loads(self, client):
        resp = client.get("/register")
        assert resp.status_code == 200

    def test_register_with_valid_data(self, client):
        resp = client.post("/register", data={
            "email": "new@example.com",
            "password": "securepass123",
            "password_confirm": "securepass123",
            "name": "New User",
        })
        assert resp.status_code == 302
        assert "/" in resp.headers["Location"]

    def test_register_short_password(self, client):
        resp = client.post("/register", data={
            "email": "new@example.com",
            "password": "short",
            "password_confirm": "short",
            "name": "New User",
        })
        assert resp.status_code == 200
        assert b"at least" in resp.data

    def test_register_password_mismatch(self, client):
        resp = client.post("/register", data={
            "email": "new@example.com",
            "password": "securepass123",
            "password_confirm": "differentpass",
            "name": "New User",
        })
        assert resp.status_code == 200
        assert b"do not match" in resp.data


class TestLogin:
    def test_login_page_loads(self, client):
        resp = client.get("/login")
        assert resp.status_code == 200

    def test_login_invalid_credentials(self, client):
        resp = client.post("/login", data={
            "email": "nonexistent@example.com",
            "password": "wrongpassword",
        })
        assert resp.status_code == 200
        assert b"Invalid" in resp.data

    def test_login_valid_credentials(self, app, client):
        # Register first
        from app.services.user import create_email_user
        with app.app_context():
            create_email_user("user@example.com", "password123", "User")

        resp = client.post("/login", data={
            "email": "user@example.com",
            "password": "password123",
        })
        assert resp.status_code == 302

    def test_logout(self, auth_client):
        resp = auth_client.get("/logout")
        assert resp.status_code == 302
        # After logout, stats should redirect to login
        resp = auth_client.get("/stats")
        assert resp.status_code == 302
        assert "/login" in resp.headers["Location"]
