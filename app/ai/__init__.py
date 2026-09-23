"""Unified AI client. Supports OpenAI, DeepSeek, Groq (free), Google AI Studio (Gemini), and Hugging Face.

Priority (first configured key wins, or set AI_PROVIDER to force one):
  1. OPENAI_API_KEY      → OpenAI   (gpt-4o-mini default)
  2. DEEPSEEK_API_KEY    → DeepSeek (deepseek-chat default) — OpenAI-compatible
  3. GROQ_API_KEY        → Groq     (llama-3.3-70b-versatile default) — free tier
  4. GOOGLE_AI_API_KEY   → Gemini   (gemini-3.6-flash default) — free tier
  5. HUGGINGFACE_API_KEY → Hugging Face Inference API — free tier
"""
from __future__ import annotations

import json
import logging
import os
from typing import Any

import requests
from tenacity import retry, stop_after_attempt, wait_exponential

logger = logging.getLogger("fce_trainer")


def _make_openai_compatible_client(api_key: str, base_url: str):
    """Build an OpenAI SDK client pointed at an OpenAI-compatible endpoint.

    OPENAI_BASE_URL is temporarily removed so a local proxy configured for the
    OpenAI provider cannot hijack a different vendor's client.
    """
    from openai import OpenAI
    saved_base = os.environ.pop("OPENAI_BASE_URL", None)
    try:
        return OpenAI(api_key=api_key, base_url=base_url)
    finally:
        if saved_base is not None:
            os.environ["OPENAI_BASE_URL"] = saved_base


# ----- OpenAI -----
openai_api_key = (os.environ.get("OPENAI_API_KEY") or "").strip()
openai_client = None
openai_model = (os.environ.get("OPENAI_MODEL") or "gpt-4o-mini").strip()
if openai_api_key:
    from openai import OpenAI
    openai_client = OpenAI(api_key=openai_api_key)

# ----- DeepSeek (OpenAI-compatible) -----
deepseek_api_key = (os.environ.get("DEEPSEEK_API_KEY") or "").strip()
deepseek_model = (os.environ.get("DEEPSEEK_MODEL") or "deepseek-chat").strip()
deepseek_base_url = (os.environ.get("DEEPSEEK_BASE_URL") or "https://api.deepseek.com/v1").strip()
deepseek_client = None
if deepseek_api_key:
    deepseek_client = _make_openai_compatible_client(deepseek_api_key, deepseek_base_url)

# ----- Groq (OpenAI-compatible, free tier) -----
groq_api_key = (os.environ.get("GROQ_API_KEY") or "").strip()
groq_model = (os.environ.get("GROQ_MODEL") or "llama-3.3-70b-versatile").strip()
groq_client = None
if groq_api_key:
    # Force Groq URL: ignore OPENAI_BASE_URL (e.g. local proxy) so we hit api.groq.com
    groq_client = _make_openai_compatible_client(groq_api_key, "https://api.groq.com/openai/v1")

# ----- Google AI Studio (Gemini) — REST API -----
google_ai_api_key = (os.environ.get("GOOGLE_AI_API_KEY") or "").strip()
google_ai_model = (os.environ.get("GOOGLE_AI_MODEL") or "gemini-3.5-flash").strip()
google_ai_configured = bool(google_ai_api_key)
# Gemini retires models for new accounts and returns 503 when a model is
# overloaded, so these are tried in order until one answers. Only models that
# are currently served belong here — a retired one just wastes a failover slot.
GOOGLE_AI_MODEL_FALLBACKS = [
    "gemini-3.5-flash",
    "gemini-flash-latest",
    "gemini-3.1-flash-lite",
    "gemini-3.6-flash",
    "gemini-3-flash-preview",
]

# ----- Hugging Face Inference API -----
hf_api_key = (os.environ.get("HUGGINGFACE_API_KEY") or os.environ.get("HF_TOKEN") or "").strip()
hf_model = (os.environ.get("HUGGINGFACE_MODEL") or os.environ.get("HF_MODEL") or "HuggingFaceH4/zephyr-7b-beta").strip()
hf_configured = bool(hf_api_key)
HF_INFERENCE_URL = "https://api-inference.huggingface.co/models"

# ----- Provider selection -----
# Set AI_PROVIDER=deepseek|openai|groq|google|huggingface to force one.
# Otherwise the first configured key in the priority order above is used.
PROVIDER_PRIORITY = ["deepseek", "openai", "groq", "google", "huggingface"]


def _select_provider(forced: str, available: dict[str, bool]) -> str | None:
    """Pick the active provider.

    An explicit ``forced`` choice wins only if that provider is actually
    configured; otherwise fall back to the documented priority order.
    """
    forced = (forced or "").strip().lower()
    if forced in available and available[forced]:
        return forced
    for name in PROVIDER_PRIORITY:
        if available.get(name):
            return name
    return None


