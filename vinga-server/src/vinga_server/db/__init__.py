"""The Postgres database holding everything this server stores.

Opening it is one call. `open_database` builds an engine from the
connection settings, creates the schema its chain lives in when it is
missing, and brings that chain up to date with the Alembic migrations
packaged beside this module. A blank database migrates to current in one
step, so there is no init command to forget.

It deliberately does no more than that. Verifying that every stored
ciphertext decrypts under the configured keys is a server-startup check
(`verify_secrets`), kept out of here for two reasons. Opening a database
is not judging what is in it: whether a configuration may be served is a
policy about starting, so it is decided once where a start is decided.
And an opener that refused would fail worse than the boot does. A boot
refuses naming the entity and the slot; a database that would not open
is one nothing can migrate, read or repair through this server at all.

There are three stores and one database. What keeps them apart is a
schema each, which is also where each Alembic chain keeps its own
version table and what the read-only analyst role is scoped to (it
reads the conversation record and neither of the others). A
`StoreChain` is the whole of what a store tells this module about
itself: which schema it owns, where its migrations are, and which
advisory-lock key serializes its writers. The domain chain is declared
below, beside the opener that takes it; the conversations and memory
chains are declared beside their own stores, because a chain is a fact
of the store that owns it.

Three properties every caller gets and none of them states:

- **Writers to one store serialize whole.** The write engine's begin
  listener takes the chain's transaction-scoped advisory lock before
  anything is read, so validation and the persist that follows it
  happen under one lock and two writers cannot each validate against
  the state before the other's change and then write over one another.
  A migration takes the same lock before Alembic reads the version
  table, which is how two starting processes settle a baseline race.
- **A transaction that writes two stores takes both locks in
  ascending key order.** A thread's erasure deletes its turns and its
  memory in one transaction, so it holds the record chain's key and
  then the memory chain's, in that order and never the reverse
  (`advisory_key` states the rule, `take_the_chain_lock` is how the
  second one is taken). Two transactions that agree on an order queue;
  two that disagree deadlock.
- **Every connection's lock wait is bounded.** `lock_timeout` is a
  connection parameter, set on the startup options rather than by a
  statement, so it survives the rollback a pooled connection is
  returned with. A lock that does not arrive inside it fails with
  `LockNotAvailable`, which this module classifies as retryable, which
  is what makes a contended write a 409 with a sentence rather than a
  wait with no end.
- **Nothing about the connection is ever quoted back.** The refusals
  below are fixed strings, and the one that says anything about its
  cause says the exception's class name, validated as an identifier,
  and nothing else. A driver's own connection failure quotes the
  DSN it tried, a URL can carry a password in its authority and in its
  query (`sslpassword`), and the discrete values are no better, so
  none of the four travel: not in a message, not in `args`, and not on
  a cause chain, which is why every raise here is built inside its
  handler and raised outside it.
"""

import os
import re
from dataclasses import dataclass
from pathlib import Path

import psycopg
from alembic import command
from alembic.config import Config as AlembicConfig
from alembic.script.revision import ResolutionError
from alembic.util.exc import CommandError
from sqlalchemy import URL, Engine, create_engine, event, make_url, text

from vinga_server.class_names import failure_name
from vinga_server.config.loader import ConfigError, DatabaseBusyError, StorageError
from vinga_server.config.models import (
    DATABASE_ENV_NAMES,
    DATABASE_PASSWORD_ENV,
    DATABASE_URL_ENV,
    DatabaseConfig,
)
from vinga_server.db import schema

# How long a connection waits for another one's lock before it gives up.
# A CLI write while the server holds the advisory lock is the case this
# exists for; two processes migrating a fresh database wait on each
# other here too, rather than racing the baseline.
#
# Per lock acquisition, which is what Postgres applies it to, and not a
# bound on a transaction or on a response: a transaction that waits this
# long on the advisory gate can wait again on a later lock, and its
# execution time was never bounded under any backend. The gate is the
# acquisition that matters, because every writer takes it first.
LOCK_TIMEOUT_MS = 10_000

# The environment the connection is read from. Four of the five names
# have a YAML key beside them (`DatabaseConfig`); the password has none
# at all, because a password in a config file is what the
# no-secrets-in-YAML stance exists to prevent, and the URL has none
# because it is the whole of the five at once.
#
# Declared beside that model with the other four rather than here, since
# the generated server reference publishes all six and a page that
# restated them would keep rendering across a rename. These are the
# names this module's own callers already read them under, so the two
# spellings are one string each.
URL_ENV = DATABASE_URL_ENV
PASSWORD_ENV = DATABASE_PASSWORD_ENV

