"""OpenAI-powered answer explanations per part."""
import json
import logging

from app.ai import chat_create, ai_available
from app.ai.prompts import (
    get_explanation_prompt_part1,
    get_explanation_prompt_part2,
    get_explanation_prompt_part3,
    get_explanation_prompt_part4,
    get_explanation_prompt_part5,
    get_explanation_prompt_part6,
    get_explanation_prompt_part7,
    get_explanation_prompt_get_phrases,
)
from app.config import LETTERS, MAX_EXPLANATION_LEN, MAX_WORD_FAMILY_LEN
from app.utils import extract_json_array

logger = logging.getLogger("fce_trainer")


def _extract_json_array(content: str):
    """Extract a JSON array from model output. Delegates to shared util."""
    return extract_json_array(content)


def fetch_explanations_part1(item, details):
    if not ai_available:
        logger.debug("Part 1 explanations skipped: no AI provider configured")
        return []
    if not item or not item.get("gaps") or len(details) < 8:
        logger.debug("Part 1 explanations skipped: missing item or details")
        return []
    logger.info("Fetching Part 1 explanations from OpenAI...")
    passage = (item.get("text") or "").strip()
    lines = []
    for i in range(8):
        g = item["gaps"][i]
        opts = g.get("options", [])
        correct_idx = g.get("correct", 0)
        user_idx = details[i].get("user_val")
        if user_idx is None or user_idx < 0:
            user_idx = -1
        correct_letter = LETTERS[correct_idx] if correct_idx < len(LETTERS) else "?"
        correct_word = opts[correct_idx] if correct_idx < len(opts) else ""
        user_letter = LETTERS[user_idx] if 0 <= user_idx < len(LETTERS) else "—"
        user_word = opts[user_idx] if 0 <= user_idx < len(opts) else "(no answer)"
        lines.append(f"Gap {i+1}: A) {opts[0]} B) {opts[1]} C) {opts[2]} D) {opts[3]}. Correct: {correct_letter}) {correct_word}. Student chose: {user_letter}) {user_word}.")
    prompt = get_explanation_prompt_part1(passage, "\n".join(lines))
    try:
        comp = chat_create([{"role": "user", "content": prompt}], temperature=0.3)
        content = (comp.choices[0].message.content or "").strip()
        arr = _extract_json_array(content)
        if isinstance(arr, list) and len(arr) >= 8:
            logger.info("Part 1 explanations received from OpenAI (%d items)", len(arr))
            return [str(arr[i]).strip() for i in range(8)]
        logger.warning("Part 1 explanations: could not parse 8 items from response (got %s)", type(arr).__name__ if arr is not None else "None")
        return []
    except Exception:
        logger.exception("OpenAI explanations Part 1 error")
        return []


def fetch_explanations_part2(item, details):
    if not ai_available or not item or not item.get("answers") or len(details) < 8:
        return []
    passage = (item.get("text") or "").strip()
    lines = []
    for i in range(8):
        correct = (item["answers"][i] if i < len(item["answers"]) else "").strip()
        user_val = (details[i].get("user_val") or "").strip()
        lines.append(f"Gap {i+1}: Correct answer: '{correct}'. Student wrote: '{user_val or '(blank)'}'.")
    prompt = get_explanation_prompt_part2(passage, "\n".join(lines))
    try:
        comp = chat_create([{"role": "user", "content": prompt}], temperature=0.3)
        content = (comp.choices[0].message.content or "").strip()
        arr = _extract_json_array(content)
        if isinstance(arr, list) and len(arr) >= 8:
            return [str(arr[i]).strip() for i in range(8)]
        return []
    except Exception:
        logger.exception("OpenAI explanations Part 2 error")
        return []


