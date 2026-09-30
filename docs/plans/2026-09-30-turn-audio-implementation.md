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
`<session>.turns/` directory with mono 16 kHz clips per started turn: a
heard clip, `<utterance>.heard.wav`, the exact bytes the turn's ASR was
handed, and, when reply audio was paced, a reply clip,
`<utterance>.reply.wav`, channel 1 of the WAV over the turn's reply
window. The manifest written at close lists them under
`capture.turns` with each reply clip's span. The budget counts every
regular file under the capture directory once per inode, upload staging
included, and the prune takes a capture's turns directory with it.
`export_audio` still sends exactly the pair: nothing here is staged or
uploaded.

### The commits

| Commit | What it is |
| --- | --- |
| `ac7e40be` Record the send_audio inventory for M2 | This file's header and the inventory below, before anything relied on it |
| `b07422bd` Test each turn's two clips in the capture | The tests, watched failing against the unchanged capture: every new case failed, on the missing `utterance_audio` (AttributeError) or the missing `capture.turns` (KeyError) |
| `eec2b75d` Give the capture's name rule one home | `capture_upload.safe_name`, which the uploader's `_named` now calls and the capture reads |
| `38ee72d4` Keep each turn's heard and reply clips in a capture | `capture.py`: the clip directory, the heard write, the reply window and its incremental file, the manifest's `turns`, the refusal, the inode-counted budget, the prune, `_wav_header` taking a channel count |
| `07abd451` Carry a turn's audio from the session to its capture | `SessionEvents.utterance_audio` and the `SessionRecording` protocol method |
| `ea4783e3` Hand each turn's audio to the capture at its start | `start_reply`'s one call after `turn_started` |
| `019d7ced` Document the per-turn clips and the staged budget | The documentation footprint, and the regenerated `server-config.md` |
| `0303d40c` Announce the turn clips and the staged-budget fix | `changelog.d/496-turn-clips.md`, `### Changed` and `### Fixed` |
| `4f37d935` Test the reply cut where arrival and placement part | Two schedule entries a surviving mutation showed were missing (below) |
| `e2cdd5e9` Record M2 of the turn audio plan | This section and the tick |
| `9e12b758` Treat a reply clip that cannot be finished as a failure | PR review round, finding 1 |
| `049df6de` Say a turn's reply clip exists only when it spoke | PR review round, finding 3 |
| `6caf2285` Record PR #572's review round for M2 | Finding 2: the PR link in the tick, this table's rebased hashes, and the round below |
| `0f44374c` Regenerate the reach-in census for the header seam | The one line finding 1's tests add to `reach-ins.txt` (`_wav_header`, two sites), regenerated by its generator |
| `73a49c9f` Name a failed capture write's class as before M2 | PR review round 2, finding 1: the first round's builtin-ancestor naming reverted |
| `4047a312` Say in the plan a turn has a reply clip only if it spoke | PR review round 2, finding 2 |
| Record PR #572's second review round for M2 | The round below |

### The `send_audio` inventory

