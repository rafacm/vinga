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

A handover writes one row per conversation under the same utterance, so the
transcript exporter composes by utterance before it releases a root. Rows stay
in store-id order. The first non-null heard value becomes the one input; the
non-empty reply values are concatenated in row order for the one output. A
conflicting second heard value makes that utterance unreadable rather than
choosing one. Keyset paging carries the final utterance group into the next
page and releases it only after a different utterance or end of input proves
the group complete. If a later page cannot be read or flushed, the partial
group is released metadata-only and reported, never exported as half a reply.
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
provider operation, and emits the same `llm_round` event with a declared
low-cardinality purpose (`reply` or `recap`) on success. Failure carries that
identity and purpose through `provider_failed`. Both outcomes therefore create
one real `llm` span under the active turn, with `vinga.llm.purpose=recap`; the
successful and failed shapes are symmetric, and the staged recap request has
an operation to enrich.

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

`provider_failed` gains only the safe invocation id needed to pair an LLM
failure with its staged logical round. The event remains content-free. The tool-call
event gains only its already-decided error type, and the `tool` span maps it to
status and `error.type`.

## The deferred-span seam

A new `vinga_server.telemetry_deferred` module owns when an original recording
span whose logical end time is already known remains enrichable and when it
must be ended exactly once. Telemetry gives it live `turn` and `llm` spans,
their explicit end timestamps, and server-minted correlation keys. Content
exporters can add only an allowlisted attribute mapping, then the ledger ends
the original span with its retained timestamp. A metadata-only release adds
nothing and ends the same span. The ordinary registered batch processor is the
only path after `Span.end()`, so a content-delivery failure cannot remove a
canonical operation or create a duplicate identity.

The module has no module-scope OpenTelemetry import. It stores an opaque span
and calls only collaborators supplied after `telemetry._import_sdk()` has
succeeded, following the existing `_Sdk` lazy-resolution boundary. Importing
the application without the `otel` extra therefore remains valid, and the
existing one-sentence missing-extra refusal and slim-image boot are explicit
M2 regression checks.

Holding is enabled by registration of an exporter instance, never by a config
flag alone. After each builder returns a non-null collaborator, `app.py` calls
`telemetry.register_transcript_exporter()` or
`telemetry.register_llm_input_exporter()` immediately. Both calls occur during
application construction, before the lifespan can admit a device session. A
flag-on transcript no-op because conversation storage or text is off registers
nothing, so its turn roots end immediately. A held class has a close protocol:
when `session_closed` reaches
telemetry, the ledger marks that session closed; each registered content
exporter must then settle every held key in its class as enriched or
metadata-only. The ledger ends a class's remaining spans metadata-only when
that exporter reports any terminal path: no recorded store, no retained trace,
builder no-op, thread-start failure, queue overflow, unreadable rows,
undelivered or stopped flush, a page that prevents later pages being read, or
exporter shutdown. Telemetry shutdown is the final backstop and ends every
remaining span metadata-only before the SDK provider is shut down.

The content worker's bounded delivery result is preserved by ending the
enriched spans onto the ordinary batch processor and calling the existing
bounded `force_flush` from that worker. A failed or timed-out flush is reported
as today, but the spans have already entered the ordinary SDK path and are not
discarded or rebuilt. Reply-serving code never waits on a flush.

The ledger is globally bounded. On overflow it ends the selected held span
metadata-only and reports the content omission through the owning exporter's
existing closed outcome. Unknown or already-ended keys are an explicit
non-delivery result, never a second span. Unit tests exercise each transition,
all terminal paths above, and repeatedly race content completion with
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
literal `x-langfuse-ingestion-version: 4` header. The Jaeger branch drops every
`langfuse.*` attribute and the whole Langfuse-only `capture` span. It receives
no Langfuse credential or ingestion header.

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
  keeps the existing Langfuse aliases, including `usage_details`, as derived
  export-boundary compatibility attributes for direct-to-Langfuse deployments
  and delegates held-span lifecycle.
- New `vinga_server/telemetry_deferred.py` owns the lifecycle decision for
  logically finished live spans: the enrichable interval, explicit end time,
  bounded retention, class settlement and exactly-once end across both content
  exporters and shutdown. It imports no OpenTelemetry name at module scope.
