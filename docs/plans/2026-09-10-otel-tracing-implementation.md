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
