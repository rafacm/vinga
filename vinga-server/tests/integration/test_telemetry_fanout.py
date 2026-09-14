"""The committed Collector graph, exercised against two real receivers.

The Collector runs from the exact pinned image and exact committed config.
Synthetic OTLP spans make the assertions deterministic: one trace-id sampler
chooses a proper subset, the two forward branches attempt the same trace
population, and only the backend adapter differs. Raw content and credentials
are checked on the complete protobuf bodies and Collector log, not only on a
selected attribute projection.
"""

import base64
import contextlib
import hashlib
import subprocess
import time
import urllib.request
import uuid
from collections.abc import Iterator
from pathlib import Path
from typing import Any

from opentelemetry.proto.collector.trace.v1.trace_service_pb2 import (
    ExportTraceServiceRequest,
)
from opentelemetry.proto.common.v1.common_pb2 import AnyValue, KeyValue
from opentelemetry.proto.trace.v1.trace_pb2 import Status

from tests.support.telemetry import Receiver, attributes

REPO = Path(__file__).resolve().parents[3]
CONFIG = REPO / "deploy" / "telemetry" / "collector.yml"
IMAGE = (
    "otel/opentelemetry-collector-contrib:0.160.0@"
    "sha256:799dc6cf12c96192af37b5bdba804da8c10b3bc563b43cb90c3f3c58d9572ad6"
)

RAW_EMAIL = "trace.person@example.test"
MASKED_EMAIL = "[email]"
MASKED_CREDENTIAL = "[credential]"
PUBLIC_KEY = "pk-lf-fanout-smoke-not-real"
SECRET_KEY = "sk-lf-fanout-smoke-not-real"
TRACE_COUNT = 64
SAMPLE_PERCENTAGE = "25"
DEADLINE_S = 30.0
IMAGE_PULL_DEADLINE_S = 300.0

CANONICAL_CONTENT = {
    "vinga.turn.input",
    "vinga.turn.output",
    "vinga.turn.legs",
    "gen_ai.system_instructions",
    "gen_ai.input.messages",
    "gen_ai.output.messages",
    "vinga.llm.tools",
    "vinga.llm.tool_choice",
}
LANGFUSE_CONTENT = {
    "langfuse.observation.input",
    "langfuse.observation.output",
    "langfuse.observation.metadata.legs",
}
CONTENT_ATTRIBUTES = CANONICAL_CONTENT | LANGFUSE_CONTENT


def _run(*args: str, check: bool = True) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        args,
        check=check,
        capture_output=True,
        text=True,
        timeout=DEADLINE_S,
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


@contextlib.contextmanager
def _collector(jaeger: Receiver, langfuse: Receiver) -> Iterator[tuple[str, str]]:
    name = f"vinga-fanout-{uuid.uuid4().hex[:12]}"
    _pull(IMAGE)
    try:
        _run(
            "docker",
            "run",
            "--detach",
            "--name",
            name,
            "--add-host",
            "host.docker.internal:host-gateway",
            "--publish",
            "127.0.0.1::4318",
            "--env",
            f"JAEGER_OTLP_ENDPOINT=http://host.docker.internal:{jaeger.port}",
            "--env",
            f"LANGFUSE_OTLP_ENDPOINT=http://host.docker.internal:{langfuse.port}",
            "--env",
            f"LANGFUSE_PUBLIC_KEY={PUBLIC_KEY}",
            "--env",
            f"LANGFUSE_SECRET_KEY={SECRET_KEY}",
            "--env",
            f"TELEMETRY_SAMPLE_PERCENTAGE={SAMPLE_PERCENTAGE}",
            "--volume",
            f"{CONFIG}:/etc/otelcol-contrib/config.yaml:ro",
            IMAGE,
            "--config=/etc/otelcol-contrib/config.yaml",
        )
        mapping = _run("docker", "port", name, "4318/tcp").stdout.strip()
        port = mapping.rsplit(":", 1)[1]
        endpoint = f"http://127.0.0.1:{port}/v1/traces"
        _wait_for_collector(endpoint, name)
        yield endpoint, name
    finally:
        _run("docker", "rm", "--force", name, check=False)


def _wait_for_collector(endpoint: str, name: str) -> None:
    deadline = time.monotonic() + DEADLINE_S
    empty = ExportTraceServiceRequest().SerializeToString()
    while time.monotonic() < deadline:
        running = _run(
            "docker", "inspect", "--format", "{{.State.Running}}", name
        ).stdout.strip()
        if running != "true":
            raise AssertionError(_container_logs(name))
        try:
            _post(endpoint, empty)
            return
        except OSError:
            pass
        time.sleep(0.1)
    raise AssertionError(
        f"Collector did not accept OTLP within {DEADLINE_S}s\n{_container_logs(name)}"
    )


def _post(endpoint: str, body: bytes) -> None:
    request = urllib.request.Request(
        endpoint,
        data=body,
        headers={"content-type": "application/x-protobuf"},
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=5) as response:
        assert response.status == 200


def _attribute(key: str, value: str) -> KeyValue:
    return KeyValue(key=key, value=AnyValue(string_value=value))


