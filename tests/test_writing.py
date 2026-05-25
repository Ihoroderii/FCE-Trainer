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


def test_rich_feedback_parser_normalises_sections():
    from app.views.writing import _parse_feedback

    raw = json.dumps({
        "overall": 4,
        "content": 4,
        "communicative_achievement": 3,
        "organisation": 4,
        "language": 3,
        "comment": "Good answer with a few issues.",
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
    assert feedback["rewrite_suggestion"]["improved"].startswith("Overall")
