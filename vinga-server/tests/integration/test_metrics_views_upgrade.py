"""The per-device views are added beside the four, then replaced in place.

The claim this file exists for is the one nothing else can make. The
agreement test next door compares every declaration with the live view
on a database built from nothing, and it would stay green if
`1008_metrics_views_by_device` had dropped and recreated the four views
`1006_metrics_views` created: a rebuilt view matches its declaration
exactly as well as an untouched one does. What an analyst loses to a
rebuild is not the definition but everything hanging off it, and a
dashboard, a saved query or a downstream view is not in this repository
to fail.

So the subject here is a database that stood at `1006_metrics_views`
before this release: what the four views were then, and what they are
after the upgrade. Three things are compared, and the first two are
what a definition check on its own cannot say.

**The identity.** A view dropped and recreated from the same SQL has
the same definition and a new oid, and the oid is what every dependent
object in the database points at. So the oids are read before and
after, and an equal pair is the only evidence that these are the same
four relations rather than four that look like them.

**The dependents.** An analyst's saved object is not in this repository
to fail, so one is planted at the baseline: a view of
`metrics_sessions_daily`, which is what a dashboard, a downstream view
or a materialized rollup is a case of. `DROP VIEW` would have been
refused by the database while it stood, and `DROP VIEW ... CASCADE`
would have taken it silently, which is the failure worth a test.

**The definition.** `pg_get_viewdef` at both ends, because it is what
the database says a view is rather than what a migration file says it
wrote.

The version stamp is asserted at both ends too, so a fixture that
quietly migrated to head could not make any of the three trivially
true.

The downgrade is asserted for the same reason it is written: it is the
inverse of an additive change, so it takes the four it added and leaves
the four it found.

**The second baseline.** `1009_views_read_the_name` replaces the four
siblings rather than adding anything, and the claim it makes is the same
one in a place the 1006 baseline cannot reach: at 1006 those four
relations do not exist, so a 1009 that dropped and recreated its own
targets would pass every assertion above. So there is a database
standing at `1008_metrics_views_by_device` too, with an analyst's object
on one of the siblings, reading the very column 1009 moves. What is
compared there is the oid against a definition and a comment that must
have changed: same relation, new answer. And the downgrade is run to
1008 rather than past it, because a run that carried on to 1006 would
drop the four and say nothing about what 1009's downgrade restored.

The lane rather than the unit suite, for the reason
`test_domain_upgrade.py` gives: the material is a database in a state no
current build produces, and the fixture that makes one is
`blank_database`, since a migrated template cannot be stamped
backwards.
"""

import datetime as dt
from collections.abc import Iterator

import pytest
from alembic import command
from alembic.config import Config as AlembicConfig
from sqlalchemy import text

from vinga_server.config.models import DatabaseConfig
from vinga_server.conversations.store import CONVERSATIONS_CHAIN, open_conversations
from vinga_server.conversations.views import BY_DEVICE_VIEWS, VIEWS
from vinga_server.db import read_engine, write_engine

# The revision a deployment carrying the four aggregate views is
# stamped at, and the whole of what the sibling migration upgrades from.
BASELINE = "1006_metrics_views"

# The revision a deployment carrying the siblings is stamped at, which
# is what `1009_views_read_the_name` replaces in place. A second
# baseline rather than a second assertion on the first: at 1006 the
# relations 1009 touches do not exist, so nothing read there can say
# whether it replaced them or rebuilt them.
SIBLING_BASELINE = "1008_metrics_views_by_device"

HEAD = "1009_views_read_the_name"

# What an analyst leaves standing on one of the four views, and on one
# of the four siblings. Named here because two fixtures and one
# assertion have to spell each.
DEPENDENT = "an_analysts_saved_query"

SIBLING_DEPENDENT = "an_analysts_saved_breakdown"

