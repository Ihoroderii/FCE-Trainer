"""Get phrases study mode: 8 gaps, each gap = correct GET collocation."""
import logging
import uuid

from flask import Blueprint, redirect, render_template, request, session, url_for

from app.config import CHECK_RESULT_CACHE_MAX
from app.db import get_get_phrase_task_by_id
from app.parts.get_phrases import (
    build_get_phrase_html,
    check_get_phrases,
    get_or_create_get_phrase_item,
)
from app.parts.get_phrases import generate_get_phrase_with_openai
from app.ai import ai_available
from app.services.stats import get_get_phrase_stats, record_check_result

logger = logging.getLogger("fce_trainer")

_CHECK_RESULT_CACHE = {}
bp = Blueprint("get_phrases", __name__)


@bp.route("/get-phrases", methods=["GET", "POST"])
def get_phrases():
    if request.method == "POST":
        action = (request.form.get("action") or "").strip()
        if action == "generate":
            if not ai_available:
                return redirect(url_for("get_phrases.get_phrases", error=1))
            item = generate_get_phrase_with_openai()
            if item and item.get("id"):
                session["get_phrase_task_id"] = item["id"]
                session.pop("get_phrase_check_result", None)
                return redirect(url_for("get_phrases.get_phrases", generated=1))
            return redirect(url_for("get_phrases.get_phrases", generate_failed=1))
        if action == "check":
            result = check_get_phrases(request.form)
            if result:
                record_check_result(result)
                if len(_CHECK_RESULT_CACHE) >= CHECK_RESULT_CACHE_MAX:
                    _CHECK_RESULT_CACHE.pop(next(iter(_CHECK_RESULT_CACHE)))
                token = uuid.uuid4().hex
                _CHECK_RESULT_CACHE[token] = result
                return redirect(url_for("get_phrases.get_phrases", check_result_token=token))
        if action == "next":
            session.pop("get_phrase_task_id", None)
            session.pop("get_phrase_check_result", None)
            return redirect(url_for("get_phrases.get_phrases"))

    check_result = None
    token = request.args.get("check_result_token")
    if token and token in _CHECK_RESULT_CACHE:
        check_result = _CHECK_RESULT_CACHE.pop(token)
    # Use current task from session if set (so refresh doesn't pick a new task or call OpenAI)
    task_id = session.get("get_phrase_task_id")
    if task_id:
        task = get_get_phrase_task_by_id(task_id)
    else:
        task, task_id = get_or_create_get_phrase_item()
        if task_id:
            session["get_phrase_task_id"] = task_id
    task_html = build_get_phrase_html(task, check_result) if task else ""
    show_error = request.args.get("error", type=int) or (not task and not ai_available)
    get_phrase_stats = get_get_phrase_stats()
    return render_template(
        "get_phrases.html",
        task_html=task_html,
        task=task,
        check_result=check_result,
        get_phrase_stats=get_phrase_stats,
        error=show_error,
        generated=request.args.get("generated", type=int),
        generate_failed=request.args.get("generate_failed", type=int),
        ai_available=ai_available,
    )
