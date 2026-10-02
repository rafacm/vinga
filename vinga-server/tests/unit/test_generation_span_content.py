"""A generation's pair is counted once its `llm` span took it (#588).

With `server.telemetry.export_llm_input` on, a round's request and
output are staged for the `llm_round` or `provider_failed` event that
closes it, that event is emitted exactly once, and the handoff is then
settled: `llm_input_exported` counts the pair in `rounds` only once the
event's fold wrote it onto the `llm` span, and a pair the emission
never delivered is discarded and reported as
`llm_input_export_failed(kind=generation)`. One logical round is one
pair counted, however many attempts the first-token watchdog made at
it.

Driven through the real exporter writing into the SDK's in-memory
exporter, and through a real session or the real provider watch, so
the handoff these cases prove is the production one.
"""

import asyncio
import json
import logging
from collections.abc import Iterator
from typing import Any, cast

import pytest

from tests.support.configs import POET_MAC, watchdog_config
from tests.support.events import both_formats, only
from tests.support.events import events as logged_events
from tests.support.llm_input import a_turn, outcomes, traced
from tests.support.providers import STALL_S, ScriptedLlm, StallingLlm
from tests.support.sessions import drive_reply, run_reply
from tests.support.sockets import RecordingSocket
from tests.support.telemetry import (
    SESSION,
    Clock,
    close_session,
    exporting,
    finish_reply,
    finished,
    open_session,
    released,
    round_done,
    session_events,
    start_turn,
)
from vinga_server.config.models import ServerConfig
from vinga_server.events import SessionEvents
from vinga_server.events.values import LlmPurpose
from vinga_server.llm_input_export import LlmInputExport, build_llm_input_export
from vinga_server.providers.base import TextDelta, Usage
from vinga_server.runtime import prompt
from vinga_server.runtime.provider_watch import ProviderWatch
from vinga_server.runtime.turns import TurnUnderway
from vinga_server.session_conversations import SessionConversations
from vinga_server.telemetry import (
    _QUIETING,
    GEN_AI_INPUT_MESSAGES,
    GEN_AI_OUTPUT_MESSAGES,
    GEN_AI_SYSTEM_INSTRUCTIONS,
    LLM_INVOCATION_ID,
    LLM_SPAN,
    LLM_TOOL_CHOICE,
    LLM_TOOLS,
)

UTTERANCE = b"\x00\x00" * 320
ONE_ROUND = [("exported", 1, 0)]
DROPPED = [("failed", "generation", "dropped")]
CONTENT = {
    GEN_AI_SYSTEM_INSTRUCTIONS,
    GEN_AI_INPUT_MESSAGES,
    GEN_AI_OUTPUT_MESSAGES,
    LLM_TOOLS,
    LLM_TOOL_CHOICE,
}
INVOCATION = "0123456789abcdef0123456789abcdef"
# A session id telemetry holds no trace for, so the pair is refused at
# staging.
UNTRACED = "fedcba9876543210fedcba9876543210"
SENT = prompt.RoundPrompt(prompt.know_how("POET"), facts=None)

# Shaped like a live credential, so a leak of it would pass any syntax
# check a reader might apply.
CREDENTIAL_SHAPED = "sk_live_" + "9xRoundOutputSentinel0Kq7"


@pytest.fixture(autouse=True)
def _release() -> Iterator[None]:
    yield
    released()
    assert _QUIETING.held() == 0


def _generations(spans: list[Any]) -> list[dict[str, Any]]:
    return [dict(span.attributes) for span in spans if span.name == LLM_SPAN]


# --- the first-token watchdog's retry is one round, not two ------------


