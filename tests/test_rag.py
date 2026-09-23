"""Tests for the RAG example corpus, retrieval, and prompt formatting.

Each test points RAG_DB_PATH at a temporary file so the real corpus is untouched.
Embeddings are never computed here: get_embedding is stubbed so the suite makes
no network calls and the keyword fallback is exercised deterministically.
"""
from __future__ import annotations

import numpy as np
import pytest

from app.rag import retrieval
from app.rag.embeddings import (
    active_backend,
    active_model_name,
    cosine_similarity,
    embedding_to_bytes,
    bytes_to_embedding,
    rebuild_embeddings,
)
from app.rag.retrieval import format_examples_for_prompt, retrieve_examples
from app.rag.store import (
    add_example,
    count_examples,
    delete_example,
    ensure_rag_tables,
    get_example,
    list_examples,
)


@pytest.fixture()
def rag_db(tmp_path, monkeypatch):
    """Isolated RAG database for one test."""
    monkeypatch.setenv("RAG_DB_PATH", str(tmp_path / "rag.db"))
    ensure_rag_tables()
    return tmp_path / "rag.db"


@pytest.fixture()
def no_embeddings(monkeypatch):
    """Force the keyword fallback path (no OpenAI calls)."""
    monkeypatch.setattr(retrieval, "get_embedding", lambda text: None)


def _add(**overrides):
    payload = {
        "paper": "use_of_english",
        "part": 2,
        "task_type": "open_cloze",
        "topic": "travel",
        "prompt_text": "A passage about travel with (1)_____ and (2)_____ gaps.",
    }
    payload.update(overrides)
    return add_example(**payload)


def test_tables_are_created_and_start_empty(rag_db):
    assert count_examples() == 0
    assert list_examples() == []


def test_add_and_fetch_example(rag_db):
    example_id = _add()
    fetched = get_example(example_id)

    assert fetched is not None
    assert fetched["paper"] == "use_of_english"
    assert fetched["part"] == 2
    assert fetched["topic"] == "travel"
    # embedding bytes must never leak into the returned dict
    assert "embedding" not in fetched


def test_add_normalises_case(rag_db):
    example_id = _add(paper="Reading", task_type="Multiple_Choice", topic="History")
    fetched = get_example(example_id)
    assert fetched["paper"] == "reading"
    assert fetched["task_type"] == "multiple_choice"
    assert fetched["topic"] == "history"


def test_search_text_is_derived_when_not_supplied(rag_db):
    example_id = _add(metadata={"target_reader": "a teacher", "purpose": "an article"})
    search_text = get_example(example_id)["search_text"]
    assert "Part 2" in search_text
    assert "topic: travel" in search_text
    assert "target reader: a teacher" in search_text


def test_list_filters_by_paper_and_part(rag_db):
    _add(part=1, task_type="multiple_choice_cloze")
    _add(part=2)
    _add(paper="reading", part=5, task_type="multiple_choice")

    assert len(list_examples()) == 3
    assert len(list_examples(paper="reading")) == 1
    assert len(list_examples(part=2)) == 1
    assert len(list_examples(paper="use_of_english", part=1)) == 1
    assert count_examples(paper="reading") == 1


def test_delete_example(rag_db):
    example_id = _add()
    assert delete_example(example_id) is True
    assert count_examples() == 0


def test_metadata_round_trips(rag_db):
    example_id = _add(metadata={"source": "My Book", "source_page": 42})
    assert get_example(example_id)["metadata"]["source"] == "My Book"


def test_retrieve_returns_empty_without_examples(rag_db, no_embeddings):
    assert retrieve_examples(paper="use_of_english", part=2, topic="travel") == []


def test_retrieve_only_returns_matching_part(rag_db, no_embeddings):
    _add(part=2, topic="travel")
    _add(part=3, task_type="word_formation", topic="travel")

    results = retrieve_examples(paper="use_of_english", part=2, topic="travel")
    assert len(results) == 1
    assert results[0]["part"] == 2


