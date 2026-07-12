# gamepoc — Project Summary

*Last updated: 2026-07-12. This document is the memory of the project: what
was built, why each decision was made, what was learned from live testing, and
where it's headed. Update it when the architecture changes.*

## What this is

`gamepoc` began as a throwaway spike ("can an LLM-backed NPC with persistent
memory, retrieval, reflection, and personality stay believable across separate
sessions?") and grew, through rapid playtest-driven iteration, into a small
**AI-driven world prototype**: *Saltmere*, a CLI text game where three NPCs
remember you, form opinions of you, gossip about you, and can die — and where
you are an Awakened rank-E adventurer with low-rank magic in a world of Gates
and Guild ranks.

**Verdict of the original spike: the architecture is viable.** In live play,
Wren greeted the player by name in a later session unprompted, called back to
a "vegetarian" remark from a previous session, referred the player to another
NPC from her own relationship data, and cooled visibly when the player pushed
an unwelcome joke — all emergent from the memory→reflection→belief loop.

## The game, currently

- **Login first**: enter a character name. Existing name → that character's
  world resumes exactly where it left off. New name → create character
  (gender + name), fresh world. One save per character
  (`npc_spike/data/saves/<name>.json`) because NPC memories are about a
  *specific person* — sharing them between characters would corrupt both
  stories. A pre-account `state.json` is adopted by the first character.
- **Setting**: mana returned three generations ago. Gates spill monsters; the
  Guild ranks the Awakened E→S; healers skirt forbidden arts; a hidden order
  moves in the shadows (inspired by Solo Leveling / Eminence in Shadow /
  Shangri-La Frontier / Redo of Healer, original naming — it's our IP). An
  unstable Gate glimmers off Saltmere's coast: the designated future dungeon.
- **Player**: level 1, rank E, three abilities — Spark (small mana bolt),
  Mend (slow minor heal by touch), Shade-step (a few hidden steps). `/stats`
  shows the sheet.
- **Map**: Gull's Rest tavern (Wren) ↔ Docks (Brann) ↔ Market (Sera), plus
  the empty Coast Road and Old Lighthouse. `/go <place>`, `/where`, `/look`.
- **Clock**: five-step time of day, ticks per login, rolls into new days.
  Position + clock persist; only the very first login is scripted — every
  later scene is generated from saved state.

## The cast

| NPC | Place | Personality | Sees the others as |
|---|---|---|---|
| **Wren** | Gull's Rest | warm underneath, guarded, values honesty, dry humor; grew up in the lighthouse, parents lost at sea | Brann = family; likes Sera but guards secrets from her |
| **Brann** | Docks | gruff harbor master, 30 years on the docks; judges by work, fair to a fault, hidden soft spot | Wren = family; tolerates Sera's chatter, trusts her prices |
| **Sera** | Market | chatty trader, knows everyone's business by sundown, shrewd, embellishes | needles Wren fondly; would trust Brann with her strongbox |

Personalities are **data** in `npc.py` — adding a character is adding a dict
entry. Relationships are in each prompt, so badmouthing one NPC to another
lands realistically.

## Core systems (and why they exist)

### 1. Memory loop (the original spike, per NPC)
1. Load memories + beliefs. 2. Per exchange: retrieve 5 most recent + 3
highest-importance memories (deduped, `last_accessed` bumped) + all beliefs →
reply from [personality + relationships + world + live scene + memories +
recent turns]. 3. After each exchange: a lightweight call logs a structured
memory (`description`, `emotional_valence`, `importance` 1–10). 4. On quit:
**reflection** turns the session's memories into 1–3 updated beliefs.
No embeddings — recency+importance sort is enough at this scale and keeps
prompts inside free-tier context caps. Memories are formatted oldest-first and
labeled "already happened" so NPCs can notice repeats instead of replaying old
answers (a real bug we hit: verbatim-identical replies on revisits).

### 2. Gossip
On quit, each NPC you dealt with produces one rumor about you, planted into
the other living NPCs' memory streams as low-importance hearsay. Sera can know
your name before you meet her. Deaths propagate instantly instead (see 5).

### 3. Narrator (replaces every fixed scene string)
LLM game master (`narrator.py`) generates login scenes (resuming exactly where
you quit, colored by the last memory), walks between locations, and outcomes
of poking around empty places. Style-fenced: 2–4 sentences, second person, no
plot invention, never speaks for NPCs. Fixed "session flavor" strings were
removed after the user asked "why fixed strings, can't we generate it".

### 4. Referee (canonical action resolution)
Root fix for "my magic didn't work" / "NPCs arbitrate my actions": any input
containing `*action*` / `(action)` is resolved FIRST by an impartial referee
against the character's actual sheet (`world.build_player_rules`). In-list
abilities work at listed strength; beyond-list attempts (grand spells, mind
control, memory erasure, teleport) visibly fizzle. Output = one established
past-tense fact, printed to the player and passed to the NPC as
`[Referee: ...]` ground truth; the memory summarizer records the *fact*, not
the player's claim. This is the seam for future combat/ability/inventory
logic.

### 5. Permadeath
The referee may rule a plausible lethal attack `fatal: true` (people resist
and unarmed swings rarely kill). Death is state: `alive: false` + death record
(day + fact); the victim's location becomes permanently empty (the narrator
describes the absence via a death note); the dead keep no memories, never
speak, don't gossip. Every survivor immediately receives an importance-10
memory of the killing, queued for reflection → fear/grief/hostility beliefs.
No undo. (No legal consequence system yet — no guards/game-over.)

### 6. LLM router (`llm.py`) — hard-won reliability knowledge
Free tiers rate-limit constantly, so the router keeps an ordered
`provider:model` route and fails over on 429/error/empty output.
- **Two tiers**: Gemma 4 31B primary voice (cerebras `gemma-4-31b`, ollama
  `gemma4:31b`), then gpt-oss-120b as the hosted-nearly-everywhere fallback
  (groq/cerebras/cloudflare/ollama/nvidia), OpenRouter free last.
- **Circuit breaker**: a failing (provider,model) is benched ~62s (Cerebras
  limits are per-minute) so only the first turn pays the sweep. Client timeout
  15s, SDK retries disabled (they fought our failover and looked like hangs).
- **Live findings (2026-07)**: Groq = fastest & most reliable (~0.3s TTFT);
  Cerebras fast but RPM-limited, its Gemma sometimes at capacity; Ollama Cloud
  reliable but slow (~11s); NVIDIA hosted Gemma timed out consistently
  (removed from tier 1); OpenRouter free upstreams 429 perpetually (kept
  last-resort only). gpt-oss-120b returns output in a `reasoning` field on
  some providers — handled in `chat()`.
- Keys: `~/.secrets/.env` (machine-global) or local `.env`, both git-ignored;
  providers without keys are skipped; `NPC_AI_ROUTE` overrides the route.
  History note: an early Cerebras/Groq/OpenRouter/NVIDIA/Cloudflare key set
  was pasted in chat during development and should be treated as rotated.

### 7. Crash-safety
Reflect+gossip+save run in a `finally` block — clean quit, Ctrl-C, or API
crash, the session persists. This fixed an early data-loss bug where a 429
during reflection threw past `save_state()` and wiped the session.

## Prompt-engineering lessons (what made NPCs feel human)
- Explicitly forbid assistant tells: no reflexive end-of-reply questions, no
  exposition dumps, no instant warmth to strangers ("guarded until earned").
- One short parenthetical of stage business, then finished sentences (token
  cap 350; 220 caused mid-sentence cutoffs).
- `*asterisk*` action convention taught in narration; NPCs react physically.
- Anti-repetition: memories oldest-first + "these already happened — call out
  repeats instead of replaying answers"; openings forbidden from reusing past
  greetings/jokes.
- The player needs a stake too: the first-login narration hands them a
  situation (storm, no roof, fresh Guild license) and explicit freedom to
  define themselves; NPCs get gender by sight, the **name only through
  conversation** (keeps the organic-memory payoff).

## File map (`npc_spike/`)
`main.py` game loop + login + commands · `npc.py` cast + reply/opening
generation · `memory.py` retrieve/summarize/reflect/gossip/event memories ·
`narrator.py` generated scenes · `referee.py` action resolution ·
`world.py` lore, map, clock, player rules · `storage.py` per-character saves
(v3 schema, migrates v1/v2) · `llm.py` router · `data/saves/*.json` runtime
saves (git-ignored) · tests: `tests/test_env_loading.py`.

## Commit timeline (abridged)
spike (`40b68a6`) → character-not-assistant prompt → shared world + crash-safe
saves → multi-provider router → Gemma-4 default → gpt-oss fallback tier →
meeting scenario (NPC speaks first) → player stake + actions → circuit breaker
→ Ollama + reliability reorder → anti-repetition + rotating scenes → 3 NPCs /
gossip / exploration / persistent position → `/go` loose matching (user + AI
versions merged) → action referee → permadeath (`96c30cc`) → character login +
per-character worlds + Awakened magic (`c28111c`).

## Known gaps / agreed next steps
- **Leveling/progression**: `level` + `abilities` are saved state and the
  referee reads them per action — "close a small Gate → level 2 → stronger
  Spark or new ability" is mechanics, not rewiring. The offshore Gate is the
  designated first dungeon. (Most-wanted next feature.)
- **Economy/jobs**: Brann "hires" conversationally but no coin/world flags.
- **Justice system**: murder has social consequences only — no guards,
  bounties, or game-over.
- **NPC relationship text is static**: a dead NPC is still described in the
  others' `relationships` prose (their memories/beliefs carry the truth).
- **Belief history**: reflection replaces beliefs; no decay or history.
- **Model voice shift**: tier-2 fallback (gpt-oss) reads slightly different
  from Gemma; acceptable, visible if you squint.
