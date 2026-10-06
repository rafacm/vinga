# vinga-server

The Vinga conversation server (Python): a wire-compatible backend for
[78/xiaozhi-esp32](https://github.com/78/xiaozhi-esp32) devices, written
against the firmware's
[protocol docs](https://github.com/78/xiaozhi-esp32/blob/main/docs/websocket.md);
the device-token scheme follows
[xinnan-tech/xiaozhi-esp32-server](https://github.com/xinnan-tech/xiaozhi-esp32-server).

It implements the two endpoints a device needs:

- **HTTP OTA/config endpoint** (`/xiaozhi/ota/`): the device POSTs its
  identity and receives the WebSocket URL (and optionally firmware updates).
- **WebSocket endpoint** (`/xiaozhi/v1/`): the conversation channel,
  carrying Opus audio frames up, JSON control messages both ways, and Opus
  audio back.

Behind the WebSocket sits the conversation pipeline: VAD segments speech,
ASR transcribes it, the LLM streams a reply, and TTS speaks it back
sentence by sentence, every stage a pluggable provider chosen per agent.
Agents reach tools over MCP, both their own servers and the device's own
controls.

Those four acronyms are the vocabulary of the whole configuration, so in
full:

| Stage | | What it does |
| ----- | - | ------------ |
| `vad` | voice activity detection | Decides where speech starts and when the user has stopped, so the rest of the pipeline runs on an utterance rather than on a stream |
| `asr` | automatic speech recognition | Turns that utterance into text. Also called speech to text |
| `llm` | large language model | Writes the reply, and asks for tools |
| `tts` | text to speech | Turns each sentence of the reply back into audio |

They run strictly in that order, each waiting on the one before it, which
is why the latency of any one of them is latency the user hears.

Those two paths, the two probes `/healthz` and `/readyz`, and the
configuration API under `/api` are
everything the server exposes: the interactive API docs are turned off,
the WebSocket requires a device token the OTA endpoint issued, and every
request to `/api` carries a bearer token.

## On this page

- [Goals](#goals): what this server is for, and what it refuses to become.
- [Developing it](#developing-it): a pointer to the contributing page, which covers what it is built on and the lanes a change is exercised in before it ships.
- [Capturing a session](#capturing-a-session): how to record a conversation for study.
- [What a conversation cost](#what-a-conversation-cost): the usage each stage reports, and the model definitions a backend needs before it can price them.
- [The conversation store](#the-conversation-store): what is kept of a turn after it ends.
- [Running in a container](#running-in-a-container): a pointer to the task guides in [`docs/run/`](../docs/run/README.md), which cover the image, its database, its limits and exposure, configuring it and its configuration API, securing it, upgrading, recovery, onboarding a device, and choosing the providers, tools, memory and prompt an agent works with.
- [Status](#status): what works today, and what is still a promise.

## Goals

- Python, and one Postgres database holding everything this server
  stores: the domain half of the configuration in a `domain` schema,
  and the conversation record, when it is turned on, in a
  `record` schema beside it. Both are migrated at every boot,
  so a blank database is a valid state to start on and there is no
  init command to forget
- Configurable providers:
  - **LLM**: Anthropic, any OpenAI-compatible endpoint (Ollama, LM Studio,
    gateways)
  - **ASR**: local (faster-whisper) or cloud (OpenAI, and anything
    speaking the same dialect)
  - **TTS**: pluggable engines as optional extras (Piper)
  - **MCP**: attach any MCP servers as tools for the assistant, alongside
    the device's own
- Distributed as a multi-arch container image, deployable on your own
  infrastructure

## Developing it

[Contributing to vinga](../docs/contributing.md) is how to run this
server from source, what it is built on, and the four lanes a change is
exercised in before it ships.

## Capturing a session

**This records room audio to disk.** It is off by default and off until
`enabled` says otherwise, and a warning at startup plus one line per
recorded session say when it is on. Turn it off again once the
recording has been taken.

```yaml
server:
  capture:
    enabled: false
    dir: /data/captures
    # stop capturing a session after this long
    max_session_s: 900
    # budget for the directory, oldest captures pruned first
    max_total_mb: 2000
    # refuse to start a capture below this much free space
    min_free_mb: 1000
```

The flag is the switch, rather than the presence of the section, so
turning capture off again does not mean deleting the directory and the
budgets along with it: the field workflow is to record, then stop, and
the tuning is worth keeping across that. `dir` is required even while
disabled, so switching on is one word rather than one word and
remembering where it writes. A section that is present but off says so
once at startup, because a configured capture that records nothing is
otherwise a silence to debug.

Because it is one flag, the env layer can do the flip on its own:
`VINGA_SERVER__CAPTURE__ENABLED=true` turns it on for one run without
editing the config the deployment mounts, and dropping the variable
turns it off again. That is usually the least disruptive way to take a
field recording.

It exists because acoustic problems cannot be reproduced in any test
lane. The unit lane feeds synthetic frames and the integration lane
drives a simulator, and both bypass the microphone, the board's echo
cancellation, and the room. Whether a reply interrupts itself turns on
how much of the assistant's own voice survives the board's cancellation
and reaches the endpointer, and no test can tell you that number.

Three files per session, sharing one timeline:

| File | What it holds |
| --- | --- |
| `<session>.wav` | Stereo 16 kHz s16le. Channel 0 is the microphone as decoded, channel 1 is what was paced out to the speaker. |
| `<session>.jsonl` | Every structured event, plus a `t_ms` offset into the audio, plus dropped frames per second and the endpointer's opinion per frame. |
| `<session>.json` | What the capture was made against: server revision, the firmware the device reported, the resolved providers verbatim, and the barge-in thresholds. |

Stereo rather than two files is the whole point: sample N in both
channels is the same instant, so echo leakage is a measurement (cross
correlate the channels and read off gain and delay) rather than a
guess, and the overlap is directly audible in any audio editor. A
channel that goes quiet is filled with silence rather than compressed,
so nothing slides against the events.

The microphone is captured before the session's own guards, so the
frames a configuration discards (not listening, or `barge_in: false`
during a reply) are in the file anyway. Those are the frames that
explain a misfire.

Storage is 64 kB/s, so a fifteen minute session is about 58 MB and the
2000 MB budget is around nine hours. Both bounds matter: the model
caches share the volume and grow underneath the budget, so capture
declines to start and says why rather than being the thing that fills
the disk.

A capture cut off by a restart stays readable. The WAV header carries
byte counts that are only patched on a clean close, so a truncated file
claims zero length, but everything after the 44 byte header is raw
interleaved PCM and the manifest's `complete: false` says the length has
to come from the file size. Both files are flushed as they are written,
so what is lost is at most the last fraction of a second.

In the field: turn it on, hold sessions in the conditions that actually
break things, and say a marker phrase aloud when something goes wrong.
It is on the WAV, and the `heard` event beside it in the decision track
points at the interesting twenty seconds instead of ten minutes of
scrubbing; with the conversation store on and `text: true`, the phrase
itself is one query away, since both records carry the same session id. Copy the three files off
after each session; a field recording is not repeatable.

## What a conversation cost

Every stage of a turn says what it was given, on its own span, in the
unit that stage is actually billed in:

| Stage | Span | What it reports |
| --- | --- | --- |
| Transcription | `asr` | `gen_ai.usage.input_milliseconds`, how much audio the ear was actually sent |
| Generation | `llm` | `gen_ai.usage.input_tokens` and `gen_ai.usage.output_tokens`, as the endpoint reported them, and `gen_ai.usage.cache_read.input_tokens` where the endpoint reported what its prompt cache served |
| Synthesis | `tts_stream` | `gen_ai.usage.input_characters`, the length of the sentence the voice was handed |

The milliseconds and the characters are both INPUT, read from the
model's side the way the OpenTelemetry GenAI conventions read the token
halves: an ear is given the audio and produces a transcript, a voice is
given the sentence and produces the audio. Those conventions name token
counts and nothing else, so the two units they have no word for state
that unit in the attribute name rather than being reported as tokens
they are not. Every value is a whole number, because a backend drops a
usage value that is not.

The cached count is part of the input count, never beside it: of the
`gen_ai.usage.input_tokens` a round reports, that many were served from
the provider's prompt cache. A backend that knows the key takes it out
of the input and prices it at the model's cached rate, which is
usually a fraction of the full one, so the round's cost is what the
provider actually charged rather than an upper bound on it. An endpoint
that does not say what it cached reports no cached count at all, rather
than a zero that would claim nothing was.

**The transcription number is what was SENT, not how long you spoke.**
The two come apart in both directions on a real endpoint: a clip under
the endpoint's own minimum is never sent at all and reports zero, and a
clip a prompt-echo retry has to send a second time reports twice its
length. How long the user spoke is a different question and stays where
it was, on `vinga.asr.duration_s`. An engine that cannot say what it
submitted, which is every local one, reports no usage rather than a
zero: an unmeasured call and a free call are different facts, and only
the second is worth nothing.

Usage is not a cost. A backend turns one into the other with a model
definition, which is a match pattern, a unit and a price per unit, and
**those are yours to enter.** This server never writes one. It holds no
admin credential for your backend, the OTLP path carries none, and a
deployment that provisioned prices at boot would be mutating a
third-party system on the strength of telemetry credentials, which is a
larger claim on your infrastructure than anything else here makes.

### The generation stage usually needs nothing

A backend ships managed definitions for well-known vendor models, so
the `llm` stage is normally priced the moment its spans arrive. On the
project this section was written against, `gpt-4o-mini` came back with
`costDetails` filled in from input and output token counts with no
definition entered by hand at all.

To check yours, hold one conversation with telemetry on, open the `llm`
observation of any turn, and look at whether it has a cost beside its
token counts. If it has, there is nothing to do for this stage, and a
definition of your own would only shadow one the backend maintains.

If it has not, the model is one the backend does not know: a
self-hosted model, a model behind a compatible endpoint, or a vendor
model under a name your deployment renamed. Then it needs a definition
like the ones below, with one difference: a generation reports tokens
in BOTH directions, so it takes `inputPrice` and `outputPrice` rather
than an input rate alone, `unit` is `TOKENS`, and the two rates are
whatever that model's own published price list says per token. This
page does not name them, because a price nobody has read is not a price.

### The definitions worth entering

These are the stages a backend has no managed definition for, because
the units are vinga's own. Prices as published on <https://developers.openai.com/api/docs/pricing>,
read 2026-09-12. A price is a fact with an as-of date; re-read it before
trusting a cost report made long after this one.

| Model | Match pattern | Unit | Input price | Published as |
| --- | --- | --- | --- | --- |
| `gpt-transcribe` | `(?i)^(gpt-transcribe)$` | `MILLISECONDS` | `0.000000075` | $0.0045 per minute |
| `whisper-1` | `(?i)^(whisper-1)$` | `MILLISECONDS` | `0.0000001` | $0.006 per minute |
| `tts-1` | `(?i)^(tts-1)$` | `CHARACTERS` | `0.000015` | $15.00 per 1M characters |
| `tts-1-hd` | `(?i)^(tts-1-hd)$` | `CHARACTERS` | `0.00003` | $30.00 per 1M characters |

The price column is the published one converted into the unit the span
reports, and nothing else: 0.0045 per minute is 0.000000075 per
millisecond, 15.00 per million characters is 0.000015 per character. An
exact conversion of a list price is still that list price. An estimate
is not, which is why the models below get no definition at all.

Milliseconds rather than seconds for the two speech models, because a
usage value has to be a whole number and whole seconds are too coarse
for what a voice assistant actually hears: rounding a 0.4 second "ja"
up to one second would overcharge it by 150%.

The match pattern is what the backend compares the span's
`gen_ai.request.model` against, and that value is whatever your provider
entry names as its model, so a definition only ever fires for a
deployment that configured that model.

### Entering one

Against a Langfuse backend, a model definition is a `POST` to
`/api/public/models` authenticated with the project's own key pair:

```bash
# The same three variables the recording upload already reads, and the
# same rule: they live in the environment, never in a configuration
# file, and this server never prints them back.
curl -sS -X POST "$LANGFUSE_HOST/api/public/models" \
  -u "$LANGFUSE_PUBLIC_KEY:$LANGFUSE_SECRET_KEY" \
  -H 'content-type: application/json' \
  -d '{
        "modelName": "tts-1",
        "matchPattern": "(?i)^(tts-1)$",
        "unit": "CHARACTERS",
        "inputPrice": 0.000015
      }'
```

One request per row of the table above. The backend's own settings page
does exactly the same thing through a form, which is usually the easier
way to enter four of them and to see what a project already has; the
request is here because a deployment that is rebuilt from files wants
the four in a file.

`unit` is a closed set (`TOKENS`, `CHARACTERS`, `MILLISECONDS`,
`SECONDS`, `REQUESTS`, `IMAGES`) and the price keys are `inputPrice`,
`outputPrice` and `totalPrice`. Both halves are why vinga reports its
seconds and characters as INPUT: a usage number under any other key has
no price beside it, however carefully it was measured.

### With none of them entered

Usage is present on every span, and every cost the backend cannot price
on its own reads zero. That is correct rather than broken: the server
measured what it was given and the backend was never told what a
millisecond of audio is worth. Enter the definitions before the run
whose cost you want to read, because whether a backend goes back and
prices traces it has already taken in is that backend's own behaviour
and not something this server can promise on its behalf.

### The models that deliberately get none

An estimate entered as a price is worse than an empty column, because it
is a number a report adds up.

- **`gpt-4o-transcribe` and `gpt-4o-mini-transcribe`** are billed per
  audio token ($2.50 and $1.25 per 1M input tokens). The `asr` span
  carries milliseconds, and converting would take a tokens-per-second
  assumption. Their transcriptions show usage and no cost.
- **`gpt-4o-mini-tts`** is billed per audio output token ($12.00 per 1M),
  and the `tts_stream` span carries the characters the voice was given.
  Same reason, same answer.
- **ElevenLabs** bills in credits whose value depends on the plan, so
  there is no list price to enter at all.
- **Piper and faster-whisper** run in this process. There is no rate
  because there is no vendor, which is a true answer rather than a gap:
  what a local voice costs is the machine it runs on. They also report
  no usage: a local engine does not count what it was sent, and this
  server will not count it on the engine's behalf.

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
same credentials and the same backup: one row per session (device,
agents, protocol, the resolved providers, when it opened, when and why
it closed), one row per conversation (its agent, the device it began
on, a title taken from the earliest utterance stored on it, and when it
was last spoken to), one row per turn (what was heard and what was replied, the ASR,
LLM and TTS timings, the rounds and the token counts), one row per tool
call a turn made (its source, its arguments and its result), and one
row per structured event, which is the same decision track the capture
writes beside its audio. A turn names both the session it was spoken in
and the conversation it belongs to, so the two are views of one set of
rows rather than two records: one session can touch several
conversations, and one conversation can span several sessions. Audio never enters it: the capture is the recording,
this is the queryable record. The columns are documented in
[`../docs/reference/conversations-schema.md`](../docs/reference/conversations-schema.md),
generated from the schema itself, and `vinga-server conversations
schema` prints the same document.

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

**`resumption` is the third switch and the only one that is not about
storage.** It decides whether an agent can find one of its own past
conversations and carry on with it, and it is off by default, because
recording a conversation and reading it back to a model are separate
decisions. It reads what the other two wrote, so a configuration that
asks for it with `enabled` or `text` off is refused at boot in a
sentence naming both keys and both ways out. What it changes, once on:
the two
[conversation tools](../docs/run/tools-and-mcp.md) stop refusing, and picking a
conversation rebuilds the model's context from the stored dialogue,
newest turns first, up to `resumption_budget_tokens`. That budget is
approximate by design (the count is estimated from the stored
characters), what it drops when a thread is longer than it are whole
turns oldest first, and a thread rebuilt from its tail is told so, as
is one whose record has holes in it. Arguments and results of the tools
a turn ran stay in the store: what a rebuilt conversation carries is
what was said, and the names of the tools that ran.

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

**The switches are deployment-wide, and they are the only privacy
control this release has.** Until per-user controls exist, enabling text
storage on a device a household shares stores what guests say to it,
which is the same statement the capture section makes about audio.
Attributing a session on a shared device to one member needs voiceprint
identification, which does not exist here yet, so the units deletion is
expressed in are the conversation and the session: the first is what
retention takes whole, and both are what the erasure API will address.
Erasing either on demand is an act of the API with a CLI verb in
front of it, which the deletion section below says in full. The session id is surfaced everywhere regardless: on the
events, on the capture triplet's filenames, and on every row the store
keeps.

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
timestamps are not a conversation.

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

**Read it live, as `vinga_ro`.** There is nothing to copy first, and
nothing to copy safely: the store is SQL, and the way in is a
read-only session as the role
[`../deploy/postgres-init.sql`](../deploy/postgres-init.sql)
provisions. It has `SELECT` on every table in the `record`
schema, now and after the next migration, and nothing at all on the two
schemas beside it: `domain`, where the stored secrets' ciphertexts
live, and `memory`, whose read surface is the addressed API under
[`vinga memory`](../docs/run/memory.md#reading-and-correcting-what-it-kept)
rather than raw tables:

```bash
psql "postgresql://vinga_ro@127.0.0.1:5432/vinga" \
  -c 'select * from record.turns order by id desc limit 20'
```

Its password under compose is `vinga_ro`, which is a loopback-only
convenience in the same way the server's own default password is. The
role also carries a `statement_timeout` and an
`idle_in_transaction_session_timeout`, which are not tidiness: a
reader's locks hold off the schema changes a migration makes, so a
session left open inside a transaction is what would make the next
boot's migration wait out its lock timeout and refuse. A database
provisioned without that file simply has no analyst role, and serves
exactly the same.

There is deliberately no analysis command, and the ids on `sessions`,
`conversations`, `turns` and `events` are identity columns a sequence
never hands out twice, so a client that has read up to one can ask for what came after
it and cannot be handed a different row under the same number.

Writing never happens on the conversation's path. One background thread
does every database call behind a queue nothing on the session loop ever
waits on, and it commits at turn boundaries and at session close, so a
page opened mid conversation reads everything up to the last completed
turn. A database that is wedged or locked drops events, says so once per
session, and records the count on the session row, and it never delays a
reply.

Turns and closes are never refused at the queue, whatever the backlog:
they are the record's structural truth and they arrive at conversational
pace. That is not a promise that a close always lands. A close whose own
transaction fails leaves the session row open-shaped, with a null
`closed_at` and no close reason, which is the same incomplete state a
process killed mid-session leaves behind: it is readable, it is listed,
and retention prunes it on `started_at` like any other. A line at
warning level says so when it happens.

## Running in a container

This has moved to
[Running vinga in a container](../docs/run/running-in-a-container.md),
and every other deployment task has a guide of its own in
[`docs/run/`](../docs/run/README.md).

## Status

vinga-server serves conversations end to end: OTA and WebSocket
endpoints, the VAD/ASR/LLM/TTS pipeline on pluggable providers, agents
bound to devices, MCP tools on both sides, device authentication,
onboarding by a short URL and an activation code, limits,
structured logging, and a published multi-arch container image. The v1
plan and its per-milestone implementation notes live in
[`docs/plans/`](../docs/plans/); getting a device on your desk onto it
is in [`../docs/devices/`](../docs/devices/README.md), and the wire it
speaks is in [`../docs/xiaozhi-notes.md`](../docs/xiaozhi-notes.md).
