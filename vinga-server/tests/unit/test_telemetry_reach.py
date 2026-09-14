"""One reach assertion, three destinations (#502 M4b).

`server.telemetry.reach` is the operator's statement about where this
section's exports point, and it is the second argument the three
`check_feature` call sites pass. The suite is here rather than split
across the three builders' own files because the claim IS the joining
up: one key governs the OTLP endpoint the traces and the transcripts
ride and the Langfuse REST host the recording upload uses, and a claim
about "every destination" asserted three times in three modules is a
claim nobody reads as one.

Four things are pinned, and the first is the reason the other three are
safe to have:

- **Absent is today's behaviour**, at every site and at every boundary.
  The three sites passed a fixed `Reach.INTERNET` before this key
  existed, so a deployment that upgrades into it and writes nothing is
  admitted and refused in precisely the cases it was. Both halves are
  asserted, the admit/refuse table and the sentence itself, because a
  default that silently narrowed is the one upgrade-breaking mistake
  available here and each half catches a different way of making it.
- **A declared reach widens**, and it widens all three features at once.
- **A reach wider than the boundary still refuses**, so the key asserts
  rather than overrides.
- **The refusal says where the reach came from and nothing else.** It
  names the switch, the reach, the boundary and the declaration, and no
  endpoint, host or credential, which is driven with an environment full
  of them rather than asserted about a format string.
"""

import logging
from collections.abc import Callable, Iterator
from typing import Any

import pytest

from tests.support.events import both_formats
from tests.support.telemetry import BUILT, released
from tests.support.transcripts import exporting as transcript_telemetry
from tests.support.uploads import exporting as upload_telemetry
from vinga_server.boundary import FEATURE_REACH_KEY, BoundaryRefusal, Reach, check_feature
from vinga_server.capture_upload import ATTACH_KEY, build_capture_upload
from vinga_server.config import ConfigError
from vinga_server.config.models import DatabaseConfig, ServerConfig
from vinga_server.events import Emission, attach_server_tap, detach_server_tap
from vinga_server.telemetry import TELEMETRY_KEY, build_telemetry
from vinga_server.transcript_export import TRANSCRIPTS_KEY, build_transcript_export

# Credential-shaped, and planted in every variable either transport
# reads: the collector's address, the headers that carry its token, and
# the three the Langfuse REST client is handed. A refusal about distance
# is exactly the sentence that must not repeat any of them back.
SECRET = "sk-lf-0TELEMETRYREACH-SENTINEL"

ENVIRONMENT = {
    "OTEL_EXPORTER_OTLP_ENDPOINT": f"https://{SECRET}.collector.invalid:4318",
    "OTEL_EXPORTER_OTLP_HEADERS": f"authorization=Bearer {SECRET}",
    "LANGFUSE_HOST": f"https://user:{SECRET}@langfuse.invalid",
    "LANGFUSE_PUBLIC_KEY": SECRET,
    "LANGFUSE_SECRET_KEY": SECRET,
}


@pytest.fixture(autouse=True)
def _release_what_a_case_built() -> Iterator[None]:
    """Every exporter a case here built is released at the end of it: the
    SDK's logging is quieted process-wide while one holds a lease."""
    yield
    released()


def a_server(*, reach: Reach | None = None, boundary: Reach | None = None) -> ServerConfig:
    """One server with all three exporting features armed, so a case
    about the section's reach drives every destination it covers.

    The key is written only when a case declares one, because the claim
    under test is what an ABSENT key means and a case that always wrote
    a value could not make it.
    """
    telemetry: dict[str, Any] = {
        "enabled": True,
        "export_audio": True,
        "export_transcripts": True,
    }
    if reach is not None:
        telemetry["reach"] = reach.value
    server: dict[str, Any] = {
        "capture": {"enabled": True, "dir": "/tmp/vinga-captures"},
        "conversations": {"enabled": True, "text": True},
        "telemetry": telemetry,
    }
    if boundary is not None:
        server["data_boundary"] = boundary.value
    return ServerConfig.model_validate(server)


