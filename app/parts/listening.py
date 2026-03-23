"""FCE Listening Parts 1–4: generation, checking, audio management."""
from __future__ import annotations

import json
import logging
import random
from pathlib import Path

from app.ai import chat_create, ai_available
from app.ai.prompts.listening_generation import (
    get_listening_prompt_part1,
    get_listening_prompt_part2,
    get_listening_prompt_part3,
    get_listening_prompt_part4,
    LISTENING_PART1_TOPICS,
    LISTENING_PART2_TOPICS,
    LISTENING_PART3_TOPICS,
    LISTENING_PART4_TOPICS,
)
from app.config import LISTENING_QUESTION_COUNTS
from app.db import (
    db_connection,
    get_listening_task,
    pick_listening_task_id,
    record_listening_show,
    save_listening_task,
    update_listening_audio_path,
)
from app.services.tts import generate_listening_audio
from app.utils import extract_json_object

logger = logging.getLogger("fce_trainer")

_PROMPT_FNS = {
    1: get_listening_prompt_part1,
    2: get_listening_prompt_part2,
    3: get_listening_prompt_part3,
    4: get_listening_prompt_part4,
}

_TOPICS = {
    1: LISTENING_PART1_TOPICS,
    2: LISTENING_PART2_TOPICS,
    3: LISTENING_PART3_TOPICS,
    4: LISTENING_PART4_TOPICS,
}


# ── Validation ───────────────────────────────────────────────────────────────

def _validate_part1(data: dict) -> bool:
    extracts = data.get("extracts")
    if not isinstance(extracts, list) or len(extracts) != 8:
        return False
    for ex in extracts:
        if not isinstance(ex.get("script"), list) or not ex.get("script"):
            return False
        if not ex.get("question") or not isinstance(ex.get("options"), list):
            return False
        if len(ex["options"]) != 3:
            return False
        if ex.get("correct") not in (0, 1, 2):
            return False
    return True


def _validate_part2(data: dict) -> bool:
    if not isinstance(data.get("script"), list) or len(data["script"]) < 2:
        return False
    sentences = data.get("sentences")
    if not isinstance(sentences, list) or len(sentences) != 10:
        return False
    for s in sentences:
        if not s.get("text") or not s.get("answer"):
            return False
    return True


def _validate_part3(data: dict) -> bool:
    speakers = data.get("speakers")
    if not isinstance(speakers, list) or len(speakers) != 5:
        return False
    stmts = data.get("statements")
    if not isinstance(stmts, list) or len(stmts) != 8:
        return False
    answers = data.get("answers")
    if not isinstance(answers, list) or len(answers) != 5:
        return False
    if not all(isinstance(a, int) and 0 <= a <= 7 for a in answers):
        return False
    return True


def _validate_part4(data: dict) -> bool:
    if not isinstance(data.get("script"), list) or len(data["script"]) < 3:
        return False
    questions = data.get("questions")
    if not isinstance(questions, list) or len(questions) != 7:
        return False
    for q in questions:
        if not q.get("text") or not isinstance(q.get("options"), list):
            return False
        if len(q["options"]) != 3:
            return False
        if q.get("correct") not in (0, 1, 2):
            return False
    return True


_VALIDATORS = {1: _validate_part1, 2: _validate_part2, 3: _validate_part3, 4: _validate_part4}


# ── Script → TTS segments ───────────────────────────────────────────────────

def _collect_segments_part1(data: dict) -> list[dict]:
    """Build flat segment list for Part 1 audio."""
    segments = [{"voice": "narrator", "text": "Part 1. You will hear people talking in eight different situations. For questions 1 to 8, choose the best answer, A, B or C."}]
    for i, ex in enumerate(data["extracts"]):
        segments.append({"voice": "narrator", "text": f"Extract {i + 1}. {ex.get('intro', '')}"})
        for s in ex["script"]:
            segments.append({"voice": s.get("voice", "narrator"), "text": s.get("text", "")})
    return segments


def _collect_segments_part2(data: dict) -> list[dict]:
    return list(data["script"])


def _collect_segments_part3(data: dict) -> list[dict]:
    intro = data.get("intro", "You will hear five different people talking.")
    segments = [{"voice": "narrator", "text": f"Part 3. {intro} For questions 1 to 5, choose from the list A to H."}]
    for i, sp in enumerate(data["speakers"]):
        segments.append({"voice": "narrator", "text": f"Speaker {i + 1}."})
        segments.append({"voice": sp.get("voice", "narrator"), "text": sp.get("text", "")})
    return segments


def _collect_segments_part4(data: dict) -> list[dict]:
    return list(data["script"])


_SEGMENT_COLLECTORS = {
    1: _collect_segments_part1,
    2: _collect_segments_part2,
    3: _collect_segments_part3,
    4: _collect_segments_part4,
}

