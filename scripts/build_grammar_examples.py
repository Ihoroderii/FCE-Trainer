#!/usr/bin/env python3
"""Structure exam-format exercises from the *Language Practice for B2 First* scan.

The book is a grammar/vocabulary practice book, but its Consolidation units and
several grammar/vocabulary exercises are printed in B2 First exam format:

    1  "Decide which answer (A, B, C or D) best fits each gap"   -> Part 1
    3  "Use the word given in capitals ... form a word"          -> Part 3
    4  "Complete the second sentence ... Do not change the word"  -> Part 4

This driver differs from `import_examples structure` in one important way: it
sends **one exercise per AI request** (instead of 12k-char chunks), so the
structurer sees the task's own instruction and never merges adjacent exercises.
Answers are taken from the book's answer key and stored in `metadata["answers"]`
rather than in `prompt_text`, because `prompt_text` is injected into generation
prompts verbatim.

Usage:
    python -m scripts.build_grammar_examples inventory
    python -m scripts.build_grammar_examples structure [--parts 1,3,4] [--limit N] [--workers 4]
    python -m scripts.build_grammar_examples merge
"""
from __future__ import annotations

import argparse
import json
import re
import sys
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from dotenv import load_dotenv  # noqa: E402

load_dotenv()  # scripts run outside the Flask app, which is what loads .env normally

OCR_DIR = Path("materials/grammar_book/ocr_pages")
OUT_DIR = Path("materials/grammar_book/examples")
ANSWER_KEY_PAGES = range(320, 323)  # printed pp. 313-320, 1-based PDF pages
SOURCE_LABEL = "Language Practice for B2 First (Vince, 5th ed.)"

# Running heads / page furniture that must not leak into a task body.
HEAD_RE = re.compile(
    r"^(?:LANGUAGE PRACTICE FOR B2 FIRST|"
    r"GRAMMAR \d+ .*|VOCABULARY \d+ .*|"
    r"CONSOLIDATION \d+(?: UNITS [\d\-]+)?|"
    r"CONTENTS?)$",
    re.I,
)

# ── exercise detection ───────────────────────────────────────────────────────

# Strict exam markers. Generic instructions such as "Choose the best word or
# phrase (A-D) to complete each sentence" are deliberately NOT here: they are
# sentence-level vocabulary drills, not FCE Part 1 cloze texts.
PART_1_MARKER = re.compile(r"best fits each gap|fits each numbered gap", re.I)
PART_3_MARKER = re.compile(r"word given in capitals", re.I)
PART_4_MARKER = re.compile(r"do not change the word given", re.I)
# A page carrying this phrase holds the exercise's own instruction, not just the
# tail of an instruction that wrapped over from the previous page.
FULL_INSTRUCTION_RE = re.compile(r"similar meaning to the first", re.I)

# A numbered exercise starts on its own line: "3 Complete ...", "5 Use the ...".
EXERCISE_START_RE = re.compile(r"^[ \t]{0,3}(\d{1,2})[ \t]*[\.\)]?[ \t]+([A-Z(].{0,140})$", re.M)

# Exam tasks always contain many numbered gaps / items; prose and notes do not.
GAP_NUMBER_RE = re.compile(r"\((\d{1,2})\)")
ITEM_NUMBER_RE = re.compile(r"^\s*(\d{1,2})\s*[\.\)]?\s+\S", re.M)

PART_TASK = {1: "multiple_choice_cloze", 3: "word_formation", 4: "key_word_transformation"}
PART_PAPER = {1: "use_of_english", 3: "use_of_english", 4: "use_of_english"}


def load_pages() -> dict[int, str]:
    if not OCR_DIR.exists():
        sys.exit(f"no OCR pages at {OCR_DIR}; run the OCR step first")
    out = {}
    for path in sorted(OCR_DIR.glob("*.txt"), key=lambda p: int(p.stem)):
        out[int(path.stem)] = path.read_text(errors="replace")
    return out


