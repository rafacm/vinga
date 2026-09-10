"""What the named aggregate views actually answer.

Three claims, and each fails in a different way when it is wrong.

**The numbers.** Every case here writes exact rows and asserts exact
view rows. Nothing drives a conversation: a driven turn's timings are
wall-clock measurements, so a percentile over them is a number nobody
can write down in advance, and the event mixes these views are for
(three failures in one turn, an event on the far side of midnight, a
session with the telemetry switch off) do not occur to order. Seeding
makes the arithmetic checkable, which is the whole point of asserting
it.

**The agreement.** The migration spells its `CREATE VIEW` statements
literally, because a migration is frozen history, and `views.py`
declares the same SQL for the docgen and the tests to read. Two
structures that must agree are one structure with a bug pending, so the
bug is pinned here: a shadow view is built from every declaration inside
a transaction that is rolled back, and `pg_get_viewdef` of the shadow is
compared with `pg_get_viewdef` of the view the chain created. The
database does the normalizing, so the comparison survives whitespace and
survives Postgres rewriting a construct into its own preferred spelling.
The live column list is compared with the declaration matrix in the same
loop, which is what makes a column missing from the matrix a red test
rather than a blank cell on the page.

**The analyst.** `vinga_ro` reading every view is asserted beside the
provisioning file that grants it, in `test_provisioning.py`, because
what makes that grant reach a view is the file's default privileges and
not anything in this module.
"""

import datetime
from collections.abc import Iterator

import pytest
from sqlalchemy import text

from vinga_server.config.models import DatabaseConfig
from vinga_server.conversations import schema
from vinga_server.conversations.store import open_conversations
from vinga_server.conversations.views import VIEWS

# One thread for every planted turn, in the shape the runtime mints.
# Nothing here reads it: the views aggregate by day and agent, and the
# column is not null, so it has to be some thread.
CONVERSATION = "3b1e5c7a9d2f4068a1b3c5d7e9f02468"


@pytest.fixture
def store() -> Iterator:
    """The migrated store, on the lane's own database.

    The autouse truncation between tests empties the tables and leaves
    the views standing, which is exactly right: a view holds no rows, so
    what each case sees is the rows it planted and nothing else.
    """
    engine = open_conversations(DatabaseConfig())
    try:
        yield engine
    finally:
        engine.dispose()


def plant_session(
    connection,
    session: str,
    started_at: str,
    *,
    metrics: bool = True,
    agent: str | None = "sam",
) -> None:
    connection.execute(
        schema.sessions.insert().values(
            session=session,
            device="aa:bb:cc:dd:ee:ff",
            agent=agent,
            started_at=started_at,
            metrics=metrics,
            text=True,
            dropped=0,
        )
    )


def plant_turn(
    connection, session: str, t_ms: int, *, agent: str | None = "sam", **measured
) -> int:
    """One turn, with whatever measured columns the case is about.

    `agent` is the turn's own rather than the session's, which is the
    distinction the token view turns on: a handover leaves the session
    agent alone and splits the reply across `legs`.
    """
    return connection.execute(
        schema.turns.insert().values(
            session=session,
            conversation=CONVERSATION,
            t_ms=t_ms,
            agent=agent,
            tool_calls=0,
            **measured,
        )
    ).inserted_primary_key[0]


def plant_event(connection, session: str, t_ms: int, name: str) -> None:
    connection.execute(
        schema.events.insert().values(
            session=session, t_ms=t_ms, name=name, level=20, fields={}
        )
    )


def rows(engine, view: str, *, timezone: str | None = None) -> list[tuple]:
    """Every row of one view, ordered so an assertion can be a literal.

    `timezone` sets the session timezone of the connection doing the
    reading, which is how the midnight case proves the day is UTC rather
    than the reader's.

    Ordered by the first two columns, which is Postgres ascending with
    nulls last, so a null agent group is the last row of its day.
    """
    with engine.connect() as connection:
        if timezone is not None:
            connection.exec_driver_sql(f"SET TIME ZONE '{timezone}'")
        return [
            tuple(row)
            for row in connection.execute(
                text(f"select * from record.{view} order by 1, 2")
            )
        ]


