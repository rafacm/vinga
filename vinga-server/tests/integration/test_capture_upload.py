"""A recording leaving the host, against a backend this lane runs.

The unit lane fakes the far side at `capture_upload.Sdk` and proves
everything that is vinga's: the staging, the bound, the worker, the
retries, the reasons. Three claims it cannot make are here.

**The whole path.** A real server with capture and the attachment on, a
real device conversation over a websocket, the real close ordering, the
real Langfuse SDK talking to a media endpoint running on a socket in
this process. What that certifies is the HTTP round trip the SDK
actually makes and the shape of the request it makes it with, which a
fake client asserts nothing about: three requests per attachment, the
presigned PUT among them, exactly two attachments and their MIME types,
a WAV whose header has its length patched in, a manifest that says it is
complete, and no request anywhere carrying the decision track.

**The hostile backend.** One that accepts the connection and never
answers, which is the failure a naive uploader has no answer for: the
`test_telemetry_hardening.py` definition, and the reason this module
fixes a request timeout and a retry ceiling at all. Three latencies are
asserted separately, because they are three different promises: the
session closes unaffected, the failure event fires inside the
timeout-and-retries budget, and the shutdown finishes inside its own
bound.

**The SDK's own voice.** A fake import seam cannot certify that the real
distribution and the real HTTP stack under it stay quiet, and what they
would say is a presigned URL. So a credential is planted in the SDK's
environment, the endpoint fails after the shutdown's bound has expired,
and both streams and both log formats are asserted clean.
"""

import asyncio
import contextlib
import json
import logging
import socket
import threading
import time
from collections.abc import Iterator
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

import pytest

from tests.support.events import every_format
from tests.support.telemetry import Receiver, attributes, named
from tests.support.uploads import exporting
from vinga_server.capture_upload import (
    _QUIETING,
    AUDIO_NAME,
    LANGFUSE_HOST_ENV,
    LANGFUSE_PUBLIC_KEY_ENV,
    LANGFUSE_SECRET_KEY_ENV,
    MANIFEST_NAME,
    CaptureUpload,
    staging_root,
)
from vinga_server.config import Config
from vinga_server.config.models import CaptureConfig, ServerConfig, TelemetryConfig

pytestmark = pytest.mark.asyncio

MOCK_PROVIDERS = {stage: {"mock": {"type": "mock"}} for stage in ("llm", "asr", "tts", "vad")}
MOCK_AGENT = dict.fromkeys(("llm", "asr", "tts", "vad"), "mock")

DEVICE_MAC = "aa:bb:cc:dd:ee:67"

# A trace id in the spelling the exporter hands out and the media API
# takes back.
TRACE = "0af7651916cd43dd8448eb211c80319c"

# A value shaped like the credential the SDK reads from its own
# environment, planted where one genuinely arrives.
SECRET = "sk-lf-0LIVEUPLOAD-SENTINEL"


class Media:
    """A Langfuse media endpoint, as much of it as an upload uses.

    Three routes and no more: the POST that mints a record and hands
    back a presigned URL, the PUT that URL points at, and the PATCH that
    closes the record. Every request is kept whole, because what this
    lane asserts is what was ASKED FOR rather than what came back.
    """

    def __init__(self) -> None:
        self.requests: list[tuple[str, str, bytes]] = []
        # The ids this endpoint minted, in order, which is what a
        # reference token has to name: the id is the far side's to
        # choose, so a case that guessed it would be asserting its own
        # arithmetic.
        self.minted: list[str] = []
        self._lock = threading.Lock()
        endpoint = self

        class Handler(BaseHTTPRequestHandler):
            def _read(self) -> bytes:
                length = int(self.headers.get("Content-Length") or 0)
                return self.rfile.read(length) if length else b""

            def _record(self, method: str) -> bytes:
                body = self._read()
                with endpoint._lock:
                    endpoint.requests.append((method, self.path, body))
                return body

            def _answer(self, status: int, payload: dict[str, Any] | None = None) -> None:
                encoded = json.dumps(payload or {}).encode()
                self.send_response(status)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(encoded)))
                self.end_headers()
                self.wfile.write(encoded)

            def do_POST(self) -> None:  # noqa: N802 - the stdlib's spelling
                self._record("POST")
                with endpoint._lock:
                    media_id = f"media-{len(endpoint.minted) + 1}"
                    endpoint.minted.append(media_id)
                self._answer(
                    201,
                    {
                        "mediaId": media_id,
                        "uploadUrl": f"{endpoint.url}/upload/{media_id}",
                    },
                )

            def do_PUT(self) -> None:  # noqa: N802 - the stdlib's spelling
                self._record("PUT")
                self._answer(200)

            def do_PATCH(self) -> None:  # noqa: N802 - the stdlib's spelling
                self._record("PATCH")
                self._answer(200)

            def log_message(self, *args: Any) -> None:
                return None

        self._server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self._thread = threading.Thread(target=self._server.serve_forever, daemon=True)
        self._thread.start()

    @property
    def url(self) -> str:
        host, port = self._server.server_address[:2]
        return f"http://{host}:{port}"

    def of(self, method: str) -> list[tuple[str, str, bytes]]:
        with self._lock:
            return [one for one in self.requests if one[0] == method]

    def close(self) -> None:
        self._server.shutdown()
        self._server.server_close()
        self._thread.join(timeout=5.0)