# What a development machine gets when it says nothing, matching the
# compose file's own default so the zero-configuration loop is
# `docker compose up -d --wait` and nothing else. A convenience on an
# instance bound to loopback, which the deployment docs say plainly.
DEFAULT_PASSWORD = "vinga"

# The one dialect this server speaks, and the schemes a URL may name it
# with. `postgresql` alone selects psycopg2, which is not installed and
# is not the driver this project chose, so it is accepted and normalized
# rather than refused: what an operator writes is the scheme Postgres
# itself documents.
DIALECT = "postgresql+psycopg"
ACCEPTED_SCHEMES = frozenset({"postgresql", DIALECT})

# The refusals. Fixed and value-free, every one of them, for the reason
# the module docstring gives: what would be quoted back is a connection
# string, and a connection string is where a password lives. The one
# exception is `MIGRATION_FAILED` below, which carries a class name and
# says why that is not a value from the connection.
URL_REFUSED = (
    f"{URL_ENV} does not name a Postgres database. It has to be a postgresql:// or "
    f"postgresql+psycopg:// URL and nothing else: this server keeps both halves of "
    f"its state in Postgres and carries no other driver. Neither the value nor any "
    f"part of it is quoted back, because a database URL carries a password in its "
    f"authority and can carry another in its query"
)

# The five names are the ones `DatabaseConfig` declares rather than five
# more literals: this sentence is what an operator reads when nothing
# opens, so a name it spells wrong is a name they would go and set.
#
# Raised for a connection that could not be made or did not survive,
# and for nothing else (`_unreachable` decides which those are). It was
# once the answer to every migration failure no other arm claimed, and
# so it sent operators to check a host, a port and a password on
# instances that were up and accepting them (#530).
UNREACHABLE = (
    f"cannot open the vinga database. Nothing of the connection is repeated here, "
    f"because a database URL carries credentials in its authority and in its query: "
    f"check that the instance {DATABASE_ENV_NAMES['host']} and "
    f"{DATABASE_ENV_NAMES['port']} name is running and "
    f"reachable, that {DATABASE_ENV_NAMES['name']} exists on it, and that "
    f"{DATABASE_ENV_NAMES['user']} and "
    f"{PASSWORD_ENV} are the credentials it expects. Set {URL_ENV} to override "
    f"all five at once. The development instance starts with "
    f"`docker compose up -d --wait`"
)

# What a boot that may not create a schema it is missing is told, and
# the whole of the upgrade choreography a release that adds one asks
# for.
#
# `deploy/postgres-init.sql` runs when a data directory initializes, and
# it deliberately leaves the server role without `CREATE` on the
# database, so an existing least-privilege deployment meeting a release
# that adds a schema cannot make it for itself. The remedy is the rerun
# the recovery documentation already carries, and the file is repeatable
# by construction, so the sentence names it and nothing else.
#
# It answers exactly one statement, and that narrowness is the whole of
# what makes it true. The rerun creates schemas that are missing and
# does nothing else: its creates are `IF NOT EXISTS`, so a schema that
# is there under the wrong owner is not fixed by running it again, and
# neither is a table-level grant a later migration wanted. Those are
# real failures with different answers, and telling their operator to
# run a file that will change nothing would be worse than the general
# sentence, which at least does not prescribe. So this is raised at the
# `CREATE SCHEMA` in `upgrade_to_head` rather than classified out of
# whatever a migration happened to fail on.
#
# Fixed and value-free like every other refusal here. The schema that
# was missing is not quoted back: it is this module's own constant
# rather than anything a caller reaches, and naming it would put a
# second thing in a sentence whose whole answer is one command. The
# connection is not repeated for the reason the sentences around it
# give.
SCHEMA_NOT_PERMITTED = (
    "the vinga database is missing a schema this server owns, and the role it "
    "connects as may not create one, which is the least-privilege contract working "
    "as intended. Rerun deploy/postgres-init.sql administratively against this "
    "database before starting this image: it creates every schema the server owns "
    "with AUTHORIZATION to the server role, every statement in it is written to be "
    "run again, and nothing already stored is touched. Nothing of the connection is "
    "repeated here, because a database URL carries credentials in its authority and "
    "can carry another in its query"
)

MIGRATION_BUSY = (
    "the vinga database is busy: another connection held a lock this migration needs "
    "for longer than the lock timeout allows. Nothing was changed; start again. A "
    "reader inside a long transaction is what blocks a migration, because the schema "
    "changes it makes need a lock that reads hold off"
)

