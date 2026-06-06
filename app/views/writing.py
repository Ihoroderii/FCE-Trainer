"""Writing section: essay + Part 2 options."""
from __future__ import annotations

import collections
import io
import secrets

from flask import Blueprint, Response, jsonify, redirect, render_template, request, session, url_for

from app.ai import ai_available, chat_create
from app.config import WRITING_HISTORY_PARTS
from app.services.stats import record_check_result
from app.services.writing import (
    get_writing_context,
    get_writing_draft,
    get_writing_owner_key,
    has_scored_writing_attempt,
    save_writing_attempt,
    save_writing_draft,
    writing_task_key,
)
from app.utils import extract_json_object

bp = Blueprint("writing", __name__)

# In-memory cache: task_token -> PNG bytes. Evict oldest (FIFO) when over limit.
_TASK_IMAGE_CACHE: collections.OrderedDict[str, bytes] = collections.OrderedDict()
_MAX_TASK_IMAGES = 15


def _render_task_image_png(essay_prompt: dict) -> bytes:
    """Render Part 1 essay task (question, points, notes) onto a PNG image. Returns PNG bytes."""
    try:
        from PIL import Image, ImageDraw, ImageFont
    except ImportError:
        return b""

    width = 520
    padding = 24
    line_height = 22
    font_size = 15
    font = None
    for path in (
        "/System/Library/Fonts/Helvetica.ttc",          # macOS
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",  # Linux
        "C:\\Windows\\Fonts\\arial.ttf",                    # Windows
    ):
        try:
            font = ImageFont.truetype(path, font_size)
            break
        except (OSError, TypeError):
            continue
    if font is None:
        font = ImageFont.load_default()
    font_bold = font

    def wrap_text(draw, text, font, max_width):
        words = text.replace("\n", " \n ").split()
        lines = []
        current = []
        for w in words:
            if w == "\n":
                if current:
                    lines.append(" ".join(current))
                    current = []
                continue
            current.append(w)
            line = " ".join(current)
            bbox = draw.textbbox((0, 0), line, font=font)
            if bbox[2] - bbox[0] > max_width and len(current) > 1:
                current.pop()
                lines.append(" ".join(current))
                current = [w]
        if current:
            lines.append(" ".join(current))
        return lines

    bits = []
    bits.append(essay_prompt.get("question", ""))
    for p in essay_prompt.get("points", []):
        bits.append("• " + p)
    bits.append(essay_prompt.get("notes", ""))
    full_text = "\n".join(bits)
    img = Image.new("RGB", (width, 10), color=(255, 255, 255))
    draw = ImageDraw.Draw(img)
    max_text_width = width - 2 * padding
    all_lines = []
    for block in full_text.split("\n"):
        all_lines.extend(wrap_text(draw, block, font, max_text_width))
    num_lines = len(all_lines)
    height = 2 * padding + num_lines * line_height
    img = Image.new("RGB", (width, height), color=(252, 252, 252))
    draw = ImageDraw.Draw(img)
    draw.rectangle([0, 0, width - 1, height - 1], outline=(220, 220, 220), width=1)
    y = padding
    for line in all_lines:
        draw.text((padding, y), line, fill=(40, 40, 40), font=font)
        y += line_height
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


ESSAY_TASK_GENERATION_PROMPT = """You are a Cambridge B2 First (FCE) exam writer. Generate exactly ONE Part 1 Writing task (compulsory essay).

The task must have:
1. "question": One or two sentences. Start with "In your English class you have been talking about [topic]. Now your teacher has asked you to write an essay." Use a different topic each time (e.g. travel, environment, work, free time, technology, health, education, family, shopping, holidays).
2. "points": An array of exactly two strings. Each is a short point the candidate must discuss (e.g. "Why people like...", "Whether it is better to...", "How we can...").
3. "notes": Exactly this text: "Write about 140–190 words. Write the essay using all the notes and give reasons for your point of view."

Respond with ONLY a single JSON object, no other text. Use this exact shape:
{"question": "...", "points": ["...", "..."], "notes": "Write about 140–190 words. Write the essay using all the notes and give reasons for your point of view."}"""


