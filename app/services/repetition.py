"""Spaced repetition engine (SM-2 algorithm).

Tracks tasks the user got wrong and schedules them for review at
increasing intervals.  When a user practices a part, due review tasks
are served first before new ones.

SM-2 quality mapping (0-5 scale from score ratio):
  score/total >= 1.0  → quality 5 (perfect recall)
  score/total >= 0.8  → quality 4 (correct after hesitation)
  score/total >= 0.6  → quality 3 (correct with difficulty)
  score/total >= 0.4  → quality 2 (incorrect; easy recall of correct)
  score/total >= 0.2  → quality 1 (incorrect; remembered upon seeing)
  score/total <  0.2  → quality 0 (complete blackout)

Quality < 3 resets the card to the start (interval = 0).
"""
from __future__ import annotations

from datetime import date

from app.db import db_connection


# ── SM-2 helpers ─────────────────────────────────────────────────────────────

def _quality_from_score(score: int, total: int) -> int:
    """Map a score/total ratio to SM-2 quality grade (0-5)."""
    if total <= 0:
        return 0
    ratio = score / total
    if ratio >= 1.0:
        return 5
    if ratio >= 0.8:
        return 4
    if ratio >= 0.6:
        return 3
    if ratio >= 0.4:
        return 2
    if ratio >= 0.2:
        return 1
    return 0


def _sm2_update(ease: float, interval: int, reps: int, quality: int) -> tuple[float, int, int]:
    """Apply one SM-2 iteration.  Returns (new_ease, new_interval_days, new_reps)."""
    if quality < 3:
        # Failed — reset to beginning
        return max(ease, 1.3), 0, 0

    # Successful recall
    reps += 1
    if reps == 1:
        new_interval = 1
    elif reps == 2:
        new_interval = 3
    else:
        new_interval = round(interval * ease)

    new_ease = ease + (0.1 - (5 - quality) * (0.08 + (5 - quality) * 0.02))
    new_ease = max(new_ease, 1.3)

    return new_ease, new_interval, reps


# ── Public API ───────────────────────────────────────────────────────────────

def record_review(user_id: int, part: int, task_id: int, score: int, total: int) -> None:
    """Record a practice result and update the spaced repetition schedule.

    Called after every check.  If the user scored perfectly the card will
    eventually graduate to very long intervals; mistakes bring it back.
    """
    if user_id is None or total <= 0:
        return

    quality = _quality_from_score(score, total)
    today = date.today().isoformat()

    with db_connection() as conn:
        row = conn.execute(
            "SELECT ease_factor, interval_days, repetitions FROM spaced_repetition "
            "WHERE user_id = ? AND part = ? AND task_id = ?",
            (user_id, part, task_id),
        ).fetchone()

        if row:
            ease, interval, reps = _sm2_update(
                row["ease_factor"], row["interval_days"], row["repetitions"], quality,
            )
            next_review = _add_days(today, interval)
            conn.execute(
                """UPDATE spaced_repetition
                   SET ease_factor = ?, interval_days = ?, repetitions = ?,
                       next_review = ?, last_review = ?, last_score = ?
                   WHERE user_id = ? AND part = ? AND task_id = ?""",
                (ease, interval, reps, next_review, today, score / total,
                 user_id, part, task_id),
            )
        else:
            # Only create a card if the user didn't get a perfect score
            if quality >= 5:
                return  # no need to schedule — user knows this
            ease, interval, reps = _sm2_update(2.5, 0, 0, quality)
            next_review = _add_days(today, interval)
            conn.execute(
                """INSERT OR IGNORE INTO spaced_repetition
                   (user_id, part, task_id, ease_factor, interval_days, repetitions,
                    next_review, last_review, last_score)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (user_id, part, task_id, ease, interval, reps,
                 next_review, today, score / total),
            )
        conn.commit()


def get_due_task_id(user_id: int, part: int) -> int | None:
    """Return the task_id of the highest-priority due review for this part, or None.

    Priority: overdue items first (oldest next_review), then lowest score.
    """
    if user_id is None:
        return None

    today = date.today().isoformat()
    with db_connection() as conn:
        row = conn.execute(
            """SELECT task_id FROM spaced_repetition
               WHERE user_id = ? AND part = ? AND next_review <= ?
               ORDER BY next_review ASC, last_score ASC
               LIMIT 1""",
            (user_id, part, today),
        ).fetchone()
    return row["task_id"] if row else None


def get_due_task_ids_for_part4(user_id: int) -> list[int] | None:
    """Return a list of Part 4 (uoe_tasks) task IDs that are due, or None."""
    if user_id is None:
        return None

    today = date.today().isoformat()
    with db_connection() as conn:
        rows = conn.execute(
            """SELECT task_id FROM spaced_repetition
               WHERE user_id = ? AND part = 4 AND next_review <= ?
               ORDER BY next_review ASC, last_score ASC
               LIMIT 6""",
            (user_id, today),
        ).fetchall()
    return [r["task_id"] for r in rows] if rows else None


def get_due_counts(user_id: int) -> dict[int, int]:
    """Return {part: count_of_due_reviews} for all parts."""
    if user_id is None:
        return {}

    today = date.today().isoformat()
    with db_connection() as conn:
        rows = conn.execute(
            """SELECT part, COUNT(*) AS cnt FROM spaced_repetition
               WHERE user_id = ? AND next_review <= ?
               GROUP BY part""",
            (user_id, today),
        ).fetchall()
    return {r["part"]: r["cnt"] for r in rows}


# ── Internal ─────────────────────────────────────────────────────────────────

def _add_days(iso_date: str, days: int) -> str:
    """Add days to an ISO date string."""
    from datetime import timedelta
    d = date.fromisoformat(iso_date)
    return (d + timedelta(days=days)).isoformat()
