# Optional OpenTelemetry tracing over the event seam

Plan for [issue #66](https://github.com/rafacm/vinga/issues/66).
Companion implementation doc:
`2026-09-10-otel-tracing-implementation.md`, one section per
milestone, appended in the same change that ticks the milestone
checklist.

## Goal

A turn a field tester asks about becomes one trace a backend can
render, instead of an hour of log archaeology. The server gains an
optional OpenTelemetry exporter that derives one trace per
conversation turn from the events the pipeline emits, sends it over
OTLP to whatever collector the standard environment variables name,
and costs nothing at all when it is off, which it is by default. The
exporter is a tap on the one emission seam the events package already
promises to #66 by name; it touches no emit site and invents no
second vocabulary. Where the catalog does not yet speak a fact a
trace needs, the catalog grows first, as its own milestone, so the
one vocabulary stays the only one.

## The issue's decisions, restated

Settled in the issue body and its 2026-08-22 comment, not
re-litigated here:

- Traces only. No OTel metrics, no OTel log export, and the per-frame
  `vad` records stay in the capture JSONL. The structured event log
  remains the source of truth.
- One trace per turn, from utterance end (or barge-in) to reply
  completion, with spans for ASR, each LLM round, TTS synthesis per
  sentence, and playback pacing.
- Session-level context on every span: session id (the capture
  filename stem), agent name, device id, build revision, resolved
  provider entries.
- The existing one-shot events become span events keeping their
  current field names.
- LLM spans follow the OTel GenAI semantic conventions (`gen_ai.*`).
- Exporter endpoint, headers and protocol come from the standard
  `OTEL_EXPORTER_OTLP_*` environment variables; the enable switch is
  vinga configuration.
- A new `server.telemetry` config section, `enabled: false` by
  default, documented commented-out in the example configs.
- The OpenTelemetry packages are the optional extra
  `vinga-server[otel]`; the server boots, runs and passes tests
  without them; `enabled: true` with the packages missing refuses at
  startup with a clear message.
- Telemetry disabled means no measurable overhead on the audio path;
  enabled means batched, fire-and-forget export where a slow or
  unreachable collector drops spans rather than delaying a reply.
- From the recorded comment: spans stay on the metadata surface
  (timings, closed reasons, never transcripts or audio); the exporter
  declares egress and `server.local_only` refuses to build it; span
  content derives from the existing event catalog rather than a
  parallel vocabulary.

## Open questions, resolved

### Where the exporter attaches

As an `EventTap` on `SessionEvents`, attached per session beside
`LiveEvents`, plus a server-scoped tap via `attach_server_tap` for
session-independent events. This is the attachment point the events
package documents for #66/#67 ("exporters attach as more, without
touching a single emit site", `src/vinga_server/events/__init__.py`)
and the one the no-leak suite already covers ("an attached server
tap" is a checked surface). The tap contract gives the exporter a
deep copy of each payload and a guard that reports a raising tap
once; the exporter adds its own never-block discipline on top, below.
The server tap is attached and its detach registered in the same
breath, the `app.py` pattern, and teardown runs in one order: the
lifespan stops accepting session emissions, detaches the server tap,
then shuts the exporter down with a bounded timeout. The exporter
owns its `TracerProvider` outright and never touches OTel's
process-global provider, so two sequential app lifespans in one
process each get a fresh, working exporter, and a partial startup
failure releases whatever was built.

### How spans get their timestamps

Retrospectively, from the emission stamps and the durations the
events carry. `SessionEvents.emit` returns the monotonic stamp it
read; an `llm_round` event carries `duration_ms` and
`first_token_ms`, so its span is constructed at emission time with
`start = at - duration_ms` and an event at `first_token_ms`. OTel
accepts explicit start and end times, so nothing needs to observe a
stage while it runs; the trace is assembled from facts the pipeline
already measured. The exporter records one monotonic-to-epoch offset
when it is built (both clocks read back to back) and converts every
stamp with it, so all spans in a process share one mapping and the
inter-span arithmetic stays exact.

### The trace lifecycle: a session trace, turn traces linked to it

Two kinds of trace, so every event has a destination:

- **The session-lifecycle trace.** One root span per device session,
  opened at `session_open` and closed at `session_closed` with the
  close reason as an attribute. Events with no turn land here as
  span events: `session_idle`, `capture_started` (a server-channel
  event carrying its session id), `handover`, and any turn-scoped
  stragglers that arrive when no turn is open. A `capture_started`
  that precedes `session_open` is held briefly and folded when the
  session span opens, keyed by its session id.
- **Turn traces, linked not parented.** Each turn is its own trace
  with its own trace id, carrying an OTel span link to the session
  span, so a backend can list a session's turns without every turn
  hiding inside one giant trace. The turn's root span opens at the
  new `turn_started` event (below), which is emitted exactly when a
  reply attempt actually starts, stamped with the utterance-end
  instant, and closes at the new `reply_finished` event, which the
  reply task's `finally` emits exactly once with a closed outcome. A
  barge-in candidate the gate rejects starts no turn and emits no
  `turn_started`: the old reply resumes, and the rejection stays
  gate vocabulary (the suppression variants, `provider_failed` for a
  failed confirmation), landing on the turn being spoken over. A
  turn whose `reply_finished` never arrives (the process dies) is
  dropped, not guessed: the batch queue is lost with the process,
  which is the accepted posture.

### The catalog delta: the turn lifecycle becomes vocabulary

Deriving spans strictly from the catalog exposes that the catalog
does not yet speak the turn's own lifecycle. The gap is closed in
the catalog, as milestone 1, before any OTel code exists, so both
the exporter and every other consumer read the same facts:

- **`turn_started`**, emitted at every successful `start_reply`
  invocation, which is the definition rather than a path list, so
  all four ways in are covered: the ordinary endpointed path, the
  manual stop (including one that interrupts a reply in progress),
  the confirmed non-empty barge-in, and the mid-ASR merge
  (`BargeInMerged`). The stamp is the original utterance-end
  instant the gate preserved, never a confirmation's or merge's
  completion time. Fields: `speech_ms` (how long the user spoke)
  and `barge_in: bool`, true for the interrupting shapes. A
  candidate the gate rejects (empty or failed confirmation) never
  reaches `start_reply` and never emits it; the rejection is
  already gate vocabulary (`BargeInWithoutTranscript`,
  `provider_failed`) and stays there.
- **`reply_finished`**, emitted exactly once per reply from the
  reply task's `finally`, as its first statement, before any
  cancellable cleanup: `SessionEvents.emit` is synchronous, so
  placing it ahead of the filler settle and the turn recording makes
  it cancellation-proof by construction. Its `outcome` comes from a
  closed set in `values.py` and is latched at each initiating
  boundary rather than guessed from `CancelledError`, which cannot
  tell a barge-in from a shutdown. The latch is reply-owned,
  write-once, first-writer-wins, and `cancel_reply` takes the
  initiating outcome as an argument and latches it before
  cancelling, so every canceller names itself. The writers,
  exhaustively: the barge-in cancel path latches `barged_in`, the
  device-abort path latches `aborted`, the session close path
  latches `aborted`, ordinary failure classification latches
  `failed` by exception type where it already classifies, the
  empty-transcript branch latches `nothing_heard`, and the reply
  body latches `device_gone` where it deliberately catches
  `DeviceGone` and returns, since an unlatched exit means
  `completed` and a vanished device must not read as one.
  Fields: `outcome`, `sentences_spoken`.
  `replied` keeps its present meaning (one or more ordinary
  sentences finished) and its present guard; consecutive silent or
  failed turns in one still-open session each get their own pair.
- **`heard` gains `asr_ms`**, the transcription latency, measured at
  the site that already measures it. On the confirmed barge-in path
  the gate measures its confirmation transcription at its own
  decision site and the measured latency travels with the
  transcription result it already hands to the reply, so the
  interrupting turn's `heard` carries a real `asr_ms` rather than
  Absent.
- **`nothing_heard`**, the missing ASR outcome: emitted where empty
  transcription is currently a log-only branch inside a started
  reply, with `duration_s` and `asr_ms` and no text field at all,
  by type. This is the issue's motivating Gap C (a 0.9 s utterance
  transcribed to nothing) becoming a first-class event; ASR failure
  keeps `provider_failed` as its outcome, and a transcription cut
  short by a mid-ASR merge says so with `transcription_abandoned`
  (the PR review round's finding 1: a cancelled call is none of the
  other three, and calling it a provider failure would lie). Every
  `turn_started` is followed by exactly one of the four; a
  gate-rejected candidate has no `turn_started` and needs none.
- **`sentence_synthesized`**, one per reply sentence, emitted when a
  sentence's synthesis stream ends, with honest semantics for a
  streamed, backpressured producer: `index`, `first_chunk_ms` (the
  provider's latency to its first audio chunk, measured
  producer-side before pacing backpressure can bite, since the
  first chunk always finds buffer room) and `stream_ms` (the
  stream's whole lifetime, documented as including playback
  backpressure, because a paced consumer makes pure synthesis time
  unobservable for a streaming provider). The TTS span reads both
  and says what each is; nothing is called synthesis latency that
  is not.
- **`frames_dropped` promoted, with the aggregation moving to its
  one home.** Per-frame counting moves into `SessionEvents` (the
  `dropped()` entry point keeps its per-frame signature and stays
  outside the tap contract), which keeps the bounded current-second
  counter and, on second rollover and at close, emits one typed
  `frames_dropped` variant (`second`, `reasons` from the
  server-owned closed set) through the normal emit seam. Counting
  runs regardless of capture state, where today `dropped()` returns
  early when capture is off, so telemetry sees drops on
  capture-less deployments too. The close ordering is explicit: the
  session close path flushes the pending partial second before it
  emits `session_closed`, while the capture tap is still attached,
  so the JSONL keeps recording everything it records today. The
  capture's decision track receives the typed variant as the tap it
  already is, and its independent aggregate writer is deleted: one
  declaration, two consumers, no duplicate arithmetic.
- **`speaking_finished`**, emitted by the session edge when a
  reply's outgoing audio is done, bounding with `speaking_started`
  the paced playback interval: first frame out to last frame out,
  the interval `ReplyPacer` actually paces, not the reply's whole
  tail. The facts it needs do not exist yet and are added as
  per-reply state: a successful-delivery count and a
  last-delivery stamp (counted after `deliver` returns, the pacer's
  own ordering rule), retained across handovers rather than reset
  per agent leg, reset at `reply_started`, and snapshotted at the
  edge's finish-speaking site. It is emitted only when at least one
  frame was delivered, before the cancellable stop send, so a
  cancelled reply's interval is truthful and a reply that never
  spoke emits nothing. Fields: `frames`, and the interval is the
  stamps'. The pacer itself stays vocabulary-free; the edge, which
  already emits `speaking_started` for the same reason, emits this
  one too.
- **`session_open` deepened with resolved providers.** A new
  sanitized, typed per-agent, per-stage derivation is built from
  the bound generation (name, type, host, model per entry, with
  explicit absent rules where a provider has no host or model), and
  becomes the one home both the session's provider manifest and
  `session_open` read, replacing the manifest's own
  current-agent-only serialization. `session_open` carries the
  entries for every bound agent, so a handover switches the
  exporter's active-agent context by reading `handover` without
  needing entries it was never given. A mid-session `apply` that
  changes providers is out of trace scope for this issue: spans
  after an apply may carry the open-time entries, stated in the
  reference.

Every addition is a payload change on a pinned surface: the baseline
driver, `events.md`, the event pins and the conversations docgen
move deliberately in the same milestone, the #437 discipline. The
closed `outcome` set is declared in `values.py` with one variant per
outcome, reachable each from a real decision site.

### `barge_in_suppressed` is three variants

The catalog holds `BargeInUnderFloor`, `BargeInInRefractory` and
`BargeInWithoutTranscript`, each with its fixed `reason` and its own
fields. All three map to span events named by their event name with
their existing fields; the acceptance criterion ("a barge-in
suppression appears as a span event with its existing reason field")
is met three-to-one, keeping the closed reason set exactly as the
decision sites chose it. They land on the turn trace that was being
spoken over when one is open, else on the session span.

### Config shape

`server.telemetry: TelemetryConfig | None = None`, following the
`capture`/`conversations` optional-section pattern: absent means
never. `TelemetryConfig` is `extra="forbid"` like everything else and
carries exactly one field today, `enabled: bool = False`. Endpoint,
protocol, headers and timeouts stay with `OTEL_EXPORTER_OTLP_*` per
the issue's decision; duplicating them into vinga config would be a
second home for facts the SDK already reads. `service.name` is fixed
to `vinga-server` and the resource is built entirely from
server-owned values (service name, build revision as
`service.version`); no environment-derived resource attributes are
read, per the restriction-at-the-source invariant. The supported
transport is OTLP over HTTP/protobuf, exactly: the extra depends on
`opentelemetry-exporter-otlp-proto-http` alone, the generated
reference says so, and an `OTEL_EXPORTER_OTLP_PROTOCOL` naming
anything else is refused at build time with a sentence naming the
supported value, rather than half-honoring a variable the
distribution cannot serve.

### The two refusals, and where each lives

- **Missing extra.** `enabled: true` with the `[otel]` packages not
  importable refuses at composition build time with the registry's
  sentence shape: the section, the extra's name, and
  `uv sync --extra otel`. It is a `ConfigError` (already in
  `BOOT_FAILURES`), raised in the telemetry build, not a pydantic
  validator: whether a package is installed is not a config
  cross-field fact, so the `BOOT_REFUSALS` registry is untouched and
  its sweep stays green. Pinned twice: a unit test that fakes the
  import failure (the `test_providers.py` precedent) so the sentence
  is pinned in every lane, and a tier-lane boot in the real `[serve]`
  environment, where the packages are genuinely absent, asserting
  the genuine refusal.
- **`local_only`.** Egress enforcement has one home, `egress.py`,
  and it stays one: the module gains a generic declared-egress check
  (a declaration that is not a provider class, the MCP
  operator-declaration shape) and the telemetry build invokes it
  before any OTel import, exporter construction or thread creation,
  so under `server.local_only: true` with `telemetry.enabled: true`
  the refusal is the egress module's fixed, value-free sentence
  naming both keys, translated to `ConfigError` with no exception
  chain, and the exporter constructor is provably never reached. An
  operator running a genuinely local collector under `local_only`
  cannot trace today; that is the strict reading of the recorded
  decision, taken deliberately, and relaxing it later (an explicit
  locality declaration, the `openai_compatible` precedent) would be
  its own recorded change.

### Never blocking, concretely

The tap's `emit` runs synchronously on the reply path, so it does
what `LiveEvents` does: bounded work, no locks shared with the
export, no syscalls. Span construction is object assembly; the SDK's
`BatchSpanProcessor` owns the bounded queue and the background
thread, and a full queue drops with a counter, which is exactly the
"dropped spans are acceptable, a stalled reply is not" posture. The
hardening lands in the same milestone that first exports, not later:
bounded shutdown in the lifespan release, detach ordering as above,
SDK logging protection installed before the exporter is constructed
and restored at shutdown, and a saturation test that replaces the
transport with a deliberately blocking exporter behind a tiny batch
queue, drives enough turns to fill it, and asserts a fixed upper
bound on every scripted reply's latency, so the certificate is about
the path that hurts, not the path that fails fast.

### No-leak, at the exporter's real inputs

The dangerous bytes enter below the catalog: `OTEL_EXPORTER_OTLP_*`
headers (collector credentials by design), endpoint userinfo, and
the SDK's own failure logging, which embeds the endpoint. The
treatment, all pinned by planted sentinels:

- Endpoint and headers are transport configuration only: they reach
  the exporter's constructor and never become span attributes,
  resource attributes, event fields or log text.
- The resource is fixed and server-owned, as above; no
  `OTEL_RESOURCE_ATTRIBUTES` or `OTEL_SERVICE_NAME` pass-through.
- SDK loggers are quieted before construction and restored at
  shutdown; nothing SDK-side reaches an emitter (the AST guard
  already forbids the way back in).
- Sentinels: a credential-shaped value planted in the OTLP headers
  env var, in endpoint userinfo, in `OTEL_SERVICE_NAME`, and in an
  event payload, asserted absent from exported span data (decoded),
  from both log formats, from stderr, and from exception chains
  during a failed export.

### What the lanes test without the extra

`[otel]` joins the `dev` group (`vinga-server[serve,sim,otel]`): the
span-mapping logic is vinga logic and runs in every unit lane, unlike
the engine wrappers whose extras stay out of `dev` for weight. The
SDK is small, pure Python and Apache-2.0 (no licensing pressure of
the piper kind), so the contributor-checkout weight argument that
keeps `faster-whisper` and `piper` out does not apply. Unit tests
drive the tap with the SDK's in-memory exporter and assert span
structure, attributes and the gen_ai mapping; missing-extra behavior
is pinned both faked and real, as above. The tier machinery grows
from three tiers to four, named as such: `tests/support/tiers.py`'s
`declared()` and its consumers currently hardcode client, serve and
sim, so the refactor extends that closed set with `otel` (its
distribution-to-import-name rows included), the tier-closure lane
gets an isolated `[otel]` environment fixture the way `sim`
arrived, the wheel metadata check closes over the fourth tier, and
the plain `[serve]` environment stays exactly as it is, since it is
the one that proves the genuine missing-extra refusal.

### Verifying against a generic backend

Two layers, per the acceptance criteria:

- **In CI:** an integration test boots the server with telemetry
  enabled and `OTEL_EXPORTER_OTLP_ENDPOINT` pointed at a stub OTLP
  HTTP receiver in the test process, drives one simulator turn, and
  asserts a trace arrives whose spans decode (the proto package
  rides the exporter dependency) with the expected names, links,
  parentage and `gen_ai.*` attributes. The hostile-collector cases
  are the saturation test above plus a blackholed endpoint, and the
  latency assertion is a fixed bound per scripted reply against the
  scripted providers' known timings, not an undefined
  "indistinguishable".
- **By hand, recorded on the PR:** Jaeger all-in-one from its
  published image, one simulator conversation, the trace queried
  over Jaeger's API; the walkthrough lands in the PR's verification
  section with what was seen. Langfuse is deliberately not part of
  this issue's verification; it is #67's.

### Image variants

Both image variants carry `[otel]`. The slim variant exists to shed
the heavy local engines and boots against external providers, which
is precisely the deployment most likely to want tracing; the OTel SDK
adds single-digit megabytes and no system dependencies. The
Dockerfile's variant `case` gains `--extra otel` on both arms, the
default image's extras-import check adds the import, and the slim
refusal check is untouched since it asserts engine refusals, not
extras generally.

## Module layout

One new module, `src/vinga_server/telemetry.py`: the whole OTel
surface behind one seam. Its callers stop having to know that
OpenTelemetry exists: the composition asks
`build_telemetry(config) -> Telemetry | None` (None when disabled;
the missing-extra refusal is this function's, and the egress check
runs before it imports anything), the device session asks the built
object for a per-session tap the way it already attaches
`LiveEvents`, and the lifespan release calls its bounded `shutdown`
after detaching. Everything else, the SDK bootstrap, the owned
tracer provider, the clock offset, the trace lifecycle, the
event-to-span-event fold and the attribute table, is implementation.
The OTel imports happen inside the build function (the registry's
`_resolved` pattern), so the module imports clean without the extra.

The attribute mapping is the settled correspondence table from the
conversation-store plan, shipped exactly: `type` to
`gen_ai.provider.name`, `model` to `gen_ai.request.model`, `host` to
`server.address`, `input_tokens`/`output_tokens` to
`gen_ai.usage.input_tokens`/`gen_ai.usage.output_tokens`. Only
`provider`, the configured entry name, is vinga-specific and stays a
plain attribute. The table is a literal dict in this module, and the
tests pin exact keys and values both in-memory and decoded from
OTLP.

The deletion test holds: inlining this into the composition would
put SDK bootstrap and span assembly into a module whose job is
build order, and inlining it into `events/` would make the event
seam know one of its consumers. It is an adapter at a seam, and it
hides a real vocabulary (the SDK's), not a pass-through.

`mypy --strict` today covers only `events/`; `telemetry.py` sits
beside it unstrict, like every other consumer. Widening the strict
scope is its own decision and not this plan's.

## Tests

Reusing the assets that exist; new tests only where the surface is
new:

- **Unit, catalog delta (M1):** every new variant and field gets a
  baseline driver; `events.md`, the pins and the docgen move in the
  same change; the `outcome` set's variants each have a reachable
  decision site; consecutive silent and failed turns in one session
  each produce their `turn_started`/`reply_finished` pair; a
  confirmed barge-in produces `turn_started` with the preserved
  stamp and `heard` with the gate-measured `asr_ms`, while a
  rejected candidate (empty and failed, both) produces neither and
  the old turn resumes; a reply cancelled during the filler settle
  still has exactly one `reply_finished` with the latched outcome;
  lookahead
  synthesis overlapping playback produces `sentence_synthesized`
  intervals that overlap the speaking window, pinned as such.
- **Unit, span structure (M2/M3):** drive `SessionEvents` with real
  event sequences (the baseline driver's shapes, in pipeline order,
  including capture-before-open, idle between turns, and close with
  no open turn) through the telemetry tap into the in-memory
  exporter; assert the session span, linked turn traces, stage
  spans, the span-event fold, session attributes and the exact
  gen_ai keys.
- **Unit, refusals:** the missing-extra sentence (faked import), the
  `local_only` refusal coming from the egress module's check with
  the exporter constructor never reached, the unsupported-protocol
  refusal, and all refusal types inside `BOOT_FAILURES`.
- **Unit, no-leak:** the sentinel battery over headers, endpoint
  userinfo, `OTEL_SERVICE_NAME`, and event payloads, asserted
  absent from decoded exported spans, both log formats, stderr and
  exception chains during a failed export.
- **Unit, lifecycle:** two sequential enabled lifespans in one
  process; partial startup failure releases what was built; detach
  ordering; a span's converted end equals its event's converted
  stamp (the one-offset pin).
- **Integration:** the stub-receiver trace assertion; the blocking-
  exporter saturation case with a fixed per-reply bound; the
  blackholed endpoint; the real `[serve]`-tier boot against the
  genuine missing-extra refusal; the tier-closure `otel` fixture;
  the wheel lane picks up the `tiers.py` rows.
- **Byte-for-byte off:** the existing suites running with no
  `telemetry` section are themselves the proof the default path is
  untouched past M1's event additions; `build_telemetry(None)` is
  None and attaches nothing, pinned.

## Risks

- **The catalog delta is the widest since the events re-cut.** Five
  new or deepened variants move the baseline, `events.md` and many
  pins at once. Mitigation: it is its own milestone with no OTel
  code in it, one variant per commit, the #437 discipline per
  commit; the exporter cannot drift from the vocabulary because it
  does not exist yet.
- **`turn_started` on the barge-in path crosses the gate.** The
  utterance-end stamp must survive from `finish_utterance` through
  confirmation to `start_reply`. Mitigation: the stamp travels with
  the transcription result the gate already hands over; a pin
  asserts the emitted stamp predates the confirmation ASR's
  completion.
- **The SDK's background thread meets the test lanes.** Mitigation:
  unit tests use the in-memory exporter (no thread); the
  integration cases shut down with a bounded timeout in teardown;
  the bounded-runner rule from #283 applies to the stub receiver.
- **Clock skew inside a trace.** Mitigation: the offset is the only
  conversion site, by construction in one module, and the lifecycle
  pin above.
- **The exporter's own logging leaks.** Mitigation: the no-leak
  battery above, installed-before-construction ordering, restored
  at shutdown.
- **Filterwarnings is `error`.** Any OTel deprecation warning fails
  the lane. Mitigation: pin the SDK lower bound to a current
  release; allowlist nothing until a real warning forces a decision.

## Milestones

- [x] **[M1: the catalog speaks the turn
  lifecycle](2026-09-10-otel-tracing-implementation.md#m1-the-catalog-speaks-the-turn-lifecycle)**
  (PR #442). `turn_started`,
  `reply_finished` with its latched closed outcome set,
  `heard.asr_ms` including the gate-measured confirmation latency,
  `nothing_heard`, `sentence_synthesized` with its honest streamed
  semantics, `speaking_finished`, the `frames_dropped` promotion
  with the aggregation moving into `SessionEvents` and capture
  consuming the one declaration, and `session_open` deepened with
  the new per-agent sanitized provider derivation the manifest also
  reads. No OTel anywhere.
  Design footprint: deepens the catalog and the decision sites that
  already classify; no new module. Documentation footprint:
  generated `events.md` and `conversations-schema.md` via their
  generators; CHANGELOG. Releasable alone: richer events, nothing
  else moves.
- [x] **[M2: the switch, the seam and the hardened
  exporter](2026-09-10-otel-tracing-implementation.md#m2-the-switch-the-seam-and-the-hardened-exporter)**
  (PR TBD). The
  `[otel]` extra (pyproject, `dev` group, `tiers.py` rows, tier
  fixture), `server.telemetry` with both example configs and the
  generated reference, the egress-module extension and both boot
  refusals with their pinned sentences (faked and real-tier), and
  `telemetry.py` with the owned tracer provider, fixed server-owned
  resource, HTTP/protobuf-only transport with the
  unsupported-protocol refusal, attach-and-detach lifecycle, bounded
  shutdown, SDK log protection, the saturation test, and the
  session-lifecycle trace plus linked turn root spans. Design
  footprint: deepens `egress.py` (one generic check both callers
  read) and the composition; adds the `telemetry.py` adapter at the
  events seam; callers stop knowing OpenTelemetry exists.
  Documentation footprint: generated `server-config.md` via its
  generator; `config.example.yaml` and `config.deploy.example.yaml`
  in the same change as the schema; CHANGELOG. Releasable alone:
  enabled means honest session-and-turn traces, disabled means
  today's server.
- [ ] **M3: the full span map, the proof and the image.** ASR spans
  from the three outcomes, LLM round spans with the settled gen_ai
  mapping, per-sentence TTS spans, the paced-playback span bounded
  by `speaking_started` and `speaking_finished`, the
  span-event fold including the three barge-in suppression variants
  and the promoted `frames_dropped`, the stub OTLP receiver
  integration test, the blackholed-endpoint case, `[otel]` in both
  image variants with the extras-import check, and the Jaeger
  all-in-one walkthrough recorded on the PR. Documentation
  footprint: `docs/architecture/observability-surfaces.md` gains the
  exporter as a surface with its retention answer (the collector's
  backend owns retention; vinga sends and forgets), and its
  still-open list drops #66; CHANGELOG.

## Plan review round

External review: codex CLI 0.154.0, model gpt-5.6-sol, read-only
sandbox, 2026-09-10, runtime 8m31s, reviewing commit 593e8785.
Verdict as received: **not ready**; the retrospective lifecycle does
not cover empty ASR, failed replies, or confirmed barge-ins, and two
settled issue requirements were removed. Findings condensed but
faithful; resolutions appended per amendment.

1. **P1: Empty or failed ASR produces no trace at all.** `Heard` is
   emitted only for a non-empty transcript; empty transcription is a
   log-only branch and ASR failure emits only `provider_failed`, so
   the plan misses the issue's motivating Gap C (an ASR span with
   empty output). The catalog needs a turn-start event for every
   reply attempt and an ASR outcome covering non-empty, empty and
   failed; `heard.asr_ms` alone is insufficient.

   *Resolution.* Adopted. The catalog delta now opens every reply
   attempt with `turn_started` and closes the ASR stage with exactly
   one of `heard`, `nothing_heard` (new, no text field by type) or
   `provider_failed`; Gap C is a first-class event. M1 owns it.

2. **P1: `replied` is not an unconditional completion marker.** It
   is guarded by `if spoken:`; empty transcription, early failure
   and pre-sentence cancellation never emit it, and `session_closed`
   as a backstop gives false durations across still-open sessions.
   The reply `finally` needs an unconditional reply-finished event
   with a closed outcome.

   *Resolution.* Adopted. `reply_finished` is emitted
   unconditionally from the `finally` with a closed `outcome` set
   chosen by exception type at the classifying sites; `replied`
   keeps its meaning and guard; the session-closed backstop is gone
   from the design; consecutive silent/failed turns are a named
   test.

3. **P1: Confirmed barge-in ASR cannot be reconstructed.** The
   confirmation transcription runs in the gate before `BargeIn` and
   the reused result deliberately leaves `TurnUnderway.asr_ms`
   unset, so the interrupting turn has no ASR latency and no
   utterance-end stamp under the proposed derivation. Measure and
   catalogue confirmation ASR at its decision site and carry the
   stamp across the gate.

   *Resolution.* Adopted. The gate measures its confirmation ASR at
   its own decision site and the interrupting turn's `heard` carries
   that measured `asr_ms`; `turn_started` carries the preserved
   utterance-end stamp across the gate, with a pin that the stamp
   predates the confirmation's completion; both confirmation
   outcomes are tested.

4. **P1: The TTS narrowing contradicts a settled decision.** The
   issue requires per-sentence synthesis and playback-pacing spans;
   the plan's single speaking-window span measures neither, and the
   seams that distinguish them (`speak_after`, `ReplyPacer.transmit`)
   already exist. Add catalog events for per-sentence synthesis
   intervals and a separately bounded pacing interval, tested with
   lookahead overlapping playback.

   *Resolution.* Adopted; the narrowing is withdrawn.
   `sentence_synthesized` carries one synthesis interval per
   sentence, the playback-pacing span is bounded separately
   (`speaking_started` to `reply_finished`), and the
   lookahead-overlap case is a named M1 pin.

5. **P1: Excluding `frames_dropped` contradicts a settled
   decision.** The capture-side record is already a bounded
   per-second aggregate, so the high-frequency objection does not
   apply. Promote the aggregate to a typed catalog variant that both
   capture and telemetry read; per-frame calls and `vad` stay
   outside the tap.

   *Resolution.* Adopted; the exclusion is withdrawn. The per-second
   aggregate becomes a typed variant with server-owned reason keys,
   capture consumes the one declaration, and the per-frame seam
   stays outside the tap contract unchanged.

6. **P1: Resolved provider context is unavailable at the attachment
   point.** No catalog event carries the sanitized resolved provider
   entries (`SessionOpen` does not; the manifest is private to the
   session edge), so the promised span attributes would need a side
   channel, violating the one-vocabulary rule. Deepen `SessionOpen`
   with the sanitized entries and define what handover changes.

   *Resolution.* Adopted. `session_open` is deepened with the
   sanitized per-agent entries from the same derivation the manifest
   uses; the exporter switches active-agent context on `handover`;
   the mid-session-apply boundary is stated in the reference as out
   of trace scope for this issue.

7. **P1: No destination for events outside an active turn.**
   `capture_started` precedes `session_open`, `session_idle` falls
   between turns, `session_closed` can land with no open turn; the
   plan defines only turn traces. Define a session-lifecycle trace
   with turn traces linked rather than parented, and state where
   pre-turn, between-turn and post-turn events land.

   *Resolution.* Adopted. The trace lifecycle section now defines
   the session-lifecycle trace, turn traces linked not parented,
   the destination of every named out-of-turn event including the
   capture-before-open hold, and a real-ordering test from capture
   start to session close.

8. **P1: The GenAI mapping omits correspondences the repository
   already settled.** The conversation-store plan maps `type` to
   `gen_ai.provider.name` and `host` to `server.address` alongside
   `model` and usage; the plan kept `type` and `host` vinga-only.
   Ship the settled mapping; only `provider` (the configured entry
   name) stays vinga-specific.

   *Resolution.* Adopted; the plan misread the settled table's
   direction. The module-layout section now ships the
   correspondence exactly, with exact-key pins in-memory and
   decoded.

9. **P1: The no-leak tests miss the exporter's most dangerous
   inputs.** Headers, endpoint userinfo, `OTEL_SERVICE_NAME` and
   automatic resource attributes enter below the catalog, and SDK
   logs may embed the endpoint. Build a fixed resource from
   server-owned values, keep endpoint and headers transport-only,
   install SDK logging protection before construction and restore it
   at shutdown, and plant sentinels in headers, endpoint userinfo,
   environment, logs, stderr, exception chains and exported spans
   during a failed export.

   *Resolution.* Adopted in full: fixed server-owned resource with
   no environment pass-through, transport-only endpoint and
   headers, protection-before-construction and restore-at-shutdown,
   and the sentinel battery as its own no-leak section.

10. **P2: A telemetry `local_only` rule would duplicate the single
    egress home.** `egress.py` exists because duplicated enforcement
    diverged. Extend it with a generic declared-egress check the
    telemetry build invokes before any OTel import or construction,
    value-free and unchained, with a test that the exporter
    constructor is never reached under `local_only`.

    *Resolution.* Adopted. The refusal moved into an `egress.py`
    generic check invoked before any import or construction,
    value-free, unchained, with the never-reached pin.

11. **P2: Tap and tracer lifecycle ownership is incomplete.** The
    plan names attach and shutdown but not detach, and does not say
    whether it touches OTel's process-global tracer provider. Attach
    and register detach in the same breath, order teardown (stop
    emissions, detach, bounded shutdown), use an owned
    `TracerProvider`, and test two sequential lifespans and partial
    startup failure.

    *Resolution.* Adopted in full; the attachment section now
    states the owned provider, the paired detach registration, the
    teardown order, and both lifecycle tests.

12. **P2: The safety tests certify paths they do not exercise, in
    the wrong milestone.** A blackholed endpoint may fail fast and
    "indistinguishable" is undefined; hardening is deferred to M3
    while M1 already exports; the missing-extra test only fakes
    imports though the tier lane has a real extra-less environment;
    the supported OTLP protocol set is undefined. Move hardening
    into the first exporting milestone, add a blocking-exporter
    saturation test with a fixed per-reply bound, boot the real
    `[serve]` tier against the genuine refusal, and define the
    protocol support exactly.

    *Resolution.* Adopted, via restructure: the milestones are
    re-cut so no milestone exports before the hardening exists (M1
    is vocabulary only; M2 is the exporter with all hardening and
    the saturation test in it), the latency assertion is a fixed
    per-reply bound against scripted timings, the real-tier refusal
    boot is added beside the faked-import pin, and the transport is
    defined as HTTP/protobuf exactly, with an unsupported-protocol
    refusal.

### Delta re-review

External review: codex CLI 0.154.0, model gpt-5.6-terra, read-only
sandbox, 2026-09-10, runtime 6m17s, reviewing commit 5c871ef3 (the
amended plan). Verdict as received: **not ready**. Findings
condensed but faithful; where a resolution supersedes a first-round
resolution note above, the note here governs.

1. **P1: Confirmed empty or failed barge-in ASR cannot satisfy the
   claimed lifecycle.** The gate resumes the old reply without
   `start_reply()` on a failed or empty confirmation, so "every
   turn_started has exactly one ASR outcome and both confirmation
   outcomes produce heard/nothing_heard" was unimplementable as
   written.

   *Resolution.* Adopted. `turn_started` is emitted only when a
   reply attempt actually starts; a gate-rejected candidate emits
   nothing new, its rejection staying gate vocabulary
   (`BargeInWithoutTranscript`, `provider_failed`) on the resumed
   turn. The catalog-delta bullets and the M1 tests now say exactly
   that, superseding the first-round note under finding 3.

2. **P1: `reply_finished` was not actually unconditional.** The
   `finally` opens with a cancellable await (the filler settle), so
   a cancellation delivered there could bypass the event, and
   `CancelledError` cannot distinguish barge-in from shutdown.

   *Resolution.* Adopted. The emit is the `finally`'s first
   statement, ahead of any await, cancellation-proof because `emit`
   is synchronous; the outcome is a write-once latch set at each
   initiating boundary (`barged_in`, `aborted`, `failed`,
   `nothing_heard`), with an unlatched exit meaning `completed`,
   and precedence defined by the latch itself. The
   cancelled-during-settle case is a named test.

3. **P1: The `frames_dropped` promotion had no emission path.** The
   per-frame `dropped()` entry is deliberately outside the tap
   contract and capture aggregates independently, so "both consume
   one declaration" named no mechanism.

   *Resolution.* Adopted as prescribed: per-frame counting moves
   into `SessionEvents` behind the unchanged `dropped()` signature,
   one typed variant is emitted through the normal seam on second
   rollover and at close, capture's decision track consumes it as
   the tap it already is, and capture's own aggregate writer is
   deleted.

4. **P1: `synthesis_ms` could not be measured at the named seam.**
   The synthesis drain is producer-backpressured by the paced
   consumer, so stream completion time includes playback, and
   calling it synthesis latency would be false.

   *Resolution.* Adopted, the honest-semantics option with a real
   producer-side number: `sentence_synthesized` carries
   `first_chunk_ms` (provider latency to first audio, measured
   before backpressure can bite) and `stream_ms` (whole stream
   lifetime, documented as including backpressure); nothing is
   called synthesis latency that is not.

5. **P2: The proposed playback-pacing span was not a pacing
   interval.** Bounding it at `reply_finished` swallowed the
   reply's non-pacing tail.

   *Resolution.* Adopted via a new fact: `speaking_finished`,
   emitted by the session edge at its finish-speaking site with the
   frames delivered; the paced-playback span is
   `speaking_started` to `speaking_finished`, the interval the
   pacer actually paces, and the pacer itself stays
   vocabulary-free.

6. **P2: The provider-context resolution overstated the existing
   derivation.** The manifest serializes only the current agent's
   entries and not the plan's quartet.

   *Resolution.* Adopted. The plan now specifies a new sanitized,
   typed per-agent, per-stage derivation from the bound generation
   with explicit absent rules, made the one home that both the
   manifest and the deepened `session_open` read.

7. **P2: The tier-closure change was incomplete.** `declared()` and
   its consumers hardcode three tiers; rows alone would not
   exercise `[otel]`.

   *Resolution.* Adopted. The lanes section now names the
   three-to-four refactor of `declared()` and its consumers, the
   isolated `[otel]` environment fixture, the import map, and the
   untouched plain `[serve]` environment that proves the genuine
   refusal.

### Confirmation round

External review: codex CLI 0.154.0, model gpt-5.6-terra, read-only
sandbox, 2026-09-10, scoped to the delta resolutions, reviewing
commit 5e59f84b. Verdict as received: **ready after amendments**.
Findings condensed but faithful.

1. **P1: `turn_started` still omitted real reply-start paths.** The
   mid-ASR merge (`BargeInMerged`) and a manual stop during a reply
   both cancel and then reach `start_reply`; the plan named only the
   ordinary and confirmed-non-empty paths.

   *Resolution.* Adopted. The bullet now defines emission as every
   successful `start_reply` invocation, names all four ways in, and
   keeps the original utterance-end stamp and `barge_in` marking
   for the interrupting shapes.

2. **P1: The outcome latch was incomplete.** `device_aborted`,
   session close and barge-in all call the same unqualified
   `cancel_reply`, and `DeviceGone` is caught-and-returned, so
   "unlatched means completed" would mislabel a vanished device.

   *Resolution.* Adopted. The latch is reply-owned, write-once,
   first-writer-wins; `cancel_reply` takes the initiating outcome
   as an argument; all six writers are enumerated, and
   `device_gone` is restored where the reply body catches
   `DeviceGone`.

3. **P2: `frames_dropped` lacked the close ordering and the
   capture-disabled rule.** Today `dropped()` returns early when
   capture is off, and `session_closed` precedes capture detach.

   *Resolution.* Adopted. Counting runs regardless of capture
   state, and the close path flushes the pending second before
   `session_closed`, while the capture tap is still attached.

4. **P2: `speaking_finished` could not yet mean last frame out.**
   No delivery count or final-frame stamp exists; the pacer's count
   resets per agent leg.

   *Resolution.* Adopted as prescribed: per-reply
   successful-delivery count and last-delivery stamp, retained
   across handovers, reset at `reply_started`, snapshotted at
   finish-speaking, emitted only when at least one frame was
   delivered, before the cancellable stop send.
