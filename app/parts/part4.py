"""Part 4: Key word transformation — 6 items from UOE DB or OpenAI."""
import difflib
import json
import logging
import re

from app.ai import openai_chat_create, openai_client
from app.ai.explanations import fetch_explanations_part4
from app.config import PART4_TASKS_PER_SET
from app.db import (
    db_connection,
    get_tasks_by_ids,
    get_recent_grammar_topics,
    pick_task_ids_from_db,
    record_shows,
    uoe_task_exists,
    _ensure_uoe_grammar_topic_column,
)
from app.utils import e as _e, norm, word_count, answers_match

logger = logging.getLogger("fce_trainer")


def _answer_uses_keyword(answer: str, keyword: str) -> bool:
    if not answer or not keyword:
        return False
    a = norm(answer)
    kw = keyword.strip().lower()
    return bool(re.search(r"\b" + re.escape(kw) + r"\b", a))


def _part4_answer_length_ok(answer: str) -> bool:
    return 3 <= word_count(answer) <= 5


def _part4_sentence2_same_as_sentence1(sentence1: str, sentence2: str, answer: str) -> bool:
    if not sentence1 or not sentence2 or "_____" not in sentence2:
        return False
    reconstructed = sentence2.replace("_____", (answer or "").strip()).strip()
    return norm(reconstructed) == norm(sentence1)


def _part4_similar_to_existing(sentence1: str, sentence2: str, answer: str, exclude_ids=None) -> bool:
    if not sentence1 or not sentence2 or "_____" not in sentence2:
        return False
    with db_connection() as conn:
        cur = conn.execute(
            "SELECT id, sentence1, sentence2, answer FROM uoe_tasks ORDER BY id DESC LIMIT 500"
        )
        rows = cur.fetchall()
    exclude_ids = set(exclude_ids or [])
    n1_new = norm(sentence1)
    recon_new = norm(sentence2.replace("_____", (answer or "").strip()))
    for r in rows:
        if r["id"] in exclude_ids:
            continue
        n1_old = norm(r["sentence1"] or "")
        recon_old = norm((r["sentence2"] or "").replace("_____", (r["answer"] or "").strip()))
        if not n1_old and not recon_old:
            continue
        if n1_old and difflib.SequenceMatcher(None, n1_new, n1_old).ratio() >= 0.88:
            return True
        if recon_old and difflib.SequenceMatcher(None, recon_new, recon_old).ratio() >= 0.88:
            return True
    return False


def _generate_tasks_with_openai(count: int, level: str = "b2plus", recent_grammar_topics=None):
    if not openai_client:
        return []
    _ensure_uoe_grammar_topic_column()
    recent_grammar_topics = recent_grammar_topics or []
    recent_avoid = ""
    if recent_grammar_topics:
        recent_avoid = "\nAvoid or minimise repetition of these recently used grammar topics: " + ", ".join(recent_grammar_topics[:10]) + ".\n"
    level_instruction = (
        "Level: B2+ (slightly more difficult than B2). Use vocabulary and grammar that is upper-intermediate to advanced: less common collocations, more complex structures, idiomatic expressions. Avoid items that are too easy (A2/B1)."
        if (level or "").strip().lower() == "b2plus"
        else "Level: B2 (Cambridge B2 First). Use vocabulary and grammar appropriate for upper-intermediate learners. Standard FCE difficulty. Avoid items that are too easy (A2/B1) or too hard (C1)."
    )
    prompt_template = """You are an FCE (B2 First) English exam expert. Generate exactly {count} "key word transformation" items.

""" + level_instruction + """

Each item: sentence1 (first sentence), keyword (ONE word in CAPITALS that MUST appear in the answer), sentence2 (second sentence with the SAME meaning, with exactly one gap "_____"), answer (EXACTLY 3 to 5 words to fill the gap—never 1 or 2 words; the answer MUST contain the key word. E.g. for CHANCE use "chance of winning" or "no chance of succeeding", not just "chance". The gap must require a phrase of 3-5 words.), grammar_topic (ONE short label for the main grammar/construction tested, e.g. "passive voice", "third conditional", "reported speech", "comparatives", "past perfect", "modal verbs", "causative have", "wish/if only", "phrasal verbs", "linking words").

CRITICAL: The second sentence (sentence2) must be a REAL REPHRASING: different wording, different grammar or structure where possible. It must NOT be the first sentence with one phrase simply replaced by "_____".

Use a DIFFERENT grammar_topic for each item—vary the grammar (passive, conditionals, reported speech, modals, etc.). Do not repeat the same grammar focus in the set.
""" + recent_avoid + """
Return ONLY a valid JSON array of objects with keys: sentence1, keyword, sentence2, answer, grammar_topic. No other text."""
    result = []
    topics_used_in_batch = set()
    for attempt in range(2):
        need = count - len(result)
        if need <= 0:
            break
        prompt = prompt_template.format(count=need)
        try:
            comp = openai_chat_create([{"role": "user", "content": prompt}], temperature=0.8)
            content = (comp.choices[0].message.content or "").strip()
            m = re.search(r"\[[\s\S]*\]", content)
            arr = json.loads(m.group(0)) if m else []
            if not isinstance(arr, list):
                continue
            with db_connection() as conn:
                for item in arr[:need]:
                    s1 = (item.get("sentence1") or "").strip()
                    kw = (item.get("keyword") or "").strip().upper()
                    s2 = (item.get("sentence2") or "").strip()
                    if "_____" not in s2:
                        s2 = re.sub(r"\s+_{2,}\s*", " _____ ", s2)
                    ans = (item.get("answer") or "").strip()
                    grammar_topic = (item.get("grammar_topic") or "").strip() or None
                    if not all([s1, kw, s2, ans]):
                        continue
                    if not _answer_uses_keyword(ans, kw):
                        continue
                    if not _part4_answer_length_ok(ans):
                        continue
                    if _part4_sentence2_same_as_sentence1(s1, s2, ans):
                        continue
                    if _part4_similar_to_existing(s1, s2, ans, exclude_ids=[x["id"] for x in result]):
                        continue
                    if uoe_task_exists(s1, kw):
                        continue
                    if grammar_topic and grammar_topic.lower() in topics_used_in_batch:
                        continue
                    cur = conn.execute(
                        "INSERT INTO uoe_tasks (sentence1, keyword, sentence2, answer, source, grammar_topic) VALUES (?, ?, ?, ?, ?, ?)",
                        (s1, kw, s2, ans, "openai", grammar_topic),
                    )
                    new_id = cur.lastrowid
                    result.append({"id": new_id, "sentence1": s1, "keyword": kw, "sentence2": s2, "answer": ans, "grammar_topic": grammar_topic})
                    if grammar_topic:
                        topics_used_in_batch.add(grammar_topic.lower())
                conn.commit()
        except Exception:
            logger.exception("OpenAI Part 4 batch error")
            break
    return result


