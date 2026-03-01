"""OpenAI client and chat completion helper."""
import os

from openai import OpenAI
from tenacity import retry, stop_after_attempt, wait_exponential

openai_api_key = os.environ.get("OPENAI_API_KEY")
openai_client = OpenAI(api_key=openai_api_key) if openai_api_key else None
openai_model = os.environ.get("OPENAI_MODEL", "gpt-5.2")


@retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=2, max=10))
def openai_chat_create(messages, temperature=0.7, model=None):
    """Call OpenAI chat completions with retries. Raises if client not configured."""
    if not openai_client:
        raise ValueError("OpenAI client not configured")
    return openai_client.chat.completions.create(
        model=model or openai_model,
        messages=messages,
        temperature=temperature,
    )
