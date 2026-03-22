"""Listening exam blueprint — /listening?part=N."""
from __future__ import annotations

import json
import logging

from flask import Blueprint, redirect, render_template, request, session, url_for

from app.config import LISTENING_HISTORY_PARTS, LISTENING_PARTS_RANGE, LISTENING_QUESTION_COUNTS
from app.parts.listening import (
    LISTENING_CHECKERS,
    get_or_create_listening_task,
    generate_listening_task,
)
from app.db import get_listening_task
from app.services.stats import record_check_result

logger = logging.getLogger("fce_trainer")
bp = Blueprint("listening", __name__)

_PART_NAMES = {
    1: "Multiple Choice (8 extracts)",
    2: "Sentence Completion",
    3: "Multiple Matching (5 speakers)",
    4: "Multiple Choice (interview)",
}


def _session_key(part: int) -> str:
    return f"listening_part{part}_task_id"


@bp.route("/listening")
def listening():
    part = request.args.get("part", 1, type=int)
    if part not in LISTENING_PARTS_RANGE:
        part = 1

    # Check for generate action
    action = request.args.get("action")
    if action == "generate":
        task = generate_listening_task(part)
        if task:
            session[_session_key(part)] = task["id"]
        return redirect(url_for("listening.listening", part=part))

    # Check for next action
    if action == "next":
        exclude_id = session.get(_session_key(part))
        session.pop(_session_key(part), None)
        task, tid = get_or_create_listening_task(part, exclude_id=exclude_id)
        if tid:
            session[_session_key(part)] = tid
        return redirect(url_for("listening.listening", part=part))

    # Get or create task
    tid = session.get(_session_key(part))
    task = get_listening_task(part, tid) if tid else None
    if not task:
        task, tid = get_or_create_listening_task(part)
        if tid:
            session[_session_key(part)] = tid

    # Retrieve check result from session if present
    check_result = session.pop("listening_check_result", None)

    return render_template(
        "listening.html",
        part=part,
        part_name=_PART_NAMES.get(part, ""),
        task=task,
        question_count=LISTENING_QUESTION_COUNTS.get(part, 0),
        parts_range=LISTENING_PARTS_RANGE,
        part_names=_PART_NAMES,
        check_result=check_result,
    )


@bp.route("/listening/check", methods=["POST"])
def listening_check():
    part = request.form.get("part", 1, type=int)
    if part not in LISTENING_PARTS_RANGE:
        return redirect(url_for("listening.listening"))

    tid = session.get(_session_key(part))
    task = get_listening_task(part, tid) if tid else None
    if not task:
        return redirect(url_for("listening.listening", part=part))

    data = task["data"]
    checker = LISTENING_CHECKERS.get(part)
    if not checker:
        return redirect(url_for("listening.listening", part=part))

    # Parse answers from form
    answers = {}
    if part == 2:
        # Sentence completion: text answers
        count = LISTENING_QUESTION_COUNTS[part]
        for i in range(count):
            answers[i] = request.form.get(f"q_{i}", "").strip()
    elif part == 3:
        # Multiple matching: speaker → statement index
        count = LISTENING_QUESTION_COUNTS[part]
        for i in range(count):
            val = request.form.get(f"q_{i}")
            if val is not None:
                try:
                    answers[i] = int(val)
                except ValueError:
                    pass
    else:
        # Part 1 and 4: MCQ
        count = LISTENING_QUESTION_COUNTS[part]
        for i in range(count):
            val = request.form.get(f"q_{i}")
            if val is not None:
                try:
                    answers[i] = int(val)
                except ValueError:
                    pass

    result = checker(data, answers)
    result["part"] = LISTENING_HISTORY_PARTS[part]

    # Record in check_history
    record_check_result(result)

    # Store result in session for display
    session["listening_check_result"] = result

    return redirect(url_for("listening.listening", part=part))
