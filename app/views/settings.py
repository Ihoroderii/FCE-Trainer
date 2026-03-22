"""User settings page — translation language & translator engine."""
import logging

from flask import Blueprint, jsonify, redirect, render_template, request, session, url_for

from app.services.settings import LANGUAGES, TRANSLATORS, get_user_settings, save_user_settings
from app.utils import login_required

logger = logging.getLogger("fce_trainer")
bp = Blueprint("settings", __name__)


@bp.route("/settings")
@login_required
def settings_page():
    user_id = session["user_id"]
    settings = get_user_settings(user_id)
    return render_template(
        "settings.html",
        settings=settings,
        languages=LANGUAGES,
        translators=TRANSLATORS,
    )


@bp.route("/settings", methods=["POST"])
@login_required
def settings_save():
    user_id = session["user_id"]
    target_lang = (request.form.get("target_lang") or "ru").strip()
    translator = (request.form.get("translator") or "google").strip()
    save_user_settings(user_id, target_lang, translator)
    return redirect(url_for("settings.settings_page"))
