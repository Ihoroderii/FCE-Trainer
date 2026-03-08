"""Unified AI client. Supports OpenAI, Groq (free), Google AI Studio (Gemini), and Hugging Face.

Priority (first configured key wins, or set AI_PROVIDER to force one):
  1. OPENAI_API_KEY     → OpenAI (gpt-4o-mini default)
  2. GROQ_API_KEY       → Groq   (llama-3.3-70b-versatile default) — free tier
  3. GOOGLE_AI_API_KEY  → Gemini (gemini-2.0-flash default) — free tier
  4. HUGGINGFACE_API_KEY → Hugging Face Inference API — free tier
"""
import json
import logging
import os

import requests
from tenacity import retry, stop_after_attempt, wait_exponential

logger = logging.getLogger("fce_trainer")

# ----- OpenAI -----
openai_api_key = (os.environ.get("OPENAI_API_KEY") or "").strip()
openai_client = None
openai_model = (os.environ.get("OPENAI_MODEL") or "gpt-4o-mini").strip()
if openai_api_key:
    from openai import OpenAI
    openai_client = OpenAI(api_key=openai_api_key)

# ----- Groq (OpenAI-compatible, free tier) -----
groq_api_key = (os.environ.get("GROQ_API_KEY") or "").strip()
groq_model = (os.environ.get("GROQ_MODEL") or "llama-3.3-70b-versatile").strip()
groq_client = None
if groq_api_key:
    from openai import OpenAI as _OAI
    # Force Groq URL: ignore OPENAI_BASE_URL (e.g. local proxy) so we hit api.groq.com
    _saved_base = os.environ.pop("OPENAI_BASE_URL", None)
    try:
        groq_client = _OAI(api_key=groq_api_key, base_url="https://api.groq.com/openai/v1")
    finally:
        if _saved_base is not None:
            os.environ["OPENAI_BASE_URL"] = _saved_base

# ----- Google AI Studio (Gemini) — REST API -----
google_ai_api_key = (os.environ.get("GOOGLE_AI_API_KEY") or "").strip()
google_ai_model = (os.environ.get("GOOGLE_AI_MODEL") or "gemini-2.0-flash").strip()
google_ai_configured = bool(google_ai_api_key)
GOOGLE_AI_MODEL_FALLBACKS = ["gemini-2.0-flash", "gemini-1.5-flash", "gemini-1.5-pro"]

# ----- Hugging Face Inference API -----
hf_api_key = (os.environ.get("HUGGINGFACE_API_KEY") or os.environ.get("HF_TOKEN") or "").strip()
hf_model = (os.environ.get("HUGGINGFACE_MODEL") or os.environ.get("HF_MODEL") or "HuggingFaceH4/zephyr-7b-beta").strip()
hf_configured = bool(hf_api_key)
HF_INFERENCE_URL = "https://api-inference.huggingface.co/models"

# ----- Provider selection -----
# Set AI_PROVIDER=openai|groq|google|huggingface to force one. Otherwise first configured key is used.
_ai_provider = os.environ.get("AI_PROVIDER", "").strip().lower()
if _ai_provider == "openai" and openai_client:
    _provider = "openai"
elif _ai_provider == "groq" and groq_client:
    _provider = "groq"
elif _ai_provider == "google" and google_ai_configured:
    _provider = "google"
elif _ai_provider == "huggingface" and hf_configured:
    _provider = "huggingface"
elif openai_client:
    _provider = "openai"
elif groq_client:
    _provider = "groq"
elif google_ai_configured:
    _provider = "google"
elif hf_configured:
    _provider = "huggingface"
else:
    _provider = None

ai_available = _provider is not None

logger.debug(
    "AI provider: %s | OpenAI: %s | Groq: %s | Google: %s | HF: %s",
    _provider or "none",
    "yes" if openai_client else "no",
    "yes" if groq_client else "no",
    "yes" if google_ai_configured else "no",
    "yes" if hf_configured else "no",
)


class _ChatResponse:
    """Thin wrapper so all providers return .choices[0].message.content (same as OpenAI shape)."""

    def __init__(self, content: str):
        content = content or ""
        message = type("_Msg", (), {"content": content})()
        choice = type("_Ch", (), {"message": message})()
        self.choices = [choice]


@retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=2, max=10))
def chat_create(messages, temperature=0.7, model=None):
    """Call the configured AI provider. Returns object with .choices[0].message.content."""
    if _provider is None:
        raise ValueError(
            "No AI provider configured. "
            "Set OPENAI_API_KEY, GROQ_API_KEY, GOOGLE_AI_API_KEY, or HUGGINGFACE_API_KEY in your .env file."
        )
    if _provider == "openai":
        return _openai_create(messages, temperature, model)
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
    )


def _groq_create(messages, temperature, model):
    return groq_client.chat.completions.create(
        model=model or groq_model,
        messages=messages,
        temperature=temperature,
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
        timeout=120,
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


def _google_create(messages, temperature, model):
    prompt = ""
    for m in messages:
        if isinstance(m, dict) and m.get("role") == "user":
            prompt = m.get("content") or ""
        elif isinstance(m, dict) and m.get("content"):
            prompt = m["content"]
    model_name = (model or google_ai_model).strip()
    to_try = [model_name] + [m for m in GOOGLE_AI_MODEL_FALLBACKS if m != model_name]
    last_err = None
    for try_model in to_try:
        try:
            return _gemini_rest(try_model, prompt, temperature)
        except Exception as e:
            last_err = e
            s = str(e).lower()
            if ("404" in s or "not found" in s) and try_model != to_try[-1]:
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
        timeout=60,
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
