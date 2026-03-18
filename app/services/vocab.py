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
_DICT_API_URL = "https://api.dictionaryapi.dev/api/v2/entries/en"
_TRANSLATION_TIMEOUT = 5  # seconds
_TTS_TIMEOUT = 8  # seconds
_DICT_TIMEOUT = 5  # seconds


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


# ── Word Forms & Synonyms (AI-powered) ───────────────────────────────────────

_WORD_FORMS_PROMPT = """\
For the English word "{word}", provide its word family forms and synonyms.

Return ONLY a JSON object with these keys (omit a key if no form exists):
- "noun": list of noun forms (1-3 words)
- "verb": list of verb forms (1-3 words)
- "adjective": list of adjective forms (1-3 words)
- "adverb": list of adverb forms (1-3 words)
- "synonyms": list of 3-6 single-word synonyms

Rules:
- Only include real, commonly used English words.
- Only include forms from the SAME word family (sharing the same root).
- Do NOT include unrelated words that merely start with the same letters.
- Prefer base/dictionary forms (e.g. "attend" not "attending").
- Output raw JSON only, no markdown, no explanation.

Example for "attention":
{{"noun":["attention"],"verb":["attend"],"adjective":["attentive"],"adverb":["attentively"],"synonyms":["focus","concentration","awareness","notice","regard"]}}
"""


def fetch_word_forms(word: str) -> dict:
    """Fetch word family (noun / verb / adjective / adverb) and synonyms via AI.

    Returns dict like::

        {
            "noun": ["attention"],
            "verb": ["attend"],
            "adjective": ["attentive"],
            "adverb": ["attentively"],
            "synonyms": ["focus", "concentration"]
        }

    Falls back to empty dict if AI is unavailable or returns bad data.
    """
    import json as _json

    if not word or not word.strip() or " " in word.strip():
        return {}
    w = word.strip().lower()

    try:
        from app.ai import ai_available, chat_create
        if not ai_available:
            logger.debug("Word forms: AI not available, skipping for '%s'", w)
            return {}

        resp = chat_create(
            messages=[
                {"role": "system", "content": "You are a helpful English linguistics assistant. Respond with valid JSON only."},
                {"role": "user", "content": _WORD_FORMS_PROMPT.format(word=w)},
            ],
            temperature=0.1,
        )
        raw = resp.choices[0].message.content.strip()
        # Strip markdown fences if present
        if raw.startswith("```"):
            raw = raw.split("\n", 1)[-1].rsplit("```", 1)[0].strip()

        forms = _json.loads(raw)
        if not isinstance(forms, dict):
            return {}

        # Validate & sanitize: keep only expected keys with list-of-string values
        clean: dict[str, list[str]] = {}
        for key in ("noun", "verb", "adjective", "adverb", "synonyms"):
            val = forms.get(key)
            if isinstance(val, list):
                items = [s.strip().lower() for s in val if isinstance(s, str) and s.strip()]
                if items:
                    clean[key] = items[:6] if key == "synonyms" else items[:3]

        logger.debug("Word forms (AI) for '%s': %s", w, clean)
        return clean

    except Exception:
        logger.debug("AI word forms failed for: %s", w, exc_info=True)
        return {}


# ── CRUD ─────────────────────────────────────────────────────────────────────

