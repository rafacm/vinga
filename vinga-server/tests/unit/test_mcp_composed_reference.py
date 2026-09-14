"""An environment reference composed into a larger value, end to end.

`Authorization: Bearer $TOKEN` is one value with a credential inside it.
That shape is what #504 adds, and everything about it that can be
observed from outside is here: what the far side is handed, what an
unset variable refuses, what a value with a newline in it does, and what
happens to a configuration that carries one when a deployment is rebuilt
from its export.

The no-leak half is the bulk of it, and the sentinel is planted as a
VALUE rather than as a key. The value is what this change lets through
and what a resolved header carries; the key is what the secret-bearing
rule matches on and is an ordinary declared word. Two paths are walked
with a server tap attached, the connection that succeeds and the one
that refuses, because an event payload is its own retained transport and
a claim about a log is not a claim about it. Records are read through
`every_format`, whoever logged them, so a foreign library's record
cannot be silently excluded from an absence.

The refusing path is deliberately the partial one: one variable set and
one not, in the same value, so the string that exists halfway through
substitution is a thing the refusal could have quoted and does not.
"""

import hashlib
import json
import logging
import traceback
from collections.abc import Iterator

import pytest
from mcp.server.fastmcp import Context, FastMCP

from tests.support.config_cli import runner
from tests.support.events import every_format
from tests.support.tools_mcp import serving
from vinga_server.config import Config
from vinga_server.config.boot import load_boot_config
from vinga_server.events import Emission, attach_server_tap, detach_server_tap
from vinga_server.tools.mcp import CONNECTED, McpServers

# Not a real credential, and shaped so a substring check for it cannot
# match by accident. It is what the environment variable HOLDS: the
# composed header this suite is about is the word `Bearer`, a space and
# this.
SENTINEL = "sk-test-9b41c7e2-never-a-real-credential"

# The variables the entries below reference. One is set for every case,
# the other is set for none of them, which is what makes a value naming
# both the partial-substitution case.
SECRET_ENV = "VINGA_TEST_COMPOSED_SECRET"
MISSING_ENV = "VINGA_TEST_COMPOSED_MISSING"

COMPOSED = f"Bearer ${SECRET_ENV}"
EXPECTED = f"Bearer {SENTINEL}"

pytestmark = pytest.mark.filterwarnings("ignore:Unclosed <MemoryObject:ResourceWarning")


def digest(value: str) -> str:
    """One header value as a fingerprint of itself.

    What the cases compare, and never the value: a mismatch prints two
    hex strings rather than the credential the comparison was about.
    """
    return hashlib.sha256(value.encode()).hexdigest()


def recording_server() -> FastMCP:
    """A streamable_http server that answers with a fingerprint of the
    Authorization header the request carried.

    The header is what the transport is handed, and reading it off the
    far side is the only reading that cannot be satisfied by a model
    that looks right. A digest rather than the header, for the reason
    `mcp_env_echo_server.py` answers a boolean: a failing assertion here
    must print no credential.
    """
    server = FastMCP("vinga-test-http-recording")

    def header(name: str, ctx: Context) -> str:
        request = ctx.request_context.request
        return digest("" if request is None else request.headers.get(name, ""))

    server.add_tool(
        header,
        name="header",
        description="A fingerprint of the named header this request carried.",
    )
    return server


def config_with(entry: dict[str, object]) -> Config:
    """One agent granted one MCP entry, which is the whole world these
    cases need."""
    return Config(
        server={},
        providers={
            stage: {"mock": {"type": "mock"}} for stage in ("llm", "asr", "tts", "vad")
        },
        mcp_servers={"weather": entry},
        agent_defaults=dict.fromkeys(("llm", "asr", "tts", "vad"), "mock"),
        agents={"assistant": {"prompt": "A", "mcp": ["weather"]}},
        default_agent="assistant",
    )


def http_entry(url: str, header: str, key: str = "Authorization") -> dict[str, object]:
    return {"transport": "streamable_http", "url": url, "headers": {key: header}}


class Tap:
    """A server-scope consumer that keeps what it was handed.

    A log record is not the whole surface: `Emission.args` reaches every
    tap as the objects themselves, so a claim that a value reaches
    nobody is asserted here as well as at the log.
    """

    def __init__(self) -> None:
        self.seen: list[Emission] = []

    def emit(self, emission: Emission) -> None:
        self.seen.append(emission)

    def rendered(self) -> str:
        return "\n".join(
            "\n".join([str(one.payload), str(one.message), repr(one.args)])
            for one in self.seen
        )


@pytest.fixture
def tap() -> Iterator[Tap]:
    consumer = Tap()
    attach_server_tap(consumer)
    try:
        yield consumer
    finally:
        detach_server_tap(consumer)


