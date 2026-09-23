"""Tests for the book-import pipeline helpers (scripts/import_examples.py).

Only the pure, offline helpers are covered — no PDF parsing and no AI calls.
"""
from __future__ import annotations

import pytest

from scripts.import_examples import (
    IMAGE_SUFFIXES,
    _order_reading,
    _validate_item,
    chunk_pages,
    collect_images,
    dedupe,
    first_page_number,
    is_probably_scanned,
    load_pages,
    normalise_example,
    pages_to_text,
    parse_json_array,
    parse_page_range,
    part_format_problem,
    part_format_warning,
    split_page_text,
    structure_heuristic,
)


# ── image (screenshot) import ────────────────────────────────────────────────

def test_collect_images_single_file(tmp_path):
    shot = tmp_path / "shot.png"
    shot.write_bytes(b"x")
    assert collect_images(shot) == [shot]


def test_collect_images_directory_is_sorted_and_filtered(tmp_path):
    for name in ("b.png", "a.png", "notes.txt", "c.jpg"):
        (tmp_path / name).write_bytes(b"x")
    found = [p.name for p in collect_images(tmp_path)]
    assert found == ["a.png", "b.png", "c.jpg"]


def test_collect_images_rejects_an_empty_directory(tmp_path):
    with pytest.raises(SystemExit):
        collect_images(tmp_path)


def test_image_suffixes_cover_common_screenshot_formats():
    for suffix in (".png", ".jpg", ".jpeg", ".webp"):
        assert suffix in IMAGE_SUFFIXES


# ── off-paper rejection ──────────────────────────────────────────────────────

LISTENING = (
    "You will hear a man talking about his job. For questions 1-8, choose the best "
    "answer. You hear a hotel manager talking to his staff. What is he doing? "
    "A informing them of something B inviting them to do something"
)
CLOZE = (
    "For questions 1-8, read the text below and decide which answer (A, B, C or D) "
    "best fits each gap. The home of (0) C athlete Helen Barnett was burgled and "
    "medals were (1)_____. 1 A robbed B mugged C lifted D stolen "
    "2 A runs B overtakes C works D holds"
)


@pytest.mark.parametrize("part", [1, 2, 3, 4, 5, 6, 7])
def test_listening_content_is_rejected_for_every_part(part):
    """A Listening task must never become a Reading/Use of English reference."""
    assert part_format_problem(part, LISTENING) is not None


@pytest.mark.parametrize("marker", [
    "Work in pairs. Discuss the questions.",
    "Write your essay in 140-190 words.",
    "Write your review of the film.",
    "There are two parts to this test.",
])
def test_speaking_and_writing_content_is_rejected(marker):
    assert part_format_problem(1, marker) is not None


def test_a_proper_cloze_is_accepted():
    assert part_format_problem(1, CLOZE) is None


# ── writing-plan detection (writing tasks labelled as reading/cloze) ─────────

WRITING_PLAN = (
    "Encouraging environmentalism on campus\n\n"
    "Introduction\n"
    "The purpose (0) in / of this report is to suggest ways in which people could be "
    "encouraged to protect our local environment.\n\n"
    "The individual\n"
    "On a personal level, we could promote the idea of reduce, reuse and recycle.\n\n"
    "The university\n"
    "As far as the university is concerned, it would be beneficial to look into "
    "renewable energy for all buildings on campus.\n"
)


def test_writing_plan_is_rejected():
    assert part_format_problem(1, WRITING_PLAN) is not None


def test_three_option_cloze_is_not_rejected():
    """Some books use 3 options; that is still a cloze, not a different paper."""
    text = ("(1) Placed / Fixed / Set in an area of outstanding beauty, the farm is ideal. "
            "We have spacious (2) pitches / parcels / lands for caravans.")
    assert part_format_problem(1, text) is None


