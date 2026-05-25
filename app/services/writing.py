"""Writing section: essay prompts, Part 2 options, drafts, and attempts."""
import hashlib
import json
import random
import secrets

from flask import session

from app.config import WRITING_MIN_WORDS, WRITING_MAX_WORDS, WRITING_TOTAL_MINUTES
from app.db import db_connection

WRITING_ESSAY_PROMPTS = [
    {
        "question": "In your English class you have been talking about different ways of travelling. Now your teacher has asked you to write an essay.",
        "points": [
            "Why people like to visit other countries",
            "Whether it is better to travel alone or with other people",
        ],
        "notes": "Write about 140–190 words. Write the essay using all the notes and give reasons for your point of view.",
    },
    {
        "question": "In your English class you have been talking about the environment. Now your teacher has asked you to write an essay.",
        "points": [
            "Why many people prefer to use their car instead of public transport",
            "How we can encourage people to use public transport more",
        ],
        "notes": "Write about 140–190 words. Write the essay using all the notes and give reasons for your point of view.",
    },
    {
        "question": "In your English class you have been talking about where people live. Now your teacher has asked you to write an essay.",
        "points": [
            "Why some people prefer to live in a city",
            "Why some people prefer to live in the countryside",
        ],
        "notes": "Write about 140–190 words. Write the essay using all the notes and give reasons for your point of view.",
    },
]

WRITING_PART2_OPTIONS = [
    {
        "id": "a",
        "type": "Article",
        "task": "You see this announcement in an international magazine.",
        "prompt": """TRAVEL STORIES WANTED

We want to hear about a journey you have made. It could be a short trip or a longer adventure.

Write an article about your journey. Describe where you went, what you did and why you enjoyed it.

Write your article in 140–190 words.""",
    },
    {
        "id": "b",
        "type": "Letter / email",
        "task": "You have received an email from your English-speaking friend, Sam, who is planning to stay in your country for a month.",
        "prompt": """From: Sam
Subject: Visit

I'm really excited about my trip. Can you tell me what the weather will be like when I'm there? And what should I pack? Also, I'd love to try some typical food – what do you recommend?

Thanks!
Sam

Write your email in 140–190 words. You must use the following words: recommend, weather, pack.""",
    },
    {
        "id": "c",
        "type": "Report",
        "task": "Your teacher has asked you to write a report on facilities for young people in your town or city.",
        "prompt": """The report should mention:
• what sports facilities exist
• what other leisure facilities exist
• how these could be improved

Write your report in 140–190 words.""",
    },
]


def get_writing_context(reset=False):
    """Return current writing prompts. If reset=True, pick new essay and reshuffle Part 2."""
    if reset:
        session.pop("writing_essay_prompt", None)
        session.pop("writing_part2_options", None)
    if "writing_essay_prompt" not in session:
        session["writing_essay_prompt"] = random.choice(WRITING_ESSAY_PROMPTS)
    essay = session["writing_essay_prompt"]

    if "writing_part2_options" not in session:
        opts = list(WRITING_PART2_OPTIONS)
        random.shuffle(opts)
        session["writing_part2_options"] = opts
    part2_options = session["writing_part2_options"]

    return {
        "essay_prompt": essay,
        "part2_options": part2_options,
        "word_min": WRITING_MIN_WORDS,
        "word_max": WRITING_MAX_WORDS,
        "total_minutes": WRITING_TOTAL_MINUTES,
    }


def get_writing_owner_key() -> tuple[str, int | None]:
    """Return a stable owner for logged-in users or the current anonymous session."""
    user_id = session.get("user_id")
    if user_id:
        try:
            return f"user:{int(user_id)}", int(user_id)
        except (TypeError, ValueError):
            pass
    client_id = session.get("writing_client_id")
    if not client_id:
        client_id = secrets.token_urlsafe(24)
        session["writing_client_id"] = client_id
    return f"session:{client_id}", None


def writing_task_key(task_snapshot: dict) -> str:
    """Create a stable key so drafts are tied to the task the student is answering."""
    payload = json.dumps(task_snapshot or {}, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:20]


def _json_dumps(value: dict) -> str:
    return json.dumps(value or {}, sort_keys=True, ensure_ascii=True)


def save_writing_draft(
    owner_key: str,
    user_id: int | None,
    part: int,
    option_id: str,
    task_key: str,
    task_snapshot: dict,
    answer: str,
) -> dict | None:
    """Upsert the current in-progress writing answer."""
    answer = (answer or "")[:30000]
    option_id = (option_id or "").strip().lower()
    with db_connection() as conn:
        conn.execute(
            """
            INSERT INTO writing_drafts
                (owner_key, user_id, part, option_id, task_key, task_json, answer, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, datetime('now'))
            ON CONFLICT(owner_key, part, option_id, task_key) DO UPDATE SET
                user_id = excluded.user_id,
                task_json = excluded.task_json,
                answer = excluded.answer,
                updated_at = datetime('now')
            """,
            (owner_key, user_id, part, option_id, task_key, _json_dumps(task_snapshot), answer),
        )
        conn.commit()
    return get_writing_draft(owner_key, part, option_id, task_key)


def get_writing_draft(owner_key: str, part: int, option_id: str, task_key: str) -> dict | None:
    option_id = (option_id or "").strip().lower()
    with db_connection() as conn:
        row = conn.execute(
            """
            SELECT id, owner_key, user_id, part, option_id, task_key, task_json, answer, updated_at
            FROM writing_drafts
            WHERE owner_key = ? AND part = ? AND option_id = ? AND task_key = ?
            LIMIT 1
            """,
            (owner_key, part, option_id, task_key),
        ).fetchone()
    return dict(row) if row else None


def save_writing_attempt(
    owner_key: str,
    user_id: int | None,
    part: int,
    option_id: str,
    task_key: str,
    task_snapshot: dict,
    answer: str,
    feedback: dict,
    word_count: int,
) -> int:
    """Store a checked writing attempt with the answer and feedback shown to the student."""
    answer = (answer or "")[:30000]
    option_id = (option_id or "").strip().lower()
    with db_connection() as conn:
        cur = conn.execute(
            """
            INSERT INTO writing_attempts
                (owner_key, user_id, part, option_id, task_key, task_json, answer, feedback_json, word_count)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                owner_key,
                user_id,
                part,
                option_id,
                task_key,
                _json_dumps(task_snapshot),
                answer,
                _json_dumps(feedback),
                max(0, int(word_count or 0)),
            ),
        )
        conn.commit()
        return int(cur.lastrowid)
