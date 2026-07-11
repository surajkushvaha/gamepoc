"""Thin wrapper around the Cerebras chat-completions endpoint.

Cerebras exposes an OpenAI-compatible API, so we just point the official
`openai` client at Cerebras' base URL. Everything else in the spike talks to
the model through the single `chat()` helper here so the retry/backoff and
model-selection logic lives in one place.
"""

import os
import time

from openai import OpenAI

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
    """Build an OpenAI-compatible client pointed at Cerebras."""
    api_key = os.environ.get("CEREBRAS_API_KEY")
    if not api_key:
        raise SystemExit(
            "CEREBRAS_API_KEY is not set. Grab a free key at "
            "https://cloud.cerebras.ai and run:\n"
            "    export CEREBRAS_API_KEY=your_key_here"
        )
    return OpenAI(api_key=api_key, base_url=BASE_URL)


def _is_rate_limit(err: Exception) -> bool:
    """Best-effort detection of a 429 across openai SDK versions."""
    status = getattr(err, "status_code", None) or getattr(err, "code", None)
    if status == 429:
        return True
    return "rate limit" in str(err).lower() or "429" in str(err)


def chat(client, messages, max_completion_tokens=512, temperature=0.8):
    """Call chat completions with simple exponential backoff on rate limits.

    Returns the assistant message content as a plain string.
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
        except Exception as err:  # noqa: BLE001 - prototype: keep it simple
            if attempt < len(_BACKOFF_SCHEDULE) and _is_rate_limit(err):
                wait = _BACKOFF_SCHEDULE[attempt]
                print(f"[rate limited, retrying in {wait}s...]")
                time.sleep(wait)
                continue
            raise
