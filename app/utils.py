"""Shared helpers: text normalization, HTML escape, answer matching."""
import difflib
import html
import re


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
