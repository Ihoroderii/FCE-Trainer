#!/usr/bin/env python3
"""Import real FCE exercises from your own study material into the RAG corpus.

Pipeline (three reviewable stages, plus a `run` shortcut):

    extract    a PDF / DOCX / TXT  ->  plain text with page markers
    structure  plain text          ->  JSON examples in the RAG schema
    load       JSON                ->  RAG database (+ embeddings)

Example:

    # Whole book, AI-structured, committed to the RAG database
    python -m scripts.import_examples run materials/fce_student_book.pdf --commit

    # Inspect first: extract, structure a slice, review the JSON, then load
    python -m scripts.import_examples extract materials/book.pdf
    python -m scripts.import_examples structure --pages 12-40
    python -m scripts.import_examples load materials/book.examples.json --commit

Why stages: AI structuring of a 200-page book costs money and is imperfect.
`structure` always writes a JSON file you can read and edit before `load`, so
nothing enters the corpus unreviewed.

Copyright: this imports *your* material into a local, gitignored database
(`rag_examples.db`, see app/rag/db.py). Do not commit the source files or the
database — `.gitignore` already excludes both.
"""
from __future__ import annotations

import argparse
import difflib
import json
import os
import re
import sys
from pathlib import Path

# Ensure project root is importable when run as a script.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from dotenv import load_dotenv

load_dotenv()

# The app package configures logging from FLASK_DEBUG at import time. This is a
# CLI, so force info-level logging to keep output readable.
os.environ["FLASK_DEBUG"] = "0"

import logging  # noqa: E402

from app.rag.db import rag_db_path  # noqa: E402
from app.rag.embeddings import rebuild_embeddings  # noqa: E402
from app.rag.store import add_example, count_examples, ensure_rag_tables  # noqa: E402

# Importing the app package calls logging.basicConfig() from FLASK_DEBUG, which is
# far too noisy for a CLI. Quiet it *after* the imports so our output stays readable.
logging.getLogger().setLevel(logging.WARNING)
for _noisy in ("httpx", "httpcore", "openai", "urllib3", "fce_trainer"):
    logging.getLogger(_noisy).setLevel(logging.WARNING)

PROJECT_ROOT = Path(__file__).resolve().parent.parent
MATERIALS_DIR = PROJECT_ROOT / "materials"
PAGE_MARKER = "=== PAGE {n} ==="
# Capture variant for detection/numbering, non-capture for splitting (a capture
# group would make re.split return the numbers instead of the page bodies).
_PAGE_RE = re.compile(r"^===\s*PAGE\s+(\d+)\s*===$", re.MULTILINE)
_PAGE_SPLIT_RE = re.compile(r"^===\s*PAGE\s+\d+\s*===$", re.MULTILINE)


def split_page_text(text: str) -> list[str]:
    """Split page-marked text into page bodies (no markers)."""
    return [part.strip() for part in _PAGE_SPLIT_RE.split(text) if part.strip()]

# RAG metadata per part — must match app/rag/helpers.py _PART_RAG_MAP
PART_META: dict[int, tuple[str, str]] = {
    1: ("use_of_english", "multiple_choice_cloze"),
    2: ("use_of_english", "open_cloze"),
    3: ("use_of_english", "word_formation"),
    4: ("use_of_english", "key_word_transformation"),
    5: ("reading", "multiple_choice"),
    6: ("reading", "gapped_text"),
    7: ("reading", "multiple_matching"),
    8: ("use_of_english", "get_phrases"),
}

STRUCTURE_SYSTEM_PROMPT = """You extract exam tasks from Cambridge B2 First (FCE) study material.

You will receive raw text from a student book. Find every exercise that is usable as
a style and format reference. Follow these rules exactly:

- Include a task when its core material is present: the passage AND its questions or
  gaps. A task with fewer questions than the standard number (e.g. 4 of 8 gaps) is
  still useful — include it and set "partial": true.
- Skip only what is genuinely unusable: fragments with no passage, bare instructions,
  answer keys with no task, tables of contents, indexes, and teacher's notes.
- `part` is an integer, one of:
    1 = Reading & Use of English Part 1, multiple-choice cloze (8 gaps, A/B/C/D options)
    2 = Reading & Use of English Part 2, open cloze (8 gaps, one word each)
    3 = Reading & Use of English Part 3, word formation (8 gaps + STEM words)
    4 = Reading & Use of English Part 4, key word transformation sentences
    5 = Reading Part 5, multiple choice (long text + 6 questions)
    6 = Reading Part 6, gapped text (6 gaps + 7 sentences A-G)
    7 = Reading Part 7, multiple matching (sections + 10 statements)
  If a part number is not printed, infer it from the task format above.
- `prompt_text` must reproduce the task faithfully and completely, including the
  passage, every gap marker, every option, and the answers if the material gives
  them. Preserve the original wording — do NOT rewrite, summarise or improve it.
  Use plain text; keep gap markers as they appear (e.g. (1)_____, GAP1, _____).
  Do not include page headers, footers or page numbers in `prompt_text`.
- `topic` is a short lowercase theme (2-4 words), e.g. "travel and tourism".
- `source_page` is the page number the task starts on, from the page markers.

Return ONLY a JSON array. No prose, no markdown fences. If nothing is extractable,
return [].

Each element:
{"paper": "use_of_english"|"reading", "part": <int>, "task_type": "<string>",
 "topic": "<string>", "prompt_text": "<string>", "source_page": <int>,
 "partial": <bool>}
"""


