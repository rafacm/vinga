"""What a watched provider call says, pinned before the watching moves.

Provider watching is the cluster of the reply that reports a failing
ASR, LLM or TTS call without swallowing it, bounds an LLM's first token
and retries it once, and reports and files a finished round (#482, M2).
It is moving out of the runtime into a module of its own, and nothing a
consumer of the records can see is allowed to move with it. So every
emit site it owns is pinned here as a consumer sees it: the unrendered
sentence, its arguments as typed values, and the structured payload's
keys and values, with the timing fields held by type and presence
rather than by value, since a clock is not something a pin can hold.

One case per caller path, because each caller reaches the watching by a
different route and a move can break one route while the rest stay
green: the reply's own ASR, the reply's LLM stream, the round the
watchdog gives up, the sentence synthesis, and the barge-in
confirmation. The recap's two paths are pinned beside the rest of the
recap flow, in `test_session_recap.py`, where the offer a recap needs
is already set up.

The turn record is pinned too, because a reply round's report is also
the line that files the round on the record: the rounds, the summed
duration, the first token and the token totals.

Driven through the suites' own session helpers and the event-baseline
drivers' helpers, so this file adds no reach-in of its own.
"""

import asyncio
import logging
import re
from typing import Any, cast

import pytest

from tests.support.configs import BOTH_MAC, POET_MAC, base_config, watchdog_config
from tests.support.events import fields_of, only
from tests.support.providers import STALL_S, ScriptedLlm, StallingLlm, Unreachable
from tests.support.records import recording_session
from tests.support.sessions import (
    call,
    drive_reply,
    hand_over_to,
    run_reply,
    session_for,
    talking_thread,
    with_device,
)
from tests.support.sockets import QuietSocket
from tests.tools.event_baseline import failing_reply
from vinga_server.providers import AsrResult, Usage

# The utterance the direct drives hand a reply: 20 ms of silence, which
# the mock ASR answers whatever it holds.
UTTERANCE = b"\x00\x00" * 320

# A server-minted id: a session, a thread, an invocation.
MINTED = re.compile(r"^[0-9a-f]{32}$")

# The template every provider failure renders, whichever stage.
FAILED = "session %s: %s provider%s %s after %.2f s%s: %s"

# What an unreachable entry is named as in that sentence, and what it
# carries in the payload, which is the identity `Unreachable` stamps.
NAMED = ' "cloud"'
WHERE = " reaching api.example.com"
CLOUD = {
    "provider": "cloud",
    "type": "openai",
    "host": "api.example.com",
    "model": "gpt-4o-mini",
}


def refused() -> ConnectionRefusedError:
    return ConnectionRefusedError("no route")


def timed(record: logging.LogRecord, *, at: int) -> float:
    """The argument at `at`, which is a duration in seconds: held to
    being a float, and handed back for whatever else a case says."""
    value = record.args[at]  # type: ignore[index]
    assert type(value) is float and value >= 0
    return value


def payload(record: logging.LogRecord, *, timing: tuple[str, ...]) -> dict[str, object]:
    """The record's payload with its timing fields checked by type and
    presence and taken out, so what is left can be compared whole."""
    fields = fields_of(record)
    for name in timing:
        value = fields.pop(name)
        assert type(value) is int and value >= 0, name
    return fields


def the_pair(session: Any) -> dict[str, object]:
    """What every record of a session names: the session, the device,
    and the pair talking now."""
    return {
        "session": session.session_id,
        "device": POET_MAC,
        "agent": "poet",
        "conversation": talking_thread(session),
    }


# --- the watchdog --------------------------------------------------------


async def test_a_retried_round_says_llm_retry(caplog: pytest.LogCaptureFixture) -> None:
    llm = StallingLlm(delays=[STALL_S, 0.0])
    session = session_for(watchdog_config(), POET_MAC, {"poet": cast(Any, llm)})

    with caplog.at_level(logging.INFO):
        await run_reply(session, "are you there")

    retried = only(caplog, "llm_retry")
    assert retried.levelno == logging.WARNING
    assert retried.msg == "session %s: no first token after %.1f s, retrying round %d"
    assert retried.args is not None and len(retried.args) == 3
    assert retried.args[0] == session.session_id
    timed(retried, at=1)
    assert type(retried.args[2]) is int and retried.args[2] == 1
    assert payload(retried, timing=("duration_ms",)) == {
        "event": "llm_retry",
        **the_pair(session),
        "round": 1,
        "stage": "llm",
        "provider": "mock",
        "type": "mock",
    }


