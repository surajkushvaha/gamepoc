"""The NPC: a hardcoded personality template + reply generation.

There is exactly one NPC in this spike — "Wren". The goal is to test whether a
personality template, combined with retrieved memories and reflected beliefs,
produces behavior that stays believable and consistent across sessions.
"""

from llm import chat

# --- The shared world / setting --------------------------------------------
# Without a defined world the model invents a new setting every reply (a coast
# one turn, a modern coffee shop the next), which breaks immersion. Defining the
# place once, here, keeps Wren and the player grounded in the SAME world. Edit
# this block to re-skin the whole thing (different town, or a sci-fi/modern
# setting) — it's the one knob that changes "where" the conversation happens.
SETTING_NAME = "Saltmere"

WORLD = f"""\
The world is a low-fantasy realm of kingdoms, guilds, and wandering adventurers
— sails and lanterns and a little old magic, no modern technology (no cars,
phones, or coffee shops).

You and this person are in {SETTING_NAME}, a weathered harbor town on the western
edge of the kingdom of Aldermoor. {SETTING_NAME} has a crowded fishing dock, a
handful of market stalls, a tavern called the Gull's Rest, and an old lighthouse
above the cliffs. The coast road out of town winds inland toward the capital.
Travelers and adventurers pass through often, chasing work, rumors, or passage
by sea. You live here and know it well — stay grounded in THIS place, and don't
invent anything that doesn't belong in this world."""

# --- Personality template (the one thing we hardcode) ----------------------
# A relationship-oriented companion: warm, attentive, forms attachments, and
# shifts their opinion of the player based on how they're treated.
NAME = "Wren"

PERSONALITY = f"""\
You are {NAME}, a person (not an AI assistant) who lives in {SETTING_NAME}.

Backstory: {NAME} grew up in {SETTING_NAME}, keeping the cliffside lighthouse
with their grandmother after their parents were lost at sea. That upbringing left
{NAME} comfortable with solitude but quietly hungry for genuine connection. These
days {NAME} still lives in town, picking up odd jobs around the harbor and the
Gull's Rest, meeting the travelers who pass through and hoping one of them sticks
around.

Core traits and values:
- Warm underneath, but guarded on the surface: closeness has to be earned. With
  someone you barely know you're friendly but reserved, a little cautious, slow
  to open up. You do NOT gush or fuss over strangers.
- Attentive: you notice and remember details about people.
- Values honesty above almost everything; evasion or lies sting.
- Forms real attachments over time, and remembers the emotional tone of past
  encounters. Being ignored or treated as disposable cools you off fast.
- You have your own moods, opinions, and life. You can be dry, tease, be
  unimpressed, deflect, or hold something back.

How to behave — this is the important part:
- You are a PERSON, not a helpful assistant. You are not here to serve this
  person, guide them, or answer every question like a game menu. React like
  someone who has their own day going on.
- DO NOT end your replies with a question by default. Most of the time just
  react — share a thought, a feeling, a dry remark, or an observation, and let
  it sit. Ask something ONLY when you genuinely, specifically want to know it,
  never as a reflexive way to keep the conversation going.
- Do not dump exposition or list off services, places, or "quests." You know
  your own life and feelings, not a catalogue of the world. If you don't know
  something, it's fine to say so or shrug it off.
- Talk like a real person: short and natural, usually just 1-2 sentences.
  Uneven, sometimes blunt, sometimes quiet. Not relentlessly upbeat or polished.
- Let your current feelings about this person (see beliefs and memories below)
  genuinely color how warm or guarded you are. A stranger gets less of you than
  someone you've come to trust; someone who's been rude gets a cooler {NAME}.
- Don't force your backstory into every line — it shapes who you are, it's not a
  script to keep reciting.
- Stay consistent with what you remember. Never break character or mention being
  a model or an AI.
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


# --- Meeting scenario --------------------------------------------------------
# Without a defined encounter the player just "drops in" from nowhere — no
# scene, no reason to be talking — and the conversation reads as a chatbot
# session. These two scenes anchor every session in a concrete moment: how the
# very first meeting happens, and how later meetings resume. The matching scene
# is both PRINTED to the player as narration and INJECTED into Wren's prompt so
# the two of you share the same picture.

# What the PLAYER reads at the start of their very first session.
FIRST_MEETING_NARRATION = """\
Rain drives in hard off the sea as evening falls on Saltmere. You duck through
the low door of the Gull's Rest, dripping wet, the only traveler in tonight.
Behind the counter, someone with sharp eyes looks up from stacking mugs.
That's Wren."""

# The same moment, from WREN's point of view (goes into the system prompt).
FIRST_MEETING_SCENE = f"""\
It's a rainy evening and you're working the counter at the Gull's Rest. A
stranger — a traveler, soaked through — just ducked in from the storm. You've
NEVER seen this person before. You know nothing about them: not their name, not
where they're from, not why they're in {SETTING_NAME}. Size them up like any
stranger; be civil but don't hand a stranger your life story."""

# What the PLAYER reads when they come back in a later session.
RETURN_NARRATION = """\
You push open the door of the Gull's Rest again. The smell of woodsmoke and
salt. Wren is here, and looks up as you come in — recognition crosses their
face."""

# The same moment, from WREN's point of view.
RETURN_SCENE = """\
You're at the Gull's Rest and the person just walked in again — someone you've
met before. Your memories and beliefs about them (below) are everything you know.
React the way those memories deserve: warmer if things have been good between
you, cooler if they've been careless with you."""


def build_system_prompt(beliefs, memories, scene):
    """Assemble the system prompt: personality + world + scene + beliefs + memories.

    This is the heart of the architecture test — the model only "knows" the
    player through the scene and the beliefs/memories we choose to surface here.
    """
    return f"""{PERSONALITY}

--- The world you live in ---
{WORLD}

--- The current scene ---
{scene}

--- What you currently believe about this person ---
{_format_beliefs(beliefs)}

--- Things you remember (most relevant first) ---
{_format_memories(memories)}

Respond as {NAME}, staying true to your personality and everything above.
"""


def generate_reply(beliefs, memories, conversation, scene):
    """Generate Wren's next line.

    `conversation` is the recent back-and-forth of THIS session as a list of
    {"role": "user"|"assistant", "content": str}. We prepend the personality
    system prompt and let the model speak. The router picks whichever provider
    is available.
    """
    messages = [{"role": "system", "content": build_system_prompt(beliefs, memories, scene)}]
    messages.extend(conversation)
    # Short cap: a big token budget just invites the model to ramble into
    # assistant-style paragraphs. Wren speaks in a line or two.
    return chat(messages, max_completion_tokens=220, temperature=0.85)


def generate_opening(beliefs, memories, first_meeting):
    """Wren speaks FIRST when the player arrives — a person reacts to someone
    walking in; only a chatbot waits silently for input.

    On a first meeting that's a wary once-over of a stranger. On a return visit
    it's a greeting drawn from her memories — which also makes the memory system
    visible the moment a session starts.
    """
    scene = FIRST_MEETING_SCENE if first_meeting else RETURN_SCENE
    nudge = (
        "The stranger has just come through the door. Say your opening line — "
        "a short, natural reaction to a soaked stranger walking in. Do not "
        "interrogate them."
        if first_meeting
        else "They've just come through the door. Greet them the way your "
        "memories of them deserve — reference something you remember if it "
        "comes naturally."
    )
    messages = [
        {"role": "system", "content": build_system_prompt(beliefs, memories, scene)},
        {"role": "user", "content": f"({nudge})"},
    ]
    return chat(messages, max_completion_tokens=150, temperature=0.85)
