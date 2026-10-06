# Composing what an agent is told

At the end of this guide you will be able to read the whole system
prompt an agent is sent, block by block with the size of each, and
share standing text between agents by writing it once.

The fields that make up the prompt are in the domain configuration
reference: an agent's `prompt` and `prompt_includes` under
[Agent](../reference/domain-config.md#agent), shared text under
[Prompt fragment](../reference/domain-config.md#prompt-fragment), and an
MCP entry's guidance under
[MCP server](../reference/domain-config.md#mcp-server). The preview
command is in the CLI reference under
[`vinga agent preview`](../reference/cli.md#vinga-agent-preview). What
an MCP entry's guidance is for is in
[Giving an agent tools](tools-and-mcp.md), and what memory contributes
in [Configuring what an agent remembers](memory.md).

## What the model is actually sent

An agent's system prompt is assembled from more than one place now, so
there is a command that says what it adds up to:

```console
$ vinga-server config agent preview house
persona (133 characters)
You are the assistant in the living room. Answer in the language you
were spoken to, and keep answers short: this is spoken out loud.

fragment:household (100 characters)
The bins go out on Tuesday evening, the kitchen speaker is called
Bosse, and the cat is called Ines.

instructions:home (210 characters)
Guidance for using the tools whose names begin with home__:
The lights, the blinds and the front door are on this server. Turn
lights on and off freely. Always ask the user to confirm before
unlocking the door.

server_instructions:home (172 characters)
What the server behind the home__ tools says about using them:
Device names are the ones set in Home Assistant. A scene is turned on
like a light, not called like a script.

memory (108 characters)
You remember these facts about past conversations:
- the user is vegetarian
- the user's dog is called Bosse

total: 731 characters
```

**The order is fixed and documented**, and deliberately not
configurable: the agent's own prompt first, because it says who is
speaking and everything after it is read in that voice; then the shared
fragments it includes, in the order its layer lists them, because they
are standing context the persona speaks within; then the guidance of
each MCP entry the agent is granted, in the order the grants name them,
each under its heading, and within one entry what the operator wrote
first and what the server itself ships after it; then what memory holds
last, which is up to three blocks in the order they take precedence in:
what this conversation is currently keeping, then the remembered facts
under the heading they have always had, then what is known about the
device. Each of those says its own rank in its heading, because the
model is the one reader that cannot see where a line came from, and a
scope holding nothing contributes no block at all. Blocks are
separated by blank lines. One
documented order beats a per-deployment permutation, and it is what lets
a later feature compose against a known base.

**A shared fragment is written once and included by name.** Household
facts, a house style, anything every agent in the deployment should
know: it goes into `prompt_fragments` under a name, and each agent that
should carry it names that fragment in its `prompt_includes`.

```bash
vinga-server config prompt-fragment set household -f examples/prompt-fragment.yaml
vinga-server config agent set house -f agent.yaml   # prompt_includes: [household]
```

The alternative is copying the same paragraph into every persona prompt
and watching the copies drift, which is what this exists to stop.
`prompt_includes` follows the `mcp` list's rules exactly: leaving it out
inherits the `agent_defaults` list, naming a list replaces the inherited
one rather than extending it, and `prompt_includes: []` opts one agent
out of what its siblings share. A name that matches no fragment is
refused when it is written, since the fragment is a row in the same
database. The text is injected as written, with no heading over it: it
is prompt text the operator composed, and a heading would editorialize.
Its indentation and its own blank lines are part of it, and the only
bytes trimmed are whitespace at the two ends of the whole prompt, which
the surface above reports trimmed with them. A fragment is one of the
kinds `vinga-server config apply` installs, so writing or editing one
reaches every agent that includes it at that agent's next activation,
and the write says so.

**Each block is counted** because every one of them competes with the
others for the context budget of a small local model, and there is no
automatic trimming: a server that silently dropped an instruction block
would be worse than one that says what it injected. The number to tune
against is the total, which is the sum of the blocks plus the blank line
between each pair of them: the prompt is the blocks joined and nothing
else, so a character counted here is a character the model receives.
The logs carry the same sizes in two halves. Agent activation logs a
[`prompt_assembled`](../reference/events.md#prompt_assembled) event
whose `sources` counts the persona, the fragments and the guidance, and
no memory, since memory is read separately. Every reply round's
[`llm_round`](../reference/events.md#llm_round) event carries the rest:
`system_characters` for the whole system prompt the round sent,
`memory_characters` and `memory_sources` for the memory blocks' sizes,
and `memory_facts` for which facts were in them. Between the two, a
model that degrades in the field can be diagnosed from the retained
logs without reproducing the session.

**It is a preview of a new session**, not a readback of a running one.
The persona, the fragments and the guidance are assembled when a
conversation starts
and again when it switches agents, and held for the life of that
activation. What memory holds is read once per activation too, at the
first reply on that conversation, and kept for every reply after it, so
a fact another live conversation stores, or an operator corrects, is
seen from this conversation's next activation (a new session, an agent
switch or a switch back) rather than its next reply. Three things make
the next reply read memory again: a fact erased outright, by
`vinga memory delete`, the API or a model's permanent `forget`; the
agent's `memory` section being switched on or off by an apply; and a
read that failed, which is never kept. What the conversation's own model writes reaches it at once, as
the tool result it already is. So this command
answers what a session opening now would be given, which is what an
operator auditing a configuration wants, and a conversation that
started before the last apply is holding the older text until it ends.

It shows the agent's own memory and no other scope, and that is the
same honesty: what a conversation is keeping and what is known about a
device belong to a session, and a preview that invented a device to
show its notes would be a second assembler pretending to be the first.
The block it shows is the one a reply gets, which is the newest of the
agent's facts rather than all of them; the rest are there, and `recall`
is what reaches them.

Over the API it is `GET /api/runtime/agents/{name}/prompt`, and it is a
read of the running server rather than of the database: the agents this
server is serving, the MCP slice it is running, and the memory it
writes. An agent it is not serving answers 404 naming the apply, since
that is what installs one.