_ai_provider = os.environ.get("AI_PROVIDER", "")
_provider = _select_provider(_ai_provider, {
    "openai": bool(openai_client),
    "deepseek": bool(deepseek_client),
    "groq": bool(groq_client),
    "google": google_ai_configured,
    "huggingface": hf_configured,
})

# Human-readable names, so logs and user-facing messages do not claim "OpenAI"
# when a different provider is doing the work.
PROVIDER_LABELS = {
    "openai": "OpenAI",
    "deepseek": "DeepSeek",
    "groq": "Groq",
    "google": "Gemini",
    "huggingface": "Hugging Face",
}


def provider_label() -> str:
    """Name of the active provider for log/status messages."""
    return PROVIDER_LABELS.get(_provider or "", "AI")


def prompts_logging_enabled() -> bool:
    """True when LOG_AI_PROMPTS is set — logs the exact text sent to the model.

    Off by default because prompts are long, but invaluable when you need to see
    what the model was actually asked.
    """
    return (os.environ.get("LOG_AI_PROMPTS") or "").strip().lower() in ("1", "true", "yes", "on")


def _log_ai_request(messages, model: str | None) -> None:
    """Dump the outgoing request so it can be inspected after the fact."""
    resolved = model or {
        "openai": openai_model,
        "deepseek": deepseek_model,
        "groq": groq_model,
        "google": google_ai_model,
        "huggingface": hf_model,
    }.get(_provider or "", "?")
    parts = [
        f"========== AI REQUEST -> {provider_label()} (model={resolved}, "
        f"messages={len(messages)}, chars={sum(len(m.get('content') or '') for m in messages if isinstance(m, dict))}) =========="
    ]
    for index, message in enumerate(messages, 1):
        if not isinstance(message, dict):
            continue
        role = (message.get("role") or "?").upper()
        content = message.get("content") or ""
        parts.append(f"---------- [{index}] {role} ----------")
        parts.append(content)
    parts.append("========== END AI REQUEST ==========")
    logger.info("\n".join(parts))

ai_available = _provider is not None

logger.debug(
    "AI provider: %s | OpenAI: %s | DeepSeek: %s | Groq: %s | Google: %s | HF: %s",
    _provider or "none",
    "yes" if openai_client else "no",
    "yes" if deepseek_client else "no",
    "yes" if groq_client else "no",
    "yes" if google_ai_configured else "no",
    "yes" if hf_configured else "no",
)


# Default request timeout in seconds for AI API calls
AI_REQUEST_TIMEOUT = int(os.environ.get("AI_REQUEST_TIMEOUT", "60"))


class _ChatResponse:
    """Thin wrapper so all providers return .choices[0].message.content (same as OpenAI shape)."""

    def __init__(self, content: str):
        content = content or ""
        message = type("_Msg", (), {"content": content})()
        choice = type("_Ch", (), {"message": message})()
        self.choices = [choice]


@retry(stop=stop_after_attempt(4), wait=wait_exponential(multiplier=2, min=3, max=45), reraise=True)
def chat_create(messages: list[dict[str, str]], temperature: float = 0.7, model: str | None = None) -> Any:
    """Call the configured AI provider. Returns object with .choices[0].message.content."""
    if _provider is None:
        raise ValueError(
            "No AI provider configured. Set OPENAI_API_KEY, DEEPSEEK_API_KEY, "
            "GROQ_API_KEY, GOOGLE_AI_API_KEY, or HUGGINGFACE_API_KEY in your .env file."
        )
    if prompts_logging_enabled():
        _log_ai_request(messages, model)
    if _provider == "openai":
        return _openai_create(messages, temperature, model)
    if _provider == "deepseek":
        return _deepseek_create(messages, temperature, model)
    if _provider == "groq":
        return _groq_create(messages, temperature, model)
    if _provider == "google":
        return _google_create(messages, temperature, model)
    return _hf_create(messages, temperature, model)


def _openai_create(messages, temperature, model):
    return openai_client.chat.completions.create(
        model=model or openai_model,
        messages=messages,
        temperature=temperature,
        timeout=AI_REQUEST_TIMEOUT,
    )


def _deepseek_create(messages, temperature, model):
    return deepseek_client.chat.completions.create(
        model=model or deepseek_model,
        messages=messages,
        temperature=temperature,
        timeout=AI_REQUEST_TIMEOUT,
    )


def _groq_create(messages, temperature, model):
    return groq_client.chat.completions.create(
        model=model or groq_model,
        messages=messages,
        temperature=temperature,
        timeout=AI_REQUEST_TIMEOUT,
    )


