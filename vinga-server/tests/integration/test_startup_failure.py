"""A boot that refuses, through the entry point a deployment runs.

Construction is the lifespan's since #142, which puts it inside uvicorn
rather than in front of it. Three things about that are only true in a
real process: uvicorn renders a lifespan exception by formatting its
whole traceback into a log line, it ends the process itself when a
lifespan startup fails, and the exit code is set by `main()` after
`serve()` has returned. None of them can be checked from a test that
builds an application object and enters it by hand, so this one runs the
real entry point in a process of its own and reads what came out.

What must come out is one sanitized sentence and an exit code of 1,
exactly what an operator read when the same failure happened in front of
`serve()`. One sentence, and nothing around it: no traceback, no frames
from this application or from anything under it, and not the name of the
exception class the bridge uses to carry the refusal out. That is the
whole assertion in `refused`, and every refusal below is held to it.

What must not come out is anything the failure was chained from: a
provider failure this deep carries a driver's or a client library's own
exception, and those quote the URL or the credential they were
configured with.
"""

import os
import subprocess
import sys
from pathlib import Path

import pytest

from vinga_server.config.models import DatabaseConfig
from vinga_server.config.store import ConfigStore
from vinga_server.db import open_database
from vinga_server.telemetry import CANNOT_BUILD_EXPORTER

STAGES = ("llm", "asr", "tts", "vad")

# Not a credential: a fixed string shaped like one, and shaped so a
# substring hunt for it cannot match by accident. It rides in on the
# `__cause__` of the refusal, which is where a real one would be.
SENTINEL = "sk-live-2f8c41d7-never-a-real-credential"

# What the registry composes when a provider factory raises something of
# its own: the entry, the type and the exception's class, and nothing the
# library said. Matched as a fragment, since counting a distinctive one
# is what "said once" means here.
PROVIDER_SENTENCE = "providers.llm.mock: the mock provider would not build (ValueError)"

# The real entry point, with one provider factory raising the way a
# third-party client does when it cannot start: a message quoting the
# endpoint and the key it was handed. The factory is replaced rather than
# the whole build, so what composes the operator's sentence is the
# registry's own wrapper, which is the thing under test.
PROVIDER_REFUSAL = f"""
import sys

from vinga_server.providers import mock


def refuse(label, config):
    raise ValueError("POST https://api.example/v1/chat failed for key {SENTINEL}")


mock.build_llm = refuse

import vinga_server.main as main

sys.argv = ["vinga-server"]
main.main()
"""


# A boot that reads its domain half and nothing else: what refuses is in
# the database this seeds.
PLAIN_ENTRYPOINT = """
import sys

import vinga_server.main as main

sys.argv = ["vinga-server"]
main.main()
"""

# An environment variable nothing sets, named so that nothing else can
# have set it either.
UNSET_VARIABLE = "VINGA_STARTUP_FAILURE_TEST_TOKEN"

MCP_SENTENCE = (
    f"mcp_servers.tools: mcp_servers.tools.env.API_TOKEN: references ${UNSET_VARIABLE}, "
    f"but it is not set in the environment"
)


def seed_domain(database: str, entry: dict[str, object] | None = None) -> None:
    """A database holding one agent on the mock providers, and one MCP
    server for it to reach when the caller wants one.

    The domain half of a configuration lives in the database and the
    entry point reads it there, so a boot that has to get as far as
    building something needs one written where a deployment writes it.
    Only a referenced MCP entry is built at boot, which is why the agent
    names it.
    """
    agent: dict[str, object] = {"prompt": "A"}
    if entry is not None:
        agent["mcp"] = ["tools"]
    engine = open_database(DatabaseConfig(name=database))
    try:
        store = ConfigStore(engine)
        for stage in STAGES:
            store.set_provider(stage, "mock", {"type": "mock"})
        store.set_agent_defaults(dict.fromkeys(STAGES, "mock"))
        if entry is not None:
            store.set_mcp_server("tools", entry)
        store.set_agent("assistant", agent)
        store.set_default_agent("assistant")
    finally:
        engine.dispose()