# --- the numbers --------------------------------------------------------


def test_percentiles_interpolate_over_a_known_distribution(store) -> None:
    """Four measured turns, at 100, 200, 300 and 400 ms.

    `percentile_cont` interpolates, which is what makes these numbers
    worth pinning: the median of an even sample is not a stored value at
    all, and the p95 of four rows sits between the third and the fourth.
    A reader who expected `percentile_disc` would get 200 and 400 here,
    so the assertion is what says which of the two this is.

    `max_ms` is beside them because it is the one number that is not
    interpolated: it is a duration that really happened.
    """
    with store.begin() as connection:
        plant_session(connection, "percentiles", "2026-05-01T09:00:00+00:00")
        for index, value in enumerate((100, 200, 300, 400)):
            plant_turn(connection, "percentiles", index * 1000, asr_ms=value)

    assert rows(store, "metrics_stage_latency_daily") == [
        (datetime.date(2026, 5, 1), "sam", "asr", 4, 250.0, 385.0, 400),
    ]


def test_a_stage_with_no_measurement_has_no_row_at_all(store) -> None:
    """The four stages are unpivoted from four columns, and a turn
    measures whichever of them it reached. A turn that spoke nothing has
    no `tts_first_audio_ms`, and the view must not report it as a stage
    that took zero milliseconds."""
    with store.begin() as connection:
        plant_session(connection, "one-stage", "2026-05-02T09:00:00+00:00")
        plant_turn(connection, "one-stage", 0, asr_ms=120, llm_ms=None)

    assert [row[2] for row in rows(store, "metrics_stage_latency_daily")] == ["asr"]


def test_input_and_output_measurement_are_counted_independently(store) -> None:
    """The store writes the two token sums independently, so one
    `measured_turns` could not describe both. Four turns, one per agent,
    make each combination its own row: an input with no output, an
    output with no input, a turn that measured neither with the switch
    on, and a turn under telemetry-off.

    The last two are identical in this view and cannot be told apart:
    the store writes a provider that reported no usage exactly as it
    writes a turn under telemetry-off. That is the ambiguity the
    reference page states rather than papering over, and this pair of
    rows is the evidence for it.
    """
    with store.begin() as connection:
        plant_session(connection, "tokens-on", "2026-05-03T09:00:00+00:00")
        plant_session(
            connection, "tokens-off", "2026-05-03T10:00:00+00:00", metrics=False
        )
        plant_turn(connection, "tokens-on", 0, agent="in-only", input_tokens=11)
        plant_turn(connection, "tokens-on", 1000, agent="out-only", output_tokens=13)
        plant_turn(connection, "tokens-on", 2000, agent="neither")
        plant_turn(connection, "tokens-off", 0, agent="switched-off")

    day = datetime.date(2026, 5, 3)
    assert rows(store, "metrics_tokens_daily") == [
        (day, "in-only", 1, 1, 0, 11, None),
        (day, "neither", 1, 0, 0, None, None),
        (day, "out-only", 1, 0, 1, None, 13),
        (day, "switched-off", 1, 0, 0, None, None),
    ]


def test_a_handover_attributes_its_legs_and_counts_no_turn_twice(store) -> None:
    """The turn a handover split is the case `turns.agent` alone gets
    wrong: it names the agent the turn started with, and the usage
    belongs to both.

    Three legs, one of which names no agent, plus the turn's own totals
    beside them. What must land is one attribution row per leg with that
    leg's numbers, the turn-level totals counted for nobody, and the
    unattributable leg as a null-agent row rather than as silence. The
    plain turn beside it is what proves the split turn is still one turn
    in the agent it started with: `turns` there is two.
    """
    legs = [
        {"agent": "sam", "input_tokens": 10, "output_tokens": 5},
        {"agent": "max", "input_tokens": 7, "output_tokens": 3},
        {"agent": None, "input_tokens": 2, "output_tokens": 1},
    ]
    with store.begin() as connection:
        plant_session(connection, "handover", "2026-05-04T09:00:00+00:00")
        plant_turn(
            connection,
            "handover",
            0,
            agent="sam",
            legs=legs,
            input_tokens=19,
            output_tokens=9,
        )
        plant_turn(
            connection, "handover", 1000, agent="sam", input_tokens=4, output_tokens=2
        )

    day = datetime.date(2026, 5, 4)
    assert rows(store, "metrics_tokens_daily") == [
        (day, "max", 1, 1, 1, 7, 3),
        (day, "sam", 2, 2, 2, 14, 7),
        (day, None, 1, 1, 1, 2, 1),
    ]


