"""Part 7: Multiple matching — 4–6 sections, 10 statements."""
import json
import logging
import random
import re

from flask import session

from app.ai import openai_chat_create, openai_client
from app.ai.explanations import fetch_explanations_part7
from app.config import MAX_EXPLANATION_LEN
from app.db import _generic_get_or_create, get_part7_task_by_id, db_connection
from app.parts.topics import PART3_TOPICS
from app.utils import e as _e

logger = logging.getLogger("fce_trainer")


def generate_part7_with_openai():
    if not openai_client:
        return None
    topic = random.choice(PART3_TOPICS)
    prompt = f"""You are an FCE (B2 First) Reading exam expert. Generate exactly ONE Part 7 (Multiple matching) task.

The text MUST be about this topic: "{topic}". Use a specific angle to make the text engaging and varied.

Part 7 consists of:
- Either ONE long text divided into 4-6 sections (labeled A, B, C, D, and optionally E, F) OR 4-5 short separate texts. Total length 600-700 words (B2 level).
- 10 statements that the candidate must match to the correct section. Each correct match = 1 mark.

QUALITY REQUIREMENTS:
- Use paraphrasing throughout: do NOT copy phrases from the text into statements. Rephrase ideas.
- Each section should be matched by at least one question. Distribute matches across sections.
- Vary difficulty: include some straightforward matches and some that require careful inference.
- Each statement must unambiguously match exactly one section.

Return ONLY a valid JSON object with these exact keys:
- "sections": an array of 4 to 6 objects. Each object has "id" (letter "A", "B", "C", "D", "E", or "F"), "title" (short section title), "text" (the section body text). The combined word count of all section "text" must be between 600 and 700 words.
- "questions": an array of exactly 10 objects. Each has "text" (the statement to match, one sentence) and "correct" (the section id, e.g. "A", "B").

No other text or markdown."""
    try:
        comp = openai_chat_create([{"role": "user", "content": prompt}], temperature=0.7)
        content = (comp.choices[0].message.content or "").strip()
        m = re.search(r"\{[\s\S]*\}", content)
        if not m:
            return None
        data = json.loads(m.group(0))
        sections = data.get("sections")
        questions = data.get("questions")
        if not isinstance(sections, list) or len(sections) < 4 or len(sections) > 6:
            return None
        if not isinstance(questions, list) or len(questions) != 10:
            return None
        section_ids = [s.get("id", "").strip().upper() for s in sections]
        sections_clean = []
        for s in sections:
            sections_clean.append({
                "id": (s.get("id") or "").strip().upper(),
                "title": (s.get("title") or "").strip(),
                "text": (s.get("text") or "").strip(),
            })
        total_words = sum(len(sec["text"].split()) for sec in sections_clean)
        if total_words < 550 or total_words > 750:
            return None
        questions_clean = []
        for q in questions:
            text = (q.get("text") or "").strip()
            correct = (q.get("correct") or "").strip().upper()
            if not text or correct not in section_ids:
                return None
            questions_clean.append({"text": text, "correct": correct})
        with db_connection() as conn:
            cur = conn.execute(
                "INSERT INTO part7_tasks (sections_json, questions_json, source) VALUES (?, ?, ?)",
                (json.dumps(sections_clean), json.dumps(questions_clean), "openai"),
            )
            tid = cur.lastrowid
            conn.commit()
        return get_part7_task_by_id(tid)
    except Exception:
        logger.exception("OpenAI Part 7 error")
        return None


def get_or_create_part7_item(exclude_task_id=None):
    return _generic_get_or_create(7, generate_part7_with_openai, exclude_task_id, openai_available=openai_client is not None)


def build_part7_text(item):
    if not item:
        return "<p>No data.</p>"
    sections = item.get("sections", [])
    out = ['<div class="part7-text-col">']
    for sec in sections:
        out.append(f'<div class="part7-section"><h4>{_e(sec.get("id"))}: {_e(sec.get("title"))}</h4><p>{_e(sec.get("text"))}</p></div>')
    out.append("</div>")
    return "".join(out)


def build_part7_questions(item, check_result=None):
    if not item:
        return "<p>No data.</p>"
    sections = item.get("sections", [])
    questions = item.get("questions", [])
    ids = [s["id"] for s in sections]
    out = ['<div class="part7-questions"><div class="part7-sentences">']
    for i, q in enumerate(questions):
        detail = None
        selected_val = None
        if check_result and check_result.get("details") and i < len(check_result["details"]):
            detail = check_result["details"][i]
            selected_val = detail.get("user_val")
        dash_checked = " checked" if (selected_val is None or selected_val == "") else ""
        opts = '<label class="part7-letter"><input type="radio" name="p7_{}" value=""{} aria-label="Question {} no answer"><span>—</span></label>'.format(i, dash_checked, i + 1)
        opts += "".join(
            f'<label class="part7-letter"><input type="radio" name="p7_{i}" value="{_e(sid)}"{" checked" if selected_val == sid else ""}'
            f' aria-label="Question {i+1} section {_e(sid)}"><span>{_e(sid)}</span></label>'
            for sid in ids
        )
        cls = ""
        if detail:
            cls = " result-correct" if detail.get("correct") else " result-wrong"
        correct_hint = ""
        explanation_html = ""
        if detail and not detail.get("correct"):
            correct_section = q.get("correct", "?")
            correct_hint = f'<p class="correct-answer-hint">Correct: {_e(correct_section)}</p>'
        if detail:
            exp = detail.get("explanation")
            if exp:
                explanation_html = f'<p class="answer-explanation">{_e(exp)}</p>'
        out.append(
            f'<div class="question-block{cls}"><p>{i + 1}. {_e(q.get("text"))}</p>'
            f'<div class="part7-choose"><span class="part7-choose-label">Choose</span><div class="part7-letters">{opts}</div></div>'
            f'{correct_hint}{explanation_html}</div>'
        )
    out.append("</div></div>")
    return "".join(out)


def check_part7(data, form):
    task_id = session.get("part7_task_id")
    if not task_id:
        _, task_id = get_or_create_part7_item()
        if task_id:
            session["part7_task_id"] = task_id
    item = get_part7_task_by_id(task_id) if task_id else None
    if not item or not item.get("questions"):
        return None
    details = []
    score = 0
    for i, q in enumerate(item["questions"]):
        user_val = (form.get(f"p7_{i}") or "").strip()
        correct = user_val == q.get("correct")
        if correct:
            score += 1
        details.append({"correct": correct, "user_val": user_val})
    result = {"part": 7, "score": score, "total": len(item["questions"]), "details": details}
    explanations = fetch_explanations_part7(item, details)
    for i, exp in enumerate(explanations):
        if i < len(result["details"]) and exp:
            result["details"][i]["explanation"] = str(exp)[:MAX_EXPLANATION_LEN].strip()
    return result