# What every migration failure without an answer of its own is told,
# which is what the connection sentence above used to be told about all
# of them (#530).
#
# The exception's class name and nothing else from the failure, which
# is the rule the configuration store's own storage refusal already
# keeps (`config/store.py`): a type name says what went wrong, and the
# text beside it is the driver's, which can quote the DSN it connected
# on, the statement it ran and the values bound to that statement. The
# name is rendered through `class_names.failure_name`, so a class
# whose name is not an identifier cannot write a second line into an
# operator's terminal.
#
# It prescribes nothing, on purpose. What reaches it is a privilege a
# migration was refused somewhere other than the schema creation, a
# migration script that failed, or an error a server sent back on a
# connection that worked: none of them has one remedy, and a sentence
# that guessed one would send somebody to fix the wrong thing, which is
# what the connection sentence did for every one of them.
MIGRATION_FAILED = (
    "the vinga database could not be brought up to the schema this server runs "
    "on ({failure}), and the failure is not one this server has an answer for. "
    "Only the exception's class name is repeated here: the failure's own text can "
    "quote the connection it was made on and the statement it was running, with "
    "the values bound to it"
)

# The revisions a re-cut deleted, named one by one because the set is
# closed and can never grow: it is the list of what one decision
# removed, and no later change adds to it. Today that is the single
# conversations baseline the thread schema replaced (#190), which is
# the second time this project has spent the priced exit its
# compatibility floor grants.
#
# A closed set rather than "any revision this build cannot find", and
# the difference is the whole of the arm below. Two databases produce
# the same Alembic failure and want opposite advice: one written before
# the re-cut, which cannot be upgraded and has to be replaced, and one
# written by a NEWER build and then met by an older image, which is
# current and must not be touched. Nothing in an unknown revision id
# says which it is; membership here does.
SUPERSEDED_REVISIONS = frozenset({"1001_postgres_conversations"})

# What a database still stamped at one of those is told, and the whole
# of the operator-facing surface of "unsupported". Fixed and value-free
# like every other refusal here: the revision it was stamped at is not
# quoted back, because the set above is what it was matched against and
# naming the member would add nothing the sentence needs, and the
# connection is not repeated for the reason the sentences above give.
#
# The remedy is the only thing worth saying, because there is no other:
# there is no export format for the conversation record and no importer,
# so the reset is the path, and it is the one the ADR addendum records
# and the one this repository tests.
SUPERSEDED_REVISION = (
    "the record schema of the vinga database is stamped at the revision the "
    "thread schema replaced, and it cannot be upgraded in place: turns recorded "
    "before conversations existed name no conversation, and there is nothing to "
    "derive one from. Drop and recreate the database, or the record schema "
    "on its own, rerun deploy/postgres-init.sql, and start the server again, which "
    "migrates a blank schema to current in one step. The conversation record is "
    "not carried across, which the changelog announces and "
    "docs/adr/2026-08-20-database-upgrades-have-a-compatibility-floor.md records "
    "with what it costs"
)

# The shape of every revision id this project commits: four digits that
# number the chain and the revision's place in it, then the migration's
# name in lower snake case (`1010_turns_name_their_utterance`). At most
# `REVISION_ID_MAX` characters, which is the width of the `version_num`
# column Alembic creates. A test holds every committed revision to both,
# so a migration named some other way fails a lane rather than being
# quietly left out of the sentence below.
REVISION_ID_PATTERN = r"[0-9]{4}(?:_[a-z0-9]+)+"
REVISION_ID_MAX = 32
_REVISION_ID = re.compile(rf"\A(?:{REVISION_ID_PATTERN})\Z")

# What a database stamped at a revision this install does not carry is
# told, when that revision is not one a re-cut deleted (#530). The
# motivating case is an install built from a stale cache, missing a
# migration its own source has, which met a database a fuller build had
# already stamped and was told to check that the instance was running.
#
# It points at the install, because that is where the fault is in both
# of the ways a database gets here: a newer build stamped it and an
# older one is opening it, which the closed set above exists to keep
# from being told to reset anything, or this install lacks a migration
# its own release ships. Neither is fixed by touching the database, so
# the sentence says so in as many words.
#
# It names the revision, which is the one fact that tells the two cases
# apart from the outside: an operator can see whether the id is one
# their source tree has. The id comes from the DATABASE, being the
# stored stamp Alembic could not resolve (`ResolutionError.argument`),
# so it is stored data rather than this install's own constant, and it
# is repeated only when it has the shape `REVISION_ID_PATTERN` states.
# Anything else, a line break, a credential pasted into the wrong
# table, a value longer than the column Alembic made, is replaced by
# `UNSHAPED_REVISION`. The shape admits lowercase words and digits and
# nothing else, which is a filename's worth of text: it cannot forge a
# line, and it is no more than this project's own migrations are named.
UNKNOWN_REVISION = (
    "the vinga database is stamped at {stamp}, and none of the migrations this "
    "install carries is that revision. The fault is in the install rather than in "
    "the database, and nothing stored needs to change: either a newer build of this "
    "server migrated the database and an older one is now opening it, in which case "
    "run the newer build again, or this install is stale or partial and is missing "
    "a migration its own release ships, in which case rebuild or reinstall it from "
    "a clean state. Do not drop or reset the database for this"
)