# ── Stage 1: extract ─────────────────────────────────────────────────────────

def extract_pdf(path: Path) -> list[str]:
    """Return one string of text per page."""
    try:
        from pypdf import PdfReader
    except ImportError:
        sys.exit("pypdf is required for PDF input:  pip install pypdf")

    reader = PdfReader(str(path))
    if reader.is_encrypted:
        try:
            reader.decrypt("")
        except Exception:
            sys.exit(f"PDF is encrypted and could not be opened: {path}")
    pages = []
    for page in reader.pages:
        try:
            pages.append(page.extract_text() or "")
        except Exception as exc:  # a single broken page must not kill the run
            print(f"  ! page skipped ({exc})", file=sys.stderr)
            pages.append("")
    return pages


def ocr_available() -> bool:
    """True if the macOS Vision OCR stack is importable."""
    if sys.platform != "darwin":
        return False
    try:
        import pymupdf  # noqa: F401
        import Vision  # noqa: F401
    except ImportError:
        return False
    return True


def _ocr_image_bytes(png_bytes: bytes) -> str:
    """Run macOS Vision text recognition on an encoded image."""
    import Quartz
    import Vision
    from Foundation import NSData

    data = NSData.dataWithBytes_length_(png_bytes, len(png_bytes))
    source = Quartz.CGImageSourceCreateWithData(data, None)
    if source is None:
        return ""
    image = Quartz.CGImageSourceCreateImageAtIndex(source, 0, None)
    if image is None:
        return ""

    request = Vision.VNRecognizeTextRequest.alloc().init()
    request.setRecognitionLevel_(Vision.VNRequestTextRecognitionLevelAccurate)
    request.setUsesLanguageCorrection_(True)
    try:
        request.setRecognitionLanguages_(["en-GB", "en-US"])
    except Exception:
        pass  # older Vision builds reject explicit languages

    handler = Vision.VNImageRequestHandler.alloc().initWithCGImage_options_(image, None)
    handler.performRequests_error_([request], None)

    items = []
    for observation in request.results() or []:
        candidates = observation.topCandidates_(1)
        if not candidates:
            continue
        box = observation.boundingBox()
        # Vision's origin is bottom-left.
        items.append((box.origin.x, box.origin.y, box.size.width, candidates[0].string()))

    return "\n".join(text for *_, text in _order_reading(items))


def _order_reading(items: list[tuple[float, float, float, str]]) -> list[tuple]:
    """Order OCR fragments into natural reading order.

    Two things matter for FCE books:

    * They are usually two-column. Sorting purely by vertical position
      interleaves the columns, so detect a real column split first and read each
      column separately.
    * A single question's options (A/B/C/D) sit on one visual line, but their
      baseline y differs by a thousandth or so. Sorting naively by (-y, x) can
      emit "D" before "A", which scrambles option lists. Fragments are therefore
      clustered into rows with a tolerance and read left-to-right within a row.
    """
    if not items:
        return items

    centres = [x + width / 2 for x, _, width, _ in items]
    two_column = False
    if len(items) >= 6:
        left = [c for c in centres if c < 0.45]
        right = [c for c in centres if c > 0.55]
        middle = [c for c in centres if 0.45 <= c <= 0.55]
        # A real column split leaves a mostly empty vertical gutter.
        if left and right and len(middle) <= max(1, int(0.05 * len(items))):
            if min(right) - max(left) > 0.10:
                two_column = True

    if two_column:
        left_items = [it for it in items if (it[0] + it[2] / 2) < 0.5]
        right_items = [it for it in items if (it[0] + it[2] / 2) >= 0.5]
        return _rows_to_reading_order(left_items) + _rows_to_reading_order(right_items)
    return _rows_to_reading_order(items)


# Fragments whose baselines differ by less than this are the same visual row.
_ROW_TOLERANCE = 0.008


def _rows_to_reading_order(items: list[tuple[float, float, float, str]]) -> list[tuple]:
    """Cluster fragments into visual rows, then read top-to-bottom, left-to-right."""
    rows: list[list[tuple[float, float, float, str]]] = []
    for item in sorted(items, key=lambda it: -it[1]):
        if rows and abs(rows[-1][0][1] - item[1]) <= _ROW_TOLERANCE:
            rows[-1].append(item)
        else:
            rows.append([item])

    ordered: list[tuple] = []
    for row in rows:
        ordered.extend(sorted(row, key=lambda it: it[0]))
    return ordered


def ocr_pdf(path: Path, start: int, end: int, *, dpi: int = 200) -> list[str]:
    """OCR pages [start, end] (1-based, inclusive) of a scanned PDF.

    Uses macOS Vision via PyMuPDF page rendering — both local, no network and no
    external OCR binaries. Returns one text string per requested page.
    """
    try:
        import pymupdf as fitz
    except ImportError:
        try:
            import fitz
        except ImportError:
            sys.exit("PyMuPDF is required for OCR:  pip install pymupdf")
    if sys.platform != "darwin":
        sys.exit("OCR currently uses the macOS Vision framework and needs macOS.")

    document = fitz.open(str(path))
    try:
        first = max(1, start)
        last = min(end, document.page_count)
        results = []
        for page_number in range(first, last + 1):
            page = document[page_number - 1]
            pixmap = page.get_pixmap(dpi=dpi)
            results.append(_ocr_image_bytes(pixmap.tobytes("png")))
        return results
    finally:
        document.close()


