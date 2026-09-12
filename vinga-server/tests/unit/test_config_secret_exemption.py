"""What the secret-key heuristic does not reach, and everything it
still does.

`max_tokens` contains the fragment `token`, so the inline-secret rule
refused it on every surface and for every provider type: the `anthropic`
and `openai_compatible` builders read an option no fragment could ever
install, and the default silently always won (#277). The fix is an
exact, case-sensitive exemption inside `secret_option_fragment`, which
is a loosening of a security rule, so what this file is for is showing
that the loosening admits exactly one name.

Containment is asserted rather than sampled, at three depths:

- **The predicate**, over every fragment of the narrow tuple, the
  exemption's near neighbours, and its case variants. Cheap enough to
  enumerate, and the one place a scan can be shown to have exactly one
  hole in it.
- **The write path**, over the same table on the three surfaces an
  operator installs an option from, because the predicate answering
  correctly and a surface asking a different question is exactly the
  shape of bug this replaces.
- **The wider rule**, which is a separate tuple with separate readers
  (`mcp_secret_fragment`, `is_url_credential_parameter`) and must not
  have moved: an MCP env key, an MCP header and a URL query parameter
  named `max_tokens` are named by somebody else, so nothing there can
  earn an exemption.

The exact name was the first answer and is no longer the general one.
A second endpoint named a second parameter (`max_completion_tokens`,
which is what OpenAI's current models take instead of `max_tokens`),
and a list of names is a list somebody has to add to before an
operator can write a cap, on the one type whose promise is that a key
this repository never heard of travels (#444). So the general question
is asked of the VALUE: a number cannot be a pasted credential, and
everything else could be. With one thing still asked of the name,
because a secret-shaped key is two shapes and the value speaks for only
one of them: a key that is itself the paste is not spelled the way a
request parameter is, so a key carrying anything but letters, digits
and underscores stays refused whatever it holds. The last section of
this file is that rule, at the predicate, on every surface, and against
the same planted credentials as the rest.

Every refused value is a sentinel, in the `PLANTED_KEYS` style of
`test_config_api_problems.py`: a refusal is a surface, and a key
refused for looking like a credential is most likely holding one, so
the value is asserted absent from the exception chain, the structured
body, the log in both formats this server writes, and the two streams
the process holds.
"""

import logging
from collections.abc import Callable, Iterator
from pathlib import Path
from typing import NamedTuple

import pytest
import yaml
from fastapi import FastAPI
from fastapi.testclient import TestClient

from tests.support.config_cli import runner
from tests.support.configs import load_config_from_data
from vinga_server import logs
from vinga_server.config.api import build_api
from vinga_server.config.loader import ConfigError
from vinga_server.config.models import (
    MASK,
    DatabaseConfig,
    could_be_inline_secret,
    is_mcp_secret_key,
    is_secret_option,
    is_url_credential_parameter,
    secret_option_fragment,
    url_credential,
)
from vinga_server.config.secrets import MASTER_KEY_ENV, generate_key, load_keys
from vinga_server.config.store import ConfigStore
from vinga_server.db import open_database

TOKEN = "test-api-token-" + "0123456789abcdef" * 2

# The exempted name, written once. Every case below is either this
# string or deliberately not it.
EXEMPT = "max_tokens"

# The parameter that says a list of names was the wrong shape: OpenAI's
# current models refuse `max_tokens` and take this instead, and nothing
# in this repository declares it, so it reaches an endpoint only by
# being passed through.
NUMERIC = "max_completion_tokens"

# The cap a fragment documents, and a value that is not the builders'
# default, so a case that asserted the option arrived cannot be passing
# on the default the defect used to leave behind.
CONFIGURED = 2048

# Not a real credential, and shaped so a substring check for it cannot
# match by accident.
SENTINEL = "sk-test-3f7a91c4-never-a-real-credential"


class Refused(NamedTuple):
    """One key the rule must go on refusing, and the fragment of this
    repository's own six words a refusal may name it by."""

    what: str
    key: str
    matched: str


