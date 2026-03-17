"""Vocabulary notebook — save words from reading texts, translate, export to Anki."""
from __future__ import annotations

import csv
import io
import logging
import re
import zipfile
from datetime import datetime
from urllib.parse import quote

import requests

from app.db import db_connection

logger = logging.getLogger("fce_trainer")

_MYMEMORY_URL = "https://api.mymemory.translated.net/get"
_TRANSLATION_TIMEOUT = 5  # seconds
_TTS_TIMEOUT = 8  # seconds


# ── Translation ──────────────────────────────────────────────────────────────

def _translate_en_ru(text: str) -> str:
    """Translate English → Russian via MyMemory free API.

    Returns translated text, or empty string on failure.
    """
    if not text or not text.strip():
        return ""
    try:
        resp = requests.get(
            _MYMEMORY_URL,
            params={"q": text.strip()[:500], "langpair": "en|ru"},
            timeout=_TRANSLATION_TIMEOUT,
        )
        resp.raise_for_status()
        data = resp.json()
        translated = data.get("responseData", {}).get("translatedText", "")
        if translated and translated.upper() != text.strip().upper():
            logger.debug("Translated '%s' → '%s'", text.strip()[:60], translated[:60])
            return translated
        return ""
    except Exception:
        logger.warning("Translation failed for: %s", text[:60], exc_info=True)
        return ""


def translate_word_and_sentence(word: str, sentence: str) -> tuple[str, str]:
    """Return (word_ru, sentence_ru)."""
    word_ru = _translate_en_ru(word)
    sentence_ru = _translate_en_ru(sentence) if sentence else ""
    return word_ru, sentence_ru


# ── CRUD ─────────────────────────────────────────────────────────────────────

def save_word(user_id: int, word: str, sentence: str, source_part: int | None = None) -> dict | None:
    """Save a word to the user's vocabulary notebook. Translates automatically.

    Returns the saved row as a dict, or None if duplicate / invalid.
    """
    if not user_id or not word or not word.strip():
        return None

    word = word.strip().lower()
    sentence = (sentence or "").strip()

    # Check for duplicate (same user + word + sentence)
    with db_connection() as conn:
        existing = conn.execute(
            "SELECT id FROM vocab_notebook WHERE user_id = ? AND word = ? AND sentence = ?",
            (user_id, word, sentence),
        ).fetchone()
        if existing:
            return None

    # Translate
    word_ru, sentence_ru = translate_word_and_sentence(word, sentence)

    with db_connection() as conn:
        conn.execute(
            """INSERT INTO vocab_notebook
               (user_id, word, sentence, word_ru, sentence_ru, source_part, created_at)
               VALUES (?, ?, ?, ?, ?, ?, datetime('now'))""",
            (user_id, word, sentence, word_ru, sentence_ru, source_part),
        )
        conn.commit()
        row = conn.execute(
            "SELECT * FROM vocab_notebook WHERE user_id = ? ORDER BY id DESC LIMIT 1",
            (user_id,),
        ).fetchone()
    logger.debug("Saved vocab word: '%s' for user %d", word, user_id)
    return dict(row) if row else None


def get_words(user_id: int) -> list[dict]:
    """Get all vocabulary words for a user, newest first."""
    with db_connection() as conn:
        rows = conn.execute(
            "SELECT * FROM vocab_notebook WHERE user_id = ? ORDER BY created_at DESC",
            (user_id,),
        ).fetchall()
    return [dict(r) for r in rows]


def get_word_count(user_id: int) -> int:
    """Get the count of saved words for a user."""
    with db_connection() as conn:
        row = conn.execute(
            "SELECT COUNT(*) AS cnt FROM vocab_notebook WHERE user_id = ?",
            (user_id,),
        ).fetchone()
    return row["cnt"] if row else 0


def delete_word(user_id: int, word_id: int) -> bool:
    """Delete a word from the notebook. Returns True if deleted."""
    with db_connection() as conn:
        cur = conn.execute(
            "DELETE FROM vocab_notebook WHERE id = ? AND user_id = ?",
            (word_id, user_id),
        )
        conn.commit()
    return cur.rowcount > 0


def update_translation(user_id: int, word_id: int, word_ru: str, sentence_ru: str) -> bool:
    """Manually update translations for a word."""
    with db_connection() as conn:
        cur = conn.execute(
            "UPDATE vocab_notebook SET word_ru = ?, sentence_ru = ? WHERE id = ? AND user_id = ?",
            (word_ru, sentence_ru, word_id, user_id),
        )
        conn.commit()
    return cur.rowcount > 0


