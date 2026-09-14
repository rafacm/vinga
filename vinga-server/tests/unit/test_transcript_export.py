"""Live acknowledged transcript settlement onto canonical turn roots."""

import asyncio
import logging
import threading
import time
from collections.abc import Callable
from typing import Any

import pytest

from tests.support.events import both_formats, fields_of
from tests.support.transcripts import (
    Exported,
    exporting,
    observed_pending,
    pending,
    settled,
)
from vinga_server.boundary import Reach
from vinga_server.config import ConfigError
from vinga_server.config.models import ServerConfig
from vinga_server.conversations.records import ToolInvocation, TurnLeg, TurnRecord
from vinga_server.events.values import TranscriptExportFailure
from vinga_server.telemetry import TurnSettlement
from vinga_server.transcript_export import (
    RECORDING_KEY,
    TEXT_KEY,
    TRANSCRIPTS_KEY,
    TRANSCRIPTS_NEED_AN_EXPORTER,
    TRANSCRIPTS_NEED_TELEMETRY,
    TranscriptExport,
    build_transcript_export,
)

SESSION = "0123456789abcdef0123456789abcdef"
UTTERANCE = "0f1e2d3c4b5a69780f1e2d3c4b5a6978"


def a_server(**server: Any) -> ServerConfig:
    return ServerConfig.model_validate(
        {
            "conversations": {"enabled": True, "text": True},
            "telemetry": {"enabled": True, "export_transcripts": True},
            **server,
        }
    )


def a_turn(
    *,
    utterance: str = UTTERANCE,
    heard: str | None = "turn the light on",
    reply: str | None = "Done.",
    agent: str = "alpha",
    legs: tuple[TurnLeg, ...] = (),
    tools: tuple[ToolInvocation, ...] = (),
) -> TurnRecord:
    return TurnRecord(
        at=101.0,
        conversation="aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
        agent=agent,
        utterance=utterance,
        heard=heard,
        reply=reply,
        legs=legs,
        tools=tools,
    )


def an_exporter(
    *,
    telemetry: Exported | None = None,
    backlog: int = 8,
    acknowledgement_timeout_s: float = 0.25,
    shutdown_timeout_s: float = 2.0,
) -> tuple[TranscriptExport, Exported]:
    held, recorded = (
        (telemetry, telemetry) if telemetry is not None else exporting()
    )
    return (
        TranscriptExport(
            telemetry=held,  # type: ignore[arg-type]
            backlog=backlog,
            acknowledgement_timeout_s=acknowledgement_timeout_s,
            shutdown_timeout_s=shutdown_timeout_s,
        ),
        recorded,
    )


async def wait_for(
    ready: Callable[[], bool], complaint: str = "the transcript worker did not finish"
) -> None:
    deadline = time.monotonic() + 5.0
    while not ready():
        assert time.monotonic() < deadline, complaint
        await asyncio.sleep(0.01)


def event_records(
    caplog: pytest.LogCaptureFixture, name: str
) -> list[logging.LogRecord]:
    return [
        record
        for record in caplog.records
        if getattr(record, "event", None) == name
    ]


def reasons(caplog: pytest.LogCaptureFixture) -> list[str]:
    return [
        str(fields_of(record)["reason"])
        for record in event_records(caplog, "transcript_export_failed")
    ]


def test_no_telemetry_section_builds_nothing() -> None:
    assert (
        build_transcript_export(a_server(telemetry=None), telemetry=None)
        is None
    )


def test_the_flag_off_builds_nothing() -> None:
    held, _ = exporting()

    assert (
        build_transcript_export(
            a_server(telemetry={"enabled": True}),
            telemetry=held,
        )
        is None
    )


@pytest.mark.parametrize(
    "conversations",
    [
        pytest.param(None, id="absent"),
        pytest.param({"enabled": False, "text": True}, id="disabled"),
        pytest.param({"enabled": True, "text": False}, id="text-off"),
    ],
)
def test_recording_nothing_is_a_logged_no_op(
    conversations: dict[str, Any] | None, caplog: pytest.LogCaptureFixture
) -> None:
    caplog.set_level(logging.INFO)
    held, _ = exporting()

    assert (
        build_transcript_export(
            a_server(conversations=conversations),
            telemetry=held,
        )
        is None
    )
    assert TRANSCRIPTS_KEY in caplog.text
    assert RECORDING_KEY in caplog.text
    assert TEXT_KEY in caplog.text


