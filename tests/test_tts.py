"""Tests for the text-to-speech service helpers.

Focus on the outbound-proxy handling, which is what lets edge-tts work on
hosts that route traffic through a proxy (PythonAnywhere, corporate networks).
Without it edge-tts attempts a direct websocket and fails with
"Network is unreachable".
"""
from __future__ import annotations

import pytest

from app.services.tts import _edge_failure_reason, edge_proxy

_PROXY_VARS = ("https_proxy", "HTTPS_PROXY", "http_proxy", "HTTP_PROXY",
               "all_proxy", "ALL_PROXY")


@pytest.fixture()
def clean_proxy_env(monkeypatch):
    for name in _PROXY_VARS:
        monkeypatch.delenv(name, raising=False)
    return monkeypatch


def test_no_proxy_configured_returns_none(clean_proxy_env):
    assert edge_proxy() is None


def test_https_proxy_is_used(clean_proxy_env):
    clean_proxy_env.setenv("https_proxy", "http://proxy.server:3128")
    assert edge_proxy() == "http://proxy.server:3128"


def test_uppercase_variant_is_used(clean_proxy_env):
    clean_proxy_env.setenv("HTTPS_PROXY", "http://proxy.example:8080")
    assert edge_proxy() == "http://proxy.example:8080"


def test_https_proxy_wins_over_http_proxy(clean_proxy_env):
    clean_proxy_env.setenv("https_proxy", "http://secure:3128")
    clean_proxy_env.setenv("http_proxy", "http://plain:3128")
    assert edge_proxy() == "http://secure:3128"


def test_blank_proxy_values_are_ignored(clean_proxy_env):
    clean_proxy_env.setenv("https_proxy", "   ")
    clean_proxy_env.setenv("http_proxy", "http://fallback:3128")
    assert edge_proxy() == "http://fallback:3128"


# ── failure messages ─────────────────────────────────────────────────────────

def test_unreachable_network_message_mentions_the_proxy():
    """The raw aiohttp error is 70 lines; the summary must be actionable."""
    exc = OSError("Multiple exceptions: [Errno 111] Connect call failed "
                  "('150.171.27.10', 443), [Errno 101] Network is unreachable")
    reason = _edge_failure_reason(exc)
    assert "proxy" in reason.lower()
    assert len(reason) < 200


def test_cannot_connect_message_names_the_host():
    exc = Exception("Cannot connect to host speech.platform.bing.com:443 ssl:...")
    reason = _edge_failure_reason(exc)
    assert "speech.platform.bing.com" in reason


def test_unknown_failure_keeps_exception_type():
    reason = _edge_failure_reason(ValueError("something odd"))
    assert "ValueError" in reason
