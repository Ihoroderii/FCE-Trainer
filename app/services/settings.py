"""User settings — translation preferences (language, translator engine)."""
from __future__ import annotations

import logging

from app.db import db_connection

logger = logging.getLogger("fce_trainer")

# Translators available without API keys
TRANSLATORS = {
    "google": "Google Translate",
    "mymemory": "MyMemory",
    "linguee": "Linguee",
    "pons": "PONS",
    "ai": "AI (uses your configured AI provider)",
}

# Popular target languages (code → display name)
LANGUAGES = {
    "ru": "🇷🇺 Russian",
    "uk": "🇺🇦 Ukrainian",
    "de": "🇩🇪 German",
    "fr": "🇫🇷 French",
    "es": "🇪🇸 Spanish",
    "it": "🇮🇹 Italian",
    "pt": "🇵🇹 Portuguese",
    "pl": "🇵🇱 Polish",
    "nl": "🇳🇱 Dutch",
    "cs": "🇨🇿 Czech",
    "tr": "🇹🇷 Turkish",
    "zh-CN": "🇨🇳 Chinese (Simplified)",
    "zh-TW": "🇹🇼 Chinese (Traditional)",
    "ja": "🇯🇵 Japanese",
    "ko": "🇰🇷 Korean",
    "ar": "🇸🇦 Arabic",
    "hi": "🇮🇳 Hindi",
    "th": "🇹🇭 Thai",
    "vi": "🇻🇳 Vietnamese",
    "sv": "🇸🇪 Swedish",
    "da": "🇩🇰 Danish",
    "fi": "🇫🇮 Finnish",
    "no": "🇳🇴 Norwegian",
    "el": "🇬🇷 Greek",
    "hu": "🇭🇺 Hungarian",
    "ro": "🇷🇴 Romanian",
    "bg": "🇧🇬 Bulgarian",
    "hr": "🇭🇷 Croatian",
    "sr": "🇷🇸 Serbian",
    "sk": "🇸🇰 Slovak",
    "sl": "🇸🇮 Slovenian",
    "lt": "🇱🇹 Lithuanian",
    "lv": "🇱🇻 Latvian",
    "et": "🇪🇪 Estonian",
    "ka": "🇬🇪 Georgian",
    "hy": "🇦🇲 Armenian",
    "kk": "🇰🇿 Kazakh",
    "az": "🇦🇿 Azerbaijani",
    "id": "🇮🇩 Indonesian",
    "ms": "🇲🇾 Malay",
    "he": "🇮🇱 Hebrew",
    "fa": "🇮🇷 Persian",
}

_DEFAULTS = {"target_lang": "ru", "translator": "google"}


def get_user_settings(user_id: int) -> dict:
    """Return user settings dict. Creates defaults if not exists."""
    with db_connection() as conn:
        row = conn.execute(
            "SELECT target_lang, translator FROM user_settings WHERE user_id = ?",
            (user_id,),
        ).fetchone()
    if row:
        return {"target_lang": row["target_lang"], "translator": row["translator"]}
    return dict(_DEFAULTS)


def save_user_settings(user_id: int, target_lang: str, translator: str) -> dict:
    """Save user settings. Returns the saved values."""
    if target_lang not in LANGUAGES:
        target_lang = _DEFAULTS["target_lang"]
    if translator not in TRANSLATORS:
        translator = _DEFAULTS["translator"]
    with db_connection() as conn:
        conn.execute(
            """INSERT INTO user_settings (user_id, target_lang, translator, updated_at)
               VALUES (?, ?, ?, datetime('now'))
               ON CONFLICT(user_id) DO UPDATE SET
                 target_lang = excluded.target_lang,
                 translator = excluded.translator,
                 updated_at = excluded.updated_at""",
            (user_id, target_lang, translator),
        )
        conn.commit()
    return {"target_lang": target_lang, "translator": translator}
