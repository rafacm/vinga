"""What was said leaving the host, off the wire and under the hostile
shapes.

The unit lane fakes both seams and proves everything that is vinga's:
the refusals, the barrier, the bound, the worker, the paging, the
reasons. Three claims it cannot make are here.

**The wire claim.** A real server with recording, telemetry and the
export on, a real device conversation with a handover, the real close
ordering, and a real OTLP collector on a socket in this process. What
that certifies is the protobuf a backend actually receives: one
observation per turn in the session's own trace, the text in the two
fields the backend renders as input and output, the legs as the exact
canonical JSON string, and the transcript present in those attributes
and nowhere else on the wire.

**The hostile backend.** One that accepts the connection and never
answers, which is the failure the shared span queue has no answer for
and the reason this surface delivers as a bounded call at all. Three
latencies are asserted separately, because they are three different
promises: the session's close is unaffected, the failure event fires
inside the exporter's own deadline, and the shutdown finishes inside
its own bound.

**The wedged store.** A real conversation writer parked in front of its
own transaction, so the close acknowledgement genuinely never settles.
That is what `unrecorded` is for, and a fake handle cannot certify that
a real writer's barrier behaves this way under a gate.
"""

import asyncio
import contextlib
import json
import logging
import socket
import threading
import time
from collections.abc import Iterator
from typing import Any

import pytest

from tests.support.events import both_formats
from tests.support.sessions import Gate
from tests.support.stores import CONVERSATIONS_MANIFEST
from tests.support.telemetry import (
    Clock,
    Receiver,
    attributes,
    close_session,
    open_session,
    session_events,
)
from tests.support.transcripts import a_row, reading, settled
from vinga_server.config import Config
from vinga_server.config.models import (
    ConversationsConfig,
    DatabaseConfig,
    ServerConfig,
    TelemetryConfig,
)
from vinga_server.conversations.store import ConversationStore
from vinga_server.telemetry import Telemetry, build_telemetry
from vinga_server.transcript_export import TranscriptExport

pytestmark = pytest.mark.asyncio

SWITCHER_MAC = "aa:bb:cc:dd:ee:95"

# The utterance every turn is transcribed to, and the sentinel this lane
# hunts: it is content this surface IS authorized to send, so the claim
# about it is where it may appear rather than that it may not.
HEARD = "tell me the secret 0TRANSCRIPT-WIRE-SENTINEL"

POET_TONE = 440
TUTOR_TONE = 660


def exporting_config() -> Config:
    """A device bound to two agents, the first scripted to hand the
    conversation over, with recording and the transcript export on.

    The handover is what makes the legs real: a reply split between two
    agents is the one turn whose per-leg attribution exists at all.
    """
    return Config(
        providers={
            "llm": {
                "handover": {
                    "type": "mock",
                    "reply": "I cannot: {tool_result}",
                    "tool_when": "secret",
                    "tool_name": "switch_agent",
                    "tool_arguments": {"agent": "tutor"},
                },
                "plain": {"type": "mock", "reply": "{system} here, hello."},
            },
            "asr": {"mock": {"type": "mock", "text": HEARD}},
            "tts": {
                "tenor": {"type": "mock", "tone_hz": POET_TONE},
                "alto": {"type": "mock", "tone_hz": TUTOR_TONE},
            },
            "vad": {"mock": {"type": "mock"}},
        },
        agent_defaults={"asr": "mock", "vad": "mock"},
        agents={
            "poet": {"prompt": "POET", "llm": "handover", "tts": "tenor"},
            "tutor": {"prompt": "TUTOR", "llm": "plain", "tts": "alto"},
        },
        devices={SWITCHER_MAC: ["poet", "tutor"]},
        default_agent="poet",
        server=ServerConfig(
            conversations=ConversationsConfig(enabled=True, text=True),
            telemetry=TelemetryConfig(enabled=True, export_transcripts=True),
        ),
    )