def test_a_session_that_crosses_utc_midnight_dates_its_turns_by_utc(store) -> None:
    """The failure this pins is silent and it is a whole day wide.

    The session opens at 23:30 UTC and its second turn is spoken 70
    minutes later, on the next UTC day. The reading connection is set to
    a timezone eight hours behind UTC, which is where a bare date cast
    would go wrong: in that zone both moments are the afternoon of the
    first day, so an implementation that let the reader's timezone
    decide would put every turn on 2026-03-01 and nobody would see the
    difference until two deployments compared numbers.
    """
    with store.begin() as connection:
        plant_session(connection, "midnight", "2026-03-01T23:30:00+00:00")
        plant_turn(connection, "midnight", 0, asr_ms=100)
        plant_turn(connection, "midnight", 70 * 60 * 1000, asr_ms=200)

    # The session is on the day it opened; its later turn is not.
    assert rows(store, "metrics_sessions_daily", timezone="America/Los_Angeles") == [
        (datetime.date(2026, 3, 1), 1, 1, 1),
        (datetime.date(2026, 3, 2), 0, 0, 1),
    ]
    assert [
        (row[0], row[3])
        for row in rows(
            store, "metrics_stage_latency_daily", timezone="America/Los_Angeles"
        )
    ] == [(datetime.date(2026, 3, 1), 1), (datetime.date(2026, 3, 2), 1)]


def test_telemetry_off_rows_reach_the_denominators_and_no_numerator(store) -> None:
    """A session with the switch off stores its turns and no events at
    all. It therefore raises the turn and session denominators while
    contributing nothing to either rate's numerator, which is a property
    of the data rather than something the view should hide.

    `telemetry_sessions` is what makes it readable: one of the two
    sessions could have produced an event and the other could not.
    """
    with store.begin() as connection:
        plant_session(connection, "on", "2026-06-01T09:00:00+00:00")
        plant_session(connection, "off", "2026-06-01T10:00:00+00:00", metrics=False)
        plant_turn(connection, "on", 0, asr_ms=100)
        plant_turn(connection, "off", 0)
        plant_event(connection, "on", 0, "provider_failed")

    day = datetime.date(2026, 6, 1)
    assert rows(store, "metrics_sessions_daily") == [(day, 2, 1, 2)]
    assert rows(store, "metrics_event_rates_daily") == [(day, 2, 2, 1, 0, 0.5, 0.0)]
    # And the stage view sees only the turn that measured something.
    assert [row[3] for row in rows(store, "metrics_stage_latency_daily")] == [1]


def test_several_events_in_one_turn_count_several_times_and_multiply_nothing(
    store,
) -> None:
    """Counting is per stored row: two provider failures in one turn are
    two, deliberately.

    The trap the join shape exists to avoid is the other half. Each
    stream is aggregated on its own before anything is joined, so the
    two unrelated events planted beside the counted ones cannot inflate
    the turn count, and the suppressions cannot inflate the failures. A
    naive join of turns to events would report four turns here.
    """
    with store.begin() as connection:
        plant_session(connection, "busy", "2026-06-02T09:00:00+00:00")
        plant_turn(connection, "busy", 0)
        plant_turn(connection, "busy", 1000)
        for _ in range(3):
            plant_event(connection, "busy", 500, "provider_failed")
        plant_event(connection, "busy", 600, "barge_in_suppressed")
        plant_event(connection, "busy", 700, "barge_in_suppressed")
        plant_event(connection, "busy", 800, "heard")
        plant_event(connection, "busy", 900, "replied")

    assert rows(store, "metrics_event_rates_daily") == [
        (datetime.date(2026, 6, 2), 2, 1, 3, 2, 1.5, 2.0),
    ]


