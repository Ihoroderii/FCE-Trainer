"""Home, health, mock exam, login/logout."""
import json
import logging
import os
from urllib.parse import urlencode

import re

from flask import Blueprint, current_app, redirect, render_template, request, session, url_for

from app.config import ACHIEVEMENTS, GAMIFICATION_ENABLED, PARTS_RANGE, PART_QUESTION_COUNTS
from app.services.stats import (
    get_part_stats,
    get_daily_stats,
    get_weekly_stats,
    get_progress_series,
    get_words_learning,
    get_get_phrase_stats,
    get_listening_stats,
    claim_orphaned_stats,
)
from app.services.mock_exam import (
    start_mock_exam,
    is_mock_exam_active,
    get_time_remaining,
    finish_mock_exam,
    cancel_mock_exam,
    get_mock_exam_results,
)
from app.services.user import create_email_user, verify_email_password, find_user_by_email, update_password
from app.services.email import send_reset_email
from app.db import create_reset_token, get_valid_reset_token, consume_reset_token
from app.utils import login_required

logger = logging.getLogger("fce_trainer")

try:
    from proctor_loader import is_configured as proctor_is_configured, get_config as proctor_get_config
except ImportError:
    def proctor_is_configured():
        return False
    def proctor_get_config():
        return {"enabled": False, "name": "Proctor"}

bp = Blueprint("home", __name__)


@bp.route("/health")
def health():
    return {"status": "ok"}, 200


@bp.route("/faq")
def faq():
    return render_template("faq.html")


@bp.route("/stats")
@login_required
def stats():
    user_id = session.get("user_id")
    user_stats = get_part_stats(user_id)
    daily = get_daily_stats(user_id)
    weekly = get_weekly_stats(user_id)
    progress_series = get_progress_series(user_id, days=14)
    words_learning = get_words_learning(user_id, part=3, limit=60)
    get_phrase_stats = get_get_phrase_stats(user_id)
    listening_stats = get_listening_stats(user_id)
    has_attempts = any(s.get("attempts", 0) for s in user_stats) or get_phrase_stats.get("attempts", 0)
    game_stats = None
    if GAMIFICATION_ENABLED:
        from app.services.gamification import get_game_stats
        game_stats = get_game_stats(user_id)
    return render_template(
        "stats.html",
        user_stats=user_stats,
        daily_stats=daily,
        weekly_stats=weekly,
        progress_series=progress_series,
        words_learning=words_learning,
        get_phrase_stats=get_phrase_stats,
        listening_stats=listening_stats,
        has_attempts=has_attempts,
        game=game_stats,
        all_achievements=ACHIEVEMENTS if GAMIFICATION_ENABLED else {},
    )


@bp.route("/")
def home():
    user_id = session.get("user_id")
    user_email = session.get("user_email") or ""
    user_name = session.get("user_name") or ""
    user_stats = get_part_stats(user_id) if user_id is not None else None
    has_attempts = user_stats and any(s.get("attempts", 0) for s in user_stats)
    game_stats = None
    if GAMIFICATION_ENABLED and user_id is not None:
        from app.services.gamification import get_game_stats
        game_stats = get_game_stats(user_id)
    google_available = bool(
        current_app.config.get("GOOGLE_OAUTH_CLIENT_ID") and current_app.config.get("GOOGLE_OAUTH_CLIENT_SECRET")
    )
    proctor_configured = proctor_is_configured()
    return render_template(
        "home.html",
        user_id=user_id,
        user_email=user_email,
        user_name=user_name,
        user_stats=user_stats,
        has_attempts=has_attempts,
        google_available=google_available,
        proctor_configured=proctor_configured,
        game=game_stats,
    )


