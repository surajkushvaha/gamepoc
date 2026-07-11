"""CLI chat loop for the NPC memory + reflection spike.

Run:  python main.py
Talk to Wren, type /memory to inspect state, type quit to reflect + save + exit.

The four core-loop steps from the spec are marked STEP 1-4 below.
"""

from llm import describe_route, get_client
from memory import reflect, retrieve, summarize_turn
import random

from npc import (
    FIRST_MEETING_NARRATION,
    FIRST_MEETING_SCENE,
    NAME,
    RETURN_NARRATION,
    RETURN_NARRATION_HINT,
    RETURN_SCENE,
    SESSION_FLAVORS,
    generate_opening,
    generate_reply,
)
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


def chat_loop(state, session_memories, conversation, scene):
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
            npc_text = generate_reply(state["beliefs"], memories, conversation, scene)
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
            memory_entry = summarize_turn(player_text, npc_text)
            state["memories"].append(memory_entry)
            session_memories.append(memory_entry)
        except Exception as err:  # noqa: BLE001
            print(f"[(couldn't log that memory: {err})]\n")


def finish(state, session_memories):
    """STEP 4: reflect this session into beliefs, then ALWAYS save.

    This runs in main()'s finally block, so memories persist no matter how the
    session ended — clean quit, API crash, or Ctrl-C. Reflection is best-effort:
    if it fails we still save the raw memories we collected.
    """
    if session_memories:
        print(f"\n[{NAME} is reflecting on your conversation...]")
        try:
            state["beliefs"] = reflect(state["beliefs"], session_memories)
        except BaseException as err:  # noqa: BLE001 - never lose data over this
            print(f"[Reflection skipped ({err}); memories still saved.]")
    save_state(state)
    print(f"[Saved. {NAME} will remember this next time.] Goodbye.")


def main():
    # Validate at least one provider is configured (raises if none).
    get_client()

    # --- STEP 1: on startup, load persisted state (or start empty) ---------
    state = load_state()

    session_memories = []  # memories created THIS run; reflection operates on these
    conversation = []      # recent turns fed back into each reply

    mem_count, belief_count = len(state["memories"]), len(state["beliefs"])
    print(f"[Loaded {mem_count} memories, {belief_count} beliefs from previous sessions]")
    print(f"[AI providers (failover order): {', '.join(describe_route())}]")
    print("Type '/memory' to inspect, 'quit' to leave.\n")

    # --- Set the scene: how the player and Wren actually meet ---------------
    # First-ever session = the first meeting (a stranger out of the rain).
    # Any later session = a return visit on a randomly different moment of the
    # day, so revisits don't all start from the identical setup and converge
    # to the same dialog.
    first_meeting = mem_count == 0
    if first_meeting:
        scene = FIRST_MEETING_SCENE
        print(FIRST_MEETING_NARRATION)
    else:
        player_flavor, wren_flavor = random.choice(SESSION_FLAVORS)
        scene = f"{RETURN_SCENE}\nRight now: {wren_flavor}"
        print(f"{RETURN_NARRATION}\n{player_flavor}\n\n{RETURN_NARRATION_HINT}")
    print()

    # Wren reacts to you walking in — a person speaks first; only a chatbot
    # waits silently for input. On return visits this greeting is drawn from
    # her memories, so cross-session recall is visible immediately.
    try:
        opening = generate_opening(state["beliefs"], retrieve(state), first_meeting, scene)
        conversation.append({"role": "assistant", "content": opening})
        print(f"{NAME}> {opening}\n")
    except Exception as err:  # noqa: BLE001 - a failed opening isn't fatal
        print(f"[{NAME} glances up as you come in. ({err})]\n")

    # try/finally guarantees STEP 4 (reflect + save) runs even if the loop is
    # interrupted by Ctrl-C or an unrecoverable error mid-conversation.
    try:
        chat_loop(state, session_memories, conversation, scene)
    except KeyboardInterrupt:
        print("\n[Interrupted]")
    finally:
        finish(state, session_memories)


if __name__ == "__main__":
    main()
