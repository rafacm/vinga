"""`vinga device invite`, the one command that issues an invite link
(#612, Q11; #613, D5, D5a, D5c, D6b, D7a).

It prints one link, `<origin>/talk/#<token>`, on stdout and nothing else
there, so `$(vinga device invite)` is the one way a script holds a link
without printing it. `--agent`, repeatable, names the agents the browser
that opens it is bound to; with none, the default agent. That it worked
is one fixed line on stderr, which names no agent it was given.

Which origin is split between the two ends: the server names its
configured public origin when that opens a secure context in a browser,
and otherwise names none; this client then names its own API target's
host as `localhost` when it reached the API on a loopback address, and
otherwise prints no link, exits non-zero, and says on stderr to set an
`https://` `server.public_url`. Never the listen address and never a
guess.

When the server will not issue one, the command fails with the server's
sentence and this client's own remedy where the state has one, and
stdout stays empty: nothing on it may be mistaken for a link.

The token is a credential, so it is printed on stdout alone, which is
the one place the plan allows it.
"""

import logging
import os
import re

import pytest

from tests.support.config_cli import logged, runner
from tests.support.leaks import renderings
from vinga_server.config.cli import acts, devices, reach
from vinga_server.config.loader import ConfigError
from vinga_server.config.models import ServerConfig
from vinga_server.config.responses import RefusalReason
from vinga_server.onboarding.invites import (
    AGENT_NOT_SERVED,
    AGENTS_UNKNOWN,
    DEFAULT_AGENT_NOT_SERVED,
    ONBOARDING_OFF,
    Invites,
    Issuer,
)

LINK = re.compile(r"^(?P<origin>\S+)/talk/#(?P<token>[A-Za-z0-9_-]{43})$")

PUBLIC = "https://vinga.test.invalid"


@pytest.fixture
def run(monkeypatch: pytest.MonkeyPatch):
    return runner(monkeypatch)


def deploy(
    run,
    server: ServerConfig | None = None,
    *,
    default_agent: bool = True,
    served: frozenset[str] = frozenset({"sam", "kids"}),
) -> Invites:
    """A deployment around the API: a store with two agents in it, the
    agents the running server serves, and the issuer the composition
    root would build."""
    links = Invites()
    run.runtime["invites"] = Issuer(links, server or ServerConfig(), False)
    run.runtime["loaded_agents"] = lambda: served
    assert run("agent", "set", "sam", "prompt=You are Sam.") == 0
    assert run("agent", "set", "kids", "prompt=You are kind.") == 0
    if default_agent:
        assert run("default-agent", "set", "sam") == 0
    return links


def port() -> str:
    return os.environ.get("VINGA_SERVER__PORT", "8003")


def token_of(out: str) -> str:
    match = LINK.match(out.rstrip("\n"))
    assert match is not None, out
    return match.group("token")


# --- the link, and nothing else on stdout ---------------------------------


def test_a_loopback_target_prints_one_localhost_link_and_nothing_else(
    run, capsys: pytest.CaptureFixture[str]
) -> None:
    links = deploy(run)
    capsys.readouterr()

    assert run("device", "invite") == 0

    printed = capsys.readouterr()
    # Exactly one line, the link: what `$(vinga device invite)` holds.
    assert printed.out.count("\n") == 1
    assert LINK.match(printed.out.rstrip("\n")).group("origin") == f"http://localhost:{port()}"
    assert printed.err == f"{devices.INVITED}\n"
    assert links.held == 1


def test_naming_no_agent_binds_the_default_agent(run, capsys: pytest.CaptureFixture[str]) -> None:
    links = deploy(run)
    capsys.readouterr()

    assert run("device", "invite") == 0

    invitation = links.claim(token_of(capsys.readouterr().out))
    assert invitation is not None and invitation.agents == ()