async def test_a_round_given_up_says_provider_failed_as_first_token_timeout(
    caplog: pytest.LogCaptureFixture,
) -> None:
    session = session_for(
        watchdog_config(), POET_MAC, {"poet": cast(Any, StallingLlm([STALL_S]))}
    )
    session.websocket = cast(Any, QuietSocket())
    with_device(session, POET_MAC)

    with caplog.at_level(logging.INFO):
        await drive_reply(session, UTTERANCE)

    failed = only(caplog, "provider_failed")
    assert failed.levelno == logging.WARNING
    assert failed.msg == FAILED
    assert failed.args is not None and len(failed.args) == 7
    assert failed.args[:4] == (session.session_id, "llm", ' "mock"', "timed out")
    timed(failed, at=4)
    assert failed.args[5:] == ("", "FirstTokenTimeout")
    fields = payload(failed, timing=("duration_ms",))
    invocation = fields.pop("invocation")
    assert isinstance(invocation, str) and MINTED.match(invocation)
    assert fields == {
        "event": "provider_failed",
        **the_pair(session),
        "error": "FirstTokenTimeout",
        "stage": "llm",
        "provider": "mock",
        "type": "mock",
        "purpose": "reply",
    }


# --- a round that finished -----------------------------------------------


async def test_every_reply_round_says_llm_round_and_files_itself_on_the_turn(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Two rounds of one reply: one that only asks for a tool, and one
    that speaks. The first has no first token to time; the record sums
    what both reported, and its first token is the reply's first."""
    script = ScriptedLlm(
        [
            [call("remember", text="tea"), Usage(prompt_tokens=10, completion_tokens=3)],
            ["Noted.", Usage(prompt_tokens=20, completion_tokens=5)],
        ]
    )
    session, spy, _ = recording_session(scripts={"poet": script})

    with caplog.at_level(logging.INFO):
        await drive_reply(session, UTTERANCE)

    rounds = [one for one in caplog.records if getattr(one, "event", None) == "llm_round"]
    assert len(rounds) == 2
    invocations = []
    durations = []
    for number, (record, turns, tokens) in enumerate(
        zip(rounds, (1, 3), ((10, 3), (20, 5)), strict=True), start=1
    ):
        assert record.levelno == logging.INFO
        assert record.msg == "session %s: %s round %d took %.2f s over %d turns"
        assert record.args is not None and len(record.args) == 5
        assert record.args[:3] == (session.session_id, "poet", number)
        assert type(record.args[2]) is int
        timed(record, at=3)
        assert type(record.args[4]) is int and record.args[4] == turns
        timing = ("duration_ms",) if number == 1 else ("duration_ms", "first_token_ms")
        durations.append(fields_of(record)["duration_ms"])
        fields = payload(record, timing=timing)
        invocation = fields.pop("invocation")
        assert isinstance(invocation, str) and MINTED.match(invocation)
        invocations.append(invocation)
        assert fields == {
            "event": "llm_round",
            **the_pair(session),
            "round": number,
            "turns": turns,
            "stage": "llm",
            "provider": "mock",
            "type": "mock",
            "input_tokens": tokens[0],
            "output_tokens": tokens[1],
            "purpose": "reply",
        }
    assert len(set(invocations)) == 2

    (_, record) = spy.records[0]
    assert record.rounds == 2
    assert record.llm_ms == sum(cast(int, one) for one in durations)
    assert record.first_token_ms == fields_of(rounds[1])["first_token_ms"]
    assert (record.input_tokens, record.output_tokens) == (30, 8)


# --- a provider that failed, by the path that reached it -----------------


async def test_a_failing_ear_says_provider_failed_at_the_asr_stage(
    caplog: pytest.LogCaptureFixture,
) -> None:
    with caplog.at_level(logging.INFO):
        session = await failing_reply("asr", Unreachable("asr", refused()))

    failed = only(caplog, "provider_failed")
    assert failed.levelno == logging.WARNING
    assert failed.msg == FAILED
    assert failed.args is not None and len(failed.args) == 7
    assert failed.args[:4] == (session.session_id, "asr", NAMED, "failed")
    timed(failed, at=4)
    assert failed.args[5:] == (WHERE, "ConnectionRefusedError")
    assert payload(failed, timing=("duration_ms",)) == {
        "event": "provider_failed",
        **the_pair(session),
        "error": "ConnectionRefusedError",
        "stage": "asr",
        **CLOUD,
    }


async def test_a_failing_stream_says_provider_failed_at_the_llm_stage(
    caplog: pytest.LogCaptureFixture,
) -> None:
    with caplog.at_level(logging.INFO):
        session = await failing_reply("llm", Unreachable("llm", refused()))

    failed = only(caplog, "provider_failed")
    assert failed.levelno == logging.WARNING
    assert failed.msg == FAILED
    assert failed.args is not None and len(failed.args) == 7
    assert failed.args[:4] == (session.session_id, "llm", NAMED, "failed")
    timed(failed, at=4)
    assert failed.args[5:] == (WHERE, "ConnectionRefusedError")
    fields = payload(failed, timing=("duration_ms",))
    invocation = fields.pop("invocation")
    assert isinstance(invocation, str) and MINTED.match(invocation)
    assert fields == {
        "event": "provider_failed",
        **the_pair(session),
        "error": "ConnectionRefusedError",
        "stage": "llm",
        **CLOUD,
        "purpose": "reply",
    }


async def test_a_failing_voice_says_provider_failed_at_the_tts_stage(
    caplog: pytest.LogCaptureFixture,
) -> None:
    with caplog.at_level(logging.INFO):
        session = await failing_reply("tts", Unreachable("tts", refused()))

    failed = only(caplog, "provider_failed")
    assert failed.levelno == logging.WARNING
    assert failed.msg == FAILED
    assert failed.args is not None and len(failed.args) == 7
    assert failed.args[:4] == (session.session_id, "tts", NAMED, "failed")
    timed(failed, at=4)
    assert failed.args[5:] == (WHERE, "ConnectionRefusedError")
    assert payload(failed, timing=("duration_ms",)) == {
        "event": "provider_failed",
        **the_pair(session),
        "error": "ConnectionRefusedError",
        "stage": "tts",
        **CLOUD,
    }


async def test_a_failing_confirmation_says_provider_failed_and_still_raises(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """The barge-in gate's transcription, which is watched too and whose
    failure is the gate ladder's to handle, so it propagates."""
    session = session_for(
        base_config(), POET_MAC, stages={"asr": cast(Any, Unreachable("asr", refused()))}
    )

    with caplog.at_level(logging.INFO), pytest.raises(ConnectionRefusedError):
        await session.runtime.confirm_transcript(UTTERANCE)

    failed = only(caplog, "provider_failed")
    assert failed.levelno == logging.WARNING
    assert failed.msg == FAILED
    assert failed.args is not None and len(failed.args) == 7
    assert failed.args[:4] == (session.session_id, "asr", NAMED, "failed")
    timed(failed, at=4)
    assert failed.args[5:] == (WHERE, "ConnectionRefusedError")
    assert payload(failed, timing=("duration_ms",)) == {
        "event": "provider_failed",
        **the_pair(session),
        "error": "ConnectionRefusedError",
        "stage": "asr",
        **CLOUD,
    }


class HeldFailingAsr:
    """An ear that announces it has started, waits to be let go, and
    then fails, so a test can land a handover while it is suspended."""

    def __init__(self) -> None:
        self.started = asyncio.Event()
        self.release = asyncio.Event()

    async def transcribe(
        self, pcm: bytes, sample_rate: int, language_hint: str | None = None
    ) -> AsrResult:
        self.started.set()
        await self.release.wait()
        raise refused()


async def test_a_confirmation_failing_across_a_handover_names_the_pair_it_ends_on(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """The pair is read when the failure is said, not when the call
    began: a confirmation suspended inside its transcription while the
    reply hands over reports its failure as the agent talking now."""
    ear = HeldFailingAsr()
    session = session_for(base_config(), BOTH_MAC, stages={"asr": cast(Any, ear)})

    with caplog.at_level(logging.INFO):
        confirming = asyncio.create_task(session.runtime.confirm_transcript(UTTERANCE))
        await ear.started.wait()
        hand_over_to(session, "tutor")
        ear.release.set()
        with pytest.raises(ConnectionRefusedError):
            await confirming

    failed = only(caplog, "provider_failed")
    assert (failed.agent, failed.conversation) == ("tutor", talking_thread(session))
