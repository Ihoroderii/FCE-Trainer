"""Live lesson rooms and polling state."""
from __future__ import annotations

import json
import secrets
import string
from typing import Any

from flask import session

from app.db import db_connection

_CODE_ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"
_MAX_STATE_BYTES = 20000
_MAX_VALUE_LEN = 500
_MAX_EXERCISE_TEXT_LEN = 8000


def _row_to_dict(row) -> dict | None:
    return dict(row) if row else None


def _normalise_code(code: str | None) -> str:
    return "".join(ch for ch in (code or "").upper() if ch in string.ascii_uppercase + string.digits)


def _make_code() -> str:
    raw = "".join(secrets.choice(_CODE_ALPHABET) for _ in range(8))
    return f"{raw[:4]}-{raw[4:]}"


def _compact_json(data: Any) -> str:
    return json.dumps(data, ensure_ascii=True, separators=(",", ":"))


def _safe_string(value: Any, limit: int = _MAX_VALUE_LEN) -> str:
    text = str(value or "").strip()
    if len(text) > limit:
        return text[:limit] + "..."
    return text


def _safe_text_block(value: Any, limit: int = _MAX_EXERCISE_TEXT_LEN) -> str:
    text = str(value or "").replace("\r\n", "\n").replace("\r", "\n")
    lines = [" ".join(line.split()) for line in text.split("\n")]
    text = "\n".join(line for line in lines if line).strip()
    if len(text) > limit:
        return text[:limit] + "..."
    return text


def sanitise_live_state(raw: dict | None) -> dict:
    raw = raw if isinstance(raw, dict) else {}
    answers = raw.get("answers") if isinstance(raw.get("answers"), list) else []
    clean_answers = []
    for item in answers[:60]:
        if not isinstance(item, dict):
            continue
        choices = item.get("choices") if isinstance(item.get("choices"), list) else []
        clean_choices = []
        for choice in choices[:12]:
            if not isinstance(choice, dict):
                continue
            clean_choices.append({
                "value": _safe_string(choice.get("value"), 80),
                "label": _safe_string(choice.get("label"), 220),
                "selected": bool(choice.get("selected")),
            })
        clean_answers.append({
            "name": _safe_string(item.get("name"), 80),
            "label": _safe_string(item.get("label"), 120),
            "value": _safe_string(item.get("value")),
            "display_value": _safe_string(item.get("display_value")),
            "choices": clean_choices,
            "filled": bool(item.get("filled")),
        })
    state = {
        "url": _safe_string(raw.get("url"), 300),
        "path": _safe_string(raw.get("path"), 200),
        "page_title": _safe_string(raw.get("page_title"), 120),
        "section_title": _safe_string(raw.get("section_title"), 160),
        "part": _safe_string(raw.get("part"), 40),
        "task_id": _safe_string(raw.get("task_id"), 80),
        "exercise_text": _safe_text_block(raw.get("exercise_text")),
        "score_text": _safe_string(raw.get("score_text"), 160),
        "filled_count": int(raw.get("filled_count") or 0),
        "total_fields": int(raw.get("total_fields") or 0),
        "answers": clean_answers,
    }
    encoded = _compact_json(state)
    if len(encoded.encode("utf-8")) > _MAX_STATE_BYTES:
        state["answers"] = state["answers"][:20]
    return state


def get_lesson_by_code(code: str | None) -> dict | None:
    lesson_code = _normalise_code(code)
    if not lesson_code:
        return None
    if len(lesson_code) == 8:
        lesson_code = f"{lesson_code[:4]}-{lesson_code[4:]}"
    with db_connection() as conn:
        cur = conn.execute(
            """SELECT ls.*, u.email AS teacher_email, u.name AS teacher_name
               FROM lesson_sessions ls
               JOIN users u ON u.id = ls.teacher_user_id
               WHERE ls.code = ?""",
            (lesson_code,),
        )
        return _row_to_dict(cur.fetchone())