# The column 1009 makes the siblings read, and the literal 1008 had them
# select instead. Named because both baselines are recognized by which
# of the two their definitions carry.
RECORDED_NAME = "device_name"

SHIPPED_NULL = "NULL::text"


def _alembic(connection) -> AlembicConfig:
    """Alembic driven the way `db.upgrade_to_head` drives it: the chain
    and the open connection handed over on the config's attributes,
    because the packaged environment refuses to run without both. The
    one difference is the target, which is a named revision rather than
    head."""
    config = AlembicConfig()
    config.set_main_option("script_location", str(CONVERSATIONS_CHAIN.migrations))
    config.attributes["connection"] = connection
    config.attributes["chain"] = CONVERSATIONS_CHAIN
    return config


def _stamped(blank_database: str, revision: str) -> DatabaseConfig:
    """A database with the conversations chain at exactly one revision
    and nothing beyond it."""
    settings = DatabaseConfig(name=blank_database)
    engine = write_engine(settings, CONVERSATIONS_CHAIN)
    try:
        with engine.connect() as connection:
            connection.execute(
                text(f'create schema if not exists "{CONVERSATIONS_CHAIN.schema}"')
            )
            command.upgrade(_alembic(connection), revision)
            connection.commit()
    finally:
        engine.dispose()
    return settings


@pytest.fixture
def at_the_baseline(blank_database: str) -> DatabaseConfig:
    """A database with the conversations chain at `1006` and nothing
    beyond it: the four views, and no sibling anywhere."""
    return _stamped(blank_database, BASELINE)


@pytest.fixture
def at_the_siblings(blank_database: str) -> DatabaseConfig:
    """A database with the chain at `1008`: the four views and the four
    siblings, each selecting the literal null for its label.

    This is the state every deployment carrying the siblings is in, and
    the only state from which "replaced rather than rebuilt" is a
    question that can be asked at all.
    """
    return _stamped(blank_database, SIBLING_BASELINE)


def _relations(
    settings: DatabaseConfig, names: list[str]
) -> dict[str, tuple[int, str, str | None] | None]:
    """Each view's oid, its definition and its comment, or `None` where
    there is no such view.

    The oid is the identity every dependent object in the database
    points at, the definition is what the database says the view is
    rather than what a migration file says it wrote, and the comment is
    what `\\d+` shows an analyst beside it. The three are read in one
    statement so they can never be read from different states.
    """
    engine = read_engine(settings)
    try:
        with engine.connect() as connection:
            found: dict[str, tuple[int, str, str | None] | None] = {}
            for name in names:
                row = connection.execute(
                    text(
                        "select to_regclass(:name)::oid, "
                        "pg_get_viewdef(to_regclass(:name), true), "
                        "obj_description(to_regclass(:name), 'pg_class')"
                    ),
                    {"name": f"record.{name}"},
                ).one()
                found[name] = None if row[0] is None else (row[0], row[1], row[2])
            return found
    finally:
        engine.dispose()


def _plant_dependent(settings: DatabaseConfig, name: str, columns: str, on: str) -> None:
    """An analyst's own object, standing on one of the views.

    A view rather than anything more elaborate because the dependency is
    the subject and not the object: what `DROP VIEW ... CASCADE` takes
    silently is anything at all that points at the relation.
    """
    engine = write_engine(settings, CONVERSATIONS_CHAIN)
    try:
        with engine.begin() as connection:
            connection.execute(
                text(f"create view record.{name} as select {columns} from record.{on}")
            )
    finally:
        engine.dispose()


def _version(settings: DatabaseConfig) -> list[str]:
    engine = read_engine(settings)
    try:
        with engine.connect() as connection:
            return [
                row[0]
                for row in connection.execute(
                    text(f"select * from {CONVERSATIONS_CHAIN.schema}.alembic_version")
                )
            ]
    finally:
        engine.dispose()