# What `UNKNOWN_REVISION` names in place of a stored stamp that is not
# shaped like a revision this project writes.
UNSHAPED_REVISION = (
    "a revision that is not repeated here, because the stored value does not have "
    "the shape of one this project writes"
)

# The advisory-lock keys, one per chain, carrying a namespace rather
# than being 1 and 2. Advisory locks share one 64-bit space with every
# other application on the instance, and an instance a deployment shares
# is exactly the case where a bare small integer collides with somebody
# else's.
_LOCK_NAMESPACE = 0x76_69_6E_67  # "ving"


def advisory_key(chain: int) -> int:
    """One chain's key in this application's half of the lock space.

    Public because the other chain is declared beside the other store
    and needs a key from the same space: two stores picking their own
    numbers is how two chains come to share one.

    The numbers are also an order, and that is the second thing this
    function decides. A transaction that writes two stores takes both
    chains' locks, and the rule is that it takes them in ASCENDING key
    order: the record chain's (2) before the memory chain's (3), never
    the other way round. Two transactions taking the same two locks in
    the same order can only queue; taking them in opposite orders is a
    deadlock the database resolves by killing one of them. That is what
    keeps the no-deadlock property above true now that a thread's
    erasure deletes the thread's memory in the same transaction as its
    turns.
    """
    return (_LOCK_NAMESPACE << 32) | chain


@dataclass(frozen=True)
class StoreChain:
    """One store's schema, its migrations, and the key its writers
    serialize on.

    Declared beside the opener that takes it rather than in a module of
    its own: it is the opener's parameter list, grouped so that the
    three facts travel together and cannot be handed in mismatched. Each
    concrete chain is declared beside its own store, because which
    schema a store lives in is a fact of that store.

    `schema` is the whole of what the chain owns: the tables, and the
    `alembic_version` table Alembic keeps inside it, which is what makes
    two chains in one database two chains rather than one with two heads.
    """

    schema: str
    migrations: Path
    lock_key: int


# The schema name is read off the metadata that declares it rather than
# written again here: which schema the domain tables are in is a fact,
# and `db/schema.py` is its home.
DOMAIN_CHAIN = StoreChain(
    schema=schema.SCHEMA,
    migrations=Path(__file__).resolve().parent / "migrations",
    lock_key=advisory_key(1),
)


def open_database(settings: DatabaseConfig) -> Engine:
    """Open and migrate the domain half's schema.

    Returns an engine the caller owns and disposes. Every failure is a
    `ConfigError` carrying one of the sentences above, chosen by
    `migration_failure` from the type of what was raised: point the
    `VINGA_DB_*` variables at a reachable instance, try again, or the
    one fact about the failure that is safe to repeat, its class name.

    Which `ConfigError` matters to the callers that open at startup:
    boot, the CLI per command, and the lifespan that owns the
    configuration API's engine. A lock another writer is holding is met
    here rather than inside a repository write, and must still be the
    retryable refusal, because that is what makes a contended database a
    startup that refused with a sentence; an instance the server cannot
    reach is the server's problem wherever it is found.
    """
    return open_at(settings, DOMAIN_CHAIN)


def open_at(settings: DatabaseConfig, chain: StoreChain) -> Engine:
    """`open_database` for a chain named by its caller: build the
    engine, create the schema if it is not there, run the chain to head.

    The chain is an argument rather than derived from anything here
    because the two stores keep their migrations beside their own
    packages, and their version tables are separate by virtue of living
    in separate schemas rather than by any naming trick.
    """
    return open_url(connection_url(settings), chain)