def test_keyword_fallback_ranks_topic_overlap(rag_db, no_embeddings):
    _add(topic="cooking and food", prompt_text="Food text " + "x" * 200)
    _add(topic="space exploration", prompt_text="Space text " + "x" * 200)

    results = retrieve_examples(paper="use_of_english", part=2, topic="space exploration", k=1)
    assert len(results) == 1
    assert results[0]["topic"] == "space exploration"


def test_retrieve_respects_k(rag_db, no_embeddings):
    for i in range(5):
        _add(topic=f"topic {i}", prompt_text=f"Body number {i} " + "y" * 150)

    assert len(retrieve_examples(paper="use_of_english", part=2, topic="", k=2)) == 2


def test_retrieved_example_has_no_embedding_blob(rag_db, no_embeddings):
    _add()
    results = retrieve_examples(paper="use_of_english", part=2, topic="travel")
    assert results
    assert "embedding" not in results[0]
    assert "metadata" in results[0]


def test_format_examples_for_prompt_empty():
    assert format_examples_for_prompt([]) == ""


def test_format_examples_for_prompt_includes_guardrail(rag_db, no_embeddings):
    _add()
    results = retrieve_examples(paper="use_of_english", part=2, topic="travel")
    block = format_examples_for_prompt(results)

    assert "REFERENCE EXAMPLES" in block
    assert "END REFERENCE EXAMPLES" in block
    # The anti-plagiarism instruction must always be present when examples are injected.
    assert "Do NOT copy sentences" in block
    assert "travel" in block


def test_get_rag_examples_text_is_safe_without_examples(rag_db, no_embeddings):
    from app.rag.helpers import get_rag_examples_text

    assert get_rag_examples_text(part=1, topic="anything") == ""


# ── how results were found (semantic vs fallback) ────────────────────────────

def test_embedding_results_are_labelled_with_a_similarity_score(rag_db, monkeypatch):
    """A log reader must be able to tell a real semantic match from a fallback."""
    _add_with_vector(2, "travel", np.ones(4, dtype=np.float32))
    monkeypatch.setattr(retrieval, "active_model_name", lambda: "test-model")
    monkeypatch.setattr(retrieval, "get_embedding", lambda text: np.ones(4, dtype=np.float32))

    results = retrieval.retrieve_examples(paper="use_of_english", part=2,
                                          topic="travel", task_type="open_cloze", k=1)
    assert results[0]["retrieval"] == "embedding"
    assert results[0]["score"] == pytest.approx(1.0, abs=1e-4)


def test_keyword_results_are_labelled_as_such(rag_db, no_embeddings):
    _add(topic="space exploration", prompt_text="Space text " + "x" * 200)
    results = retrieval.retrieve_examples(paper="use_of_english", part=2,
                                          topic="space exploration", k=1)
    assert results[0]["retrieval"] == "keyword"
    assert results[0]["score"] >= 1


def test_keyword_scoring_ignores_stopwords():
    """'a sculptor's block of stone' must match on sculptor/block/stone, not 'a'/'of'."""
    words = retrieval._content_words("a sculptor's block of stone")
    assert "sculptor" in words
    assert "block" in words
    assert "stone" in words
    assert "a" not in words and "of" not in words and "the" not in words


def test_describe_examples_reports_the_score_and_mode(rag_db, no_embeddings):
    from app.rag.helpers import describe_examples

    _add(topic="space exploration", prompt_text="Space text " + "x" * 200)
    results = retrieval.retrieve_examples(paper="use_of_english", part=2,
                                          topic="space exploration", k=1)
    line = describe_examples(results)[0]
    assert "keyword_overlap=" in line
    assert "id=" in line


# ── query embedding cache ────────────────────────────────────────────────────

