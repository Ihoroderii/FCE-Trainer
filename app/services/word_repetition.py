"""Per-word spaced repetition for Part 3 (word formation).

Tracks individual stem words the user got wrong and schedules them
for re-appearance in future generated tasks.

States:
  - learning: answered wrong → include in next 1-2 generated tasks
  - review:   answered correct once after being wrong → include next day
  - mastered: answered correct again on review day → done
"""
from __future__ import annotations

import logging
from datetime import date, timedelta

from flask import session

from app.db import db_connection

logger = logging.getLogger("fce_trainer")

MAX_REQUIRED_STEMS = 4  # max stems injected into a single generated task


def record_part3_word_results(details: list[dict], stems: list[str]) -> None:
    """After checking Part 3, record per-word outcomes.

    For each of the 8 gaps:
      - wrong  → upsert with status 'learning', next_review = today
      - correct & word in 'learning' → move to 'review', next_review = tomorrow
      - correct & word in 'review' & due today → move to 'mastered'
    """
    user_id = session.get("user_id")
    if not user_id:
        return
    if not details or not stems or len(stems) < 8:
        return

    today = date.today().isoformat()
    tomorrow = (date.today() + timedelta(days=1)).isoformat()

    with db_connection() as conn:
        for i, d in enumerate(details):
            if i >= len(stems):
                break
            stem = stems[i].strip().upper()
            if not stem:
                continue
            expected = d.get("expected", "").strip().lower()
            correct = d.get("correct", False)

            if not correct:
                # Wrong → upsert as 'learning', review immediately
                existing = conn.execute(
                    "SELECT id, status FROM part3_word_repetition WHERE user_id = ? AND stem = ?",
                    (user_id, stem),
                ).fetchone()
                if existing:
                    conn.execute(
                        "UPDATE part3_word_repetition SET status = 'learning', wrong_count = wrong_count + 1, "
                        "next_review = ?, last_seen = datetime('now'), answer = ? WHERE id = ?",
                        (today, expected, existing["id"]),
                    )
                else:
                    conn.execute(
                        "INSERT INTO part3_word_repetition (user_id, stem, answer, status, wrong_count, next_review) "
                        "VALUES (?, ?, ?, 'learning', 1, ?)",
                        (user_id, stem, expected, today),
                    )
            else:
                # Correct → promote if tracked
                existing = conn.execute(
                    "SELECT id, status, next_review FROM part3_word_repetition WHERE user_id = ? AND stem = ?",
                    (user_id, stem),
                ).fetchone()
                if not existing:
                    continue  # never got it wrong, nothing to track
                if existing["status"] == "learning":
                    conn.execute(
                        "UPDATE part3_word_repetition SET status = 'review', correct_count = correct_count + 1, "
                        "next_review = ?, last_seen = datetime('now') WHERE id = ?",
                        (tomorrow, existing["id"]),
                    )
                elif existing["status"] == "review" and existing["next_review"] <= today:
                    conn.execute(
                        "UPDATE part3_word_repetition SET status = 'mastered', correct_count = correct_count + 1, "
                        "last_seen = datetime('now') WHERE id = ?",
                        (existing["id"],),
                    )
        conn.commit()


def get_due_stems(user_id: int | None = None) -> list[dict]:
    """Return stems due for repetition (status 'learning' or 'review' with next_review <= today).

    Returns up to MAX_REQUIRED_STEMS dicts: {"stem": "COMPLETE", "answer": "completion"}.
    'learning' words come first (priority), then 'review' words.
    """
    if user_id is None:
        user_id = session.get("user_id")
    if not user_id:
        return []

    today = date.today().isoformat()
    with db_connection() as conn:
        rows = conn.execute(
            "SELECT stem, answer FROM part3_word_repetition "
            "WHERE user_id = ? AND status IN ('learning', 'review') AND next_review <= ? "
            "ORDER BY CASE status WHEN 'learning' THEN 0 ELSE 1 END, wrong_count DESC "
            "LIMIT ?",
            (user_id, today, MAX_REQUIRED_STEMS),
        ).fetchall()
    return [{"stem": r["stem"], "answer": r["answer"]} for r in rows]