def _answers(settings: DatabaseConfig, name: str) -> list[tuple]:
    """Every row of one view. The database is empty, so the answer is
    the empty list; what is being asserted is that the view can be
    selected from at all, which is what a view left in place after a
    chain moved under it cannot always do."""
    engine = read_engine(settings)
    try:
        with engine.connect() as connection:
            return [
                tuple(row) for row in connection.execute(text(f"select * from record.{name}"))
            ]
    finally:
        engine.dispose()


SEEDED_NAME = "Kitchen Speaker"


def _seed(settings: DatabaseConfig) -> None:
    """One session, one turn and one event, so "still answers" is a row
    coming back rather than an empty list coming back.

    The session names its device, which only a database already past
    `1007_sessions_name_the_device` can hold: this runs after the
    upgrade, and the name is what the siblings have to read.
    """
    engine = write_engine(settings, CONVERSATIONS_CHAIN)
    try:
        with engine.begin() as connection:
            connection.execute(
                text(
                    "insert into record.sessions "
                    "(session, device, device_name, agent, started_at, metrics, text, "
                    "dropped) values "
                    "(:session, :device, :device_name, :agent, :started_at, true, true, 0)"
                ),
                {
                    "session": "upgraded",
                    "device": "aa:bb:cc:dd:ee:ff",
                    "device_name": SEEDED_NAME,
                    "agent": "sam",
                    "started_at": "2026-05-01T09:00:00+00:00",
                },
            )
            connection.execute(
                text(
                    "insert into record.turns "
                    "(session, conversation, t_ms, agent, tool_calls, asr_ms) values "
                    "('upgraded', 'thread', 0, 'sam', 0, 120)"
                )
            )
            connection.execute(
                text(
                    "insert into record.events (session, t_ms, name, level, fields) "
                    "values ('upgraded', 0, 'provider_failed', 20, '{}')"
                )
            )
    finally:
        engine.dispose()


@pytest.fixture
def before(at_the_baseline: DatabaseConfig) -> dict[str, tuple[int, str, str | None] | None]:
    """What the four views are before this release touches the database,
    with the analyst's object already standing on one of them."""
    _plant_dependent(
        at_the_baseline, DEPENDENT, "day, sessions", "metrics_sessions_daily"
    )
    return _relations(at_the_baseline, [view.name for view in VIEWS])


@pytest.fixture
def upgraded(at_the_baseline: DatabaseConfig) -> Iterator[DatabaseConfig]:
    """The same database after a boot, which is what runs the migration:
    `open_conversations` brings the chain to head before anything reads
    a row."""
    engine = open_conversations(at_the_baseline)
    try:
        yield at_the_baseline
    finally:
        engine.dispose()


@pytest.fixture
def siblings_before(
    at_the_siblings: DatabaseConfig,
) -> dict[str, tuple[int, str, str | None] | None]:
    """What the four siblings are as 1008 shipped them, with an
    analyst's object already standing on one of them.

    The oid, the definition and the comment, because 1009 replaces all
    three surfaces of a view and the downgrade has to put back exactly
    what it found. The dependent selects the label as well as the keys,
    which is the column 1009 moves: an object reading it is what a
    rebuild would take and what a replacement must not.
    """
    _plant_dependent(
        at_the_siblings,
        SIBLING_DEPENDENT,
        "day, device, name, sessions",
        "metrics_sessions_by_device_daily",
    )
    return _relations(at_the_siblings, [view.name for view in BY_DEVICE_VIEWS])


@pytest.fixture
def replaced(at_the_siblings: DatabaseConfig) -> Iterator[DatabaseConfig]:
    """The 1008 database after a boot, which is what runs 1009."""
    engine = open_conversations(at_the_siblings)
    try:
        yield at_the_siblings
    finally:
        engine.dispose()


