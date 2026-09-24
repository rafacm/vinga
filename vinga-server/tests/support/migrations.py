"""Alembic, driven to a named revision, for the suites that need a
database in a state no current build produces.

An upgrade test's material is a database an older release left behind:
a chain stamped at its baseline, rows written in the shape that
release wrote. The server never makes one, because the only migration
it runs is `db.upgrade_to_head`, which targets head. So these helpers
drive Alembic the way `upgrade_to_head` drives it, with one difference,
the target, which is a named revision in either direction.

"The way `upgrade_to_head` drives it" is three requirements, and they
are why this module exists rather than a copy of them in each suite:

- the script location is the chain's own migrations directory;
- the open connection and the chain are handed over on the config's
  attributes, because the packaged environment refuses to run without
  both;
- the chain's schema exists before Alembic starts, because Alembic
  creates the schema-qualified version table before any `upgrade()`
  runs, which is why `upgrade_to_head` creates the schema first.

`upgrade_to_head` builds its config privately, and `vinga_server.db`
offers no revision-parameterized operation, so `_alembic` is the one
test-side mirror of it. A change to what the environment needs lands
there and in `upgrade_to_head`, and nowhere else.

Each operation owns its whole transaction: it opens an engine, does its
work on one connection, commits, and disposes the engine in a
`finally`. On failure the exception propagates, the connection's
context exit discards the uncommitted work, and the engine is disposed.
"""

from alembic import command
from alembic.config import Config as AlembicConfig
from sqlalchemy import Connection, Engine, text

from vinga_server.config.models import DatabaseConfig
from vinga_server.db import StoreChain, read_engine, write_engine


def upgrade_to(database: str, chain: StoreChain, revision: str) -> DatabaseConfig:
    """A database with `chain` at exactly `revision` and nothing beyond
    it, created from blank, and the settings that reach it."""
    settings = DatabaseConfig(name=database)
    engine = write_engine(settings, chain)
    try:
        with engine.connect() as connection:
            connection.execute(text(f'create schema if not exists "{chain.schema}"'))
            command.upgrade(_alembic(connection, chain), revision)
            connection.commit()
    finally:
        engine.dispose()
    return settings


def downgrade_to(settings: DatabaseConfig, chain: StoreChain, revision: str) -> None:
    """Take `chain` back down to `revision`, the inverse of every
    migration above it."""
    engine = write_engine(settings, chain)
    try:
        with engine.connect() as connection:
            command.downgrade(_alembic(connection, chain), revision)
            connection.commit()
    finally:
        engine.dispose()


def version(engine: Engine, schema: str) -> list[str]:
    """The revisions a chain's version table is stamped with, read
    through an engine the caller owns."""
    with engine.connect() as connection:
        return [
            row[0] for row in connection.execute(text(f"select * from {schema}.alembic_version"))
        ]


def version_of(settings: DatabaseConfig, chain: StoreChain) -> list[str]:
    """The same read through a read engine opened for it and disposed
    after, which neither migrates nor takes the chain's lock."""
    engine = read_engine(settings)
    try:
        return version(engine, chain.schema)
    finally:
        engine.dispose()


def _alembic(connection: Connection, chain: StoreChain) -> AlembicConfig:
    """The config `upgrade_to_head` builds, for this connection and this
    chain."""
    config = AlembicConfig()
    config.set_main_option("script_location", str(chain.migrations))
    config.attributes["connection"] = connection
    config.attributes["chain"] = chain
    return config