def strip_furniture(text: str) -> str:
    kept = [ln for ln in text.splitlines() if not HEAD_RE.match(ln.strip())]
    return "\n".join(kept)


def _marker_offset(text: str, marker: re.Pattern[str]) -> int:
    """Character offset of the *block* containing the first marker match.

    The marker usually sits in a numbered instruction ("7 Use the word given in
    capitals ...") but its first line can be on the previous page, in which case
    the match stands alone above the items.
    """
    m = marker.search(text)
    if not m:
        return -1
    return text.rfind("\n", 0, m.start()) + 1


def _has_numbered_instruction(text: str) -> bool:
    """True when this page holds the exercise's own numbered instruction line.

    Consolidation tasks print the instruction as a numbered exercise
    ("5 Complete the second sentence ... Do not change ..."). When the instruction
    merely wrapped over from the previous page, the page has only the tail
    ("between two and five words, including the word given.") and no number.
    """
    for line in text.splitlines():
        if FULL_INSTRUCTION_RE.search(line) and EXERCISE_START_RE.match(line):
            return True
    return False


def _detect_part(text: str) -> int | None:
    """Which exam part starts on this page (earliest instruction marker wins)."""
    candidates = []
    for part, marker in ((1, PART_1_MARKER), (3, PART_3_MARKER), (4, PART_4_MARKER)):
        off = _marker_offset(text, marker)
        if off >= 0:
            candidates.append((off, part))
    if not candidates:
        # Part 4 instructions are sometimes split so the marker lands above the
        # items with no numbered header; the *page top* then reads "between two
        # and five words, including the word given." Restrict this to the top of
        # the page so unrelated units cannot be swept in.
        top = "\n".join(text.splitlines()[:6])
        if re.search(r"including the word given", top, re.I):
            return 4
        return None
    candidates.sort()
    part = candidates[0][1]
    # A Part 4 page must carry the exercise's own opening instruction. Pages that
    # only hold the tail of an instruction ("between two and five words, ...")
    # belong to an exercise starting on the *next* page and must not be sliced
    # into a task of their own.
    if part == 4 and not _has_numbered_instruction(text):
        return None
    return part


INSTRUCTION_WORDS_RE = re.compile(
    r"\b(?:rewrite|complete|decide|use the word|underline|choose)\b", re.I
)


def _segment_from(text: str, offset: int, *, lookback: int = 4) -> str:
    """Slice a page from the instruction block, keeping instruction lines above it.

    In many units the numbered instruction ("6 Use the word given in capitals")
    sits *above* the marker line, so a naive slice from the marker would hand the
    structurer a body with no instruction at all.
    """
    lines = text.splitlines()
    # Find the line index containing `offset`.
    consumed = 0
    idx = 0
    for i, ln in enumerate(lines):
        nxt = consumed + len(ln) + 1
        if consumed <= offset < nxt:
            idx = i
            break
        consumed = nxt
    start = idx
    for j in range(idx - 1, max(-1, idx - 1 - lookback), -1):
        candidate = lines[j].strip()
        if not candidate:
            break
        if INSTRUCTION_WORDS_RE.search(candidate):
            start = j
        else:
            break
    return "\n".join(lines[start:])


def _is_continuation(text: str, part: int | None = None) -> bool:
    """A page with no fresh instruction that continues the previous task.

    Must actually look like the same kind of task: a cloze/word-formation
    continuation is full of numbered gaps, a key word transformation page is
    full of capitalised key words.
    """
    if len(ITEM_NUMBER_RE.findall(text)) < 3:
        return False
    if part in (1, 3):
        return len(GAP_NUMBER_RE.findall(text)) >= 4
    if part == 4:
        return len(KEY_LINE_RE.findall(text)) >= 4
    return False


KEY_LINE_RE = re.compile(r"^[A-Z][A-Z'\-]{2,20}$", re.M)


