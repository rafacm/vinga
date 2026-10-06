# Recording conversations

At the end of this guide you will have decided whether a deployment
keeps what is said to it, and which half: the measured numbers, the
text, or both; for how long; whether an agent may find a past
conversation and carry on with it; and you will know how to erase one
on demand and how to read the record without touching the server's own
connection.

Every key named here, with its default and bounds, is in the server
configuration reference under
[`server.conversations`](../reference/server-config.md#serverconversations).
The erasure routes are in the
[OpenAPI document](../reference/api-openapi.json), and the commands in
front of them in the CLI reference under
[`vinga session`](../reference/cli.md#vinga-session) and
[`vinga conversation`](../reference/cli.md#vinga-conversation).

## The conversation store

**This keeps what was said in a database.** It is off by default and off
until `enabled` says otherwise, and a warning at startup says when it is
on. It names nothing further: which database a server records into is
its own configuration's answer, given once, rather than a line per
start, and a connection is not a thing a log line may carry.

```yaml
server:
  conversations:
    enabled: false
    # store the structured events and every measured number
    telemetry: true
    # store conversation text, and tool names, arguments and results
    text: true
    # prune conversations inactive for longer than this; 0 keeps
    # everything
    retention_days: 90
    # find and resume a past conversation by describing it out loud
    resumption: false
    # how much of a resumed conversation is rebuilt into the model's
    # context, in tokens
    resumption_budget_tokens: 6000
```

What lands is the `record` schema of the same database the
domain half's `domain` schema is in, which means the same instance, the
same credentials and the same backup: one row per session, one per
conversation, one per turn, one per tool call a turn made, one per recap
checkpoint, and one per structured event, which is the same decision track the capture writes
beside its audio. What each row holds, column by column, is the
generated [conversation store reference](../reference/conversations-schema.md),
and `vinga-server conversations schema` prints the same document. A
turn names both the session it was spoken in and the conversation it
belongs to, so the two are views of one set of rows rather than two
records: one session can touch several conversations, and one
conversation can span several sessions. Audio never enters it: the
capture is the recording, this is the queryable record.

The section's absence, and `enabled: false`, both mean the same thing:
no writer is started and no row is ever written. The tables are still
brought up to the current schema at every start, because empty tables
are not a recording and switching recording off does not make what was
already recorded unreadable.

The two switches under the flag are independent, and all four
combinations are supported configurations:

| `telemetry` | `text` | What a session keeps |
| --- | --- | --- |
| on | on | everything: the events, every measured number, and what was said |
| on | off | the events and the numbers; the text columns, tool names, arguments and results are null |
| off | on | what was said, with no events rows and the numbers null: the transparency-first setting |
| off | off | the session spine and the shape of each turn, and nothing else |

Session and conversation rows land in every enabled configuration,
because retention and every read key on them, and their timestamps
survive both switches for the same reason. A conversation's title is
the exception and is content, because it is what somebody said: with
`text: false` a thread has no title. Each session row also records which way the switches
were set for it, so a null column is distinguishable from a column that
was never stored.

## Resuming a past conversation

**`resumption` is the third switch and the only one that is not about
storage.** It decides whether an agent can find one of its own past
conversations and carry on with it, and it is off by default, because
recording a conversation and reading it back to a model are separate
decisions. It reads what the other two wrote, so a configuration that
asks for it with `enabled` or `text` off is refused at boot in a
sentence naming both keys and both ways out. What it changes, once on:
the two
[conversation tools](tools-and-mcp.md) stop refusing, and picking a
conversation rebuilds the model's context from the stored dialogue,
newest turns first, up to `resumption_budget_tokens`. That budget is
approximate by design (the count is estimated from the stored
characters), what it drops when a thread is longer than it are whole
turns oldest first, and a thread rebuilt from its tail is told so, as
is one whose record has holes in it. A turn's tool calls are rebuilt as
the session kept them, each with its arguments and its result, so a
rebuilt conversation carries what was said and what its tools were
asked and answered; a call that never got a result does not come back.

A thread longer than that budget is not silently trimmed. The tool
answers with the choice instead, for the agent to put to the user: a
short recap of the whole of it, or carrying on from the recent part.
Carrying on from the recent part is the paragraph above and stores
nothing. A recap is the agent summarizing the thread once, against its
own model, and speaking that summary out loud; only when the user has
heard it to the end is it stored, as a checkpoint on the conversation,
and every later resume is rebuilt from that checkpoint plus what was
said after it. A recap cut off by an interruption, a voice that failed
or a device that went away is not stored at all, and the next resume
offers the same choice again; so is one the model could not produce,
and the thread is picked up from its recent part with the agent told
why. Recap text is conversation content like the dialogue it
summarizes: it lives under the `text` switch, is served by the API, and
is retained and deleted with its thread.

Off, nothing about a conversation's behaviour changes at all: an
agent's working context is assembled inside one session and ends when
the session closes, which is what this server always did.

## Who it records

**The switches are deployment-wide, and beside erasing on demand they
are the only privacy control vinga has.** There are no per-user
controls, so enabling text
storage on a device a household shares stores what guests say to it,
which is the same statement
[Capturing a session](capturing-a-session.md) makes about audio.
Attributing a session on a shared device to one member needs voiceprint
identification, which vinga does not do, so the units deletion is
expressed in are the conversation and the session: the first is what
retention takes whole, and both are what the erasure API addresses.
Erasing either on demand is an act of the API with a CLI verb in
front of it, which the deletion section below says in full. The session id is surfaced everywhere regardless: on the
events, on the capture triplet's filenames, and on every row the store
keeps.

## How long it is kept

Retention is 90 days by default, and what the window is measured
against is a conversation's last activity, because the conversation is
the unit this store retains. A thread inactive for longer than the
window is deleted whole, with its turns; the events of a session older
than the window go on the session's own age, whether or not its row
survives; and a session row goes once no turn names it any more, so a
session that began before the cutoff while its thread is still being
talked to keeps the row those turns cross-reference. The pass runs at
startup and at each session close, and a line says how many
conversations and how many session records went. `retention_days: 0`
keeps everything, which is a deliberate choice rather than a default,
because a store with no policy retains forever. In a deployment that
never resumes a conversation this is the behaviour it always had: a
thread never spans sessions there, so its age and its session's
coincide.

## Deleting on demand

**Deleting on demand is an act of the API.** `DELETE
/api/sessions/{session}` erases one named session; `DELETE
/api/sessions` with at least one of `?session=`, `?device=` and
`?before=` (combined with AND, the day strict) is the purge, answering
how many of everything it took; `DELETE
/api/conversations/{conversation}` erases one named thread out of
every session it touched, leaving session rows and events alone. In
front of them stand `vinga session delete`, `vinga session purge` and
`vinga conversation delete`, each confirming at a terminal and taking
`--force`. Erasure outranks every copy the store derived, not only the
rows named: a thread whose title came from an erased turn is renamed
from its earliest surviving turn or loses its title, recap checkpoints
that summarized an erased turn go along with everything descended from
them, the activity stamp falls back to what the survivors support, and
a thread left with no turns is deleted whole, because a title and two
timestamps are not a conversation. A thread that goes, by erasure or by
retention, takes its memory with it in the same transaction, the
conversation's ledger and the facts it forgot, and an erasure's answer
counts those too.

A session that is still running when its row goes stops being
recorded: the writer finds the row gone and stops writing for that
session, so what is said afterwards is not recorded. Capture files are a
separate instrument and are never touched by any of this; the session id
is the correlation key for whoever needs to remove the matching triplet.

What deletion means is worth stating exactly, because the database
server decides it rather than this one. A deleted row is invisible to
every transaction that begins after the deletion commits, the
read-only `vinga_ro` role's included. A repeatable-read transaction
that was already in flight when it committed keeps seeing the row
until that transaction ends, which is what multi-version concurrency
is and not something this server can prevent: a query left open in a
terminal is one such transaction. Reclaiming the space the row
occupied is the instance's own storage maintenance (autovacuum), not a
per-delete overwrite, so the interval between the delete and the
reclamation is yours to tune rather than this server's to promise.
There is no write-ahead log to truncate here and no sidecar file to
take with it, and copies that have already left the database (a
`pg_dump`, a filesystem snapshot, a replica) are yours to manage.

## Reading it

**Read it live, as `vinga_ro`.** There is nothing to copy first, and
nothing to copy safely: the store is SQL, and the way in is a
read-only session as the role
[`deploy/postgres-init.sql`](../../deploy/postgres-init.sql)
provisions, which
[Reading what was said](database.md#reading-what-was-said) shows, with
the role's password and the timeouts it carries. It has `SELECT` on
every table in the `record` schema, now and after the next migration,
and nothing at all on the two schemas beside it: `domain`, where the
stored secrets' ciphertexts live, and `memory`, whose read surface is
the addressed API under
[`vinga memory`](memory.md#reading-and-correcting-what-it-kept)
rather than raw tables. A database provisioned without that file
simply has no analyst role, and serves exactly the same.

Beside raw SQL, `vinga metric` reads the named aggregate views over the
record (served at `/api/metrics`), and `vinga session` and
`vinga conversation` list and show single sessions and threads. The ids
on `sessions`, `conversations`, `turns` and `events` are identity
columns a sequence never hands out twice, so a client that has read up
to one can ask for what came after it and cannot be handed a different
row under the same number.

## How it is written

Writing never happens on the conversation's path. One background thread
does every database call behind a queue nothing on the session loop ever
waits on, and it commits at turn boundaries and at session close, so a
page opened mid conversation reads everything up to the last completed
turn. A database that is wedged or locked drops events, says so once per
session, and records the count on the session row (where `telemetry` is
on; with it off the count stays zero), and it never delays a reply.

Turns and closes are never refused at the queue, whatever the backlog:
they are the record's structural truth and they arrive at conversational
pace. That is not a promise that every turn or close lands. A turn
whose write still fails after three attempts is dropped, and its thread
is marked incomplete rather than silently short. A close whose own
transaction fails leaves the session row open-shaped, with a null
`closed_at` and no close reason, which is the same incomplete state a
process killed mid-session leaves behind: it is readable, it is listed,
and retention prunes it on `started_at` like any other. A line at
warning level says so when it happens.