def create_lesson(teacher_user_id: int, title: str = "") -> dict:
    clean_title = _safe_string(title, 120)
    with db_connection() as conn:
        for _ in range(20):
            code = _make_code()
            try:
                cur = conn.execute(
                    "INSERT INTO lesson_sessions (code, teacher_user_id, title) VALUES (?, ?, ?)",
                    (code, teacher_user_id, clean_title),
                )
                lesson_id = cur.lastrowid
                conn.execute(
                    """INSERT OR IGNORE INTO lesson_participants (lesson_id, user_id, role)
                       VALUES (?, ?, 'teacher')""",
                    (lesson_id, teacher_user_id),
                )
                conn.commit()
                return get_lesson_by_code(code)
            except Exception:
                conn.rollback()
        raise RuntimeError("Could not create a unique lesson code")


def join_lesson(code: str, user_id: int) -> dict | None:
    lesson = get_lesson_by_code(code)
    if not lesson or lesson["status"] != "active":
        return None
    with db_connection() as conn:
        conn.execute(
            """INSERT INTO lesson_participants (lesson_id, user_id, role, left_at, last_seen_at)
               VALUES (?, ?, 'student', NULL, datetime('now'))
               ON CONFLICT(lesson_id, user_id, role) DO UPDATE SET
                   left_at = NULL,
                   last_seen_at = datetime('now')""",
            (lesson["id"], user_id),
        )
        conn.commit()
    return lesson


def activate_lesson_session(lesson: dict, role: str) -> None:
    session["live_lesson_id"] = lesson["id"]
    session["live_lesson_code"] = lesson["code"]
    session["live_lesson_role"] = role


def clear_lesson_session() -> None:
    session.pop("live_lesson_id", None)
    session.pop("live_lesson_code", None)
    session.pop("live_lesson_role", None)


def current_lesson_from_session() -> dict | None:
    lesson_id = session.get("live_lesson_id")
    code = session.get("live_lesson_code")
    role = session.get("live_lesson_role")
    if not lesson_id or not code or not role:
        return None
    lesson = get_lesson_by_code(code)
    if not lesson or lesson["id"] != lesson_id or lesson["status"] != "active":
        clear_lesson_session()
        return None
    lesson["active_role"] = role
    return lesson


def leave_lesson(user_id: int | None) -> None:
    lesson_id = session.get("live_lesson_id")
    role = session.get("live_lesson_role")
    if user_id and lesson_id and role:
        with db_connection() as conn:
            conn.execute(
                """UPDATE lesson_participants
                   SET left_at = datetime('now')
                   WHERE lesson_id = ? AND user_id = ? AND role = ?""",
                (lesson_id, user_id, role),
            )
            conn.commit()
    clear_lesson_session()


def close_lesson(code: str, teacher_user_id: int) -> bool:
    lesson = get_lesson_by_code(code)
    if not lesson or lesson["teacher_user_id"] != teacher_user_id:
        return False
    with db_connection() as conn:
        conn.execute(
            """UPDATE lesson_sessions
               SET status = 'closed', closed_at = datetime('now')
               WHERE id = ? AND teacher_user_id = ?""",
            (lesson["id"], teacher_user_id),
        )
        conn.commit()
    if session.get("live_lesson_id") == lesson["id"]:
        clear_lesson_session()
    return True


def save_live_state(lesson_id: int, user_id: int, state: dict) -> dict:
    clean = sanitise_live_state(state)
    state_json = _compact_json(clean)
    with db_connection() as conn:
        conn.execute(
            """INSERT INTO live_exercise_state (lesson_id, user_id, state_json, updated_at)
               VALUES (?, ?, ?, datetime('now'))
               ON CONFLICT(lesson_id, user_id) DO UPDATE SET
                   state_json = excluded.state_json,
                   updated_at = datetime('now')""",
            (lesson_id, user_id, state_json),
        )
        conn.execute(
            """UPDATE lesson_participants
               SET last_seen_at = datetime('now')
               WHERE lesson_id = ? AND user_id = ? AND role = 'student'""",
            (lesson_id, user_id),
        )
        conn.commit()
    return clean