# Every fragment of the narrow tuple, each under a representative name,
# and then the names that make the exemption's edges: one letter short,
# each half alone, the fragment as the whole key, the exemption with a
# suffix, its words reversed, two ordinary credential names, and the two
# case variants.
#
# The case variants are the P1 of the plan's review round. Option names
# are case-sensitive everywhere they are declared and read, so
# `MAX_TOKENS` is a spelling nothing declares; exempting the lowered
# name would admit it, and the open-doors type would forward it into a
# request as a passthrough field.
#
# `max_tokens_env` is deliberately not here and is not a probe: a key
# ending in `_env` is handled before the fragment scan runs at all, so
# it says nothing about this rule. Its own validation is pinned below.
REFUSED_KEYS = [
    Refused("the fragment secret", "secret_key", "secret"),
    Refused("the fragment token", "access_token", "token"),
    Refused("the fragment password", "db_password", "password"),
    Refused("the fragment api_key", "api_key", "api_key"),
    Refused("the fragment apikey", "apikey", "apikey"),
    Refused("the fragment credential", "vendor_credential", "credential"),
    Refused("one letter short of the exemption", "max_token", "token"),
    Refused("the exemption's second half alone", "tokens", "token"),
    Refused("the fragment as the whole key", "token", "token"),
    Refused("the exemption with a suffix", "max_tokens_backup", "token"),
    Refused("the exemption's words reversed", "tokens_max", "token"),
    Refused("an ordinary credential name", "session_token", "token"),
    Refused("the credential name the wider tuple was widened for", "auth_token", "token"),
    Refused("a credential name carrying the first fragment", "client_secret", "secret"),
    Refused("the exemption in upper case", "MAX_TOKENS", "token"),
    Refused("the exemption in title case", "Max_Tokens", "token"),
]

REFUSED_IDS = [case.what for case in REFUSED_KEYS]


# The predicate itself


def test_the_exemption_admits_exactly_the_one_name() -> None:
    """The rule as a rule, before any surface asks it.

    Both directions in one case, because the claim is an equality: the
    exempted name is not secret-shaped, and every neighbour of it still
    is. A one-sided assertion would pass on an exemption that swallowed
    the fragment whole.
    """
    assert secret_option_fragment(EXEMPT) is None
    assert not is_secret_option(EXEMPT)

    for case in REFUSED_KEYS:
        assert secret_option_fragment(case.key) == case.matched, case.key
        assert is_secret_option(case.key), case.key


def test_the_exemption_did_not_reach_the_wider_tuple_or_the_url_rule() -> None:
    """The other two readers, which have their own tuple and their own
    names to be right about (#279).

    An MCP server's env and headers key and a URL's query parameter are
    named by whoever runs the server or the endpoint, so no name there
    is a declared option a builder reads, which is the condition an
    exemption is earned by. Both spellings, because the exemption's own
    compare is case-sensitive and these two rules are not.
    """
    for spelling in (EXEMPT, EXEMPT.upper()):
        assert is_mcp_secret_key(spelling), spelling
        assert is_url_credential_parameter(spelling), spelling

    # And the URL reader through the door that reads it, which is the
    # half a predicate check on its own would not exercise.
    assert url_credential(f"https://host/v1?{EXEMPT}={SENTINEL}") == "query"
    assert url_credential(f"https://host/v1?{EXEMPT.upper()}={SENTINEL}") == "query"


# The write path
#
# The predicate is not the contract; what an operator meets is. So the
# same table is driven through the three surfaces an option is installed
# from, with the exempted name asserted to arrive and every other name
# asserted to be refused without its value being quoted back.


