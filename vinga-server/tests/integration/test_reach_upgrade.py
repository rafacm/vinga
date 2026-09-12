"""The reach migration, proved on rows a pre-#493 build left behind.

`tests/unit/test_db_open.py` asks what the chain builds from nothing,
and every one of its questions passes on a database whose bodies this
migration mangled. Rows are the whole subject here: #493 replaced the
boolean `egress` key with `reach` and gave the new models no alias, so
a deployment upgrading into this release carries provider and MCP
bodies the new build refuses at boot, before the configuration API that
would fix them is reachable at all.

Three claims, in the order an operator would meet them:

- every legacy shape translates, including the explicit `null` that
  `exclude_unset=True` preserves and that a migration keyed only on
  true and false would leave behind as a forbidden key;
- the distinction the two old refusals drew survives the translation. A
  provider's `false` said "off this host" and becomes `host`; an MCP
  entry's said "off this network" and becomes `network`. A migration
  that mapped both to the same value would erase exactly the difference
  #493 exists to make sayable;
- everything else on a translated row is untouched, and a row that
  never carried the key is not rewritten at all.

And the fourth, which is what makes this a translation rather than an
alias: a NEW write carrying the old key is still refused after the
migration exists.

The lane rather than the unit suite, for `test_domain_upgrade.py`'s
reason: the material is a database in a state no current build
produces, and the fixture that makes one is `blank_database`, since a
migrated template cannot be stamped backwards.
"""

import json

import pytest
from alembic import command
from alembic.config import Config as AlembicConfig
from cryptography.fernet import Fernet, MultiFernet
from sqlalchemy import text

from vinga_server.boundary import Reach
from vinga_server.config.loader import ConfigError
from vinga_server.config.models import DatabaseConfig
from vinga_server.config.secrets import generate_key
from vinga_server.config.store import ConfigStore
from vinga_server.db import DOMAIN_CHAIN, open_database, read_engine, write_engine

# The revision a deployment whose bodies carry `egress` is stamped at,
# and the whole of what this release upgrades from.
BASELINE = "3003_device_record"

HEAD = "3004_reach_replaces_egress"

# One row per legacy shape, per entry kind. The explicit null is the
# delta round's finding and the one a reader would not think to write:
# bodies are dumped with `exclude_unset=True`, so a fragment that SET
# the key to null keeps it while one that never mentioned it does not,
# and only the first of those is a row the new models refuse.
# The declared half every seeded provider carries, so the rows differ
# only in the key under test.
_PROVIDER = '"type": "openai_compatible", "model": "m", "base_url": "http://ollama:11434/v1"'

PROVIDERS = {
    "kept": (f"{{{_PROVIDER}, \"egress\": false}}", Reach.HOST),
    "sent": (f"{{{_PROVIDER}, \"egress\": true}}", Reach.INTERNET),
    "unsaid": (f"{{{_PROVIDER}, \"egress\": null}}", None),
    "absent": (f"{{{_PROVIDER}}}", None),
}

MCP_SERVERS = {
    "kept": ('{"transport": "stdio", "command": "uvx", "egress": false}', Reach.NETWORK),
    "sent": ('{"transport": "stdio", "command": "uvx", "egress": true}', Reach.INTERNET),
    "unsaid": ('{"transport": "stdio", "command": "uvx", "egress": null}', None),
    "absent": ('{"transport": "stdio", "command": "uvx"}', None),
}

STAGE = "llm"


@pytest.fixture
def at_the_baseline(blank_database: str) -> DatabaseConfig:
    """A database with the domain chain at `3003_device_record` and
    nothing beyond it.

    Alembic is driven the way `db.upgrade_to_head` drives it, with the
    schema created first and the connection and the chain handed over on
    the config's attributes, because the packaged environment refuses to
    run without both. The one difference is the target: a named revision
    rather than head, which is the whole of what makes this a database
    from before the release.
    """
    settings = DatabaseConfig(name=blank_database)
    engine = write_engine(settings, DOMAIN_CHAIN)
    try:
        with engine.connect() as connection:
            connection.execute(text(f'create schema if not exists "{DOMAIN_CHAIN.schema}"'))
            config = AlembicConfig()
            config.set_main_option("script_location", str(DOMAIN_CHAIN.migrations))
            config.attributes["connection"] = connection
            config.attributes["chain"] = DOMAIN_CHAIN
            command.upgrade(config, BASELINE)
            connection.commit()
    finally:
        engine.dispose()
    return settings


@pytest.fixture
def seeded(at_the_baseline: DatabaseConfig) -> DatabaseConfig:
    """The deployment this release meets: every legacy shape, on both
    entry kinds.

    Written into the columns directly, because the repository from this
    build refuses every one of these bodies. What is being reproduced is
    a database an older build left behind, and a repository from this
    build is not an older build.
    """
    settings = at_the_baseline
    engine = write_engine(settings, DOMAIN_CHAIN)
    try:
        with engine.begin() as connection:
            for name, (body, _) in PROVIDERS.items():
                connection.execute(
                    text(
                        "insert into domain.providers (stage, name, body, secrets) "
                        "values (:stage, :name, :body, cast(:secrets as json))"
                    ),
                    {"stage": STAGE, "name": name, "body": body, "secrets": "{}"},
                )
            for name, (body, _) in MCP_SERVERS.items():
                connection.execute(
                    text(
                        "insert into domain.mcp_servers (name, body, secrets) "
                        "values (:name, :body, cast(:secrets as json))"
                    ),
                    {"name": name, "body": body, "secrets": "{}"},
                )
    finally:
        engine.dispose()
    return settings