The plan's window rule (a reply clip's window opens at
`utterance_audio(U)` and closes at the next one) is only right if no
audio reaches the device outside a reply that answers an utterance.
The inventory the plan asks for, taken before anything relied on it,
at the branch's base (`a72e8f75`, the plan branch's tip before the
rebase onto `main`; the same command gives the same eight lines at
`origin/main` after it), untruncated:

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
  `4f37d935` adds both to the schedule, and the mutation now fails on
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
| Reply audio placed at its arrival frame, never before the clip's own last end, rather than at the channel's placement | the same | **Survived the first version of the test**; killed after `4f37d935` (Discoveries above) |
| The prune skipping the `.turns` removal (the plan's) | `test_a_pruned_capture_takes_its_turns_with_it` | Killed: `s0.turns` left behind |
| The budget counting per name rather than per inode (the plan's) | `test_staged_audio_stays_inside_the_capture_budget` | Killed at the first measurement, which double-counts the staged pair |
| The budget walk skipping `upload-staging/` (the plan's) | the same | Killed at the second measurement, which loses the pruned capture's staged pair |
| The `safe_name` check removed | `test_an_utterance_id_this_server_did_not_mint_writes_nothing` | Killed: the traversal id is listed in the manifest, the first assertion to fail |

### Verification

On agentpi, from `vinga-server/`, at `c783a615`, the milestone's last
code commit before the rebase onto `main` after M1 merged (this record
adds prose only). That rebase moved only commits beneath M2 (the plan
and M1), and the same commit is `4f37d935` after it; the lanes were not
rerun on the rebased tree. What the review round below changed was
verified on its own, and says so there.

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
  `019d7ced`; `scripts/check_doc_links.py` and
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

### PR review round, PR #572

Automated external review of this PR's diff (origin/main...e2cdd5e9).
Reviewed 2026-09-30 by openai/gpt-5.6-sol, thinking high via codex CLI 0.156.1, read-only sandbox, runtime 6m04s, at commit e2cdd5e9.
Verdict as received: **mergeable after the listed fixes**. Three
findings, all fixed here.

1. **P2: a reply header that could not be patched was published as a
   complete capture.** `close()` finished the open reply window under
   `contextlib.suppress`, so a failed header patch or file close left
   `_stopped` false and the manifest said `complete: true` while
   listing a clip with a stale header, against the class's own
   write-failure contract.

   *Resolution*: fixed in `9e12b758`. The close catches that failure,
   reports it once the except suite is left as a capture write failure
   (`CaptureWrite.AUDIO`, `capture_failed`, `_stopped` set), and goes
   on closing, so the manifest says `complete: false`; a capture an
   earlier failure already stopped says nothing more. `_disable` is
   split into `_failed` (say it, stop) and the close, so the close can
   report without re-entering itself. Going further than the finding,
   and for the reason its no-leak half gave: `capture_failed` now names
   the nearest class in the failure's ancestry that is Python's own
   builtin of that name (checked by identity against `builtins`), never
   the raised class, whose name `type` lets anyone choose; this covers
   every capture write failure, since they share the one report. The
   other places the clip code closes a file were checked: the window
   close and the heard write in `utterance_audio`, and the reply clip's
   first open and its writes in `_add`, all already disabled the
   capture. Two tests, watched failing first: the header patch failing
   at close (no `capture_failed` at all before the fix), with a
   credential-shaped string planted in the exception's message and in
   its class name and asserted absent from every record in both log
   formats, along with any traceback; and a clip that fails on its
   first write and again at close, said once. Mutations: `ClassName.of`
   in place of the builtin ancestor fails the first (the planted class
   is named); dropping the already-stopped guard fails the second (two
   events). Not changed, and noted: the session WAV's own header patch
   in `close()` is still under a blanket suppress, which predates this
   milestone and is outside the clip code the finding named; and
   `capture_directory_unusable` and `capture_files_unopenable` still
   name the raised class through `ClassName.of`.

2. **P2: the milestone record was not finalized after the rebase and
   the PR.** The tick still said `PR TBD`, and the commit table listed
   the pre-rebase hashes.

   *Resolution*: fixed in the commit that adds this round. The tick
   links PR [#572](https://github.com/rafacm/vinga/pull/572); the
   commit table and every other hash in this section are the rebased
   ones; the verification section keeps `c783a615`, the tree the lanes
   actually ran on, and says it is `4f37d935` after the rebase. The
   inventory's base `a72e8f75` is kept too, as the commit it was taken
   at, with a note that the same command gives the same lines at
   `origin/main`, which was checked.

3. **P3: the operator documentation promised a reply clip for turns
   that spoke nothing.** The capture prose, `observability-surfaces.md`
   and the regression suite said two clips per turn, while a turn that
   paced no reply audio has no reply file and a `reply: null` entry.

   *Resolution*: fixed in `049df6de`. Each now says a heard clip and,
   when reply audio was paced, a reply clip: the `enabled` prose in
   `config/models.py` (and `server-config.md`, regenerated from it),
   `config.example.yaml`, `observability-surfaces.md`, the regression
   suite, the capture module's docstring, and the changelog fragment's
   opening sentence, which stated the exception later but opened with
   the same phrase. This section's own summary was reworded to match in
   the commit that adds this round.

Verified for the round, on agentpi from `vinga-server/`, at `049df6de`
plus this record: `uv run ruff check .` (`All checks passed!`),
`uv run mypy` (`Success: no issues found in 5 source files`), the files
the fixes touch (`test_capture.py`, `test_capture_session.py`,
`test_capture_upload.py` in both lanes, `test_recording.py`,
`test_recording_order.py`, `test_config.py`, with `-n auto --dist
loadfile`: `337 passed in 42.09s`), the two suites that pin
`capture_failed`'s declaration (`test_event_baseline.py`,
`test_server_event_pins.py`: `17 passed in 68.02s (0:01:08)`), the
server, OpenAPI and events references against their generators (all
current), `scripts/check_doc_links.py` and `scripts/fold_changelog.py
check`, and last the census lane, which found the two new
`_wav_header` reach-ins; `reach-ins.txt` was regenerated by its
generator in `0f44374c` and the lane rerun last, on this record. The
full unit and integration lanes were not rerun for the round.

### PR review round 2, PR #572

Automated external review of this PR's diff (e2cdd5e9...63c9c85d).
Reviewed 2026-09-30 by openai/gpt-5.6-terra, thinking high via codex CLI 0.156.1, read-only sandbox, runtime 3m46s, at commit 63c9c85d.
Verdict as received: **mergeable after the listed fixes**. Two
findings, both resolved here.

1. **P1: hostile exception metadata could escape the capture's error
   guard.** The first round's fix named `capture_failed`'s class by
   walking `type(exc).__mro__` and each class's `__name__`, and a
   metaclass can override both reads, so the lookup could raise inside
   the write-error `except` suite with the original failure as its
   context. The reviewer proposed a hardened lookup and a metaclass
   test.

   *Resolution*: resolved by reverting the change the first round's
   fix had added, rather than hardening it (the orchestrator's
   decision), in `73a49c9f`. That change went beyond finding 1 of the
   first round and widened `capture_failed` for every capture write
   failure; `_failed` now names the class with `ClassName.of(exc)`
   inside the thunk, exactly as `_disable` did before M2, and
   `_builtin_class` is gone. The reply-window finalization fix itself
   stays. The regression test keeps a credential-shaped sentinel in the
   exception's message and asserts it absent from every record's
   attributes and both log formats; for the class name it asserts what
   `ClassName.of` yields for the planted class, which is its name,
   since an identifier passes `ClassName`'s guard. Whether a rendered
   class name needs validating beyond that is #565's question, whose
   body records that the typed `ClassName` path already guards the
   worst of it. The first round's record above is left as written; its
   builtin-ancestor mutation no longer applies. Rerun here: restoring
   the blanket suppress around the window close fails the finalization
   test (no `capture_failed`), and dropping the already-stopped guard
   fails the said-once test (two events).

2. **P3: the plan still promised a reply clip for a silent turn.** Its
   Goal, the M2 summary and the M3 item said every turn keeps two
   clips.

   *Resolution*: fixed in `4047a312`. Those three sentences now say
   every turn has a heard clip, and a reply clip when reply audio was
   paced. The plan's review-round sections are records and are
   unchanged, and so is the milestone's name, which the checklist
   anchor spells.

Verified for the round, on agentpi from `vinga-server/`, at `4047a312`
plus this record: `uv run ruff check .` (`All checks passed!`),
`uv run mypy` (`Success: no issues found in 5 source files`), the
capture files (`test_capture.py`, `test_capture_session.py`,
`test_capture_upload.py` in both lanes, `-n auto --dist loadfile`:
`138 passed in 48.25s`), the two suites that pin `capture_failed`'s
declaration (`17 passed in 59.02s`), the events reference against its
generator (current), `scripts/check_doc_links.py` and
`scripts/fold_changelog.py check`, and last the census lane. The full
unit and integration lanes were not rerun for the round.

## M3: `export_audio` files the clips on their turns

**Attribution:** anthropic/claude-opus-5-5, thinking high; Claude Code 2.1.286; 2026-10-01.

With `server.telemetry.export_audio` on, the upload after a session
closes sends the pair to the session's trace as before and then, turn
by turn, each turn's heard clip and (when reply audio was paced) reply
clip against that turn's own trace, referenced there by one `capture`
span under the turn span. What the worker reads is decided in process:
the capture's close hands the store its in-memory clip list, the
staging records every staged file's `(st_dev, st_ino, st_size)`, and
one reading helper opens the job, `turns/` and each leaf descriptor
relative without following a link, checks the identity, and reads
through the checked descriptor. The guarantee, exactly: the worker
reads only through a descriptor whose device, inode and size match what
was staged, opened without following links; it does not defend against
a same-size file taking over a staged file's inode after the capture's
own names are pruned, which only a writer running as this server's user
can arrange; and it claims nothing about content. `capture_uploaded`
gains `clips`, a new
WARNING `capture_clips_incomplete` carries the four counts and a
`ClipFilingFailure` reason, and both reach the session's trace.

### The commits

| Commit | What it is |
| --- | --- |
| `26456452` Test each turn's clips filed on its own trace | The unit, telemetry and integration cases, and the doubles they need, watched failing (below) |
| `f4975113` Hand the store a capture's clips at its close | `TurnClips`; `SessionCapture.close()` passes its clip list to `on_close`, and `CaptureStore.finished()` to `stage()` |
| `01625d75` Declare what the clip filing says | `ClipFilingFailure`, `clips` on `CaptureUploaded`, `CaptureClipsIncomplete`, the README index row and the regenerated events reference |
| `787f8e29` Stage the clips with an inventory, read by descriptor | Staging with the trusted inventory, `_read_staged` for the pair and the clips, the `_identity_checked` seam |
| `c2463a61` File each turn's clips on its own turn | `_file_turns`, `_file_clip`, `_retrying`, the outcomes, and the event baseline's driver |
| `1c7705ae` Put the clip outcomes on the session's trace | `capture_clips_incomplete` in `AFTER_THE_CLOSE`, five rows in `AFTER_THE_CLOSE_ATTRIBUTES` |
| `a6f7004f` Document what export_audio now sends | The egress documentation footprint and the regenerated `server-config.md` |
| `3d0b08c5` Announce the turn clips leaving with export_audio | `changelog.d/496-turn-clips-export.md` under `### Changed` |
| Record M3 of the turn audio plan | This section and the tick |

### The tests, and how they were watched failing

Against the unchanged uploader (M2's tip), the unit run of
`test_capture_upload.py` and `test_telemetry.py` ended
`34 failed, 163 passed, 5 errors in 24.96s` (the errors are teardown
failures on the refused emission of a `capture_uploaded` carrying a
`clips` field that did not exist yet), and the integration file
`4 failed, 3 passed in 109.95s`, each integration failure
`only 2 attachment(s) were asked for`. The cases that passed there and
were meant to are claims about kept behavior: an altered pair replaced
by a directory (a path read already refused one), a failed pair trying
no clip, and the transcripts-only flag case staging nothing.

- Unit (`tests/unit/test_capture_upload.py`, a new section): the pair
  and four clips, every request's digest and trace id in order, one
  reference per turn with `heard_audio` and `reply_audio`, `clips=4`
  and no warning; a heard clip alone for a turn that spoke nothing; a
  recording with no turns (`clips=0`, no warning); a turn with no
  retained context counted unfiled and never referenced on the session;
  a refused reply clip, a refused first clip (not retried, stops
  nothing), a 413, a retry-exhausted 503 skipping every later clip, an
  unreferenced turn (one reference asked for, with both tokens), a
  vanished staged clip, each asserting the `capture_clips_incomplete`
  record exactly (WARNING, four counts, `reason` or its absence); a
  failed pair, refused and lost, trying no clip and saying only
  `capture_upload_failed`; through the real exporter, one `capture`
  span per turn in the turn's trace and under the turn span beside the
  session's own, and #517's sequence leaving the second turn unfiled
  with no reference anywhere; the clips inside the one-rename commit
  and the sweep taking them; seven altered stagings of a clip and four
  of the pair with an outside sentinel padded to the clip's size (every
  request's digest one of the capture's own files, the sentinel's
  digest in none, the sentinel and its path in no record or field); a
  same-size in-place rewrite of the staged manifest naming a traversal,
  an absolute path and an unstaged utterance, after which the clips
  asked for are exactly the inventory's; the rename between check and
  read; and a clip's presigned URL with a credential-shaped query string
  failing to connect, hunted in both formats, every field and both
  streams.
- Telemetry (`tests/unit/test_telemetry.py`): `vinga.export.clips` on
  `capture_uploaded`, the new outcome's span on the session's retained
  trace under the session span with its four counts and
  `vinga.export.reason`, and no reason attribute where nothing failed.
- Integration (`tests/integration/test_capture_upload.py`): the whole
  path now expects the pair and the turn's two clips, the clips against
  a trace that is not the session's, the PUT bodies exactly the pair and
  the turn's two clips (the "nothing outside what the capture staged"
  extension beside the decision-track assertion), the turn's `capture`
  span under the turn span with tokens naming the minted ids, and
  `vinga.export.clips == 2`; two new cases hold the flags apart (audio
  alone: four requests and no transcript on the turn or anywhere on the
  wire; transcripts alone: the transcript on the turn, no media request,
  nothing staged, no `capture` span).
- Doubles: `Traced` answers `turn_context` and records per-turn
  references (and every reference asked for); the fake client answers
  each request on its own (`answering`).

### Deviations from the plan

- **Commit order.** The plan lists the event fields after the worker's
  filing. The vocabulary was declared before the staging instead,
  because the staging's reading helper already chooses between two
  `ClipFilingFailure` members; the baseline's every-variant case was red
  on the new event between that commit and the filing's, the order the
  transcript export's vocabulary took. The telemetry mapping is its own
  commit after the filing.
- **The plan's live gate reads back "with the Langfuse MCP"; the brief
  asked for the public REST API.** Both were done: the REST read-back
  covers every turn, and the MCP read of turn 1's `capture` and `turn`
  observations agrees with it (below).

### Resolutions and decisions made here

- **The seam for the rename case** is a module-level no-op in
  `capture_upload.py`, `_identity_checked(leaf)`, called by
  `_read_staged` after the identity check and before the read. The case
  replaces it with `monkeypatch.setattr` and, from inside that window,
  renames the staged clip away and links the sentinel in its place.
- **A clip whose link fails at staging** stays in the inventory with no
  identity, the pair still goes, and the worker reports that clip
  `staging_lost` without opening anything, rather than failing the
  whole job. A failed PAIR link still fails the staging, as before. The
  staging now also refuses a pair link that is not a regular file.
- **Leaves are opened `O_NONBLOCK`** as well as `O_NOFOLLOW`, so a FIFO
  planted in a clip's place cannot wedge the worker on its open; its
  `fstat` then refuses it as `staging_altered`.
- **Exactly the staged number of bytes is read**, so a file grown after
  its check cannot send more than was checked, and one cut short after
  its check is `staging_altered`. A read error is `staging_lost`.
- **Reasons**: `ENOENT` anywhere on the way is `staging_lost`; any other
  open failure (`ELOOP` on a link, `ENOTDIR` on a file where `turns/`
  was) and any identity mismatch is `staging_altered`. For the pair,
  both stay `staging_lost`. An upload's classification maps to the
  clip's set by name (`_clip_reason`: `refused`, `too_large`, otherwise
  `unreachable`), never raising, since a raise there would fail a job
  whose pair had landed.
- **`capture_clips_incomplete` has one variant** with `reason` declared
  `ClipFilingFailure | Absent`; the sentence renders the four counts,
  and the reason rides the payload and the span. Skipped clips always
  follow a failed one, so an absent reason means every missing clip was
  unfiled.
- **`elapsed_ms` on `capture_uploaded`** now covers the clips as well as
  the pair, since the event is said after them; the note ("how long the
  whole attachment took") was left as written, since it still reads
  true.
- **Staging holds the clips too**, so M2's budget case now counts them
  among what a pruned capture leaves on the disk.
- **The two integration hostile-backend cases** stage through `stage()`
  rather than writing the uploader's private map, which removes two
  reach-ins (`_staged`) from the census.
- **Prose** follows the plan as amended during M2's review: every turn
  has a heard clip, and a reply clip when reply audio was paced.

### Discoveries

- **The regular-file check on the opened leaf is not independently
  reachable** (the one surviving mutation, below). An inode's file type
  is fixed for its life and the staging records only regular files, so
  a descriptor whose device and inode equal the inventory's is a
  regular file; a directory in a clip's place is refused by its inode
  and size. The check is kept because the plan states it and it costs
  one comparison, and recorded here rather than claimed as tested.
- **During the work M2's review tip briefly failed**
  `test_a_failed_capture_write_refuses_carrying_nothing` (the
  builtin-ancestor class naming meant the planted class no longer
  reached construction); the second review round's revert fixed it, and
  the full unit lane below, on the merged M2, passes it.
- **M2's changelog fragment** says `export_audio` still sends only the
  pair; it was folded into `CHANGELOG.md` before this milestone, true
  of M2 alone, and this milestone's fragment supersedes it.

### Mutations

One run each, against the finished code, each restored from a copy
(not `git checkout`) and touched afterwards, with
`PYTHONDONTWRITEBYTECODE=1`, each running only the named cases:

| Mutation | Outcome |
| --- | --- |
| A clip filed under the session's trace (plan) | Killed: the first case's trace ids |
| Clips tried after a retry-exhausted failure (plan) | Killed: the skip case |
| Stopping after a refusal (plan) | Killed: both refusal cases |
| Referencing per clip rather than per turn (plan) | Killed: the unreferenced case and the first case |
| Counting a clip attached before its reference answered (plan) | Killed: the unreferenced case |
| Reading by path after the check (plan) | Killed: the rename case |
| Dropping the inode comparison (plan) | Killed: the hard-link case |
| Following the directory symlink (plan) | Killed: the `turns/`-to-the-real-clips case |
| Dropping `clips` from the outcome table (plan) | Killed |
| Dropping `skipped` from the outcome table (added) | Killed |
| Following a leaf symlink (added) | Killed: the leaf-link-to-its-own-inode case |
| Dropping the size from the identity (added) | Killed: the grown case |
| Dropping the regular-file check (added) | **Survived**: not independently reachable (Discoveries) |
| The pair read by path again (added) | Killed: all four altered-pair cases |
| Every clip failure called `unreachable` (added) | Killed: the refused-first-clip case |
| An unfiled turn filed on the session instead (added) | Killed: both unfiled cases |
| Clips tried after the pair failed (added) | Killed: the refused-pair case |

### The live gates

Run on agentpi at `3d0b08c5` (this record adds prose only) with a
scratch driver copied from #536's: a real server in process, OpenAI
ASR (`gpt-transcribe`, `language: en`), LLM (`gpt-4.1-mini`) and TTS,
silero VAD, capture into a scratch directory, `server.conversations`
with text, `server.telemetry` with `export_audio` and
`export_transcripts`, OTLP to the Langfuse project in `.env`, and
`LANGFUSE_HOST` set from its `LANGFUSE_BASE_URL`. One session, two
spoken turns. Its database was dropped afterwards.

- Session `7077676e9dcb49e2920c7fa8395814a5`, session trace
  `6c95faddf82f07e4f8d60a61b6e09e7d`.
- Turn 1, utterance `7c6f547da26c403899fca0105b1c4c17`, trace
  `8fb3e48ab9a500b1995160a9c0d18cb6`; turn 2, utterance
  `71893f609e754d8da1b5ddf555c9188a`, trace
  `7bf3c6e79505ba43f937be4ed2890698`.
- Events: `capture_uploaded` with `clips=4` (and the pair's sizes), two
  `transcripts_exported`, and no `capture_clips_incomplete` and no
  `capture_upload_failed`.

**Gate 1, passed.** Read back through the public REST API
(`/api/public/traces/<id>`, `/api/public/media/<id>`) for both turns:
each turn's trace holds `turn`, `asr`, `llm`, `tts_stream`,
`playback` and `capture`; the `capture` observation's parent is the
turn observation, its metadata holds `heard_audio` and `reply_audio`
media tokens, and each media record exists with content type
`audio/wav`, marked uploaded, its length equal to the local clip's
(turn 1: 117132 and 112076 bytes; turn 2: 97836 and 144406); the turn
observation's input is the transcript ("What time does the garden open
on Saturdays?", "Is there a cafe in the garden?"); and the `asr`
observation under the same turn root carries model `gpt-transcribe`
and provider `openai`. The Langfuse MCP read of turn 1's `capture`
observation (`bfe6460e5b3ad88d`, parent `1e40ce255f247a1a`) and its
`turn` observation (input the same transcript) agrees. The session's
own `capture` span is under the session span in the session trace, as
before.

**Gate 2, passed.** Turn 1's persisted
`7c6f547da26c403899fca0105b1c4c17.heard.wav` (117132 bytes, a 44-byte
header whose data length matches) had its PCM re-wrapped by the
provider's own `wav_bytes` and sent to `gpt-transcribe` with
`response_format: json` and `language: en`, the options the server
used. It returned "What time does the garden open on Saturdays?",
identical to the transcript recorded on the turn's trace and to what
the device was told it said.

### Verification

On agentpi, from `vinga-server/`, at `3d0b08c5` (the milestone's last
code and prose commit before this record, on `origin/main` after M2's
merge):

- `uv run ruff check .`: `All checks passed!`
- `uv run mypy`: `Success: no issues found in 5 source files`
- `uv run pytest tests/unit -q -n auto --dist loadfile`:
  `7694 passed, 19 skipped in 908.98s (0:15:08)`; the skips are the
  `piper` and `faster-whisper` extras, not installed here
- `uv run pytest tests/integration -q -n auto --dist loadfile`:
  `349 passed in 236.02s (0:03:56)`
- The drift checks: every generated reference regenerated through its
  generator (`config reference server`, `config reference`, `events
  reference`, `config openapi`, `conversations schema`, `conversations
  views`, `config cli-reference`); `events.md` moved with the
  vocabulary and `server-config.md` with the prose, and nothing else;
  `scripts/check_doc_links.py .` and `scripts/fold_changelog.py check .`
  pass
- `uv run pytest tests/census -q`, run last, after this section was
  written: `66 passed`. The reach-in manifest was regenerated with its
  generator first: it lost `tests/integration/test_capture_upload.py
  _staged 2`, the two reach-ins the hostile-backend cases no longer
  make; the rename seam is set through `monkeypatch.setattr` on the
  module and adds none

Not verified here: the image build and its smoke conversation, which
run only in CI, and anything on a board.

Rebases during the work: onto M2's review tips `63c9c85d` and then
`f3985469` (both clean), and finally `git rebase --onto origin/main
f3985469` after PR #572 merged (clean; `git log origin/main..HEAD`
lists only this milestone's commits). The mutation runs were made
before the last rebase, which moved only M2's commits beneath them.

### PR review round, PR #574

Automated external review of this PR's diff (origin/main...43389ed7).
Reviewed 2026-09-30 by openai/gpt-5.6-sol, thinking high via codex CLI 0.156.1, read-only sandbox, runtime 8m03s, at commit 43389ed7.
Verdict as received: **mergeable after the listed fixes**. Three
findings: the first rejected with its claim made exact, the other two
fixed.

1. **P1: the trusted inventory is open to inode-reuse substitution.**
   The inventory keeps `(st_dev, st_ino, st_size)` and no descriptor, so
   once the prune has removed the capture's names, a staged link could
   be unlinked, its freed inode reused for same-sized unrelated content
   at the staged name, and the worker would upload it with every check
   passing. The reviewer asked for a descriptor held on each staged file
   as an inode anchor until the job ends, closed on every exit, and an
   unlink-and-reuse sentinel test for a clip and the pair.

   *Resolution*: Rejected, claim made exact, in `2a7fc2e2`. Two
   reasons. First, only a process running as this server's own user
   can unlink a staged link and get a freed inode reused for
   same-sized content in its place, and such a process can already
   read every file the uploader can, and the uploader's own
   `LANGFUSE_*` credentials from the environment, so it gains no
   exfiltration it lacked; the staging defences are against the
   uploader being steered by on-disk state (path strings, links,
   renames, replaced files), not a boundary against the server's own
   user. Second, anchors cost one descriptor per staged file held for
   the job's whole life, up to the backlog (`max_sessions`) times two
   plus two per turn, which puts descriptor exhaustion, and with it the
   server's own sockets, within reach of a slow backend. What is taken
   is the finding's point that the claim overstated the mechanism:
   the uploader's module and `_Identity` docstrings,
   observability-surfaces' "Exported capture media", the changelog
   fragment, a test comment and this section's summary now say
   exactly that the worker reads only through a descriptor whose
   device, inode and size match what was staged, opened without
   following links; that it does not defend against a same-size file
   taking over a staged file's inode after the capture's own names are
   pruned, which only a writer running as this server's user can
   arrange; and that it claims nothing about content. No code change.

2. **P2: the completed M3 item still said `PR TBD`.**

   *Resolution*: fixed in this record's commit; the item now links PR
   [#574](https://github.com/rafacm/vinga/pull/574).

3. **P3: the uploader's documentation said no request carries a file
   the manifest does not list**, which contradicts the inventory being
   authoritative (the rewritten-manifest case sends the inventory's
   clips whatever the manifest says).

   *Resolution*: fixed in `9222af59`. The module docstring and the
   integration wire test's prose say no file outside what the capture
   staged, the in-process inventory, is sent; the docstring adds that
   the staged manifest is an uploaded artifact never read to choose a
   file. The worker is unchanged and still does not read the manifest.

Verified for the round, on agentpi from `vinga-server/`, at `9222af59`
plus this record: `uv run ruff check .` (`All checks passed!`),
`uv run mypy` (`Success: no issues found in 5 source files`), the
upload files in both lanes (`tests/unit/test_capture_upload.py` and
`tests/integration/test_capture_upload.py`, `-n auto --dist loadfile`:
`115 passed in 44.64s`), every generated reference against its
generator (all six current; the round regenerates nothing),
`scripts/check_doc_links.py .` and `scripts/fold_changelog.py check .`,
and last the census lane (`66 passed`). The full unit and integration
lanes were not rerun for the round, which changed prose only.

## M4: which loop answers which ASR question

**Attribution:** anthropic/claude-opus-5-5, thinking high; Claude Code 2.1.286; 2026-10-01.

Documentation only. `docs/conversational-quality-regression-suite.md`
gains a section, "Which loop answers which ASR question", between the
three layers and the invalidation table, written to the 2026-09-20
comment on #496 item by item: the field round and the dataset loop as
supplier and consumer; the decision rule as two lists of examples; how
an item is born, attributed to its session's manifest and its round,
with the clips as instrument and the numbers derived from them as
calibration; that the parts meet by utterance id on the host, and on
the turn's own trace only with `export_transcripts` on (with
`server.conversations` storing text) as well as `export_audio` (round
1, finding 8); who corrects the expected text, paid once per item;
where the durable copy lives, which is nowhere until an operator
copies it out of both retentions; and the closed list of what the
dataset loop may never claim, each with its reason. The invalidation
table's ASR row is split in place into two rows, one per loop, and the
field round's row carries the sentence that keeps short-clip loss rate
apart from word error rate on survivors. The page is research and
field notes in `docs/README.md`'s taxonomy, which is where evidence
about how to run and read a round belongs; what the exports carry is
left to `observability-surfaces.md`, which the section links rather
than restates.

The section describes M3's behavior (each turn's clips filed on its
own trace under `export_audio`) as the plan and its review rounds
specify it, since this milestone merges after M3.

### The commits

| Commit | What it is |
| --- | --- |
| `5d580622` Say which loop answers which ASR question | The section, the split row, and one sentence in the working procedure below the table |
| `330e704a` Record M4 of the turn audio plan | This section and the plan's tick |
| `aaab4b57` Say a turn row holds its transcript only with text on | PR review round, finding 2 |
| `15877e66` Say only a retained turn gets its clips on its trace | PR review round, finding 1 |
| `b5b5adf0` Tell an item's retained sources from the item | PR review round, finding 3 |
| `873a7b6b` Link M4's tick to its pull request | PR review round, finding 4 |
| Record PR #573's review round for M4 | The round below |

### Deviations, resolutions and decisions

One deviation from the plan's M4 item, in how it was built rather
than what it says: the item says "stacked on M3", and this branch was
cut from `origin/main` (the plan, M1 and M2) while M3 was implemented
in parallel, at the orchestrator's direction, to be rebased onto M3
before it merges. So the section was written against M3's plan and
review resolutions rather than M3's merged prose, and the link check
is rerun after that rebase. Nothing in the section depends on M3's
wording, only on its behavior.

What the plan and the comment left to the writer, decided here:

- **The loss-rate sentence follows the plan, not the 2026-09-20
  comment's wording.** The comment said none of the lost clips has a
  dataset item. That was written before the capture kept them: M2
  writes the heard clip in `start_reply`, before the ASR runs, so a
  turn whose transcript the echo retry discarded (or that fell under
  the openai adapter's minimum) keeps its clip, which is the plan's
  stated reason for keeping short audio. The table row therefore says
  speech the VAD never segmented never has an item and a discarded
  transcript has no transcript to score, and the section adds that a
  lost clip can be harvested and corrected like any other, so the
  dataset can say how a candidate does on it but never how many the
  pipeline loses.
- **The split is two rows, not two cells.** "Each cell names the loop"
  is met by naming the loop in each row's Change cell, so the
  Re-measure and Still valid cells stay one answer each, in the
  table's existing shape.
- **The closed list is the comment's six field-only classes plus the
  loss rate.** The comment calls the list the between-turn failure
  classes; the loss rate is the one number counted over them, and it
  is the concrete case the section exists to prevent, so it is on the
  list with its reason. The list says how it grows: a between-turn
  class found later joins it in the change that finds it.
- **The durable-copy paragraph follows the 2026-09-30 decision.** The
  2026-09-20 comment said the three field files last; the capture has
  a budget and prunes whole sessions, so the section says neither copy
  is durable, as the decision comment settled.
- **Two sentences beyond the comment's list**, both consequences of it
  rather than new claims: that an item's audio survives an ASR change
  but not a device change or input-pipeline redesign, whose ASR
  questions wait for a harvest of their own (the invalidation table's
  own device and pipeline rows); and, in the working procedure under
  the table, that for an ASR change the dataset's row runs first and
  the field round carries only its own.
- **Links.** The page links other documentation pages and cites the
  tracker only by bare issue number in its introduction; it links no
  plan and no issue. The section follows that: it links the two
  `observability-surfaces.md` sections that own what the exports
  carry (`#exported-capture-media`, `#exported-transcripts`), and
  names no issue or plan. Those anchors are headings M3 edits the
  prose under; the link check is rerun after the rebase onto M3.
- **The field-only reason for "does it feel right"** is worded as
  happening "across the exchange as a person lived it", since feel is
  not literally located between two turns the way a VAD miss is.

No changelog fragment, as the plan says.

### Mutations

None: the milestone changes no code and adds no test, so there is no
claim a mutation could falsify. The claims the prose makes about the
code were read at the source rather than assumed: the heard clip is
written in `start_reply` before the ASR runs (M2's section above and
`runtime/pipeline.py`); the echo retry's discarding outcomes answer an
empty transcript (`providers/openai_asr.py`, `_retry_without_prompt`, whose
`EchoSkipped`, `EchoRetryTimedOut`, `EchoConfirmed` and
`EchoConfirmedEmpty` arms all return an empty hearing);
the conversation store's turn row carries `utterance`
(`docs/reference/conversations-schema.md`); the transcript export
needs `server.conversations.text` and `export_transcripts`
(`config/models.py`, `observability-surfaces.md`); the capture prunes
to `server.capture.max_total_mb`.

### Verification

From the worktree, after the final prose edit:

- `python3 scripts/check_doc_links.py .`: `checked 278 files, 0 failures`
- Census lane, `uv run pytest tests/census -q` from `vinga-server/`,
  on the final prose with only this line still to fill in:
  `66 passed in 32.60s`, neither manifest needing regeneration; rerun
  after this record was committed, as the last step, with the same
  count.

The unit and integration lanes were not run: nothing they exercise
changed.

### PR review round, PR #573

Automated external review of this PR's diff (origin/main...330e704a).
Reviewed 2026-09-30 by openai/gpt-5.6-terra, thinking high via codex CLI 0.156.1, read-only sandbox, runtime 3m03s, at commit 330e704a.
Verdict as received: **mergeable after the listed fixes**. Four
findings, all fixed here, each in its own commit.

1. **P2: `export_audio` was documented as filing every turn.** The
   section said the flag sends each turn's clips to its trace, while
   M3 files a clip only where the exporter still holds the turn's
   context and reports the rest unfiled, with no session-trace
   fallback.

   *Resolution*: fixed in `15877e66`. The sentence is qualified to
   every turn whose trace the exporter still holds, names the turns it
   does not (past the retained count, a span never opened, a turn it
   never saw), says their clips are left unfiled and counted in the
   `capture_clips_incomplete` warning rather than attached to the
   session's trace or anywhere else, and that such a turn's item has
   to come from the host.

2. **P2: the host-side recipe promised a transcript on every turn
   row.** The stored turn's `heard` is null under text-off, and the
   store may be off altogether.

   *Resolution*: fixed in `aaab4b57`. The recipe now says the row
   holds the transcript only with `server.conversations` on and
   storing text, that otherwise no row holds the production
   transcript, and that a round meant to feed the dataset either turns
   text storage on for its duration or has the operator keep the
   transcript some other way. The backend recipe moved to a paragraph
   of its own so the two read apart.

3. **P2: the retention paragraph called the retained artifacts
   "copies of an item".** Neither the capture nor the backend holds
   the hand-corrected expected text, which the same paragraph named
   as part of the item.

   *Resolution*: fixed in `b5b5adf0`. The section now separates the
   item's sources, which vinga retains under retentions the dataset
   does not control (the heard clip and the manifest in the capture
   directory, the production transcript in the conversation store
   where text was stored and in the backend where it was exported),
   from the curated item, whose corrected text none of them holds. The
   conversation store's `retention_days` is named beside the other two
   retentions, since the production transcript is now one of the
   sources. The operator assembles the item in storage of their own:
   the sources copied out before their retentions remove them, the
   corrected text stored beside them.

4. **P2: the completed milestone still said `PR TBD`.**

   *Resolution*: fixed in `873a7b6b`. The tick links PR
   [#573](https://github.com/rafacm/vinga/pull/573). This section's
   commit table now carries the hashes of the commits after the push,
   which were not rebased.

Verified for the round, from the worktree after the last prose edit:
`python3 scripts/check_doc_links.py .` (`checked 278 files, 0
failures`), and last the census lane from `vinga-server/`
(`uv run pytest tests/census -q`): `66 passed in 28.58s` on this
record with only this figure still to fill in, neither manifest
needing regeneration, and rerun after the record was committed, as the
last step, with the same count.
