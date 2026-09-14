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
ingestion headers only on that branch. Recording upload remains the existing
Langfuse-only media path and never joins the shared traces pipeline.

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
  stays separate and opt-in. Jaeger receives neither media nor upload
  references.
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
valid across OTLP destinations. The canonical span records therefore have to
be held, boundedly, until the content exporter has either supplied the
authorized content or declared it absent.

### The event catalog remains metadata-only

The event tap is the source of span timing and safe metadata. It intentionally
does not carry transcripts, LLM requests, model output, tool arguments or tool
results. This plan does not weaken that boundary. Content continues through
the dedicated collaborators that already exist, and the telemetry layer joins
it to an ended span only by server-minted session, utterance and round
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

Every span keeps its original trace id, span id, parent span id, links,
start/end timestamps, status, trace flags and trace state. Every span keeps
`session.id`; turn and child spans keep the existing utterance correlation.
The Collector may add Langfuse-only aliases after the common processing
pipeline, but may not rewrite any of those facts or any canonical attribute.

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

The Langfuse Collector branch copies these already-masked values to
`langfuse.observation.input` and `langfuse.observation.output` so its UI renders
the turn root as an observation. That copy is an export adapter, not a second
source of truth. Direct Jaeger shows the canonical vinga names.

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
The input and output of one logical round share its existing session-local
round index. The first-token retry does not create a second logical round or a
second content snapshot. A failed round retains its request and any partial
semantic output admitted before failure, and has no invented completion.

The existing per-request, per-session and maximum-round bounds apply to the
combined canonical content. A round over the per-request bound is dropped
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

`provider_failed` gains only the safe ordinal needed to pair an LLM failure
with its staged logical round. The event remains content-free. The tool-call
event gains only its already-decided error type, and the `tool` span maps it to
status and `error.type`.

## The deferred-span seam

A new `vinga_server.telemetry_deferred` module owns the lifecycle of canonical
span records whose optional content is decided after `Span.end()`. Its callers
stop knowing how an OpenTelemetry `ReadableSpan` becomes an immutable retained
record, how the original sampling identity is preserved, how records are
correlated, and how a held record is released through the bounded direct OTLP
delivery path.

The module provides one routing span processor in front of the ordinary batch
processor. Metadata-only spans pass straight through. When the corresponding
content exporter exists, ended `turn` and `llm` spans are converted to
immutable SDK span data and held by their server-minted correlation key. The
transcript and LLM input workers later provide allowlisted attributes or a
metadata-only release. The module creates one final record with the original
identity, timing, topology, resource, instrumentation scope, events, links,
status, trace flags and trace state, plus only those supplied attributes. It
exports that record exactly once.

The ledger is globally bounded. Its fixed bound is derived from the existing
session and LLM-round bounds rather than added as operator configuration. On
overflow it releases the oldest held record metadata-only and counts the
content omission in the owning exporter's existing closed outcome. Session
close, exporter refusal, queue overflow, rendering failure and shutdown all
release every addressable record exactly once. Unknown or already-released
keys are an explicit non-delivery result, never a duplicate span. Unit tests
exercise each transition and repeatedly race content completion with
shutdown.

`transcript_export.py` keeps responsibility for waiting on the conversation
writer's acknowledgement, paging the store, bounded admission, delivery
reporting and retention truth. Instead of asking telemetry to mint a
`transcript` span, it supplies `vinga.turn.input` and
`vinga.turn.output` to the held turn root. `llm_input_export.py` deepens its
existing staging responsibility to pair schema-shaped input and output for
each round, enforce the byte bounds over the pair, and release the matching
held `llm` record. Separate `transcript` and `llm_input` span creation is
deleted.

This is not a wrapper beside telemetry. It is the one owner of delayed span
lifecycle, exact identity preservation and release. Inlining it into
`telemetry.py` would put a second queueing and retention subsystem inside the
event-to-span fold, which is the second responsibility the module removes.

## Fanout, masking and backend adaptation

The committed deployment examples live under `deploy/telemetry/` and compose
with the root trial stack. They do not alter the production deployment
artifacts or make observability mandatory.

