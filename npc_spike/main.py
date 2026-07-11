"""CLI chat loop for the NPC memory + reflection spike.

Run:  python main.py
Talk to Wren, type /memory to inspect state, type quit to reflect + save + exit.

The four core-loop steps from the spec are marked STEP 1-4 below.
"""

from llm import get_client
from memory import reflect, retrieve, summarize_turn
from npc import NAME, SETTING_NAME, generate_reply
from storage import load_state, save_state

# Only keep the last few turns of the *current* conversation in the prompt.
# Long-term continuity comes from memories/beliefs, not raw history — this keeps
# us comfortably under the free-tier context cap.
MAX_HISTORY_TURNS = 6  # 6 messages ≈ 3 back-and-forth exchanges


def print_debug(state):
    """/memory command: dump current beliefs + 5 most recent memories."""
    print("\n" + "=" * 50)
    print("BELIEFS:")
    if state["beliefs"]:
        for b in state["beliefs"]:
            print(f"  - {b['belief']}")
    else:
        print("  (none yet)")

    print("\nRECENT MEMORIES (newest first):")
    recent = sorted(state["memories"], key=lambda m: m["timestamp"], reverse=True)[:5]
    if recent:
        for m in recent:
            print(f"  - [{m['importance']}] {m['description']} ({m['emotional_valence']})")
    else:
        print("  (none yet)")
    print("=" * 50 + "\n")


def chat_loop(client, state, session_memories, conversation):
    """The interactive loop. Returns when the player quits.

    A failed API call on a single turn is caught here so it doesn't kill the
    whole session (and lose everything unsaved) — we just report it and carry on.
    """
    while True:
        try:
            player_text = input("you> ").strip()
        except EOFError:  # Ctrl-D / piped input ending -> treat as quit
            print()
            return

        if not player_text:
            continue
        if player_text.lower() == "quit":
            return
        # Debug command: does NOT count as a conversation turn.
        if player_text == "/memory":
            print_debug(state)
            continue

        # STEP 2 (retrieve): surface a small, relevant slice of memory + beliefs.
        memories = retrieve(state)

        # STEP 2 (respond): build the prompt from personality + world + beliefs +
        # retrieved memories + recent conversation, then generate Wren's reply.
        conversation.append({"role": "user", "content": player_text})
        conversation[:] = conversation[-MAX_HISTORY_TURNS:]  # trim to stay lean
        try:
            npc_text = generate_reply(client, state["beliefs"], memories, conversation)
        except Exception as err:  # noqa: BLE001 - keep the session alive
            conversation.pop()  # drop the turn we couldn't answer
            print(f"[Couldn't reach {NAME} right now: {err}]\n")
            continue
        conversation.append({"role": "assistant", "content": npc_text})
        conversation[:] = conversation[-MAX_HISTORY_TURNS:]
        print(f"{NAME}> {npc_text}\n")

        # STEP 3: log a new memory summarizing what just happened. If this second
        # call fails, we keep the conversation going rather than dropping it.
        try:
            memory_entry = summarize_turn(client, player_text, npc_text)
            state["memories"].append(memory_entry)
            session_memories.append(memory_entry)
        except Exception as err:  # noqa: BLE001
            print(f"[(couldn't log that memory: {err})]\n")


def finish(client, state, session_memories):
    """STEP 4: reflect this session into beliefs, then ALWAYS save.

    This runs in main()'s finally block, so memories persist no matter how the
    session ended — clean quit, API crash, or Ctrl-C. Reflection is best-effort:
    if it fails we still save the raw memories we collected.
    """
    if session_memories:
        print(f"\n[{NAME} is reflecting on your conversation...]")
        try:
            state["beliefs"] = reflect(client, state["beliefs"], session_memories)
        except BaseException as err:  # noqa: BLE001 - never lose data over this
            print(f"[Reflection skipped ({err}); memories still saved.]")
    save_state(state)
    print(f"[Saved. {NAME} will remember this next time.] Goodbye.")


def main():
    client = get_client()

    # --- STEP 1: on startup, load persisted state (or start empty) ---------
    state = load_state()

    session_memories = []  # memories created THIS run; reflection operates on these
    conversation = []      # recent turns fed back into each reply

    mem_count, belief_count = len(state["memories"]), len(state["beliefs"])
    print(f"[Loaded {mem_count} memories, {belief_count} beliefs from previous sessions]")
    print(f"You're in {SETTING_NAME}, talking with {NAME}.")
    print("Type '/memory' to inspect, 'quit' to leave.\n")

    # try/finally guarantees STEP 4 (reflect + save) runs even if the loop is
    # interrupted by Ctrl-C or an unrecoverable error mid-conversation.
    try:
        chat_loop(client, state, session_memories, conversation)
    except KeyboardInterrupt:
        print("\n[Interrupted]")
    finally:
        finish(client, state, session_memories)


if __name__ == "__main__":
    main()