def run_entrypoint(
    script: str, tmp_path: Path, database: str
) -> subprocess.CompletedProcess[str]:
    """One server process, on a configuration whose startup refuses.

    Run from a directory of its own so no `.env` beside the repository
    reaches it, and with bytecode writing off, which is this
    repository's rule for anything outside pytest.

    On a database of this test's own, which is what makes the refusal
    the one the test seeded: a boot reads the whole stored half, so a
    row another test left would refuse first and this would be reading
    somebody else's sentence.
    """
    environment = dict(os.environ)
    environment["VINGA_DB_NAME"] = database
    environment["PYTHONDONTWRITEBYTECODE"] = "1"
    environment.pop(UNSET_VARIABLE, None)
    return subprocess.run(
        [sys.executable, "-c", script],
        cwd=tmp_path,
        env=environment,
        capture_output=True,
        text=True,
        check=False,
        timeout=120,
    )


def refused(finished: subprocess.CompletedProcess[str], sentence: str) -> str:
    """What a refused boot is allowed to have written, asserted, and the
    combined output for a caller with more to check.

    The sentence once, on either stream, and no rendering of the
    exception that carried it: `Traceback`, a frame line, or the class
    name would each mean the CLI had gone back to answering a
    configuration mistake with a stack.
    """
    written = finished.stdout + finished.stderr

    assert finished.returncode == 1, written
    assert written.count(sentence) == 1, written
    assert "Traceback (most recent call last)" not in written, written
    assert 'File "' not in written, written
    assert "StartupFailed" not in written, written
    return written


def test_a_refused_provider_build_says_one_sentence_and_exits_one(
    tmp_path: Path, blank_database: str
) -> None:
    seed_domain(blank_database)

    refused(run_entrypoint(PROVIDER_REFUSAL, tmp_path, blank_database), PROVIDER_SENTENCE)


def test_a_refused_mcp_entry_says_one_sentence_and_exits_one(
    tmp_path: Path, blank_database: str
) -> None:
    """An MCP entry naming an environment variable nothing sets is a
    boot refusal like a bad provider, and reached the operator as a bug
    until it was classified as one (`McpConfigError` is a `ValueError`,
    so nothing in the taxonomy caught it): uvicorn's traceback, and exit
    code 3 rather than 1. The message was written to be read as it is,
    and now it is."""
    entry: dict[str, object] = {
        "transport": "stdio",
        "command": "/usr/bin/true",
        "env": {"API_TOKEN": f"${UNSET_VARIABLE}"},
    }
    seed_domain(blank_database, entry)

    refused(run_entrypoint(PLAIN_ENTRYPOINT, tmp_path, blank_database), MCP_SENTENCE)


def test_nothing_a_provider_library_said_reaches_either_stream(
    tmp_path: Path, blank_database: str
) -> None:
    """Two guards, and the sentinel goes past both or neither.

    The registry composes the sentence rather than copying the library's,
    so what is printed cannot hold what the library was configured with;
    and the bridge raises its replacement outside the `except` that
    caught the refusal, so there is no `__cause__` or `__context__` for a
    renderer to walk into where one runs.
    """
    seed_domain(blank_database)

    written = refused(
        run_entrypoint(PROVIDER_REFUSAL, tmp_path, blank_database), PROVIDER_SENTENCE
    )

    assert SENTINEL not in written, written
    assert "api.example" not in written, written


# The telemetry exporter's own environment
#
# The `OTEL_EXPORTER_OTLP_*` family is operator-written text this server
# deliberately never reads, and the SDK parses several members of it
# eagerly inside a constructor, quoting what it was handed when one will
# not parse. That put a library `ValueError` on the boot path holding
# exactly the bytes those variables exist to carry, and `ValueError` is
# outside `BOOT_FAILURES`, so it reached the operator as uvicorn's
# traceback and exit code 3.
#
# Two lanes, because the family has two halves. The whole boot is driven
# for the member that refuses, which is what says the taxonomy carries
# it out as one sentence and exit code 1. The build alone is driven for
# all five, in a process of its own with logging turned all the way up,
# which is what says the members the SDK ACCEPTS leak nothing either:
# three of these five construct successfully today, and one of those
# three (`HEADERS`) logs the value it could not parse as it does it.
#
# The malformed values carry the sentinel because that is what a real
# one would: the headers variable holds the collector's credential by
# design, an endpoint may have a password in its userinfo, and a person
# who pasted one into the wrong variable is exactly who this is for.

