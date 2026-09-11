"""The device record's migration, proved on rows rather than on an
empty database.

`tests/unit/test_db_open.py` asks what the chain builds from nothing:
the head, the tables, the columns. Every one of those passes on a
database whose rows `3003_device_record` mangled, and rows are this
migration's whole subject. It mints an identity for every device a
deployment already had, backfills a name for each, and moves the
primary key off the MAC, and the only place any of that can go wrong is
a table with something in it.

Four claims, in the order an operator would meet them:

- every row that was there gets an id, and no two rows get the same one;
- every row gets the `Device <full mac>` name, and no two collide,
  which is why the backfill uses the whole MAC rather than a tail of
  it: the leading octets are the vendor OUI and a fleet shares them;
- the bindings the deployment had are exactly the bindings it still
  has, read back through the repository that will serve them;
- a writer from the previous image is refused rather than silently
  accepted. The one-replica topology ADR (#316) means a rolling
  two-version overlap is not a supported deployment shape, so the
  upgrade is stop-then-migrate and the old row shape stops working the
  moment it lands. That is a decision, and this is where it is worth
  what it claims.

The lane rather than the unit suite, for `test_domain_upgrade.py`'s
reason: the material is a database in a state no current build
produces, and the fixture that makes one is `blank_database`, since a
migrated template cannot be stamped backwards.
"""

from collections.abc import Iterator

import pytest
from alembic import command
from alembic.config import Config as AlembicConfig
from sqlalchemy import text

from vinga_server.config.models import DatabaseConfig, fold_device_name, is_device_id
from vinga_server.config.store import ConfigStore, read_live_binding
from vinga_server.db import DOMAIN_CHAIN, open_database, read_engine, write_engine

# The revision a deployment carrying MAC-keyed device rows is stamped
# at, and the whole of what this release upgrades from.
BASELINE = "3002_drop_max_tokens_secrets"

HEAD = "3003_device_record"

# Three boards of one fleet, sharing a vendor OUI. Sharing it is the
# point: a backfill that named a device after the tail of its MAC would
# give all three one name and fail inside the migration, where there is
# no good answer.
FLEET = ("a4:cf:12:00:00:01", "a4:cf:12:00:00:02", "a4:cf:12:00:00:03")

AGENT = "sam"


