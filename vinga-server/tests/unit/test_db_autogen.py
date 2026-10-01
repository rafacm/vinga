"""What the autogeneration command connects to.

`python -m vinga_server.db.migrations.autogen` is the one thing in this
repository that makes a database, migrates it and drops it, and it is
run by a maintainer on a machine where an exported `VINGA_DB_URL` may
name anything at all. That combination is worth pinning: the command
used to make its scratch database from the discrete settings and then
open it through `open_at`, which resolves the connection AGAIN from the
environment, and a URL wins that resolution whole. The scratch database
landed locally and the migration ran wherever the URL pointed.

Driven against a real database rather than a mock, because what is
asserted is which database has schemas in it afterwards, and that is a
fact only Postgres can answer. The chain's migrations directory is
copied into `tmp_path` first: autogenerate WRITES a revision file, and a
test that let it write into the packaged tree would leave one behind.
"""

import re
import secrets
import shutil
import threading
from pathlib import Path

import psycopg
import pytest
from alembic import command
from sqlalchemy import text

from vinga_server.config.models import DatabaseConfig
from vinga_server.db import DOMAIN_CHAIN, URL_REFUSED, StoreChain, connection_url
from vinga_server.db.migrations import autogen


def _chain_in(tmp_path: Path, chain: StoreChain = DOMAIN_CHAIN) -> StoreChain:
    """One chain, with its migrations somewhere disposable.

    Same schema and same lock key, because the subject is the connection
    and not the chain: what moves is only the directory the revision
    file is written into.
    """
    where = tmp_path / "migrations"
    shutil.copytree(chain.migrations, where)
    return StoreChain(schema=chain.schema, migrations=where, lock_key=chain.lock_key)


def _url_of(database: str) -> str:
    """One of this run's databases as a `VINGA_DB_URL` would name it."""
    return connection_url(DatabaseConfig(name=database)).render_as_string(
        hide_password=False
    )


def _schemas(database: str) -> set[str]:
    """Every schema in one database, as its own connection reports them."""
    url = connection_url(DatabaseConfig(name=database)).set(drivername="postgresql")
    connection = psycopg.connect(url.render_as_string(hide_password=False))
    try:
        found = connection.execute(
            "select nspname from pg_namespace where nspname not like 'pg\\_%' "
            "and nspname <> 'information_schema'"
        ).fetchall()
    finally:
        connection.close()
    return {row[0] for row in found}


def _exists(database: str) -> bool:
    url = connection_url(DatabaseConfig(name="postgres")).set(drivername="postgresql")
    connection = psycopg.connect(url.render_as_string(hide_password=False))
    try:
        return (
            connection.execute(
                "select 1 from pg_database where datname = %s", (database,)
            ).fetchone()
            is not None
        )
    finally:
        connection.close()


def _drop_scratch(database: str) -> None:
    """Clean up after a case whose subject is a database the command may
    have left behind, so a mutant that leaks one does not litter the
    instance. Refuses any name that is not the command's own."""
    assert database.startswith(autogen.SCRATCH_PREFIX), database
    url = connection_url(DatabaseConfig(name="postgres")).set(drivername="postgresql")
    connection = psycopg.connect(url.render_as_string(hide_password=False), autocommit=True)
    try:
        connection.execute(f'drop database if exists "{database}" with (force)')
    finally:
        connection.close()