def test_an_event_on_a_day_with_no_session_start_still_gets_a_row(store) -> None:
    """The day spine, and the zero denominators with it.

    A session opens at 23:00 and a provider fails two hours later, on
    the next UTC day, with no turn anywhere. Without a full outer join
    over the union of days that failure would vanish: there is no
    session row and no turn row on the day it landed. With one, the day
    exists with both denominators at zero, and both rates are null
    rather than zero, because nothing happened and nothing could have
    happened are different facts.
    """
    with store.begin() as connection:
        plant_session(connection, "spine", "2026-04-01T23:00:00+00:00")
        plant_event(connection, "spine", 2 * 60 * 60 * 1000, "provider_failed")

    assert rows(store, "metrics_event_rates_daily") == [
        # The day the session opened: one session, no turns, so the
        # per-turn rate is null and the per-session rate is a real zero.
        (datetime.date(2026, 4, 1), 0, 1, 0, 0, None, 0.0),
        # The day the failure landed: nothing else at all, and both
        # rates null.
        (datetime.date(2026, 4, 2), 0, 0, 1, 0, None, None),
    ]


# --- the agreement ------------------------------------------------------


def test_every_live_view_matches_its_declaration(store) -> None:
    """The pin on the one duplication `views.py` cannot remove.

    A shadow view is created from the declaration and dropped again by
    the rollback, and Postgres renders both definitions, so what is
    compared is two normalized forms of the same query rather than two
    strings somebody formatted. A migration that drifted from the module
    (or a module edited without a migration behind it) fails here and
    nowhere else, because views live outside the metadata that
    `compare_metadata` walks.
    """
    with store.connect() as connection:
        for view in VIEWS:
            live = connection.execute(
                text("select pg_get_viewdef(to_regclass(:name), true)"),
                {"name": view.qualified},
            ).scalar()
            assert live is not None, f"{view.name} is not in the migrated database"

            # A savepoint rather than a transaction: reading the live
            # definition above has already begun one on this connection.
            savepoint = connection.begin_nested()
            try:
                connection.exec_driver_sql(
                    f"CREATE VIEW record.shadow_{view.name} AS\n{view.body}"
                )
                declared = connection.execute(
                    text("select pg_get_viewdef(to_regclass(:name), true)"),
                    {"name": f"record.shadow_{view.name}"},
                ).scalar()
            finally:
                savepoint.rollback()

            assert declared == live, f"{view.name} has drifted from its declaration"


def test_every_live_view_has_exactly_the_columns_it_declares(store) -> None:
    """The declaration matrix is what the reference page renders, so a
    column the database hands back and the matrix has never heard of
    would be an undocumented column rather than a blank cell, and a
    matrix entry with no column behind it would be a documented column
    that does not exist. Names and types, in order, both ways."""
    with store.connect() as connection:
        for view in VIEWS:
            found = [
                (row[0], row[1])
                for row in connection.execute(
                    text(
                        "select column_name, data_type from information_schema.columns "
                        "where table_schema = 'record' and table_name = :name "
                        "order by ordinal_position"
                    ),
                    {"name": view.name},
                )
            ]
            declared = [(column.name, column.type) for column in view.columns]
            assert found == declared, view.name


def test_every_view_carries_its_comment(store) -> None:
    """What `\\d+` shows an analyst before they trust a number: the
    question the view answers and what its denominator is."""
    with store.connect() as connection:
        for view in VIEWS:
            found = connection.execute(
                text("select obj_description(to_regclass(:name), 'pg_class')"),
                {"name": view.qualified},
            ).scalar()
            assert found == view.comment, view.name
