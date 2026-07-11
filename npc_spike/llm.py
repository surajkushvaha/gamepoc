"""Multi-provider LLM router (availability-aware failover).

The free tiers we use rate-limit aggressively, so relying on a single provider
means constant 429s. Instead we keep an ordered list of providers and, on each
call, try them best-first: if one rate-limits, errors, or returns empty output,
we immediately fall over to the next. Every provider here is OpenAI-compatible,
so a single `openai` client works for all of them — only the base URL, API key,
and model name change.

Configure keys in a local `.env` (git-ignored). Set at least one; the router
skips any provider whose key is missing. Override the order with NPC_AI_ROUTE.
"""

import os
import time
from pathlib import Path

from dotenv import load_dotenv
from openai import APIConnectionError, APIError, APITimeoutError, OpenAI, RateLimitError

# Load local .env file from the project root when present.
load_dotenv(Path(__file__).resolve().parent / ".env")

# --- Provider registry -----------------------------------------------------
# name -> (OpenAI-compatible base URL, env var holding the key).
# Cloudflare's base URL is templated with the account id, filled in below.
_PROVIDERS = {
    "cerebras":   ("https://api.cerebras.ai/v1",        "CEREBRAS_API_KEY"),
    "groq":       ("https://api.groq.com/openai/v1",    "GROQ_API_KEY"),
    "nvidia":     ("https://integrate.api.nvidia.com/v1", "NVIDIA_NIM_API_KEY"),
    "openrouter": ("https://openrouter.ai/api/v1",      "OPENROUTER_API_KEY"),
    "cloudflare": ("__cloudflare__",                    "CLOUDFLARE_API_TOKEN"),
}

# Cerebras' API prefers the newer `max_completion_tokens`; every other
# provider here still expects the classic `max_tokens`.
_TOKEN_PARAM = {"cerebras": "max_completion_tokens"}

# Default failover order (best-first), in two tiers:
#   Tier 1 — Gemma 4 31B, the primary voice, on every provider that hosts it.
#   Tier 2 — gpt-oss-120b, the fallback: the one model ALL five providers host,
#            so even a full Gemma outage still answers with a single consistent
#            model. The fallback tier leads with providers not used in tier 1
#            (Groq, Cloudflare), whose rate-limit budgets are still untouched.
DEFAULT_ROUTE = [
    # tier 1: Gemma 4 31B (primary)
    "cerebras:gemma-4-31b",
    "nvidia:google/gemma-4-31b-it",
    "openrouter:google/gemma-4-31b-it:free",
    # tier 2: gpt-oss-120b (fallback, hosted everywhere)
    "groq:openai/gpt-oss-120b",
    "cloudflare:@cf/openai/gpt-oss-120b",
    "cerebras:gpt-oss-120b",
    "nvidia:openai/gpt-oss-120b",
    "openrouter:openai/gpt-oss-120b:free",
]

# If a full pass over the route fails (e.g. everything is momentarily limited),
# wait and try the whole route again along this schedule before giving up.
_BACKOFF_SCHEDULE = [3, 8]

_client_cache = {}


def _client_for(provider):
    """Return a cached OpenAI client for a provider, or None if unconfigured."""
    if provider in _client_cache:
        return _client_cache[provider]
    if provider not in _PROVIDERS:
        return None
    base_url, key_env = _PROVIDERS[provider]
    api_key = os.environ.get(key_env)
    if not api_key:
        return None
    if provider == "cloudflare":
        account_id = os.environ.get("CLOUDFLARE_ACCOUNT_ID")
        if not account_id:
            return None  # Cloudflare needs the account id too
        base_url = f"https://api.cloudflare.com/client/v4/accounts/{account_id}/ai/v1"
    # max_retries=0: the router handles retries/failover, so the SDK shouldn't
    # silently retry. timeout keeps a hung provider from stalling the whole app.
    client = OpenAI(api_key=api_key, base_url=base_url, max_retries=0, timeout=60)
    _client_cache[provider] = client
    return client


def _parse_route():
    """Build the active route from NPC_AI_ROUTE (or the default), dropping any
    provider whose key isn't configured."""
    raw = os.environ.get("NPC_AI_ROUTE")
    specs = [s.strip() for s in raw.split(",")] if raw else DEFAULT_ROUTE
    route = []
    for spec in specs:
        if ":" not in spec:
            continue
        provider, model = spec.split(":", 1)  # split once: models can contain ':'
        provider, model = provider.strip().lower(), model.strip()
        if _client_for(provider) is not None:
            route.append((provider, model))
    return route


def describe_route():
    """Human-readable 'provider:model' list for the active route (for startup)."""
    return [f"{p}:{m}" for p, m in _parse_route()]


def get_client():
    """Validate that at least one provider is configured; return the route.

    Kept named get_client() so main.py's startup check reads naturally. Raises
    with a helpful message if no keys are set.
    """
    route = _parse_route()
    if not route:
        raise SystemExit(
            "No AI providers configured. Copy .env.example to .env and set at "
            "least one key (CEREBRAS_API_KEY, GROQ_API_KEY, OPENROUTER_API_KEY, "
            "NVIDIA_NIM_API_KEY, or CLOUDFLARE_API_TOKEN + CLOUDFLARE_ACCOUNT_ID)."
        )
    return route


def _short(err):
    """A compact one-line reason for logging a provider failure."""
    text = str(err).strip().replace("\n", " ")
    return (text[:120] + "...") if len(text) > 120 else text or type(err).__name__


def chat(messages, max_completion_tokens=512, temperature=0.8):
    """Send a chat request, failing over across providers until one answers.

    Returns the assistant message content as a plain string. Tries each provider
    in the route once; on rate-limit/error/empty output it moves to the next. If
    an entire pass fails, it waits (see _BACKOFF_SCHEDULE) and retries the route.
    """
    route = _parse_route()
    if not route:
        raise SystemExit("No AI providers configured (see .env.example).")

    last_err = None
    for pass_index in range(len(_BACKOFF_SCHEDULE) + 1):
        for provider, model in route:
            client = _client_for(provider)
            token_param = _TOKEN_PARAM.get(provider, "max_tokens")
            try:
                resp = client.chat.completions.create(
                    model=model,
                    messages=messages,
                    temperature=temperature,
                    **{token_param: max_completion_tokens},
                )
                content = (resp.choices[0].message.content or "").strip()
                if content:
                    return content
                last_err = RuntimeError("empty output")
                print(f"[{provider} returned nothing, trying next provider...]")
            except (RateLimitError, APIConnectionError, APITimeoutError, APIError) as err:
                last_err = err
                tag = "rate limited" if isinstance(err, RateLimitError) else "unavailable"
                print(f"[{provider} {tag} ({_short(err)}), trying next provider...]")

        # Whole route exhausted this pass; back off and try again if we can.
        if pass_index < len(_BACKOFF_SCHEDULE):
            wait = _BACKOFF_SCHEDULE[pass_index]
            print(f"[all providers busy — waiting {wait}s before retrying...]")
            time.sleep(wait)

    raise RuntimeError(f"All providers failed. Last error: {_short(last_err)}")