def _parse_essay_task_from_ai(content: str) -> dict | None:
    """Extract and validate essay task JSON from AI response. Returns dict or None."""
    if not content:
        return None
    data = extract_json_object(content)
    if not data:
        return None
    question = (data.get("question") or "").strip()
    points = data.get("points")
    notes = (data.get("notes") or "").strip()
    if not question or not isinstance(points, list) or len(points) != 2:
        return None
    points = [str(p).strip() for p in points if p]
    if len(points) != 2:
        return None
    if "140" not in notes and "190" not in notes:
        notes = "Write about 140–190 words. Write the essay using all the notes and give reasons for your point of view."
    return {"question": question, "points": points, "notes": notes}


def _generate_essay_task_with_ai() -> dict | None:
    """Ask AI for a new Part 1 essay task. Returns essay dict or None."""
    if not ai_available:
        return None
    try:
        comp = chat_create(
            [{"role": "user", "content": ESSAY_TASK_GENERATION_PROMPT}],
            temperature=0.8,
        )
        content = (comp.choices[0].message.content or "").strip()
        return _parse_essay_task_from_ai(content)
    except Exception:
        return None


def _ensure_task_image(essay_prompt: dict) -> str:
    """Create or reuse a task token and ensure image is in cache. Returns task_token."""
    token = session.get("writing_task_token")
    if token and token in _TASK_IMAGE_CACHE:
        return token
    token = secrets.token_urlsafe(32)
    png = _render_task_image_png(essay_prompt)
    if png:
        while len(_TASK_IMAGE_CACHE) >= _MAX_TASK_IMAGES:
            _TASK_IMAGE_CACHE.popitem(last=False)
        _TASK_IMAGE_CACHE[token] = png
        session["writing_task_token"] = token
    else:
        token = ""
    return token


def _extract_json_object(text: str):
    """Deprecated — use extract_json_object from app.utils instead."""
    return extract_json_object(text)


def _parse_feedback(raw: str):
    """Parse JSON feedback or fall back to plain text."""
    if not raw:
        return None
    data = extract_json_object(raw)
    if data:
        return _normalise_feedback(data, raw)
    return _normalise_feedback({"raw_text": raw, "comment": raw}, raw)


def _as_text_list(value) -> list[str]:
    if isinstance(value, list):
        return [str(item).strip() for item in value if str(item).strip()]
    if isinstance(value, str) and value.strip():
        return [value.strip()]
    return []


def _as_feedback_items(value, keys: tuple[str, ...]) -> list[dict]:
    items = []
    if not isinstance(value, list):
        return items
    for item in value:
        if isinstance(item, dict):
            normalised = {key: str(item.get(key) or "").strip() for key in keys}
        else:
            normalised = {keys[0]: str(item).strip()}
            for key in keys[1:]:
                normalised[key] = ""
        if any(normalised.values()):
            items.append(normalised)
    return items


def _normalise_feedback(feedback: dict | None, raw_text: str = "") -> dict:
    data = dict(feedback or {})
    if raw_text and not data.get("raw_text"):
        data["raw_text"] = raw_text
    data.setdefault("comment", data.get("raw_text", ""))
    data["student_improved_version"] = str(data.get("student_improved_version") or "").strip()
    data["ai_improved_version"] = str(data.get("ai_improved_version") or "").strip()
    data["missing_task_points"] = _as_text_list(data.get("missing_task_points"))
    data["organisation_advice"] = _as_text_list(data.get("organisation_advice"))
    data["grammar_corrections"] = _as_feedback_items(
        data.get("grammar_corrections"),
        ("original", "corrected", "explanation"),
    )
    data["better_sentence_examples"] = _as_feedback_items(
        data.get("better_sentence_examples"),
        ("original", "improved", "reason"),
    )
    data["vocabulary_upgrades"] = _as_feedback_items(
        data.get("vocabulary_upgrades"),
        ("original", "upgraded", "reason"),
    )
    rewrite = data.get("rewrite_suggestion")
    if isinstance(rewrite, dict):
        data["rewrite_suggestion"] = {
            "original": str(rewrite.get("original") or "").strip(),
            "improved": str(rewrite.get("improved") or "").strip(),
            "reason": str(rewrite.get("reason") or "").strip(),
        }
    else:
        data["rewrite_suggestion"] = {"original": "", "improved": "", "reason": ""}
    return data