def is_probably_scanned(pages: list[str]) -> bool:
    """True when a PDF yielded almost no text — i.e. it is page images."""
    if not pages:
        return False
    non_empty = [p.strip() for p in pages if p.strip()]
    if not non_empty:
        return True
    average = sum(len(p) for p in non_empty) / len(non_empty)
    return average < 100


def extract_docx(path: Path) -> list[str]:
    """Return the document text as a single 'page' (DOCX has no fixed pages)."""
    try:
        import docx  # python-docx
    except ImportError:
        sys.exit("python-docx is required for DOCX input:  pip install python-docx")
    document = docx.Document(str(path))
    return ["\n".join(p.text for p in document.paragraphs)]


def extract_txt(path: Path) -> list[str]:
    """Read a text file, honouring existing page markers if present."""
    text = path.read_text(encoding="utf-8", errors="replace")
    if _PAGE_RE.search(text):
        return split_page_text(text)
    # No markers: split on form feeds, else treat as one page.
    chunks = [c for c in text.split("\f") if c.strip()]
    return chunks or [text]


def pages_to_text(pages: list[str], start: int = 1) -> str:
    """Render pages with absolute page markers (so source_page stays correct)."""
    blocks = []
    for i, page in enumerate(pages, start):
        blocks.append(PAGE_MARKER.format(n=i))
        blocks.append(page.strip())
    return "\n\n".join(b for b in blocks if b) + "\n"


def first_page_number(text_path: Path) -> int:
    """First page marker in an extracted text file (1 if there are none)."""
    text = text_path.read_text(encoding="utf-8", errors="replace")
    match = _PAGE_RE.search(text)
    return int(match.group(1)) if match else 1


def parse_page_range(spec: str | None, total: int) -> tuple[int, int]:
    """Parse '12-40' or '7' into a 1-based inclusive (start, end)."""
    if not spec:
        return 1, total
    match = re.fullmatch(r"\s*(\d+)\s*(?:-\s*(\d+)\s*)?", spec)
    if not match:
        sys.exit(f"Invalid --pages value: {spec!r} (expected e.g. '12-40' or '7')")
    start = int(match.group(1))
    end = int(match.group(2)) if match.group(2) else start
    if start < 1 or end < start:
        sys.exit(f"Invalid --pages range: {spec!r}")
    return start, min(end, total)


def load_pages(text_path: Path) -> list[str]:
    """Read a text file produced by `extract` back into pages."""
    text = text_path.read_text(encoding="utf-8", errors="replace")
    if not _PAGE_RE.search(text):
        return [text]
    return split_page_text(text)


def cmd_extract(args) -> int:
    source = Path(args.source).expanduser()
    if not source.exists():
        sys.exit(f"Source not found: {source}")

    suffix = source.suffix.lower()
    ocr_used = False

    if suffix == ".pdf":
        written = extract_pdf(source)
        total = len(written)
        start, end = parse_page_range(args.pages, total)

        want_ocr = args.ocr or (not args.no_ocr and is_probably_scanned(written[start - 1:end]))
        if want_ocr and not args.ocr and not ocr_available():
            print("  ! this PDF looks like scanned images but OCR is unavailable; "
                  "install it with: pip install pymupdf pyobjc-framework-Vision",
                  file=sys.stderr)
            want_ocr = False

        if want_ocr:
            if not ocr_available():
                sys.exit("OCR needs macOS:  pip install pymupdf pyobjc-framework-Vision")
            print(f"Scanned PDF detected — OCR-ing pages {start}-{end} of {total} "
                  f"with macOS Vision (this can take a while)…")
            selected = []
            for offset in range(start, end + 1):
                selected.append(ocr_pdf(source, offset, offset, dpi=args.dpi)[0])
                if (offset - start + 1) % 10 == 0 or offset == end:
                    print(f"  · OCR page {offset}/{end}")
            ocr_used = True
        else:
            selected = written[start - 1:end]
    else:
        if suffix == ".docx":
            written = extract_docx(source)
        elif suffix in (".txt", ".md"):
            written = extract_txt(source)
        else:
            sys.exit(f"Unsupported input type {suffix!r}. Use .pdf, .docx, .txt or .md")
        total = len(written)
        start, end = parse_page_range(args.pages, total)
        selected = written[start - 1:end]

    out = Path(args.out) if args.out else MATERIALS_DIR / f"{source.stem}.txt"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(pages_to_text(selected, start=start), encoding="utf-8")

    empty = sum(1 for p in selected if not p.strip())
    print(f"Extracted {len(selected)}/{total} page(s) -> {out}"
          + ("  [OCR]" if ocr_used else ""))
    if empty:
        print(f"  ! {empty} page(s) still have no text — those pages may be "
              f"blank or contain only images/diagrams")
    print(f"  Next: python -m scripts.import_examples structure --text {out}")
    return 0


# ── Stage 2: structure ───────────────────────────────────────────────────────

