#!/usr/bin/env python3
"""CLI tool for managing RAG examples in the FCE-Trainer.

Usage:
    python -m scripts.rag_manager export --out corpus.html
    python -m scripts.rag_manager list [--paper X] [--part N]
    python -m scripts.rag_manager show <id>
    python -m scripts.rag_manager add --paper use_of_english --part 1 --type multiple_choice_cloze --topic "travel" --file example.txt
    python -m scripts.rag_manager add-json examples.json
    python -m scripts.rag_manager delete <id>
    python -m scripts.rag_manager rebuild-embeddings [--all]
    python -m scripts.rag_manager stats
"""
from __future__ import annotations

import argparse
import html
import json
import sys
from pathlib import Path

# Ensure project root is in path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from dotenv import load_dotenv
load_dotenv()

from app.rag.store import ensure_rag_tables, add_example, get_example, list_examples, delete_example
from app.rag.embeddings import active_backend, active_model_name, rebuild_embeddings
from app.rag.db import rag_connection, rag_db_path


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
    print("Run 'python -m scripts.rag_manager rebuild-embeddings' to compute embeddings.")


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
    print("Run 'python -m scripts.rag_manager rebuild-embeddings' to compute embeddings.")


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
    print("\n--- Prompt Text ---")
    print(ex["prompt_text"])
    print("\n--- Search Text ---")
    print(ex.get("search_text", ""))


def cmd_delete(args):
    """Delete an example."""
    ensure_rag_tables()
    if delete_example(args.id):
        print(f"Deleted example {args.id}")
    else:
        print(f"Example {args.id} not found.")


def _count_needing_embeddings(model: str) -> int:
    """Examples with no vector, or a vector from a different model."""
    with rag_connection() as conn:
        row = conn.execute(
            "SELECT COUNT(*) FROM rag_examples "
            "WHERE embedding IS NULL OR IFNULL(embedding_model, '') != ?",
            (model,),
        ).fetchone()
    return row[0] if row else 0


def cmd_rebuild(args):
    """Compute/update embeddings for all examples missing them."""
    ensure_rag_tables()
    backend = active_backend()
    model = active_model_name()
    if backend is None:
        print("No embedding backend available.")
        print("Install fastembed (free, local):  pip install fastembed")
        print("or set OPENAI_API_KEY / GOOGLE_AI_API_KEY. "
              "Retrieval currently falls back to keyword matching.")
        return

    print(f"Embedding backend: {backend} ({model})")
    updated = rebuild_embeddings(force=getattr(args, "all", False))
    if updated:
        print(f"Updated {updated} embeddings.")
        return

    # A zero result is ambiguous: either everything was already up to date, or
    # every request failed. Re-check the table so the message is not misleading.
    remaining = _count_needing_embeddings(model)
    if remaining:
        print(f"Embedding FAILED: {remaining} example(s) still have no vector for "
              f"'{model}'.")
        print("Retrieval will fall back to keyword matching until this succeeds.")
        print("If the provider returned 429, you have hit a rate/quota limit — "
              "wait and re-run this command.")
    else:
        print("Nothing to update (all examples already embedded with this model).")


_EXPORT_CSS = """
body { font-family: -apple-system, system-ui, Segoe UI, sans-serif; margin: 0;
       background: #f6f7f9; color: #1c1f23; }
header { background: #1c1f23; color: #fff; padding: 18px 26px; position: sticky; top: 0; z-index: 5; }
header h1 { margin: 0 0 6px; font-size: 19px; }
header .meta { font-size: 13px; opacity: .8; }
#filter { margin-top: 10px; padding: 7px 10px; width: 320px; max-width: 100%;
          border: 0; border-radius: 5px; font-size: 14px; }
main { padding: 20px 26px 60px; }
h2 { font-size: 16px; margin: 26px 0 10px; padding-bottom: 6px; border-bottom: 2px solid #d6dae0; }
.card { background: #fff; border: 1px solid #e1e5ea; border-radius: 7px; margin: 10px 0; }
.card > summary { cursor: pointer; padding: 11px 14px; font-size: 14px; display: flex;
                  gap: 12px; align-items: baseline; flex-wrap: wrap; }
.card > summary:hover { background: #f0f3f6; }
.id { color: #6b7280; font-variant-numeric: tabular-nums; }
.topic { font-weight: 600; }
.tag { font-size: 11px; background: #eef1f5; border-radius: 4px; padding: 2px 7px; color: #444; }
.body { border-top: 1px solid #eef1f5; padding: 14px; }
pre { white-space: pre-wrap; word-wrap: break-word; font-size: 13px; line-height: 1.5;
      background: #fbfcfd; border: 1px solid #eef1f5; border-radius: 5px; padding: 12px; margin: 0; }
dl { margin: 0 0 10px; font-size: 12px; color: #555; display: flex; gap: 18px; flex-wrap: wrap; }
dt { font-weight: 600; }
.empty { color: #666; font-style: italic; }
"""

