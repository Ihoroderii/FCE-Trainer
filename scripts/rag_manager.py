#!/usr/bin/env python3
"""CLI tool for managing RAG examples in the FCE-Trainer.

Usage:
    python -m scripts.rag_manager add --paper use_of_english --part 1 --type multiple_choice_cloze --topic "travel" --file example.txt
    python -m scripts.rag_manager add --paper use_of_english --part 2 --type open_cloze --topic "technology" --text "Your task text here..."
    python -m scripts.rag_manager add-json examples.json
    python -m scripts.rag_manager list [--paper X] [--part N]
    python -m scripts.rag_manager show <id>
    python -m scripts.rag_manager delete <id>
    python -m scripts.rag_manager rebuild-embeddings
    python -m scripts.rag_manager stats
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

# Ensure project root is in path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from dotenv import load_dotenv
load_dotenv()

from app.rag.store import ensure_rag_tables, add_example, get_example, list_examples, delete_example, count_examples
from app.rag.embeddings import rebuild_embeddings


def cmd_add(args):
    """Add a single example."""
    if args.file:
        prompt_text = Path(args.file).read_text(encoding="utf-8").strip()
    elif args.text:
        prompt_text = args.text.strip()
    else:
        print("Error: provide --text or --file")
        sys.exit(1)

    metadata = {}
    if args.target_reader:
        metadata["target_reader"] = args.target_reader
    if args.purpose:
        metadata["purpose"] = args.purpose
    if args.word_limit:
        metadata["word_limit"] = args.word_limit

    ensure_rag_tables()
    eid = add_example(
        paper=args.paper,
        part=args.part,
        task_type=args.type or "",
        topic=args.topic or "",
        prompt_text=prompt_text,
        level=args.level or "b2",
        metadata=metadata if metadata else None,
    )
    print(f"Added example id={eid}")
    print(f"Run 'python -m scripts.rag_manager rebuild-embeddings' to compute embeddings.")


def cmd_add_json(args):
    """Bulk-add examples from a JSON file.

    Expected format: array of objects with keys:
      paper, part, task_type, topic, prompt_text, level (optional),
      metadata (optional dict), search_text (optional)
    """
    data = json.loads(Path(args.file).read_text(encoding="utf-8"))
    if not isinstance(data, list):
        print("Error: JSON file must contain an array of objects")
        sys.exit(1)

    ensure_rag_tables()
    added = 0
    for item in data:
        try:
            add_example(
                paper=item["paper"],
                part=item["part"],
                task_type=item.get("task_type", ""),
                topic=item.get("topic", ""),
                prompt_text=item["prompt_text"],
                level=item.get("level", "b2"),
                metadata=item.get("metadata"),
                search_text=item.get("search_text"),
            )
            added += 1
        except Exception as e:
            print(f"Skipped item: {e}")

    print(f"Added {added}/{len(data)} examples")
    print(f"Run 'python -m scripts.rag_manager rebuild-embeddings' to compute embeddings.")


def cmd_list(args):
    """List examples with optional filters."""
    ensure_rag_tables()
    examples = list_examples(paper=args.paper, part=args.part, task_type=args.type)
    if not examples:
        print("No examples found.")
        return
    print(f"{'ID':>4}  {'Paper':<18} {'Part':>4}  {'Type':<25} {'Topic':<20} {'Chars':>5}")
    print("-" * 82)
    for ex in examples:
        print(f"{ex['id']:>4}  {ex['paper']:<18} {ex['part']:>4}  {ex.get('task_type',''):<25} {ex.get('topic',''):<20} {len(ex.get('prompt_text','')):>5}")


def cmd_show(args):
    """Show a single example."""
    ensure_rag_tables()
    ex = get_example(args.id)
    if not ex:
        print(f"Example {args.id} not found.")
        return
    print(f"ID:        {ex['id']}")
    print(f"Paper:     {ex['paper']}")
    print(f"Part:      {ex['part']}")
    print(f"Type:      {ex.get('task_type', '')}")
    print(f"Topic:     {ex.get('topic', '')}")
    print(f"Level:     {ex.get('level', '')}")
    print(f"Metadata:  {ex.get('metadata', {})}")
    print(f"Created:   {ex.get('created_at', '')}")
    print(f"\n--- Prompt Text ---")
    print(ex["prompt_text"])
    print(f"\n--- Search Text ---")
    print(ex.get("search_text", ""))


def cmd_delete(args):
    """Delete an example."""
    ensure_rag_tables()
    if delete_example(args.id):
        print(f"Deleted example {args.id}")
    else:
        print(f"Example {args.id} not found.")


def cmd_rebuild(args):
    """Compute/update embeddings for all examples missing them."""
    ensure_rag_tables()
    updated = rebuild_embeddings()
    print(f"Updated {updated} embeddings.")


def cmd_stats(args):
    """Show RAG example counts by paper and part."""
    ensure_rag_tables()
    all_examples = list_examples()
    if not all_examples:
        print("No examples in database.")
        return

    from collections import Counter
    by_paper = Counter()
    by_part = Counter()
    for ex in all_examples:
        by_paper[ex["paper"]] += 1
        by_part[(ex["paper"], ex["part"])] += 1

    print(f"Total examples: {len(all_examples)}\n")
    print(f"{'Paper':<20} {'Part':>4}  {'Count':>5}")
    print("-" * 35)
    for (paper, part), cnt in sorted(by_part.items()):
        print(f"{paper:<20} {part:>4}  {cnt:>5}")


def main():
    parser = argparse.ArgumentParser(description="Manage RAG examples for FCE-Trainer")
    sub = parser.add_subparsers(dest="command", required=True)

    # add
    p_add = sub.add_parser("add", help="Add a single example")
    p_add.add_argument("--paper", required=True, help="Paper: reading, use_of_english, writing, listening, speaking")
    p_add.add_argument("--part", type=int, required=True, help="Part number (1-7)")
    p_add.add_argument("--type", default="", help="Task type (e.g. multiple_choice_cloze, open_cloze)")
    p_add.add_argument("--topic", default="", help="Topic keyword")
    p_add.add_argument("--level", default="b2", help="Level (b2 or b2plus)")
    p_add.add_argument("--text", help="Prompt text (inline)")
    p_add.add_argument("--file", help="Read prompt text from file")
    p_add.add_argument("--target-reader", help="Target reader metadata")
    p_add.add_argument("--purpose", help="Purpose metadata")
    p_add.add_argument("--word-limit", help="Word limit metadata")
    p_add.set_defaults(func=cmd_add)

    # add-json
    p_json = sub.add_parser("add-json", help="Bulk-add from JSON file")
    p_json.add_argument("file", help="Path to JSON file with array of examples")
    p_json.set_defaults(func=cmd_add_json)

    # list
    p_list = sub.add_parser("list", help="List examples")
    p_list.add_argument("--paper", help="Filter by paper")
    p_list.add_argument("--part", type=int, help="Filter by part number")
    p_list.add_argument("--type", help="Filter by task type")
    p_list.set_defaults(func=cmd_list)

    # show
    p_show = sub.add_parser("show", help="Show example details")
    p_show.add_argument("id", type=int, help="Example ID")
    p_show.set_defaults(func=cmd_show)

    # delete
    p_del = sub.add_parser("delete", help="Delete an example")
    p_del.add_argument("id", type=int, help="Example ID")
    p_del.set_defaults(func=cmd_delete)

    # rebuild-embeddings
    p_rebuild = sub.add_parser("rebuild-embeddings", help="Compute missing embeddings")
    p_rebuild.set_defaults(func=cmd_rebuild)

    # stats
    p_stats = sub.add_parser("stats", help="Show example counts")
    p_stats.set_defaults(func=cmd_stats)

    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