def fetch_explanations_part3(task, details):
    if not ai_available or not task or len(details) < 8:
        return []
    if isinstance(task, dict) and "text" in task:
        passage = (task.get("text") or "").strip()
        stems = task.get("stems") or []
        answers = task.get("answers") or []
    else:
        items = task.get("items") if isinstance(task, dict) else (task if isinstance(task, list) else [])
        if not items or len(items) < 8:
            return []
        passage = " ".join((it.get("sentence") or "").strip() for it in items[:8])
        stems = [items[i].get("key", "").strip() for i in range(8)]
        answers = [items[i].get("answer", "").strip() for i in range(8)]
    if len(stems) < 8 or len(answers) < 8:
        return []
    lines = []
    for i in range(8):
        stem = (stems[i] if i < len(stems) else "").strip()
        correct = (answers[i] if i < len(answers) else "").strip()
        user_val = (details[i].get("user_val") or "").strip()
        lines.append(f"Gap {i+1}: Stem word: {stem}. Correct answer: '{correct}'. Student wrote: '{user_val or '(blank)'}'.")
    prompt = get_explanation_prompt_part3(passage[:4000], "\n".join(lines))
    try:
        comp = chat_create([{"role": "user", "content": prompt}], temperature=0.3)
        content = (comp.choices[0].message.content or "").strip()
        arr = _extract_json_array(content)
        if not isinstance(arr, list) or len(arr) < 8:
            return []
        result = []
        for i in range(8):
            el = arr[i] if isinstance(arr[i], dict) else {}
            result.append({
                "explanation": str(el.get("explanation") or "").strip()[:MAX_EXPLANATION_LEN],
                "word_family": str(el.get("word_family") or "").strip()[:MAX_WORD_FAMILY_LEN],
            })
        return result
    except Exception:
        logger.exception("OpenAI explanations Part 3 error")
        return []


def fetch_explanations_part4(tasks, details):
    if not ai_available or not tasks or len(details) < len(tasks):
        return []
    lines = []
    for i in range(len(tasks)):
        t = tasks[i]
        d = details[i]
        correct_ans = t.get("answer", "")
        user_ans = d.get("user_val", "") or "(no answer)"
        lines.append(f"Item {i+1}: First sentence: {t.get('sentence1')}. Key word: {t.get('keyword')}. Second sentence (gap): {t.get('sentence2')}. Correct answer: \"{correct_ans}\". Student wrote: \"{user_ans}\".")
    prompt = get_explanation_prompt_part4("\n".join(lines))
    try:
        comp = chat_create([{"role": "user", "content": prompt}], temperature=0.3)
        content = (comp.choices[0].message.content or "").strip()
        arr = _extract_json_array(content)
        if isinstance(arr, list) and len(arr) >= len(tasks):
            return [str(arr[i]).strip() for i in range(len(tasks))]
        return []
    except Exception:
        logger.exception("OpenAI explanations Part 4 error")
        return []


def fetch_explanations_part5(item, details):
    if not ai_available or not item or not item.get("questions") or len(details) < 6:
        return []
    text_snippet = (item.get("text") or "")[:3000]
    lines = []
    for i, q in enumerate(item["questions"]):
        correct_idx = q.get("correct", 0)
        opts = q.get("options", [])
        correct_letter = LETTERS[correct_idx] if correct_idx < len(LETTERS) else "?"
        correct_text = opts[correct_idx] if correct_idx < len(opts) else ""
        user_idx = details[i].get("user_val", -1)
        user_letter = LETTERS[user_idx] if 0 <= user_idx < len(LETTERS) else "—"
        user_text = opts[user_idx] if 0 <= user_idx < len(opts) else "(no answer)"
        lines.append(f"Q{i+1}: {q.get('q')}. Correct: {correct_letter}) {correct_text}. Student chose: {user_letter}) {user_text}.")
    prompt = get_explanation_prompt_part5(text_snippet, "\n".join(lines))
    try:
        comp = chat_create([{"role": "user", "content": prompt}], temperature=0.3)
        content = (comp.choices[0].message.content or "").strip()
        arr = _extract_json_array(content)
        if isinstance(arr, list) and len(arr) >= 6:
            return [str(arr[i]).strip() for i in range(6)]
        return []
    except Exception:
        logger.exception("OpenAI explanations Part 5 error")
        return []


