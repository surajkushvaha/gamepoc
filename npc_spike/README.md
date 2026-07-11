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
  llm.py       # Cerebras client wrapper + rate-limit backoff
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

## Setup

1. **Get a free Cerebras API key** (no credit card): sign up at
   [cloud.cerebras.ai](https://cloud.cerebras.ai), generate a key.

2. **Install the dependency** (Python 3.10+):
   ```bash
   cd npc_spike
   pip install -r requirements.txt
   ```

3. **Set your key:**
   ```bash
   export CEREBRAS_API_KEY=your_key_here
   ```

### Model choice

The spec suggested `llama-3.3-70b`, but Cerebras **deprecated that model in Feb
2026**. This spike defaults to **`gpt-oss-120b`** — Cerebras' own recommended
replacement, open-weight (Apache 2.0) and available on the free tier. It's held
in an env var so it's trivial to swap when the catalog changes again (check the
[current catalog](https://inference-docs.cerebras.ai/models/overview)):

```bash
export CEREBRAS_MODEL=some-other-model-id   # optional override
```

### Free-tier notes

Roughly 1M tokens/day, 30 requests/minute, ~8k-token context. Each player turn
makes 2 API calls (reply + memory summary), and `quit` makes 1 more (reflect).
If you hit the rate limit, `llm.py` retries with exponential backoff (2/4/8/16s)
instead of crashing.

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