def chunk_pages(pages: list[str], *, max_chars: int = 4500, overlap: int = 1,
                start_number: int = 1) -> list[tuple[int, str]]:
    """Group pages into windows of at most ~max_chars, with `overlap` pages shared.

    Returns (first_page_number, text) tuples. Overlap keeps a task that straddles
    a page boundary whole inside at least one window.

    Page markers are embedded in the returned text so the model can report an
    accurate `source_page` instead of guessing.
    """
    chunks: list[tuple[int, str]] = []
    i = 0
    while i < len(pages):
        start = i
        buf: list[str] = []
        size = 0
        while i < len(pages):
            page_text = pages[i]
            if buf and size + len(page_text) > max_chars:
                break
            marker = PAGE_MARKER.format(n=start_number + i)
            buf.append(f"{marker}\n{page_text}")
            size += len(page_text)
            i += 1
            if size >= max_chars:
                break
        chunks.append((start_number + start, "\n\n".join(buf)))
        if i >= len(pages):
            break
        i = max(start + 1, i - overlap)
    return chunks


def parse_json_array(raw: str) -> list[dict]:
    """Best-effort extraction of a JSON array from a model response."""
    if not raw:
        return []
    text = raw.strip()
    fence = re.search(r"```(?:json)?\s*(.*?)```", text, re.DOTALL)
    if fence:
        text = fence.group(1).strip()
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        start, end = text.find("["), text.rfind("]")
        if start == -1 or end <= start:
            return []
        try:
            data = json.loads(text[start:end + 1])
        except json.JSONDecodeError:
            return []
    if isinstance(data, dict):
        data = data.get("examples") or data.get("tasks") or []
    if not isinstance(data, list):
        return []
    return [d for d in data if isinstance(d, dict)]


def normalise_example(item: dict, *, source_label: str, default_page: int) -> dict | None:
    """Coerce one model-produced item into a valid RAG example, or None if unusable."""
    try:
        part = int(item.get("part"))
    except (TypeError, ValueError):
        return None
    if part not in PART_META:
        return None

    prompt_text = str(item.get("prompt_text") or "").strip()
    # A usable reference example needs real body text, not just a heading.
    if len(prompt_text) < 120:
        return None

    paper, task_type = PART_META[part]
    topic = str(item.get("topic") or "").strip().lower()
    page = item.get("source_page")
    try:
        page = int(page)
    except (TypeError, ValueError):
        page = default_page

    metadata = {
        "source": source_label,
        "source_page": page,
        "origin": "imported",
        "partial": bool(item.get("partial")),
    }
    return {
        "paper": paper,
        "part": part,
        "task_type": task_type,
        "topic": topic,
        "level": "b2",
        "prompt_text": prompt_text,
        "metadata": metadata,
    }


# Tasks belonging to a different paper entirely. The structurer occasionally
# labels Listening/Speaking/Writing exercises with a Reading & Use of English
# part number, and those must never become style references for generation.
_OFF_PAPER_RE = re.compile(
    r"You(?:'ll| will)?\s+hear|You\s+hear|"
    r"Work\s+in\s+pairs|Work\s+with\s+a\s+partner|"
    r"Write\s+your\s+(?:essay|review|email|article|letter|report|story)|"
    r"There\s+are\s+two\s+parts\s+to\s+this|"
    r"Speaking\s+Part",
    re.IGNORECASE,
)

# A question row of four options, e.g. "A advance B lift C rise D boost".
_ABCD_RE = re.compile(r"\bA\b[^\nA-D]{0,60}\bB\b[^\nA-D]{0,60}\bC\b[^\nA-D]{0,60}\bD\b", re.DOTALL)
_GAP_RE = re.compile(r"\(\d\)\s*[_\.]{2,}")
_CAPS_WORD_RE = re.compile(r"\b[A-Z]{4,}\b")


# Standalone heading lines used by Writing plans (reports/essays). A reading
# passage can legitimately contain "Conclusion", so this only counts as
# disqualifying together with the absence of A/B/C/D option rows.
_WRITING_HEADING_RE = re.compile(
    r"^\s*(?:Introduction|Conclusion|Paragraph\s*\d|"
    r"The\s+(?:individual|university|local\s+community|problem|solution|"
    r"benefits?|drawbacks?|advantages?|disadvantages?)|"
    r"Recommendations?|Reasons?|Background)\s*$",
    re.IGNORECASE | re.MULTILINE,
)


def _looks_like_writing_task(text: str) -> bool:
    """True for a Writing plan/report rather than a Reading & Use of English task."""
    headings = _WRITING_HEADING_RE.findall(text)
    if len(headings) < 2:
        return False
    # A cloze has A/B/C/D option rows; a writing plan does not.
    return not _ABCD_RE.search(text) and not re.search(r"\b\d{1,2}\s+[A-D]\b", text)


def part_format_problem(part: int, text: str) -> str | None:
    """Explain why `text` definitely does not belong to `part`, else None.

    Only unambiguous cases are rejected: a Listening, Speaking or Writing task
    carrying a Reading & Use of English part number. An example of the wrong
    paper is worse than no example, because it teaches the generator the wrong
    format.

    Structural checks live in ``part_format_warning`` instead — OCR noise and
    legitimate layout variation make them too unreliable to auto-reject on. A
    3-option cloze or an open cloze whose *example* gap shows alternatives
    (``(0) who/that``) are both valid, so neither is rejected here.
    """
    off_paper = _OFF_PAPER_RE.search(text)
    if off_paper:
        return f"belongs to another paper ({off_paper.group(0)[:28]!r})"
    if _looks_like_writing_task(text):
        return "looks like a Writing plan (report/essay headings, no options)"
    return None


