"""Tests for app.utils — shared helpers."""
from __future__ import annotations

import json

from app.utils import (
    answers_match,
    e,
    extract_json_array,
    extract_json_object,
    format_explanation_list,
    login_required,
    norm,
    validate_get_phrase_data,
    validate_part1_data,
    validate_part2_data,
    validate_part3_data,
    validate_part5_data,
    word_count,
)


# ---------------------------------------------------------------------------
# norm / e / word_count
# ---------------------------------------------------------------------------

class TestNorm:
    def test_basic(self):
        assert norm("  Hello  World  ") == "hello world"

    def test_none(self):
        assert norm(None) == ""

    def test_empty(self):
        assert norm("") == ""


class TestHtmlEscape:
    def test_escapes_angle_brackets(self):
        assert e("<script>") == "&lt;script&gt;"

    def test_none_returns_empty(self):
        assert e(None) == ""


class TestWordCount:
    def test_counts(self):
        assert word_count("hello world foo") == 3

    def test_empty(self):
        assert word_count("") == 0
        assert word_count(None) == 0


# ---------------------------------------------------------------------------
# answers_match
# ---------------------------------------------------------------------------

class TestAnswersMatch:
    def test_exact(self):
        assert answers_match("hello", "hello")

    def test_case_insensitive(self):
        assert answers_match("Hello", "hello")

    def test_close_match(self):
        assert answers_match("travelling", "traveling")

    def test_no_match(self):
        assert not answers_match("cat", "dog")

    def test_empty(self):
        assert not answers_match("", "dog")
        assert not answers_match("cat", "")


# ---------------------------------------------------------------------------
# JSON extraction
# ---------------------------------------------------------------------------

class TestExtractJsonObject:
    def test_simple(self):
        result = extract_json_object('Here is the result: {"key": "value"}')
        assert result == {"key": "value"}

    def test_none_when_no_json(self):
        assert extract_json_object("no json here") is None

    def test_none_when_empty(self):
        assert extract_json_object("") is None
        assert extract_json_object(None) is None

    def test_nested(self):
        result = extract_json_object('{"a": {"b": 1}}')
        assert result["a"]["b"] == 1


class TestExtractJsonArray:
    def test_simple(self):
        result = extract_json_array('Result: [1, 2, 3]')
        assert result == [1, 2, 3]

    def test_none_when_no_array(self):
        assert extract_json_array("no array") is None

    def test_none_when_empty(self):
        assert extract_json_array("") is None
        assert extract_json_array(None) is None

    def test_strings(self):
        result = extract_json_array('["a", "b", "c"]')
        assert result == ["a", "b", "c"]


# ---------------------------------------------------------------------------
# Validation helpers
# ---------------------------------------------------------------------------

class TestValidatePart1Data:
    def test_valid(self):
        data = {
            "text": "Some text with (1)_____ and gaps",
            "gaps": [
                {"options": ["a", "b", "c", "d"], "correct": 0}
                for _ in range(8)
            ],
        }
        result = validate_part1_data(data)
        assert result is not None
        assert len(result["gaps"]) == 8

    def test_wrong_gap_count(self):
        data = {"text": "text", "gaps": [{"options": ["a", "b", "c", "d"], "correct": 0}]}
        assert validate_part1_data(data) is None

    def test_wrong_option_count(self):
        data = {
            "text": "text",
            "gaps": [
                {"options": ["a", "b"], "correct": 0}
                for _ in range(8)
            ],
        }
        assert validate_part1_data(data) is None

    def test_missing_text(self):
        data = {"text": "", "gaps": [{"options": ["a", "b", "c", "d"], "correct": 0}] * 8}
        assert validate_part1_data(data) is None


class TestValidatePart2Data:
    def test_valid(self):
        text = " ".join(f"word ({i})_____ more" for i in range(1, 9))
        data = {"text": text, "answers": ["a"] * 8}
        result = validate_part2_data(data)
        assert result is not None
        assert len(result["answers"]) == 8

    def test_missing_gap_markers(self):
        data = {"text": "no gaps here", "answers": ["a"] * 8}
        assert validate_part2_data(data) is None

    def test_wrong_answer_count(self):
        text = " ".join(f"({i})_____" for i in range(1, 9))
        data = {"text": text, "answers": ["a"] * 5}
        assert validate_part2_data(data) is None


class TestValidatePart3Data:
    def test_valid(self):
        text = " ".join(f"word ({i})_____ more" for i in range(1, 9))
        data = {"text": text, "stems": ["STEM"] * 8, "answers": ["answer"] * 8}
        result = validate_part3_data(data)
        assert result is not None
        assert all(s == "STEM" for s in result["stems"])

    def test_missing_stems(self):
        text = " ".join(f"({i})_____" for i in range(1, 9))
        data = {"text": text, "stems": ["STEM"] * 5, "answers": ["a"] * 8}
        assert validate_part3_data(data) is None


class TestValidatePart5Data:
    def test_valid(self):
        data = {
            "title": "Test Title",
            "text": " ".join(["word"] * 500),
            "questions": [
                {"q": f"Question {i}", "options": ["a", "b", "c", "d"], "correct": 0}
                for i in range(6)
            ],
        }
        result = validate_part5_data(data)
        assert result is not None
        assert len(result["questions"]) == 6

    def test_text_too_short(self):
        data = {
            "title": "Title",
            "text": "short",
            "questions": [{"q": "q", "options": ["a", "b", "c", "d"], "correct": 0}] * 6,
        }
        assert validate_part5_data(data) is None

    def test_wrong_question_count(self):
        data = {
            "title": "Title",
            "text": " ".join(["word"] * 500),
            "questions": [{"q": "q", "options": ["a", "b", "c", "d"], "correct": 0}] * 3,
        }
        assert validate_part5_data(data) is None


class TestValidateGetPhraseData:
    def test_valid(self):
        text = " ".join(f"word ({i})_____ more" for i in range(1, 9))
        data = {"text": text, "answers": ["get over"] * 8}
        result = validate_get_phrase_data(data)
        assert result is not None
        assert all(a == "get over" for a in result["answers"])

    def test_missing_markers(self):
        data = {"text": "no markers", "answers": ["a"] * 8}
        assert validate_get_phrase_data(data) is None


# ---------------------------------------------------------------------------
# format_explanation_list
# ---------------------------------------------------------------------------

class TestFormatExplanationList:
    def test_empty_details(self):
        assert format_explanation_list([], []) == ""

    def test_correct_item(self):
        details = [{"correct": True, "explanation": "Good job"}]
        html = format_explanation_list(details, ["answer"], total=1)
        assert "Good job" in html
        assert "part2-expl-correct" in html

    def test_wrong_item(self):
        details = [{"correct": False, "expected": "right", "explanation": "Wrong because..."}]
        html = format_explanation_list(details, ["right"], total=1)
        assert "Wrong because" in html
        assert "part2-expl-wrong" in html
        assert "right" in html
