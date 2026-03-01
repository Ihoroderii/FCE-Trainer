"""Part 1: Multiple-choice cloze — 8 gaps, A/B/C/D."""
import json
import logging
import random
import re

from flask import session

from app.ai import openai_chat_create, openai_client
from app.ai.explanations import fetch_explanations_part1
from app.config import LETTERS
from app.db import (
    db_connection,
    get_part1_task_by_id,
    _generic_get_or_create,
    record_show_for_part,
)
from app.parts.topics import PART1_TOPICS
from app.utils import e as _e

logger = logging.getLogger("fce_trainer")


def generate_part1_with_openai(level="b2"):
    if not openai_client:
        return None
    level = (level or "b2").strip().lower()
    if level != "b2plus":
        level = "b2"
    topic = random.choice(PART1_TOPICS)
    if level == "b2plus":
        level_instruction = "The text must be at B2+ level: slightly more complex vocabulary and grammar (e.g. less common collocations, more formal linkers, or subtle meaning differences between options). Standard FCE Part 1 length (4-6 sentences, 8 gaps)."
    else:
        level_instruction = "The text must be at B2 level: clear vocabulary and grammar appropriate for FCE. Standard Part 1 length (4-6 sentences, 8 gaps)."
    prompt = f"""You are an FCE (B2 First) English exam expert. Generate exactly ONE "multiple-choice cloze" task.

The text MUST be clearly about this topic: "{topic}". Write a short, coherent paragraph that is obviously on this theme (not work or offices unless the topic says so). Use a specific angle or situation so the text feels fresh and varied.

{level_instruction}

The task must have:
- text: A short paragraph with exactly 8 gaps. Each gap must be written as (1)_____, (2)_____, ... (8)_____ in order. The gaps should test vocabulary/grammar in context.
- gaps: An array of exactly 8 objects. Each object has: "options" (array of exactly 4 words/phrases that could fit the gap), "correct" (integer 0, 1, 2, or 3 - the index of the correct option in "options").

Return ONLY a valid JSON object with keys "text" and "gaps". No other text. Example shape:
{{"text": "Some text with (1)_____ and (2)_____ ...", "gaps": [{{"options": ["a","b","c","d"], "correct": 0}}, ...]}}"""
    try:
        comp = openai_chat_create([{"role": "user", "content": prompt}], temperature=0.8)
        content = (comp.choices[0].message.content or "").strip()
        m = re.search(r"\{[\s\S]*\}", content)
        if not m:
            return None
        data = json.loads(m.group(0))
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
        with db_connection() as conn:
            cur = conn.execute(
                "INSERT INTO part1_tasks (text, gaps_json, source) VALUES (?, ?, ?)",
                (text, json.dumps(normalized), "openai"),
            )
            tid = cur.lastrowid
            conn.commit()
        return get_part1_task_by_id(tid)
    except Exception:
        logger.exception("OpenAI Part 1 error")
        return None


def get_or_create_part1_task():
    item, _ = _generic_get_or_create(1, generate_part1_with_openai, openai_available=openai_client is not None)
    return item


def build_part1_html(item, check_result=None):
    if not item or not item.get("gaps"):
        return "<p>No data.</p>"
    parts = re.split(r"(\(\d+\)_____)", item["text"])
    gap_i = 0
    out = []
    for p in parts:
        if re.match(r"^\(\d+\)_____$", p) and gap_i < len(item["gaps"]):
            g = item["gaps"][gap_i]
            opts = "".join(
                f'<option value="{j}"{" selected" if check_result and check_result.get("details") and check_result["details"][gap_i].get("user_val") == j else ""}>'
                f"{LETTERS[j]}) {_e(opt)}</option>"
                for j, opt in enumerate(g["options"])
            )
            cls = ""
            if check_result and check_result.get("details") and gap_i < len(check_result["details"]):
                d = check_result["details"][gap_i]
                cls = " result-correct" if d.get("correct") else " result-wrong"
            out.append(f'<span class="gap-inline{cls}"><select name="p1_{gap_i}" aria-label="Gap {gap_i + 1}"><option value="">—</option>{opts}</select></span>')
            gap_i += 1
        else:
            out.append(_e(p))
    html = "".join(out)
    if check_result and check_result.get("details"):
        expl_list = []
        for i, d in enumerate(check_result["details"]):
            if i >= len(item["gaps"]):
                break
            correct = d.get("correct")
            correct_idx = item["gaps"][i].get("correct", 0)
            correct_letter = LETTERS[correct_idx] if correct_idx < len(LETTERS) else "?"
            expected_word = d.get("expected") or (item["gaps"][i].get("options") or [""])[correct_idx]
            exp = d.get("explanation", "")
            if not correct:
                if exp:
                    expl_list.append(
                        f'<li class="part2-expl-item part2-expl-wrong">'
                        f'<strong>Gap {i + 1}:</strong> <span class="part2-expl-correct">Correct: <em>{correct_letter}) {_e(expected_word)}</em></span>. '
                        f'<span class="part2-expl-reason">{_e(exp)}</span></li>'
                    )
                else:
                    expl_list.append(
                        f'<li class="part2-expl-item part2-expl-wrong">'
                        f'<strong>Gap {i + 1}:</strong> <span class="part2-expl-correct">Correct: <em>{correct_letter}) {_e(expected_word)}</em></span>.</li>'
                    )
            elif exp:
                expl_list.append(f'<li class="part2-expl-item part2-expl-correct"><strong>Gap {i + 1}:</strong> <span class="part2-expl-reason">{_e(exp)}</span></li>')
        if expl_list:
            html += '<div class="explanations-block"><h4>Why this answer is correct / why it is wrong</h4><ol class="answer-explanations">' + "".join(expl_list) + "</ol></div>"
    return html


def check_part1(data, form):
    task_id = session.get("part1_task_id")
    item = get_part1_task_by_id(task_id) if task_id else session.get("part1_task")
    if not item or not item.get("gaps"):
        return None
    details = []
    score = 0
    for i in range(8):
        user_val = form.get(f"p1_{i}")
        try:
            user_int = int(user_val)
        except (TypeError, ValueError):
            user_int = -1
        correct_idx = item["gaps"][i]["correct"]
        correct = user_int == correct_idx
        if correct:
            score += 1
        details.append({"correct": correct, "user_val": user_int, "expected": item["gaps"][i]["options"][correct_idx]})
    result = {"part": 1, "score": score, "total": 8, "details": details}
    explanations = fetch_explanations_part1(item, details)
    for i, exp in enumerate(explanations):
        if i < len(result["details"]):
            result["details"][i]["explanation"] = exp
    return result
