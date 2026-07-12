"""Persistence: load/save the whole game state to a single local JSON file.

Schema (v2):
{
  "version": 2,
  "started": bool,              # has the scripted first login happened yet?
  "world":  {"day": int, "time_index": int},
  "player": {"location": "gulls_rest"},
  "npcs":   {npc_id: {"memories": [...], "beliefs": [...]}, ...}
}

Old spike files (a bare {"memories", "beliefs"} for Wren) are migrated in
place so nobody loses an existing relationship with Wren.
"""

import json
import os

_DATA_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data")
STATE_PATH = os.path.join(_DATA_DIR, "state.json")

NPC_IDS = ["wren", "brann", "sera"]
START_LOCATION = "gulls_rest"


def _empty_npc():
    return {"memories": [], "beliefs": [], "alive": True}


def _empty_state():
    return {
        "version": 2,
        "started": False,
        "world": {"day": 1, "time_index": 3},  # first login: evening, day 1
        "player": {"location": START_LOCATION},
        "npcs": {npc_id: _empty_npc() for npc_id in NPC_IDS},
    }


def _migrate_v1(old):
    """Old single-NPC spike file -> v2. Wren keeps everything she knew."""
    state = _empty_state()
    state["started"] = bool(old.get("memories"))
    state["npcs"]["wren"]["memories"] = old.get("memories", [])
    state["npcs"]["wren"]["beliefs"] = old.get("beliefs", [])
    return state


def load_state():
    """Load persisted state, migrating old formats; fresh state on first run."""
    if not os.path.exists(STATE_PATH):
        return _empty_state()
    try:
        with open(STATE_PATH, "r", encoding="utf-8") as f:
            raw = json.load(f)
    except (json.JSONDecodeError, OSError):
        # Corrupt/partial file: start clean rather than crash. This is a spike.
        return _empty_state()

    if raw.get("version") != 2:
        return _migrate_v1(raw)

    # Defensive defaults so a hand-edited file can't break the loop.
    base = _empty_state()
    for key, default in base.items():
        raw.setdefault(key, default)
    for npc_id in NPC_IDS:
        raw["npcs"].setdefault(npc_id, _empty_npc())
        raw["npcs"][npc_id].setdefault("alive", True)  # pre-death saves
    return raw


def save_state(state):
    """Write the full state back to disk, creating data/ if needed."""
    os.makedirs(_DATA_DIR, exist_ok=True)
    with open(STATE_PATH, "w", encoding="utf-8") as f:
        json.dump(state, f, indent=2, ensure_ascii=False)