def open_url(url: URL, chain: StoreChain) -> Engine:
    """`open_at` for a caller that has already resolved its connection.

    The distinction is not decoration, and the bug that produced it says
    why. The autogeneration entry point made a scratch database from the
    discrete settings and then opened it with `open_at`, which resolves
    the connection AGAIN, and `VINGA_DB_URL` wins that resolution whole.
    So on a machine with an exported production URL, the command created
    a scratch database on the local instance and ran the migration and
    the comparison against production.

    A URL passed in is a connection nothing ambient can replace between
    the moment it is decided and the moment it is used, which is what a
    caller that derives several databases from one instance needs. Every
    other caller keeps `open_at` and its settings, because for them
    resolving from the environment IS the contract.
    """
    engine = _write_engine_at(url, chain)
    # Built inside the handler and raised outside it: `from exc` (and
    # `from None`) leave the library's exception reachable from the one
    # that travels out, and both a SQLAlchemy error and a psycopg one
    # hold the connection string they failed on.
    problem: ConfigError | None = None
    try:
        upgrade_to_head(engine, chain)
    except ConfigError:
        engine.dispose()
        raise
    except Exception as exc:
        engine.dispose()
        problem = migration_failure(exc)
    if problem is not None:
        raise problem
    return engine


def read_engine(settings: DatabaseConfig) -> Engine:
    """An engine for reading a database somebody else has already
    migrated, which on a running server means the one boot opened.

    Everything `open_database` does beyond creating an engine is exactly
    what a device path must not do. It migrates, which is an Alembic
    round trip, and it takes the chain's advisory lock before it reads,
    so a lookup would queue behind whichever writer holds it for up to
    the lock timeout. This does neither.

    Two connection properties carry what the SQLite era got from a URI
    and a hand-written deferred `BEGIN`, and both are the server's
    rather than this code's:

    - `REPEATABLE READ`, because `read_live_binding` reads two rows in
      one transaction so that a write landing between them cannot
      produce a state that never existed, and under the default
      `READ COMMITTED` every statement takes its own snapshot, which is
      exactly that torn read.
    - `default_transaction_read_only`, so "a lookup creates nothing" is
      enforced by the database rather than promised by a mode flag.

    A reader never blocks ordinary DML and is never blocked by it, which
    is the snapshot-read property this engine exists for. What a
    reader's locks do hold off is DDL, so a reader left inside a long
    transaction can make a boot migration wait out its lock timeout and
    refuse retryably; `deploy/postgres-init.sql` caps the analyst side
    of that with role-level timeouts on `vinga_ro`.

    The caller owns the engine and disposes it. Nothing is connected
    here: SQLAlchemy connects lazily, so an unreachable database is a
    failure at the first lookup, where the caller can fall back, rather
    than at app build.
    """
    return create_engine(
        connection_url(settings),
        # Echo off, and parameter logging never enabled, so a secret
        # bound into a statement cannot ride a debug log line. Off by
        # default; named here because turning it on for a debugging
        # session would be a leak rather than a convenience.
        echo=False,
        isolation_level="REPEATABLE READ",
        connect_args=_connect_args(read_only=True),
    )


def write_engine(settings: DatabaseConfig, chain: StoreChain) -> Engine:
    """The engine a schema is migrated and written through.

    Every transaction it opens takes the chain's advisory lock first.
    That is the whole of the single-writer discipline: a lock taken at
    the first write would let two writers each validate against the
    pre-change state and then persist over one another, and would let
    two openers each decide the baseline still needs running.
    """
    return _write_engine_at(connection_url(settings), chain)


def _write_engine_at(url: URL, chain: StoreChain) -> Engine:
    """`write_engine` for a connection already resolved, which is the
    half `open_url` and `write_engine` share."""
    engine = create_engine(
        url,
        echo=False,
        connect_args=_connect_args(read_only=False),
    )

    @event.listens_for(engine, "begin")
    def _serialize(connection: object) -> None:
        take_the_chain_lock(connection, chain)

    return engine


def take_the_chain_lock(connection: object, chain: StoreChain) -> None:
    """Take one chain's advisory lock inside a transaction that is
    already open.

    The statement every write transaction begins with, written once
    because two callers issue it. A write engine's begin listener issues
    it for its own chain, which is the single-writer discipline above;
    and a transaction that crosses into a second store issues it for
    that store's chain before its first statement there, which is where
    the ascending order `advisory_key` states is kept.

    Transaction-scoped, so it is released by the commit or the rollback
    and by nothing else, and re-entrant: a transaction that takes the
    same key twice holds it once and gives it back once.
    """
    connection.exec_driver_sql(  # type: ignore[attr-defined]
        f"SELECT pg_advisory_xact_lock({chain.lock_key})"
    )


