# Each turn's audio, kept by the capture and filed on its turn: implementation

Companion to [`2026-09-30-turn-audio.md`](2026-09-30-turn-audio.md),
one section per milestone, appended in the same change that ticks the
milestone checklist. It records deviations from the plan, resolutions
of the plan's open questions, and discoveries.

## M1: a turn that is not opened is reported

**Attribution:** anthropic/claude-opus-5-5, thinking high; Claude Code 2.1.286; 2026-09-30.

`Telemetry._open_turn` keeps its early return when a turn span is
already open, and now says so: the first time it fires in a session it
logs one `logger.warning`,
`"session %s: a turn started while another was open, so its span was not opened"`,
with the session id as the only argument. The latch is a new field on
the session's own trace state, `_SessionTrace.reported_unopened`, so
each session reports its own first time and the latch leaves with the
session when `_close_session` pops it. No span event and no catalog
event, per the plan review's finding 6. The early return's condition
was split in two (`trace is None` returns silently as before, since a
turn for a session the exporter never opened is a different case the
plan does not touch), and the comment beside the return now says what
the case is, why the pipeline never produces it, why the open turn is
kept rather than closed, and why the report is a log line said once.

### The commits

| Commit | What it is |
| --- | --- |
| `b05a4bfd` Test that a turn the exporter declines is reported | The four M1 cases in `tests/unit/test_telemetry.py`, watched failing |
| `b99ddd17` Report a turn the exporter declines to open | The latch field, the split condition, the warning and the comment in `telemetry.py` |
| `4c7cf701` Add the changelog fragment for #517 | `changelog.d/517-turn-not-opened.md` under `### Fixed` |
| Record M1 of the turn audio plan | This file, created with its header, and the plan's tick |

### The tests, and how they were watched failing

In `tests/unit/test_telemetry.py`, under a new section beside the turn
context cases, driven through `session_events` into the in-memory
exporter as #517's own probe was:

- `test_a_turn_started_over_an_open_one_is_reported_and_not_opened`:
  `turn_started(A)`, `turn_started(B)`, `reply_finished`. One turn span,
  carrying A's utterance id, with no span events; `turn_context` answers
  for A and `None` for B; exactly one record from
  `vinga_server.telemetry`, at `WARNING`, with `record.msg` equal to the
  template and `record.args == (SESSION,)`, its one argument a `str`.
- `test_the_report_is_said_once_per_session_however_often_it_fires`:
  the start, start, finish sequence three times in one session, one
  warning.
- `test_each_session_gets_its_own_report`: the sequence in two sessions
  under one exporter, one warning each, in order, each naming its own
  session.
- `test_turns_in_the_ordinary_order_report_nothing`: start, finish,
  start, finish; two turn spans and no record from the exporter's
  logger at all.

Against the unchanged exporter, the three reporting cases failed on the
missing record alone (`assert 0 == 1`, and `[]` where the per-session
args were expected), with their span and `turn_context` assertions
already passing, which is the kept behavior they pin. The
ordinary-order case passed, as it should.

### Mutations

Each run once against `tests/unit/test_telemetry.py -k report`, the
source restored and touched after each:

| Mutation | Outcome |
| --- | --- |
| Remove the warning (plan) | Killed: the three reporting cases fail |
| Warn on every firing (plan: latch never set) | Killed: the once-per-session case fails |
| A process-wide latch on the exporter instead of the session (plan) | Killed: the second-session case fails |
| Reset the latch when a turn closes (added) | Killed: the once-per-session case fails, because its three firings each follow a close |
| Drop the early return, so the second turn opens over the first (added) | Killed: the kept-behavior case fails on the turn span's utterance id |

None survived.

### Documentation

- The `_open_turn` comment, rewritten as the plan asks, and a comment on
  the new `_SessionTrace` field.
