"""Check history and per-part statistics."""
from datetime import datetime

from flask import session

from app.config import PARTS_RANGE
from app.db import db_connection


def record_check_result(result):
    part = result.get("part")
    score = result.get("score", 0)
    total = result.get("total", 0)
    if part not in PARTS_RANGE or total <= 0:
        return
    user_id = session.get("user_id")
    with db_connection() as conn:
        conn.execute(
            "INSERT INTO check_history (part, score, total, user_id, created_at) VALUES (?, ?, ?, ?, datetime('now'))",
            (part, score, total, user_id),
        )
        conn.commit()


def get_part_stats(user_id=None):
    if user_id is None:
        user_id = session.get("user_id")
    with db_connection() as conn:
        if user_id is None:
            cur = conn.execute(
                "SELECT part, SUM(score) AS total_correct, SUM(total) AS total_questions, COUNT(*) AS attempts, MAX(created_at) AS last_attempt_at FROM check_history WHERE user_id IS NULL GROUP BY part"
            )
        else:
            cur = conn.execute(
                "SELECT part, SUM(score) AS total_correct, SUM(total) AS total_questions, COUNT(*) AS attempts, MAX(created_at) AS last_attempt_at FROM check_history WHERE user_id = ? GROUP BY part",
                (user_id,),
            )
        rows = cur.fetchall()
    stats_by_part = {r["part"]: r for r in rows}
    out = []
    for part in PARTS_RANGE:
        row = stats_by_part.get(part)
        if not row or not row["total_questions"]:
            out.append({
                "part": part,
                "total_correct": 0,
                "total_wrong": 0,
                "total_questions": 0,
                "attempts": 0,
                "percent": None,
                "last_attempt_at": None,
                "last_attempt_at_display": None,
            })
        else:
            total_correct = row["total_correct"] or 0
            total_questions = row["total_questions"] or 0
            total_wrong = total_questions - total_correct
            percent = round(100 * total_correct / total_questions, 1) if total_questions else None
            raw_at = row["last_attempt_at"] if row["last_attempt_at"] else None
            try:
                dt = datetime.strptime(raw_at[:19], "%Y-%m-%d %H:%M:%S") if raw_at and len(raw_at) >= 19 else None
                last_display = dt.strftime("%d %b %Y, %H:%M") if dt else None
            except (ValueError, TypeError):
                last_display = raw_at[:16] if raw_at else None
            out.append({
                "part": part,
                "total_correct": total_correct,
                "total_wrong": total_wrong,
                "total_questions": total_questions,
                "attempts": row["attempts"] or 0,
                "percent": percent,
                "last_attempt_at": raw_at,
                "last_attempt_at_display": last_display,
            })
    return out
