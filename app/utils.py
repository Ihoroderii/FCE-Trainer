"""Shared helpers: text normalization, HTML escape, answer matching."""
from __future__ import annotations

import difflib
import html
import json
import re
from functools import wraps
from typing import Any

from flask import redirect, session, url_for


def norm(s):
    return re.sub(r"\s+", " ", (s or "").strip().lower())


def e(s):
    """HTML-escape for safe output."""
    return html.escape(str(s)) if s is not None else ""


def answers_match(user_val: str, expected: str) -> bool:
    a, b = norm(user_val), norm(expected)
    if a == b:
        return True
    if not a or not b:
        return False
    return difflib.SequenceMatcher(None, a, b).ratio() >= 0.88


def word_count(s: str) -> int:
    return len((s or "").split())


# ---------------------------------------------------------------------------
# Auth decorator
# ---------------------------------------------------------------------------

def login_required(f):
    """Redirect to login page if user is not authenticated."""
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if not session.get("user_id"):
            return redirect(url_for("home.login"))
        return f(*args, **kwargs)
    return decorated_function


# ---------------------------------------------------------------------------
# JSON helpers (shared across parts)
# ---------------------------------------------------------------------------

def extract_json_object(text: str) -> dict[str, Any] | None:
    """Extract first {...} JSON object from text. Returns parsed dict or None."""
    if not text:
        return None
    m = re.search(r"\{[\s\S]*\}", text)
    if not m:
        return None
    try:
        data = json.loads(m.group(0))
        return data if isinstance(data, dict) else None
    except (json.JSONDecodeError, ValueError):
        return None


def extract_json_array(text: str) -> list[Any] | None:
    """Extract first [...] JSON array from text. Returns parsed list or None."""
    if not text:
        return None
    start = text.find("[")
    if start == -1:
        return None
    for end in range(len(text) - 1, start, -1):
        if text[end] != "]":
            continue
        try:
            chunk = text[start : end + 1]
            arr = json.loads(chunk)
            if isinstance(arr, list):
                return arr
        except (json.JSONDecodeError, TypeError):
            continue
    return None


# ---------------------------------------------------------------------------
# AI response validation helpers
# ---------------------------------------------------------------------------

def validate_part1_data(data: dict) -> dict | None:
    """Validate Part 1 task data (multiple-choice cloze). Returns cleaned dict or None."""
    text = (data.get("text") or "").strip()
    gaps = data.get("gaps")
    if not text or not isinstance(gaps, list) or len(gaps) != 8:
        return None
    normalized = []
    for g in gaps:
        opts = g.get("options") or []
        if len(opts) != 4:
            return None
        correct = int(g.get("correct", 0))
        if correct not in (0, 1, 2, 3):
            correct = 0
        normalized.append({"options": [str(o).strip() for o in opts], "correct": correct})
    return {"text": text, "gaps": normalized}


def validate_part2_data(data: dict) -> dict | None:
    """Validate Part 2 task data (open cloze). Returns cleaned dict or None."""
    text = (data.get("text") or "").strip()
    answers = data.get("answers")
    if not text or not isinstance(answers, list) or len(answers) != 8:
        return None
    for i in range(1, 9):
        if f"({i})_____" not in text:
            return None
    return {"text": text, "answers": [str(a).strip() for a in answers]}


def validate_part3_data(data: dict) -> dict | None:
    """Validate Part 3 task data (word formation). Returns cleaned dict or None."""
    text = (data.get("text") or "").strip()
    stems = data.get("stems")
    answers = data.get("answers")
    if not text or not isinstance(stems, list) or len(stems) != 8:
        return None
    if not isinstance(answers, list) or len(answers) != 8:
        return None
    for i in range(1, 9):
        if f"({i})_____" not in text:
            return None
    return {
        "text": text,
        "stems": [str(s).strip().upper() for s in stems],
        "answers": [str(a).strip() for a in answers],
    }


def validate_part5_data(data: dict) -> dict | None:
    """Validate Part 5 task data (reading MCQ). Returns cleaned dict or None."""
    title = (data.get("title") or "").strip()
    text = (data.get("text") or "").strip()
    questions = data.get("questions")
    if not title or not text or not isinstance(questions, list) or len(questions) != 6:
        return None
    wc = len(text.split())
    if wc < 400 or wc > 750:
        return None
    normalized = []
    for qq in questions:
        q = (qq.get("q") or "").strip()
        opts = qq.get("options") or []
        if len(opts) != 4:
            return None
        correct = int(qq.get("correct", 0))
        if correct not in (0, 1, 2, 3):
            correct = 0
        normalized.append({"q": q, "options": [str(o).strip() for o in opts], "correct": correct})
    return {"title": title, "text": text, "questions": normalized}


def validate_get_phrase_data(data: dict) -> dict | None:
    """Validate get-phrase task data. Returns cleaned dict or None."""
    text = (data.get("text") or "").strip()
    answers = data.get("answers")
    if not text or not isinstance(answers, list) or len(answers) != 8:
        return None
    for i in range(1, 9):
        if f"({i})_____" not in text:
            return None
    return {"text": text, "answers": [str(a).strip().lower() for a in answers]}


# ---------------------------------------------------------------------------
# Explanation formatting (shared across parts 1, 2, 3, 5, get_phrases)
# ---------------------------------------------------------------------------

def format_explanation_list(
    details: list[dict],
    answers: list[Any],
    *,
    total: int = 8,
    get_expected: Any = None,
    get_word_family: bool = False,
) -> str:
    """Build the common <ol class='answer-explanations'> HTML block.

    *get_expected* is an optional callable(index, detail) -> expected_display_str.
    """
    expl_list: list[str] = []
    for i, d in enumerate(details):
        if i >= total:
            break
        correct = d.get("correct")
        expected = d.get("expected", answers[i] if i < len(answers) else "")
        if get_expected:
            expected = get_expected(i, d)
        exp = d.get("explanation", "")
        word_family = d.get("word_family", "") if get_word_family else ""
        li_cls = " part2-expl-correct" if correct else " part2-expl-wrong"
        if not correct and expected:
            body = (
                f'<span class="part2-expl-correct">Correct: <em>{e(expected)}</em></span>.'
                + (f' <span class="part2-expl-reason">{e(exp)}</span>' if exp else "")
            )
        elif correct and exp:
            body = f'<span class="part2-expl-reason">{e(exp)}</span>'
        elif correct:
            body = "Correct."
        else:
            body = f'<span class="part2-expl-correct">Correct: <em>{e(expected)}</em></span>.'
        if word_family:
            body += f'<div class="part3-word-family"><strong>Word family:</strong> {e(word_family)}</div>'
        expl_list.append(f'<li class="part2-expl-item{li_cls}"><strong>Gap {i + 1}:</strong> {body}</li>')
    if not expl_list:
        return ""
    return (
        '<div class="explanations-block">'
        '<h4>Why this answer is correct / why it is wrong</h4>'
        '<ol class="answer-explanations">' + "".join(expl_list) + "</ol></div>"
    )
