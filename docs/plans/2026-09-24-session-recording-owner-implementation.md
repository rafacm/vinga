# Give a session's recording one owner: implementation

Companion to [`2026-09-24-session-recording-owner.md`](2026-09-24-session-recording-owner.md),
one section per milestone, appended in the same change that ticks the
milestone checklist. It records deviations from the plan, resolutions
of the plan's open questions, and discoveries.

## M1: a session's recording gets one owner

**Attribution:** anthropic/claude-opus-5-5, thinking high; Claude Code 2.1.281; 2026-09-24.

A device session's recording has one owner,
`vinga_server/device/recording.py`'s `Recording`: the capture (its
decision-track attachment, the `CaptureAudio` codecs, the release when
those will not open), the conversation store's session row and its
sink, the two audio feeds, and the close, which ends the row, finishes
the capture and makes the three post-close handoffs in their order.
`DeviceSession` takes one `RecordingFactory` in place of four
collaborators, builds its owner once in `__init__`, and calls `open`,
the feeds and `close` at the moments it already decided. No behavior
changed, and the pins committed first say so.

### The commits

| Commit | What it is |
| --- | --- |
| `575655c8` Pin the order a session's recording runs in | `tests/unit/test_recording_order.py`, two pins in `test_capture_session.py`, and `recording_session` in `tests/support/sessions.py`, green against the session before anything moved |
| `32a827e1` Add the owner of a device session's recording | `device/recording.py` and `tests/unit/test_recording.py`, nothing using it yet |
| `3b3c2897` Move a session's recording onto its owner | The move as one commit, its body walking the session's calls, the constructor and its sites, the fields and methods, the patch targets and the white-box lines; the reach-in manifest |
| Record M1 of the recording owner | The three docstrings of the documentation footprint, this section and the tick |

### What landed

| Piece | Where |
| --- | --- |
| The owner | `device/recording.py`: `Recording` (`open`, `microphone`, `reply`, `close`), `RecordingFactory`, `recordings(...)`; imports at runtime only modules `device/session.py` already imported, and the two exports under `TYPE_CHECKING`, with the true reason: they are named for annotations and nothing else |
| The session | `device/session.py`: the six fields and `_start_capture`, `_start_recording`, `_stop_recording` gone; `self._recording` built in `__init__`; the open site hands over the manifest, the accept's reading, the protocol version, `OUTPUT_AUDIO`'s rate, the renames thunk and `_device_name()`; the close tail's recording lines are one `close` with `_open_duration_s()` and `_closed_reason()` read at the call; the two feed sites keep their positions and lose their `None` checks. 50 lines added, 196 removed |
| The renames thunk | Built at the open site in `_converse` from `self._generation`, exactly as `_start_recording` built it, with its comment; the owner hands it to the store as it came |
| The composition | `ws.py`: `recordings(comp.capture, comp.conversations, comp.transcripts, comp.llm_input)` in the fourth position, derived at the call; `Composition` unchanged |
| The docstrings | the session's module docstring (the owner joins `pacing` and `watchdog` as what it owns without carrying, and "records the capture" became "hands its recording the facts it needs"); `CaptureAudio`'s class docstring; the owner's module docstring, which carries the open and close orderings that were the session's comments and names `events.SessionRecording` as one of the things it holds |

### The pins, and what they pinned

The plan's inventory of what was unpinned held; each gap it numbered
has a pin now, all green at `575655c8` against the session before the
move and unchanged by it:

- **(1) the open's order**, and the two failure injections:
  `test_the_open_runs_capture_first_then_the_store_then_its_sink`,
  `test_a_capture_store_that_declines_leaves_the_row_opening_normally`,
  `test_a_store_that_will_not_open_still_leaves_the_capture_released`.
- **(2) to (7) the close's order**, the barrier by identity, the
  LLM-input handoff made at all, and `session_closed` as the capture
  track's last line: `test_the_close_runs_in_its_order_and_hands_on_the_barrier`.
- **(8) the reason and the duration**, through the duration cap:
  `test_the_row_is_closed_with_the_reason_and_duration_the_session_ended_with`.
- **(9) a `not_listening` drop still recorded**:
  `test_the_microphone_is_recorded_before_the_device_asked_to_be_heard`
  in `test_capture_session.py`, over the wire like its `barge_in_off`
  counterpart.
- **(10) the reply recorded after its send, and never when the send
  raised**: `test_a_reply_frame_is_recorded_after_it_is_sent_and_never_if_it_was_not`,
  through `send_audio` on a served session.
- **(11) the refusals**, parametrized over a bad Device-Id, no agent
  and no hello: `test_a_session_refused_before_its_hello_records_nothing`.
- **(12) the codec warning exactly**: the existing codec test asserts
  `record.name == SESSION_LOGGER`, `record.levelno == logging.WARNING`,
  `record.msg` and `record.args == (session_id, "CodecUnavailable")`
  beside its substring and sentinel checks, which stay.