def test_each_agent_flag_names_an_agent_the_browser_is_bound_to(
    run, capsys: pytest.CaptureFixture[str]
) -> None:
    links = deploy(run)
    capsys.readouterr()

    assert run("device", "invite", "--agent", "kids", "--agent", "sam") == 0

    printed = capsys.readouterr()
    invitation = links.claim(token_of(printed.out))
    assert invitation is not None and invitation.agents == ("kids", "sam")
    # The line that says it worked names no agent: it is a fixed
    # sentence, and what was typed is not repeated back.
    assert printed.err == f"{devices.INVITED}\n"
    assert "kids" not in printed.err


def test_naming_agents_needs_no_default_agent(run, capsys: pytest.CaptureFixture[str]) -> None:
    links = deploy(run, default_agent=False)
    capsys.readouterr()

    assert run("device", "invite", "--agent", "kids") == 0

    assert links.claim(token_of(capsys.readouterr().out)).agents == ("kids",)  # type: ignore[union-attr]


def test_the_configured_origin_wins(run, capsys: pytest.CaptureFixture[str]) -> None:
    deploy(run, ServerConfig(public_url=PUBLIC))
    capsys.readouterr()

    assert run("device", "invite") == 0

    assert LINK.match(capsys.readouterr().out.rstrip("\n")).group("origin") == PUBLIC


def test_a_configured_origin_is_used_whatever_the_target(
    run, capsys: pytest.CaptureFixture[str]
) -> None:
    deploy(run, ServerConfig(public_url=PUBLIC))
    capsys.readouterr()

    assert run("--api-url", "https://vinga.test.invalid/api", "device", "invite") == 0

    assert LINK.match(capsys.readouterr().out.rstrip("\n")).group("origin") == PUBLIC


