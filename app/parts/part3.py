"""Part 3: Word formation — 8 gaps, stem words in CAPITALS."""
import json
import logging
import random
import re

from flask import session

from app.ai import chat_create, ai_available
from app.ai.prompts import get_task_prompt_part3
from app.ai.explanations import fetch_explanations_part3
from app.config import MAX_EXPLANATION_LEN, MAX_WORD_FAMILY_LEN
from app.db import _generic_get_or_create, get_part3_task_by_id, db_connection
from app.parts.topics import PART3_TOPICS
from app.utils import e as _e, answers_match, extract_json_object, validate_part3_data

logger = logging.getLogger("fce_trainer")


def generate_part3_with_openai(level="b2"):
    if not ai_available:
        return None
    topic = random.choice(PART3_TOPICS)
    prompt = get_task_prompt_part3(topic, level)
    max_unchanged = 1
    for attempt in range(3):
        try:
            comp = chat_create([{"role": "user", "content": prompt}], temperature=0.7)
            content = (comp.choices[0].message.content or "").strip()
            data = extract_json_object(content)
            if not data:
                continue
            validated = validate_part3_data(data)
            if not validated:
                continue
            unchanged_count = sum(
                1 for i in range(8)
                if validated["answers"][i].upper() == validated["stems"][i]
            )
            if unchanged_count > max_unchanged:
                continue
            with db_connection() as conn:
                cur = conn.execute(
                    "INSERT INTO part3_tasks (items_json, source) VALUES (?, ?)",
                    (json.dumps(validated), "openai"),
                )
                tid = cur.lastrowid
                conn.commit()
            return get_part3_task_by_id(tid)
        except Exception:
            if attempt == 2:
                logger.exception("OpenAI Part 3 error")
            continue
    return None


def get_or_create_part3_item(exclude_task_id=None):
    return _generic_get_or_create(3, generate_part3_with_openai, exclude_task_id, openai_available=ai_available)