def part_format_warning(part: int, text: str) -> str | None:
    """Soft signal that `text` may not match `part`'s expected shape.

    Report-only: these heuristics mis-fire on OCR'd books (gaps rendered as
    dots, options wrapped across lines), so they must not silently delete data.
    """
    gaps = len(_GAP_RE.findall(text))
    has_options = bool(_ABCD_RE.search(text)) or bool(re.search(r"\b\d{1,2}\s+[A-D]\b", text))

    if part in (1, 2):
        if gaps < 4 and "_____" not in text:
            return "no obvious cloze gaps"
        if part == 1 and not has_options:
            return "no obvious A/B/C/D options"
        if part == 2 and has_options:
            return "has options (Part 2 is an open cloze)"
    elif part == 3:
        if not _CAPS_WORD_RE.search(text):
            return "no stem words in capitals"
    elif part == 4:
        if "_____" not in text and gaps < 1:
            return "no obvious transformation gap"
        if not _CAPS_WORD_RE.search(text):
            return "no keyword in capitals"
    elif part == 5:
        questions = len(re.findall(r"(?:^|\n)\s*\d{1,2}\s", text))
        if questions < 4:
            return f"only {questions} numbered questions found"
    elif part == 6:
        if not re.search(r"GAP\s*[1-6]", text, re.IGNORECASE) and gaps < 4:
            return "no obvious gapped-text markers"
    elif part == 7:
        if not re.search(r"(?:^|\n)\s*[A-F]\b", text) and gaps == 0:
            return "no obvious lettered sections"
    return None


def _canonical_body(text: str) -> str:
    """Normalise task text for duplicate detection.

    Overlapping AI chunks yield the same task with slightly different leading
    labels ("Part 5" vs "Reading\\n\\nPart 5"), so strip those and compare the
    remaining body rather than the raw string.
    """
    body = text.strip()
    for _ in range(4):
        stripped = re.sub(
            r"^(?:reading\s+and\s+use\s+of\s+english|use\s+of\s+english|reading)\b[\s:.\-—–]*",
            "", body, flags=re.IGNORECASE,
        )
        stripped = re.sub(r"^part\s*\d+\b[\s:.\-—–]*", "", stripped, flags=re.IGNORECASE)
        if stripped == body:
            break
        body = stripped
    return re.sub(r"\W+", " ", body.lower()).strip()


def dedupe(examples: list[dict], *, threshold: float = 0.9) -> list[dict]:
    """Drop near-duplicates produced by overlapping chunks.

    Exact prefix matching is not enough: overlapping chunks (and OCR jitter)
    produce copies that diverge a couple of hundred characters in. Tasks from the
    same part are therefore compared by similarity, cheapest check first.
    """
    unique: list[dict] = []
    bodies_by_part: dict[int, list[str]] = {}

    for ex in examples:
        body = _canonical_body(ex["prompt_text"])
        peers = bodies_by_part.setdefault(ex["part"], [])
        head = body[:800]

        duplicate = False
        for other in peers:
            if other[:600] == head[:600]:
                duplicate = True
                break
            # Length gate: very different lengths cannot be near-duplicates.
            shorter, longer = sorted((len(other), len(head)))
            if longer and shorter / longer < threshold:
                continue
            # autojunk must be off: cloze passages repeat words often, and the
            # default junk heuristic would collapse the similarity score.
            matcher = difflib.SequenceMatcher(None, other, head, autojunk=False)
            if matcher.real_quick_ratio() < threshold:
                continue
            if matcher.quick_ratio() < threshold:
                continue
            if matcher.ratio() >= threshold:
                duplicate = True
                break

        if not duplicate:
            peers.append(head)
            unique.append(ex)

    return unique


def structure_chunk_with_ai(chunk_text: str, first_page: int, source_label: str,
                            model: str | None) -> list[dict]:
    """Ask the model to extract examples from one chunk of book text."""
    from app.ai import ai_available, chat_create

    if not ai_available:
        sys.exit(
            "No AI provider configured. Set OPENAI_API_KEY (or GROQ_API_KEY / "
            "GOOGLE_AI_API_KEY) in .env, or run `structure --no-ai`."
        )

    user = (
        f"The material is pages {first_page} onward from: {source_label}\n\n"
        f"--- BEGIN BOOK TEXT ---\n{chunk_text}\n--- END BOOK TEXT ---\n\n"
        "Return the JSON array of complete tasks."
    )
    resp = chat_create(
        [
            {"role": "system", "content": STRUCTURE_SYSTEM_PROMPT},
            {"role": "user", "content": user},
        ],
        temperature=0.0,
        model=model,
    )
    raw = resp.choices[0].message.content
    items = parse_json_array(raw)
    out = []
    for item in items:
        normalised = normalise_example(item, source_label=source_label, default_page=first_page)
        if normalised:
            out.append(normalised)
        else:
            print(f"  - skipped unusable item (part={item.get('part')!r})", file=sys.stderr)
    return out


# Heuristic (no-AI) segmentation ──────────────────────────────────────────────

_PART_HEADING_RE = re.compile(
    r"(?:reading\s+and\s+use\s+of\s+english|use\s+of\s+english|reading)?"
    r"[\s\-—–]*part\s*([1-7])\b",
    re.IGNORECASE,
)
# Section headings that switch which paper we are inside. Order matters: the
# combined "Reading and Use of English" must win over a bare "Reading".
_PAPER_SECTION_RE = re.compile(
    r"reading\s+and\s+use\s+of\s+english"
    r"|use\s+of\s+english"
    r"|listening"
    r"|writing"
    r"|speaking"
    r"|reading",
    re.IGNORECASE,
)
_NON_EXAM_PAPERS = {"listening", "writing", "speaking"}


