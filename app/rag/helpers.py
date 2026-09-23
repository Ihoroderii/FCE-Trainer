"""Convenience function for getting RAG examples in generation functions.

Maps FCE part numbers to RAG paper/task_type metadata.
"""
from __future__ import annotations

import logging
import os

logger = logging.getLogger("fce_trainer")

# Maps part number → (paper, task_type) for RAG retrieval
_PART_RAG_MAP = {
    1: ("use_of_english", "multiple_choice_cloze"),
    2: ("use_of_english", "open_cloze"),
    3: ("use_of_english", "word_formation"),
    4: ("use_of_english", "key_word_transformation"),
    5: ("reading", "multiple_choice"),
    6: ("reading", "gapped_text"),
    7: ("reading", "multiple_matching"),
    8: ("use_of_english", "get_phrases"),  # special "get phrases" mode
}


def prompts_logging_enabled() -> bool:
    """True when LOG_AI_PROMPTS is set, meaning log full prompts and examples."""
    return (os.environ.get("LOG_AI_PROMPTS") or "").strip().lower() in ("1", "true", "yes", "on")


def describe_examples(examples: list[dict]) -> list[str]:
    """One short line per retrieved example, for logs.

    Includes how it was found (semantic similarity vs keyword fallback) and the
    score, so a log reader can tell a real match from a degraded fallback.
    """
    described = []
    for index, example in enumerate(examples, 1):
        meta = example.get("metadata") or {}
        page = meta.get("source_page")
        mode = example.get("retrieval")
        score = example.get("score")
        detail = ""
        if mode == "embedding" and score is not None:
            detail = f" similarity={score}"
        elif mode == "keyword" and score is not None:
            detail = f" keyword_overlap={score}"
        described.append(
            f"#{index} id={example.get('id')} part={example.get('part')} "
            f"topic={example.get('topic')!r}"
            + (f" source_page={page}" if page else "")
            + f" chars={len(example.get('prompt_text') or '')}"
            + detail
        )
    return described


def get_rag_examples_text(part: int, topic: str = "") -> str:
    """Retrieve RAG examples for a given part and format them for prompt injection.

    Returns empty string if no examples are available (so generation works without RAG).
    This is safe to call even if the RAG tables are empty.
    """
    try:
        from app.rag.retrieval import retrieve_examples, format_examples_for_prompt

        paper, task_type = _PART_RAG_MAP.get(part, ("use_of_english", ""))
        examples = retrieve_examples(paper=paper, part=part, topic=topic, task_type=task_type)
        if examples:
            logger.info("RAG: retrieved %d examples for part %d (topic=%s)", len(examples), part, topic)
            # With LOG_AI_PROMPTS on, name the examples and include their text so a
            # generation can be traced end to end from the log alone.
            if prompts_logging_enabled():
                logger.info("RAG: selected examples:\n  %s",
                            "\n  ".join(describe_examples(examples)))
                for index, example in enumerate(examples, 1):
                    logger.info("RAG: example #%d full text:\n%s",
                                index, example.get("prompt_text", ""))
            return format_examples_for_prompt(examples)
    except Exception:
        logger.debug("RAG retrieval not available (part %d)", part, exc_info=True)
    return ""