TELEMETRY_ENTRYPOINT = """
import sys

import vinga_server.main as main

sys.argv = ["vinga-server"]
main.main()
"""

# The build on its own, with every logger this process has wide open and
# writing to stderr. A quieting that failed, or an SDK line that reached
# a handler anyway, lands in the captured stream and fails the hunt
# below; a boot would have swallowed the same line behind uvicorn's own
# configuration.
TELEMETRY_BUILD = """
import asyncio
import logging
import sys

logging.basicConfig(level=logging.DEBUG, stream=sys.stderr)

from vinga_server.config import ConfigError
from vinga_server.config.models import TelemetryConfig
from vinga_server.telemetry import build_telemetry

try:
    built = build_telemetry(TelemetryConfig(enabled=True))
except ConfigError as refusal:
    print("REFUSED", refusal)
else:
    print("BUILT")
    asyncio.run(built.shutdown())
"""

# One per member of the family the SDK reads, malformed in the way that
# member can be, each with the sentinel in it.
TELEMETRY_ENVIRONMENTS = {
    "timeout": {"OTEL_EXPORTER_OTLP_TIMEOUT": SENTINEL},
    "compression": {"OTEL_EXPORTER_OTLP_COMPRESSION": SENTINEL},
    "headers": {"OTEL_EXPORTER_OTLP_HEADERS": SENTINEL},
    "certificate": {"OTEL_EXPORTER_OTLP_CERTIFICATE": f"/nowhere/{SENTINEL}.pem"},
    "endpoint": {"OTEL_EXPORTER_OTLP_ENDPOINT": f"::::{SENTINEL}"},
}


def run_with_otlp(
    script: str, tmp_path: Path, database: str, environment: dict[str, str]
) -> subprocess.CompletedProcess[str]:
    """One process told to export, with one member of the OTLP family
    malformed.

    The database is reachable and seeded, because the domain half is
    read before the composition is built: an unreachable one refuses
    first and this lane would be reading the database's sentence.
    """
    inherited = dict(os.environ)
    inherited["VINGA_DB_NAME"] = database
    inherited["PYTHONDONTWRITEBYTECODE"] = "1"
    inherited["VINGA_SERVER__TELEMETRY__ENABLED"] = "true"
    inherited.update(environment)
    return subprocess.run(
        [sys.executable, "-c", script],
        cwd=tmp_path,
        env=inherited,
        capture_output=True,
        text=True,
        check=False,
        timeout=120,
    )


@pytest.mark.parametrize("member", sorted(TELEMETRY_ENVIRONMENTS))
def test_a_malformed_otlp_variable_leaks_nothing_at_all(
    tmp_path: Path, blank_database: str, member: str
) -> None:
    """The sentinel is nowhere, whichever member was malformed and
    whether the SDK refused it or took it.

    All five are driven rather than the two that raise today, because
    which member raises is the SDK's business and moves with a release,
    and the claim being made is about the family.
    """
    finished = run_with_otlp(
        TELEMETRY_BUILD, tmp_path, blank_database, TELEMETRY_ENVIRONMENTS[member]
    )
    written = finished.stdout + finished.stderr

    assert finished.returncode == 0, written
    assert SENTINEL not in written, written
    assert "Traceback (most recent call last)" not in written, written
    assert written.startswith(("BUILT", "REFUSED")), written
    if written.startswith("REFUSED"):
        assert CANNOT_BUILD_EXPORTER in written, written


def test_a_malformed_timeout_refuses_the_whole_boot(
    tmp_path: Path, blank_database: str
) -> None:
    """And the same failure through the entry point a deployment runs.

    A timeout is parsed as a float inside the exporter's constructor,
    and the `ValueError` it raises quotes the string it was given, which
    is the exact failure this containment was added for. What must come
    out is one sentence and exit code 1, like every other refusal in
    this file, rather than uvicorn's rendering of a library exception.
    """
    seed_domain(blank_database)

    finished = run_with_otlp(
        TELEMETRY_ENTRYPOINT, tmp_path, blank_database, TELEMETRY_ENVIRONMENTS["timeout"]
    )

    written = refused(finished, CANNOT_BUILD_EXPORTER)
    assert SENTINEL not in written, written
    assert "ValueError" not in written, written
    assert "float" not in written, written
