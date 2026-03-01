"""Use of English / Reading: index page with part tabs and check result."""
import logging
import uuid

from flask import Blueprint, current_app, redirect, render_template, request, session, url_for

from app.config import CHECK_RESULT_CACHE_MAX, PARTS_RANGE, PART_QUESTION_COUNTS
from app.db import get_task_by_id_for_part, get_tasks_by_ids
from app.parts import (
    CHECKERS,
    _PART_ERROR_MSGS,
    _PART_TASK_CONFIG,
    _GENERATE_CONFIG,
    _ensure_part_task,
    build_part1_html,
    build_part2_html,
    build_part3_html,
    build_part4_html,
    build_part5_text,
    build_part5_html,
    build_part6_text,
    build_part6_questions,
    build_part7_text,
    build_part7_questions,
    fetch_part4_tasks,
    get_or_create_part1_task,
    get_part1_task_by_id,
)
from app.services.stats import get_part_stats, record_check_result

logger = logging.getLogger("fce_trainer")

_CHECK_RESULT_CACHE = {}
bp = Blueprint("use_of_english", __name__)


def _get_idx(part: int):
    key = f"part{part}_idx"
    if key not in session:
        session[key] = 0
    return session[key]


def _inc_idx(part: int):
    session[f"part{part}_idx"] = _get_idx(part) + 1


def _handle_generate_action(action):
    from app.config import PART4_TASKS_PER_SET
    from app.db import get_recent_grammar_topics
    from app.parts import part4
    for part_num, cfg in _GENERATE_CONFIG.items():
        if action != f"generate_part{part_num}":
            continue
        default_level = cfg["default_level"]
        level = (request.form.get("level") or default_level).strip().lower()
        if level not in ("b2", "b2plus"):
            level = default_level
        if part_num == 4:
            generated = part4.fetch_part4_tasks(
                level=level,
                db_only=False,
            )
            if generated:
                session["part4_task_ids"] = [t["id"] for t in generated]
                session.pop("part4_tasks", None)
                session.pop("check_result", None)
            return redirect(url_for("use_of_english.use_of_english", part=4, part4_generated=len(generated) if generated else 0, part4_level=level))
        item = cfg["fn"](level)
        if item and item.get("id"):
            session[cfg["session_key"]] = item["id"]
            for key in cfg.get("extra_cleanup", []):
                session.pop(key, None)
            session.pop("check_result", None)
            params = {"part": part_num, f"part{part_num}_generated": 1}
            if part_num in (1, 2, 3):
                params[f"part{part_num}_level"] = level
            return redirect(url_for("use_of_english.use_of_english", **params))
        return redirect(url_for("use_of_english.use_of_english", part=part_num))
    return None


def _handle_check_action(form):
    part = form.get("part", type=int)
    switch_to_part = form.get("switch_to_part", type=int)
    if part not in PARTS_RANGE:
        return redirect(url_for("use_of_english.use_of_english", part=1))
    if switch_to_part in PARTS_RANGE:
        return redirect(url_for("use_of_english.use_of_english", part=switch_to_part))
    checker = CHECKERS.get(part)
    if not checker:
        return redirect(url_for("use_of_english.use_of_english", part=part))
    result = checker(None, form)
    if result:
        record_check_result(result)
        part_checked = result.get("part")
        if part_checked and part_checked in PARTS_RANGE:
            parts_checked = session.get("parts_checked") or []
            if part_checked not in parts_checked:
                session["parts_checked"] = parts_checked + [part_checked]
        if len(_CHECK_RESULT_CACHE) >= CHECK_RESULT_CACHE_MAX:
            _CHECK_RESULT_CACHE.pop(next(iter(_CHECK_RESULT_CACHE)))
        token = uuid.uuid4().hex
        _CHECK_RESULT_CACHE[token] = result
        return redirect(url_for("use_of_english.use_of_english", part=part, check_result_token=token))
    return redirect(url_for("use_of_english.use_of_english", part=part))


def _handle_next(current_part):
    _inc_idx(current_part)
    if current_part == 1:
        task = get_or_create_part1_task()
        if task and task.get("id"):
            session["part1_task_id"] = task["id"]
            session.pop("part1_task", None)
    elif current_part == 4:
        p4 = fetch_part4_tasks(level="b2plus", db_only=bool(session.get("part4_db_only")))
        session["part4_task_ids"] = [t["id"] for t in p4] if p4 else []
        session.pop("part4_tasks", None)
    if current_part in _PART_TASK_CONFIG:
        key, get_or_create, _get_by_id = _PART_TASK_CONFIG[current_part]
        current_tid = session.get(key)
        _, tid = get_or_create(exclude_task_id=current_tid)
        if tid:
            session[key] = tid
    session.pop("check_result", None)
    return redirect(url_for("use_of_english.use_of_english", part=current_part))