# ── TTS Audio ────────────────────────────────────────────────────────────────

def _safe_filename(word: str) -> str:
    """Create a safe filename from a word."""
    return re.sub(r"[^a-zA-Z0-9_-]", "_", word.strip().lower())[:50]


def _fetch_tts_audio(word: str) -> bytes | None:
    """Fetch TTS MP3 audio for an English word via Google Translate TTS.

    Returns MP3 bytes, or None on failure.
    """
    if not word or not word.strip():
        return None
    try:
        encoded_word = quote(word.strip()[:100])
        url = (
            "https://translate.google.com/translate_tts"
            f"?ie=UTF-8&client=tw-ob&tl=en&q={encoded_word}"
        )
        resp = requests.get(
            url,
            timeout=_TTS_TIMEOUT,
            headers={"User-Agent": "Mozilla/5.0"},
        )
        if resp.status_code == 200 and len(resp.content) > 100:
            return resp.content
        return None
    except Exception:
        logger.debug("TTS fetch failed for: %s", word[:30], exc_info=True)
        return None


# ── Anki Export ──────────────────────────────────────────────────────────────

def _build_anki_rows(words: list[dict], with_audio: bool = False) -> list[list[str]]:
    """Build rows for Anki TSV. Each row = [front, back, tag]."""
    rows = []
    for w in words:
        front_parts = [f"<b>{w['word']}</b>"]
        if with_audio:
            fname = f"fce_{_safe_filename(w['word'])}.mp3"
            front_parts.append(f" [sound:{fname}]")
        if w.get("sentence"):
            front_parts.append(f"<br><i>{w['sentence']}</i>")
        front = "".join(front_parts)

        back_parts = []
        if w.get("word_ru"):
            back_parts.append(f"<b>{w['word_ru']}</b>")
        if w.get("sentence_ru"):
            back_parts.append(f"<br><i>{w['sentence_ru']}</i>")
        back = "".join(back_parts) or "—"

        tag = f"fce_part{w['source_part']}" if w.get("source_part") else "fce_vocab"
        rows.append([front, back, tag])
    return rows


def export_anki_tsv(user_id: int) -> str:
    """Export vocabulary as a tab-separated file for Anki import.

    Format: Front (English) \t Back (Russian)
    Front = word + sentence context
    Back = translation + sentence translation
    """
    words = get_words(user_id)
    output = io.StringIO()
    writer = csv.writer(output, delimiter="\t", quoting=csv.QUOTE_MINIMAL)
    # Anki comment header
    output.write("#separator:tab\n")
    output.write("#html:true\n")
    output.write("#tags column:3\n")

    for row in _build_anki_rows(words, with_audio=False):
        writer.writerow(row)

    return output.getvalue()


def export_anki_zip(user_id: int) -> bytes:
    """Export vocabulary as a ZIP containing TSV + MP3 audio files.

    The ZIP structure:
      fce_vocab_anki.tsv   — the card data referencing [sound:fce_word.mp3]
      fce_word.mp3          — pronunciation audio per word

    User unpacks into Anki's collection.media folder, then imports the TSV.
    """
    words = get_words(user_id)
    rows = _build_anki_rows(words, with_audio=True)

    # Build TSV
    tsv_io = io.StringIO()
    writer = csv.writer(tsv_io, delimiter="\t", quoting=csv.QUOTE_MINIMAL)
    tsv_io.write("#separator:tab\n")
    tsv_io.write("#html:true\n")
    tsv_io.write("#tags column:3\n")
    for row in rows:
        writer.writerow(row)
    tsv_bytes = tsv_io.getvalue().encode("utf-8")

    # Build ZIP
    zip_io = io.BytesIO()
    with zipfile.ZipFile(zip_io, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("fce_vocab_anki.tsv", tsv_bytes)

        seen = set()
        for w in words:
            fname = f"fce_{_safe_filename(w['word'])}.mp3"
            if fname in seen:
                continue
            seen.add(fname)
            audio = _fetch_tts_audio(w["word"])
            if audio:
                zf.writestr(fname, audio)
            else:
                logger.debug("Skipped audio for '%s' — TTS unavailable", w["word"])

    return zip_io.getvalue()
