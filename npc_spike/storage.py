"""Persistence: load/save the NPC's state to a single local JSON file.

State is deliberately tiny and human-readable so you can open data/state.json
during testing and eyeball what the NPC "remembers" and "believes".
"""

import json
import os

# state.json lives next to this file, under data/.
_DATA_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data")
STATE_PATH = os.path.join(_DATA_DIR, "state.json")


def _empty_state():
    return {"memories": [], "beliefs": []}


def load_state():
    """Load persisted state, or return a fresh empty state on first run."""
    if not os.path.exists(STATE_PATH):
        return _empty_state()
    try:
        with open(STATE_PATH, "r", encoding="utf-8") as f:
            state = json.load(f)
    except (json.JSONDecodeError, OSError):
        # Corrupt/partial file: start clean rather than crash. This is a spike.
        return _empty_state()
    # Defensive defaults so a hand-edited file can't break the loop.
    state.setdefault("memories", [])
    state.setdefault("beliefs", [])
    return state


def save_state(state):
    """Write the full state back to disk, creating data/ if needed."""
    os.makedirs(_DATA_DIR, exist_ok=True)
    with open(STATE_PATH, "w", encoding="utf-8") as f:
        json.dump(state, f, indent=2, ensure_ascii=False)
