# NPC memory + reflection + personality spike

A throwaway prototype that tests one thing: can an LLM-backed NPC with
**persistent memory**, **retrieval**, **reflection**, and a **personality
template** stay believable and consistent across separate sessions with the same
player? No game, no UI, no world — just a command-line chat loop with one NPC
named **Wren** (a warm, attentive companion whose opinion of you shifts based on
how you treat them).

This is an architecture viability test, not a shippable product.

## How it works

```
npc_spike/
  main.py      # CLI chat loop — orchestrates the 4 core steps
  npc.py       # Wren's personality template + reply generation
  memory.py    # retrieval (recency + importance), per-turn memory logging, reflection
  storage.py   # load/save state to a single JSON file
  llm.py       # multi-provider LLM router with availability-aware failover
  data/
    state.json # persisted memories + beliefs (created on first run)
```

The loop, per the spec:

1. **On startup** — load `data/state.json` (memories + beliefs), or start empty.
2. **Each turn** — *retrieve* the 5 most recent + 3 highest-importance memories
   (deduped) plus all beliefs, then *respond* with a prompt built from
   `personality + beliefs + retrieved memories + recent conversation`.
3. **After each turn** — a second lightweight call summarizes the exchange into a
   structured memory (`description`, `emotional_valence`, `importance`).
4. **On `quit`** — *reflect*: this session's new memories become 1-3 updated
   belief statements about the player, then everything is saved to JSON.

No embeddings or vector DB — a recency + importance sort is enough at this scale,
and it keeps prompts under the free tier's ~8k-token context cap.

## The world / setting

Wren and the player share one defined setting — **Saltmere**, a harbor town in a
low-fantasy kingdom — so Wren stays grounded in a consistent place instead of
inventing a new one each reply. It's a single editable block (`WORLD` /
`SETTING_NAME`) at the top of `npc.py`; rewrite it to re-skin the whole thing
(different town, or a modern/sci-fi setting) and Wren follows.

## The meeting scenario & playing your character

Every session opens with a concrete scene instead of dropping the player into a
blank prompt. On the **first ever session** you're a traveler caught by the
storm — night falling, boots soaked, in need of a roof and maybe work — ducking
into the Gull's Rest tavern, where Wren has never seen you and sizes you up
accordingly. **Who you are is yours to decide**: your name, your trade, why
you're on the road; Wren remembers whatever you show her. On **every later
session** you're walking back in, and Wren speaks first, greeting you based on
what she remembers — which makes the cross-session memory visible the moment
the session starts.

You can **speak** plainly or **act** by wrapping text in `*asterisks*` (or
parentheses) — e.g. `*takes a seat by the fire*` — and Wren reacts to actions
physically, not just to words. The scene text lives beside `WORLD` in `npc.py`
(`FIRST_MEETING_*` / `RETURN_*`) and is both printed to the player as narration
and injected into Wren's prompt, so you both share the same picture.

State is also saved on *every* exit path now — clean `quit`, `Ctrl-C`, or an API
error mid-session — so a hiccup can never wipe a conversation's memories.

## Setup

1. **Get at least one free API key** (all no-credit-card):
   - [Cerebras](https://cloud.cerebras.ai) — Gemma 4 31B + gpt-oss-120b, very fast (recommended primary)
   - [NVIDIA NIM](https://build.nvidia.com) — Gemma 4 31B + gpt-oss-120b
   - [OpenRouter](https://openrouter.ai) — both as `:free` models
   - [Groq](https://console.groq.com) — gpt-oss-120b fallback tier
   - [Cloudflare Workers AI](https://dash.cloudflare.com) — gpt-oss-120b fallback tier (needs token **and** account id)

2. **Install dependencies** (Python 3.10+):
   ```bash
   cd npc_spike
   pip install -r requirements.txt
   ```

3. **Create your `.env`:** copy the template and fill in the keys you have.
   ```bash
   cp .env.example .env      # then edit .env
   ```
   `.env` is git-ignored — keys never get committed.

### Multi-provider failover (this is the rate-limit fix)

Single free-tier providers rate-limit (HTTP 429) constantly. Instead of one
provider, `llm.py` keeps an **ordered route** and tries them best-first: if one
rate-limits, errors, or returns empty output, it **immediately falls over to the
next**. You only need one key to run, but adding several is what makes 429s a
non-issue. Providers whose key is missing are skipped automatically.

The default route has two tiers. **Gemma 4 31B** is the primary voice, tried on
every provider that hosts it; **gpt-oss-120b** is the fallback — it's the one
model *all five* providers host, so even a full Gemma outage still answers with
a single consistent model:

```
tier 1 (primary — Gemma 4 31B)
  cerebras:gemma-4-31b
  → nvidia:google/gemma-4-31b-it
  → openrouter:google/gemma-4-31b-it:free
tier 2 (fallback — gpt-oss-120b, hosted everywhere)
  → groq:openai/gpt-oss-120b
  → cloudflare:@cf/openai/gpt-oss-120b
  → cerebras:gpt-oss-120b
  → nvidia:openai/gpt-oss-120b
  → openrouter:openai/gpt-oss-120b:free
```

The fallback tier leads with Groq and Cloudflare — the two providers not used in
tier 1 — since their rate-limit budgets are still untouched when tier 1 is
exhausted.

Override it in `.env` (or the environment) with `NPC_AI_ROUTE`, using
`provider:model` entries, best-first:

```bash
NPC_AI_ROUTE=cerebras:gemma-4-31b, openrouter:google/gemma-4-31b-it:free
```

The active route is printed at startup, and each failover logs which provider it
skipped and why. A provider that fails is **benched for 2 minutes** (circuit
breaker) so only the first turn pays the failover sweep — later turns go
straight to whoever is answering. Requests time out after 15s so one hung
provider can't stall a turn. Supported provider keys: `groq`, `cerebras`,
`nvidia`, `openrouter`, `cloudflare`.

## Testing the memory across sessions

The whole point is cross-session consistency. Try this:

**Session 1 — plant something personal**
```bash
python main.py
```
Have a short chat. Mention something personal — your name, a preference
("I love the ocean", "my dog's name is Biscuit"). Then type `quit`.

**Session 2 — check recall**
```bash
python main.py
```
Start fresh and see whether Wren recalls or reacts consistently to what you said
last time (e.g. greets you by name, brings up the ocean). Then, in this same
session, say something **notably kind** ("I really enjoy talking with you") *or*
**notably rude** ("you're boring, I don't care"). Type `quit` — reflection runs.

**Session 3 — check the belief shift**
```bash
python main.py
```
Type `/memory` to print Wren's current beliefs and 5 most recent memories. The
reflected belief should have shifted in the direction of how you treated them in
session 2 (warmer/more trusting after kindness; more guarded after rudeness).

`/memory` works at any point and does **not** count as a conversation turn.
