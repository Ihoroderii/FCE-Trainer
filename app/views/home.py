"""Home, health, mock exam, login/logout."""
import json
import logging
import os
from urllib.parse import urlencode

import re

from flask import Blueprint, current_app, redirect, render_template, request, session, url_for

from app.config import PARTS_RANGE
from app.services.stats import (
    get_part_stats,
    get_daily_stats,
    get_weekly_stats,
    get_progress_series,
    get_words_learning,
    get_get_phrase_stats,
)
from app.services.user import create_email_user, verify_email_password

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


@bp.route("/stats")
def stats():
    user_id = session.get("user_id")
    if user_id is None:
        return redirect(url_for("home.home"))
    user_stats = get_part_stats(user_id)
    daily = get_daily_stats(user_id)
    weekly = get_weekly_stats(user_id)
    progress_series = get_progress_series(user_id, days=14)
    words_learning = get_words_learning(user_id, part=3, limit=60)
    get_phrase_stats = get_get_phrase_stats(user_id)
    has_attempts = any(s.get("attempts", 0) for s in user_stats) or get_phrase_stats.get("attempts", 0)
    return render_template(
        "stats.html",
        user_stats=user_stats,
        daily_stats=daily,
        weekly_stats=weekly,
        progress_series=progress_series,
        words_learning=words_learning,
        get_phrase_stats=get_phrase_stats,
        has_attempts=has_attempts,
    )


@bp.route("/")
def home():
    user_id = session.get("user_id")
    user_email = session.get("user_email") or ""
    user_name = session.get("user_name") or ""
    user_stats = get_part_stats(user_id) if user_id is not None else None
    has_attempts = user_stats and any(s.get("attempts", 0) for s in user_stats)
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
            return (data.get("session_id"), data.get("livekit_room_name"))
    except (urllib.error.URLError, urllib.error.HTTPError, json.JSONDecodeError, KeyError) as e:
        logger.warning("Proctor join failed: %s", e)
        return None


@bp.route("/mock-exam")
def mock_exam():
    if not proctor_is_configured():
        return redirect(url_for("home.home", mode="mock", proctor_required=1))
    proctor_config = proctor_get_config()
    return render_template(
        "mock_exam.html",
        proctor_name=proctor_config.get("name", "Proctor"),
    )


@bp.route("/mock-exam/start", methods=["GET", "POST"])
def mock_exam_start():
    if not proctor_is_configured():
        return redirect(url_for("home.home", mode="mock", proctor_required=1))
    cfg = proctor_get_config()
    backend_url = cfg.get("backend_url")
    frontend_url = cfg.get("frontend_url")
    exam_code = cfg.get("exam_code", "DEMO")
    candidate = (session.get("user_name") or session.get("user_email") or "Candidate").strip() or "Candidate"
    if backend_url and frontend_url:
        result = _call_proctor_join(backend_url, exam_code, candidate)
        if result:
            session_id, livekit_room_name = result
            params = urlencode({"session_id": session_id, "livekit_room_name": livekit_room_name or ""})
            return redirect(f"{frontend_url}/entry?{params}")
        params = urlencode({"exam_code": exam_code, "name": candidate})
        return redirect(f"{frontend_url}/join?{params}")
    session["mock_exam"] = True
    return redirect(url_for("use_of_english.use_of_english", part=1))


EMAIL_RE = re.compile(r"^[^\s@]+@[^\s@]+\.[^\s@]+$")
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
        except Exception:
            logger.exception("OAuth callback error")
    return redirect(url_for("home.home"))


@bp.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("home.home"))