Across the move the pins changed only where the plan allows: the
`CaptureAudio` and `SessionSink` patch targets, and the one import line
in `test_recording_order.py` that names the module its `CaptureAudio`
stand-in patches. Every other pin line is byte-unchanged
(`git diff 575655c8 3b3c2897 -- vinga-server/tests/unit/test_recording_order.py`
is that one line).

### The falsification runs

One run each; every rule here is straight-line. Each mutation was
applied to a copy-restored source file, touched after the restore, and
each failed on the assertion it was aimed at. None survived.

Against the session, for the pins (at `575655c8`):

| Mutation | Result |
| --- | --- |
| the capture and the row opened in the other order | the open pin fails at index 0 |
| the row opened first, with the taps still attached capture first | the open pin fails at index 0 |
| the row closed before its sink is detached | the close pin: `close_session` recorded the sink still attached |
| the capture closed before its tap is detached | the close pin: `('capture.close', False)` |
| the transcript and LLM-input handoffs swapped | the close pin at index 9 |
| the capture store told before the capture closes | the close pin at index 7 |
| `None` handed to the transcript export | the barrier identity check |
| the LLM-input handoff deleted | the close pin is one entry short |
| the capture and row closed before `session_closed` is emitted | the close pin at index 5 |
| a fixed close reason | the reason pin: `'client' != 'limit'` |
| a duration 50 ms short of the event's | `0.29 >= 0.34` fails |
| the row skipped when the capture store declined | the declining pin at index 1 |
| the handoffs skipped when no row was closed | the row-refusal pin at index 5 |
| the capture left open when no row was closed | the row-refusal pin at index 4 |
| the reply recorded before its send | the reply pin at index 0 |
| a handoff made from the refusal path | all three refusal cases fail |
| the mic feed moved behind the listening guard | the `not_listening` pin: 0 ms recorded |
| the codec warning through a module logger | `'vinga_server.device.session' != 'vinga_server.session'` |
| the codec warning at INFO | `20 == 30` fails |
| the codec warning pre-rendered | `record.msg` differs |

Against the owner, for its own tests (at `32a827e1`):

| Mutation | Result |
| --- | --- |
| the warning through `logging.getLogger(__name__)` | `'vinga_server.device.recording' != 'vinga_server.session'` |
| the row closed before its sink is detached | the close recorded the sink attached |
| the row opened before the capture store, taps still attached capture first | the opening list at index 0 |
| the sink attached before the capture | the opening list at index 0 |
| the handoffs reordered | the close list at index 2 |
| `None` handed to the transcript export | the barrier identity check |
| the capture closed before its tap is detached, in the close | `('capture.close', False)` |
| the same, in the codec-failure arm | `('capture.close', False)` |
| the release dropped from the codec-failure arm | the failure's list at index 2 |
| a feed after `close` reaching the codecs | two feeds too many |
| the renames callable wrapped rather than handed on | the identity check |
| a fixed reply rate | `('CaptureAudio', True, 2, 16000)` |
| the device name dropped | the opening list at index 3 |
| the handoffs made only after a row closed | the close-without-open list |

### Deviations from the plan

- **The reply sample rate reaches the owner through `open`, not its
  constructor.** The plan's sketch has `Recording.__init__` take
  `reply_sample_rate` while the factory is called with the session id
  and the events object only, which leaves the rate nowhere to come
  from: it is the session's `OUTPUT_AUDIO`, and importing it into the
  owner would be an import of the session that imports the owner. It
  travels with the protocol version instead, the other wire fact the
  codecs are built against, and both are keyword-only, as are
  `renames` and `device_name` after them.
- **A tenth construction site.** The pins needed a session holding
  doubles its runtime does not hold, and `served` hands its store to
  both, so commit 1 added `recording_session` to
  `tests/support/sessions.py`. At the move there are ten sites: the
  plan's nine and that one.
- **The reach-in manifest was regenerated in the move commit**, not in
  the documentation commit the checklist names, so the move commit's
  census lane is green on its own, which the checklist also asks. The
  #484 milestone resolved the same conflict the same way. The delta is
  the plan's.
