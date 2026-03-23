"""Mock FCE exam session service.

Manages timed exam state: start, check time remaining, finish, score.
Stores state in Flask session so it survives page navigations.
"""
from __future__ import annotations

import logging
import time
from typing import Any

from flask import session

from app.config import PART_QUESTION_COUNTS, PARTS_RANGE

logger = logging.getLogger("fce_trainer")

# Real FCE Reading & Use of English: 75 minutes
MOCK_EXAM_DURATION_SECONDS = 75 * 60

# Session keys
_SK_ACTIVE = "mock_exam_active"
_SK_START = "mock_exam_start_ts"
_SK_DURATION = "mock_exam_duration"
_SK_PROCTOR_SESSION = "mock_exam_proctor_session_id"
_SK_FINISHED = "mock_exam_finished"
_SK_PARTS_SCORES = "mock_exam_scores"  # {part: {score, total}}


def start_mock_exam(proctor_session_id: int | None = None) -> None:
    """Begin a new mock exam session."""
    session[_SK_ACTIVE] = True
    session[_SK_START] = time.time()
    session[_SK_DURATION] = MOCK_EXAM_DURATION_SECONDS
    session[_SK_FINISHED] = False
    session[_SK_PARTS_SCORES] = {}
    session["parts_checked"] = []
    if proctor_session_id:
        session[_SK_PROCTOR_SESSION] = proctor_session_id
    # Clear any leftover task IDs so fresh tasks are loaded
    for p in PARTS_RANGE:
        session.pop(f"part{p}_task_id", None)
    session.pop("part4_task_ids", None)
    logger.info("Mock exam started (proctor_session=%s)", proctor_session_id)


def is_mock_exam_active() -> bool:
    """Return True if there's an active (not finished) mock exam."""
    return bool(session.get(_SK_ACTIVE)) and not session.get(_SK_FINISHED)


def get_time_remaining() -> int:
    """Seconds remaining. Returns 0 if expired or no exam active."""
    if not session.get(_SK_ACTIVE):
        return 0
    start = session.get(_SK_START, 0)
    duration = session.get(_SK_DURATION, MOCK_EXAM_DURATION_SECONDS)
    elapsed = time.time() - start
    remaining = max(0, int(duration - elapsed))
    return remaining


def is_time_expired() -> bool:
    return is_mock_exam_active() and get_time_remaining() <= 0


def record_part_score(part: int, score: int, total: int) -> None:
    """Record score for a part during the mock exam."""
    scores = session.get(_SK_PARTS_SCORES) or {}
    scores[str(part)] = {"score": score, "total": total}
    session[_SK_PARTS_SCORES] = scores


def get_mock_exam_results() -> dict:
    """Get full mock exam results."""
    scores = session.get(_SK_PARTS_SCORES) or {}
    total_score = 0
    total_questions = 0
    part_results = []
    for p in PARTS_RANGE:
        ps = scores.get(str(p), {})
        s = ps.get("score", 0)
        t = ps.get("total", PART_QUESTION_COUNTS.get(p, 0))
        completed = str(p) in scores
        total_score += s
        total_questions += PART_QUESTION_COUNTS.get(p, 0)
        part_results.append({
            "part": p,
            "score": s,
            "total": PART_QUESTION_COUNTS.get(p, 0),
            "completed": completed,
        })

    start_ts = session.get(_SK_START, 0)
    duration = session.get(_SK_DURATION, MOCK_EXAM_DURATION_SECONDS)
    time_used = min(duration, int(time.time() - start_ts)) if start_ts else 0

    return {
        "total_score": total_score,
        "total_questions": total_questions,
        "percent": round(total_score / total_questions * 100, 1) if total_questions else 0,
        "parts": part_results,
        "parts_completed": sum(1 for pr in part_results if pr["completed"]),
        "parts_total": len(PARTS_RANGE),
        "time_used_seconds": time_used,
        "time_limit_seconds": duration,
        "proctor_session_id": session.get(_SK_PROCTOR_SESSION),
    }


def finish_mock_exam() -> dict:
    """Finish the mock exam and return results."""
    session[_SK_FINISHED] = True
    session[_SK_ACTIVE] = False
    results = get_mock_exam_results()
    logger.info("Mock exam finished: %d/%d (%.1f%%)",
                results["total_score"], results["total_questions"], results["percent"])
    return results


def cancel_mock_exam() -> None:
    """Cancel/abandon the mock exam without scoring."""
    for key in (_SK_ACTIVE, _SK_START, _SK_DURATION, _SK_PROCTOR_SESSION,
                _SK_FINISHED, _SK_PARTS_SCORES):
        session.pop(key, None)
    session.pop("parts_checked", None)
    session.pop("mock_exam", None)
