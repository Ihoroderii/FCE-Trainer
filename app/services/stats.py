"""Check history and per-part statistics."""
from __future__ import annotations

import logging
from datetime import datetime

from flask import session

from app.config import GAMIFICATION_ENABLED, GET_PHRASE_PART, PARTS_RANGE, LISTENING_HISTORY_PARTS
from app.db import db_connection
from app.services.repetition import record_review

logger = logging.getLogger("fce_trainer")


def _user_filter_sql(user_id: int | None) -> tuple[str, tuple]:
    """Return (sql_fragment, params) for filtering by user_id or anonymous."""
    if user_id is None:
        return "user_id IS NULL", ()
    return "user_id = ?", (user_id,)


# Map part number → session key holding the current task_id
_PART_SESSION_KEYS = {
    1: "part1_task_id",
    2: "part2_task_id",
    3: "part3_task_id",
    5: "part5_task_id",
    6: "part6_task_id",
    7: "part7_task_id",
}


def _current_task_id(part: int) -> int | None:
    """Return the current task_id from session for the given part."""
    key = _PART_SESSION_KEYS.get(part)
    if key:
        return session.get(key)
    # Part 4 uses a list of task IDs — return first one as representative
    if part == 4:
        ids = session.get("part4_task_ids")
        return ids[0] if ids else None
    return None


def _record_part4_reviews(user_id: int, result: dict) -> None:
    """Record spaced repetition for each individual Part 4 item."""
    if not user_id:
        return
    task_ids = session.get("part4_task_ids") or []
    details = result.get("details") or []
    for i, d in enumerate(details):
        if i >= len(task_ids):
            break
        tid = task_ids[i]
        # Each item is scored individually: 1/1 if correct, 0/1 if wrong
        item_score = 1 if d.get("correct") else 0
        record_review(user_id, 4, tid, item_score, 1)


def claim_orphaned_stats(user_id: int) -> int:
    """Assign all check_history rows with user_id=NULL to the given user. Returns count."""
    with db_connection() as conn:
        cur = conn.execute("SELECT COUNT(*) AS n FROM check_history WHERE user_id IS NULL")
        count = cur.fetchone()["n"]
        if count > 0:
            conn.execute("UPDATE check_history SET user_id = ? WHERE user_id IS NULL", (user_id,))
            conn.commit()
            logging.getLogger("fce_trainer").info("Claimed %d orphaned stats for user %d", count, user_id)
    return count


def record_check_result(result: dict) -> dict | None:
    part = result.get("part")
    score = result.get("score", 0)
    total = result.get("total", 0)
    if total <= 0:
        return None
    _valid_parts = set(PARTS_RANGE) | {GET_PHRASE_PART} | set(LISTENING_HISTORY_PARTS.values())
    if part not in _valid_parts:
        return None
    user_id = session.get("user_id")
    logger.debug("record_check_result: part=%s score=%d/%d user=%s", part, score, total, user_id)
    details = result.get("details") or []
    with db_connection() as conn:
        cur = conn.execute(
            "INSERT INTO check_history (part, score, total, user_id, created_at) VALUES (?, ?, ?, ?, datetime('now'))",
            (part, score, total, user_id),
        )
        check_id = cur.lastrowid
        for i, d in enumerate(details):
            explanation = d.get("explanation") if isinstance(d, dict) else None
            if not explanation:
                continue
            conn.execute(
                """INSERT INTO answer_explanations (check_id, part, item_index, user_val, expected_val, explanation_text, created_at)
                   VALUES (?, ?, ?, ?, ?, ?, datetime('now'))""",
                (
                    check_id,
                    part,
                    i,
                    d.get("user_val") if isinstance(d, dict) else None,
                    d.get("expected") if isinstance(d, dict) else None,
                    str(explanation).strip(),
                ),
            )
        conn.commit()

    # Award XP & check achievements for logged-in users
    reward = None
    if GAMIFICATION_ENABLED:
        try:
            from app.services.gamification import award_xp
            reward = award_xp(user_id, score, total, part)
        except Exception:
            logging.getLogger("fce_trainer").warning("award_xp failed", exc_info=True)
        if reward and reward.get("xp_gained"):
            session["last_reward"] = reward

    # Schedule spaced repetition review for the task
    try:
        if part == 4:
            _record_part4_reviews(user_id, result)
        else:
            task_id = _current_task_id(part)
            if user_id and task_id:
                record_review(user_id, part, task_id, score, total)
    except Exception:
        logging.getLogger("fce_trainer").warning("record_review failed", exc_info=True)

    # Per-word repetition tracking for Part 3
    if part == 3:
        try:
            from app.services.word_repetition import record_part3_word_results
            stems = result.get("stems") or []
            if stems and details:
                record_part3_word_results(details, stems)
        except Exception:
            logging.getLogger("fce_trainer").warning("record_part3_word_results failed", exc_info=True)

    # Per-word repetition + collocation tracking for Part 2
    if part == 2:
        try:
            from app.services.word_repetition import record_part2_word_results, record_part2_collocations
            p2_answers = result.get("answers") or []
            p2_text = result.get("text") or ""
            if p2_answers and details:
                record_part2_word_results(details, p2_answers)
                record_part2_collocations(details, p2_answers, p2_text)
        except Exception:
            logging.getLogger("fce_trainer").warning("record_part2_word_results failed", exc_info=True)

    return reward


def get_part_stats(user_id: int | None = None) -> list[dict]:
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