def save_word(user_id: int, word: str, sentence: str, source_part: int | None = None,
              word_forms: str | None = None) -> dict | None:
    """Save a word to the user's vocabulary notebook. Translates automatically.

    Returns the saved row as a dict, or None if duplicate / invalid.
    """
    if not user_id or not word or not word.strip():
        return None

    word = word.strip().lower()
    sentence = (sentence or "").strip()
    word_forms = (word_forms or "").strip()

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

    # Fetch word forms if not provided and it's a single word
    if not word_forms and " " not in word:
        forms = fetch_word_forms(word)
        if forms:
            import json
            word_forms = json.dumps(forms)

    with db_connection() as conn:
        conn.execute(
            """INSERT INTO vocab_notebook
               (user_id, word, sentence, word_ru, sentence_ru, source_part, word_forms, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, datetime('now'))""",
            (user_id, word, sentence, word_ru, sentence_ru, source_part, word_forms),
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


def refresh_word_forms_for_entry(user_id: int, word_id: int) -> dict | None:
    """Re-fetch word forms for an existing vocab entry. Returns updated forms dict or None."""
    import json as _json
    with db_connection() as conn:
        row = conn.execute(
            "SELECT id, word FROM vocab_notebook WHERE id = ? AND user_id = ?",
            (word_id, user_id),
        ).fetchone()
        if not row:
            return None
        word = row["word"]
        if " " in word:
            return {}  # no forms for phrases
        forms = fetch_word_forms(word)
        forms_json = _json.dumps(forms) if forms else ""
        conn.execute(
            "UPDATE vocab_notebook SET word_forms = ? WHERE id = ? AND user_id = ?",
            (forms_json, word_id, user_id),
        )
        conn.commit()
    return forms


def refresh_all_word_forms(user_id: int) -> int:
    """Re-fetch word forms for all single-word entries. Returns count of updated entries."""
    import json as _json
    words = get_words(user_id)
    updated = 0
    for w in words:
        if " " in w["word"]:
            continue
        forms = fetch_word_forms(w["word"])
        forms_json = _json.dumps(forms) if forms else ""
        with db_connection() as conn:
            conn.execute(
                "UPDATE vocab_notebook SET word_forms = ? WHERE id = ? AND user_id = ?",
                (forms_json, w["id"], user_id),
            )
            conn.commit()
        updated += 1
    return updated


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
    import json as _json
    rows = []
    for w in words:
        front_parts = [f"<b>{w['word']}</b>"]
        if with_audio:
            fname = f"fce_{_safe_filename(w['word'])}.mp3"
            front_parts.append(f" [sound:{fname}]")
        # Word forms
        if w.get("word_forms"):
            try:
                forms = _json.loads(w["word_forms"]) if isinstance(w["word_forms"], str) else w["word_forms"]
                labels = {"noun": "n", "verb": "v", "adjective": "adj", "adverb": "adv"}
                form_parts = []
                for pos, abbr in labels.items():
                    if forms.get(pos):
                        vals = forms[pos]
                        if isinstance(vals, list):
                            vals = ", ".join(vals)
                        form_parts.append(f"<span style='color:#7c4dff;font-size:0.8em'>{abbr}: {vals}</span>")
                if forms.get("synonyms"):
                    syns = forms["synonyms"]
                    if isinstance(syns, list):
                        syns = ", ".join(syns)
                    form_parts.append(f"<span style='color:#2e7d32;font-size:0.8em'>syn: {syns}</span>")
                if form_parts:
                    front_parts.append(f"<br>{' &middot; '.join(form_parts)}")
            except Exception:
                pass
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


def export_quizlet_tsv(user_id: int) -> str:
    """Export vocabulary as tab-separated text for Quizlet import.

    Quizlet format: term \t definition  (one card per line).
    Term  = English word + word forms.
    Definition = Russian translation + sentence.
    """
    import json as _json
    words = get_words(user_id)
    lines: list[str] = []
    for w in words:
        # Term side: word + forms
        term_parts = [w["word"]]
        if w.get("word_forms"):
            try:
                forms = _json.loads(w["word_forms"]) if isinstance(w["word_forms"], str) else w["word_forms"]
                labels = {"noun": "n", "verb": "v", "adjective": "adj", "adverb": "adv"}
                for pos, abbr in labels.items():
                    if forms.get(pos):
                        vals = forms[pos]
                        if isinstance(vals, list):
                            vals = ", ".join(vals)
                        term_parts.append(f"{abbr}: {vals}")
                if forms.get("synonyms"):
                    syns = forms["synonyms"]
                    if isinstance(syns, list):
                        syns = ", ".join(syns)
                    term_parts.append(f"syn: {syns}")
            except Exception:
                pass
        if w.get("sentence"):
            term_parts.append(w["sentence"])
        term = " | ".join(term_parts)

        # Definition side: Russian translation + sentence translation
        def_parts: list[str] = []
        if w.get("word_ru"):
            def_parts.append(w["word_ru"])
        if w.get("sentence_ru"):
            def_parts.append(w["sentence_ru"])
        definition = " | ".join(def_parts) or "\u2014"

        # Escape tabs and newlines (Quizlet uses them as delimiters)
        term = term.replace("\t", " ").replace("\n", " ")
        definition = definition.replace("\t", " ").replace("\n", " ")
        lines.append(f"{term}\t{definition}")

    return "\n".join(lines)