- **The open site asserts the accept's reading** (`assert opened_at is
  not None`) where `_start_capture` and `_start_recording` each
  returned on `None`. The reading is stamped at the accept, above every
  path to the open, so the branch was unreachable; `open` takes a
  `float`, as the plan's signature says, and `_converse` already
  asserts its conversations the same way.
- **The session evaluates `_device_name()`, the renames thunk and the
  close's duration and reason whether or not a store is configured**,
  where the old methods read them only when one was. All four are pure
  reads at the same instant as before, so nothing observable moved.

Otherwise none: the module, its place, the class and factory names, the
factory derived in `ws.py`, the unguarded close and the verbatim codec
warning are the plan's.

### Discoveries

- **The plan's "five of them pass" count excludes `ws.py`.** At the
  base six sites passed one of the four: `ws.py` (all four,
  positionally), `device_session` (`transcripts`, `llm_input`),
  `served` (`conversations`), and `test_session_device.py`,
  `test_capture_session.py` and `test_conversations_session.py`
  (`captures` fourth, the last with `conversations` too). Not
  load-bearing; all six changed.
- **The false comment's dates hold.** The `TYPE_CHECKING` comment was
  written at `bc6924fa` (2026-09-12), two days after `c5cbe42d`
  (2026-09-10) gave the session its runtime import of
  `vinga_server.telemetry`, so it was false when written, as the plan
  says. It left with the fields; the owner's comment states the true
  reason.
- **One teardown error in the first integration run, not reproduced.**
  `test_telemetry_hardening.py::test_the_shutdown_of_a_wedged_exporter_is_bounded`
  errored at teardown in the parallel lane: its autouse fixture found
  the SDK's quieting lease still held (`assert 1 == 0`) after the
  exporter was "left behind" at its 5 s bound. The whole lane rerun was
  green, and the file alone passed three runs of three. The session
  that file builds (through `session_for`) hands its owner no recording
  collaborator at all, so the owner does nothing there; the lease is
  the exporter's. It was not run at the plan base, so this records a
  load-dependent teardown race in that file rather than a cause.

### The closing greps

Untruncated, from `vinga-server/`, counting lines.

| Question | At `7133366d` (plan base) | At this commit |
| --- | --- | --- |
| `\._(capture_audio\|record\|captures\|conversations\|transcripts\|llm_input\|start_capture\|start_recording\|stop_recording)\b` in `src/vinga_server/device/session.py` | 33 | **0** |
| the same names read off a session under `tests/` | 4 | **0** |
| the same names anywhere under `tests/` | 7 | 3, all `self._record(...)` in `tests/integration/test_capture_upload.py`, an HTTP handler's own method |
| `DeviceSession(` construction sites in `src` and `tests` | 9 | 10 (see the deviations): 7 changed at the move, 3 that passed none of the four unchanged |

### The reach-in census

Expected delta: three rows removed, `test_capture_session.py
_capture_audio 1`, `test_conversations_session.py _capture_audio 1` and
`test_conversations_session.py _record 2`, none added. Observed:
exactly those three removed and nothing added, regenerated with
`uv run python -m tests.census.test_reach_ins`. The pins and the owner's
tests add no reach-in: their doubles keep their state in public
attributes, and the reads of the events object go through
`events_of`, `attached_capture` and `SessionEvents.taps()`. The
command-spellings manifest did not move.

### #489's bookkeeping

The plan's command, run from `vinga-server/tests/unit` at `7133366d`
(the plan base), at `575655c8` (the pins) and at `3b3c2897` (the move);
the documentation commit changes no test. Column (b) judged per file.

| File | (a) base | (a) pins | (a) move | (b) storage reaching the subject through a visible parameter |
| --- | --- | --- | --- | --- |
| `test_capture_session.py` | 1 | 1 | 1 | yes: `lane_memory()` into the factory at line 407, and the capture store into `recordings(captures)` at line 409 |
| `test_capture_upload.py` | 2 | 2 | 2 | yes: the subject is built over `tmp_path` with its uploads double, `capture_store(tmp_path, uploads=uploads)`, first at line 524 |
| `test_session_record.py` | 4 | 4 | 4 | yes: the store is the subject, `ConversationStore(DatabaseConfig())` at line 230 |
| `test_session_device.py` | 8 | 8 | 8 | yes: a database-backed view, `DeviceBindings(generations, read_engine(DatabaseConfig()))` at line 215, handed to `session_for` as `devices=bindings` at line 222; and `lane_memory()` into the factory at line 537 |
| `test_session_device_name.py` | 3 | 3 | 3 | no: the store is written through `store_at()` (line 57) and reaches the session through `create_app(config, from_store=True)` (line 101), the composition root |
| `test_boundary.py` | 0 | 0 | 0 | no |
| `test_boundary_contract.py` | 1 | 1 | 1 | yes: `lane_memory()` into the factory at line 318 |
| `test_session.py` | 0 | 0 | 0 | no |

**Neither column moved**, which is the plan's prediction, and the pins
added nothing to either: the one pin that landed in one of the eight
(`test_capture_session.py`'s `not_listening` case and its codec-warning
assertions) names no storage, and the pin file and the owner's tests
are outside the eight. The move's edits to the eight are
`recordings(captures)` at two sites and the deleted white-box line,
none of which names storage. So this is the second seam of the three
the #489 comment named where the extraction did not make the storage
dependency more explicit: a test that handed the session a store hands
it to `recordings(...)`, one call deeper and just as visible. The
instrument's disagreement with the comment stands as #484 recorded it:
six of the eight name a storage helper.

### Verification

From `vinga-server/`, on agentpi.

| Where | What ran | Result |
| --- | --- | --- |
| the pins commit | `test_recording_order.py`; `test_capture_session.py`; the census lane | 9 passed; 14 passed; 66 passed |
| the pins commit | the new pins three more times | 11 passed, three runs |
| the owner commit | `test_recording.py`; the census lane | 14 passed; 66 passed |
| the move commit | the pins, the owner's tests, `test_capture_session.py`, `test_conversations_session.py`, `test_session_device.py`, `test_generation_binding.py`, `test_events_live_wiring.py`, `test_event_baseline.py`, `-n auto` | 94 passed |
| the move commit | `test_agent_rename_in_flight.py`, `test_session_record.py`, `test_boundary_contract.py`, the transcript and LLM-input suites, and the recording suites again, `-n auto` | 201 passed |
| the move commit | the census lane; `uv run ruff check .`; `uv run mypy` | 66 passed; clean; no issues in 5 source files |
| this commit | unit lane, `-n auto --dist loadfile` | 7577 passed, 19 skipped in 874.83s |
| this commit | integration lane, `-n auto --dist loadfile` | first run: 347 passed, 1 error in 207.78s (see the last discovery); rerun: 347 passed in 206.82s |
| this commit | `tests/integration/test_telemetry_hardening.py` alone | 4 passed, three runs |
| this commit | `uv run pytest tests/census -q`; `uv run ruff check .`; `uv run mypy` | 66 passed; clean; no issues in 5 source files |
| this commit | the eight drift checks the integration job runs (domain, server, conversations schema, metrics views, events, OpenAPI, CLI reference, CLI recipes) | no difference in any |
| `4926a5f6` (after the plan's round-2 citations were unlinked) | `python3 scripts/check_doc_links.py .` | 272 files, 0 failures |

Not run here: the image build, the smoke conversation and the compose
boot, the tier-closure and wheel lanes beyond what the integration lane
holds. No event, field, configuration key or command changed, so none
of them should move; the pull request records what CI says.

### PR review round, PR #562

Automated external review of this PR's diff (origin/main...4926a5f6).
Reviewed 2026-09-24 by openai/gpt-5.6-sol, thinking high via codex CLI 0.156.1, read-only sandbox, runtime 7m11s, at commit 4926a5f6.
Verdict as received: **mergeable after the listed fixes**. Three
findings: two fixed here, and one deferred to M2.

1. **P1: the codec-start warning renders an untrusted exception class
   name.** `recording.py` logs `type(exc).__name__` to the retained
   session logger, and `events/__init__.py` (the `_offer` comment)
   records that a dynamically created exception class can carry
   far-side bytes in its name. The owner's test poisons only the
   message and pins the class name, so it misses that leak. The
   reviewer asked for an owner-chosen label only, tested with a
   dynamically named, credential-shaped exception whose name and
   message are absent from the record's arguments, both renderings,
   stdout and stderr.

   *Resolution*: deferred to M2 by the orchestrator: M1 is a
   behavior-preserving move and its pins record today's warning
   verbatim; M2, the PR that already makes the close warnings
   class-name free, changes this warning to render nothing from the
   exception, with a dynamically named credential-shaped exception
   test, and its PR carries the fix. The warning and its tests are
   unchanged in M1.

2. **P2: the close-order pin did not pin the capture's detach after
   the row's close.** The pin instrumented `attach_capture` but not
   `detach_capture`, and its "whole close sequence" left the detach
   out, so moving the capture's detach before `close_session` still
   logged `("capture.close", True)` and passed.

   *Resolution*: accepted, in `fee7de09`. `watch_attachments` logs
   `detach_capture` while a capture is attached (the clearing inside
   `attach_capture` detaches nothing and is not logged), and
   `("detach_capture",)` sits between `close_session` and
   `capture.close` in the close sequence and in the row-refusal pin.
   Checked one run each: green against the pre-move session (a
   temporary worktree at `575655c8`, the file's patch target pointed
   back at the session module), green at HEAD, and failing at HEAD
   with the owner's capture detach moved before `close_session` (index
   5, `('detach_capture',)` where the sink's detach was expected). The
   same mutation passed the pin as it stood before the fix, which
   confirms the finding. These are pin lines changed after the move,
   by this round; the statement above that the move changed only the
   patch targets is about `3b3c2897` and stays true.

3. **P3: the record carried a stale link-check result.** The
   discoveries and the verification table claimed four broken links in
   the plan's review record, which `9dbadf53` had since unlinked; the
   checker reports 272 files, 0 failures.

   *Resolution*: accepted, in `3fcc8fae`. The discovery is removed and
   the verification row records the zero-failure run.

After the fixes: `tests/unit/test_recording_order.py` and
`tests/unit/test_recording.py` 23 passed, `tests/census` 66 passed,
`python3 scripts/check_doc_links.py .` 0 failures. The full lanes were
not rerun for a test-only and a doc-only change; CI runs them on the
pull request.

## M2: the recording's close always reaches its end

**Attribution:** anthropic/claude-opus-5-5, thinking high; Claude Code 2.1.281; 2026-09-24.

The owner's `close` gives each of its five steps its own guard: the
sink's detachment and the row's close; the capture's detachment and
close; the capture store's handoff; the transcript export's; the
LLM-input export's. A step that raises an `Exception` is reported as
`"session %s: %s did not stop cleanly"` through `events.logger`, with
the session id and the step's fixed name and nothing from the
exception, and the next step runs. The session did not change: its
`finally` already called `close` and then re-raised a held
cancellation, and `close` no longer raises one of its steps' failures
past that re-raise. A scope addition from PR #562's review rides
along: the codec-failure warning M1 moved verbatim no longer names the
exception's class.

### The commits

| Commit | What it is |
| --- | --- |
| `1626faf7` Guard each step of a recording's close on its own | The guard and its tests in one commit, the body recording the tests' red runs against M1's owner |
| `d2011820` Stop the codec warning naming the exception's class | The scope addition from PR #562's review, with its two pins |
| `e8deb81e` Record the recording close's fix for operators | The changelog fragment and the owner's docstrings |
| Record M2 of the recording owner | This section and the tick |

### What landed

| Piece | Where |
| --- | --- |
| The guard | `device/recording.py`: `_stopping(step)`, a context manager around each step. `except Exception:` binds nothing; the report is one `logger.warning` inside `contextlib.suppress(Exception)`, its comment citing `events._report` |
| The labels | `"the conversation record"`, `"the capture"`, `"the capture upload"`, `"the transcript export"`, `"the LLM-input export"`, each written once, at its step |
| The state | `_close_record` releases the sink in a `finally` around its detachment; the capture's detach and close moved into `_close_capture`, which releases the codecs in a `finally` |
| The barrier | `recorded` starts as `None` and is assigned inside the row's guard, so a row whose close raised hands the transcript export `None` |
| The codec warning | `"session %s: recording could not start"`, the session id alone; the `except` arm no longer binds the exception |
| The docstrings | the module's gains a paragraph on the close always reaching its end; `close`'s says the close does not raise; `_stopping`'s says why nothing of the exception is rendered, why nothing is latched, and why only `Exception` |
| The fragment | `changelog.d/483-recording-close.md`: `### Fixed` for the close, `### Security` for the codec warning |

### The tests

In `tests/unit/test_recording.py`, through the owner's doubles:

- `test_a_close_step_that_raises_is_reported_and_every_later_step_still_runs`,
  parametrized over six failure points. The planted exception's class
  is `type(CLASS_SENTINEL, (Exception,), {})` with a credential-shaped
  name, and its message carries a second sentinel. Each case asserts
  the whole close log (every later step ran, in order), the barrier
  (`None` for the row's two cases, the store's own otherwise), one
  warning with `record.name == SESSION_LOGGER`, level WARNING, exact
  `record.msg` and `record.args == (SID, step)`, no `exc_info`, neither
  sentinel in `both_formats` (the text and JSON renderings through
  `logs.py`'s own formatters, the arguments and the exception info),
  no tap or capture left attached, and a second close that finds only
  the three handoffs to make and closes the capture no second time.
- `test_a_report_that_raises_costs_no_later_step`, the same six cases
  with a logger filter on the session channel that raises on the
  owner's sentence; it asserts the filter was reached, once, before
  asserting the close log.
- `test_what_is_not_an_exception_still_propagates`: a `BaseException`
  subclass planted in the capture store's handoff leaves `close`, and
  the handoffs behind it are not made.
- `test_codecs_that_will_not_open_release_the_capture_and_say_nothing_of_why`,
  renamed from `..._say_so_by_class`: the codec failure raises the same
  planted class, and the warning's message is exact, its arguments the
  session id alone, both sentinels absent.

In `tests/unit/test_recording_order.py`, through a served session:
`test_a_failing_handoff_skips_no_later_one_and_loses_no_held_cancellation`,
parametrized over a working and a broken session channel. The
runtime's close raises `CancelledError` (the `_cleanly` hold) and the
capture store's handoff raises; the task ends cancelled, the close log
is the whole of M1's close sequence, the transcript export is handed
the store's barrier, and the warning names the capture upload (or,
with the broken channel, the filter was reached once and nothing was
logged).

In `tests/unit/test_capture_session.py`, the session-level codec pin:
its `CodecUnavailable` is now built with `type()` and a
credential-shaped name, and it asserts the new message, the session id
as the only argument, and neither sentinel in the renderings or the
process's output.

### The red runs

| Tests | Against | Result |
| --- | --- | --- |
| `test_recording.py` | M1's owner, `4926a5f6` | 12 failed, 15 passed: the six step cases and the six broken-filter cases; the `BaseException` case passed, since M1 lets everything through |
| `test_recording_order.py` | M1's owner, `4926a5f6` | 2 failed, 9 passed: the task ended with the planted exception, not cancelled |
| `test_recording.py`, `test_capture_session.py` | the guard commit's owner | 2 failed, 39 passed: both codec cases |

### The falsification runs

One run each, every mutation applied to a copy of `recording.py`,
restored by copy and touched after, and the file's hash compared with
the backup's once the set was done. Tests run:
`test_recording.py` and the session-level test.

Run twice: once at the guard commit before the rebase onto M1's review
fixes, and again on the final tree after it, since the rebase changed
the session-level test's expected close sequence (M1's `fee7de09` added
the capture's detach to it). Every mutation failed both times, none
survived; the counts below are the final tree's.

| Mutation | Result |
| --- | --- |
| the row's guard removed | 4 failed: both row cases, in both the step and the broken-filter tests |
| the capture's guard removed | 2 failed: the capture case in both |
| the capture upload's guard removed | 4 failed: its case in both, and both session-level cases |
| the transcript export's guard removed | 2 failed: its case in both |
| the LLM-input export's guard removed | 2 failed: its case in both |
| the class name in the message | 14 failed |
| the class name as an extra field | 6 failed: every step case, on the sentinel check alone, since the message and arguments are unchanged |
| `str(exc)` in the message | 14 failed |
| `str(exc)` as an extra field | 6 failed, on the sentinel check alone |
| the traceback attached (`exc_info=True`) | 6 failed |
| the report's suppression removed | 7 failed: the six broken-filter cases and the session-level broken-channel case |
| re-raising after the report | 14 failed, both session-level cases among them |
| the first failure latched and raised after the last step | 14 failed, both session-level cases among them |
| `except BaseException` | 1 failed: the `BaseException` case |
| the report through `logging.getLogger(__name__)` | 13 failed |
| the report at INFO | 12 failed |
| the codecs released only after a clean close | 1 failed: the capture case |
| the sink released only after a clean detach | 1 failed: the sink's detachment case |

On the final tree, `catching BaseException` first matched two lines,
since the codec arm now spells its `except` the same way, and the
runner's uniqueness check refused it rather than mutating either; it
was rerun against the close's own line, with the result above.

For the codec warning, against `test_recording.py`'s and
`test_capture_session.py`'s codec cases:

| Mutation | Result |
| --- | --- |
| the class name back in the message | both fail |
| the class name as an extra field | both fail, on the sentinel check alone |
| `str(exc)` as an extra field | both fail, on the sentinel check alone |
| the traceback attached | both fail |

### The scope addition from PR #562's review

Finding 1 of M1's review round (P1, above) was deferred here by the
orchestrator: the codec-failure warning rendered `type(exc).__name__`,
which `type(...)` lets carry a far side's bytes, the same leak round 2
of the plan review found in M2's own warning. It landed as its own
commit, `d2011820`, with the two pins that asserted the old message and
arguments changed to the new ones and a dynamically named
credential-shaped exception planted in both. The changelog fragment
records it under `### Security`, since what changed is what a retained
log line can carry.

### Deviations from the plan

- **The tests and the guard are one commit, not two.** The plan lists
  "Tests first, watched failing" and "The guard" as commits 1 and 2;
  a tests-only commit would be red on its own, and each commit here is
  green. The tests were written and run against M1's owner before the
  guard existed, and the commit body records those runs; the table
  above repeats them.
- **Six failure cases, not five.** The row's step can fail at either
  of its two calls, and the case where the sink's detachment raises is
  the only one that proves the sink is released in the `finally` (the
  row's close raising happens after the release either way); the
  mutation that drops that `finally` fails that case and no other.
- **The broken-filter case is parametrized over the same six** rather
  than being one case, and a `BaseException` case was added, since
  "only `Exception`" was a stated rule with no test holding it.
- **"Latching" was run as the owner keeping its first failure and
  raising it after the last step.** The owner has no access to the
  session's close-reason latch, so that is the one latch it could grow;
  it fails the session-level test, as re-raising does.
- **The session-level test sits in `test_recording_order.py`**, whose
  module docstring calls its contents characterization, under a
  section comment saying this one is not. Its doubles are that file's,
  and `tests/unit/test_support_boundaries.py` refuses an import from one
  test module into another. For the same reason the raising filter is
  defined in both files, as `test_event_typed_emit.py` defines its own
  broken handler.
- **A second changelog heading.** The plan's fragment is `### Fixed`
  only; the scope addition adds `### Security`.

Otherwise none: the five labels, the sentence, the suppression and its
comment, the release in a `finally`, the barrier degrading to `None`,
no latch, `Exception` only, and the session left unchanged are the
plan's.

### Discoveries

- **The session needed no change**, as the plan predicted:
  `git diff d2b0d879 HEAD -- vinga-server/src/vinga_server/device/session.py`
  is empty.
- **Other retained lines still render an exception's class name.**
  Beside the session's `_cleanly`, which the plan's round 2 already
  records as a follow-up candidate, `capture.py`'s `_disable` (the PR
  #153 review's "class name and never the exception") and
  `device/bindings.py` (its module docstring and line 485) do too.
  Whether any of those can meet an exception built by a far side was
  not assessed here; they are recorded so the follow-up can weigh all
  of them together.

### The reach-in census

No delta: `git diff d2b0d879 HEAD -- vinga-server/tests/census` is
empty. The new tests read the doubles' public attributes, and the
session-level test reaches the session only through `handshaken`,
`monkeypatch.setattr` on its runtime's `close`, and the doubles.

### #489's bookkeeping

Of the eight files, M2 touches only `test_capture_session.py`, and the
plan's count there is 1 at `d2b0d879` and 1 at `e8deb81e`: the codec
pin's edit names no storage.

### Verification

From `vinga-server/`, on agentpi. The lanes ran at `e8deb81e`, whose
code is this commit's: what this commit adds is the section and the
tick.

| Where | What ran | Result |
| --- | --- | --- |
| before the guard | `test_recording.py`; `test_recording_order.py`, against M1's owner | 12 failed, 15 passed; 2 failed, 9 passed (the red runs above) |
| the guard commit | `test_recording.py`, `test_recording_order.py`; `uv run ruff check .`; `uv run mypy` | 38 passed; clean; no issues in 5 source files |
| the guard commit | the two recording suites, `test_capture_session.py`, `test_conversations_session.py`, `test_session_device.py`, `test_event_baseline.py`, `test_transcript_export.py`, `-n auto` | 133 passed |
| the guard commit | the census lane | 66 passed |
| the codec commit | `test_recording.py`, `test_capture_session.py` against the guard commit's owner, then its own | 2 failed, 39 passed; 41 passed |
| the codec commit | `uv run ruff check .`; the census lane | clean; 66 passed |
| after the rebase onto `d2b0d879` | the two recording suites, `test_capture_session.py`, `test_conversations_session.py`, `-n 4` | 75 passed |
| the fragment commit | `python3 scripts/fold_changelog.py check .`; `uv run ruff check .` | 1 fragment, 0 failures; clean |
| `e8deb81e` | unit lane, `-n auto --dist loadfile` | 7592 passed, 19 skipped in 852.81s |
| `e8deb81e` | integration lane, `-n auto --dist loadfile` | 347 passed in 213.48s |
| the final tree | both mutation sets | 22 mutations, 22 failing runs, none survived |
| this commit | `uv run pytest tests/census -q`; `uv run ruff check .`; `python3 scripts/check_doc_links.py .` | 66 passed; clean; 272 files, 0 failures |

The unit lane's 7592 is M1's 7577 and the fifteen new tests: six step
cases, six broken-filter cases and the `BaseException` case in the
owner's file, and the two session-level cases.

Not run here: the image build, the smoke conversation, the compose
boot, and the drift checks the integration job runs. No event, field,
configuration key or command changed, and the one log sentence that
changed (the codec warning's) is in no generated reference, so none of
them should move; the pull request records what CI says.

### PR review round, PR #563

Automated external review of this PR's diff (origin/main...98ae6c88).
Reviewed 2026-09-24 by openai/gpt-5.6-sol, thinking high via codex CLI 0.156.1, read-only sandbox, runtime 5m26s, at commit 98ae6c88.
Verdict as received: **mergeable after the listed fix**. One finding.

1. **P1: the class-free warnings could still leak the caught exception
   through implicit chaining.** Both the codec arm and `_stopping` made
   their cleanup and their report inside the `except` suite, and a
   caught exception is the implicit `__context__` of anything raised
   there, bound or not. A raising filter on the codec warning left
   `open` with the codec's exception chained beneath it, since that
   report was not suppressed at all; and for the close warnings a
   failing formatter is caught by `StreamHandler.handleError`, which
   prints the chained traceback to stderr before `contextlib.suppress`
   can act. The tests exercised only a logger-level filter, which
   raises before any formatting, and the codec tests no failing
   reporter at all. The reviewer asked for the failure to be recorded
   as a boolean, the suite left, and the cleanup and the warning made
   after it, the codec report suppressed too, with a failing
   formatter test holding the sentinels out of stderr and out of any
   exception chain.

   *Resolution*: accepted, in `3f85ea39`. One thing the fix could not
   be is a boolean inside `_stopping`: a with-statement runs `__exit__`
   while the exception it is handed is still being handled, so a probe
   showed `sys.exception()` still holding the planted exception after
   the generator's own `except` suite had ended. The guard is now a
   function, `_step(step, work)`, whose `except` suite does nothing and
   whose report comes after it, through `_report`, one
   `logger.warning` under `contextlib.suppress`. The close hands each
   step to it (`functools.partial` for the handoffs). The codec arm
   notes its failure in a boolean, leaves the suite, releases the
   capture as a step of its own (a capture whose close raises is then
   reported as "the capture" and the row still opens) and reports
   under the same suppression. The "What landed" table above describes
   `_stopping` as M2 first landed it; `_step` and `_report` replace it.

   Tests added to `test_recording.py`: a `BrokenFormatter` on a real
   `logging.StreamHandler` writing to a `StringIO`, with
   `logging.raiseExceptions` on, for the six close failure points and
   for the codec failure; the broken filter extended to the codec
   warning; a capture whose close raises after a codec failure. Each
   broken filter and formatter records `sys.exception()` at the
   instant the report reaches it, and the tests assert it is None,
   which is the chain the finding describes, observed directly; the
   formatter cases also assert that `handleError` did report (`---
   Logging error ---` on stderr, so the driver reached the condition)
   and that neither sentinel reached stderr, stdout or the handler's
   stream. Later close steps still run; the row still opens.

   Red against 98ae6c88: 15 failed, 21 passed. With the
   `sys.exception()` assertions removed for one run, the seven
   formatter cases still failed, on stderr alone: both sentinels were
   printed there.

   Falsified one run each on `3f85ea39`, restored by copy and touched,
   the file byte-identical to its backup afterwards; none survived:

   | Mutation | Result |
   | --- | --- |
   | the close's report back inside the `except` suite | 12 failed: the six broken-filter and six formatter cases |
   | the codec's release and report back inside the `except` suite | 2 failed: the codec filter and formatter cases |
   | the codec's report unsuppressed | 1 failed: the codec filter case |
   | the codec's release unguarded | 1 failed: the release case |
   | `_report`'s suppression removed | 8 failed, the session-level broken-channel case among them |
   | each close step's guard removed, in order | 6, 3, 5, 3 and 3 failed |
   | `except BaseException` in `_step` | 1 failed |

   The same pattern elsewhere in `device/recording.py`: none left. An
   untruncated `grep -n -A4 '^ *except'` finds two `except` suites
   (the codec arm's and `_step`'s), and each only notes the failure.
   The two `finally` clauses, in `_close_record` and `_close_capture`,
   only assign `None` and cannot raise. Outside this module the
   pattern is not assessed here: the session's `_cleanly` reports from
   inside its `except` suite, and its `finally` runs its reports while
   an exception that is ending the session is being handled, so a
   failing handler there would print that exception's chain. That
   belongs with the class-name follow-up already recorded above.

   After the fix: `test_recording.py`, `test_recording_order.py` and
   `test_capture_session.py` 61 passed; `uv run ruff check .` clean;
   `uv run mypy` no issues in 5 source files; `tests/census` 66 passed;
   `python3 scripts/check_doc_links.py .` 272 files, 0 failures; the unit lane,
   `-n auto --dist loadfile`, 7601 passed, 19 skipped in 878.16s
   (M2's 7592 and the nine new tests). The integration lane was not rerun,
   as the orchestrator directed. That leaves one thing unverified
   locally: the fix reshapes the close's ordinary path too (every step
   now goes through `_step`), and while the unit lane's session suites
   drive that path, the integration lane's sessions over the real
   stores have not run on it; CI runs them on the pull request.

   CI then ran the integration lane on the fix: green at `b8a21be9`
   (unit 8m41s, integration 3m45s, docs and all four image variants).

### PR review round 2, PR #563

Reviewed 2026-09-24 by openai/gpt-5.6-terra, thinking high via codex CLI 0.156.1, read-only sandbox, runtime 1m49s, at commit b8a21be9.

A re-review of round 1's fix. Verdict as received: not mergeable.

1. **P1: a broken formatter still prints a library traceback to
   stderr.** `logging.StreamHandler.emit` catches a formatter's
   failure itself and calls `handleError`, which prints
   `--- Logging error ---` and a traceback before `_report`'s
   suppression can act. The new tests require that line. The
   reviewer asked for a non-printing failure policy for these
   reports, and for tests requiring empty stdout and stderr.

   *Resolution* (by the orchestrator, anthropic/claude-opus-5-5,
   thinking high): rejected on the PR, with reasons
   (https://github.com/rafacm/vinga/pull/563#issuecomment-5812659423).
   Two of them. First, what reaches stderr carries nothing untrusted:
   it is the formatter's own exception and a fixed record (the
   session id and a step label). No recording exception is chained
   beneath it, and the tests prove neither sentinel reaches stderr.
   The `--- Logging error ---` assertion proves the failure path ran;
   it does not endorse the output. Second, whether `handleError`
   prints is decided by `logging.raiseExceptions`, a process-wide
   policy. Nothing in `vinga-server/src` sets it, and every channel
   behaves the same way. Rafael chose to merge and decide that policy
   once for every channel, in `logs.py`: filed as #564. No code
   change. #563 merged on green at 13:06 CEST, closing #483.