def validate_structure(part: int, body: str) -> str:
    """Structural sanity check of an AI-extracted task. Returns "" when fine."""
    gaps = sorted({int(g) for g in GAP_NUMBER_RE.findall(body)})
    if part in (1, 3):
        if len(gaps) < 4:
            return f"only {len(gaps)} distinct numbered gaps"
        if gaps != list(range(1, len(gaps) + 1)):
            return f"gaps are not a contiguous run from 1: {gaps[:12]}"
        if not body.rstrip().endswith((")", ".", "?", "!", "”", '"', "…")):
            return "" if len(body) > 600 else "suspiciously short tail"
    else:
        if len(KEY_LINE_RE.findall(body)) < 4:
            return "fewer than 4 key words"
    return ""


def _is_usable(part: int, page_texts: list[str]) -> tuple[bool, str]:
    """Guard against prose, notes and answer-key fragments."""
    body = "\n".join(page_texts)
    gaps = len(GAP_NUMBER_RE.findall(body))
    items = len(ITEM_NUMBER_RE.findall(body))
    keys = len(KEY_LINE_RE.findall(body))
    if len(body) < 400:
        return False, "body too short"
    if part == 1 and gaps < 6:
        return False, f"only {gaps} numbered gaps"
    if part == 3 and gaps < 4:
        return False, f"only {gaps} numbered gaps"
    if part == 4 and items < 6:
        return False, f"only {items} numbered items"
    if part == 4 and keys < 4:
        return False, f"only {keys} key words"
    return True, ""


TRAILING_ITEM_RE = re.compile(r"^\s*(\d{1,2})\s*[\.\)]?\s+\S", re.M)


def _looks_complete(text: str) -> bool:
    """True when a key word transformation page already ends at item 10."""
    numbers = [int(m.group(1)) for m in TRAILING_ITEM_RE.finditer(text)]
    return bool(numbers) and max(numbers) >= 10


def find_exercises(pages: dict[int, str], *, include_excluded: bool = False) -> list[dict]:
    """Return detected exam-format exercises as {part, pages, text, instruction}."""
    records: list[dict] = []
    excluded: list[dict] = []
    prev_part: int | None = None

    for n in sorted(pages):
        raw = pages[n]
        stripped = strip_furniture(raw)
        part = _detect_part(stripped)

        if part is not None:
            full_marker = bool(FULL_INSTRUCTION_RE.search(stripped))
            fragment = part == 4 and not full_marker
            joins = (
                fragment
                and records
                and records[-1]["part"] == 4
                and records[-1]["pages"][-1] == n - 1
                # The previous page already shows the whole task (items up to 10):
                # this page is a *different* exercise, not a continuation.
                and not _looks_complete("\n".join(records[-1]["text"]))
                # At most one continuation page: longer runs are a run of
                # separate exercises that happen to share the same unit.
                and len(records[-1]["pages"]) == 1
            )
            if joins:
                records[-1]["pages"].append(n)
                records[-1]["text"].append(stripped)
                prev_part = part
                continue
            # A later page that repeats the same marker is the next exercise of
            # that type, not part of the previous one - except when the previous
            # page was itself cut off mid-task.
            if (
                records
                and records[-1]["part"] == part
                and records[-1]["pages"][-1] == n - 1
                and len(records[-1]["pages"]) == 1
                and not _looks_complete("\n".join(records[-1]["text"]))
                and not _has_numbered_instruction(stripped)
            ):
                records[-1]["pages"].append(n)
                records[-1]["text"].append(stripped)
                prev_part = part
                continue
            offset = _marker_offset(stripped, {1: PART_1_MARKER, 3: PART_3_MARKER, 4: PART_4_MARKER}[part])
            if offset < 0:
                offset = 0
            segment = _segment_from(stripped, offset)
            records.append(
                    {
                        "part": part,
                        "pages": [n],
                        "text": [segment],
                    "instruction": segment.splitlines()[0] if segment.splitlines() else "",
                }
            )
            prev_part = part
            continue

        if prev_part is not None and _is_continuation(stripped, prev_part):
            records[-1]["pages"].append(n)
            records[-1]["text"].append(stripped)
            continue

        prev_part = None

    found = []
    for rec in records:
        ok, reason = _is_usable(rec["part"], rec["text"])
        if ok:
            found.append(rec)
        else:
            rec["reason"] = reason
            excluded.append(rec)

    if include_excluded:
        for rec in excluded:
            print(f"  skipped part {rec['part']} p{rec['pages'][0]}: {rec['reason']}")
    return found


