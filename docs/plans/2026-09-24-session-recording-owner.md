# Give a session's recording one owner

Plan for [#483](https://github.com/rafacm/vinga/issues/483), as Step 0
re-verified it at `219c8ba2` (issue comment 5810452145). Its companion
is `docs/plans/2026-09-24-session-recording-owner-implementation.md`,
one section per milestone, appended in the same change that ticks the
milestone.

**Local baseline:** not applicable. No conversational capability
changes: what is recorded, when, and where it goes stay as they are,
and what moves is which module holds the ordering.

**Cheapest alternative:** moving only the hazard the issue names.
`CaptureAudio` gains an `open` that takes the capture store, the events
object and the session's facts, attaches the decision track, builds
the codecs, releases the capture on a codec failure and answers `None`,
which moves `_start_capture` (`device/session.py` lines 849-892 at
`219c8ba2`, 44 lines) into `capture_audio.py` and deletes the comment
the session must keep true. It leaves the rest of the recording where
it is: six constructor fields (lines 217-258), `_start_recording` and
`_stop_recording` (lines 894-939 and 962-980, 65 lines), and the close
tail's ordering (lines 705-742), which today is held by comments in
the session: the store row closed after `session_closed`, its barrier
handed to the transcript export, the capture detached before it is
closed, then three post-close handoffs in narrow-to-wide order. What
the owner buys over that is the collapse of those six fields into one,
that ordering as one module's implementation rather than the
session's comments, and one place for the next recording surface to
land. That last is measured rather than asserted: the two surfaces
added since the issue was filed (the transcript export, #495, and the
LLM-input export, #502) each added a constructor argument, a `ws.py`
argument and a close-tail stanza to the session. The price is one
module of roughly 200 lines, moved rather than written, and its unit
tests, inside the one PR the cheaper change would also need.

**Attribution:** anthropic/claude-opus-5-5, thinking high; Claude Code
2.1.281; 2026-09-24.

## Goal

One object owns everything a device session leaves behind it: the
capture (its decision-track tap, the codecs `CaptureAudio` holds, and
the release when those codecs will not open), the conversation store's
session row and the sink that feeds it, the two audio feeds, and the
close, which ends the row, finishes the capture, and makes the three
post-close handoffs in their order. The session keeps the socket, the
protocol, the manifest's content and the moment each step happens; it
hands the owner the facts it needs at `open` and at `close`, and feeds
it frames.

Nothing a person running vinga can observe changes: no event, field,
log line (the owner logs through the same `events.logger`, so the
`logger` field of every JSON record is unchanged), stored row, capture
file, or upload. The milestone proves that with pins committed before
the move.

## The issue's decisions, restated

- **One recording lifecycle module** owning attachment, opening and
  closing. The session keeps the socket and protocol responsibilities
  and hands recording a seam instead of interleaving its stages with
  its own.
- **The half-constructed-capture cleanup ordering** becomes that
  module's implementation detail rather than a comment the session
  must keep true.
- **The session learns one interface** (open, attach, close); the
  module owns codec construction, the decision-track tap and the
  stranded-capture hazard.

Step 0 confirmed all three and widened what "closing" covers: since
the issue was filed the close tail gained the transcript export's and
the LLM-input export's handoffs, so the owner's close covers all three
post-close surfaces. It also read "telemetry subscriptions" in the
problem statement against the code: the live stream and the trace
exporter are observers attached at construction for the whole
connection and detached by `detach_observers`, not part of a
recording's lifecycle, and the issue's direction does not name them.
They stay where they are.

## Resolutions and design decisions

### Where the owner lives, and its name

`vinga_server/device/recording.py`, class `Recording`: one device
session's recording, in the issue's own word. In `device/` beside
`capture_audio.py`, `pacing.py` and `watchdog.py`, the session's other
carried collaborators, because the session is its only caller and
every module it imports (`capture`, `conversations`, `events`,
`capture_audio`) is one `device/session.py` already imports, so no
import direction changes. `llm_input_export` and `transcript_export`
stay `TYPE_CHECKING` imports, because the owner only holds them. The
reason the session's comment gives for that (lines 122-125: each
imports `telemetry.py`, "which nothing here does") is false at
`219c8ba2` and was when written: `device/session.py` has imported
`vinga_server.telemetry` at runtime since `c5cbe42d` (2026-09-10), two
days before the comment. The comment leaves with the fields, and the
owner's states the true reason rather than inheriting that one.

The name sits beside `events.SessionRecording`, a protocol that means
something narrower: the capture as the events object sees it (what
`attach_capture` takes and `vad` writes to). The owner's docstring says
so in one sentence and names the protocol, so a reader finding both
knows the protocol is one of the things the owner holds. Renaming the
protocol is out of scope: it is the decision-track hooks' vocabulary,
which the 2026-08-10 hardware-edge ADR places on `SessionEvents`, and
this plan leaves them there.

`CaptureAudio` stays its own module. It passes the deletion test on
its own terms (it owns three codec objects and the rule that a frame
the capture cannot read is not a reason to stop), and folding it into
the owner would put codec knowledge beside store knowledge, two
reasons to change in one file. The owner constructs it.

### The interface

Named here so the review can price it; the implementer may rename
within the plan's intent and records any rename.

```python
RecordingFactory = Callable[[str, SessionEvents], "Recording"]

def recordings(
    captures: CaptureStore | None = None,
    conversations: ConversationStore | None = None,
    transcripts: "TranscriptExport | None" = None,
    llm_input: "LlmInputExport | None" = None,
) -> RecordingFactory: ...   # closes over the four, answers a builder

class Recording:
    def __init__(
        self,
        session_id: str,
        events: SessionEvents,
        *,
        captures: CaptureStore | None,
        conversations: ConversationStore | None,
        transcripts: "TranscriptExport | None",
        llm_input: "LlmInputExport | None",
        reply_sample_rate: int,
    ) -> None: ...
    def open(
        self,
        opened_at: float,
        manifest: dict[str, Any],
        protocol_version: int,
        renames: Callable[[], Sequence[tuple[str, str]]] | None,
        device_name: str | None,
    ) -> None: ...
    def microphone(self, data: bytes) -> None: ...
    def reply(self, packet: bytes) -> None: ...
    def close(self, duration_s: float, reason: str) -> None: ...
```

The issue's "open, attach, close" maps onto this as: `open` opens the
capture and the row and attaches both taps, since no caller has a
reason to do one without the other; `close` detaches and closes. The
two feeds are the frames the session hands over, which the issue's
list does not name and its "hands recording a seam" does.

- **`open`** is today's `_start_capture` then `_start_recording`, in
  that order, so the capture's tap attaches before the store's and the
  dispatch order stays capture first, store second, log last. The
  codec-failure release (detach, then close, then the warning by class
  name) is inside it, unchanged, with its comment. `renames` is the
  thunk the session builds today from its pinned generation, passed as
  built, so the window the comment at lines 913-926 describes is still
  closed at the instant the store registers the session; the thunk's
  construction and its comment stay in the session, which owns the
  generation. `device_name` is the session's `_device_name()`, which
  stays in the session because `session_open` reads it too.
- **`microphone` and `reply`** are no-ops when nothing is recording,
  so the session's two feed sites lose their `is not None` checks and
  keep their positions: the microphone feed before every guard in
  `_handle_audio`, the reply feed after the wire send in `deliver`.
  Those positions are the session's decision (what "every frame that
  arrived" and "what the device was sent" mean at the socket), and the
  comments saying so stay at the sites.
- **`close`** is today's `_stop_recording`, the capture's detach and
  close, and the three handoffs, in today's order: the store row closed
  with the duration and reason the session passes, the barrier it
  answers held; the capture's tap detached, then the capture closed;
  then `captures.session_closed`, `transcripts.session_closed` with
  that barrier, and `llm_input.session_closed`. The handoffs do not
  depend on how far `open` got, as today: a finally reached after an
  `open` that raised part way still hands the session to all three.
  `close` answers nothing: the barrier's one consumer is the transcript
  export, which is now inside the owner.
- **The session's side of the close** stays the session's: flushing
  the dropped-frame aggregate while the capture's tap is still
  attached, emitting `session_closed`, then `close` with
  `self._open_duration_s()` and `self._closed_reason()` read at the
  call, which is the instant `_stop_recording` reads them today.
- **No guard is added.** Today none of the close tail's recording steps
  runs under `_cleanly`, and the owner keeps that exactly; wrapping
  them is a behavior change (a step that raises today propagates out
  of the `finally`) and belongs to its own issue if anyone wants it.
  Every one of those callees is written not to raise
  (`SessionCapture.close` suppresses, the store's close is a queue put
  that answers a settled refusal when stopped), which is why the
  question has never been forced.

### Who constructs it

**The connection handler, through a factory, and the session learns
one collaborator.** `device/recording.py` exports `recordings(...)`,
which closes over the four shared collaborators (the capture store,
the conversation store, the transcript export, the LLM-input export)
and answers a `RecordingFactory`: a callable taking the session id and
the events object and building that session's `Recording`.
`DeviceSession` takes one argument, `recordings: RecordingFactory |
None = None`, in place of `captures`, `conversations`, `transcripts`
and `llm_input`, calls it once in `__init__` with the id it minted and
the events object it built, and holds the answer as
`self._recording`, which is never None. `None` is compared `is not
None` and means `recordings()` with nothing in it, an owner whose
`open`, feeds and `close` do nothing, which is what every caller that
passes none of the four gets today.

`ws.py` builds the factory from the `Composition` fields it already
passes one by one, `recordings(comp.capture, comp.conversations,
comp.transcripts, comp.llm_input)`, at the one production site.
`Composition` does not change: its module docstring says it holds the
declaration and nothing else, and the four fields have readers other
than the session (the lifespan's shutdown, the API), so the factory is
derived from them at the call rather than stored beside them as a
second structure that would have to agree. Nothing else in `ws.py`
changes.

The price, measured at `219c8ba2`: `DeviceSession(` is constructed at
9 sites, `ws.py`, `tests/support/sessions.py` twice,
`tests/tools/event_baseline.py`, and one each in
`test_capture_session.py`, `test_conversations_session.py`,
`test_events_live_wiring.py`, `test_generation_binding.py` and
`test_session_device.py`. Five of them pass `captures` positionally
(4th) or `conversations`, `transcripts` or `llm_input` by keyword;
each becomes `recordings=recordings(...)` with the same objects. The
support helpers keep their own keyword arguments and build the factory
inside, so the tests that call them do not change. The milestone
recounts the sites untruncated on its own base and records the number.

What this buys over keeping the four arguments on the session, which
the plan first proposed: the growth point leaves the session
entirely. On the first shape a fifth surface still added a
`DeviceSession` argument and a `ws.py` argument, two of the three
edits #495 and #502 each made; on this one it adds a parameter to
`recordings` and a line in the owner, and the session does not
change. That is the depth the issue settled on (the session learns
one interface), and a constructor's parameters are interface in the
design guide's sense.

### The white-box reads of the old fields

Three test lines read the fields this plan deletes
(`test_capture_session.py` `_capture_audio` once,
`test_conversations_session.py` `_capture_audio` once and `_record`
twice, per the reach-in manifest at `219c8ba2`). Each sits beside the
behavioral assertions it backs up (no tap left attached, the capture's
manifest marked complete, the session row closed), and each says in
its own comment that it is white-box. They are deleted rather than
redirected at the owner: a redirected read would be a reach-in into a
private field of a module this plan creates, which is the review flag
the design guide names. What they protected is held by the owner's
unit tests below, which assert through doubles that the capture is
closed once and the sink detached, and by the behavioral assertions
that stay beside each deleted line. The reach-in manifest therefore
loses those three lines, and the milestone states that delta.

Two tests patch a name on `vinga_server.device.session`:
`test_capture_session.py` line 417 replaces `CaptureAudio` to make the
codecs fail to open, and the `spy` fixture in
`test_conversations_session.py` line 130 replaces `SessionSink`. A name
is patched where it is looked up, and both lookups move into the
owner, so both targets become the owner's module. Those are one-line
changes to pins, stated here so the review reads them as the move and
not as weakened tests.

### One milestone, cut into reviewable commits

The move cannot be split across PRs without an intermediate `main`
where half the lifecycle is in the owner and half in the session, two
homes for one ordering, which is the state the issue exists to end. So
one milestone, with the cut inside it as commits, each green on its
own.

## Module layout

- New: `src/vinga_server/device/recording.py` (`Recording`).
- Changed: `device/session.py` (six fields become one; `_start_capture`,
  `_start_recording` and `_stop_recording` deleted; the close tail's
  recording lines become one `close` call; the two feed sites; the
  module docstring's paragraph on what it owns without carrying),
  `device/capture_audio.py` (its class docstring's sentence about the
  session holding one field for recording's audio now names the owner),
  `ws.py` (the one production construction), and every test
  construction site named under "Who constructs it".
- Tests: new `tests/unit/test_recording.py`; the pin changes named
  under "Tests".

## Tests

### What is pinned today, and what is not

An inventory of the existing suites at `219c8ba2`, fact by fact, taken
before this section was written. What is pinned is mostly end state.
The manifest is marked complete, no tap is left attached, and the row
is closed with the reason for the client and error paths
(`test_conversations_session.py` lines 137, 755 and 815,
`test_capture_session.py` lines 217 and 391). `session_open` and
`session_closed` are the first and last rows of the store record
(`test_conversations_session.py` line 175). The microphone is recorded
through a `barge_in_off` drop (`test_capture_session.py` line 144).
Each absent collaborator records nothing (`test_capture_session.py`
lines 84 and 94, `tests/integration/test_conversations.py` line 167).

**Not pinned at the session level**, and so exactly what a move could
break silently:

1. the capture's tap attached before the store's sink (nothing reads
   the order of `attached_taps`);
2. `session_closed` as the last line of the capture's decision track;
3. the capture's tap detached before the capture is closed, in the
   close tail and in the codec-failure release;
4. `captures.session_closed` called after the capture closes (only
   incidentally, through the integration upload test, since the
   upload is staged by the close);
5. `transcripts.session_closed` receiving the very `Acknowledgement`
   `close_session` returned: no test double defines `session_closed`,
   and the real export discards the argument;
6. `llm_input.session_closed` being called at all through a session
   (the integration test's docstring claims it, and it would pass
   with the call deleted);
7. the three handoffs' relative order;
8. the row's close reason for anything but `client` and `error`;
9. a `not_listening` drop still reaching the capture;
10. the reply feed following the wire send;
11. a session refused before its hello opening no capture and no row
    and making none of the three handoffs, for the bad Device-Id,
    no-agent and no-hello paths (only a hello send that disconnects
    is pinned, line 722);
12. the codec-failure warning's exact `record.msg` and typed
    `record.args` (line 456 matches a substring).

### Pins, committed first, green against today's code

Session-level, through the tests' existing support
(`tests/support/sessions.py`) and doubles that record into one shared
call log, so an order is asserted as a list rather than inferred.
Each covers the numbered gaps it names:

- **The open's order** (1): after the hello, the capture's
  `CaptureTap` precedes the `SessionSink` in `attached_taps`,
  comparing positions by type, with any observer taps ignored.
- **The close's order** (2, 3, 4, 5, 6, 7): a capture store, a
  conversation store, a transcript export and an LLM-input export,
  each wrapping or standing in for the real one and appending to one
  log, driven through a served session that ends by the device
  closing. The log must read exactly: store `close_session`; the
  capture's tap detached (the capture double's `close` records
  whether `attached_capture(session)` is None at that instant); the
  capture closed; `captures.session_closed`;
  `transcripts.session_closed`, whose second argument `is` the
  object `close_session` returned; `llm_input.session_closed`. And
  the capture's `.jsonl` ends with `session_closed`.
- **The reason and duration reach the row** (8): the same doubles,
  the session ended by its duration cap, and `close_session` receives
  `reason == "limit"` and a duration no smaller than the
  `session_closed` event's, which is the earlier of the two readings.
  One non-default path is enough: the owner is handed the latched
  token and has no branch per reason.
- **A `not_listening` drop is recorded** (9): mic frames sent before
  any `listen start` appear on the capture's microphone channel, the
  counterpart of the line 144 test's `barge_in_off` case.
- **The reply is recorded after it is sent** (10): a socket whose
  sends append to the shared log and a `CaptureAudio` stand-in whose
  `reply` does the same; every packet appears on the wire before it
  appears in the capture, and a packet whose send raises is not
  recorded.
- **Refusals record nothing** (11): parametrized over the bad
  Device-Id, the no-agent and the no-hello paths, with a capture
  store and a conversation store configured and both export doubles
  attached: no capture files, no session row, and an empty call log.
- **The codec warning, exactly** (12): the existing codec test gains
  assertions on the warning's `record.msg` and typed `record.args`
  (the session id, then the class name), beside its substring and
  sentinel checks, which stay.

Patch targets are the one permitted change to a pin across the move,
because a name is patched where it is looked up and the lookup moves:
`test_capture_session.py` line 417 (`CaptureAudio`) and
`test_conversations_session.py` line 130 (the `spy` fixture's
`SessionSink`) retarget from `vinga_server.device.session` to the
owner's module, as does any new pin's `CaptureAudio` stand-in. Every
other pin line is byte-unchanged across commit 3.

Gaps deliberately left: the renames thunk's anchor (only incidentally
pinned by `test_agent_rename_in_flight.py` lines 706 and 747) is
built in the session and handed to the owner as built, so the move
cannot change it; the owner's unit test pins that the store receives
the very callable `open` was given. And the close on the idle, drain
and WebSocketDisconnect paths: those differ only in what the session
latches before its `finally`, which the close-reason tests pin, and
the owner's `close` has no branch on the path.

### The owner's own tests

`tests/unit/test_recording.py`, through the owner's interface and
doubles only, no database and no files:

- `open` attaches the capture before the sink (`events.taps()` order);
  hands the store the manifest, the opened-at reading, the device
  name, and the renames callable by identity; and builds the codecs
  with the protocol version and reply rate it was given.
- A codec failure at `open`: the capture's tap is detached before the
  capture is closed, the warning's `record.msg` and `record.args` are
  today's, a credential-shaped sentinel in the exception's message is
  absent from both and from the rendered line, the store's row still
  opens, later feeds are no-ops, and `close` does not close the
  capture a second time and still makes all three handoffs.
- `close` runs the store close, the detach, the capture close and the
  three handoffs in that order, handing the transcript export the
  barrier by identity; with `open` never called it still makes the
  three handoffs and closes nothing else; each absent collaborator is
  skipped without raising.
- The feeds reach `CaptureAudio` while a capture is open and do
  nothing before `open`, after `close`, or with no capture store.
- **Falsification**, one run each since every rule here is
  straight-line: the tests are watched failing against a mutation of
  each rule they name (the sink attached before the capture; the
  handoffs reordered; `None` handed to the transcript export; the
  capture closed before its tap is detached; the release dropped from
  the codec-failure arm; a feed after `close` reaching the codecs).
  The commit body says so, and a mutation that survives is reported as
  a finding about the test.

### What must not move

- `tests/unit/test_event_baseline.py` keys emit sites by module and
  function. The owner emits no event (its one output is the
  codec-failure warning, a log call through `events.logger`, not an
  emission; the capture store's own events are emitted inside
  `capture.py`), so no key moves; the lane confirms it.
- The reach-in manifest loses exactly the three lines named under
  "The white-box reads of the old fields" and gains none. Regenerated
  with `uv run python -m tests.census.test_reach_ins`, never by hand,
  and any other line added or removed is a deviation the
  implementation doc explains; a new underscore read in a pin is a
  review flag rather than a manifest update. The command-spellings
  manifest is checked the same way and is expected not to move.

## #489's bookkeeping

The eight files the #489 comment (on this issue, 2026-09-20) assigns to
this issue's territory, all under `vinga-server/tests/unit/`:
`test_capture_session.py`, `test_capture_upload.py`,
`test_session_record.py`, `test_session_device.py`,
`test_session_device_name.py`, `test_boundary.py`,
`test_boundary_contract.py`, `test_session.py`.

The instrument is the one #484's plan fixed, so the two issues'
numbers are comparable, run from `vinga-server/tests/unit`:

```bash
RE='support\.stores|support import stores|clean_store|blank_database|throwaway_database|module_database|spare_database|packaged_database|ConversationStore|vinga_server\.db\b|vinga_server\.conversations\.store|\bstore_at\b'
for f in test_capture_session.py test_capture_upload.py \
         test_session_record.py test_session_device.py \
         test_session_device_name.py test_boundary.py \
         test_boundary_contract.py test_session.py; do
  printf '%s %s\n' "$(grep -cE "$RE" "$f")" "$f"
done
```

Baseline at `219c8ba2`: 1, 2, 4, 8, 3, 0, 1, 0 in that order, so **six
of the eight already name a storage helper somewhere**, the same
disagreement with the comment's "name no storage at all" that #484
recorded for its seven. As there, the milestone records two columns
per file: (a) the count above, before and after; and (b) whether
storage reaches the object under test through a parameter the test
visibly passes, judged per file with the line cited.

The prediction written down now, so it can be wrong: **neither column
moves.** A test that hands the session a conversation store today
hands it to `recordings(...)` instead, one call deeper and just as
visible, so no test gains or loses a storage parameter it can see. The move's own edits to these
files (a patch target and a white-box line in
`test_capture_session.py`) name no storage. Where a new pin lands in
one of the eight and needs a store, column (a) moves for that reason
and not the extraction's, and the implementation doc separates the
two, counting the pins' additions apart. If that
holds, it is a second seam of the three the comment named where the
extraction did not make the storage dependency more explicit, and the
implementation doc says so in those words.

## Risks and mitigations

- **An ordering changed in the move.** Every ordering fact the close
  tail and the open hold is pinned before the move (see "Tests"), by
  typed assertions against doubles that record call order, not by
  rendered text. The pins are committed green against today's code and
  are byte-unchanged after, apart from the two patch targets.
- **A reader of the old fields left behind.** The milestone closes on
  a grep, run without truncation, proving no `_capture_audio`,
  `_record`, `_captures`, `_conversations`, `_transcripts`,
  `_llm_input`, `_start_capture`, `_start_recording` or
  `_stop_recording` remains in `device/session.py` or anywhere under
  `tests/` naming a session attribute, with the count recorded.
  Deleting the fields turns any missed reader into an `AttributeError`
  the lanes catch.
- **The feed sites move relative to their guards.** The microphone
  feed must stay before every guard and the reply feed after the wire
  send. Both are pinned (see "Tests"), and the diff at each site is one
  line.
- **No-leak.** The one message the owner composes is today's warning,
  rendering the exception's class and never its words, moved
  unchanged; its existing test plants a credential-shaped sentinel in
  the exception's message and asserts it is absent, and that test is
  one of the pins. No new value reaches any surface.
- **Import cycles.** The owner imports nothing at runtime that
  `device/session.py` does not already import, and the session
  imports the owner, so no cycle is possible that does not exist
  today; the lanes import both.

## Documentation footprint

- In code: `device/session.py`'s module docstring (the paragraph
  listing what the session owns without carrying gains the owner, and
  "records the capture" becomes "hands its recording the facts it
  needs"), `capture_audio.py`'s class docstring, and the new module's
  docstring, which carries the ordering comments that leave the
  session.
- No hand-maintained page under `docs/` describes where these steps
  live: the glossary's *Capture* and *Wire-true capture* entries
  describe what is recorded, which is unchanged;
  `docs/architecture/observability-surfaces.md` describes the surfaces
  and their gates, not the module that opens them; and the one
  `device/session.py` mention in `docs/xiaozhi-notes.md` (line 383)
  is about debug logging. Stated here so the footprint is explicit
  rather than implied.
- No ADR: no recorded decision's placement changes. The 2026-08-10
  hardware-edge ADR puts the capture decision-track hooks on
  `SessionEvents`, and they stay there; the owner calls them.
- No generated reference changes, since no event, field or
  configuration key changes.
- **Changelog:** none. Nothing a person running vinga can observe
  changes.

## Milestones

- [ ] **M1: a session's recording gets one owner**. Commits in this
  order, each green on its own:
  1. Pins: the characterization tests under "Tests" that the existing
     suites do not already cover, green against today's code.
  2. `device/recording.py` and `tests/unit/test_recording.py`,
     falsified as "Tests" states. Unused by the session in this
     commit.
  3. The move, as one commit: the session constructs the owner and
     calls `open`, the feeds and `close`; the constructor takes
     `recordings` in place of the four collaborators, at every
     construction site; the six fields and three methods leave; the two patch targets move; the three white-box
     lines are deleted. The body walks the diff in that order.
  4. The docstrings in the documentation footprint; the reach-in
     manifest regenerated with the stated delta; the #489 count in the
     implementation doc.

  Design footprint: adds one module whose callers stop having to know
  that recording is a capture plus a store row plus three post-close
  surfaces, in what order they attach and close, that a codec failure
  strands a half-built capture, and which close answers the barrier
  the transcript export waits on. Deepens `device/session.py` by
  removing a responsibility rather than adding one. Adds one seam,
  `RecordingFactory`, stated as a type: what the connection handler
  hands the session so the session learns one collaborator instead of
  four.
  Changelog: none.

## Plan review round

Reviewed 2026-09-24 by openai/gpt-5.6-sol, thinking high via codex CLI 0.156.1, read-only sandbox, runtime 7m06s, at commit 5c4760a9, plan blob 78c35feb.

---

1. **P1: The session still knows four recording collaborators, contrary to the settled one-interface decision**

   **Evidence:** The plan restates that the session learns one interface at `docs/plans/2026-09-24-session-recording-owner.md:57-68`, but keeps `CaptureStore`, `ConversationStore`, `TranscriptExport`, and `LlmInputExport` in `DeviceSession.__init__` and constructs `Recording` itself (`:119-143`, `:187-207`). The design guide defines constructor types and wiring as part of an interface (`docs/architecture/design-guide.md`, “Interface and implementation”). The proposed API also has `open`, `microphone`, `reply`, and `close`, but no `attach`, despite restating the settled interface as `open, attach, close`. The “no seam changes” claim at `:519-524` further contradicts the issue’s requirement to hand recording a seam.

   **The plan should say instead:** The composition root builds a `RecordingFactory` that closes over the four shared collaborators, and `DeviceSession` receives that single abstraction. The factory creates the per-session owner from the session id and events object. Specify the exact factory and owner protocols, map the audio-feed operations explicitly to the issue’s settled interface, and update all nine construction sites. The one-time call-site cost cannot overrule a settled issue decision.

   *Resolution:* Accepted, with the factory built in `ws.py` rather than stored on `Composition`. `device/recording.py` exports `recordings(captures, conversations, transcripts, llm_input) -> RecordingFactory`, where `RecordingFactory = Callable[[str, SessionEvents], Recording]`; `DeviceSession` takes `recordings: RecordingFactory | None` in place of the four and calls it once in `__init__`. `ws.py` derives the factory from the `Composition` fields it already passes, because `composition.py` declares itself a declaration and nothing else, and a stored factory beside the four fields would be a second structure that must agree with them. The nine construction sites change, the support helpers absorb the change for their callers, and the plan now says what that buys over the first shape: a new surface no longer touches the session at all. The issue's "open, attach, close" is mapped explicitly (`open` opens and attaches, `close` detaches and closes, the feeds are the frames), and the design footprint now names the one seam added.

2. **P2: The open-order tests pin final tap order, not the opening order they claim to protect**

   **Evidence:** Current behavior is `CaptureStore.open`, capture attachment, codec construction, `ConversationStore.open_session`, then sink attachment (`device/session.py:579-581`, `:872-881`, `:927-939`). The proposed session and owner tests inspect only the eventual `events.taps()` order (`plan:306-308`, `:365-368`). An implementation that opens the conversation row first, then attaches the capture before the sink, passes every named assertion while changing failure behavior if either store or codec construction raises.

   **The plan should say instead:** Record the complete opening sequence in one shared log and assert `captures.open`, `attach_capture`, codec construction, `conversations.open_session`, then sink attachment. Add failure injections at capture opening and conversation opening to prove the same artifacts are opened and released as today. Include mutations that reorder store opening, not merely tap attachment.

3. **P2: Sink detachment before row closure is missing from both the specification and the proof**

   **Evidence:** `_stop_recording` currently detaches and clears `SessionSink` before calling `ConversationStore.close_session` (`device/session.py:974-980`). The proposed sequence starts with `close_session` and mentions only capture detachment afterward (`plan:163-172`, `:309-319`). The owner test requires the sink to be detached eventually (`:375-379`), so moving its detachment after `close_session` would pass all listed tests.

   **The plan should say instead:** Spell out the exact close sequence beginning with `events.detach(sink)`, clearing the sink, and only then calling `close_session`. Have the store double inspect `events.taps()` at the instant `close_session` runs, and add the reverse-order mutation to falsification.

4. **P2: The unguarded close-tail rationale is false and leaves later cleanup vulnerable during drains**

   **Evidence:** The plan says every close callee is written not to raise (`plan:178-185`). `CaptureStore.session_closed` calls `CaptureUpload.session_closed` (`capture.py:622-632`), which can call `_start()` and an uncaught `threading.Thread.start()` (`capture_upload.py:629-659`, `:704-719`). Transcript cleanup also reaches telemetry operations without a blanket suppression (`transcript_export.py:147-157`). Any such exception skips later handoffs and the pending cancellation re-raise at `device/session.py:727-748`, contradicting the close path’s stated “always reaches the end” contract at `:682-685`. A redeploy draining many sessions is precisely when uploader startup and simultaneous post-close handoffs occur.

   **The plan should say instead:** Give each synchronous close step its own sanitized guard, clear owned state in `finally`, and continue through every later handoff and the pending cancellation. Tests should make each step raise in turn, assert later cleanup still runs, and verify that no exception text or chained value reaches logs. If fail-fast preservation is intentionally retained, the plan must accurately document and pin which cleanup is skipped instead of claiming the calls cannot raise.

5. **P2: The compatibility-sensitive logger name is promised but not tested**

   **Evidence:** The plan promises the warning retains the same JSON `logger` field (`plan:51-55`), while its tests assert only `record.msg`, `record.args`, and sentinel absence (`:338-341`, `:369-374`). `events/__init__.py:102-114` explicitly identifies `SESSION_LOGGER` as a compatibility surface. Using `logging.getLogger(__name__)` in the new module would satisfy every proposed assertion while changing retained records from `vinga_server.session` to `vinga_server.device.recording`.

   **The plan should say instead:** The characterization and owner tests must assert `record.name == SESSION_LOGGER`, `record.levelno == logging.WARNING`, and the exact message and arguments. Keep the explicit requirement that the owner imports `events.logger`.

6. **P3: The white-box deletion count confuses four source sites with three manifest rows**

   **Evidence:** There are four current reads: `test_capture_session.py:446`, plus `test_conversations_session.py:791`, `:793`, and `:848`. The plan calls these “three test lines” and later says three white-box lines are deleted (`plan:211-224`, `:511-514`). The reach-in manifest has three distinct path/name rows because the two `_record` reads are aggregated into one row.

   **The plan should say instead:** Delete four source sites; regenerate a manifest delta of three rows: one `_capture_audio` row from each test file and the single aggregated `_record 2` row.

**Verdict: ready after the P1/P2 amendments.**