def a_traced_exporter(config: ServerConfig, boundary: Reach | None) -> object | None:
    from opentelemetry.sdk.trace.export.in_memory_span_exporter import (
        InMemorySpanExporter,
    )

    built = build_telemetry(
        config.telemetry, boundary=boundary, exporter=InMemorySpanExporter()
    )
    if built is not None:
        BUILT.append(built)
    return built


def a_transcript_export(config: ServerConfig, boundary: Reach | None) -> object | None:
    held, _ = transcript_telemetry()
    return build_transcript_export(
        config, telemetry=held, database=DatabaseConfig(), boundary=boundary
    )


def a_capture_upload(config: ServerConfig, boundary: Reach | None) -> object | None:
    return build_capture_upload(config, telemetry=upload_telemetry(), boundary=boundary)


Build = Callable[[ServerConfig, Reach | None], object | None]

# The three features one assertion covers, each with the switch its own
# refusal names. Every case below runs against all three, because "every
# destination the section sends to" is not a claim one of them can make.
SITES: tuple[tuple[str, Build], ...] = (
    (TELEMETRY_KEY, a_traced_exporter),
    (TRANSCRIPTS_KEY, a_transcript_export),
    (ATTACH_KEY, a_capture_upload),
)

SITE_IDS = [key for key, _ in SITES]


class Recorder:
    """Every emission the server channels offered while a case ran."""

    def __init__(self) -> None:
        self.seen: list[Emission] = []

    def emit(self, emission: Emission) -> None:
        self.seen.append(emission)


# --- absent means internet, which is what today does -------------------


@pytest.mark.parametrize(("key", "build"), SITES, ids=SITE_IDS)
@pytest.mark.parametrize("boundary", [None, Reach.INTERNET, Reach.NETWORK, Reach.HOST])
def test_the_absent_key_admits_and_refuses_exactly_what_today_does(
    key: str, build: Build, boundary: Reach | None
) -> None:
    """The upgrade proof, as a table rather than a sentence.

    A file that says nothing about reach gets the fixed `Reach.INTERNET`
    the three sites passed before this key existed: built with no
    boundary and under `internet`, refused under `network` and `host`.
    A default that narrowed to `network` would admit the third row and a
    default of `host` the last two, so the mutation this is written
    against fails the table rather than merely reading differently.
    """
    config = a_server(boundary=boundary)
    refuses = boundary in (Reach.HOST, Reach.NETWORK)

    if refuses:
        with pytest.raises(ConfigError) as refusal:
            build(config, boundary)
        assert key in str(refusal.value)
    else:
        assert build(config, boundary) is not None


@pytest.mark.parametrize(("key", "build"), SITES, ids=SITE_IDS)
@pytest.mark.parametrize("boundary", [Reach.HOST, Reach.NETWORK])
def test_the_absent_key_refuses_in_todays_words(
    key: str, build: Build, boundary: Reach
) -> None:
    """The other half of the upgrade proof, and the half a table cannot
    make: the sentence an undeclared deployment is refused with is the
    one a fixed `Reach.INTERNET` composes, character for character.

    Differential rather than golden, so the wording stays the boundary
    module's to choose while the DEFAULT stays pinned: a default of
    `network` would still refuse under `host`, and would say so in a
    different sentence.
    """
    with pytest.raises(BoundaryRefusal) as fixed:
        check_feature(key, Reach.INTERNET, boundary)
    with pytest.raises(ConfigError) as boot:
        build(a_server(boundary=boundary), boundary)

    assert str(boot.value) == str(fixed.value)


# --- a declaration widens, and widens all three ------------------------