# ── AI structuring (one exercise per request) ────────────────────────────────

STRUCTURE_PROMPT = """You convert one exercise from a Cambridge B2 First practice book into \
a corpus entry. The book is *Language Practice for B2 First* by Michael Vince.

The exercise below is in exam format for Reading and Use of English Part {part} \
({task_desc}). Reproduce it faithfully and completely:
- transcribe the instruction exactly as printed (including the "word given" keyword rules)
- transcribe every numbered gap and every item
- KEEP THE OPTION LISTS. For Part 1 every gap's four options must appear as
  "1 A ... B ... C ... D ..." lines after the text - without them the entry is useless.
- KEEP THE STEM WORDS. For Part 3 every gap's capitalised stem must stay on its own
  line next to the gap line, exactly as printed.
- KEEP THE KEY WORDS. For Part 4 every key word must stay on its own line between
  the two sentences.
- keep option letters and answer letters exactly (A, B, C, D)
- do NOT invent items, do NOT rewrite, summarise or correct the English
- do NOT include running heads or page numbers

IMPORTANT - the text may contain more than one exercise, or the start of the next
exercise after this one. Extract ONLY the FIRST complete exercise of this format.
Stop at the next exercise's instruction line and do not include its items.
Set "complete" to false if this exercise itself is cut off or partly illegible.

The scan sometimes shows the answers written in (for example "When I arrived at the
office, .. Jack had already ... left."). Keep the printed text in `prompt_text` but
put the corrected answers in `answers`.

Return ONLY a JSON array with exactly one element:
{{"part": {part},
 "topic": "short lowercase theme, 2-4 words",
 "prompt_text": "the complete exercise, plain text, gaps as they appear",
 "answers": {{"1": "...", "2": "..."}},
 "complete": true|false,
 "notes": "anything missing or illegible"}}

--- BEGIN EXERCISE TEXT ---
{body}
--- END EXERCISE TEXT ---"""

TASK_DESC = {
    1: "multiple-choice cloze: a text with numbered gaps and A-D options",
    3: "word formation: a text with numbered gaps and a stem word in capitals",
    4: "key word transformation: pairs of sentences with a given key word",
}


def _alnum(text: str) -> str:
    """Lowercase letters and digits only, for fuzzy containment checks."""
    return re.sub(r"[^a-z0-9]+", "", text.lower())


def verify_answers(answers: dict, source: str) -> tuple[dict, dict]:
    """Split model answers into those the scan actually supports and those it does not.

    The OCR text contains the answers written in, so a real answer's words are
    present in the source (possibly broken across an OCR line). Anything that is
    not found is treated as model confabulation and kept out of the corpus.
    """
    flat = _alnum(source)
    kept: dict[str, str] = {}
    dropped: dict[str, str] = {}
    for key, value in (answers or {}).items():
        value = str(value).strip()
        if not value:
            continue
        probe = _alnum(value)
        # Require a meaningful probe; very short answers ("to") prove nothing.
        if len(probe) < 4:
            dropped[str(key)] = f"{value} (too short to verify)"
            continue
        if probe in flat:
            kept[str(key)] = value
        else:
            dropped[str(key)] = value
    return kept, dropped


