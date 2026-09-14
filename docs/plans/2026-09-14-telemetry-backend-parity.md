# Align telemetry across Langfuse and Jaeger

Plan for [issue #523](https://github.com/rafacm/vinga/issues/523).
Companion implementation doc:
`2026-09-14-telemetry-backend-parity-implementation.md`, one section per
milestone, appended in the same change that ticks the milestone checklist.

## Goal

Give vinga one backend-neutral trace model that is equally useful in Jaeger
and Langfuse. One conversation turn remains one root trace, grouped with the
rest of its session by `session.id`; the existing semantic ASR, LLM, tool,
TTS and playback operations remain its children. Optional conversation and
model content moves onto the operation it describes, failed provider and tool
operations become real failed spans, and the exporter stops emitting a second
Langfuse-shaped observation model beside the canonical one.

Two runnable paths prove the contract from outside. A direct OTLP/HTTP
protobuf path makes Jaeger a supported destination. A Collector path applies
one masking and sampling decision before it splits the same trace population
to Jaeger and Langfuse, adding the minimum Langfuse rendering hints and
ingestion headers only on that branch. Recording bytes remain on the existing
Langfuse-only media path. The current Langfuse `capture` reference span does
use the shared OTLP transport and is treated as an explicit backend-specific
exception rather than canonical fanout telemetry.

Local baseline: not applicable. No conversational capability changes. This
plan changes an optional, off-by-default export surface already governed by
the content-and-telemetry boundary.

## The issue's decisions, restated

These are settled by #523 and are not re-litigated here.

- Instrument semantic work at provider and orchestration seams. Raw HTTP or
  SDK calls, WebSocket frames, binary audio, headers, credentials and vendor
  wire payloads are not ordinary telemetry.
- A conversation turn is one trace. The turn root and its existing stable,
  low-cardinality ASR, LLM, tool, TTS and playback children are canonical;
  `session.id` groups the turn traces that belong to one session.
- With `export_transcripts` on, the turn root carries the heard transcript as
  its input and the final assistant reply as its output. With it off, neither
  appears anywhere in telemetry.
- With `export_llm_input` on, each actual `llm` generation span carries that
  round's assembled request and generated response. Tool and handover rounds
  remain separate generation spans with their own matched input and output.
  With it off, none of that content appears.
- Failed ASR, LLM, TTS and tool work is represented by real spans with error
  status and safe metadata. A failure is not represented only by an event.
- Masking and sampling happen before fanout. Both backends receive the same
  sampled trace identifiers and the same masked canonical values.
- OpenTelemetry GenAI semantic attributes are the source of truth. Backend
  hints may be derived only at the export boundary and do not create a second
  instrumentation model.
- The existing Langfuse recording upload, including its WAV and manifest,
  stays separate and opt-in. Its `capture` reference span remains a
  Langfuse-specific OTLP operation; the Collector Jaeger branch drops that
  span, and Jaeger receives neither media nor upload references.
- The existing data-boundary refusals, bounded non-blocking delivery, local
  conversation and capture retention, and content flags remain in force.

## Premises checked before planning

### The current topology is already the topology to keep

`vinga_server.telemetry.Telemetry` opens one session root trace, then opens
each `turn` with an empty parent context and a link back to that session. ASR,
LLM, tool, `tts_stream` and playback spans are children of the turn. Every
span carries both `vinga.session.id` and the backend-neutral `session.id`.
The issue asks to align backends around this topology, not to turn the session
into the parent trace again.

### Optional content is currently on the wrong spans

`transcript_export.py` reads acknowledged conversation rows after the close
and `Telemetry.export_transcript` writes new `transcript` spans. Likewise,
`llm_input_export.py` stages each request and later writes a new `llm_input`
span under the session. Those spans are a second observation model: the turn
root has no input or output, the actual generation has no request or response,
and a multi-round tool reply cannot be read as matched generation pairs.

An ended SDK span cannot be enriched. Reusing its identifiers in a second
span, relying on a backend upsert, or keeping both the old and new span is not
valid across OTLP destinations. Where content is enabled, telemetry therefore
keeps the original recording span open after the logical operation has ended,
retains its already-known end timestamp, and calls `Span.end(end_time=...)`
only after the content exporter has supplied authorized attributes or declared
them absent. The exported interval is unchanged even though release is later.

### The event catalog remains metadata-only

The event tap is the source of span timing and safe metadata. It intentionally
does not carry transcripts, LLM requests, model output, tool arguments or tool
results. This plan does not weaken that boundary. Content continues through
the dedicated collaborators that already exist, and the telemetry layer joins
it to a held span only by server-minted session, utterance and invocation
identities.

### Failure coverage is uneven

An ASR `provider_failed` already becomes a real `asr` span with error status.
LLM and TTS provider failures are only events on the turn. A tool call is a
real span, but `is_error` neither sets error status nor provides `error.type`.
The runtime still knows the safe exception class at all three decision sites,
so no exception message or traceback is needed to close the gaps.

### Sampling state is not preserved on the post-close path

The retained context currently reconstructs every post-close parent with the
sampled flag set. That is harmless only while the SDK samples everything. It
would make later content disagree with the root decision as soon as an
operator configured source sampling. The original trace flags and trace state
must be retained exactly, and an unsampled span must never be resurrected by a
content exporter.

## The canonical trace contract

### Topology and identity

The contract is one table, used by implementation tests, the direct Jaeger
walkthrough and the two-backend comparison:

| Operation | Parentage | Stable name | Content when authorized |
| --- | --- | --- | --- |
| session | root of the session trace | `session` | none |
| turn | root of one turn trace, linked to session | `turn` | heard input and final reply output |
| ASR | child of turn | `asr` | none |
| generation | child of turn | `llm` | that round's instructions, input messages and output message |
| tool execution | child of turn | `tool` | none on the trace metadata surface |
| synthesis | child of turn | `tts_stream` | none |
| playback | child of turn | existing playback name | none |

The existing `capture` span is deliberately outside this canonical table. It
contains backend-minted media tokens and Langfuse observation attributes for
the player, travels over the shared OTLP transport, and is routed only to the
Langfuse branch. The canonical parity comparison excludes it by stable span
name. Audio export against direct Jaeger is documented as inapplicable rather
than a Jaeger media feature.

Every span keeps its original trace id, span id, parent span id, links,
start/end timestamps, status, trace flags and trace state. Every span keeps
`session.id`; turn and child spans keep the existing utterance correlation.
The OTLP export boundary may add the existing, documented Langfuse aliases as
pure derivations for direct-to-Langfuse compatibility, but they may not become
a second source of truth or rewrite any canonical fact. The Collector keeps
those aliases on its Langfuse branch and removes them from its Jaeger branch.

The parity assertion compares the canonical projection, not every backend
extension: trace and span identifiers, parentage and links, names,
timestamps, status, standard attributes, `vinga.*` attributes, and authorized
semantic content must match exactly. Langfuse-only attributes and transport
headers are permitted only on its branch and are excluded by name from that
comparison.

### Turn content

There is no OpenTelemetry GenAI attribute that truthfully describes the input
and output of a whole voice-agent turn. The root therefore uses the vinga
extensions `vinga.turn.input` and `vinga.turn.output`, each a text value. They
are populated from the same acknowledged `TurnRecord` projection the current
transcript exporter reads. The reply is the final stored reply, including the
ordered legs of a handover exactly once, not the response of any one LLM
round. Empty input or output remains absent rather than becoming an empty
string.

Per-agent attribution is preserved on the same root as canonical JSON in
`vinga.turn.legs`, rendered from an allowlisted ordered array of agent, text and
token-count fields. The existing `langfuse.observation.metadata.legs` value is
derived from that canonical value for direct compatibility and is included in
the common content mask. The retired row-observation attributes
`vinga.turn.index`, `vinga.turn.id` and `vinga.turn.t_ms` have no truthful
root-level meaning and are removed. Legacy rows without an utterance also lose
their old session-parent content fallback; live turns with server-minted
utterances are the only rows that can enrich a canonical root.

A handover writes one row per conversation under the same utterance, so the
transcript exporter composes by utterance before it releases a root. Rows stay
in store-id order. The first non-null heard value becomes the one input; the
non-empty reply values are concatenated in row order for the one output. A
conflicting second heard value makes that utterance unreadable rather than
choosing one. The exporter stages consecutive live rows by utterance and the
reply's final boundary proves the group complete. It waits for every staged
row's acknowledgement before composing. A failed acknowledgement releases the
group metadata-only and reports the omission, never exports half a reply.
Rows without an utterance cannot address a canonical turn root and remain an
explicit unaddressable omission rather than creating a session-level content
span.

The OTLP export mapping copies these values to
`langfuse.observation.input` and `langfuse.observation.output` so an existing
direct-to-Langfuse deployment still renders the turn root as an observation.
That copy is an export adapter, not a second source of truth. The Collector's
Jaeger branch removes the aliases after common masking; direct Jaeger may show
the inert compatibility keys as additional attributes.

### Generation content

The canonical source is the current OpenTelemetry GenAI semantic convention,
including its input and output message JSON schemas. Python span attributes do
not yet carry structured values, so each structured value is encoded once as
canonical JSON and the exact encoded bytes are both weighed and exported:

- `gen_ai.system_instructions` carries the separately assembled system prompt
  as one text part;
- `gen_ai.input.messages` carries the ordered user, assistant and tool history
  sent to the model, including structured tool calls and tool responses;
- `gen_ai.output.messages` carries one assistant choice for that round, with
  the raw generated text and structured tool calls captured at the neutral
  provider seam before sentence splitting, withholding, TTS or vendor framing;
- `vinga.llm.tools` carries the ordered offered tool definitions and
  `vinga.llm.tool_choice` carries the choice, because the current GenAI span
  convention defines no span attribute for either fact. They extend rather
  than replace the standard attributes.

The serializer follows the published schemas field by field and never walks
provider or SDK objects generically. A tool or provider object gaining a
credential-bearing field cannot therefore make it exportable by accident.
The existing `vinga.llm.round` remains the reply-local display ordinal it is
today and is not used as a join key. Each logical generation instead mints a
server-owned opaque invocation id at the assembly point that can see both the
content collaborator and the eventual `llm_round` or `provider_failed`
emission. The event catalog carries it as declared metadata and the span maps
it to `vinga.llm.invocation.id`; `LlmInputRound` carries the same value. That
identity is session-unique, is consumed only for correlation, and contains no
provider value. The first-token retry reuses it, so a retry does not create a
second logical round or content snapshot. A dropped content snapshot consumes
no later round's identity. A failed round retains its request and any partial
semantic output admitted before failure, and has no invented completion.

The recap path becomes a first-class generation rather than an exporter-only
special case. `_summarized` mints the same invocation id, measures the same
provider operation, and emits `llm_round` through a metadata-only helper with
a declared low-cardinality purpose (`reply` or `recap`) on success. For recap,
the existing `round` field is absent: recap neither increments the reply-local
ordinal nor calls `TurnUnderway.round_done`. Its latency and tokens therefore
do not change stored turn totals or the metrics views derived from them.
Failure carries that identity and purpose through `provider_failed`. Both
outcomes create one real `llm` span under the active turn, with
`vinga.llm.purpose=recap`; the successful and failed shapes are symmetric, and
the staged recap request has an operation to enrich. Event and generated
reference prose distinguish traced recap work from reply-round accounting.

The recap's outer `asyncio.timeout` is a third failure site: cancellation
passes through `_watched_stream` and becomes `TimeoutError` only at the outer
boundary. That `except TimeoutError` arm explicitly calls `_provider_failed`
with the recap invocation id, `purpose=recap`, elapsed time and the safe
`TimeoutError` type before returning its existing no-recap result. It does not
rely on the inner helper to catch `CancelledError`, and it consumes the staged
request onto the failed generation span.

The existing per-request, per-session and maximum-round bounds apply to the
combined canonical content. `MAX_CONTENT_BYTES = 256 * 1024` is the maximum
combined serialized content added to any one turn or generation span. A round
or turn over that per-operation bound is dropped
whole. The session budget evicts whole rounds oldest first. Dropping content
always releases the operation span with metadata only; it never drops the
fact that the operation happened.

### Error semantics

Failed semantic operations set OpenTelemetry status `ERROR` with no status
description and carry `error.type`. At exception decision sites the value is
the exception class name. A tool that returns its own `is_error` result without
raising uses the closed token `tool_error`; a tool timeout uses
`TimeoutError`. The existing `vinga.*.outcome` and provider metadata remain.
No exception words, response body, traceback, tool arguments or tool result
is copied into error metadata.

`provider_failed` gains only the safe invocation id needed to pair an LLM
failure with its staged logical round. The event remains content-free. The tool-call
event gains only its already-decided error type, and the `tool` span maps it to
status and `error.type`. The existing ASR failure mapping also writes canonical
`error.type` beside `vinga.asr.error`; the vinga key remains as a compatibility
attribute and is not the canonical substitute.

The fold is substitutive, not additive. ASR, LLM and TTS `provider_failed`
emissions create their failed stage span and do not also become a span event on
the turn. A failed `tool_call` is likewise represented by its existing tool
span with error status, not by a duplicate event. Unit and wire tests assert
the absence of the second carrier.

## Per-operation content settlement

Generation content is complete at the neutral provider seam before its event
is emitted. `llm_input_export.py` finishes its bounded snapshot there and
stages one allowlisted attribute mapping in `Telemetry` under the invocation
id. The immediately following `llm_round` or `provider_failed` fold consumes
it while creating the actual `llm` span and ends the span normally. No
generation span waits for session close, no second provider exists, and a
missing or dropped snapshot changes only its content.

Transcript truth becomes available one store acknowledgement later. The
existing transcript worker changes from one post-close paging job into bounded
per-turn settlement. Every `TurnRecord` and acknowledgement returned by the
recorder is offered to it as the reply proceeds, including each handover row;
the final reply boundary marks that utterance complete. The `reply_finished`
fold retains only that one original `turn` span with its already-known end
timestamp. The worker waits for all rows in the completed utterance to be
acknowledged, composes them, adds the allowlisted root attributes and calls
`Span.end(end_time=...)`. A false acknowledgement, missing record, overflow or
shutdown ends the same root metadata-only. Earlier turns of a long session are
therefore released as their own writes land rather than waiting for session
close.

Holding a turn is enabled by registration of a built transcript exporter,
never by a config flag alone. `app.py` calls
`telemetry.register_transcript_exporter()` immediately after the builder
returns a non-null collaborator, during application construction and before a
session can be admitted. A flag-on transcript no-op because conversation
storage or text is off registers nothing, so its roots end immediately.
Session close settles an incomplete utterance group; transcript-exporter
shutdown and telemetry shutdown are successive metadata-only backstops before
the SDK provider shuts down.

Moving content onto canonical spans deliberately retires the private,
processorless post-close transport and its per-content-batch
`DELIVERED`/`UNDELIVERED` answer. The ordinary BatchSpanProcessor retains its
2,048-span queue, five-second schedule, finite HTTP timeout, non-blocking reply
path and bounded shutdown. Content events stop claiming that a far-side
backend accepted an exact page. Their generated schema and documentation say
which turn or generation content was attached to the canonical span or omitted
before queueing, while ordinary telemetry exporter health owns downstream
delivery. The old `undelivered` content reason and private `Delivery` API are
removed, and that reporting change is a `### Changed` migration item. The
existing event names remain for compatibility, but their definitions become
exact: `transcripts_exported` and `llm_input_exported` mean authorized content
was attached and enqueued through the normal exporter, not that a backend
acknowledged it; `transcript_export_failed` and `llm_input_export_failed` mean
content was omitted before enqueueing for one of their remaining closed
reasons.

The shared processor's `max_export_batch_size` moves from 512 to
`CONTENT_SAFE_BATCH_SIZE = 8`. Together with the 256 KiB per-operation content
ceiling, one worst-case OTLP protobuf request stays below 3 MiB including
resource and span overhead. The 2,048-span queue and five-second schedule do
not change. A serializer test fills eight maximal content spans, encodes the
actual `ExportTraceServiceRequest`, and asserts the body bound; the local OTLP
receiver also rejects any request above it so the integration path proves the
batcher did not combine a ninth. This replaces the transcript page's old
request-size bound with one that applies to every canonical content span.

The held-turn ledger is globally bounded at `DEFERRED_TURNS = 4096` logically
finished roots for the process. This is a flat safety cap, not a value derived
from unbounded `max_sessions`, per-session turn retention or byte-based LLM
budgets. On overflow it ends the oldest logically finished root globally as
metadata-only and reports the content omission. It never evicts an operation
still running. Unknown or already-ended keys are an explicit omission result,
never a second span. Unit tests exercise each transition and repeatedly race
acknowledgement completion with shutdown.

`Telemetry._held_turns_lock` guards the map and, more importantly, ownership
of the terminal transition. At `reply_finished`, the session-loop fold records
the explicit end time, moves the span into the held map and clears the live
turn slot; the session loop never touches that span again. A worker, overflow
or shutdown contender pops under the lock. Only the winner receives the held
span and mutates or ends it after releasing the lock; every loser sees an
already-settled key. This makes `set_attributes` plus `end` single-owner rather
than assuming SDK span mutation is safe across threads.

`transcript_export.py` keeps responsibility for store acknowledgement,
bounded admission, handover composition, outcome reporting and retention
truth, but its unit of work is a completed live utterance rather than a
post-close store page. It supplies root attributes instead of minting a
`transcript` span. `llm_input_export.py` deepens its existing staging
responsibility to pair schema-shaped input and output synchronously for each
round, enforce the byte bounds over the pair, and stage matching attributes
before the event fold. Separate `transcript` and `llm_input` span creation and
their private OTLP transport are deleted.

## Fanout, masking and backend adaptation

The committed deployment examples live under `deploy/telemetry/` and compose
with the root trial stack. They do not alter the production deployment
artifacts or make observability mandatory.

The direct example runs a pinned Jaeger v2 image, exposes its UI on loopback,
accepts OTLP HTTP/protobuf on 4318 and points vinga directly at it. The example
sets the SDK sampler explicitly to `always_on`; no Collector exists on this
path. The pull-request smoke starts vinga from the source tree with the same
`uvicorn.Server` fixture the integration suite already owns, drives the
existing simulated conversation, shuts it down cleanly, polls the containerized
Jaeger query API under a fixed deadline and asserts the session, turn and
semantic children. An optional built-image repetition belongs only to the
existing non-PR image job and is not claimed as the PR gate.

The maintained direct-to-Langfuse recipe remains part of the server exporter
contract. It supplies both requirements in the SDK-owned transport variable as
one comma-separated value:
`OTEL_EXPORTER_OTLP_HEADERS="Authorization=Basic%20<base64-public-key-colon-secret-key>,x-langfuse-ingestion-version=4"`.
Neither value becomes vinga configuration. The live v4 gate exercises this
direct recipe as well as the Collector path and records the accepted generation
and turn-root rendering before the old recipe is called supported.

The fanout example sends vinga to a pinned Collector Contrib image. Its graph
has one common traces pipeline with, in order, content masking, one
trace-id-based probabilistic sampler and batching. Its exporters are two named
Contrib `forward` connectors, `forward/jaeger` and `forward/langfuse`; those
same connectors are the receivers of separate sink pipelines. Vinga's OTLP
mapping is the one home that derives the existing Langfuse aliases needed by
direct-to-Langfuse deployments. The Langfuse sink preserves those already
masked aliases without recreating them, then uses OTLP/HTTP with the Basic Auth
client extension and the literal
`x-langfuse-ingestion-version: 4` header. The Jaeger sink pipeline drops every
`langfuse.*` attribute and the whole Langfuse-only `capture` span before its
OTLP/HTTP exporter. Vinga is explicitly `always_on`, so the one sampler in the
common pipeline is the only population decision. Neither sink pipeline may
contain a sampler or content mask, and both receive the exact same processed
records from the common pipeline before their documented backend adaptation.

Sampling is per trace id, and vinga deliberately gives the session and every
turn independent trace ids. A partial ratio therefore samples turns, not whole
conversations: a kept turn may link to a dropped session trace, and a kept
session trace may have dropped turn traces. `session.id` still groups what
survives but cannot reconstruct what was sampled away. The runnable live
comparison defaults to 100 percent so its topology is complete; the automated
two-receiver smoke alone uses a deterministic partial ratio to prove matching
populations. The deployment guide states this tradeoff beside the sampler.

The sample mask covers every canonical content-bearing attribute introduced
here and every content-bearing alias Vinga derives from it, including
`langfuse.observation.input`, `langfuse.observation.output` and the per-leg
metadata alias, before the split. It includes a documented email-shaped rule so an
automated sentinel can prove the raw value appears in neither receiver and the
same replacement appears in both. Vinga's opt-in flags and allowlisted source
projections remain the privacy guarantee. Collector masking is a defensive
deployment control inside the operator's trust boundary, not permission to
capture content with a flag off.

One processed pipeline guarantees one policy decision and identical inputs to
both exporters. It does not make two independent backends a transaction. An
exporter outage can still make stored populations diverge, and the deployment
guide says so rather than claiming delivery parity the Collector cannot
provide.

Collector Langfuse credentials live only in the ignored,
root-relative `deploy/telemetry/.env`, made from the committed
`deploy/telemetry/.env.example`. The override attaches that explicit file only
to the Collector service; the Collector config reads its process environment
with `${env:...}` expansion and the Compose file never interpolates those
values. The root `.env` remains vinga's file and never receives a `LANGFUSE_*`
name. Credentials therefore never enter vinga configuration, the vinga
container or a committed rendered compose file. The fanout smoke
substitutes two local OTLP receivers and dummy credentials, checks headers at
the receiver boundary, and plants credential-shaped sentinels in errors and
content to assert their absence from both protobuf bodies, Collector output
and server logs.

`server.telemetry.reach` continues to name the outermost destination, not the
first-hop Collector. A cloud Langfuse branch therefore requires `internet`
even when the Collector runs on the same host. Audio export additionally keeps
the existing Langfuse REST and object-storage destinations in that assertion.

## Module and documentation footprint

- `vinga_server/telemetry.py` keeps event-to-span topology, semantic attribute
  mapping, exporter construction and the public content release methods. It
  keeps the existing Langfuse aliases, including `usage_details`, as derived
  export-boundary compatibility attributes for direct-to-Langfuse deployments
  and delegates held-span lifecycle.
- `vinga_server/telemetry.py` also owns the bounded held-turn map beside its
  existing pending and retained trace maps. Its public methods are the only
  interface the transcript worker uses to register, enrich or release a turn;
  no new pass-through module is added and optional SDK imports stay behind the
  existing lazy boundary.
- `transcript_export.py` keeps store acknowledgement, bounded admission and
  outcome reporting, but stages completed live utterances and enriches turn
  roots rather than creating observations.
- `llm_input_export.py` keeps neutral-seam rendering and byte budgets, adds
  schema-shaped semantic output pairing, and enriches generation spans rather
  than creating observations.
- `config/models.py` widens the `export_llm_input` field description to say
  that each round's generated output, including model text withheld from
  speech, leaves with its assembled request. This is a disclosure widening of
  an existing flag, not a new switch.
  The `export_transcripts` field says that a turn root is released after that
  turn's rows are acknowledged, so an ungraceful process death can lose roots
  still waiting on storage while already-acknowledged earlier turns have left.
  It also replaces the old one-observation-per-row and session-parent fallback
  mechanism. The enclosing `TelemetryConfig` disclosure-ladder docstring moves
  with both field descriptions.
- `runtime/pipeline.py`, `runtime/turns.py` and the event catalog/assembly/value
  modules expose the safe round output and failure type at the decision sites.
- `device/session.py`, `composition.py` and `app.py` retain the shutdown and
  ownership ordering while wiring the deepened collaborators. `app.py`
  registers only successfully built exporters with telemetry before session
  admission.
- `deploy/telemetry/` adds the direct Jaeger and Collector fanout examples,
  pinned configurations, dummy environment template and smoke helpers.
- `.github/workflows/vinga-server.yml` validates both configurations and runs
  the source-tree direct Jaeger and two-receiver Collector smoke on pull
  requests. Its existing image job may repeat the direct check after building.
- `vinga-server/README.md` owns the exporter contract and configuration
  consequences. `docs/deployment.md` owns runnable direct and fanout
  walkthroughs. `docs/architecture/observability-surfaces.md` owns the updated
  surface map. `docs/README.md` routes readers to the deployment procedures.
  The two server config examples link to the runnable add-ons without copying
  their credentials. M2 amends the content-and-telemetry ADR because its
  metadata-only fold and separate content-span mechanism become false. The
  replacement invariant is: the event fold never reads content; a fold-made
  span may receive content only from a successfully registered content
  exporter, under that class's explicit flag, through a server-minted
  correlation identity and an allowlisted projection. The observability map
  derives its current-surface wording from that policy.
- `docs/reference/server-config.md`, `docs/reference/domain-config.md` and
  `docs/reference/events.md` are regenerated only from their generators. The
  first two change with the widened `export_llm_input` description even though
  no field is added; the events reference changes with the safe correlation and
  failure metadata.
- Each releasable milestone carries its own issue-prefixed changelog fragment,
  because every merge publishes a valid intermediate release. M1 records real
  failed operations and recap tracing. M2 records the wider LLM-output
  disclosure and reporting change under `### Changed`, the new canonical
  content locations under `### Changed`, and removal of the `transcript` and
  `llm_input` span names under `### Removed`. Its Changed entry tells
  direct-to-Langfuse operators that their path remains supported and tells
  saved-view owners to select `turn` and `llm` instead. Its Removed entry also
  names the row-only index, id and time attributes and the legacy
  session-parent fallback. Per-agent legs are explicitly retained on
  `vinga.turn.legs`, not silently lost. M3 records the supported Jaeger and
  Collector paths under `### Added`. `CHANGELOG.md` is never edited.

## Tests and verification

Existing telemetry, transcript, LLM-input, handover, tool and stub-receiver
fixtures are extended rather than replaced.

- Unit pins freeze the current stable operation names, one-turn-one-trace
  topology, session link, all canonical standard attributes, timestamps and
  content-off absence before the internal span-lifecycle changes.
- Failure tests falsify each new claim first: remove the failure fold and prove
  ASR, LLM, TTS and tool cases fail because the real span, `ERROR` status or
  safe `error.type` is absent. Credential-shaped exception messages are absent
  from the span, event, log record message, typed arguments and exception
  chains in both log formats.
  They also assert that no `provider_failed` or failed `tool_call` span event
  duplicates the real failed operation.
- Held-turn unit tests pin original span identity, explicit end time,
  sampled and unsampled decisions, exact-once end, metadata-only release after every
  drop reason, the 4,097th-record oldest-finished overflow and shutdown races. The concurrency test
  is run at least 100 times because one passing interleaving proves nothing.
  It asserts one successful pop and one `Span.end` across worker, overflow and
  shutdown contenders.
- The pull-request unit lane imports the application with the OTel packages
  hidden and pins the existing one-sentence missing-extra refusal. The slim
  container boot remains an unchecked workflow-dispatch or post-merge image
  verification item because the image job does not run on pull requests.
- A live-session test settles several turn acknowledgements without closing
  the session and proves each earlier root is already on the OTLP wire. A
  pending false acknowledgement releases only that root metadata-only, and an
  ungraceful-exit simulation proves generation spans were never held.
- Transcript tests assert the actual `turn` root, not a child, carries the
  acknowledged heard/reply pair; ordinary, empty, cancelled and handover turns
  are covered. A handover with two independently acknowledged rows proves
  ordered, exactly-once composition; one false acknowledgement proves the
  whole group releases metadata-only. There is no span named `transcript`. A
  flag-on, conversation-off build proves no exporter registers and the root
  ends without delay.
- LLM tests assert every successful, tool-only, tool-result, handover, recap
  and failed round has one actual `llm` span with its own matched standard
  input/output JSON. All three content attributes and both vinga extensions
  are absent when the flag is off. Bounds drop a whole pair, never half and
  never its metadata span. Two turns with repeated reply-local ordinals, plus
  an oversized round between retained rounds, prove that only the opaque
  invocation id performs the join. There is no span named `llm_input`.
  A recap outer-timeout test proves one failed `llm` span receives the staged
  recap input and that neither a duplicate failure event nor an orphaned
  snapshot remains.
- The existing OTLP protobuf integration receiver compares decoded wire data,
  not SDK objects, for topology, status, standard attributes and both flag
  combinations. A multi-round tool and handover conversation proves ordinal
  pairing end to end. Its receiver records body sizes and enforces the 3 MiB
  ceiling while eight maximal spans prove the worst-case batch.
- Static deployment tests resolve both compose graphs, validate the exact
  committed Collector configuration with the pinned image, assert that common
  masking and the graph's only sampler precede both `forward` connectors, and
  prove neither sink pipeline contains either processor. They also prove Basic Auth, the v4
  ingestion header and Langfuse aliases exist only on the Langfuse boundary.
  The fully resolved fanout graph is also inspected service by service: the
  Collector has the dummy `LANGFUSE_*` names and the vinga service has none.
- A Docker-backed fanout smoke sends deterministic traces through the exact
  committed Collector configuration to two local OTLP receivers. With partial
  sampling it asserts a nonempty proper subset, identical trace-id populations,
  exact canonical projections, absence of the raw content and credential
  sentinels, presence of the same mask marker, and Langfuse-only headers and
  aliases.
- The direct Jaeger PR smoke runs the source-tree server through the existing
  integration fixture, drives the simulated conversation and queries Jaeger
  for the expected topology. A built-image repetition, if added, runs only in
  the non-PR image job. The
  live gate then sends one multi-round content-enabled conversation through
  the Collector to Jaeger and a real Langfuse v4 project, compares exact trace
  identifiers and canonical projections, and records the UI/API observations
  and commands in the implementation doc. CI uses local protocol receivers
  because repository secrets must not be required on pull requests.
- A direct Langfuse v4 live gate sends Basic Auth and the ingestion-version
  header through `OTEL_EXPORTER_OTLP_HEADERS`, then verifies turn and generation
  rendering. It is checked only when actually run with a real project's
  credentials.
- Run `uv run ruff check .`, the distributed unit lane, integration tests,
  command-spelling census, generated-document drift checks, both compose
  resolutions and the new telemetry smoke. Any image or real-Langfuse gate
  that cannot be executed locally remains an unchecked PR verification item.

## Risks and mitigations

- **A content exporter can strand a canonical span.** Every terminal exporter
  outcome ends the held span, the ledger has its own bound,
  and telemetry shutdown drains remaining records metadata-only before the SDK
  provider shuts down.
- **An ungraceful exit can lose a root waiting for its store acknowledgement.**
  This is limited to currently pending turns rather than the whole session;
  acknowledged earlier roots and every LLM span have already ended. The
  4,096-turn ledger bounds the exposure, and the flag prose plus changelog state
  it. A graceful shutdown ends any remainder metadata-only.
- **A delayed root can arrive after its children.** OTLP permits this and both
  target backends join by identifiers. The direct and dual-receiver smokes
  deliberately observe children before release, then assert the final topology.
- **Content buffering can grow with a long session.** Existing request/session
  budgets remain, telemetry's held-turn map has a flat 4,096-span process cap, and
  overflow ends the oldest logically finished span metadata-only rather than
  losing operation metadata or selecting by session state.
- **A sampling decision can fork.** Original trace flags and state are retained
  exactly. The fanout example fixes the source to `always_on` and makes one
  trace-id-based Collector sampler the only population decision before split.
  The guide states that this samples independent turn traces rather than whole
  sessions and defaults the walkthrough to 100 percent.
- **Masking can protect one spelling but miss its alias.** Vinga mints the
  direct-Langfuse aliases before the Collector. The common processor therefore
  masks canonical content keys and their content-bearing aliases explicitly.
  The sentinel test scans both complete protobuf payloads, not selected
  attributes.
- **The two exporters can store different populations after an outage.** The
  guide distinguishes identical attempted populations from transactional
  delivery and gives a trace-id comparison procedure rather than claiming
  atomic fanout.
- **Deleting Langfuse aliases can regress its UI.** The live v4 gate verifies
  standard generation rendering and the Collector branch derives only the
  turn-root aliases it demonstrably needs. A required additional alias is
  documented at that branch and tested as a derivation from a canonical value,
  never restored to core instrumentation by precaution.
- **A tool failure can leak far-side prose.** Classification occurs in each
  `except` or returned-error arm and carries only a class name or closed token.
  Sentinel tests inspect records, logs, OTLP bodies and exception chains.

## Milestones

- [x] **[M1, canonical metadata and real failed operations.](2026-09-14-telemetry-backend-parity-implementation.md#m1-canonical-metadata-and-real-failed-operations)**
  (PR #524) Preserve original
  trace flags and state, freeze the canonical topology and attribute contract,
  add the server-minted generation invocation id at reply and recap assembly,
  make successful and failed recap calls symmetric real `llm` spans, add
  canonical `error.type` beside the existing ASR compatibility key, and turn
  failed LLM/TTS/tool work into real `ERROR` spans with safe
  `error.type`, pin the existing Langfuse usage aliases as derived compatibility
  output rather than canonical metadata, and regenerate the event reference.
  Design footprint: deepen `telemetry.py` and
  the existing runtime/event seams; no new module. Documentation footprint:
  update the exporter contract in `vinga-server/README.md` and the exported
  traces entry in the observability map, plus an M1 changelog fragment; no
  deployment procedure changes yet.
- [x] **[M2, content on the operations it describes](2026-09-14-telemetry-backend-parity-implementation.md#m2-content-on-the-operations-it-describes).** (PR #525) Add the bounded held-turn
  lifecycle beside telemetry's existing retention maps, enrich acknowledged
  turn roots and paired generation spans,
  remove the `transcript` and `llm_input` observation topology, and prove flags
  off, flags on, bounds, tools, handover, recap, failures and teardown on the
  decoded OTLP wire. Design footprint: deepen `telemetry.py`, the two existing
  content exporters and pipeline content seams; no new module. Documentation
  footprint: widen the flag's source description in `config/models.py` to name
  generated and withheld model output, update the server exporter contract and
  LLM-input row of the observability map; replace the `export_transcripts`
  field description, `TelemetryConfig` docstring and exported-transcripts
  observability section that describe per-row child spans and a session-parent
  fallback; and regenerate both configuration references plus examples whose
  current post-close observation descriptions become false. The changelog
  announces the existing flag's wider disclosure and topology migration in an
  M2 fragment.
- [ ] **M3, direct Jaeger and one processed fanout.** Add the pinned direct
  Jaeger and Collector examples, common masking and sampling, boundary-only
  Langfuse adaptation, Basic Auth and v4 ingestion header, static validation,
  direct Jaeger smoke, dual-receiver parity smoke, live Jaeger/Langfuse
  walkthrough, deployment and index documentation, configuration-example
  pointers, changelog fragment and final implementation record. Design
  footprint: no server module; `deploy/telemetry/` owns the optional deployment
  graph so the server stops knowing backend topology or credentials.
  Documentation footprint: `docs/deployment.md`, `docs/README.md`, the server
  README and observability map describe the supported current paths and their
  non-transactional limit, with an M3 changelog fragment.

## Plan review round

External review of commit `afcf50c8`: Claude CLI 2.1.270, read-only tool set,
model `claude-opus-5`, 2026-09-14, runtime 5m18s.

1. **P1: removing Langfuse aliases in M1 breaks the only Langfuse path that
   exists today, and M3 never restores it.** Direct-to-Langfuse deployments
   depend on the current input/output and `usage_details` aliases, especially
   for ASR and TTS pricing. The plan must either keep them in core or declare
   and fully document a breaking Collector-only migration with every mapping.

   *Resolution:* Direct-to-Langfuse remains supported.
   Existing input/output and usage aliases stay as derived OTLP export-boundary
   compatibility fields, while canonical attributes remain authoritative. The
   Collector preserves them only on the Langfuse branch.
2. **P1: the recording-reference span is on the shared trace pipeline and
   carries Langfuse aliases.** `reference_media` uses the shared tracer, so the
   plan's claims that media never joins the common trace stream and that Jaeger
   sees no Langfuse alias are false. The capture exception and Jaeger-side
   filtering must be explicit.

   *Resolution:* The plan now names `reference_media` and its `capture` span as
   the one backend-specific OTLP exception. The Collector drops that entire
   span and all `langfuse.*` attributes from the Jaeger branch, while the media
   bytes remain on the separate Langfuse REST and object-storage path.
3. **P1: there is no shared round key.** `vinga.llm.round` resets per reply,
   while the staged content index is session-local and advances even for
   dropped rounds. A server-minted correlation id visible at both seams is
   required.

   *Resolution:* M1 now mints a session-unique opaque invocation id at each
   generation assembly point and carries it through the declared event and
   content seams as `vinga.llm.invocation.id`. The existing round number stays
   reply-local and tests deliberately repeat it across turns and content drops.
4. **P1: successful recap generations have no `llm` span.** The recap path
   stages a request but emits no `llm_round`; a failed recap would gain a span
   through `provider_failed`, making the asymmetry worse. The plan must decide
   and instrument recap explicitly.

   *Resolution:* M1 now makes recap a normal semantic generation. It mints the
   same invocation id, emits `llm_round` on success and `provider_failed` on
   failure, and marks the span with the declared `recap` purpose so M2 has one
   actual operation to enrich in either outcome.
5. **P1: tying canonical-root release to content delivery can lose root spans
   and leaves no-release paths.** No store, no trace, builder no-op, an
   undelivered page, and stopped delivery can all bypass later rows. Canonical
   metadata release must be independent from content delivery failure and have
   a deadline or close trigger.

   *Resolution:* The design now holds the original live span before end rather
   than intercepting an ended record. Class settlement is triggered by session
   close and every enumerated exporter terminal path, with telemetry shutdown
   as the final backstop. Ending the span puts it on the ordinary batch path;
   bounded flush failure changes the outcome report but cannot delete or
   rebuild the canonical span.
6. **P1: a handover turn is two store rows that can straddle pages.** The plan
   does not say how those rows become one ordered root output before exactly-once
   release. Grouping and page-boundary carryover must be specified.

   *Resolution:* Transcript projection now groups consecutive rows by
   utterance, carries the last group across keyset pages, and releases only
   when the next utterance or EOF proves completeness. It chooses the first
   heard value, concatenates replies in row order, rejects conflicting input,
   and releases an incomplete group metadata-only on later-page failure.
7. **P2: registering a router beside the batch processor exports held spans
   twice.** OpenTelemetry calls every registered processor. The router must own
   the ordinary batch processor and be the only provider registration.

   *Resolution:* The routing processor has been deleted from the design. The
   original SDK span remains live until content settlement, then its one
   `Span.end(end_time=...)` call reaches the unchanged, sole batch processor.
   A provider-wiring pin asserts that only the existing batch processor is
   registered.
8. **P2: the deferred module can break no-extra and slim-image boots.** It must
   not import OpenTelemetry at module scope and must use the existing lazy SDK
   resolution pattern, with the slim boot pinned.

   *Resolution:* The module now accepts opaque spans and SDK callbacks only
   after `_import_sdk()` succeeds, with no module-scope SDK import. M2 adds the
   no-extra import/refusal tests and the existing slim-image boot to its gates.
9. **P2: telemetry is constructed before either content exporter.** The plan
   must name a pre-admission registration call and hold spans only for an
   exporter that was actually built, never on a config flag alone.

   *Resolution:* The plan now names two telemetry registration methods, called
   by `app.py` only after the corresponding builder returns a non-null exporter
   and before the lifespan admits sessions. A documented transcript no-op does
   not register and therefore never delays turn roots.
10. **P2: branch-specific Collector processing needs a connector.** One
    receiver pipeline with two exporters cannot add aliases to only one branch;
    two independent pipelines sample twice. The plan must name a Contrib
    `forward` connector and assert one sampler in the graph.

    *Resolution:* The deployment graph now names two Contrib `forward`
    connectors from one commonly processed pipeline into separate Jaeger and
    Langfuse sink pipelines. Static tests count exactly one sampler and prove
    all masking occurs before both connectors.
11. **P2: generated output widens `export_llm_input`.** The flag prose and
    generated server reference must change, including the fact that withheld
    model text leaves, and the changelog must announce that widening.

    *Resolution:* M2 now updates the `export_llm_input` source description,
    both generated configuration references and the observability ladder to
    name generated output, including withheld text. The changelog records the
    disclosure widening under `### Changed`.
12. **P2: a built server image does not exist on pull-request runs.** The PR
    direct-Jaeger smoke must run the server from source in the integration lane;
    an image variant can only run in the existing non-PR image job.

    *Resolution:* The PR gate now starts the source-tree server with the
    existing integration fixture against containerized Jaeger. A built-image
    repetition is optional and explicitly limited to the non-PR image job.
13. **P2: an Added-only changelog is incomplete.** Removing the `transcript`
    and `llm_input` span names and moving their content needs Removed and
    Changed entries with an upgrade note.

    *Resolution:* The fragment now has Added, Changed and Removed footprints.
    It names the disclosure widening, replacement span names and saved-view
    upgrade action while affirming direct-to-Langfuse compatibility.
14. **P2: the content-and-telemetry ADR must be amended.** Its current
    metadata-only fold and separate content-span rule becomes false. It needs a
    replacement invariant that content reaches a fold-made span only through a
    registered, flagged content exporter keyed by server-minted identity.

    *Resolution:* M2 now carries a required ADR amendment. The new checkable
    invariant keeps events content-free and permits content on a fold-made span
    only through a built, flagged exporter, a server identity and an allowlist.
15. **P3: the deferred module's deletion-test reason is wrong.** Its caller is
    already the SDK-owning module. The real deep responsibility is deciding
    when an ended span remains enrichable and when it must be released exactly
    once across both exporters and shutdown.

    *Resolution:* The deletion-test argument now rests only on the shared
    lifecycle decision: the enrichable interval and one terminal end across
    telemetry, both content exporters and shutdown. SDK mechanics and file
    length are no longer offered as the module's reason to exist.
16. **P3: trace-id sampling samples turns, not sessions.** Session and turn
    traces have independent ids, so partial sampling can leave either side of
    their link absent. The deployment guide must say so.

    *Resolution:* The contract now states that ratio sampling preserves or
    drops independent turn traces, that links can have a missing peer, and that
    `session.id` cannot recover dropped data. Live walkthroughs default to 100
    percent; deterministic partial sampling remains an automated parity test.
17. **P3: the ledger bound is not actually derived.** The existing unlimited
    `max_sessions`, per-session turn count and byte-based LLM bounds do not
    yield a global span count. The plan must state the formula or flat cap and
    the overflow cost.

    *Resolution:* The ledger now has the explicit flat process cap 4,096. The
    4,097th hold ends the globally oldest logically finished span
    metadata-only and reports that class's content omission; it never targets
    an operation still running or infers a bound from `max_sessions`.

Verdict: not ready. Findings 1 through 6 are load-bearing; findings 7, 10 and
the rest of the P2 set require concrete amendments before implementation.

## Plan re-review round

External re-review of amended commit `c89c58db`: Claude CLI 2.1.270,
read-only tool set, model `claude-opus-5`, 2026-09-14, runtime 9m08s.

1. **P1: alias ownership contradicts itself and the masking claim is false.**
   Vinga must keep aliases for direct Langfuse compatibility, so the Collector
   common processor sees raw canonical values and raw aliases. The plan must
   give aliases one home and mask both forms before fanout.

   *Resolution:* Vinga's OTLP mapping is now the single alias-minting home, as
   direct Langfuse compatibility requires. The common Collector processor
   explicitly masks every canonical content key and each derived
   content-bearing alias before either forward connector; the Langfuse sink
   only preserves them and the Jaeger sink drops them.
2. **P1: the shared batch processor cannot preserve per-content delivery
   answers.** Today's processorless private exporter reports on the exact
   content batch. A process-wide `force_flush` neither attributes rejection nor
   prevents a saturated queue from dropping the span. The plan must keep an
   answerable transport or explicitly retire and replace the guarantee.

   *Resolution:* The plan explicitly retires the private exact-batch answer and
   `undelivered` content reason. Content events now report attachment or
   pre-queue omission, while the unchanged bounded BatchSpanProcessor owns
   downstream delivery for canonical spans. The config, event reference,
   observability map and changelog carry that reporting migration.
3. **P1: holding every turn and LLM span until session close delays live
   observability and loses the whole session's canonical metadata on SIGKILL.**
   The trade must be explicit or the hold must be per operation and shorter.

   *Resolution:* LLM spans now settle synchronously at each generation end,
   and a turn root waits only for that turn's acknowledgement. Tests prove
   earlier roots leave during a still-open session. The config prose, risk and
   changelog explicitly state that an ungraceful exit can lose only roots still
   awaiting storage, while graceful shutdown releases them metadata-only.
4. **P1: composing with the root stack can put Langfuse credentials into the
   vinga container.** The root `.env` is mounted whole by vinga. The telemetry
   stack needs a distinct explicit env file and a resolved-environment test.

   *Resolution:* The overlay now attaches root-relative
   `deploy/telemetry/.env` only to the Collector and uses Collector-side
   `${env:...}` expansion, with no credential interpolation in Compose. The
   walkthrough never adds Langfuse names to the root `.env`, and a resolved
   graph test asserts no `LANGFUSE_*` name enters vinga's environment.
5. **P2: recap timeout bypasses `provider_failed`.** Cancellation becomes
   `TimeoutError` only outside `_watched_stream`, after the helper's catch, so
   the plan must instrument this third recap outcome explicitly.

   *Resolution:* The recap's outer `except TimeoutError` now emits the one safe
   provider failure with its invocation id, recap purpose and elapsed time
   before preserving the existing no-recap return. A regression test proves
   the staged request lands on that failed span and is not stranded.
6. **P2: using ordinary `_llm_round_done` for recap changes stored turn
   accounting and metrics.** The plan must decide whether recap advances the
   reply ordinal or `TurnRecord.round_done`, and document any metrics change.

   *Resolution:* Recap emits the semantic event through a helper that does not
   advance the reply ordinal or call `round_done`; its `round` field is absent
   and `purpose=recap` identifies it. Stored turn totals and metrics views stay
   byte-for-byte unchanged, while the changelog Added entry names the newly
   visible recap span.
7. **P2: ASR failure still lacks canonical `error.type`.** M1 names only the
   other three stages even though the issue and contract require all four.

   *Resolution:* M1 now writes `error.type` on failed ASR spans beside the
   retained `vinga.asr.error` compatibility attribute, and the same four-stage
   unit table proves status plus safe type for every semantic failure.
8. **P2: `telemetry_deferred.py` still fails the deletion test.** Its exporters
   call only through `Telemetry`, and telemetry already owns the same bounded
   map shape. Fold it in unless a real second responsibility exists.

   *Resolution:* The new module is removed from the plan. `Telemetry` owns the
   held-turn map beside its three existing retention structures, and its public
   methods remain the sole worker interface. This supersedes the first review's
   module-resolution note while retaining the no-extra regression gates.
9. **P2: M2 misses the transcript field prose, `TelemetryConfig` docstring and
   exported-transcripts observability section that its mechanism falsifies.**

   *Resolution:* M2's footprint now names all three maintained sources and the
   generated references they feed. The transcript field and class docstring
   lose the child-span and fallback claims, and the observability section is
   rewritten around acknowledged per-turn root enrichment.
10. **P2: the changelog omits removed transcript attributes, per-agent leg
    attribution and the removed session-parent fallback.** The plan must keep
    or explicitly remove each capability.

    *Resolution:* Per-agent attribution is retained as canonical
    `vinga.turn.legs` on the root, with the existing Langfuse alias derived from
    it. The plan and Removed entry now name the three row-only attributes and
    the unaddressable legacy-row fallback that genuinely disappear.
11. **P2: shared batching removes the transcript page's OTLP body bound.** A
    batch can combine many unbounded transcript values and 256 KiB LLM values.
    The replacement needs a per-content and per-export body bound with a wire
    assertion.

    *Resolution:* Every turn and generation now has one 256 KiB combined
    content ceiling, and the shared processor exports at most eight spans per
    request. A worst-case protobuf serialization and the integration receiver
    both enforce a 3 MiB body ceiling.
12. **P2: direct-to-Langfuse remains supported but never receives the v4
    ingestion header in the plan.** Its README recipe and live gate must cover
    both Basic Auth and the version header.

    *Resolution:* The server README now owns the exact combined
    `OTEL_EXPORTER_OTLP_HEADERS` template with Basic Auth and ingestion version
    4. The live v4 walkthrough exercises the direct path separately from the
    Collector path before compatibility is claimed.
13. **P3: slim-image boot is not a pull-request gate.** Only the no-extra unit
    refusal runs on PRs; image verification is workflow-dispatch or post-merge.

    *Resolution:* M2's PR gate is now only the no-extra import and refusal unit
    test. The slim-image boot is listed honestly as an unchecked dispatch or
    post-merge image verification item.
14. **P3: the cross-thread deferred map has no stated concurrency boundary.**
    The plan must name its lock and the point at which the session loop hands
    sole span ownership to it.

    *Resolution:* `_held_turns_lock` now owns the map and terminal handoff. The
    session loop clears its live reference at `reply_finished`; contenders pop
    under the lock, and only the winner mutates and ends the span outside it.
    Repeated race tests prove one pop and one end.
15. **P3: the plan does not say whether `provider_failed` remains as a duplicate
    span event.** LLM and TTS must match the ASR and tool precedent: one failed
    span, no duplicate event.

    *Resolution:* M1 now states the folds are substitutive. Each failed ASR,
    LLM, TTS or tool operation produces one failed span and no duplicate turn
    event, with unit and decoded-wire absence assertions.

Verdict: not ready. Findings 1 through 4 are load-bearing; findings 5 through
12 require concrete amendments, and findings 13 through 15 should be folded
in while the design is open.
