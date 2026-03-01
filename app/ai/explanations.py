"""OpenAI-powered answer explanations per part."""
import json
import logging
import re

from app.ai import openai_chat_create, openai_client
from app.config import LETTERS, MAX_EXPLANATION_LEN, MAX_WORD_FAMILY_LEN

logger = logging.getLogger("fce_trainer")


def fetch_explanations_part1(item, details):
    if not openai_client or not item or not item.get("gaps") or len(details) < 8:
        return []
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
    prompt = """You are an FCE (B2 First) English teacher. You will see a multiple-choice cloze passage and, for each gap, the four options (A–D), the correct answer, and what the student chose.

Use the PASSAGE as context so your explanations refer to the actual sentences (e.g. "In this sentence, X is needed because...").

PASSAGE (gaps are marked as (1)_____, (2)_____, etc.):
---
""" + passage + """

---
For each gap, write ONE short explanation (1-2 sentences) in plain English:
1) Why the correct answer is right in this context (grammar/meaning in the sentence above).
2) If the student's answer was wrong, briefly why that option is wrong or doesn't fit here.

Keep each explanation clear and educational. Return ONLY a JSON array of exactly 8 strings (one per gap, in order). No other text.

Gaps:
""" + "\n".join(lines)
    try:
        comp = openai_chat_create([{"role": "user", "content": prompt}], temperature=0.3)
        content = (comp.choices[0].message.content or "").strip()
        m = re.search(r"\[[\s\S]*?\]", content)
        if not m:
            return []
        arr = json.loads(m.group(0))
        if isinstance(arr, list) and len(arr) >= 8:
            return [str(arr[i]).strip() for i in range(8)]
        return []
    except Exception:
        logger.exception("OpenAI explanations Part 1 error")
        return []


def fetch_explanations_part2(item, details):
    if not openai_client or not item or not item.get("answers") or len(details) < 8:
        return []
    passage = (item.get("text") or "").strip()
    lines = []
    for i in range(8):
        correct = (item["answers"][i] if i < len(item["answers"]) else "").strip()
        user_val = (details[i].get("user_val") or "").strip()
        lines.append(f"Gap {i+1}: Correct answer: '{correct}'. Student wrote: '{user_val or '(blank)'}'.")
    prompt = """You are an FCE (B2 First) English teacher. You will see an open-cloze passage and, for each gap, the correct answer and what the student wrote.

Use the PASSAGE as context so your explanations refer to the actual sentences (e.g. "In this sentence, X is needed because...").

PASSAGE (gaps are marked as (1)_____, (2)_____, etc.):
---
""" + passage + """

---
For each gap, write ONE short explanation (1-2 sentences) in plain English:
1) Why the correct word is right in this context (grammar/meaning in the sentence above).
2) If the student's answer was wrong or blank, briefly why their word doesn't fit or what the gap requires here.

Keep each explanation clear and educational. Return ONLY a JSON array of exactly 8 strings (one per gap, in order). No other text.

Gaps:
""" + "\n".join(lines)
    try:
        comp = openai_chat_create([{"role": "user", "content": prompt}], temperature=0.3)
        content = (comp.choices[0].message.content or "").strip()
        m = re.search(r"\[[\s\S]*?\]", content)
        if not m:
            return []
        arr = json.loads(m.group(0))
        if isinstance(arr, list) and len(arr) >= 8:
            return [str(arr[i]).strip() for i in range(8)]
        return []
    except Exception:
        logger.exception("OpenAI explanations Part 2 error")
        return []


def fetch_explanations_part3(task, details):
    if not openai_client or not task or len(details) < 8:
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
    prompt = """You are an FCE (B2 First) English teacher. For a Part 3 (word formation) task, you will see the passage and for each gap: the stem word in CAPITALS, the correct answer, and what the student wrote.

PASSAGE (for context):
---
""" + passage[:4000] + """

---
For each gap, provide TWO things:

1) **Explanation** (1-2 sentences): Why the correct word fits in this context (grammar/meaning). If the student's answer was wrong or blank, explain briefly why their word doesn't fit or what form was needed.

2) **Word family** for the stem: Give the main forms that exist for this word, in this exact format (use — for forms that don't exist or aren't common):
  noun: ... ; adjective: ... ; adverb: ... ; verb: ...

Return ONLY a valid JSON array of exactly 8 objects. Each object has two keys: "explanation" (string) and "word_family" (string). No other text.

Gaps:
""" + "\n".join(lines)
    try:
        comp = openai_chat_create([{"role": "user", "content": prompt}], temperature=0.3)
        content = (comp.choices[0].message.content or "").strip()
        m = re.search(r"\[[\s\S]*?\]", content)
        if not m:
            return []
        arr = json.loads(m.group(0))
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
    if not openai_client or not tasks or len(details) < len(tasks):
        return []
    lines = []
    for i in range(len(tasks)):
        t = tasks[i]
        d = details[i]
        correct_ans = t.get("answer", "")
        user_ans = d.get("user_val", "") or "(no answer)"
        lines.append(f"Item {i+1}: First sentence: {t.get('sentence1')}. Key word: {t.get('keyword')}. Second sentence (gap): {t.get('sentence2')}. Correct answer: \"{correct_ans}\". Student wrote: \"{user_ans}\".")
    prompt = """You are an FCE (B2 First) English teacher. Below are key word transformation items with the correct answer and what the student wrote.

For each item, write ONE short explanation (1-2 sentences) in plain English:
1) Why the correct answer is right (same meaning, uses the key word correctly).
2) If the student's answer was wrong, briefly why it doesn't work or what the mistake is.

Keep each explanation clear and educational. Return ONLY a JSON array of strings (one per item). No other text.

Items:
""" + "\n".join(lines)
    try:
        comp = openai_chat_create([{"role": "user", "content": prompt}], temperature=0.3)
        content = (comp.choices[0].message.content or "").strip()
        m = re.search(r"\[[\s\S]*?\]", content)
        if not m:
            return []
        arr = json.loads(m.group(0))
        if isinstance(arr, list) and len(arr) >= len(tasks):
            return [str(arr[i]).strip() for i in range(len(tasks))]
        return []
    except Exception:
        logger.exception("OpenAI explanations Part 4 error")
        return []


