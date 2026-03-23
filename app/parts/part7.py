"""Part 7: Multiple matching — 4–6 sections, 10 statements."""
import json
import logging
import random
import re

from flask import session

from app.ai import chat_create, ai_available
from app.ai.prompts import get_task_prompt_part7
from app.ai.explanations import fetch_explanations_part7
from app.config import MAX_EXPLANATION_LEN
from app.db import _generic_get_or_create, get_part7_task_by_id, db_connection
from app.parts.topics import PART3_TOPICS
from app.utils import e as _e

logger = logging.getLogger("fce_trainer")


def _extract_json_object(text):
    """Extract first complete {...} from text, optionally inside markdown code block."""
    text = text.strip()
    # Strip markdown code block if present
    code_match = re.search(r"```(?:json)?\s*([\s\S]*?)```", text)
    if code_match:
        text = code_match.group(1).strip()
    # Find first { and then matching } by brace count
    start = text.find("{")
    if start == -1:
        return None
    depth = 0
    for i in range(start, len(text)):
        if text[i] == "{":
            depth += 1
        elif text[i] == "}":
            depth -= 1
            if depth == 0:
                return text[start : i + 1]
    return None


def _parse_json_relaxed(raw):
    """Try json.loads; on failure, fix common LLM issues and retry."""
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        pass
    # Remove trailing commas before ] or }
    fixed = re.sub(r",\s*([}\]])", r"\1", raw)
    try:
        return json.loads(fixed)
    except json.JSONDecodeError:
        return None


def generate_part7_with_openai(level="b2"):
    if not ai_available:
        return None
    topic = random.choice(PART3_TOPICS)
    from app.rag.helpers import get_rag_examples_text
    ref_examples = get_rag_examples_text(part=7, topic=topic)
    prompt = get_task_prompt_part7(topic, level=level, ref_examples=ref_examples)
    try:
        comp = chat_create([{"role": "user", "content": prompt}], temperature=0.7)
        content = (comp.choices[0].message.content or "").strip()
        raw = _extract_json_object(content)
        if not raw:
            return None
        data = _parse_json_relaxed(raw)
        if not data:
            return None
        sections = data.get("sections")
        questions = data.get("questions")
        if not isinstance(sections, list) or len(sections) < 4 or len(sections) > 6:
            logger.warning("Part 7 generation: invalid section count %s", len(sections) if isinstance(sections, list) else type(sections))
            return None
        if not isinstance(questions, list) or len(questions) != 10:
            logger.warning("Part 7 generation: expected 10 questions, got %s", len(questions) if isinstance(questions, list) else type(questions))
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
            logger.warning("Part 7 generation: word count %d out of range 550-750", total_words)
            return None
        questions_clean = []
        for q in questions:
            text = (q.get("text") or "").strip()
            correct = (q.get("correct") or "").strip().upper()
            if not text or correct not in section_ids:
                logger.warning("Part 7 generation: invalid question (text=%r, correct=%r, valid_ids=%s)", text[:50] if text else '', correct, section_ids)
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
    return _generic_get_or_create(7, generate_part7_with_openai, exclude_task_id, openai_available=ai_available)


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