@pytest.fixture
def watched(caplog: pytest.LogCaptureFixture) -> Iterator[pytest.LogCaptureFixture]:
    """Every logger, at the level a deployment runs at. Deliberately not
    DEBUG, for the reason the reflection suite gives: at DEBUG `httpcore`
    prints the headers of every response any httpx client in the process
    receives, which is a property of debug logging rather than anything
    these surfaces decide."""
    with caplog.at_level(logging.INFO):
        yield caplog


def chained(exc: BaseException) -> str:
    """One failure and everything behind it, rendered the way a
    traceback would be. `__cause__` and `__context__` both, since a
    value quoted by a wrapped exception is in the log of anything that
    prints the chain."""
    seen: list[str] = []
    current: BaseException | None = exc
    while current is not None:
        seen.append("".join(traceback.format_exception(current)))
        seen.append(repr(current))
        current = current.__cause__ or current.__context__
    return "\n".join(seen)


async def fingerprint(config: Config, name: str = "authorization") -> str:
    """What the far side says about one header it was sent, over a real
    connection this function opens and closes."""
    servers = McpServers.build(config)
    await servers.start_all()
    try:
        assert servers.status()["weather"]["state"] == CONNECTED
        answered, is_error = await servers.call(
            "weather__header", {"name": name}, "assistant", "weather"
        )
    finally:
        await servers.stop_all()
    assert not is_error, answered
    return answered


# --- what the far side is handed --------------------------------------