The direct example runs a pinned Jaeger v2 image, exposes its UI on loopback,
accepts OTLP HTTP/protobuf on 4318 and points vinga directly at it. The example
sets the SDK sampler explicitly to `always_on`; no Collector exists on this
path. A smoke drives the built server through the existing simulated
conversation, shuts it down cleanly, polls Jaeger's query API under a fixed
deadline and asserts the session, turn and semantic children.

The fanout example sends vinga to a pinned Collector Contrib image. Its graph
has one common traces pipeline with, in order, content masking, one
trace-id-based probabilistic sampler and batching. Only after those processors
does it split into Jaeger and Langfuse branches. Vinga is explicitly
`always_on` in this example so the Collector sampler is the single population
decision. Both branches receive the exact processed records. The Langfuse
branch derives its observation aliases from the already-masked canonical
attributes, then uses OTLP/HTTP with the Basic Auth client extension and the
literal `x-langfuse-ingestion-version: 4` header. The Jaeger branch receives no
Langfuse alias, credential or ingestion header.

The sample mask covers every canonical content-bearing attribute introduced
here before the split. It includes a documented email-shaped rule so an
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

Collector Langfuse credentials live only in an ignored environment file made
from `deploy/telemetry/.env.example`. They never enter vinga configuration,
the vinga container or a committed rendered compose file. The fanout smoke
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
  loses Langfuse content and usage aliases and delegates held-span lifecycle.
- New `vinga_server/telemetry_deferred.py` owns immutable delayed span records,
  original trace state, bounded retention, enrichment and exactly-once
  release. Its callers stop knowing OpenTelemetry SDK span-data mechanics.
- `transcript_export.py` keeps store acknowledgement, paging, admission and
  outcome reporting, but enriches turn roots rather than creating observations.
- `llm_input_export.py` keeps neutral-seam rendering and byte budgets, adds
  schema-shaped semantic output pairing, and enriches generation spans rather
  than creating observations.
- `runtime/pipeline.py`, `runtime/turns.py` and the event catalog/assembly/value
  modules expose the safe round output and failure type at the decision sites.
- `device/session.py`, `composition.py` and `app.py` retain the shutdown and
  ownership ordering while wiring the deepened collaborators.
- `deploy/telemetry/` adds the direct Jaeger and Collector fanout examples,
  pinned configurations, dummy environment template and smoke helpers.
- `.github/workflows/vinga-server.yml` validates both configurations and runs
  the direct Jaeger and two-receiver Collector smoke on pull requests.
- `vinga-server/README.md` owns the exporter contract and configuration
  consequences. `docs/deployment.md` owns runnable direct and fanout
  walkthroughs. `docs/architecture/observability-surfaces.md` owns the updated
  surface map. `docs/README.md` routes readers to the deployment procedures.
  The two server config examples link to the runnable add-ons without copying
  their credentials. The content-and-telemetry ADR receives an amendment only
  if implementation changes a standing policy rather than its mechanism.
- `docs/reference/server-config.md`, `docs/reference/domain-config.md` and
  `docs/reference/events.md` are regenerated only from their generators. The
  first two should remain byte-identical because no configuration field is
  added; the events reference changes with the safe failure metadata.
- `changelog.d/523-telemetry-backend-parity.md` records the completed operator
  feature under `### Added`; `CHANGELOG.md` is not edited.

## Tests and verification

Existing telemetry, transcript, LLM-input, handover, tool and stub-receiver
fixtures are extended rather than replaced.

- Unit pins freeze the current stable operation names, one-turn-one-trace
  topology, session link, all canonical standard attributes, timestamps and
  content-off absence before the internal span routing changes.
- Failure tests falsify each new claim first: remove the failure fold and prove
  ASR, LLM, TTS and tool cases fail because the real span, `ERROR` status or
  safe `error.type` is absent. Credential-shaped exception messages are absent
  from the span, event, log record message, typed arguments and exception
  chains in both log formats.
- Deferred-ledger unit tests pin immutable span identity, original sampled and
  unsampled decisions, exact-once release, metadata-only release after every
  drop reason, oldest-first overflow and shutdown races. The concurrency test
  is run at least 100 times because one passing interleaving proves nothing.
