"""Part 6: Gapped text — 6 gaps, 7 sentences A–G."""
import json
import logging
import random
import re

from flask import session

from app.ai import chat_create, ai_available
from app.ai.prompts import get_task_prompt_part6
from app.ai.explanations import fetch_explanations_part6
from app.config import MAX_EXPLANATION_LEN
from app.db import _generic_get_or_create, get_part6_task_by_id, db_connection
from app.parts.topics import PART6_TOPICS
from app.utils import e as _e

logger = logging.getLogger("fce_trainer")


def generate_part6_with_openai(level="b2"):
    if not ai_available:
        return None
    topic = random.choice(PART6_TOPICS)
    prompt = get_task_prompt_part6(topic, level=level)
    try:
        comp = chat_create([{"role": "user", "content": prompt}], temperature=0.7)
        content = (comp.choices[0].message.content or "").strip()
        m = re.search(r"\{[\s\S]*\}", content)
        if not m:
            return None
        data = json.loads(m.group(0))
        paragraphs = data.get("paragraphs")
        sentences = data.get("sentences")
        answers = data.get("answers")
        if not isinstance(paragraphs, list) or not isinstance(sentences, list) or len(sentences) != 7:
            return None
        if not isinstance(answers, list) or len(answers) != 6:
            return None
        # Count GAP markers embedded within paragraphs
        all_text = ' '.join(paragraphs)
        found_gaps = re.findall(r'GAP[1-6]', all_text)
        if len(found_gaps) != 6 or set(found_gaps) != {"GAP1", "GAP2", "GAP3", "GAP4", "GAP5", "GAP6"}:
            return None
        for a in answers:
            if a not in range(7):
                return None
        sentences_clean = [str(s).strip() for s in sentences]
        paragraphs_clean = [str(p).strip() for p in paragraphs]
        answers_clean = [int(a) for a in answers]
        with db_connection() as conn:
            cur = conn.execute(
                "INSERT INTO part6_tasks (paragraphs_json, sentences_json, answers_json, source) VALUES (?, ?, ?, ?)",
                (json.dumps(paragraphs_clean), json.dumps(sentences_clean), json.dumps(answers_clean), "openai"),
            )
            tid = cur.lastrowid
            conn.commit()
        return get_part6_task_by_id(tid)
    except Exception:
        logger.exception("OpenAI Part 6 error")
        return None


def get_or_create_part6_item(exclude_task_id=None):
    return _generic_get_or_create(6, generate_part6_with_openai, exclude_task_id, openai_available=ai_available)


def build_part6_text(item, check_result=None):
    if not item:
        return "<p>No data.</p>"
    letters_g = ["A", "B", "C", "D", "E", "F", "G"]
    sentences = item.get("sentences", [])
    answers = item.get("answers", [])
    out = []
    gap_i = 0
    gap_pattern = re.compile(r'(GAP[1-6])')
    for para in item.get("paragraphs", []):
        parts = gap_pattern.split(para)
        para_html = []
        for part in parts:
            if gap_pattern.fullmatch(part):
                user_val = None
                detail = None
                if check_result and check_result.get("details") and gap_i < len(check_result["details"]):
                    detail = check_result["details"][gap_i]
                    user_val = detail.get("user_val")
                cls = ""
                if detail:
                    cls = " result-correct" if detail.get("correct") else " result-wrong"
                try:
                    sel_idx = int(user_val) if user_val is not None else -1
                except (TypeError, ValueError):
                    sel_idx = -1
                letter = letters_g[sel_idx] if 0 <= sel_idx < len(letters_g) else "-"
                val_attr = str(sel_idx) if 0 <= sel_idx < len(letters_g) else ""
                correct_hint = ""
                explanation_html = ""
                if detail and not detail.get("correct"):
                    correct_idx = answers[gap_i] if gap_i < len(answers) else -1
                    correct_letter = letters_g[correct_idx] if 0 <= correct_idx < len(letters_g) else "?"
                    correct_sentence = sentences[correct_idx][:80] if 0 <= correct_idx < len(sentences) else ""
                    correct_hint = f'<span class="correct-answer-hint">Correct: {correct_letter}) {_e(correct_sentence)}...</span>'
                if detail:
                    exp = detail.get("explanation")
                    if exp:
                        explanation_html = f'<span class="answer-explanation">{_e(exp)}</span>'
                gap_num = gap_i + 1
                para_html.append(
                    f'<span class="part6-gap-drop part6-gap-inline{cls}" data-gap-index="{gap_i}" data-droppable="true">'
                    f'<span class="part6-gap-num">{gap_num}</span>'
                    f'<span class="part6-gap-label">{letter}</span>'
                    f'<span class="part6-gap-sentence"></span>'
                    f'<button type="button" class="part6-gap-clear" title="Clear gap" aria-label="Clear gap">x</button>'
                    f'<input type="hidden" name="p6_{gap_i}" value="{val_attr}" aria-label="Gap {gap_num}">'
                    f'{correct_hint}{explanation_html}'
                    f'</span>'
                )
                gap_i += 1
            else:
                text = part.strip()
                if text:
                    para_html.append(_e(text))
        if para_html:
            out.append(f'<p class="part6-para">{" ".join(para_html)}</p>')
    return '\n'.join(out)


def build_part6_questions(item):
    if not item:
        return ""
    letters_g = ["A", "B", "C", "D", "E", "F", "G"]
    sentences = item.get("sentences", [])
    out = ['<div class="part6-sentences"><p><strong>Drag a sentence into a gap:</strong></p><div class="part6-sentence-list">']
    for j, s in enumerate(sentences):
        out.append(
            f'<div class="part6-sentence-drag" draggable="true" data-sentence-index="{j}" role="button" tabindex="0">'
            f'<strong>{letters_g[j]}</strong>) {_e(s)}'
            f'</div>'
        )
    out.append("</div></div>")
    return "".join(out)


def check_part6(data, form):
    task_id = session.get("part6_task_id")
    item = get_part6_task_by_id(task_id) if task_id else None
    if not item or not item.get("answers"):
        return None
    answers = item["answers"]
    details = []
    score = 0
    for i in range(6):
        try:
            user_int = int(form.get(f"p6_{i}"))
        except (TypeError, ValueError):
            user_int = -1
        correct = user_int == answers[i]
        if correct:
            score += 1
        details.append({"correct": correct, "user_val": user_int})
    result = {"part": 6, "score": score, "total": 6, "details": details}
    explanations = fetch_explanations_part6(item, details)
    for i, exp in enumerate(explanations):
        if i < len(result["details"]) and exp:
            result["details"][i]["explanation"] = str(exp)[:MAX_EXPLANATION_LEN].strip()
    return result