def _call_proctor_join(backend_url, exam_code, candidate_identifier):
    import urllib.request
    import urllib.error
    url = f"{backend_url}/api/session/join"
    body = json.dumps({
        "exam_code": exam_code,
        "candidate_identifier": candidate_identifier or "Candidate",
    }).encode("utf-8")
    req = urllib.request.Request(url, data=body, method="POST", headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            return (data.get("session_id"), data.get("room_name"))
    except (urllib.error.URLError, urllib.error.HTTPError, json.JSONDecodeError, KeyError) as e:
        logger.warning("Proctor join failed: %s", e)
        return None


@bp.route("/mock-exam")
@login_required
def mock_exam():
    if not proctor_is_configured():
        return redirect(url_for("home.home", mode="mock", proctor_required=1))
    proctor_config = proctor_get_config()
    # Show different page if exam already active
    active = is_mock_exam_active()
    return render_template(
        "mock_exam.html",
        proctor_name=proctor_config.get("name", "Proctor"),
        exam_active=active,
        time_remaining=get_time_remaining() if active else None,
    )


@bp.route("/mock-exam/start", methods=["GET", "POST"])
@login_required
def mock_exam_start():
    if not proctor_is_configured():
        return redirect(url_for("home.home", mode="mock", proctor_required=1))
    cfg = proctor_get_config()
    backend_url = cfg.get("backend_url")
    frontend_url = cfg.get("frontend_url")
    exam_code = cfg.get("exam_code", "DEMO")
    candidate = (session.get("user_name") or session.get("user_email") or "Candidate").strip() or "Candidate"

    proctor_session_id = None

    if backend_url and frontend_url:
        result = _call_proctor_join(backend_url, exam_code, candidate)
        if result:
            proctor_session_id = result[0]
            # Store proctor info for later callback
            session["proctor_backend_url"] = backend_url
            session["proctor_frontend_url"] = frontend_url

    # Start the timed mock exam
    start_mock_exam(proctor_session_id=proctor_session_id)
    session["mock_exam"] = True

    # If proctor frontend exists and session was created, redirect there first
    # Proctor frontend will redirect back to /mock-exam/begin when ready
    if proctor_session_id and frontend_url:
        params = urlencode({
            "session_id": proctor_session_id,
            "return_url": url_for("home.mock_exam_begin", _external=True),
        })
        return redirect(f"{frontend_url}/entry?{params}")

    # No proctor frontend — go directly to exam
    return redirect(url_for("use_of_english.use_of_english", part=1))


@bp.route("/mock-exam/begin")
@login_required
def mock_exam_begin():
    """Return point from proctor frontend — candidate starts the actual exam."""
    if not is_mock_exam_active():
        return redirect(url_for("home.mock_exam"))
    return redirect(url_for("use_of_english.use_of_english", part=1))


@bp.route("/mock-exam/finish", methods=["GET", "POST"])
@login_required
def mock_exam_finish():
    """Finish the mock exam, show results, optionally post to proctor."""
    results = finish_mock_exam()

    # Post results to proctor backend if session exists
    proctor_session_id = results.get("proctor_session_id")
    backend_url = session.pop("proctor_backend_url", None)
    if proctor_session_id and backend_url:
        _post_results_to_proctor(backend_url, proctor_session_id, results)

    session.pop("mock_exam", None)

    return render_template("mock_exam_results.html", results=results)


@bp.route("/mock-exam/cancel", methods=["POST"])
@login_required
def mock_exam_cancel():
    """Abandon the mock exam."""
    cancel_mock_exam()
    return redirect(url_for("home.home"))


def _post_results_to_proctor(backend_url: str, proctor_session_id: int, results: dict):
    """Post exam results to proctor backend as a note + terminate session."""
    import urllib.request
    import urllib.error

    score_summary = f"FCE Exam Results: {results['total_score']}/{results['total_questions']} ({results['percent']}%)"
    parts_detail = []
    for pr in results["parts"]:
        status = f"{pr['score']}/{pr['total']}" if pr["completed"] else "not completed"
        parts_detail.append(f"Part {pr['part']}: {status}")
    note_text = score_summary + "\n" + "\n".join(parts_detail)

    # Post note
    try:
        url = f"{backend_url}/api/proctor/sessions/{proctor_session_id}/notes"
        body = json.dumps({"note": note_text, "timestamp_sec": results["time_used_seconds"]}).encode("utf-8")
        req = urllib.request.Request(url, data=body, method="POST", headers={"Content-Type": "application/json"})
        urllib.request.urlopen(req, timeout=10)
    except Exception:
        logger.warning("Failed to post results to proctor", exc_info=True)

    # Terminate session
    try:
        url = f"{backend_url}/api/proctor/sessions/{proctor_session_id}/terminate"
        req = urllib.request.Request(url, data=b"{}", method="POST", headers={"Content-Type": "application/json"})
        urllib.request.urlopen(req, timeout=10)
    except Exception:
        logger.warning("Failed to terminate proctor session", exc_info=True)


EMAIL_RE = re.compile(r"^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$")
MIN_PASSWORD_LEN = 8


@bp.route("/register", methods=["GET", "POST"])
def register():
    if session.get("user_id"):
        return redirect(url_for("home.home"))
    error = None
    if request.method == "POST":
        email = (request.form.get("email") or "").strip().lower()
        password = request.form.get("password") or ""
        password_confirm = request.form.get("password_confirm") or ""
        name = (request.form.get("name") or "").strip()
        if not email:
            error = "Email is required."
        elif not EMAIL_RE.match(email):
            error = "Please enter a valid email address."
        elif len(password) < MIN_PASSWORD_LEN:
            error = f"Password must be at least {MIN_PASSWORD_LEN} characters."
        elif password != password_confirm:
            error = "Passwords do not match."
        else:
            uid = create_email_user(email, password, name or None)
            if uid:
                session["user_id"] = uid
                session["user_email"] = email
                session["user_name"] = name or email
                claim_orphaned_stats(uid)
                return redirect(url_for("home.home"))
            error = "This email is already registered. Try logging in."
    return render_template("register.html", error=error)


@bp.route("/login", methods=["GET", "POST"])
def login():
    if session.get("user_id"):
        return redirect(url_for("home.home"))
    error = None
    if request.method == "POST":
        email = (request.form.get("email") or "").strip().lower()
        password = request.form.get("password") or ""
        if not email or not password:
            error = "Email and password are required."
        else:
            user = verify_email_password(email, password)
            if user:
                session["user_id"] = user["id"]
                session["user_email"] = user["email"]
                session["user_name"] = user["name"]
                claim_orphaned_stats(user["id"])
                return redirect(url_for("home.home"))
            error = "Invalid email or password."
    return render_template("login.html", error=error)


@bp.route("/login/callback")
def login_callback():
    try:
        from flask_dance.contrib.google import google as google_client
    except ImportError:
        google_client = None
    if google_client is not None and google_client.authorized:
        try:
            resp = google_client.get("/oauth2/v1/userinfo")
            if resp.ok:
                data = resp.json()
                google_id = data.get("id") or data.get("sub") or ""
                email = data.get("email") or ""
                name = data.get("name") or ""
                if google_id:
                    from app.services.user import find_or_create_user
                    uid = find_or_create_user(google_id, email=email, name=name)
                    session["user_id"] = uid
                    session["user_email"] = email
                    session["user_name"] = name
                    claim_orphaned_stats(uid)
        except Exception:
            logger.exception("OAuth callback error")
    return redirect(url_for("home.home"))


@bp.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("home.home"))


