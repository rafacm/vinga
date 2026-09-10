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
conversation turn from the events the pipeline already emits, sends
it over OTLP to whatever collector the standard environment variables
name, and costs nothing at all when it is off, which it is by
default. The exporter is a tap on the one emission seam the events
package already promises to #66 by name; it touches no emit site and
invents no second vocabulary.

## The issue's decisions, restated

Settled in the issue body and its 2026-08-22 comment, not
re-litigated here:

- Traces only. No OTel metrics, no OTel log export, and the per-frame
  `vad` records stay in the capture JSONL. The structured event log
  remains the source of truth.
- One trace per turn, from utterance end (or barge-in) to reply
  completion, with spans for ASR, each LLM round, TTS synthesis, and
  playback pacing.
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

### How spans get their timestamps

Retrospectively, from the emission stamps and the durations the
events already carry. `SessionEvents.emit` returns the monotonic
stamp it read; an `llm_round` event carries `duration_ms` and
`first_token_ms`, so its span is constructed at emission time with
`start = at - duration_ms` and an event at `first_token_ms`. OTel
accepts explicit start and end times, so nothing needs to observe a
stage while it runs; the trace is assembled from facts the pipeline
already measured. The exporter records one monotonic-to-epoch offset
when it is built (both clocks read back to back) and converts every
stamp with it, so all spans in a process share one mapping and the
inter-span arithmetic stays exact.

### What the turn's root span is

The root span opens at utterance end and closes at reply completion,
both read from events: `heard` marks the utterance (its stamp minus
the ASR time is utterance end; its `duration_s` is how long the user
spoke), `replied` marks completion however the reply ended, since the
pipeline emits it from the reply task's `finally`. A barge-in turn is
the same shape: `barge_in` lands as a span event on the turn it cut
short, and the interrupting utterance opens its own trace. A turn
that dies without `replied` (device gone mid-reply) is closed by
`session_closed`, with the close reason as a span attribute, so no
span leaks open past its session.

### The vocabulary gap: one field, one home

Deriving spans strictly from the catalog exposes one missing fact:
no event carries the ASR latency. `heard` is emitted when
transcription completes and carries the utterance's `duration_s`, but
the transcription time itself lives only in the turn accumulator and
the conversations record. Under the one-vocabulary rule the fix is to
add the fact to the catalog, not to smuggle it through a side
channel: `heard` gains an `asr_ms` field, the same number
`turns.asr_ms` stores, measured at the same site. That is a payload
key on a pinned surface, so the baseline driver, `events.md` and the
event pins move deliberately in the same change.

No other stage needs a new fact for the issue's acceptance criteria:
LLM rounds carry their numbers on `llm_round`, first sentence audio
latency is on the record and the speaking window is bounded by
`speaking_started` and `replied`. Per-sentence TTS synthesis spans,
which the issue's proposal sketch mentions, are cut to what the
vocabulary carries: one TTS-and-playback span per turn (the speaking
window) with `spoken` sentence count, rather than a per-sentence
ladder that would need several new catalog variants. If per-sentence
depth earns its way in later, it arrives as catalog events first, by
this same rule. This narrowing is a recorded deviation from the
proposal sketch; the acceptance criterion says ASR, LLM and TTS
spans, and it is met.

### `frames_dropped` is not an event, and stays out

The issue lists `frames_dropped` among the one-shot events that
become span events. The census found it is not an event at all: it is
a per-second aggregated dict written straight into the capture JSONL
through `SessionEvents.dropped()`, which is deliberately outside the
tap contract for the same reason `vad()` is (a consumer of events has
no meaning for it). Promoting it to a catalog variant just to export
it would put a high-frequency capture fact onto the metadata surface
against the grain of both designs. It stays capture-only, by the same
argument the issue itself makes for excluding `vad`. Recorded here as
a deviation from the issue's letter.

### `barge_in_suppressed` is three variants