def test_open_cloze_with_alternative_example_answer_is_not_rejected():
    """`(0) who/that` is the worked example, not a set of options."""
    text = ("How well do you know the people (0) who/that live in the same street? "
            "Perhaps you live in a large city, (1)_____ it's easy to go unnoticed. "
            "There's a site (2)_____ can help. When I moved to the area in (3)_____ I live.")
    assert part_format_problem(2, text) is None


def test_a_reading_text_with_one_heading_is_not_rejected():
    """A single 'Conclusion' heading must not condemn a reading passage."""
    text = ("The history of the bicycle\n\nConclusion\n"
            "Bicycles remain popular today and are (1) A seen B viewed C regarded D held "
            "as a green alternative to cars.")
    assert part_format_problem(5, text) is None


# ── textbook drill detection ─────────────────────────────────────────────────

@pytest.mark.parametrize("drill", [
    "1 Complete each sentence with one word from the box.\ndo make have take give\n"
    "1 ..take.. one of these pills three times a day.",
    "Complete each sentence with an adverb from box A and a word from box B.",
    "3 Complete each sentence with a passive form of the verb in brackets.",
    "Rewrite the following sentences using the word given.",
    "Match the words to their definitions.",
])
def test_textbook_drills_are_rejected(drill):
    """Language-focus exercises are the wrong shape to be exam style references."""
    assert part_format_problem(1, drill) is not None


def test_real_part1_cloze_is_not_mistaken_for_a_drill():
    text = ("Coming second: pleasure or pain?\n"
            "Every ambitious athlete hopes to (0) their dream of winning a gold medal. "
            "A team of psychologists recently (1)_____ some research on the emotional "
            "responses of those finishing second.\n"
            "0 A fulfil B finish C complete D succeed\n"
            "1 A made B did C took D gave")
    assert part_format_problem(1, text) is None


def test_word_formation_instructions_are_not_a_drill():
    """Part 3 has its own instruction wording and must survive."""
    text = ("For questions 1-8, read the text below. Use the word given in capitals at the "
            "end of some of the lines to form a word that fits in the gap.\n"
            "The (1)_____ of the centre has been delayed. COMPLETE\n"
            "She looked at him (2)_____ when he told the joke. SUSPECT")
    assert part_format_problem(3, text) is None


def test_validate_item_rejects_off_paper_content():
    """Loading must skip these, not just warn about them."""
    item = {"paper": "use_of_english", "part": 1, "prompt_text": LISTENING}
    error = _validate_item(item)
    assert error is not None
    assert "another paper" in error


def test_validate_item_accepts_a_proper_cloze():
    item = {"paper": "use_of_english", "part": 1, "prompt_text": CLOZE}
    assert _validate_item(item) is None


# ── soft warnings (report only, never auto-delete) ───────────────────────────

def test_warning_fires_but_does_not_reject():
    """A cloze with no visible options is suspicious, not certainly wrong."""
    text = "For questions 1-8, choose the best answer. The city was (1)_____ and (2)_____."
    assert part_format_problem(1, text) is None
    assert part_format_warning(1, text) is not None


def test_warning_is_silent_for_good_content():
    assert part_format_warning(1, CLOZE) is None


def test_warning_tolerates_ocr_gaps_rendered_as_dots():
    """OCR often renders gap underscores as dots; that must not be a warning."""
    text = "For questions 1-8, read the text and think of the word that fits. " + " ".join(
        f"({n})........" for n in range(1, 9)
    )
    assert part_format_warning(2, text) is None


# ── load validation ──────────────────────────────────────────────────────────

def test_validate_item_accepts_a_good_entry():
    item = {"paper": "reading", "part": 5, "prompt_text": "x" * 200}
    assert _validate_item(item) is None


