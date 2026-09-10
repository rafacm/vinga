# Optional OpenTelemetry tracing over the event seam: implementation

Companion to [`2026-09-10-otel-tracing.md`](2026-09-10-otel-tracing.md),
one section per milestone, appended in the same change that ticks the
milestone checklist. It records deviations from the plan, resolutions of
the plan's open questions, and discoveries.

## M1: the catalog speaks the turn lifecycle

No OpenTelemetry anywhere, which was the milestone's own constraint: no
`[otel]` extra, no `server.telemetry` section, no `telemetry.py`. What
landed is vocabulary, its emit sites, and the pinned surfaces moving with
them.

### What was built

- **`turn_started`** (`catalog.TurnStarted`), emitted from
  `PipelineRuntime.start_reply`, which is the definition rather than a
  path list: the ordinary endpointed utterance, a manual stop, a
  confirmed non-empty barge-in and the `BargeInMerged` mid-ASR merge all
  arrive there, and a gate-rejected candidate never does. Fields
  `speech_ms` and `barge_in`.
- **`reply_finished`** (`catalog.ReplyFinished`), the first statement of
  `_reply`'s `finally` and ahead of every await. `outcome` is the new
  `values.ReplyOutcome` closed set, latched by `PipelineRuntime._latch`,
  write-once, first-writer-wins. `cancel_reply` takes the initiating
  outcome as an argument; the barge-in paths pass `barged_in`, the
  device abort and the session close pass `aborted`, the failure arm
  latches `failed`, the empty-transcript branch latches `nothing_heard`,
  and the `DeviceGone` catch latches `device_gone`. Field
  `sentences_spoken`. `replied` is untouched.
- **`heard.asr_ms`**, measured where the reply already measured its own
  ASR, and on the confirmed barge-in path measured by
  `TurnTaking._gate_barge_in` at its own decision site and carried over
  with the transcription it belongs to.
- **`nothing_heard`** (`catalog.NothingHeard`), where the empty
  transcript was a log-only line. `duration_s` and `asr_ms`, and no text
  field by type.
- **`sentence_synthesized`** (`catalog.SentenceSynthesized`), emitted
  when a `_Synthesis` stream ends, with `index`, `first_chunk_ms`
  (producer-side, before backpressure) and `stream_ms` (whole stream
  lifetime, whose docstring says it includes playback backpressure).