def structure_one(ex: dict, model: str | None) -> list[dict]:
    from app.ai import chat_create
    from scripts.import_examples import normalise_example, parse_json_array

    prompt = STRUCTURE_PROMPT.format(
        part=ex["part"], task_desc=TASK_DESC[ex["part"]], body=ex["text"]
    )
    resp = chat_create(
        [
            {"role": "system", "content": "You transcribe exam tasks into JSON. No prose."},
            {"role": "user", "content": prompt},
        ],
        temperature=0.0,
        model=model,
    )
    raw = resp.choices[0].message.content
    items = parse_json_array(raw)
    source = "\n".join(ex["text"])
    out = []
    for item in items:
        answers = item.get("answers") or {}
        item = dict(item)
        item.pop("answers", None)
        normalised = normalise_example(
            item, source_label=SOURCE_LABEL, default_page=ex["pages"][0]
        )
        if not normalised:
            continue
        meta = normalised["metadata"]
        # The scan prints answers inline (this is a "with key" book), but the
        # model also likes to invent the ones it cannot see. Keep only answers
        # whose words actually occur in the scan; do not trust the rest.
        kept, dropped = verify_answers(answers, source)
        meta["answers"] = kept
        if dropped:
            meta["answers_dropped"] = dropped
        meta["book_pages"] = ex["pages"]
        meta["complete"] = bool(item.get("complete", True))
        note = str(item.get("notes") or "").strip()
        if note:
            meta["notes"] = note
        out.append(normalised)
    return out


def cmd_inventory(args) -> int:
    pages = load_pages()
    found = find_exercises(pages, include_excluded=args.excluded)
    per_part: dict[int, int] = {}
    print(f"{'part':>4}  {'pdf pages':<14} items  instruction")
    for ex in found:
        per_part[ex["part"]] = per_part.get(ex["part"], 0) + 1
        pages_s = ",".join(str(p) for p in ex["pages"])
        body = "\n".join(ex["text"])
        instr = (ex["instruction"].splitlines() or [""])[0][:58]
        print(
            f"{ex['part']:>4}  {pages_s[:14]:<14} "
            f"{len(GAP_NUMBER_RE.findall(body)):>5}  {instr}"
        )
    print()
    for part in sorted(per_part):
        print(f"Part {part}: {per_part[part]} exercises")
    print(f"total: {len(found)}")
    return 0


def cmd_structure(args) -> int:
    from app.ai import ai_available, provider_label

    if not ai_available:
        sys.exit("no AI provider configured; set a key in .env")
    pages = load_pages()
    found = find_exercises(pages)
    if args.parts:
        wanted = {int(p) for p in args.parts.split(",")}
        found = [e for e in found if e["part"] in wanted]
    if args.limit:
        found = found[: args.limit]

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    print(f"provider={provider_label()} model={args.model or 'default'} exercises={len(found)}")

    lock = threading.Lock()
    done = 0
    written: list[Path] = []

    def work(ex: dict) -> tuple[dict, list[dict]]:
        return ex, structure_one(ex, args.model)

    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        futures = {pool.submit(work, ex): ex for ex in found}
        for fut in as_completed(futures):
            ex = futures[fut]
            try:
                _, items = fut.result()
            except Exception as exc:  # one bad exercise must not kill the run
                with lock:
                    print(f"  ! part {ex['part']} pages {ex['pages']}: {exc}")
                continue
            path = OUT_DIR / f"part{ex['part']}_p{ex['pages'][0]:03d}.json"
            path.write_text(json.dumps(items, indent=2, ensure_ascii=False))
            with lock:
                done += 1
                written.append(path)
                print(
                    f"  [{done}/{len(found)}] part {ex['part']} "
                    f"pages {ex['pages'][0]}-{ex['pages'][-1]}: {len(items)} entries"
                )

    print(f"wrote {len(written)} files to {OUT_DIR}")
    return 0


