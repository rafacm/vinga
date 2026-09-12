"""The uploader: what it refuses, what it stages, and what it says.

The one surface in this server that deliberately sends content off the
host, so this file is written the way the exporter's was: what a
default deployment gets is nothing at all, every refusal is a fixed
sentence with no value and no chain, and a credential planted in each
place one genuinely arrives is hunted through both log formats, both
events' payloads and every exception chain.

The far side is faked at `capture_upload.Sdk`, which is the module's own
seam and the shape `build_telemetry(exporter=...)` established. Nothing
else is faked: the staging is real hardlinks on a real filesystem, the
queue is the real bounded one, the worker is the real daemon thread, and
the retries and the classification are the real ones. The real-SDK cases
live in the integration lane, which has the extra.

Two claims here are about timing rather than about values, and both are
driven rather than asserted about a design: a capture that finished
early must not upload until its session closes, and a prune storm
between those two moments must not be able to erase what was staged.
"""

import asyncio
import json
import logging
import threading
import time
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest

from tests.support.events import both_formats, fields_of
from tests.support.stores import CAPTURE_MANIFEST, tone
from tests.support.stores import store as capture_store
from tests.support.uploads import ApiError, Recorder, exporting, fake_sdk
from vinga_server.capture import CaptureStore, SessionCapture, sweep_upload_staging
from vinga_server.capture_upload import (
    _QUIETING,
    ATTACH_KEY,
    AUDIO_NAME,
    LANGFUSE_HOST_ENV,
    LANGFUSE_PUBLIC_KEY_ENV,
    LANGFUSE_SECRET_KEY_ENV,
    MANIFEST_NAME,
    NEEDS_THE_LANGFUSE_EXTRA,
    CaptureUpload,
    build_capture_upload,
    staging_root,
)
from vinga_server.config import ConfigError
from vinga_server.config.models import ServerConfig
from vinga_server.events.values import CaptureUploadFailure

# A trace id in the spelling the exporter hands out and the media API
# takes back: thirty-two lowercase hex characters.
TRACE = "0af7651916cd43dd8448eb211c80319c"

# The other one, so a claim about which trace a session's attachment was
# asked against is a claim rather than a coincidence.
OTHER_TRACE = "4bf92f3577b34da6a3ce929d0e0e4736"

# A value shaped like the credential the SDK reads, planted where one
# genuinely arrives.
SECRET = "sk-lf-0CAPTUREUPLOAD-SENTINEL"

# And the other untrusted input family: a manifest is written from what
# a device said about itself, so a field of it is where content-shaped
# text arrives.
HOSTILE = "hostile-manifest-0CAPTUREUPLOAD-SENTINEL"

ENDPOINT = "http://langfuse.invalid:53010"


@pytest.fixture(autouse=True)
def _no_credentials_from_the_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    """A developer with a Langfuse configured must not change what these
    cases mean."""
    for name in (
        LANGFUSE_HOST_ENV,
        # Not a variable this module reads, and deleted anyway: a
        # developer whose shell exports it must not be able to make the
        # case below pass by accident.
        "LANGFUSE_BASE_URL",
        LANGFUSE_PUBLIC_KEY_ENV,
        LANGFUSE_SECRET_KEY_ENV,
    ):
        monkeypatch.delenv(name, raising=False)


@pytest.fixture
def endpoint(monkeypatch: pytest.MonkeyPatch) -> str:
    """A Langfuse to aim at, for the cases that get as far as a
    request."""
    monkeypatch.setenv(LANGFUSE_HOST_ENV, ENDPOINT)
    return ENDPOINT


def a_server(**server: Any) -> ServerConfig:
    """One server section, with capture and attachment on unless a case
    says otherwise."""
    return ServerConfig.model_validate(
        {
            "capture": {"enabled": True, "dir": "/tmp/vinga-captures"},
            "telemetry": {"enabled": True, "attach_captures": True},
            **server,
        }
    )


def an_uploader(
    tmp_path: Path,
    *,
    traces: dict[str, str] | None = None,
    backlog: int = 8,
    sdk: Any = None,
    recorder: Recorder | None = None,
    **options: Any,
) -> tuple[CaptureUpload, Recorder]:
    """An uploader over a throwaway capture directory, with the far side
    faked."""
    seam, kept = (sdk, recorder) if sdk is not None else fake_sdk(recorder)
    assert kept is not None
    uploads = CaptureUpload(
        tmp_path / "captures",
        sdk=seam,
        telemetry=options.pop(
            "telemetry", exporting(traces if traces is not None else {})
        ),
        backlog=backlog,
        retries=options.pop("retries", 0),
        backoff_s=options.pop("backoff_s", 0.0),
        shutdown_timeout_s=options.pop("shutdown_timeout_s", 10.0),
        **options,
    )
    return uploads, kept


def a_recording(
    store: CaptureStore, session: str, manifest: dict[str, Any] | None = None
) -> SessionCapture:
    """One recording, made and closed cleanly, so its pair is final."""
    opened = time.monotonic()
    capture = store.open(session, opened, manifest or CAPTURE_MANIFEST)
    assert capture is not None
    capture.microphone(tone(100), opened)
    capture.close()
    return capture


async def drained(uploads: CaptureUpload) -> None:
    """Every queued job run, and the worker stopped.

    The shutdown's own bound is what a lane waits on: the worker takes
    whatever is queued before it sees that it was asked to stop, so a
    case that closes a session and then shuts down has driven the whole
    path rather than raced it.
    """
    await uploads.shutdown()


def staged(uploads_directory: Path) -> list[str]:
    """What is in the staging root right now, by job name."""
    root = staging_root(uploads_directory)
    if not root.exists():
        return []
    return sorted(path.name for path in root.iterdir())


def reasons(caplog: pytest.LogCaptureFixture) -> list[str]:
    """Every failure reason this run reported, in order."""
    return [
        str(fields_of(record)["reason"])
        for record in caplog.records
        if getattr(record, "event", None) == "capture_upload_failed"
    ]


def uploads_said(caplog: pytest.LogCaptureFixture) -> list[logging.LogRecord]:
    return [
        record
        for record in caplog.records
        if getattr(record, "event", None) == "capture_uploaded"
    ]


# --- nothing at all ----------------------------------------------------


def test_no_telemetry_section_builds_nothing() -> None:
    """The default, and it costs a server nothing: no import, no object,
    no thread, no callback."""
    config = a_server(telemetry=None)

    assert build_capture_upload(config, telemetry=None) is None


def test_the_flag_off_builds_nothing() -> None:
    """Telemetry on and the attachment off is the ordinary traced
    deployment, and it must not acquire a second surface by being
    traced."""
    config = a_server(telemetry={"enabled": True})

    assert build_capture_upload(config, telemetry=exporting()) is None


