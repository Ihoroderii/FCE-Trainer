"""Part 2: Open cloze — 8 gaps, one word each."""
import json
import logging
import random
import re

from flask import session

from app.ai import openai_chat_create, openai_client
from app.ai.explanations import fetch_explanations_part2
from app.config import MAX_EXPLANATION_LEN
from app.db import _generic_get_or_create, get_part2_task_by_id, db_connection
from app.utils import e as _e, answers_match

logger = logging.getLogger("fce_trainer")

PART2_TOPICS = [
    "travel and holidays",
    "education and learning",
    "technology and the internet",
    "health and fitness",
    "the environment and climate",
    "arts and music",
    "sport and competition",
    "work and careers",
    "family and relationships",
    "food and cooking",
    "science and discovery",
    "history and culture",
    "shopping and consumerism",
    "nature and wildlife",
    "entertainment and media",
    "transport and cities",
    "hobbies and free time",
    "news and current events",
]


def generate_part2_with_openai(level="b2"):
    if not openai_client:
        return None
    topic = random.choice(PART2_TOPICS)
    level = (level or "b2").strip().lower()
    if level != "b2plus":
        level = "b2"
    if level == "b2plus":
        level_instruction = """- The text must be at B2+ level: slightly more complex grammar and vocabulary than standard B2. Use a mix of sentence structures (e.g. participle clauses, inversion, or more formal linkers). Include at least one or two gaps that could require phrasal verbs, complex prepositions, or linking words (e.g. however, although, despite, whereas). Length about 180-220 words."""
    else:
        level_instruction = """- A short text (about 150-200 words) at B2 level. Standard FCE open-cloze difficulty."""
    prompt = f"""You are an FCE (B2 First) Use of English exam expert. Generate exactly ONE Part 2 (Open cloze) task.

The text must be about this topic: {topic}. Use a different angle or situation (e.g. a personal story, a news-style piece, advice, or a description). Do NOT write about working from home or remote work unless the chosen topic is "work and careers" and you pick that angle.

Part 2 consists of:
{level_instruction}
- The text must contain exactly 8 gaps marked (1)_____, (2)_____, (3)_____, (4)_____, (5)_____, (6)_____, (7)_____, (8)_____ in order. Each gap needs ONE word (articles, prepositions, auxiliaries, pronouns, conjunctions, phrasal verb particles, linkers, etc.).
- The 8 correct answers (one word per gap).

Return ONLY a valid JSON object with these exact keys:
- "text": the full text with the exact placeholders (1)_____, (2)_____, ... (8)_____ where the gaps are. No other placeholder format.
- "answers": an array of exactly 8 strings: the correct word for gap 1, then gap 2, ... gap 8. Use lowercase unless the word must be capitalised (e.g. start of sentence).

No other text or markdown."""
    try:
        comp = openai_chat_create([{"role": "user", "content": prompt}], temperature=0.7)
        content = (comp.choices[0].message.content or "").strip()
        m = re.search(r"\{[\s\S]*\}", content)
        if not m:
            return None
        data = json.loads(m.group(0))
        text = (data.get("text") or "").strip()
        answers = data.get("answers")
        if not text or not isinstance(answers, list) or len(answers) != 8:
            return None
        for i in range(1, 9):
            if f"({i})_____" not in text:
                return None
        answers_clean = [str(a).strip() for a in answers]
        with db_connection() as conn:
            cur = conn.execute(
                "INSERT INTO part2_tasks (text, answers_json, source) VALUES (?, ?, ?)",
                (text, json.dumps(answers_clean), "openai"),
            )
            tid = cur.lastrowid
            conn.commit()
        return get_part2_task_by_id(tid)
    except Exception:
        logger.exception("OpenAI Part 2 error")
        return None


def get_or_create_part2_item(exclude_task_id=None):
    return _generic_get_or_create(2, generate_part2_with_openai, exclude_task_id, openai_available=openai_client is not None)


def build_part2_html(item, check_result=None):
    if not item or not item.get("answers"):
        return "<p>No data.</p>"
    parts = re.split(r"(\(\d+\)_____)", item["text"])
    gap_i = 0
    out = []
    for p in parts:
        if re.match(r"^\(\d+\)_____$", p) and gap_i < len(item["answers"]):
            val = ""
            if check_result and check_result.get("details") and gap_i < len(check_result["details"]):
                val = check_result["details"][gap_i].get("user_val", "")
            cls = ""
            if check_result and check_result.get("details") and gap_i < len(check_result["details"]):
                d = check_result["details"][gap_i]
                cls = " result-correct" if d.get("correct") else " result-wrong"
            out.append(f'<span class="gap-inline{cls}"><input type="text" name="p2_{gap_i}" value="{_e(val)}" placeholder="{gap_i + 1}" aria-label="Gap {gap_i + 1}" /></span>')
            gap_i += 1
        else:
            out.append(_e(p))
    html = "".join(out)
    if check_result and check_result.get("details"):
        expl_list = []
        for i, d in enumerate(check_result["details"]):
            if i >= len(item["answers"]):
                break
            correct = d.get("correct")
            expected = d.get("expected", "")
            exp = d.get("explanation", "")
            if not correct and expected:
                if exp:
                    expl_list.append(
                        f'<li class="part2-expl-item part2-expl-wrong">'
                        f'<strong>Gap {i + 1}:</strong> <span class="part2-expl-correct">Correct: <em>{_e(expected)}</em></span>. '
                        f'<span class="part2-expl-reason">{_e(exp)}</span></li>'
                    )
                else:
                    expl_list.append(
                        f'<li class="part2-expl-item part2-expl-wrong">'
                        f'<strong>Gap {i + 1}:</strong> <span class="part2-expl-correct">Correct: <em>{_e(expected)}</em></span>.</li>'
                    )
            elif exp:
                expl_list.append(f'<li class="part2-expl-item part2-expl-correct"><strong>Gap {i + 1}:</strong> <span class="part2-expl-reason">{_e(exp)}</span></li>')
        if expl_list:
            html += '<div class="explanations-block"><h4>Why this answer is correct / why it is wrong</h4><ol class="answer-explanations">' + "".join(expl_list) + "</ol></div>"
    return html


def check_part2(data, form):
    task_id = session.get("part2_task_id")
    if not task_id:
        _, task_id = get_or_create_part2_item()
        if task_id:
            session["part2_task_id"] = task_id
    item = get_part2_task_by_id(task_id) if task_id else None
    if not item or not item.get("answers"):
        return None
    details = []
    score = 0
    for i in range(len(item["answers"])):
        user_val = (form.get(f"p2_{i}") or "").strip()
        expected = item["answers"][i]
        correct = answers_match(user_val, expected)
        if correct:
            score += 1
        details.append({"correct": correct, "user_val": user_val, "expected": expected})
    result = {"part": 2, "score": score, "total": len(item["answers"]), "details": details}
    explanations = fetch_explanations_part2(item, details)
    for i, exp in enumerate(explanations):
        if i < len(result["details"]) and exp:
            result["details"][i]["explanation"] = (str(exp)[:MAX_EXPLANATION_LEN]).strip()
    return result