def _load_part_items(current_part):
    items = {}
    if current_part == 1 and not session.get("part1_task_id") and not session.get("part1_task"):
        task = get_or_create_part1_task()
        if task and task.get("id"):
            session["part1_task_id"] = task["id"]
            session.pop("part1_task", None)
    if session.get("part1_task_id"):
        items[1] = get_part1_task_by_id(session["part1_task_id"])
    elif session.get("part1_task"):
        items[1] = session.get("part1_task")
    for p in (2, 3, 5, 6, 7):
        if current_part == p:
            item, _ = _ensure_part_task(p)
            items[p] = item
        else:
            tid = session.get(f"part{p}_task_id")
            items[p] = get_task_by_id_for_part(p, tid) if tid else None
    if current_part == 4 and not session.get("part4_task_ids") and not session.get("part4_tasks"):
        p4 = fetch_part4_tasks(level="b2plus", db_only=bool(session.get("part4_db_only")))
        if p4:
            session["part4_task_ids"] = [t["id"] for t in p4]
            session.pop("part4_tasks", None)
    if session.get("part4_task_ids"):
        items[4] = get_tasks_by_ids(session["part4_task_ids"])
    elif session.get("part4_tasks"):
        items[4] = session.get("part4_tasks")
    else:
        items[4] = None
    return items


def _build_template_context(current_part, check_result, items):
    cr = check_result if check_result and check_result.get("part") == current_part else None
    errors = {}
    for p, msg in _PART_ERROR_MSGS.items():
        if current_part == p and not items.get(p):
            errors[p] = msg
    if current_part == 4 and not items.get(4):
        errors[4] = (
            "No Part 4 tasks in database. Generate tasks or turn off 'Database only'."
            if session.get("part4_db_only")
            else "No tasks in database. Set OPENAI_API_KEY to generate new tasks."
        )
    ctx = {"current_part": current_part, "check_result": check_result}
    ctx["part1_html"] = build_part1_html(items.get(1), cr if current_part == 1 else None) if 1 not in errors else ""
    ctx["part1_error"] = errors.get(1)
    ctx["part2_html"] = build_part2_html(items.get(2), cr if current_part == 2 else None)
    ctx["part2_error"] = errors.get(2)
    ctx["part3_html"] = build_part3_html(items.get(3) or [], cr if current_part == 3 else None)
    ctx["part3_error"] = errors.get(3)
    ctx["part4_html"] = build_part4_html(items.get(4) or [], cr if current_part == 4 else None) if 4 not in errors else ""
    ctx["part4_error"] = errors.get(4)
    ctx["part4_db_only"] = bool(session.get("part4_db_only"))
    ctx["part5_text"] = build_part5_text(items.get(5)) if 5 not in errors else ""
    ctx["part5_html"] = build_part5_html(items.get(5), cr if current_part == 5 else None) if 5 not in errors else ""
    ctx["part5_error"] = errors.get(5)
    ctx["part6_text"] = build_part6_text(items.get(6), cr if current_part == 6 else None) if 6 not in errors else ""
    ctx["part6_questions"] = build_part6_questions(items.get(6)) if 6 not in errors else ""
    ctx["part6_error"] = errors.get(6)
    ctx["part7_text"] = build_part7_text(items.get(7)) if items.get(7) else ""
    ctx["part7_questions"] = build_part7_questions(items.get(7), cr if current_part == 7 else None) if items.get(7) else ""
    ctx["part7_error"] = errors.get(7)
    for p in (1, 2, 3, 4, 5, 6, 7):
        ctx[f"part{p}_generated"] = request.args.get(f"part{p}_generated", type=int)
    for p in (1, 2, 3, 4):
        ctx[f"part{p}_level"] = request.args.get(f"part{p}_level") or ""
    part_stats = get_part_stats()
    ctx["current_part_stats"] = part_stats[current_part - 1] if part_stats else None
    parts_checked = session.get("parts_checked") or []
    ctx["parts_done"] = [p in parts_checked for p in PARTS_RANGE]
    ctx["part_counts"] = [PART_QUESTION_COUNTS[p] for p in PARTS_RANGE]
    return ctx


@bp.route("/use-of-english", methods=["GET", "POST"])
def use_of_english():
    if request.method == "POST":
        try:
            action = request.form.get("action") or ""
            if action.startswith("generate_part"):
                result = _handle_generate_action(action)
                if result:
                    return result
            return _handle_check_action(request.form)
        except Exception:
            logger.exception("Error handling POST in use_of_english")
            raise
    current_part = request.args.get("part", type=int, default=1)
    if current_part not in PARTS_RANGE:
        current_part = 1
    if "part4_db_only" in request.args:
        session["part4_db_only"] = request.args.get("part4_db_only", "").strip().lower() in ("1", "true", "on", "yes")
    if request.args.get("next", type=int, default=0):
        return _handle_next(current_part)
    check_result = None
    token = request.args.get("check_result_token")
    if token and token in _CHECK_RESULT_CACHE:
        check_result = _CHECK_RESULT_CACHE.pop(token)
    if check_result is None:
        check_result = session.pop("check_result", None)
    items = _load_part_items(current_part)
    ctx = _build_template_context(current_part, check_result, items)
    ctx["csrf_expired"] = request.args.get("csrf_expired")
    return render_template("index.html", **ctx)
