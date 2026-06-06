"""User settings page — translation language & translator engine."""
import logging

from flask import Blueprint, redirect, render_template, request, session, url_for

from app.services.settings import LANGUAGES, TRANSLATORS, get_user_settings, save_user_settings
from app.services.user import update_password, user_can_change_password, verify_user_password
from app.utils import login_required

logger = logging.getLogger("fce_trainer")
bp = Blueprint("settings", __name__)
MIN_PASSWORD_LEN = 8


def _render_settings_page(password_error: str | None = None, password_success: str | None = None):
    user_id = session["user_id"]
    settings = get_user_settings(user_id)
    return render_template(
        "settings.html",
        settings=settings,
        languages=LANGUAGES,
        translators=TRANSLATORS,
        can_change_password=user_can_change_password(user_id),
        password_error=password_error,
        password_success=password_success,
    )


@bp.route("/settings")
@login_required
def settings_page():
    password_success = None
    if request.args.get("password_updated") == "1":
        password_success = "Your password has been updated."
    return _render_settings_page(password_success=password_success)


@bp.route("/settings", methods=["POST"])
@login_required
def settings_save():
    user_id = session["user_id"]
    target_lang = (request.form.get("target_lang") or "ru").strip()
    translator = (request.form.get("translator") or "google").strip()
    save_user_settings(user_id, target_lang, translator)
    return redirect(url_for("settings.settings_page"))


@bp.route("/settings/password", methods=["POST"])
@login_required
def change_password():
    user_id = session["user_id"]
    current_password = request.form.get("current_password") or ""
    new_password = request.form.get("new_password") or ""
    new_password_confirm = request.form.get("new_password_confirm") or ""
    new_password_clean = new_password.strip()

    if not user_can_change_password(user_id):
        return _render_settings_page(
            password_error="Password changes are available only for email/password accounts."
        )
    if not verify_user_password(user_id, current_password):
        return _render_settings_page(password_error="Current password is incorrect.")
    if len(new_password_clean) < MIN_PASSWORD_LEN:
        return _render_settings_page(
            password_error=f"New password must be at least {MIN_PASSWORD_LEN} characters."
        )
    if new_password != new_password_confirm:
        return _render_settings_page(password_error="New passwords do not match.")

    update_password(user_id, new_password_clean)
    return redirect(url_for("settings.settings_page", password_updated=1))