- **`speaking_finished`** (`catalog.SpeakingFinished`), emitted by the
  session edge from `finish_speaking`, before either cancellable send,
  only where at least one frame was delivered. The facts it needs are
  new per-reply state on `ReplyPacer` (`Delivered`: a successful
  delivery count and the last delivery's stamp), counted after `deliver`
  returns, reset at `reply_started` and not at `restart`.
- **`frames_dropped`** (`catalog.FramesDropped`), counted in
  `SessionEvents` behind the unchanged per-frame `dropped(reason)`
  signature and emitted through the ordinary seam on rollover and at the
  close. Counting runs regardless of capture state.
  `SessionCapture.dropped` and `SessionCapture._emit_dropped` are
  deleted, and `SessionRecording` is two methods rather than three.
- **`session_open.providers`**, from the new
  `ProviderWorld.resolved(agents)` derivation, typed as
  `values.ProviderEntries`, which the capture manifest and the store's
  session row read too.

Two new payload kinds were needed: `Kind.DROP_COUNTS` and
`Kind.PROVIDER_ENTRIES`, each with its sentence in
`events_docgen.KIND_MEANING` and its constraint cell.

### Deviations from the plan

1. **`SessionEvents.emit` gained an optional `at`.** The plan says
   `turn_started` carries "the original utterance-end instant the gate
   preserved" and names as a pin that "the emitted stamp predates the
   confirmation ASR's completion". The emitter stamped every emission
   with its own clock read at emit time, so there was no way to say
   that. `emit(build, at=None)` now accepts a reading of the same clock,
   used by exactly two sites: `turn_started` (the utterance's end) and
   `speaking_finished` (the last delivery). Everything else is unchanged
   and stamped where it is emitted.

2. **`start_reply` takes a `Utterance` rather than `(pcm, result)`.**
   Five facts had to cross from the floor to the reply (the audio, the
   utterance's end, how much of it was speech, whether it interrupted a
   reply, and the confirmation with its latency), and five parameters
   would have been a widening argument list at a seam the design guide
   asks to state as a type. `runtime/turntaking.Utterance` is that type;
   `_gate_barge_in` answers a three-tuple so the measured latency
   travels with the result it belongs to.

3. **`SessionEvents` gained a public `opened_at`.** The per-second
   dropped-frame aggregate needs a session origin to count seconds from,
   and the capture's own origin (`DeviceSession._opened_at`) is set
   inside the loop, after the emitter is constructed. The edge writes
   the same reading onto the emitter, so the JSONL's `second` numbering
   is still the capture timeline's. Before an origin is known the
   emitter answers second zero, which is an emitter built outside a
   session and has nothing to be misaligned with.

4. **The capture manifest and `sessions.providers` change shape.** The
   plan prescribes replacing "the manifest's current current-agent-only
   serialization" with the new derivation, and that is what landed:
   `{agent: {stage: {name, type, host?, model?}}}` where it was
   `{stage: {name, type, api_key_env?, egress?, **options}}`. Two
   consequences worth naming, because they are losses as well as gains:
   the record no longer carries the configured options (a `base_url`, a
   voice, a temperature) that `views.provider_record` masked on their
   way past, and it does carry the resolved host and every bound agent.
   The rule the plan is applying is the stronger one: four names off the
   built provider's identity cannot hold a credential at all, where a
   key-by-key record had to keep remembering to mask. The
   `sessions.providers` column comment follows through migration
   `1005_providers_are_per_agent`, comment-only, priced the way 1003 and
   1004 are; rows written before it keep the shape they were written in
   and are not rewritten.

5. **The turn record's `asr_ms` keeps its stricter meaning.** The plan
   speaks only of the event. `turns.asr_ms` says "null where no elapsed
   was measured this turn", and an interrupting turn still did not
   measure one, so it stays null there while `heard.asr_ms` carries the
   gate's measurement. The two answer different questions and both say
   so in their own words; making them one would have been a second
   comment migration for a fact the event already states.

6. **A cancelled synthesis emits no `sentence_synthesized`.** The plan
   says "when a sentence's synthesis stream ends". A stream a barge-in
   cancelled has no stream lifetime worth reporting: what would be
   measured is how far into it the interruption landed, which is a fact
   about the interruption. Streams that finish and streams that fail
   both report.

### Discoveries

- **The old empty-transcript log line was in no closed set.**
  `test_event_baseline.py`'s `UNTYPED` frozenset closes the set of
  untyped records on a scoped channel, and `session %s: nothing
  transcribed` was not in it, because no driver ever reached that branch.
  It is a typed event now, so the set is unchanged either way, but the
  gap is worth naming: the closed set only closes over what the drivers
  execute.

- **`drive_reply` bypasses `start_reply`.** The support helper awaits
  `PipelineRuntime._reply` directly, so the sixty-odd suites that drive
  a whole reply through it see no `turn_started` at all. That is correct
  for what those suites are about, and it is why the `turn_started`
  driver and the lifecycle suite go through `start_reply` instead. The
  helper's docstring now says so.

- **The barge-in latch has a real window.** `self._outcome` is cleared in
  `start_reply` and not in the reply body, because a canceller latches on
  the reply it is cancelling and then waits it out: by the time
  `start_reply` runs, the cancelled reply's `finally` has already
  emitted. A body that cleared its own latch would clear it whenever the
  loop got round to starting the task, which is after the next
  canceller could have written to it.

### Tests

`tests/unit/test_turn_lifecycle.py` is new and holds the four claims a
shape check cannot make: every `ReplyOutcome` member driven onto its own
decision site; consecutive silent and failed turns in one still-open
session each producing their pair; a confirmed barge-in stamped before
its own confirmation finished and carrying the gate-measured `asr_ms`,
with both rejected candidates (empty and failed) starting no turn and
leaving the reply in flight the same object; a cancellation delivered
into the filler settle leaving exactly one `reply_finished` with the
latched outcome; and a later sentence's synthesis stream living inside
the window `speaking_started` and `speaking_finished` bound.

Six drivers were added to `tests/tools/event_baseline.py` (ninety-three
to ninety-nine), with their `CARRIED` rows and the two changed rows for
`SessionOpen` and `Heard`. `test_capture.py`'s dropped-frame test drives
the emitter through the capture's tap now rather than the capture's own
counter, and the offset-clamping test beside it drives two ordinary
events, since the aggregate it used to use is not the capture's any more.

### Verification

`uv run ruff check .`: all checks passed. `uv run pytest tests/unit -q -n
auto --dist loadfile`: 5982 passed, 19 skipped. `uv run pytest
tests/integration -q`: 245 passed. The five generated-document drift
checks (`events reference`, `conversations schema`, `config reference`,
`config reference server`, `config openapi`) all diff clean against the
committed copies.

Re-run after the review round below: `ruff check .` all checks passed,
`mypy` no issues in five source files, `pytest tests/unit -q` 5985
passed and 19 skipped, `pytest tests/integration -q` 245 passed, and the
five drift checks clean again. A first attempt at both lanes failed with
mass connection errors while a sibling worktree drove the same Postgres;
the runs above are the reruns, and the failing one is recorded here
rather than dropped because a lane that goes red for the instance rather
than for the change should say so.

### PR review round

External review of PR #442, sol, four findings, verdict mergeable after
fixes. Each is recorded with what the fix did, because two of them
changed the catalog and one changed an interval's meaning.

1. **P1: a mid-ASR merge left the interrupted turn with no ASR
   outcome.** The merge cancels the reply while its `transcribe` call
   is still running, and `_watching` reports an `Exception` rather than
   a cancellation, so that turn opened with `turn_started`, closed with
   `reply_finished` and said nothing about the stage between them.
   Fixed by declaring the fourth way an ASR stage ends,
   `transcription_abandoned`, with the utterance's length and how long
   the call had been running when it was given up on, emitted where the
   cancellation is caught beside the call. Deliberately not
   `provider_failed`: nothing failed, the answer was no longer wanted,
   and a record naming a provider would send an operator looking at a
   network. The reference, the README index and a hundredth baseline
   driver move with it, and a real-runtime mid-ASR merge test asserts
   both turns' sequences whole.

   This narrows the plan's "every `turn_started` is followed by exactly
   one of the three": there are four, and the fourth is the one that
   says the stage was cut short.

2. **P1: a disconnect while showing the transcript dropped a completed
   ASR outcome.** `heard` was emitted after `show_transcript`, which is
   a socket call, so a transcription that succeeded and a disconnect a
   millisecond later ended the turn `device_gone` with no ASR outcome at
   all. Fixed as prescribed: the record is made where the result is
   classified, ahead of any await, and a disconnect test asserts the
   turn's sequence is exactly `turn_started`, `heard`, `reply_finished`.

3. **P2: the playback window opened before the first frame reached the
   device.** `speaking_started` was emitted where a batch was handed to
   the pacer, so the frame's slot in the cadence, a confirmation's
   pause and the send itself all fell inside an interval the reference
   calls first frame out to last frame out, while `speaking_finished`
   closes it at a real delivery. Fixed as prescribed: `transmit`
   answers the instant of the first successful delivery and the edge
   emits the event retrospectively at that stamp; `first_frame` is
   gone. A test holds the first delivery and proves the event is not
   stamped early, and the characterization pin that used to assert the
   old order moves with a note saying which order is now correct and
   why.

4. **P3: the manifest docstring described the removed serialization.**
   Updated to the sanitized per-agent derivation: four names off each
   built provider, nothing to hold an environment variable name and
   nothing to mask.

## M2: the switch, the seam and the hardened exporter

The exporter exists, is off, and refuses three ways when it is on and
cannot be. What landed is one module, one configuration key, a fourth
dependency tier, and the hardening that had to arrive in the same
milestone as the first export.

### What was built

- **The `[otel]` extra**: `opentelemetry-sdk` and
  `opentelemetry-exporter-otlp-proto-http`, both pinned at `>=1.44.0`,
  which is a current release rather than the oldest that works because
  `filterwarnings` is `error`. It joins the `dev` group
  (`vinga-server[serve,sim,otel]`), unlike the two engine extras: the
  span mapping is vinga logic every unit lane runs, and neither the
  weight argument nor the licensing one applies to a small pure-Python
  Apache-2.0 SDK.
- **The tier machinery, three to four.** `tests/support/tiers.py`
  answers a `Tiers` record now instead of a positional triple,
  `OTEL_MODULES` is its import map, the closure lane gained an isolated
  `[otel]` environment with the exactness comparison, the bite and both
  negative halves, and the wheel lane closes over the fourth extra in
  both directions. The plain `[serve]` environment is untouched.
- **`server.telemetry`** (`config/models.TelemetryConfig`), the
  `capture`/`conversations` optional-section pattern exactly:
  `extra="forbid"`, one `enabled: bool = False`, absent by default. Both
  example configs document it commented out and the generated server
  reference moved with it.
- **`egress.check_feature`**, the third shape of the one egress rule: a
  declaration that is neither a provider class's marking nor an
  operator's entry, for a feature whose reach is a property of what it
  is. The telemetry build declares `True` unconditionally.
- **`src/vinga_server/telemetry.py`**: `build_telemetry(config, *,
  local_only=False, ...) -> Telemetry | None`, with the OTel imports
  inside the build (the registry's `_resolved` pattern) so the module
  imports clean without the extra. The built object owns its
  `TracerProvider`, fixes its resource to `vinga-server` plus the build
  revision with no environment pass-through, records one
  monotonic-to-epoch offset from two back-to-back clock reads, and puts
  its spans behind a `BatchSpanProcessor` with a bounded queue. The SDK's
  whole logging namespace is quieted before construction and restored at
  shutdown.
- **The wiring**: `Composition.telemetry`, built first of everything in
  `_build_composition`; the server tap attached with its detach
  registered in the same breath; the device session asking for a
  per-session tap beside `LiveEvents`; and three exit-stack
  registrations whose LIFO order is the teardown's (stop accepting,
  detach, bounded shutdown).
- **M2's span map**: the session root span from `session_open` to
  `session_closed` with the close reason, turn root spans opened at
  `turn_started` with the utterance-end stamp and closed at
  `reply_finished` with the outcome, each in a trace of its own with an
  OTel link back to the session span, and everything else folded as a
  span event onto whichever span is open. `capture_started` arrives on
  the server tap ahead of its session and is held, bounded, until the
  span exists.

### Deviations from the plan

1. **`build_telemetry` takes the section, not the whole
   `ServerConfig`.** The plan writes `build_telemetry(config)` and the
   milestone's own pin is that `build_telemetry(None)` is None. Those
   two only agree if the argument is `TelemetryConfig | None`, where
   None IS the absent section; a `ServerConfig | None` would have made
   the pin a statement about a server with no configuration, which is
   not a state that exists. `local_only` is therefore a keyword
   argument, which the composition passes from the same object.

2. **`egress.check_feature` takes a `bool`, not the MCP tri-state.** The
   MCP shape has three answers because an operator may decline to
   declare; a feature that is not configured has no such hole, so the
   two-state version has no unreachable branch. The declaration is still
   the argument rather than implied by the call, so the call site says
   what it is claiming.

3. **`detach_live` became `detach_observers`.** A session now attaches
   two taps at construction and has to take both off however the
   connection ended, and a method named after one of them would have
   been a name that lied at the second. It is still a detach and never a
   shutdown, which the docstring says: the exporter outlives every
   session it watched, and a conversation ending must not be able to
   stop a server exporting.

4. **`SessionEvents.taps()` and `events.server_taps()` are new.** The
   claim "telemetry off attaches nothing" is a claim about the emitter
   and the hub, and both held their tap lists privately, so the tests
   for the milestone's own headline would have been underscore
   reach-ins. Both are one-line readers beside `server_emitters()`,
   which already exists for the same kind of question.

5. **`Telemetry.flush()` is public.** For the same reason: "has what I
   emitted actually left" cannot be answered from outside an exporter,
   the shutdown asks it implicitly, and the alternative was every
   telemetry test reaching for `_provider`.

6. **The lifecycle cases are in the unit lane and the saturation case in
   the integration lane**, which is what the plan's own test section
   says; the milestone bullet reads as though all the hardening were one
   lane's. The saturation case drives real scripted replies through
   `tests/support/sessions.py` rather than over the wire: what it
   measures is the reply path, and a websocket in front of it would add
   noise to the number being bounded.

7. **The span attribute names are vinga's own (`vinga.session.id`,
   `vinga.turn.outcome` and their neighbours).** The settled `gen_ai.*`
   correspondence belongs to the stage spans, which are M3's; nothing on
   a session or turn root span is a GenAI fact, and putting one there to
   have used the table would have been the wrong altitude.

### Discoveries

- **`session_open` is the edge's, so a session built below the edge has
  no trace at all.** `tests/support/sessions.py` builds sessions by
  transcribing what `run` does, and `session_open` is not among the four
  lines it transcribes. A turn whose session span does not exist opens
  nothing (there is nothing to link to), so the saturation case emits
  the open by hand. Worth naming because it is the same gap the M1 notes
  found for `drive_reply`: the support helpers stand in for the edge at
  a precise depth, and the events emitted above that depth are not among
  what they provide.

- **A namespace package defeats a top-level import map.**
  `SERVE_MODULES` and `SIM_MODULES` map a distribution to the top-level
  module it installs, and for OpenTelemetry that module is
  `opentelemetry` for every distribution in the ecosystem. Importing it
  says nothing about which one is installed, so `OTEL_MODULES` maps to
  the subtree instead (`opentelemetry.sdk`,
  `opentelemetry.exporter.otlp.proto.http`), which is also what makes
  the `[serve]` environment's negative check mean something.

- **`Resource.create()` is the leak, not the exporter.** The obvious way
  to build a resource merges `OTEL_SERVICE_NAME` and
  `OTEL_RESOURCE_ATTRIBUTES` into what every span carries, which is
  environment-derived text on the retained surface and would have passed
  every test that did not plant a sentinel there. The constructor is
  used directly, and the sentinel battery plants a value in both.

- **A shared Postgres instance is what makes the parallel unit lane look
  broken.** Running `-n auto` against the instance another worktree was
  already using produced a dozen `OperationalError: server closed the
  connection unexpectedly` failures scattered across unrelated suites.
  An instance of this worktree's own (`VINGA_DB_PORT=55432 docker
  compose up -d --wait postgres`) turns the same command green. Nothing
  to do with this change, and worth an hour to somebody who meets it.

### Tests

`tests/unit/test_telemetry.py` holds the switch, the three refusals and
the span map: `build_telemetry(None)` is None and attaches nothing;
`local_only` refuses with the egress module's own sentence, unchained,
value-free, and with both `_import_sdk` and `_otlp_exporter` proven
never called; the missing extra refuses with the registry's sentence
shape, faked by putting `None` in `sys.modules` so the real import
statement raises a real `ImportError`; an unsupported protocol is
refused by naming the supported one and never quoting the rejected one.
The fold is driven through a real `SessionEvents` into the SDK's
in-memory exporter for the session span, the linked turn traces, two
turns as two trace ids, the between-turn and inside-turn destinations,
the capture-before-open hold and its bound, and the one-offset pin (a
span's converted end equals its event's converted stamp, exactly). The
no-leak battery plants a credential-shaped value in the OTLP headers
variable, in endpoint userinfo, in `OTEL_SERVICE_NAME` and in an event
payload, and hunts it in exported span data, in both log formats and in
stderr, including during an export against an endpoint nothing answers.

**Correction.** The sentence above said "and in an event payload" before
the PR review round, and it was not true: three of the four sentinels
were planted and the fourth was not. It is recorded here as a
correction rather than quietly rewritten, because a verification note
claiming a test that does not exist is worse than one that admits a
gap: the next reader would have taken the payload surface as covered.
What made it false is also what made it matter, and both are the review
round's finding 3 below.

`tests/unit/test_telemetry_lifecycle.py` runs the whole composition
twice in one process, refuses a boot after the exporter was built, and
pins that a stopped exporter takes no more emissions.
`tests/integration/test_telemetry_hardening.py` is the saturation case
and the bounded shutdown against a wedged collector.

### Rebasing onto M1's review round

M1 merged with four review fixes on top of the branch point this
milestone was cut from, and two of them touch what the fold reads.

`transcription_abandoned` is the fourth way an ASR stage ends and lands
INSIDE a turn, which is exactly the case an exporter that enumerated the
events it knew would have dropped in silence. Nothing here enumerates
them: the span map names four lifecycle events and one server-channel
one, and everything else folds as a span event onto whichever span is
open. So the new variant needed no row, and it now has a pin saying so,
which is the more useful thing to own: `test_telemetry.py` drives it
into an open turn and asserts it arrives on the turn trace with its
fields and not on the session span.

`speaking_started` moved to the first delivery's stamp and
`ReplyPacer.first_frame` was deleted. Neither reaches this milestone:
the span map does not name `speaking_started` at all (the paced-playback
span it bounds is M3's), and nothing written here touched the pacer. The
grep is recorded because the deletion is the kind a rebase silently
undoes.

### Verification

`uv run ruff check .`: all checks passed. `uv run mypy`: success, no
issues in 5 source files. `uv run pytest tests/unit -q -n auto --dist
loadfile`: 6015 passed, 19 skipped. `uv run pytest tests/integration
-q`: 255 passed. The five generated-document drift checks (`events
reference`, `conversations schema`, `config reference`, `config
reference server`, `config openapi`) all diff clean against the
committed copies.

### PR review round

External review of PR #446, sol, three P1 and two P2, verdict not
mergeable. Each is recorded with what the fix did, because three of
them changed what reaches a span and one of them corrects a claim this
document made.

1. **P1: a malformed `OTEL_EXPORTER_OTLP_*` value escaped as a raw SDK
   traceback.** The SDK parses several members of that family eagerly
   inside the exporter's constructor and quotes what it was handed, so
   `OTEL_EXPORTER_OTLP_TIMEOUT=sk-live-...` raised a `ValueError`
   carrying the value; the build restored logging and re-raised it
   unchanged, and `ValueError` is outside `BOOT_FAILURES`, so an
   operator got uvicorn's traceback with a credential in it and exit
   code 3. Fixed as prescribed: every failure of that construction is
   contained, the exception is never bound, anything half-built is shut
   down rather than abandoned with a thread running, and one fixed
   value-free `ConfigError` is raised outside the handler. Two lanes,
   because the family has two halves: the whole boot for the member
   that refuses, and the build alone for all five malformed members in
   a process of its own with logging wide open, since three of the five
   are ACCEPTED by the SDK and one of those logs the value it could not
   parse while accepting it.

2. **P1: a timed-out shutdown restored the SDK's logging while the
   abandoned export could still fail.** The wait was bounded and the
   restore was tied to the wait, so an export the timeout left in
   flight failed a moment later and logged the endpoint it could not
   reach, userinfo and all, into a log nothing was watching. Fixed as
   prescribed: the wait is bounded and the quieting is not. A release
   worker owns the provider's shutdown and restores from its own
   `finally`; the public `shutdown` only stops the lifespan waiting. It
   is a daemon thread rather than `asyncio.to_thread`, because the
   default executor's threads are joined by an `atexit` hook and
   abandoned work on one of them would hold the process open exactly as
   long as the collector felt like holding it. The test that covered
   this released the blocking exporter immediately after `shutdown()`
   returned, which masked the whole window; it now fails AFTER the
   timeout with a credential in the message and waits on the SDK's own
   last act rather than on anything that races it. Reverting the
   restore to the wait makes it fail with the sentinel in a traceback,
   which is the mutation that says it bites.

3. **P1: the event-payload sentinel was never planted, and this
   document said it was.** The fold copied a payload wholesale, taking
   every key but the three identities, so what reached a backend was
   whatever the dict held. Fixed as prescribed with an explicit safe
   mapping: the fold iterates an APPROVED table derived from the
   catalog's own declarations, so a key the catalog does not declare
   for that event is not exported whatever put it there, and what each
   declared field becomes is decided by its `Kind` through a table with
   a row per member, held to the enumeration in both directions. The
   sentinel is planted through `EventTap.emit` with a payload the
   emitter could not have built, which is the point: the question is
   what the CONSUMER does when handed one.

   *The correction.* The Tests note above claimed the battery planted a
   value "in an event payload". It did not; three of the four sentinels
   were planted and that one was not. The note now carries the
   correction inline rather than being quietly rewritten, because a
   verification claim about a test that does not exist is worse than an
   admitted gap: the next reader would have taken the payload surface
   as covered and looked elsewhere.

4. **P2: two mapping fields were being dropped by the SDK in silence.**
   OTel attributes are scalars and sequences of scalars, so
   `prompt_assembled.sources` and `frames_dropped.reasons` arrived on a
   span as nothing at all, with the SDK's warning about it already
   silenced by this module. Fixed as prescribed: both are bounded,
   server-owned mappings of names to numbers, and their kind now maps
   to deterministic JSON (sorted keys, no spaces) under the field's own
   name. The exact strings are asserted, and a third case builds the
   same mapping in the other insertion order and insists the attribute
   is identical.

5. **P2: the resolved provider entries were on no span.** M1 deepened
   `session_open` to carry them for every bound agent and nothing read
   them: the attribute tables omitted the field, `handover` updated no
   active-agent state, and the fixtures opened against an empty
   mapping, so the gap was invisible from both ends. Fixed as
   prescribed: the entries are retained whole at the open, `handover`
   moves which agent is active, the session span is stamped with the
   agent it opened with and each turn span with the agent that turn is
   spoken by. Flattened per stage rather than dumped as a blob, because
   a backend filters on attributes and a JSON blob would be present and
   unqueryable, which for this question is the same as absent. The
   shared fixtures open against two agents on different models, so the
   before-and-after-handover assertions can tell a handover from a
   constant.

The three fixes that touch the fold share one mapping, which is what
finding 5's note asked for: `SHAPES` decides what a payload kind
becomes, `APPROVED` decides which fields an event may contribute, and
both the span-attribute tables and the span-event fold read them, so
this module has one answer to "what may a payload field become on a
span" rather than one per surface.

### Verification after the review round

`uv run ruff check .`: all checks passed. `uv run mypy`: success, no
issues in 5 source files. `uv run pytest tests/unit -q -n auto --dist
loadfile`: 6023 passed, 19 skipped. `uv run pytest tests/integration
-q`: 262 passed. The five generated-document drift checks all diff
clean against the committed copies.

### Delta re-review

External review of the fixes above, terra, three findings, all of them
introduced BY those fixes rather than surviving them; everything else
was confirmed to hold. Verdict not mergeable.

1. **P1: overlapping lifespans raced the logging restore.** The
   quieting was snapshotted and restored per exporter, which is correct
   for one at a time and wrong the moment two overlap, and two overlap
   routinely once a wedged exporter's release outlives the bounded wait.
   In order: A wedges and its wait expires; B is built and quietens an
   already-quiet namespace, so B's snapshot records SILENCE; A's
   abandoned release finishes and restores the ORIGINAL configuration,
   un-silencing the SDK while B is still exporting, so B's next failure
   logs its credentialed endpoint; then B's release restores A's quiet
   snapshot and the namespace stays silent for the rest of the process
   with nothing holding it. Fixed as prescribed: one process-wide,
   locked, reference-counted lease, snapshot taken at the first
   acquisition and put back after the last release, with a lease given
   back twice counted once. The regression drives that exact sequence.

   Two things came with it. `_release` became the public `release`,
   because a caller holding an exporter it no longer wants and nothing
   to wait for needs the blocking form and `shutdown` is that same work
   off the loop and bounded. And the telemetry suites drain their leases
   after every case and assert the count is zero: thirty cases that
   built an exporter and released none used to be invisible, and under
   a counted lease they are a namespace silenced for the rest of the
   run, which is a leak a server would have too.

2. **P1: `Shape.CONTEXT` bypassed the catalog's own validation.**
   `providers` is the one payload field whose content becomes part of an
   attribute NAME, and the fold walked the mapping itself, checking only
   that a stage was a string and an entry a dict. A payload handed to
   `EventTap.emit` could therefore choose the key, and an arbitrary
   stage with a credential in `name` reached a span as
   `vinga.provider.<whatever was sent>.name`, which defeats both
   promises this context makes: bounded cardinality, and sanitized by
   construction. Fixed as prescribed by validating through
   `ProviderEntries` before anything is retained, which is the type that
   makes those promises: agent names as identifiers, stages from the
   pipeline's own set, entries with their required pair and no fifth
   key, values as identifiers. A hostile payload with an arbitrary
   stage, a fifth key and the sentinel in three places produces no
   provider attributes at all.

3. **P3: a release thread that would not start left nothing owning the
   exporter.** The finished event was recorded before `Thread.start()`,
   so a creation that raised meant every later shutdown waited its whole
   bound on an event nobody would set, and the lease was held for the
   life of the process. Fixed with a defined ending rather than a best
   effort: the lease goes back, the wait ends, and one plain sentence
   says the work was left to the process's exit. The provider is
   deliberately NOT shut down inline, because that call blocks for as
   long as the collector takes and this runs on the event loop; what is
   lost is the SDK's own daemon thread, which dies with the process.

All three regressions were mutation-checked: reverting each fix
reproduces the reported failure (a credentialed endpoint in a
traceback, `vinga.provider.../../etc/passwd.name`, and a shutdown that
waits its whole bound).

### Verification after the delta round

`uv run ruff check .`: all checks passed. `uv run mypy`: success, no
issues in 5 source files. `uv run pytest tests/unit -q -n auto --dist
loadfile`: 6027 passed, 19 skipped. `uv run pytest tests/integration
-q`: 262 passed. The five generated-document drift checks all diff
clean against the committed copies.

### Confirmation round

External review of the delta fixes, terra, one finding. Verdict not
mergeable as is.

1. **P1: the public `release` was not once-only.** Making `_release`
   public gave the same operation two doors, and neither knew about the
   other: a direct `release()` and `shutdown()`'s worker could both be
   inside `provider.shutdown()` at once. That is a leak rather than a
   waste, and the reason is the SDK's own guard: a batch processor
   early-returns from a second shutdown, so the second caller finished
   instantly and gave the logging lease back while the first was still
   exporting, un-silencing exactly the endpoint-bearing failures the
   first one was about to log. The lease lock protected the count and
   nothing owned the release.

   *Resolution.* Adopted as prescribed. Shutting the provider down and
   giving the lease back is one completion, claimed under the lock by
   the first caller through, and every later caller (either door, any
   mix) waits on it rather than starting another; one that arrives
   after it is over returns at once. The thread-start-failure path
   keeps its semantics and is stated as what it always was, a
   completion: it returns the claim and ends the wait without touching
   the provider, because that call blocks for as long as the collector
   takes and this runs on the event loop.

   The review also noted that the suites' own teardown called
   `release()` on exporters already released and asserted nothing about
   it. That shape is now what the regression's last two lines are
   about, so the fixture is exercising a stated contract rather than an
   accident.

   The regression drives both doors at once against an exporter whose
   shutdown the test holds open, and asserts the lease is still held
   while the second caller has already returned, that the provider was
   shut down exactly once, and that a caller arriving afterwards does
   none of it again. Ungating `release` makes the lease assertion fail
   with the count already back to zero, which is the finding.

### Verification after the confirmation round

`uv run ruff check .`: all checks passed. `uv run mypy`: success, no
issues in 5 source files. `uv run pytest tests/unit -q -n auto --dist
loadfile`: 6028 passed, 19 skipped. `uv run pytest
tests/integration/test_telemetry_hardening.py -q`: 3 passed. The five
generated-document drift checks all diff clean against the committed
copies.

## M3: the full span map, the proof and the image

The turn trace gained what is inside it, the proof moved from an
in-memory exporter to a collector's wire, and the extra is in both
images. One bug was found that no test in this repository could have
found, and it was found by the walkthrough the acceptance criteria asked
for.

### What was built

- **The stage spans**, all four constructed retrospectively out of the
  event that ended each and the duration the pipeline had already
  measured. `asr`, from all four ends of the ASR stage (`heard`,
  `nothing_heard`, `provider_failed` at the ASR stage,
  `transcription_abandoned`), with the outcome as the event's own name,
  the utterance's length, the detected language where one was, and the
  exception's class name and an ERROR status on the one of the four
  that is a failure. `llm`, one per `llm_round`, carrying the settled
  correspondence exactly (`type` to `gen_ai.provider.name`, `model` to
  `gen_ai.request.model`, `host` to `server.address`,
  `input_tokens`/`output_tokens` to the GenAI usage keys) with
  `provider`, the configured entry name, as the one vinga attribute
  among them, and `first_token_ms` as a span event inside the round.
  `tts_stream`, one per `sentence_synthesized`. `playback`, bounded by
  `speaking_started` and `speaking_finished`, with the frame count.
- **The fold became a table with a default**, `Telemetry._folds`:
  twelve names have a shape of their own and everything else, present
  and future, is a span event on whichever span is open. The three
  barge-in suppression variants keep their own names and their fixed
  reasons, and the promoted `frames_dropped` needed no row.
- **`tests/integration/test_telemetry_export.py`**, the stub OTLP
  receiver: the real server booted with the exporter on, the standard
  endpoint variable pointed at an HTTP receiver in the test process, one
  simulator turn, and the protobuf decoded with the proto package the
  exporter's own dependency installs.
- **The blackholed endpoint**, a third case in
  `test_telemetry_hardening.py`, with the real transport in place and
  the SDK's own timeout variables.
- **`[otel]` in both image variants**, with the extras-import check
  naming the SUBTREES, and the reinstated claim that both images carry
  it.
- **One offset per clock**, which is the bug below.

### Deviations from the plan

1. **The paced-playback span is held open past `reply_finished`.** The
   plan has the pair bound the interval and says nothing about the
   emission order, which turns out to be the opposite of the reading
   order: `reply_finished` is the reply `finally`'s FIRST statement and
   `finish_speaking` is its last, so the event that closes the interval
   is said after the event that closes the turn while being stamped at
   the last delivery, which precedes both. Dropping an open playback at
   the turn's close, which the first cut did, dropped every playback
   span a real reply produced. The span is now left for its own event
   to end it and what it bounds is unchanged; a next turn and the
   session's close each drop one whose event never arrived, which is
   the only shape a cancellation delivered into the reply's very last
   statement can leave.

2. **`provider_failed` is an ASR outcome only at the ASR stage.** The
   plan lists it among the ASR ends without saying what an LLM or TTS
   failure does. Those end no interval this exporter draws (the `llm`
   and `tts_stream` spans are built from the rounds and streams that
   FINISHED), so they fold as span events onto the turn, and a span
   built from a failure would claim an interval nobody measured.

3. **The ASR span does not repeat `asr_ms` as an attribute.** The span's
   extent IS that measurement, and two structures that must agree are
   one structure with a bug pending. An outcome that carried no latency
   gets a span with no extent, which says the stage ended here and
   declines to say when it began.

4. **The GenAI table is not pinned by value in the integration lane.**
   That lane's providers are the mocks, which report no host, no model
   and no usage, and an absent field is the catalog's answer to an
   unreported fact. So the decoded case pins the key that IS reported,
   spelled exactly, plus the ABSENCE of the ones nothing measured; the
   whole table's values are pinned against a real quartet in
   `test_telemetry_spans.py`.

5. **The slim image gained a positive import check.** The plan leaves
   the slim job's engine-refusal check untouched, and it is untouched:
   the refusal loop is exactly as it was. Beside it, where the existing
   `pysilero_vad` assertion already lives, the slim image is now asked
   to import the OTel subtrees too, because "both images carry the
   extra" is a claim this milestone makes in three documents and an
   unasserted claim about an image is one that goes stale in a
   dependency bump nobody connects to it.

6. **The exporter has two offsets, not one.** The plan says one
   monotonic-to-epoch offset for the process. That is one offset too
   few, and the discovery below says why.

### Discoveries

- **The events package has two clocks, and uvloop makes the difference
  enormous.** A session event is stamped with the session loop's clock
  (`asyncio.get_running_loop().time()`, because the capture's audio
  tracks are aligned by it) and a server event with `time.monotonic`
  (because server events fire where no loop is running). Under uvloop,
  which is what uvicorn runs when it is installed, the loop's clock is
  libuv's and shares no origin with `time.monotonic`: on the machine
  this was found on they read 131,249 seconds apart, thirty-six hours.
  One offset for both put every session span thirty-six hours in the
  future. Jaeger accepted them, saved them, indexed their operation
  names, and answered every trace search with nothing at all.

  Nothing in this repository could have caught it. Every unit case
  drives a clock anchored on `time.monotonic`, and the integration lane
  runs on the plain asyncio loop where the two clocks agree by
  construction; the shape of a trace is right either way, and shape is
  what a structural assertion reads. The fix is one offset per clock:
  the server clock's read at construction, the session clock's read at
  the FIRST session emission, which is a reading taken on the loop that
  does the stamping, whatever loop that turns out to be. The pin drives
  a session clock a uvloop-shaped gap away and asserts the exported span
  lands on now, and the decoded case now asks the wire the same question.

- **A span event on a closed turn lands on the session.** `replied` and
  `speaking_finished` are both emitted after `reply_finished`, so in a
  real conversation `replied` appears as a span event on the SESSION
  span rather than on the turn it describes. That is the default fold
  working as designed rather than a defect, and it is worth writing
  down because a reader looking for `replied` inside a turn will not
  find it there.

- **Jaeger's operations index and its trace search disagree happily.**
  `/api/operations?service=vinga-server` listed all six span names while
  `/api/traces?service=vinga-server` answered nothing, for the whole
  time the timestamps were wrong. A collector that has stored a span is
  not a collector that will show it to you, which is the difference
  between the stub receiver's proof and this walkthrough's.

### The Jaeger walkthrough

Run on 2026-09-10 against Jaeger's published all-in-one image, on the
real server started from a YAML file with its domain half in Postgres,
driven by the packaged device simulator. Recorded verbatim, including
the first run, which is the one that found the bug.

```
docker run --rm -d --name vinga-jaeger-m3 \
  -p 16686:16686 -p 4318:4318 jaegertracing/all-in-one:1.60

# the server, telemetry on, pointed at Jaeger's OTLP HTTP port
VINGA_DB_PORT=55433 VINGA_DB_HOST=127.0.0.1 \
VINGA_API_SECRET=... \
OTEL_EXPORTER_OTLP_ENDPOINT=http://127.0.0.1:4318 \
  uv run vinga-server --config config.yaml
# config.yaml: server.telemetry.enabled true, server.auth.enabled false,
# server.port 8103, server.api.secret_env VINGA_API_SECRET

uv run vinga-server config import -f document.yaml --config config.yaml
uv run vinga-server config apply --config config.yaml --force
# mock providers for the four stages, one agent, default_agent set

uv run vinga simulator run http://127.0.0.1:8103/x/ --config config.yaml
#   saying: Hello, can you hear me?
#   heard: hello from a simulated board
#   said: You said hello from a simulated board.
#   reply: 26 frames, 12454 bytes, about 1560 ms of audio
#   close: the session ended normally

curl -s "http://127.0.0.1:16686/api/traces?service=vinga-server&lookback=1h&limit=20"
```

**The first run.** `/api/services` listed `vinga-server` and
`/api/operations?service=vinga-server` listed all six operation names
(`session`, `turn`, `asr`, `llm`, `tts_stream`, `playback`); Jaeger's own
metrics said `jaeger_collector_spans_saved_by_svc_total{svc="vinga-server"}
12`. Every trace search answered `{"data":[],"total":0}`, at every
lookback and with an explicit start and end spanning a day either side.
A plain probe trace sent from the same machine was searchable
immediately, and so was a probe built in exactly this exporter's shape
(explicit start and end times, an empty context, a link, a child span),
which is what narrowed it to the timestamps and then to the two clocks.

**The second run, after the fix.** The same commands, and the search
answered two traces:

```
 trace fc7a7d4f354f06f1d502a190454bb0cf
    session dur_us= 3319000 refs= []
 trace 13d3a1f70f595322f185b150da8790b6
    asr dur_us= 0 refs= [('CHILD_OF', '9eafe277d68b49b0')]
    turn dur_us= 1524999 refs= [('FOLLOWS_FROM', '83a200f05197cab2')]
    llm dur_us= 20000 refs= [('CHILD_OF', '9eafe277d68b49b0')]
    tts_stream dur_us= 1387000 refs= [('CHILD_OF', '9eafe277d68b49b0')]
    playback dur_us= 1500000 refs= [('CHILD_OF', '9eafe277d68b49b0')]
```

The turn is a trace of its own whose only reference is the
`FOLLOWS_FROM` Jaeger renders an OTel link as, pointing at the session
span; the four stages are `CHILD_OF` the turn. The attributes, as
Jaeger shows them:

```
session   {"vinga.agent": "assistant", "vinga.conversation.id": "...",
           "vinga.device.id": "02:00:00:00:00:01", "vinga.device.protocol": 1,
           "vinga.session.close_reason": "client",
           "vinga.session.duration_s": 3.32, "vinga.session.id": "..."}
   log: event=replied agent=assistant conversation=... sentences=1
turn      {"vinga.turn.barge_in": false, "vinga.turn.outcome": "completed",
           "vinga.turn.sentences_spoken": 1, "vinga.turn.speech_ms": 1140, ...}
asr       {"vinga.asr.duration_s": 1.68, "vinga.asr.outcome": "heard"}
llm       {"gen_ai.provider.name": "mock", "vinga.provider": "mock",
           "vinga.llm.round": 1, "vinga.llm.turns": 1, "vinga.agent": "assistant"}
   log: event=first_token
tts_stream {"vinga.tts.first_chunk_ms": 0, "vinga.tts.index": 0, ...}
playback  {"vinga.playback.frames": 26, "vinga.agent": "assistant"}
process   {"service.version": "..."} and service.name vinga-server
```

`asr` has a duration of zero because the mock ear answers instantly, and
`gen_ai.request.model`, `server.address` and the usage keys are absent
because a mock provider names no model, reaches no host and reports no
usage. `replied` appears on the SESSION span, not the turn, for the
ordering reason recorded above. The acceptance criterion is met: the
trace was rendered by a generic OTLP backend that has never heard of
this project, and every attribute a person would search on is visible in
it.

Torn down afterwards: `docker rm -f vinga-jaeger-m3`, the server stopped,
and the worktree's Postgres brought down.

### Tests

`tests/unit/test_telemetry_spans.py` is new and holds the stage map: the
four ASR ends with their outcomes, their extents and the one status;
the GenAI keys pinned by name and by value with the set of foreign
prefixes closed; the first-token mark and its absence; two rounds in one
turn; the stream span's name and the absence of anything called
synthesis; the paced interval closing after its turn and being dropped
when its event never comes; a whole turn read as one trace; the three
suppression variants and the dropped-frame aggregate still folding. Two
clock cases joined `test_telemetry.py`, and the case there that pinned
the default fold on `transcription_abandoned` now pins it on `barge_in`,
since the abandoned transcription became a stage span.

`tests/integration/test_telemetry_export.py` is the stub receiver, and
`test_telemetry_hardening.py` gained the blackholed endpoint.

### Verification

`uv run ruff check .`: all checks passed. `uv run mypy`: success, no
issues in 5 source files. `uv run pytest tests/unit -q -n auto --dist
loadfile`: 6039 passed, 19 skipped, with the command-spellings census
regenerated afterwards for the changelog's new lines and green on the
rerun. `uv run pytest tests/integration -q`: 259 passed in 385 s. The
five generated-document drift checks (`events reference`, `conversations
schema`, `config reference`, `config reference server`, `config openapi`,
plus the generated region of `cli.md`) all diff clean against the
committed copies, and `scripts/check_doc_links.py` checked 216 files
with 0 failures.

The image lanes are **not verifiable locally** and were not run: the
Dockerfile's two variants and the extras-import checks are built and
executed by the `image` job in CI, which needs a builder this worktree
does not have. What was changed there is three lines of build arguments
and three import invocations, and the first CI run on the PR is what
proves them.
