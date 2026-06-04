#!/usr/bin/env python3
"""Search the web for B2 First / FCE Part 3 word-formation examples.

The script intentionally stores short snippets plus source URLs, not whole pages.
Use the collected examples as review material or inspiration before adding your
own original tasks to the app.

Examples:
    python scripts/search_fce_word_formation.py --limit 15 --out /tmp/fce_part3_examples.json
    python scripts/search_fce_word_formation.py --format markdown --out /tmp/fce_part3_examples.md
    python scripts/search_fce_word_formation.py --query "B2 First word formation PDF" --limit 10
"""
from __future__ import annotations

import argparse
import json
import re
import sys
import time
from collections.abc import Iterable
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from html import unescape
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import parse_qs, quote_plus, unquote, urlparse

import requests


DEFAULT_QUERIES = [
    "FCE word formation exercises answers",
    "B2 First Use of English Part 3 word formation exercise",
    "Cambridge B2 First word formation practice answers",
    "FCE word formation PDF answers",
]

USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/125.0 Safari/537.36"
)

TASK_GAP_RE = re.compile(r"\(\s*[1-8]\s*\)\s*(?:_{3,}|\.{3,}|\[[^\]]{0,20}\])")
STEM_LINE_RE = re.compile(r"\(([A-Z][A-Z-]{2,})\)\.?\s*$")
UPPER_WORD_RE = re.compile(r"\b[A-Z][A-Z-]{2,}\b")
SPACE_RE = re.compile(r"[ \t\r\f\v]+")
BLOCK_BREAK_RE = re.compile(r"\n{3,}")

IGNORED_UPPER_WORDS = {
    "B2",
    "CAE",
    "CAMBRIDGE",
    "CERTIFICATE",
    "ENGLISH",
    "EXAM",
    "EXERCISE",
    "EXERCISES",
    "FCE",
    "FIRST",
    "FORMATION",
    "KEY",
    "PART",
    "PDF",
    "QUESTIONS",
    "READING",
    "USE",
    "WORD",
    "WORDS",
}


@dataclass
class SearchHit:
    title: str
    url: str
    snippet: str = ""


@dataclass
class TaskCandidate:
    snippet: str
    gap_count: int
    stems: list[str]
    answer_key_hint: str = ""


@dataclass
class PageResult:
    title: str
    url: str
    score: int
    candidates: list[TaskCandidate]
    search_snippet: str = ""
    error: str = ""


class DuckDuckGoParser(HTMLParser):
    """Extract result links from DuckDuckGo's lightweight HTML page."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.results: list[SearchHit] = []
        self._in_result = False
        self._href = ""
        self._text: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag != "a":
            return
        attr = {name: value or "" for name, value in attrs}
        classes = attr.get("class", "")
        href = attr.get("href", "")
        if "result__a" in classes and href:
            self._in_result = True
            self._href = href
            self._text = []

    def handle_data(self, data: str) -> None:
        if self._in_result:
            self._text.append(data)

    def handle_endtag(self, tag: str) -> None:
        if tag != "a" or not self._in_result:
            return
        title = clean_text(" ".join(self._text))
        url = unwrap_duckduckgo_url(self._href)
        if title and url.startswith(("http://", "https://")):
            self.results.append(SearchHit(title=title, url=url))
        self._in_result = False
        self._href = ""
        self._text = []


class VisibleTextParser(HTMLParser):
    """Extract a readable title and body text from HTML."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.title = ""
        self.text_parts: list[str] = []
        self._in_title = False
        self._skip_depth = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag in {"script", "style", "noscript", "svg"}:
            self._skip_depth += 1
        elif tag == "title":
            self._in_title = True
        elif tag in {"p", "div", "section", "article", "li", "br", "tr", "h1", "h2", "h3", "h4"}:
            self.text_parts.append("\n")

    def handle_endtag(self, tag: str) -> None:
        if tag in {"script", "style", "noscript", "svg"} and self._skip_depth:
            self._skip_depth -= 1
        elif tag == "title":
            self._in_title = False
        elif tag in {"p", "div", "section", "article", "li", "tr", "h1", "h2", "h3", "h4"}:
            self.text_parts.append("\n")

    def handle_data(self, data: str) -> None:
        if self._skip_depth:
            return
        if self._in_title:
            self.title += data
        else:
            self.text_parts.append(data)

    def visible_text(self) -> str:
        return normalise_body_text("".join(self.text_parts))


