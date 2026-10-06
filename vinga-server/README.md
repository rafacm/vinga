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
- [Listening and barge-in](#listening-and-barge-in): how a turn ends, and what it takes to interrupt a reply.
- [Masking reply latency](#masking-reply-latency), [When a reply fails](#when-a-reply-fails), and [When a model writes a tool call into its speech](#when-a-model-writes-a-tool-call-into-its-speech): the three things that go wrong between a model and a speaker, and what the server does about each.
- [Logging](#logging) and [Capturing a session](#capturing-a-session): what a running server says about itself, and how to record a conversation for study.
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

## Listening and barge-in

The firmware decides how it listens and the server follows. In `auto`
mode the device shuts its microphone off while a reply plays and sends a
fresh `listen start` afterwards. In `realtime` mode, which it picks when
its echo cancellation is on, it streams continuously and asks only once,
so the session here never stops listening: an utterance that ends while
a reply is playing cancels that reply and is answered instead. Talking
over the assistant stops it, which is what barge-in means.

```yaml
server:
  barge_in: true               # speech during a reply interrupts it
  barge_in_min_speech_ms: 500  # least classified speech that may interrupt
```

Turn it off for a board whose echo cancellation leaks the speaker back
into the microphone, typically a single-mic board, where a reply would
otherwise interrupt itself. Conversations stay multi-turn with it off;
only the interrupting goes. What says a board wants it: replies that
answer nothing at all, arriving just after the previous reply finished
speaking.

An interruption the endpointer hears is gated before it may cancel: a
reply is only cancelled on evidence of user speech. Speech shorter than
`barge_in_min_speech_ms` is a noise blip and never interrupts. Past
that floor, the reply pauses while ASR transcribes the interruption,
and only a non-empty transcript cancels; an empty one resumes the reply
where it stopped, about one ASR pass later. An interruption landing
while the reply is still transcribing merges with what it interrupted
instead, so one reply answers the whole sentence. Nothing is dropped
for arriving early in the playback: a refractory window used to do
that, and it turned out to catch only users finishing their own
sentence, since half a second of classified speech cannot come out of
the fraction of a second of reply the room has heard by then.
Every one of these decisions is a structured log event, which is what
the threshold is tuned from. A manual `listen stop` mid-reply is the
user holding the button and speaking, so it cancels unconditionally.

**Where a turn ends is one number, and it belongs to the agent rather
than to the server.** The endpointer ends an utterance after
`trailing_silence_ms` of silence, 700 ms by default, which is the right
bound for question-and-answer speech. Dictation is slower: telling an
agent things to remember pauses between clauses for longer than that,
so the turn ends mid-sentence, the reply answers a fragment, and the
rest of the sentence arrives as an interruption to it. Raising the
bound for the whole server would put the added latency on every turn of
every agent to fix one agent's usage pattern, and there is no need to.
The bound is an option on the VAD provider entry, and an agent binds
the entry it wants:

```yaml
providers:
  vad:
    quick:
      type: silero
    patient:
      type: silero
      trailing_silence_ms: 1200

agents:
  quizmaster:
    vad: quick
  archivist:
    vad: patient
```

Each agent's endpointer is built from the entry that agent binds, and a
handover mid-conversation builds a fresh one from the incoming agent's,
so the two agents above listen differently inside the same session.
What a longer bound cannot do is tell a thinking pause from a finished
sentence: every pause costs its full length before the reply starts,
which is why this is per agent rather than raised everywhere, and why
reading more than silence is its own piece of work
([end-of-turn detection](../docs/glossary.md#end-of-turn-detection)).

## Masking reply latency

The silence between the end of an utterance and the first audio of the
reply is where the assistant feels dead: healthy field turns run 1.5
to 3 s of it, and a slow provider stretches it well past the point
where users ask "are you there?". Humans hold exactly this gap with a
filled pause, and an agent can too:

```bash
vinga-server config agent-defaults set -f - <<'YAML'
filler:
  # off by default
  enabled: true
  delay_ms: 1800
  phrases:
    - "Hmm, let me see..."
    - "Good question..."
YAML
```

When a reply's first audio has not started within `delay_ms` of the
utterance being transcribed, the session plays one of the phrases,
rotating through them, and the real reply queues behind the clip's
tail. The clips are synthesized ahead of time in each agent's own voice
and cached as PCM, never at fire time: synthesis at the moment of
masking would add TTS latency to the exact gap being masked, and a
cached clip keeps working when the TTS provider is the thing being
slow. Ahead of time is the server start and every `vinga-server config
apply` after it, which re-synthesizes the agents whose effective
`filler` section or whose voice moved, whichever field of the section it
was, and hands the result to the next conversation; one already open
keeps the clips it opened with. A synthesis failure logs a
warning and leaves the feature off for that agent rather than failing
the boot or refusing the apply.

The filler is honest assistant speech: it moves the device into its
speaking state, counts as the turn's `speaking_started`, lands on
capture channel 1, and enters the barge-in gates like any reply audio,
so talking over it interrupts the reply, which is the correct reading.
One filler per turn, logged as a `filler_played` event; a turn that
outlives both the filler and the first-token watchdog resolves through
the watchdog's give-up path (see below), the filler being the soft
early threshold and the watchdog the hard late one. Write the phrases
in each agent's own language; an agent's own `filler` section replaces
the inherited one wholly, like the stage fields, and the reasoning
behind the default delay is in
[`examples/agent-defaults.yaml`](examples/agent-defaults.yaml).

The mask yields to the user. At fire time the timer stands down, with
a `filler_skipped` event, when the endpointer holds unresolved speech
or a barge-in confirmation has the outgoing frames paused. Both mean
the turn ended at a premature endpoint and the user is already mid
continuation: the reply in flight is about to be cancelled, and a
clip played into that would talk over them (field round 2 measured
exactly this on dictation-style turns). The skip consumes no phrase,
and the reply that answers the completed sentence arms its own timer.

## When a reply fails

The other end of the same turn. A reply that fails outright, on a
provider that is down or a model that never answers, used to be
silence: the failure was logged and nothing reached the speaker or the
display, so from the couch a broken pipeline and a slow one were the
same turn. Every agent therefore has a fixed phrase for it, cached the
same way the filled pauses above are:

```bash
vinga-server config agent-defaults set -f - <<'YAML'
fallback:
  # on by default
  enabled: true
  phrase: "I ran into a problem and could not answer. The server log has the details."
YAML
```

It is spoken and shown: the sentence goes out as a `tts sentence_start`,
so it renders on the display, and the cached clip follows it, so it is
heard. It is vinga's own words rather than the agent's, and it goes no
further than that turn: it never enters the reply's spoken sentences,
the conversation history or the stored conversation, and `replied`
keeps its meaning of model speech that went out. What says it happened
is a `reply_fallback` event, carrying the reason and whether the phrase
was heard as well as shown, never the words themselves. The phrase is
fixed configuration and is never the failure's own message, which
arrives from the far side of a network and is not this server's to
speak.

Only a terminal failure speaks. A device that went away is told
nothing, because there is nobody left to tell, and a reply cancelled by
a barge-in says nothing either, because a cancellation means the user
is talking. Neither reads the section.

**This one is on by default, unlike the filler above.** The silent turn
is at its worst during onboarding, where a misconfiguration is
likeliest and nobody has a log open, so a deployment that would rather
have silence is the one that says so: `fallback: {enabled: false}`, on
`agent_defaults` or on a single agent. Being on by default has a cost
worth knowing, and it is per start rather than per upgrade: **every**
server start synthesizes one short phrase for every agent that has not
switched the section off, through the configured TTS provider, before
the server begins serving. That is one provider call per agent, a few
seconds of startup, and, on a metered voice, a few seconds of billed
synthesis, paid again at every restart, redeploy and container
replacement. Nothing is cached across processes: a start has no previous
world to keep a clip from. What reuse there is lives inside one running
process, across `vinga apply`: an agent whose `fallback` section and
whose voice are both unchanged keeps the clip it already had, and each
of the two kinds of clip is re-synthesized only when its own section or
its voice moves, so applying a prompt edit costs no synthesis at all.
Synthesis is bounded per phrase, so a provider that hangs delays a start
by seconds rather than indefinitely; a phrase that will not synthesize
in time, or at all, degrades to the display alone, with a
`fallback_degraded` event naming the agent. That turn still shows the
sentence and still closes with its `tts stop`, and only the audio is
lost.

## When a model writes a tool call into its speech

A reply is spoken sentence by sentence, and every sentence is spoken
except one kind: a sentence shaped like a call to a tool this reply
actually offered. Some models, small local ones especially, write their
calls out as ordinary prose instead of issuing them, and read aloud
that is JSON in the assistant's voice on the one user-facing surface
with no filter on what a model produced.

The check is narrow, and it is anchored to the tools of the reply it is
in rather than to "looks like JSON": someone asking an agent to explain
a JSON snippet is a real conversation and gets an answer. A sentence is
withheld when it contains a complete JSON object that either names one
of the offered tools, in its own `name` or in the `name` under a
`function` key, or whose keys all fall inside the properties one
offered tool declared. The second is the shape the field actually
produces, where the name never made it out and only the arguments did
(`{"volume":"100"}`), so nothing about it can be matched by name; keys
are compared and values never are, since the observed one had the wrong
type for the schema it belonged to.

The sentence goes whole and the reply carries on. It is not spoken, not
shown, not added to the conversation this server keeps, and not stored,
and no event or log line carries a byte of it: what says it happened is
a `sentence_withheld` event, carrying its length in characters and
which tool it was shaped like, under the same naming rule `tool_call`
follows. A reply left with nothing at all to say, every sentence of it
withheld, says the fallback phrase above with the reason
`nothing_sayable`, because the alternative is the silence that phrase
exists to end.

**One bound, stated rather than hidden.** The test is on each sentence
as it arrives, because a sentence has already been handed to the voice
by then. Sentences are cut at newlines, so a pretty-printed call
arrives as a handful of fragments no JSON decoder can read, and those
fragments are spoken. Closing that would mean holding sentences back to
see what follows them, which puts a stall in front of live speech at
every ordinary `{` in every reply. The residue is left visible through
the event instead: an operator seeing `sentence_withheld` repeatedly,
or hearing the fragments, is reading a fact about the model this
deployment configured. The same event is what makes the cost of the
key-matching rule visible, since an agent reading out a JSON example
whose keys mirror an offered tool is withheld too.

## Logging

Two formats, one handler:

```yaml
server:
  log_format: text   # or json, which is the container image's default
  log_level: INFO
```

Every event is logged as a human sentence and, in `json` mode, as a line
of structured fields. Every record carries `event`; the ones a
conversation emits, on the `vinga_server.session` channel, carry
`session` and `device` beside it, and the server's own channels carry
either only where the record is about one.

Which fields an event carries, which tokens a reason field admits, what
each of them is held to and which sentence it renders are the generated
[event schema reference](../docs/reference/events.md), one section per
event and one subsection per shape it may be emitted in. It is generated
from the declarations themselves, so it cannot say anything they do not.
This index is the other half: what exists, and when it fires.

| `event` | when |
| --- | --- |
| `ota_check` | a device checks in (no session yet, so the record names the device) |
| `ota_check_body` | the whole of what a board reported at that check-in, at DEBUG, so `vinga events tail --level DEBUG` is how somebody asks for it |
| `activation_not_offered` | an unbound device is answered with no activation code, and why |
| `activation_complete` | a waiting device has been claimed; its next check hands it a token |
| `activation_pending` | a waiting device polls and is still waiting |
| `activation_refused` | a version-2 activation poll fails one of the checks this server can hold it to; nothing of the body is ever quoted |
| `ota_request_rejected` | a request this endpoint could not read, refused with one of three fixed sentences |
| `onboarding_banner` | where devices are configured, said once at startup |
| `onboarding_key_mismatch` | a request reaches the onboarding path carrying a key-shaped segment that is not this server's; neither is repeated |
| `onboarding_key_unshaped` | the same path, carrying something that is not key-shaped at all |
| `auth_rejected` | a handshake is refused before the accept; no device, since nothing is authenticated yet and the Device-Id header is whatever the caller sent |
| `session_rejected` | a device is turned away, either by the endpoint before a session can run (`vinga_server.ws`) or by the session after the accept (`vinga_server.session`) |
| `session_open` | a conversation starts |
| `session_limit` | the duration cap fires |
| `session_idle` | the idle timeout hangs up on a realtime session |
| `session_closed` | a conversation ends |
| `speaking_started` | the reply's first audio frame goes out |
| `speaking_finished` | the reply's last audio frame has gone out; with `speaking_started` it bounds the interval the frame pacer actually paces, and a reply that never spoke emits none |
| `frames_dropped` | one second of mic frames the edge's guards discarded before they could be decoded, counted by reason; at DEBUG, and counted whether or not this deployment records anything |
| `turn_started` | a reply attempt begins, stamped with the instant the user stopped speaking; `barge_in` says whether answering it interrupted a reply in flight |
| `reply_finished` | a reply ends, however it ended: exactly one per `turn_started`, with an outcome latched where the end was decided |
| `heard` | an utterance is transcribed. No transcript: what was said is the conversation store's |
| `nothing_heard` | an utterance is transcribed to nothing at all, which is one of the four ways an utterance's ASR stage ends, beside `heard`, `provider_failed` and `transcription_abandoned`; no text field, by type |
| `transcription_abandoned` | a transcription was given up on before it answered, because the reply it belonged to was cancelled with the call still running; deliberately not `provider_failed`, since nothing failed |
| `sentence_synthesized` | one sentence of a reply has finished streaming out of the voice: the provider's latency to its first chunk, and the stream's whole lifetime, which includes playback backpressure. At DEBUG |
| `replied` | a reply finishes |
| `agent_said` | one agent's part of a reply |
| `handover` | `switch_agent` succeeds |
| `conversation_resumed` | a stored conversation is picked up again: how much of it was rebuilt, how much could not be, and whether there was more of it than the budget had room for |
| `milestone_recorded` | a consented recap is stored as a checkpoint on its thread, after the user has heard it |
| `prompt_assembled` | the know-how half of a prompt is assembled and cached, with each block's size by provenance |
| `llm_retry` | the first-token watchdog cancels a stalled generation and retries the round once |
| `llm_round` | a generation call finishes |
| `provider_failed` | an ASR, LLM or TTS call fails; a round whose retry also stalled carries `FirstTokenTimeout` |
| `tool_call` | a tool returns |
| `tool_arguments_coerced` | a call went out with argument types this server corrected, because the model quoted a value its tool declares as a number or a boolean: how many were converted, and never which or to what |
| `sentence_withheld` | a sentence of a reply was shaped like a call to a tool this session offered, so it was dropped rather than spoken: how long it was and which tool it was shaped like, never a byte of it |
| `barge_in` | speech cuts a reply short |
| `barge_in_suppressed` | an interruption is dropped and the reply lives |
| `barge_in_merged` | an interruption merges with the utterance the reply was transcribing |
| `filler_skipped` | the filler timer fired but the user was there first, so no clip played |
| `filler_played` | the reply was slow, so a pre-synthesized filler clip masked the wait (its first frame is the turn's `speaking_started`) |
| `reply_fallback` | a turn said the agent's fixed fallback phrase instead of an answer, and why; `audio` says whether it was heard as well as shown |
| `asr_prompt_echo` | a transcript came back as the ASR prompt and the clip was retried once without it, on what the first request left of `timeout_s` (no session or device: providers serve them all) |
| `mcp_connected` | an MCP entry's connect finishes and its tools are published (no session or device: one entry serves every conversation, and the rest of this block is the same) |
| `mcp_down` | an MCP entry fails to come up, or its connection is given up. `stopped` is the intentional one (a shutdown or a reload) and the only one at INFO |
| `mcp_call_dropped` | a tool call failed and the connection was dropped because of it, always beside an `mcp_down` with `call_failed` |
| `mcp_tool_shadowed` | a published tool is dropped because a more specific entry owns its name |
| `mcp_reload` | a reload of the MCP servers finishes, whether or not the caller is still connected |
| `provider_reaches_loopback` | a provider entry built inside a container names this machine in its endpoint |
| `memory_unreadable` | one scope of an agent's memory could not be read, so it remembers nothing of that scope this round |
| `memory_unwritable` | a change an agent asked for could not be stored, so nothing was changed |
| `memory_cleanup_failed` | the memory of conversations that are gone could not be removed, so the next sweep takes it |
| `filler_disabled` | filler synthesis failed for one agent, so latency masking is off for it |
| `fallback_degraded` | the phrase a failed reply says would not synthesize for one agent, so its failed turns are shown on the display and not spoken |
| `capture_started` | a session is being recorded |
| `capture_declined` | a session is not being recorded, and why |
| `capture_limit` | a recording reaches its per-session ceiling |
| `capture_failed` | a recording stops after a write failed |
| `capture_pruned` | old recordings are removed to stay inside the disk budget |
| `capture_over_budget` | the disk budget is exceeded and nothing more can be pruned |
| `capture_enabled` | capture is on, said once at startup and at WARNING: recording room audio is not something to discover by accident |
| `capture_disabled` | capture is configured but off |
| `capture_uploaded` | a closed session's recording is beside its trace in the telemetry backend, with its sizes, how long it took and how many turn clips went to their turns |
| `capture_upload_failed` | a recording is not beside its trace, and why, from a closed set of reasons; also what a restart says about a job it found still staged |
| `capture_clips_incomplete` | a recording is beside its trace and some of its turns' clips are not on their turns: how many attached, had no turn, failed or were never tried, and the first failure's reason |
| `transcripts_exported` | acknowledged content was attached to an original turn root and enqueued for ordinary OTLP processing, with how long settlement took |
| `transcript_export_failed` | turn content was omitted before enqueue, and why, from a closed set of reasons |
| `llm_input_exported` | a complete input and raw-output pair was attached to its actual generation span and enqueued for ordinary OTLP processing |
| `llm_input_export_failed` | generation content was omitted before enqueue, and why, from a closed set of reasons |
| `conversations_enabled` | the conversation store opens at startup, which means this server is recording what is said to it (no session or device: it is said once, before anything connects) |
| `conversations_dropped` | the store is behind and events for one session are being dropped, said once per session at its first drop; the total lands on that session's row |
| `conversations_failed` | a write to the store failed and its batch was dropped, or a prune could not run |
| `conversations_pruned` | retention deleted the conversations that aged out of the window, and the session records nothing points at any more (at INFO: a policy doing its job) |
| `drain_started` | a shutdown begins draining |
| `drain_finished` | every reply finished speaking |
| `drain_incomplete` | a reply was cut, or a session hung |
| `device_bindings_unreadable` | the configuration database could not be read, so the answer is the served world's and may be older |
| `api_error` | the configuration API failed to handle a request; the class name and nothing else |
| `api_storage_error` | the configuration API met unreadable stored state |

No MCP event names a tool, and none of them can. Half of a published
tool name is whatever the far side called it, sanitizing replaces only
the characters both LLM APIs refuse, and an alphanumeric credential goes
through that untouched, so a server handed one of your own could put it
in the logs you keep by listing a tool under it. Every line about a
single tool therefore says which one by its position in that server's
listing. `vinga-server config mcp-server status` prints the names
themselves, to a terminal, when you ask it.

Every event above is declared: its channel, its level, the sentence it
renders, the arguments that sentence takes and every field it may carry,
with closed sets for the fields that hold a reason token. The reference
this index points at is those declarations rendered, and CI regenerates
it and refuses any difference. The emitters build each emission inside a
guard, so an emission that could not be built costs one line on the
emitter's own channel, naming a fixed label and a fixed code and nothing
about the emission itself; it is dropped rather than written in some
other shape, because a telemetry bug must never cost a reply.

### Watching a deployment as it runs

The table above is what gets written down. The same events are also
readable as they happen, over the configuration API and from wherever
the CLI already reaches, which is what the two moments that used to mean
reading the container's log on the server host are:

```bash
# Wait for the next event of one board, print it and exit: what to run
# after typing a URL into a captive portal.
vinga events tail --device aa:bb:cc:dd:ee:ff

# Or watch until you stop it, which is the diagnostic reading.
vinga events tail --follow
vinga events tail --follow --session 6f1a2b3c4d5e6f708192a3b4c5d6e7f8
vinga events tail --follow --level warning
```

One line per event: the clock time, the level unless it is `INFO`, the
event's name, and its own fields. Nothing is kept behind the stream, so
it carries what happens while it is open and a reader that reconnects
rejoins the present; what happened before is the conversation record's
to answer. A reader that falls behind loses its oldest events rather
than slowing a conversation down, and is told how many on stderr. The
stream ends when you stop it or when the server shuts down, and an end
you did not ask for is a sentence and exit 1 rather than a quiet
terminal, because nothing reconnects on its own: a tail that rejoined
across a gap would look continuous while missing what happened in it.

The same route is `GET /api/runtime/events`, behind the same bearer
token, answering `text/event-stream`.

These events are metadata, and metadata only. What was said is in the
conversation store, keyed by the same `session`: query `turns` there for
the transcript and the reply, and `tool_invocations` for what a tool was
asked and what it answered. Filtering the logs for it no longer works,
and that is the point (see the [content and telemetry
ADR](../docs/adr/2026-08-15-content-and-telemetry-are-separate-surfaces.md)):
a surface with no free-text field cannot leak one. What the events keep
is what a latency brief reads, which is every duration, every count and
every identifier they ever carried. Tokens are never logged, at any
level.

## Exporting traces

`server.telemetry.enabled` sends one backend-neutral OpenTelemetry model over
OTLP/HTTP protobuf. A session is the root of its own trace. Each conversation
turn is a separate root trace linked to that session and grouped with it by
`session.id`. The semantic operations are `asr`, `llm`, `tool`, `tts_stream`
and the existing playback operation. They are children of the open turn, or
of the session when provider work such as a recap happens between turns. The
exporter keeps the trace flags and trace state each root received; a later
post-close writer does not turn an unsampled trace back on. Transcript and
assembled-request exporters report that case as `no_trace` without asking the
OTLP transport, rather than calling a deliberate sampling decision a failed
delivery.

Each model call gets a server-minted `vinga.llm.invocation.id` before its
request is assembled. A retry keeps that identity, while the next logical
generation gets another. `vinga.llm.round` remains the reply-local ordinal.
A recap is also an `llm` operation, marked with
`vinga.llm.purpose=recap`, but has no reply ordinal and changes none of the
turn record's round, latency or token totals.

Failed ASR, LLM, TTS and tool work is represented by the semantic operation
span itself. It has OpenTelemetry `ERROR` status with no description and an
`error.type` containing only an exception class name. A tool that returned an
error without raising uses the fixed `tool_error` value. Exception messages,
tracebacks, tool arguments and tool results do not become failure metadata,
and there is no duplicate `provider_failed` or `tool_call` span event beside
the failed operation.

OpenTelemetry names are the canonical attributes. The existing
`langfuse.observation.usage_details` fields for ASR and TTS remain derived
copies of the canonical whole-number usage values so direct-to-Langfuse
deployments keep their pricing behavior. A live gate measured the condition
that alias is read under: Langfuse prices an observation only where it stored
one as a generation, which it decides from `gen_ai.request.model` or from a
`gen_ai.operation.name` it knows. Both paths to it are canonical attributes
rather than a backend hint, and the two stage kinds reach it differently. An
`llm` round always names its operation, so it is a generation whether or not
its provider reported a model. `asr` and `tts_stream` have no operation name
the backend recognizes, so they reach it only by the model a real provider
reports; against a provider that reports none, which in practice means the
mock providers the test lanes run on, they are stored as plain spans and are
not priced. With `export_transcripts`, acknowledged
text and ordered handover legs enrich the original turn root as
`vinga.turn.input`, `vinga.turn.output` and `vinga.turn.legs`. With
`export_llm_input`, the actual generation span receives
`gen_ai.system_instructions`, `gen_ai.input.messages`,
`gen_ai.output.messages`, `vinga.llm.tools` and `vinga.llm.tool_choice`.
Generated output is captured before speech filtering, so text withheld from the
user also leaves. The turn root also carries direct Langfuse input, output and
legs aliases derived from its transcript values; the generation span carries
none, because Langfuse maps the GenAI conventions itself and shows the system
prompt as the first message of the generation's input. The former `transcript`
and `llm_input` child spans no longer exist.

The ordinary trace path still has one bounded batch queue. A full queue drops
spans instead of delaying a reply, and a bounded shutdown gives the exporter a
last chance to flush. It holds 2,048 spans, schedules every five seconds and
exports at most eight spans per request. Each turn or generation content
projection is limited to 256 KiB, keeping a maximal request below 3 MiB.
`transcripts_exported` and `llm_input_exported` report attachment and enqueue,
not backend acknowledgement; ordinary exporter health owns downstream
delivery. Standard `OTEL_EXPORTER_OTLP_*` variables own the
destination, protocol and credentials; none becomes span content. This
repository provides three current trace paths. The Jaeger and Collector paths
are exercised in automated tests, and all three have been walked live under the
M2 turn-root and generation-content model: direct Jaeger against a Jaeger
instance, and both Langfuse destinations, the direct one and the Collector's
Langfuse branch, against a live Langfuse v4 project:

- direct Jaeger v2 over OTLP/HTTP protobuf;
- direct Langfuse v4 over OTLP/HTTP with Basic Auth and its ingestion-version
  header;
- one Collector Contrib pipeline that masks, samples and batches before it
  forwards the same attempted population to Jaeger and Langfuse.

The runnable Jaeger and fanout Compose add-ons are under
[`deploy/telemetry/`](../deploy/telemetry/README.md), with their worked
procedure in [the deployment guide](../docs/deployment.md#telemetry-backends).
The fanout source sampler is explicitly `always_on`; its Collector owns the
one trace-id sampling decision before split. Since a session and each turn
have independent trace IDs, partial sampling keeps or drops turns rather than
whole conversations. The walkthrough defaults to 100 percent so its topology
is complete.

For direct Langfuse, supply the v4 OTLP endpoint and both required headers to
the SDK-owned transport. The Authorization value is the word `Basic`, one
URL-encoded space, then base64 of `public-key:secret-key`:

```bash
export OTEL_EXPORTER_OTLP_ENDPOINT=https://cloud.langfuse.com/api/public/otel
export OTEL_EXPORTER_OTLP_PROTOCOL=http/protobuf
export OTEL_EXPORTER_OTLP_HEADERS="Authorization=Basic%20<base64-public-key-colon-secret-key>,x-langfuse-ingestion-version=4"
```

Fanout applies one policy decision and gives both exporters the same records.
It is not a transaction across two backends. A backend outage can still make
their stored populations differ, so compare trace IDs when diagnosing parity.
The Langfuse-only `capture` reference span is removed on the Jaeger branch.
Recording bytes (the WAV, the manifest and each turn's clips) never enter OTLP:
they remain on the separate Langfuse REST and object-storage upload path
governed by `export_audio`.

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
