"""One turn, over the wire, decoded from the bytes a collector receives.

Every other telemetry case reads spans out of an in-memory exporter,
which proves the fold and proves nothing about the transport. This one
boots the real server with `server.telemetry.enabled` on, points
`OTEL_EXPORTER_OTLP_ENDPOINT` at an HTTP receiver running in this
process, drives one utterance through the xiaozhi-sdk device simulator,
and reads what actually arrived: OTLP protobuf, decoded with the proto
package the exporter's own dependency installs.

So what is asserted here is the contract a backend nobody in this
repository controls will read. The session span, the turn span linked to
it and living in a trace of its own, the four stage spans parented
inside the turn, and the GenAI attribute keys spelled exactly as the
conventions spell them.

The bounded-runner rule (#283) applies throughout: the server start, the
conversation, the shutdown and the wait for the export each have a
deadline, and none of them is a bare `while True`.
"""

import asyncio
import gzip
import http.server
import math
import struct
import threading
import time
from typing import Any

import pytest
import uvicorn
from xiaozhi_sdk import XiaoZhiWebsocket

from tests.integration.conftest import booted
from vinga_server.config import Config

pytestmark = pytest.mark.asyncio

MOCK_PROVIDERS = {stage: {"mock": {"type": "mock"}} for stage in ("llm", "asr", "tts", "vad")}
MOCK_AGENT = dict.fromkeys(("llm", "asr", "tts", "vad"), "mock")

DEVICE_MAC = "aa:bb:cc:dd:ee:66"
SAMPLE_RATE = 16000
FRAME_MS = 60
FRAME_BYTES = SAMPLE_RATE * FRAME_MS // 1000 * 2

# Every wait in this module, in seconds. One number per thing waited on,
# because a deadline that is shared is a deadline nobody can read.
REPLY_DEADLINE_S = 15.0
BOOT_DEADLINE_S = 20.0
SHUTDOWN_DEADLINE_S = 30.0

# How close a decoded span's epoch has to land to the instant this case
# ran. Generous, because what it separates is "now" from "a day and a
# half from now".
NOW_ENOUGH_S = 60.0


class Receiver:
    """An OTLP/HTTP collector, in this process and in one thread.

    It accepts exactly what the exporter sends (a POST of protobuf to
    `/v1/traces`, gzipped or not) and keeps the bodies. Answering 200
    with an empty `ExportTraceServiceResponse` is what an OTLP receiver
    owes a client, and it matters here: a client that is refused retries,
    and a retry would make the count of what arrived a function of
    timing.
    """

    def __init__(self) -> None:
        self.bodies: list[bytes] = []
        received = self.bodies

        class Handler(http.server.BaseHTTPRequestHandler):
            def do_POST(self) -> None:  # noqa: N802 (the stdlib's spelling)
                length = int(self.headers.get("content-length", 0))
                body = self.rfile.read(length)
                if self.headers.get("content-encoding") == "gzip":
                    body = gzip.decompress(body)
                if self.path.endswith("/v1/traces"):
                    received.append(body)
                self.send_response(200)
                self.send_header("content-type", "application/x-protobuf")
                self.send_header("content-length", "0")
                self.end_headers()

            def log_message(self, *args: Any) -> None:
                """Silence: this lane's output is the test's."""

        self._server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self._thread = threading.Thread(target=self._server.serve_forever, daemon=True)
        self._thread.start()

    @property
    def endpoint(self) -> str:
        host, port = self._server.server_address[:2]
        return f"http://{host}:{port}"

    def close(self) -> None:
        self._server.shutdown()
        self._server.server_close()
        self._thread.join(timeout=5.0)

    def spans(self) -> list[Any]:
        """Every span in every body, decoded.

        The proto package rides the exporter's own dependency, so this
        decodes with the same definitions the server encoded with rather
        than with a hand-written reader.
        """
        from opentelemetry.proto.collector.trace.v1.trace_service_pb2 import (
            ExportTraceServiceRequest,
        )

        decoded = []
        for body in self.bodies:
            request = ExportTraceServiceRequest()
            request.ParseFromString(body)
            for resource in request.resource_spans:
                for scope in resource.scope_spans:
                    decoded.extend(scope.spans)
        return decoded

    def resources(self) -> list[Any]:
        from opentelemetry.proto.collector.trace.v1.trace_service_pb2 import (
            ExportTraceServiceRequest,
        )

        found = []
        for body in self.bodies:
            request = ExportTraceServiceRequest()
            request.ParseFromString(body)
            found.extend(resource.resource for resource in request.resource_spans)
        return found