def _add_with_vector(part, topic, vector):
    example_id = _add(part=part, topic=topic)
    import sqlite3
    from app.rag.db import rag_db_path
    from app.rag.embeddings import embedding_to_bytes
    conn = sqlite3.connect(rag_db_path())
    conn.execute(
        "UPDATE rag_examples SET embedding = ?, embedding_model = ? WHERE id = ?",
        (embedding_to_bytes(vector), "test-model", example_id),
    )
    conn.commit()
    conn.close()


def test_query_embedding_is_cached_across_retrievals(rag_db, monkeypatch):
    """Repeated generations reuse one query vector instead of re-calling the provider."""
    _add_with_vector(2, "travel", np.ones(4, dtype=np.float32))
    monkeypatch.setattr(retrieval, "active_model_name", lambda: "test-model")

    calls = {"n": 0}

    def counting_embed(text):
        calls["n"] += 1
        return np.ones(4, dtype=np.float32)

    monkeypatch.setattr(retrieval, "get_embedding", counting_embed)

    for _ in range(4):
        results = retrieval.retrieve_examples(paper="use_of_english", part=2,
                                              topic="travel", task_type="open_cloze", k=1)
        assert results

    assert calls["n"] == 1, "query embedding should only be computed once"


def test_query_cache_is_keyed_by_model(rag_db, monkeypatch):
    """Switching embedding backends must not reuse the previous model's vectors."""
    _add_with_vector(2, "travel", np.ones(4, dtype=np.float32))

    calls = {"n": 0}

    def counting_embed(text):
        calls["n"] += 1
        return np.ones(4, dtype=np.float32)

    monkeypatch.setattr(retrieval, "get_embedding", counting_embed)

    monkeypatch.setattr(retrieval, "active_model_name", lambda: "model-a")
    retrieval.retrieve_examples(paper="use_of_english", part=2, topic="travel", k=1)
    monkeypatch.setattr(retrieval, "active_model_name", lambda: "model-b")
    retrieval.retrieve_examples(paper="use_of_english", part=2, topic="travel", k=1)

    assert calls["n"] == 2, "a different model must not hit the other model's cache"


def test_query_cache_failure_does_not_break_retrieval(rag_db, monkeypatch):
    """Caching is an optimisation; a broken cache must not fail generation."""
    import sqlite3

    from app.rag.db import rag_db_path

    _add_with_vector(2, "travel", np.ones(4, dtype=np.float32))
    monkeypatch.setattr(retrieval, "active_model_name", lambda: "test-model")
    monkeypatch.setattr(retrieval, "get_embedding", lambda text: np.ones(4, dtype=np.float32))

    # Simulate the cache table being absent (e.g. an un-migrated database).
    conn = sqlite3.connect(rag_db_path())
    conn.execute("DROP TABLE rag_query_cache")
    conn.commit()
    conn.close()

    results = retrieval.retrieve_examples(paper="use_of_english", part=2, topic="travel", k=1)
    assert len(results) == 1


# ── HTML export (browsing the corpus) ────────────────────────────────────────

def _export_args(out, **overrides):
    import argparse
    defaults = {"out": str(out), "paper": None, "part": None, "type": None,
                "min_chars": 0, "no_js": False}
    defaults.update(overrides)
    return argparse.Namespace(**defaults)


def test_export_writes_a_valid_html_document(rag_db, tmp_path):
    from scripts.rag_manager import cmd_export

    _add(topic="travel", prompt_text="A passage about travel. " + "x" * 200)
    _add(part=5, paper="reading", task_type="multiple_choice",
         topic="history", prompt_text="A reading text. " + "y" * 200)

    out = tmp_path / "corpus.html"
    cmd_export(_export_args(out))

    html = out.read_text(encoding="utf-8")
    assert html.startswith("<!doctype html>")
    assert html.rstrip().endswith("</html>")
    assert html.count("class='card'") == 2
    # _add defaults to part 2; the second example is part 5.
    assert "Part 2" in html and "Part 5" in html


