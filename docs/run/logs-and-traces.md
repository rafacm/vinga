# Reading logs and traces

At the end of this guide you will have chosen the log format a
deployment writes, know which events exist and when each fires, be
able to watch one board's events or the whole server's live from
wherever the CLI reaches, and have sent traces to Jaeger, Langfuse or
both, knowing what each trace carries and what never leaves.

The two log keys, `log_format` and `log_level`, are in the server
configuration reference under
[`server`](../reference/server-config.md#server), and every trace
setting under
[`server.telemetry`](../reference/server-config.md#servertelemetry).
What each event carries is the generated
[event schema reference](../reference/events.md), and `vinga events
tail` is in the CLI reference under
[`vinga events tail`](../reference/cli.md#vinga-events-tail).

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
[event schema reference](../reference/events.md), one section per
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
ADR](../adr/2026-08-15-content-and-telemetry-are-separate-surfaces.md)):
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
[`deploy/telemetry/`](../../deploy/telemetry/README.md), with their worked
procedure in [the deployment guide](../deployment.md#telemetry-backends).
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