def test_the_baseline_really_is_the_state_this_release_upgrades_from(
    at_the_baseline: DatabaseConfig, before: dict[str, tuple[int, str, str | None] | None]
) -> None:
    """The control the claims below rest on. Without it, a fixture that
    had quietly migrated to head would make "the four survived" true by
    never having exercised the migration at all, and the siblings would
    be there to prove it and nobody would be looking."""
    assert _version(at_the_baseline) == [BASELINE]
    assert all(found is not None for found in before.values()), before
    assert _relations(at_the_baseline, [view.name for view in BY_DEVICE_VIEWS]) == {
        view.name: None for view in BY_DEVICE_VIEWS
    }


def test_the_four_views_survive_the_upgrade_unmoved(
    before: dict[str, tuple[int, str, str | None] | None], upgraded: DatabaseConfig
) -> None:
    """The whole reason the per-device views are siblings rather than
    two more columns on these four: what selects from them is somebody
    else's object, and a redefinition moves it without asking.

    The oid is half of what is compared and it is the half that fails
    on a migration that dropped and recreated the four from the same
    SQL, which is the shape a definition check alone reads as
    untouched.
    """
    assert _version(upgraded) == [HEAD]
    assert _relations(upgraded, list(before)) == before


def test_what_an_analyst_left_standing_on_them_is_still_standing(
    before: dict[str, tuple[int, str, str | None] | None], upgraded: DatabaseConfig
) -> None:
    """The consequence, in the form it would arrive in. A saved object
    pointing at one of the four is what `DROP VIEW ... CASCADE` takes
    without saying so, and nothing in this repository would fail."""
    _seed(upgraded)

    assert _answers(upgraded, DEPENDENT) == [(dt.date(2026, 5, 1), 1)]


def test_the_four_views_still_answer_after_the_upgrade(
    upgraded: DatabaseConfig,
) -> None:
    """Survived and works are different claims, and a view whose
    definition is intact can still be unselectable. One session, one
    turn and one event, so each of the four has something to say."""
    _seed(upgraded)
    day = dt.date(2026, 5, 1)

    assert _answers(upgraded, "metrics_stage_latency_daily") == [
        (day, "sam", "asr", 1, 120.0, 120.0, 120)
    ]
    assert _answers(upgraded, "metrics_tokens_daily") == [
        (day, "sam", 1, 0, 0, None, None)
    ]
    assert _answers(upgraded, "metrics_event_rates_daily") == [
        (day, 1, 1, 1, 0, 1.0, 0.0)
    ]
    assert _answers(upgraded, "metrics_sessions_daily") == [(day, 1, 1, 1)]


def test_the_upgrade_adds_the_four_siblings_and_they_answer(
    upgraded: DatabaseConfig,
) -> None:
    _seed(upgraded)

    for view in BY_DEVICE_VIEWS:
        rows = _answers(upgraded, view.name)
        assert len(rows) == 1, view.name
        # The device is the second column of every sibling and the
        # label the third, which is the shape a caller reads. The label
        # is the name the session itself recorded, which is the whole of
        # what an upgraded deployment gains here.
        assert rows[0][1] == "aa:bb:cc:dd:ee:ff", view.name
        assert rows[0][2] == SEEDED_NAME, view.name


def test_the_downgrade_takes_what_it_added_and_leaves_what_it_found(
    before: dict[str, tuple[int, str, str | None] | None], upgraded: DatabaseConfig
) -> None:
    """The inverse of an additive change. A view holds no rows, so
    dropping one loses nothing that was not derived from the tables
    underneath it, and the four this migration found are not its to
    drop."""
    engine = write_engine(upgraded, CONVERSATIONS_CHAIN)
    try:
        with engine.connect() as connection:
            command.downgrade(_alembic(connection), BASELINE)
            connection.commit()
    finally:
        engine.dispose()

    assert _version(upgraded) == [BASELINE]
    assert _relations(upgraded, list(before)) == before
    assert _relations(upgraded, [view.name for view in BY_DEVICE_VIEWS]) == {
        view.name: None for view in BY_DEVICE_VIEWS
    }


