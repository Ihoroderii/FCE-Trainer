#!/usr/bin/env python3
"""Inventory the OCR'd *Language Practice for B2 First* scan.

Reports, per page, the signals that matter for RAG import:
  * consolidation / exam-practice markers
  * open-cloze style gap numbering  "(1) ... (2) ..."
  * word-formation stems in capitals  (e.g. "DECIDE")
  * key-word-transformation stems  ("KEY WORD" + "DO NOT CHANGE")
  * multiple-choice options  A) B) C) D)
  * gapped-text sentence banks  A-G
"""
from __future__ import annotations

import re
import sys
from collections import Counter
from pathlib import Path

PAGES_DIR = Path("materials/grammar_book/ocr_pages")

PATTERNS = {
    "consolidation": re.compile(r"\bconsolidation\b", re.I),
    "exam_practice": re.compile(r"exam\s+practice|exam\s+task|first\s+certificate", re.I),
    "open_cloze_gaps": re.compile(r"\(\d{1,2}\)\s*_*|\(\d{1,2}\)\s*$", re.M),
    "numbered_gaps": re.compile(r"\b\d{1,2}\s*_{2,}"),
    "cap_stem": re.compile(r"^\s*[A-Z][A-Z\-']{3,}\s*$", re.M),
    "key_word": re.compile(r"key\s+word|do\s+not\s+change\s+the\s+word", re.I),
    "mc_options": re.compile(r"^\s*[A-D][\).]\s+\S", re.M),
    "sentence_bank": re.compile(r"^\s*[A-G]\s*$", re.M),
    "part_heading": re.compile(r"\bpart\s+[1-7]\b", re.I),
    "word_formation": re.compile(r"word\s+formation", re.I),
}


def page_number(path: Path) -> int:
    return int(path.stem)


def main() -> int:
    pages = sorted(PAGES_DIR.glob("*.txt"), key=page_number)
    if not pages:
        sys.exit(f"no OCR pages in {PAGES_DIR}")

    page_hits: Counter[str] = Counter()
    totals: Counter[str] = Counter()
    hits: dict[str, list[int]] = {k: [] for k in PATTERNS}

    for path in pages:
        text = path.read_text(errors="replace")
        for name, rx in PATTERNS.items():
            n = len(rx.findall(text))
            if n:
                totals[name] += n
                page_hits[name] += 1
                hits[name].append(page_number(path))

    print(f"pages scanned: {len(pages)}  (pdf pages {page_number(pages[0])}-{page_number(pages[-1])})")
    print()
    print(f"{'signal':16} {'pages':>6} {'matches':>8}  page numbers")
    for name in PATTERNS:
        pgs = hits[name]
        shown = str(pgs[:40]) + (" ..." if len(pgs) > 40 else "")
        print(f"{name:16} {page_hits[name]:6} {totals[name]:8}  {shown}")

    print("\n--- pages with consolidation / exam markers ---")
    for p in sorted(set(hits["consolidation"]) | set(hits["exam_practice"])):
        first = next((ln.strip() for ln in (PAGES_DIR / f"{p:03d}.txt").read_text(errors="replace").splitlines() if ln.strip()), "")
        print(f"  p{p:3}  {first[:80]}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
