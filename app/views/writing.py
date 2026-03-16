"""Writing section: essay + Part 2 options."""
from __future__ import annotations

import io
import json
import re
import secrets

from flask import Blueprint, Response, redirect, render_template, request, session, url_for

from app.ai import ai_available, chat_create
from app.config import WRITING_MIN_WORDS, WRITING_MAX_WORDS
from app.services.writing import get_writing_context
from app.utils import extract_json_object

bp = Blueprint("writing", __name__)

# In-memory cache: task_token -> PNG bytes. Evict oldest when over limit.
_TASK_IMAGE_CACHE = {}
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
    try:
        font = ImageFont.truetype("/System/Library/Fonts/Helvetica.ttc", font_size)
        font_bold = ImageFont.truetype("/System/Library/Fonts/Helvetica.ttc", font_size)
    except (OSError, TypeError):
        try:
            font = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", font_size)
            font_bold = font
        except (OSError, TypeError):
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
        while len(_TASK_IMAGE_CACHE) >= _MAX_TASK_IMAGES and _TASK_IMAGE_CACHE:
            _TASK_IMAGE_CACHE.pop(next(iter(_TASK_IMAGE_CACHE)))
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
        data.setdefault("raw_text", raw)
        return data
    return {"raw_text": raw}


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
        "Then give short, concrete advice on how to improve.\n\n"
        "TASK (what the student was asked to write):\n"
        f"\n{task_desc}\n\n"
        "STUDENT ANSWER:\n"
        f"\n{answer}\n\n"
        "Respond ONLY in strict JSON with this shape:\n"
        "{\n"
        '  \"overall\": 0-5 number,\n'
        '  \"content\": 0-5 number,\n'
        '  \"communicative_achievement\": 0-5 number,\n'
        '  \"organisation\": 0-5 number,\n'
        '  \"language\": 0-5 number,\n'
        '  \"comment\": \"short paragraph with feedback\"\n'
        "}\n"
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


@bp.route("/writing", methods=["GET", "POST"])
def writing():
    ctx = get_writing_context()
    ctx["active_part"] = 1
    ctx["part1_feedback"] = None
    ctx["part2_feedback"] = {}

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
        ctx["active_part"] = part if part in (1, 2) else 1
        if action == "check" and text and ai_available and part in (1, 2):
            if len(text.split()) < 20:
                fb = {
                    "raw_text": "Your answer is too short to evaluate. Please write more before checking.",
                    "overall": 0,
                }
            else:
                if part == 1:
                    essay = ctx["essay_prompt"]
                    task_desc = (
                        f"{essay['question']}\n\nPoints to cover:\n"
                        + "\n".join(f"- {p}" for p in essay["points"])
                    )
                else:
                    opt_id = (request.form.get("option_id") or "").strip().lower()
                    opt = next((o for o in ctx["part2_options"] if o["id"] == opt_id), None)
                    task_desc = ""
                    if opt:
                        task_desc = f"{opt['task']}\n\n{opt['prompt']}"
                prompt = _build_writing_prompt(part, task_desc, text)
                comp = chat_create([{"role": "user", "content": prompt}], temperature=0.4)
                content = (comp.choices[0].message.content or "").strip()
                fb = _parse_feedback(content) or {"raw_text": content}
            fb.setdefault("overall", fb.get("overall", 0))
            if part == 1:
                ctx["part1_feedback"] = fb
            else:
                opt_id = (request.form.get("option_id") or "").strip().lower()
                if opt_id:
                    ctx["part2_feedback"][opt_id] = fb

    ctx["task_token"] = _ensure_task_image(ctx["essay_prompt"])
    return render_template("writing.html", **ctx)