def test_recording_off_resolves_before_the_boundary() -> None:
    held, _ = exporting()
    config = a_server(
        conversations={"enabled": False, "text": True}, data_boundary="network"
    )

    assert (
        build_transcript_export(
            config,
            telemetry=held,
            boundary=Reach.NETWORK,
        )
        is None
    )


def test_the_export_needs_enabled_telemetry() -> None:
    config = a_server(telemetry={"enabled": False, "export_transcripts": True})

    with pytest.raises(ConfigError, match=TRANSCRIPTS_NEED_TELEMETRY) as refusal:
        build_transcript_export(config, telemetry=None)

    assert refusal.value.__cause__ is None
    assert refusal.value.__context__ is None


def test_the_export_needs_a_built_telemetry_exporter() -> None:
    with pytest.raises(ConfigError, match=TRANSCRIPTS_NEED_AN_EXPORTER):
        build_transcript_export(a_server(), telemetry=None)


@pytest.mark.parametrize("boundary", [Reach.HOST, Reach.NETWORK])
def test_a_narrow_boundary_refuses_before_construction(boundary: Reach) -> None:
    held, _ = exporting()

    with pytest.raises(ConfigError) as refusal:
        build_transcript_export(
            a_server(data_boundary=boundary.value),
            telemetry=held,
            boundary=boundary,
        )

    assert "data boundary" in str(refusal.value)
    assert TRANSCRIPTS_KEY in str(refusal.value)
    assert refusal.value.__cause__ is None


@pytest.mark.parametrize("boundary", [None, Reach.INTERNET])
def test_permissive_boundaries_build_the_live_collaborator(
    boundary: Reach | None,
) -> None:
    held, _ = exporting()

    built = build_transcript_export(a_server(), telemetry=held, boundary=boundary)

    assert built is not None


