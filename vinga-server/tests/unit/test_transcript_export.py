"""The transcript exporter: what it refuses, what it reads, and what it
says.

The second surface in this server that deliberately sends content off
the host, so this file is written the way the uploader's is: what a
default deployment gets is nothing at all, every refusal is a fixed
sentence with no value and no chain, and the content that genuinely
passes through is hunted through both log formats, both events' payloads
and every exception chain.

Two seams are faked, both of them the module's own: the telemetry the
spans go through and the store's read door. Nothing else is. The queue
is the real bounded one, the worker is the real daemon thread, the
acknowledgement wait is the real interruptible one, and the paging
arithmetic is the real one, driven against a reader that pages exactly
as the projection does.

The sentinel section is two families with opposite claims, and it is the
reason the projection is a projection. The IN-projection family is
content this surface is authorized to send: it has to reach the span
writer and nothing else. The OUT-of-projection family is everything else
a turn's row family can hold, planted in a real store and read through
the real `Reads`: none of it may reach the span writer, the events, the
logs or an exception chain, which is what proves the projection rather
than trusting it.

Two claims here are about timing rather than about values, and both are
driven rather than asserted about a design: a session's close must not
wait on a wedged worker, and a shutdown must interrupt a job that is
sitting in an acknowledgement wait rather than merely join it.
"""

import asyncio
import datetime as dt
import logging
import threading
import time
import uuid
from collections.abc import Iterator
from typing import Any

import pytest

from tests.support.events import both_formats, fields_of
from tests.support.stores import CONVERSATIONS_MANIFEST as MANIFEST
from tests.support.stores import rows
from tests.support.transcripts import (
    A_CONTEXT,
    Exported,
    Reading,
    a_row,
    exporting,
    pending,
    reading,
    settled,
)
from vinga_server.config import ConfigError
from vinga_server.config.models import DatabaseConfig, ServerConfig
from vinga_server.conversations import threads
from vinga_server.conversations.records import (
    MilestoneRecord,
    ToolInvocation,
    TurnLeg,
    TurnRecord,
)
from vinga_server.conversations.store import ConversationStore
from vinga_server.events.values import TranscriptExportFailure
from vinga_server.telemetry import Delivery
from vinga_server.transcript_export import (
    RECORDING_KEY,
    TEXT_KEY,
    TRANSCRIPTS_KEY,
    TRANSCRIPTS_NEED_TELEMETRY,
    TranscriptExport,
    build_transcript_export,
)

SESSION = "0123456789abcdef0123456789abcdef"

# What this surface IS authorized to send, planted in each half of a
# turn that genuinely carries it. Credential-shaped on purpose: if the
# projection ever widened into a field nobody authorized, this is the
# shape of thing that would ride out with it.
HEARD_SENTINEL = "heard-sk-live-0TRANSCRIPT-SENTINEL"
REPLY_SENTINEL = "reply-sk-live-0TRANSCRIPT-SENTINEL"
LEG_SENTINEL = "leg-sk-live-0TRANSCRIPT-SENTINEL"

# And what it is NOT, planted in every other content-bearing field the
# row family can hold. Distinct values, because the claim about these is
# the opposite of the claim above and a shared sentinel could not say
# which claim failed.
ARGUMENTS_SENTINEL = "arguments-0TRANSCRIPT-FORBIDDEN"
RESULT_SENTINEL = "result-0TRANSCRIPT-FORBIDDEN"
RECAP_SENTINEL = "recap-0TRANSCRIPT-FORBIDDEN"

# The token halves inside `legs`, replaced by marker numbers so a leak of
# them is visible as a number that could not have come from anywhere
# else.
INPUT_MARKER = 8675309
OUTPUT_MARKER = 5551212

NOW = dt.datetime(2026, 8, 15, 12, 0, tzinfo=dt.UTC)


def a_server(**server: Any) -> ServerConfig:
    """One server section, with recording and the export on unless a
    case says otherwise."""
    return ServerConfig.model_validate(
        {
            "conversations": {"enabled": True, "text": True},
            "telemetry": {"enabled": True, "export_transcripts": True},
            **server,
        }
    )


def an_exporter(
    rows: dict[str, list[dict[str, Any]]] | None = None,
    *,
    contexts: dict[str, Any] | None = None,
    backlog: int = 8,
    telemetry: Any = None,
    reads: Any = None,
    **options: Any,
) -> tuple[TranscriptExport, Exported, Reading]:
    """An exporter over both faked seams, with the real everything
    else."""
    held, recorded = (
        (telemetry, telemetry)
        if telemetry is not None
        else exporting(contexts if contexts is not None else {SESSION: A_CONTEXT})
    )
    door, read = (reads, reads) if reads is not None else reading(rows)
    exporter = TranscriptExport(
        telemetry=held,
        reads=door,
        backlog=backlog,
        batch_turns=options.pop("batch_turns", 256),
        acknowledgement_timeout_s=options.pop("acknowledgement_timeout_s", 2.0),
        shutdown_timeout_s=options.pop("shutdown_timeout_s", 10.0),
        **options,
    )
    return exporter, recorded, read