@pytest.mark.parametrize("item,expected", [
    ({"part": 5, "prompt_text": "x" * 200}, "paper"),
    ({"paper": "reading", "prompt_text": "x" * 200}, "part"),
    ({"paper": "reading", "part": 5}, "prompt_text"),
    ({"paper": "reading", "part": 99, "prompt_text": "x" * 200}, "unsupported part"),
    ({"paper": "reading", "part": "abc", "prompt_text": "x" * 200}, "invalid part"),
    ({"paper": "reading", "part": 5, "prompt_text": "short"}, "too short"),
    ("not a dict", "not an object"),
])
def test_validate_item_rejects_bad_entries(item, expected):
    error = _validate_item(item)
    assert error is not None
    assert expected in error


# ── OCR reading order ────────────────────────────────────────────────────────
def _texts(items):
    return [it[3] for it in _order_reading(items)]


def test_order_reading_puts_option_row_back_in_abcd_order():
    """A question's options share a visual row but their baselines jitter slightly."""
    items = [
        (0.725, 0.1830, 0.06, "D boost"),
        (0.296, 0.1820, 0.10, "0 A advance"),
        (0.587, 0.1820, 0.04, "C rise"),
        (0.448, 0.1820, 0.04, "B lift"),
    ]
    assert _texts(items) == ["0 A advance", "B lift", "C rise", "D boost"]


def test_order_reading_sorts_rows_top_to_bottom():
    items = [
        (0.1, 0.2, 0.1, "lower"),
        (0.1, 0.9, 0.1, "upper"),
        (0.1, 0.5, 0.1, "middle"),
    ]
    assert _texts(items) == ["upper", "middle", "lower"]


def test_order_reading_reads_left_column_before_right():
    """Two-column pages must not interleave their lines."""
    items = [
        (0.10, 0.90, 0.25, "L1"),
        (0.62, 0.90, 0.25, "R1"),
        (0.10, 0.85, 0.25, "L2"),
        (0.62, 0.85, 0.25, "R2"),
        (0.10, 0.80, 0.25, "L3"),
        (0.62, 0.80, 0.25, "R3"),
    ]
    assert _texts(items) == ["L1", "L2", "L3", "R1", "R2", "R3"]


def test_order_reading_single_column_when_gutter_has_content():
    """Full-width lines mean one column, so pure top-to-bottom order is kept."""
    items = [
        (0.05, 0.90, 0.90, "wide1"),
        (0.05, 0.85, 0.90, "wide2"),
        (0.05, 0.80, 0.90, "wide3"),
        (0.05, 0.75, 0.90, "wide4"),
        (0.05, 0.70, 0.90, "wide5"),
        (0.05, 0.65, 0.90, "wide6"),
    ]
    assert _texts(items) == ["wide1", "wide2", "wide3", "wide4", "wide5", "wide6"]


def test_order_reading_handles_empty_input():
    assert _order_reading([]) == []


# ── page handling ────────────────────────────────────────────────────────────

def test_split_page_text_returns_bodies_not_numbers():
    text = "=== PAGE 1 ===\nFirst body\n\n=== PAGE 2 ===\nSecond body\n"
    assert split_page_text(text) == ["First body", "Second body"]


def test_pages_to_text_round_trips_through_split():
    pages = ["alpha", "beta", "gamma"]
    assert split_page_text(pages_to_text(pages)) == pages


def test_pages_to_text_uses_absolute_page_numbers():
    """A slice starting at book page 152 must keep those numbers in metadata."""
    text = pages_to_text(["body a", "body b"], start=152)
    assert "=== PAGE 152 ===" in text
    assert "=== PAGE 153 ===" in text
    assert "=== PAGE 1 ===" not in text


def test_load_pages_round_trips_absolute_numbering(tmp_path):
    """Extract -> load must preserve real book page numbers."""
    path = tmp_path / "book.txt"
    path.write_text(pages_to_text(["first", "second"], start=152), encoding="utf-8")
    assert load_pages(path) == ["first", "second"]
    assert first_page_number(path) == 152


def test_first_page_number_reads_marker(tmp_path):
    path = tmp_path / "book.txt"
    path.write_text(pages_to_text(["x", "y"], start=42), encoding="utf-8")
    assert first_page_number(path) == 42