def fetch_part4_tasks(level: str = "b2plus", db_only: bool = False):
    _ensure_uoe_grammar_topic_column()
    tasks = []
    if not db_only and openai_client:
        tasks = _generate_tasks_with_openai(
            PART4_TASKS_PER_SET,
            level=level,
            recent_grammar_topics=get_recent_grammar_topics(15),
        )
    if not tasks:
        recent_topics = get_recent_grammar_topics(15)
        ids = pick_task_ids_from_db(PART4_TASKS_PER_SET * 2, recent_grammar_topics=recent_topics)
        if not ids:
            return None
        rows = get_tasks_by_ids(ids)
        out = []
        for r in rows:
            if len(out) >= PART4_TASKS_PER_SET:
                break
            if not _answer_uses_keyword(r["answer"], r["keyword"]) or not _part4_answer_length_ok(r["answer"]):
                continue
            if _part4_sentence2_same_as_sentence1(r["sentence1"], r["sentence2"], r["answer"]):
                continue
            out.append(r)
        if out:
            record_shows([r["id"] for r in out])
        return [{"id": r["id"], "sentence1": r["sentence1"], "keyword": r["keyword"], "sentence2": r["sentence2"], "answer": r["answer"]} for r in out] if out else None
    record_shows([t["id"] for t in tasks])
    return [{"id": t["id"], "sentence1": t["sentence1"], "keyword": t["keyword"], "sentence2": t["sentence2"], "answer": t["answer"]} for t in tasks]


def build_part4_html(tasks, check_result=None):
    if not tasks:
        return "<p>No tasks loaded.</p>"
    out = []
    for i, t in enumerate(tasks):
        if not isinstance(t, dict):
            continue
        s2 = (t.get("sentence2") or "").replace("_____", '<span class="gap-placeholder">_____</span>')
        val = ""
        cls = ""
        detail = None
        if check_result and isinstance(check_result.get("details"), list) and i < len(check_result["details"]):
            d = check_result["details"][i]
            detail = d if isinstance(d, dict) else None
        attempted = detail is not None and (detail.get("user_val") or "").strip()
        if attempted:
            val = detail.get("user_val", "")
            cls = " result-correct" if detail.get("correct") else " result-wrong"
        out.append(
            f'<div class="question-block uoe-block{cls}">'
            f'<p class="uoe-sentence1"><strong>{i + 1}.</strong> {_e(t.get("sentence1"))}</p>'
            f'<p class="uoe-keyword">Use <strong>{_e(t.get("keyword"))}</strong></p>'
            f'<p class="uoe-sentence2">{s2}</p>'
            f'<div class="gap-line"><input type="text" name="p4_{i}" value="{_e(val)}" placeholder="3–5 words" aria-label="Question {i + 1} answer" /></div>'
        )
        if attempted and not detail.get("correct"):
            out.append(f'<p class="correct-answer-hint">Correct: {_e(detail.get("expected"))}</p>')
        if attempted:
            exp = detail.get("explanation")
            if exp:
                out.append(f'<p class="answer-explanation">{_e(exp)}</p>')
        out.append("</div>")
    return "".join(out)


def check_part4(data, form):
    from flask import session
    if session.get("part4_task_ids"):
        tasks = get_tasks_by_ids(session["part4_task_ids"])
    else:
        raw = session.get("part4_tasks")
        tasks = list(raw) if isinstance(raw, list) else []
    if not tasks:
        return None
    details = []
    score = 0
    total_attempted = 0
    for i in range(len(tasks)):
        t = tasks[i]
        if not isinstance(t, dict):
            continue
        user_val = (form.get(f"p4_{i}") or "").strip()
        expected = t.get("answer") or ""
        correct = answers_match(user_val, expected)
        if user_val:
            total_attempted += 1
            if correct:
                score += 1
        details.append({"correct": correct, "user_val": user_val, "expected": expected})
    result = {"part": 4, "score": score, "total": total_attempted, "details": details}
    explanations = fetch_explanations_part4(tasks, details)
    max_explanation_len = 400
    for i, exp in enumerate(explanations):
        if i < len(result["details"]) and exp:
            result["details"][i]["explanation"] = (str(exp)[:max_explanation_len]).strip()
    return result
