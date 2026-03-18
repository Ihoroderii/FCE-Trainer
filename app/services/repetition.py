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

import logging
from datetime import date

from app.db import db_connection

logger = logging.getLogger("fce_trainer")


# ── SM-2 helpers ─────────────────────────────────────────────────────────────

def _quality_from_score(score: int, total: int) -> int:
    """Map a score/total ratio to SM-2 quality grade (0-5)."""
    if total <= 0:
        return 0
    ratio = score / total
    if ratio >= 1.0:
        q = 5
    elif ratio >= 0.8:
        q = 4
    elif ratio >= 0.6:
        q = 3
    elif ratio >= 0.4:
        q = 2
    elif ratio >= 0.2:
        q = 1
    else:
        q = 0
    logger.debug("  _quality_from_score: score=%d/%d ratio=%.2f → quality=%d", score, total, ratio, q)
    return q


def _sm2_update(ease: float, interval: int, reps: int, quality: int) -> tuple[float, int, int]:
    """Apply one SM-2 iteration.  Returns (new_ease, new_interval_days, new_reps)."""
    logger.debug("  _sm2_update INPUT:  ease=%.2f interval=%dd reps=%d quality=%d", ease, interval, reps, quality)
    if quality < 3:
        # Failed — reset to beginning
        logger.debug("  _sm2_update: quality < 3 → RESET (interval=0, reps=0, ease kept ≥ 1.3)")
        return max(ease, 1.3), 0, 0

    # Successful recall
    reps += 1
    if reps == 1:
        new_interval = 1
        logger.debug("  _sm2_update: 1st success → interval=1 day")
    elif reps == 2:
        new_interval = 3
        logger.debug("  _sm2_update: 2nd success → interval=3 days")
    else:
        new_interval = round(interval * ease)
        logger.debug("  _sm2_update: rep #%d → interval = round(%d × %.2f) = %d days", reps, interval, ease, new_interval)

    new_ease = ease + (0.1 - (5 - quality) * (0.08 + (5 - quality) * 0.02))
    new_ease = max(new_ease, 1.3)
    logger.debug("  _sm2_update OUTPUT: ease=%.2f interval=%dd reps=%d", new_ease, new_interval, reps)

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
    logger.debug("═══ record_review START ═══")
    logger.debug("  user=%d  part=%d  task_id=%d  score=%d/%d  today=%s", user_id, part, task_id, score, total, today)

    with db_connection() as conn:
        row = conn.execute(
            "SELECT ease_factor, interval_days, repetitions, next_review FROM spaced_repetition "
            "WHERE user_id = ? AND part = ? AND task_id = ?",
            (user_id, part, task_id),
        ).fetchone()

        if row:
            logger.debug("  DB row FOUND — existing card: ease=%.2f interval=%dd reps=%d next_review=%s",
                         row["ease_factor"], row["interval_days"], row["repetitions"], row["next_review"])
            ease, interval, reps = _sm2_update(
                row["ease_factor"], row["interval_days"], row["repetitions"], quality,
            )
            next_review = _add_days(today, interval)
            logger.debug("  → UPDATING DB: ease=%.2f interval=%dd reps=%d next_review=%s last_review=%s",
                         ease, interval, reps, next_review, today)
            conn.execute(
                """UPDATE spaced_repetition
                   SET ease_factor = ?, interval_days = ?, repetitions = ?,
                       next_review = ?, last_review = ?, last_score = ?
                   WHERE user_id = ? AND part = ? AND task_id = ?""",
                (ease, interval, reps, next_review, today, score / total,
                 user_id, part, task_id),
            )
        else:
            logger.debug("  DB row NOT found — this is a new card")
            # Only create a card if the user didn't get a perfect score
            if quality >= 5:
                logger.debug("  Perfect score (quality=5) → no card created, user knows this")
                return
            ease, interval, reps = _sm2_update(2.5, 0, 0, quality)
            next_review = _add_days(today, interval)
            logger.debug("  → INSERTING into DB: ease=%.2f interval=%dd reps=%d next_review=%s last_review=%s",
                         ease, interval, reps, next_review, today)
            conn.execute(
                """INSERT OR IGNORE INTO spaced_repetition
                   (user_id, part, task_id, ease_factor, interval_days, repetitions,
                    next_review, last_review, last_score)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (user_id, part, task_id, ease, interval, reps,
                 next_review, today, score / total),
            )
        conn.commit()
    logger.debug("═══ record_review END ═══")


def get_due_task_id(user_id: int, part: int) -> int | None:
    """Return the task_id of the highest-priority due review for this part, or None.

    Priority: overdue items first (oldest next_review), then lowest score.
    """
    if user_id is None:
        return None

    today = date.today().isoformat()
    logger.debug("get_due_task_id: user=%d part=%d today=%s", user_id, part, today)
    logger.debug("  SQL: SELECT task_id FROM spaced_repetition WHERE user_id=%d AND part=%d AND next_review<='%s' ORDER BY next_review ASC, last_score ASC LIMIT 1", user_id, part, today)
    with db_connection() as conn:
        row = conn.execute(
            """SELECT task_id, next_review, last_score FROM spaced_repetition
               WHERE user_id = ? AND part = ? AND next_review <= ?
               ORDER BY next_review ASC, last_score ASC
               LIMIT 1""",
            (user_id, part, today),
        ).fetchone()
    if row:
        logger.debug("  → FOUND due task_id=%d  next_review=%s  last_score=%.2f", row["task_id"], row["next_review"], row["last_score"])
        return row["task_id"]
    logger.debug("  → No due reviews for part %d", part)
    return None


def get_due_task_ids_for_part4(user_id: int) -> list[int] | None:
    """Return a list of Part 4 (uoe_tasks) task IDs that are due, or None."""
    if user_id is None:
        return None

    today = date.today().isoformat()
    logger.debug("get_due_task_ids_for_part4: user=%d today=%s", user_id, today)
    with db_connection() as conn:
        rows = conn.execute(
            """SELECT task_id, next_review, last_score FROM spaced_repetition
               WHERE user_id = ? AND part = 4 AND next_review <= ?
               ORDER BY next_review ASC, last_score ASC
               LIMIT 6""",
            (user_id, today),
        ).fetchall()
    if rows:
        for r in rows:
            logger.debug("  due Part4 task_id=%d  next_review=%s  last_score=%.2f", r["task_id"], r["next_review"], r["last_score"])
        return [r["task_id"] for r in rows]
    logger.debug("  → No due Part 4 reviews")
    return None


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
    counts = {r["part"]: r["cnt"] for r in rows}
    if counts:
        logger.debug("get_due_counts: user=%d today=%s → %s", user_id, today, counts)
    return counts


# ── Internal ─────────────────────────────────────────────────────────────────

def _add_days(iso_date: str, days: int) -> str:
    """Add days to an ISO date string."""
    from datetime import timedelta
    d = date.fromisoformat(iso_date)
    return (d + timedelta(days=days)).isoformat()