def clean_text(value: str) -> str:
    value = unescape(value or "")
    value = SPACE_RE.sub(" ", value)
    return value.strip()


def normalise_body_text(value: str) -> str:
    value = unescape(value or "")
    value = value.replace("\xa0", " ")
    lines = [clean_text(line) for line in value.splitlines()]
    value = "\n".join(line for line in lines if line)
    return BLOCK_BREAK_RE.sub("\n\n", value).strip()


def unwrap_duckduckgo_url(url: str) -> str:
    if url.startswith("//"):
        url = "https:" + url
    parsed = urlparse(url)
    if parsed.path.startswith("/l/"):
        target = parse_qs(parsed.query).get("uddg", [""])[0]
        if target:
            return unquote(target)
    return url


def build_search_url(query: str) -> str:
    return "https://duckduckgo.com/html/?q={}&kl=us-en".format(quote_plus(query))


def search_duckduckgo(query: str, session: requests.Session, limit: int, timeout: float) -> list[SearchHit]:
    response = session.get(build_search_url(query), timeout=timeout)
    response.raise_for_status()
    parser = DuckDuckGoParser()
    parser.feed(response.text)
    return parser.results[:limit]


def fetch_visible_text(url: str, session: requests.Session, timeout: float) -> tuple[str, str]:
    response = session.get(url, timeout=timeout)
    response.raise_for_status()
    content_type = response.headers.get("content-type", "").lower()
    if "pdf" in content_type or url.lower().endswith(".pdf"):
        return "", "[PDF] {}".format(url)
    parser = VisibleTextParser()
    parser.feed(response.text)
    title = clean_text(parser.title)
    return title, parser.visible_text()


def unique_preserve_order(items: Iterable[str]) -> list[str]:
    seen = set()
    out = []
    for item in items:
        key = item.strip()
        if not key or key.lower() in seen:
            continue
        seen.add(key.lower())
        out.append(key)
    return out


def extract_stems(snippet: str) -> list[str]:
    stems = []
    for word in UPPER_WORD_RE.findall(snippet):
        cleaned = word.strip("-")
        if cleaned and cleaned not in IGNORED_UPPER_WORDS:
            stems.append(cleaned)
    return unique_preserve_order(stems)[:16]


def answer_key_hint(text: str, center: int, max_chars: int) -> str:
    lower = text.lower()
    search_start = max(0, center - 1000)
    search_end = min(len(text), center + 4000)
    window = text[search_start:search_end]
    marker_match = re.search(r"\b(answer key|answers?|key)\b", window, flags=re.IGNORECASE)
    if not marker_match:
        marker_match = re.search(r"\b(answer key|answers?|key)\b", lower[center: center + 8000], flags=re.IGNORECASE)
        if marker_match:
            start = center + marker_match.start()
        else:
            return ""
    else:
        start = search_start + marker_match.start()
    return clean_text(text[start: start + max_chars])