def test_first_page_number_defaults_to_one_without_markers(tmp_path):
    path = tmp_path / "plain.txt"
    path.write_text("no markers here", encoding="utf-8")
    assert first_page_number(path) == 1


def test_is_probably_scanned_detects_image_only_pdfs():
    assert is_probably_scanned(["", "", ""]) is True
    assert is_probably_scanned(["short", "tiny"]) is True
    assert is_probably_scanned(["word " * 200, "word " * 200]) is False
    assert is_probably_scanned([]) is False


def test_parse_page_range_variants():
    assert parse_page_range(None, 100) == (1, 100)
    assert parse_page_range("7", 100) == (7, 7)
    assert parse_page_range("12-40", 100) == (12, 40)
    # end is clamped to the document length
    assert parse_page_range("90-500", 100) == (90, 100)


@pytest.mark.parametrize("spec", ["abc", "0", "40-12", "-", "1.5"])
def test_parse_page_range_rejects_bad_input(spec):
    with pytest.raises(SystemExit):
        parse_page_range(spec, 100)


# ── chunking ─────────────────────────────────────────────────────────────────

def test_chunk_pages_covers_every_page():
    pages = [f"page {i} " + "z" * 100 for i in range(10)]
    chunks = chunk_pages(pages, max_chars=300, overlap=1)

    covered = set()
    for _, chunk in chunks:
        for i in range(10):
            if f"page {i} " in chunk:
                covered.add(i)
    assert covered == set(range(10))


def test_chunk_pages_respects_max_chars_except_for_single_pages():
    pages = ["a" * 500, "b" * 500, "c" * 500]
    chunks = chunk_pages(pages, max_chars=600, overlap=0)
    assert len(chunks) >= 3


def test_chunk_pages_numbers_first_page_from_one():
    chunks = chunk_pages(["x" * 10, "y" * 10], max_chars=15, overlap=0)
    assert chunks[0][0] == 1


def test_chunk_pages_embeds_page_markers_so_source_page_is_accurate():
    """The model needs the markers in the prompt, else it guesses source_page."""
    chunks = chunk_pages(["alpha body", "beta body"], max_chars=1000, overlap=0)
    _, text = chunks[0]
    assert "=== PAGE 1 ===" in text
    assert "=== PAGE 2 ===" in text


def test_chunk_pages_honours_start_number_for_absolute_pages():
    chunks = chunk_pages(["a", "b"], max_chars=10, overlap=0, start_number=42)
    assert chunks[0][0] == 42
    assert "=== PAGE 42 ===" in chunks[0][1]
    assert "=== PAGE 43 ===" in chunks[0][1]


# ── AI response parsing ──────────────────────────────────────────────────────

def test_parse_json_array_plain():
    assert parse_json_array('[{"part": 1}]') == [{"part": 1}]


def test_parse_json_array_strips_markdown_fence():
    assert parse_json_array('```json\n[{"part": 2}]\n```') == [{"part": 2}]


def test_parse_json_array_recovers_from_surrounding_prose():
    raw = 'Here are the tasks:\n[{"part": 3}]\nHope that helps!'
    assert parse_json_array(raw) == [{"part": 3}]


def test_parse_json_array_accepts_wrapped_object():
    assert parse_json_array('{"examples": [{"part": 4}]}') == [{"part": 4}]


@pytest.mark.parametrize("raw", ["", "not json", "[]", "{broken", "null"])
def test_parse_json_array_returns_empty_for_unusable_input(raw):
    assert parse_json_array(raw) == []


# ── normalisation ────────────────────────────────────────────────────────────

def test_normalise_example_maps_part_to_paper_and_task_type():
    item = {"part": 5, "topic": "History of Tea", "prompt_text": "x" * 200, "source_page": 11}
    result = normalise_example(item, source_label="My Book", default_page=1)

    assert result["paper"] == "reading"
    assert result["task_type"] == "multiple_choice"
    assert result["topic"] == "history of tea"
    assert result["metadata"]["source"] == "My Book"
    assert result["metadata"]["source_page"] == 11


