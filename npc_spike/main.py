"""CLI chat loop for the NPC memory + reflection spike.

Run:  python main.py
Talk to Wren, type /memory to inspect state, type quit to reflect + save + exit.

The four core-loop steps from the spec are marked STEP 1-4 below.
"""

from llm import get_client
from memory import reflect, retrieve, summarize_turn
from npc import NAME, generate_reply
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


def main():
    client = get_client()

    # --- STEP 1: on startup, load persisted state (or start empty) ---------
    state = load_state()

    # Memories created during THIS run — reflection at the end operates on these.
    session_memories = []
    # Recent turns of the current conversation, fed back into each reply.
    conversation = []

    mem_count, belief_count = len(state["memories"]), len(state["beliefs"])
    print(f"[Loaded {mem_count} memories, {belief_count} beliefs from previous sessions]")
    print(f"You're talking with {NAME}. Type '/memory' to inspect, 'quit' to leave.\n")

    # --- STEP 2: the chat loop ---------------------------------------------
    while True:
        try:
            player_text = input("you> ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            player_text = "quit"

        if not player_text:
            continue

        # Exit path -> STEP 4 below.
        if player_text.lower() == "quit":
            break

        # Debug command: does NOT count as a conversation turn.
        if player_text == "/memory":
            print_debug(state)
            continue

        # STEP 2 (retrieve): surface a small, relevant slice of memory + beliefs.
        memories = retrieve(state)

        # STEP 2 (respond): build the prompt from personality + beliefs +
        # retrieved memories + recent conversation, then generate Wren's reply.
        conversation.append({"role": "user", "content": player_text})
        conversation[:] = conversation[-MAX_HISTORY_TURNS:]  # trim to stay lean
        npc_text = generate_reply(client, state["beliefs"], memories, conversation)
        conversation.append({"role": "assistant", "content": npc_text})
        conversation[:] = conversation[-MAX_HISTORY_TURNS:]
        print(f"{NAME}> {npc_text}\n")

        # STEP 3: log a new memory summarizing what just happened.
        memory_entry = summarize_turn(client, player_text, npc_text)
        state["memories"].append(memory_entry)
        session_memories.append(memory_entry)

    # --- STEP 4: on exit, reflect this session's memories into beliefs, save ---
    if session_memories:
        print(f"\n[{NAME} is reflecting on your conversation...]")
        state["beliefs"] = reflect(client, state["beliefs"], session_memories)

    save_state(state)
    print(f"[Saved. {NAME} will remember this next time.] Goodbye.")


if __name__ == "__main__":
    main()