def upgrade_to_head(engine: Engine, chain: StoreChain) -> None:
    """Bring one chain to head, inside one transaction under its lock.

    The schema is created here rather than by the baseline migration,
    and that is not a matter of taste: with `version_table_schema`
    configured, Alembic creates the schema-qualified version table
    before any `upgrade()` runs, so a `CREATE SCHEMA` written as the
    baseline's first operation would be too late.

    Existence is asked before it is created, rather than leaning on
    `IF NOT EXISTS` alone. `CREATE SCHEMA` checks `CREATE` on the
    database before it looks at whether the schema is there, so the
    `IF NOT EXISTS` form still refuses for a role that lacks that
    privilege, including when the answer would have been "nothing to
    do". Asking first is what lets a deployment provision the schemas
    with `deploy/postgres-init.sql` and give the server role nothing
    but its own schemas.

    That same statement is the one place `SCHEMA_NOT_PERMITTED` is
    raised, and the placement is the sentence's warrant. What it
    prescribes is a rerun of the provisioning file, and the file creates
    missing schemas and nothing else, so it is the answer to this
    refusal and to no other privilege failure a migration can meet: a
    schema standing under the wrong owner is not moved by a rerun, and a
    table-level grant a later revision wanted is not granted by one.
    Everything else that this connection is refused travels out as it
    is and is sanitized by `migration_failure`, which names the
    exception's class and prescribes nothing.
    """
    with engine.connect() as connection:
        # Takes the lock before Alembic looks at the version table: the
        # loser of a race then reads the schema the winner committed and
        # finds it current. Alembic sees a connection already in a
        # transaction, leaves transaction control alone, and the commit
        # below is what ends it.
        connection.execute(text("SELECT 1"))
        found = connection.execute(
            text("SELECT to_regnamespace(:name) IS NOT NULL"), {"name": chain.schema}
        ).scalar()
        if not found:
            # Built inside the handler and raised after it, the rule this
            # module keeps everywhere: the driver's own error holds the
            # DSN it connected on, and `from exc` would leave it reachable
            # from the refusal that travels. A failure that is not the
            # privilege is re-raised untouched, so the caller's own
            # handler classifies it.
            refusal: ConfigError | None = None
            try:
                # The name is this module's own constant, never a value
                # from anywhere a caller reaches.
                connection.execute(
                    text(f'CREATE SCHEMA IF NOT EXISTS "{chain.schema}"')
                )
            except Exception as exc:
                if not _not_permitted(exc):
                    raise
                refusal = StorageError(SCHEMA_NOT_PERMITTED)
            if refusal is not None:
                raise refusal
        config = AlembicConfig()
        config.set_main_option("script_location", str(chain.migrations))
        config.attributes["connection"] = connection
        # What the environment needs to put its version table in the
        # right schema and compare against the right one. Handed over
        # rather than imported there, so the environment stays a
        # function of the chain it was invoked for.
        config.attributes["chain"] = chain
        command.upgrade(config, "head")
        connection.commit()


def connection_url(settings: DatabaseConfig) -> URL:
    """The URL an engine is built from: the five discrete facts, or the
    one variable that replaces all five.

    The password is read here and nowhere else. It has no YAML key and
    no field on any model, so it cannot reach a generated reference, an
    API response or a configuration diff by being carried somewhere it
    would be rendered; this function is the single consumer the no-leak
    rule names.

    `VINGA_DB_URL` wins whole when it is set, and is constrained rather
    than trusted: only the two Postgres schemes are accepted, the bare
    one is normalized to the psycopg 3 dialect, and everything else is
    refused. That refusal is what makes "there is no second storage
    backend" a property of the code rather than a line in a document.
    """
    override = os.environ.get(URL_ENV)
    if override:
        return _named_url(override)
    return URL.create(
        DIALECT,
        username=settings.user,
        password=os.environ.get(PASSWORD_ENV) or DEFAULT_PASSWORD,
        host=settings.host,
        port=settings.port,
        database=settings.name,
    )


def is_busy(exc: BaseException) -> bool:
    """Whether this failure is one the caller may simply make again.

    A closed set of three psycopg errors, matched by type and never by
    message, walked to through SQLAlchemy's `orig` because a driver
    error arrives wrapped. Each member has a decision site:

    - `LockNotAvailable` is `lock_timeout` expiring, on the chain's
      advisory gate or on a lock a migration's DDL needed. It is the
      member every contended write reaches, and the reason the
      retryable refusal exists.
    - `DeadlockDetected` and `SerializationFailure` cannot happen under
      the advisory-lock discipline, which orders every writer before it
      reads. They are here because Postgres defines both as retryable
      and a caller that met one would be right to retry: classifying
      them honestly is a better answer than an arm that says nothing
      until the day the discipline gains an exception.

    Everything else is not retryable and stays a `StorageError`. There
    is no message sniffing anywhere in this project because of this
    function: it is the one home for the question, and both raisers ask
    it here.
    """
    seen: set[int] = set()
    cause: BaseException | None = exc
    while cause is not None and id(cause) not in seen:
        seen.add(id(cause))
        if isinstance(cause, _RETRYABLE):
            return True
        cause = getattr(cause, "orig", None)
    return False


