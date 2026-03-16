"""Part 5: Reading — long text + 6 multiple-choice questions."""
import json
import logging
import random
import re

from flask import session

from app.ai import chat_create, ai_available
from app.ai.prompts import get_task_prompt_part5
from app.ai.explanations import fetch_explanations_part5
from app.config import LETTERS, MAX_EXPLANATION_LEN
from app.db import _generic_get_or_create, get_part5_task_by_id, db_connection
from app.parts.topics import PART3_TOPICS
from app.utils import e as _e, extract_json_object, validate_part5_data

logger = logging.getLogger("fce_trainer")


def generate_part5_with_openai():
    if not ai_available:
        return None
    topic = random.choice(PART3_TOPICS)
    prompt = get_task_prompt_part5(topic)
    try:
        comp = chat_create([{"role": "user", "content": prompt}], temperature=0.7)
        content = (comp.choices[0].message.content or "").strip()
        data = extract_json_object(content)
        if not data:
            return None
        validated = validate_part5_data(data)
        if not validated:
            return None
        with db_connection() as conn:
            cur = conn.execute(
                "INSERT INTO part5_tasks (title, text, questions_json, source) VALUES (?, ?, ?, ?)",
                (validated["title"], validated["text"], json.dumps(validated["questions"]), "openai"),
            )
            tid = cur.lastrowid
            conn.commit()
        return get_part5_task_by_id(tid)
    except Exception:
        logger.exception("OpenAI Part 5 error")
        return None


def get_or_create_part5_item(exclude_task_id=None):
    return _generic_get_or_create(5, generate_part5_with_openai, exclude_task_id, openai_available=ai_available)


def build_part5_text(item):
    if not item:
        return ""
    return f'<h3>{_e(item.get("title"))}</h3>{item.get("text", "")}'


def build_part5_html(item, check_result=None):
    if not item or not item.get("questions"):
        return "<p>No data.</p>"
    out = []
    for i, q in enumerate(item["questions"]):
        detail = None
        if check_result and check_result.get("details") and i < len(check_result["details"]):
            detail = check_result["details"][i]
        cls = " result-correct" if detail and detail.get("correct") else (" result-wrong" if detail else "")
        selected_val = detail.get("user_val") if detail is not None else None
        opts = "".join(
            f'<label class="part5-option">'
            f'<input type="radio" name="p5_{i}" value="{j}"{" checked" if selected_val == j else ""}'
            f' aria-label="Question {i+1} option {LETTERS[j]}" /> '
            f'<span class="part5-option-letter">{LETTERS[j]}</span>) {_e(opt)}</label>'
            for j, opt in enumerate(q.get("options", []))
        )
        correct_hint = ""
        explanation_html = ""
        if detail and not detail.get("correct"):
            correct_idx = q.get("correct", 0)
            correct_letter = LETTERS[correct_idx] if correct_idx < len(LETTERS) else "?"
            correct_text = q.get("options", [])[correct_idx] if correct_idx < len(q.get("options", [])) else ""
            correct_hint = f'<p class="correct-answer-hint">Correct: {correct_letter}) {_e(correct_text)}</p>'
        if detail:
            exp = detail.get("explanation")
            if exp:
                explanation_html = f'<p class="answer-explanation">{_e(exp)}</p>'
        out.append(
            f'<div class="question-block{cls}"><p>{i + 1}. {_e(q.get("q"))}</p>'
            f'<div class="part5-choices"><span class="part5-choose-label">Choose</span><div class="part5-options">{opts}</div></div>'
            f'{correct_hint}{explanation_html}</div>'
        )
    return "".join(out)


def check_part5(data, form):
    task_id = session.get("part5_task_id")
    item = get_part5_task_by_id(task_id) if task_id else None
    if not item or not item.get("questions"):
        return None
    details = []
    score = 0
    for i, q in enumerate(item["questions"]):
        try:
            user_int = int(form.get(f"p5_{i}"))
        except (TypeError, ValueError):
            user_int = -1
        correct_idx = q["correct"]
        correct = user_int == correct_idx
        if correct:
            score += 1
        details.append({"correct": correct, "user_val": user_int})
    result = {"part": 5, "score": score, "total": len(item["questions"]), "details": details}
    explanations = fetch_explanations_part5(item, details)
    for i, exp in enumerate(explanations):
        if i < len(result["details"]) and exp:
            result["details"][i]["explanation"] = str(exp)[:MAX_EXPLANATION_LEN].strip()
    return result
