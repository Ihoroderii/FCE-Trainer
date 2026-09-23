"""Tests for AI provider selection and the DeepSeek integration.

These exercise the pure selection helper and client construction rather than
reloading the module, so no network calls are made and global state is untouched.
"""
from __future__ import annotations

import pytest

from app.ai import (
    GOOGLE_AI_MODEL_FALLBACKS,
    PROVIDER_LABELS,
    PROVIDER_PRIORITY,
    _make_openai_compatible_client,
    _messages_to_prompt,
    _select_provider,
    provider_label,
)


# ── provider labels (log/status messages) ────────────────────────────────────

def test_every_selectable_provider_has_a_label():
    for name in PROVIDER_PRIORITY:
        assert name in PROVIDER_LABELS, f"{name} has no human-readable label"


def test_provider_label_matches_the_active_provider():
    """Logs must name the provider actually in use, not always 'OpenAI'."""
    import app.ai as ai

    if ai._provider is None:
        assert provider_label() == "AI"
    else:
        assert provider_label() == PROVIDER_LABELS[ai._provider]


def test_deepseek_label_is_deepseek():
    assert PROVIDER_LABELS["deepseek"] == "DeepSeek"


# ── prompt flattening (providers without a chat API) ─────────────────────────

def test_messages_to_prompt_keeps_the_system_instruction():
    """Dropping the system message silently removes the requested output schema."""
    prompt = _messages_to_prompt([
        {"role": "system", "content": "RETURN JSON ONLY"},
        {"role": "user", "content": "here is the text"},
    ])
    assert "RETURN JSON ONLY" in prompt
    assert "here is the text" in prompt
    assert prompt.index("RETURN JSON ONLY") < prompt.index("here is the text")


def test_messages_to_prompt_handles_user_only():
    assert _messages_to_prompt([{"role": "user", "content": "solo"}]) == "solo"


def test_messages_to_prompt_joins_multiple_system_messages():
    prompt = _messages_to_prompt([
        {"role": "system", "content": "rule one"},
        {"role": "system", "content": "rule two"},
        {"role": "user", "content": "data"},
    ])
    assert "rule one" in prompt and "rule two" in prompt


def test_messages_to_prompt_skips_empty_and_malformed_entries():
    prompt = _messages_to_prompt([
        "not a dict",
        {"role": "user", "content": ""},
        {"role": "system", "content": "kept"},
        {"role": "user"},
    ])
    assert prompt == "kept"


def test_messages_to_prompt_on_empty_list():
    assert _messages_to_prompt([]) == ""


def test_no_configured_provider_returns_none():
    assert _select_provider("", {}) is None


def test_auto_selection_follows_documented_priority():
    available = {"openai": True, "deepseek": True, "groq": True, "google": True, "huggingface": True}
    assert _select_provider("", available) == "deepseek"


@pytest.mark.parametrize("only,expected", [
    ("deepseek", "deepseek"),
    ("openai", "openai"),
    ("groq", "groq"),
    ("google", "google"),
    ("huggingface", "huggingface"),
])
def test_auto_selection_picks_the_only_configured_provider(only, expected):
    assert _select_provider("", {only: True}) == expected


def test_deepseek_is_first_in_priority():
    """DeepSeek is the primary provider for this deployment."""
    assert PROVIDER_PRIORITY[0] == "deepseek"


def test_forced_provider_wins_when_configured():
    assert _select_provider("deepseek", {"deepseek": True, "openai": True}) == "deepseek"


def test_forced_provider_falls_back_when_not_configured():
    """Asking for a provider with no key must not leave the app with no AI."""
    assert _select_provider("deepseek", {"openai": True}) == "openai"


def test_forced_provider_with_nothing_configured_returns_none():
    assert _select_provider("deepseek", {}) is None


def test_forced_provider_is_case_insensitive():
    assert _select_provider("DeepSeek", {"deepseek": True}) == "deepseek"


def test_unknown_forced_provider_falls_back_to_priority():
    assert _select_provider("nonsense", {"groq": True}) == "groq"


def test_deepseek_client_targets_deepseek_endpoint():
    client = _make_openai_compatible_client("sk-test-key", "https://api.deepseek.com/v1")
    assert str(client.base_url).rstrip("/") == "https://api.deepseek.com/v1"


def test_deepseek_client_ignores_openai_base_url_proxy(monkeypatch):
    """A proxy set for OpenAI must not hijack the DeepSeek client."""
    monkeypatch.setenv("OPENAI_BASE_URL", "http://localhost:9999/v1")
    client = _make_openai_compatible_client("sk-test-key", "https://api.deepseek.com/v1")
    assert "9999" not in str(client.base_url)
    # The proxy setting is restored for the OpenAI client.
    import os
    assert os.environ.get("OPENAI_BASE_URL") == "http://localhost:9999/v1"


def test_gemini_fallbacks_do_not_start_with_retired_models():
    """gemini-2.0-flash and 1.5-* are retired for new accounts."""
    assert GOOGLE_AI_MODEL_FALLBACKS[0].startswith("gemini-3")
    assert "gemini-2.0-flash" not in GOOGLE_AI_MODEL_FALLBACKS


def test_gemini_fallbacks_are_unique():
    assert len(GOOGLE_AI_MODEL_FALLBACKS) == len(set(GOOGLE_AI_MODEL_FALLBACKS))