def _hf_create(messages, temperature, model):
    """Hugging Face Inference API (text-generation). Builds prompt from messages."""
    prompt = ""
    for m in messages:
        if not isinstance(m, dict):
            continue
        role = (m.get("role") or "").strip().lower()
        content = (m.get("content") or "").strip()
        if not content:
            continue
        if role == "user":
            prompt = content if not prompt else f"{prompt}\n\nUser: {content}\n\nAssistant:"
        elif role == "assistant":
            prompt = f"{prompt}\n\nAssistant: {content}\n\nUser:" if prompt else content
        elif role == "system":
            prompt = f"System: {content}\n\n{prompt}" if prompt else f"System: {content}\n\n"
    if not prompt.strip():
        # Fallback: use last message content
        for m in reversed(messages):
            if isinstance(m, dict) and m.get("content"):
                prompt = m["content"].strip()
                break
    model_id = (model or hf_model).strip()
    url = f"{HF_INFERENCE_URL}/{model_id}"
    payload = {
        "inputs": prompt,
        "parameters": {
            "max_new_tokens": 2048,
            "temperature": max(0.01, min(1.0, float(temperature))) if temperature is not None else 0.7,
            "return_full_text": False,
        },
    }
    resp = requests.post(
        url,
        headers={"Authorization": f"Bearer {hf_api_key}", "Content-Type": "application/json"},
        json=payload,
        timeout=AI_REQUEST_TIMEOUT,
    )
    try:
        data = resp.json()
    except json.JSONDecodeError:
        data = {}
    if resp.status_code == 503 and isinstance(data, dict) and "error" in data:
        raise RuntimeError(f"Hugging Face model loading: {data.get('error', 'try again in a minute')}")
    if resp.status_code != 200:
        err_msg = data.get("error", resp.text) if isinstance(data, dict) else resp.text
        raise RuntimeError(f"Hugging Face {resp.status_code}: {str(err_msg)[:500]}")
    text = ""
    if isinstance(data, list) and len(data) > 0 and isinstance(data[0], dict):
        text = (data[0].get("generated_text") or "").strip()
    elif isinstance(data, dict) and data.get("generated_text"):
        text = (data["generated_text"] or "").strip()
    return _ChatResponse(text)


def _messages_to_prompt(messages) -> str:
    """Flatten chat messages into one prompt for providers without a chat API.

    System/instruction messages must be preserved — dropping them silently
    removes the output schema, which is how Gemini previously ended up ignoring
    the requested JSON shape.
    """
    system_parts: list[str] = []
    other_parts: list[str] = []
    for message in messages:
        if not isinstance(message, dict):
            continue
        content = (message.get("content") or "").strip()
        if not content:
            continue
        role = (message.get("role") or "").strip().lower()
        if role == "system":
            system_parts.append(content)
        else:
            other_parts.append(content)

    sections = []
    if system_parts:
        sections.append("\n\n".join(system_parts))
    if other_parts:
        sections.append("\n\n".join(other_parts))
    return "\n\n".join(sections)


def _google_create(messages, temperature, model):
    prompt = _messages_to_prompt(messages)
    model_name = (model or google_ai_model).strip()
    to_try = [model_name] + [m for m in GOOGLE_AI_MODEL_FALLBACKS if m != model_name]
    last_err = None
    for index, try_model in enumerate(to_try):
        try:
            return _gemini_rest(try_model, prompt, temperature)
        except Exception as e:
            last_err = e
            s = str(e).lower()
            # A model can be retired (404) or temporarily overloaded (503/429).
            # Either way another model may still serve the request.
            retryable = any(k in s for k in (
                "404", "not found", "503", "unavailable", "429", "overloaded", "high demand",
            ))
            if retryable and index < len(to_try) - 1:
                logger.info("Gemini model %s unavailable, trying next", try_model)
                continue
            raise
    raise last_err  # type: ignore[misc]


def _gemini_rest(model_id: str, prompt: str, temperature: float) -> _ChatResponse:
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{model_id}:generateContent"
    resp = requests.post(
        url,
        params={"key": google_ai_api_key},
        json={"contents": [{"parts": [{"text": prompt}]}], "generationConfig": {"temperature": temperature}},
        timeout=AI_REQUEST_TIMEOUT,
    )
    try:
        data = resp.json()
    except json.JSONDecodeError:
        data = {}
    if resp.status_code != 200:
        raise RuntimeError(f"Gemini {resp.status_code}: {data.get('error', {}).get('message', resp.text)[:500]}")
    text = ""
    try:
        text = data["candidates"][0]["content"]["parts"][0]["text"].strip()
    except (KeyError, IndexError, TypeError):
        pass
    return _ChatResponse(text)


def openai_chat_create(messages, temperature=0.7, model=None):
    """Legacy alias for chat_create."""
    return chat_create(messages, temperature=temperature, model=model)
