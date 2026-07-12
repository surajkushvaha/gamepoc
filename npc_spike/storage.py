"""Persistence: one save file PER CHARACTER, under data/saves/<slug>.json.

Each character owns a whole world instance — the clock, their position, and
every NPC's memories/beliefs. That isolation is deliberate: NPC memories are
about a specific person, so two characters sharing Wren's memory stream would
corrupt both stories. Logging in with an existing name resumes that world;
a new name begins a new one.

Save schema (v3):
{
  "version": 3,
  "started": bool,              # has the scripted first login happened yet?
  "world":  {"day": int, "time_index": int},
  "player": {"name": str, "gender": str, "level": int, "abilities": [...],
              "location": "gulls_rest"},
  "npcs":   {npc_id: {"memories": [...], "beliefs": [...], "alive": bool}, ...}
}

The pre-account save (data/state.json) is adopted by the FIRST character
created, so an existing relationship with the town carries over.
"""

import json
import os
import re

_DATA_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data")
_SAVES_DIR = os.path.join(_DATA_DIR, "saves")
_LEGACY_PATH = os.path.join(_DATA_DIR, "state.json")

NPC_IDS = ["wren", "brann", "sera"]
START_LOCATION = "gulls_rest"

# Set by set_active_character(); everything saves/loads through it.
STATE_PATH = None


def slugify(name):
    slug = re.sub(r"[^a-z0-9]+", "_", name.strip().lower()).strip("_")
    return slug or "traveler"


def list_characters():
    """Names of existing characters (from their save files), for the login."""
    if not os.path.isdir(_SAVES_DIR):
        return []
    names = []
    for fn in sorted(os.listdir(_SAVES_DIR)):
        if fn.endswith(".json"):
            try:
                with open(os.path.join(_SAVES_DIR, fn), "r", encoding="utf-8") as f:
                    names.append(json.load(f)["player"]["name"])
            except Exception:  # noqa: BLE001 - unreadable save; show the slug
                names.append(fn[:-5])
    return names


def character_exists(name):
    return os.path.exists(os.path.join(_SAVES_DIR, slugify(name) + ".json"))


def set_active_character(name):
    """Point all load/save at this character's world."""
    global STATE_PATH
    STATE_PATH = os.path.join(_SAVES_DIR, slugify(name) + ".json")


def _empty_npc():
    return {"memories": [], "beliefs": [], "alive": True}


def _empty_state(name="Traveler", gender="unspecified"):
    from world import STARTING_ABILITIES  # local import avoids a cycle
    return {
        "version": 3,
        "started": False,
        "world": {"day": 1, "time_index": 3},  # first login: evening, day 1
        "player": {
            "name": name,
            "gender": gender,
            "level": 1,
            "abilities": list(STARTING_ABILITIES),
            "location": START_LOCATION,
        },
        "npcs": {npc_id: _empty_npc() for npc_id in NPC_IDS},
    }


def _normalize(raw, name, gender):
    """Fill defaults / upgrade older schemas into v3 without losing anything."""
    state = _empty_state(name, gender)
    if "npcs" in raw:  # v2+: keep world/position/minds
        state["started"] = raw.get("started", True)
        state["world"] = raw.get("world", state["world"])
        for npc_id in NPC_IDS:
            npc = raw.get("npcs", {}).get(npc_id, _empty_npc())
            npc.setdefault("alive", True)
            state["npcs"][npc_id] = npc
        old_player = raw.get("player", {})
        state["player"]["location"] = old_player.get("location", START_LOCATION)
        # keep any newer player fields already saved (level, abilities...)
        for key in ("level", "abilities", "gender", "name"):
            if key in old_player:
                state["player"][key] = old_player[key]
    else:  # v1: bare Wren memories/beliefs
        state["started"] = bool(raw.get("memories"))
        state["npcs"]["wren"]["memories"] = raw.get("memories", [])
        state["npcs"]["wren"]["beliefs"] = raw.get("beliefs", [])
    state["player"]["name"] = state["player"].get("name") or name
    return state


def create_character(name, gender):
    """New character. Adopts the legacy pre-account save if this is the very
    first character ever created, so existing history isn't orphaned."""
    set_active_character(name)
    if os.path.exists(_LEGACY_PATH) and not list_characters():
        try:
            with open(_LEGACY_PATH, "r", encoding="utf-8") as f:
                raw = json.load(f)
            state = _normalize(raw, name, gender)
            state["player"]["name"] = name
            state["player"]["gender"] = gender
            os.rename(_LEGACY_PATH, _LEGACY_PATH + ".migrated")
            save_state(state)
            return state, True  # adopted legacy world
        except (json.JSONDecodeError, OSError):
            pass
    state = _empty_state(name, gender)
    save_state(state)
    return state, False


def load_state():
    """Load the active character's world (set_active_character first)."""
    if STATE_PATH is None:
        raise RuntimeError("No active character — call set_active_character().")
    if not os.path.exists(STATE_PATH):
        return _empty_state()
    try:
        with open(STATE_PATH, "r", encoding="utf-8") as f:
            raw = json.load(f)
    except (json.JSONDecodeError, OSError):
        return _empty_state()
    return _normalize(raw, raw.get("player", {}).get("name", "Traveler"),
                      raw.get("player", {}).get("gender", "unspecified"))


def save_state(state):
    """Write the active character's world to disk."""
    if STATE_PATH is None:
        raise RuntimeError("No active character — call set_active_character().")
    os.makedirs(os.path.dirname(STATE_PATH), exist_ok=True)
    with open(STATE_PATH, "w", encoding="utf-8") as f:
        json.dump(state, f, indent=2, ensure_ascii=False)
