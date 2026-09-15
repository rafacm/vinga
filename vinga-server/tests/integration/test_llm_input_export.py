"""What the model saw and generated on its actual generation spans.

The unit lanes fake the one seam each and prove everything that is
vinga's: the refusals, the stage, the bound, the drop accounting, the
worker, the reasons, and which call shapes stage at all. Two claims they
cannot make are here.

**The wire claim.** A real server with telemetry and the export on, a
real device conversation, the real close ordering, and a real OTLP
collector on a socket in this process. What that certifies is the
protobuf a backend actually receives: one observation per logical round,
on the trace the session was exported under, with the assembled request
in the field the backend renders as an observation's input.

It is also the whole of what this milestone's live gate could be
verified as here. The gate itself wants a real backend and asks whether
an assembled request arrives rendered as an observation's input with
tool arguments and results present; this asserts the same attributes on
the same encoding, one hop short of a backend.

**The close claim.** Nothing in this file reaches into the server, so
what carries the staged rounds from a conversation to the exporter is
the device session's own close path. A unit case can only call the
hand-over itself, which proves the exporter and not the wiring; this is
where the wiring is proved, because the only thing driving it is a
device that stopped talking.
"""

import asyncio
import logging
from typing import Any

import pytest

from tests.integration.conftest import mock_voice
from tests.support.events import both_formats
from tests.support.telemetry import Receiver, attributes
from vinga_server.config import Config
from vinga_server.config.models import ServerConfig, TelemetryConfig

pytestmark = pytest.mark.asyncio

TALKER_MAC = "aa:bb:cc:dd:ee:96"

# The utterance every turn is transcribed to, and the sentinel this lane
# hunts. It is content this surface IS authorized to send, so the claim
# about it is where it may appear rather than that it may not: it is in
# the history the model was given, so it has to be in the request and in
# nothing else on the wire.
HEARD = "tell me the secret 0LLMINPUT-WIRE-SENTINEL"

# And what the agent's own prompt says, which is the other half of an
# assembled request and the half no other surface here carries at all.
PROMPT = "POET-0LLMINPUT-PROMPT-SENTINEL"
MAX_OTLP_BODY_BYTES = 3 * 1024 * 1024


def exporting_config() -> Config:
    """One device, one agent, telemetry on and the LLM input export on.

    Deliberately without `conversations`: this class answers to no
    second switch, so a deployment that records nothing still exports
    what its model was given, and a configuration that recorded would
    leave the claim ambiguous about which surface the text arrived from.
    """
    return Config(
        providers={
            "llm": {"plain": {"type": "mock", "reply": "{system} here, hello."}},
            "asr": {"mock": {"type": "mock", "text": HEARD}},
            "tts": {"tenor": mock_voice(tone_hz=440)},
            "vad": {"mock": {"type": "mock"}},
        },
        agent_defaults={"asr": "mock", "vad": "mock"},
        agents={"poet": {"prompt": PROMPT, "llm": "plain", "tts": "tenor"}},
        devices={TALKER_MAC: ["poet"]},
        default_agent="poet",
        server=ServerConfig(
            telemetry=TelemetryConfig(enabled=True, export_llm_input=True)
        ),
    )


async def exported(caplog: pytest.LogCaptureFixture, timeout_s: float = 20.0) -> None:
    """Wait for the export to have said what became of it.

    The lane's own half of the contract rather than politeness: a
    shutdown INTERRUPTS this exporter, so a case that left the server
    before the worker reached the job would be driving the drop path
    whatever it meant to drive.
    """
    loop = asyncio.get_running_loop()
    deadline = loop.time() + timeout_s
    while loop.time() < deadline:
        if any(
            getattr(record, "event", None)
            in ("llm_input_exported", "llm_input_export_failed")
            for record in caplog.records
        ):
            return
        await asyncio.sleep(0.05)
    raise AssertionError("the export said nothing at all within the bound")


def generations(spans: list[Any]) -> list[Any]:
    return [span for span in spans if span.name == "llm"]