def _paper_events(full: str) -> list[tuple[int, str]]:
    """Chronological (position, normalised paper) events for section headings."""
    events = []
    for match in _PAPER_SECTION_RE.finditer(full):
        label = re.sub(r"\s+", " ", match.group(0)).strip().lower()
        if label.startswith("reading and") or label.startswith("use of"):
            paper = "use_of_english"
        else:
            paper = label
        events.append((match.start(), paper))
    return events


def structure_heuristic(pages: list[str], source_label: str, page_offset: int = 0) -> list[dict]:
    """Segment by printed 'Part N' headings. Crude — prefer --ai when possible.

    Walks the text in order, tracking the most recent paper section so that
    Listening/Writing/Speaking parts are skipped and Reading & Use of English
    parts are kept even when their heading is far from the section title.
    """
    marked: list[str] = []
    for i, page in enumerate(pages, 1):
        marked.append(PAGE_MARKER.format(n=i + page_offset))
        marked.append(page)
    full = "\n".join(marked)

    matches = list(_PART_HEADING_RE.finditer(full))
    if not matches:
        print("  ! no 'Part N' headings found; cannot segment without --ai", file=sys.stderr)
        return []

    paper_events = _paper_events(full)
    page_markers = [(m.start(), int(m.group(1)))
                    for m in re.finditer(r"===\s*PAGE\s+(\d+)\s*===", full)]

    def current_paper(pos: int) -> str | None:
        paper = None
        for event_pos, label in paper_events:
            if event_pos > pos:
                break
            paper = label
        return paper

    def page_at(pos: int) -> int:
        page = 1 + page_offset
        for marker_pos, num in page_markers:
            if marker_pos > pos:
                break
            page = num
        return page

    examples: list[dict] = []
    for idx, match in enumerate(matches):
        part = int(match.group(1))
        if part not in PART_META:
            continue
        if current_paper(match.start()) in _NON_EXAM_PAPERS:
            continue
        end = matches[idx + 1].start() if idx + 1 < len(matches) else len(full)
        body = full[match.end():end].strip()
        if len(body) < 120:
            continue
        paper, task_type = PART_META[part]
        examples.append({
            "paper": paper,
            "part": part,
            "task_type": task_type,
            "topic": "",
            "level": "b2",
            "prompt_text": body,
            "metadata": {
                "source": source_label,
                "source_page": page_at(match.start()),
                "origin": "imported",
                "structured": "heuristic",
            },
        })
    return dedupe(examples)