def attributes(carrier: Any) -> dict[str, Any]:
    """One protobuf attribute list as the plain mapping a case reads.

    `AnyValue` is a union of five fields and exactly one is set, so the
    value is whichever one the message says it is; anything else would
    be this helper inventing a type the wire did not carry.
    """
    flat = {}
    for pair in carrier.attributes:
        which = pair.value.WhichOneof("value")
        flat[pair.key] = getattr(pair.value, which) if which else None
    return flat


def named(spans: list[Any], name: str) -> Any:
    matching = [span for span in spans if span.name == name]
    assert len(matching) == 1, f"expected one {name} span, got {len(matching)}"
    return matching[0]


@pytest.fixture
def receiver():
    stub = Receiver()
    try:
        yield stub
    finally:
        stub.close()


@pytest.fixture
async def exporting_server(receiver: Receiver, monkeypatch: pytest.MonkeyPatch):
    """A real server with the exporter on, pointed at the stub.

    The endpoint is set before the app is built, because that is when
    the exporter is constructed and the SDK reads its own environment.
    What comes back is the port to talk to and the way to stop it: the
    stop is what flushes, since the lifespan's release shuts the
    exporter down and the shutdown flushes what the batch queue holds.
    """
    monkeypatch.setenv("OTEL_EXPORTER_OTLP_ENDPOINT", receiver.endpoint)
    monkeypatch.delenv("OTEL_EXPORTER_OTLP_HEADERS", raising=False)
    config = Config(
        providers=MOCK_PROVIDERS,
        agents={"assistant": MOCK_AGENT},
        default_agent="assistant",
        server={"telemetry": {"enabled": True}},
    )
    server = uvicorn.Server(
        uvicorn.Config(booted(config), host="127.0.0.1", port=0, log_level="warning")
    )
    task = asyncio.create_task(server.serve())

    async def started() -> None:
        while not server.started:
            if task.done():
                task.result()
            await asyncio.sleep(0.01)

    await asyncio.wait_for(started(), BOOT_DEADLINE_S)
    port = server.servers[0].sockets[0].getsockname()[1]

    async def stop() -> None:
        server.should_exit = True
        await asyncio.wait_for(task, SHUTDOWN_DEADLINE_S)

    yield port, stop
    if not task.done():
        server.should_exit = True
        await asyncio.wait_for(task, SHUTDOWN_DEADLINE_S)


def speech_pcm(duration_ms: int) -> bytes:
    samples = SAMPLE_RATE * duration_ms // 1000
    return b"".join(
        struct.pack("<h", int(8000 * math.sin(2 * math.pi * 300 * n / SAMPLE_RATE)))
        for n in range(samples)
    )


async def one_turn(port: int) -> None:
    """One utterance and the spoken reply to it, as a device does it."""
    spoken = asyncio.Event()

    async def on_message(data: dict) -> None:
        if data.get("type") == "tts" and data.get("state") == "stop":
            spoken.set()

    client = XiaoZhiWebsocket(
        on_message,
        ota_url=f"http://127.0.0.1:{port}/xiaozhi/ota/",
        audio_sample_rate=SAMPLE_RATE,
    )
    try:
        assert await client.init_connection(DEVICE_MAC)
        pcm = speech_pcm(960)
        for start in range(0, len(pcm), FRAME_BYTES):
            assert await client.send_audio(pcm[start : start + FRAME_BYTES])
        await client.send_silence_audio(1.2)
        await asyncio.wait_for(spoken.wait(), REPLY_DEADLINE_S)
    finally:
        await client.close()


