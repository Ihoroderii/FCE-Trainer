"""Part registry: CHECKERS, task config, generate config, error messages, and re-exports."""
from flask import session

from app.config import PARTS_RANGE, PART_QUESTION_COUNTS
from app.db import get_task_by_id_for_part, get_tasks_by_ids

from . import part1, part2, part3, part4, part5, part6, part7

PARTS = {1: part1, 2: part2, 3: part3, 4: part4, 5: part5, 6: part6, 7: part7}

CHECKERS = {
    1: part1.check_part1,
    2: part2.check_part2,
    3: part3.check_part3,
    4: part4.check_part4,
    5: part5.check_part5,
    6: part6.check_part6,
    7: part7.check_part7,
}

_PART_TASK_CONFIG = {
    2: ("part2_task_id", part2.get_or_create_part2_item, lambda tid: get_task_by_id_for_part(2, tid)),
    3: ("part3_task_id", part3.get_or_create_part3_item, lambda tid: get_task_by_id_for_part(3, tid)),
    5: ("part5_task_id", part5.get_or_create_part5_item, lambda tid: get_task_by_id_for_part(5, tid)),
    6: ("part6_task_id", part6.get_or_create_part6_item, lambda tid: get_task_by_id_for_part(6, tid)),
    7: ("part7_task_id", part7.get_or_create_part7_item, lambda tid: get_task_by_id_for_part(7, tid)),
}

_GENERATE_CONFIG = {
    1: {"fn": lambda level: part1.generate_part1_with_openai(level=level), "session_key": "part1_task_id", "default_level": "b2", "extra_cleanup": ["part1_task"]},
    2: {"fn": lambda level: part2.generate_part2_with_openai(level=level), "session_key": "part2_task_id", "default_level": "b2"},
    3: {"fn": lambda level: part3.generate_part3_with_openai(level=level), "session_key": "part3_task_id", "default_level": "b2"},
    5: {"fn": lambda level: part5.generate_part5_with_openai(), "session_key": "part5_task_id", "default_level": "b2"},
    6: {"fn": lambda level: part6.generate_part6_with_openai(), "session_key": "part6_task_id", "default_level": "b2"},
    7: {"fn": lambda level: part7.generate_part7_with_openai(), "session_key": "part7_task_id", "default_level": "b2"},
}

_PART_ERROR_MSGS = {
    1: "No tasks available. Set OPENAI_API_KEY to generate new tasks (database is seeded with 2 sample tasks).",
    2: "No Part 2 tasks in database. Set OPENAI_API_KEY to generate new open cloze texts.",
    3: "No Part 3 tasks available. Set OPENAI_API_KEY to generate new word-formation texts (150-200 words, 8 gaps).",
    5: "No Part 5 tasks in database. Set OPENAI_API_KEY to generate new texts and questions.",
    6: "No Part 6 tasks in database. Set OPENAI_API_KEY to generate new gapped texts.",
    7: "No Part 7 tasks in database. Set OPENAI_API_KEY to generate new multiple-matching texts (600-700 words, 10 questions).",
}


def _ensure_part_task(part, exclude_task_id=None):
    if part not in _PART_TASK_CONFIG:
        return None, None
    key, get_or_create, get_by_id = _PART_TASK_CONFIG[part]
    if not session.get(key):
        _, tid = get_or_create(exclude_task_id=exclude_task_id)
        if tid:
            session[key] = tid
    tid = session.get(key)
    return (get_by_id(tid) if tid else None, tid)


# Re-exports for views
def get_part1_task_by_id(tid):
    return get_task_by_id_for_part(1, tid)


__all__ = [
    "PARTS",
    "CHECKERS",
    "_PART_TASK_CONFIG",
    "_GENERATE_CONFIG",
    "_PART_ERROR_MSGS",
    "_ensure_part_task",
    "get_part1_task_by_id",
    "get_tasks_by_ids",
    "fetch_part4_tasks",
    "build_part1_html",
    "build_part2_html",
    "build_part3_html",
    "build_part4_html",
    "build_part5_text",
    "build_part5_html",
    "build_part6_text",
    "build_part6_questions",
    "build_part7_text",
    "build_part7_questions",
    "get_or_create_part1_task",
]

fetch_part4_tasks = part4.fetch_part4_tasks
build_part1_html = part1.build_part1_html
build_part2_html = part2.build_part2_html
build_part3_html = part3.build_part3_html
build_part4_html = part4.build_part4_html
build_part5_text = part5.build_part5_text
build_part5_html = part5.build_part5_html
build_part6_text = part6.build_part6_text
build_part6_questions = part6.build_part6_questions
build_part7_text = part7.build_part7_text
build_part7_questions = part7.build_part7_questions
get_or_create_part1_task = part1.get_or_create_part1_task
