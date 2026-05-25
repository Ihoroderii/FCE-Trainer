"""Tests for live lesson rooms."""
from __future__ import annotations


def _create_logged_in_client(app, email: str, name: str):
    from app.services.user import create_email_user

    with app.app_context():
        uid = create_email_user(email, "password123", name)
    client = app.test_client()
    with client.session_transaction() as sess:
        sess["user_id"] = uid
        sess["user_email"] = email
        sess["user_name"] = name
    return client, uid


class TestLiveLessons:
    def test_lessons_page_requires_login(self, client):
        resp = client.get("/lessons")
        assert resp.status_code == 302
        assert "/login" in resp.headers["Location"]

    def test_teacher_can_create_room(self, app):
        teacher, uid = _create_logged_in_client(app, "teacher@example.com", "Teacher")

        resp = teacher.post("/lessons/create", data={"title": "B2 lesson"})
        assert resp.status_code == 302
        assert "/teacher" in resp.headers["Location"]

        from app.db import db_connection
        with app.app_context(), db_connection() as conn:
            row = conn.execute("SELECT code, teacher_user_id, title FROM lesson_sessions").fetchone()
        assert row["teacher_user_id"] == uid
        assert row["title"] == "B2 lesson"
        assert row["code"] in resp.headers["Location"]

    def test_student_live_state_is_visible_to_teacher(self, app):
        teacher, teacher_id = _create_logged_in_client(app, "teacher-live@example.com", "Teacher")
        student, _student_id = _create_logged_in_client(app, "student-live@example.com", "Student")

        from app.services.lessons import create_lesson
        with app.app_context():
            lesson = create_lesson(teacher_id, "Live lesson")

        join_resp = student.post("/lessons/join", data={"code": lesson["code"]})
        assert join_resp.status_code == 302

        state_resp = student.post(
            "/api/lessons/live-state",
            json={
                "path": "/use-of-english?part=1",
                "section_title": "Part 1 - Multiple-choice cloze",
                "part": "1",
                "exercise_text": "Part 1 - Multiple-choice cloze\nRead the text and choose A, B, C or D.\nQuestion 1: _____",
                "filled_count": 1,
                "total_fields": 8,
                "answers": [
                    {
                        "name": "p1_0",
                        "label": "Gap 1",
                        "value": "1",
                        "display_value": "B) although",
                        "filled": True,
                        "choices": [
                            {"value": "0", "label": "A) because", "selected": False},
                            {"value": "1", "label": "B) although", "selected": True},
                        ],
                    },
                ],
            },
        )
        assert state_resp.status_code == 200
        assert state_resp.get_json()["ok"] is True

        snapshot_resp = teacher.get(f"/api/lessons/{lesson['code']}/snapshot")
        assert snapshot_resp.status_code == 200
        data = snapshot_resp.get_json()
        assert data["ok"] is True
        assert data["students"][0]["name"] == "Student"
        assert data["students"][0]["state"]["section_title"] == "Part 1 - Multiple-choice cloze"
        assert "choose A, B, C or D" in data["students"][0]["state"]["exercise_text"]
        assert data["students"][0]["state"]["answers"][0]["display_value"] == "B) although"
        assert data["students"][0]["state"]["answers"][0]["choices"][1]["selected"] is True

    def test_non_teacher_cannot_open_snapshot(self, app):
        teacher, teacher_id = _create_logged_in_client(app, "owner@example.com", "Owner")
        other, _other_id = _create_logged_in_client(app, "other@example.com", "Other")

        from app.services.lessons import create_lesson
        with app.app_context():
            lesson = create_lesson(teacher_id, "Private")

        ok_resp = teacher.get(f"/api/lessons/{lesson['code']}/snapshot")
        assert ok_resp.status_code == 200

        denied_resp = other.get(f"/api/lessons/{lesson['code']}/snapshot")
        assert denied_resp.status_code == 404
