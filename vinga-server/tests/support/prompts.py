"""What a session's prompt looks like around its memory section, for the
suites that assert a whole system prompt.

Since #536 an agent that may remember is always sent a memory section,
opened by the framing sentence and, where nothing is saved, saying so.
These are the assembler's own constants joined the way it joins them,
so a suite states the prompt it expects without restating a rule the
assembler owns, and a wording change moves every suite with it.
"""

from vinga_server.runtime import prompt

# The framing sentence and the blank line after it, which opens the
# first block of the memory section when memory was read at the start
# of the conversation.
FRAMED = prompt.FRAMING_AT_START + prompt.JOIN

# The whole memory section of an agent that may remember and has
# nothing saved, read at the start.
EMPTY_SECTION = FRAMED + prompt.NOTHING_SAVED


def nothing_saved(half: str, *after: str) -> str:
    """The prompt of an agent that may remember with nothing saved: its
    know-how half, the empty memory section, and whatever follows the
    section (the device's introduction, where the record has one)."""
    return prompt.JOIN.join((half, EMPTY_SECTION, *after))