def test_capture_absent_is_a_no_op_and_says_so(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """The issue's own rule: the flag on with capture off is a no-op
    rather than a misconfiguration, because an operator mid-toggle has
    not misconfigured anything.

    Said out loud because a switch that does nothing is otherwise a
    silence somebody has to debug, and value-free because there is
    nothing to name but the two keys.
    """
    caplog.set_level(logging.INFO)
    config = a_server(capture=None)

    assert build_capture_upload(config, telemetry=exporting()) is None
    assert ATTACH_KEY in caplog.text
    assert "server.capture.enabled" in caplog.text


def test_capture_disabled_is_the_same_no_op(caplog: pytest.LogCaptureFixture) -> None:
    """A section left in the file is not consent, and the flag above it
    does not turn it into consent either."""
    caplog.set_level(logging.INFO)
    config = a_server(capture={"enabled": False, "dir": "/tmp/vinga-captures"})

    assert build_capture_upload(config, telemetry=exporting()) is None
    assert ATTACH_KEY in caplog.text


def test_a_capture_off_deployment_never_reaches_a_refusal() -> None:
    """The decision order, which is the contract: capture resolves
    FIRST, so a capture-off deployment boots identically with or without
    the extra, the telemetry section or local_only.

    Driven with local_only on, which is the refusal that would otherwise
    fire: a server that turned off recording and then could not boot
    would be an operator punished for the toggle they were told to make.
    """
    config = a_server(
        capture={"enabled": False, "dir": "/tmp/vinga-captures"}, local_only=True
    )

    assert build_capture_upload(config, telemetry=exporting(), local_only=True) is None


# Every combination the decision order has to answer, and the shape of
# the answer for each.
#
# The rows are the point rather than the loop: what the round found is
# that one of them (capture off with the exporter off) was refused by the
# CONFIGURATION before any builder could apply the no-op, so a matrix
# that stopped at "capture off is a no-op" could not see it. Each row
# names both switches and what the pair must do.
CAPTURE_OFF = (
    pytest.param(None, {"enabled": True, "attach_captures": True}, id="absent-traced"),
    pytest.param(
        {"enabled": False, "dir": "/tmp/vinga-captures"},
        {"enabled": True, "attach_captures": True},
        id="disabled-traced",
    ),
    pytest.param(
        None, {"enabled": False, "attach_captures": True}, id="absent-untraced"
    ),
    pytest.param(
        {"enabled": False, "dir": "/tmp/vinga-captures"},
        {"enabled": False, "attach_captures": True},
        id="disabled-untraced",
    ),
)


@pytest.mark.parametrize(("capture", "telemetry"), CAPTURE_OFF)
def test_every_capture_off_shape_loads_and_builds_nothing(
    capture: dict[str, Any] | None,
    telemetry: dict[str, Any],
    caplog: pytest.LogCaptureFixture,
) -> None:
    """The matrix the round asked for, and the row that caught the bug.

    `absent-untraced` and `disabled-untraced` are the attachment on with
    neither a recording nor an exporter, which is exactly what an
    operator has in hand for the two toggles between a recording
    deployment and a plain one. The rule used to refuse both at LOAD, so
    the file would not even parse and the no-op below could never run.
    """
    caplog.set_level(logging.INFO)
    config = a_server(capture=capture, telemetry=telemetry)

    assert build_capture_upload(config, telemetry=None) is None
    assert ATTACH_KEY in caplog.text


@pytest.mark.parametrize(("capture", "telemetry"), CAPTURE_OFF)
@pytest.mark.parametrize("local_only", [False, True])
def test_no_capture_off_shape_refuses_for_anything(
    capture: dict[str, Any] | None,
    telemetry: dict[str, Any],
    local_only: bool,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """And none of them reaches a refusal, whichever refusal it would
    have been.

    All three are armed at once: local_only on, no exporter handed in,
    and the extra faked away. A capture-off deployment boots identically
    through every one of them, which is the contract's own sentence.
    """
    import vinga_server.capture_upload as module

    def never() -> None:
        raise AssertionError("the SDK was imported for a capture-off deployment")

    monkeypatch.setattr(module, "_import_sdk", never)
    config = a_server(capture=capture, telemetry=telemetry, local_only=local_only)

    assert (
        build_capture_upload(config, telemetry=None, local_only=local_only) is None
    )


def test_a_capture_off_deployment_says_nothing_with_the_flag_off(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """And the silence that goes with it: most servers have neither,
    and a line about a feature nobody asked for is noise."""
    caplog.set_level(logging.DEBUG)
    config = a_server(capture=None, telemetry=None)

    assert build_capture_upload(config, telemetry=None) is None
    assert ATTACH_KEY not in caplog.text


# --- the refusals ------------------------------------------------------


def test_the_attachment_is_refused_without_an_exporter() -> None:
    """The cross-field rule, once there is something to attach.

    Three keys across two sections, which is why it is `ServerConfig`'s
    and not `TelemetryConfig`'s: a rule that could see only the telemetry
    section refused every capture-off file at load, ahead of the no-op
    the decision order promises. With capture effectively on, an
    attachment still needs an exporter, because what names it is the
    trace its session was exported under.

    The sentence names both keys and the way out, and no value.
    """
    from vinga_server.config.models import ATTACHMENT_NEEDS_TELEMETRY

    with pytest.raises(ValueError) as refusal:
        a_server(telemetry={"enabled": False, "attach_captures": True})

    assert ATTACHMENT_NEEDS_TELEMETRY in str(refusal.value)
    assert "telemetry.enabled" in ATTACHMENT_NEEDS_TELEMETRY
    assert ATTACH_KEY.endswith("telemetry.attach_captures")


def test_the_telemetry_section_alone_refuses_nothing() -> None:
    """And the same combination on the section by itself loads, which is
    what makes the rule a server-level one rather than a moved one: the
    section cannot see whether anything is being recorded."""
    from vinga_server.config.models import TelemetryConfig

    assert TelemetryConfig(enabled=False, attach_captures=True).attach_captures


def test_local_only_refuses_before_anything_is_built() -> None:
    """Sending a recording to a backend is egress like any other, and
    the refusal is the egress module's own sentence: it names the switch
    and the key that turns it off and nothing about any endpoint."""
    config = a_server(local_only=True)

    with pytest.raises(ConfigError) as refusal:
        build_capture_upload(config, telemetry=exporting(), local_only=True)

    assert ATTACH_KEY in str(refusal.value)
    assert "server.local_only" in str(refusal.value)
    assert refusal.value.__cause__ is None
    assert refusal.value.__context__ is None


def test_the_missing_extra_refuses_with_the_command_to_type(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The install that never had the distribution, faked at the import
    seam the way the exporter's is.

    No ImportError chained, because one carries its module search path
    and a traceback through somebody else's package, and this sentence
    is printed as it is.
    """
    import vinga_server.capture_upload as module

    monkeypatch.setattr(module, "_import_sdk", lambda: None)

    with pytest.raises(ConfigError) as refusal:
        build_capture_upload(a_server(), telemetry=exporting())

    assert str(refusal.value) == NEEDS_THE_LANGFUSE_EXTRA
    assert "uv sync --extra langfuse" in NEEDS_THE_LANGFUSE_EXTRA
    assert refusal.value.__cause__ is None
    assert refusal.value.__context__ is None


def test_the_refusals_run_in_the_order_the_contract_states(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Egress before the import, which is what lets the egress refusal
    honestly say nothing was constructed.

    Asserted by making the import itself fail loudly: reaching it under
    local_only would be the ordering broken, and the case would see the
    planted failure instead of the sentence.
    """
    import vinga_server.capture_upload as module

    def never() -> None:
        raise AssertionError("the SDK was imported under local_only")

    monkeypatch.setattr(module, "_import_sdk", never)

    with pytest.raises(ConfigError) as refusal:
        build_capture_upload(a_server(local_only=True), telemetry=exporting(), local_only=True)

    assert "server.local_only" in str(refusal.value)


def test_an_uploader_is_built_when_everything_is_on() -> None:
    """And the positive, so the refusals above are not the only thing
    this function can do."""
    built = build_capture_upload(a_server(), telemetry=exporting())

    assert built is not None


def test_the_backlog_is_sized_from_the_session_limit() -> None:
    """A routine shutdown closes every live session at once, so the
    backlog that must not deterministically drop any of them is the
    number of sessions this server holds."""
    config = a_server(limits={"max_sessions": 3})

    built = build_capture_upload(config, telemetry=exporting())

    assert built is not None
    assert built._queue.maxsize == 3


# --- staging -----------------------------------------------------------


def test_a_closed_capture_is_staged_as_a_pair_in_a_job_of_its_own(
    tmp_path: Path,
) -> None:
    """Two hardlinks in one per-job subdirectory, which is what makes
    the commit atomic: a directory that appears under the staging root
    has both its links in it."""
    uploads, _ = an_uploader(tmp_path)
    store = capture_store(tmp_path, uploads=uploads)

    a_recording(store, "s1")

    assert staged(store.directory) == ["s1"]
    job = staging_root(store.directory) / "s1"
    assert sorted(path.name for path in job.iterdir()) == [MANIFEST_NAME, AUDIO_NAME]


def test_the_staged_audio_is_the_same_inode_rather_than_a_copy(
    tmp_path: Path,
) -> None:
    """A hardlink, which is the whole reason staging costs no time on
    the close path and survives the unlink a prune is."""
    uploads, _ = an_uploader(tmp_path)
    store = capture_store(tmp_path, uploads=uploads)

    capture = a_recording(store, "s1")

    job = staging_root(store.directory) / "s1"
    assert (job / AUDIO_NAME).stat().st_ino == capture.wav_path.stat().st_ino


def test_the_decision_track_is_never_staged(tmp_path: Path) -> None:
    """Exactly two files. The JSONL is a third content-bearing artifact
    the issue never named, so it stays on this host."""
    uploads, _ = an_uploader(tmp_path)
    store = capture_store(tmp_path, uploads=uploads)

    capture = a_recording(store, "s1")

    assert capture.jsonl_path.exists()
    job = staging_root(store.directory) / "s1"
    assert not any(path.suffix == ".jsonl" for path in job.iterdir())


def test_a_staging_that_cannot_finish_leaves_no_links(
    tmp_path: Path, caplog: pytest.LogCaptureFixture, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Rollback, asserted on the directory's exact contents.

    A partial staging is a pair somebody would later upload half of, so
    what a failure leaves is zero links and one event.
    """
    caplog.set_level(logging.DEBUG)
    uploads, _ = an_uploader(tmp_path)
    store = capture_store(tmp_path, uploads=uploads)
    real = __import__("os").link
    calls = {"count": 0}

    def once(source: Any, target: Any) -> None:
        calls["count"] += 1
        if calls["count"] > 1:
            raise OSError("the second link failed")
        real(source, target)

    monkeypatch.setattr("vinga_server.capture_upload.os.link", once)

    a_recording(store, "s1")

    assert staged(store.directory) == []
    assert reasons(caplog) == [CaptureUploadFailure.STAGING_LOST]


def test_a_session_id_that_is_not_a_name_is_refused(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    """The one way a name could reach outside the staging root, turned
    away before any directory is made.

    Said on the module's own logger rather than as a
    `capture_upload_failed`, and that is forced rather than chosen: the
    event carries a `SessionId`, and an id this refuses is by definition
    not one, so there is no lawful event to emit about it. The ids this
    server mints are hex, so nothing real reaches here.
    """
    caplog.set_level(logging.DEBUG)
    uploads, _ = an_uploader(tmp_path)

    uploads.stage("../escape", tmp_path / "a.wav", tmp_path / "a.json")

    assert staged(tmp_path / "captures") == []
    assert reasons(caplog) == []
    assert "escape" not in caplog.text
    assert "session id" in caplog.text


# --- the two moments ---------------------------------------------------


@pytest.mark.asyncio
async def test_nothing_uploads_until_the_session_closes(tmp_path: Path, endpoint: str) -> None:
    """The seam's whole point. `finished()` means the files are final,
    not that the conversation is over."""
    uploads, recorder = an_uploader(tmp_path, traces={"s1": TRACE})
    store = capture_store(tmp_path, uploads=uploads)

    a_recording(store, "s1")

    assert recorder.asked == []
    store.session_closed("s1")
    await drained(uploads)
    assert recorder.kinds == ["audio/wav", "application/json"]


@pytest.mark.asyncio
async def test_a_capture_that_hit_its_duration_limit_still_waits(
    tmp_path: Path, endpoint: str
) -> None:
    """The first early-finish path: the recording stops at
    `max_session_s` and the conversation carries on."""
    uploads, recorder = an_uploader(tmp_path, traces={"s1": TRACE})
    store = capture_store(tmp_path, uploads=uploads, max_session_s=1.0)
    opened = time.monotonic()
    capture = store.open("s1", opened, CAPTURE_MANIFEST)
    assert capture is not None

    capture.microphone(tone(100), opened)
    capture.microphone(tone(100), opened + 2.0)

    assert staged(store.directory) == ["s1"]
    assert recorder.asked == []
    store.session_closed("s1")
    await drained(uploads)
    assert len(recorder.asked) == 2


@pytest.mark.asyncio
async def test_a_prune_between_the_two_moments_cannot_erase_the_pair(
    tmp_path: Path, endpoint: str
) -> None:
    """The delta round's finding, driven rather than argued.

    An early-finished capture is a prune candidate while its session
    talks on, so the links are taken ahead of prune-candidacy. What the
    prune unlinks is the triplet; the staged pair is the same inodes
    under another name, so it survives by construction, and this is the
    property that says so.

    A second recording is what makes the first prunable at all: the
    newest finished capture is never dropped, because a budget smaller
    than one session would otherwise delete the recording somebody just
    went out to make. So the storm is driven with a later session in the
    directory, which is also the shape the hazard really has.
    """
    uploads, recorder = an_uploader(tmp_path, traces={"s1": TRACE, "s2": TRACE})
    store = capture_store(tmp_path, uploads=uploads, max_session_s=1.0)
    opened = time.monotonic()
    early = store.open("s1", opened, CAPTURE_MANIFEST)
    assert early is not None
    early.microphone(tone(2000), opened)
    early.microphone(tone(100), opened + 2.0)
    a_recording(store, "s2")

    # A prune storm: a budget of nothing, run over and over the way a
    # busy server's session closes would run it.
    store._max_total_mb = 0.0
    for _ in range(5):
        store.prune()

    assert not early.wav_path.exists(), "the prune did not bite, so this proved nothing"
    assert staged(store.directory) == ["s1", "s2"]
    store.session_closed("s1")
    await drained(uploads)
    assert len(recorder.asked) == 2, "the staged pair did not survive the prune"
    assert recorder.asked[0].content_length > 44


@pytest.mark.asyncio
async def test_a_capture_the_manifest_disowns_is_never_uploaded(
    tmp_path: Path, caplog: pytest.LogCaptureFixture, endpoint: str
) -> None:
    """The second early-finish path. A write failure leaves
    `complete: false` and a header that may never have been patched, and
    attaching that would present broken evidence as evidence."""
    caplog.set_level(logging.DEBUG)
    uploads, recorder = an_uploader(tmp_path, traces={"s1": TRACE})
    store = capture_store(tmp_path, uploads=uploads)
    opened = time.monotonic()
    capture = store.open("s1", opened, CAPTURE_MANIFEST)
    assert capture is not None
    # White-box: a real failed write needs a file that cannot be written
    # to, and nothing public makes one.
    capture._wav.close()  # type: ignore[union-attr]
    capture.microphone(tone(100), opened)
    # The second write is what reaches the closed file: the first is
    # buffered behind the writer's flush lag.
    capture.microphone(tone(100), opened + 3.0)

    assert staged(store.directory) == []
    store.session_closed("s1")
    await drained(uploads)

    assert recorder.asked == []
    assert CaptureUploadFailure.INCOMPLETE in reasons(caplog)


# --- what reaches the far side ----------------------------------------


@pytest.mark.asyncio
async def test_the_pair_goes_out_as_two_attachments_of_their_own_kinds(
    tmp_path: Path, endpoint: str
) -> None:
    """Exactly two, with their MIME types, against the trace the session
    was exported under, and with a manifest that says it is complete."""
    uploads, recorder = an_uploader(tmp_path, traces={"s1": TRACE, "s2": OTHER_TRACE})
    store = capture_store(tmp_path, uploads=uploads)

    a_recording(store, "s1")
    store.session_closed("s1")
    await drained(uploads)

    assert recorder.kinds == ["audio/wav", "application/json"]
    assert [one.trace_id for one in recorder.asked] == [TRACE, TRACE]
    assert {one.field for one in recorder.asked} == {"metadata"}


@pytest.mark.asyncio
async def test_the_wav_that_goes_out_has_its_length_patched_in(
    tmp_path: Path, endpoint: str
) -> None:
    """The finalized header, which is the fact that makes the timing of
    the staging matter at all: a capture staged before its close would
    carry the placeholder."""
    uploads, recorder = an_uploader(tmp_path, traces={"s1": TRACE})
    store = capture_store(tmp_path, uploads=uploads)

    capture = a_recording(store, "s1")
    store.session_closed("s1")
    await drained(uploads)

    audio = recorder.asked[0]
    assert audio.content_length == capture.wav_path.stat().st_size
    # The placeholder header is 44 bytes with two zero length fields;
    # what went has both filled in, so the file is longer than its
    # header and the count the API was told matches the file.
    assert audio.content_length > 44


@pytest.mark.asyncio
async def test_the_manifest_that_goes_out_says_it_is_complete(
    tmp_path: Path, endpoint: str
) -> None:
    """The other half of the same claim, read off the staged file rather
    than off the capture's own belief about it."""
    uploads, _ = an_uploader(tmp_path, traces={"s1": TRACE})
    store = capture_store(tmp_path, uploads=uploads)

    a_recording(store, "s1")
    manifest = json.loads(
        (staging_root(store.directory) / "s1" / MANIFEST_NAME).read_text()
    )
    store.session_closed("s1")
    await drained(uploads)

    assert manifest["capture"]["complete"] is True


@pytest.mark.asyncio
async def test_the_staging_empties_when_the_job_is_done(tmp_path: Path, endpoint: str) -> None:
    """A job nobody will run again is room audio on a disk, whichever
    way it ended."""
    uploads, _ = an_uploader(tmp_path, traces={"s1": TRACE})
    store = capture_store(tmp_path, uploads=uploads)

    a_recording(store, "s1")
    store.session_closed("s1")
    await drained(uploads)

    assert staged(store.directory) == []


@pytest.mark.asyncio
async def test_an_attachment_that_landed_says_what_it_cost(
    tmp_path: Path, caplog: pytest.LogCaptureFixture, endpoint: str
) -> None:
    """The ledger's positive half: the two sizes exactly, and how long
    it took, and deliberately no URL and no far-side identifier."""
    caplog.set_level(logging.DEBUG)
    uploads, _ = an_uploader(tmp_path, traces={"s1": TRACE})
    store = capture_store(tmp_path, uploads=uploads)

    capture = a_recording(store, "s1")
    store.session_closed("s1")
    await drained(uploads)

    said = uploads_said(caplog)
    assert len(said) == 1
    held = fields_of(said[0])
    assert held["audio_bytes"] == capture.wav_path.stat().st_size
    assert held["session"] == "s1"
    assert "elapsed_ms" in held
    assert not any("url" in str(key).lower() for key in held)
    assert not any("media" in str(key).lower() for key in held)


@pytest.mark.asyncio
async def test_each_uploaded_file_is_referenced_back_onto_the_trace(
    tmp_path: Path, endpoint: str
) -> None:
    """The half that makes an attachment playable rather than merely
    stored.

    An upload associates a recording with a trace; what makes the backend
    render it is a reference token written back onto that trace, which
    both milestones' walkthroughs established. So the uploader asks the
    exporter for exactly that, once per file, in the backend's own
    spelling and naming the id the backend minted.
    """
    from tests.support.uploads import Traced

    traced = Traced({"s1": TRACE})
    uploads = CaptureUpload(
        tmp_path / "captures",
        sdk=fake_sdk()[0],
        telemetry=traced,  # type: ignore[arg-type]
        backlog=4,
        retries=0,
        shutdown_timeout_s=10.0,
    )
    store = capture_store(tmp_path, uploads=uploads)

    a_recording(store, "s1")
    store.session_closed("s1")
    await drained(uploads)

    assert len(traced.referenced) == 1
    session, references = traced.referenced[0]
    assert session == "s1"
    assert sorted(references) == ["capture_audio", "capture_manifest"]
    assert references["capture_audio"].startswith("@@@langfuseMedia:type=audio/wav|id=")
    assert references["capture_manifest"].startswith(
        "@@@langfuseMedia:type=application/json|id="
    )
    assert all(one.endswith("|source=bytes@@@") for one in references.values())
    # The ids are the far side's, one per file, and they are the only
    # far-side facts this server ever repeats: inside a token that only
    # the backend can resolve, and never in an event.
    assert len({one.split("|id=")[1] for one in references.values()}) == 2


@pytest.mark.asyncio
async def test_a_recording_nothing_points_at_is_reported_as_a_failure(
    tmp_path: Path, caplog: pytest.LogCaptureFixture, endpoint: str
) -> None:
    """`unreferenced`, which is the gap this surface exists to close
    wearing a success.

    The bytes landed and nothing points at them, so a reader has a trace,
    audio in a store they cannot reach from it, and no reason to think
    any is there. Said as a failure rather than as an upload with an
    asterisk, and the exporter refusing is the real shape of it: a server
    shutting down stops accepting spans while the worker is still
    finishing.
    """
    caplog.set_level(logging.DEBUG)
    uploads, recorder = an_uploader(
        tmp_path, traces={"s1": TRACE}, telemetry=exporting({"s1": TRACE}, refusing=True)
    )
    store = capture_store(tmp_path, uploads=uploads)

    a_recording(store, "s1")
    store.session_closed("s1")
    await drained(uploads)

    # The upload itself happened, which is what makes the reason the
    # right one rather than `unreachable`.
    assert recorder.kinds == ["audio/wav", "application/json"]
    assert reasons(caplog) == [CaptureUploadFailure.UNREFERENCED]
    assert uploads_said(caplog) == []


# --- the failures ------------------------------------------------------


@pytest.mark.asyncio
async def test_a_session_the_exporter_never_saw_cannot_be_attached(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    """`no_trace`, and it is never retried: M1's walkthrough established
    that the media API accepts a trace it has not ingested, so the only
    thing this reason means is that this server has no id to name."""
    caplog.set_level(logging.DEBUG)
    uploads, recorder = an_uploader(tmp_path, traces={})
    store = capture_store(tmp_path, uploads=uploads)

    a_recording(store, "s1")
    store.session_closed("s1")
    await drained(uploads)

    assert recorder.asked == []
    assert reasons(caplog) == [CaptureUploadFailure.NO_TRACE]
    assert staged(store.directory) == []


@pytest.mark.asyncio
async def test_a_staged_pair_that_vanished_is_reported_rather_than_guessed(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    """`staging_lost`, for the pair that was there at the close and gone
    at the worker."""
    caplog.set_level(logging.DEBUG)
    uploads, recorder = an_uploader(tmp_path, traces={"s1": TRACE})
    store = capture_store(tmp_path, uploads=uploads)

    a_recording(store, "s1")
    (staging_root(store.directory) / "s1" / AUDIO_NAME).unlink()
    store.session_closed("s1")
    await drained(uploads)

    assert recorder.asked == []
    assert reasons(caplog) == [CaptureUploadFailure.STAGING_LOST]


@pytest.mark.asyncio
async def test_a_backend_that_says_no_is_not_retried(
    tmp_path: Path, caplog: pytest.LogCaptureFixture, endpoint: str
) -> None:
    """`refused`: a credential the far side will not accept is not going
    to become acceptable in half a second, so the retries are spent on
    the failures that could change."""
    caplog.set_level(logging.DEBUG)
    # No status code, which is the generated client's own shape for
    # this one: it raises a typed `UnauthorizedError` carrying headers
    # and a body and no code at all, so what says the far side answered
    # is the class.
    seam, recorder = fake_sdk(asking=ApiError())
    uploads, _ = an_uploader(
        tmp_path, traces={"s1": TRACE}, sdk=seam, recorder=recorder, retries=2
    )
    store = capture_store(tmp_path, uploads=uploads)

    a_recording(store, "s1")
    store.session_closed("s1")
    await drained(uploads)

    assert reasons(caplog) == [CaptureUploadFailure.REFUSED]
    assert len(recorder.asked) == 1, "a refusal was retried"


@pytest.mark.asyncio
async def test_a_backend_that_is_down_is_retried_to_the_ceiling(
    tmp_path: Path, caplog: pytest.LogCaptureFixture, endpoint: str
) -> None:
    """`unreachable`, with the ceiling: two retries and then the event.
    Without a ceiling a wedged backend would mean no event ever fires."""
    caplog.set_level(logging.DEBUG)
    seam, recorder = fake_sdk(asking=ApiError(status_code=503))
    uploads, _ = an_uploader(
        tmp_path, traces={"s1": TRACE}, sdk=seam, recorder=recorder, retries=2
    )
    store = capture_store(tmp_path, uploads=uploads)

    a_recording(store, "s1")
    store.session_closed("s1")
    await drained(uploads)

    assert reasons(caplog) == [CaptureUploadFailure.UNREACHABLE]
    assert len(recorder.asked) == 3, "the retry ceiling is not three attempts"


@pytest.mark.asyncio
async def test_a_payload_over_the_backends_ceiling_says_so(
    tmp_path: Path, caplog: pytest.LogCaptureFixture, endpoint: str
) -> None:
    """`too_large`, which is a capture-length question rather than a
    deployment one, and is why it is told apart from the rest."""
    caplog.set_level(logging.DEBUG)
    seam, recorder = fake_sdk(asking=ApiError(status_code=413))
    uploads, _ = an_uploader(
        tmp_path, traces={"s1": TRACE}, sdk=seam, recorder=recorder, retries=2
    )
    store = capture_store(tmp_path, uploads=uploads)

    a_recording(store, "s1")
    store.session_closed("s1")
    await drained(uploads)

    assert reasons(caplog) == [CaptureUploadFailure.TOO_LARGE]


@pytest.mark.asyncio
async def test_a_client_that_cannot_be_constructed_is_an_upload_failure(
    tmp_path: Path, caplog: pytest.LogCaptureFixture, endpoint: str
) -> None:
    """The settled position on construction: it is deferred into the
    worker's first job, and every exception out of it is contained as a
    sanitized failure rather than a boot that refused or a thread that
    died."""
    caplog.set_level(logging.DEBUG)
    seam, recorder = fake_sdk(building=RuntimeError(f"cannot build with {SECRET}"))
    uploads, _ = an_uploader(
        tmp_path, traces={"s1": TRACE}, sdk=seam, recorder=recorder
    )
    store = capture_store(tmp_path, uploads=uploads)

    a_recording(store, "s1")
    store.session_closed("s1")
    await drained(uploads)

    assert reasons(caplog) == [CaptureUploadFailure.UNREACHABLE]
    assert SECRET not in both_formats(caplog)


@pytest.mark.asyncio
async def test_no_endpoint_at_all_is_an_upload_failure_and_not_a_default(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    """And specifically not the SDK's own default, which is a vendor's
    hosted endpoint: a server that quietly shipped room audio to a cloud
    nobody named would be the opposite of what this flag is for."""
    caplog.set_level(logging.DEBUG)
    uploads, recorder = an_uploader(tmp_path, traces={"s1": TRACE})
    store = capture_store(tmp_path, uploads=uploads)

    a_recording(store, "s1")
    store.session_closed("s1")
    await drained(uploads)

    assert recorder.constructed == []
    assert reasons(caplog) == [CaptureUploadFailure.UNREACHABLE]


# --- the bound ---------------------------------------------------------


@pytest.mark.asyncio
async def test_a_full_backlog_drops_with_its_links_and_its_event(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    """The bound is best-effort and says so. A job the backlog turns
    away has its links removed in the same breath as the event, because
    a job nobody will ever run is room audio waiting on a disk."""
    caplog.set_level(logging.DEBUG)
    uploads, recorder = an_uploader(
        tmp_path, traces={f"s{index}": TRACE for index in range(4)}, backlog=1
    )
    store = capture_store(tmp_path, uploads=uploads)
    # The worker is what would empty the queue, so the bound is only
    # observable while nothing is draining it.
    uploads._stopping.set()

    for index in range(4):
        a_recording(store, f"s{index}")
        store.session_closed(f"s{index}")

    dropped = [one for one in reasons(caplog) if one == CaptureUploadFailure.DROPPED]
    assert len(dropped) == 3
    # One job admitted and still staged, three refused and cleaned.
    assert len(staged(store.directory)) == 1
    assert recorder.asked == []


@pytest.mark.asyncio
async def test_every_job_of_a_full_drain_is_accounted_for(
    tmp_path: Path, caplog: pytest.LogCaptureFixture, endpoint: str
) -> None:
    """The drain the bound is sized for: a full server's sessions
    closing at once, with the backlog already occupied by jobs from
    earlier ones.

    What is asserted is accounting rather than success: every session
    either attached or said why not, and none of them vanished. The
    staging directory is empty at the end, which is the same claim from
    the disk's side.
    """
    caplog.set_level(logging.DEBUG)
    sessions = [f"s{index}" for index in range(8)]
    uploads, _ = an_uploader(
        tmp_path, traces={session: TRACE for session in sessions}, backlog=8
    )
    store = capture_store(tmp_path, uploads=uploads)
    # The backlog occupied before the drain begins, which is the case
    # the plan names: jobs from sessions that closed earlier.
    uploads._stopping.set()
    for session in sessions[:4]:
        a_recording(store, session)
        store.session_closed(session)
    uploads._stopping.clear()

    for session in sessions[4:]:
        a_recording(store, session)
        store.session_closed(session)
    await drained(uploads)

    accounted = {
        str(fields_of(record)["session"])
        for record in caplog.records
        if getattr(record, "event", None) in {"capture_uploaded", "capture_upload_failed"}
    }
    assert accounted == set(sessions)
    assert staged(store.directory) == []


# --- the sweep ---------------------------------------------------------


def test_a_restart_says_what_it_found_staged_and_removes_it(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    """A restart must not be the thing that silently discards the only
    record that an upload never happened."""
    caplog.set_level(logging.DEBUG)
    store = capture_store(tmp_path)
    store.directory.mkdir(parents=True, exist_ok=True)
    a_leftover(store.directory, "s1")
    a_leftover(store.directory, "s2")

    sweep_upload_staging(store.directory)

    assert reasons(caplog) == [
        CaptureUploadFailure.ABANDONED,
        CaptureUploadFailure.ABANDONED,
    ]
    assert staged(store.directory) == []


def test_a_boot_with_no_uploader_still_sweeps(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    """The delta round's second finding, and the reason the sweep is the
    store's: a next boot with the flag off, capture off, local_only on
    or the extra gone builds no uploader at all."""
    caplog.set_level(logging.DEBUG)
    store = capture_store(tmp_path)
    store.directory.mkdir(parents=True, exist_ok=True)
    a_leftover(store.directory, "s1")

    assert store._uploads is None
    sweep_upload_staging(store.directory)

    assert reasons(caplog) == [CaptureUploadFailure.ABANDONED]
    assert staged(store.directory) == []


def test_a_job_younger_than_this_process_is_left_alone(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    """Sequential lifespans in one process share a staging directory,
    and a prior lifespan's worker may still hold a job in flight:
    adopting it would mean deleting a pair out from under an upload that
    is happening."""
    caplog.set_level(logging.DEBUG)
    store = capture_store(tmp_path)
    store.directory.mkdir(parents=True, exist_ok=True)
    a_leftover(store.directory, "s1", aged=False)

    sweep_upload_staging(store.directory)

    assert reasons(caplog) == []
    assert staged(store.directory) == ["s1"]


def test_a_staging_that_never_committed_goes_without_a_word(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    """There was never a job to abandon: a directory under the building
    name is a pair that was half made, and what it needs is removing."""
    caplog.set_level(logging.DEBUG)
    store = capture_store(tmp_path)
    store.directory.mkdir(parents=True, exist_ok=True)
    a_leftover(store.directory, ".s1.building")

    sweep_upload_staging(store.directory)

    assert reasons(caplog) == []
    assert staged(store.directory) == []


def test_a_directory_with_nothing_staged_sweeps_nothing(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    """The ordinary boot, which is every boot: no staging root, no
    events, no complaint."""
    caplog.set_level(logging.DEBUG)
    store = capture_store(tmp_path)

    sweep_upload_staging(store.directory)

    assert reasons(caplog) == []


def a_leftover(directory: Path, session: str, *, aged: bool = True) -> Path:
    """One job on disk as a previous run would have left it."""
    job = staging_root(directory) / session
    job.mkdir(parents=True, exist_ok=True)
    (job / AUDIO_NAME).write_bytes(b"RIFF")
    (job / MANIFEST_NAME).write_text("{}")
    if aged:
        __import__("os").utime(job, (0, 0))
    return job


# --- the sweep, from a boot -------------------------------------------
#
# The round's third finding, and the reason these are composition-level
# rather than more calls to the function: what it caught is not the
# sweep's own behaviour but WHERE it was called from. A store is built
# only where capture is enabled, and the uploader's builder runs ahead of
# it and can refuse, so each of these four configurations reached
# neither and left staged room audio on disk. A case that called the
# function directly would have passed against every one of them.

BOOTS = (
    pytest.param(
        {"capture": {"enabled": True}, "telemetry": {"enabled": True}},
        False,
        id="attachment-off",
    ),
    pytest.param(
        {
            "capture": {"enabled": False},
            "telemetry": {"enabled": True, "attach_captures": True},
        },
        False,
        id="capture-disabled",
    ),
    pytest.param(
        {
            "capture": {"enabled": True},
            "telemetry": {"enabled": True, "attach_captures": True},
            "local_only": True,
        },
        True,
        id="local-only",
    ),
    pytest.param(
        {
            "capture": {"enabled": True},
            "telemetry": {"enabled": True, "attach_captures": True},
        },
        True,
        id="extra-absent",
    ),
)


@pytest.mark.parametrize(("server", "refuses"), BOOTS)
def test_every_boot_with_a_capture_section_sweeps_what_was_left(
    server: dict[str, Any],
    refuses: bool,
    tmp_path: Path,
    caplog: pytest.LogCaptureFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Four boots, each with a job a previous run left staged, and each
    of them says so and removes it.

    Two boot and two refuse, and the refusals are the point: `local_only`
    exits above the capture section entirely, at the exporter, and the
    missing extra exits above the store. A sweep that ran from either of
    those would never run at all.
    """
    import vinga_server.capture_upload as module
    from tests.support.apps import entered_client
    from tests.support.configs import config_with_agent
    from vinga_server.app import StartupFailed

    caplog.set_level(logging.DEBUG)
    captures = tmp_path / "captures"
    a_leftover(captures, "s1")
    if server is BOOTS[3].values[0]:
        monkeypatch.setattr(module, "_import_sdk", lambda: None)
    section = dict(server["capture"])
    section["dir"] = str(captures)
    config = config_with_agent(server={**server, "capture": section})

    if refuses:
        with pytest.raises(StartupFailed):
            with entered_client(config):
                pass
    else:
        with entered_client(config):
            pass

    assert reasons(caplog) == [CaptureUploadFailure.ABANDONED]
    assert staged(captures) == []


def test_a_boot_with_no_capture_section_leaves_the_directory_alone(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    """The one configuration that touches nothing, which is stated in the
    flag's own reference prose: removing the section parks the sweep with
    the rest of the capture machinery."""
    from tests.support.apps import entered_client
    from tests.support.configs import config_with_agent

    caplog.set_level(logging.DEBUG)
    captures = tmp_path / "captures"
    a_leftover(captures, "s1")

    with entered_client(config_with_agent()):
        pass

    assert reasons(caplog) == []
    assert staged(captures) == ["s1"]


# --- what may never leak ----------------------------------------------


@pytest.fixture
def planted(monkeypatch: pytest.MonkeyPatch) -> str:
    """The credential sentinel where one genuinely arrives: the two
    variables the SDK reads, and the endpoint, which is a URL an
    operator may have pasted a password into."""
    monkeypatch.setenv(LANGFUSE_SECRET_KEY_ENV, SECRET)
    monkeypatch.setenv(LANGFUSE_PUBLIC_KEY_ENV, SECRET)
    monkeypatch.setenv(LANGFUSE_HOST_ENV, f"http://user:{SECRET}@127.0.0.1:1")
    return SECRET


def a_hostile_manifest() -> dict[str, Any]:
    """The other untrusted family: a manifest carries what a device said
    about itself, so a field of it is where content-shaped text
    arrives."""
    return {**CAPTURE_MANIFEST, "device": {"mac": HOSTILE, "client": HOSTILE}}


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("failing", "reason"),
    [
        ("refused", CaptureUploadFailure.REFUSED),
        ("unreachable", CaptureUploadFailure.UNREACHABLE),
        ("construction", CaptureUploadFailure.UNREACHABLE),
    ],
)
async def test_no_failure_family_leaks_either_sentinel(
    tmp_path: Path,
    caplog: pytest.LogCaptureFixture,
    capsys: pytest.CaptureFixture[str],
    planted: str,
    failing: str,
    reason: str,
) -> None:
    """The sentinel battery, one run per family of failure.

    Both sentinels, hunted in both log formats, in both events'
    payloads, in stderr and in the exception chain of anything the
    shutdown raised: a traceback is the other way a library's message
    reaches a terminal.
    """
    caplog.set_level(logging.DEBUG)
    planted_failure: BaseException = RuntimeError(f"the far side said {SECRET}")
    seam, recorder = fake_sdk(
        asking=ApiError(status_code=401, body=SECRET)
        if failing == "refused"
        else planted_failure
        if failing == "unreachable"
        else None,
        building=planted_failure if failing == "construction" else None,
    )
    uploads, _ = an_uploader(
        tmp_path, traces={"s1": TRACE}, sdk=seam, recorder=recorder
    )
    store = capture_store(tmp_path, uploads=uploads)

    capture = store.open("s1", time.monotonic(), a_hostile_manifest())
    assert capture is not None
    capture.microphone(tone(100), time.monotonic())
    capture.close()
    store.session_closed("s1")
    await drained(uploads)

    captured = capsys.readouterr()
    rendered = both_formats(caplog)
    assert reasons(caplog) == [reason]
    assert planted not in rendered
    assert HOSTILE not in rendered
    assert planted not in captured.err + captured.out
    assert HOSTILE not in captured.err + captured.out


@pytest.mark.asyncio
async def test_the_session_id_appears_only_where_it_is_declared(
    tmp_path: Path, caplog: pytest.LogCaptureFixture, endpoint: str
) -> None:
    """The positional assertion the review round asked for instead of an
    absence claim.

    Both events deliberately carry `session`, and the policy treats a
    bounded server-minted id as a trusted identifier. So what is
    asserted is that it appears in the declared position and stays
    bounded by `SessionId`, rather than that it does not appear.
    """
    from vinga_server.events.values import SessionId

    caplog.set_level(logging.DEBUG)
    uploads, _ = an_uploader(tmp_path, traces={"s1": TRACE})
    store = capture_store(tmp_path, uploads=uploads)

    a_recording(store, "s1")
    store.session_closed("s1")
    await drained(uploads)

    said = uploads_said(caplog)
    assert len(said) == 1
    held = fields_of(said[0])
    assert held["session"] == "s1"
    assert [key for key, value in held.items() if value == "s1"] == ["session"]
    assert SessionId("s1").value == "s1"


@pytest.mark.asyncio
async def test_the_trace_id_never_reaches_an_event(
    tmp_path: Path, caplog: pytest.LogCaptureFixture, endpoint: str
) -> None:
    """The correlation identifier stays out of the catalog, which is the
    plan's standing rejection of carrying it on a payload: it would put
    a fact about one reader's backend into every consumer's
    vocabulary."""
    caplog.set_level(logging.DEBUG)
    uploads, _ = an_uploader(tmp_path, traces={"s1": TRACE})
    store = capture_store(tmp_path, uploads=uploads)

    a_recording(store, "s1")
    store.session_closed("s1")
    await drained(uploads)

    assert TRACE not in both_formats(caplog)


# --- the SDK's own voice ----------------------------------------------


@pytest.mark.asyncio
async def test_the_sdk_namespace_is_quiet_before_the_worker_does_anything(
    tmp_path: Path, endpoint: str
) -> None:
    """The lease, over the SDK's namespace and the HTTP stack it drives.

    The stack is the half that matters: `httpx` logs a request line
    carrying its URL, and the URL of an upload's second request is a
    presigned one, which is a credential in a query string.

    Observed at the FIRST thing the worker does for a job rather than at
    the client's construction, and the difference is what the case is
    worth: a lease taken just before the constructor would pass a check
    at the constructor and still leave the namespace loud for anything
    the worker did in front of it.
    """
    quiet: list[bool] = []

    class Watching:
        def trace_of(self, session: str) -> str | None:
            quiet.append(logging.getLogger("httpx").propagate is False)
            return TRACE

        def reference_media(self, session: str, references: dict[str, str]) -> bool:
            return True

    seam, _ = fake_sdk()
    uploads = CaptureUpload(
        tmp_path / "captures",
        sdk=seam,
        telemetry=Watching(),  # type: ignore[arg-type]
        backlog=4,
        retries=0,
        shutdown_timeout_s=10.0,
    )
    store = capture_store(tmp_path, uploads=uploads)
    before = logging.getLogger("httpx").propagate

    a_recording(store, "s1")
    store.session_closed("s1")
    await drained(uploads)

    assert quiet == [True], "the namespace was not quiet before the worker ran"
    assert logging.getLogger("httpx").propagate is before


@pytest.mark.asyncio
async def test_the_lease_goes_back_when_the_worker_genuinely_stops(
    tmp_path: Path, endpoint: str
) -> None:
    """And it is one process-wide claim, so a lane that left one held
    would silence every case after it."""
    uploads, _ = an_uploader(tmp_path, traces={"s1": TRACE})
    store = capture_store(tmp_path, uploads=uploads)

    a_recording(store, "s1")
    store.session_closed("s1")
    await drained(uploads)

    assert _QUIETING.held() == 0


@pytest.mark.asyncio
async def test_an_uploader_that_outlived_its_bound_keeps_the_next_one_quiet(
    tmp_path: Path, endpoint: str
) -> None:
    """The overlapping-lifespans case, which is why the quieting is one
    process-wide claim rather than one per uploader.

    Two uploaders exist routinely: a wedged worker outlives its
    shutdown's bound, so a redeploy builds the next one while the last
    is still finishing. With a claim each, A's release restores the
    original configuration while B is still uploading, so B's next
    presigned URL reaches the retained log, and B's own release then
    restores A's already-quiet snapshot and silences the namespaces for
    the rest of the process with nothing holding them.

    Driven in that order: A wedges, A's bounded wait expires, B runs, A
    finishes, and the namespaces are asserted quiet at every step until
    B is genuinely done.
    """
    held = threading.Event()
    release = threading.Event()
    quiet_while_b_ran: list[bool] = []

    def wedging(**options: Any) -> Any:
        held.set()
        release.wait(30.0)
        raise RuntimeError("A never got anywhere")

    first, recorder = fake_sdk()
    wedged = CaptureUpload(
        tmp_path / "a",
        sdk=type(first)(client=wedging, error=first.error, content_type=str),
        telemetry=exporting({"s1": TRACE}),
        backlog=4,
        retries=0,
        shutdown_timeout_s=0.2,
    )
    store_a = capture_store(tmp_path / "a-dir", uploads=wedged)

    class Watching:
        def trace_of(self, session: str) -> str | None:
            quiet_while_b_ran.append(logging.getLogger("httpx").propagate is False)
            return TRACE

        def reference_media(self, session: str, references: dict[str, str]) -> bool:
            return True

    second, _ = fake_sdk(recorder)
    running = CaptureUpload(
        tmp_path / "b",
        sdk=second,
        telemetry=Watching(),  # type: ignore[arg-type]
        backlog=4,
        retries=0,
        shutdown_timeout_s=10.0,
    )
    store_b = capture_store(tmp_path / "b-dir", uploads=running)

    try:
        a_recording(store_a, "s1")
        store_a.session_closed("s1")
        assert held.wait(10.0), "A never reached its client"
        assert _QUIETING.held() == 1

        # A's bounded wait expires with its worker still inside the
        # client, which is the state this case is about.
        await wedged.shutdown()
        assert _QUIETING.held() == 1, "the expired wait gave the silence back"

        a_recording(store_b, "s1")
        store_b.session_closed("s1")
        await asyncio.sleep(0.2)
        assert _QUIETING.held() == 2

        # A finishes now, on the abandoned side of its own timeout.
        release.set()
        deadline = time.monotonic() + 10.0
        while _QUIETING.held() > 1 and time.monotonic() < deadline:
            await asyncio.sleep(0.02)

        assert _QUIETING.held() == 1, "A's release did not come back at all"
        assert logging.getLogger("httpx").propagate is False, (
            "A's release un-silenced the HTTP stack while B was still working"
        )
        assert quiet_while_b_ran == [True]
    finally:
        release.set()
        await wedged.shutdown()
        await running.shutdown()

    assert _QUIETING.held() == 0
    assert logging.getLogger("httpx").propagate is not False


@pytest.mark.asyncio
async def test_only_the_documented_host_variable_is_read(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """One documented name for where a recording goes.

    The SDK's own tracing client honors `LANGFUSE_BASE_URL` ahead of
    `LANGFUSE_HOST`; this module reads only the second, because that
    client is not the one it uses, nothing in this repository documents
    the alias, and a variable an operator never wrote taking precedence
    over the one they did is a way for room audio to reach a deployment
    nobody named.
    """
    monkeypatch.setenv(LANGFUSE_HOST_ENV, "http://named.invalid:53010")
    monkeypatch.setenv("LANGFUSE_BASE_URL", "http://elsewhere.invalid:53010")
    uploads, recorder = an_uploader(tmp_path, traces={"s1": TRACE})
    store = capture_store(tmp_path, uploads=uploads)

    a_recording(store, "s1")
    store.session_closed("s1")
    await drained(uploads)

    assert [one["base_url"] for one in recorder.constructed] == [
        "http://named.invalid:53010"
    ]


@pytest.mark.asyncio
async def test_the_alias_alone_is_no_endpoint_at_all(
    tmp_path: Path, caplog: pytest.LogCaptureFixture, monkeypatch: pytest.MonkeyPatch
) -> None:
    """And the other half of the same claim: the alias on its own does
    not configure anything, so an operator who wrote only it gets the
    ordinary no-endpoint failure rather than a silent upload."""
    caplog.set_level(logging.DEBUG)
    monkeypatch.setenv("LANGFUSE_BASE_URL", "http://elsewhere.invalid:53010")
    uploads, recorder = an_uploader(tmp_path, traces={"s1": TRACE})
    store = capture_store(tmp_path, uploads=uploads)

    a_recording(store, "s1")
    store.session_closed("s1")
    await drained(uploads)

    assert recorder.constructed == []
    assert reasons(caplog) == [CaptureUploadFailure.UNREACHABLE]


@pytest.mark.asyncio
async def test_a_shutdown_with_no_worker_is_not_an_error(tmp_path: Path) -> None:
    """Most servers never upload anything, so the ordinary teardown is
    one that has no thread to wait for."""
    uploads, _ = an_uploader(tmp_path)

    await uploads.shutdown()

    assert _QUIETING.held() == 0


@pytest.fixture(autouse=True)
def _no_lease_outlives_its_case() -> Iterator[None]:
    """Every uploader a case built has given its claim back.

    Asserted as well as tidied, because a leak that a fixture cleans up
    is a leak a server would have too.
    """
    yield
    assert _QUIETING.held() == 0, "a case left an uploader holding the silence"
    assert logging.getLogger("langfuse").propagate is not False
