"""Per-word spaced repetition for Part 2 (open cloze) and Part 3 (word formation).

Tracks individual words the user got wrong and schedules them
for re-appearance in future generated tasks.

States:
  - learning: answered wrong → include in next 1-2 generated tasks
  - review:   answered correct once after being wrong → include next day
  - mastered: answered correct again on review day → done
"""
from __future__ import annotations

import logging
import re
from datetime import date, timedelta

from flask import session

from app.db import db_connection

logger = logging.getLogger("fce_trainer")

MAX_REQUIRED_STEMS = 4  # max stems injected into a single Part 3 task
MAX_REQUIRED_WORDS = 4  # max words injected into a single Part 2 task


# ---------------------------------------------------------------------------
# Generic helpers (shared by Part 2 and Part 3)
# ---------------------------------------------------------------------------

def _record_word_results(table: str, key_col: str, details: list[dict],
                         keys: list[str], key_transform=str.upper) -> None:
    """Generic per-word result recorder."""
    user_id = session.get("user_id")
    if not user_id:
        return
    if not details or not keys or len(keys) < len(details):
        return

    today = date.today().isoformat()
    tomorrow = (date.today() + timedelta(days=1)).isoformat()

    with db_connection() as conn:
        for i, d in enumerate(details):
            if i >= len(keys):
                break
            key = key_transform(keys[i].strip())
            if not key:
                continue
            expected = d.get("expected", "").strip().lower()
            correct = d.get("correct", False)

            if not correct:
                existing = conn.execute(
                    f"SELECT id, status FROM {table} WHERE user_id = ? AND {key_col} = ?",
                    (user_id, key),
                ).fetchone()
                if existing:
                    conn.execute(
                        f"UPDATE {table} SET status = 'learning', wrong_count = wrong_count + 1, "
                        f"next_review = ?, last_seen = datetime('now'), answer = ? WHERE id = ?",
                        (today, expected, existing["id"]),
                    )
                else:
                    conn.execute(
                        f"INSERT INTO {table} (user_id, {key_col}, answer, status, wrong_count, next_review) "
                        f"VALUES (?, ?, ?, 'learning', 1, ?)",
                        (user_id, key, expected, today),
                    )
            else:
                existing = conn.execute(
                    f"SELECT id, status, next_review FROM {table} WHERE user_id = ? AND {key_col} = ?",
                    (user_id, key),
                ).fetchone()
                if not existing:
                    continue
                if existing["status"] == "learning":
                    conn.execute(
                        f"UPDATE {table} SET status = 'review', correct_count = correct_count + 1, "
                        f"next_review = ?, last_seen = datetime('now') WHERE id = ?",
                        (tomorrow, existing["id"]),
                    )
                elif existing["status"] == "review" and existing["next_review"] <= today:
                    conn.execute(
                        f"UPDATE {table} SET status = 'mastered', correct_count = correct_count + 1, "
                        f"last_seen = datetime('now') WHERE id = ?",
                        (existing["id"],),
                    )
        conn.commit()


def _get_due_items(table: str, key_col: str, limit: int,
                   user_id: int | None = None) -> list[dict]:
    """Return due items for repetition."""
    if user_id is None:
        user_id = session.get("user_id")
    if not user_id:
        return []

    today = date.today().isoformat()
    with db_connection() as conn:
        rows = conn.execute(
            f"SELECT {key_col}, answer FROM {table} "
            f"WHERE user_id = ? AND status IN ('learning', 'review') AND next_review <= ? "
            f"ORDER BY CASE status WHEN 'learning' THEN 0 ELSE 1 END, wrong_count DESC "
            f"LIMIT ?",
            (user_id, today, limit),
        ).fetchall()
    return [{"key": r[key_col], "answer": r["answer"]} for r in rows]


# ---------------------------------------------------------------------------
# Part 3 — word formation stems
# ---------------------------------------------------------------------------

def record_part3_word_results(details: list[dict], stems: list[str]) -> None:
    """After checking Part 3, record per-stem outcomes."""
    _record_word_results("part3_word_repetition", "stem", details, stems,
                         key_transform=str.upper)


def get_due_stems(user_id: int | None = None) -> list[dict]:
    """Return stems due for repetition.

    Returns up to MAX_REQUIRED_STEMS dicts: {"stem": "COMPLETE", "answer": "completion"}.
    """
    items = _get_due_items("part3_word_repetition", "stem", MAX_REQUIRED_STEMS,
                           user_id=user_id)
    return [{"stem": it["key"], "answer": it["answer"]} for it in items]


# ---------------------------------------------------------------------------
# Part 2 — open cloze words
# ---------------------------------------------------------------------------

def record_part2_word_results(details: list[dict], answers: list[str]) -> None:
    """After checking Part 2, record per-word outcomes."""
    _record_word_results("part2_word_repetition", "word", details, answers,
                         key_transform=str.lower)


def get_due_words_part2(user_id: int | None = None) -> list[dict]:
    """Return Part 2 words due for repetition.

    Returns up to MAX_REQUIRED_WORDS dicts: {"word": "although", "answer": "although"}.
    """
    items = _get_due_items("part2_word_repetition", "word", MAX_REQUIRED_WORDS,
                           user_id=user_id)
    return [{"word": it["key"], "answer": it["answer"]} for it in items]


# ---------------------------------------------------------------------------
# Part 2 — collocation extraction
# ---------------------------------------------------------------------------