async def test_a_composed_header_reaches_the_server_with_the_secret_in_it(
    tap: Tap, watched: pytest.LogCaptureFixture, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The header the vendor asks for, sent as one value.

    Asserted on what the transport is handed rather than on the model,
    because the model would look right whatever the resolver did with
    it. The word `Bearer` is in the configuration, where an operator can
    read it, instead of inside the secret.

    This is the connecting path of the no-leak claim: a credential is
    materialized, sent and answered, and the tap and the log are read
    afterwards. An absence here is an absence from a run that did the
    whole thing rather than from one that refused early.
    """
    monkeypatch.setenv(SECRET_ENV, SENTINEL)
    async with serving(recording_server()) as url:
        assert await fingerprint(config_with(http_entry(url, COMPOSED))) == digest(EXPECTED)

    # The connect line is there, so the absences below are absences from
    # a log something was written to.
    assert [record for record in watched.records if record.name.startswith("vinga_server")]
    for surface in (every_format(watched), tap.rendered()):
        assert SENTINEL not in surface


async def test_a_value_with_no_reference_reaches_the_server_byte_for_byte(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The other half of the rule: a value holding no reference is sent
    exactly as written, dollar-free text and all.

    Under an ordinary header key rather than a secret-bearing one,
    because a secret-bearing key holding no reference is the case the
    write refuses, which is asserted on its own below.
    """
    monkeypatch.delenv(SECRET_ENV, raising=False)
    written = "eu-west-1 v2"
    async with serving(recording_server()) as url:
        entry = http_entry(url, written, key="X-Region")
        assert await fingerprint(config_with(entry), "x-region") == digest(written)


# --- what an unset variable refuses, and what it does not say ---------


async def test_an_unset_variable_inside_a_composed_value_refuses_and_quotes_nothing(
    tap: Tap, watched: pytest.LogCaptureFixture, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The refusing path, with the secret half of the value resolved.

    One variable set to the sentinel and one unset, in the same value,
    so a string holding the credential genuinely exists while the
    refusal is being raised. The refusal names the location and the
    variable it could not read, and carries neither the value, the
    partially substituted string, nor the credential inside it, on any
    surface a boot reaches: the sentence, the exception chain, both log
    formats over every record whoever wrote it, and every emission an
    attached tap was handed.
    """
    monkeypatch.setenv(SECRET_ENV, SENTINEL)
    monkeypatch.delenv(MISSING_ENV, raising=False)
    entry = http_entry("http://127.0.0.1:1/mcp", f"Bearer ${SECRET_ENV} ${MISSING_ENV}")

    with pytest.raises(ValueError) as caught:
        McpServers.build(config_with(entry))

    said = str(caught.value)
    assert "mcp_servers.weather.headers.Authorization" in said
    assert f"${MISSING_ENV}" in said
    # The rule and the location, and nothing of what was written there.
    assert "Bearer" not in said
    for surface in (said, chained(caught.value), every_format(watched), tap.rendered()):
        assert SENTINEL not in surface


def test_a_value_with_no_reference_under_a_secret_bearing_key_still_refuses(
    tap: Tap,
    watched: pytest.LogCaptureFixture,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """The check is widened, not withdrawn.

    A pasted credential under `Authorization` references nothing, so it
    is still refused, and the refusal still quotes no key material. At
    the surface an operator meets it on: the command's own streams, both
    log formats over every record, and every emission a tap was handed.
    """
    monkeypatch.delenv(SECRET_ENV, raising=False)
    run = runner(monkeypatch)

    assert (
        run(
            "mcp-server", "set", "weather",
            "transport=streamable_http",
            "url=http://127.0.0.1:1/mcp",
            f"headers.Authorization={SENTINEL}",
        )
        == 1
    )

    captured = capsys.readouterr()
    assert "references no environment variable" in captured.err
    assert "Traceback" not in captured.err
    for surface in (captured.err, captured.out, every_format(watched), tap.rendered()):
        assert SENTINEL not in surface


# --- the newline, measured rather than asserted -----------------------


async def test_a_composed_header_carrying_a_newline_never_reaches_the_wire(
    tap: Tap, watched: pytest.LogCaptureFixture, monkeypatch: pytest.MonkeyPatch
) -> None:
    """What a newline inside a composed value does, as measured.

    A value that is nothing but a reference is stripped before it is
    read, so `$TOKEN\\n` keeps resolving to the bare secret. A COMPOSED
    value is not stripped, by design, so `Bearer $TOKEN\\n` reaches the
    HTTP client with a newline in it. Measured on 2026-09-14 against
    httpx 0.28.1: the client accepts the value and h11 refuses to put it
    on the wire (`LocalProtocolError: Illegal header value`), so the
    request is never sent and header injection is not reachable through
    this transport. No refusal of our own is added for it, because the
    transport already answers.

    What this pins is the consequence rather than the message: the
    connection does not come up, the far side is never asked, and the
    exception h11 raises quotes the header value, so this is also the
    case where a credential is closest to a log. It reaches none.
    """
    monkeypatch.setenv(SECRET_ENV, SENTINEL)
    async with serving(recording_server()) as url:
        servers = McpServers.build(config_with(http_entry(url, COMPOSED + "\n")))
        await servers.start_all()
        try:
            status = servers.status()
            assert status["weather"]["state"] != CONNECTED
            assert status["weather"]["tools"] == []
        finally:
            await servers.stop_all()

    for surface in (json.dumps(status), every_format(watched), tap.rendered()):
        assert SENTINEL not in surface
    # And nothing was reported through a traceback, which is the other
    # way the value could have travelled: h11's message holds it.
    assert all(record.exc_info is None for record in watched.records)


# --- the acceptance case: a deployment rebuilt from its export --------


# The agent that reaches the entry, written as a fragment because a list
# is not a scalar and an inline value is one scalar.
GRANTING = "prompt: A\nllm: mock\nasr: mock\ntts: mock\nvad: mock\nmcp: [weather]\n"


def _grant(run) -> None:
    """The rest of a deployment: four mock engines, the agent that is
    granted the entry, and the agent a device without a binding gets."""
    for stage in ("llm", "asr", "tts", "vad"):
        assert run("provider", "set", stage, "mock", "type=mock") == 0
    assert run("agent", "set", "assistant", "-f", "-", stdin=GRANTING) == 0
    assert run("default-agent", "set", "assistant") == 0


async def test_a_composed_header_survives_an_export_into_an_empty_database(
    spare_database: str,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """The recovery this configuration has to survive, end to end.

    A composed header is written, the store is exported, the document is
    imported into an EMPTY database, and the deployment built from the
    second database sends the byte-identical header the first one did.

    It is the export-and-reapply promise, and it is the reason the
    display rule follows the write rule rather than masking a composed
    value: a mask means keep what is stored, an empty database has
    nothing stored, and an entry that exported as eight asterisks could
    not be imported at all.
    """
    monkeypatch.setenv(SECRET_ENV, SENTINEL)
    async with serving(recording_server()) as url:
        first = runner(monkeypatch)
        assert (
            first(
                "mcp-server", "set", "weather",
                "transport=streamable_http",
                f"url={url}",
                f"headers.Authorization={COMPOSED}",
            )
            == 0
        )
        _grant(first)
        capsys.readouterr()

        assert first("export") == 0
        exported = capsys.readouterr().out
        # The document carries the reference as written: a reference is a
        # body value, and this one is composed.
        assert f"Authorization: {COMPOSED}" in exported
        # And carries no credential: what travels is the name of the
        # variable, which is the whole reason a reference is a body
        # value rather than a command in the footer.
        assert SENTINEL not in exported

        sent = await fingerprint(load_boot_config().config)

        # A fresh store, built from the export and from nothing else.
        # Empty before the import, which is what the case is about and
        # what says this deployment is a second one rather than the
        # first answering twice.
        second = runner(monkeypatch, database=spare_database)
        assert load_boot_config().config.mcp_servers == {}
        assert second("import", "-f", "-", stdin=exported) == 0
        capsys.readouterr()

        rebuilt = await fingerprint(load_boot_config().config)

    assert sent == digest(EXPECTED)
    assert rebuilt == sent
