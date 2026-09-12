"""The two sides of a transcript export, as things a lane can hold.

`transcript_export.py` reaches exactly two objects: a `Telemetry`, for
the retained context and the bounded write, and a `Reads`, for one page
of a session's turns. Both are seams the module declares, so what is
here stands in for each of them and a suite drives the REAL queue, the
real worker, the real acknowledgement wait, the real paging and the real
outcome events with no OpenTelemetry, no database and no clock.

Nothing here asserts. A helper returns a seam or a recorder, and the
suite says what it expects.

The recorders are the point rather than the fakes. What has to be proved
is which pages were read, with which cursor, and exactly what crossed
into the span writer, which are questions about what was ASKED FOR: so
both sides write down every call.
"""

import threading
from typing import Any

from vinga_server.conversations.records import Acknowledgement
from vinga_server.conversations.threads import Reads, Unreadable
from vinga_server.telemetry import Delivery, Telemetry, TranscriptTurn

# The opaque handle a retained context is, from the exporter's side. It
# never looks inside one, which is the whole of what "opaque" buys, so a
# lane can hand it anything it can recognize again.
A_CONTEXT = "a-retained-context"


def settled(landed: bool = True) -> Acknowledgement:
    """A close acknowledgement the writer has already answered."""
    answered = Acknowledgement()
    answered.settle(landed)
    return answered


def pending() -> Acknowledgement:
    """And one it has not, which is what a wedged store looks like from
    the worker's side."""
    return Acknowledgement()


class Exported:
    """The telemetry exporter, as the two questions a transcript export
    asks it.

    Not a `Telemetry`, and typed as one at the call site because that is
    what the module declares: what it uses is `retained_context` and
    `export_transcript`, and a lane that had to build a real provider to
    answer one handle would be driving OpenTelemetry to test a queue.

    `pages` is what a case reads back: one entry per bounded write, with
    the session, the context it was given and the turns that crossed,
    which is how a claim about paging, ordinals and what a span may
    carry is made without a span.

    `answers` is a script, so a case can drive a page that delivers
    followed by one that does not; `answer` is what it falls back on
    once the script runs out.
    """

    def __init__(
        self,
        contexts: dict[str, Any] | None = None,
        *,
        answer: Delivery = Delivery.DELIVERED,
        answers: list[Delivery] | None = None,
    ) -> None:
        self.contexts = dict(contexts or {})
        self.pages: list[tuple[str, Any, list[TranscriptTurn]]] = []
        self.asked: list[str] = []
        self._answer = answer
        self._answers = list(answers or [])
        self._lock = threading.Lock()

    def retained_context(self, session: str) -> Any | None:
        with self._lock:
            self.asked.append(session)
        return self.contexts.get(session)

    def export_transcript(
        self, session: str, context: Any, turns: Any
    ) -> Delivery:
        with self._lock:
            self.pages.append((session, context, list(turns)))
            if self._answers:
                return self._answers.pop(0)
        return self._answer

    @property
    def turns(self) -> list[TranscriptTurn]:
        """Every turn of every page, in the order they were written."""
        return [turn for _, _, turns in self.pages for turn in turns]


def exporting(
    contexts: dict[str, Any] | None = None, **answers: Any
) -> tuple[Telemetry, Exported]:
    """`Exported` under the type the module declares, and itself."""
    held = Exported(contexts, **answers)
    return held, held  # type: ignore[return-value]


class Reading:
    """The store's read seam, as the one question a transcript export
    asks it.

    A whole session's rows are planted and this pages them the way
    `threads.transcript_rows` does, on `id > after` with a limit, so the
    worker's own cursor arithmetic is exercised rather than mocked. What
    it records is every call, which is what a claim about a job that
    stopped reading after a failed page is made of.

    `unreadable` is the seam's other answer, and `unreadable_after` is
    the one a mid-session failure needs: the first pages answer and a
    later one does not.
    """

    def __init__(
        self,
        rows: dict[str, list[dict[str, Any]]] | None = None,
        *,
        unreadable: bool = False,
        unreadable_after: int | None = None,
    ) -> None:
        self.rows = dict(rows or {})
        self.calls: list[tuple[str, int | None, int]] = []
        self._unreadable = unreadable
        self._unreadable_after = unreadable_after
        self._lock = threading.Lock()

    def transcript_rows(
        self, session: str, after: int | None = None, limit: int = 256
    ) -> "list[dict[str, Any]] | Unreadable":
        with self._lock:
            self.calls.append((session, after, limit))
            reads = len(self.calls)
        if self._unreadable:
            return Unreadable()
        if self._unreadable_after is not None and reads > self._unreadable_after:
            return Unreadable()
        held = self.rows.get(session, [])
        page = [row for row in held if after is None or row["id"] > after]
        return page[:limit]


def reading(
    rows: dict[str, list[dict[str, Any]]] | None = None, **failing: Any
) -> tuple[Reads, Reading]:
    """`Reading` under the type the module declares, and itself."""
    held = Reading(rows, **failing)
    return held, held  # type: ignore[return-value]


def a_row(
    id: int,  # noqa: A002 - the column's own name, which is what a row carries
    heard: str | None = "turn the light on",
    reply: str | None = "Done.",
    agent: str | None = "alpha",
    legs: Any = None,
    t_ms: int | None = None,
) -> dict[str, Any]:
    """One row of the transcript projection, spelled exactly as
    `threads.transcript_rows` answers it."""
    return {
        "id": id,
        "t_ms": id * 100 if t_ms is None else t_ms,
        "agent": agent,
        "heard": heard,
        "reply": reply,
        "legs": legs,
    }