async def test_one_turn_arrives_at_a_collector_as_the_trace_it_is(
    exporting_server, receiver: Receiver
) -> None:
    """The milestone's acceptance, end to end and off the wire.

    One conversation, then a shutdown, then the bytes: the session span
    and its turn, the turn in a trace of its own with a link back, and
    the stages parented inside the turn where they happened.
    """
    port, stop = exporting_server
    await one_turn(port)
    # The shutdown is the flush: the batch processor holds spans for its
    # schedule delay, and the lifespan's release drains it under a bound.
    await stop()

    spans = receiver.spans()
    assert spans, "nothing reached the collector at all"
    session, turn = named(spans, "session"), named(spans, "turn")

    # Linked, not parented, and therefore a trace a backend lists on its
    # own rather than a branch inside one enormous session trace.
    assert turn.parent_span_id == b""
    assert turn.trace_id != session.trace_id
    assert [link.span_id for link in turn.links] == [session.span_id]

    # The stages, parented inside the turn and in the turn's own trace.
    stages = {span.name for span in spans if span.parent_span_id == turn.span_id}
    assert stages == {"asr", "llm", "tts_stream", "playback"}
    assert all(
        span.trace_id == turn.trace_id
        for span in spans
        if span.parent_span_id == turn.span_id
    )

    # And when they say they happened, which is a claim only the wire
    # can be asked for: a span whose epoch is hours from now decodes
    # perfectly, satisfies every structural assertion above, and is
    # invisible in a backend, because no search window a person types
    # contains it. That is what one offset across two clocks cost until
    # the Jaeger walkthrough found it, and this lane runs on the plain
    # asyncio loop where the two clocks happen to agree, so what this
    # asserts is the sanity rather than the fix.
    assert all(
        abs(span.start_time_unix_nano / 1e9 - time.time()) < NOW_ENOUGH_S
        for span in spans
    )

    # And the identities every span in the trace is read by, plus what
    # the session opened against: the retained provider context is
    # stamped per stage on the session and on the turn, which is the
    # fact a backend filters a deployment's traces by.
    assert attributes(session)["vinga.device.id"] == DEVICE_MAC
    assert attributes(session)["vinga.provider.llm.type"] == "mock"
    assert attributes(turn)["vinga.provider.asr.name"] == "mock"
    assert attributes(turn)["vinga.turn.outcome"] == "completed"
    assert attributes(named(spans, "asr"))["vinga.asr.outcome"] == "heard"


async def test_the_gen_ai_keys_arrive_spelled_as_the_conventions_spell_them(
    exporting_server, receiver: Receiver
) -> None:
    """The correspondence table, off the wire.

    This lane's providers are the mocks, which have no host, no model
    and no usage to report, and the catalog answers an unreported fact
    with an absent field rather than a zero. So what a decoded round can
    pin here is the key that IS reported, spelled exactly, plus the
    absence of the ones nothing measured: a span carrying
    `gen_ai.usage.input_tokens: 0` against a provider that reported no
    usage would be a number invented on the way out. The whole table's
    values are pinned against a real quartet in the unit lane
    (`test_telemetry_spans.py`).
    """
    port, stop = exporting_server
    await one_turn(port)
    await stop()

    llm = named(receiver.spans(), "llm")
    carried = attributes(llm)

    assert carried["gen_ai.provider.name"] == "mock"
    # The entry's name under the attribute the retained provider context
    # uses for the same fact, rather than a second spelling of it.
    assert carried["vinga.provider.llm.name"] == "mock"
    assert carried["vinga.llm.round"] == 1
    # Nothing the mock did not report, and nothing wearing a foreign
    # prefix that was not asked for.
    assert {key for key in carried if not key.startswith("vinga.")} == {
        "gen_ai.provider.name"
    }
    assert [event.name for event in llm.events] == ["first_token"]


async def test_the_resource_that_arrives_is_the_servers_own(
    exporting_server, receiver: Receiver
) -> None:
    """The no-leak rule, checked where it would actually be broken: on
    the bytes. Every span arrives under a resource of exactly two
    server-owned attributes, whatever the environment says."""
    port, stop = exporting_server
    await one_turn(port)
    await stop()

    resources = receiver.resources()
    assert resources
    for resource in resources:
        carried = attributes(resource)
        assert carried["service.name"] == "vinga-server"
        assert set(carried) == {"service.name", "service.version"}
