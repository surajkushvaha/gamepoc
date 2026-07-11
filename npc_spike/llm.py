"""Thin wrapper around the Cerebras chat-completions endpoint.

Cerebras exposes an OpenAI-compatible API, so we just point the official
`openai` client at Cerebras' base URL. Everything else in the spike talks to
the model through the single `chat()` helper here so the retry/backoff and
model-selection logic lives in one place.
"""

import os
import time
from pathlib import Path

from dotenv import load_dotenv
from openai import APIConnectionError, APITimeoutError, OpenAI, RateLimitError

# Load local .env file from the project root when present.
load_dotenv(Path(__file__).resolve().parent / ".env")

# --- Model selection -------------------------------------------------------
# The task pointed at llama-3.3-70b, but that model was deprecated on Cerebras
# in Feb 2026. Its official replacement is `gpt-oss-120b` (open-weight, Apache
# 2.0), which is what we default to. Kept in an env var so it's a one-line swap
# when the catalog changes again: https://inference-docs.cerebras.ai/models
DEFAULT_MODEL = "gpt-oss-120b"
MODEL = os.environ.get("CEREBRAS_MODEL", DEFAULT_MODEL)

BASE_URL = "https://api.cerebras.ai/v1"

# Free tier is ~30 requests/minute. If we trip that limit we get HTTP 429;
# back off along this schedule (seconds) rather than crashing mid-conversation.
_BACKOFF_SCHEDULE = [2, 4, 8, 16]


def get_client():
    """Build an OpenAI-compatible client pointed at Cerebras.

    max_retries=0 turns off the SDK's *own* silent retry loop so our backoff in
    chat() is the single, visible authority on rate limits — otherwise the two
    fight each other and a 429 just looks like a long hang before crashing.
    """
    api_key = os.environ.get("CEREBRAS_API_KEY")
    if not api_key:
        raise SystemExit(
            "CEREBRAS_API_KEY is not set. Grab a free key at "
            "https://cloud.cerebras.ai and run:\n"
            "    export CEREBRAS_API_KEY=your_key_here"
        )
    return OpenAI(api_key=api_key, base_url=BASE_URL, max_retries=0)


def _retry_after_seconds(err, fallback):
    """Prefer the server's Retry-After header over our guess, when present."""
    resp = getattr(err, "response", None)
    headers = getattr(resp, "headers", None) or {}
    value = headers.get("retry-after") or headers.get("Retry-After")
    try:
        return max(float(value), fallback)
    except (TypeError, ValueError):
        return fallback


def chat(client, messages, max_completion_tokens=512, temperature=0.8):
    """Call chat completions, retrying on rate limits / transient network errors.

    Returns the assistant message content as a plain string. On a 429 we wait —
    honoring the server's Retry-After if it sends one — then try again, so a
    burst against the free tier's ~30 req/min limit self-heals instead of
    crashing the conversation.
    """
    for attempt in range(len(_BACKOFF_SCHEDULE) + 1):
        try:
            resp = client.chat.completions.create(
                model=MODEL,
                messages=messages,
                max_completion_tokens=max_completion_tokens,
                temperature=temperature,
            )
            return resp.choices[0].message.content.strip()
        except (RateLimitError, APIConnectionError, APITimeoutError) as err:
            if attempt >= len(_BACKOFF_SCHEDULE):
                raise
            wait = _BACKOFF_SCHEDULE[attempt]
            if isinstance(err, RateLimitError):
                wait = _retry_after_seconds(err, wait)
                print(f"[rate limited — waiting {wait:.0f}s before retrying...]")
            else:
                print(f"[connection hiccup — retrying in {wait}s...]")
            time.sleep(wait)