@pytest.fixture
def keys(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(MASTER_KEY_ENV, generate_key())


@pytest.fixture
def store(keys: None) -> Iterator[ConfigStore]:
    engine = open_database(DatabaseConfig())
    try:
        yield ConfigStore(engine, load_keys())
    finally:
        engine.dispose()


@pytest.fixture
def api(keys: None) -> FastAPI:
    return build_api(TOKEN, DatabaseConfig())


@pytest.fixture
def client(api: FastAPI) -> Iterator[TestClient]:
    with TestClient(api, headers={"Authorization": f"Bearer {TOKEN}"}) as client:
        yield client


@pytest.fixture
def run(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    return runner(monkeypatch)


def _entry(**options: object) -> dict[str, object]:
    """One `anthropic` entry, which is the open-doors half of the
    question: every key beyond `type` is passed through, so a key is
    refused here by the shared rule and by nothing else."""
    return {"type": "anthropic", "model": "claude-sonnet-5", **options}


def test_the_exempted_option_installs_from_a_file(store: ConfigStore) -> None:
    """The file surface, which is where a deployment writes one, and the
    one that never reaches a store: the models refuse on construction,
    so this is the rule at its earliest door."""
    config = load_config_from_data(
        {"providers": {"llm": {"claude": _entry(max_tokens=CONFIGURED)}}}
    )

    assert config.providers.llm["claude"].options == {
        "model": "claude-sonnet-5",
        EXEMPT: CONFIGURED,
    }


def test_the_exempted_option_installs_over_the_api(
    client: TestClient, store: ConfigStore
) -> None:
    """The API surface, read back through the repository rather than
    through the display: what a read shows is a separate claim, made
    below."""
    assert (
        client.put("/providers/llm/claude", json=_entry(max_tokens=CONFIGURED)).status_code
        == 200
    )

    assert store.read_provider("llm", "claude").entry.model_extra[EXEMPT] == CONFIGURED


def test_the_exempted_option_installs_from_the_command_line(
    run, capsys: pytest.CaptureFixture[str]
) -> None:
    """The CLI surface, through its own assignment parsing, so the
    option arrives as the integer a YAML scalar makes of it rather than
    as the string a shell handed over."""
    assert (
        run(
            "provider", "set", "llm", "claude",
            "type=anthropic", "model=claude-sonnet-5", f"max_tokens={CONFIGURED}",
        )
        == 0
    )
    capsys.readouterr()

    assert run("provider", "show", "llm", "claude") == 0
    assert f"{EXEMPT}: {CONFIGURED}" in capsys.readouterr().out


def test_the_exempted_option_installs_under_a_type_that_declares_it(
    client: TestClient, store: ConfigStore
) -> None:
    """The other half of the type question. `openai_compatible` declares
    `max_tokens` as a `StrictInt`, and before the exemption the shared
    rule refused the key before the model it belongs to ever saw it."""
    written = {
        "type": "openai_compatible",
        "base_url": "http://localhost:11434/v1",
        "model": "qwen3:8b",
        "reach": "host",
        EXEMPT: CONFIGURED,
    }

    assert client.put("/providers/llm/local", json=written).status_code == 200

    assert store.read_provider("llm", "local").entry.model_extra[EXEMPT] == CONFIGURED


@pytest.mark.parametrize("case", REFUSED_KEYS, ids=REFUSED_IDS)
@pytest.mark.parametrize("nested", [False, True], ids=["flat", "nested"])
def test_every_other_secret_shaped_key_is_still_refused(
    store: ConfigStore, capsys: pytest.CaptureFixture[str], case: Refused, nested: bool
) -> None:
    """The matrix, at the repository, flat and one key deep.

    Depth is a case rather than a footnote: a provider entry passes
    every option beyond the declared ones through to its implementation,
    so an option can be a structure, and `connection: {api_key: ...}` is
    as ordinary a shape to write as `api_key: ...` is. The exemption is
    a name rule, so it has to hold at whatever depth a name is met.

    The refusal names the fragment and never the key, because an option
    is a key the caller wrote; the value is a sentinel and is asserted
    absent from the exception, its chain, its problems and the two
    streams a repository refusal must put nothing on.
    """
    written = {case.key: SENTINEL}
    fragment = _entry(connection=written) if nested else _entry(**written)

    with pytest.raises(ConfigError) as caught:
        store.set_provider("llm", "claude", fragment)

    refusal = caught.value
    assert f'a key containing "{case.matched}"' in str(refusal)
    assert SENTINEL not in str(refusal)
    assert SENTINEL not in repr(refusal)
    if case.key != case.matched:
        # The key the caller wrote is not quoted back. Skipped only
        # where the key IS one of this repository's own six words, which
        # the refusal names on purpose and which nobody invented.
        assert case.key not in str(refusal)
    assert refusal.__cause__ is None
    assert refusal.__context__ is None
    for carried in refusal.problems:
        assert SENTINEL not in carried.path
        assert SENTINEL not in carried.message

    streams = capsys.readouterr()
    assert SENTINEL not in streams.out
    assert SENTINEL not in streams.err


@pytest.mark.parametrize("case", REFUSED_KEYS, ids=REFUSED_IDS)
@pytest.mark.parametrize("nested", [False, True], ids=["flat", "nested"])
def test_a_refused_key_leaks_nothing_over_the_api(
    client: TestClient,
    caplog: pytest.LogCaptureFixture,
    capsys: pytest.CaptureFixture[str],
    case: Refused,
    nested: bool,
) -> None:
    """And the same table over HTTP, where a refusal has four more
    places to carry a value: the sentence, every pointer, every message,
    and the log in both formats this server writes."""
    written = {case.key: SENTINEL}
    fragment = _entry(connection=written) if nested else _entry(**written)

    with caplog.at_level(logging.DEBUG):
        response = client.put("/providers/llm/claude", json=fragment)

    assert response.status_code == 422
    body = response.json()
    assert SENTINEL not in body["detail"]
    for error in body["errors"]:
        assert SENTINEL not in error["path"]
        assert SENTINEL not in error["message"]
    assert SENTINEL not in response.text
    assert SENTINEL not in str(response.headers)

    text = logging.Formatter(logs.TEXT_FORMAT)
    for record in caplog.records:
        assert SENTINEL not in logs.JsonFormatter().format(record)
        assert SENTINEL not in text.format(record)

    streams = capsys.readouterr()
    assert SENTINEL not in streams.out
    assert SENTINEL not in streams.err


def test_the_env_reference_spelling_keeps_its_own_validation(store: ConfigStore) -> None:
    """`max_tokens_env` is not a probe of this rule and never was: a key
    ending in `_env` is answered before the fragment scan runs, so the
    exemption cannot have moved it either way.

    Both halves, so this is not passing on a key nothing looks at: a
    pasted value is refused without being quoted, and a variable name is
    kept.
    """
    with pytest.raises(ConfigError) as caught:
        store.set_provider("llm", "claude", _entry(max_tokens_env=SENTINEL))
    assert "ending in _env" in str(caught.value)
    assert SENTINEL not in str(caught.value)

    store.set_provider("llm", "claude", _entry(max_tokens_env="MY_PROVIDER_MAX_TOKENS"))
    assert store.read_provider("llm", "claude").entry.model_extra == {
        "model": "claude-sonnet-5",
        "max_tokens_env": "MY_PROVIDER_MAX_TOKENS",
    }


# The wider rule, at the doors that read it
#
# `mcp_secret_fragment` and `is_url_credential_parameter` read a tuple
# of their own, over names this repository never chose: an MCP server's
# env and headers are keyed by whatever the server calls them, and a URL
# query parameter is named by the vendor whose endpoint it addresses. So
# no name there can meet the second condition an exemption is earned by,
# and `max_tokens` is a credential-shaped name at all three doors.
#
# Held to the same discipline as the narrow half above rather than to a
# weaker one, and for the same reason: these refusals are about a value
# that most likely IS a credential, and a refusal is a surface. Each
# case therefore runs on all three surfaces an operator reaches them
# from, with the sentinel asserted absent from the exception, its chain,
# its structured problems, the response body and headers, both log
# formats and both streams.


class Wider(NamedTuple):
    """One wider-rule refusal, and the three ways in: the route a
    request reaches it by, the repository call under it that composes
    the same refusal, and the command words the CLI writes it with.

    `entity` is what every one of these refusals names and the only
    semantic token they share, which is what keeps the terminal case
    from passing on a command that failed for some unrelated reason.
    """

    what: str
    path: str
    argv: tuple[str, ...]
    fragment: dict[str, object]
    write: Callable[[ConfigStore, dict[str, object]], None]
    entity: str


def _mcp(group: str, key: str) -> dict[str, object]:
    """One MCP entry carrying the sentinel under `key`.

    The transport is the one the group belongs to, because an entry that
    is wrong twice would be answered twice, and a case about a
    credential-shaped key must not be riding on a refusal about where
    headers may be written.
    """
    if group == "headers":
        return {
            "transport": "streamable_http",
            "url": "https://example.invalid/mcp",
            "headers": {key: SENTINEL},
        }
    return {"transport": "stdio", "command": "uvx", "env": {key: SENTINEL}}


def _addressed(spelling: str) -> dict[str, object]:
    return {
        "type": "openai_compatible",
        "model": "qwen3:8b",
        "reach": "host",
        "base_url": f"https://host/v1?{spelling}={SENTINEL}",
    }


WIDER = [
    Wider(
        f"an mcp {group} key named {spelling}",
        "/mcp-servers/home",
        ("mcp-server", "set", "home"),
        _mcp(group, spelling),
        lambda store, fragment: store.set_mcp_server("home", fragment),
        "mcp_servers.home",
    )
    for group in ("env", "headers")
    for spelling in (EXEMPT, EXEMPT.upper())
] + [
    Wider(
        f"a provider address with a {spelling} query parameter",
        "/providers/llm/local",
        ("provider", "set", "llm", "local"),
        _addressed(spelling),
        lambda store, fragment: store.set_provider("llm", "local", fragment),
        "providers.llm.local",
    )
    for spelling in (EXEMPT, EXEMPT.upper())
]

WIDER_IDS = [case.what for case in WIDER]


@pytest.mark.parametrize("case", WIDER, ids=WIDER_IDS)
def test_the_exempted_name_is_still_a_credential_to_the_wider_rule(
    store: ConfigStore, capsys: pytest.CaptureFixture[str], case: Wider
) -> None:
    """At the repository, on the exception itself.

    An exception is a surface of its own: anything that walks one reads
    its message, its repr, its cause and its context, and the API's own
    `problems` ride on it. The two streams are asserted because a
    repository refusal is raised rather than printed, so what the write
    path puts on a terminal is nothing at all.
    """
    with pytest.raises(ConfigError) as caught:
        case.write(store, case.fragment)

    refusal = caught.value
    assert SENTINEL not in str(refusal)
    assert SENTINEL not in repr(refusal)
    assert refusal.__cause__ is None
    assert refusal.__context__ is None
    for carried in refusal.problems:
        assert SENTINEL not in carried.path
        assert SENTINEL not in carried.message

    streams = capsys.readouterr()
    assert SENTINEL not in streams.out
    assert SENTINEL not in streams.err


@pytest.mark.parametrize("case", WIDER, ids=WIDER_IDS)
def test_a_wider_rule_refusal_leaks_nothing_over_the_api(
    client: TestClient,
    caplog: pytest.LogCaptureFixture,
    capsys: pytest.CaptureFixture[str],
    case: Wider,
) -> None:
    """And over HTTP, where the same refusal has four more places to
    carry a value: the sentence, every pointer, every message, and the
    log in both formats this server writes."""
    with caplog.at_level(logging.DEBUG):
        response = client.put(case.path, json=case.fragment)

    assert response.status_code == 422
    body = response.json()
    assert SENTINEL not in body["detail"]
    for error in body["errors"]:
        assert SENTINEL not in error["path"]
        assert SENTINEL not in error["message"]
    assert SENTINEL not in response.text
    assert SENTINEL not in str(response.headers)

    text = logging.Formatter(logs.TEXT_FORMAT)
    for record in caplog.records:
        assert SENTINEL not in logs.JsonFormatter().format(record)
        assert SENTINEL not in text.format(record)

    streams = capsys.readouterr()
    assert SENTINEL not in streams.out
    assert SENTINEL not in streams.err


@pytest.mark.parametrize("case", WIDER, ids=WIDER_IDS)
def test_a_wider_rule_refusal_leaks_nothing_from_the_command_line(
    run,
    caplog: pytest.LogCaptureFixture,
    capsys: pytest.CaptureFixture[str],
    case: Wider,
) -> None:
    """And the surface an operator most often writes one from, which is
    the one place a value that got past the two above would be printed
    at a terminal.

    The fragment goes in on stdin, which is how a whole entry is
    written, so what the command holds is the credential the operator
    pasted, and the refusal it prints is the repository's own sentence
    reaching a terminal rather than a body.
    """
    with caplog.at_level(logging.DEBUG):
        code = run(*case.argv, "-f", "-", stdin=yaml.safe_dump(case.fragment))

    assert code != 0
    streams = capsys.readouterr()
    assert SENTINEL not in streams.out
    assert SENTINEL not in streams.err
    # And the refusal really is the one this case is about, so a command
    # that failed for some other reason cannot pass this vacuously.
    assert case.entity in streams.err

    text = logging.Formatter(logs.TEXT_FORMAT)
    for record in caplog.records:
        assert SENTINEL not in logs.JsonFormatter().format(record)
        assert SENTINEL not in text.format(record)


# The value half
#
# A name says a key might carry a credential; what it holds says whether
# it could. The rule above answers the first for one name, and this one
# answers the second for every name there will ever be: a number and a
# bool are not shapes a pasted credential takes, and everything else is
# refused exactly as before.
#
# Held to the same discipline as every other loosening in this file. The
# cases that accept name what arrived, so an acceptance cannot pass by
# dropping the key it is about; the cases that refuse plant the sentinel
# and assert it absent from every surface a refusal has.


VALUE_CASES = [
    ("an integer", 1024, False),
    ("a zero", 0, False),
    ("a float", 0.5, False),
    ("a bool", True, False),
    ("a string", SENTINEL, True),
    ("a blank string", "", True),
    ("the digits as a string", "1024", True),
    ("nothing at all", None, True),
    ("a mapping", {"nested": SENTINEL}, True),
    ("a list", [SENTINEL], True),
]

VALUE_IDS = [case[0] for case in VALUE_CASES]


@pytest.mark.parametrize(("what", "value", "guarded"), VALUE_CASES, ids=VALUE_IDS)
def test_only_a_number_takes_a_secret_shaped_key_out_of_the_guard(
    what: str, value: object, guarded: bool
) -> None:
    """The predicate, before any surface asks it.

    A mapping and a list are refused rather than walked into, which is
    the conservative side of the same decision: a credential nested
    under a key already named `token` is one the walk would have to be
    right about twice, and the key it hangs from already said what it
    is.
    """
    assert could_be_inline_secret(NUMERIC, value) is guarded, what


@pytest.mark.parametrize("case", REFUSED_KEYS, ids=REFUSED_IDS)
def test_every_secret_shaped_key_admits_a_number(store: ConfigStore, case: Refused) -> None:
    """The loosening at its widest, said out loud: this is not a rule
    about `max_completion_tokens`, it is a rule about numbers, so it is
    driven over the whole table of names the string half refuses.

    At the repository rather than at the predicate, because a rule that
    answered correctly while a surface asked a different question is the
    defect this file exists over.
    """
    store.set_provider("llm", "claude", _entry(**{case.key: CONFIGURED}))

    assert store.read_provider("llm", "claude").entry.model_extra[case.key] == CONFIGURED


def test_the_numeric_cap_installs_from_a_file(store: ConfigStore) -> None:
    """The boot surface, which is the door a deployment writes through
    and the one that never reaches a store: the models refuse on
    construction, so a fragment that boots is a fragment the guard
    admitted."""
    config = load_config_from_data(
        {
            "providers": {
                "llm": {
                    "openai": {
                        "type": "openai_compatible",
                        "base_url": "https://api.openai.com/v1",
                        "model": "gpt-5.6-terra",
                        "reach": "internet",
                        NUMERIC: CONFIGURED,
                    }
                }
            }
        }
    )

    assert config.providers.llm["openai"].options[NUMERIC] == CONFIGURED


def test_the_numeric_cap_installs_over_the_api(client: TestClient, store: ConfigStore) -> None:
    """The API surface, read back through the repository."""
    assert (
        client.put("/providers/llm/claude", json=_entry(**{NUMERIC: CONFIGURED})).status_code
        == 200
    )

    assert store.read_provider("llm", "claude").entry.model_extra[NUMERIC] == CONFIGURED


def test_the_numeric_cap_installs_from_the_command_line(
    run, capsys: pytest.CaptureFixture[str]
) -> None:
    """The CLI surface, and the display beside it: what a read shows
    under such a key is the number rather than a mask.

    Both halves in one case, because they are one rule. A cap the write
    path admits and the display hides is a cap an operator cannot read
    back, and an export of it would carry eight asterisks where a number
    belongs.
    """
    assert (
        run(
            "provider", "set", "llm", "claude",
            "type=anthropic", "model=claude-sonnet-5", f"{NUMERIC}={CONFIGURED}",
        )
        == 0
    )
    capsys.readouterr()

    assert run("provider", "show", "llm", "claude") == 0
    shown = capsys.readouterr().out
    assert f"{NUMERIC}: {CONFIGURED}" in shown
    assert "***" not in shown


def test_a_planted_string_beside_a_number_is_still_refused_and_never_echoed(
    store: ConfigStore, capsys: pytest.CaptureFixture[str]
) -> None:
    """The neighbour case, which is the one a value rule could get
    wrong: a number under one secret-shaped key does not buy the entry
    past the string under the next one.

    The refusal is the unchanged sentence, it names the fragment rather
    than the key, and the planted credential reaches neither the
    exception, its chain, its problems nor a terminal.
    """
    fragment = _entry(**{NUMERIC: CONFIGURED, "session_token": SENTINEL})

    with pytest.raises(ConfigError) as caught:
        store.set_provider("llm", "claude", fragment)

    refusal = caught.value
    assert 'a key containing "token" looks like an inline secret' in str(refusal)
    assert SENTINEL not in str(refusal)
    assert SENTINEL not in repr(refusal)
    assert "session_token" not in str(refusal)
    assert refusal.__cause__ is None
    assert refusal.__context__ is None
    for carried in refusal.problems:
        assert SENTINEL not in carried.path
        assert SENTINEL not in carried.message

    streams = capsys.readouterr()
    assert SENTINEL not in streams.out
    assert SENTINEL not in streams.err


def test_a_planted_string_under_the_numeric_name_is_refused_over_the_api(
    client: TestClient, caplog: pytest.LogCaptureFixture
) -> None:
    """The same name the fix is about, holding the thing the fix is not
    about. `max_completion_tokens` is a cap when it holds a number and a
    credential-shaped string when it holds one, and the guard reads what
    is there rather than what the name suggests."""
    with caplog.at_level(logging.DEBUG):
        response = client.put("/providers/llm/claude", json=_entry(**{NUMERIC: SENTINEL}))

    assert response.status_code == 422
    body = response.json()
    assert 'a key containing "token" looks like an inline secret' in body["detail"]
    assert SENTINEL not in response.text
    for error in body["errors"]:
        assert SENTINEL not in error["path"]
        assert SENTINEL not in error["message"]

    text = logging.Formatter(logs.TEXT_FORMAT)
    for record in caplog.records:
        assert SENTINEL not in logs.JsonFormatter().format(record)
        assert SENTINEL not in text.format(record)


@pytest.mark.parametrize(
    ("what", "key"),
    [
        ("a pasted credential", SENTINEL),
        ("a key holding a dot and a slash", "max.completion/tokens"),
        ("a key holding a dash", "max-completion-tokens"),
    ],
)
def test_a_key_that_is_not_a_parameter_name_is_refused_whatever_it_holds(
    store: ConfigStore, capsys: pytest.CaptureFixture[str], what: str, key: str
) -> None:
    """The other condition the value half rests on, and the reason it is
    not just a rule about numbers.

    A secret-shaped key is two shapes: one NAMING a credential slot,
    where the value is the paste, and one that IS the paste, since a key
    is as good a place to put a credential and better at hiding there.
    Only the first is a request parameter, so only a key spelled the way
    a parameter is spelled gets to have its value speak for it, and the
    number under these is not asked about at all.
    """
    with pytest.raises(ConfigError) as caught:
        store.set_provider("llm", "claude", _entry(**{key: CONFIGURED}))

    assert "looks like an inline secret" in str(caught.value)
    assert SENTINEL not in str(caught.value)
    assert SENTINEL not in repr(caught.value)

    streams = capsys.readouterr()
    assert SENTINEL not in streams.out
    assert SENTINEL not in streams.err


# The unchanged-value marker, which is the other door the same rule has
#
# A read masks what a secret-shaped key holds, and a resubmission of
# that read means keep what is stored (#192). The value half moves both
# ends of that: what the read masks, and therefore what a mask
# resubmitted may mean. A number is shown in full, so eight asterisks
# over one were never handed to the caller and cannot be handed back.


@pytest.mark.parametrize("nested", [False, True], ids=["flat", "nested"])
def test_the_mask_is_not_a_keep_marker_over_a_numeric_option(
    store: ConfigStore, nested: bool
) -> None:
    """The round trip the first cut of #444 left open.

    The display shows a numeric cap in full, and the marker walk read
    the name alone, so `max_completion_tokens: "********"` resubmitted
    was read as keep-what-is-stored and quietly restored the number.
    Two doors answering one string two ways: refused as an inline secret
    at one, accepted as a marker at the other.

    Flat and one key deep, because an option can be a structure and the
    walk that finds markers goes to the same depth the display does.
    """
    def written(value: object) -> dict[str, object]:
        return _entry(connection={NUMERIC: value}) if nested else _entry(**{NUMERIC: value})

    store.set_provider("llm", "claude", written(CONFIGURED))

    with pytest.raises(ConfigError) as caught:
        store.set_provider("llm", "claude", written(MASK))

    assert 'a key containing "token" looks like an inline secret' in str(caught.value)

    # And the refused write left the stored cap exactly as it was: the
    # mask was neither written nor resolved.
    held = store.read_provider("llm", "claude").entry.model_extra
    assert (held["connection"][NUMERIC] if nested else held[NUMERIC]) == CONFIGURED


def test_the_marker_still_keeps_what_a_read_really_hid(store: ConfigStore) -> None:
    """The other direction, so the case above is a narrowing rather than
    a removal.

    `max_tokens_env` is secret-shaped and holds a string, so a read
    masks it and a resubmitted mask still means keep what is stored.
    Nothing about the marker moved except the values it can stand for.
    """
    store.set_provider("llm", "claude", _entry(max_tokens_env="MY_PROVIDER_MAX_TOKENS"))

    store.set_provider("llm", "claude", _entry(max_tokens_env=MASK))

    assert store.read_provider("llm", "claude").entry.model_extra == {
        "model": "claude-sonnet-5",
        "max_tokens_env": "MY_PROVIDER_MAX_TOKENS",
    }


def test_the_wider_rule_reads_the_value_the_same_way() -> None:
    """The MCP and URL readers are untouched by this, and they cannot be
    reached by it either: both maps are typed `dict[str, str]` and a URL
    query parameter is a string by construction, so there is no number
    to admit there. Stated rather than assumed, since the two tuples
    remain one rule with one exemption between them."""
    assert is_mcp_secret_key(NUMERIC)
    assert is_url_credential_parameter(NUMERIC)
    assert url_credential(f"https://host/v1?{NUMERIC}={SENTINEL}") == "query"