async def exported(caplog: pytest.LogCaptureFixture, timeout_s: float = 20.0) -> None:
    """Wait for the export to have said what became of it.

    The wait is the lane's own half of the contract rather than
    politeness: a shutdown INTERRUPTS this exporter, so a case that left
    the server before the worker reached the job would be driving the
    drop path whatever it meant to drive.
    """
    loop = asyncio.get_running_loop()
    deadline = loop.time() + timeout_s
    while loop.time() < deadline:
        if any(
            getattr(record, "event", None)
            in ("transcripts_exported", "transcript_export_failed")
            for record in caplog.records
        ):
            return
        await asyncio.sleep(0.05)
    raise AssertionError("the export said nothing at all within the bound")


def transcripts(spans: list[Any]) -> list[Any]:
    return [span for span in spans if span.name == "transcript"]


# --- the wire ----------------------------------------------------------


async def test_a_conversations_turns_arrive_as_observations_on_its_trace(
    serve, simulate, caplog: pytest.LogCaptureFixture, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The acceptance, decoded from the protobuf a collector received.

    Nothing here reaches into the server: the configuration says record
    and export, a device talks, a handover splits the reply, and what is
    asserted is what arrived at an OTLP endpoint on a socket.
    """
    caplog.set_level(logging.INFO)
    collector = Receiver()
    monkeypatch.setenv("OTEL_EXPORTER_OTLP_ENDPOINT", collector.endpoint)

    try:
        async with serve(exporting_config()) as port:
            await simulate(port, SWITCHER_MAC)
            await exported(caplog)
        spans = collector.spans()
    finally:
        collector.close()

    assert spans, "nothing reached the collector at all"
    written = transcripts(spans)
    # Two turns, because this is what a mock-driven handover actually
    # records: the first agent's reply was the switch itself and spoke
    # nothing, and the second agent answered in a turn of its own. One
    # observation each, in the store's own order.
    assert len(written) == 2
    first, second = (attributes(one) for one in written)

    # The text, in the two fields the backend renders as an
    # observation's own input and output. This is the claim the
    # milestone's gate was run for, off the wire.
    assert first["langfuse.observation.input"] == HEARD
    assert second["langfuse.observation.output"] == "TUTOR here, hello."
    # The ordinal, session-local and one-based, with the store's own row
    # id beside it as a separate fact.
    assert [first["vinga.turn.index"], second["vinga.turn.index"]] == [1, 2]
    assert first["vinga.turn.id"] > 0
    assert second["vinga.turn.id"] > first["vinga.turn.id"]
    assert first["vinga.turn.t_ms"] >= 0
    # The agent each turn opened with, which is how a reader follows a
    # handover: the conversation moved between these two rows.
    assert first["vinga.agent"] == "poet"
    assert second["vinga.agent"] == "tutor"
    # The legs, as ONE canonical JSON string on the wire rather than as
    # a structure: span attributes take primitives and never mappings.
    # Allowlisted to the two fields, which this pipeline proves rather
    # than states, because the stored column also holds the per-leg
    # token counts and none of them is here.
    legs = first["langfuse.observation.metadata.legs"]
    assert legs == '[{"agent":"poet"}]'
    assert json.loads(legs) == [{"agent": "poet"}]
    assert "tokens" not in legs
    # In the session's own trace and under the session span, which is
    # what makes a reader who opened the session find the words rather
    # than having to know they exist.
    session_span = next(span for span in spans if span.name == "session")
    assert {span.trace_id for span in written} == {session_span.trace_id}
    assert {span.parent_span_id for span in written} == {session_span.span_id}
    assert first["session.id"] == attributes(session_span)["session.id"]
    assert first["vinga.session.id"] == attributes(session_span)["vinga.session.id"]


async def test_the_transcript_is_on_the_transcript_spans_and_nowhere_else(
    serve, simulate, caplog: pytest.LogCaptureFixture, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The sentinel claim, made on the wire rather than in this process.

    What was said is authorized onto the transcript observation and
    nowhere else: every other span of every trace is derived from the
    structured events, which carry no text by construction, and this is
    that construction checked against the bytes a backend receives.
    """
    caplog.set_level(logging.DEBUG)
    collector = Receiver()
    monkeypatch.setenv("OTEL_EXPORTER_OTLP_ENDPOINT", collector.endpoint)

    try:
        async with serve(exporting_config()) as port:
            await simulate(port, SWITCHER_MAC)
            await exported(caplog)
        spans = collector.spans()
        bodies = list(collector.bodies)
    finally:
        collector.close()

    carrying = [span for span in spans if HEARD in repr(attributes(span))]
    assert [span.name for span in carrying] == ["transcript"]
    # And it is on the wire exactly once, which is what says no second
    # copy rode some span's events or a resource attribute.
    assert sum(body.count(HEARD.encode()) for body in bodies) == 1
    # Never in this server's own records, which is the surface the
    # events keep metadata-only. This server's channels alone: the
    # device protocol carries the transcript back to the board that
    # spoke it, and what the test's own websocket client writes down
    # about that is not something this server chose to write.
    assert HEARD not in both_formats(caplog)


async def test_a_deployment_with_the_flag_off_exports_no_transcript(
    serve, simulate, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The default, from the wire's end: the same conversation, the same
    collector, the same recording, and not one observation carrying a
    word of it."""
    collector = Receiver()
    monkeypatch.setenv("OTEL_EXPORTER_OTLP_ENDPOINT", collector.endpoint)
    config = exporting_config()
    config.server.telemetry = TelemetryConfig(enabled=True)

    try:
        async with serve(config) as port:
            await simulate(port, SWITCHER_MAC)
            await asyncio.sleep(0.5)
        spans = collector.spans()
        bodies = list(collector.bodies)
    finally:
        collector.close()

    assert spans, "nothing reached the collector at all"
    assert transcripts(spans) == []
    assert not any(HEARD.encode() in body for body in bodies)


# --- the hostile backend ----------------------------------------------


class Withholding:
    """A real listening endpoint that accepts the connection, reads the
    request and then says nothing at all until it is released.

    The `test_telemetry_hardening.py` shape, and here for the reason it
    is there: an address that REFUSES costs an exporter nothing whatever
    it does, and an unroutable one is only slow if the network treats it
    as one.
    """

    def __init__(self) -> None:
        self.entered = threading.Event()
        self.release = threading.Event()
        self._socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self._socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self._socket.bind(("127.0.0.1", 0))
        self._socket.listen(8)
        self._held: list[socket.socket] = []
        self._thread = threading.Thread(target=self._serve, daemon=True)
        self._thread.start()

    @property
    def url(self) -> str:
        host, port = self._socket.getsockname()[:2]
        return f"http://{host}:{port}"

    def _serve(self) -> None:
        while not self.release.is_set():
            try:
                connection, _ = self._socket.accept()
            except OSError:
                return
            self._held.append(connection)
            threading.Thread(target=self._hold, args=(connection,), daemon=True).start()

    def _hold(self, connection: socket.socket) -> None:
        try:
            connection.settimeout(5.0)
            connection.recv(65536)
        except OSError:
            return
        self.entered.set()
        self.release.wait(120.0)
        with contextlib.suppress(OSError):
            connection.close()

    def close(self) -> None:
        self.release.set()
        with contextlib.suppress(OSError):
            self._socket.close()
        for connection in self._held:
            with contextlib.suppress(OSError):
                connection.close()
        self._thread.join(timeout=5.0)


def a_retained_session(telemetry: Telemetry, session: str) -> None:
    """One whole session through the real exporter, which is what puts a
    trace in the retention for a job to be admitted on."""
    clock = Clock()
    events = session_events(clock, telemetry, session=session)
    open_session(events)
    clock.tick(1.0)
    close_session(events)


def outcomes(caplog: pytest.LogCaptureFixture) -> list[str]:
    return [
        str(getattr(record, "reason", ""))
        for record in caplog.records
        if getattr(record, "event", None) == "transcript_export_failed"
    ]


async def test_a_backend_that_never_answers_costs_three_bounded_things(
    caplog: pytest.LogCaptureFixture, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The hostile shape, with the real OTLP exporter and the real HTTP
    stack.

    Three promises, asserted separately because they are three:

    - the session's close is unaffected, which is what "off the audio
      path" means and is measured as the time `session_closed` takes;
    - the failure event fires inside the exporter's own deadline, which
      is the whole reason delivery is a bounded call: riding the shared
      queue, an unreachable backend would produce no event at all;
    - and the shutdown finishes inside its own bound, because a backend
      that has stopped answering must not hold a redeploy open.
    """
    caplog.set_level(logging.DEBUG)
    backend = Withholding()
    session = "1111111111111111aaaaaaaaaaaaaaaa"
    monkeypatch.setenv("OTEL_EXPORTER_OTLP_ENDPOINT", backend.url)
    # The call's bound is the exporter's OWN deadline, read from the
    # environment the SDK already reads, which is what this shortens:
    # the ceiling is the operator's to set and this module never touches
    # it.
    monkeypatch.setenv("OTEL_EXPORTER_OTLP_TIMEOUT", "2")
    telemetry = build_telemetry(TelemetryConfig(enabled=True))
    assert telemetry is not None
    a_retained_session(telemetry, session)
    door, _ = reading({session: [a_row(1)]})
    exporter = TranscriptExport(
        telemetry=telemetry,
        reads=door,
        backlog=4,
        acknowledgement_timeout_s=2.0,
        shutdown_timeout_s=1.0,
    )

    try:
        began = time.monotonic()
        exporter.session_closed(session, settled())
        closing = time.monotonic() - began

        # The close read a map and put a job on a queue: no request, no
        # wait, no lock the export holds.
        assert closing < 0.5, f"the close took {closing:.2f} s with a wedged backend"
        assert backend.entered.wait(20.0), "the export never reached the backend"

        deadline = time.monotonic() + 20.0
        while time.monotonic() < deadline and not outcomes(caplog):
            await asyncio.sleep(0.05)
        assert outcomes(caplog) == ["undelivered"], (
            "no failure event fired, so the delivery had no ceiling"
        )

        began = time.monotonic()
        await exporter.shutdown()
        assert time.monotonic() - began < 5.0, "the shutdown was not bounded"
    finally:
        backend.close()
        await exporter.shutdown()
        telemetry.release()


# --- the wedged store --------------------------------------------------


async def test_a_wedged_store_costs_a_close_nothing_and_says_unrecorded(
    caplog: pytest.LogCaptureFixture, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A real conversation writer parked in front of its own
    transaction, which is what makes this an integration claim: the
    barrier the export waits on is a real handle from a real writer, and
    what a gate proves is that a store which never commits produces
    `unrecorded` rather than a worker that waits forever.
    """
    caplog.set_level(logging.DEBUG)
    collector = Receiver()
    monkeypatch.setenv("OTEL_EXPORTER_OTLP_ENDPOINT", collector.endpoint)
    session = "2222222222222222bbbbbbbbbbbbbbbb"
    gate = Gate()
    store = ConversationStore(DatabaseConfig(), gate=gate)
    telemetry = build_telemetry(TelemetryConfig(enabled=True))
    assert telemetry is not None
    a_retained_session(telemetry, session)
    door, read = reading({session: [a_row(1)]})
    exporter = TranscriptExport(
        telemetry=telemetry,
        reads=door,
        backlog=4,
        acknowledgement_timeout_s=1.0,
        shutdown_timeout_s=5.0,
    )

    try:
        store.start()
        store.open_session(session, 100.0, dict(CONVERSATIONS_MANIFEST))
        # The writer is now parked in front of the open's own
        # transaction, so everything behind it, the close included, is
        # a record nothing will settle.
        gate.wait()

        began = time.monotonic()
        recorded = store.close_session(session, duration_s=1.0, reason="idle")
        closing = time.monotonic() - began
        exporter.session_closed(session, recorded)

        assert closing < 0.5, f"the close took {closing:.2f} s against a wedged store"
        deadline = time.monotonic() + 10.0
        while time.monotonic() < deadline and not outcomes(caplog):
            await asyncio.sleep(0.05)

        assert outcomes(caplog) == ["unrecorded"]
        assert read.calls == [], "the store was read past its own barrier"
    finally:
        gate.open_forever()
        await exporter.shutdown()
        store.stop()
        telemetry.release()
        collector.close()


@pytest.fixture(autouse=True)
def _no_lease_outlives_its_case() -> Iterator[None]:
    """These cases wedge exporters on purpose, so a lease that did not go
    back would leave the rest of this lane running against a silenced
    OpenTelemetry."""
    yield
    assert logging.getLogger("opentelemetry").propagate is not False