def test_a_configured_origin_with_a_path_prefix_keeps_it(
    run, capsys: pytest.CaptureFixture[str]
) -> None:
    """A deployment a proxy serves under a prefix names it in
    `server.public_url`, and the link is the page under that prefix."""
    deploy(run, ServerConfig(public_url=f"{PUBLIC}/vinga"))
    capsys.readouterr()

    assert run("device", "invite") == 0

    assert capsys.readouterr().out.startswith(f"{PUBLIC}/vinga/talk/#")


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
    microphone, so there is none, and the command fails rather than
    leaving a caller holding an empty link."""
    deploy(run, ServerConfig(host="0.0.0.0"))
    capsys.readouterr()

    assert run("--api-url", api_url, "device", "invite") == 1

    printed = capsys.readouterr()
    assert printed.out == ""
    assert "/talk/#" not in printed.err
    assert devices.NO_LINK_ORIGIN in printed.err


# --- refusals: the command fails, and stdout stays empty ------------------


def test_with_the_default_unserved_and_none_named_the_refusal_and_its_remedy_are_said(
    run, capsys: pytest.CaptureFixture[str]
) -> None:
    """No default agent is stored, so the default is vinga, which this
    server does not serve (#612, D5): the server's sentence, then this
    client's remedy for the token."""
    links = deploy(run, default_agent=False)
    capsys.readouterr()

    assert run("device", "invite") == 1

    printed = capsys.readouterr()
    assert printed.out == ""
    assert DEFAULT_AGENT_NOT_SERVED in printed.err
    assert "`vinga info` says why" in printed.err
    assert links.held == 0


def test_an_older_client_quotes_the_server_s_sentence_for_the_new_token(
    run, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    """D5's compatibility claim: a client built before the token was
    renamed cannot name `default-agent-not-served`, and its rule for a
    token it does not know is to quote the server's sentence. Driven by
    taking the token out of this client's vocabulary, which is what an
    older build's vocabulary is."""
    links = deploy(run, default_agent=False)
    known = reach._KNOWN_REASONS - {RefusalReason.DEFAULT_AGENT_NOT_SERVED.value}
    monkeypatch.setattr(reach, "_KNOWN_REASONS", known)
    capsys.readouterr()

    assert run("device", "invite") == 1

    printed = capsys.readouterr()
    assert printed.out == ""
    assert DEFAULT_AGENT_NOT_SERVED in printed.err
    assert "`vinga info` says why" not in printed.err
    assert links.held == 0


def test_an_agent_this_deployment_does_not_have_is_refused_without_its_name(
    run, capsys: pytest.CaptureFixture[str]
) -> None:
    links = deploy(run)
    capsys.readouterr()

    assert run("device", "invite", "--agent", "sk-live-AGENT-NAME-SENTINEL-0000") == 1

    printed = capsys.readouterr()
    assert printed.out == ""
    assert AGENTS_UNKNOWN in printed.err
    assert "`vinga list`" in printed.err
    assert "SENTINEL" not in printed.err
    assert links.held == 0


def test_an_agent_this_server_is_not_serving_is_refused_with_the_apply_named(
    run, capsys: pytest.CaptureFixture[str]
) -> None:
    links = deploy(run, served=frozenset({"sam"}))
    capsys.readouterr()

    assert run("device", "invite", "--agent", "kids") == 1

    printed = capsys.readouterr()
    assert printed.out == ""
    assert AGENT_NOT_SERVED in printed.err
    assert "`vinga apply`" in printed.err
    assert links.held == 0


def test_with_onboarding_off_the_refusal_is_said(run, capsys: pytest.CaptureFixture[str]) -> None:
    deploy(run, ServerConfig(onboarding={"enabled": False}))
    capsys.readouterr()

    assert run("device", "invite") == 1

    printed = capsys.readouterr()
    assert printed.out == ""
    assert ONBOARDING_OFF in printed.err


def test_an_application_with_no_server_around_it_issues_nothing(
    run, capsys: pytest.CaptureFixture[str]
) -> None:
    capsys.readouterr()

    assert run("device", "invite") == 1

    printed = capsys.readouterr()
    assert printed.out == ""
    assert "no running server around it" in printed.err


def test_a_request_that_never_got_an_answer_fails_the_command(
    run, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    deploy(run)
    real = acts._call

    def call(reached, method, path, *rest, **kwargs):
        if path == "/runtime/invites":
            raise ConfigError("the configuration API could not be reached")
        return real(reached, method, path, *rest, **kwargs)

    monkeypatch.setattr(acts, "_call", call)
    capsys.readouterr()

    assert run("device", "invite") == 1

    printed = capsys.readouterr()
    assert printed.out == ""
    assert "could not be reached" in printed.err


# --- the token, and the grammar -------------------------------------------


def test_the_token_reaches_stdout_and_nothing_else(
    run,
    capsys: pytest.CaptureFixture[str],
    caplog: pytest.LogCaptureFixture,
) -> None:
    """The one owner-facing disclosure the plan allows (#613, D7a): the
    operator's own terminal. Not stderr, not a log record of the whole
    invocation in either format."""
    deploy(run)
    capsys.readouterr()

    with caplog.at_level(logging.DEBUG):
        assert run("device", "invite", "--agent", "kids") == 0

    printed = capsys.readouterr()
    token = token_of(printed.out)
    assert token not in printed.err
    assert token not in logged(caplog)
    assert token not in "\n".join(renderings(caplog))


def test_each_run_is_a_new_link(run, capsys: pytest.CaptureFixture[str]) -> None:
    links = deploy(run)
    capsys.readouterr()

    assert run("device", "invite") == 0
    first = capsys.readouterr().out
    assert run("device", "invite") == 0
    second = capsys.readouterr().out

    assert first != second
    assert links.held == 2


def test_it_takes_no_positional(run, capsys: pytest.CaptureFixture[str]) -> None:
    """Nothing is addressed, so nothing is positional: an agent is a
    flag, which keeps a stray word from becoming one."""
    links = deploy(run)
    capsys.readouterr()

    assert run("device", "invite", "kids") != 0

    assert capsys.readouterr().out == ""
    assert links.held == 0