def fetch_explanations_part5(item, details):
    if not openai_client or not item or not item.get("questions") or len(details) < 6:
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
    prompt = """You are an FCE (B2 First) English teacher. For a Part 5 (reading comprehension, multiple choice) task, you will see the passage and for each question: the question text, correct answer, and student's answer.

PASSAGE (for context):
---
""" + text_snippet + """

---
For each question, write ONE short explanation (1-2 sentences):
1) Why the correct answer is right, referring to specific parts of the text.
2) If the student was wrong, briefly why their choice doesn't fit.

Return ONLY a JSON array of exactly 6 strings (one per question). No other text.

Questions:
""" + "\n".join(lines)
    try:
        comp = openai_chat_create([{"role": "user", "content": prompt}], temperature=0.3)
        content = (comp.choices[0].message.content or "").strip()
        m = re.search(r"\[[\s\S]*?\]", content)
        if not m:
            return []
        arr = json.loads(m.group(0))
        if isinstance(arr, list) and len(arr) >= 6:
            return [str(arr[i]).strip() for i in range(6)]
        return []
    except Exception:
        logger.exception("OpenAI explanations Part 5 error")
        return []


def fetch_explanations_part6(item, details):
    if not openai_client or not item or not item.get("answers") or len(details) < 6:
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
    prompt = """You are an FCE (B2 First) English teacher. For a Part 6 (gapped text) task, you will see the text and for each gap: which sentence correctly fills it and what the student chose.

TEXT (for context):
---
""" + paragraphs_text + """

---
For each gap, write ONE short explanation (1-2 sentences):
1) Why the correct sentence fits (coherence, linking words, pronouns, logical flow).
2) If the student was wrong, briefly why their sentence doesn't fit there.

Return ONLY a JSON array of exactly 6 strings. No other text.

Gaps:
""" + "\n".join(lines)
    try:
        comp = openai_chat_create([{"role": "user", "content": prompt}], temperature=0.3)
        content = (comp.choices[0].message.content or "").strip()
        m = re.search(r"\[[\s\S]*?\]", content)
        if not m:
            return []
        arr = json.loads(m.group(0))
        if isinstance(arr, list) and len(arr) >= 6:
            return [str(arr[i]).strip() for i in range(6)]
        return []
    except Exception:
        logger.exception("OpenAI explanations Part 6 error")
        return []


def fetch_explanations_part7(item, details):
    if not openai_client or not item or not item.get("questions") or len(details) < 10:
        return []
    sections = item.get("sections", [])
    sections_text = " | ".join(f"{s.get('id')}: {s.get('title', '')}" for s in sections)[:1000]
    lines = []
    for i, q in enumerate(item["questions"]):
        correct_section = q.get("correct", "?")
        user_val = details[i].get("user_val", "(no answer)")
        lines.append(f"Statement {i+1}: '{q.get('text')}'. Correct: {correct_section}. Student chose: {user_val}.")
    prompt = """You are an FCE (B2 First) English teacher. For a Part 7 (multiple matching) task, you will see the sections and for each statement: the correct section and what the student chose.

Sections: """ + sections_text + """

For each statement, write ONE short explanation (1-2 sentences):
1) Why the correct section matches (what in that section corresponds to the statement).
2) If the student was wrong, briefly why their chosen section doesn't match.

Return ONLY a JSON array of exactly 10 strings. No other text.

Statements:
""" + "\n".join(lines)
    try:
        comp = openai_chat_create([{"role": "user", "content": prompt}], temperature=0.3)
        content = (comp.choices[0].message.content or "").strip()
        m = re.search(r"\[[\s\S]*?\]", content)
        if not m:
            return []
        arr = json.loads(m.group(0))
        if isinstance(arr, list) and len(arr) >= 10:
            return [str(arr[i]).strip() for i in range(10)]
        return []
    except Exception:
        logger.exception("OpenAI explanations Part 7 error")
        return []
