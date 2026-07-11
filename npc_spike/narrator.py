"""The narrator: an LLM game master that generates every scene after the
scripted first login.

Nothing here is a fixed string shown to the player — session openings,
arrivals, and the outcomes of exploring are all generated from the real saved
state (where you are, what time it is, what recently happened), so no two
visits read the same.
"""

from llm import chat
from world import LOCATIONS, WORLD_LORE, when_and_where

# Shared style rules so the narrator stays a camera, not a co-author: it paints
# the moment but must not invent plot, speak for NPCs, or decide for the player.
_STYLE = """\
You are the narrator of a quiet low-fantasy text game. Style rules:
- Write in second person ("you"), present tense. 2-4 short sentences, no more.
- Ground everything in the location, time of day, and facts you're given.
- Small sensory details over drama. No plot twists, no new characters, no
  treasure, no danger unless the player's own action clearly causes it.
- NEVER speak dialogue for anyone, never decide the player's feelings or next
  action, and never address the player out of character.
"""


def _scene_facts(world, location_id):
    loc = LOCATIONS[location_id]
    return (
        f"World: {WORLD_LORE}\n"
        f"Current moment: {when_and_where(world, location_id)}.\n"
        f"Location: {loc['name']} — {loc['description']}"
    )


def narrate_login(world, location_id, last_memory=None):
    """Opening scene for a returning player: picks up exactly where they left
    off, colored by the most recent thing that happened to them."""
    recent = f"\nLast time: {last_memory}" if last_memory else ""
    prompt = (
        f"{_scene_facts(world, location_id)}{recent}\n\n"
        "The player returns to the game here, exactly where they left off. "
        "Narrate the moment they find themselves in — the place, the hour, "
        "the feel of picking their life here back up."
    )
    return chat(
        [{"role": "system", "content": _STYLE}, {"role": "user", "content": prompt}],
        max_completion_tokens=180,
        temperature=0.9,  # high temp on purpose: openings should vary
    )


def narrate_arrival(world, from_id, to_id):
    """The walk from one place to another, generated from the map + clock."""
    frm, to = LOCATIONS[from_id], LOCATIONS[to_id]
    prompt = (
        f"{_scene_facts(world, to_id)}\n\n"
        f"The player just walked here from {frm['name']}. Narrate the short "
        "walk and what greets them as they arrive."
    )
    return chat(
        [{"role": "system", "content": _STYLE}, {"role": "user", "content": prompt}],
        max_completion_tokens=160,
        temperature=0.9,
    )


def narrate_action(world, location_id, player_text):
    """Resolve what the player says/does somewhere with no NPC around —
    looking, searching, wandering. The narrator is the world's answer."""
    prompt = (
        f"{_scene_facts(world, location_id)}\n\n"
        f"Alone here, the player does/says: {player_text!r}\n"
        "Narrate what they find, notice, or what happens. Stay modest and "
        "grounded — this is an ordinary place on an ordinary day."
    )
    return chat(
        [{"role": "system", "content": _STYLE}, {"role": "user", "content": prompt}],
        max_completion_tokens=180,
        temperature=0.85,
    )
