"""Multi-provider LLM router (availability-aware failover).

The free tiers we use rate-limit aggressively, so relying on a single provider
means constant 429s. Instead we keep an ordered list of providers and, on each
call, try them best-first: if one rate-limits, errors, or returns empty output,
we immediately fall over to the next. Every provider here is OpenAI-compatible,
so a single `openai` client works for all of them — only the base URL, API key,
and model name change.

Configure keys in `~/.secrets/.env` (machine-global, shared across projects)
or a local git-ignored `.env`. Set at least one; the router skips any provider
whose key is missing. Override the order with NPC_AI_ROUTE.
"""

import os
import time
from pathlib import Path

from dotenv import load_dotenv
from openai import APIConnectionError, APIError, APITimeoutError, OpenAI, RateLimitError

# Secrets live in the machine-global ~/.secrets/.env, shared by every project
# (keeps keys out of project folders that get screen-shared). A local .env in
# this folder still wins when present: dotenv never overrides vars already set.
load_dotenv(Path(__file__).resolve().parent / ".env")
load_dotenv(Path.home() / ".secrets" / ".env")

# --- Provider registry -----------------------------------------------------
# name -> (OpenAI-compatible base URL, env var holding the key).
# Cloudflare's base URL is templated with the account id, filled in below.
_PROVIDERS = {
    "cerebras":   ("https://api.cerebras.ai/v1",        "CEREBRAS_API_KEY"),
    "groq":       ("https://api.groq.com/openai/v1",    "GROQ_API_KEY"),
    "nvidia":     ("https://integrate.api.nvidia.com/v1", "NVIDIA_NIM_API_KEY"),
    "openrouter": ("https://openrouter.ai/api/v1",      "OPENROUTER_API_KEY"),
    "cloudflare": ("__cloudflare__",                    "CLOUDFLARE_API_TOKEN"),
    # Ollama Cloud (ollama.com account key). Model names keep Ollama's own
    # "name:tag" form, e.g. gemma4:31b — the route parser splits provider from
    # model on the FIRST colon only, so those tags survive intact.
    "ollama":     ("https://ollama.com/v1",             "OLLAMA_API_KEY"),
}

# Cerebras' API prefers the newer `max_completion_tokens`; every other
# provider here still expects the classic `max_tokens`.
_TOKEN_PARAM = {"cerebras": "max_completion_tokens"}

# Default failover order (best-first), in two tiers:
#   Tier 1 — Gemma 4 31B, the primary voice, on every provider that hosts it.
#   Tier 2 — gpt-oss-120b, the fallback: a model virtually every provider
#            hosts, so even a full Gemma outage still answers with a single
#            consistent model.
# Ordering within tiers reflects observed reliability from live dashboards:
# Groq answered ~everything, Cerebras is solid (its Gemma occasionally hits
# capacity), OpenRouter's free upstreams 429 even after its internal retries —
# so OpenRouter sits last in each tier.
DEFAULT_ROUTE = [
    # tier 1: Gemma 4 31B (primary)
    "cerebras:gemma-4-31b",
    "ollama:gemma4:31b",
    "nvidia:google/gemma-4-31b-it",
    "openrouter:google/gemma-4-31b-it:free",
    # tier 2: gpt-oss-120b (fallback, hosted nearly everywhere)
    "groq:openai/gpt-oss-120b",
    "cerebras:gpt-oss-120b",
    "cloudflare:@cf/openai/gpt-oss-120b",
    "ollama:gpt-oss:120b",
    "nvidia:openai/gpt-oss-120b",
    "openrouter:openai/gpt-oss-120b:free",
]

# If a full pass over the route fails (e.g. everything is momentarily limited),
# wait and try the whole route again along this schedule before giving up.
_BACKOFF_SCHEDULE = [3, 8]

# Circuit breaker: an entry that just failed sits out for this many seconds
# instead of being retried on every call. Without this, one dead provider at
# the head of the route adds its failure latency to EVERY turn; with it, only
# the first turn pays the sweep and later turns go straight to whoever works.
_COOLDOWN_SECONDS = 120
_cooldown_until = {}  # (provider, model) -> time.monotonic() deadline

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
    # silently retry. Short timeout: healthy providers answer in a couple of
    # seconds; a hung one must not stall the conversation for a minute.
    client = OpenAI(api_key=api_key, base_url=base_url, max_retries=0, timeout=15)
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
            "least one key (CEREBRAS_API_KEY, GROQ_API_KEY, OLLAMA_API_KEY, "
            "OPENROUTER_API_KEY, NVIDIA_NIM_API_KEY, or CLOUDFLARE_API_TOKEN "
            "+ CLOUDFLARE_ACCOUNT_ID)."
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
        # Skip entries that recently failed (still cooling down) — unless that
        # leaves nothing, in which case try everyone anyway rather than fail.
        now = time.monotonic()
        candidates = [e for e in route if _cooldown_until.get(e, 0.0) <= now]
        if not candidates:
            candidates = route

        for provider, model in candidates:
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
                    _cooldown_until.pop((provider, model), None)
                    return content
                last_err = RuntimeError("empty output")
                _cooldown_until[(provider, model)] = time.monotonic() + _COOLDOWN_SECONDS
                print(f"[{provider} returned nothing — benching it for "
                      f"{_COOLDOWN_SECONDS}s, trying next...]")
            except (RateLimitError, APIConnectionError, APITimeoutError, APIError) as err:
                last_err = err
                _cooldown_until[(provider, model)] = time.monotonic() + _COOLDOWN_SECONDS
                tag = "rate limited" if isinstance(err, RateLimitError) else "unavailable"
                print(f"[{provider} {tag} — benching it for {_COOLDOWN_SECONDS}s, "
                      f"trying next... ({_short(err)})]")

        # Whole route exhausted this pass; back off and try again if we can.
        if pass_index < len(_BACKOFF_SCHEDULE):
            wait = _BACKOFF_SCHEDULE[pass_index]
            print(f"[all providers busy — waiting {wait}s before retrying...]")
            time.sleep(wait)

    raise RuntimeError(f"All providers failed. Last error: {_short(last_err)}")