async def drained(
    exporter: TranscriptExport,
    ready: Any = None,
    complaint: str = "the worker never finished its job",
) -> None:
    """Wait for the work a case is about, then stop the worker.

    The wait is not politeness. A shutdown INTERRUPTS this exporter:
    anything still queued when the stop flag goes up is dropped with its
    event, which is the contract. So a case that shut down without
    waiting would be driving the drop path every time, whatever it meant
    to drive, and the claim it thought it was making would be about
    nothing.

    `ready` is the case's own signal that the job is over, which is
    whatever the case is about: an outcome event, a delivered page, a
    read that happened. A case whose claim is that NOTHING happens
    passes none and gets a moment the worker could have used instead.
    """
    if ready is None:
        await asyncio.sleep(0.25)
    else:
        deadline = time.monotonic() + 10.0
        while not ready():
            assert time.monotonic() < deadline, complaint
            await asyncio.sleep(0.01)
    await exporter.shutdown()


def outcomes(caplog: pytest.LogCaptureFixture) -> int:
    """How many jobs have said what became of them, either way."""
    return len(exports(caplog)) + len(reasons(caplog))


def reasons(caplog: pytest.LogCaptureFixture) -> list[str]:
    """Every failure reason this run reported, in order."""
    return [
        str(fields_of(record)["reason"])
        for record in caplog.records
        if getattr(record, "event", None) == "transcript_export_failed"
    ]


def exports(caplog: pytest.LogCaptureFixture) -> list[logging.LogRecord]:
    return [
        record
        for record in caplog.records
        if getattr(record, "event", None) == "transcripts_exported"
    ]


# --- nothing at all ----------------------------------------------------


def test_no_telemetry_section_builds_nothing() -> None:
    """The default, and it costs a server nothing: no object, no thread,
    no callback, no read."""
    config = a_server(telemetry=None)

    assert build_transcript_export(config, telemetry=None, database=DatabaseConfig()) is None


def test_the_flag_off_builds_nothing() -> None:
    """Telemetry on and the export off is the ordinary traced
    deployment, and it must not acquire a content surface by being
    traced."""
    config = a_server(telemetry={"enabled": True})
    held, _ = exporting()

    assert build_transcript_export(config, telemetry=held, database=DatabaseConfig()) is None


@pytest.mark.parametrize(
    "conversations",
    [
        pytest.param(None, id="absent"),
        pytest.param({"enabled": False, "text": True}, id="disabled"),
        pytest.param({"enabled": True, "text": False}, id="no text"),
    ],
)
def test_recording_nothing_is_a_no_op_and_says_so(
    conversations: dict[str, Any] | None, caplog: pytest.LogCaptureFixture
) -> None:
    """The issue's own rule, three ways: the flag on with nothing
    recorded is a no-op rather than a misconfiguration, because an
    operator mid-toggle has not misconfigured anything.

    Said out loud because a switch that does nothing is otherwise a
    silence somebody has to debug, and value-free because there is
    nothing to name but the keys.
    """
    caplog.set_level(logging.INFO)
    config = a_server(conversations=conversations)
    held, _ = exporting()

    assert (
        build_transcript_export(config, telemetry=held, database=DatabaseConfig())
        is None
    )
    assert TRANSCRIPTS_KEY in caplog.text
    assert RECORDING_KEY in caplog.text
    assert TEXT_KEY in caplog.text