def _extract_sentence_context(text: str, gap_index: int, answer: str) -> str:
    """Extract the sentence surrounding a gap from Part 2 text.

    Returns the sentence with the answer filled in.
    """
    filled = text
    for j in range(8, 0, -1):
        placeholder = f"({j})_____"
        if j == gap_index + 1:
            filled = filled.replace(placeholder, answer)
        else:
            filled = filled.replace(placeholder, "___")

    # Split into sentences and find the one containing our answer insertion point
    sentences = re.split(r'(?<=[.!?])\s+', filled)
    for sent in sentences:
        if answer in sent and "___" not in sent:
            return sent.strip()
    # Fallback: return the sentence even if it has other gaps
    for sent in sentences:
        if answer in sent:
            return sent.strip()
    return ""


def record_part2_collocations(details: list[dict], answers: list[str],
                              text: str) -> None:
    """Save collocations (word + context sentence) from Part 2 for study.

    Only records gaps the user got wrong — these are the collocations to learn.
    """
    user_id = session.get("user_id")
    if not user_id or not details or not answers or not text:
        return

    with db_connection() as conn:
        for i, d in enumerate(details):
            if i >= len(answers):
                break
            if d.get("correct"):
                continue  # only record wrong answers
            expected = answers[i].strip().lower()
            if not expected:
                continue
            context = _extract_sentence_context(text, i, expected)
            if not context:
                continue
            # Avoid duplicates (same user + word + context)
            existing = conn.execute(
                "SELECT id FROM part2_collocations WHERE user_id = ? AND word = ? AND context = ?",
                (user_id, expected, context),
            ).fetchone()
            if existing:
                continue
            conn.execute(
                "INSERT INTO part2_collocations (user_id, word, context) VALUES (?, ?, ?)",
                (user_id, expected, context),
            )
        conn.commit()


def get_collocations(user_id: int | None = None) -> list[dict]:
    """Return all collocations for the user, ordered by most recent first."""
    if user_id is None:
        user_id = session.get("user_id")
    if not user_id:
        return []
    with db_connection() as conn:
        rows = conn.execute(
            "SELECT id, word, context, word_ru, context_ru, created_at "
            "FROM part2_collocations WHERE user_id = ? ORDER BY created_at DESC",
            (user_id,),
        ).fetchall()
    return [dict(r) for r in rows]


def get_collocation_count(user_id: int | None = None) -> int:
    if user_id is None:
        user_id = session.get("user_id")
    if not user_id:
        return 0
    with db_connection() as conn:
        row = conn.execute(
            "SELECT COUNT(*) AS n FROM part2_collocations WHERE user_id = ?",
            (user_id,),
        ).fetchone()
    return row["n"] if row else 0


def delete_collocation(collocation_id: int, user_id: int) -> bool:
    with db_connection() as conn:
        cur = conn.execute(
            "DELETE FROM part2_collocations WHERE id = ? AND user_id = ?",
            (collocation_id, user_id),
        )
        conn.commit()
        return cur.rowcount > 0


def update_collocation_translation(collocation_id: int, user_id: int,
                                   word_ru: str, context_ru: str) -> bool:
    with db_connection() as conn:
        cur = conn.execute(
            "UPDATE part2_collocations SET word_ru = ?, context_ru = ? WHERE id = ? AND user_id = ?",
            (word_ru.strip(), context_ru.strip(), collocation_id, user_id),
        )
        conn.commit()
        return cur.rowcount > 0


def export_collocations_anki_tsv(user_id: int) -> str:
    """Export collocations as TSV for Anki import."""
    import csv
    import io

    collocations = get_collocations(user_id)
    output = io.StringIO()
    writer = csv.writer(output, delimiter="\t", quoting=csv.QUOTE_MINIMAL)
    output.write("#separator:tab\n")
    output.write("#html:true\n")
    output.write("#tags column:3\n")

    for c in collocations:
        word = c["word"]
        context = c["context"]
        word_ru = c.get("word_ru") or ""
        context_ru = c.get("context_ru") or ""

        # Front: context sentence with the word highlighted
        highlighted = context.replace(word, f"<b>{word}</b>", 1) if word in context else f"<b>{word}</b><br>{context}"
        front = highlighted

        # Back: Russian translation
        back_parts = []
        if word_ru:
            back_parts.append(f"<b>{word_ru}</b>")
        if context_ru:
            back_parts.append(context_ru)
        back = "<br>".join(back_parts) if back_parts else word

        writer.writerow([front, back, "fce_part2_collocations"])

    return output.getvalue()


def translate_collocation(collocation_id: int, user_id: int) -> dict:
    """Auto-translate a collocation's word and context to Russian."""
    from app.services.vocab import translate_word_and_sentence

    with db_connection() as conn:
        row = conn.execute(
            "SELECT word, context FROM part2_collocations WHERE id = ? AND user_id = ?",
            (collocation_id, user_id),
        ).fetchone()
        if not row:
            return {}
        word_ru, context_ru = translate_word_and_sentence(row["word"], row["context"])
        if word_ru or context_ru:
            conn.execute(
                "UPDATE part2_collocations SET word_ru = ?, context_ru = ? WHERE id = ? AND user_id = ?",
                (word_ru, context_ru, collocation_id, user_id),
            )
            conn.commit()
        return {"word_ru": word_ru, "context_ru": context_ru}