- `docs/architecture/observability-surfaces.md`: checked, not edited.
  The one sentence about turn spans in "Exported traces" ("A session is
  one span, each turn a trace of its own linked to it, and inside a turn
  the stages that took the time") describes the trace's shape, not its
  completeness: it makes no claim that every started turn gets a span,
  and nothing in the file promises one. M1 changes no behavior the
  sentence describes (the early return is unchanged, and the case it
  covers is one the pipeline does not produce), and the new warning is a
  plain server log line rather than an exported span or event, so it
  belongs to no surface that page catalogs. Every other mention of
  "turn" there is about the store, the transcript export or sampling.
- `changelog.d/517-turn-not-opened.md`, under `### Fixed`, in final
  form: what the case is, that behavior is unchanged, the warning's text
  and its once-per-session rule, and that nothing is added to the trace.

### Deviations, resolutions and discoveries

No deviations from the plan. Two things the plan leaves implicit, decided
here:

- **The condition was split.** The plan speaks only of the case where
  `trace.turn is not None`; `trace is None` (a `turn_started` for a
  session the exporter holds no trace for) stays a silent return,
  because it is a different case from the one #517 describes and the
  plan asks for no change to it.
- **Two mutations beyond the three the plan names** were run (the latch
  reset on a turn's close, and a dropped early return), since the latch
  living on a state object that `_close_turn` also touches made the
  first a plausible regression, and the second is the behavior the plan
  says is kept.

One discovery, about formatting rather than behavior: `ruff format
--check` reports `telemetry.py` and `test_telemetry.py` as unformatted
before this change, on lines M1 does not touch. Formatting is not a CI
gate (lint is), so nothing was reformatted; the new warning's template
is kept on one line, which is how the formatter would place it and what
makes it greppable whole.

### Verification

All from `vinga-server/`, at `fdaab781`, the fragment's commit before
the rebase onto the final plan tip (this record adds prose only). That
rebase moved only plan-document commits beneath M1, and the same
commit is `4c7cf701` after it; the lanes were not rerun on the rebased
tree.

- `uv run ruff check .`: `All checks passed!`
- `uv run mypy`: `Success: no issues found in 5 source files`
- Unit lane, `-n auto --dist loadfile`:
  `7645 passed, 19 skipped in 895.00s (0:14:55)`
- Integration lane, `-n auto --dist loadfile`:
  `347 passed in 228.33s (0:03:48)`
- The generated-document drift checks, run as the workflow runs them
  (the domain, server, conversations-schema, metrics-views, events,
  OpenAPI and CLI references, and the CLI recipes): all eight identical
  to their committed copies. Nothing M1 touches reaches a generator.
- Census lane (`uv run pytest tests/census -q`), run last, after this
  record: `66 passed in 27.27s`, both manifests current.

Not verified locally: the image build and its smoke conversation, which
only CI runs. M1 changes nothing either of them exercises differently.

### PR review round, PR #571

Automated external review of this PR's diff (feature/turn-audio-plan...22e0b230).
Reviewed 2026-09-30 by openai/gpt-5.6-sol, thinking high via codex CLI 0.156.1, read-only sandbox, runtime 4m16s, at commit 22e0b230.
Verdict as received: **mergeable after the listed fixes**. Two
findings, both fixed here.

1. **P2: the completed milestone still named `PR TBD`.** The plan's M1
   item was ticked with the pull-request placeholder left in, where
   `AGENTS.md` asks for the milestone's PR number in the tick.

   *Resolution*: fixed in `ece2a3e9`. The item now links PR
   [#571](https://github.com/rafacm/vinga/pull/571), in the shape the
   other ticked plans use.

2. **P2: the new warning contradicted the module's own contract.** The
   `telemetry.py` module docstring said nothing in the module can state
   a fact the catalog does not declare, and that a tap's dispatch makes
   no syscall, while the #517 report is a non-catalog log line written
   synchronously from inside that dispatch. The reviewer asked for the
   catalog rule to be scoped to exported spans and span events, and for
   the once-per-session warning and its ordinary logging path to be
   acknowledged.

   *Resolution*: fixed in `4f431946`. The catalog rule now covers what
   the module exports, no span and no span event, and a new paragraph
   names the warning as the one exception to the reply-path rule: logged
   through the module's ordinary logger with whatever I/O its handlers
   do, never on a trace, at most once per session and only on an event
   order the runtime does not produce. The rest of the no-syscall claim
   was checked while there: the module's only other logger calls are on
   the shutdown path, not in the dispatch. Verified with
   `uv run ruff check .` (`All checks passed!`), the two telemetry test
   files (`144 passed in 179.65s (0:02:59)`, on a machine shared with a
   parallel lane, against 15.85s for the same files earlier), the doc
   link check and, last, the census lane.

The rebase onto the final plan tip moved every M1 commit, so the hashes
in the commit table above were rewritten to the rebased ones
(`b05a4bfd`, `b99ddd17`, `4c7cf701`) in the same change that added this
round. The verification section keeps `fdaab781`, the tree the lanes
actually ran on, and says so.

## M2: the capture keeps each turn's two clips

**Attribution:** anthropic/claude-opus-5-5, thinking high; Claude Code 2.1.286; 2026-09-30.

A capture keeps, beside a session's three files, a
`<session>.turns/` directory with two mono 16 kHz clips per started
turn: `<utterance>.heard.wav`, the exact bytes the turn's ASR was
handed, and `<utterance>.reply.wav`, channel 1 of the WAV over the
turn's reply window. The manifest written at close lists them under
`capture.turns` with each reply clip's span. The budget counts every
regular file under the capture directory once per inode, upload staging
included, and the prune takes a capture's turns directory with it.
`export_audio` still sends exactly the pair: nothing here is staged or
uploaded.

### The commits

| Commit | What it is |
| --- | --- |
| `301479ec` Record the send_audio inventory for M2 | This file's header and the inventory below, before anything relied on it |
| `f90eb95f` Test each turn's two clips in the capture | The tests, watched failing against the unchanged capture: every new case failed, on the missing `utterance_audio` (AttributeError) or the missing `capture.turns` (KeyError) |
| `26e5b055` Give the capture's name rule one home | `capture_upload.safe_name`, which the uploader's `_named` now calls and the capture reads |
| `2c30ba11` Keep each turn's heard and reply clips in a capture | `capture.py`: the clip directory, the heard write, the reply window and its incremental file, the manifest's `turns`, the refusal, the inode-counted budget, the prune, `_wav_header` taking a channel count |
| `5927e98f` Carry a turn's audio from the session to its capture | `SessionEvents.utterance_audio` and the `SessionRecording` protocol method |
| `08cc021d` Hand each turn's audio to the capture at its start | `start_reply`'s one call after `turn_started` |
| `ba258b6e` Document the per-turn clips and the staged budget | The documentation footprint, and the regenerated `server-config.md` |
| `ee38cb95` Announce the turn clips and the staged-budget fix | `changelog.d/496-turn-clips.md`, `### Changed` and `### Fixed` |
| `c783a615` Test the reply cut where arrival and placement part | Two schedule entries a surviving mutation showed were missing (below) |
| Record M2 of the turn audio plan | This section and the tick |

### The `send_audio` inventory

The plan's window rule (a reply clip's window opens at
`utterance_audio(U)` and closes at the next one) is only right if no
audio reaches the device outside a reply that answers an utterance.
The inventory the plan asks for, taken before anything relied on it,
at the branch's base (`a72e8f75`), untruncated:

```
$ git grep -n "send_audio(" -- vinga-server/src
vinga-server/src/vinga_server/device/boundary.py:103:    `send_audio(pcm)`. The encoder buffers partial frames, so a chunk of
vinga-server/src/vinga_server/device/boundary.py:212:    async def send_audio(self, batch: PlayableAudio) -> None:
vinga-server/src/vinga_server/device/session.py:1312:    async def send_audio(self, batch: PlayableAudio) -> None:
vinga-server/src/vinga_server/runtime/filler_runner.py:312:            await self._output.send_audio(batch)
vinga-server/src/vinga_server/runtime/filler_runner.py:496:                await self._output.send_audio(batch)
vinga-server/src/vinga_server/runtime/pipeline.py:1034:        await self._output.send_audio(batch)
vinga-server/src/vinga_server/simulator/conversation.py:420:        _send_audio(socket, framing.wrap(version, packet))
vinga-server/src/vinga_server/simulator/conversation.py:599:def _send_audio(socket, frame: bytes) -> None:
```

Three of those are not callers: `boundary.py:103` is prose,
`boundary.py:212` the protocol's declaration and `session.py:1312` the
one implementation, whose `deliver` is the only place a paced packet
reaches `Recording.reply` and so channel 1. The two `simulator` lines
are the device simulator's own microphone, the far side of the wire,
and never reach a server capture. The three callers:

- **`pipeline.py:1034`, `_send_reply_audio`.** Its three callers are
  `_speak` (one sentence, `:2574`), the round loop's tail flush
  (`:1894`) and `_speak_text` (a handover's recap, `:2246`), and all
  three are reached only from `_speak_reply`, whose one caller is the
  reply body (`_reply`, `:1303`). Every frame it sends is the reply of
  the `ReplyInFlight` that `start_reply` minted. Cannot pace outside a
  reply.
- **`filler_runner.py:312`, `_fire`.** The latency mask's task is
  created by `arm()`, whose one caller is `_reply` (`pipeline.py`,
  after the transcript), and it is either stood down or seen through
  by `settle()` in the reply's own `finally`, or cancelled by
  `abandon()` in the reply's cancellation arm, which that `finally`
  then awaits through. So a clip still sounding when the reply's body
  ends is waited out inside the reply, before `reply_finished`'s
  successor can begin: a barge-in's `cancel_reply` awaits the task
  whole. Cannot pace outside a reply.
- **`filler_runner.py:496`, `speak_fallback`.** Called from two sites,
  both inside `_reply`: the failure arm's notice (`pipeline.py:1374`)
  and the nothing-sayable notice (`pipeline.py:1672`, reached from the
  reply's rounds). Cannot pace outside a reply.

No caller paces audio outside a reply that answers an utterance, so
the plan's fallback (closing the window from the reply's `finally`
through a second `SessionEvents` call) is not needed and was not
built. The one reply body that answers no utterance is a body driven
without `start_reply` (`tests/support/sessions.py`'s `drive_reply`),
which only the test suites do; its audio lands in whatever window is
open, or in none, and no production path reaches it.

### The deviation the plan already decided: the reply cut is written as it is placed

The decision comment on #496 described the reply clip as cut from the
finished WAV at close, between the turn's boundaries on the decision
track's `t_ms`. The artifact is kept (channel 1, 16 kHz, as paced out,
per turn) and the cut is made differently, as the plan's "Why not cut
at close" section and its review rounds settled: `SessionCapture._add`
feeds each reply chunk to the open turn's clip at the same frame index
the channel just placed it at, with the same silence in its gaps, so
the clip is channel 1's span byte for byte by construction. The window
opens at `utterance_audio(U)`, which `start_reply` calls in the same
breath as it emits `turn_started(U)`, and closes at the next
`utterance_audio`, the capture limit, a write failure or the close.
Two reasons: bounding by `turn_started` stamps would file an
interrupted reply's last frames under the interrupting turn, because
that stamp is `utterance.ended_at`, earlier than the moment the
interrupted reply stopped being paced; and a cut at close would read
the reply spans back out of the WAV on the shared session loop. The
manifest records each clip's span as `reply_from_ms` and `reply_to_ms`,
so anyone holding the three files reproduces the clip by cutting the
WAV at close, which is exactly what the writer test checks. Rafael may
overrule this; the M2 pull request and #496 repeat it.

### Resolutions and decisions made here

- **`reply_to_ms` is the end of the clip, not its last frame.** The
  span is half-open, from the first frame to just past the last, so
  cutting channel 1 at `[reply_from_ms, reply_to_ms)` reproduces the
  clip and `reply_to_ms - reply_from_ms` is its duration. The plan's
  wording ("first and last frame") read literally would make every
  reader add a frame.
- **The offsets are exact to the frame, not rounded like `t_ms`.** The
  decision track rounds `t_ms` to a tenth of a millisecond, and a frame
  at 16 kHz is 0.0625 ms, so a rounded offset does not round-trip to
  its frame. The clip offsets are `frame * 1000 / 16000`, which is
  exact in a float and in JSON, and `ms * 16` is the frame again. Same
  timeline, same unit, finer grain.
- **`heard` and `reply` are leaf names** inside `<session>.turns/`, the
  entry shape the plan gives. The directory is the session's own name
  with `.turns`, which the manifest's `audio` already names.
- **`CaptureWrite` gains no member.** A clip is audio, and a failed
  clip write reads correctly as `capture_failed` with `write audio`. No
  events reference change.
- **The refusal of an unminted utterance id** is a value-free
  `logger.warning` on the capture channel,
  `"session %s: an utterance id this server did not mint reached the capture, so no clip was kept for it"`,
  with the session id as its one argument: the uploader's precedent for
  the same refusal of a session id. Not a catalog event, because no
  lawful value can carry the refused string and the case has no
  production producer (the ids are `uuid4().hex`). A refused turn still
  closes the window before it, since a turn did begin; its reply
  belongs to no clip.
- **The name rule's one home** is a public `safe_name()` in
  `capture_upload.py`, beside `SAFE_NAME` and `NAME_LIMIT`, which the
  uploader's `_named` now calls and the capture reads. The capture
  already imported from that module (`staging_root`,
  `BUILDING_PREFIX`), so no new edge.
- **A turn that starts past the capture's limit** finishes the capture
  at the limit, the rule `event` and `_add` already follow, and writes
  nothing. A reply chunk placed across the limit is cut at the limit in
  the clip, as the close cuts it in the WAV.
- **The budget walk** (`os.walk`, `os.lstat`) counts regular files only
  and follows no symlink, so a planted link cannot make a file
  elsewhere count. Directory entries no longer count at all; the old
  top-level glob counted their own sizes (`upload-staging/`'s 4 KiB,
  for one).
- **One line of egress prose moved.** `export_audio`'s field prose and
  `config.example.yaml`'s telemetry comment said the capture budget
  does not see a staged recording. That is this milestone's `### Fixed`,
  so the sentence now says it counts until the upload is done with it.
  Nothing about what the flag sends moved; that is M3's.
- **Audio under the openai adapter's minimum is kept**, read in the
  code rather than changed: `openai_asr.transcribe` answers a clip
  under `MIN_AUDIO_S` with `AsrResult(text="", submitted_ms=0)`
  without a request; the reply emits `nothing_heard` with
  `submitted_ms=Whole(0)`; `nothing_heard` is one of the ASR span's
  four outcomes and `ASR_ATTRIBUTES` maps `submitted_ms` to
  `gen_ai.usage.input_milliseconds`, exported as a measured zero. The
  heard clip is written at `start_reply`, before the ASR runs, so the
  turn keeps it whatever the ASR then does. One boundary worth naming:
  a barge-in candidate whose gate confirmation comes back empty (the
  same short-clip answer) never starts a turn, so it has no clip, which
  is the plan's "a gate-rejected barge-in gets no clip".

### Discoveries

- **A surviving mutation, and the two cases it was missing.** Feeding
  the clip at each chunk's arrival frame (never before the clip's own
  last end) instead of the channel's placement survived the first
  version of the reply-cut test. Inside one window the two rules agree
  unless a chunk arrives before the one ahead of it has finished, and
  across windows they part when a turn begins while the previous
  reply's last chunk is still playing. The driver never reached either.
  `c783a615` adds both to the schedule, and the mutation now fails on
  `u3`'s `reply_from_ms` (1765.625 against the derived 1775.0).
- **A sentence is spoken only once something follows its full stop.**
  The barge-in cases need a reply that is audibly speaking and then
  hangs. A model that yields one complete sentence and then hangs is
  never spoken, because `SentenceSplitter` cannot cut at a full stop
  with nothing after it and only flushes the remainder when the stream
  ends; the double yields `"Interrupted now. And"`.
- **The blocked worker is a client that blocks in construction.** The
  worker reads the first job's bytes before it builds its REST client,
  and removes a job's links only when the attempt ends, so a client
  factory that waits on an event holds the first job's links on the
  disk with the rest queued behind it: the backlog the plan's budget
  test asks for, with no reach into the uploader.

- **One unexplained failure, once.** In the run that watched the new
  tests fail against the unchanged code,
  `test_nothing_is_recorded_without_a_capture_section` (an existing
  case in `test_capture_session.py`, on no path this milestone
  touches) failed too. Its failure text is lost: that run's output was
  piped through `tail`, which cut it. It has passed in every run since
  (the full unit lane, and both capture files serially, twice, against
  the finished code), and the machine had other pytest processes
  running at the time. Recorded rather than explained.

### Mutations

One run each, against the finished code, each restored from a copy
(not `git checkout`) and touched afterwards, with
`PYTHONDONTWRITEBYTECODE=1`:

| Mutation | Test that must fail | Outcome |
| --- | --- | --- |
| The heard clip written at the transcribe call site in `_reply` instead of in `start_reply` (the plan's) | `test_a_confirmed_barge_in_keeps_the_gates_bytes_as_its_one_clip` | Killed: the interrupting turn has no clip, one manifest entry where two turns started. `test_each_turns_heard_clip_is_what_its_asr_was_handed` passes under it, as it should: on the ordinary path the two sites hand over the same bytes |
| Reply audio appended to the clip in arrival order, no silence for gaps (the plan's) | `test_a_reply_clip_is_channel_one_over_the_span_its_turn_paced` | Killed: the clip differs at the first gap |
| Reply audio placed at its arrival frame, never before the clip's own last end, rather than at the channel's placement | the same | **Survived the first version of the test**; killed after `c783a615` (Discoveries above) |
| The prune skipping the `.turns` removal (the plan's) | `test_a_pruned_capture_takes_its_turns_with_it` | Killed: `s0.turns` left behind |
| The budget counting per name rather than per inode (the plan's) | `test_staged_audio_stays_inside_the_capture_budget` | Killed at the first measurement, which double-counts the staged pair |
| The budget walk skipping `upload-staging/` (the plan's) | the same | Killed at the second measurement, which loses the pruned capture's staged pair |
| The `safe_name` check removed | `test_an_utterance_id_this_server_did_not_mint_writes_nothing` | Killed: the traversal id is listed in the manifest, the first assertion to fail |

### Verification

On agentpi, from `vinga-server/`, at the milestone's last code commit
(`c783a615`):

- `uv run ruff check .`: `All checks passed!`
- `uv run mypy`: `Success: no issues found in 5 source files`
- `uv run pytest tests/unit -q -n auto --dist loadfile`:
  `7655 passed, 19 skipped in 875.05s (0:14:35)`; the 19 skips are the
  `piper` and `faster-whisper` extras, not installed here
- `uv run pytest tests/integration -q -n auto --dist loadfile`:
  `347 passed in 210.78s (0:03:30)`
- The drift checks: every generated reference regenerated through its
  generator (`config reference server`, `config reference`, `events
  reference`, `config openapi`, `conversations schema`, `conversations
  views`, the CLI region), and only `server-config.md` moved, in
  `ba258b6e`; `scripts/check_doc_links.py` and
  `scripts/fold_changelog.py check` pass
- `uv run pytest tests/census -q`, run last, on this section as
  committed: `66 passed in 25.92s`, neither manifest needing
  regeneration

Not verified here: the image build and its smoke conversation, which
run only in CI; and anything on a board. What a clip sounds like from
a real microphone and speaker was not listened to: the served-session
tests run the mock providers through the real session, codecs and
pacer, and the byte-identity claims are pinned there, but the first
real capture with clips is M3's live gate.
