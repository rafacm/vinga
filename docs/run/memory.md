# Configuring what an agent remembers

At the end of this guide you will know what an agent keeps between
conversations and within one, how to read and correct what it has
kept, where what it keeps is stored and which providers it is sent to,
and how to switch remembering off for one agent or for all of them.

Whether an agent remembers is its `memory` section, in the domain
configuration reference under
[Memory](../reference/domain-config.md#memory). The commands that read
and correct what it kept are in the CLI reference under
[`vinga memory`](../reference/cli.md#vinga-memory). The other tools
an agent is offered, builtins included, are in
[Giving an agent tools](tools-and-mcp.md).

## What an agent keeps

`remember` keeps one fact, and says which memory it belongs in. Left
alone it is the agent's own, keyed by the agent and not by the device,
because an agent is one entity across rooms: what the kitchen told it
holds in the bedroom. Called with `scope: device` it is the board's,
shared by every agent bound to that board, which is where the room, the
household and the hardware's own quirks belong; what is true of a person
stays with the agent. The scope is steered by the tool's description
rather than enforced, so an assistant that files something in the wrong
place has written a true fact you can move, and the two memories are
separate in every direction: neither is read into the other's block.

The facts live in the `memory` schema of the database this server
already keeps its other two stores in, one row per fact. An agent's
scope holds up to 1000 facts in 64 KiB and a device's up to 30 in 2 KiB,
oldest dropped first, and one fact too long to fit inside its own
scope's budget is refused rather than stored. The insert and the pruning
happen in one transaction under the schema's own writer lock, so two
conversations talking to the same agent at once cannot lose each other's
fact and no reply ever reads a memory that is over its cap. There is
nothing to switch on: the schema is migrated at every boot the way the
record's is, and an agent that may remember and has been told nothing
is sent a short memory block saying nothing is saved yet, under the
same framing sentence a full one carries. There is something to switch off, and it is an agent's own
`memory` section, below.

**An agent that is dictated to wants its own endpointer.** Telling an
agent things to remember is slower speech than asking it a question,
and the pauses between clauses run past the 700 ms silence that ends a
turn by default, so the agent answers half a sentence and the rest
arrives as an interruption. The bound is per VAD entry and an agent
binds its own, so give that agent a patient entry rather than slowing
every agent down: see
[Listening and barge-in](../../vinga-server/README.md#listening-and-barge-in).

**The prompt carries the newest of an agent's facts, not all of them.**
A scope of a thousand facts does not fit in front of a small local
model, so the block is the newest 40 lines within 4 KiB and everything
else is reached with `recall`. A device's notes and the conversation's
ledger are small enough to inject whole.

`recall` looks the facts up: a case-insensitive match on the words
themselves over everything the agent and its device hold, injected or
not, newest first, bounded at 20 lines within 2 KiB with a fixed
sentence when more matched than fits. It is also where the numbers come
from. Every remembered fact has one, `remember` answers with it, the
injected block never shows one, and the number is what the two tools
that change a fact address:

- `update_memory` replaces one fact's words, keeping its number;
- `forget` removes one and answers with the words it removed, which the
  assistant is asked to say out loud so you can ask for it back;
  `restore_memory` brings back the last thing forgotten in the
  conversation, or a named one. A removal is held rather than erased
  for as long as the conversation it was made in is kept, which on a
  deployment that stores no conversations is until the session closes,
  and `permanently: true` erases outright with nothing to bring back.

An assistant reaches its own facts and its device's, and nothing else:
every numbered operation is bounded by ownership in the query itself, so
a number belonging to another agent is answered exactly as a number
belonging to nobody, in one sentence that confirms neither.

`set_state` and `clear_state` keep the other kind: a small ledger of
what is currently true in the conversation happening now, under names
the model chooses, where writing the same name again replaces what it
held. It is what a game's scene and hit points, a board position, or
the step of something in progress belong in, and it is injected as its
own block above the remembered facts, because what is current outranks
what was remembered. It is capped at 4 KiB or 50 entries, and a write
past either is refused with a sentence rather than trimmed silently: a
ledger that dropped entries is a ledger the model cannot trust.

The ledger is keyed by the conversation, not by the connection, so it
survives a device hanging up and comes back when that conversation is
resumed. It is deleted in the same transaction as the thread it belongs
to, whether that thread goes because it was erased through the API or
because retention pruned it, and an erasure through the API answers
how much of it went. On a deployment that does not store conversation text a thread
cannot be resumed at all, so every conversation there begins with an
empty ledger and anything worth keeping has to be remembered instead.

## Reading and correcting what it kept

**What has accrued is an operator's to see, and to correct.** Nothing
but this server reads the `memory` schema, so the surface is an
addressed API under `/api/memory` rather than SQL, with `vinga memory`
in front of it. Three questions, in the order they get asked:

```bash
vinga memory list agent                  # who is remembering anything, and how much
vinga memory list agent poet             # what one of them holds, with each fact's number
vinga memory list device aa:bb:cc:dd:ee:ff
vinga memory list conversation <thread>  # what one conversation is currently keeping
```

Correcting one fact reads the corrected text from a file or from
standard input and never from an argument, because what is being
written is something somebody said in a room and arguments land in
shell history and in the process list:

```bash
# Write the corrected fact in an editor, then hand the file over: on
# -f, or on standard input. Nothing of it is on a command line.
"${EDITOR:-vi}" corrected.txt
vinga memory set agent poet 7 -f corrected.txt
vinga memory set agent poet 7 < corrected.txt
```

And removing is `vinga memory delete`, which asks before it acts:
`vinga memory delete agent poet 7` for one fact, `--all` for the whole
of one memory, and `vinga memory delete conversation <thread>` reading
the name of one ledger entry from standard input, or `--all` for the
ledger. Every deletion through this door is permanent: the soft
forgetting an agent does belongs to the conversation that spoke it, and
this door is correction and audit rather than that flow.

The listings answer owners nothing is configured under, which is the
point of them rather than an oversight: deleting an agent leaves what it
remembered behind, deleting a device record leaves that board's notes
behind, and a rename leaves whatever a conversation still speaking the
old name wrote before an apply caught up. `--all` is how those rows
leave. Replacing a board is not one of them: a swap moves the device's
notes to the new address in the same transaction, so nothing is left
under the old one.

## Where what it keeps goes

**Memory is stored on the host and read out to the model.** What an
agent remembers, what a device's notes hold and what a conversation is
keeping never leave this deployment as storage: they are rows in the
database it already owns, they travel in the same `pg_dump` as
everything else, and no other server is told about them. But they are
read when an agent starts speaking in a conversation and carried in the
system prompt of every reply after that, and `recall` answers a
model with more of them on demand, which makes them prompt content: they
follow the active LLM provider's reach like the transcript and the
persona do, so an agent on a cloud model sends what it remembered along
with what was just said. The device scope is worth stating on its own: a
note about the room or the household is shared by every agent bound to
that board that may remember, so it reaches every one of their providers
rather than only the provider of the agent that was told it. An agent
whose `memory` section is off is read none of it and sends none of it,
which is the one lever that narrows this. `server.data_boundary` is the
guard, and it is the same guard: a provider whose reach exceeds the
declared boundary cannot be booted, and memory rides the boundary that
draws.

## Switching it off

**Whether an agent remembers at all is one line of its
configuration.** No builtin is granted the way an MCP server is, and
none needs to be: each of them is either structural or a policy of its
own, and the two are different things.

`switch_agent`'s condition is the device's: it exists exactly when the
board is bound to more than one agent, and withholding it from one of
them would strand a conversation on whichever agent has no way back,
which is the receptionist handoff the tool was written for. The two
conversation tools have no condition, for a reason of their own: a tool
that is simply absent is a tool a model invents, so they are offered
wherever a conversation is and a server that cannot resume anything
says so in a sentence the agent reads out.

The seven memory tools have a policy, which is the `memory` section of
the agent, or of `agent_defaults` for every agent that names none. On
unless it says otherwise, so a deployment that writes nothing has the
memory every agent has always had; off is one field:

```yaml
memory:
  enabled: false
```

Off is the whole family at once, tools and injection together, because
they are one feature seen from two sides: an agent with `remember`
withheld and the block still injected would recall for ever and never
learn, one with the state tools withheld would be read a ledger it had
no way to write, and one with the numbered three withheld could not
correct or take back anything it had been told. So a switched-off agent
is offered none of the seven and is sent none of the blocks, including
the notes its siblings on the same board keep: it can neither write
what the room knows nor read it. Asking for a tool it was not offered
is answered as any name this server does not publish is.

Nothing already stored is deleted by it. The rows stay under the
agent's name, `vinga memory list agent poet` still shows them, and
switching the section back on is an agent that remembers what it
remembered before; `vinga memory delete` is the door that takes rows
away. An apply installs the change at that agent's next utterance, and
one reply never gets half of it: which tools it is offered and what its
prompt carries are decided together, once, at the top of the reply.
