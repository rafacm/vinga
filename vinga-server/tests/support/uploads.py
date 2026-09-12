"""The far side of a capture upload, as something a lane can hold.

`capture_upload.py` reaches three names out of the Langfuse SDK and asks
nothing else of it, which is what `Sdk` is: the module's own test seam,
the shape `build_telemetry(exporter=...)` already established. What is
here is one of those, backed by a recorder, so a suite can drive the
real staging, the real queue, the real worker, the real retries and the
real failure classification with no SDK, no network and no clock.

Nothing here asserts. A helper returns a seam, a recorder or a staged
pair, and the suite says what it expects.

The recorder is the point rather than the fake. What the plan requires
proving is that exactly two attachments go out, with their MIME types,
a finalized WAV header and a manifest that says it is complete, and that
no request ever carries the decision track; all four are questions about
what was ASKED FOR, so what a fake has to do is write down every call.
"""

import threading
from dataclasses import dataclass, field
from typing import Any

from vinga_server.capture_upload import Sdk
from vinga_server.telemetry import Telemetry


class ApiError(Exception):
    """The generated client's error, in the shape this module's
    classification reads: a status code and nothing it would ever
    repeat.

    A stand-in for `langfuse.api.core.ApiError`, which the seam names by
    type rather than by import, so a lane without the distribution can
    still produce one.
    """

    def __init__(self, status_code: int | None = None, body: Any = None) -> None:
        super().__init__(status_code)
        self.status_code = status_code
        self.body = body


@dataclass
class Asked:
    """One `get_upload_url` call, as the fields a claim is made about."""

    content_type: str
    content_length: int
    sha256hash: str
    field: str
    trace_id: str | None


@dataclass
class Uploaded:
    """One presigned PUT, with the bytes that went."""

    url: str
    content_type: str
    payload: bytes


@dataclass
class Recorder:
    """Everything one fake far side was asked for, in order.

    Shared by every client the seam hands out, so a case that drives two
    uploads reads one list rather than hunting for the client that
    happened to run.
    """

    asked: list[Asked] = field(default_factory=list)
    uploaded: list[Uploaded] = field(default_factory=list)
    patched: list[str] = field(default_factory=list)
    constructed: list[dict[str, Any]] = field(default_factory=list)
    _lock: threading.Lock = field(default_factory=threading.Lock)

    @property
    def kinds(self) -> list[str]:
        """The content types asked for, which is what "exactly two
        attachments, audio/wav and application/json" is a claim about."""
        return [one.content_type for one in self.asked]


class _Answer:
    """What the media API answers a request for an upload URL with."""

    def __init__(self, media_id: str, upload_url: str | None) -> None:
        self.media_id = media_id
        self.upload_url = upload_url


class _Media:
    """The media half of the generated client, which is the only half
    this server touches."""

    def __init__(self, client: "FakeClient") -> None:
        self._client = client

    def get_upload_url(
        self,
        *,
        content_type: Any,
        content_length: int,
        sha256hash: str,
        field: str,
        trace_id: str | None = None,
        observation_id: str | None = None,
        dataset_id: str | None = None,
        dataset_item_id: str | None = None,
        request_options: Any = None,
    ) -> _Answer:
        client = self._client
        with client.recorder._lock:
            client.recorder.asked.append(
                Asked(
                    content_type=str(getattr(content_type, "value", content_type)),
                    content_length=content_length,
                    sha256hash=sha256hash,
                    field=field,
                    trace_id=trace_id,
                )
            )
        if client.asking is not None:
            raise client.asking
        media_id = f"media-{len(client.recorder.asked)}"
        return _Answer(media_id, None if client.deduplicates else client.upload_url)

    def patch(
        self,
        media_id: str,
        *,
        uploaded_at: Any,
        upload_http_status: int,
        upload_http_error: str | None = None,
        upload_time_ms: int | None = None,
        request_options: Any = None,
    ) -> None:
        with self._client.recorder._lock:
            self._client.recorder.patched.append(media_id)


class FakeClient:
    """The generated REST client, as much of it as the uploader uses.

    Constructed by the uploader's own `_media()` with whatever the
    environment held, which is why the constructor records its arguments
    and why a case can make the construction itself raise: a client that
    cannot be built has to become a sanitized upload failure rather than
    a thread that died.
    """

    # What every instance shares, so a seam handed to an uploader and
    # the case that made it are looking at one recorder.
    def __init__(
        self,
        *,
        base_url: str,
        username: str | None = None,
        password: str | None = None,
        timeout: float | None = None,
        httpx_client: Any = None,
        recorder: Recorder,
        asking: BaseException | None = None,
        building: BaseException | None = None,
        deduplicates: bool = True,
        upload_url: str | None = None,
    ) -> None:
        self.recorder = recorder
        self.asking = asking
        self.deduplicates = deduplicates
        self.upload_url = upload_url
        with recorder._lock:
            recorder.constructed.append(
                {
                    "base_url": base_url,
                    "username": username,
                    "password": password,
                    "timeout": timeout,
                }
            )
        if building is not None:
            raise building
        self.media = _Media(self)


def fake_sdk(
    recorder: Recorder | None = None,
    *,
    asking: BaseException | None = None,
    building: BaseException | None = None,
    deduplicates: bool = True,
    upload_url: str | None = None,
) -> tuple[Sdk, Recorder]:
    """One seam and the recorder behind it.

    `deduplicates` is the media API's own behavior when the bytes are
    already held: it answers with no upload URL and there is nothing to
    PUT, which is what makes a retry free. A case that wants the PUT
    itself passes `upload_url` and turns it off.
    """
    kept = recorder if recorder is not None else Recorder()

    def client(**options: Any) -> FakeClient:
        return FakeClient(
            recorder=kept,
            asking=asking,
            building=building,
            deduplicates=deduplicates,
            upload_url=upload_url,
            **options,
        )

    return Sdk(client=client, error=ApiError, content_type=str), kept


class Traced:
    """A telemetry exporter, as the one question the uploader asks it.

    Not a `Telemetry`, and typed as one at the call site because that is
    what the uploader declares: what it uses is `trace_of`, and a lane
    that had to build a real exporter to answer one string would be
    driving OpenTelemetry to test a hardlink.
    """

    def __init__(self, traces: dict[str, str] | None = None) -> None:
        self.traces = dict(traces or {})

    def trace_of(self, session: str) -> str | None:
        return self.traces.get(session)


def exporting(traces: dict[str, str] | None = None) -> Telemetry:
    """`Traced` under the type the uploader declares."""
    return Traced(traces)  # type: ignore[return-value]