- `transcript_export.py` keeps store acknowledgement, paging, admission and
  outcome reporting, but enriches turn roots rather than creating observations.
- `llm_input_export.py` keeps neutral-seam rendering and byte budgets, adds
  schema-shaped semantic output pairing, and enriches generation spans rather
  than creating observations.
- `runtime/pipeline.py`, `runtime/turns.py` and the event catalog/assembly/value
  modules expose the safe round output and failure type at the decision sites.
- `device/session.py`, `composition.py` and `app.py` retain the shutdown and
  ownership ordering while wiring the deepened collaborators. `app.py`
  registers only successfully built exporters with telemetry before session
  admission.
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
  content-off absence before the internal span-lifecycle changes.
- Failure tests falsify each new claim first: remove the failure fold and prove
  ASR, LLM, TTS and tool cases fail because the real span, `ERROR` status or
  safe `error.type` is absent. Credential-shaped exception messages are absent
  from the span, event, log record message, typed arguments and exception
  chains in both log formats.
- Deferred-ledger unit tests pin original span identity, explicit end time,
  sampled and unsampled decisions, exact-once end, metadata-only release after every
  drop reason, oldest-first overflow and shutdown races. The concurrency test
  is run at least 100 times because one passing interleaving proves nothing.
- Transcript tests assert the actual `turn` root, not a child, carries the
  acknowledged heard/reply pair; ordinary, empty, cancelled and handover turns
  are covered. A handover whose two rows straddle the 256-row page boundary
  proves carryover and ordered, exactly-once composition; a failed following
  page proves the partial group releases metadata-only. There is no span named
  `transcript`. A flag-on, conversation-off build proves no exporter registers
  and the root ends without delay.
- LLM tests assert every successful, tool-only, tool-result, handover, recap
  and failed round has one actual `llm` span with its own matched standard
  input/output JSON. All three content attributes and both vinga extensions
  are absent when the flag is off. Bounds drop a whole pair, never half and
  never its metadata span. Two turns with repeated reply-local ordinals, plus
  an oversized round between retained rounds, prove that only the opaque
  invocation id performs the join. There is no span named `llm_input`.
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
  outcome ends the held span, the ledger has its own bound,
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
  add the server-minted generation invocation id at reply and recap assembly,
  make successful and failed recap calls symmetric real `llm` spans,
  turn failed LLM/TTS/tool work into real `ERROR` spans with safe
  `error.type`, pin the existing Langfuse usage aliases as derived compatibility
  output rather than canonical metadata, and regenerate the event reference.
  Design footprint: deepen `telemetry.py` and
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
11. **P2: generated output widens `export_llm_input`.** The flag prose and
    generated server reference must change, including the fact that withheld
    model text leaves, and the changelog must announce that widening.
12. **P2: a built server image does not exist on pull-request runs.** The PR
    direct-Jaeger smoke must run the server from source in the integration lane;
    an image variant can only run in the existing non-PR image job.
13. **P2: an Added-only changelog is incomplete.** Removing the `transcript`
    and `llm_input` span names and moving their content needs Removed and
    Changed entries with an upgrade note.
14. **P2: the content-and-telemetry ADR must be amended.** Its current
    metadata-only fold and separate content-span rule becomes false. It needs a
    replacement invariant that content reaches a fold-made span only through a
    registered, flagged content exporter keyed by server-minted identity.
15. **P3: the deferred module's deletion-test reason is wrong.** Its caller is
    already the SDK-owning module. The real deep responsibility is deciding
    when an ended span remains enrichable and when it must be released exactly
    once across both exporters and shutdown.
16. **P3: trace-id sampling samples turns, not sessions.** Session and turn
    traces have independent ids, so partial sampling can leave either side of
    their link absent. The deployment guide must say so.
17. **P3: the ledger bound is not actually derived.** The existing unlimited
    `max_sessions`, per-session turn count and byte-based LLM bounds do not
    yield a global span count. The plan must state the formula or flat cap and
    the overflow cost.

Verdict: not ready. Findings 1 through 6 are load-bearing; findings 7, 10 and
the rest of the P2 set require concrete amendments before implementation.
