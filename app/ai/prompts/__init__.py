"""AI prompts: task generation and chat (answer explanations). Kept in separate modules for clarity and accuracy."""

from app.ai.prompts.task_generation import (
    get_task_prompt_part1,
    get_task_prompt_part2,
    get_task_prompt_part3,
    get_task_prompt_part4,
    get_task_prompt_part5,
    get_task_prompt_part6,
    get_task_prompt_part7,
    get_task_prompt_get_phrases,
)
from app.ai.prompts.chat_explanations import (
    get_explanation_prompt_part1,
    get_explanation_prompt_part2,
    get_explanation_prompt_part3,
    get_explanation_prompt_part4,
    get_explanation_prompt_part5,
    get_explanation_prompt_part6,
    get_explanation_prompt_part7,
    get_explanation_prompt_get_phrases,
)

__all__ = [
    "get_task_prompt_part1",
    "get_task_prompt_part2",
    "get_task_prompt_part3",
    "get_task_prompt_part4",
    "get_task_prompt_part5",
    "get_task_prompt_part6",
    "get_task_prompt_part7",
    "get_task_prompt_get_phrases",
    "get_explanation_prompt_part1",
    "get_explanation_prompt_part2",
    "get_explanation_prompt_part3",
    "get_explanation_prompt_part4",
    "get_explanation_prompt_part5",
    "get_explanation_prompt_part6",
    "get_explanation_prompt_part7",
    "get_explanation_prompt_get_phrases",
]
