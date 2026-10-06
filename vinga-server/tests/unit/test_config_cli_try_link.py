"""`vinga info`'s try link line (#613, D5, D5a, D5c, D6b, D7a).

`info` issues a try link and prints it, `<origin>/try/#<token>`, on a
line of its own under a label saying what it does. Which origin is
split between the two ends: the server names its configured public
origin when that opens a secure context in a browser, and otherwise
names none; this client then names its own API target's host as
`localhost` when it reached the API on a loopback address, and
otherwise prints no link and a sentence asking for an `https://`
`server.public_url`. Never the listen address and never a guess.

When the server will not issue one, its sentence stands where the link
would be, with this client's own remedy where the state has one, and
`info` goes on to say the rest of what it says: a deployment with no
default agent yet is the deployment a person meets first.

The token is a credential, so it is printed on stdout alone, which is
the one place the plan allows it.
"""

import logging
import os
import re

import pytest

from tests.support.config_cli import logged, runner
from tests.support.leaks import renderings
from vinga_server.config.cli import acts, deployment
from vinga_server.config.loader import ConfigError
from vinga_server.config.models import ServerConfig
from vinga_server.config.responses import RuntimeInfo
from vinga_server.onboarding.try_links import (
    NO_DEFAULT_AGENT,
    ONBOARDING_OFF,
    Issuer,
    TryLinks,
)

LINK = re.compile(r"^(?P<origin>\S+)/try/#(?P<token>[A-Za-z0-9_-]{43})$")

PUBLIC = "https://vinga.test.invalid"


@pytest.fixture
def run(monkeypatch: pytest.MonkeyPatch):
    return runner(monkeypatch)


def identity() -> RuntimeInfo:
    return RuntimeInfo(
        version="0.1.0",
        revision="v0.1.0-3-gdeadbee",
        onboarding_enabled=True,
        onboarding_url="https://vinga.test.invalid/x/aaaaaaaa/",
        onboarding_provenance="from server.public_url",
    )


def deploy(run, server: ServerConfig | None = None, *, default_agent: bool = True) -> TryLinks:
    """A deployment around the API: its identity, a store with an agent
    in it, and the issuer the composition root would build."""
    links = TryLinks()
    run.runtime["identity"] = identity()
    run.runtime["try_links"] = Issuer(links, server or ServerConfig(), False)
    assert run("agent", "set", "sam", "prompt=You are Sam.") == 0
    if default_agent:
        assert run("default-agent", "set", "sam") == 0
    return links


def port() -> str:
    return os.environ.get("VINGA_SERVER__PORT", "8003")


def link_lines(out: str) -> list[str]:
    return [line for line in out.splitlines() if LINK.match(line)]


def test_a_loopback_target_prints_a_localhost_link(
    run, capsys: pytest.CaptureFixture[str]
) -> None:
    links = deploy(run)
    capsys.readouterr()

    assert run("info") == 0

    printed = capsys.readouterr()
    lines = printed.out.splitlines()
    (link,) = link_lines(printed.out)
    assert LINK.match(link).group("origin") == f"http://localhost:{port()}"
    # The label is the line above, saying what the link does; the link
    # stands alone so it can be selected whole.
    assert lines[lines.index(link) - 1] == f"{deployment.TRY_LINK_LABEL}:"
    assert links.held == 1
    assert printed.err == ""


def test_the_configured_origin_wins(run, capsys: pytest.CaptureFixture[str]) -> None:
    deploy(run, ServerConfig(public_url=PUBLIC))
    capsys.readouterr()

    assert run("info") == 0

    (link,) = link_lines(capsys.readouterr().out)
    assert LINK.match(link).group("origin") == PUBLIC


def test_a_link_follows_the_onboarding_url_and_precedes_the_counts(
    run, capsys: pytest.CaptureFixture[str]
) -> None:
    deploy(run)
    capsys.readouterr()

    assert run("info") == 0

    lines = capsys.readouterr().out.splitlines()
    (link,) = link_lines("\n".join(lines))
    assert lines.index(identity().onboarding_url) < lines.index(link)
    configured = next(index for index, line in enumerate(lines) if line.startswith("configured:"))
    assert lines.index(link) < configured


@pytest.mark.parametrize(
    "api_url",
    ["https://vinga.test.invalid/api", "https://192.168.1.10:8443/api"],
)
def test_a_target_that_is_not_loopback_with_no_configured_origin_prints_no_link(
    api_url: str, run, capsys: pytest.CaptureFixture[str]
) -> None:
    """The server listens wherever it listens, `0.0.0.0` included, and
    names no origin; this client reached it somewhere that is not this
    machine, so there is no origin either end can vouch for. A link
    with a guessed origin would open nothing, or open a page with no
    microphone, so there is none."""
    deploy(run, ServerConfig(host="0.0.0.0"))
    capsys.readouterr()

    assert run("--api-url", api_url, "info") == 0

    printed = capsys.readouterr()
    assert link_lines(printed.out) == []
    assert "/try/#" not in printed.out + printed.err
    assert f"{deployment.TRY_LINK_LABEL}: {deployment.NO_LINK_ORIGIN}" in printed.out.splitlines()


