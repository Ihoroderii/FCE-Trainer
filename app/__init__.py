"""Application factory and Flask app creation."""
import logging
import os
from pathlib import Path
from urllib.parse import urlencode, urlparse, urlunparse, parse_qs

from flask import Flask, redirect, request, url_for
from flask_wtf.csrf import CSRFProtect

from app.config import PARTS_RANGE
from app.db import init_db, seed_db, _ensure_uoe_grammar_topic_column, _ensure_check_history_user_id
from app.views.home import bp as home_bp
from app.views.use_of_english import bp as uoe_bp
from app.views.writing import bp as writing_bp

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
logger = logging.getLogger("fce_trainer")

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
    app.config["WTF_CSRF_TIME_LIMIT"] = None

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

    if app.config["GOOGLE_OAUTH_CLIENT_ID"] and app.config["GOOGLE_OAUTH_CLIENT_SECRET"]:
        from flask_dance.contrib.google import make_google_blueprint
        google_bp = make_google_blueprint(scope=["profile", "email"], redirect_to="home.login_callback")
        app.register_blueprint(google_bp, url_prefix="/login")
    else:
        pass  # no Google OAuth

    with app.app_context():
        init_db()
        _ensure_uoe_grammar_topic_column()
        _ensure_check_history_user_id()
        seed_db()

    return app
