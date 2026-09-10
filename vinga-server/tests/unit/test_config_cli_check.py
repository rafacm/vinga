"""The diagnosis command: `config check`.

An `apply` that the stored configuration will not satisfy is refused
without a location, deliberately (#414): what a reload refuses on is
arbitrary stored state, and a sentence composed over it can quote a
value that was written into the wrong field. A boot refuses on the same
state and names the location and the rule without the value, because it
is composing a snapshot rather than answering a request about one. #443
is the gap between those two, and this command is the bridge: it runs
the boot's own read and prints what that read says.

So the claims here come in two halves.

**It is the boot and not a second opinion.** Every refusal below is
reached by seeding a store and running the command, and every sentence
asserted is one `config/boot.py` composes, because the command calls
`load_boot_config` and nothing else. A test that pinned wording of its
own would be describing a formatter this command must never grow.

**It says nothing a value could be read out of.** The refusals name an
entry, a slot and a rule; they never name what is stored there, and
neither does the success line. Credential-shaped sentinels are planted
in the fields that could carry one (a prompt, an MCP server's URL, a
stored secret's plaintext, the path of the file half, the database
password), and absence is asserted on the surfaces the refusal suites
use: stdout, stderr, every log record rendered whole, and the exception
chain a walker would find. The database password is the one that is not
stored state, and it is here because an unreachable instance is a
failure mode this command has and the reload answer does not.

The last claim is per boundary rather than global, and the suite is
shaped that way rather than claiming it once: five failure families
(the file half will not parse, the snapshot will not compose, a stored
credential will not open, a stored row will not read, the database
cannot be reached) are each a different module's `except` replacing a
different exception, so each is driven and each asserts the chain and
the log for itself. A migration that fails has no case of its own
because it has no boundary of its own: `db.open_url` catches everything
`upgrade_to_head` raises and answers with the fixed sentence the
unreachable case asserts.

What this file does NOT claim is anything about a stored IDENTITY. That
those are spoken in full, stripped of what a URL of one hides and
escaped where a control character survives, is #382's settled decision
and lives with the rest of the identity-display claims in
`test_config_url_credential_display.py`, which drives this command
against planted names of all four kinds.
"""

import logging
from collections.abc import Callable
from pathlib import Path

import pytest
from sqlalchemy import insert

from tests.support.config_cli import chain, logged
from vinga_server import logs
from vinga_server.config import cli
from vinga_server.config.loader import ConfigError, load_file_config
from vinga_server.config.secrets import (
    MASTER_KEY_ENV,
    SecretLocation,
    generate_key,
    load_keys,
)
from vinga_server.config.store import ConfigStore
from vinga_server.db import open_database, schema

# One per field a stored value or an invocation could carry, so a leak
# says which field it came out of. None is a real credential and each is
# shaped so a substring check for it cannot match by accident.
PROMPT_SENTINEL = "sk-prompt-1c4e8a02-never-a-real-credential"

URL_SENTINEL = "tok-url-9b3d51fa-never-a-real-credential"

STORED_SENTINEL = "sk-stored-6e07b24d-never-a-real-credential"

CONFIG_PATH_SENTINEL = "sk-path-3f95c1e8-never-a-real-credential"

PASSWORD_SENTINEL = "sk-password-8d26af03-never-a-real-credential"

ALL_SENTINELS = (
    PROMPT_SENTINEL,
    URL_SENTINEL,
    STORED_SENTINEL,
    CONFIG_PATH_SENTINEL,
    PASSWORD_SENTINEL,
)

# The slot the rotated-away key case stores under, named once because
# both the seeding and the assertion need the same location.
SLOT = SecretLocation.mcp_server("weather", "headers.Authorization")

# The library whose INFO records are the stored configuration itself,
# read off the floors table rather than spelled a second time.
SQL_LOGGER = "sqlalchemy"


@pytest.fixture(autouse=True)
def _environment(monkeypatch: pytest.MonkeyPatch) -> None:
    """A machine with a master key and no server anywhere.

    No `VINGA_CONFIG` and no API address, because this command reads
    neither: the file half it composes is the environment's, and the
    configuration API is not in its path at all. `build_client` is taken
    away rather than left unused, so a command that started reaching for
    a server fails here rather than passing quietly.
    """
    monkeypatch.delenv("VINGA_CONFIG", raising=False)
    monkeypatch.delenv(cli.API_URL_ENV, raising=False)
    monkeypatch.setenv(MASTER_KEY_ENV, generate_key())
    monkeypatch.setattr(cli, "build_client", _never_a_client)


def _never_a_client(base_url: str, token: str):
    raise AssertionError("check reached for the configuration API, which it must not")


