"""The referee: canonical resolution for player *actions*.

The problem this solves: without it, whether an action "works" is decided by
whichever NPC happens to be watching — the LLM playing Sera arbitrates your
"magic", and each character rules differently. The referee is an impartial
layer that resolves every *action* against the world's rules (world.PLAYER_RULES)
BEFORE the NPC sees it, producing one established fact. The NPC then reacts to
what actually happened, not to the player's claim.

This is also the seam where a real ability/combat/inventory system plugs in
later: parse the action, check it against player state, mutate the world, and
hand the NPC the result.
"""

import re

from llm import chat
from memory import _extract_json
from world import LOCATIONS, PLAYER_RULES, WORLD_LORE, when_and_where

# An "action" is any input containing *asterisked* (or parenthesized) stage
# direction — the conventions the game teaches the player.
_ACTION_RE = re.compile(r"\*[^*]+\*|\([^)]+\)")


def is_action(player_text):
    return bool(_ACTION_RE.search(player_text))


def resolve_action(world, location_id, npc_name, player_text):
    """Decide what ACTUALLY happens. Returns a dict:

        {"outcome": "succeeds"|"partly"|"fails"|"impossible",
         "fact": "one past-tense sentence of what really happened"}

    or None if resolution failed (callers fall back to the old behavior of
    letting the NPC interpret the raw text).
    """
    witness = f"{npc_name} is present and watching." if npc_name else "No one else is here."
    prompt = f"""You are the impartial REFEREE of a text game. You do not roleplay
anyone; you only decide what actually happens, like physics.

World: {WORLD_LORE}

Hard rules about the player character:
{PLAYER_RULES}

Scene: {when_and_where(world, location_id)} — {LOCATIONS[location_id]['description']}
{witness}

The player wrote (text in *asterisks*/(parentheses) is attempted action, the
rest is speech): {player_text!r}

Resolve the ATTEMPTED ACTION strictly under the rules:
- Ordinary feats (sitting, handing over an item, working, running) usually succeed.
- Risky feats can succeed, partly succeed, or fail — judge plausibility.
- Anything violating the rules (magic, superhuman feats, mind control, erasing
  memories, teleporting) is "impossible": describe the attempt visibly failing
  or amounting to nothing — the words are just words.
- Violence between people: resolve the ATTEMPT realistically (people dodge,
  struggle, shout, get hurt) but never kill or permanently maim anyone.
- Never invent new characters, items of power, or plot.

Respond with ONLY a JSON object, no prose:
{{ "outcome": "succeeds" | "partly" | "fails" | "impossible",
  "fact": "ONE short past-tense sentence stating what actually, visibly happened" }}
"""
    raw = chat(
        [{"role": "user", "content": prompt}],
        max_completion_tokens=150,
        temperature=0.3,  # referee should be consistent, not creative
    )
    parsed = _extract_json(raw) or {}
    outcome = str(parsed.get("outcome", "")).strip().lower()
    fact = str(parsed.get("fact", "")).strip()
    if outcome in {"succeeds", "partly", "fails", "impossible"} and fact:
        return {"outcome": outcome, "fact": fact}
    return None