def _write_examples(path: Path, examples: list[dict]) -> None:
    """Write the corpus JSON (also used as a per-chunk checkpoint)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(examples, indent=2, ensure_ascii=False), encoding="utf-8")


def cmd_structure(args) -> int:
    text_path = Path(args.text) if args.text else None
    if text_path is None:
        candidates = sorted(MATERIALS_DIR.glob("*.txt"))
        if not candidates:
            sys.exit("No text file given and nothing found in materials/. Run `extract` first.")
        text_path = candidates[-1]
    if not text_path.exists():
        sys.exit(f"Text file not found: {text_path}")

    pages = load_pages(text_path)
    total = len(pages)
    start, end = parse_page_range(args.pages, total)
    selected = pages[start - 1:end]
    # Page markers in the file are absolute, so keep source_page absolute.
    base_page = first_page_number(text_path) + start - 1
    source_label = args.source_label or text_path.stem.replace("_", " ")

    print(f"Structuring {len(selected)}/{total} page(s) from {text_path}")

    out = Path(args.out) if args.out else text_path.with_suffix(".examples.json")
    out.parent.mkdir(parents=True, exist_ok=True)

    if args.no_ai:
        examples = structure_heuristic(selected, source_label, page_offset=base_page - 1)
    else:
        examples = []
        failures = 0
        chunks = chunk_pages(selected, max_chars=args.chunk_chars, start_number=base_page)
        total_chunks = len(chunks)
        for index, (first_page, chunk) in enumerate(chunks, 1):
            print(f"  · chunk {index}/{total_chunks} at page {first_page} ({len(chunk)} chars)")
            try:
                examples.extend(
                    structure_chunk_with_ai(chunk, first_page, source_label, args.model)
                )
            except Exception as exc:
                # One bad chunk (provider overload, retired model, timeout) must
                # not discard everything already extracted.
                failures += 1
                print(f"    ! chunk at page {first_page} failed: {str(exc)[:200]}",
                      file=sys.stderr)
            # Checkpoint after every chunk so a crash never loses progress.
            _write_examples(out, dedupe(examples))
        examples = dedupe(examples)
        if failures:
            print(f"  ! {failures}/{total_chunks} chunk(s) failed; "
                  f"re-run with --pages to fill the gaps")

    _write_examples(out, examples)

    by_part: dict[int, int] = {}
    for ex in examples:
        by_part[ex["part"]] = by_part.get(ex["part"], 0) + 1
    print(f"\nFound {len(examples)} example(s) -> {out}")
    for part in sorted(by_part):
        print(f"  Part {part}: {by_part[part]}")
    if not examples:
        print("  ! nothing extracted. Try a bigger --pages range, or check that the "
              "PDF has real text (scanned books need OCR).")
    else:
        print(f"\nReview {out}, then:  python -m scripts.import_examples load {out} --commit")
    return 0


# ── merge ────────────────────────────────────────────────────────────────────

def cmd_merge(args) -> int:
    """Combine several examples.json files into one deduplicated corpus file."""
    combined: list[dict] = []
    for name in args.inputs:
        path = Path(name)
        if not path.exists():
            sys.exit(f"JSON not found: {path}")
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            sys.exit(f"{path} is not valid JSON: {exc}")
        if not isinstance(data, list):
            sys.exit(f"{path} must contain a JSON array")
        print(f"  + {len(data):>4} from {path.name}")
        combined.extend(data)

    merged = dedupe(combined)
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(merged, indent=2, ensure_ascii=False), encoding="utf-8")

    by_part: dict[int, int] = {}
    for ex in merged:
        by_part[ex["part"]] = by_part.get(ex["part"], 0) + 1
    print(f"\nMerged {len(combined)} -> {len(merged)} unique example(s) -> {out}")
    for part in sorted(by_part):
        print(f"  Part {part}: {by_part[part]}")
    print(f"\nReview {out}, then:  python -m scripts.import_examples load {out} --commit")
    return 0


# ── Stage 3: load ────────────────────────────────────────────────────────────

def _validate_item(item: dict) -> str | None:
    """Return an error string if the item cannot be loaded, else None."""
    if not isinstance(item, dict):
        return "not an object"
    missing = [k for k in ("paper", "part", "prompt_text") if not item.get(k)]
    if missing:
        return f"missing {', '.join(missing)}"
    try:
        part = int(item["part"])
    except (TypeError, ValueError):
        return f"invalid part {item['part']!r}"
    if part not in PART_META:
        return f"unsupported part {part}"
    prompt_text = str(item["prompt_text"]).strip()
    if len(prompt_text) < 120:
        return "prompt_text too short"
    # Reject examples that do not match the part's format, so a mislabelled
    # Listening/Writing task never becomes a style reference for generation.
    return part_format_problem(part, prompt_text)


def cmd_audit(args) -> int:
    """Report corpus entries whose content does not match their declared part."""
    path = Path(args.json)
    if not path.exists():
        sys.exit(f"JSON not found: {path}")
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, list):
        sys.exit(f"{path} must contain a JSON array")

    problems: list[tuple[int, dict, str]] = []
    warnings: list[tuple[int, dict, str]] = []
    for index, item in enumerate(data):
        if not isinstance(item, dict):
            problems.append((index, {"part": "?", "topic": ""}, "not an object"))
            continue
        try:
            part = int(item.get("part"))
        except (TypeError, ValueError):
            problems.append((index, item, "invalid part"))
            continue
        text = str(item.get("prompt_text") or "")
        reason = part_format_problem(part, text)
        if reason:
            problems.append((index, item, reason))
            continue
        warning = part_format_warning(part, text)
        if warning:
            warnings.append((index, item, warning))

    print(f"{path}: {len(data)} entries")
    print(f"  definitely wrong (will be rejected on load): {len(problems)}")
    print(f"  suspicious, review manually:                 {len(warnings)}")
    for label, group in (("WRONG", problems), ("REVIEW", warnings)):
        if not group:
            continue
        print(f"\n--- {label} ---")
        for index, item, reason in group[:args.limit]:
            topic = str(item.get("topic") or "")[:28]
            print(f"  idx={index:<4} part={item.get('part')} topic={topic:<28} -> {reason}")
        if len(group) > args.limit:
            print(f"  … and {len(group) - args.limit} more")

    if args.drop:
        bad_indexes = {index for index, _, _ in problems}
        kept = [item for index, item in enumerate(data) if index not in bad_indexes]
        _write_examples(path, kept)
        print(f"\nWrote {len(kept)} kept entries back to {path} "
              f"(dropped {len(bad_indexes)})")
    return 0


def cmd_load(args) -> int:
    path = Path(args.json)
    if not path.exists():
        sys.exit(f"JSON not found: {path}")
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        sys.exit(f"{path} is not valid JSON: {exc}")
    if not isinstance(data, list):
        sys.exit(f"{path} must contain a JSON array of examples")

    # Validate first so a dry run reports exactly what --commit would do.
    valid: list[dict] = []
    skipped = 0
    for item in data:
        error = _validate_item(item)
        if error:
            skipped += 1
            print(f"  - skipped ({error})", file=sys.stderr)
        else:
            valid.append(item)

    if not args.commit:
        print(f"Dry run: {len(valid)} of {len(data)} example(s) would load "
              f"into {rag_db_path()} ({skipped} skipped).")
        print("Nothing was written. Re-run with --commit to store them.")
        return 0

    ensure_rag_tables()
    before = count_examples()

    added = 0
    for item in valid:
        add_example(
            paper=item["paper"],
            part=int(item["part"]),
            task_type=item.get("task_type", ""),
            topic=item.get("topic", ""),
            prompt_text=item["prompt_text"],
            level=item.get("level", "b2"),
            metadata=item.get("metadata"),
            search_text=item.get("search_text"),
        )
        added += 1

    after = count_examples()
    print(f"Loaded {added} example(s) into {rag_db_path()} ({skipped} skipped)")
    print(f"Corpus size: {before} -> {after}")

    if added and not args.no_embeddings:
        print("Computing embeddings...")
        updated = rebuild_embeddings()
        if updated:
            print(f"Embeddings stored for {updated} example(s).")
        else:
            print("  ! no embeddings were computed — retrieval will fall back to "
                  "keyword matching. Check your embedding provider/credits.")
    elif added:
        print("Embeddings skipped (--no-embeddings); retrieval will use keyword matching.")
    return 0


# ── run (all three stages) ───────────────────────────────────────────────────

def cmd_run(args) -> int:
    class _Args:
        pass

    extract_args = _Args()
    extract_args.source = args.source
    extract_args.pages = args.pages
    extract_args.out = None
    extract_args.ocr = getattr(args, "ocr", False)
    extract_args.no_ocr = getattr(args, "no_ocr", False)
    extract_args.dpi = getattr(args, "dpi", 200)
    rc = cmd_extract(extract_args)
    if rc:
        return rc

    source = Path(args.source).expanduser()
    text_path = MATERIALS_DIR / f"{source.stem}.txt"

    structure_args = _Args()
    structure_args.text = str(text_path)
    structure_args.pages = None
    structure_args.no_ai = args.no_ai
    structure_args.out = str(text_path.with_suffix(".examples.json"))
    structure_args.model = args.model
    structure_args.chunk_chars = args.chunk_chars
    structure_args.source_label = args.source_label or source.stem.replace("_", " ")
    rc = cmd_structure(structure_args)
    if rc:
        return rc

    load_args = _Args()
    load_args.json = structure_args.out
    load_args.commit = args.commit
    load_args.no_embeddings = args.no_embeddings
    return cmd_load(load_args)


# ── CLI ──────────────────────────────────────────────────────────────────────

def main() -> int:
    parser = argparse.ArgumentParser(
        description="Import real FCE exercises from your own material into the RAG corpus.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    sub = parser.add_subparsers(dest="command", required=True)

    p_extract = sub.add_parser("extract", help="PDF/DOCX/TXT -> text with page markers")
    p_extract.add_argument("source", help="Path to the book (.pdf, .docx, .txt, .md)")
    p_extract.add_argument("--pages", help="Page range, e.g. '12-40' or '7'")
    p_extract.add_argument("--out", help="Output .txt path (default materials/<stem>.txt)")
    p_extract.add_argument("--ocr", action="store_true",
                           help="Force OCR (macOS Vision) even if the PDF has a text layer")
    p_extract.add_argument("--no-ocr", action="store_true",
                           help="Never OCR; keep whatever text layer exists")
    p_extract.add_argument("--dpi", type=int, default=200,
                           help="Render DPI for OCR (default 200)")
    p_extract.set_defaults(func=cmd_extract)

    p_structure = sub.add_parser("structure", help="Text -> JSON examples (AI by default)")
    p_structure.add_argument("--text", help="Extracted .txt (defaults to newest in materials/)")
    p_structure.add_argument("--pages", help="Page range within the text file")
    p_structure.add_argument("--no-ai", action="store_true",
                             help="Use the 'Part N' heading heuristic instead of AI")
    p_structure.add_argument("--out", help="Output .json path")
    p_structure.add_argument("--model", help="Override the AI model")
    p_structure.add_argument("--chunk-chars", type=int, default=12000,
                             help="Approx characters per AI request (default 12000). "
                                  "Lower it if tasks are being missed in dense books.")
    p_structure.add_argument("--source-label", help="Human-readable source name for metadata")
    p_structure.set_defaults(func=cmd_structure)

    p_merge = sub.add_parser("merge", help="Combine several examples JSON files, deduplicated")
    p_merge.add_argument("out", help="Output .json path for the merged corpus")
    p_merge.add_argument("inputs", nargs="+", help="Input .json files")
    p_merge.set_defaults(func=cmd_merge)

    p_audit = sub.add_parser("audit", help="Report entries that do not match their part's format")
    p_audit.add_argument("json", help="Path to the examples .json")
    p_audit.add_argument("--limit", type=int, default=40, help="How many problems to list")
    p_audit.add_argument("--drop", action="store_true",
                         help="Rewrite the file with the bad entries removed")
    p_audit.set_defaults(func=cmd_audit)

    p_load = sub.add_parser("load", help="JSON -> RAG database")
    p_load.add_argument("json", help="Path to the examples .json")
    p_load.add_argument("--commit", action="store_true",
                        help="Actually write to the database (otherwise dry run)")
    p_load.add_argument("--no-embeddings", action="store_true",
                        help="Skip computing embeddings after loading")
    p_load.set_defaults(func=cmd_load)

    p_run = sub.add_parser("run", help="extract + structure + load in one go")
    p_run.add_argument("source", help="Path to the book")
    p_run.add_argument("--pages", help="Page range, e.g. '12-40'")
    p_run.add_argument("--no-ai", action="store_true", help="Use the heading heuristic")
    p_run.add_argument("--model", help="Override the AI model")
    p_run.add_argument("--chunk-chars", type=int, default=12000,
                       help="Approx characters per AI request (default 12000)")
    p_run.add_argument("--source-label", help="Human-readable source name for metadata")
    p_run.add_argument("--commit", action="store_true", help="Write to the database")
    p_run.add_argument("--no-embeddings", action="store_true")
    p_run.add_argument("--ocr", action="store_true", help="Force OCR for the PDF")
    p_run.add_argument("--no-ocr", action="store_true", help="Never OCR the PDF")
    p_run.add_argument("--dpi", type=int, default=200, help="OCR render DPI (default 200)")
    p_run.set_defaults(func=cmd_run)

    args = parser.parse_args()
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
