"""Live lesson routes: teacher rooms and student polling."""
from __future__ import annotations

from flask import Blueprint, jsonify, redirect, render_template, request, session, url_for

from app.services.lessons import (
    activate_lesson_session,
    clear_lesson_session,
    close_lesson,
    create_lesson,
    current_lesson_from_session,
    get_lesson_by_code,
    get_student_lessons,
    get_teacher_lessons,
    get_teacher_snapshot,
    join_lesson,
    leave_lesson,
    save_live_state,
    teacher_can_access,
)
from app.utils import login_required

bp = Blueprint("lessons", __name__)


def _render_lessons_page(error: str = "", joined_code: str = ""):
    user_id = session["user_id"]
    return render_template(
        "lessons.html",
        active_lesson=current_lesson_from_session(),
        teacher_lessons=get_teacher_lessons(user_id),
        student_lessons=get_student_lessons(user_id),
        error=error,
        joined_code=joined_code,
    )


@bp.route("/lessons")
@login_required
def lessons_page():
    return _render_lessons_page(error=request.args.get("error", ""))


@bp.route("/lessons/create", methods=["POST"])
@login_required
def create_lesson_room():
    title = (request.form.get("title") or "").strip()
    lesson = create_lesson(session["user_id"], title)
    activate_lesson_session(lesson, "teacher")
    return redirect(url_for("lessons.teacher_room", code=lesson["code"]))


@bp.route("/lessons/join", methods=["POST"])
@login_required
def join_lesson_room():
    code = request.form.get("code") or ""
    lesson = join_lesson(code, session["user_id"])
    if not lesson:
        return _render_lessons_page(error="Lesson code not found or the lesson is closed.", joined_code=code), 404
    activate_lesson_session(lesson, "student")
    return redirect(url_for("lessons.student_room", code=lesson["code"]))


@bp.route("/lessons/leave", methods=["POST"])
@login_required
def leave_lesson_room():
    leave_lesson(session["user_id"])
    return redirect(url_for("lessons.lessons_page"))


@bp.route("/lessons/<code>/close", methods=["POST"])
@login_required
def close_lesson_room(code):
    close_lesson(code, session["user_id"])
    return redirect(url_for("lessons.lessons_page"))


@bp.route("/lessons/<code>/teacher")
@login_required
def teacher_room(code):
    lesson = get_lesson_by_code(code)
    if not lesson or not teacher_can_access(code, session["user_id"]):
        return redirect(url_for("lessons.lessons_page", error="You cannot open that teacher room."))
    activate_lesson_session(lesson, "teacher")
    snapshot = get_teacher_snapshot(code, session["user_id"]) or {"students": [], "events": []}
    return render_template("lesson_teacher.html", lesson=lesson, snapshot=snapshot)


@bp.route("/lessons/<code>/student")
@login_required
def student_room(code):
    lesson = get_lesson_by_code(code)
    if not lesson or lesson["status"] != "active":
        clear_lesson_session()
        return redirect(url_for("lessons.lessons_page", error="This lesson is not active."))
    joined = join_lesson(code, session["user_id"])
    if not joined:
        clear_lesson_session()
        return redirect(url_for("lessons.lessons_page", error="Could not join that lesson."))
    activate_lesson_session(joined, "student")
    return render_template("lesson_student.html", lesson=joined)


@bp.route("/api/lessons/live-state", methods=["POST"])
@login_required
def live_state_api():
    lesson = current_lesson_from_session()
    if not lesson or lesson.get("active_role") != "student":
        return jsonify({"ok": False, "error": "No active student lesson."}), 409
    payload = request.get_json(silent=True) or {}
    state = save_live_state(lesson["id"], session["user_id"], payload)
    return jsonify({"ok": True, "state": state})


@bp.route("/api/lessons/<code>/snapshot")
@login_required
def teacher_snapshot_api(code):
    snapshot = get_teacher_snapshot(code, session["user_id"])
    if not snapshot:
        return jsonify({"ok": False, "error": "Not found"}), 404
    return jsonify({"ok": True, **snapshot})