def migration_failure(exc: Exception) -> ConfigError:
    """What an open that did not migrate is answered with.

    Five sentences: the lock that did not arrive, which the caller may
    retry; a database stamped at a revision a re-cut deleted, which has
    to be replaced; a database stamped at any other revision this
    install does not carry, which is the install's fault and names the
    revision; a connection that could not be made, which names the
    variables to check; and everything else, which names the
    exception's class and prescribes nothing. None of them carries a
    word of the driver's own text, because a psycopg connection error
    quotes the DSN it tried and a statement error carries the values
    bound to it.

    A privilege the role does not have is deliberately not a fourth arm
    here. It has an answer only when the refused statement is the
    `CREATE SCHEMA` in `upgrade_to_head`, which is where the sentence
    naming the provisioning rerun is raised; a privilege failure
    anywhere else in a migration is one that rerunning the file will not
    change, and falls through to the general sentence below rather than
    being told to run something that does nothing.

    The superseded arm is narrow on purpose, because the sentence it
    answers with says to throw a database away. Three things have to
    hold before it is said, and each rules out a case that would be told
    to destroy something it should keep. It has to be Alembic's own
    `CommandError`, which a driver failure is not. Its cause has to be a
    `ResolutionError`, which is the stored revision not being findable
    rather than an unreadable script directory or a chain with two
    heads. And the revision it could not find has to be one a re-cut is
    known to have deleted: a database stamped by a NEWER build, met by
    an image that was rolled back, raises exactly the same
    `ResolutionError` and is current rather than stranded, so it is
    given the unknown-revision sentence instead, which points at the
    install and tells its operator not to touch the database.
    """
    if is_busy(exc):
        return DatabaseBusyError(MIGRATION_BUSY)
    if _stranded(exc):
        return StorageError(SUPERSEDED_REVISION)
    unlocatable = _unlocatable(exc)
    if unlocatable is not None:
        return StorageError(UNKNOWN_REVISION.format(stamp=_stamp(unlocatable.argument)))
    if _unreachable(exc):
        return StorageError(UNREACHABLE)
    return StorageError(MIGRATION_FAILED.format(failure=failure_name(exc)))


def _unreachable(exc: BaseException) -> bool:
    """Whether this failure is a connection that could not be made or
    did not survive, which is the one thing `UNREACHABLE` is true of.

    By type, walked to through `orig` like `is_busy`, and by EXACT type
    rather than `isinstance`. Measured against the lane's instance,
    every failure the connection sentence lists (a refused port, a host
    name that does not resolve, and a database, a role or a password
    the instance does not accept) arrives as psycopg's bare
    `OperationalError`: libpq gave up before any server answered, so
    there is no SQLSTATE and so no subclass. A connection lost partway
    through is the same bare class, and its operator has the same list
    to check. `ConnectionTimeout` is the one subclass psycopg raises on
    its own account, when a connect outlasts its timeout.

    Every other subclass of `OperationalError` is a SQLSTATE a server
    sent back on a connection that worked, `LockNotAvailable` and a full
    disk among them, and telling an operator to check a host and a port
    for one of those is the misdirection this function exists to stop.
    """
    seen: set[int] = set()
    cause: BaseException | None = exc
    while cause is not None and id(cause) not in seen:
        seen.add(id(cause))
        if type(cause) in _CONNECTION_FAILURES:
            return True
        cause = getattr(cause, "orig", None)
    return False


def _not_permitted(exc: BaseException) -> bool:
    """Whether the database refused this statement for want of a
    privilege.

    Asked at one call site, the `CREATE SCHEMA` in `upgrade_to_head`,
    because that is the one refusal with a remedy: a role that may not
    create a schema is exactly what a least-privilege deployment has,
    and the provisioning file is what creates one for it. Asked of a
    whole migration it would answer for failures the same file cannot
    fix, and the sentence would then prescribe a command that changes
    nothing.

    Walked through `orig` like `is_busy`, and by class, because a driver
    error arrives wrapped and its message is the one thing that may not
    be read: the wording is the server's, it is localized, and reading
    it is how a classifier comes to depend on a sentence.
    """
    seen: set[int] = set()
    cause: BaseException | None = exc
    while cause is not None and id(cause) not in seen:
        seen.add(id(cause))
        if isinstance(cause, psycopg.errors.InsufficientPrivilege):
            return True
        cause = getattr(cause, "orig", None)
    return False