The catalog holds `BargeInUnderFloor`, `BargeInInRefractory` and
`BargeInWithoutTranscript`, each with its fixed `reason` and its own
fields. All three map to span events named by their event name with
their existing fields; the acceptance criterion ("a barge-in
suppression appears as a span event with its existing reason field")
is met three-to-one, keeping the closed reason set exactly as the
decision sites chose it.

### Config shape

`server.telemetry: TelemetryConfig | None = None`, following the
`capture`/`conversations` optional-section pattern: absent means
never. `TelemetryConfig` is `extra="forbid"` like everything else and
carries exactly one field today, `enabled: bool = False`. Endpoint,
protocol, headers and timeouts stay with `OTEL_EXPORTER_OTLP_*` per
the issue's decision; duplicating them into vinga config would be a
second home for facts the SDK already reads. `service.name` defaults
to `vinga-server` via the SDK resource, overridable with
`OTEL_SERVICE_NAME`; the build revision rides the resource as
`service.version`.

### The two refusals, and where each lives

- **Missing extra.** `enabled: true` with the `[otel]` packages not
  importable refuses at composition build time with the registry's
  sentence shape: the section, the extra's name, and
  `uv sync --extra otel`. It is a `ConfigError` (already in
  `BOOT_FAILURES`), raised in the telemetry build, not a pydantic
  validator: whether a package is installed is not a config
  cross-field fact, so the `BOOT_REFUSALS` registry is untouched and
  its sweep stays green. The refusal message is pinned by a test that
  fakes the import failure, the `test_providers.py` precedent, so the
  pin runs in every lane whatever is installed.
- **`local_only`.** The exporter sends session metadata to wherever
  the environment points, and the server does not parse that
  environment to guess locality, so under the recorded decision it
  declares egress unconditionally: `server.local_only: true` with
  `telemetry.enabled: true` refuses at startup, with a sentence
  naming both keys. An operator running a genuinely local collector
  under `local_only` cannot trace today; that is the strict reading
  of the recorded decision, taken deliberately, and relaxing it later
  (an explicit locality declaration, the `openai_compatible`
  precedent) would be its own recorded change. The refusal is a
  cross-field fact between two config keys, but it crosses the
  file-half/composition seam the same way the provider egress check
  does, so it lives beside the egress machinery in the composition
  build, not as a model validator; if review prefers the
  `BOOT_REFUSALS` registry route, the condition is expressible there
  and the plan bends.

### Never blocking, concretely

The tap's `emit` runs synchronously on the reply path, so it does
what `LiveEvents` does: bounded work, no locks shared with the
export, no syscalls. Span construction is object assembly; the SDK's
`BatchSpanProcessor` owns the queue and the background thread, and
its queue is bounded and drops with a counter, which is exactly the
"dropped spans are acceptable, a stalled reply is not" posture. Two
sharp edges get explicit treatment: shutdown (the processor's flush
gets a bounded timeout and runs in the lifespan release, never on a
session's close path) and the exporter's own logging (the OTel SDK
logs export failures through `logging`; those loggers are pointed at
a quiet level so an unreachable collector does not spray the
structured log, and none of its output reaches the event surface,
which the AST guard and the no-leak sentinels already police).

### What the lanes test without the extra

`[otel]` joins the `dev` group (`vinga-server[serve,sim,otel]`): the
span-mapping logic is vinga logic and runs in every unit lane, unlike
the engine wrappers whose extras stay out of `dev` for weight. The
SDK is small, pure Python and Apache-2.0 (no licensing pressure of
the piper kind), so the contributor-checkout weight argument that
keeps `faster-whisper` and `piper` out does not apply. Unit tests drive the tap with the SDK's in-memory exporter
and assert span structure, attributes and the gen_ai mapping;
missing-extra behavior is pinned by faking the import, as above. The
tier-closure lane gets the `otel` fixture the way `sim` arrived, and
`tests/support/tiers.py` gains the distribution-to-import-name rows
so the wheel metadata check closes over the third extra.

### Verifying against a generic backend

Two layers, per the acceptance criteria:

- **In CI:** an integration test boots the server with telemetry
  enabled and `OTEL_EXPORTER_OTLP_ENDPOINT` pointed at a stub OTLP
  HTTP receiver in the test process, drives one simulator turn, and
  asserts a trace arrives whose spans decode (the proto package rides
  the exporter dependency) with the expected names, parentage and
  `gen_ai.*` attributes. A second integration case blackholes the
  endpoint (a non-routable address with a short SDK export timeout
  via the standard env vars) and asserts the turn's reply latency is
  indistinguishable from the telemetry-off baseline.
- **By hand, recorded on the PR:** Jaeger all-in-one from its
  published image, one simulator conversation, the trace queried over
  Jaeger's API; the walkthrough lands in the PR's verification
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
`build_telemetry(config) -> Telemetry | None` (None when disabled,
and the refusals above are this function's), the device session asks
the built object for a per-session tap the way it already attaches
`LiveEvents`, and the lifespan release calls its bounded `shutdown`.
Everything else, the SDK bootstrap, the clock offset, the span map,
the event-to-span-event fold, the gen_ai attribute table, is
implementation. The OTel imports happen inside the build function
(the registry's `_resolved` pattern), so the module imports clean
without the extra. The mapping table the conversation-store plan
promised ("#66/#67 exporters map by reading one table") is a literal
dict in this module: event field to OTel attribute, with the
deliberate non-correspondences (`provider`, `type`, `host` keep
vinga's names as plain attributes) stated beside it.

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

- **Unit, span structure:** drive `SessionEvents` with the baseline
  driver's event shapes through the telemetry tap into the in-memory
  exporter; assert per-turn root span, ASR/LLM/TTS child spans,
  span-event fold for the one-shot events, session attributes,
  gen_ai mapping, and the three-variant barge-in suppression fold.
- **Unit, refusals:** the missing-extra sentence (faked import), the
  `local_only` conflict sentence, and both refusal types staying
  inside `BOOT_FAILURES`.
- **Unit, no-leak:** the existing planted-credential sentinels
  already sweep attached taps; add the telemetry tap to that sweep
  so a credential-shaped value planted in an event never reaches an
  exported span's attributes, in either rendering.
- **Unit, catalog delta:** `heard.asr_ms` moves the baseline,
  `events.md` and the pins in one deliberate commit; the docgen
  drift check proves the regenerated page.
- **Unit, config:** `server.telemetry` in `config.example.yaml`
  satisfies the every-field sweep; unknown keys refused by
  `extra="forbid"` as everywhere.
- **Integration:** the stub-receiver trace assertion and the
  blackholed-endpoint latency case, above; the tier-closure `otel`
  fixture; the existing wheel lane picks up the `tiers.py` rows.
- **Byte-for-byte off:** the existing suites running with no
  `telemetry` section are themselves the proof the default path is
  untouched; the tap is simply never built, and a characterization
  assertion pins that `build_telemetry(None)` is None and attaches
  nothing.

## Risks

- **The catalog delta ripples.** Touching `Heard` moves the baseline,
  the docs and several pins at once. Mitigation: it is one field in
  one commit with the regenerations in the same change, the #437
  discipline.
- **The SDK's background thread meets the test lanes.** A batch
  processor thread per test server could leak across tests or hang a
  worker at exit. Mitigation: tests use the in-memory exporter
  (no thread) except the two integration cases, which shut the
  processor down with a bounded timeout in teardown; the bounded-
  runner rule from #283 applies to the stub receiver.
- **Clock skew inside a trace.** Mixing the offset conversion with
  any direct `time.time()` read would let spans disagree with their
  own events. Mitigation: the offset is the only conversion site,
  by construction in one module, and a test pins that a span's end
  equals its event's converted stamp.
- **The exporter's own logging leaks.** The SDK logs transport
  errors with prose that may embed the endpoint URL. Mitigation:
  quiet the SDK loggers at build time; the no-leak sentinel sweep
  covers the attached tap; nothing SDK-side ever reaches an emitter.
- **Filterwarnings is `error`.** Any OTel deprecation warning fails
  the lane. Mitigation: pin the SDK lower bound to a current
  release; allowlist nothing until a real warning forces a decision.

## Milestones

- [ ] **M1: the switch, the seam and the turn trace.** The `[otel]`
  extra (pyproject, `dev` group, `tiers.py` rows), the
  `server.telemetry` section with both example configs and the
  generated reference, both boot refusals with their pinned
  sentences, and `telemetry.py` building a real tracer that exports
  the per-turn root span with the session-level attributes. Design
  footprint: deepens the composition (one more built-and-released
  member) and adds the `telemetry.py` adapter at the events seam;
  callers stop knowing OpenTelemetry exists. Documentation
  footprint: generated `server-config.md` moves via its generator;
  `config.example.yaml` and `config.deploy.example.yaml` in the same
  change as the schema; CHANGELOG. Releasable alone: enabled means
  honest (thin) turn traces, disabled means today's server.
- [ ] **M2: the span map.** `heard.asr_ms` (catalog, baseline,
  `events.md`, pins, one commit), ASR/LLM/TTS child spans, gen_ai
  attributes on LLM round spans, the span-event fold for the
  one-shot events including the three barge-in suppression variants,
  the session-closed backstop for turns that never replied, and the
  no-leak sweep extension. Design footprint: deepens `telemetry.py`
  only; the catalog change is one field in its one home.
  Documentation footprint: generated `events.md` and
  `conversations-schema.md` cross-reference via generators;
  CHANGELOG.
- [ ] **M3: hostile collectors, the proof, and the image.** The stub
  OTLP receiver integration test, the blackholed-endpoint latency
  case, bounded shutdown in the lifespan release, quieted SDK
  loggers, `[otel]` in both image variants with the extras-import
  check, the tier-closure fixture, and the Jaeger all-in-one
  walkthrough recorded on the PR. Documentation footprint:
  `docs/architecture/observability-surfaces.md` gains the exporter
  as a surface with its retention answer (the collector's backend
  owns retention; vinga sends and forgets), and its still-open list
  drops #66; CHANGELOG.

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

2. **P1: `replied` is not an unconditional completion marker.** It
   is guarded by `if spoken:`; empty transcription, early failure
   and pre-sentence cancellation never emit it, and `session_closed`
   as a backstop gives false durations across still-open sessions.
   The reply `finally` needs an unconditional reply-finished event
   with a closed outcome.

3. **P1: Confirmed barge-in ASR cannot be reconstructed.** The
   confirmation transcription runs in the gate before `BargeIn` and
   the reused result deliberately leaves `TurnUnderway.asr_ms`
   unset, so the interrupting turn has no ASR latency and no
   utterance-end stamp under the proposed derivation. Measure and
   catalogue confirmation ASR at its decision site and carry the
   stamp across the gate.

4. **P1: The TTS narrowing contradicts a settled decision.** The
   issue requires per-sentence synthesis and playback-pacing spans;
   the plan's single speaking-window span measures neither, and the
   seams that distinguish them (`speak_after`, `ReplyPacer.transmit`)
   already exist. Add catalog events for per-sentence synthesis
   intervals and a separately bounded pacing interval, tested with
   lookahead overlapping playback.

5. **P1: Excluding `frames_dropped` contradicts a settled
   decision.** The capture-side record is already a bounded
   per-second aggregate, so the high-frequency objection does not
   apply. Promote the aggregate to a typed catalog variant that both
   capture and telemetry read; per-frame calls and `vad` stay
   outside the tap.

6. **P1: Resolved provider context is unavailable at the attachment
   point.** No catalog event carries the sanitized resolved provider
   entries (`SessionOpen` does not; the manifest is private to the
   session edge), so the promised span attributes would need a side
   channel, violating the one-vocabulary rule. Deepen `SessionOpen`
   with the sanitized entries and define what handover changes.

7. **P1: No destination for events outside an active turn.**
   `capture_started` precedes `session_open`, `session_idle` falls
   between turns, `session_closed` can land with no open turn; the
   plan defines only turn traces. Define a session-lifecycle trace
   with turn traces linked rather than parented, and state where
   pre-turn, between-turn and post-turn events land.

8. **P1: The GenAI mapping omits correspondences the repository
   already settled.** The conversation-store plan maps `type` to
   `gen_ai.provider.name` and `host` to `server.address` alongside
   `model` and usage; the plan kept `type` and `host` vinga-only.
   Ship the settled mapping; only `provider` (the configured entry
   name) stays vinga-specific.

9. **P1: The no-leak tests miss the exporter's most dangerous
   inputs.** Headers, endpoint userinfo, `OTEL_SERVICE_NAME` and
   automatic resource attributes enter below the catalog, and SDK
   logs may embed the endpoint. Build a fixed resource from
   server-owned values, keep endpoint and headers transport-only,
   install SDK logging protection before construction and restore it
   at shutdown, and plant sentinels in headers, endpoint userinfo,
   environment, logs, stderr, exception chains and exported spans
   during a failed export.

10. **P2: A telemetry `local_only` rule would duplicate the single
    egress home.** `egress.py` exists because duplicated enforcement
    diverged. Extend it with a generic declared-egress check the
    telemetry build invokes before any OTel import or construction,
    value-free and unchained, with a test that the exporter
    constructor is never reached under `local_only`.

11. **P2: Tap and tracer lifecycle ownership is incomplete.** The
    plan names attach and shutdown but not detach, and does not say
    whether it touches OTel's process-global tracer provider. Attach
    and register detach in the same breath, order teardown (stop
    emissions, detach, bounded shutdown), use an owned
    `TracerProvider`, and test two sequential lifespans and partial
    startup failure.

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
