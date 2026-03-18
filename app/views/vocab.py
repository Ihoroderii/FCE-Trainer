"""Vocabulary notebook routes — save, list, delete, export."""
import logging

from flask import Blueprint, jsonify, make_response, redirect, render_template, request, session, url_for

from app.services.vocab import (
    delete_word,
    export_anki_tsv,
    export_anki_zip,
    export_quizlet_tsv,
    fetch_word_forms,
    get_word_count,
    get_words,
    save_word,
    update_translation,
)
from app.utils import login_required

logger = logging.getLogger("fce_trainer")
bp = Blueprint("vocab", __name__)


def _api_login_required(f):
    """Like login_required but returns JSON 401 instead of redirect."""
    from functools import wraps
    @wraps(f)
    def decorated(*args, **kwargs):
        if not session.get("user_id"):
            return jsonify({"error": "Login required"}), 401
        return f(*args, **kwargs)
    return decorated


@bp.route("/vocab")
@login_required
def vocab_page():
    import json
    user_id = session["user_id"]
    words = get_words(user_id)
    for w in words:
        w["forms_parsed"] = {}
        if w.get("word_forms"):
            try:
                w["forms_parsed"] = json.loads(w["word_forms"]) if isinstance(w["word_forms"], str) else {}
            except (json.JSONDecodeError, TypeError):
                pass
    return render_template("vocab.html", words=words, current_part=0)


# ── AJAX endpoints ───────────────────────────────────────────────────────────

@bp.route("/api/vocab/save", methods=["POST"])
@_api_login_required
def api_save_word():
    user_id = session["user_id"]
    data = request.get_json(silent=True) or {}
    word = (data.get("word") or "").strip()
    sentence = (data.get("sentence") or "").strip()
    source_part = data.get("source_part")

    if not word:
        return jsonify({"error": "No word provided"}), 400

    if source_part is not None:
        try:
            source_part = int(source_part)
        except (ValueError, TypeError):
            source_part = None

    saved = save_word(user_id, word, sentence, source_part, word_forms=data.get("word_forms"))
    if saved is None:
        return jsonify({"error": "Already saved or invalid"}), 409

    return jsonify({
        "ok": True,
        "word": saved,
    })


@bp.route("/api/vocab/delete", methods=["POST"])
@_api_login_required
def api_delete_word():
    user_id = session["user_id"]
    data = request.get_json(silent=True) or {}
    word_id = data.get("id")
    if not word_id:
        return jsonify({"error": "No id provided"}), 400
    deleted = delete_word(user_id, int(word_id))
    return jsonify({"ok": deleted})


@bp.route("/api/vocab/update", methods=["POST"])
@_api_login_required
def api_update_translation():
    user_id = session["user_id"]
    data = request.get_json(silent=True) or {}
    word_id = data.get("id")
    word_ru = (data.get("word_ru") or "").strip()
    sentence_ru = (data.get("sentence_ru") or "").strip()
    if not word_id:
        return jsonify({"error": "No id provided"}), 400
    updated = update_translation(user_id, int(word_id), word_ru, sentence_ru)
    return jsonify({"ok": updated})


@bp.route("/vocab/export-anki")
@login_required
def export_anki():
    user_id = session["user_id"]
    tsv_content = export_anki_tsv(user_id)
    resp = make_response(tsv_content)
    resp.headers["Content-Type"] = "text/tab-separated-values; charset=utf-8"
    resp.headers["Content-Disposition"] = "attachment; filename=fce_vocab_anki.tsv"
    return resp


@bp.route("/vocab/export-anki-zip")
@login_required
def export_anki_zip_route():
    user_id = session["user_id"]
    zip_bytes = export_anki_zip(user_id)
    resp = make_response(zip_bytes)
    resp.headers["Content-Type"] = "application/zip"
    resp.headers["Content-Disposition"] = "attachment; filename=fce_vocab_anki.zip"
    return resp


@bp.route("/vocab/export-quizlet")
@login_required
def export_quizlet():
    user_id = session["user_id"]
    tsv_content = export_quizlet_tsv(user_id)
    resp = make_response(tsv_content)
    resp.headers["Content-Type"] = "text/plain; charset=utf-8"
    resp.headers["Content-Disposition"] = "attachment; filename=fce_vocab_quizlet.txt"
    return resp


@bp.route("/api/vocab/count")
@_api_login_required
def api_word_count():
    user_id = session["user_id"]
    return jsonify({"count": get_word_count(user_id)})


@bp.route("/api/vocab/word-forms")
def api_word_forms():
    word = (request.args.get("word") or "").strip().lower()
    if not word or len(word) < 2 or " " in word:
        return jsonify({"forms": {}})
    forms = fetch_word_forms(word)
    return jsonify({"forms": forms})


@bp.route("/api/vocab/refresh-forms", methods=["POST"])
@_api_login_required
def api_refresh_forms():
    user_id = session["user_id"]
    data = request.get_json(silent=True) or {}
    word_id = data.get("id")
    if not word_id:
        return jsonify({"error": "No id provided"}), 400
    from app.services.vocab import refresh_word_forms_for_entry
    forms = refresh_word_forms_for_entry(user_id, int(word_id))
    if forms is None:
        return jsonify({"error": "Not found"}), 404
    return jsonify({"ok": True, "forms": forms})


@bp.route("/api/vocab/refresh-all-forms", methods=["POST"])
@_api_login_required
def api_refresh_all_forms():
    user_id = session["user_id"]
    from app.services.vocab import refresh_all_word_forms
    count = refresh_all_word_forms(user_id)
    return jsonify({"ok": True, "updated": count})
