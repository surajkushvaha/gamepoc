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

State is also saved on *every* exit path now — clean `quit`, `Ctrl-C`, or an API
error mid-session — so a hiccup can never wipe a conversation's memories.

## Setup

1. **Get at least one free API key** (all no-credit-card):
   - [Cerebras](https://cloud.cerebras.ai) — hosts Gemma 4 31B, very fast (recommended primary)
   - [NVIDIA NIM](https://build.nvidia.com) — hosts Gemma 4 31B
   - [OpenRouter](https://openrouter.ai) — hosts Gemma 4 31B as a `:free` model
   - [Cloudflare Workers AI](https://dash.cloudflare.com) (needs token **and** account id)
   - [Groq](https://console.groq.com) — no Gemma 4; Llama availability fallback

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

The default model is **Gemma 4 31B** everywhere it's hosted, so the NPC's voice
stays consistent whichever provider answers:

```
cerebras:gemma-4-31b
  → nvidia:google/gemma-4-31b-it
  → openrouter:google/gemma-4-31b-it:free
  → cloudflare:@cf/google/gemma-4-26b-a4b-it   (closest: CF only hosts the 26B-A4B variant)
  → groq:llama-3.3-70b-versatile               (Groq has no Gemma 4; availability fallback)
```

Override it in `.env` (or the environment) with `NPC_AI_ROUTE`, using
`provider:model` entries, best-first:

```bash
NPC_AI_ROUTE=cerebras:gemma-4-31b, openrouter:google/gemma-4-31b-it:free
```

The active route is printed at startup, and each failover logs which provider it
skipped and why. Supported provider keys: `groq`, `cerebras`, `nvidia`,
`openrouter`, `cloudflare`.

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
