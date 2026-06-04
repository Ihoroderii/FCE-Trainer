"""Tests for Writing drafts and rich feedback."""
from __future__ import annotations

import json


def test_writing_draft_api_saves_draft(app, auth_client):
    resp = auth_client.post(
        "/api/writing/draft",
        json={
            "part": 1,
            "option_id": "",
            "answer": "This is my saved essay draft.",
        },
    )
    assert resp.status_code == 200
    assert resp.get_json()["ok"] is True

    with auth_client.session_transaction() as sess:
        user_id = sess["user_id"]

    from app.db import db_connection

    with app.app_context(), db_connection() as conn:
        row = conn.execute(
            "SELECT owner_key, user_id, part, answer FROM writing_drafts WHERE user_id = ?",
            (user_id,),
        ).fetchone()
    assert row["owner_key"] == f"user:{user_id}"
    assert row["part"] == 1
    assert row["answer"] == "This is my saved essay draft."


def test_writing_page_loads_saved_draft(auth_client):
    answer = "This draft should still be here after a refresh."
    resp = auth_client.post("/api/writing/draft", json={"part": 1, "answer": answer})
    assert resp.status_code == 200

    page = auth_client.get("/writing")
    assert page.status_code == 200
    assert answer.encode() in page.data


def test_writing_ai_unavailable_message_and_attempt(app, auth_client, monkeypatch):
    import app.views.writing as writing_view

    monkeypatch.setattr(writing_view, "ai_available", False)
    answer = " ".join(["This answer has enough words for checking"] * 4)
    resp = auth_client.post(
        "/writing",
        data={
            "action": "check",
            "part": "1",
            "answer": answer,
        },
    )
    assert resp.status_code == 200
    assert b"AI feedback is unavailable. Configure API key." in resp.data

    from app.db import db_connection

    with app.app_context(), db_connection() as conn:
        row = conn.execute("SELECT feedback_json FROM writing_attempts ORDER BY id DESC LIMIT 1").fetchone()
    assert row is not None
    assert "Configure API key" in row["feedback_json"]


def test_writing_attempt_saves_task_student_and_ai_versions(app, auth_client, monkeypatch):
    import app.views.writing as writing_view

    feedback = {
        "overall": 4,
        "content": 4,
        "communicative_achievement": 4,
        "organisation": 4,
        "language": 4,
        "comment": "Clear work.",
        "student_improved_version": "This is my improved answer with clearer linking.",
        "ai_improved_version": "This is the AI improved answer for the same task.",
        "missing_task_points": [],
        "grammar_corrections": [],
        "better_sentence_examples": [],
        "vocabulary_upgrades": [],
        "organisation_advice": [],
        "rewrite_suggestion": {"original": "", "improved": "", "reason": ""},
    }

    class _Message:
        content = json.dumps(feedback)

    class _Choice:
        message = _Message()

    class _Completion:
        choices = [_Choice()]

    monkeypatch.setattr(writing_view, "ai_available", True)
    monkeypatch.setattr(writing_view, "chat_create", lambda *args, **kwargs: _Completion())

    answer = " ".join(["Technology can help students study more effectively."] * 4)
    resp = auth_client.post(
        "/writing",
        data={
            "action": "check",
            "part": "1",
            "answer": answer,
        },
    )
    assert resp.status_code == 200

    from app.db import db_connection

    with app.app_context(), db_connection() as conn:
        row = conn.execute(
            """
            SELECT task_text, student_answer, student_improved_version, ai_improved_version
            FROM writing_attempts
            ORDER BY id DESC
            LIMIT 1
            """
        ).fetchone()
    assert row is not None
    assert "Points to cover:" in row["task_text"]
    assert row["student_answer"] == answer
    assert row["student_improved_version"] == feedback["student_improved_version"]
    assert row["ai_improved_version"] == feedback["ai_improved_version"]

    second_resp = auth_client.post(
        "/writing",
        data={
            "action": "check",
            "part": "1",
            "answer": answer,
        },
    )
    assert second_resp.status_code == 200

    with app.app_context(), db_connection() as conn:
        history_count = conn.execute(
            "SELECT COUNT(*) AS n FROM check_history WHERE part = 201"
        ).fetchone()["n"]
        attempt_count = conn.execute(
            "SELECT COUNT(*) AS n FROM writing_attempts"
        ).fetchone()["n"]
    assert attempt_count == 2
    assert history_count == 1


def test_rich_feedback_parser_normalises_sections():
    from app.views.writing import _parse_feedback

    raw = json.dumps({
        "overall": 4,
        "content": 4,
        "communicative_achievement": 3,
        "organisation": 4,
        "language": 3,
        "comment": "Good answer with a few issues.",
        "student_improved_version": "Overall, I think this is a good idea because it is practical.",
        "ai_improved_version": "Overall, this approach would benefit students because it is practical and affordable.",
        "missing_task_points": ["Add your own idea."],
        "grammar_corrections": [
            {"original": "people is", "corrected": "people are", "explanation": "People is plural."},
        ],
        "better_sentence_examples": [
            {"original": "It is good.", "improved": "It offers clear benefits.", "reason": "More precise."},
        ],
        "vocabulary_upgrades": [
            {"original": "good", "upgraded": "beneficial", "reason": "More formal."},
        ],
        "organisation_advice": ["Use one paragraph per point."],
        "rewrite_suggestion": {
            "original": "I think this is good.",
            "improved": "Overall, this approach is beneficial because it is practical.",
            "reason": "Clearer support.",
        },
    })
    feedback = _parse_feedback(raw)
    assert feedback["missing_task_points"] == ["Add your own idea."]
    assert feedback["grammar_corrections"][0]["corrected"] == "people are"
    assert feedback["better_sentence_examples"][0]["improved"] == "It offers clear benefits."
    assert feedback["vocabulary_upgrades"][0]["upgraded"] == "beneficial"
    assert feedback["organisation_advice"] == ["Use one paragraph per point."]
    assert feedback["student_improved_version"].startswith("Overall, I think")
    assert feedback["ai_improved_version"].startswith("Overall, this approach")
    assert feedback["rewrite_suggestion"]["improved"].startswith("Overall")


def test_writing_prompt_requests_two_full_improved_versions():
    from app.views.writing import _build_writing_prompt

    prompt = _build_writing_prompt(1, "Write an essay about technology.", "Technology is useful.")

    assert '"student_improved_version"' in prompt
    assert '"ai_improved_version"' in prompt
    assert "improve the student's own draft" in prompt
    assert "write your own strong B2 First model answer" in prompt