def extract_candidates(text: str, max_snippet_chars: int) -> list[TaskCandidate]:
    candidates: list[TaskCandidate] = []
    matches = list(TASK_GAP_RE.finditer(text))
    used_ranges: list[tuple[int, int]] = []
    for match in matches:
        start = max(0, match.start() - max_snippet_chars // 2)
        end = min(len(text), match.end() + max_snippet_chars // 2)

        nearby_matches = [m for m in matches if start <= m.start() <= end]
        if len(nearby_matches) < 2:
            continue
        start = max(0, nearby_matches[0].start() - 250)
        end = min(len(text), nearby_matches[-1].end() + 450)
        if end - start > max_snippet_chars:
            end = start + max_snippet_chars

        if any(abs(start - old_start) < 300 or (start >= old_start and end <= old_end) for old_start, old_end in used_ranges):
            continue
        used_ranges.append((start, end))

        snippet = clean_text(text[start:end])
        gap_count = len(TASK_GAP_RE.findall(snippet))
        candidates.append(
            TaskCandidate(
                snippet=snippet,
                gap_count=gap_count,
                stems=extract_stems(snippet),
                answer_key_hint=answer_key_hint(text, end, min(800, max_snippet_chars)),
            )
        )
    candidates.extend(extract_stem_line_candidates(text, max_snippet_chars=max_snippet_chars))
    candidates.sort(key=lambda item: (item.gap_count, len(item.stems)), reverse=True)
    return candidates[:3]


def extract_stem_line_candidates(text: str, max_snippet_chars: int) -> list[TaskCandidate]:
    """Extract pages that list word-formation sentences with stems like '(SCIENCE)'."""
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    example_rows: list[tuple[str, str]] = []
    for line in lines:
        if len(line) < 25 or len(line) > 240:
            continue
        match = STEM_LINE_RE.search(line)
        if match:
            stem = match.group(1).strip()
            if stem not in IGNORED_UPPER_WORDS:
                example_rows.append((line, stem))
    if len(example_rows) < 3:
        return []

    candidates = []
    for start in range(0, min(len(example_rows), 30), 10):
        chunk = example_rows[start: start + 10]
        if len(chunk) < 3:
            continue
        snippet = "\n".join(row[0] for row in chunk)
        if len(snippet) > max_snippet_chars:
            snippet = snippet[:max_snippet_chars].rsplit("\n", 1)[0]
        candidates.append(
            TaskCandidate(
                snippet=snippet,
                gap_count=len(chunk),
                stems=unique_preserve_order(row[1] for row in chunk),
                answer_key_hint="",
            )
        )
    return candidates


def score_page(title: str, text: str, candidates: list[TaskCandidate]) -> int:
    haystack = "{}\n{}".format(title, text[:5000]).lower()
    score = 0
    for keyword, weight in (
        ("word formation", 8),
        ("part 3", 5),
        ("use of english", 5),
        ("b2 first", 5),
        ("fce", 4),
        ("answers", 2),
        ("answer key", 3),
    ):
        if keyword in haystack:
            score += weight
    for candidate in candidates:
        score += min(candidate.gap_count, 8) * 2
        score += min(len(candidate.stems), 8)
    return score


def collect_examples(
    queries: list[str],
    limit: int,
    pages_per_query: int,
    fetch_pages: bool,
    delay: float,
    timeout: float,
    max_snippet_chars: int,
) -> dict:
    session = requests.Session()
    session.headers.update({"User-Agent": USER_AGENT})
    hits_by_url: dict[str, SearchHit] = {}

    for query in queries:
        try:
            hits = search_duckduckgo(query, session=session, limit=pages_per_query, timeout=timeout)
        except requests.RequestException as exc:
            print("Search failed for {!r}: {}".format(query, exc), file=sys.stderr)
            continue
        for hit in hits:
            hits_by_url.setdefault(hit.url, hit)
        time.sleep(delay)

    page_results: list[PageResult] = []
    for hit in list(hits_by_url.values())[:limit]:
        title = hit.title
        candidates: list[TaskCandidate] = []
        error = ""
        if fetch_pages:
            try:
                page_title, text = fetch_visible_text(hit.url, session=session, timeout=timeout)
                title = page_title or hit.title
                candidates = extract_candidates(text, max_snippet_chars=max_snippet_chars)
            except requests.RequestException as exc:
                error = str(exc)
            except UnicodeError as exc:
                error = str(exc)
            time.sleep(delay)
        score = score_page(title, hit.snippet, candidates)
        page_results.append(
            PageResult(
                title=title,
                url=hit.url,
                score=score,
                candidates=candidates,
                search_snippet=hit.snippet,
                error=error,
            )
        )

    page_results.sort(key=lambda item: item.score, reverse=True)
    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "queries": queries,
        "note": "Review sources and create original tasks before importing into the app.",
        "results": [asdict(result) for result in page_results],
    }


def write_output(data: dict, output_format: str, out_path: str | None) -> None:
    if output_format == "json":
        text = json.dumps(data, ensure_ascii=False, indent=2)
    elif output_format == "jsonl":
        rows = data.get("results", [])
        text = "\n".join(json.dumps(row, ensure_ascii=False) for row in rows)
    else:
        text = render_markdown(data)

    if out_path:
        Path(out_path).write_text(text + "\n", encoding="utf-8")
    else:
        print(text)


def render_markdown(data: dict) -> str:
    lines = [
        "# FCE / B2 First Word Formation Search Results",
        "",
        "Generated: {}".format(data.get("generated_at", "")),
        "",
        "Note: {}".format(data.get("note", "")),
        "",
    ]
    for index, result in enumerate(data.get("results", []), start=1):
        lines.extend([
            "## {}. {}".format(index, result.get("title") or result.get("url")),
            "",
            "- URL: {}".format(result.get("url", "")),
            "- Score: {}".format(result.get("score", 0)),
            "",
        ])
        if result.get("error"):
            lines.extend(["Fetch error: `{}`".format(result["error"]), ""])
        for cand_index, candidate in enumerate(result.get("candidates") or [], start=1):
            lines.extend([
                "### Candidate {}".format(cand_index),
                "",
                "- Items/gaps found: {}".format(candidate.get("gap_count", 0)),
                "- Possible stems: {}".format(", ".join(candidate.get("stems") or []) or "not detected"),
                "",
                "```text",
                candidate.get("snippet", ""),
                "```",
                "",
            ])
            if candidate.get("answer_key_hint"):
                lines.extend([
                    "Possible answer-key area:",
                    "",
                    "```text",
                    candidate["answer_key_hint"],
                    "```",
                    "",
                ])
    return "\n".join(lines).rstrip()


def self_test() -> None:
    sample_search = """
    <a rel="nofollow" class="result__a" href="/l/?uddg=https%3A%2F%2Fexample.com%2Ffce">FCE Word Formation</a>
    """
    parser = DuckDuckGoParser()
    parser.feed(sample_search)
    assert parser.results[0].url == "https://example.com/fce"
    sample_text = """
    B2 First Word Formation Part 3
    The (1)_____ of the museum surprised visitors. POPULAR
    Many people were (2)_____ impressed by the new design. PARTICULAR
    The guide spoke with great (3)_____. CONFIDENT
    Answers: 1 popularity 2 particularly 3 confidence
    """
    candidates = extract_candidates(normalise_body_text(sample_text), max_snippet_chars=1000)
    assert candidates
    assert candidates[0].gap_count == 3
    assert "POPULAR" in candidates[0].stems
    print("Self-test passed.")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--query", action="append", help="Search query. Can be used more than once.")
    parser.add_argument("--limit", type=int, default=20, help="Maximum unique URLs to return.")
    parser.add_argument("--pages-per-query", type=int, default=10, help="Search results to read per query.")
    parser.add_argument("--no-fetch", action="store_true", help="Only collect search result URLs; do not fetch pages.")
    parser.add_argument("--delay", type=float, default=1.0, help="Delay between HTTP requests in seconds.")
    parser.add_argument("--timeout", type=float, default=15.0, help="HTTP timeout in seconds.")
    parser.add_argument("--max-snippet-chars", type=int, default=1800, help="Maximum characters stored per snippet.")
    parser.add_argument("--format", choices=("json", "jsonl", "markdown"), default="json", help="Output format.")
    parser.add_argument("--out", help="Output file path. Defaults to stdout.")
    parser.add_argument("--self-test", action="store_true", help="Run parser self-test without internet access.")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if args.self_test:
        self_test()
        return 0

    queries = args.query or DEFAULT_QUERIES
    data = collect_examples(
        queries=queries,
        limit=max(1, args.limit),
        pages_per_query=max(1, args.pages_per_query),
        fetch_pages=not args.no_fetch,
        delay=max(0.0, args.delay),
        timeout=max(1.0, args.timeout),
        max_snippet_chars=max(400, args.max_snippet_chars),
    )
    write_output(data, output_format=args.format, out_path=args.out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