def get_get_phrase_stats(user_id=None):
    """Single summary for Get phrases (part=8). Returns dict with part, total_correct, total_wrong, attempts, percent."""
    if user_id is None:
        user_id = session.get("user_id")
    where, params = _user_filter_sql(user_id)
    with db_connection() as conn:
        cur = conn.execute(
            f"""SELECT SUM(score) AS total_correct, SUM(total) AS total_questions, COUNT(*) AS attempts
                FROM check_history
                WHERE {where} AND part = ?""",
            (*params, GET_PHRASE_PART),
        )
        row = cur.fetchone()
    if not row or not row["total_questions"]:
        return {"part": GET_PHRASE_PART, "total_correct": 0, "total_wrong": 0, "attempts": 0, "percent": None}
    tc = row["total_correct"] or 0
    tq = row["total_questions"] or 0
    tw = tq - tc
    pct = round(100 * tc / tq, 1) if tq else None
    return {
        "part": GET_PHRASE_PART,
        "total_correct": tc,
        "total_wrong": tw,
        "attempts": row["attempts"] or 0,
        "percent": pct,
    }


def get_daily_stats(user_id=None):
    """Stats for today only: per-part correct/total/attempts. Same shape as get_part_stats but for date(created_at)=today."""
    if user_id is None:
        user_id = session.get("user_id")
    where, params = _user_filter_sql(user_id)
    with db_connection() as conn:
        cur = conn.execute(
            f"""SELECT part, SUM(score) AS total_correct, SUM(total) AS total_questions, COUNT(*) AS attempts
                FROM check_history
                WHERE {where} AND date(created_at) = date('now', 'localtime')
                GROUP BY part""",
            params,
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
            })
        else:
            total_correct = row["total_correct"] or 0
            total_questions = row["total_questions"] or 0
            total_wrong = total_questions - total_correct
            percent = round(100 * total_correct / total_questions, 1) if total_questions else None
            out.append({
                "part": part,
                "total_correct": total_correct,
                "total_wrong": total_wrong,
                "total_questions": total_questions,
                "attempts": row["attempts"] or 0,
                "percent": percent,
            })
    return out


def get_weekly_stats(user_id=None):
    """Stats for last 7 days: per-part correct/total/attempts."""
    if user_id is None:
        user_id = session.get("user_id")
    where, params = _user_filter_sql(user_id)
    with db_connection() as conn:
        cur = conn.execute(
            f"""SELECT part, SUM(score) AS total_correct, SUM(total) AS total_questions, COUNT(*) AS attempts
                FROM check_history
                WHERE {where} AND created_at >= datetime('now', '-7 days', 'localtime')
                GROUP BY part""",
            params,
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
            })
        else:
            total_correct = row["total_correct"] or 0
            total_questions = row["total_questions"] or 0
            total_wrong = total_questions - total_correct
            percent = round(100 * total_correct / total_questions, 1) if total_questions else None
            out.append({
                "part": part,
                "total_correct": total_correct,
                "total_wrong": total_wrong,
                "total_questions": total_questions,
                "attempts": row["attempts"] or 0,
                "percent": percent,
            })
    return out


def get_progress_series(user_id=None, days=14):
    """Daily aggregates for the last `days` days: list of {date, total_correct, total_questions, percent} for chart."""
    if user_id is None:
        user_id = session.get("user_id")
    where, params = _user_filter_sql(user_id)
    with db_connection() as conn:
        cur = conn.execute(
            f"""SELECT date(created_at) AS d, SUM(score) AS total_correct, SUM(total) AS total_questions
                FROM check_history
                WHERE {where} AND created_at >= date('now', '-{int(days)} days', 'localtime')
                GROUP BY date(created_at)
                ORDER BY d ASC""",
            params,
        )
        rows = cur.fetchall()
    out = []
    for r in rows:
        tc = r["total_correct"] or 0
        tq = r["total_questions"] or 0
        pct = round(100 * tc / tq, 1) if tq else 0
        out.append({
            "date": r["d"],
            "total_correct": tc,
            "total_questions": tq,
            "percent": pct,
        })
    return out


def get_words_learning(user_id=None, part=3, limit=50):
    """Part 3 (word formation) vocabulary from answer explanations: expected word + explanation. For 'words I learn'."""
    if user_id is None:
        user_id = session.get("user_id")
    with db_connection() as conn:
        if user_id is None:
            cur = conn.execute(
                """SELECT e.expected_val, e.explanation_text, e.created_at
                   FROM answer_explanations e
                   JOIN check_history c ON c.id = e.check_id
                   WHERE c.user_id IS NULL AND e.part = ?
                   ORDER BY e.created_at DESC LIMIT ?""",
                (part, limit),
            )
        else:
            cur = conn.execute(
                """SELECT e.expected_val, e.explanation_text, e.created_at
                   FROM answer_explanations e
                   JOIN check_history c ON c.id = e.check_id
                   WHERE c.user_id = ? AND e.part = ?
                   ORDER BY e.created_at DESC LIMIT ?""",
                (user_id, part, limit),
            )
        rows = cur.fetchall()
    out = []
    for r in rows:
        raw_at = r["created_at"]
        try:
            dt = datetime.strptime(raw_at[:19], "%Y-%m-%d %H:%M:%S") if raw_at and len(raw_at) >= 19 else None
            display_at = dt.strftime("%d %b") if dt else raw_at[:10] if raw_at else ""
        except (ValueError, TypeError):
            display_at = raw_at[:10] if raw_at else ""
        out.append({
            "word": (r["expected_val"] or "").strip() or "—",
            "explanation": (r["explanation_text"] or "").strip(),
            "created_at": raw_at,
            "created_at_display": display_at,
        })
    return out
