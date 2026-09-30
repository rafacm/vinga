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
proving is that the pair goes out, with its MIME types, a finalized WAV
header and a manifest that says it is complete, that each turn's clips
go out against that turn's own trace (#496), and that no request ever
carries the decision track or a file the staging did not put there; all
of those are questions about what was ASKED FOR, so what a fake has to
do is write down every call.
"""

import threading
from collections.abc import Callable
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
        if client.answering is not None:
            # One request's own answer, for the cases about which of a
            # job's several files fails: a raise is that request
            # failing, and a string is the presigned URL it answers
            # with (None, as ever, is bytes already held).
            answer = client.answering(client.recorder.asked[-1])
            if isinstance(answer, BaseException):
                raise answer
            return _Answer(f"media-{len(client.recorder.asked)}", answer)
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
        answering: "Answering | None" = None,
    ) -> None:
        self.recorder = recorder
        self.asking = asking
        self.answering = answering
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


# What one request for an upload URL is answered with, decided per
# request: an exception to raise, a presigned URL to PUT to, or None for
# bytes the backend already holds.
Answering = Callable[[Asked], BaseException | str | None]


def fake_sdk(
    recorder: Recorder | None = None,
    *,
    asking: BaseException | None = None,
    building: BaseException | None = None,
    deduplicates: bool = True,
    upload_url: str | None = None,
    answering: Answering | None = None,
) -> tuple[Sdk, Recorder]:
    """One seam and the recorder behind it.

    `deduplicates` is the media API's own behavior when the bytes are
    already held: it answers with no upload URL and there is nothing to
    PUT, which is what makes a retry free. A case that wants the PUT
    itself passes `upload_url` and turns it off.

    `answering` decides each request on its own, which is what a case
    about one clip among several needs: the pair lands and the third
    request is refused, say. It is handed the request as the recorder
    kept it, and it runs after `asking`, which fails every request.
    """
    kept = recorder if recorder is not None else Recorder()

    def client(**options: Any) -> FakeClient:
        return FakeClient(
            recorder=kept,
            asking=asking,
            building=building,
            deduplicates=deduplicates,
            upload_url=upload_url,
            answering=answering,
            **options,
        )

    return Sdk(client=client, error=ApiError, content_type=str), kept


@dataclass(frozen=True)
class Pin:
    """What a pinned context is, as far as the uploader can tell.

    Opaque to the uploader by contract: it takes one from
    `retained_context` at admission, carries it, and hands it back. This
    double therefore makes it a session id in a wrapper, which is the
    least a thing can be and still be a handle rather than a name.
    """

    session: str


@dataclass(frozen=True)
class TurnPin:
    """A turn's pinned context under a session's, as `turn_context`
    answers it: the utterance it answered, beside the session."""

    session: str
    utterance: str


class Traced:
    """A telemetry exporter, as the three questions the uploader asks it.

    Not a `Telemetry`, and typed as one at the call site because that is
    what the uploader declares: what it uses is `retained_context`,
    `trace_of` and `reference_media`, and a lane that had to build a real
    exporter to answer one string would be driving OpenTelemetry to test
    a hardlink.

    The two reads take a PINNED CONTEXT rather than a session id, which
    is the interface M4a left behind. What this double deliberately does
    NOT model is eviction: a fake that dropped a context on request could
    not tell a pin taken at admission from one taken on the worker, and
    telling those apart is the whole of that milestone. The cases that
    make that claim use the real retention instead, and they live beside
    the uploader's own suite.

    `referenced` is what a case reads back: the tokens the uploader asked
    to have written onto each session's trace, which is the claim that
    an attachment is playable rather than merely stored. `refusing` makes
    the write fail, which is the state an exporter shutting down leaves.

    `turns` is the fourth question, since #496: each turn's own trace by
    the utterance it answered, which is where that turn's clips go. A
    turn this double does not hold answers None, which is the exporter's
    answer for a turn it never opened. `turn_referenced` is what was
    written onto each turn, `turn_asked` every write that was asked for
    whatever it answered, and `refusing_turns` makes one turn's write
    fail while the session's still lands.
    """

    def __init__(
        self,
        traces: dict[str, str] | None = None,
        *,
        refusing: bool = False,
        turns: dict[str, str] | None = None,
        refusing_turns: frozenset[str] = frozenset(),
    ) -> None:
        self.traces = dict(traces or {})
        self.refusing = refusing
        self.turns = dict(turns or {})
        self.refusing_turns = refusing_turns
        self.referenced: list[tuple[str, dict[str, str]]] = []
        self.turn_referenced: list[tuple[str, dict[str, str]]] = []
        self.turn_asked: list[tuple[str, dict[str, str]]] = []

    def retained_context(self, session: str) -> Any | None:
        return Pin(session) if session in self.traces else None

    def trace_of(self, context: Any) -> str | None:
        if isinstance(context, TurnPin):
            return self.turns.get(context.utterance)
        if not isinstance(context, Pin):
            return None
        return self.traces.get(context.session)

    def turn_context(self, context: Any, utterance: str | None) -> Any | None:
        if not isinstance(context, Pin) or utterance not in self.turns:
            return None
        return TurnPin(context.session, utterance)

    def reference_media(self, context: Any, references: dict[str, str]) -> bool:
        if isinstance(context, TurnPin):
            self.turn_asked.append((context.utterance, dict(references)))
            if self.refusing or context.utterance in self.refusing_turns:
                return False
            self.turn_referenced.append((context.utterance, dict(references)))
            return True
        if self.refusing or not isinstance(context, Pin):
            return False
        if context.session not in self.traces:
            return False
        self.referenced.append((context.session, dict(references)))
        return True


def exporting(
    traces: dict[str, str] | None = None,
    *,
    refusing: bool = False,
    turns: dict[str, str] | None = None,
) -> Telemetry:
    """`Traced` under the type the uploader declares."""
    return Traced(traces, refusing=refusing, turns=turns)  # type: ignore[return-value]
