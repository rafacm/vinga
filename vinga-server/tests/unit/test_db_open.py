"""Opening the domain configuration schema: migration, reopen, refusal.

The database is opened by the server at boot and by every CLI
invocation, so the interesting cases are the ones that happen without
anybody watching: a blank database, a schema that is already current,
two processes doing either at the same moment, and an instance that is
not there at all.

What retired with SQLite is named here rather than left as an absence,
because the deletions are half of this change. The uncreatable and
unwritable directory cases go with the directory; the stranded-database
family (a file stamped at a revision the squash deleted) goes with the
file, because the only databases carrying those stamps are SQLite files
this build cannot open at all, so no Postgres database can reach the
arm. What replaces both is one refusal for an instance this server
cannot use, tested below.
"""

import re
import threading
from pathlib import Path

import psycopg
import pytest
from alembic.script import ScriptDirectory
from alembic.script.revision import ResolutionError
from alembic.util.exc import CommandError
from fastapi.testclient import TestClient
from sqlalchemy import inspect, text
from sqlalchemy.exc import DBAPIError, OperationalError, ProgrammingError

import vinga_server
from tests.support.configs import config_with_agent
from tests.support.leaks import chain, renderings
from vinga_server import db, serving
from vinga_server.app import StartupFailed, create_app
from vinga_server.class_names import UNNAMED_FAILURE, failure_name
from vinga_server.config import ConfigError
from vinga_server.config.loader import DatabaseBusyError, StorageError
from vinga_server.config.models import DatabaseConfig
from vinga_server.config.secrets import MASTER_KEY_ENV, generate_key
from vinga_server.conversations.store import CONVERSATIONS_CHAIN
from vinga_server.db import (
    DOMAIN_CHAIN,
    LOCK_TIMEOUT_MS,
    MIGRATION_FAILED,
    REVISION_ID_MAX,
    REVISION_ID_PATTERN,
    SCHEMA_NOT_PERMITTED,
    SUPERSEDED_REVISION,
    SUPERSEDED_REVISIONS,
    UNKNOWN_REVISION,
    UNREACHABLE,
    UNSHAPED_REVISION,
    StoreChain,
    advisory_key,
    connection_url,
    migration_failure,
    open_at,
    open_database,
)
from vinga_server.memory.store import MEMORY_CHAIN

EXPECTED_TABLES = {
    "providers",
    "mcp_servers",
    "prompt_fragments",
    "agent_defaults",
    "agents",
    "devices",
    "domain_settings",
}

# The body column on each entity table, which is where every non-key
# field of that entity lives (#243). A chain that did not create them
# fails here rather than at the first write on a deployment. The same
# set the installed-wheel check in CI holds, and the two move together.
EXPECTED_COLUMNS = {
    "providers": {"stage", "name", "body", "secrets"},
    "mcp_servers": {"name", "body", "secrets"},
    "prompt_fragments": {"name", "body"},
    "agent_defaults": {"id", "body"},
    "agents": {"name", "body"},
    # The one table with no body at all, and the one whose columns are
    # what #449 reshaped: the record's identity, the MAC a board
    # connects with, what an operator calls it, where it stands, and
    # the agents it reaches.
    "devices": {"id", "mac", "name", "location", "agents"},
}

# The head of the packaged domain chain, which is one revision. A new
# migration moves this line, deliberately.
HEAD = "3004_reach_replaces_egress"

SCHEMA = DOMAIN_CHAIN.schema


def _tables(engine) -> set[str]:
    return set(inspect(engine).get_table_names(schema=SCHEMA))


def _columns(engine, table: str) -> set[str]:
    return {column["name"] for column in inspect(engine).get_columns(table, schema=SCHEMA)}


def _version(engine) -> list[str]:
    with engine.connect() as connection:
        return [
            row[0]
            for row in connection.execute(text(f"select * from {SCHEMA}.alembic_version"))
        ]


