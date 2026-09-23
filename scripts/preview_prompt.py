#!/usr/bin/env python3
"""Show exactly which examples RAG retrieves and the prompt sent to the LLM.

This makes no AI call, so it is free and instant. Use it to answer "what did we
actually send?" for any part and topic.

Examples:
    # Retrieval + the exact prompt for Part 1
    python -m scripts.preview_prompt --part 1 --topic "a comedian's worst gig"

    # List the built-in topics so you can preview realistic requests
    python -m scripts.preview_prompt --list-topics --part 1

    # Just the retrieved examples, with their full text
    python -m scripts.preview_prompt --part 5 --topic "space travel" --examples-only

    # Write the prompt to a file for diffing
    python -m scripts.preview_prompt --part 2 --topic "city life" --save prompt.txt
"""
from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from dotenv import load_dotenv

load_dotenv()

os.environ["FLASK_DEBUG"] = "0"

import logging  # noqa: E402

from app.rag.db import rag_db_path  # noqa: E402
from app.rag.embeddings import active_backend, active_model_name  # noqa: E402
from app.rag.helpers import _PART_RAG_MAP, describe_examples  # noqa: E402
from app.rag.retrieval import retrieve_examples  # noqa: E402
from app.rag.store import count_examples, ensure_rag_tables  # noqa: E402

logging.getLogger().setLevel(logging.WARNING)

# Part -> (prompt builder, whether it needs a topic)
PROMPT_BUILDERS = {
    1: "get_task_prompt_part1",
    2: "get_task_prompt_part2",
    3: "get_task_prompt_part3",
    4: "get_task_prompt_part4",
    5: "get_task_prompt_part5",
    6: "get_task_prompt_part6",
    7: "get_task_prompt_part7",
    8: "get_task_prompt_get_phrases",
}

TOPIC_CONSTANTS = {
    1: "PART1_TOPICS",
    2: "PART2_TOPICS",
    3: "PART3_TOPICS",
    5: "PART5_TOPICS",
    6: "PART6_TOPICS",
    7: "PART7_TOPICS",
}


def list_topics(part: int | None) -> int:
    from app.parts import topics as topic_module

    wanted = [part] if part else sorted(TOPIC_CONSTANTS)
    for number in wanted:
        name = TOPIC_CONSTANTS.get(number)
        if not name:
            print(f"Part {number}: no topic list (uses other inputs)")
            continue
        values = getattr(topic_module, name, [])
        print(f"--- Part {number}: {len(values)} topics ---")
        for topic in values:
            print(f"  {topic}")
    return 0


def build_prompt(part: int, topic: str, level: str, ref_examples: str) -> str:
    """Build the same prompt the app would send, without calling the model."""
    from app.ai import prompts as prompt_module

    builder = getattr(prompt_module, PROMPT_BUILDERS[part])
    if part == 8:
        return builder(level=level, ref_examples=ref_examples)
    if part == 4:
        return builder(6, level=level, ref_examples=ref_examples)
    return builder(topic, level=level, ref_examples=ref_examples)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Inspect RAG retrieval and the LLM prompt without making an AI call.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--part", type=int, choices=sorted(PROMPT_BUILDERS),
                        help="FCE part number (1-8)")
    parser.add_argument("--topic", default="", help="Generation topic")
    parser.add_argument("--level", default="b2", help="b2 or b2plus (default b2)")
    parser.add_argument("--k", type=int, default=3, help="How many examples to retrieve")
    parser.add_argument("--show-examples", action="store_true",
                        help="Print the full text of each retrieved example")
    parser.add_argument("--examples-only", action="store_true",
                        help="Print only the retrieval section, not the prompt")
    parser.add_argument("--no-examples", action="store_true",
                        help="Build the prompt without RAG references")
    parser.add_argument("--save", metavar="FILE", help="Write the prompt to a file")
    parser.add_argument("--list-topics", action="store_true",
                        help="List the built-in topics and exit")
    args = parser.parse_args()

    if args.list_topics:
        return list_topics(args.part)
    if not args.part:
        parser.error("--part is required (or use --list-topics)")

    ensure_rag_tables()
    paper, task_type = _PART_RAG_MAP.get(args.part, ("use_of_english", ""))

    print(f"RAG database : {rag_db_path()}")
    print(f"Corpus size  : {count_examples()} examples")
    print(f"Embeddings   : {active_backend()} {active_model_name()}")
    print(f"Query        : part={args.part} paper={paper} task_type={task_type} "
          f"topic={args.topic!r} k={args.k}")
    print()

    examples = []
    if not args.no_examples:
        examples = retrieve_examples(paper=paper, part=args.part, topic=args.topic,
                                     task_type=task_type, k=args.k)

    print(f"=== RETRIEVED {len(examples)} EXAMPLE(S) ===")
    if not examples:
        print("  (none — the prompt will be sent without RAG references)")
    for line in describe_examples(examples):
        print(f"  {line}")
    if args.show_examples or args.examples_only:
        for index, example in enumerate(examples, 1):
            print(f"\n----- example #{index}: {example.get('topic')} "
                  f"(id={example.get('id')}) -----")
            print(example.get("prompt_text", ""))

    if args.examples_only:
        return 0

    from app.rag.retrieval import format_examples_for_prompt

    ref_examples = format_examples_for_prompt(examples) if examples else ""
    prompt = build_prompt(args.part, args.topic, args.level, ref_examples)

    print(f"\n=== PROMPT SENT TO THE MODEL ({len(prompt)} chars) ===")
    print(prompt)

    if args.save:
        Path(args.save).write_text(prompt, encoding="utf-8")
        print(f"\nSaved prompt to {args.save}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
