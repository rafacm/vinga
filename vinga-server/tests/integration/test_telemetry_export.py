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
import contextlib
import json
import math
import struct
import subprocess
import time
import urllib.parse
import urllib.request
import uuid

import pytest
import uvicorn
from opentelemetry.proto.trace.v1.trace_pb2 import Status
from xiaozhi_sdk import XiaoZhiWebsocket

from tests.integration.conftest import booted
from tests.support.telemetry import (
    Clock,
    Receiver,
    attributes,
    call_tool,
    close_session,
    finish_reply,
    named,
    open_session,
    provider_failed,
    session_events,
    start_turn,
)
from vinga_server.config import Config
from vinga_server.config.models import TelemetryConfig
from vinga_server.events.values import ReplyOutcome
from vinga_server.telemetry import build_telemetry

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

JAEGER_IMAGE = (
    "jaegertracing/jaeger:2.20.0@"
    "sha256:46a886260e04002d8f45e213fc39063fa11a50446048fdaa64786fc0840cb9f8"
)
JAEGER_DEADLINE_S = 30.0
IMAGE_PULL_DEADLINE_S = 300.0


def _run(*args: str, check: bool = True) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        args,
        check=check,
        capture_output=True,
        text=True,
        timeout=JAEGER_DEADLINE_S,
    )


def _pull(image: str) -> None:
    subprocess.run(
        ("docker", "pull", image),
        check=True,
        capture_output=True,
        text=True,
        timeout=IMAGE_PULL_DEADLINE_S,
    )


def _container_logs(name: str) -> str:
    result = _run("docker", "logs", name, check=False)
    return result.stdout + result.stderr


@pytest.fixture
def jaeger():
    """The pinned v2 backend used by the committed direct overlay."""
    name = f"vinga-jaeger-{uuid.uuid4().hex[:12]}"
    _pull(JAEGER_IMAGE)
    try:
        _run(
            "docker",
            "run",
            "--detach",
            "--name",
            name,
            "--publish",
            "127.0.0.1::4318",
            "--publish",
            "127.0.0.1::16686",
            JAEGER_IMAGE,
        )
        otlp = _run("docker", "port", name, "4318/tcp").stdout.strip().rsplit(":", 1)[1]
        query = _run("docker", "port", name, "16686/tcp").stdout.strip().rsplit(":", 1)[1]
        origin = f"http://127.0.0.1:{query}"
        deadline = time.monotonic() + JAEGER_DEADLINE_S
        while time.monotonic() < deadline:
            try:
                with urllib.request.urlopen(f"{origin}/api/services", timeout=2) as response:
                    if response.status == 200:
                        break
            except OSError:
                pass
            time.sleep(0.1)
        else:
            raise AssertionError(_container_logs(name))
        yield f"http://127.0.0.1:{otlp}", origin
    finally:
        _run("docker", "rm", "--force", name, check=False)


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
    async with _exporting_server(receiver.endpoint, monkeypatch) as served:
        yield served


@contextlib.asynccontextmanager
async def _exporting_server(endpoint: str, monkeypatch: pytest.MonkeyPatch):
    """One source-tree server exporting directly to the supplied OTLP host."""
    monkeypatch.setenv("OTEL_EXPORTER_OTLP_ENDPOINT", endpoint)
    monkeypatch.setenv("OTEL_EXPORTER_OTLP_PROTOCOL", "http/protobuf")
    monkeypatch.setenv("OTEL_TRACES_SAMPLER", "always_on")
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

    try:
        yield port, stop
    finally:
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

    # Every stage span carries the session context off the wire too,
    # which is the assertion OTel's own model makes necessary: a child
    # carries its parent's id and none of its parent's attributes, so a
    # backend filtering by device or by session finds only the spans
    # that spell it themselves.
    for span in spans:
        if span.parent_span_id != turn.span_id:
            continue
        carried = attributes(span)
        assert carried["vinga.session.id"], span.name
        assert carried["vinga.device.id"] == DEVICE_MAC, span.name
        assert carried["vinga.agent"] == "assistant", span.name
        assert carried["vinga.conversation.id"], span.name
        # The mocks name no host and no model, so what the resolved
        # entries can say here is the entry and its type. The stage
        # asserted for all four is the ASR one because it is the one
        # every span here answers with the same word: the round and the
        # stream spans answer for their own stages and carry the
        # session's ASR entry, and the ASR span answers for that stage
        # itself with the entry the transcription actually ran on, which
        # in this lane is the same mock.
        assert carried["vinga.provider.asr.name"] == "mock", span.name

    # And the identities every span in the trace is read by, plus what
    # the session opened against: the retained provider context is
    # stamped per stage on the session and on the turn, which is the
    # fact a backend filters a deployment's traces by.
    assert attributes(session)["vinga.device.id"] == DEVICE_MAC
    assert attributes(session)["vinga.provider.llm.type"] == "mock"
    assert attributes(turn)["vinga.provider.asr.name"] == "mock"
    assert attributes(turn)["vinga.turn.outcome"] == "completed"
    assert attributes(named(spans, "asr"))["vinga.asr.outcome"] == "heard"