def test_recording_nothing_with_the_flag_off_says_nothing(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """There is no no-op to explain when nothing was switched on, and a
    line about a switch nobody set is noise in every log that does not
    want it."""
    caplog.set_level(logging.INFO)
    config = a_server(conversations=None, telemetry={"enabled": True})
    held, _ = exporting()

    assert (
        build_transcript_export(config, telemetry=held, database=DatabaseConfig())
        is None
    )
    assert TRANSCRIPTS_KEY not in caplog.text


def test_a_recording_off_deployment_never_reaches_a_refusal() -> None:
    """The decision order, which is the contract: recording resolves
    FIRST, so a deployment that records nothing boots identically
    whatever the telemetry section or local_only say.

    Driven with local_only on, which is the refusal that would otherwise
    fire: a server that turned off recording and then could not boot
    would be an operator punished for the toggle they were told to make.
    """
    config = a_server(conversations={"enabled": False, "text": True}, local_only=True)
    held, _ = exporting()

    assert (
        build_transcript_export(
            config, telemetry=held, database=DatabaseConfig(), local_only=True
        )
        is None
    )


# --- the two refusals --------------------------------------------------


def test_the_export_needs_telemetry_and_says_so_without_a_value() -> None:
    """A transcript is an observation on the trace its session was
    exported under, so the flag on with `enabled` off has nothing to
    write onto."""
    config = a_server(telemetry={"enabled": False, "export_transcripts": True})

    with pytest.raises(ConfigError) as refusal:
        build_transcript_export(config, telemetry=None, database=DatabaseConfig())

    assert str(refusal.value) == TRANSCRIPTS_NEED_TELEMETRY
    assert refusal.value.__cause__ is None
    assert refusal.value.__context__ is None


def test_the_telemetry_refusal_names_both_ways_out() -> None:
    """Value-free and actionable: the two keys and the two edits, and
    nothing an operator wrote."""
    assert "telemetry.enabled" in TRANSCRIPTS_NEED_TELEMETRY
    assert "telemetry.export_transcripts" in TRANSCRIPTS_NEED_TELEMETRY


def test_local_only_refuses_before_anything_is_built() -> None:
    """Egress is asked before any construction and any thread, which is
    the caller's half of `check_feature`'s contract and the only way the
    refusal can honestly say nothing was built."""
    config = a_server(local_only=True)
    held, _ = exporting()

    with pytest.raises(ConfigError) as refusal:
        build_transcript_export(
            config, telemetry=held, database=DatabaseConfig(), local_only=True
        )

    assert "server.local_only is on" in str(refusal.value)
    assert TRANSCRIPTS_KEY in str(refusal.value)
    assert refusal.value.__cause__ is None


def test_the_local_only_sentence_is_the_egress_modules_own() -> None:
    """One home for the rule, checked rather than asserted: a transcript
    rule of its own would show up here as two sentences."""
    from vinga_server.egress import EgressRefusal, check_feature

    config = a_server(local_only=True)
    held, _ = exporting()

    with pytest.raises(EgressRefusal) as direct:
        check_feature(TRANSCRIPTS_KEY, egress=True, local_only=True)
    with pytest.raises(ConfigError) as boot:
        build_transcript_export(
            config, telemetry=held, database=DatabaseConfig(), local_only=True
        )

    assert str(boot.value) == str(direct.value)


def test_a_configured_deployment_builds_one() -> None:
    """And the positive, so the refusals above are about a path that
    otherwise works."""
    held, _ = exporting()

    built = build_transcript_export(
        a_server(), telemetry=held, database=DatabaseConfig()
    )

    assert built is not None


# --- what it exports ---------------------------------------------------


@pytest.mark.asyncio
async def test_a_multi_turn_session_exports_one_turn_per_row() -> None:
    """The ordinary path: every stored turn of the session crosses into
    the span writer once, in the store's own order, with the row's own
    id beside the ordinal."""
    exporter, telemetry, _ = an_exporter(
        {SESSION: [a_row(40), a_row(41), a_row(42)]}
    )

    exporter.session_closed(SESSION, settled())
    await drained(exporter, lambda: telemetry.pages)

    assert [turn.id for turn in telemetry.turns] == [40, 41, 42]
    assert [turn.index for turn in telemetry.turns] == [1, 2, 3]


@pytest.mark.asyncio
async def test_the_ordinal_is_one_based_and_session_local() -> None:
    """A database-wide row id is not a turn index: a later session's
    first turn begins at an arbitrary number, so the ordinal counts this
    export's own turns and starts at one."""
    exporter, telemetry, _ = an_exporter({SESSION: [a_row(90210), a_row(90211)]})

    exporter.session_closed(SESSION, settled())
    await drained(exporter, lambda: telemetry.pages)

    assert [turn.index for turn in telemetry.turns] == [1, 2]


@pytest.mark.asyncio
async def test_a_turn_with_neither_text_half_is_not_exported() -> None:
    """Recorded before the text switch went on, or nothing said and
    nothing answered: a span with no input and no output would be an
    observation carrying nothing at all, and it consumes no ordinal
    either."""
    exporter, telemetry, _ = an_exporter(
        {
            SESSION: [
                a_row(1),
                a_row(2, heard=None, reply=None),
                a_row(3),
            ]
        }
    )

    exporter.session_closed(SESSION, settled())
    await drained(exporter, lambda: telemetry.pages)

    assert [turn.id for turn in telemetry.turns] == [1, 3]
    assert [turn.index for turn in telemetry.turns] == [1, 2]


@pytest.mark.asyncio
async def test_a_turn_with_one_half_is_exported(caplog: pytest.LogCaptureFixture) -> None:
    """Half a turn is still a turn: an utterance nothing answered is
    part of what happened in the room."""
    exporter, telemetry, _ = an_exporter({SESSION: [a_row(1, reply=None)]})

    exporter.session_closed(SESSION, settled())
    await drained(exporter, lambda: telemetry.pages)

    assert [turn.id for turn in telemetry.turns] == [1]


@pytest.mark.asyncio
async def test_a_session_with_nothing_readable_says_nothing(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """A trail entry for an empty export would be noise a reader filters
    out, and the flag's own boot line already says why nothing will ever
    export when that is config's doing."""
    caplog.set_level(logging.INFO)
    exporter, telemetry, read = an_exporter({SESSION: []})

    exporter.session_closed(SESSION, settled())
    await drained(exporter, lambda: read.calls)

    assert telemetry.pages == []
    assert exports(caplog) == []
    assert reasons(caplog) == []


@pytest.mark.asyncio
async def test_a_session_whose_turns_are_all_textless_says_nothing(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """The same silence one layer in: rows exist, none of them has
    anything to say, and an event claiming zero turns exported would be
    a line about nothing."""
    caplog.set_level(logging.INFO)
    exporter, telemetry, _ = an_exporter(
        {SESSION: [a_row(1, heard=None, reply=None), a_row(2, heard=None, reply=None)]}
    )

    exporter.session_closed(SESSION, settled())
    await drained(exporter, lambda: telemetry.pages)

    assert telemetry.turns == []
    assert exports(caplog) == []


@pytest.mark.asyncio
async def test_the_success_event_counts_the_turns_that_went(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """What a reader compares against what the session's own record
    holds, and the elapsed time beside it, which is a fact about the
    store and the backend rather than about any reply's latency."""
    caplog.set_level(logging.INFO)
    exporter, _, _ = an_exporter({SESSION: [a_row(1), a_row(2), a_row(3)]})

    exporter.session_closed(SESSION, settled())
    await drained(exporter, lambda: exports(caplog))

    (said,) = exports(caplog)
    assert fields_of(said)["turns"] == 3
    assert fields_of(said)["session"] == SESSION
    assert isinstance(fields_of(said)["elapsed_ms"], int)


@pytest.mark.asyncio
async def test_the_legs_cross_the_seam_as_the_store_holds_them() -> None:
    """Allowlisting and encoding them is the span writer's decision, so
    what crosses here is the column: one decision in one place beats two
    that have to agree."""
    legs = [{"agent": "alpha", "text": "Let me ask."}]
    exporter, telemetry, _ = an_exporter({SESSION: [a_row(1, legs=legs)]})

    exporter.session_closed(SESSION, settled())
    await drained(exporter, lambda: telemetry.pages)

    (turn,) = telemetry.turns
    assert turn.legs == legs


@pytest.mark.asyncio
async def test_the_captured_context_is_what_every_page_is_written_with() -> None:
    """Read once, at admission, and carried: the whole point of the
    handle is that eviction between the close and the worker cannot
    change what a healthy export does."""
    exporter, telemetry, _ = an_exporter(
        {SESSION: [a_row(index) for index in range(1, 6)]}, batch_turns=2
    )

    exporter.session_closed(SESSION, settled())
    await drained(exporter, lambda: len(telemetry.pages) == 3)

    assert telemetry.asked == [SESSION], "the context was looked up more than once"
    assert {context for _, context, _ in telemetry.pages} == {A_CONTEXT}


# --- paging ------------------------------------------------------------


@pytest.mark.asyncio
async def test_an_oversized_session_is_read_and_delivered_a_page_at_a_time() -> None:
    """Nothing bounds a session's turn count, so the page is what bounds
    the database result, the spans in memory and one request's payload.

    Three pages and more, every turn present exactly once, and the
    ordinals continuous across the page boundaries, which is the one
    thing a per-page ordinal would get wrong.
    """
    rows = [a_row(index) for index in range(1, 12)]
    exporter, telemetry, read = an_exporter({SESSION: rows}, batch_turns=3)

    exporter.session_closed(SESSION, settled())
    await drained(exporter, lambda: len(telemetry.pages) == 4)

    assert [len(turns) for _, _, turns in telemetry.pages] == [3, 3, 3, 2]
    assert [turn.id for turn in telemetry.turns] == [row["id"] for row in rows]
    assert [turn.index for turn in telemetry.turns] == list(range(1, 12))


@pytest.mark.asyncio
async def test_each_page_continues_from_the_last_id_of_the_one_before() -> None:
    """Keyset paging on the identity column, which is what makes the
    read stable while a session's rows are being written behind it."""
    exporter, _, read = an_exporter(
        {SESSION: [a_row(index) for index in (10, 20, 30, 40, 50)]}, batch_turns=2
    )

    exporter.session_closed(SESSION, settled())
    await drained(exporter, lambda: len(read.calls) == 3)

    assert [after for _, after, _ in read.calls] == [None, 20, 40]


@pytest.mark.asyncio
async def test_a_full_final_page_costs_one_more_read_and_no_more() -> None:
    """A page exactly the size of the bound cannot say whether the
    session ended there, so one empty read settles it and the job
    stops."""
    exporter, telemetry, read = an_exporter(
        {SESSION: [a_row(1), a_row(2), a_row(3), a_row(4)]}, batch_turns=2
    )

    exporter.session_closed(SESSION, settled())
    await drained(exporter, lambda: len(read.calls) == 3)

    assert len(read.calls) == 3
    assert len(telemetry.pages) == 2


@pytest.mark.asyncio
async def test_a_page_that_fails_to_deliver_ends_the_job_where_it_is(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """The leading pages stand, deliberately: a reader meets the turns
    that did land and the failure event on the same trace, and where the
    transcript stops is the highest index they can see. The job reads no
    further, because a backend that refused one page is not going to take
    the next."""
    exporter, telemetry, read = an_exporter(
        {SESSION: [a_row(index) for index in range(1, 10)]},
        batch_turns=2,
        telemetry=Exported(
            {SESSION: A_CONTEXT},
            answers=[Delivery.DELIVERED, Delivery.UNDELIVERED],
        ),
    )

    exporter.session_closed(SESSION, settled())
    await drained(exporter, lambda: reasons(caplog))

    assert len(telemetry.pages) == 2, "the job kept going after a failed page"
    assert len(read.calls) == 2, "the job read on after a failed page"
    assert reasons(caplog) == [TranscriptExportFailure.UNDELIVERED]
    assert exports(caplog) == []


# --- the five failures, each at its decision site ----------------------


@pytest.mark.asyncio
async def test_a_session_with_no_retained_trace_is_no_trace(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Decided at admission and never at export, which is what the
    captured context is for: telemetry that never saw the session, or a
    session whose trace had aged out before it closed, has nothing to be
    written onto."""
    exporter, telemetry, read = an_exporter({SESSION: [a_row(1)]}, contexts={})

    exporter.session_closed(SESSION, settled())
    await drained(exporter, lambda: reasons(caplog))

    assert reasons(caplog) == [TranscriptExportFailure.NO_TRACE]
    assert read.calls == [], "a session with no trace was read anyway"


@pytest.mark.asyncio
async def test_an_unsettled_record_is_unrecorded(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """The barrier's `False`, and the three answers it deliberately does
    not tell apart: dropped, stopped, or the wait ran out. All three mean
    the session's turns may not be assumed readable."""
    exporter, _, read = an_exporter({SESSION: [a_row(1)]})

    exporter.session_closed(SESSION, settled(False))
    await drained(exporter, lambda: reasons(caplog))

    assert reasons(caplog) == [TranscriptExportFailure.UNRECORDED]
    assert read.calls == [], "the store was read past its own barrier"


@pytest.mark.asyncio
async def test_a_wait_that_runs_out_is_unrecorded_too(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """A store that never answers at all, which is what a wedged writer
    looks like from here: the wait has a bound of its own and what it
    reports is the same reason, because what a caller may do about it is
    the same."""
    exporter, _, read = an_exporter(
        {SESSION: [a_row(1)]}, acknowledgement_timeout_s=0.2
    )

    began = time.monotonic()
    exporter.session_closed(SESSION, pending())
    await drained(exporter, lambda: reasons(caplog))

    assert reasons(caplog) == [TranscriptExportFailure.UNRECORDED]
    assert read.calls == []
    assert time.monotonic() - began < 5.0


@pytest.mark.asyncio
async def test_a_store_that_will_not_answer_is_unreadable(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """The read seam's own answer, which exists so a driver's DSN never
    reaches a surface: a raise here would put a credential in the log
    this event is written to."""
    door, read = reading(unreadable=True)
    exporter, telemetry, _ = an_exporter(reads=door)

    exporter.session_closed(SESSION, settled())
    await drained(exporter, lambda: reasons(caplog))

    assert reasons(caplog) == [TranscriptExportFailure.UNREADABLE]
    assert telemetry.pages == []


@pytest.mark.asyncio
async def test_a_read_that_fails_mid_session_is_unreadable(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """And the same answer when the store stops answering part way, with
    the pages already delivered left standing."""
    door, read = reading(
        {SESSION: [a_row(index) for index in range(1, 8)]}, unreadable_after=2
    )
    exporter, telemetry, _ = an_exporter(reads=door, batch_turns=2)

    exporter.session_closed(SESSION, settled())
    await drained(exporter, lambda: reasons(caplog))

    assert reasons(caplog) == [TranscriptExportFailure.UNREADABLE]
    assert len(telemetry.pages) == 2


@pytest.mark.asyncio
async def test_a_backend_that_will_not_take_the_spans_is_undelivered(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """The bounded call's own answer. No retry beyond the exporter's
    own, because a backend that is down stays down for longer than a
    worker should wait, and the event is the honest report."""
    exporter, _, _ = an_exporter(
        {SESSION: [a_row(1)]},
        telemetry=Exported({SESSION: A_CONTEXT}, answer=Delivery.UNDELIVERED),
    )

    exporter.session_closed(SESSION, settled())
    await drained(exporter, lambda: reasons(caplog))

    assert reasons(caplog) == [TranscriptExportFailure.UNDELIVERED]


@pytest.mark.asyncio
async def test_a_full_backlog_drops_the_job_and_says_so(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """The bound stated rather than hidden: a job nobody will ever run
    is a transcript nobody exported, and the event is the whole of the
    ledger since nothing is persisted."""
    held = threading.Event()
    door, read = reading({f"s{index}": [a_row(1)] for index in range(8)})
    blocking = Exported({f"s{index}": A_CONTEXT for index in range(8)})
    original = blocking.export_transcript

    def wait_first(session: str, context: Any, turns: Any) -> Delivery:
        held.wait(10.0)
        return original(session, context, turns)

    blocking.export_transcript = wait_first  # type: ignore[method-assign]
    exporter, _, _ = an_exporter(reads=door, telemetry=blocking, backlog=2)

    try:
        for index in range(6):
            exporter.session_closed(f"s{index}", settled())
    finally:
        held.set()
    await drained(exporter, lambda: reasons(caplog))

    assert TranscriptExportFailure.DROPPED in reasons(caplog)


@pytest.mark.asyncio
async def test_a_session_closing_behind_a_shutdown_is_dropped(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Which a drain produces: no worker will start for it, so the drop
    is said at the door rather than left as a job nothing will ever
    answer."""
    exporter, _, _ = an_exporter({SESSION: [a_row(1)]})

    await exporter.shutdown()
    exporter.session_closed(SESSION, settled())

    assert reasons(caplog) == [TranscriptExportFailure.DROPPED]


@pytest.mark.asyncio
async def test_a_session_that_recorded_nothing_is_silence(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """No handle means the store was never told about this session, so
    there is nothing to wait for, nothing to read, and nothing to
    report."""
    caplog.set_level(logging.INFO)
    exporter, telemetry, read = an_exporter({SESSION: [a_row(1)]})

    exporter.session_closed(SESSION, None)
    await drained(exporter)

    assert reasons(caplog) == []
    assert exports(caplog) == []
    assert telemetry.asked == []


# --- the drain, the close ordering and the interrupt -------------------


@pytest.mark.asyncio
async def test_every_job_of_a_full_drain_is_accounted_for(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """A routine shutdown closes every live session at once, which is
    what the backlog is sized from. Every one of them is either exported
    or dropped with its event: a session that closed and produced
    neither would be a transcript that vanished in silence.
    """
    caplog.set_level(logging.INFO)
    sessions = [f"s{index:02d}" for index in range(12)]
    door, _ = reading({session: [a_row(1)] for session in sessions})
    exporter, _, _ = an_exporter(
        reads=door,
        contexts=dict.fromkeys(sessions, A_CONTEXT),
        backlog=4,
    )

    for session in sessions:
        exporter.session_closed(session, settled())
    await drained(
        exporter,
        lambda: outcomes(caplog) == len(sessions),
        "not every job of the drain said what became of it",
    )

    said = [str(fields_of(record)["session"]) for record in exports(caplog)] + [
        str(fields_of(record)["session"])
        for record in caplog.records
        if getattr(record, "event", None) == "transcript_export_failed"
    ]
    assert sorted(said) == sorted(sessions)


@pytest.mark.asyncio
async def test_a_close_does_not_wait_on_a_wedged_worker() -> None:
    """The one latency claim the close path makes: the hook is a map
    read and a queue put, so a worker stuck on a store that will not
    answer costs a session's close nothing."""
    door, _ = reading({f"s{index}": [a_row(1)] for index in range(4)})
    exporter, _, _ = an_exporter(
        reads=door,
        contexts={f"s{index}": A_CONTEXT for index in range(4)},
        acknowledgement_timeout_s=30.0,
    )
    exporter.session_closed("s0", pending())

    began = time.monotonic()
    for index in range(1, 4):
        exporter.session_closed(f"s{index}", settled())
    elapsed = time.monotonic() - began

    assert elapsed < 1.0, "a close waited on the worker"
    await exporter.shutdown()


@pytest.mark.asyncio
async def test_nothing_is_enqueued_before_the_session_closed(caplog) -> None:
    """The hook is the only door, and it is called from the close
    ordering: a store read that began while the conversation was still
    being recorded could read past the turns it was about to write."""
    exporter, telemetry, read = an_exporter({SESSION: [a_row(1)]})

    await asyncio.sleep(0.1)

    assert read.calls == []
    assert telemetry.pages == []
    await exporter.shutdown()


@pytest.mark.asyncio
async def test_a_shutdown_interrupts_a_job_sitting_in_the_wait(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """The teardown claim, driven at the moment it is about: a job may
    lawfully be thirty seconds deep in an acknowledgement wait when a
    shutdown begins, and the composition unwinds this exporter FIRST so
    the event can still be said while the tap is attached.

    So the wait is made of short slices watching a stop flag: the job in
    flight ends as `dropped` inside the join budget rather than being
    abandoned in silence after it.
    """
    exporter, _, read = an_exporter(
        {SESSION: [a_row(1)]}, acknowledgement_timeout_s=30.0, shutdown_timeout_s=5.0
    )
    exporter.session_closed(SESSION, pending())
    # The worker is genuinely inside the wait rather than about to be.
    await asyncio.sleep(0.2)

    began = time.monotonic()
    await exporter.shutdown()
    elapsed = time.monotonic() - began

    assert elapsed < 5.0, "the shutdown waited out the acknowledgement bound"
    assert reasons(caplog) == [TranscriptExportFailure.DROPPED]
    assert read.calls == []


@pytest.mark.asyncio
async def test_a_shutdown_answers_what_it_left_queued(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Everything the stop flag stranded, said rather than dropped in
    silence: nothing is persisted, so this event is the only ledger
    there is."""
    sessions = [f"s{index}" for index in range(5)]
    door, _ = reading({session: [a_row(1)] for session in sessions})
    exporter, _, _ = an_exporter(
        reads=door,
        contexts=dict.fromkeys(sessions, A_CONTEXT),
        acknowledgement_timeout_s=30.0,
    )
    for session in sessions:
        exporter.session_closed(session, pending())
    await asyncio.sleep(0.2)

    await exporter.shutdown()

    assert sorted(reasons(caplog)) == [TranscriptExportFailure.DROPPED] * 5


# --- the sentinels, two families with opposite claims ------------------


@pytest.fixture
def stores() -> Iterator[Any]:
    """Real conversation stores, always stopped."""
    built: list[ConversationStore] = []

    def _build(**options: Any) -> ConversationStore:
        store = ConversationStore(DatabaseConfig(), now=lambda: NOW, **options)
        built.append(store)
        return store

    yield _build
    for store in built:
        store.stop()


def a_thread(name: str) -> str:
    return uuid.uuid5(uuid.NAMESPACE_OID, name).hex


def a_planted_session(store: ConversationStore, session: str, thread: str) -> None:
    """One session's worth of rows carrying every content-bearing field
    the family can hold, both families of sentinel among them."""
    store.start()
    store.open_session(session, 100.0, MANIFEST)
    assert store.record_turn(
        session,
        TurnRecord(
            at=101.0,
            conversation=thread,
            agent="alpha",
            heard=HEARD_SENTINEL,
            reply=REPLY_SENTINEL,
            legs=(
                TurnLeg(
                    agent="alpha",
                    text=LEG_SENTINEL,
                    input_tokens=INPUT_MARKER,
                    output_tokens=OUTPUT_MARKER,
                ),
                TurnLeg(agent="beta", text="Done."),
            ),
            tools=(
                ToolInvocation(
                    position=0,
                    source="builtin",
                    name="remember",
                    arguments={"fact": ARGUMENTS_SENTINEL},
                    result=RESULT_SENTINEL,
                ),
            ),
        ),
    )
    spoken = tuple(row["id"] for row in rows("turns", session=session))
    assert spoken, "the planted turn never landed"
    assert store.record_milestone(
        session,
        MilestoneRecord(
            conversation=thread, covered=spoken, parent=None, text=RECAP_SENTINEL
        ),
    ).wait(10.0), "the planted recap never landed"
    assert store.close_session(session, duration_s=1.0, reason="idle").wait(10.0)


@pytest.mark.asyncio
async def test_the_authorized_content_reaches_the_span_writer_and_nowhere_else(
    stores: Any, caplog: pytest.LogCaptureFixture
) -> None:
    """The in-projection family: what this surface exists to send has to
    arrive at the one place that sends it, and must not appear in a log
    line, an event payload or an exception chain on the way.

    Driven through the real store and the real read seam, because the
    claim is about what a projection of real rows carries.
    """
    caplog.set_level(logging.DEBUG)
    session = "aaaa0000aaaa0000aaaa0000aaaa0000"
    a_planted_session(stores(), session, a_thread("authorized"))
    exporter, telemetry, _ = an_exporter(
        contexts={session: A_CONTEXT}, reads=threads.Reads(DatabaseConfig())
    )

    exporter.session_closed(session, settled())
    await drained(exporter, lambda: telemetry.pages)

    (turn,) = telemetry.turns
    assert turn.heard == HEARD_SENTINEL
    assert turn.reply == REPLY_SENTINEL
    assert LEG_SENTINEL in repr(turn.legs)
    written = both_formats(caplog)
    for sentinel in (HEARD_SENTINEL, REPLY_SENTINEL, LEG_SENTINEL):
        assert sentinel not in written, f"{sentinel} reached a log record"


@pytest.mark.asyncio
async def test_no_unauthorized_content_reaches_the_span_writer(
    stores: Any, caplog: pytest.LogCaptureFixture
) -> None:
    """The out-of-projection family, which is what proves the projection
    rather than trusting it: the same rows carry tool arguments, a tool
    result, a recap's text and the legs' token halves, and none of them
    may cross into the span writer, the events, either log format or an
    exception chain.
    """
    caplog.set_level(logging.DEBUG)
    session = "bbbb0000bbbb0000bbbb0000bbbb0000"
    a_planted_session(stores(), session, a_thread("unauthorized"))
    exporter, telemetry, _ = an_exporter(
        contexts={session: A_CONTEXT}, reads=threads.Reads(DatabaseConfig())
    )

    exporter.session_closed(session, settled())
    await drained(exporter, lambda: telemetry.pages)

    crossed = repr(telemetry.pages)
    written = both_formats(caplog)
    for sentinel in (ARGUMENTS_SENTINEL, RESULT_SENTINEL, RECAP_SENTINEL):
        assert sentinel not in crossed, f"{sentinel} crossed into the span writer"
        assert sentinel not in written, f"{sentinel} reached a log record"
    for marker in (INPUT_MARKER, OUTPUT_MARKER):
        assert str(marker) not in written, f"{marker} reached a log record"


@pytest.mark.asyncio
async def test_a_failure_says_nothing_of_what_it_was_carrying(
    stores: Any, caplog: pytest.LogCaptureFixture
) -> None:
    """Every failure family, one after another, over rows that carry
    both sentinel families: the reason is a token from a closed set, and
    nothing of the conversation rides beside it."""
    caplog.set_level(logging.DEBUG)
    session = "cccc0000cccc0000cccc0000cccc0000"
    a_planted_session(stores(), session, a_thread("failing"))
    door = threads.Reads(DatabaseConfig())

    unreadable, _ = reading(unreadable=True)
    families: list[tuple[Any, Any, Any]] = [
        (door, Exported({}), settled()),
        (door, Exported({session: A_CONTEXT}, answer=Delivery.UNDELIVERED), settled()),
        (door, Exported({session: A_CONTEXT}, answer=Delivery.STOPPED), settled()),
        (unreadable, Exported({session: A_CONTEXT}), settled()),
        (door, Exported({session: A_CONTEXT}), settled(False)),
    ]
    for index, (read, telemetry, recorded) in enumerate(families, start=1):
        exporter, _, _ = an_exporter(reads=read, telemetry=telemetry)
        exporter.session_closed(session, recorded)
        await drained(
            exporter,
            lambda index=index: len(reasons(caplog)) >= index,
            "a failure family said nothing at all",
        )

    assert sorted(set(reasons(caplog))) == sorted(
        {
            TranscriptExportFailure.NO_TRACE,
            TranscriptExportFailure.UNDELIVERED,
            TranscriptExportFailure.DROPPED,
            TranscriptExportFailure.UNREADABLE,
            TranscriptExportFailure.UNRECORDED,
        }
    )
    written = both_formats(caplog)
    for sentinel in (
        HEARD_SENTINEL,
        REPLY_SENTINEL,
        LEG_SENTINEL,
        ARGUMENTS_SENTINEL,
        RESULT_SENTINEL,
        RECAP_SENTINEL,
    ):
        assert sentinel not in written, f"{sentinel} rode a failure"


# --- the resumed conversation ------------------------------------------


@pytest.mark.asyncio
async def test_a_resumed_conversation_exports_only_this_sessions_turns(
    stores: Any,
) -> None:
    """The presumption proved by schema: `turns.session` says which
    session a turn was spoken in, so a thread that spans two sessions
    exports each session's own turns when that session closes, under
    whatever the flag said then.

    And the ordinal convention with it: the second session's first
    exported turn is index 1, whatever the thread held before it.
    """
    thread = a_thread("resumed")
    first = "dddd0000dddd0000dddd0000dddd0000"
    second = "eeee0000eeee0000eeee0000eeee0000"
    store = stores()
    store.start()
    store.open_session(first, 100.0, MANIFEST)
    for spoken in ("the first session", "still the first"):
        store.record_turn(
            first,
            TurnRecord(at=101.0, conversation=thread, agent="alpha", heard=spoken, reply="."),
        )
    assert store.close_session(first, duration_s=1.0, reason="idle").wait(10.0)
    store.open_session(second, 200.0, MANIFEST)
    store.record_turn(
        second,
        TurnRecord(
            at=201.0, conversation=thread, agent="alpha", heard="the second session", reply="."
        ),
    )
    assert store.close_session(second, duration_s=1.0, reason="idle").wait(10.0)

    exporter, telemetry, _ = an_exporter(
        contexts={second: A_CONTEXT}, reads=threads.Reads(DatabaseConfig())
    )
    exporter.session_closed(second, settled())
    await drained(exporter, lambda: telemetry.pages)

    assert [turn.heard for turn in telemetry.turns] == ["the second session"]
    assert [turn.index for turn in telemetry.turns] == [1]


@pytest.mark.asyncio
async def test_a_shutdown_interrupts_a_job_between_its_pages(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """The other half of the interrupt, and the one the acknowledgement
    wait's own slices do not cover.

    A long session is many page reads and many bounded calls, and only
    the call in flight is uninterruptible. A loop that read on would
    spend a shutdown's whole budget on a backlog of them, blow through
    the join, and say what became of the job after the event tap and
    telemetry had already been torn down, which is the one moment it has
    to speak in.

    So: one page held open, a shutdown begun behind it, the page
    released, and nothing after it read or delivered.
    """
    held = threading.Event()
    entered = threading.Event()
    blocking = Exported({SESSION: A_CONTEXT})
    delivering = blocking.export_transcript

    def hold(session: str, context: Any, turns: Any) -> Delivery:
        answer = delivering(session, context, turns)
        entered.set()
        held.wait(10.0)
        return answer

    blocking.export_transcript = hold  # type: ignore[method-assign]
    exporter, _, read = an_exporter(
        {SESSION: [a_row(index) for index in range(1, 7)]},
        batch_turns=2,
        telemetry=blocking,
        shutdown_timeout_s=5.0,
    )

    exporter.session_closed(SESSION, settled())
    assert entered.wait(10.0), "the worker never reached a delivery"
    stopping = asyncio.ensure_future(exporter.shutdown())
    await asyncio.sleep(0.1)
    held.set()
    await stopping

    assert len(blocking.pages) == 1, "a page was delivered after the stop flag"
    assert len(read.calls) == 1, "a page was read after the stop flag"
    assert reasons(caplog) == [TranscriptExportFailure.DROPPED], (
        "the in-flight job was not accounted for before the shutdown returned"
    )


@pytest.mark.asyncio
async def test_a_job_that_finishes_on_its_last_page_is_not_dropped(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """The other side of that check, so the interrupt cannot be bought
    by reporting a failure for a job that really finished: the stop is
    read AFTER the page that ends the session, never before it."""
    caplog.set_level(logging.INFO)
    exporter, telemetry, _ = an_exporter(
        {SESSION: [a_row(1), a_row(2), a_row(3)]}, batch_turns=2
    )

    exporter.session_closed(SESSION, settled())
    await drained(exporter, lambda: exports(caplog))

    assert reasons(caplog) == []
    assert len(telemetry.turns) == 3


@pytest.mark.asyncio
async def test_a_worker_that_will_not_start_is_a_dropped_job(
    caplog: pytest.LogCaptureFixture, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A process that cannot start a thread has larger problems than its
    transcripts, and this module's job is to leave none of them on the
    close path.

    The hook runs inside the device session's own cleanup, which is the
    one path in this server that always reaches its end: an exception
    out of here would travel through the close of a conversation that
    has nothing to do with it. So a start that fails is the closed set's
    `dropped`, exactly as a full backlog is, and what the caller sees is
    a session closing normally.
    """
    starting = threading.Thread.start

    def refuse(self: threading.Thread) -> None:
        if self.name == "vinga-transcript-export":
            raise RuntimeError("can't start new thread")
        starting(self)

    monkeypatch.setattr(threading.Thread, "start", refuse)
    exporter, telemetry, read = an_exporter({SESSION: [a_row(1)]})

    exporter.session_closed(SESSION, settled())

    assert reasons(caplog) == [TranscriptExportFailure.DROPPED]
    assert read.calls == []
    assert telemetry.pages == []


@pytest.mark.asyncio
async def test_a_shutdown_after_a_worker_that_never_started_is_harmless(
    caplog: pytest.LogCaptureFixture, monkeypatch: pytest.MonkeyPatch
) -> None:
    """And the other end of it: the field is assigned only once a start
    has succeeded, so a teardown behind a failed one has nothing to join
    rather than a thread that was never running.
    """
    starting = threading.Thread.start

    def refuse(self: threading.Thread) -> None:
        if self.name == "vinga-transcript-export":
            raise RuntimeError("can't start new thread")
        starting(self)

    monkeypatch.setattr(threading.Thread, "start", refuse)
    exporter, _, _ = an_exporter({SESSION: [a_row(1)]})
    exporter.session_closed(SESSION, settled())

    await exporter.shutdown()

    assert reasons(caplog) == [TranscriptExportFailure.DROPPED]