def fetch_explanations_part6(item, details):
    if not ai_available or not item or not item.get("answers") or len(details) < 6:
        return []
    letters_g = ["A", "B", "C", "D", "E", "F", "G"]
    sentences = item.get("sentences", [])
    answers = item.get("answers", [])
    paragraphs_text = " ".join(p for p in item.get("paragraphs", []) if not p.startswith("GAP"))[:3000]
    lines = []
    for i in range(6):
        correct_idx = answers[i] if i < len(answers) else -1
        correct_letter = letters_g[correct_idx] if 0 <= correct_idx < len(letters_g) else "?"
        correct_sentence = sentences[correct_idx] if 0 <= correct_idx < len(sentences) else ""
        user_idx = details[i].get("user_val", -1)
        try:
            user_idx = int(user_idx)
        except (TypeError, ValueError):
            user_idx = -1
        user_letter = letters_g[user_idx] if 0 <= user_idx < len(letters_g) else "—"
        user_sentence = sentences[user_idx] if 0 <= user_idx < len(sentences) else "(no answer)"
        lines.append(f"Gap {i+1}: Correct: {correct_letter}) {correct_sentence}. Student chose: {user_letter}) {user_sentence}.")
    prompt = get_explanation_prompt_part6(paragraphs_text, "\n".join(lines))
    try:
        comp = chat_create([{"role": "user", "content": prompt}], temperature=0.3)
        content = (comp.choices[0].message.content or "").strip()
        arr = _extract_json_array(content)
        if isinstance(arr, list) and len(arr) >= 6:
            return [str(arr[i]).strip() for i in range(6)]
        return []
    except Exception:
        logger.exception("OpenAI explanations Part 6 error")
        return []


def fetch_explanations_part7(item, details):
    if not ai_available or not item or not item.get("questions") or len(details) < 10:
        return []
    sections = item.get("sections", [])
    sections_text = " | ".join(f"{s.get('id')}: {s.get('title', '')}" for s in sections)[:1000]
    lines = []
    for i, q in enumerate(item["questions"]):
        correct_section = q.get("correct", "?")
        user_val = details[i].get("user_val", "(no answer)")
        lines.append(f"Statement {i+1}: '{q.get('text')}'. Correct: {correct_section}. Student chose: {user_val}.")
    prompt = get_explanation_prompt_part7(sections_text, "\n".join(lines))
    try:
        comp = chat_create([{"role": "user", "content": prompt}], temperature=0.3)
        content = (comp.choices[0].message.content or "").strip()
        arr = _extract_json_array(content)
        if isinstance(arr, list) and len(arr) >= 10:
            return [str(arr[i]).strip() for i in range(10)]
        return []
    except Exception:
        logger.exception("OpenAI explanations Part 7 error")
        return []


def fetch_explanations_get_phrases(task, details):
    """Get phrases: 8 gaps, each correct answer is a 'get' collocation. Returns list of dicts with 'explanation'."""
    if not ai_available or not task or not task.get("text") or not task.get("answers") or len(details) < 8:
        return []
    passage = (task.get("text") or "").strip()
    answers = task.get("answers") or []
    if len(answers) < 8:
        return []
    lines = []
    for i in range(8):
        correct = (answers[i] if i < len(answers) else "").strip()
        user_val = (details[i].get("user_val") or "").strip()
        lines.append(f"Gap {i+1}: Correct: '{correct}'. Student wrote: '{user_val or '(blank)'}'.")
    prompt = get_explanation_prompt_get_phrases(passage[:4000], "\n".join(lines))
    try:
        comp = chat_create([{"role": "user", "content": prompt}], temperature=0.3)
        content = (comp.choices[0].message.content or "").strip()
        arr = _extract_json_array(content)
        if isinstance(arr, list) and len(arr) >= 8:
            return [{"explanation": str(arr[i]).strip()[:MAX_EXPLANATION_LEN]} for i in range(8)]
        return []
    except Exception:
        logger.exception("OpenAI explanations Get phrases error")
        return []
