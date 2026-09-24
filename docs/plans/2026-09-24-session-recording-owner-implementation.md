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
- **The plan's review record has four broken links.**
  `scripts/check_doc_links.py` reports four "missing target" failures
  at lines 782 and 788 of the plan: the second review round's
  `docs/plans/...md:311` and `:303` link targets, as the reviewer wrote
  them. They predate this milestone and are left as recorded; the
  documentation workflow will report them on any pull request that
  touches `docs/`.

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
| this commit | `scripts/check_doc_links.py` | 272 files, 4 failures, all the plan's pre-existing review-record links (see the discoveries) |

Not run here: the image build, the smoke conversation and the compose
boot, the tier-closure and wheel lanes beyond what the integration lane
holds. No event, field, configuration key or command changed, so none
of them should move; the pull request records what CI says.