@pytest.fixture
def media() -> Iterator[Media]:
    endpoint = Media()
    try:
        yield endpoint
    finally:
        endpoint.close()


async def a_finished_capture(directory: Path, timeout_s: float = 20.0) -> Path:
    """Wait for one capture to be written and closed, and answer its
    manifest.

    The three files exist from the moment the session opens, so the
    manifest's `complete` is what says the writer finished with them.
    """
    loop = asyncio.get_running_loop()
    deadline = loop.time() + timeout_s
    while loop.time() < deadline:
        for manifest in sorted(directory.glob("*.json")):
            written = json.loads(manifest.read_text(encoding="utf-8"))
            if written.get("capture", {}).get("complete") is True:
                return manifest
        await asyncio.sleep(0.05)
    raise AssertionError("no capture was finished within the bound")


async def uploaded(endpoint: Media, count: int, timeout_s: float = 20.0) -> None:
    """Wait for the far side to have been asked `count` times."""
    loop = asyncio.get_running_loop()
    deadline = loop.time() + timeout_s
    while loop.time() < deadline:
        if len(endpoint.of("POST")) >= count:
            return
        await asyncio.sleep(0.05)
    raise AssertionError(f"only {len(endpoint.of('POST'))} attachment(s) were asked for")


def attaching(captures: Path) -> Config:
    return Config(
        providers=MOCK_PROVIDERS,
        agents={"assistant": MOCK_AGENT},
        default_agent="assistant",
        server=ServerConfig(
            capture=CaptureConfig(enabled=True, dir=captures),
            telemetry=TelemetryConfig(enabled=True, attach_captures=True),
        ),
    )


# --- the whole path ----------------------------------------------------


async def test_a_recorded_session_is_attached_to_its_trace(
    serve, simulate, tmp_path: Path, media: Media, monkeypatch: pytest.MonkeyPatch
) -> None:
    """One conversation, recorded, closed through the real ordering, and
    beside its trace by the time the server has stopped.

    Nothing here reaches into the server: the configuration says record
    and attach, a device talks, and what is asserted is what arrived at
    a Langfuse-shaped endpoint on a socket.
    """
    captures = tmp_path / "captures"
    monkeypatch.setenv(LANGFUSE_HOST_ENV, media.url)
    monkeypatch.setenv(LANGFUSE_PUBLIC_KEY_ENV, "pk-lf-test")
    monkeypatch.setenv(LANGFUSE_SECRET_KEY_ENV, "sk-lf-test")

    async with serve(attaching(captures)) as port:
        await simulate(port, DEVICE_MAC)
        manifest = await a_finished_capture(captures)
        await uploaded(media, 2)

    asked = [json.loads(body) for _, _, body in media.of("POST")]

    # Exactly two attachments, and their kinds.
    assert len(asked) == 2
    assert [one["contentType"] for one in asked] == ["audio/wav", "application/json"]
    # Both against one trace, which is the whole point of the surface,
    # and in the spelling the media API takes: thirty-two hex characters.
    traces = {one["traceId"] for one in asked}
    assert len(traces) == 1
    trace = traces.pop()
    assert len(trace) == 32 and int(trace, 16) >= 0
    # The presigned PUT is a real request to a real URL, and it is the
    # bytes of the two files.
    assert len(media.of("PUT")) == 2
    assert len(media.of("PATCH")) == 2
    audio = media.of("PUT")[0][2]
    assert audio.startswith(b"RIFF")
    # The header's two length fields are patched on a clean close, so a
    # capture that went out before its close would carry zeroes here.
    assert int.from_bytes(audio[40:44], "little") == len(audio) - 44
    assert int.from_bytes(audio[4:8], "little") == len(audio) - 8
    # And the manifest that went is the final one.
    written = json.loads(media.of("PUT")[1][2])
    assert written["capture"]["complete"] is True
    assert written == json.loads(manifest.read_text(encoding="utf-8"))
    # The decision track never leaves. Asserted on its CONTENT rather
    # than on its name, because the manifest legitimately names the
    # file beside it: what may not go is the track's own lines, and
    # every one of them carries the offset that indexes into the WAV.
    track = manifest.with_suffix(".jsonl").read_bytes()
    assert track, "the capture wrote no decision track, so this asserts nothing"
    assert {body for _, _, body in media.of("PUT")} == {
        manifest.with_suffix(".wav").read_bytes(),
        manifest.read_bytes(),
    }
    assert not any(b'"t_ms"' in body for _, _, body in media.requests)
    assert all(one["field"] == "metadata" for one in asked)
    # And the staging is empty, because a job nobody will run again is
    # room audio waiting on a disk.
    assert not list(staging_root(captures).iterdir())