@pytest.fixture
def at_the_baseline(blank_database: str) -> DatabaseConfig:
    """A database with the domain chain at `3002` and nothing beyond it.

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
    """The deployment this release meets: one agent and three boards
    bound to it, all written in the row shape the previous image wrote.

    The rows go in through raw SQL rather than through the repository,
    because the repository this commit ships cannot write them: what is
    being reproduced is a database an older build left behind, and only
    the database is old.
    """
    engine = write_engine(at_the_baseline, DOMAIN_CHAIN)
    try:
        with engine.begin() as connection:
            connection.execute(
                text("insert into domain.agents (name, body) values (:name, :body)"),
                {"name": AGENT, "body": '{"prompt":"You are Sam."}'},
            )
            for mac in FLEET:
                connection.execute(
                    text("insert into domain.devices (mac, agents) values (:mac, :agents)"),
                    {"mac": mac, "agents": f'["{AGENT}"]'},
                )
    finally:
        engine.dispose()
    return at_the_baseline


@pytest.fixture
def upgraded(seeded: DatabaseConfig) -> Iterator[DatabaseConfig]:
    """The same database after a boot, which is what runs the migration:
    `open_database` brings the chain to head before anything reads a
    row."""
    engine = open_database(seeded)
    try:
        yield seeded
    finally:
        engine.dispose()


def _rows(settings: DatabaseConfig) -> list[dict[str, object]]:
    engine = read_engine(settings)
    try:
        with engine.connect() as connection:
            return [
                dict(row)
                for row in connection.execute(
                    text("select id, mac, name, location, agents from domain.devices order by mac")
                ).mappings()
            ]
    finally:
        engine.dispose()


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


def test_the_seeded_rows_really_are_the_old_shape(seeded: DatabaseConfig) -> None:
    """The control the three claims below rest on: without it, a seed
    that quietly wrote the new columns would make every one of them
    pass by never having exercised the migration."""
    engine = read_engine(seeded)
    try:
        with engine.connect() as connection:
            columns = {
                row[0]
                for row in connection.execute(
                    text(
                        "select column_name from information_schema.columns "
                        "where table_schema = 'domain' and table_name = 'devices'"
                    )
                )
            }
    finally:
        engine.dispose()
    assert columns == {"mac", "agents"}
    assert _version(seeded) == [BASELINE]


def test_every_row_is_minted_an_identity_of_its_own(upgraded: DatabaseConfig) -> None:
    rows = _rows(upgraded)

    assert [row["mac"] for row in rows] == list(FLEET)
    assert all(is_device_id(row["id"]) for row in rows), rows
    assert len({row["id"] for row in rows}) == len(FLEET)
    assert _version(upgraded) == [HEAD]


def test_every_row_is_backfilled_a_name_that_does_not_collide(
    upgraded: DatabaseConfig,
) -> None:
    """The full MAC and not a tail of it. These three share a vendor
    OUI, so a truncated default would have given all three one name and
    violated the index this migration creates a statement later."""
    rows = _rows(upgraded)

    assert [row["name"] for row in rows] == [f"Device {mac}" for mac in FLEET]
    assert len({fold_device_name(str(row["name"])) for row in rows}) == len(FLEET)


def test_a_device_that_was_nowhere_in_particular_still_is(
    upgraded: DatabaseConfig,
) -> None:
    assert [row["location"] for row in _rows(upgraded)] == [None] * len(FLEET)


def test_the_bindings_survive_and_read_back_through_the_repository(
    upgraded: DatabaseConfig,
) -> None:
    """The claim that matters to the fleet: three boards that reached an
    agent before the upgrade reach it after, through the repository and
    through the lookup a board's own check-in takes."""
    engine = open_database(upgraded)
    try:
        store = ConfigStore(engine)
        for mac in FLEET:
            assert store.read_device(mac).entry.agents == [AGENT]
    finally:
        engine.dispose()

    lookup = read_engine(upgraded)
    try:
        for mac in FLEET:
            assert read_live_binding(lookup, mac).agents == (AGENT,)
    finally:
        lookup.dispose()


def test_a_writer_from_the_previous_image_is_refused(upgraded: DatabaseConfig) -> None:
    """Not staged around, and that is the decision rather than an
    oversight.

    An older process still running would keep upserting only `mac` and
    `agents`. The one-replica topology ADR says a rolling two-version
    overlap is not a supported deployment shape, so the answer is
    stop-then-migrate, and what this asserts is that the database says
    no rather than accepting a row with no identity and no name.
    """
    engine = write_engine(upgraded, DOMAIN_CHAIN)
    try:
        with pytest.raises(Exception) as caught:  # noqa: PT011 - the driver's own
            with engine.begin() as connection:
                connection.execute(
                    text("insert into domain.devices (mac, agents) values (:mac, :agents)"),
                    {"mac": "a4:cf:12:00:00:09", "agents": f'["{AGENT}"]'},
                )
    finally:
        engine.dispose()

    assert "null value" in str(caught.value).lower()
    assert [row["mac"] for row in _rows(upgraded)] == list(FLEET)


def test_the_folded_name_index_is_there_after_the_upgrade(
    upgraded: DatabaseConfig,
) -> None:
    """The invariant the migration's last statement but one creates,
    asserted by attempting the insert on a database that reached it by
    upgrading rather than by being built fresh."""
    engine = write_engine(upgraded, DOMAIN_CHAIN)
    try:
        with pytest.raises(Exception) as caught:  # noqa: PT011 - the driver's own
            with engine.begin() as connection:
                connection.execute(
                    text(
                        "update domain.devices set name = :name where mac = :mac"
                    ),
                    {"name": f"  DEVICE   {FLEET[1]} ", "mac": FLEET[0]},
                )
    finally:
        engine.dispose()

    assert "uq_devices_folded_name" in str(caught.value)