def test_a_blank_database_gains_a_migrated_schema(blank_database: str) -> None:
    """From truly empty: no schemas, no stamps, nothing an init script
    put there, which is what a deployment that provisioned nothing has.

    The one case a migrated template cannot exercise, which is why this
    test asks for a database made from `template0` rather than for the
    worker's own.
    """
    engine = open_database(DatabaseConfig(name=blank_database))
    try:
        assert EXPECTED_TABLES <= _tables(engine)
        assert _version(engine) == [HEAD]
        for table, columns in EXPECTED_COLUMNS.items():
            assert _columns(engine, table) == columns
    finally:
        engine.dispose()


def test_the_connection_carries_the_lock_timeout() -> None:
    """What lets a CLI write land while the server holds the same
    database open, and what bounds the wait when it cannot."""
    engine = open_database(DatabaseConfig())
    try:
        with engine.connect() as connection:
            assert connection.execute(text("show lock_timeout")).scalar() == (
                f"{LOCK_TIMEOUT_MS // 1000}s"
            )
    finally:
        engine.dispose()


def test_an_already_migrated_schema_reopens(blank_database: str) -> None:
    settings = DatabaseConfig(name=blank_database)

    first = open_database(settings)
    version = _version(first)
    first.dispose()

    second = open_database(settings)
    try:
        assert EXPECTED_TABLES <= _tables(second)
        assert _version(second) == version
    finally:
        second.dispose()


