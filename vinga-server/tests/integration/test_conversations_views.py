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

The per-device siblings are asserted here beside the views they mirror,
because a breakdown is a claim about numbers before it is anything
else: two boards on one day have to be two rows whose ungrouped view is
still the whole day, and a session whose device was never understood
has to be one row rather than one row per stream. That last one is the
case the join shape exists for, and it is the case an implementation
gets wrong silently.

The recorded name is the second key of exactly that shape. It is dated
and never rewritten, so a board renamed mid-window is two rows rather
than one retitled series, and the sessions that carry no name (every
one recorded before the column existed, and every board nobody named)
are one more null group the join has to keep whole rather than scatter
across its streams.

That the four originals survive the migration that added the siblings
is `test_metrics_views_upgrade.py`, on a database that stood at
`1006_metrics_views`: nothing here could tell an untouched view from a
rebuilt one, since both match their declaration.
"""

import datetime
from collections.abc import Iterator

import pytest
from sqlalchemy import text

from tests.support.stores import plant_event, plant_session, plant_turn
from vinga_server.config.models import DatabaseConfig
from vinga_server.conversations.store import open_conversations
from vinga_server.conversations.views import DEFINED


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


def rows(
    engine, view: str, *, timezone: str | None = None, by: str = "1, 2"
) -> list[tuple]:
    """Every row of one view, ordered so an assertion can be a literal.

    `timezone` sets the session timezone of the connection doing the
    reading, which is how the midnight case proves the day is UTC rather
    than the reader's.

    Ordered by the first two columns, which is Postgres ascending with
    nulls last, so a null agent group is the last row of its day. `by`
    widens that where two columns are not a total order: one board under
    two names is two rows of a per-device view that share both of them.
    """
    with engine.connect() as connection:
        if timezone is not None:
            connection.exec_driver_sql(f"SET TIME ZONE '{timezone}'")
        return [
            tuple(row)
            for row in connection.execute(
                text(f"select * from record.{view} order by {by}")
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


# --- the per-device siblings --------------------------------------------


# Two boards of the same fleet. They share a vendor OUI, the way a real
# fleet does, so the assertions below are about the whole MAC.
BOARD_A = "a4:cf:12:00:00:01"

BOARD_B = "a4:cf:12:00:00:02"


def test_two_boards_on_one_day_are_two_rows_and_the_day_is_still_the_day(store) -> None:
    """The breakdown, and the view it breaks down, in one case.

    Two boards, one day, and every number planted so that a row of a
    sibling is that board's and the ungrouped row is both of them. The
    second half is what says the sibling is additive rather than a
    replacement: an analyst who never asked for a device still gets the
    day.

    The latency pair is the sharpest of the four. The ungrouped p50 of
    100 and 300 is 200, which is a number neither board measured, so a
    sibling that had quietly been served the ungrouped rows could not
    produce these two and an ungrouped view rebuilt from the sibling
    could not produce that one.
    """
    with store.begin() as connection:
        plant_session(connection, "board-a", "2026-07-01T09:00:00+00:00", device=BOARD_A)
        plant_session(connection, "board-b", "2026-07-01T10:00:00+00:00", device=BOARD_B)
        plant_turn(connection, "board-a", 0, asr_ms=100, input_tokens=5, output_tokens=2)
        plant_turn(connection, "board-b", 0, asr_ms=300, input_tokens=7, output_tokens=3)
        plant_event(connection, "board-a", 0, "provider_failed")

    day = datetime.date(2026, 7, 1)
    assert rows(store, "metrics_sessions_by_device_daily") == [
        (day, BOARD_A, None, 1, 1, 1),
        (day, BOARD_B, None, 1, 1, 1),
    ]
    assert rows(store, "metrics_sessions_daily") == [(day, 2, 2, 2)]

    assert rows(store, "metrics_stage_latency_by_device_daily") == [
        (day, BOARD_A, None, "sam", "asr", 1, 100.0, 100.0, 100),
        (day, BOARD_B, None, "sam", "asr", 1, 300.0, 300.0, 300),
    ]
    assert rows(store, "metrics_stage_latency_daily") == [
        (day, "sam", "asr", 2, 200.0, 290.0, 300),
    ]

    assert rows(store, "metrics_tokens_by_device_daily") == [
        (day, BOARD_A, None, "sam", 1, 1, 1, 5, 2),
        (day, BOARD_B, None, "sam", 1, 1, 1, 7, 3),
    ]
    assert rows(store, "metrics_tokens_daily") == [(day, "sam", 2, 2, 2, 12, 5)]

    # The failure is one board's, so its rate is one per turn and the
    # other board's is a real zero. The day's rate is neither.
    assert rows(store, "metrics_event_rates_by_device_daily") == [
        (day, BOARD_A, None, 1, 1, 1, 0, 1.0, 0.0),
        (day, BOARD_B, None, 1, 1, 0, 0, 0.0, 0.0),
    ]
    assert rows(store, "metrics_event_rates_daily") == [(day, 2, 2, 1, 0, 0.5, 0.0)]


def test_a_session_with_no_device_is_one_group_and_not_one_row_per_stream(store) -> None:
    """The case the join shape exists for, and the one that fails
    silently without it.

    `sessions.device` is null when a session was rejected before a
    device was understood, and the two views below combine streams that
    were aggregated independently. Two SQL nulls are not equal to each
    other, so joining those streams with `=` leaves every one of them
    unmatched by every other: the spine still yields one row per group,
    because `UNION` treats two nulls as one value, and that row comes
    back with zeroes where the other streams' numbers should have been
    and its rates null. Asserting merely that exactly one row came back,
    or that no device was invented, would pass on exactly that.

    So what is asserted is the numbers. One session, one turn and one
    counted failure, all of them on a device nobody knows, and the row
    that has to come back says one, one, one and a rate of one failure
    per turn.
    """
    with store.begin() as connection:
        plant_session(connection, "unknown", "2026-07-02T09:00:00+00:00", device=None)
        plant_turn(connection, "unknown", 0, asr_ms=100)
        plant_event(connection, "unknown", 0, "provider_failed")

    day = datetime.date(2026, 7, 2)
    assert rows(store, "metrics_event_rates_by_device_daily") == [
        (day, None, None, 1, 1, 1, 0, 1.0, 0.0),
    ]
    assert rows(store, "metrics_sessions_by_device_daily") == [(day, None, None, 1, 1, 1)]


def test_a_board_and_a_stranger_on_one_day_keep_their_own_numbers(store) -> None:
    """The null group beside a named one, which is where a join that
    coalesced a missing key to something could put one board's numbers
    on the other's row.

    The two sessions differ in every number, so a row that borrowed from
    the other would be visibly wrong rather than coincidentally right.
    """
    with store.begin() as connection:
        plant_session(connection, "known", "2026-07-03T09:00:00+00:00", device=BOARD_A)
        plant_session(connection, "stranger", "2026-07-03T10:00:00+00:00", device=None)
        plant_turn(connection, "known", 0, asr_ms=100)
        for offset in (0, 1000, 2000):
            plant_turn(connection, "stranger", offset, asr_ms=200)
        plant_event(connection, "stranger", 0, "provider_failed")
        plant_event(connection, "stranger", 1, "barge_in_suppressed")

    day = datetime.date(2026, 7, 3)
    # Ordered by the day and then the device ascending with nulls last,
    # which is the order the read surface pages on.
    assert rows(store, "metrics_event_rates_by_device_daily") == [
        (day, BOARD_A, None, 1, 1, 0, 0, 0.0, 0.0),
        (day, None, None, 3, 1, 1, 1, 1 / 3, 1.0),
    ]
    assert rows(store, "metrics_sessions_by_device_daily") == [
        (day, BOARD_A, None, 1, 1, 1),
        (day, None, None, 1, 1, 3),
    ]


def test_a_renamed_board_splits_its_series_rather_than_retitling_it(store) -> None:
    """What the label being part of the key means, in the case it was
    chosen for.

    `sessions.device_name` is dated: it says what the board was called
    when the session opened, and nothing rewrites it. So a board renamed
    mid-window has sessions carrying both names, and the view has to
    decide what a row is. One row per (device, name) pair is what this
    asserts: the old name keeps the numbers it earned and the new name
    starts its own series, which is the reading a most-recent-name rule
    would destroy by stamping today's label over last week's rows.

    The third session is the board before anybody named it, which is
    every session recorded before the column existed. It groups as its
    own null-name row rather than joining either series or vanishing,
    the way a null device already does.

    The ungrouped view beside them is what says none of this moved a
    total: one board, three sessions, one day.
    """
    with store.begin() as connection:
        plant_session(
            connection,
            "renamed-old",
            "2026-07-04T09:00:00+00:00",
            device=BOARD_A,
            device_name="Kitchen Speaker",
        )
        plant_session(
            connection,
            "renamed-new",
            "2026-07-04T10:00:00+00:00",
            device=BOARD_A,
            device_name="Hallway Speaker",
        )
        plant_session(
            connection, "renamed-never", "2026-07-04T11:00:00+00:00", device=BOARD_A
        )
        plant_turn(connection, "renamed-old", 0, asr_ms=100)
        plant_turn(connection, "renamed-new", 0, asr_ms=300)
        plant_turn(connection, "renamed-never", 0, asr_ms=200)

    day = datetime.date(2026, 7, 4)
    # Ordered by the day, the device and then the name ascending with
    # nulls last, which is the order the read surface pages on now that
    # the name is one of the keys.
    assert rows(store, "metrics_sessions_by_device_daily", by="1, 2, 3") == [
        (day, BOARD_A, "Hallway Speaker", 1, 1, 1),
        (day, BOARD_A, "Kitchen Speaker", 1, 1, 1),
        (day, BOARD_A, None, 1, 1, 1),
    ]
    assert rows(store, "metrics_sessions_daily") == [(day, 3, 3, 3)]

    # The latency numbers are what a series being split really means:
    # each name's percentile is over its own turn, and the day's is over
    # all three.
    assert rows(store, "metrics_stage_latency_by_device_daily", by="1, 2, 3") == [
        (day, BOARD_A, "Hallway Speaker", "sam", "asr", 1, 300.0, 300.0, 300),
        (day, BOARD_A, "Kitchen Speaker", "sam", "asr", 1, 100.0, 100.0, 100),
        (day, BOARD_A, None, "sam", "asr", 1, 200.0, 200.0, 200),
    ]
    assert rows(store, "metrics_stage_latency_daily") == [
        (day, "sam", "asr", 3, 200.0, 290.0, 300),
    ]


def test_sessions_with_no_recorded_name_are_one_row_and_keep_their_numbers(
    store,
) -> None:
    """The rows every deployment already has, and the second null key of
    these views.

    Nothing backfilled `sessions.device_name`, so every session recorded
    before it existed carries a null there, as does every board nobody
    named. Those sessions have to keep aggregating exactly as they did
    when the column was the literal null: one row for the board, with
    the numbers of all of them.

    The trap is the same one the null device sprang, one key over. The
    two views below combine independently aggregated streams, and two
    SQL nulls are not equal, so a join on `=` over the name would leave
    every stream of this group unmatched by every other: one row would
    still come back, because `UNION` treats two nulls as one value, and
    it would carry one stream's number, zeroes where the others belong
    and a broken rate. So the numbers are what is asserted, not the row
    count.
    """
    with store.begin() as connection:
        plant_session(connection, "unnamed-one", "2026-07-05T09:00:00+00:00", device=BOARD_A)
        plant_session(connection, "unnamed-two", "2026-07-05T10:00:00+00:00", device=BOARD_A)
        plant_turn(connection, "unnamed-one", 0, asr_ms=100)
        plant_turn(connection, "unnamed-two", 0, asr_ms=200)
        plant_event(connection, "unnamed-one", 0, "provider_failed")

    day = datetime.date(2026, 7, 5)
    assert rows(store, "metrics_sessions_by_device_daily", by="1, 2, 3") == [
        (day, BOARD_A, None, 2, 2, 2),
    ]
    assert rows(store, "metrics_event_rates_by_device_daily", by="1, 2, 3") == [
        (day, BOARD_A, None, 2, 2, 1, 0, 0.5, 0.0),
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
        for view in DEFINED:
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
        for view in DEFINED:
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
        for view in DEFINED:
            found = connection.execute(
                text("select obj_description(to_regclass(:name), 'pg_class')"),
                {"name": view.qualified},
            ).scalar()
            assert found == view.comment, view.name