def record_result_event_from_session(result: dict, check_id: int | None = None) -> None:
    lesson = current_lesson_from_session()
    user_id = session.get("user_id")
    if not lesson or lesson.get("active_role") != "student" or not user_id:
        return
    payload = {
        "check_id": check_id,
        "score": result.get("score"),
        "total": result.get("total"),
    }
    with db_connection() as conn:
        conn.execute(
            """INSERT INTO lesson_events
               (lesson_id, user_id, event_type, part, score, total, payload_json)
               VALUES (?, ?, 'check_result', ?, ?, ?, ?)""",
            (
                lesson["id"],
                user_id,
                result.get("part"),
                result.get("score"),
                result.get("total"),
                _compact_json(payload),
            ),
        )
        conn.commit()


def teacher_can_access(code: str, teacher_user_id: int) -> bool:
    lesson = get_lesson_by_code(code)
    return bool(lesson and lesson["teacher_user_id"] == teacher_user_id)


def get_teacher_lessons(teacher_user_id: int, limit: int = 20) -> list[dict]:
    with db_connection() as conn:
        cur = conn.execute(
            """SELECT ls.*,
                      (SELECT COUNT(*) FROM lesson_participants lp
                       WHERE lp.lesson_id = ls.id AND lp.role = 'student' AND lp.left_at IS NULL) AS student_count
               FROM lesson_sessions ls
               WHERE ls.teacher_user_id = ?
               ORDER BY ls.created_at DESC
               LIMIT ?""",
            (teacher_user_id, limit),
        )
        return [dict(row) for row in cur.fetchall()]


def get_student_lessons(user_id: int, limit: int = 20) -> list[dict]:
    with db_connection() as conn:
        cur = conn.execute(
            """SELECT ls.*, lp.joined_at, lp.left_at,
                      u.email AS teacher_email, u.name AS teacher_name
               FROM lesson_participants lp
               JOIN lesson_sessions ls ON ls.id = lp.lesson_id
               JOIN users u ON u.id = ls.teacher_user_id
               WHERE lp.user_id = ? AND lp.role = 'student'
               ORDER BY lp.joined_at DESC
               LIMIT ?""",
            (user_id, limit),
        )
        return [dict(row) for row in cur.fetchall()]


def get_teacher_snapshot(code: str, teacher_user_id: int) -> dict | None:
    lesson = get_lesson_by_code(code)
    if not lesson or lesson["teacher_user_id"] != teacher_user_id:
        return None
    with db_connection() as conn:
        cur = conn.execute(
            """SELECT lp.user_id, lp.role, lp.joined_at, lp.last_seen_at, lp.left_at,
                      u.email, u.name, les.state_json, les.updated_at
               FROM lesson_participants lp
               JOIN users u ON u.id = lp.user_id
               LEFT JOIN live_exercise_state les
                    ON les.lesson_id = lp.lesson_id AND les.user_id = lp.user_id
               WHERE lp.lesson_id = ? AND lp.role = 'student'
               ORDER BY lp.joined_at ASC""",
            (lesson["id"],),
        )
        students = []
        for row in cur.fetchall():
            state = {}
            if row["state_json"]:
                try:
                    state = json.loads(row["state_json"])
                except json.JSONDecodeError:
                    state = {}
            students.append({
                "user_id": row["user_id"],
                "name": row["name"] or row["email"] or f"Student {row['user_id']}",
                "email": row["email"] or "",
                "joined_at": row["joined_at"],
                "last_seen_at": row["last_seen_at"],
                "left_at": row["left_at"],
                "state_updated_at": row["updated_at"],
                "state": state,
            })
        cur = conn.execute(
            """SELECT le.*, u.email, u.name
               FROM lesson_events le
               JOIN users u ON u.id = le.user_id
               WHERE le.lesson_id = ?
               ORDER BY le.id DESC
               LIMIT 20""",
            (lesson["id"],),
        )
        events = []
        for row in cur.fetchall():
            events.append({
                "id": row["id"],
                "user_id": row["user_id"],
                "name": row["name"] or row["email"] or f"Student {row['user_id']}",
                "event_type": row["event_type"],
                "part": row["part"],
                "score": row["score"],
                "total": row["total"],
                "created_at": row["created_at"],
            })
    return {"lesson": lesson, "students": students, "events": events}