def build_part3_html(task_or_items, check_result=None):
    if not task_or_items:
        return "<p>No data.</p>"
    if isinstance(task_or_items, dict) and "text" in task_or_items:
        text = (task_or_items.get("text") or "").strip()
        stems = task_or_items.get("stems") or []
        answers = task_or_items.get("answers") or []
        if not text or len(answers) < 8 or len(stems) < 8:
            return "<p>No data.</p>"
        parts = re.split(r"\((?:1|2|3|4|5|6|7|8)\)_____", text)
        if len(parts) != 9:
            return "<p>Invalid Part 3 text format.</p>"
        for i in range(1, 9):
            stem = (stems[i - 1] if i - 1 < len(stems) else "").strip()
            if stem:
                parts[i] = re.sub(r"\s+" + re.escape(stem) + r"\s*", " ", parts[i], count=1)
                parts[i] = parts[i].strip()
                if parts[i] and not parts[i].startswith(" "):
                    parts[i] = " " + parts[i]
        out = []
        for i in range(8):
            val = ""
            cls = ""
            if check_result and check_result.get("details") and i < len(check_result["details"]):
                val = check_result["details"][i].get("user_val", "")
                cls = " result-correct" if check_result["details"][i].get("correct") else " result-wrong"
            out.append(_e(parts[i]))
            out.append(f'<span class="gap-inline part3-gap{cls}"><input type="text" name="p3_{i}" value="{_e(val)}" placeholder="{i + 1}" autocomplete="off" aria-label="Gap {i + 1}" /></span>')
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
                word_family = d.get("word_family", "")
                cls = " part2-expl-correct" if correct else " part2-expl-wrong"
                body = ""
                if not correct and expected:
                    body = f'<span class="part2-expl-correct">Correct: <em>{_e(expected)}</em></span>. <span class="part2-expl-reason">{_e(exp)}</span>'
                elif correct and exp:
                    body = f'<span class="part2-expl-reason">{_e(exp)}</span>'
                elif correct:
                    body = "Correct."
                else:
                    body = f'<span class="part2-expl-correct">Correct: <em>{_e(expected)}</em></span>.'
                if word_family:
                    body += f'<div class="part3-word-family"><strong>Word family:</strong> {_e(word_family)}</div>'
                expl_list.append(f'<li class="part2-expl-item{cls}"><strong>Gap {i + 1}:</strong> {body}</li>')
            if expl_list:
                left_html += '<div class="explanations-block"><h4>Why this answer is correct / why it is wrong</h4><ol class="answer-explanations">' + "".join(expl_list) + "</ol></div>"
        right_html = "".join(
            f'<div class="part3-stem-row"><span class="part3-stem-num">{i + 1}.</span> <strong class="part3-stem-word">{_e((stems[i] if i < len(stems) else "").strip())}</strong></div>'
            for i in range(8)
        )
        return (
            '<div class="part3-layout" id="part3-layout">'
            '<div class="part3-text-col reading-text exercise cloze-text">' + left_html + '</div>'
            '<div class="part3-resizer split-resizer" id="part3-resizer" title="Drag to resize"></div>'
            '<div class="part3-stems-col exercise">' + right_html + '</div>'
            '</div>'
        )
    items = task_or_items if isinstance(task_or_items, list) else task_or_items.get("items") or []
    if not items or len(items) < 8:
        return "<p>No data.</p>"
    out = []
    stems_right = []
    for i, it in enumerate(items):
        sent = (it.get("sentence") or "").strip()
        key = (it.get("key") or "").strip()
        val = ""
        cls = ""
        if check_result and check_result.get("details") and i < len(check_result["details"]):
            val = check_result["details"][i].get("user_val", "")
            cls = " result-correct" if check_result["details"][i].get("correct") else " result-wrong"
        sent_without_stem = re.sub(r"\s+" + re.escape(key) + r"\s*$", "", sent).strip() if key else sent
        segs_clean = sent_without_stem.split("_____", 1)
        if len(segs_clean) == 2:
            out.append(f'<span class="part3-sentence">{_e(segs_clean[0])}<span class="gap-inline part3-gap{cls}"><input type="text" name="p3_{i}" value="{_e(val)}" placeholder="{i + 1}" autocomplete="off" aria-label="Gap {i + 1}" /></span>{_e(segs_clean[1])}</span> ')
        else:
            out.append(f'<span class="gap-inline part3-gap{cls}"><input type="text" name="p3_{i}" value="{_e(val)}" placeholder="{i + 1}" autocomplete="off" aria-label="Gap {i + 1}" /></span> ')
        if check_result and check_result.get("details") and i < len(check_result["details"]) and not check_result["details"][i].get("correct"):
            out.append(f'<span class="correct-answer-hint">(Correct: {_e(check_result["details"][i].get("expected"))})</span> ')
        stems_right.append(f'<div class="part3-stem-row"><span class="part3-stem-num">{i + 1}.</span> <strong class="part3-stem-word">{_e(key)}</strong></div>')
    left_html = "".join(out)
    if check_result and check_result.get("details"):
        expl_list = []
        for i, d in enumerate(check_result["details"]):
            if i >= 8:
                break
            expected = d.get("expected", items[i].get("answer", "") if i < len(items) else "")
            correct = d.get("correct")
            exp = d.get("explanation", "")
            word_family = d.get("word_family", "")
            li_cls = " part2-expl-correct" if correct else " part2-expl-wrong"
            body = ""
            if not correct and expected:
                body = f'<span class="part2-expl-correct">Correct: <em>{_e(expected)}</em></span>. <span class="part2-expl-reason">{_e(exp)}</span>'
            elif correct and exp:
                body = f'<span class="part2-expl-reason">{_e(exp)}</span>'
            elif correct:
                body = "Correct."
            else:
                body = f'<span class="part2-expl-correct">Correct: <em>{_e(expected)}</em></span>.'
            if word_family:
                body += f'<div class="part3-word-family"><strong>Word family:</strong> {_e(word_family)}</div>'
            expl_list.append(f'<li class="part2-expl-item{li_cls}"><strong>Gap {i + 1}:</strong> {body}</li>')
        if expl_list:
            left_html += '<div class="explanations-block"><h4>Why this answer is correct / why it is wrong</h4><ol class="answer-explanations">' + "".join(expl_list) + "</ol></div>"
    right_html = "".join(stems_right)
    left_html = "".join(out)
    return (
        '<div class="part3-layout" id="part3-layout">'
        '<div class="part3-text-col reading-text exercise cloze-text">' + left_html + '</div>'
        '<div class="part3-resizer split-resizer" id="part3-resizer" title="Drag to resize"></div>'
        '<div class="part3-stems-col exercise">' + right_html + '</div>'
        '</div>'
    )


def check_part3(data, form):
    task_id = session.get("part3_task_id")
    if not task_id:
        _, task_id = get_or_create_part3_item()
        if task_id:
            session["part3_task_id"] = task_id
    task = get_part3_task_by_id(task_id) if task_id else None
    if not task:
        return None
    if "answers" in task:
        answers = task["answers"]
    else:
        items = task.get("items") or []
        if not items:
            return None
        answers = [items[i].get("answer", "") for i in range(min(8, len(items)))]
    if len(answers) < 8:
        return None
    details = []
    score = 0
    for i in range(8):
        user_val = (form.get(f"p3_{i}") or "").strip()
        expected = answers[i] if i < len(answers) else ""
        correct = answers_match(user_val, expected)
        if correct:
            score += 1
        details.append({"correct": correct, "user_val": user_val, "expected": expected})
    result = {"part": 3, "score": score, "total": 8, "details": details}
    explanations_data = fetch_explanations_part3(task, details)
    for i, data in enumerate(explanations_data):
        if i < len(result["details"]):
            if data.get("explanation"):
                result["details"][i]["explanation"] = str(data["explanation"])[:MAX_EXPLANATION_LEN].strip()
            if data.get("word_family"):
                result["details"][i]["word_family"] = str(data["word_family"])[:MAX_WORD_FAMILY_LEN].strip()
    return result