def test_export_escapes_task_text(rag_db, tmp_path):
    """Task text may contain < and & from HTML-ish source material."""
    from scripts.rag_manager import cmd_export

    _add(prompt_text="Passage with <p>tags</p> & an ampersand. " + "z" * 200)
    out = tmp_path / "corpus.html"
    cmd_export(_export_args(out))

    html = out.read_text(encoding="utf-8")
    # Rendered content must not contain a live <p> tag from the example body.
    body = html.split("<pre>", 1)[1].split("</pre>", 1)[0]
    assert "<p>" not in body
    assert "&lt;p&gt;" in body
    assert "&amp;" in body


def test_export_can_filter_to_one_part(rag_db, tmp_path):
    from scripts.rag_manager import cmd_export

    _add(part=2, topic="travel", prompt_text="t " * 100)
    _add(part=3, task_type="word_formation", topic="sport", prompt_text="s " * 100)

    out = tmp_path / "part2.html"
    cmd_export(_export_args(out, part=2))

    html = out.read_text(encoding="utf-8")
    assert html.count("class='card'") == 1
    assert "Part 2" in html and "Part 3" not in html


def test_export_can_omit_the_filter_script(rag_db, tmp_path):
    from scripts.rag_manager import cmd_export

    _add(prompt_text="text " * 100)
    out = tmp_path / "static.html"
    cmd_export(_export_args(out, no_js=True))

    assert "<script>" not in out.read_text(encoding="utf-8")


def test_export_reports_when_nothing_matches(rag_db, tmp_path, capsys):
    from scripts.rag_manager import cmd_export

    out = tmp_path / "empty.html"
    cmd_export(_export_args(out, part=7))

    assert not out.exists()
    assert "Nothing exported" in capsys.readouterr().out


# ── embedding backends ───────────────────────────────────────────────────────

def test_cosine_similarity_of_identical_vectors_is_one():
    vec = np.array([1.0, 2.0, 3.0], dtype=np.float32)
    assert cosine_similarity(vec, vec) == pytest.approx(1.0)


def test_cosine_similarity_returns_zero_for_mismatched_widths():
    """Vectors from different models must never be compared."""
    a = np.ones(384, dtype=np.float32)
    b = np.ones(1536, dtype=np.float32)
    assert cosine_similarity(a, b) == 0.0


def test_cosine_similarity_handles_zero_vector():
    zero = np.zeros(4, dtype=np.float32)
    assert cosine_similarity(zero, np.ones(4, dtype=np.float32)) == 0.0


def test_embedding_bytes_round_trip_preserves_values():
    vec = np.array([0.5, -1.25, 3.0], dtype=np.float32)
    assert np.allclose(bytes_to_embedding(embedding_to_bytes(vec)), vec)


def test_active_backend_honours_explicit_local_choice(monkeypatch):
    monkeypatch.setenv("RAG_EMBEDDING_BACKEND", "local")
    backend = active_backend()
    # Either fastembed is installed (local) or it is not (None) — never OpenAI.
    assert backend in ("local", None)


def test_active_backend_honours_explicit_openai_choice(monkeypatch):
    monkeypatch.setenv("RAG_EMBEDDING_BACKEND", "openai")
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    assert active_backend() is None
    assert active_model_name() == ""


def test_active_backend_honours_explicit_google_choice(monkeypatch):
    monkeypatch.setenv("RAG_EMBEDDING_BACKEND", "google")
    monkeypatch.setenv("GOOGLE_AI_API_KEY", "test-key")
    assert active_backend() == "google"


def test_active_backend_google_requires_a_key(monkeypatch):
    monkeypatch.setenv("RAG_EMBEDDING_BACKEND", "google")
    monkeypatch.delenv("GOOGLE_AI_API_KEY", raising=False)
    assert active_backend() is None


