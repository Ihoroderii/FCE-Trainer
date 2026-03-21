"""Application factory and Flask app creation."""
import logging
import os
from pathlib import Path
from urllib.parse import urlencode, urlparse, urlunparse, parse_qs

from flask import Flask, redirect, request, session, url_for
from flask_wtf.csrf import CSRFProtect

from app.config import PARTS_RANGE
from app.db import init_db, seed_db, _ensure_uoe_grammar_topic_column, _ensure_check_history_user_id, _ensure_users_password_column, _ensure_gamification_tables, _ensure_check_history_created_index, _ensure_spaced_repetition_table, _ensure_orphaned_stats_claimed, _ensure_vocab_notebook_table, _ensure_vocab_word_forms_column, _ensure_part3_word_repetition_table
from app.views.home import bp as home_bp
from app.views.use_of_english import bp as uoe_bp
from app.views.writing import bp as writing_bp
from app.views.get_phrases import bp as get_phrases_bp
from app.views.vocab import bp as vocab_bp

_debug_mode = os.environ.get("FLASK_DEBUG", "").lower() in ("1", "true", "yes")
_log_level = logging.DEBUG if _debug_mode else logging.INFO
logging.basicConfig(level=_log_level, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
logger = logging.getLogger("fce_trainer")
if _debug_mode:
    logger.debug("Debug mode ON — verbose logging enabled")

# Project root (parent of the app package) — templates/ and static/ live here
_PROJECT_ROOT = Path(__file__).resolve().parent.parent


def create_app(config=None):
    app = Flask(
        __name__,
        template_folder=str(_PROJECT_ROOT / "templates"),
        static_folder=str(_PROJECT_ROOT / "static"),
        static_url_path="",
    )
    _secret = (os.environ.get("SECRET_KEY") or "").strip()
    if not _secret:
        if os.environ.get("FLASK_ENV") == "production":
            raise ValueError(
                "SECRET_KEY must be set in production. "
                'Generate one: python -c "import secrets; print(secrets.token_hex(32))"'
            )
        _secret = "dev-secret-change-in-production"
        logger.warning("SECRET_KEY not set; using dev default. Set SECRET_KEY in production.")
    app.secret_key = _secret
    app.config["SESSION_COOKIE_HTTPONLY"] = True
    app.config["SESSION_COOKIE_SAMESITE"] = "Lax"
    if os.environ.get("SESSION_COOKIE_SECURE", "").lower() in ("1", "true", "yes"):
        app.config["SESSION_COOKIE_SECURE"] = True
    CSRFProtect(app)
    app.config["WTF_CSRF_TIME_LIMIT"] = 3600

    # Rate limiting
    from flask_limiter import Limiter
    from flask_limiter.util import get_remote_address
    limiter = Limiter(
        get_remote_address,
        app=app,
        default_limits=["200 per day", "50 per hour"],
        storage_uri="memory://",
    )
    app.extensions["limiter"] = limiter

    app.config["GOOGLE_OAUTH_CLIENT_ID"] = os.environ.get("GOOGLE_OAUTH_CLIENT_ID", "")
    app.config["GOOGLE_OAUTH_CLIENT_SECRET"] = os.environ.get("GOOGLE_OAUTH_CLIENT_SECRET", "")

    @app.errorhandler(400)
    def handle_bad_request(err):
        if request.method == "POST" and request.referrer and "/use-of-english" in request.referrer:
            parsed = urlparse(request.referrer)
            qs = parse_qs(parsed.query)
            qs["csrf_expired"] = ["1"]
            new_query = urlencode(qs, doseq=True)
            return redirect(urlunparse((parsed.scheme, parsed.netloc, parsed.path, "", new_query, "")))
        part = request.form.get("part", type=int, default=0) or request.args.get("part", type=int, default=1)
        if part not in PARTS_RANGE:
            part = 1
        return redirect(url_for("use_of_english.use_of_english", part=part, csrf_expired=1))

    app.register_blueprint(home_bp)
    app.register_blueprint(uoe_bp)
    app.register_blueprint(writing_bp)
    app.register_blueprint(get_phrases_bp)
    app.register_blueprint(vocab_bp)

    # Apply strict rate limits to auth endpoints
    limiter.limit("5/minute")(app.view_functions["home.register"])
    limiter.limit("5/minute")(app.view_functions["home.login"])

    if app.config["GOOGLE_OAUTH_CLIENT_ID"] and app.config["GOOGLE_OAUTH_CLIENT_SECRET"]:
        from flask_dance.contrib.google import make_google_blueprint
        google_bp = make_google_blueprint(scope=["profile", "email"], redirect_to="home.login_callback")
        app.register_blueprint(google_bp, url_prefix="/login")
    else:
        pass  # no Google OAuth

    @app.context_processor
    def inject_user():
        return {
            "current_user_id": session.get("user_id"),
            "current_user_email": session.get("user_email") or "",
            "current_user_name": session.get("user_name") or "",
        }

    with app.app_context():
        logger.debug("Initialising database and running migrations…")
        init_db()
        _ensure_uoe_grammar_topic_column()
        _ensure_check_history_user_id()
        _ensure_users_password_column()
        _ensure_gamification_tables()
        _ensure_check_history_created_index()
        _ensure_spaced_repetition_table()
        _ensure_orphaned_stats_claimed()
        _ensure_vocab_notebook_table()
        _ensure_vocab_word_forms_column()
        _ensure_part3_word_repetition_table()
        seed_db()
        logger.debug("Database ready")

    logger.info("FCE-Trainer starting (debug=%s, AI=%s)",
                _debug_mode,
                "enabled" if app.config.get("AI_ENABLED") else "disabled")

    return app