# --- the second baseline: what 1009 replaces ----------------------------


def test_the_sibling_baseline_really_is_the_state_1009_replaces(
    at_the_siblings: DatabaseConfig,
    siblings_before: dict[str, tuple[int, str, str | None] | None],
) -> None:
    """The control the two claims below rest on, and the thing the 1006
    baseline cannot be: at 1008 the four relations 1009 touches exist,
    and they select the literal null the label shipped as. A fixture
    that had quietly migrated to head would fail here rather than make
    "replaced in place" true by comparing a view with itself."""
    assert _version(at_the_siblings) == [SIBLING_BASELINE]
    assert all(found is not None for found in siblings_before.values()), siblings_before
    for name, found in siblings_before.items():
        assert found is not None
        assert SHIPPED_NULL in found[1], name
        assert RECORDED_NAME not in found[1], name


def test_the_four_siblings_are_replaced_where_they_stand(
    siblings_before: dict[str, tuple[int, str, str | None] | None],
    replaced: DatabaseConfig,
) -> None:
    """The claim `CREATE OR REPLACE` is chosen for, and the one a
    definition check cannot make on its own.

    A migration that dropped these four and created them again would
    leave definitions matching the declarations exactly as well as these
    do, and would have taken every dependent object with it. So what is
    compared is the oid, which is what a dependent points at, against a
    definition that must have changed and a comment that must have
    changed with it: same relation, new answer.
    """
    assert _version(replaced) == [HEAD]

    after = _relations(replaced, list(siblings_before))
    for name, was in siblings_before.items():
        now = after[name]
        assert was is not None and now is not None, name
        # The identity is the same relation, not a new one wearing the
        # same name.
        assert now[0] == was[0], name
        # And the answer is a different answer: the label is read off
        # the session now, and the comment says what a row is one row of.
        assert now[1] != was[1], name
        assert RECORDED_NAME in now[1], name
        assert SHIPPED_NULL not in now[1], name
        assert now[2] != was[2], name


def test_what_an_analyst_left_standing_on_a_sibling_is_still_standing(
    siblings_before: dict[str, tuple[int, str, str | None] | None],
    replaced: DatabaseConfig,
) -> None:
    """The consequence, in the form it would arrive in. The planted view
    reads the very column 1009 moves, so a migration that dropped its
    target would have needed `CASCADE` and would have taken this
    silently, and nothing else in this repository would have failed."""
    _seed(replaced)

    assert _answers(replaced, SIBLING_DEPENDENT) == [
        (dt.date(2026, 5, 1), "aa:bb:cc:dd:ee:ff", SEEDED_NAME, 1)
    ]


def test_the_downgrade_restores_the_definitions_1008_shipped(
    siblings_before: dict[str, tuple[int, str, str | None] | None],
    replaced: DatabaseConfig,
) -> None:
    """The inverse of a replacement, which is a replacement back rather
    than a drop: the same four relations, the definitions and the
    comments 1008 shipped, and the label a literal null again.

    Downgraded to 1008 rather than past it, because a run that carried
    on to 1006 would drop these four and prove nothing about what 1009's
    downgrade put back. The oids are in the comparison for the same
    reason they are in the upgrade's: a downgrade that dropped and
    recreated would restore the definition and lose the dependents.
    """
    engine = write_engine(replaced, CONVERSATIONS_CHAIN)
    try:
        with engine.connect() as connection:
            command.downgrade(_alembic(connection), SIBLING_BASELINE)
            connection.commit()
    finally:
        engine.dispose()

    assert _version(replaced) == [SIBLING_BASELINE]
    assert _relations(replaced, list(siblings_before)) == siblings_before

    # And the relation still answers, with the label back to the null
    # 1008 shipped rather than the name the session recorded.
    _seed(replaced)
    rows = _answers(replaced, "metrics_sessions_by_device_daily")
    assert [row[2] for row in rows] == [None]