def test_normalise_example_falls_back_to_default_page():
    item = {"part": 2, "prompt_text": "y" * 200}
    result = normalise_example(item, source_label="Book", default_page=9)
    assert result["metadata"]["source_page"] == 9


def test_normalise_example_records_partial_flag():
    item = {"part": 1, "prompt_text": "z" * 200, "partial": True}
    result = normalise_example(item, source_label="Book", default_page=1)
    assert result["metadata"]["partial"] is True


@pytest.mark.parametrize("item", [
    {"part": 9, "prompt_text": "x" * 200},          # no such part
    {"part": "abc", "prompt_text": "x" * 200},      # not an int
    {"prompt_text": "x" * 200},                     # missing part
    {"part": 1, "prompt_text": "too short"},        # not enough body text
    {"part": 1},                                    # missing text
])
def test_normalise_example_rejects_unusable_items(item):
    assert normalise_example(item, source_label="Book", default_page=1) is None


# ── dedupe ───────────────────────────────────────────────────────────────────

def _example(part, text):
    return {"part": part, "prompt_text": text}


def test_dedupe_removes_chunk_overlap_duplicates():
    """The same task from two overlapping chunks differs only by leading labels."""
    first = _example(5, "Part 5\nYou are going to read an article about tea. " + "a" * 300)
    second = _example(5, "Reading\n\nPart 5\nYou are going to read an article about tea. " + "a" * 300)

    assert len(dedupe([first, second])) == 1


def test_dedupe_keeps_genuinely_different_tasks():
    first = _example(5, "Article about tea. " + "a" * 300)
    second = _example(5, "Article about bicycles. " + "b" * 300)
    assert len(dedupe([first, second])) == 2


def test_dedupe_keeps_same_text_in_different_parts():
    text = "Shared instruction body. " + "c" * 300
    assert len(dedupe([_example(1, text), _example(2, text)])) == 2


def test_dedupe_removes_near_duplicates_differing_midway():
    """Overlapping chunks / OCR jitter can diverge well past the first 600 chars."""
    base = "You are going to read an article in which four people talk. " + "detail " * 60
    variant = base.replace("four people", "four speakers", 1)
    assert dedupe([_example(7, base), _example(7, variant)]) == [_example(7, base)]


def test_dedupe_keeps_similar_length_but_distinct_tasks():
    first = "Article about the history of tea in China. " + "tea " * 60
    second = "Article about the history of coffee in Brazil. " + "coffee " * 60
    assert len(dedupe([_example(5, first), _example(5, second)])) == 2


# ── heuristic segmentation ───────────────────────────────────────────────────

def test_structure_heuristic_finds_parts_after_long_passages():
    pages = [
        "Reading and Use of English\n\nPart 1\n" + "Passage body one. " * 30
        + "\n\nPart 2\n" + "Passage body two. " * 30,
    ]
    results = structure_heuristic(pages, "My Book")

    assert {r["part"] for r in results} == {1, 2}
    assert all(r["metadata"]["structured"] == "heuristic" for r in results)


def test_structure_heuristic_skips_listening_and_writing_sections():
    pages = [
        "Listening\n\nPart 1\n" + "Audio transcript body. " * 40
        + "\n\nWriting\n\nPart 1\n" + "Essay instruction body. " * 40,
    ]
    assert structure_heuristic(pages, "My Book") == []


def test_structure_heuristic_returns_empty_without_headings():
    assert structure_heuristic(["Just some prose with no part headings at all."], "Book") == []


def test_structure_heuristic_records_source_page():
    pages = [
        "Reading and Use of English\n\nPart 1\n" + "First page body. " * 30,
        "Part 2\n" + "Second page body. " * 30,
    ]
    results = {r["part"]: r["metadata"]["source_page"] for r in structure_heuristic(pages, "Book")}
    assert results[1] == 1
    assert results[2] == 2
