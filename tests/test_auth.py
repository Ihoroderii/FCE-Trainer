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


class TestForgotPassword:
    def test_forgot_password_shows_local_reset_link_for_existing_user(self, app, client, monkeypatch):
        from app.services.user import create_email_user

        monkeypatch.delenv("SMTP_HOST", raising=False)
        with app.app_context():
            create_email_user("reset@example.com", "password123", "Reset User")

        resp = client.post("/forgot-password", data={"email": "reset@example.com"})
        assert resp.status_code == 200
        assert b"Set a new password" in resp.data
        assert b"/reset-password/" in resp.data

    def test_forgot_password_hides_local_reset_link_for_unknown_user(self, client, monkeypatch):
        monkeypatch.delenv("SMTP_HOST", raising=False)

        resp = client.post("/forgot-password", data={"email": "unknown@example.com"})
        assert resp.status_code == 200
        assert b"If that email is registered" in resp.data
        assert b"/reset-password/" not in resp.data


class TestStatsProfile:
    def test_stats_profile_api_requires_login(self, client):
        resp = client.get("/api/stats/profile")
        assert resp.status_code == 302
        assert "/login" in resp.headers["Location"]

    def test_stats_profile_api_returns_cambridge_scale_profile(self, app, client):
        from app.db import db_connection
        from app.services.user import create_email_user

        with app.app_context():
            uid = create_email_user("scale@example.com", "password123", "Scale User")
            with db_connection() as conn:
                conn.execute(
                    "INSERT INTO check_history (part, score, total, user_id) VALUES (?, ?, ?, ?)",
                    (1, 8, 10, uid),
                )
                conn.execute(
                    "INSERT INTO check_history (part, score, total, user_id) VALUES (?, ?, ?, ?)",
                    (5, 6, 10, uid),
                )
                conn.execute(
                    "INSERT INTO check_history (part, score, total, user_id) VALUES (?, ?, ?, ?)",
                    (101, 9, 10, uid),
                )
                conn.execute(
                    "INSERT INTO check_history (part, score, total, user_id) VALUES (?, ?, ?, ?)",
                    (201, 4, 5, uid),
                )
                conn.commit()

        with client.session_transaction() as sess:
            sess["user_id"] = uid
            sess["user_email"] = "scale@example.com"
            sess["user_name"] = "Scale User"

        resp = client.get("/api/stats/profile")
        assert resp.status_code == 200
        data = resp.get_json()
        components = {c["key"]: c for c in data["components"]}
        assert components["use_of_english"]["score"] == 176
        assert components["reading"]["score"] == 162
        assert components["listening"]["score"] == 183
        assert components["writing"]["score"] == 176
        assert components["speaking"]["score"] is None
        assert data["overall_score"] == 174


class TestChangePassword:
    def _login_client(self, app, client, email):
        from app.services.user import create_email_user

        with app.app_context():
            uid = create_email_user(email, "password123", "Password User")
        assert uid
        with client.session_transaction() as sess:
            sess["user_id"] = uid
            sess["user_email"] = email
            sess["user_name"] = "Password User"

    def test_change_password_requires_login(self, client):
        resp = client.post("/settings/password", data={
            "current_password": "password123",
            "new_password": "newpassword123",
            "new_password_confirm": "newpassword123",
        })
        assert resp.status_code == 302
        assert "/login" in resp.headers["Location"]

    def test_change_password_rejects_wrong_current_password(self, app, client):
        self._login_client(app, client, "change-wrong-current@example.com")
        resp = client.post("/settings/password", data={
            "current_password": "wrongpassword",
            "new_password": "newpassword123",
            "new_password_confirm": "newpassword123",
        })
        assert resp.status_code == 200
        assert b"Current password is incorrect" in resp.data

    def test_change_password_rejects_mismatch(self, app, client):
        self._login_client(app, client, "change-mismatch@example.com")
        resp = client.post("/settings/password", data={
            "current_password": "password123",
            "new_password": "newpassword123",
            "new_password_confirm": "differentpassword123",
        })
        assert resp.status_code == 200
        assert b"New passwords do not match" in resp.data

    def test_change_password_rejects_blank_new_password(self, app, client):
        self._login_client(app, client, "change-blank@example.com")
        resp = client.post("/settings/password", data={
            "current_password": "password123",
            "new_password": "        ",
            "new_password_confirm": "        ",
        })
        assert resp.status_code == 200
        assert b"at least 8 characters" in resp.data

    def test_change_password_updates_login_password(self, app, client):
        self._login_client(app, client, "change-success@example.com")
        resp = client.post("/settings/password", data={
            "current_password": "password123",
            "new_password": "newpassword123",
            "new_password_confirm": "newpassword123",
        })
        assert resp.status_code == 302
        assert "/settings?password_updated=1" in resp.headers["Location"]

        client.get("/logout")

        resp = client.post("/login", data={
            "email": "change-success@example.com",
            "password": "password123",
        })
        assert resp.status_code == 200
        assert b"Invalid" in resp.data

        resp = client.post("/login", data={
            "email": "change-success@example.com",
            "password": "newpassword123",
        })
        assert resp.status_code == 302