def _word_count(text: str) -> int:
    return len((text or "").split())


def _get_part2_option(ctx: dict, option_id: str) -> dict | None:
    option_id = (option_id or "").strip().lower()
    return next((opt for opt in ctx["part2_options"] if opt["id"] == option_id), None)


def _task_snapshot(ctx: dict, part: int, option_id: str = "") -> dict:
    if part == 1:
        essay = ctx["essay_prompt"]
        return {
            "part": 1,
            "type": "Essay",
            "question": essay.get("question", ""),
            "points": list(essay.get("points") or []),
            "notes": essay.get("notes", ""),
        }
    opt = _get_part2_option(ctx, option_id)
    if not opt:
        return {"part": 2, "option_id": (option_id or "").strip().lower()}
    return {
        "part": 2,
        "option_id": opt["id"],
        "type": opt.get("type", ""),
        "task": opt.get("task", ""),
        "prompt": opt.get("prompt", ""),
    }


def _task_description(ctx: dict, part: int, option_id: str = "") -> str:
    if part == 1:
        essay = ctx["essay_prompt"]
        return (
            f"{essay['question']}\n\nPoints to cover:\n"
            + "\n".join(f"- {p}" for p in essay["points"])
            + f"\n\n{essay.get('notes', '')}"
        )
    opt = _get_part2_option(ctx, option_id)
    if not opt:
        return ""
    return f"{opt['task']}\n\n{opt['prompt']}"


def _drafts_for_current_tasks(ctx: dict) -> dict:
    owner_key, _user_id = get_writing_owner_key()
    part1_snapshot = _task_snapshot(ctx, 1)
    drafts = {
        "part1": get_writing_draft(owner_key, 1, "", writing_task_key(part1_snapshot)),
        "part2": {},
    }
    for opt in ctx["part2_options"]:
        snapshot = _task_snapshot(ctx, 2, opt["id"])
        drafts["part2"][opt["id"]] = get_writing_draft(owner_key, 2, opt["id"], writing_task_key(snapshot))
    return drafts


def _record_writing_result(part: int, feedback: dict) -> None:
    """Persist AI writing feedback as a saved practice score."""
    if part not in WRITING_HISTORY_PARTS:
        return
    if not any(key in feedback for key in ("content", "communicative_achievement", "organisation", "language", "comment")):
        return
    try:
        score = float(feedback.get("overall", 0))
    except (TypeError, ValueError):
        return
    score = max(0, min(5, round(score)))
    record_check_result({
        "part": WRITING_HISTORY_PARTS[part],
        "score": score,
        "total": 5,
        "details": [],
    })


