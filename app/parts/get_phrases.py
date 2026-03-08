"""Get phrases: study mode — 8 gaps, each gap = correct collocation with GET (e.g. get over, get rid of)."""
import json
import logging
import re

from flask import session

from app.ai import chat_create, ai_available
from app.ai.prompts import get_task_prompt_get_phrases
from app.ai.explanations import fetch_explanations_get_phrases
from app.config import GET_PHRASE_PART, MAX_EXPLANATION_LEN
from app.db import db_connection, get_get_phrase_task_by_id, pick_get_phrase_task_id, record_get_phrase_show
from app.utils import e as _e, answers_match

logger = logging.getLogger("fce_trainer")


def generate_get_phrase_with_openai(level="b2"):
    if not ai_available:
        return None
    prompt = get_task_prompt_get_phrases(level=level)
    for attempt in range(3):
        try:
            comp = chat_create([{"role": "user", "content": prompt}], temperature=0.7)
            content = (comp.choices[0].message.content or "").strip()
            m = re.search(r"\{[\s\S]*\}", content)
            if not m:
                continue
            data = json.loads(m.group(0))
            text = (data.get("text") or "").strip()
            answers = data.get("answers")
            if not text or not isinstance(answers, list) or len(answers) != 8:
                continue
            for i in range(1, 9):
                if f"({i})_____" not in text:
                    break
            else:
                answers_str = [str(a).strip().lower() for a in answers]
                payload = {"text": text, "answers": answers_str}
                with db_connection() as conn:
                    cur = conn.execute(
                        "INSERT INTO get_phrase_tasks (items_json, source) VALUES (?, ?)",
                        (json.dumps(payload), "openai"),
                    )
                    tid = cur.lastrowid
                    conn.commit()
                return get_get_phrase_task_by_id(tid)
        except Exception:
            if attempt == 2:
                logger.exception("OpenAI Get phrases error")
            continue
    return None


def get_or_create_get_phrase_item(exclude_task_id=None):
    task_id = pick_get_phrase_task_id(exclude_task_id=exclude_task_id)
    if task_id is None and ai_available:
        item = generate_get_phrase_with_openai()
        if item:
            with db_connection() as conn:
                cur = conn.execute("SELECT id FROM get_phrase_tasks ORDER BY id DESC LIMIT 1")
                row = cur.fetchone()
            if row:
                record_get_phrase_show(row["id"])
                return (item, row["id"])
            return (item, None)
    if task_id is None:
        return (None, None)
    record_get_phrase_show(task_id)
    return (get_get_phrase_task_by_id(task_id), task_id)


def build_get_phrase_html(task, check_result=None):
    if not task or not task.get("text") or not task.get("answers") or len(task.get("answers", [])) < 8:
        return "<p>No data.</p>"
    text = (task.get("text") or "").strip()
    answers = task.get("answers") or []
    parts = re.split(r"\((?:1|2|3|4|5|6|7|8)\)_____", text)
    if len(parts) != 9:
        return "<p>Invalid get-phrase text format.</p>"
    out = []
    for i in range(8):
        val = ""
        cls = ""
        if check_result and check_result.get("details") and i < len(check_result["details"]):
            val = check_result["details"][i].get("user_val", "")
            cls = " result-correct" if check_result["details"][i].get("correct") else " result-wrong"
        out.append(_e(parts[i]))
        out.append(
            f'<span class="gap-inline part3-gap{cls}">'
            f'<input type="text" name="gp_{i}" value="{_e(val)}" placeholder="{i + 1}" autocomplete="off" aria-label="Gap {i + 1}" />'
            f"</span>"
        )
    out.append(_e(parts[8]))
    left_html = "".join(out)
    if check_result and check_result.get("details"):
        expl_list = []
        for i, d in enumerate(check_result["details"]):
            if i >= 8:
                break
            expected = d.get("expected", answers[i] if i < len(answers) else "")
            correct = d.get("correct")
            exp = d.get("explanation", "")
            li_cls = " part2-expl-correct" if correct else " part2-expl-wrong"
            if not correct and expected:
                body = f'<span class="part2-expl-correct">Correct: <em>{_e(expected)}</em></span>. <span class="part2-expl-reason">{_e(exp)}</span>'
            elif correct and exp:
                body = f'<span class="part2-expl-reason">{_e(exp)}</span>'
            elif correct:
                body = "Correct."
            else:
                body = f'<span class="part2-expl-correct">Correct: <em>{_e(expected)}</em></span>.'
            expl_list.append(f'<li class="part2-expl-item{li_cls}"><strong>Gap {i + 1}:</strong> {body}</li>')
        if expl_list:
            left_html += (
                '<div class="explanations-block">'
                '<h4>Why this answer is correct / why it is wrong</h4>'
                '<ol class="answer-explanations">' + "".join(expl_list) + "</ol></div>"
            )
    hint = '<p class="get-phrase-hint">Each gap needs a phrase with <strong>get</strong> (e.g. get over, get rid of, get along with, get through).</p>'
    return (
        '<div class="get-phrase-single reading-text exercise cloze-text">'
        + hint
        + left_html
        + "</div>"
    )


def check_get_phrases(form):
    task_id = session.get("get_phrase_task_id")
    if not task_id:
        _, task_id = get_or_create_get_phrase_item()
        if task_id:
            session["get_phrase_task_id"] = task_id
    task = get_get_phrase_task_by_id(task_id) if task_id else None
    if not task or not task.get("answers") or len(task["answers"]) < 8:
        return None
    answers = task["answers"]
    details = []
    score = 0
    for i in range(8):
        user_val = (form.get(f"gp_{i}") or "").strip()
        expected = answers[i] if i < len(answers) else ""
        correct = answers_match(user_val, expected)
        if correct:
            score += 1
        details.append({"correct": correct, "user_val": user_val, "expected": expected})
    result = {"part": GET_PHRASE_PART, "score": score, "total": 8, "details": details}
    explanations_data = fetch_explanations_get_phrases(task, details)
    for i, data in enumerate(explanations_data):
        if i < len(result["details"]) and data.get("explanation"):
            result["details"][i]["explanation"] = str(data["explanation"])[:MAX_EXPLANATION_LEN].strip()
    return result