async def test_one_source_tree_turn_arrives_directly_in_jaeger(
    jaeger: tuple[str, str], monkeypatch: pytest.MonkeyPatch
) -> None:
    """The supported direct path terminates in the pinned Jaeger v2 API."""
    endpoint, query_origin = jaeger
    async with _exporting_server(endpoint, monkeypatch) as (port, stop):
        await one_turn(port)
        await stop()

    query = urllib.parse.urlencode(
        {"service": "vinga-server", "lookback": "1h", "limit": "20"}
    )
    deadline = time.monotonic() + JAEGER_DEADLINE_S
    traces: list[dict] = []
    while time.monotonic() < deadline:
        with urllib.request.urlopen(
            f"{query_origin}/api/traces?{query}", timeout=3
        ) as response:
            traces = json.load(response)["data"]
        names = {
            span["operationName"]
            for trace in traces
            for span in trace.get("spans", [])
        }
        if {"session", "turn", "asr", "llm", "tts_stream", "playback"} <= names:
            break
        await asyncio.sleep(0.1)
    else:
        raise AssertionError(f"Jaeger did not expose the source-tree topology: {traces!r}")

    by_name = {
        span["operationName"]: span
        for trace in traces
        for span in trace["spans"]
    }
    assert by_name["session"]["traceID"] != by_name["turn"]["traceID"]
    turn_id = by_name["turn"]["spanID"]
    for name in ("asr", "llm", "tts_stream", "playback"):
        references = by_name[name]["references"]
        assert any(
            reference["refType"] == "CHILD_OF" and reference["spanID"] == turn_id
            for reference in references
        ), name


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
    # prefix that was not asked for. The grouping alias is in the set by
    # name, because it is the one foreign-prefixed attribute every span
    # carries whatever its stage did (#67 M1); the case below is what
    # holds it to its value.
    assert {key for key in carried if not key.startswith("vinga.")} == {
        "gen_ai.provider.name",
        "session.id",
    }
    assert [event.name for event in llm.events] == ["first_token"]


async def test_the_session_id_arrives_under_the_grouping_alias_too(
    exporting_server, receiver: Receiver
) -> None:
    """The #67 M1 finding, off the wire.

    A backend that groups traces into sessions keys that grouping on an
    attribute of its own vocabulary, and `vinga.session.id` is not one:
    against a live Langfuse the whole conversation arrived as unrelated
    traces with an empty session until every span also spelled the
    generic `session.id`. So what this pins is the bytes a collector
    receives, which is the only surface that claim can be made on: both
    names on every span, and the same value under each, since two
    spellings are only safe while they are one fact.
    """
    port, stop = exporting_server
    await one_turn(port)
    await stop()

    spans = receiver.spans()
    assert spans, "nothing reached the collector at all"
    for span in spans:
        carried = attributes(span)
        assert carried["session.id"], span.name
        assert carried["session.id"] == carried["vinga.session.id"], span.name


async def test_failed_operations_replace_their_turn_events_on_the_wire(
    receiver: Receiver, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A collector receives each failure once, as the operation itself.

    This drives the fold directly so both failure variants can share one
    decoded trace without teaching the server fixture test-only provider
    behavior. The exporter and HTTP receiver are the real transport: the
    assertions below are against the protobuf a backend receives.
    """
    monkeypatch.setenv("OTEL_EXPORTER_OTLP_ENDPOINT", receiver.endpoint)
    monkeypatch.delenv("OTEL_EXPORTER_OTLP_HEADERS", raising=False)
    telemetry = build_telemetry(TelemetryConfig(enabled=True))
    assert telemetry is not None
    events = session_events(Clock(), telemetry)

    try:
        open_session(events)
        start_turn(events)
        provider_failed(events, stage="llm")
        call_tool(events, which="mcp", is_error=True)
        finish_reply(events, outcome=ReplyOutcome.FAILED, sentences=0)
        close_session(events)
    finally:
        telemetry.release()

    spans = receiver.spans()
    assert spans, "nothing reached the collector at all"
    turn = named(spans, "turn")
    llm, tool = named(spans, "llm"), named(spans, "tool")

    assert llm.parent_span_id == turn.span_id
    assert tool.parent_span_id == turn.span_id
    assert llm.status.code == Status.STATUS_CODE_ERROR
    assert tool.status.code == Status.STATUS_CODE_ERROR
    assert attributes(llm)["error.type"] == "TimeoutError"
    assert attributes(tool)["error.type"] == "tool_error"
    assert not {event.name for event in turn.events} & {
        "provider_failed",
        "tool_call",
    }


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