def test_a_url_override_never_migrates_the_database_it_names(
    blank_database: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The bug, stated as the property that was violated.

    `VINGA_DB_URL` names a database with nothing in it. The command must
    derive its scratch database from that same connection, migrate THAT,
    and leave the database the URL actually names as blank as it found
    it. Before the connection was resolved once, this database came back
    with the domain schema in it and a version table stamped.
    """
    monkeypatch.setenv("VINGA_DB_URL", _url_of(blank_database))
    before = _schemas(blank_database)

    autogen.generate("a probe of where this lands", _chain_in(tmp_path))

    assert _schemas(blank_database) == before
    assert DOMAIN_CHAIN.schema not in _schemas(blank_database)


def test_the_scratch_database_is_made_migrated_and_taken_away(
    blank_database: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """And the other half, so the case above cannot be satisfied by a
    command that does nothing at all.

    A revision file is written, which is only possible against a
    database Alembic reached and compared, and the scratch database is
    gone afterwards, which is what makes the command repeatable. Asked
    about by the name this run made, and no other: a concurrent lane's
    run is free to hold a database with the same prefix at this moment.

    The name is the prefix and a suffix of its own, and a lowercase
    identifier Postgres would neither fold nor truncate, so the name
    the command drops is the name it made.
    """
    monkeypatch.setenv("VINGA_DB_URL", _url_of(blank_database))
    chain = _chain_in(tmp_path)
    before = set((chain.migrations / "versions").glob("*.py"))

    name = autogen.generate("a probe that leaves a file", chain)

    written = set((chain.migrations / "versions").glob("*.py")) - before
    assert len(written) == 1, written
    assert name.startswith(autogen.SCRATCH_PREFIX), name
    assert name != autogen.SCRATCH_PREFIX, name
    assert re.fullmatch(r"[a-z_][a-z0-9_]{0,62}", name), name
    assert not _exists(name)


class ComparisonFailed(Exception):
    """What the comparison raises in the case below: nothing a real
    failure could be mistaken for."""


def test_a_failed_comparison_still_takes_its_scratch_database_away(
    blank_database: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The drop is in a `finally`, and this is the case that says so.

    The comparison fails after the scratch database was made, migrated
    and connected to, which is where an Alembic failure lands. The
    database is named from inside it, through the connection the
    command handed Alembic, and it must be gone once the failure has
    travelled out. A drop on the success path only would leave it.
    """
    monkeypatch.setenv("VINGA_DB_URL", _url_of(blank_database))
    made: list[str] = []

    def failing_revision(config, **options):
        connection = config.attributes["connection"]
        made.append(connection.execute(text("select current_database()")).scalar_one())
        raise ComparisonFailed

    monkeypatch.setattr(command, "revision", failing_revision)
    try:
        with pytest.raises(ComparisonFailed):
            autogen.generate("a probe whose comparison fails", _chain_in(tmp_path))

        assert len(made) == 1, made
        assert made[0].startswith(autogen.SCRATCH_PREFIX), made
        assert not _exists(made[0])
    finally:
        for name in made:
            _drop_scratch(name)


def test_a_name_already_taken_is_refused_and_left_alone(
    blank_database: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The other edge of the same `finally`: the drop is entered only
    once this run's own `create` succeeded.

    The name the command would choose is made to exist first, which is
    a collision forced rather than waited for: the random suffix is
    pinned to one drawn here, so no other run, this lane's or another's,
    can hold it. The command must refuse at its `create` and leave that
    database exactly where it was, because it is somebody else's. A
    `finally` that also covered the `create` would drop it with `force`,
    connections and all, which is the bug the per-run name exists to fix.
    """
    monkeypatch.setenv("VINGA_DB_URL", _url_of(blank_database))
    suffix = secrets.token_hex(8)
    taken = autogen.SCRATCH_PREFIX + suffix
    url = connection_url(DatabaseConfig(name="postgres")).set(drivername="postgresql")
    connection = psycopg.connect(url.render_as_string(hide_password=False), autocommit=True)
    try:
        connection.execute(f'create database "{taken}"')
    finally:
        connection.close()
    try:
        monkeypatch.setattr(secrets, "token_hex", lambda nbytes=None: suffix)

        with pytest.raises(psycopg.errors.DuplicateDatabase):
            autogen.generate("a probe that meets a taken name", _chain_in(tmp_path))

        assert _exists(taken)
    finally:
        _drop_scratch(taken)


def test_two_runs_at_once_each_keep_their_own_scratch_database(
    blank_database: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Two lanes on one instance, which is every machine with more than
    one worktree, and the interleaving that used to break one of them.

    The first run is held at the moment it has its scratch database at
    head and a connection open inside it, about to compare, and the
    second run goes through its whole lifecycle in that window. Then
    the first is let go. Forced rather than raced, so the collision is
    met on every run and not on a lucky one: with one fixed name the
    second run's `drop ... with (force)` terminated the first's
    connection and its comparison failed, and with no drop before the
    create it is the second run's `create` that fails instead. Either
    way one of the two did not complete.

    Each run writes its own candidate and leaves no database behind,
    asked about by the name each one made.
    """
    monkeypatch.setenv("VINGA_DB_URL", _url_of(blank_database))
    chains = {
        "first": _chain_in(tmp_path / "first"),
        "second": _chain_in(tmp_path / "second"),
    }
    before = {
        run: set((chain.migrations / "versions").glob("*.py"))
        for run, chain in chains.items()
    }
    holding = threading.Event()
    second_done = threading.Event()
    compare = command.revision

    def held_revision(config, **options):
        # The first run's thread pauses here, with its connection to its
        # scratch database open, until the second run has finished.
        if threading.current_thread().name == "first":
            holding.set()
            second_done.wait(timeout=600)
        return compare(config, **options)

    monkeypatch.setattr(command, "revision", held_revision)
    outcomes: dict[str, str | Exception] = {}

    def run(which: str) -> None:
        try:
            outcomes[which] = autogen.generate(f"a probe from the {which} run", chains[which])
        except Exception as failure:
            # Kept rather than raised: a thread's exception reaches no
            # assertion, and the answer below reads both outcomes.
            outcomes[which] = failure

    first = threading.Thread(target=run, args=("first",), name="first")
    first.start()
    try:
        assert holding.wait(timeout=600), outcomes
        run("second")
    finally:
        second_done.set()
        first.join(timeout=600)
    assert not first.is_alive()

    for which in chains:
        assert isinstance(outcomes[which], str), (which, outcomes[which])
    names = {which: str(outcomes[which]) for which in chains}
    assert names["first"] != names["second"], names
    for which, chain in chains.items():
        written = set((chain.migrations / "versions").glob("*.py")) - before[which]
        assert len(written) == 1, (which, written)
        assert not _exists(names[which]), which


# Which chain a selector reaches
#
# The command is one piece of work with the chain as its only argument,
# which is what `StoreChain` is for, and the selectors are therefore the
# whole of what can be wrong about it: a flag that was deleted, or one
# mapped to the wrong chain, would write a candidate migration for a
# schema nobody asked about. Nothing else in this suite would notice,
# because every case above passes the chain in directly.
#
# Asserted through `generate`, which is the public seam `main` reaches
# the work through, so what is pinned is the argument the command
# composes rather than an internal call.


def _selected(monkeypatch: pytest.MonkeyPatch) -> list[StoreChain]:
    """Every chain this run's command hands to the work, in order."""
    seen: list[StoreChain] = []

    def spy(message: str, chain: StoreChain) -> None:
        seen.append(chain)

    monkeypatch.setattr(autogen, "generate", spy)
    return seen


def test_the_selectors_name_the_chains_they_say_they_do(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """All three, by the spelling an operator types.

    The domain chain has no flag because it is what the command did when
    it was the only chain there was, and that is asserted here too: a
    default quietly moved to another chain is the same defect as a flag
    pointing at the wrong one.
    """
    from vinga_server.conversations.store import CONVERSATIONS_CHAIN
    from vinga_server.memory.store import MEMORY_CHAIN

    expected = {
        (): DOMAIN_CHAIN,
        ("--conversations",): CONVERSATIONS_CHAIN,
        ("--memory",): MEMORY_CHAIN,
    }
    for selector, chain in expected.items():
        seen = _selected(monkeypatch)

        assert autogen.main([*selector, "a probe of which chain"]) == 0, selector

        assert seen == [chain], selector


def test_the_usage_line_names_every_selector(
    capsys: pytest.CaptureFixture[str],
) -> None:
    """A flag nothing prints is a flag nobody finds. The usage is what a
    maintainer reads when they get the arguments wrong, so it names the
    chains the command can be pointed at."""
    assert autogen.main([]) == 2

    usage = capsys.readouterr().err
    assert "--conversations" in usage
    assert "--memory" in usage


def test_the_memory_chain_autogenerates_against_a_scratch_database(
    blank_database: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The third chain through the whole lifecycle, which is how its
    baseline was written in the first place.

    The environment under `memory/migrations/` refuses to run without a
    connection and a chain on the config's attributes, so this is the
    one path that proves the command supplies both for it: a revision
    file is written, which is only possible against a database Alembic
    reached, migrated and compared.
    """
    from vinga_server.memory.store import MEMORY_CHAIN

    monkeypatch.setenv("VINGA_DB_URL", _url_of(blank_database))
    chain = _chain_in(tmp_path, MEMORY_CHAIN)
    before = set((chain.migrations / "versions").glob("*.py"))

    name = autogen.generate("a probe of the third chain", chain)

    written = set((chain.migrations / "versions").glob("*.py")) - before
    assert len(written) == 1, written
    assert not _exists(name)
    # And the database the URL named is as blank as it was: the scratch
    # database is derived from that connection, never the one it names.
    assert MEMORY_CHAIN.schema not in _schemas(blank_database)


# What a failing maintenance lifecycle is allowed to say
#
# This is the one module in the project that connects with psycopg
# directly and issues `CREATE DATABASE`, and psycopg quotes the DSN it
# tried in every failure it raises. A module entry point that let one
# escape would print a connection string, so the sentinel is planted in
# all three places a credential can ride in and the streams are read.

# Not a credential: fixed strings shaped like one, and shaped so a
# substring hunt for either cannot match by accident.
SENTINEL = "sk-live-7d31c9f4-never-a-real-credential"
OTHER_SENTINEL = "tok-live-2b8e50a1-never-a-real-credential"

# A host nothing can resolve, so the lifecycle fails at its first
# connection whatever else is planted. `.invalid` is reserved by
# RFC 2606 for exactly this.
NOWHERE = "nowhere.invalid"

# The three doors a credential reaches this command through: the
# authority of a whole URL, the query of a whole URL (`sslpassword` is
# the one people forget, which is why the plan named it), and the
# discrete variables.
PLANTINGS: dict[str, dict[str, str]] = {
    "a URL authority": {
        "VINGA_DB_URL": f"postgresql://vinga:{SENTINEL}@{NOWHERE}:5432/vinga",
    },
    "a URL query": {
        "VINGA_DB_URL": (
            f"postgresql://vinga:pw@{NOWHERE}:5432/vinga?sslpassword={SENTINEL}"
        ),
    },
    "the discrete variables": {
        "VINGA_DB_HOST": f"{SENTINEL}.invalid",
        "VINGA_DB_PORT": "5432",
        "VINGA_DB_NAME": SENTINEL,
        "VINGA_DB_USER": SENTINEL,
        "VINGA_DB_PASSWORD": OTHER_SENTINEL,
    },
}


@pytest.fixture
def planted(monkeypatch: pytest.MonkeyPatch, request: pytest.FixtureRequest):
    """One of the three plantings, and nothing of this lane's own left in
    the environment to answer instead."""
    monkeypatch.delenv("VINGA_CONFIG", raising=False)
    monkeypatch.delenv("VINGA_DB_URL", raising=False)
    for name, value in PLANTINGS[request.param].items():
        monkeypatch.setenv(name, value)


@pytest.mark.parametrize("planted", list(PLANTINGS), indirect=True)
def test_a_failed_lifecycle_says_one_sentence_and_carries_no_credential(
    planted: None, capsys: pytest.CaptureFixture[str]
) -> None:
    """The entry point, driven at an instance that is not there.

    One fixed sentence on stderr, exit 1, and nothing of the connection:
    no sentinel, no traceback, and no psycopg wording. `main` returning
    rather than raising is the rest of the claim, since an exception is
    what would carry the DSN out on a chain a renderer walks, and this
    call site would see it.
    """
    assert autogen.main(["a probe that cannot connect"]) == 1

    captured = capsys.readouterr()
    written = captured.out + captured.err
    assert autogen.MAINTENANCE_FAILED in captured.err, written
    assert SENTINEL not in written, written
    assert OTHER_SENTINEL not in written, written
    assert "Traceback" not in written, written
    assert "connection to server" not in written, written
    assert NOWHERE not in written, written


def test_a_url_that_is_not_a_postgres_url_refuses_without_repeating_it(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """The other arm of the boundary: a refusal this project composed
    itself is printed as it stands, because `db` builds those outside
    their handlers precisely so they carry nothing."""
    monkeypatch.delenv("VINGA_CONFIG", raising=False)
    monkeypatch.setenv("VINGA_DB_URL", f"mysql://vinga:{SENTINEL}@{NOWHERE}/vinga")

    assert autogen.main(["a probe with the wrong scheme"]) == 1

    captured = capsys.readouterr()
    assert URL_REFUSED in captured.err
    assert SENTINEL not in captured.out + captured.err
