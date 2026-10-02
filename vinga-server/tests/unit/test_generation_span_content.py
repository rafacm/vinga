"""A generation's pair is counted once its `llm` span took it (#588).

With `server.telemetry.export_llm_input` on, a round's request and
output are staged for the `llm_round` or `provider_failed` event that
closes it, and `llm_input_exported` counts the pair in `rounds`. What
these cases hold is the accounting: one logical round is one pair
counted, however many attempts the first-token watchdog made at it.

Driven through a real session and the real exporter writing into the
SDK's in-memory exporter, so the handoff these cases prove is the
production one.
"""

import json
import logging
from collections.abc import Iterator
from typing import Any, cast

import pytest

from tests.support.configs import watchdog_config
from tests.support.events import only
from tests.support.llm_input import outcomes, traced
from tests.support.providers import STALL_S, StallingLlm
from tests.support.sessions import drive_reply, run_reply
from tests.support.sockets import RecordingSocket
from tests.support.telemetry import (
    close_session,
    exporting,
    finish_reply,
    finished,
    released,
)
from vinga_server.llm_input_export import LlmInputExport
from vinga_server.telemetry import (
    _QUIETING,
    GEN_AI_INPUT_MESSAGES,
    GEN_AI_OUTPUT_MESSAGES,
    LLM_INVOCATION_ID,
    LLM_SPAN,
)

UTTERANCE = b"\x00\x00" * 320
ONE_ROUND = [("exported", 1, 0)]


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