def _unlocatable(exc: Exception) -> ResolutionError | None:
    """The stored revision Alembic could not find, when that is what
    this failure is, and otherwise nothing.

    Alembic's own `CommandError` with a `ResolutionError` on its cause
    chain, decided by type and never by the "Can't locate revision"
    text. The chain is walked rather than only its first link, because
    what makes this the right question is the `ResolutionError` being in
    it at all; which library happened to wrap it is not this module's
    business to depend on.

    Answers the error rather than a yes, because both arms that ask it
    then read the revision off it: membership of the closed set is what
    tells a stranded database from one this install does not carry, and
    the second arm names what it found.
    """
    if not isinstance(exc, CommandError):
        return None
    seen: set[int] = set()
    cause: BaseException | None = exc.__cause__
    while cause is not None and id(cause) not in seen:
        seen.add(id(cause))
        if isinstance(cause, ResolutionError):
            return cause
        cause = cause.__cause__
    return None


def _stranded(exc: Exception) -> bool:
    """Whether this failure is a database left behind by a re-cut, which
    is the one failure answered by telling an operator to replace it."""
    unlocatable = _unlocatable(exc)
    return unlocatable is not None and unlocatable.argument in SUPERSEDED_REVISIONS


def _stamp(revision: object) -> str:
    """The stored revision as `UNKNOWN_REVISION` may say it: named when
    it has the shape every committed revision has, and replaced by a
    fixed phrase otherwise, because it was read out of a table rather
    than out of this install."""
    if (
        isinstance(revision, str)
        and len(revision) <= REVISION_ID_MAX
        and _REVISION_ID.match(revision)
    ):
        return f"revision {revision}"
    return UNSHAPED_REVISION


_RETRYABLE = (
    psycopg.errors.LockNotAvailable,
    psycopg.errors.DeadlockDetected,
    psycopg.errors.SerializationFailure,
)

# Matched by exact type, for the reason `_unreachable` gives.
_CONNECTION_FAILURES = frozenset({psycopg.OperationalError, psycopg.errors.ConnectionTimeout})


def _connect_args(read_only: bool) -> dict[str, str]:
    """The startup options every connection this module makes carries.

    On the connection's options rather than in a `connect` listener
    running `SET`, and that is load-bearing: a pooled connection is
    returned with a rollback, and a session-level `SET` made inside a
    transaction is undone by one. A startup parameter cannot be rolled
    back, so the timeout holds for the connection's whole life.
    """
    options = [f"-c lock_timeout={LOCK_TIMEOUT_MS}"]
    if read_only:
        options.append("-c default_transaction_read_only=on")
    return {"options": " ".join(options)}


def _named_url(value: str) -> URL:
    """One `VINGA_DB_URL`, parsed and constrained.

    The parse failure is caught and dropped rather than reported:
    SQLAlchemy's own message quotes the string it could not parse, and
    that string is a URL.
    """
    problem: str | None = None
    url: URL | None = None
    try:
        url = make_url(value)
    except Exception:
        problem = URL_REFUSED
    if url is not None and url.drivername not in ACCEPTED_SCHEMES:
        problem = URL_REFUSED
    if problem is not None:
        raise ConfigError(problem)
    assert url is not None
    return url.set(drivername=DIALECT)


__all__ = [
    "ACCEPTED_SCHEMES",
    "DEFAULT_PASSWORD",
    "DIALECT",
    "DOMAIN_CHAIN",
    "LOCK_TIMEOUT_MS",
    "MIGRATION_BUSY",
    "MIGRATION_FAILED",
    "PASSWORD_ENV",
    "REVISION_ID_MAX",
    "REVISION_ID_PATTERN",
    "SCHEMA_NOT_PERMITTED",
    "SUPERSEDED_REVISION",
    "SUPERSEDED_REVISIONS",
    "URL_ENV",
    "UNSHAPED_REVISION",
    "URL_REFUSED",
    "UNKNOWN_REVISION",
    "UNREACHABLE",
    "StoreChain",
    "advisory_key",
    "connection_url",
    "is_busy",
    "migration_failure",
    "open_at",
    "open_database",
    "open_url",
    "read_engine",
    "take_the_chain_lock",
    "upgrade_to_head",
    "write_engine",
]