def test_a_configured_origin_is_used_whatever_the_target(
    run, capsys: pytest.CaptureFixture[str]
) -> None:
    deploy(run, ServerConfig(public_url=PUBLIC))
    capsys.readouterr()

    assert run("--api-url", "https://vinga.test.invalid/api", "info") == 0

    (link,) = link_lines(capsys.readouterr().out)
    assert LINK.match(link).group("origin") == PUBLIC


def test_with_no_default_agent_the_refusal_and_its_remedy_stand_in_its_place(
    run, capsys: pytest.CaptureFixture[str]
) -> None:
    links = deploy(run, default_agent=False)
    capsys.readouterr()

    assert run("info") == 0

    printed = capsys.readouterr()
    assert link_lines(printed.out) == []
    line = next(
        line for line in printed.out.splitlines() if line.startswith(deployment.TRY_LINK_LABEL)
    )
    assert line == (
        f"{deployment.TRY_LINK_LABEL}: {NO_DEFAULT_AGENT} Set one with "
        f"`vinga default-agent set <name>`, and a browser opening a link is bound to that "
        f"agent."
    )
    # And the rest of what `info` says is still said.
    assert any(line.startswith("configured:") for line in printed.out.splitlines())
    assert printed.err == ""
    assert links.held == 0


def test_with_onboarding_off_the_refusal_stands_in_its_place(
    run, capsys: pytest.CaptureFixture[str]
) -> None:
    server = ServerConfig(onboarding={"enabled": False})
    deploy(run, server)
    capsys.readouterr()

    assert run("info") == 0

    out = capsys.readouterr().out
    assert f"{deployment.TRY_LINK_LABEL}: {ONBOARDING_OFF}" in out.splitlines()
    assert link_lines(out) == []


def test_a_server_that_issues_no_links_does_not_fail_info(
    run, capsys: pytest.CaptureFixture[str]
) -> None:
    """An application with no server around it, or a server from before
    try links existed: a refusal this API wrote, of the one act whose
    refusal is a line of the answer rather than the end of it."""
    run.runtime["identity"] = identity()
    capsys.readouterr()

    assert run("info") == 0

    out = capsys.readouterr().out
    line = next(line for line in out.splitlines() if line.startswith(deployment.TRY_LINK_LABEL))
    assert "no running server around it" in line


def test_the_token_reaches_stdout_and_nothing_else(
    run,
    capsys: pytest.CaptureFixture[str],
    caplog: pytest.LogCaptureFixture,
) -> None:
    """The one owner-facing disclosure the plan allows (D7a): the
    operator's own terminal. Not stderr, not a log record of the whole
    invocation in either format."""
    deploy(run)
    capsys.readouterr()

    with caplog.at_level(logging.DEBUG):
        assert run("info") == 0

    printed = capsys.readouterr()
    (link,) = link_lines(printed.out)
    token = LINK.match(link).group("token")
    assert token not in printed.err
    assert token not in logged(caplog)
    assert token not in "\n".join(renderings(caplog))


def test_each_run_is_a_new_link(run, capsys: pytest.CaptureFixture[str]) -> None:
    links = deploy(run)
    capsys.readouterr()

    assert run("info") == 0
    first = link_lines(capsys.readouterr().out)
    assert run("info") == 0
    second = link_lines(capsys.readouterr().out)

    assert first != second
    assert links.held == 2


def test_a_try_link_request_that_never_got_an_answer_still_ends_info(
    run, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """Only a refusal the API wrote is a line of the answer. A request
    that did not complete is not a state of the deployment, and `info`
    ends with it as it ends with any other act's."""
    deploy(run)
    real = acts._call

    def call(reached, method, path, *rest, **kwargs):
        if path == "/runtime/try-links":
            raise ConfigError("the configuration API could not be reached")
        return real(reached, method, path, *rest, **kwargs)

    monkeypatch.setattr(acts, "_call", call)
    capsys.readouterr()

    assert run("info") == 1

    printed = capsys.readouterr()
    assert "could not be reached" in printed.err
    assert deployment.TRY_LINK_LABEL not in printed.out
    assert "configured:" not in printed.out


def test_a_configured_origin_with_a_path_prefix_keeps_it(
    run, capsys: pytest.CaptureFixture[str]
) -> None:
    """A deployment a proxy serves under a prefix names it in
    `server.public_url`, and the link is the page under that prefix."""
    deploy(run, ServerConfig(public_url=f"{PUBLIC}/vinga"))
    capsys.readouterr()

    assert run("info") == 0

    (link,) = link_lines(capsys.readouterr().out)
    assert link.startswith(f"{PUBLIC}/vinga/try/#")