def _bodies(settings: DatabaseConfig, table: str) -> dict[str, dict]:
    """Every row's body as JSON, read underneath every model that would
    refuse one."""
    engine = read_engine(settings)
    try:
        with engine.connect() as connection:
            rows = connection.execute(
                text(f"select name, body from domain.{table}")
            ).all()
    finally:
        engine.dispose()
    return {name: json.loads(body) for name, body in rows}


def _version(settings: DatabaseConfig) -> list[str]:
    engine = read_engine(settings)
    try:
        with engine.connect() as connection:
            return [
                row[0]
                for row in connection.execute(
                    text(f"select * from {DOMAIN_CHAIN.schema}.alembic_version")
                )
            ]
    finally:
        engine.dispose()


def _upgrade(settings: DatabaseConfig) -> None:
    """The boot's own step, which is what runs the migration."""
    open_database(settings).dispose()


def test_the_seeded_rows_really_carry_the_key_the_release_withdraws(
    seeded: DatabaseConfig,
) -> None:
    """Without this every assertion below would be vacuously true of
    rows that never held the key, which is exactly what a seed written
    through a repository that now refuses it would produce."""
    assert _version(seeded) == [BASELINE]
    providers = _bodies(seeded, "providers")
    assert {name for name, body in providers.items() if "egress" in body} == {
        "kept",
        "sent",
        "unsaid",
    }
    servers = _bodies(seeded, "mcp_servers")
    assert {name for name, body in servers.items() if "egress" in body} == {
        "kept",
        "sent",
        "unsaid",
    }


def test_the_upgrade_translates_every_legacy_shape(seeded: DatabaseConfig) -> None:
    """The migration's whole claim, at the column: no row keeps the
    forbidden key, each `false` becomes the value its own old refusal
    named, each `true` becomes `internet`, and an explicit null leaves
    with no key at all, which is the state absence already is."""
    _upgrade(seeded)

    assert _version(seeded) == [HEAD]
    for table, expected in (("providers", PROVIDERS), ("mcp_servers", MCP_SERVERS)):
        bodies = _bodies(seeded, table)
        for name, (_, reach) in expected.items():
            assert "egress" not in bodies[name], (table, name)
            assert bodies[name].get("reach") == (None if reach is None else reach.value), (
                table,
                name,
            )


def test_the_translation_keeps_the_host_and_network_distinction(
    seeded: DatabaseConfig,
) -> None:
    """Stated on its own because it is the one thing a plausible
    migration gets wrong. The two old refusals said different things,
    and a translation that mapped both `false`s to one value would erase
    exactly the difference this release exists to make sayable."""
    _upgrade(seeded)

    assert _bodies(seeded, "providers")["kept"]["reach"] == "host"
    assert _bodies(seeded, "mcp_servers")["kept"]["reach"] == "network"


def test_the_rest_of_a_translated_row_is_untouched(seeded: DatabaseConfig) -> None:
    """One key of one column, and nothing beside it: a migration that
    rewrote a body through a JSON round trip would move fields no part
    of this release is about."""
    _upgrade(seeded)

    providers = _bodies(seeded, "providers")
    assert providers["kept"]["type"] == "openai_compatible"
    assert providers["kept"]["model"] == "m"
    servers = _bodies(seeded, "mcp_servers")
    assert servers["sent"]["transport"] == "stdio"
    assert servers["sent"]["command"] == "uvx"


def test_the_upgraded_store_loads_and_reads_back_the_translated_values(
    seeded: DatabaseConfig,
) -> None:
    """The surface the migration exists for: a boot that reads these
    rows. Before it, the first start on this release refused the whole
    snapshot on a key the operator could only fix through an API the
    refusal kept them out of."""
    engine = open_database(seeded)
    try:
        store = ConfigStore(engine, MultiFernet([Fernet(generate_key())]))
        snapshot = store.load()
    finally:
        engine.dispose()

    assert snapshot.domain.providers.llm["kept"].reach is Reach.HOST
    assert snapshot.domain.providers.llm["sent"].reach is Reach.INTERNET
    assert snapshot.domain.providers.llm["unsaid"].reach is None
    assert snapshot.domain.mcp_servers["kept"].reach is Reach.NETWORK
    assert snapshot.domain.mcp_servers["sent"].reach is Reach.INTERNET
    assert snapshot.domain.mcp_servers["absent"].reach is None


def test_a_new_write_carrying_the_old_key_is_still_refused(
    seeded: DatabaseConfig,
) -> None:
    """Which is what makes this a one-time translation rather than an
    alias. The migration reads what an older build wrote; nothing about
    it lets an operator write the old key again."""
    engine = open_database(seeded)
    try:
        store = ConfigStore(engine, MultiFernet([Fernet(generate_key())]))
        with pytest.raises(ConfigError):
            store.set_provider(STAGE, "fresh", {"type": "mock", "egress": False})
        with pytest.raises(ConfigError):
            store.set_mcp_server(
                "fresh", {"transport": "stdio", "command": "uvx", "egress": False}
            )
    finally:
        engine.dispose()