def seeded(write: Callable[[ConfigStore], object]) -> None:
    """One write against the store this command is about to read.

    Through the file half's own database settings, which is what the
    command resolves too: the lane names its database in the model
    defaults and in the environment, and reading it the way the command
    reads it is what keeps this test and the command in one database.
    """
    engine = open_database(load_file_config(None).server.database)
    try:
        write(ConfigStore(engine, load_keys()))
    finally:
        engine.dispose()


def pipeline(store: ConfigStore) -> None:
    """The four stages an agent needs, so that a store is refused for
    the reason a case is about rather than for a missing provider."""
    for stage in ("llm", "asr", "tts", "vad"):
        store.set_provider(stage, "mock", {"type": "mock"})
    store.set_agent_defaults(dict.fromkeys(("llm", "asr", "tts", "vad"), "mock"))


def planted(store: ConfigStore) -> None:
    """A store that composes, carrying a sentinel in each of the two
    plaintext fields an entity body can hold a pasted credential in."""
    pipeline(store)
    store.set_mcp_server(
        "weather",
        {"transport": "streamable_http", "url": f"https://api.example/mcp?key={URL_SENTINEL}"},
    )
    store.set_agent("sam", {"prompt": f"You are Sam. {PROMPT_SENTINEL}"})
    store.set_default_agent("sam")


def absent(*surfaces: str) -> None:
    """Every sentinel, on every surface a value could come out on.

    The surfaces are passed in rather than read here, because reading
    them is destructive: `capsys.readouterr()` empties what it returns,
    and a helper that took the fixture would leave a caller with nothing
    to make its own assertion about.
    """
    for surface in surfaces:
        for sentinel in ALL_SENTINELS:
            assert sentinel not in surface, sentinel


# What it answers


def test_a_store_that_composes_is_one_line_and_an_exit_of_zero(
    capsys: pytest.CaptureFixture[str],
) -> None:
    """The success answer. On stderr, because it is a fact about this
    run rather than an artifact: the command renders no document, and
    its refusal leaves by the same door, so the exit code is what a
    script reads and the line is what a person does."""
    seeded(planted)

    assert cli.main(["check"]) == 0

    printed = capsys.readouterr()
    assert printed.out == ""
    assert printed.err.strip() == cli.COMPOSES


def test_an_empty_store_composes(capsys: pytest.CaptureFixture[str]) -> None:
    """A deployment that has configured nothing yet is not a broken one:
    it is what a fresh database holds, and a server boots on it."""
    assert cli.main(["check"]) == 0
    assert capsys.readouterr().err.strip() == cli.COMPOSES


def test_a_store_that_does_not_compose_names_the_entry_and_the_rule(
    capsys: pytest.CaptureFixture[str],
) -> None:
    """The sentence #443 was filed for, and the whole reason this
    command exists: `apply` refuses this same state without saying
    where, and here is where."""
    seeded(lambda store: (pipeline(store), store.set_agent("sam", {"prompt": "You are Sam."})))

    assert cli.main(["check"]) == 1

    printed = capsys.readouterr()
    assert printed.out == ""
    refusal = printed.err
    # The location, the rule, and what to do about it, which is what the
    # boot composes and this command does not compose again.
    assert "the domain schema of the vinga database" in refusal
    assert "default_agent is required" in refusal
    assert "sam" in refusal