# ── Transcript file ──────────────────────────────────────────────────────────

_TRANSCRIPTS_DIR = Path(__file__).resolve().parent.parent.parent / "static" / "transcripts"


def _save_transcript(part: int, task_id: int, data: dict) -> None:
    """Save a plain-text transcript to static/transcripts/."""
    try:
        _TRANSCRIPTS_DIR.mkdir(parents=True, exist_ok=True)
        lines = [f"FCE Listening — Part {part}  (task #{task_id})\n"]
        if part == 1:
            for i, ex in enumerate(data.get("extracts", [])):
                lines.append(f"\n--- Extract {i + 1} ---")
                lines.append(ex.get("intro", ""))
                for seg in ex.get("script", []):
                    lines.append(f"[{seg.get('voice', '')}] {seg.get('text', '')}")
                lines.append(f"\nQ: {ex.get('question', '')}")
                for j, opt in enumerate(ex.get("options", [])):
                    mark = " ✓" if j == ex.get("correct") else ""
                    lines.append(f"  {'ABC'[j]}) {opt}{mark}")
        elif part == 2:
            for seg in data.get("script", []):
                lines.append(f"[{seg.get('voice', '')}] {seg.get('text', '')}")
            lines.append("\n--- Sentences ---")
            for i, s in enumerate(data.get("sentences", [])):
                lines.append(f"{i + 1}. {s.get('text', '')}  →  {s.get('answer', '')}")
        elif part == 3:
            for i, sp in enumerate(data.get("speakers", [])):
                lines.append(f"\n--- Speaker {i + 1} ---")
                lines.append(f"[{sp.get('voice', '')}] {sp.get('text', '')}")
            lines.append("\n--- Statements ---")
            for st in data.get("statements", []):
                lines.append(f"  {st}")
            lines.append(f"\nAnswers: {data.get('answers', [])}")
        elif part == 4:
            for seg in data.get("script", []):
                lines.append(f"[{seg.get('voice', '')}] {seg.get('text', '')}")
            lines.append("\n--- Questions ---")
            for i, q in enumerate(data.get("questions", [])):
                lines.append(f"\n{i + 1}. {q.get('text', '')}")
                for j, opt in enumerate(q.get("options", [])):
                    mark = " ✓" if j == q.get("correct") else ""
                    lines.append(f"  {'ABC'[j]}) {opt}{mark}")

        path = _TRANSCRIPTS_DIR / f"listening_p{part}_{task_id}.txt"
        path.write_text("\n".join(lines), encoding="utf-8")
        logger.info("Transcript saved: %s", path)
    except Exception:
        logger.warning("Failed to save transcript", exc_info=True)


# ── Generate ─────────────────────────────────────────────────────────────────

def generate_listening_task(part: int) -> dict | None:
    """Generate a new listening task with AI + TTS. Returns task dict or None."""
    if not ai_available:
        logger.warning("AI not available for listening generation")
        return None

    prompt_fn = _PROMPT_FNS.get(part)
    topics = _TOPICS.get(part, [])
    if not prompt_fn or not topics:
        return None

    topic = random.choice(topics)
    prompt = prompt_fn(topic)

    try:
        comp = chat_create([{"role": "user", "content": prompt}], temperature=0.7)
        content = (comp.choices[0].message.content or "").strip()
        data = extract_json_object(content)
        if not data:
            logger.error("Listening Part %d: failed to parse AI JSON", part)
            return None

        validator = _VALIDATORS.get(part)
        if validator and not validator(data):
            logger.error("Listening Part %d: validation failed", part)
            return None

        # Generate audio
        collector = _SEGMENT_COLLECTORS.get(part)
        if collector:
            segments = collector(data)
            import time
            filename = f"listening_p{part}_{int(time.time())}"
            audio_url = generate_listening_audio(segments, filename)
        else:
            audio_url = None

        # Save to DB
        data_json = json.dumps(data, ensure_ascii=False)
        task_id = save_listening_task(part, data_json, audio_url)

        if task_id:
            _save_transcript(part, task_id, data)
            return {"id": task_id, "data": data, "audio_path": audio_url, "source": "openai"}
        return None

    except Exception:
        logger.exception("Listening Part %d generation failed", part)
        return None


