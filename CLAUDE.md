# gamepoc

AI-driven NPC world prototype ("Saltmere"): a CLI text game where LLM-backed
NPCs have persistent memory, reflection, beliefs, gossip, and permadeath, and
the player is an Awakened rank-E adventurer with referee-resolved actions.

**Read `docs/PROJECT_SUMMARY.md` first** — it holds the full architecture,
every design decision and its reason, live provider-reliability findings, and
the agreed next steps. Keep it updated when the architecture changes.

Quick facts:
- All code in `npc_spike/`; run with `python main.py` (Python 3.10+,
  `pip install -r npc_spike/requirements.txt`).
- API keys come from `~/.secrets/.env` or a local git-ignored `.env`
  (`.env.example` lists providers). At least one is required.
- LLM access ONLY through `llm.chat()` — it owns multi-provider failover,
  circuit breaker, and rate-limit handling. Never call a provider directly.
- One save per character in `npc_spike/data/saves/<name>.json` (git-ignored).
  NPC memories are per-person; never share a save between characters.
- Fixed scene strings are forbidden by design: after the scripted first login,
  every scene must be generated (narrator.py) from saved state.
- Player actions (`*action*`) must resolve through referee.py before an NPC
  sees them; NPC prompts treat `[Referee: ...]` lines as ground truth.
- Reflect + gossip + save run in main()'s `finally` — keep every exit path
  loss-proof.