async def test_a_conversations_assembled_requests_arrive_as_observations(
    serve, simulate, caplog: pytest.LogCaptureFixture, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The acceptance, decoded from the protobuf a collector received,
    and the close path that put it there.

    Nothing here reaches into the server: the configuration says export,
    a device talks, the device stops talking, and what is asserted is
    what arrived at an OTLP endpoint on a socket. The hand-over from the
    device session to the exporter has no other driver, so a close that
    stopped handing the stage over fails here and nowhere else.
    """
    caplog.set_level(logging.INFO)
    collector = Receiver(MAX_OTLP_BODY_BYTES)
    monkeypatch.setenv("OTEL_EXPORTER_OTLP_ENDPOINT", collector.endpoint)

    try:
        async with serve(exporting_config()) as port:
            await simulate(port, TALKER_MAC)
            await exported(caplog)
        spans = collector.spans()
    finally:
        collector.close()

    assert spans, "nothing reached the collector at all"
    written = generations(spans)
    assert written, "the generation was not exported"
    said = attributes(written[0])

    # The request, in the field the backend renders as an observation's
    # input, carrying both halves of what was assembled: the agent's own
    # system prompt, and the history the model was given.
    assert PROMPT in said["gen_ai.system_instructions"]
    assert HEARD in said["gen_ai.input.messages"]
    assert HEARD in said["langfuse.observation.input"]
    assert "POET" in said["gen_ai.output.messages"]
    # And the facts a reader puts the observations in order by.
    assert said["vinga.llm.round"] == 1
    assert said["vinga.llm.purpose"] == "reply"
    assert said["vinga.agent"] == "poet"

    turn_span = next(span for span in spans if span.name == "turn")
    assert written[0].trace_id == turn_span.trace_id
    assert written[0].parent_span_id == turn_span.span_id


async def test_nothing_of_the_request_is_anywhere_else_on_the_wire(
    serve, simulate, caplog: pytest.LogCaptureFixture, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The sentinel claim, made on the wire rather than in this process.

    The prompt is content only this class carries, so it has to be in
    exactly one attribute of exactly one span, and in no log record this
    server wrote on the way there. A metadata span that gained a copy of
    it, or a log line that rendered one, fails here.
    """
    caplog.set_level(logging.DEBUG)
    collector = Receiver(MAX_OTLP_BODY_BYTES)
    monkeypatch.setenv("OTEL_EXPORTER_OTLP_ENDPOINT", collector.endpoint)

    try:
        async with serve(exporting_config()) as port:
            await simulate(port, TALKER_MAC)
            await exported(caplog)
        spans = collector.spans()
    finally:
        collector.close()

    carrying = [
        (span.name, name)
        for span in spans
        for name, value in attributes(span).items()
        if isinstance(value, str) and PROMPT in value
    ]
    assert carrying == [
        ("llm", "gen_ai.system_instructions"),
        ("llm", "gen_ai.output.messages"),
        ("llm", "langfuse.observation.output"),
    ], carrying
    assert PROMPT not in both_formats(caplog)


async def test_the_flag_off_puts_no_such_span_on_the_wire(
    serve, simulate, caplog: pytest.LogCaptureFixture, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The default, from the wire's end: the same conversation on the
    same traced server, with the flag off, sends the metadata it always
    did and not a word of what the model was given."""
    caplog.set_level(logging.INFO)
    collector = Receiver(MAX_OTLP_BODY_BYTES)
    monkeypatch.setenv("OTEL_EXPORTER_OTLP_ENDPOINT", collector.endpoint)
    config = exporting_config()
    config.server.telemetry = TelemetryConfig(enabled=True)

    try:
        async with serve(config) as port:
            await simulate(port, TALKER_MAC)
            await asyncio.sleep(0.5)
        spans = collector.spans()
    finally:
        collector.close()

    assert spans, "the traced server exported nothing at all"
    assert generations(spans), "ordinary generation metadata was not exported"
    assert not any(
        PROMPT in value
        for span in spans
        for value in attributes(span).values()
        if isinstance(value, str)
    )