_EXPORT_JS = """
const box = document.getElementById('filter');
box.addEventListener('input', () => {
  const q = box.value.toLowerCase();
  document.querySelectorAll('.card').forEach(card => {
    card.style.display = card.textContent.toLowerCase().includes(q) ? '' : 'none';
  });
  document.querySelectorAll('section').forEach(section => {
    const visible = [...section.querySelectorAll('.card')].some(c => c.style.display !== 'none');
    section.style.display = visible ? '' : 'none';
  });
});
document.querySelectorAll('details.card').forEach((d, i) => { if (i < 2) d.open = true; });
"""


def cmd_export(args):
    """Write the corpus to a self-contained HTML file you can open in a browser."""
    ensure_rag_tables()
    examples = list_examples(paper=args.paper, part=args.part, task_type=args.type)
    if args.min_chars:
        examples = [e for e in examples if len(e.get("prompt_text") or "") >= args.min_chars]

    if not examples:
        print("No examples matched. Nothing exported.")
        return

    grouped: dict[int, list[dict]] = {}
    for example in examples:
        grouped.setdefault(example["part"], []).append(example)

    parts = []
    parts.append(
        "<!doctype html><html lang='en'><head><meta charset='utf-8'>"
        f"<title>FCE RAG corpus ({len(examples)} examples)</title>"
        f"<style>{_EXPORT_CSS}</style></head><body>"
    )
    parts.append(
        "<header><h1>FCE RAG corpus</h1>"
        f"<div class='meta'>{len(examples)} examples &middot; "
        f"database {rag_db_path()} &middot; embeddings {active_backend()} "
        f"{active_model_name()}</div>"
        "<input id='filter' placeholder='Filter by topic, text or id…' autocomplete='off'>"
        "</header><main>"
    )

    for part in sorted(grouped):
        items = grouped[part]
        paper = items[0].get("paper", "")
        parts.append(
            f"<section><h2>Part {part} &middot; {html.escape(paper)} "
            f"({len(items)} example{'s' if len(items) != 1 else ''})</h2>"
        )
        for example in items:
            meta = example.get("metadata") or {}
            title = html.escape(example.get("topic") or "(no topic)")
            row = [
                f"<span class='id'>#{example.get('id')}</span>",
                f"<span class='topic'>{title}</span>",
            ]
            if meta.get("source_page"):
                row.append(f"<span class='tag'>p{meta['source_page']}</span>")
            if example.get("task_type"):
                row.append(f"<span class='tag'>{html.escape(example['task_type'])}</span>")
            row.append(f"<span class='tag'>{len(example.get('prompt_text') or '')} chars</span>")
            if meta.get("source"):
                row.append(f"<span class='tag'>{html.escape(str(meta['source']))}</span>")
            if meta.get("partial"):
                row.append("<span class='tag'>partial</span>")

            details = [
                "<details class='card'><summary>" + "".join(row) + "</summary><div class='body'>",
                "<dl>",
                f"<div><dt>model</dt> {html.escape(str(example.get('level', '')))}</div>",
                f"<div><dt>paper</dt> {html.escape(str(example.get('paper', '')))}</div>",
            ]
            if example.get("embedding_model"):
                details.append(f"<div><dt>embedded by</dt> "
                               f"{html.escape(str(example['embedding_model']))}</div>")
            details.append("</dl>")
            details.append(f"<pre>{html.escape(example.get('prompt_text') or '')}</pre>")
            details.append("</div></details>")
            parts.append("".join(details))
        parts.append("</section>")

    if not args.no_js:
        parts.append(f"<script>{_EXPORT_JS}</script>")
    parts.append("</main></body></html>")

    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text("".join(parts), encoding="utf-8")

    print(f"Exported {len(examples)} example(s) across {len(grouped)} part(s) -> {out}")
    print(f"Open it in a browser:  file://{out.resolve()}")
    if not args.no_js:
        print("(type in the filter box to search topic/text/id; click a row to expand)")


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
    p_rebuild.add_argument("--all", action="store_true",
                           help="Re-embed every example (needed after switching backend)")
    p_rebuild.set_defaults(func=cmd_rebuild)

    # stats
    p_stats = sub.add_parser("stats", help="Show example counts")
    p_stats.set_defaults(func=cmd_stats)

    p_export = sub.add_parser("export", help="Write the corpus to a browsable HTML file")
    p_export.add_argument("--out", default="rag_corpus.html", help="Output .html path")
    p_export.add_argument("--paper", help="Only this paper")
    p_export.add_argument("--part", type=int, help="Only this part")
    p_export.add_argument("--type", help="Only this task type")
    p_export.add_argument("--min-chars", type=int, default=0,
                          help="Skip examples shorter than this")
    p_export.add_argument("--no-js", action="store_true",
                          help="Omit the filter script (pure static HTML)")
    p_export.set_defaults(func=cmd_export)

    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