def test_concurrent_openers_serialize_on_the_migration_lock(
    blank_database: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The first opener is held inside the migration after its
    transaction has taken the advisory lock; the second is started and
    must not reach the migration until the first commits. That pins the
    serialization property directly, rather than hoping the scheduler
    produces the race: the lock is taken before Alembic's version-table
    read, so the loser reads the schema the winner committed and finds
    it current instead of creating the same tables twice. Without the
    lock, the second opener enters the migration while the first still
    holds it, and the ordering assertion below fails."""
    from vinga_server import db as db_module

    settings = DatabaseConfig(name=blank_database)
    real_upgrade = db_module.command.upgrade
    first_inside = threading.Event()
    release_first = threading.Event()
    entered: list[int] = []
    entered_lock = threading.Lock()
    failures: list[BaseException] = []
    engines = []

    def gated_upgrade(config, revision) -> None:
        with entered_lock:
            ordinal = len(entered)
            entered.append(ordinal)
        if ordinal == 0:
            first_inside.set()
            assert release_first.wait(timeout=30), "the first opener was never released"
        real_upgrade(config, revision)

    monkeypatch.setattr(db_module.command, "upgrade", gated_upgrade)

    def opener() -> None:
        try:
            engines.append(open_database(settings))
        except BaseException as exc:  # noqa: BLE001 - reported, not swallowed
            failures.append(exc)

    first = threading.Thread(target=opener)
    first.start()
    assert first_inside.wait(timeout=30), "the first opener never reached the migration"

    second = threading.Thread(target=opener)
    second.start()
    # The second opener must park on the advisory lock, outside the
    # migration, for as long as the first holds it. The window is long
    # enough to catch an unserialized entry and far inside the lock
    # timeout, so a correctly parked opener neither enters nor fails.
    second.join(timeout=1.0)
    assert second.is_alive(), "the second opener finished while the first held the lock"
    with entered_lock:
        assert entered == [0], "the second opener entered the migration behind the lock"

    release_first.set()
    first.join(timeout=60)
    second.join(timeout=60)

    try:
        assert not first.is_alive() and not second.is_alive()
        assert not failures, failures
        assert len(engines) == 2
        assert len(entered) == 2
        for engine in engines:
            assert EXPECTED_TABLES <= _tables(engine)
            assert len(_version(engine)) == 1
    finally:
        for engine in engines:
            engine.dispose()


# The instance this server cannot use
#
# One refusal, with a fixed sentence, replacing the directory family
# (uncreatable, unwritable) and the stranded-file family (a database
# stamped at a revision the squash deleted). The first two were about a
# path; the third was advice to delete a file, and there is no file.


def test_an_unreachable_instance_refuses_with_the_fixed_sentence() -> None:
    """The boot refusal decision 7 of the issue asks for: a sentence,
    not a traceback, and one that names the variables to look at."""
    with pytest.raises(ConfigError) as caught:
        open_database(DatabaseConfig(port=1))

    assert str(caught.value) == UNREACHABLE
    assert isinstance(caught.value, StorageError)
    assert not isinstance(caught.value, DatabaseBusyError)


def test_a_database_that_is_not_there_refuses_the_same_way() -> None:
    """The other shape of unreachable, and deliberately the same
    sentence: a name that does not exist on a reachable instance is a
    connection this server cannot make, and the operator's next step is
    the same list of variables. Distinguishing the two would mean
    reporting what the driver said, and the driver quotes the DSN."""
    with pytest.raises(ConfigError) as caught:
        open_database(DatabaseConfig(name="vinga_no_such_database_at_all"))

    assert str(caught.value) == UNREACHABLE


@pytest.mark.parametrize(
    ("settings", "password"),
    [
        pytest.param(
            DatabaseConfig(host="vinga-no-such-host.invalid"),
            None,
            id="a-host-name-that-does-not-resolve",
        ),
        pytest.param(
            DatabaseConfig(user="vinga_no_such_role_at_all"),
            None,
            id="a-role-the-instance-does-not-have",
        ),
        pytest.param(DatabaseConfig(), "not-the-password-9e21b4", id="a-wrong-password"),
    ],
)
def test_every_other_connection_failure_is_the_same_sentence(
    monkeypatch: pytest.MonkeyPatch, settings: DatabaseConfig, password: str | None
) -> None:
    """The rest of what the connection sentence lists, each driven at a
    real instance: a host that is not there by name, and credentials it
    does not accept. Every one of them is a connection this server could
    not make, so each is told to check the five variables.

    `.invalid` is the top-level domain reserved never to resolve, so the
    name lookup fails at once rather than waiting on a resolver.
    """
    if password is not None:
        monkeypatch.setenv("VINGA_DB_PASSWORD", password)

    with pytest.raises(ConfigError) as caught:
        open_database(settings)

    assert str(caught.value) == UNREACHABLE
    assert isinstance(caught.value, StorageError)
    assert not isinstance(caught.value, DatabaseBusyError)

# What a failure with no answer of its own is told (#530)
#
# The connection sentence used to be the answer to everything the other
# arms did not claim, so a migration that failed on an instance that was
# up and accepting the credentials sent its operator to check the host,
# the port and the password. Now it is said for the failures it is true
# of, which the cases above pin, and everything else is told its
# exception's class and nothing more: the rule the configuration store
# already answers its own storage failures with.


def test_a_failure_with_no_answer_names_its_class(
    blank_database: str, tmp_path: Path
) -> None:
    """Driven for real, through the opener, at a reachable instance: a
    chain whose migrations are not where it says they are, which Alembic
    refuses with its own `CommandError` after the connection was made and
    the schema created.

    A failure no arm has a remedy for, and the shape of the one that
    motivated #530: the instance is fine, so the sentence that sends
    an operator to check it is the wrong one to say.
    """
    nowhere = StoreChain(
        schema="vinga_no_migrations_here",
        migrations=tmp_path / "missing",
        lock_key=advisory_key(0x530),
    )

    with pytest.raises(ConfigError) as caught:
        open_at(DatabaseConfig(name=blank_database), nowhere)

    assert str(caught.value) == MIGRATION_FAILED.format(failure="CommandError")
    assert str(caught.value) != UNREACHABLE
    assert isinstance(caught.value, StorageError)
    assert not isinstance(caught.value, DatabaseBusyError)
    assert str(tmp_path) not in str(caught.value)


def test_an_answer_from_a_server_that_was_reached_is_not_the_connection() -> None:
    """The boundary `_unreachable` draws by exact type, at its nearest
    neighbour. psycopg files every SQLSTATE in class 53 and class 57
    under `OperationalError`, the same class it raises when libpq could
    not connect at all, so a classifier that asked `isinstance` would
    tell an instance with a full disk to check that it is running.

    Constructed, because a full disk is not something a lane can arrange.
    """
    answered = psycopg.errors.DiskFull("could not extend file")
    problem = migration_failure(OperationalError("create table", {}, answered))

    assert str(problem) == MIGRATION_FAILED.format(failure="OperationalError")
    assert str(problem) != UNREACHABLE


def test_a_connect_that_timed_out_is_the_connection_sentence() -> None:
    """The one subclass the connection sentence does claim: psycopg's own
    `ConnectionTimeout`, raised when a connect outlasts its timeout,
    which is a host that did not answer rather than one that refused.

    Constructed, because a real one waits out the timeout it is named
    for.
    """
    timed_out = psycopg.errors.ConnectionTimeout("connection timeout expired")
    problem = migration_failure(OperationalError(None, None, timed_out))

    assert str(problem) == UNREACHABLE


def test_a_class_name_that_is_not_an_identifier_is_not_repeated() -> None:
    """A class can be named anything, a line break and a sentence after
    it included, and an operator's terminal would print that second line
    as if this server had said it. The name goes through `ClassName`,
    which admits an identifier and nothing else, and what it refuses is
    replaced by a fixed phrase rather than dropped or raised."""
    forged = type("Forged\nthe database was dropped", (Exception,), {})

    problem = migration_failure(forged("sk-test-5f02c1-never-a-real-credential"))

    assert str(problem) == MIGRATION_FAILED.format(failure=UNNAMED_FAILURE)
    assert "\n" not in str(problem)
    assert "dropped" not in str(problem)
    assert failure_name(forged()) == UNNAMED_FAILURE
    assert failure_name(ValueError()) == "ValueError"


# A revision this install does not carry (#530)
#
# The failure that motivated the change: an install built from a stale
# cache, missing a migration its own source has, met a database a fuller
# build had already stamped, and was told to check that the instance was
# running. Alembic's answer is a `ResolutionError` under a
# `CommandError`, and now it has an arm of its own that points at the
# install and names the revision, which is read out of the database and
# so is repeated only when it is shaped like a revision this project
# writes.


def _stamped_at(database: str, revision: str) -> None:
    """A migrated domain schema whose stamp has been moved to a revision
    this install does not carry, which is exactly the state a newer
    build or a fuller install leaves behind."""
    engine = open_database(DatabaseConfig(name=database))
    try:
        with engine.begin() as connection:
            connection.execute(
                text(f"update {SCHEMA}.alembic_version set version_num = :stamp"),
                {"stamp": revision},
            )
    finally:
        engine.dispose()


def test_a_revision_this_install_lacks_points_at_the_install(blank_database: str) -> None:
    """Driven for real: the stamp is read back by Alembic, which cannot
    resolve it against the packaged scripts. The sentence names the
    revision so an operator can see which side has it, and it is neither
    the connection sentence, since the instance answered throughout, nor
    the reset, since the database is fine."""
    _stamped_at(blank_database, "9999_from_a_newer_build")

    with pytest.raises(ConfigError) as caught:
        open_database(DatabaseConfig(name=blank_database))

    said = str(caught.value)
    assert said == UNKNOWN_REVISION.format(stamp="revision 9999_from_a_newer_build")
    assert said != UNREACHABLE
    assert said != SUPERSEDED_REVISION
    assert "Do not drop or reset the database" in said
    assert isinstance(caught.value, StorageError)
    assert caught.value.__cause__ is None
    assert caught.value.__context__ is None


@pytest.mark.parametrize(
    "stored",
    [
        pytest.param("sk-test-61b0e2-never-a-real-cred", id="a-credential-pasted-in"),
        pytest.param("1010_turns\nthe database is fine", id="a-forged-second-line"),
        pytest.param("1010_Turns_Name_Their_Utterance", id="not-this-projects-case"),
        pytest.param("10", id="a-bare-prefix"),
    ],
)
def test_a_stamp_not_shaped_like_a_revision_is_not_repeated(
    blank_database: str, stored: str
) -> None:
    """The stamp is stored data, read out of a table anyone with the
    server role's grants can write, so what reaches an operator's
    terminal is decided by its shape and not by where it came from. Each
    of these is something the column holds and the pattern refuses."""
    _stamped_at(blank_database, stored)

    with pytest.raises(ConfigError) as caught:
        open_database(DatabaseConfig(name=blank_database))

    said = str(caught.value)
    assert said == UNKNOWN_REVISION.format(stamp=UNSHAPED_REVISION)
    assert stored not in chain(caught.value)


def test_a_stamp_longer_than_the_column_is_not_repeated() -> None:
    """The length bound, which a lane cannot store its way past (the
    column Alembic made is `REVISION_ID_MAX` wide), so the failure is
    built the way Alembic builds it."""
    overlong = "1010_" + "a" * REVISION_ID_MAX
    unresolved = ResolutionError(f"No such revision or branch '{overlong}'", overlong)
    failure = CommandError(f"Can't locate revision identified by '{overlong}'")
    failure.__cause__ = unresolved

    problem = migration_failure(failure)

    assert str(problem) == UNKNOWN_REVISION.format(stamp=UNSHAPED_REVISION)
    assert overlong not in str(problem)


def test_a_resolution_failure_further_down_the_chain_is_still_found() -> None:
    """By type wherever it sits on the cause chain, not only as the first
    link, because which library wrapped Alembic's error on the way out is
    not something this classification should depend on. Today Alembic
    raises the `CommandError` directly from the `ResolutionError`; this
    is the case where something has wrapped it once more."""
    unresolved = ResolutionError("No such revision or branch", "9999_further_down")
    between = RuntimeError("wrapped on the way out")
    between.__cause__ = unresolved
    failure = CommandError("Can't locate revision")
    failure.__cause__ = between

    problem = migration_failure(failure)

    assert str(problem) == UNKNOWN_REVISION.format(stamp="revision 9999_further_down")


def test_every_committed_revision_has_the_shape_the_sentence_admits() -> None:
    """The pattern and the migrations are two structures that must
    agree, so the second is read off the first's subject: every revision
    of every chain, as Alembic itself lists them. A migration named some
    other way would be left out of the unknown-revision sentence the
    day an install lacked it, which is the day the name is wanted."""
    revisions = [
        script.revision
        for store in (DOMAIN_CHAIN, CONVERSATIONS_CHAIN, MEMORY_CHAIN)
        for script in ScriptDirectory(str(store.migrations)).walk_revisions()
    ]

    assert revisions
    for revision in [*revisions, *SUPERSEDED_REVISIONS]:
        assert len(revision) <= REVISION_ID_MAX, revision
        assert re.fullmatch(REVISION_ID_PATTERN, revision), revision


# The sentinel, at both doors a migration failure leaves through
#
# A credential-shaped value planted everywhere a real failure keeps one:
# in the DSN a driver error quotes, in the statement and the parameters
# bound to it, and on the exception's `__cause__`. What has to hold is
# that none of it reaches the refusal, its arguments, anything walking
# its chain, or a log record in either format, while the class name
# does reach the sentence. The boot opens the domain chain and prints
# its refusal; the lifespan opens the memory chain and hands uvicorn a
# `StartupFailed`. They are separate `except` clauses on the way out, so
# each is driven.

PLANTED = "sk-test-7c4d93-never-a-real-credential"


def _a_failure_holding_the_sentinel() -> ProgrammingError:
    dsn = f"postgresql+psycopg://vinga:{PLANTED}@db.internal:5432/vinga"
    driver = psycopg.errors.InsufficientPrivilege(f"permission denied, connected as {dsn}")
    failure = ProgrammingError(
        f"INSERT INTO domain.providers (secrets) VALUES ('{PLANTED}')",
        {"secrets": PLANTED},
        driver,
    )
    failure.__cause__ = RuntimeError(f"while migrating over {dsn}")
    return failure


def _failing_at(monkeypatch: pytest.MonkeyPatch, chain: StoreChain) -> None:
    """Every chain migrates as it always does except the one named,
    whose migration raises the planted failure from where a real one
    would: inside the opener's own `try`."""
    real = db.upgrade_to_head

    def upgrade(engine: object, which: StoreChain) -> None:
        if which is chain:
            raise _a_failure_holding_the_sentinel()
        real(engine, which)  # type: ignore[arg-type]

    monkeypatch.setattr(db, "upgrade_to_head", upgrade)


def test_the_boot_refusal_carries_the_class_and_nothing_planted(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    caplog: pytest.LogCaptureFixture,
) -> None:
    monkeypatch.delenv("VINGA_CONFIG", raising=False)
    monkeypatch.setenv(MASTER_KEY_ENV, generate_key())
    _failing_at(monkeypatch, DOMAIN_CHAIN)

    with caplog.at_level(0):
        assert serving.run(None) == 1

    printed = capsys.readouterr()
    assert MIGRATION_FAILED.format(failure="ProgrammingError") in printed.err
    assert PLANTED not in printed.err
    assert PLANTED not in printed.out
    assert not [found for found in renderings(caplog) if PLANTED in found]


def test_the_lifespan_refusal_carries_the_class_and_nothing_planted(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    _failing_at(monkeypatch, MEMORY_CHAIN)

    with caplog.at_level(0), pytest.raises(StartupFailed) as raised:
        with TestClient(create_app(config_with_agent())):
            pass

    refusal = raised.value
    assert str(refusal) == MIGRATION_FAILED.format(failure="ProgrammingError")
    assert PLANTED not in chain(refusal)
    assert refusal.__cause__ is None
    assert refusal.__context__ is None
    assert not [found for found in renderings(caplog) if PLANTED in found]


def test_the_refusal_itself_carries_nothing_planted() -> None:
    """The exception the opener raises, before any door renders it: its
    text, its arguments both ways and everything a walker of its graph
    would find."""
    problem = migration_failure(_a_failure_holding_the_sentinel())

    assert str(problem) == MIGRATION_FAILED.format(failure="ProgrammingError")
    assert PLANTED not in chain(problem)
    assert problem.__cause__ is None
    assert problem.__context__ is None


# A schema the role may not create
#
# The one migration failure whose answer is a command rather than a
# connection to check, and the shape an existing least-privilege
# deployment meets a release that adds a schema in (#314). The sentence
# is raised at the `CREATE SCHEMA` in `upgrade_to_head` and nowhere
# else, so both real paths are driven in the integration lane, where a
# restricted role and the committed provisioning file exist: a missing
# schema the role may not create, answered with the rerun, and a schema
# standing under the wrong owner, answered with the general sentence.
#
# What is pinned here is the half that lane cannot show, which is what
# `migration_failure` does NOT do. A classifier that reached for the
# exception class would answer the rerun for every privilege failure a
# migration can meet, and most of them are failures the rerun cannot
# fix: its creates are `IF NOT EXISTS`, so a wrongly owned schema stays
# wrongly owned and a missing table grant stays missing.


def test_a_privilege_failure_inside_a_migration_prescribes_nothing() -> None:
    """`InsufficientPrivilege` reaching the general classifier is an
    instance this server cannot use as configured, and not the rerun.

    Constructed rather than provoked, because what this pins is an
    absence: whatever a migration was refused, the answer is the
    sentence that prescribes nothing unless the refused statement was
    the schema creation itself, and that decision is made at the
    statement rather than here.
    """
    refused = psycopg.errors.InsufficientPrivilege(
        "permission denied for table sk-test-9e21b4-never-a-real-credential"
    )
    problem = migration_failure(DBAPIError("create table", {}, refused))

    # The general sentence, naming the class it was handed. It was the
    # connection sentence until #530, which told an operator whose
    # instance had answered to go and check that it was there.
    assert str(problem) == MIGRATION_FAILED.format(failure="DBAPIError")
    assert str(problem) != UNREACHABLE
    assert str(problem) != SCHEMA_NOT_PERMITTED
    assert "deploy/postgres-init.sql" not in str(problem)
    assert isinstance(problem, StorageError)
    assert not isinstance(problem, DatabaseBusyError)


def test_the_refused_privilege_repeats_nothing_the_driver_said() -> None:
    """A psycopg error quotes what it was asked about, and a refusal is
    printed to an operator's terminal and into whatever captured it."""
    planted = "sk-test-9e21b4-never-a-real-credential"
    refused = psycopg.errors.InsufficientPrivilege(f"permission denied for {planted}")
    problem = migration_failure(DBAPIError("create table", {"p": planted}, refused))

    assert planted not in str(problem)
    assert planted not in repr(problem.args)
    assert problem.__cause__ is None
    assert problem.__context__ is None


def test_the_rerun_sentence_names_the_file_and_no_value() -> None:
    """The remedy is the only thing the sentence carries, and the file
    it names is a path in this repository rather than anything read off
    a connection or a configuration."""
    assert "deploy/postgres-init.sql" in SCHEMA_NOT_PERMITTED
    assert "VINGA_DB" not in SCHEMA_NOT_PERMITTED


@pytest.mark.parametrize(
    "planted",
    [
        "sk-test-2b7e11-never-a-real-credential",
        "hunter2",
    ],
)
def test_no_refusal_repeats_the_password(
    monkeypatch: pytest.MonkeyPatch, planted: str
) -> None:
    """The sentinel, in its simplest form: a credential-shaped password
    in the environment, an open that cannot succeed, and nothing of it
    anywhere on the way out.

    The whole chain, not only the message: psycopg quotes the DSN it
    tried in its own error, and `from exc` would leave that reachable
    from the refusal that travels.
    """
    monkeypatch.setenv("VINGA_DB_PASSWORD", planted)

    with pytest.raises(ConfigError) as caught:
        open_database(DatabaseConfig(port=1))

    problem = caught.value
    assert planted not in str(problem)
    assert planted not in repr(problem.args)
    assert problem.__cause__ is None
    assert problem.__context__ is None


def test_the_baseline_builds_exactly_what_the_tables_declare() -> None:
    """The chain and `db/schema.py` agree, asked of the whole shape
    rather than of a list somebody remembered to update.

    This is the gate the squash removed. The chain is one file with no
    successor, so a column added to `schema.py` without a migration used
    to be invisible: the tables all exist, the body columns are all
    there, the head is still one revision, and the first write on a
    deployment fails on a column that was never created. Nothing else
    here pins column types, nullability, the primary keys or the
    singleton check constraint either.

    `compare_metadata` is the same comparison `alembic revision
    --autogenerate` makes, which the plan makes the sanctioned way to
    earn a column back, so this asks the migration machinery whether it
    would have anything to write. An empty answer is the whole
    assertion: if it is not empty, the difference it reports is the
    migration that is missing.

    Schema-qualified, and that part is not decoration: without the name
    filter the comparison would see the conversation store's tables in
    the same database and propose dropping them.
    """
    from alembic.autogenerate import compare_metadata
    from alembic.migration import MigrationContext

    from vinga_server.db import schema

    engine = open_database(DatabaseConfig())
    try:
        with engine.connect() as connection:
            context = MigrationContext.configure(
                connection,
                opts={
                    "include_schemas": True,
                    "version_table_schema": SCHEMA,
                    "include_name": lambda name, type_, parents: (
                        type_ != "schema" or name == SCHEMA
                    ),
                },
            )
            difference = compare_metadata(context, schema.metadata)
    finally:
        engine.dispose()

    assert difference == []


def test_the_migrations_ship_inside_the_package() -> None:
    """Discovery from an installed wheel is proved in CI, which installs
    one and migrates from it. This is the cheap half: the scripts are
    inside the package directory hatchling builds, not beside it."""
    from pathlib import Path

    package = Path(vinga_server.__file__).resolve().parent
    migrations = package / "db" / "migrations"

    assert (migrations / "env.py").is_file()
    assert list((migrations / "versions").glob("*.py"))


# The URL override, and what it will not accept
#
# `VINGA_DB_URL` replaces all five discrete facts when it is set, which
# is what a deployment with a connection string in a secret manager
# needs. It is constrained rather than trusted: accepting any SQLAlchemy
# URL would admit `sqlite://` and psycopg2's `postgresql://` dialect,
# and "there is no second storage backend" would be documentation
# rather than a property of the code.


def test_the_url_override_wins_over_the_discrete_values(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv(
        "VINGA_DB_URL", "postgresql+psycopg://someone:pw@elsewhere:6543/other"
    )

    url = connection_url(DatabaseConfig())

    assert url.host == "elsewhere"
    assert url.port == 6543
    assert url.database == "other"


def test_a_bare_postgresql_url_is_normalized_to_psycopg(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """`postgresql://` alone selects psycopg2, which is not installed and
    is not the driver this project chose. It is what Postgres itself
    documents, so it is accepted and normalized rather than refused."""
    monkeypatch.setenv("VINGA_DB_URL", "postgresql://someone:pw@elsewhere:6543/other")

    assert connection_url(DatabaseConfig()).drivername == "postgresql+psycopg"


@pytest.mark.parametrize(
    "url",
    [
        "sqlite:///vinga.db",
        "mysql+pymysql://someone:pw@elsewhere/vinga",
        "postgresql+psycopg2://someone:pw@elsewhere/vinga",
        "not a url at all",
        "",
    ],
)
def test_a_url_that_is_not_this_backend_is_refused(
    monkeypatch: pytest.MonkeyPatch, url: str
) -> None:
    """Every other scheme, and an unparseable string, one by one.

    The empty string is the one that is not a refusal: an unset-shaped
    value falls through to the discrete settings, which is what an
    operator who cleared the variable meant.
    """
    monkeypatch.setenv("VINGA_DB_URL", url)

    if url == "":
        assert connection_url(DatabaseConfig()).host == "127.0.0.1"
        return

    with pytest.raises(ConfigError) as caught:
        connection_url(DatabaseConfig())

    assert "postgresql" in str(caught.value)


@pytest.mark.parametrize(
    "url",
    [
        "sqlite:///sk-test-4a9c02-never-a-real-credential.db",
        "mysql://someone:sk-test-4a9c02-never-a-real-credential@host/vinga",
        "postgresql+psycopg2://u:p@h/db?sslpassword=sk-test-4a9c02-never-a-real-credential",
        "://sk-test-4a9c02-never-a-real-credential",
    ],
)
def test_a_refused_url_is_never_quoted_back(
    monkeypatch: pytest.MonkeyPatch, url: str
) -> None:
    """The three places a URL can carry a credential: its authority, its
    query parameters, and a value somebody pasted into the wrong
    variable entirely.

    A password-hidden rendering would cover only the first, which is why
    the refusal is fixed rather than rendered at all. The parse failure
    is included because SQLAlchemy's own message quotes the string it
    could not parse.
    """
    monkeypatch.setenv("VINGA_DB_URL", url)
    planted = "sk-test-4a9c02-never-a-real-credential"

    with pytest.raises(ConfigError) as caught:
        connection_url(DatabaseConfig())

    problem = caught.value
    assert planted not in str(problem)
    assert planted not in repr(problem.args)
    assert problem.__cause__ is None
    assert problem.__context__ is None
