# Each turn's audio, kept by the capture and filed on its turn

Plan for [#496](https://github.com/rafacm/vinga/issues/496), with
[#501](https://github.com/rafacm/vinga/issues/501) folded into it and
[#517](https://github.com/rafacm/vinga/issues/517)'s option 1 as a
first, independent milestone. The scope is the one the decision
comment set (issue comment 5919531169, 2026-09-30) and Step 0
re-verified at `5493e335` (issue comment 5919655155). Its companion is
`docs/plans/2026-09-30-turn-audio-implementation.md`, one section per
milestone, appended in the same change that ticks the milestone.

**Local baseline:** not applicable. No conversational capability
changes: what the assistant hears, says and decides is untouched. What
changes is what a capture keeps on disk and what `export_audio` sends.

**Cheapest alternative:** for the user's side, slicing channel 0 of
the session WAV at the turn's boundaries, which needs no server change
at all. It is not the same bytes: channel 0 is decoded by the
capture's own decoder, holds the frames the guards dropped, and has no
record of where a turn's clip began (the VAD's pre-roll, a merged
utterance's concatenation), so a word error rate measured on it
measures the slicer as well as the model, which is the whole of what
#496 exists to avoid. Persisting the clip instead is one file write at
the one site where the clip and its turn's id already meet. For the
reply side the cheap shape IS the plan: #501's new tap before the Opus
encoder is dropped for a cut of channel 1, which the capture already
writes. For the export, the cheapest alternative is keeping the clips
local and letting an operator upload them by hand; what M3 buys over
it is every dataset item arriving as (audio, transcript, model) on one
trace with no joining, which Rafael asked for explicitly on
2026-09-30. For #517, option 3 (state the early return in a comment)
is cheaper and leaves the loss silent; option 1 is Rafael's call.

**Attribution:** anthropic/claude-opus-5-5, thinking high; Claude Code
2.1.286; 2026-09-30.

## Goal

A capture keeps, beside a session's three files, two mono clips for
each turn: the exact audio its ASR was handed (the "heard" clip) and
what was paced out to the speaker while that turn was being answered
(the "reply" clip). With `server.telemetry.export_audio` on, both are
uploaded after the session closes over the path the session WAV
already takes, and referenced on their own turn's trace, so each
turn's trace plays what the user said and what the assistant said
back, beside the transcript and the provider attribution the trace
already carries. And a turn span the exporter declines to open is
reported rather than lost in silence (#517), which is what lets an
unfiled clip's report say why.

Four milestones:

- **M1** (#517): the exporter says so when a turn starts while another
  is open. Independent of the rest, runs in parallel with M2.
- **M2**: the capture writes each turn's two clips, locally. No
  egress change.
- **M3**: `export_audio` carries the clips to their turn traces. The
  class widening, with its documentation and changelog announcement,
  and the live gates.
- **M4**: the regression-suite section that says which loop answers
  which ASR question. Documentation only. Closes #496 and #501.

## The issues' decisions, restated

From #496's body and the 2026-09-30 decision comment, as Step 0
confirmed them:

- **The clips belong to the capture.** `server.capture` decides
  whether they exist and `server.telemetry.export_audio` decides
  whether they leave, which is the ladder's own rule ("if this content
  exists locally, it leaves"). No new flag: the `attach_` spelling is
  decommissioned and this is a widening of the audio class, announced
  in the changelog (#502's class-widening rule).
- **Refusals unchanged.** `export_audio` on with `server.capture` off
  stays a no-op said once; with `telemetry.enabled` off it stays
  refused; under a `server.data_boundary` narrower than the section's
  `reach` it stays refused. The clips add no destination: they go to
  the same presigned target the WAV goes to.
- **The heard clip is the exact bytes the ASR received**, not a cut
  of channel 0.
- **The reply clip is a per-turn cut of channel 1**, the reply as
  paced out, at 16 kHz decoded from the Opus actually sent. No tap
  before the encoder, no 24 kHz copy. Barge-in truncation comes from
  the channel itself.
- **One clip pair per started turn**, keyed by the utterance id
  `turn_started` names. A confirmed barge-in reuses its
  transcription, so it is one turn and one clip. A merged utterance's
  clip is the merged audio. A gate-rejected barge-in never starts a
  turn and gets no clip. Audio under the openai adapter's minimum
  length is kept (its turn's `asr` span already carries
  `submitted_ms=0`), not dropped, because dropping it would hide the
  short-clip loss the regression suite must keep apart from word
  error rate.
- **A handover's two replies under one utterance** are one reply
  clip, since the clip is keyed by utterance.
- **Neither copy of a dataset item is durable**: the capture prunes
  its oldest sessions, the backend deletes media on its own schedule.
  M4's section says so.
- **#517 option 1**: keep the early return; say so when it fires.

Step 0 corrected one line of the decision comment: `reference_media`
needs no turn-parented variant, because it takes any `_Pinned` and a
turn's pin names the turn span in the turn's own trace.

## Resolutions and design decisions

### Where the heard clip is tapped: `start_reply`

`PipelineRuntime.start_reply(utterance)` (`runtime/pipeline.py`,
around line 2602 at `5493e335`) is where a turn begins: it mints the
utterance id, emits `turn_started`, and starts the reply that will
hand `utterance.pcm` to the ASR (or reuse the barge-in's
transcription of those same bytes). Its docstring already lists every
way in (endpointed utterance, manual stop, confirmed barge-in,
mid-ASR merge) and says a gate-rejected candidate never arrives. It is
the only site constructing a `ReplyInFlight`. So the clip is handed to
the recording right after `turn_started` is emitted, from there and
nowhere else.

Byte identity follows by construction for the path that runs ASR in
the reply (`transcribe(pcm, ...)` with `pcm = utterance.pcm`) and for
the confirmed barge-in (the gate transcribed the utterance's own
`pcm`). M2 pins both by test rather than by this paragraph: a
recording ASR double captures what it was handed and the clip's data
chunk must equal it.

### How it crosses: `SessionEvents`, beside `vad`

The runtime reaches the capture today through exactly one channel,
`SessionEvents`, whose "capture's own tracks, which are not events"
section already forwards `vad` samples to the attached
`SessionRecording`. The clip goes the same way:
`SessionEvents.utterance_audio(utterance: str, pcm: bytes)` forwards
to `SessionRecording.utterance_audio(utterance, pcm, now)` when a
capture is attached, and does nothing otherwise. It is not an event:
no tap sees it, no log line carries it, and the pcm never enters an
`Emission`.

Rejected: a `DeviceOutput` method. The boundary's own test ("would it
still exist if the backend were a telephone call to a human?") fails
it, and it would make the device session a courier for bytes it has
no use for. Rejected: carrying pcm on `turn_started`. Events are the
retained, tap-visible vocabulary; audio in them would reach every
consumer, the log included.

### Where the clips live: a per-session directory

`<capture dir>/<session>.turns/<utterance>.heard.wav` and
`<utterance>.reply.wav`, mono 16 kHz s16le, canonical 44 byte header.
A directory rather than more top-level files, because
`CaptureStore._captures` globs `*.wav` at the top level and treats
every stem as a session: a clip there would be pruned as a capture of
its own and would leave its session's files behind. The utterance id
is server-minted hex; the capture refuses any other spelling with the
uploader's `SAFE_NAME` rule (one home: M2 moves the rule to where both
read it, or reads the uploader's), so no id can reach outside the
directory.

The budget and the prune follow the files:

- `_total_mb` counts the files inside every `*.turns` directory. It
  deliberately still does not descend into the upload staging
  directory, whose entries are hardlinks to files already counted.
- `prune` removes `<stem>.turns/` with the other three files, in the
  same step. "Two thirds of a capture is not a capture" holds for five
  parts.

The manifest lists the clips at close, under `capture.turns`: one
entry per turn in start order, `{"utterance": id, "heard": name,
"reply": name or null, "reply_from_ms": offset or null, "reply_to_ms":
offset or null}`, the two offsets on the WAV's `t_ms` timeline. The manifest written at open says nothing
about turns, as it says nothing about duration; a pod stopped
mid-session leaves clips on disk that the manifest does not list, and
`complete: false` already tells the analysis side to trust the files
over the manifest.

### When they are written

- **Heard**: at `utterance_audio`, in one write, on the session loop,
  like every other capture write. The size is one utterance's audio
  (32 KB a second). A write failure disables the capture the way any
  capture write failure does (`CaptureWrite` gains no member unless
  the implementer finds the existing `AUDIO` misleading, in which case
  a new closed member `CLIP` is added and the events reference
  regenerated).
- **Reply**: incrementally, in `SessionCapture._add` for the reply
  channel, at the same frame index the channel places the audio at,
  with the same silence padding for gaps. So the reply clip's samples
  equal channel 1 of the WAV over the clip's span, which M2 pins
  byte for byte. The clip file is opened at the first reply audio of
  its window and its header patched when the window closes.
- **The window**: opens at `utterance_audio(U)` and closes at the next
  `utterance_audio`, at the capture's limit, at a write failure, or at
  close. Reply audio arriving while no window is open belongs to no
  clip. Since #517's invariant is pinned
  (`test_a_reply_finishes_before_the_turn_that_interrupted_it_starts`),
  a reply's last packet goes out before the next turn begins.
- **The span is recorded.** Each manifest entry carries the reply
  clip's first and last frame as `reply_from_ms` and `reply_to_ms` on
  the WAV's own timeline (the `t_ms` scale the decision track uses), so
  the cut is checkable against the WAV by anyone holding the three
  files, without trusting the clip.

**Why not cut at close, as the 2026-09-30 decision comment said.** That
comment described the reply clip as cut from the finished WAV at the
turn's `t_ms` boundaries. This plan keeps the artifact (channel 1,
16 kHz, as paced out, per turn) and changes how and where the cut is
made, for two reasons, and the deviation is recorded here and in the
implementation doc:

- **Attribution.** `turn_started` is stamped with `utterance.ended_at`,
  the instant the user stopped speaking, which on a barge-in is
  earlier than the moment the interrupted reply stopped being paced.
  A cut between consecutive `turn_started` stamps would file the
  interrupted reply's last frames under the interrupting turn. The
  window opens where the turn's reply can first be paced, so every
  frame is filed under the reply that sent it.
- **Loop time.** A cut at close reads the reply spans back out of the
  WAV on the session loop, up to the whole reply duration of a
  fifteen-minute session, while other sessions share that loop. Written
  as it goes, the cut costs the writes the channel already makes.

The M2 test does not take the span from the implementation (Sol's
point): it paces reply audio for known turns at known frames through
the session, derives each turn's expected span from what it paced and
when it started each turn, and asserts the clip equals channel 1 of the
finished WAV over that independently derived span, and the manifest's
`reply_from_ms` and `reply_to_ms` equal it. A confirmed barge-in case
paces the interrupted reply up to the cancel and asserts those frames
are in the interrupted turn's clip and not the interrupting one's.

**M2 owes an inventory before relying on the window rule**: every
caller of `DeviceOutput.send_audio` (at `5493e335`:
`runtime/pipeline.py:1034`, `runtime/filler_runner.py:312` and `:496`,
by `git grep -n "send_audio("` over `src/`, untruncated), stating for
each whether it can pace audio outside a reply that answers an
utterance. If one can (a filler between turns, say), the window
closes at the reply's own end instead, through a second
`SessionEvents` call from the reply's `finally`, and the
implementation doc records the finding.

### How the clips are uploaded

`CaptureStore.finished()` hands `stage()` the session's `.turns`
directory beside the pair; `stage()` hardlinks its files into the
job's own `turns/` directory inside the same one-rename commit, so a
job still appears whole or not at all. The job's manifest lists the
clips, and the worker reads the list from the staged manifest rather
than from a directory listing, so what is uploaded is what the capture
said it wrote.

The worker uploads the pair first, exactly as today. Then, per listed
turn, in order:

1. `turn = telemetry.turn_context(job.context, utterance)`. `None`
   (more than `RETAINED_TURNS` turns, a turn span never opened, an
   exporter that never saw it) counts the clip as **unfiled** and
   moves on. A clip with no target is reported, never attached to the
   session trace instead: the per-artifact rule already stated at
   `telemetry.py:1256-1260`.
2. `trace_of(turn)` names the turn's own trace, and each clip goes up
   through the existing `_attach` against that trace id, with the same
   retry loop the pair uses.
3. `reference_media(turn, {"heard_audio": ..., "reply_audio": ...})`
   writes the reference span as a child of the turn span. The span
   keeps the `capture` name, **deliberately**: the Collector's Jaeger
   branch drops spans by that name (the Langfuse-only exception in
   `observability-surfaces.md`), and a new name would send media
   references down the Jaeger branch.

A clip whose upload fails after its retries counts as **failed**, and
the remaining clips of that job are counted failed without being
tried: the pair just succeeded, so a clip failure means the backend
went away, and trying N more clips against it is N more timeouts on a
worker other sessions are queued behind. The pair failing fails the
job exactly as today, and no clip is tried.

What is said: `capture_uploaded` gains three counts, `clips`
(attached and referenced), `clips_unfiled` and `clips_failed`. Counts,
not reasons, because each count's cause is fixed by its name and the
job already carries the one session id. No new event and no new
`CaptureUploadFailure` member. The byte ceiling
(`MAX_ATTACHMENT_BYTES`) applies to each clip on its own as it does to
the pair.

A clip upload is still content leaving the host, under the same
quieting (`_QUIETING`), the same presigned-URL rule (no URL, no body
and no far-side word reaches a log or event), and the same
`LANGFUSE_HOST`-only endpoint rule.

### #517: what "report it" means

In `Telemetry._open_turn`, where `trace.turn is not None`:

- a span event on the turn that stayed open, named `turn_not_opened`,
  carrying the dropped turn's `vinga.utterance.id`, every time it
  fires; and
- one `logger.warning` per session, the first time:
  `"session %s: a turn started while another was open, so its span was not opened"`
  with the session id as the one argument. Once per session because
  a broken invariant would otherwise fire on every turn of every
  session, and the first line is the one that matters.

Not a catalog event: the exporter is a tap, and emitting from inside a
tap's dispatch re-enters the dispatch it is running in. The existing
exporter warnings are `logger.warning` for the same reason. The
behavior (the early return, the stage spans folding onto the open
turn) is unchanged.

### Which documentation owns which fact

- What a capture writes: the `capture.py` module docstring, the
  capture section's field prose in `config/models.py` (and so the
  generated `server-config.md`), `config.example.yaml`'s capture
  comment, the Capture section of `observability-surfaces.md`, and
  "What a session yields" in `conversational-quality-regression-suite.md`.
- What `export_audio` sends: the field's own prose (and so the
  generated reference), `config.example.yaml`, the uploader's module
  docstring ("Exactly two files"), the "Exported capture media"
  section of `observability-surfaces.md`, and the Audio row of the
  content-class table there. The ADR
  (`docs/adr/2026-08-15-content-and-telemetry-are-separate-surfaces.md`)
  is a decision record and is not edited; it already names the
  per-utterance and per-turn reply audio as `export_audio` artifacts.
- The per-session egress count ("audio leaves the pod exactly once
  per session" was an operator-reasonable property): the field prose
  states it is now the pair plus up to two clips per turn.

## Module layout

- `runtime/pipeline.py`: `start_reply` calls
  `self._events.utterance_audio(reply.utterance, utterance.pcm)` after
  `turn_started`. One line and its comment.
- `events/__init__.py`: `SessionEvents.utterance_audio`, and
  `SessionRecording.utterance_audio` on the protocol.
- `capture.py`: `SessionCapture` gains the clip directory, the heard
  write, the reply window and its incremental file, the manifest's
  `turns`; `_wav_header` takes a channel count; `CaptureStore` counts
  and prunes `.turns`, and hands the directory to `stage()`.
- `capture_upload.py`: staging links the clips; the worker files
  them on their turns; `capture_uploaded` fields.
- `events/catalog.py`: the three counts on `CaptureUploaded` (M3).
- `telemetry.py`: `_open_turn`'s report (M1). No change for M3: the
  existing `turn_context`, `trace_of` and `reference_media` are the
  whole interface M3 needs.

## Tests

Reuse the existing assets rather than restating them:
`tests/unit/test_capture.py` and `test_capture_session.py` (the
capture's files, the prune, the budget), `test_recording.py` and
`test_recording_order.py` (the owner), `test_capture_upload.py` in
both lanes (the fake media API and the worker), `test_telemetry.py`
and `test_telemetry_spans.py` (spans, span events, the
`session_events` driver #517's probe used), and
`test_session_record.py` (the emission-order pin).

### M1

- `turn_started` then `turn_started` with no `reply_finished`: still
  one turn span (the behavior kept), a `turn_not_opened` event on it
  carrying the second utterance id, exactly one warning record with
  `record.msg` and typed `record.args` asserted exactly, and
  `turn_context` for the second utterance answering `None`.
- The same sequence three times in one session: three span events,
  still one warning.
- The ordinary order (`turn_started`, `reply_finished`,
  `turn_started`): no event, no warning.
- Falsified: removing the warning fails the first case; warning on
  every firing fails the second; emitting the span event on the
  session span instead fails the first.

### M2

- **Byte identity, heard**: a served session through the existing
  session fixtures with a recording ASR double; each turn's
  `.heard.wav` data chunk equals the bytes the double was handed, its
  duration equals the turn's `heard.duration_s`, and its header says
  mono, 16 kHz, 16 bit. A confirmed barge-in case: the clip equals the
  bytes the gate's confirmation was handed, and there is one clip for
  that turn. A gate-rejected case: no clip.
- **Byte identity, reply**: the `.reply.wav` data equals channel 1 of
  the finished WAV over a span the test derives from what it paced
  (not from the clip or the manifest), including a gap padded with
  silence, a barge-in truncation, and the interrupted reply's last
  frames filed under the interrupted turn; the manifest's
  `reply_from_ms` and `reply_to_ms` equal the derived span.
- **Window**: reply audio before any turn belongs to no clip; the
  window closes at the next turn, at the limit and at close.
- **Directory and budget**: a pruned capture takes its `.turns`
  directory with it; `_total_mb` counts clip bytes and not the
  staging links; a planted `<x>.wav` inside `.turns` is not treated
  as a capture.
- **Refusals**: an utterance id outside the safe alphabet writes
  nothing and says so value-free; a disabled or limit-stopped capture
  writes no further clips.
- **Manifest**: `capture.turns` lists every clip in start order, with
  `reply: null` for a turn that spoke nothing.
- **No capture**: `utterance_audio` with nothing attached does
  nothing (the no-capture path costs one `is None`).
- Falsified, one run each: writing the clip from the transcribe call
  site instead of `start_reply` fails the barge-in case; writing reply
  audio at arrival order rather than the channel's frame fails the
  gap case; skipping the `.turns` removal fails the prune case.

### M3

- Through the existing fake media API: a closed session with two
  turns uploads the pair and four clips, each clip against its turn's
  trace id (not the session's), and writes one reference span per
  turn as a child of that turn's span, named `capture`, carrying
  `heard_audio` and `reply_audio` tokens. `capture_uploaded` carries
  `clips=4, clips_unfiled=0, clips_failed=0`.
- A turn the exporter never opened (drive #517's sequence): its clips
  count unfiled and nothing is referenced on the session instead.
- A clip upload failing after retries: that clip and every later one
  count failed, the pair's references stand, and no failure event
  fires for the pair.
- The pair failing: no clip is tried; the existing failure event, and
  no `capture_uploaded`.
- No-leak: the existing presigned-URL sentinel tests extended to a
  clip upload (a planted credential-shaped query string on the
  presigned URL never reaches a log record, an event field, or either
  log format).
- The wire tests' "no request carries the decision track" assertion
  kept, and extended: no request carries anything the manifest does
  not list.
- Staging: the one-rename commit carries the clips; a sweep of a
  leftover job removes its clips with it.
- Falsified: filing a clip under the session's trace fails the first
  case; trying clips after the first failure fails the failure case.

**Live gates** (M3's completion gate, run against the real backend at
the PR's head, recorded in the implementation doc with session and
trace ids): a two-turn conversation with capture and `export_audio`
on; each turn's trace in Langfuse shows a playable heard clip and a
playable reply clip (read back with the Langfuse MCP); and the
byte-identity claim, verified once: one persisted heard clip re-sent
out of band to the same openai model with the same options returns
the recorded transcript. The rig is the #536 driver (a real server in
process, OpenAI ASR, LLM and TTS, silero, OTLP to the Langfuse
endpoint), copied to this session's scratchpad as
`live-driver-536.py`; it needs `LANGFUSE_HOST` set from the `.env`'s
`LANGFUSE_BASE_URL`, since the uploader reads only `LANGFUSE_HOST`.

## Risks and mitigations

- **Disk.** Clips are mono, so a turn's pair costs at most what its
  span costs in the stereo WAV; typically about half the WAV again
  per session, more where merged utterances repeat absorbed audio.
  The capture budget governs it: the prune counts clips. The field
  prose says so.
- **Loop time.** The heard write is one file of one utterance, the
  same order as the capture's existing per-quarter-second writes; the
  reply writes ride the existing flush cadence. No read happens at
  close (the cut is written as it goes, not sliced afterwards), which
  is why the incremental shape was chosen over slicing the finished
  WAV: slicing would read up to the whole WAV on the loop at close,
  while other sessions share it.
- **A reply clip attributed to the wrong turn.** The window rule rests
  on replies ending before the next turn starts; the invariant is
  pinned, and M2's inventory checks the audio paths that are not
  replies.
- **Egress count.** An operator's mental model was one upload per
  session. The field prose and the changelog state the new count.
- **The Jaeger branch.** Reusing the `capture` span name keeps the
  Collector's filter correct; M3's test asserts the name.
- **A clip failure storm.** Stop-at-first-failure bounds a dead
  backend to one clip's retries per job.

## Documentation footprint

Per milestone, below. Generated references (`server-config.md`, the
events reference, `api-openapi.json` if a field docstring reaches it)
change only through their generators.

## Milestones

- [ ] **M1: a turn that is not opened is reported** (#517). Off
  `feature/turn-audio-plan`, in parallel with M2. Commits: the tests,
  watched failing; the report in `_open_turn`; the changelog
  fragment `changelog.d/517-turn-not-opened.md` under `### Fixed` (a
  turn span the exporter declines to open is reported, as a span
  event on the open turn and one warning per session, instead of
  being lost in silence).
  Design footprint: deepens `telemetry.py`'s turn handling; no module
  or seam added. Documentation footprint: the `_open_turn` comment;
  `observability-surfaces.md` only if it describes turn span
  completeness (the implementer checks and says). Closes #517.
- [ ] **M2: the capture keeps each turn's two clips**. Off
  `feature/turn-audio-plan`, in parallel with M1. Commits: the
  `send_audio` inventory recorded; tests watched failing;
  `SessionEvents.utterance_audio` and the protocol; `start_reply`'s
  call; the capture's clips, window, manifest, budget and prune; the
  docs; the changelog fragment `changelog.d/496-turn-clips.md` under
  `### Changed` (a capture now also keeps each turn's heard and reply
  audio in `<session>.turns/`, counted against the capture budget).
  Design footprint: deepens `capture.py` (its callers stop having to
  know that a turn's audio is a file of its own, where it goes, or how
  the reply is cut); adds one crossing to an existing seam
  (`SessionEvents` to `SessionRecording`), stated as a protocol
  method. Documentation footprint: the capture docstring, the capture
  field prose and generated reference, `config.example.yaml`'s capture
  comment, observability-surfaces' Capture section, the regression
  suite's "What a session yields". No egress documentation moves: with
  M2 alone, `export_audio` still sends exactly the pair. Part of #496.
- [ ] **M3: `export_audio` files the clips on their turns**. Stacked
  on M2. Commits: tests watched failing; staging; the worker's per-turn
  filing; the event fields and regenerated reference; the egress
  documentation; the changelog fragment
  `changelog.d/496-turn-clips-export.md` under `### Changed`, worded as
  the class-widening announcement (with `export_audio` on, each turn's
  two clips now leave too, referenced on the turn's trace; an operator
  who agreed to the pair has not agreed to this and should re-read the
  flag); the live gates recorded.
  Design footprint: deepens `capture_upload.py` (its callers still
  call `stage` and `session_closed` and stop having to know that a job
  has parts filed on different traces); no new seam, since the
  telemetry interface it needs exists. Documentation footprint:
  `export_audio`'s prose and generated reference,
  `config.example.yaml`'s telemetry comment, the uploader docstring,
  observability-surfaces' "Exported capture media" and the Audio row.
  Part of #496.
- [ ] **M4: which loop answers which ASR question**. Stacked on M3.
  Documentation only: a section in
  `docs/conversational-quality-regression-suite.md` per the
  2026-09-20 comment on #496 (the two loops as supplier and consumer;
  the decision rule by examples; the invalidation table's ASR row
  split in place so each cell names its loop, with the sentence that
  keeps short-clip loss rate apart from word error rate on survivors;
  how an item is born and attributed to its manifest stack; where the
  durable copy lives, which is nowhere until an operator copies it out
  of both retentions; the closed list of what the dataset loop may
  never claim; who hand-corrects the expected text). No changelog
  fragment. Closes #496 and #501.

## Plan review round

Reviewed 2026-09-30 by openai/gpt-5.6-sol, thinking high via codex CLI 0.156.1, read-only sandbox, runtime 8m31s, at commit fa46912c, plan blob 543a02f8.

---

1. **P1: The reply clip contradicts the settled close-time slicing decision**

   **Evidence:** `.review-context/issue-496-comments.md`, lines 61-66, requires a cut of the finished channel 1 WAV at close using decision-track `t_ms` boundaries. The plan instead creates an incremental second recording with a window opened at the current `utterance_audio` call and closed by later calls (`docs/plans/2026-09-30-turn-audio.md`, lines 185-206). This is observably different because `turn_started` is stamped with `utterance.ended_at` (`runtime/pipeline.py`, lines 2629-2638), while `utterance_audio` would sample the later current clock, especially after barge-in confirmation. The proposed equality test uses “the clip’s span” as defined by the implementation, so it would not catch shifted boundaries.

   **The plan should say instead:** Record the exact decision-track boundary events and their frame offsets, then cut channel 1 from the finalized WAV at close as decided. Name the start and end events explicitly and test against their recorded `t_ms`, including a confirmed barge-in whose confirmation delays `start_reply`. Resolve the loop-time cost without replacing the settled artifact definition.

   *Resolution:* Taken in part. The test half is taken whole: M2's reply test now derives each turn's span from what it paced and when it started each turn, never from the clip or the manifest, and adds a confirmed barge-in case asserting the interrupted reply's last frames are filed under the interrupted turn. The manifest now records each reply clip's span as `reply_from_ms` and `reply_to_ms` on the WAV's `t_ms` timeline, so the cut is checkable against the WAV. The mechanism is kept, and the deviation from the decision comment is stated in the plan under "Why not cut at close": cutting between `turn_started` stamps is the attribution error this finding describes (the stamp is `utterance.ended_at`, earlier than the moment an interrupted reply stops being paced), and a close-time cut reads the reply spans back on the shared session loop. The artifact the comment settled (channel 1, as paced out, per turn) is unchanged; how and where the cut is made is the plan's to decide, and the implementation doc and the M2 PR repeat the deviation.

2. **P1: Manifest-controlled clip paths create a local-file exfiltration path**

   **Evidence:** The worker is to read clip names from the staged manifest (`docs/plans/2026-09-30-turn-audio.md`, lines 210-216), but the only stated validation occurs when the capture initially writes the utterance (`lines 148-157`). Staging hard-links the manifest and the worker reads it later (`capture_upload.py`, lines 609-627 and 776-779); a hard link is not an immutable snapshot. A modified `heard` or `reply` value such as an absolute path or `../../secret` could therefore make the uploader read and send an unrelated local file. The proposed no-leak test covers only presigned URLs (`plan`, lines 384-390), not hostile staged manifests.

   **The plan should say instead:** Treat every staged manifest field as untrusted. Revalidate the manifest’s closed shape, validate each utterance ID, require filenames to equal the fixed names derived from that ID, reject absolute paths, separators, symlinks, non-regular files, duplicates, and missing files, and never join an unchecked manifest string to a filesystem path. Add traversal, absolute-path, symlink, and credential-sentinel tests proving no unrelated bytes are read or requested and no hostile value is logged.

3. **P1: Clip delivery failures are neither warnings nor actionable**

   **Evidence:** The binding decision requires every upload failure to be a warning (`.review-context/issue-496-comments.md`, line 55). The plan instead records clip failures only as fields on `capture_uploaded` and explicitly adds no failure event (`docs/plans/2026-09-30-turn-audio.md`, lines 237-250). `CaptureUploaded` is currently INFO, while `CaptureUploadFailed` is WARNING (`events/catalog.py`, lines 3724-3762). The assertion that `clips_failed` has a fixed cause is false: existing classification distinguishes `unreachable`, `refused`, `too_large`, `staging_lost`, and `unreferenced` (`capture_upload.py`, lines 916-949; `events/values.py`, lines 1519 onward).

   **The plan should say instead:** Add a warning-level catalog outcome for incomplete clip filing, carrying sanitized counts and a closed failure reason or reason-count mapping. Preserve the existing successful pair outcome, never carry exception or far-side prose, export the warning outcome to the retained session trace, and test each materially different classification.

4. **P1: Staged clips can escape the capture budget after pruning**

   **Evidence:** The settled decision says the capture budget counts the clips (`.review-context/issue-496-comments.md`, lines 46-50). The plan deliberately excludes upload staging because its entries are hard links “already counted” (`docs/plans/2026-09-30-turn-audio.md`, lines 159-164). However, current ordering stages first and then prunes (`capture.py`, lines 597-620). Once prune unlinks the capture’s `.turns` directory, the staging hard links retain the blocks while `_total_mb` can no longer see them. A slow backend can therefore retain up to a queue of enlarged jobs outside `max_total_mb`, particularly dangerous for deployments that already have `export_audio` enabled when upgrading.

   **The plan should say instead:** Count unique file inodes across capture storage and staging so hard links count once while both names exist and remain counted after pruning removes one name, or introduce a separately documented and enforced staging-byte budget. Test a blocked worker, several staged captures, pruning of their source paths, and the resulting actual disk and reported budget totals.

5. **P2: Stop-on-first-failure misreports unattempted clips and can orphan successful media**

   **Evidence:** The plan declares every later clip “failed” without trying it because any clip failure supposedly means the backend disappeared (`docs/plans/2026-09-30-turn-audio.md`, lines 237-242). That premise is false for per-file size refusal, missing staging files, credentials or project refusal, and reference failure. It also does not define what happens when the heard upload succeeds but the reply upload fails before the one per-turn `reference_media` call. The successful heard media can be left uploaded but unreferenced. No M3 test covers a `reply: null` entry or failure of the second clip (`lines 369-394`).

   **The plan should say instead:** Stop later attempts only after a retry-exhausted transport failure if that policy is retained. Distinguish failed from skipped. Accumulate successful tokens per turn and reference the successful subset, including heard-only turns; account an upload as successful only when its reference was enqueued. Add tests for `reply: null`, second-clip failure, non-retryable first-clip refusal, missing staged media, and `reference_media` returning false.

6. **P2: The proposed `turn_not_opened` span event bypasses the declared telemetry vocabulary**

   **Evidence:** The plan deliberately creates a span event that is not a catalog event (`docs/plans/2026-09-30-turn-audio.md`, lines 257-274). The observability contract says every exported span event is derived from the structured-event catalog and telemetry can say nothing undeclared (`docs/architecture/observability-surfaces.md`, lines 200-202 and 266-272). The implementation enforces that rule twice (`telemetry.py`, lines 2413-2435 and 3112-3137). A direct `span.add_event` would bypass both guards. Issue #517 option 1 requires a log line or a span event, not both (`.review-context/issue-517.md`, lines 40-46).

   **The plan should say instead:** Keep the early return and emit only the once-per-session sanitized warning, which fully implements option 1 without introducing undeclared trace vocabulary. Remove the span-event assertions and test the warning, unchanged span count, missing second turn context, and ordinary-order silence.

7. **P2: The new upload counts would disappear from the trace outcome**

   **Evidence:** The plan adds three fields to `CaptureUploaded` but explicitly says telemetry needs no M3 change (`docs/plans/2026-09-30-turn-audio.md`, lines 295-311). Post-close outcome spans copy only fields present in `AFTER_THE_CLOSE_ATTRIBUTES` (`telemetry.py`, lines 1180-1187 and 2474-2522), which currently has no clip counts. Existing tests explicitly assert that the outcome span carries the declaration’s relevant fields (`tests/unit/test_telemetry.py`, lines 878-908). Without a mapping change, a backend reader sees neither unfiled nor failed clip counts.

   **The plan should say instead:** Add canonical `vinga.export.*` mappings for all new counts, name `telemetry.py` in M3’s footprint, regenerate the event reference, and test the post-close span attributes as well as the structured log record.

8. **P2: The no-joining dataset claim omits the independent transcript export prerequisite**

   **Evidence:** The plan says each clip lands beside the production transcript and that the dataset item requires no joining (`docs/plans/2026-09-30-turn-audio.md`, lines 39-47), but its live gate enables only capture and `export_audio` (`lines 396-407`). Transcripts leave only under the independent, default-off `export_transcripts` flag, which additionally requires stored conversation text (`config/models.py`, lines 980-1016; `observability-surfaces.md`, lines 347-390). The export ladder expressly says sibling flags imply nothing about each other (`observability-surfaces.md`, lines 494-516; ADR lines 214-234).

   **The plan should say instead:** State that `export_audio` alone produces audio plus metadata, while the no-joining `(audio, transcript, model)` dataset requires `server.conversations.enabled`, text storage, and `server.telemetry.export_transcripts`. Test audio-only behavior to preserve flag independence, and make the live dataset gate enable both exports and verify the transcript, model attribution, and clips on the same turn root.

**Verdict:** Ready after the P1/P2 amendments.