async def test_a_retried_round_is_exported_and_counted_once(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """The first attempt stalls and is cancelled, the retry answers: one
    `llm_round`, one `llm` span carrying the pair, and one round counted.
    The retry sends what the first attempt would have, so a second count
    would claim the model was given two things."""
    telemetry, memory = exporting()
    llm = StallingLlm(delays=[STALL_S, 0.0])
    session, events = traced(
        telemetry, llm, LlmInputExport(telemetry=telemetry), watchdog_config()
    )

    with caplog.at_level(logging.INFO):
        spoken = await run_reply(session, "are you there")
        finish_reply(events)
        close_session(events)

    assert spoken == ["Recovered now."]
    assert llm.calls == 2
    rounded = only(caplog, "llm_round")
    assert outcomes(caplog) == ONE_ROUND
    (generation,) = _generations(finished(telemetry, memory))
    assert generation[LLM_INVOCATION_ID] == rounded.invocation
    assert "Recovered now." in generation[GEN_AI_OUTPUT_MESSAGES]


async def test_a_round_given_up_twice_is_exported_and_counted_once(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Both attempts stall: the round fails once, as `provider_failed`,
    and its failed `llm` span carries the request it was sending."""
    telemetry, memory = exporting()
    llm = StallingLlm(delays=[STALL_S])
    session, events = traced(
        telemetry, llm, LlmInputExport(telemetry=telemetry), watchdog_config()
    )
    session.websocket = cast(Any, RecordingSocket())

    with caplog.at_level(logging.INFO):
        await drive_reply(session, UTTERANCE)
        finish_reply(events)
        close_session(events)

    assert llm.calls == 2
    failed = only(caplog, "provider_failed")
    assert not [r for r in caplog.records if getattr(r, "event", None) == "llm_round"]
    assert outcomes(caplog) == ONE_ROUND
    (generation,) = _generations(finished(telemetry, memory))
    assert generation[LLM_INVOCATION_ID] == failed.invocation
    assert json.loads(generation[GEN_AI_INPUT_MESSAGES])


# --- a refused round event keeps nothing and claims nothing ------------


def _watched(
    telemetry: Any, llm_input: LlmInputExport | None
) -> tuple[ProviderWatch, SessionEvents, TurnUnderway]:
    """The provider watch of one session whose trace is open on a turn,
    with the export it was built with."""
    events = session_events(Clock(), telemetry)
    open_session(events)
    start_turn(events)
    conversations = SessionConversations(POET_MAC)
    active = conversations.activate("poet")
    watch = ProviderWatch(events, conversations, 5.0, llm_input)
    return watch, events, TurnUnderway(active.conversation, active.agent, None)


def _staged(exporter: LlmInputExport, session: str = SESSION) -> None:
    """One reply round assembled and streamed under `INVOCATION`."""
    exporter.stage_reply(
        session,
        invocation=INVOCATION,
        agent="poet",
        system="be concise",
        turns=[a_turn()],
        tools=[],
        choice="none",
    )
    exporter.observe(INVOCATION, TextDelta(CREDENTIAL_SHAPED))


def _rounded(watch: ProviderWatch, turn: TurnUnderway, usage: Usage | None = None) -> None:
    """The round finishing, as the reply reports it."""
    began = asyncio.get_running_loop().time()
    watch.reply_round_done(
        turn, 1, object(), [], began, None, usage, invocation=INVOCATION, prompt=SENT
    )


def _failed(watch: ProviderWatch, failure: BaseException | None = None) -> None:
    """The round failing, as the stream's guard reports it."""
    watch.failed(
        "llm",
        object(),
        ConnectionRefusedError() if failure is None else failure,
        0.5,
        invocation=INVOCATION,
        purpose=LlmPurpose.REPLY,
        prompt=SENT,
    )


# A class whose name the `provider_failed` event refuses, spelled as a
# sentinel: the name is the value the refusal rejected, so it may reach
# no retained surface by any other route either.
REJECTED_NAME = "0REJECTED-CLASS-SENTINEL not a class name"
Rejected = type(REJECTED_NAME, (Exception,), {})


@pytest.mark.usefixtures("refusals_are_expected")
@pytest.mark.parametrize("closing", ["llm_round", "provider_failed"])
async def test_a_refused_round_event_reports_failure_and_keeps_nothing(
    closing: str,
    caplog: pytest.LogCaptureFixture,
    capfd: pytest.CaptureFixture[str],
) -> None:
    """The handoff is settled after the emission rather than assumed,
    driven through a whole reply so every route the failure takes is
    the production one. `llm_round` refuses a negative token count the
    model reported, and `provider_failed` an error class with no
    nameable name, raised by the stream after the round's output began.
    Either way the pair the refused event never consumed is reported as
    dropped, counted nowhere as exported, and gone, so a later round
    under the same invocation carries none of it; and neither the
    round's content nor the value the refusal rejected reaches a log
    line, in either rendering, or stderr (#588)."""
    failing: list[Any] = (
        [CREDENTIAL_SHAPED, Usage(prompt_tokens=-1, completion_tokens=1)]
        if closing == "llm_round"
        else [CREDENTIAL_SHAPED, Rejected()]
    )
    telemetry, memory = exporting()
    exporter = LlmInputExport(telemetry=telemetry)
    invocations: list[str] = []
    stage_reply = exporter.stage_reply

    def staging(session: str, **round_: Any) -> None:
        invocations.append(round_["invocation"])
        stage_reply(session, **round_)

    exporter.stage_reply = staging  # type: ignore[method-assign]
    session, events = traced(telemetry, ScriptedLlm([failing]), exporter)
    session.websocket = cast(Any, RecordingSocket())

    with caplog.at_level(logging.DEBUG):
        await drive_reply(session, UTTERANCE)

    (invocation,) = invocations
    assert not logged_events(caplog, closing)
    assert outcomes(caplog) == DROPPED
    retained = both_formats(caplog) + capfd.readouterr().err
    assert CREDENTIAL_SHAPED not in retained
    assert REJECTED_NAME not in retained

    round_done(events, invocation=invocation)
    finish_reply(events)
    spans = finished(telemetry, memory)
    (generation,) = _generations(spans)
    assert not CONTENT & set(generation)
    for span in spans:
        assert CREDENTIAL_SHAPED not in repr(dict(span.attributes)), span.name


@pytest.mark.parametrize("closing", ["llm_round", "provider_failed"])
async def test_a_delivered_round_event_counts_the_pair_its_span_took(
    closing: str, caplog: pytest.LogCaptureFixture
) -> None:
    """The other half of the settle: the event's fold wrote the pair, so
    it is counted, once, and its span carries it whole."""
    telemetry, memory = exporting()
    exporter = LlmInputExport(telemetry=telemetry)
    watch, events, turn = _watched(telemetry, exporter)
    _staged(exporter)

    with caplog.at_level(logging.INFO):
        if closing == "llm_round":
            _rounded(watch, turn)
        else:
            _failed(watch)

    assert len(logged_events(caplog, closing)) == 1
    assert outcomes(caplog) == ONE_ROUND
    finish_reply(events)
    (generation,) = _generations(finished(telemetry, memory))
    assert CONTENT <= set(generation)
    assert CREDENTIAL_SHAPED in generation[GEN_AI_OUTPUT_MESSAGES]


# What becomes of the pair, and whether there is an export at all. The
# two `off` builds are the composition's own: no export is built with
# the setting off, nor with telemetry off, and the watch then emits
# exactly what it always did.
def _off(telemetry: Any) -> LlmInputExport | None:
    return build_llm_input_export(
        ServerConfig.model_validate(
            {"telemetry": {"enabled": True, "export_llm_input": False}}
        ),
        telemetry=telemetry,
    )


def _telemetry_off(telemetry: Any) -> LlmInputExport | None:
    del telemetry
    return build_llm_input_export(
        ServerConfig.model_validate({"telemetry": {"enabled": False}}), telemetry=None
    )


def _on(telemetry: Any) -> LlmInputExport | None:
    return LlmInputExport(telemetry=telemetry)


@pytest.mark.parametrize(
    "build, staged_for",
    [
        (_off, None),
        (_telemetry_off, None),
        (_on, SESSION),
        (_on, None),
        (_on, UNTRACED),
    ],
    ids=["export-off", "telemetry-off", "attached", "unstaged", "no-trace"],
)
@pytest.mark.parametrize("closing", ["llm_round", "provider_failed"])
async def test_the_round_event_is_emitted_once_whatever_becomes_of_the_pair(
    build: Any,
    staged_for: str | None,
    closing: str,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """The export owns the emission while it is on, so neither a pair it
    drops nor its absence may take the round's event with it, and
    neither may a pair it attaches say the event twice."""
    telemetry, _ = exporting()
    llm_input = build(telemetry)
    assert (llm_input is None) == (build is not _on)
    watch, _, turn = _watched(telemetry, llm_input)
    if llm_input is not None and staged_for is not None:
        _staged(llm_input, staged_for)

    with caplog.at_level(logging.INFO):
        if closing == "llm_round":
            _rounded(watch, turn)
        else:
            _failed(watch)

    assert len(logged_events(caplog, closing)) == 1