def _build_writing_prompt(part: int, task_desc: str, answer: str) -> str:
    return (
        "You are a Cambridge English B2 First (FCE) Writing examiner.\n"
        f"Part {part} candidate answer should be 140–190 words.\n\n"
        "Evaluate the answer for:\n"
        "1) Content\n"
        "2) Communicative achievement\n"
        "3) Organisation\n"
        "4) Language\n\n"
        "Give scores from 0 to 5 for each category and an overall score from 0 to 5.\n"
        "Then give practical feedback a B2 student can immediately use. Be specific and quote only short "
        "student fragments when needed.\n\n"
        "After the feedback, provide two complete improved answers:\n"
        "- student_improved_version: improve the student's own draft while preserving their ideas, voice, "
        "and structure as much as possible. Correct grammar, spelling, vocabulary, linking, and task coverage.\n"
        "- ai_improved_version: write your own strong B2 First model answer for the same task. It may reorganise "
        "the ideas and add a clear missing point if needed, but it must still stay at B2 level and within 140-190 words.\n\n"
        "TASK (what the student was asked to write):\n"
        f"\n{task_desc}\n\n"
        "STUDENT ANSWER:\n"
        f"\n{answer}\n\n"
        "Respond ONLY in strict JSON with this shape:\n"
        "{\n"
        '  "overall": 0-5 number,\n'
        '  "content": 0-5 number,\n'
        '  "communicative_achievement": 0-5 number,\n'
        '  "organisation": 0-5 number,\n'
        '  "language": 0-5 number,\n'
        '  "comment": "short summary paragraph",\n'
        '  "student_improved_version": "complete improved version of the student answer",\n'
        '  "ai_improved_version": "complete model answer written by the examiner",\n'
        '  "missing_task_points": ["task point or requirement the student missed"],\n'
        '  "grammar_corrections": [\n'
        '    {"original": "student fragment", "corrected": "corrected fragment", "explanation": "brief reason"}\n'
        "  ],\n"
        '  "better_sentence_examples": [\n'
        '    {"original": "student sentence", "improved": "better B2 sentence", "reason": "why it is better"}\n'
        "  ],\n"
        '  "vocabulary_upgrades": [\n'
        '    {"original": "simple word or phrase", "upgraded": "more precise B2 phrase", "reason": "when to use it"}\n'
        "  ],\n"
        '  "organisation_advice": ["concrete paragraphing or linking advice"],\n'
        '  "rewrite_suggestion": {\n'
        '    "original": "one weak paragraph or sentence from the answer",\n'
        '    "improved": "rewritten improved version",\n'
        '    "reason": "what changed and why"\n'
        "  }\n"
        "}\n"
    )


def _save_draft_for_answer(ctx: dict, part: int, option_id: str, answer: str) -> dict | None:
    task = _task_snapshot(ctx, part, option_id)
    owner_key, user_id = get_writing_owner_key()
    return save_writing_draft(
        owner_key=owner_key,
        user_id=user_id,
        part=part,
        option_id=option_id if part == 2 else "",
        task_key=writing_task_key(task),
        task_snapshot=task,
        answer=answer,
    )


@bp.route("/writing/task-image/<token>")
def task_image(token):
    """Serve the task image PNG for the given token (from cache). Only the owning session can access."""
    if session.get("writing_task_token") != token:
        return Response(status=403)
    png = _TASK_IMAGE_CACHE.get(token)
    if not png:
        return Response(status=404)
    return Response(png, mimetype="image/png", headers={"Cache-Control": "private, max-age=3600"})


@bp.post("/api/writing/draft")
def save_writing_draft_api():
    ctx = get_writing_context()
    payload = request.get_json(silent=True) or {}
    part = payload.get("part")
    try:
        part = int(part)
    except (TypeError, ValueError):
        part = 0
    if part not in (1, 2):
        return jsonify({"ok": False, "error": "Invalid writing part."}), 400
    option_id = (payload.get("option_id") or "").strip().lower()
    if part == 2 and not _get_part2_option(ctx, option_id):
        return jsonify({"ok": False, "error": "Invalid writing option."}), 400
    answer = str(payload.get("answer") or "")
    draft = _save_draft_for_answer(ctx, part, option_id, answer)
    return jsonify({"ok": True, "updated_at": draft["updated_at"] if draft else ""})


