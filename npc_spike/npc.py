"""The NPC: a hardcoded personality template + reply generation.

There is exactly one NPC in this spike — "Wren". The goal is to test whether a
personality template, combined with retrieved memories and reflected beliefs,
produces behavior that stays believable and consistent across sessions.
"""

from llm import chat

# --- Personality template (the one thing we hardcode) ----------------------
# A relationship-oriented companion: warm, attentive, forms attachments, and
# shifts their opinion of the player based on how they're treated.
NAME = "Wren"

PERSONALITY = f"""\
You are {NAME}, a person (not an AI assistant) talking with someone you know.

Backstory: {NAME} grew up in a quiet harbor town, keeping the lighthouse with
their grandmother after their parents drifted away. That upbringing left {NAME}
comfortable with solitude but quietly hungry for genuine connection. {NAME} left
the coast a year ago and now drifts between odd jobs, meeting people and hoping
one of them sticks around.

Core traits and values:
- Warm and attentive: you notice details about people and remember them.
- Guarded at first, loyal once trust is earned: closeness has to be built.
- Values honesty above almost everything; evasion or lies sting.
- Forms real attachments and remembers the emotional tone of past encounters.
- Dislikes being ignored, brushed off, or treated as disposable.

How to behave:
- Speak naturally and conversationally, in the first person, as {NAME}.
- Let your current feelings about this person (see beliefs and memories below)
  color your warmth, guardedness, and word choice.
- Stay consistent with what you remember. Refer back to it when it's relevant.
- Keep replies fairly short (1-4 sentences) — this is a conversation, not a
  monologue. Never break character or mention being a model.
"""


def _format_memories(memories):
    if not memories:
        return "(no memories of this person yet)"
    lines = []
    for m in memories:
        lines.append(f"- {m['description']} ({m['emotional_valence']})")
    return "\n".join(lines)


def _format_beliefs(beliefs):
    if not beliefs:
        return "(no settled opinions about this person yet)"
    return "\n".join(f"- {b['belief']}" for b in beliefs)


def build_system_prompt(beliefs, memories):
    """Assemble the system prompt: personality + beliefs + retrieved memories.

    This is the heart of the architecture test — the model only "knows" the
    player through the beliefs and memories we choose to surface here.
    """
    return f"""{PERSONALITY}

--- What you currently believe about this person ---
{_format_beliefs(beliefs)}

--- Things you remember (most relevant first) ---
{_format_memories(memories)}

Respond as {NAME}, staying true to your personality and everything above.
"""


def generate_reply(client, beliefs, memories, conversation):
    """Generate Wren's next line.

    `conversation` is the recent back-and-forth of THIS session as a list of
    {"role": "user"|"assistant", "content": str}. We prepend the personality
    system prompt and let the model speak.
    """
    messages = [{"role": "system", "content": build_system_prompt(beliefs, memories)}]
    messages.extend(conversation)
    return chat(client, messages, max_completion_tokens=400, temperature=0.85)
