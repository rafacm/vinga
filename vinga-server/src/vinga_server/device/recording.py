"""One device session's recording: everything the session leaves
behind it, and the order it is opened and closed in.

A recording is four surfaces, each optional and each asked for by the
deployment: the capture (a decision track written from the session's
events and two audio channels written through `CaptureAudio`'s codecs),
the conversation store's session row and the sink that feeds it, and
the two exports a closed session is handed to. The session decides when
each step happens and knows none of this: it opens its recording after
the hello, feeds it every frame that arrived and every packet that was
sent, and closes it after `session_closed`. What this module holds is
what the session used to keep true in comments.

The open, capture first. The capture store opens, the capture attaches
to the events object, its codecs are built, and only then does the row
open and its sink attach, so the dispatch order is capture first, store
second, log last, and the row is the capture's decision track, from the
same first event. A codec that will not open is the one step here that
can fail for a reason nothing on this side chose, and it strands a half
built capture: attached, open, and not yet assigned anywhere the close
would find it. So it is released where it failed, detached before it is
closed, and the session goes on unrecorded.

The close, narrow to wide. The sink is detached before the row closes,
so nothing reaches the row after its close record is queued; the row's
close answers the store's barrier for this session. The capture's tap
is detached before the capture closes, so the last line of its track is
the session's last emission and its WAV header covers everything. Then
the three handoffs, in order: the capture store (the one signal that the
conversation is over, not merely a file), the transcript export with the
barrier, and the LLM-input export last because it is the widest. None of
them depends on how far the open got.

And the close always reaches its end. Each of its five steps (the row,
the capture, and the three handoffs) is guarded on its own, so a step
that raises is reported as that step not stopping cleanly and the steps
after it still run: the session calls this from its `finally`, and what
comes after the call there (the re-raise of a cancellation its close was
holding) must not be lost to a handoff that failed. A row whose close
raised answered no barrier, so the transcript export is handed none. The
report names the session and the step and nothing of the exception, and
is made only once the exception is no longer being handled, for the
reasons `_step` gives.

Not `events.SessionRecording`, which is narrower: that protocol is the
capture as the events object sees it (what `attach_capture` takes and
`vad` writes to), and it is one of the things this owner holds.
"""

import contextlib
from collections.abc import Callable, Sequence
from functools import partial
from typing import TYPE_CHECKING, Any

from vinga_server.capture import CaptureStore
from vinga_server.conversations import ConversationStore, SessionSink
from vinga_server.conversations.records import Acknowledgement
from vinga_server.device.capture_audio import CaptureAudio
from vinga_server.events import SessionEvents, logger

if TYPE_CHECKING:
    # Named for the annotations and nothing else: this module holds
    # each export and calls its `session_closed`, and never needs
    # either class at runtime to do that.
    from vinga_server.llm_input_export import LlmInputExport
    from vinga_server.transcript_export import TranscriptExport