@pytest.mark.asyncio
async def test_one_acknowledged_turn_settles_its_original_root(
    caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(logging.INFO)
    exporter, telemetry = an_exporter()

    exporter.turn_recorded(SESSION, a_turn(), settled(), final=True)
    await wait_for(lambda: bool(telemetry.settled))
    await exporter.shutdown()

    assert telemetry.settled == [
        (
            SESSION,
            UTTERANCE,
            {
                "input": "turn the light on",
                "output": "Done.",
                "legs": [{"agent": "alpha", "text": "Done."}],
            },
        )
    ]
    assert telemetry.released == []
    (event,) = event_records(caplog, "transcripts_exported")
    assert fields_of(event)["turns"] == 1


@pytest.mark.asyncio
async def test_settlement_waits_for_the_store_acknowledgement() -> None:
    exporter, telemetry = an_exporter(acknowledgement_timeout_s=30.0)
    acknowledgement = observed_pending()

    exporter.turn_recorded(SESSION, a_turn(), acknowledgement, final=True)
    assert await asyncio.to_thread(acknowledgement.wait_entered.wait, 5.0), (
        "the transcript worker did not enter the acknowledgement wait"
    )
    assert telemetry.settled == []
    assert telemetry.released == []

    acknowledgement.settle(True)
    await wait_for(lambda: bool(telemetry.settled))
    await exporter.shutdown()


@pytest.mark.asyncio
async def test_handover_rows_wait_independently_and_compose_once() -> None:
    exporter, telemetry = an_exporter(acknowledgement_timeout_s=30.0)
    first = settled()
    second = observed_pending()
    exporter.turn_recorded(
        SESSION,
        a_turn(
            heard="help me",
            reply="I will ask beta.",
            legs=(TurnLeg(agent="alpha", text="I will ask beta."),),
        ),
        first,
        final=False,
    )
    exporter.turn_recorded(
        SESSION,
        a_turn(
            heard=None,
            reply="Beta here.",
            agent="beta",
        ),
        second,
        final=True,
    )

    assert await asyncio.to_thread(second.wait_entered.wait, 5.0), (
        "the transcript worker did not enter the final acknowledgement wait"
    )
    assert telemetry.settled == []
    assert telemetry.released == []
    second.settle(True)
    await wait_for(lambda: bool(telemetry.settled))
    await exporter.shutdown()

    assert telemetry.settled == [
        (
            SESSION,
            UTTERANCE,
            {
                "input": "help me",
                "output": "I will ask beta. Beta here.",
                "legs": [
                    {"agent": "alpha", "text": "I will ask beta."},
                    {"agent": "beta", "text": "Beta here."},
                ],
            },
        )
    ]
    assert telemetry.released == []


@pytest.mark.asyncio
async def test_a_final_boundary_without_a_new_row_finishes_the_handover_group() -> None:
    exporter, telemetry = an_exporter()
    exporter.turn_recorded(
        SESSION,
        a_turn(
            heard="help me",
            reply="I will ask beta.",
            legs=(TurnLeg(agent="alpha", text="I will ask beta."),),
        ),
        settled(),
        final=False,
    )

    exporter.turn_missing(SESSION, UTTERANCE)
    await wait_for(lambda: bool(telemetry.settled))
    await exporter.shutdown()

    assert telemetry.settled == [
        (
            SESSION,
            UTTERANCE,
            {
                "input": "help me",
                "output": "I will ask beta.",
                "legs": [{"agent": "alpha", "text": "I will ask beta."}],
            },
        )
    ]
    assert telemetry.released == []


@pytest.mark.asyncio
async def test_one_failed_handover_acknowledgement_releases_the_whole_root(
    caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(logging.WARNING)
    exporter, telemetry = an_exporter()
    exporter.turn_recorded(SESSION, a_turn(reply="first"), settled(), final=False)
    exporter.turn_recorded(
        SESSION, a_turn(heard=None, reply="second"), settled(False), final=True
    )

    await wait_for(lambda: bool(telemetry.released))
    await exporter.shutdown()

    assert telemetry.settled == []
    assert telemetry.released == [(SESSION, UTTERANCE)]
    assert reasons(caplog) == [TranscriptExportFailure.UNRECORDED]


@pytest.mark.asyncio
async def test_missing_acknowledgement_is_unrecorded(
    caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(logging.WARNING)
    exporter, telemetry = an_exporter()

    exporter.turn_recorded(SESSION, a_turn(), None, final=True)
    await wait_for(lambda: bool(telemetry.released))
    await exporter.shutdown()

    assert telemetry.released == [(SESSION, UTTERANCE)]
    assert reasons(caplog) == [TranscriptExportFailure.UNRECORDED]


@pytest.mark.asyncio
async def test_acknowledgement_timeout_is_unrecorded(
    caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(logging.WARNING)
    exporter, telemetry = an_exporter(acknowledgement_timeout_s=0.05)

    exporter.turn_recorded(SESSION, a_turn(), pending(), final=True)
    await wait_for(lambda: bool(telemetry.released))
    await exporter.shutdown()

    assert telemetry.released == [(SESSION, UTTERANCE)]
    assert reasons(caplog) == [TranscriptExportFailure.UNRECORDED]


@pytest.mark.asyncio
async def test_conflicting_heard_values_make_the_group_unreadable(
    caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(logging.WARNING)
    exporter, telemetry = an_exporter()
    exporter.turn_recorded(SESSION, a_turn(heard="one"), settled(), final=False)
    exporter.turn_recorded(SESSION, a_turn(heard="two"), settled(), final=True)

    await wait_for(lambda: bool(telemetry.released))
    await exporter.shutdown()

    assert telemetry.settled == []
    assert telemetry.released == [(SESSION, UTTERANCE)]
    assert reasons(caplog) == [TranscriptExportFailure.UNREADABLE]


@pytest.mark.asyncio
async def test_an_empty_projection_releases_the_root_without_an_outcome(
    caplog: pytest.LogCaptureFixture,
) -> None:
    exporter, telemetry = an_exporter()

    exporter.turn_recorded(
        SESSION, a_turn(heard=None, reply=None), settled(), final=True
    )
    await wait_for(lambda: bool(telemetry.released))
    await exporter.shutdown()

    assert telemetry.settled == []
    assert telemetry.released == [(SESSION, UTTERANCE)]
    assert event_records(caplog, "transcripts_exported") == []
    assert event_records(caplog, "transcript_export_failed") == []


@pytest.mark.asyncio
async def test_the_projection_admits_only_turn_content_and_leg_fields(
    caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(logging.DEBUG)
    exporter, telemetry = an_exporter()
    arguments = "arguments-0TRANSCRIPT-FORBIDDEN"
    result = "result-0TRANSCRIPT-FORBIDDEN"
    heard = "heard-sk-live-0TRANSCRIPT-SENTINEL"
    reply = "reply-sk-live-0TRANSCRIPT-SENTINEL"
    exporter.turn_recorded(
        SESSION,
        a_turn(
            heard=heard,
            reply=reply,
            legs=(
                TurnLeg(
                    agent="alpha", text="first leg", input_tokens=11, output_tokens=5
                ),
            ),
            tools=(
                ToolInvocation(
                    position=0,
                    source="builtin",
                    name="remember",
                    arguments={"fact": arguments},
                    result=result,
                ),
            ),
        ),
        settled(),
        final=True,
    )

    await wait_for(lambda: bool(telemetry.settled))
    await exporter.shutdown()

    content = telemetry.settled[0][2]
    assert content == {
        "input": heard,
        "output": reply,
        "legs": [
            {
                "agent": "alpha",
                "text": "first leg",
                "input_tokens": 11,
                "output_tokens": 5,
            }
        ],
    }
    crossed = repr(content)
    written = both_formats(caplog)
    for forbidden in (arguments, result):
        assert forbidden not in crossed
        assert forbidden not in written
    for authorized in (heard, reply):
        assert authorized not in written


@pytest.mark.asyncio
async def test_an_oversized_turn_is_dropped_whole(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    caplog.set_level(logging.WARNING)
    monkeypatch.setattr("vinga_server.transcript_export.MAX_CONTENT_BYTES", 20)
    exporter, telemetry = an_exporter()

    exporter.turn_recorded(
        SESSION, a_turn(heard="12345678901", reply=None), settled(), final=True
    )
    await wait_for(lambda: bool(telemetry.released))
    await exporter.shutdown()

    assert telemetry.settled == []
    assert telemetry.released == [(SESSION, UTTERANCE)]
    assert reasons(caplog) == [TranscriptExportFailure.DROPPED]


@pytest.mark.asyncio
async def test_unencodable_text_releases_the_root_as_unreadable(
    caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(logging.WARNING)
    exporter, telemetry = an_exporter()

    exporter.turn_recorded(
        SESSION, a_turn(heard="invalid-\ud800"), settled(), final=True
    )
    await wait_for(lambda: bool(telemetry.released))
    await exporter.shutdown()

    assert telemetry.settled == []
    assert telemetry.released == [(SESSION, UTTERANCE)]
    assert reasons(caplog) == [TranscriptExportFailure.UNREADABLE]


@pytest.mark.asyncio
async def test_a_missing_root_is_reported_without_a_second_release(
    caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(logging.WARNING)
    telemetry = Exported(answer=False)
    exporter, _ = an_exporter(telemetry=telemetry)

    exporter.turn_recorded(SESSION, a_turn(), settled(), final=True)
    await wait_for(lambda: bool(telemetry.settled))
    await exporter.shutdown()

    assert len(telemetry.settled) == 1
    assert telemetry.released == []
    assert reasons(caplog) == [TranscriptExportFailure.NO_TRACE]


def test_a_missing_record_releases_the_root_without_a_failure(
    caplog: pytest.LogCaptureFixture,
) -> None:
    exporter, telemetry = an_exporter()

    exporter.turn_missing(SESSION, UTTERANCE)

    assert telemetry.released == [(SESSION, UTTERANCE)]
    assert event_records(caplog, "transcript_export_failed") == []


def test_session_close_releases_an_incomplete_handover_group(
    caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(logging.WARNING)
    exporter, telemetry = an_exporter()
    exporter.turn_recorded(SESSION, a_turn(reply="first"), settled(), final=False)

    exporter.session_closed(SESSION)

    assert telemetry.settled == []
    assert telemetry.released == [(SESSION, UTTERANCE)]
    assert reasons(caplog) == [TranscriptExportFailure.DROPPED]


@pytest.mark.asyncio
async def test_shutdown_interrupts_an_acknowledgement_wait_exactly_once(
    caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(logging.WARNING)
    exporter, telemetry = an_exporter(acknowledgement_timeout_s=30.0)
    exporter.turn_recorded(SESSION, a_turn(), pending(), final=True)
    await asyncio.sleep(0.1)

    await exporter.shutdown()

    assert telemetry.settled == []
    assert telemetry.released == [(SESSION, UTTERANCE)]
    assert reasons(caplog) == [TranscriptExportFailure.DROPPED]


@pytest.mark.asyncio
async def test_full_backlog_drops_newest_completed_group(
    caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(logging.WARNING)
    exporter, telemetry = an_exporter(
        backlog=1, acknowledgement_timeout_s=30.0
    )
    first = observed_pending()
    second = pending()
    exporter.turn_recorded(
        SESSION, a_turn(utterance="1" * 32), first, final=True
    )
    assert await asyncio.to_thread(first.wait_entered.wait, 5.0), (
        "the transcript worker did not enter the first acknowledgement wait"
    )
    exporter.turn_recorded(
        SESSION, a_turn(utterance="2" * 32), second, final=True
    )
    exporter.turn_recorded(
        SESSION, a_turn(utterance="3" * 32), settled(), final=True
    )

    await wait_for(lambda: (SESSION, "3" * 32) in telemetry.released)
    first.settle(True)
    second.settle(True)
    await wait_for(lambda: len(telemetry.settled) == 2)
    await exporter.shutdown()

    assert telemetry.settled[0][1] == "1" * 32
    assert telemetry.settled[1][1] == "2" * 32
    assert telemetry.released == [(SESSION, "3" * 32)]
    assert reasons(caplog) == [TranscriptExportFailure.DROPPED]


@pytest.mark.asyncio
async def test_shutdown_drains_queued_groups_as_dropped(
    caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(logging.WARNING)
    exporter, telemetry = an_exporter(
        backlog=2, acknowledgement_timeout_s=30.0
    )
    exporter.turn_recorded(
        SESSION, a_turn(utterance="1" * 32), pending(), final=True
    )
    await asyncio.sleep(0.1)
    exporter.turn_recorded(
        SESSION, a_turn(utterance="2" * 32), pending(), final=True
    )

    await exporter.shutdown()

    assert telemetry.settled == []
    assert sorted(telemetry.released) == [
        (SESSION, "1" * 32),
        (SESSION, "2" * 32),
    ]
    assert reasons(caplog) == [
        TranscriptExportFailure.DROPPED,
        TranscriptExportFailure.DROPPED,
    ]


@pytest.mark.asyncio
async def test_acknowledgement_and_shutdown_race_has_one_terminal_call() -> None:
    for index in range(100):
        utterance = f"{index:032x}"
        exporter, telemetry = an_exporter(acknowledgement_timeout_s=30.0)
        acknowledgement = pending()
        exporter.turn_recorded(
            SESSION,
            a_turn(utterance=utterance),
            acknowledgement,
            final=True,
        )
        answer = threading.Thread(target=acknowledgement.settle, args=(True,))
        answer.start()
        await exporter.shutdown()
        answer.join()

        terminals = [
            key
            for session, key, *_ in telemetry.settled
            if session == SESSION and key == utterance
        ] + [
            key
            for session, key in telemetry.released
            if session == SESSION and key == utterance
        ]
        assert terminals == [utterance]


def test_a_group_arriving_after_shutdown_is_dropped(
    caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(logging.WARNING)
    exporter, telemetry = an_exporter()
    asyncio.run(exporter.shutdown())

    exporter.turn_recorded(SESSION, a_turn(), settled(), final=True)

    assert telemetry.released == [(SESSION, UTTERANCE)]
    assert reasons(caplog) == [TranscriptExportFailure.DROPPED]


@pytest.mark.asyncio
async def test_worker_start_failure_releases_the_root(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    caplog.set_level(logging.WARNING)
    exporter, telemetry = an_exporter()

    def refuses_to_start(_thread: threading.Thread) -> None:
        raise RuntimeError("credential-shaped detail")

    monkeypatch.setattr(threading.Thread, "start", refuses_to_start)
    exporter.turn_recorded(SESSION, a_turn(), settled(), final=True)
    await exporter.shutdown()

    assert telemetry.released == [(SESSION, UTTERANCE)]
    assert reasons(caplog) == [TranscriptExportFailure.DROPPED]
    assert "credential-shaped detail" not in both_formats(caplog)


def test_telemetry_ledger_omission_is_reported_without_span_ownership(
    caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(logging.WARNING)
    exporter, telemetry = an_exporter()

    exporter.omitted(SESSION, UTTERANCE)

    assert telemetry.settled == []
    assert telemetry.released == []
    assert reasons(caplog) == [TranscriptExportFailure.DROPPED]


@pytest.mark.asyncio
async def test_overflow_callback_before_worker_reports_one_outcome(
    caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(logging.WARNING)
    telemetry = Exported(answer=False)
    exporter, _ = an_exporter(telemetry=telemetry)

    exporter.omitted(SESSION, UTTERANCE)
    exporter.turn_recorded(SESSION, a_turn(), settled(), final=True)
    await wait_for(lambda: bool(telemetry.settled))
    await exporter.shutdown()

    assert reasons(caplog) == [TranscriptExportFailure.DROPPED]


@pytest.mark.asyncio
async def test_overflow_worker_before_callback_reports_one_outcome(
    caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(logging.WARNING)
    telemetry = Exported(
        settlement=TurnSettlement.OMITTED,
        acknowledges_omission=False,
    )
    exporter, _ = an_exporter(telemetry=telemetry)

    exporter.turn_recorded(SESSION, a_turn(), settled(), final=True)
    await wait_for(lambda: bool(telemetry.settled))
    exporter.omitted(SESSION, UTTERANCE)
    await exporter.shutdown()

    assert reasons(caplog) == [TranscriptExportFailure.DROPPED]