@bp.route("/writing", methods=["GET", "POST"])
def writing():
    ctx = get_writing_context()
    ctx["active_part"] = 1
    ctx["active_option_id"] = ""
    ctx["part1_feedback"] = None
    ctx["part2_feedback"] = {}
    ctx["writing_error"] = ""
    ctx["ai_feedback_available"] = ai_available

    if request.method == "POST":
        action = request.form.get("action") or ""
        if action == "generate":
            essay = _generate_essay_task_with_ai()
            if essay:
                session["writing_essay_prompt"] = essay
                session.pop("writing_task_token", None)
            else:
                get_writing_context(reset=True)
            ctx = get_writing_context()
            token = _ensure_task_image(ctx["essay_prompt"])
            session["writing_task_token"] = token
            return redirect(url_for("writing.writing"))

        part = request.form.get("part", type=int)
        text = (request.form.get("answer") or "").strip()
        option_id = (request.form.get("option_id") or "").strip().lower()
        ctx["active_part"] = part if part in (1, 2) else 1
        ctx["active_option_id"] = option_id
        if part in (1, 2):
            _save_draft_for_answer(ctx, part, option_id, text)
        if action == "check" and part in (1, 2):
            if part == 2 and not _get_part2_option(ctx, option_id):
                ctx["writing_error"] = "Choose a valid Part 2 task before checking."
            elif not text:
                ctx["writing_error"] = "Write your answer before checking."
            elif not ai_available:
                fb = _normalise_feedback({
                    "raw_text": "AI feedback is unavailable. Configure API key.",
                    "comment": "AI feedback is unavailable. Configure API key.",
                    "overall": 0,
                })
                if part == 1:
                    ctx["part1_feedback"] = fb
                else:
                    ctx["part2_feedback"][option_id] = fb
                ctx["writing_error"] = "AI feedback is unavailable. Configure API key."
                task = _task_snapshot(ctx, part, option_id)
                owner_key, user_id = get_writing_owner_key()
                save_writing_attempt(
                    owner_key,
                    user_id,
                    part,
                    option_id if part == 2 else "",
                    writing_task_key(task),
                    task,
                    text,
                    fb,
                    _word_count(text),
                )
            elif _word_count(text) < 20:
                fb = _normalise_feedback({
                    "raw_text": "Your answer is too short to evaluate. Please write more before checking.",
                    "comment": "Your answer is too short to evaluate. Please write more before checking.",
                    "overall": 0,
                })
                task = _task_snapshot(ctx, part, option_id)
                owner_key, user_id = get_writing_owner_key()
                save_writing_attempt(
                    owner_key,
                    user_id,
                    part,
                    option_id if part == 2 else "",
                    writing_task_key(task),
                    task,
                    text,
                    fb,
                    _word_count(text),
                )
                if part == 1:
                    ctx["part1_feedback"] = fb
                else:
                    ctx["part2_feedback"][option_id] = fb
            else:
                task_desc = _task_description(ctx, part, option_id)
                prompt = _build_writing_prompt(part, task_desc, text)
                try:
                    comp = chat_create([{"role": "user", "content": prompt}], temperature=0.4)
                    content = (comp.choices[0].message.content or "").strip()
                    fb = _parse_feedback(content) or {"raw_text": content}
                except Exception:
                    fb = _normalise_feedback({
                        "raw_text": "Sorry, the AI is temporarily unavailable. Please try again in a moment.",
                        "comment": "Sorry, the AI is temporarily unavailable. Please try again in a moment.",
                        "overall": 0,
                    })
                fb = _normalise_feedback(fb)
                fb.setdefault("overall", fb.get("overall", 0))
                task = _task_snapshot(ctx, part, option_id)
                task_key = writing_task_key(task)
                owner_key, user_id = get_writing_owner_key()
                stored_option_id = option_id if part == 2 else ""
                if not has_scored_writing_attempt(owner_key, part, stored_option_id, task_key):
                    _record_writing_result(part, fb)
                save_writing_attempt(
                    owner_key,
                    user_id,
                    part,
                    stored_option_id,
                    task_key,
                    task,
                    text,
                    fb,
                    _word_count(text),
                )
                if part == 1:
                    ctx["part1_feedback"] = fb
                else:
                    ctx["part2_feedback"][option_id] = fb

    ctx["task_token"] = _ensure_task_image(ctx["essay_prompt"])
    ctx["writing_drafts"] = _drafts_for_current_tasks(ctx)
    return render_template("writing.html", **ctx)