def test_a_stored_credential_no_key_opens_names_the_entity_and_the_slot(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """The second refusal family, and the one where a value is closest
    to the sentence: what will not open is the plaintext, and the answer
    names the entity and the slot instead of it."""
    seeded(
        lambda store: (
            pipeline(store),
            store.set_mcp_server(
                "weather", {"transport": "streamable_http", "url": "https://api.example/mcp"}
            ),
            store.set_secret(SLOT, STORED_SENTINEL),
        )
    )
    monkeypatch.setenv(MASTER_KEY_ENV, generate_key())

    assert cli.main(["check"]) == 1

    printed = capsys.readouterr()
    assert printed.out == ""
    assert SLOT.describe() in printed.err
    assert STORED_SENTINEL not in printed.err


def test_a_database_it_cannot_reach_is_the_databases_own_sentence(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """The failure mode this command has and the reload answer does not:
    a store nothing can open at all. It is the sentence `db` composes,
    which repeats no part of the connection, and it is reached through
    this command without a word of its own added."""
    monkeypatch.setenv("VINGA_DB_PORT", "1")
    monkeypatch.setenv("VINGA_DB_PASSWORD", PASSWORD_SENTINEL)

    assert cli.main(["check"]) == 1

    printed = capsys.readouterr()
    assert printed.out == ""
    assert "cannot open the vinga database" in printed.err
    assert PASSWORD_SENTINEL not in printed.err


def test_a_file_half_that_will_not_open_is_refused_before_the_database(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """`--config` is the one argument this command takes, and a path
    that names nothing is the boot's own refusal: the file half is step
    one, so nothing is opened before it fails."""
    named = str(tmp_path / f"{CONFIG_PATH_SENTINEL}.yaml")

    assert cli.main(["--config", named, "check"]) == 1

    printed = capsys.readouterr()
    assert printed.out == ""
    assert printed.err.strip()
    assert CONFIG_PATH_SENTINEL not in printed.err


# What it never says while answering


@pytest.mark.parametrize(
    "argv",
    [
        pytest.param(["check"], id="the-store-alone"),
        pytest.param(
            ["--config", f"/tmp/{CONFIG_PATH_SENTINEL}/config.yaml", "check"],
            id="a-file-half-that-is-not-there",
        ),
    ],
)
def test_no_answer_repeats_anything_it_was_given(
    argv: list[str],
    capsys: pytest.CaptureFixture[str],
    caplog: pytest.LogCaptureFixture,
) -> None:
    """The sentinel battery over the paths that succeed and the paths
    that refuse, with a planted value in every field of a store that
    composes.

    Both invocations read the same seeded store; one of them never
    reaches it, because the file half it was pointed at is not there.
    Neither may print a stored value, and neither may print the path.
    """
    seeded(planted)
    with caplog.at_level(0):
        cli.main(argv)

    printed = capsys.readouterr()
    absent(printed.out, printed.err, logged(caplog))


def test_a_refusal_about_the_store_repeats_nothing_stored(
    capsys: pytest.CaptureFixture[str], caplog: pytest.LogCaptureFixture
) -> None:
    """The same battery on the path that matters most: a store carrying
    sentinels that does NOT compose, so the sentence being printed is
    one composed over the state the sentinels are in.

    The rule broken is the default agent's, which is the one whose
    sentence quotes names out of the store: it lists the agents that
    could be named, and an agent's name is beside the prompt a
    credential gets pasted into.
    """
    seeded(
        lambda store: (
            pipeline(store),
            store.set_mcp_server(
                "weather",
                {
                    "transport": "streamable_http",
                    "url": f"https://api.example/mcp?key={URL_SENTINEL}",
                },
            ),
            store.set_secret(SLOT, STORED_SENTINEL),
            store.set_agent("sam", {"prompt": f"You are Sam. {PROMPT_SENTINEL}"}),
        )
    )

    with caplog.at_level(0):
        assert cli.main(["check"]) == 1

    printed = capsys.readouterr()
    assert "default_agent is required" in printed.err
    absent(printed.out, printed.err, logged(caplog))


def test_an_unreachable_database_repeats_nothing_of_the_connection(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    caplog: pytest.LogCaptureFixture,
) -> None:
    """The failure mode with the most to leak: the driver's own error
    carries the connection string, and a command that let it out would
    publish the database password. Both surfaces and the log."""
    monkeypatch.setenv("VINGA_DB_PORT", "1")
    monkeypatch.setenv("VINGA_DB_PASSWORD", PASSWORD_SENTINEL)

    with caplog.at_level(0):
        assert cli.main(["check"]) == 1

    printed = capsys.readouterr()
    absent(printed.out, printed.err, logged(caplog))


def _unparseable(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> str:
    """A file half that will not parse, holding a sentinel where a
    parser would point. What PyYAML raises carries the buffer it stopped
    in, which is the whole document."""
    named = tmp_path / "config.yaml"
    named.write_text(f"server:\n  port: [8003\n  token: {CONFIG_PATH_SENTINEL}\n", encoding="utf-8")
    return str(named)


def _will_not_compose(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> str:
    """A store carrying a sentinel in every plaintext field, refused by
    the rule about a runnable deployment."""
    seeded(
        lambda store: (
            pipeline(store),
            store.set_mcp_server(
                "weather",
                {
                    "transport": "streamable_http",
                    "url": f"https://api.example/mcp?key={URL_SENTINEL}",
                },
            ),
            store.set_agent("sam", {"prompt": f"You are Sam. {PROMPT_SENTINEL}"}),
        )
    )
    return ""


def _a_key_that_will_not_open(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> str:
    """A stored credential written under one key and read under another,
    which is the failure whose plaintext is closest to the sentence."""
    seeded(
        lambda store: (
            pipeline(store),
            store.set_mcp_server(
                "weather", {"transport": "streamable_http", "url": "https://api.example/mcp"}
            ),
            store.set_secret(SLOT, STORED_SENTINEL),
            store.set_agent("sam", {"prompt": f"You are Sam. {PROMPT_SENTINEL}"}),
            store.set_default_agent("sam"),
        )
    )
    monkeypatch.setenv(MASTER_KEY_ENV, generate_key())
    return ""


def _a_row_that_will_not_read(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> str:
    """Storage rather than composition: a row put in place by something
    that never passed through a write, holding a body no model parses.

    The same door a failed migration leaves by, which is why there is no
    separate case for one: `db.open_url` catches everything
    `upgrade_to_head` raises and answers with the fixed sentence the
    unreachable case below asserts, so a migration failure is that case
    with a different cause behind the same boundary.
    """
    engine = open_database(load_file_config(None).server.database)
    try:
        with engine.begin() as connection:
            connection.execute(
                insert(schema.agents).values(name="sam", body=f'{{"llm": {PROMPT_SENTINEL!r}}}')
            )
    finally:
        engine.dispose()
    return ""


def _nothing_to_connect_to(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> str:
    """An instance nothing can reach, with the password in the
    connection string the driver's own error carries."""
    monkeypatch.setenv("VINGA_DB_PORT", "1")
    monkeypatch.setenv("VINGA_DB_PASSWORD", PASSWORD_SENTINEL)
    return ""


@pytest.mark.parametrize(
    ("arrange", "marker"),
    [
        pytest.param(_unparseable, "invalid YAML in the config file", id="file-parsing"),
        pytest.param(
            _will_not_compose, "invalid config in the domain schema", id="composition"
        ),
        pytest.param(
            _a_key_that_will_not_open,
            "the stored secret cannot be decrypted",
            id="secret-verification",
        ),
        pytest.param(
            _a_row_that_will_not_read,
            "the row cannot be read as configuration",
            id="storage",
        ),
        pytest.param(
            _nothing_to_connect_to, "cannot open the vinga database", id="the-database"
        ),
    ],
)
def test_no_refusal_carries_a_sentinel_on_any_surface(
    arrange: Callable[[Path, pytest.MonkeyPatch], str],
    marker: str,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Every way this command can refuse, against the surface no caller
    of `cli.main` can reach.

    The command function is driven directly rather than through the
    boundary, which is the point: `main` prints the refusal and returns,
    so the exception is gone by the time a test could look at it, and
    what has to be held is the raise itself. A psycopg error on
    `__context__` holds the connection string it failed on, password and
    all, and a PyYAML error's `problem_mark.buffer` holds the whole
    document it stopped in; neither is displayed and both are one
    `__context__` hop from anything walking the chain.

    Parameterized over the failure families rather than over one of
    them, because the containment is per boundary and not global: each
    of these is a different module's `except` and a different exception
    being replaced. A suite that drove one and claimed all five would be
    the docstring the review round asked to be narrowed.

    An underscore reach-in, for the reason `test_missing_server_half`
    makes the same one: the exception chain is not on this module's
    interface, and it is what the claim is about.
    """
    path = arrange(tmp_path, monkeypatch)

    with caplog.at_level(0), pytest.raises(ConfigError) as refused:
        cli._check(cli.Invocation(config=path or None))

    # The marker is what keeps the parameterization honest: five cases
    # that all fell into one boundary would satisfy the absence claim
    # while proving it about one `except` five times.
    assert marker in str(refused.value)
    absent(chain(refused.value), logged(caplog))


# The floor under the libraries that narrate somebody else's bytes


def test_the_vendor_floor_is_applied_before_the_store_is_opened(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """A SQLAlchemy logger deliberately turned all the way up, and a
    command that turns it back down before opening anything.

    The gap this closes is the console script's: `vinga-server config`
    passes through `main.py`, which applies the floor before it
    dispatches, and `vinga` does not, because the script is its own
    entry point into `cli.main`. That was harmless while every command
    was an HTTP request, which quiets the request libraries around its
    own call. It stopped being harmless here: an engine whose logger is
    enabled for INFO echoes every statement with the parameters bound to
    it, and for this store those parameters are the stored
    configuration.

    Driven at the level a diagnosis would leave behind rather than at
    the library's default, since the default is already quiet and a test
    against it would pass with no floor at all. Through `caplog` rather
    than by setting the level outright, so a logger's level, which is
    process state, is given back to the next test whatever this one
    does.
    """
    seeded(planted)

    with caplog.at_level(logging.DEBUG, logger=SQL_LOGGER), caplog.at_level(0):
        assert cli.main(["check"]) == 0

    assert logging.getLogger(SQL_LOGGER).level == logs.VENDOR_LOG_FLOORS[SQL_LOGGER]
    assert [record for record in caplog.records if record.name.startswith(SQL_LOGGER)] == []
    absent(logged(caplog))