async def test_the_uploaded_pair_is_referenced_on_the_session_trace(
    serve, simulate, tmp_path: Path, media: Media, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The half that makes an attachment playable rather than merely
    stored, decoded off the wire.

    The upload associates the bytes with a trace; the reference written
    back onto that trace is what makes the backend render a player. It
    goes out as a span in the session's own trace, which is the path the
    backend's own ingestion route names as supported when it refuses a
    trace upsert, so what this reads is protobuf a collector received
    rather than a second request.

    The teardown order is what makes it readable at all, and it is the
    exit stack's own: the uploader's shutdown was registered after the
    exporter's, so it unwinds first, the worker finishes and writes its
    span, and the exporter's flush behind it is what carries it.
    """
    captures = tmp_path / "captures"
    monkeypatch.setenv(LANGFUSE_HOST_ENV, media.url)
    monkeypatch.setenv(LANGFUSE_PUBLIC_KEY_ENV, "pk-lf-test")
    monkeypatch.setenv(LANGFUSE_SECRET_KEY_ENV, "sk-lf-test")
    collector = Receiver()
    monkeypatch.setenv("OTEL_EXPORTER_OTLP_ENDPOINT", collector.endpoint)

    try:
        async with serve(attaching(captures)) as port:
            await simulate(port, DEVICE_MAC)
            await a_finished_capture(captures)
            await uploaded(media, 2)
        spans = collector.spans()
    finally:
        collector.close()

    minted = media.minted
    assert len(minted) == 2
    assert spans, "nothing reached the collector at all"

    written = named(spans, "capture")
    held = attributes(written)
    # Both tokens, in the backend's own spelling, naming the ids the
    # endpoint minted a moment earlier.
    for name, kind, media_id in (
        ("capture_audio", "audio/wav", minted[0]),
        ("capture_manifest", "application/json", minted[1]),
    ):
        token = f"@@@langfuseMedia:type={kind}|id={media_id}|source=bytes@@@"
        assert held[f"langfuse.observation.metadata.{name}"] == token
        assert token in held["langfuse.observation.output"]
    # In the session's own trace and under the session span, which is
    # what makes a reader looking at the session find it rather than a
    # player in a trace nobody opens.
    session_span = named(spans, "session")
    assert written.trace_id == session_span.trace_id
    assert written.parent_span_id == session_span.span_id
    # And it groups with the session, so the query a reader makes for
    # that session returns it beside the turns.
    assert held["session.id"] == attributes(session_span)["session.id"]


# --- the hostile backend ----------------------------------------------


class Withholding:
    """A real listening endpoint that accepts the connection, reads the
    request and then says nothing at all until it is released.

    Lifted from `test_telemetry_hardening.py`, where the same shape is
    what the exporter is certified against, and for the same reason: an
    address that REFUSES costs an uploader nothing whatever it does, and
    an unroutable one is only slow if the network treats it as one.
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


def a_staged_pair(directory: Path, session: str) -> None:
    """One job on disk in the shape a close would have left it."""
    job = staging_root(directory) / session
    job.mkdir(parents=True)
    (job / AUDIO_NAME).write_bytes(b"RIFF" + bytes(40) + b"\x00" * 64)
    (job / MANIFEST_NAME).write_text(json.dumps({"capture": {"complete": True}}))


async def test_a_backend_that_never_answers_costs_three_bounded_things(
    tmp_path: Path, caplog: pytest.LogCaptureFixture, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The hostile shape, with the real SDK and the real HTTP stack.

    Three promises, asserted separately because they are three:

    - the session's close is unaffected, which is what "off the audio
      path" means and is measured as the time `session_closed` takes;
    - the failure event fires inside the request timeout and its
      retries, which is the whole reason there is a ceiling: with no
      ceiling no `capture_upload_failed` could ever fire, and a bounded
      shutdown would merely abandon the job in silence;
    - and the shutdown finishes inside its own bound, because a backend
      that has stopped answering must not hold a redeploy open.
    """
    caplog.set_level(logging.DEBUG)
    backend = Withholding()
    monkeypatch.setenv(LANGFUSE_HOST_ENV, backend.url)
    monkeypatch.setenv(LANGFUSE_PUBLIC_KEY_ENV, "pk-lf-test")
    monkeypatch.setenv(LANGFUSE_SECRET_KEY_ENV, "sk-lf-test")
    from vinga_server.capture_upload import _import_sdk

    sdk = _import_sdk()
    assert sdk is not None, "this lane has the extra"
    uploads = CaptureUpload(
        tmp_path / "captures",
        sdk=sdk,
        telemetry=exporting({"s1": TRACE}),
        backlog=4,
        timeout_s=1.0,
        retries=1,
        backoff_s=0.1,
        shutdown_timeout_s=1.0,
    )
    a_staged_pair(tmp_path / "captures", "s1")
    uploads._staged["s1"] = staging_root(tmp_path / "captures") / "s1"

    try:
        began = time.monotonic()
        uploads.session_closed("s1")
        closing = time.monotonic() - began

        assert backend.entered.wait(10.0), "the uploader never reached the backend"
        # The close put a job on a queue and nothing else: no request,
        # no wait, no lock the upload holds.
        assert closing < 0.5, f"the close took {closing:.2f} s with a wedged backend"

        # The failure, inside the timeout-and-retries budget. Two
        # attempts of one second each, plus a tenth of backoff, so four
        # seconds is generous and unbounded is what it rejects.
        deadline = time.monotonic() + 6.0
        while time.monotonic() < deadline:
            if any(
                getattr(record, "event", None) == "capture_upload_failed"
                for record in caplog.records
            ):
                break
            await asyncio.sleep(0.05)
        failures = [
            record
            for record in caplog.records
            if getattr(record, "event", None) == "capture_upload_failed"
        ]
        assert failures, "no failure event fired, so the request had no ceiling"
        assert time.monotonic() - began < 6.0

        began = time.monotonic()
        await uploads.shutdown()
        assert time.monotonic() - began < 5.0, "the shutdown was not bounded"
    finally:
        backend.close()
        await uploads.shutdown()


async def test_the_real_sdk_says_nothing_after_the_shutdowns_bound(
    tmp_path: Path,
    caplog: pytest.LogCaptureFixture,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The case the fake import seam cannot make.

    A credential planted in the SDK's own environment, an endpoint that
    fails only after the bounded shutdown has already given up, and both
    streams and both log formats asserted clean. The quieting is held
    past the expiry for exactly this: a shutdown that expired leaves a
    request in flight, and what that request is about to log is the
    endpoint it failed against.
    """
    caplog.set_level(logging.DEBUG)
    backend = Withholding()
    monkeypatch.setenv(LANGFUSE_HOST_ENV, f"{backend.url}/{SECRET}")
    monkeypatch.setenv(LANGFUSE_PUBLIC_KEY_ENV, SECRET)
    monkeypatch.setenv(LANGFUSE_SECRET_KEY_ENV, SECRET)
    from vinga_server.capture_upload import _import_sdk

    sdk = _import_sdk()
    assert sdk is not None, "this lane has the extra"
    uploads = CaptureUpload(
        tmp_path / "captures",
        sdk=sdk,
        telemetry=exporting({"s1": TRACE}),
        backlog=4,
        timeout_s=3.0,
        retries=0,
        backoff_s=0.0,
        shutdown_timeout_s=0.2,
    )
    a_staged_pair(tmp_path / "captures", "s1")
    uploads._staged["s1"] = staging_root(tmp_path / "captures") / "s1"

    try:
        uploads.session_closed("s1")
        assert backend.entered.wait(10.0), "the uploader never reached the backend"
        # The bound expires with the request still in flight, which is
        # the state this case is about.
        await uploads.shutdown()
        # And now the request fails, on a path nothing is waiting on.
        await asyncio.sleep(4.0)
    finally:
        backend.close()
        await uploads.shutdown()

    captured = capsys.readouterr()
    assert SECRET not in every_format(caplog)
    assert SECRET not in captured.err
    assert SECRET not in captured.out
    assert _QUIETING.held() == 0


@pytest.fixture(autouse=True)
def _no_lease_outlives_its_case() -> Iterator[None]:
    """These cases wedge uploaders on purpose, so a lease that did not
    go back would leave the rest of this lane running against a silenced
    HTTP stack."""
    yield
    assert logging.getLogger("langfuse").propagate is not False
    assert logging.getLogger("httpx").propagate is not False