@pytest.mark.parametrize(("key", "build"), SITES, ids=SITE_IDS)
@pytest.mark.parametrize(
    ("reach", "boundary"),
    [
        (Reach.HOST, Reach.HOST),
        (Reach.HOST, Reach.NETWORK),
        (Reach.NETWORK, Reach.NETWORK),
    ],
)
def test_a_declared_reach_admits_what_a_fixed_internet_refused(
    key: str, build: Build, reach: Reach, boundary: Reach
) -> None:
    """The case the key exists for: a collector on the LAN, or on this
    machine, under a deployment that declared its data boundary.

    Every cell here is one a fixed `Reach.INTERNET` refused, which is
    asserted rather than assumed so the case cannot quietly become a
    restatement of the row above it.
    """
    with pytest.raises(BoundaryRefusal):
        check_feature(key, Reach.INTERNET, boundary)

    assert build(a_server(reach=reach, boundary=boundary), boundary) is not None


def test_one_assertion_covers_every_destination_the_section_sends_to() -> None:
    """The milestone's own sentence, driven: one key, written once,
    admits the exporter, the transcript export and the recording upload
    together under a boundary that refuses all three without it.

    Written as one configuration built three ways rather than three
    parametrized cells, because what is being shown is that the three
    read the SAME declaration: three cells would pass equally against
    three keys.
    """
    config = a_server(reach=Reach.NETWORK, boundary=Reach.NETWORK)

    assert [build(config, Reach.NETWORK) is not None for _, build in SITES] == [
        True,
        True,
        True,
    ]


# --- and it asserts rather than overrides ------------------------------


@pytest.mark.parametrize(("key", "build"), SITES, ids=SITE_IDS)
@pytest.mark.parametrize(
    ("reach", "boundary"),
    [
        (Reach.NETWORK, Reach.HOST),
        (Reach.INTERNET, Reach.HOST),
        (Reach.INTERNET, Reach.NETWORK),
    ],
)
def test_a_reach_wider_than_the_boundary_is_still_refused(
    key: str, build: Build, reach: Reach, boundary: Reach
) -> None:
    """The key is a declaration, not a waiver: writing a reach the
    boundary does not admit refuses the boot exactly as the fixed one
    did, and the sentence names the reach that was declared."""
    with pytest.raises(ConfigError) as refusal:
        build(a_server(reach=reach, boundary=boundary), boundary)

    said = str(refusal.value)
    assert key in said
    assert reach.value in said
    assert boundary.value in said


# --- what the refusal says, and what it must never say -----------------


@pytest.mark.parametrize(("key", "build"), SITES, ids=SITE_IDS)
def test_the_refusal_names_the_switch_the_reach_the_boundary_and_the_declaration(
    key: str, build: Build
) -> None:
    """The one fact the sentence gains: which of the operator's own
    statements produced the reach it is refusing. Without it a reader of
    a refusal under a declared `network` has no way to tell the reach
    apart from something this server decided for them."""
    with pytest.raises(ConfigError) as refusal:
        build(a_server(boundary=Reach.HOST), Reach.HOST)

    said = str(refusal.value)
    assert key in said
    assert Reach.INTERNET.value in said
    assert Reach.HOST.value in said
    assert FEATURE_REACH_KEY in said


@pytest.mark.parametrize(("key", "build"), SITES, ids=SITE_IDS)
def test_no_refusal_renders_an_endpoint_a_host_or_a_credential(
    key: str,
    build: Build,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """The environment is full of the strings a refusal about distance
    must not carry, and the refusal is produced inside it.

    Hunted in every rendering a deployment keeps: the sentence itself,
    both log formats and the typed `record.args` behind them, and every
    emission an attached server tap was offered. The tap is the half a
    log hunt cannot make, because a tap consumer is a second transport
    for the same events and a payload is what reaches it.
    """
    caplog.set_level(logging.DEBUG)
    for name, value in ENVIRONMENT.items():
        monkeypatch.setenv(name, value)
    recorder = Recorder()
    attach_server_tap(recorder)
    try:
        with pytest.raises(ConfigError) as refusal:
            build(a_server(boundary=Reach.HOST), Reach.HOST)
    finally:
        detach_server_tap(recorder)

    assert SECRET not in str(refusal.value)
    assert SECRET not in both_formats(caplog)
    assert SECRET not in repr(recorder.seen)