def test_google_accepts_gemini_alias(monkeypatch):
    monkeypatch.setenv("RAG_EMBEDDING_BACKEND", "gemini")
    monkeypatch.setenv("GOOGLE_AI_API_KEY", "test-key")
    assert active_backend() == "google"


def test_google_model_name_includes_dimension(monkeypatch):
    """Truncation means the same model can emit different widths."""
    monkeypatch.setenv("RAG_EMBEDDING_BACKEND", "google")
    monkeypatch.setenv("GOOGLE_AI_API_KEY", "test-key")
    monkeypatch.setenv("RAG_GOOGLE_EMBEDDING_DIM", "512")
    assert active_model_name() == "gemini-embedding-001@512"


def test_google_dim_falls_back_on_bad_value(monkeypatch):
    from app.rag.embeddings import DEFAULT_GOOGLE_DIM, google_dim
    monkeypatch.setenv("RAG_GOOGLE_EMBEDDING_DIM", "not-a-number")
    assert google_dim() == DEFAULT_GOOGLE_DIM
    monkeypatch.setenv("RAG_GOOGLE_EMBEDDING_DIM", "-5")
    assert google_dim() == DEFAULT_GOOGLE_DIM


def test_auto_prefers_local_then_openai_then_google(monkeypatch):
    """Order matters: a working local model must not be pre-empted."""
    monkeypatch.setenv("RAG_EMBEDDING_BACKEND", "auto")
    monkeypatch.setenv("GOOGLE_AI_API_KEY", "g")
    monkeypatch.setenv("OPENAI_API_KEY", "o")
    monkeypatch.setattr("app.rag.embeddings._local_available", lambda: False)
    assert active_backend() == "openai"
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    assert active_backend() == "google"


def test_rebuild_embeddings_is_a_noop_without_a_backend(rag_db, monkeypatch):
    _add()
    monkeypatch.setattr("app.rag.embeddings.active_model_name", lambda: "")
    assert rebuild_embeddings() == 0


def test_rebuild_embeddings_stores_model_name(rag_db, monkeypatch):
    """Each vector records its model so mixed-width vectors are never compared."""
    _add()
    monkeypatch.setattr("app.rag.embeddings.active_model_name", lambda: "test-model")
    monkeypatch.setattr(
        "app.rag.embeddings.get_embeddings_batch",
        lambda texts, for_query=False: [np.ones(8, dtype=np.float32) for _ in texts],
    )

    assert rebuild_embeddings(force=True) == 1

    import sqlite3
    conn = sqlite3.connect(rag_db)
    try:
        model = conn.execute("SELECT embedding_model FROM rag_examples").fetchone()[0]
    finally:
        conn.close()
    assert model == "test-model"


def test_retrieval_skips_embeddings_from_a_different_model(rag_db, monkeypatch):
    """A stale OpenAI-width vector must not be compared to a local-width query."""
    from app.rag.embeddings import embedding_to_bytes as to_bytes

    _add(topic="travel")
    import sqlite3
    conn = sqlite3.connect(rag_db)
    conn.execute(
        "UPDATE rag_examples SET embedding = ?, embedding_model = ?",
        (to_bytes(np.ones(1536, dtype=np.float32)), "text-embedding-3-small"),
    )
    conn.commit()
    conn.close()

    monkeypatch.setattr("app.rag.embeddings.active_model_name", lambda: "BAAI/bge-small-en-v1.5")
    monkeypatch.setattr(retrieval, "get_embedding", lambda text: np.ones(384, dtype=np.float32))
    monkeypatch.setattr(retrieval, "active_model_name", lambda: "BAAI/bge-small-en-v1.5")

    # No comparable vectors -> embedding pass yields nothing -> keyword fallback.
    results = retrieve_examples(paper="use_of_english", part=2, topic="travel", k=1)
    assert len(results) == 1
    assert results[0]["topic"] == "travel"