def _request() -> bytes:
    request = ExportTraceServiceRequest()
    resource = request.resource_spans.add()
    resource.resource.attributes.append(_attribute("service.name", "vinga-server"))
    scope = resource.scope_spans.add()
    scope.scope.name = "vinga-server"

    for index in range(1, TRACE_COUNT + 1):
        # The sampler reads bits from the trace id. A sequential integer
        # encoded into the low end can put every example on one side of
        # its threshold, while this stable spread exercises both sides.
        trace_id = hashlib.sha256(f"trace-{index}".encode()).digest()[:16]
        for offset, name in enumerate(("turn", "capture"), start=1):
            span = scope.spans.add()
            span.trace_id = trace_id
            span.span_id = (index * 10 + offset).to_bytes(8, "big")
            span.name = name
            span.start_time_unix_nano = 1_800_000_000_000_000_000 + index * 1_000
            span.end_time_unix_nano = span.start_time_unix_nano + 500
            span.status.code = Status.STATUS_CODE_ERROR
            # Deliberately violates vinga's safe-error rule so the
            # Collector's defensive credential mask is tested too.
            span.status.message = f"failed with {SECRET_KEY}"
            span.attributes.extend(
                [
                    _attribute("session.id", "fanout-session"),
                    *(
                        _attribute(key, f"mail {RAW_EMAIL} token {SECRET_KEY}")
                        for key in sorted(CONTENT_ATTRIBUTES)
                    ),
                    _attribute("vinga.safe.error.type", "ProviderError"),
                ]
            )
            if name == "capture":
                span.attributes.append(
                    _attribute("langfuse.observation.metadata.capture_audio", "media-token")
                )
    return request.SerializeToString()


def _trace_ids(receiver: Receiver, *, name: str = "turn") -> set[bytes]:
    return {span.trace_id for span in receiver.spans() if span.name == name}


def _canonical(span: Any) -> tuple[Any, ...]:
    carried = {
        key: value
        for key, value in attributes(span).items()
        if not key.startswith("langfuse.")
    }
    return (
        span.trace_id,
        span.span_id,
        span.parent_span_id,
        span.name,
        span.start_time_unix_nano,
        span.end_time_unix_nano,
        span.status.code,
        span.status.message,
        tuple(sorted(carried.items())),
    )


def _wait_for_fanout(jaeger: Receiver, langfuse: Receiver) -> None:
    deadline = time.monotonic() + DEADLINE_S
    while time.monotonic() < deadline:
        left, right = _trace_ids(jaeger), _trace_ids(langfuse)
        if left and left == right:
            return
        time.sleep(0.1)
    raise AssertionError("both Collector branches did not receive one matching population")


def test_committed_collector_fans_out_one_masked_sampled_population() -> None:
    jaeger = Receiver(bind="0.0.0.0")
    langfuse = Receiver(bind="0.0.0.0")
    try:
        with _collector(jaeger, langfuse) as (endpoint, name):
            _post(endpoint, _request())
            _wait_for_fanout(jaeger, langfuse)
            logs = _run("docker", "logs", name).stdout

        left, right = _trace_ids(jaeger), _trace_ids(langfuse)
        assert left == right
        assert 0 < len(left) < TRACE_COUNT

        jaeger_turns = {_canonical(span) for span in jaeger.spans() if span.name == "turn"}
        langfuse_turns = {
            _canonical(span) for span in langfuse.spans() if span.name == "turn"
        }
        assert jaeger_turns == langfuse_turns

        assert not [span for span in jaeger.spans() if span.name == "capture"]
        assert _trace_ids(langfuse, name="capture") == right
        assert all(
            not any(key.startswith("langfuse.") for key in attributes(span))
            for span in jaeger.spans()
        )
        expected = f"mail {MASKED_EMAIL} token {MASKED_CREDENTIAL}"
        assert all(
            {key: attributes(span)[key] for key in CANONICAL_CONTENT}
            == dict.fromkeys(CANONICAL_CONTENT, expected)
            for span in jaeger.spans()
        )
        assert all(MASKED_CREDENTIAL in span.status.message for span in jaeger.spans())
        for span in langfuse.spans():
            carried = attributes(span)
            assert {key: carried[key] for key in CONTENT_ATTRIBUTES} == dict.fromkeys(
                CONTENT_ATTRIBUTES, expected
            )
            assert MASKED_CREDENTIAL in span.status.message

        raw = b"".join(jaeger.bodies + langfuse.bodies)
        for sentinel in (RAW_EMAIL, PUBLIC_KEY, SECRET_KEY):
            assert sentinel.encode() not in raw
            assert sentinel not in logs

        expected_auth = "Basic " + base64.b64encode(
            f"{PUBLIC_KEY}:{SECRET_KEY}".encode()
        ).decode()
        assert all("authorization" not in headers for headers in jaeger.headers)
        assert all("x-langfuse-ingestion-version" not in headers for headers in jaeger.headers)
        assert all(headers.get("authorization") == expected_auth for headers in langfuse.headers)
        assert all(
            headers.get("x-langfuse-ingestion-version") == "4"
            for headers in langfuse.headers
        )
    finally:
        jaeger.close()
        langfuse.close()