class Recording:
    """Everything one device session leaves behind it, opened, fed and
    closed in one order.

    Each collaborator is optional, compared `is not None`, and absent
    unless the deployment asked for it; an owner holding none of them
    opens nothing, feeds nothing and hands nothing on, which is what a
    session that records nothing needs."""

    def __init__(
        self,
        session_id: str,
        events: SessionEvents,
        *,
        captures: CaptureStore | None,
        conversations: ConversationStore | None,
        transcripts: "TranscriptExport | None",
        llm_input: "LlmInputExport | None",
    ) -> None:
        self._session_id = session_id
        self._events = events
        self._captures = captures
        self._conversations = conversations
        self._transcripts = transcripts
        self._llm_input = llm_input
        # The recording's own decode path, built only when a capture
        # opens, so a server that is not recording pays for none of it.
        # It is what closes the capture it was built around.
        self._audio: CaptureAudio | None = None
        # The store's tap, attached where the capture's is.
        self._sink: SessionSink | None = None

    def open(
        self,
        opened_at: float,
        manifest: dict[str, Any],
        *,
        protocol_version: int,
        reply_sample_rate: int,
        renames: Callable[[], Sequence[tuple[str, str]]] | None,
        device_name: str | None,
    ) -> None:
        """Open the capture and then the session row, each where one is
        configured, and attach both to the session's events.

        The capture first, so its tap attaches before the store's and
        the dispatch order stays capture first, store second, log last:
        the store sees exactly what the capture's decision track sees,
        in the same order and from the same first event. That record is
        the decision track, `session_open` through `session_closed`.

        Both are opened with the same reading, so a `t_ms` in the
        database and a `t_ms` in the capture's decision track index into
        one timeline, and with the same manifest, which is where the
        session row's device, agents, protocol and providers come from.

        `renames` is handed to the store exactly as it came: the session
        builds it from the world it pinned, and the store calls it at the
        instant it registers this session. `protocol_version` and
        `reply_sample_rate` are what the capture's codecs unwrap and
        decode against, both facts about the wire the session speaks."""
        self._open_capture(opened_at, manifest, protocol_version, reply_sample_rate)
        self._open_record(opened_at, manifest, renames, device_name)

    def _open_capture(
        self,
        opened_at: float,
        manifest: dict[str, Any],
        protocol_version: int,
        reply_sample_rate: int,
    ) -> None:
        """Begin recording this session, when a directory is configured.

        The decision track is attached before the audio owner is built,
        and from the raw capture: which events a session emits is the
        session's business, through the events object it owns, while the
        audio is the one thing recording needs codecs of its own for.

        Building it is also the one step here that runs a media library,
        and a library that cannot open a codec raises. That is released
        on the spot rather than left to the close, because the close
        releases the field, and the field is only assigned once the
        construction has returned: a capture stranded at this line would
        be an open file and an attached consumer that nothing ever
        closes.

        The session then carries on without a recording. Recording is
        best-effort, and it is the promise `CaptureAudio` keeps about a
        capture too (a frame it cannot read is not a reason to stop
        capturing); a household that cannot record is not a household
        that cannot talk. Reported with the session id and nothing taken
        from the exception, not even its class, and only once the
        exception is no longer being handled, for the reasons `_step`
        gives; the release is a step of its own, so a capture whose close
        raises is reported the way a close step's failure is, and the row
        still opens after it."""
        if self._captures is None:
            return
        capture = self._captures.open(self._session_id, opened_at, manifest)
        if capture is None:
            return
        self._events.attach_capture(capture)
        failed = False
        try:
            self._audio = CaptureAudio(capture, protocol_version, reply_sample_rate)
        except Exception:  # noqa: BLE001 - a recording is best-effort
            # Only noted, and not bound: the release and the report below
            # run once this suite is left, for the reason `_step` gives.
            failed = True
        if not failed:
            return

        def release() -> None:
            # Detached before closed, so a close that fails in its own
            # right still leaves no consumer writing into a capture that
            # is on its way out.
            self._events.detach_capture()
            capture.close()

        self._step("the capture", release)
        self._report("session %s: recording could not start")

    def _open_record(
        self,
        opened_at: float,
        manifest: dict[str, Any],
        renames: Callable[[], Sequence[tuple[str, str]]] | None,
        device_name: str | None,
    ) -> None:
        """Begin this session's row in the conversation store, when one
        is configured, and attach its tap after the capture's.

        What the initial agent activation emitted before the hello is
        outside the row, as it is outside the capture's track, because
        no consumer can be attached before a session has a manifest to
        be opened with."""
        if self._conversations is None:
            return
        self._conversations.open_session(
            self._session_id,
            opened_at,
            manifest,
            renames=renames,
            device_name=device_name,
        )
        self._sink = SessionSink(self._conversations, self._session_id)
        self._events.attach(self._sink)

    def microphone(self, data: bytes) -> None:
        """One mic frame as it arrived, for the capture's microphone
        channel. Nothing while no capture is open."""
        if self._audio is not None:
            self._audio.microphone(data)

    def reply(self, packet: bytes) -> None:
        """One reply packet as it was sent, for the capture's reply
        channel. Nothing while no capture is open."""
        if self._audio is not None:
            self._audio.reply(packet)

    def close(self, duration_s: float, reason: str) -> None:
        """Finish everything `open` began, and hand the session to the
        surfaces that outlive it.

        Called after the session's `session_closed` is emitted, so that
        event is the last line of the decision track, the last row of the
        record, and the WAV header is patched with a length covering
        everything. `duration_s` and `reason` are the row's, read by the
        session at the call.

        The handoffs do not depend on how far `open` got: a close after
        an `open` that raised part way, or after none at all, still
        hands the session to all three. Nor on how far the close got:
        each step is guarded on its own, so one that raises an
        `Exception` is reported and the next still runs, and the close
        itself does not raise one."""
        # The barrier stays None where the row's step did not finish: a
        # row whose close raised answered nothing, and None is what the
        # transcript export is handed for a session with no row at all.
        recorded = self._step(
            "the conversation record", partial(self._close_record, duration_s, reason)
        )
        self._step("the capture", self._close_capture)
        # And last of all, the one signal that means the conversation is
        # over rather than that a recording's files are final (#67). The
        # capture store's own `finished()` fires mid-conversation for a
        # capture that ended at its duration limit or after a write
        # failure, so a recording queued there would be attached to a
        # session still talking. Here the WAV header is patched, the
        # manifest is written, and this session is done.
        if self._captures is not None:
            self._step(
                "the capture upload", partial(self._captures.session_closed, self._session_id)
            )
        # And beside it, the other post-close surface, handed the barrier
        # the store just returned: the close is the last thing this
        # session puts on the writer's queue, so an acknowledgement of it
        # is what says the session's turns are readable (#495). It does
        # no work here: a read of a retained context and a put on a
        # bounded queue, and everything else happens on a worker of its
        # own.
        if self._transcripts is not None:
            self._step(
                "the transcript export",
                partial(self._transcripts.session_closed, self._session_id, recorded),
            )
        # And the third (#502), which needs no barrier and no handle:
        # what it exports was staged as the conversation went, so this is
        # a dictionary pop, a read of a map and a put on a bounded queue.
        # Last of the three because it is the widest, and a close that
        # failed part way through should have let the narrower surfaces
        # go first.
        if self._llm_input is not None:
            self._step(
                "the LLM-input export", partial(self._llm_input.session_closed, self._session_id)
            )

    def _step[T](self, step: str, work: Callable[[], T]) -> T | None:
        """Run one step guarded on its own: what it answers, or None
        where it raised an `Exception`, which is reported, and the step
        after it runs.

        Reported with the session id and the step named in this module's
        own words, both values this server chose, and nothing taken from
        the exception, not even its class: `type(name, (Exception,), {})`
        accepts any string as a name, so a far side's client can raise
        an exception whose class name is the far side's bytes (the
        correction recorded beside `events._offer`). The sentence keeps
        the session's `_cleanly` prefix, so filtering on "did not stop
        cleanly" still finds every cleanup step that failed.

        Not binding the exception is not enough on its own. Whatever runs
        inside an `except` suite runs while that exception is being
        handled, so anything the report raises gets it as its
        `__context__`, and a handler whose formatter fails prints that
        chain to stderr from inside `handleError` before any guard around
        the call can act. So the suite does nothing, and the report is
        made after it, when there is no exception left to chain. That is
        also why this is a function around the step and not a context
        manager: a with-statement's `__exit__` runs while the exception
        it is handed is still being handled, whatever the generator
        behind it does.

        Nothing is latched: the close's steps run after `session_closed`
        has rendered the close reason, and the row was handed its reason
        before any of them could fail. The log line is the record. And
        only `Exception`: the steps are synchronous, so no cancellation
        arrives inside one, and a `KeyboardInterrupt` or a `SystemExit`
        keeps going the way it goes through `_cleanly`."""
        try:
            return work()
        except Exception:  # noqa: BLE001 - a close always reaches its end
            # Nothing here, deliberately: see above.
            pass
        self._report("session %s: %s did not stop cleanly", step)
        return None

    def _report(self, message: str, *args: str) -> None:
        """Warn about this session on the session channel, and never
        fail while saying it.

        A logging call runs filters and handlers somebody else
        installed, and `events._report` exists because one of them can
        raise exactly where a guard has nothing left to catch it with;
        this is the same trade in one line, a lost diagnostic line rather
        than a lost step or a lost row."""
        with contextlib.suppress(Exception):
            logger.warning(message, self._session_id, *args)

    def _close_record(self, duration_s: float, reason: str) -> Acknowledgement | None:
        """Close this session's row: its duration, what ended it, and
        what it lost.

        The sink is detached before the row is closed, so no emission
        can reach the row after its close record is queued, and released
        whether or not the detachment finished, so a close that failed
        part way leaves no sink held here. What comes back is the store's
        barrier for this session, or nothing where there was no row to
        close; nothing here waits on it."""
        if self._sink is None or self._conversations is None:
            return None
        try:
            self._events.detach(self._sink)
        finally:
            self._sink = None
        return self._conversations.close_session(self._session_id, duration_s, reason)

    def _close_capture(self) -> None:
        """Finish the capture, where one is open.

        Its tap is detached before it closes, so the last line of its
        track is the session's last emission and its WAV header covers
        everything; and the codecs are released whether or not either
        finished, so a close that failed part way leaves nothing here to
        feed and nothing a second close would close again."""
        if self._audio is None:
            return
        try:
            self._events.detach_capture()
            self._audio.close()
        finally:
            self._audio = None


RecordingFactory = Callable[[str, SessionEvents], Recording]
"""What a device session is handed to build its recording from: called
once with the session's id and its events object."""


def recordings(
    captures: CaptureStore | None = None,
    conversations: ConversationStore | None = None,
    transcripts: "TranscriptExport | None" = None,
    llm_input: "LlmInputExport | None" = None,
) -> RecordingFactory:
    """The composition root's half: the collaborators every session's
    recording shares, closed over once, answering a builder for one
    session's. Called with none of them, it answers owners that record
    nothing."""

    def build(session_id: str, events: SessionEvents) -> Recording:
        return Recording(
            session_id,
            events,
            captures=captures,
            conversations=conversations,
            transcripts=transcripts,
            llm_input=llm_input,
        )

    return build
