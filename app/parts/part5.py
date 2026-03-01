"""Part 5: Reading — long text + 6 multiple-choice questions."""
import json
import logging
import random
import re

from flask import session

from app.ai import openai_chat_create, openai_client
from app.ai.explanations import fetch_explanations_part5
from app.config import LETTERS, MAX_EXPLANATION_LEN
from app.db import _generic_get_or_create, get_part5_task_by_id, db_connection
from app.parts.topics import PART3_TOPICS
from app.utils import e as _e

logger = logging.getLogger("fce_trainer")


def generate_part5_with_openai():
    if not openai_client:
        return None
    topic = random.choice(PART3_TOPICS)
    prompt = f"""You are an FCE (B2 First) Reading and Use of English exam expert. Generate exactly ONE Part 5 task.

The text MUST be clearly about this topic: "{topic}". Write a single continuous text (e.g. magazine article, report, or extract from a modern novel) that is obviously on this theme. Use a specific angle or situation so the text feels fresh and varied.

Part 5 consists of:
1. A single continuous text. Length: between 550 and 650 words. Upper-Intermediate (B2) level. The text should test understanding of the writer's opinion, attitude, purpose, tone, and implied meaning—not just surface facts.
2. Exactly 6 multiple-choice questions. Each question has four options (A, B, C, D). Questions must follow the chronological order of the text: question 1 relates to the beginning, question 6 may relate to the end or the text as a whole. Each correct answer is worth 2 marks.

QUESTION QUALITY REQUIREMENTS:
- Mix question types: include at least one of each: (a) detail/fact comprehension, (b) writer's opinion/attitude, (c) implied meaning/inference, (d) purpose of a phrase or paragraph.
- Distractors must be plausible: each wrong option should seem reasonable at first glance but be clearly wrong when the relevant passage is read carefully. Avoid obviously absurd options.
- Vary the position of the correct answer: do NOT always put it in the same slot. Distribute correct answers across A, B, C, D roughly evenly.
- Questions should use paraphrase, not copy text verbatim.

Return ONLY a valid JSON object with these exact keys:
- "title": a short title for the text (e.g. "The benefits of learning music")
- "text": the full text. Use <p>...</p> for paragraphs. No other HTML. The text must be 550-650 words.
- "questions": an array of exactly 6 objects. Each object has: "q" (the question text), "options" (array of exactly 4 strings, in order A then B then C then D), "correct" (integer 0, 1, 2, or 3—the index of the correct option).

Example shape:
{{"title": "...", "text": "<p>...</p><p>...</p>", "questions": [{{"q": "...", "options": ["A text", "B text", "C text", "D text"], "correct": 1}}, ...]}}

No other text or markdown."""
    try:
        comp = openai_chat_create([{"role": "user", "content": prompt}], temperature=0.7)
        content = (comp.choices[0].message.content or "").strip()
        m = re.search(r"\{[\s\S]*\}", content)
        if not m:
            return None
        data = json.loads(m.group(0))
        title = (data.get("title") or "").strip()
        text = (data.get("text") or "").strip()
        questions = data.get("questions")
        if not title or not text or not isinstance(questions, list) or len(questions) != 6:
            return None
        wc = len(text.split())
        if wc < 400 or wc > 750:
            return None
        normalized = []
        for i, qq in enumerate(questions):
            q = (qq.get("q") or "").strip()
            opts = qq.get("options") or []
            if len(opts) != 4:
                return None
            correct = int(qq.get("correct", 0))
            if correct not in (0, 1, 2, 3):
                correct = 0
            normalized.append({"q": q, "options": [str(o).strip() for o in opts], "correct": correct})
        with db_connection() as conn:
            cur = conn.execute(
                "INSERT INTO part5_tasks (title, text, questions_json, source) VALUES (?, ?, ?, ?)",
                (title, text, json.dumps(normalized), "openai"),
            )
            tid = cur.lastrowid
            conn.commit()
        return get_part5_task_by_id(tid)
    except Exception:
        logger.exception("OpenAI Part 5 error")
        return None


def get_or_create_part5_item(exclude_task_id=None):
    return _generic_get_or_create(5, generate_part5_with_openai, exclude_task_id, openai_available=openai_client is not None)


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