- Transcript tests assert the actual `turn` root, not a child, carries the
  acknowledged heard/reply pair; ordinary, empty, cancelled and handover turns
  are covered. There is no span named `transcript`.
- LLM tests assert every successful, tool-only, tool-result, handover, recap
  and failed round has one actual `llm` span with its own matched standard
  input/output JSON. All three content attributes and both vinga extensions
  are absent when the flag is off. Bounds drop a whole pair, never half and
  never its metadata span. There is no span named `llm_input`.
- The existing OTLP protobuf integration receiver compares decoded wire data,
  not SDK objects, for topology, status, standard attributes and both flag
  combinations. A multi-round tool and handover conversation proves ordinal
  pairing end to end.
- Static deployment tests resolve both compose graphs, validate the exact
  committed Collector configuration with the pinned image, assert that common
  masking and sampling precede both branches, and prove Basic Auth, the v4
  ingestion header and Langfuse aliases exist only on the Langfuse boundary.
- A Docker-backed fanout smoke sends deterministic traces through the exact
  committed Collector configuration to two local OTLP receivers. With partial
  sampling it asserts a nonempty proper subset, identical trace-id populations,
  exact canonical projections, absence of the raw content and credential
  sentinels, presence of the same mask marker, and Langfuse-only headers and
  aliases.
- The direct Jaeger smoke runs the built server image, drives the existing
  simulated conversation and queries Jaeger for the expected topology. The
  live gate then sends one multi-round content-enabled conversation through
  the Collector to Jaeger and a real Langfuse v4 project, compares exact trace
  identifiers and canonical projections, and records the UI/API observations
  and commands in the implementation doc. CI uses local protocol receivers
  because repository secrets must not be required on pull requests.
- Run `uv run ruff check .`, the distributed unit lane, integration tests,
  command-spelling census, generated-document drift checks, both compose
  resolutions and the new telemetry smoke. Any image or real-Langfuse gate
  that cannot be executed locally remains an unchecked PR verification item.

## Risks and mitigations

- **A content exporter can strand a canonical span.** Every terminal exporter
  outcome releases the held record, the ledger has its own oldest-first bound,
  and telemetry shutdown drains remaining records metadata-only before the SDK
  provider shuts down.
- **A delayed root can arrive after its children.** OTLP permits this and both
  target backends join by identifiers. The direct and dual-receiver smokes
  deliberately observe children before release, then assert the final topology.
- **Content buffering can grow with a long session.** Existing request/session
  budgets remain, the deferred record ledger adds a fixed global bound, and
  overflow loses content rather than operation metadata.
- **A sampling decision can fork.** Original trace flags and state are retained
  exactly. The fanout example fixes the source to `always_on` and makes one
  trace-id-based Collector sampler the only population decision before split.
- **Masking can protect one alias but miss its source.** The common processor
  masks the canonical names before aliases exist. The sentinel test scans both
  complete protobuf payloads, not selected attributes.
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

- [ ] **M1, canonical metadata and real failed operations.** Preserve original
  trace flags and state, freeze the canonical topology and attribute contract,
  turn failed LLM/TTS/tool work into real `ERROR` spans with safe
  `error.type`, remove backend-specific usage aliases from core telemetry, and
  regenerate the event reference. Design footprint: deepen `telemetry.py` and
  the existing runtime/event seams; no new module. Documentation footprint:
  update the exporter contract in `vinga-server/README.md` and the exported
  traces entry in the observability map; no deployment procedure changes yet.
- [ ] **M2, content on the operations it describes.** Add the bounded deferred
  span owner, enrich acknowledged turn roots and paired generation spans,
  remove the `transcript` and `llm_input` observation topology, and prove flags
  off, flags on, bounds, tools, handover, recap, failures and teardown on the
  decoded OTLP wire. Design footprint: add `telemetry_deferred.py`, whose
  callers stop knowing delayed SDK record identity and release, and deepen the
  two existing content exporters and pipeline content seams. Documentation
  footprint: update the server exporter contract, observability map, generated
  configuration prose and examples whose current post-close observation
  descriptions become false.
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
  non-transactional limit.