def cmd_merge(args) -> int:
    files = sorted(OUT_DIR.glob("part*.json"))
    if not files:
        sys.exit(f"nothing to merge in {OUT_DIR}")
    merged: list[dict] = []
    seen: set[str] = set()
    for path in files:
        for item in json.loads(path.read_text()):
            key = item["prompt_text"][:400]
            if key in seen:
                continue
            seen.add(key)
            merged.append(item)
    out = Path(args.out)
    problems = audit_entries(merged)
    bad_where = {where for where, _ in problems}
    flagged = [
        e for e in merged
        if f"part {e['part']} p{e['metadata'].get('source_page')}" in bad_where
        or not e["metadata"].get("complete", True)
    ]
    clean = [e for e in merged if e not in flagged]

    out.write_text(json.dumps(clean, indent=2, ensure_ascii=False))
    from collections import Counter

    print(f"{out}: {len(clean)} clean entries (ready to load)")
    print(" clean by part:", dict(sorted(Counter(i['part'] for i in clean).items())))
    if flagged:
        flagged_path = out.with_name(out.stem + ".flagged.json")
        flagged_path.write_text(json.dumps(flagged, indent=2, ensure_ascii=False))
        print(f"{flagged_path}: {len(flagged)} flagged entries (excluded from the load file)")
        print("   excluded because the scan or the model reported them incomplete:")
        for i in flagged:
            reason = i["metadata"].get("notes") or "structural audit failed"
            print(f"   part {i['part']} p{i['metadata']['source_page']}: {reason[:70]}")

    print(f"\nstructural problems: {len(problems)}")
    for where, why in problems:
        print(f"   {where}: {why}")
    return 0


def audit_entries(entries: list[dict]) -> list[tuple[str, str]]:
    """Structural audit of merged entries. Returns (where, problem) pairs.

    Nothing here judges English quality; it only checks that the exam format was
    reproduced: the gaps form a contiguous run, Part 1 keeps its A-D options,
    Part 3 keeps its capitalised stems and Part 4 keeps its key words.
    """
    problems: list[tuple[str, str]] = []
    for item in entries:
        part = item["part"]
        text = item["prompt_text"]
        page = item["metadata"].get("source_page", "?")
        where = f"part {part} p{page}"
        gaps = sorted({int(g) for g in GAP_NUMBER_RE.findall(text)})
        keys = len(KEY_LINE_RE.findall(text))

        if len(text) < 300:
            problems.append((where, "text is suspiciously short"))
        if not gaps and part in (1, 3):
            problems.append((where, "no numbered gaps found"))
            continue

        if part == 1:
            highest = max(gaps)
            if gaps != list(range(1, highest + 1)):
                problems.append((where, f"gaps are not 1..{highest}: {gaps}"))
            option_lines = [ln for ln in text.splitlines() if re.match(r"^\s*\d{1,2}\s+A\s+\S", ln)]
            if len(option_lines) < highest:
                problems.append(
                    (where, f"only {len(option_lines)} option lines for {highest} gaps")
                )
        elif part == 3:
            if gaps != list(range(1, max(gaps) + 1)):
                problems.append((where, f"gaps are not 1..{max(gaps)}: {gaps}"))
            if keys < len(gaps) - 1:
                problems.append((where, f"{keys} capitalised stems for {len(gaps)} gaps"))
        else:
            if keys < 4:
                problems.append((where, f"only {keys} key words"))
            if keys > 15:
                problems.append((where, f"{keys} key words - probably two tasks merged"))
    return problems


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)

    p_inv = sub.add_parser("inventory", help="list detected exercises")
    p_inv.add_argument("--excluded", action="store_true",
                       help="also report exercise-like blocks rejected by the guards")
    p_inv.set_defaults(func=cmd_inventory)

    p_str = sub.add_parser("structure", help="run AI structuring, one exercise per call")
    p_str.add_argument("--parts", help="comma list, e.g. 1,3,4")
    p_str.add_argument("--limit", type=int, help="only the first N exercises")
    p_str.add_argument("--workers", type=int, default=4)
    p_str.add_argument("--model", help="override the AI model")
    p_str.set_defaults(func=cmd_structure)

    p_merge = sub.add_parser("merge", help="combine per-exercise JSON into one corpus file")
    p_merge.add_argument("--out", default="materials/grammar_book.examples.json")
    p_merge.set_defaults(func=cmd_merge)

    args = parser.parse_args()
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
