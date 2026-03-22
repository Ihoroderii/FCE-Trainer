"""Convenience function for getting RAG examples in generation functions.

Maps FCE part numbers to RAG paper/task_type metadata.
"""
from __future__ import annotations

import logging

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
            return format_examples_for_prompt(examples)
    except Exception:
        logger.debug("RAG retrieval not available (part %d)", part, exc_info=True)
    return ""