def get_or_create_listening_task(part: int, exclude_id: int | None = None) -> tuple[dict | None, int | None]:
    """Get existing task from DB or generate new one. Returns (task, task_id)."""
    task_id = pick_listening_task_id(part, exclude_current=exclude_id)

    if task_id is None and ai_available:
        task = generate_listening_task(part)
        if task:
            record_listening_show(part, task["id"])
            return task, task["id"]

    # Fallback to any existing task
    if task_id is None:
        from app.db import _LISTENING_DB_SCHEMA
        schema = _LISTENING_DB_SCHEMA.get(part)
        if schema:
            with db_connection() as conn:
                if exclude_id is not None:
                    cur = conn.execute(
                        f"SELECT id FROM {schema['table']} WHERE id != ? ORDER BY RANDOM() LIMIT 1",
                        (exclude_id,),
                    )
                else:
                    cur = conn.execute(f"SELECT id FROM {schema['table']} ORDER BY RANDOM() LIMIT 1")
                row = cur.fetchone()
                task_id = row["id"] if row else None

    if task_id is None:
        return None, None

    record_listening_show(part, task_id)
    task = get_listening_task(part, task_id)

    # Auto-retry audio generation for tasks saved without audio
    if task and not task.get("audio_path"):
        task = retry_audio_generation(part, task)

    return task, task_id


def retry_audio_generation(part: int, task: dict, force: bool = False) -> dict:
    """Generate (or re-generate) audio for a listening task."""
    if not force and task.get("audio_path"):
        return task
    collector = _SEGMENT_COLLECTORS.get(part)
    if not collector or not task.get("data"):
        return task
    try:
        segments = collector(task["data"])
        import time
        filename = f"listening_p{part}_{int(time.time())}"
        audio_url = generate_listening_audio(segments, filename)
        if audio_url:
            # Delete old audio file if it exists
            if task.get("audio_path"):
                old_file = Path(__file__).resolve().parent.parent.parent / "static" / task["audio_path"].lstrip("/")
                try:
                    old_file.unlink(missing_ok=True)
                except Exception:
                    pass
            update_listening_audio_path(part, task["id"], audio_url)
            task["audio_path"] = audio_url
            logger.info("Audio generated for listening part %d task %d", part, task["id"])
    except Exception:
        logger.exception("Audio generation failed for listening part %d task %d", part, task.get("id"))
    return task


# ── Check answers ────────────────────────────────────────────────────────────

def check_listening_part1(data: dict, answers: dict[int, int]) -> dict:
    """Check Part 1 answers. answers: {question_index: chosen_option_index}."""
    extracts = data.get("extracts", [])
    details = []
    score = 0
    for i, ex in enumerate(extracts):
        user_ans = answers.get(i)
        correct = ex.get("correct", 0)
        is_correct = user_ans == correct
        if is_correct:
            score += 1
        details.append({
            "correct": is_correct,
            "user_val": user_ans,
            "expected": correct,
            "question": ex.get("question", ""),
            "options": ex.get("options", []),
        })
    return {"score": score, "total": len(extracts), "details": details}


def check_listening_part2(data: dict, answers: dict[int, str]) -> dict:
    """Check Part 2 answers. answers: {sentence_index: user_text}."""
    sentences = data.get("sentences", [])
    details = []
    score = 0
    for i, s in enumerate(sentences):
        user_ans = (answers.get(i) or "").strip().lower()
        expected = (s.get("answer") or "").strip().lower()
        is_correct = user_ans == expected
        if is_correct:
            score += 1
        details.append({
            "correct": is_correct,
            "user_val": answers.get(i, ""),
            "expected": s.get("answer", ""),
            "sentence": s.get("text", ""),
        })
    return {"score": score, "total": len(sentences), "details": details}


def check_listening_part3(data: dict, answers: dict[int, int]) -> dict:
    """Check Part 3 answers. answers: {speaker_index: statement_index}."""
    correct_answers = data.get("answers", [])
    statements = data.get("statements", [])
    details = []
    score = 0
    for i, correct in enumerate(correct_answers):
        user_ans = answers.get(i)
        is_correct = user_ans == correct
        if is_correct:
            score += 1
        details.append({
            "correct": is_correct,
            "user_val": user_ans,
            "expected": correct,
            "statement": statements[correct] if correct < len(statements) else "",
        })
    return {"score": score, "total": len(correct_answers), "details": details}


def check_listening_part4(data: dict, answers: dict[int, int]) -> dict:
    """Check Part 4 answers. answers: {question_index: chosen_option_index}."""
    questions = data.get("questions", [])
    details = []
    score = 0
    for i, q in enumerate(questions):
        user_ans = answers.get(i)
        correct = q.get("correct", 0)
        is_correct = user_ans == correct
        if is_correct:
            score += 1
        details.append({
            "correct": is_correct,
            "user_val": user_ans,
            "expected": correct,
            "question": q.get("text", ""),
            "options": q.get("options", []),
        })
    return {"score": score, "total": len(questions), "details": details}


LISTENING_CHECKERS = {
    1: check_listening_part1,
    2: check_listening_part2,
    3: check_listening_part3,
    4: check_listening_part4,
}
