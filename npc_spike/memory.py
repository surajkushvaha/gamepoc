"""Memory stream: retrieval, per-turn memory logging, and end-of-session reflection.

No embeddings or vector search — at this scale a recency + importance sort is
plenty, and it keeps every prompt small enough for the free-tier context cap.
"""

import json
import uuid
from datetime import datetime, timezone

from llm import chat

# How many memories of each kind to surface per turn. Kept small on purpose:
# the free tier caps context around 8k tokens, so retrieval must stay lean.
RECENT_COUNT = 5
IMPORTANT_COUNT = 3


def _now():
    return datetime.now(timezone.utc).isoformat()


def _extract_json(text):
    """Pull the first {...} block out of a model reply and parse it.

    Models sometimes wrap JSON in prose or ```json fences; be forgiving.
    """
    start = text.find("{")
    end = text.rfind("}")
    if start == -1 or end == -1 or end < start:
        return None
    try:
        return json.loads(text[start : end + 1])
    except json.JSONDecodeError:
        return None


# --- STEP 2 (retrieve) -----------------------------------------------------
def retrieve(state):
    """Return the memories to surface this turn: the RECENT_COUNT most recent
    plus the IMPORTANT_COUNT highest-importance ones, deduped.

    Also bumps `last_accessed` on everything we surface, so the memory stream
    reflects what's actually been recalled (useful when inspecting state.json).
    """
    memories = state["memories"]
    recent = sorted(memories, key=lambda m: m["timestamp"], reverse=True)[:RECENT_COUNT]
    important = sorted(memories, key=lambda m: m["importance"], reverse=True)[:IMPORTANT_COUNT]

    seen = set()
    combined = []
    for m in recent + important:  # recent first, then fill in salient older ones
        if m["id"] not in seen:
            seen.add(m["id"])
            m["last_accessed"] = _now()
            combined.append(m)
    return combined


# --- STEP 3 (log a memory after each turn) ---------------------------------
def summarize_turn(client, player_text, npc_text):
    """Ask the model to summarize the exchange into a structured memory entry.

    A second lightweight call: we ask for a small JSON block describing what
    happened, its emotional tone for Wren, and how important it is to remember.
    """
    prompt = f"""You are Wren's memory. Summarize this exchange into ONE memory
entry from Wren's point of view. Respond with ONLY a JSON object, no prose:

{{
  "description": "one plain sentence: what happened / what the person said or did",
  "emotional_valence": "a short phrase for how it made Wren feel, e.g. 'felt appreciated' or 'felt dismissed'",
  "importance": <integer 1-10, how important this is for Wren to remember>
}}

Person said: {player_text!r}
Wren replied: {npc_text!r}
"""
    raw = chat(
        client,
        [{"role": "user", "content": prompt}],
        max_completion_tokens=200,
        temperature=0.3,  # low temp: we want reliable, parseable structure
    )
    parsed = _extract_json(raw) or {}

    # Fall back to sane defaults if the model returned something unparseable,
    # so a single bad response never loses the memory entirely.
    description = parsed.get("description") or f"The person said: {player_text}"
    valence = parsed.get("emotional_valence") or "neutral"
    try:
        importance = int(parsed.get("importance", 3))
    except (TypeError, ValueError):
        importance = 3
    importance = max(1, min(10, importance))

    now = _now()
    return {
        "id": str(uuid.uuid4()),
        "timestamp": now,
        "description": description,
        "emotional_valence": valence,
        "importance": importance,
        "last_accessed": now,
    }


# --- STEP 4 (reflect on exit) ----------------------------------------------
def reflect(client, existing_beliefs, session_memories):
    """Turn this session's memories into 1-3 updated beliefs about the player.

    Reflection is what lets Wren's *opinion* evolve rather than just accumulating
    raw events. We hand the model the current beliefs plus what just happened and
    ask for a refreshed, small set of belief statements, which replaces the old
    set. If nothing new happened this session, we keep the existing beliefs.
    """
    if not session_memories:
        return existing_beliefs

    prior = "\n".join(f"- {b['belief']}" for b in existing_beliefs) or "(none yet)"
    events = "\n".join(
        f"- {m['description']} ({m['emotional_valence']})" for m in session_memories
    )

    prompt = f"""You are Wren reflecting after a conversation. Based on your
prior beliefs about this person and what happened just now, produce an UPDATED
set of 1-3 belief statements about them (each one short sentence, first person,
e.g. "This person seems genuinely curious about me."). Update or replace old
beliefs where the new events warrant it; keep ones that still hold.

Respond with ONLY a JSON object, no prose:
{{ "beliefs": ["...", "..."] }}

Prior beliefs:
{prior}

What happened this session:
{events}
"""
    raw = chat(
        client,
        [{"role": "user", "content": prompt}],
        max_completion_tokens=300,
        temperature=0.4,
    )
    parsed = _extract_json(raw) or {}
    statements = parsed.get("beliefs")

    # If reflection failed to parse, don't wipe out what Wren already believed.
    if not isinstance(statements, list) or not statements:
        return existing_beliefs

    now = _now()
    return [
        {"id": str(uuid.uuid4()), "timestamp": now, "belief": str(s).strip()}
        for s in statements
        if str(s).strip()
    ][:3]