@bp.route("/forgot-password", methods=["GET", "POST"])
def forgot_password():
    if session.get("user_id"):
        return redirect(url_for("home.home"))
    sent = False
    error = None
    if request.method == "POST":
        import secrets
        email = (request.form.get("email") or "").strip().lower()
        if not email or not EMAIL_RE.match(email):
            error = "Please enter a valid email address."
        else:
            user = find_user_by_email(email)
            if user:
                token = secrets.token_urlsafe(32)
                create_reset_token(user["id"], token)
                reset_url = url_for("home.reset_password", token=token, _external=True)
                send_reset_email(email, reset_url)
            # Always show success to avoid user enumeration
            sent = True
    return render_template("forgot_password.html", sent=sent, error=error)


@bp.route("/reset-password/<token>", methods=["GET", "POST"])
def reset_password(token: str):
    if session.get("user_id"):
        return redirect(url_for("home.home"))
    row = get_valid_reset_token(token)
    if not row:
        return render_template("reset_password.html", invalid=True, token=token)
    error = None
    if request.method == "POST":
        password = request.form.get("password") or ""
        password_confirm = request.form.get("password_confirm") or ""
        if len(password) < MIN_PASSWORD_LEN:
            error = f"Password must be at least {MIN_PASSWORD_LEN} characters."
        elif password != password_confirm:
            error = "Passwords do not match."
        else:
            update_password(row["user_id"], password)
            consume_reset_token(token)
            return render_template("reset_password.html", success=True, token=token)
    return render_template("reset_password.html", token=token, error=error, invalid=False)
