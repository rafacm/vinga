"""The named aggregates over HTTP: the window, the vocabulary and the
caveats.

What the views answer is asserted where a database is, in
`tests/integration/test_conversations_views.py`, which plants exact rows
and pins exact numbers. What is left for this file is everything the
read surface adds on top of them, and it is three things.

**The request contract, boundary by boundary.** Each default, both ends
of the window included, a window at the cap and one past it, a malformed
day, a grouping nothing serves, the order a page comes back in, and a
window with nothing in it. The contract is prose until something fails
on the day it is wrong, and a boundary is exactly where that happens.

**The closed mapping, pinned by what a hostile value does.** The view is
the one request-controlled value on this API that selects a database
relation, and a relation name cannot be a bound parameter. So the bytes
are a key in a mapping derived from the registry and nothing else, and
the case here sends values that would be unmistakable in a statement, a
body or a log line, and hunts for them in all three.

**The switches, as sentences and statuses.** Recording off with history
behind it, a deployment that never recorded, and telemetry off asserted
per view, because it is not one behaviour: the latency view produces no
row at all for a turn stored under the switch, while the event-rate view
keeps both denominators and loses both numerators. A surface that
flattened that would report a blind day as a quiet one.

The caveats reaching the contract a client reads are asserted in
`test_api_openapi.py`, on the document rather than on a response, since
that is where a client generator finds them.
"""

import datetime as dt
import logging
from typing import Any
from urllib.parse import quote

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import text

from tests.support.problems import paths, refused
from tests.support.stores import plant_event, plant_session, plant_turn
from vinga_server import logs
from vinga_server.config.api import MOUNT_PATH, build_api
from vinga_server.config.models import DatabaseConfig
from vinga_server.config.responses import GROUPINGS
from vinga_server.conversations import api as conversations_api
from vinga_server.conversations.api import WINDOW_DEFAULT_DAYS, WINDOW_MAX_DAYS
from vinga_server.conversations.store import ConversationStore, open_conversations
from vinga_server.conversations.views import ALIASES, COMMON, VIEWS

TOKEN = "test-api-token-" + "0123456789abcdef" * 2

# Shaped like something an operator would be horrified to find quoted
# back, and so that a substring check for it cannot match by accident.
SENTINEL = "sk-test-4a7e2c01-never-a-real-credential"

# The other two halves of a credential-bearing name, distinct from the
# first so that an answer keeping any one of the three fails on that
# one rather than on whichever is checked first.
TOKEN_SENTINEL = "tok-test-5b8f3d12-never-a-real-credential"

AUTHORIZATION_SENTINEL = "Bearer-br-6c9a4e23-never-a-real-credential"

SECRET_PARTS = (SENTINEL, TOKEN_SENTINEL, AUTHORIZATION_SENTINEL)

# A name that arrived around the write path's refusal, which is the
# state `sessions.device_name` is documented to hold as written, and
# what `without_url_credential` leaves of it: the address, without the
# userinfo and without the credential-named parameters.
CREDENTIAL_NAME = (
    f"https://u:{SENTINEL}@example.invalid/desk"
    f"?token={TOKEN_SENTINEL}&authorization={AUTHORIZATION_SENTINEL}"
)

STRIPPED_NAME = "https://example.invalid/desk"

# The day every planted session opens on, and the window around it. A
# fixed day rather than today's, so a case that asserts an exact row is
# asserting about what it planted and not about when it was run.
DAY = "2026-05-14"

# Two boards of one fleet, sharing a vendor OUI the way a real fleet
# does. The second is spelled back in the mixed, dash-separated form a
# caller may type, which is what says the filter is normalized rather
# than matched literally.
BOARD_A = "a4:cf:12:00:00:01"

BOARD_B = "a4:cf:12:00:00:02"

BOARD_B_AS_TYPED = "A4-CF-12-00-00-02"


@pytest.fixture
def store() -> Any:
    """The migrated store, on the lane's own database.

    Boot is what migrates the `record` schema in a real deployment, and
    a suite that plants rows has to stand where boot stood. The autouse
    truncation between tests empties the tables and leaves the views.
    """
    engine = open_conversations(DatabaseConfig())
    try:
        yield engine
    finally:
        engine.dispose()


@pytest.fixture
def api() -> FastAPI:
    return build_api(TOKEN, DatabaseConfig())


@pytest.fixture
def client(api: FastAPI) -> TestClient:
    return TestClient(api, headers={"Authorization": f"Bearer {TOKEN}"})


def _get(client: TestClient, path: str, **params: Any) -> Any:
    response = client.get(path, params=params)
    assert response.status_code == 200, response.text
    return response.json()


def _leaked(caplog: pytest.LogCaptureFixture) -> str:
    """Everything this server logged, in both shipped formats: a
    sentence is rendered one way by the plain formatter and another by
    the JSON one, and a value can hide in a field the plain rendering
    never prints."""
    records = [record for record in caplog.records if record.name.startswith("vinga_server")]
    return "".join(
        record.getMessage() + str(record.__dict__) + logs.JsonFormatter().format(record)
        for record in records
    )


def a_day(
    store: Any,
    day: str,
    *,
    session: str | None = None,
    agent: str = "sam",
    device: str | None = BOARD_A,
    device_name: str | None = None,
) -> None:
    """One session opened at noon on a named UTC day, with a measured
    turn and one counted event on it.

    Noon rather than midnight so that the day a row lands on is the day
    that was asked for whichever way a reader's own timezone leans, which
    is the property the views are cut on.

    `device` is the board it ran on. `None` is the state the schema
    documents, a session rejected before a device was understood, and it
    is what the per-device rows have to carry as a group of its own.

    `device_name` is what that board was called when the session opened.
    `None` by default, which is what a board nobody named and every
    session recorded before the column existed carry.
    """
    named = session if session is not None else day
    with store.begin() as connection:
        plant_session(
            connection,
            named,
            f"{day}T12:00:00+00:00",
            agent=agent,
            device=device,
            device_name=device_name,
        )
        plant_turn(
            connection, named, 0, agent=agent, asr_ms=120, input_tokens=7, output_tokens=3
        )
        plant_event(connection, named, 0, "provider_failed")


# The listing


def test_the_listing_is_the_registry_and_opens_nothing(client: TestClient) -> None:
    """`GET /metrics` describes what the schema declares rather than
    what anybody wrote, so it answers the same thing on a deployment
    that never recorded a syllable. No store fixture here, deliberately:
    this route takes no reader at all."""
    listing = _get(client, "/metrics")

    assert [item["view"] for item in listing["items"]] == [view.alias for view in VIEWS]
    for item, view in zip(listing["items"], VIEWS, strict=True):
        assert item["relation"] == view.qualified
        assert item["question"] == view.question
        assert item["denominator"] == view.denominator
        assert item["telemetry_off"] == view.telemetry_off
        assert [column["name"] for column in item["columns"]] == [
            column.name for column in view.columns
        ]
        assert [column["key"] for column in item["columns"]] == [
            column.key for column in view.columns
        ]


def test_the_listing_carries_what_holds_for_every_view(client: TestClient) -> None:
    """The caveats travel with the vocabulary, because the CLI in front
    of this is a client of the API and has no other way to reach them."""
    listing = _get(client, "/metrics")

    assert listing["common"] == [
        {"heading": group.heading, "notes": list(group.notes)} for group in COMMON
    ]


# The window


def test_the_default_window_is_the_current_utc_day_and_the_month_before_it(
    client: TestClient, store: Any
) -> None:
    """Both defaults, read off the answer rather than recomputed by the
    caller: a client that sent neither argument is told which two days
    it was given.

    Either side of the request is accepted as the day, because the
    server takes its own reading and a case that took one reading would
    fail once a year at midnight UTC for a reason that is not a defect.
    """
    before = dt.datetime.now(dt.UTC).date()
    answered = _get(client, "/metrics/sessions")
    after = dt.datetime.now(dt.UTC).date()

    days = {before, after}
    assert dt.date.fromisoformat(answered["until"]) in days
    assert dt.date.fromisoformat(answered["since"]) in {
        day - dt.timedelta(days=WINDOW_DEFAULT_DAYS) for day in days
    }
    # And the two are exactly the window apart, whichever day it was.
    assert (
        dt.date.fromisoformat(answered["until"])
        - dt.date.fromisoformat(answered["since"])
    ).days == WINDOW_DEFAULT_DAYS
    assert answered["group"] == GROUPINGS[0]


def test_both_ends_of_the_window_are_included(client: TestClient, store: Any) -> None:
    """Inclusive at both ends, which is the half of a date range nobody
    can guess: a caller asking for the first to the seventh means seven
    days, and a row on either named day is in."""
    for day in ("2026-05-13", "2026-05-14", "2026-05-15", "2026-05-16"):
        a_day(store, day)

    answered = _get(client, "/metrics/sessions", since="2026-05-14", until="2026-05-15")

    assert [row["day"] for row in answered["rows"]] == ["2026-05-15", "2026-05-14"]
    assert answered["since"] == "2026-05-14"
    assert answered["until"] == "2026-05-15"


def test_a_window_of_one_day_spans_that_day(client: TestClient, store: Any) -> None:
    """The degenerate case of the rule above, which is where an
    off-by-one in either direction shows up as an empty answer or as two
    days."""
    a_day(store, DAY)
    a_day(store, "2026-05-15")

    answered = _get(client, "/metrics/sessions", since=DAY, until=DAY)

    assert [row["day"] for row in answered["rows"]] == [DAY]


def test_a_window_at_the_cap_is_answered_and_one_past_it_is_refused(
    client: TestClient, store: Any
) -> None:
    """The cap counts both ends, so the widest answerable window is one
    leap year and the first refused one is a day wider.

    Refused rather than narrowed, which is the whole reason there is a
    bound worth stating: an answer trimmed to fit would be less than
    what was asked for while nothing in it said so.
    """
    until = dt.date(2026, 5, 14)
    at_the_cap = until - dt.timedelta(days=WINDOW_MAX_DAYS - 1)
    over = until - dt.timedelta(days=WINDOW_MAX_DAYS)

    answered = _get(
        client, "/metrics/sessions", since=at_the_cap.isoformat(), until=until.isoformat()
    )
    assert answered["since"] == at_the_cap.isoformat()

    response = client.get(
        "/metrics/sessions", params={"since": over.isoformat(), "until": until.isoformat()}
    )
    assert response.status_code == 422
    sentence = refused(response.json(), 422)
    assert str(WINDOW_MAX_DAYS) in sentence
    assert "refused rather than narrowed" in sentence


@pytest.mark.parametrize("until", ["0001-01-01", "0001-01-30"])
def test_a_day_with_no_room_for_the_default_window_is_refused(
    client: TestClient, until: str
) -> None:
    """The other end of the window rule, and the one that is not about
    the caller being wrong.

    `0001-01-01` is a well-formed UTC day and passes the day rule, so it
    is not a malformed value at all: it is the first day this calendar
    has, and the window that would be put behind it by default begins
    before the calendar does. That has to be a stated refusal rather
    than an arithmetic failure answering 500 about a request nothing was
    wrong with.
    """
    response = client.get("/metrics/sessions", params={"until": until})

    assert response.status_code == 422
    sentence = refused(response.json(), 422)
    assert "until" in sentence
    # The calendar's own first day, which is a constant of the calendar
    # and not anything the caller sent.
    assert dt.date.min.isoformat() in sentence
    if until != dt.date.min.isoformat():
        assert until not in sentence
    # And what to send instead, since the request is well formed.
    assert "since" in sentence


def test_the_first_day_of_the_calendar_is_answerable_when_since_says_so(
    client: TestClient, store: Any
) -> None:
    """The same days, with a `since` in hand, are an ordinary window: it
    is the implied one that had nowhere to begin, and naming it is what
    the refusal above tells a caller to do."""
    answered = _get(client, "/metrics/sessions", since="0001-01-01", until="0001-01-30")

    assert (answered["since"], answered["until"]) == ("0001-01-01", "0001-01-30")
    assert answered["rows"] == []


def test_the_last_day_of_the_calendar_needs_no_room_ahead_of_it(
    client: TestClient, store: Any
) -> None:
    """The far end, which has no rule of its own: the window is put
    behind `until`, never in front of it, so the last day the calendar
    has is an ordinary one to ask about."""
    answered = _get(client, "/metrics/sessions", until="9999-12-31")

    assert answered["until"] == "9999-12-31"
    assert answered["since"] == "9999-12-01"


def test_a_window_that_ends_before_it_begins_is_refused(client: TestClient) -> None:
    """Neither argument is wrong on its own, so the refusal is about the
    pair and names both of them."""
    response = client.get(
        "/metrics/sessions", params={"since": "2026-05-15", "until": DAY}
    )

    assert response.status_code == 422
    assert "since" in refused(response.json(), 422)
    assert "until" in refused(response.json(), 422)


def test_an_empty_window_is_an_empty_list_and_not_a_refusal(
    client: TestClient, store: Any
) -> None:
    """A window with nothing in it is an ordinary answer, and it says
    which window it was: a caller that got an empty list can tell it
    asked about the wrong fortnight without asking again."""
    a_day(store, DAY)

    answered = _get(client, "/metrics/sessions", since="2026-01-01", until="2026-01-31")

    assert answered["rows"] == []
    assert (answered["since"], answered["until"]) == ("2026-01-01", "2026-01-31")


# The ordering


def test_a_page_is_ordered_newest_day_first_then_by_its_other_keys(
    client: TestClient, store: Any
) -> None:
    """The day descending because a reader of a trend wants the newest
    first, then the view's other key columns ascending with nulls last.

    Those columns are what a row is unique by, so the order is total and
    the same request answers the same page twice. The latency view is
    the one with three of them, and the null agent is what a planner
    would otherwise be free to put anywhere.
    """
    with store.begin() as connection:
        plant_session(connection, "older", f"{DAY}T12:00:00+00:00")
        plant_session(connection, "newer", "2026-05-15T12:00:00+00:00")
        for session in ("older", "newer"):
            plant_turn(connection, session, 0, agent="zoe", asr_ms=10, llm_ms=20)
            plant_turn(connection, session, 1000, agent="ada", asr_ms=30, llm_ms=40)
            plant_turn(connection, session, 2000, agent=None, asr_ms=50, llm_ms=60)

    rows = _get(client, "/metrics/stage-latency", since=DAY, until="2026-05-15")["rows"]

    assert [(row["day"], row["agent"], row["stage"]) for row in rows] == [
        ("2026-05-15", "ada", "asr"),
        ("2026-05-15", "ada", "llm"),
        ("2026-05-15", "zoe", "asr"),
        ("2026-05-15", "zoe", "llm"),
        # Nulls last within the day, which is where usage nobody can
        # attribute belongs: under the named groups rather than above
        # them.
        ("2026-05-15", None, "asr"),
        ("2026-05-15", None, "llm"),
        (DAY, "ada", "asr"),
        (DAY, "ada", "llm"),
        (DAY, "zoe", "asr"),
        (DAY, "zoe", "llm"),
        (DAY, None, "asr"),
        (DAY, None, "llm"),
    ]


def test_every_view_answers_over_the_same_window(client: TestClient, store: Any) -> None:
    """All four, because the window and the ordering are built from each
    view's own declaration rather than written once per view: a view
    whose key columns were declared wrong answers here and nowhere
    else."""
    a_day(store, DAY)

    for alias in ALIASES:
        answered = _get(client, f"/metrics/{alias}", since=DAY, until=DAY)
        assert answered["view"]["view"] == alias
        assert [row["day"] for row in answered["rows"]] == [DAY], alias
        assert set(answered["rows"][0]) == {
            column["name"] for column in answered["view"]["columns"]
        }, alias


# The vocabulary, and what a value nothing answers to meets


def test_an_unknown_view_says_where_the_list_is_and_quotes_nothing(
    client: TestClient, store: Any, caplog: pytest.LogCaptureFixture
) -> None:
    with caplog.at_level(logging.DEBUG):
        response = client.get(f"/metrics/{SENTINEL}")

    assert response.status_code == 404
    sentence = refused(response.json(), 404)
    assert "GET /metrics" in sentence
    assert SENTINEL not in response.text
    assert SENTINEL not in _leaked(caplog)


def test_a_grouping_nothing_serves_is_refused(client: TestClient, store: Any) -> None:
    """Refused rather than ignored: a caller asking for a breakdown that
    was quietly answered with the ungrouped rows could not tell the two
    apart."""
    response = client.get("/metrics/sessions", params={"group": SENTINEL})

    assert response.status_code == 422
    sentence = refused(response.json(), 422)
    assert "group" in sentence
    for grouping in GROUPINGS:
        assert grouping in sentence


def test_the_device_grouping_answers_from_the_sibling(
    client: TestClient, store: Any
) -> None:
    """The second token, and what makes it a different question rather
    than a different rendering of the same one.

    Two boards on one day. Ungrouped, the day is one row with two
    sessions in it; grouped by device, it is two rows of one session
    each, and the answer carries the relation that produced them, its
    own columns and the two extra keys a page is now ordered on. A
    surface that had answered the grouping from the ungrouped view would
    give the same row twice and no device at all.
    """
    a_day(store, DAY, session="a", device=BOARD_A, device_name="Kitchen Speaker")
    a_day(store, DAY, session="b", device=BOARD_B)

    ungrouped = _get(client, "/metrics/sessions", since=DAY, until=DAY)
    assert [row["sessions"] for row in ungrouped["rows"]] == [2]
    assert "device" not in ungrouped["rows"][0]
    assert ungrouped["view"]["relation"].endswith("metrics_sessions_daily")

    answered = _get(client, "/metrics/sessions", since=DAY, until=DAY, group="device")

    assert answered["group"] == "device"
    # The word a request spelled is unchanged: the question is one
    # question and the grouping chose which relation answers it.
    assert answered["view"]["view"] == "sessions"
    assert answered["view"]["relation"].endswith("metrics_sessions_by_device_daily")
    # The label is what each session recorded, and it is null where
    # nothing recorded one rather than absent: a client renders a column
    # it was told about.
    assert [(row["device"], row["name"], row["sessions"]) for row in answered["rows"]] == [
        (BOARD_A, "Kitchen Speaker", 1),
        (BOARD_B, None, 1),
    ]
    declared = {column["name"]: column for column in answered["view"]["columns"]}
    assert declared["device"]["key"] is True
    # A key because the name a session recorded is never rewritten, so
    # a renamed board is two rows rather than one retitled series.
    assert declared["name"]["key"] is True
    assert declared["name"]["nullable"] is True


def test_a_renamed_board_comes_back_as_two_rows_in_name_order(
    client: TestClient, store: Any
) -> None:
    """The page a rename produces, in the order the read surface pages
    on.

    One board, three sessions, two of them naming it and one recorded
    before anybody did. The name is one of the keys, so the answer is
    three rows rather than one, and the order is the day descending then
    the device and the name ascending with nulls last: a label nobody
    recorded belongs under the named series rather than above them.
    Without the name in the key columns the order would not be total and
    the same request could answer two different pages.
    """
    a_day(store, DAY, session="old", device=BOARD_A, device_name="Kitchen Speaker")
    a_day(store, DAY, session="new", device=BOARD_A, device_name="Hallway Speaker")
    a_day(store, DAY, session="never", device=BOARD_A)

    answered = _get(client, "/metrics/sessions", since=DAY, until=DAY, group="device")

    assert [(row["device"], row["name"], row["sessions"]) for row in answered["rows"]] == [
        (BOARD_A, "Hallway Speaker", 1),
        (BOARD_A, "Kitchen Speaker", 1),
        (BOARD_A, None, 1),
    ]


def test_a_credential_in_a_recorded_name_reaches_no_answer_as_written(
    client: TestClient, store: Any, caplog: pytest.LogCaptureFixture
) -> None:
    """The name is the one value in one of these rows that a person
    wrote, and the record keeps it exactly as written on purpose:
    `vinga_ro` is granted the record schema and a row is not a display.
    So the projection belongs where a reader is answered, which is here,
    and it is the same `without_url_credential` the session detail
    applies to the same column and the display walk applies to the
    record it was copied from.

    A name that arrived around the write path's refusal is the case:
    userinfo, a `token` parameter and an `authorization` parameter, each
    a distinct sentinel so that an answer keeping any one of them fails
    on that one. The stripped address is asserted present beside the
    absences, because an answer that dropped the column entirely would
    satisfy every absence and tell a reader nothing.

    All four views, because which relation answers is derived rather
    than written per view, and the log beside the body, because a value
    that is kept out of a response and written to a log has not been
    kept out of anything.
    """
    a_day(store, DAY, session="named", device=BOARD_A, device_name=CREDENTIAL_NAME)

    with caplog.at_level(logging.DEBUG):
        for alias in ALIASES:
            response = client.get(
                f"/metrics/{alias}", params={"since": DAY, "until": DAY, "group": "device"}
            )

            assert response.status_code == 200, response.text
            assert [row["name"] for row in response.json()["rows"]] == [
                STRIPPED_NAME
            ], alias
            for secret in SECRET_PARTS:
                assert secret not in response.text, alias

    for secret in SECRET_PARTS:
        assert secret not in _leaked(caplog)


def test_the_stored_name_keeps_the_credential_the_answer_strips(
    client: TestClient, store: Any
) -> None:
    """The control beside the case above, and the reason the projection
    is at the boundary rather than in the view: storage is not a
    surface. A rule applied to the column would rewrite what an operator
    wrote, and the record is what an analyst reads with the grant they
    were given."""
    a_day(store, DAY, session="named", device=BOARD_A, device_name=CREDENTIAL_NAME)

    with store.connect() as connection:
        stored = connection.execute(
            text("select name from record.metrics_sessions_by_device_daily")
        ).scalar()

    assert stored == CREDENTIAL_NAME


def test_every_view_answers_the_device_grouping_with_the_device_first(
    client: TestClient, store: Any
) -> None:
    """All four, because which relation answers is derived from the
    declarations rather than written per view, and because the plan's
    ordering is a claim about every one of them: the day descending,
    then the device ascending.

    The null device is what makes the order worth asserting. It is a
    group of its own and it sorts last, which is where a key nobody can
    attribute belongs.
    """
    a_day(store, DAY, session="known", device=BOARD_A)
    a_day(store, DAY, session="stranger", device=None)
    a_day(store, "2026-05-15", session="later", device=BOARD_A)

    for alias in ALIASES:
        answered = _get(
            client, f"/metrics/{alias}", since=DAY, until="2026-05-15", group="device"
        )
        assert answered["view"]["view"] == alias
        assert [column["name"] for column in answered["view"]["columns"]][:3] == [
            "day",
            "device",
            "name",
        ], alias
        assert [(row["day"], row["device"]) for row in answered["rows"]][:3] == [
            ("2026-05-15", BOARD_A),
            (DAY, BOARD_A),
            (DAY, None),
        ], alias


def test_a_device_narrows_a_per_device_read_and_is_normalized_first(
    client: TestClient, store: Any
) -> None:
    """One board of the three groups a day has, named in the spelling a
    person types: upper case and dash-separated.

    Normalized rather than matched literally, the way `/sessions`
    normalizes the same argument, which is what makes the two spellings
    one filter. A surface that matched the bytes would answer this with
    an empty list, and an empty list is a true answer to a question the
    caller did not ask.
    """
    a_day(store, DAY, session="a", device=BOARD_A)
    a_day(store, DAY, session="b", device=BOARD_B)
    a_day(store, DAY, session="stranger", device=None)

    answered = _get(
        client,
        "/metrics/sessions",
        since=DAY,
        until=DAY,
        group="device",
        device=BOARD_B_AS_TYPED,
    )

    assert [row["device"] for row in answered["rows"]] == [BOARD_B]
    # And without the filter the same window has all three groups,
    # which is what says the filter did the narrowing.
    assert len(
        _get(client, "/metrics/sessions", since=DAY, until=DAY, group="device")["rows"]
    ) == 3


def test_a_device_without_the_grouping_is_refused_rather_than_ignored(
    client: TestClient, store: Any, caplog: pytest.LogCaptureFixture
) -> None:
    """The ungrouped rows are not one device's, so a filter on them
    would answer a different question in a shape the caller could not
    tell apart. Refused rather than ignored, and refused rather than
    taken as a grouping of its own: one argument silently changing what
    another means is worse than either.
    """
    with caplog.at_level(logging.DEBUG):
        response = client.get("/metrics/sessions", params={"device": BOARD_A})

    assert response.status_code == 422
    sentence = refused(response.json(), 422)
    assert "device" in sentence
    assert f"group={GROUPINGS[-1]}" in sentence
    assert BOARD_A not in response.text
    assert BOARD_A not in _leaked(caplog)


def test_a_device_that_is_not_a_mac_is_refused_under_the_grouping(
    client: TestClient, store: Any, caplog: pytest.LogCaptureFixture
) -> None:
    """The filter is held to the same rule every other MAC on this API
    is held to, and the refusal is the same fixed sentence: matched
    literally, a value that is not a MAC would answer an empty list and
    call it the truth."""
    with caplog.at_level(logging.DEBUG):
        response = client.get(
            "/metrics/sessions", params={"group": "device", "device": SENTINEL}
        )

    assert response.status_code == 422
    assert "MAC" in refused(response.json(), 422)
    assert SENTINEL not in response.text
    assert SENTINEL not in _leaked(caplog)


@pytest.mark.parametrize("argument", ["since", "until"])
@pytest.mark.parametrize(
    "value",
    [
        SENTINEL,
        # Spellings `fromisoformat` accepts and this API does not, so the
        # documented form and the accepted form are one form.
        "20260514",
        "2026-W20-4",
        "2026-05-14T12:00:00+00:00",
        "2026-13-01",
    ],
)
def test_a_day_that_is_not_a_utc_calendar_day_is_refused(
    client: TestClient, argument: str, value: str
) -> None:
    response = client.get("/metrics/sessions", params={argument: value})

    assert response.status_code == 422
    assert argument in refused(response.json(), 422)
    assert value not in response.text


@pytest.mark.parametrize(
    "hostile",
    [
        SENTINEL,
        # A relation name and the punctuation that would end a statement,
        # which is what this mapping exists to make impossible.
        "record.sessions",
        "sessions; drop schema record cascade",
        "sessions' or '1'='1",
        # And control characters, which is the half a log line is
        # corrupted by rather than injected through.
        "sessions\r\nlevel=CRITICAL",
        "sessions\x00\x1b[31m",
    ],
)
def test_a_hostile_value_reaches_no_body_no_log_and_no_statement(
    client: TestClient,
    store: Any,
    caplog: pytest.LogCaptureFixture,
    capsys: pytest.CaptureFixture[str],
    hostile: str,
) -> None:
    """The pin behind the closed mapping.

    `{view}` selects a database relation and `group` selects which of
    two relations answers, and neither can be a bound parameter, so what
    makes this safe is that the bytes are a key looked up in a mapping
    derived from the registry and are never anything else. `device` is
    the one that does travel, as a bound value on a column of the
    relation those two chose, and it is normalized or refused before it
    gets there. This sends each hostile value through all three, and
    hunts for it in the response, in both shipped log formats and in the
    process output.

    That a value which resolved to no declaration reaches no statement is
    the case below this one, which counts the opens rather than reading
    SQL.
    """
    a_day(store, DAY)

    with caplog.at_level(logging.DEBUG):
        responses = [
            # Percent-encoded, which is what a client that could send
            # these at all would do: an HTTP library refuses a control
            # character in a URL, and the server decodes the segment
            # before a route ever sees it, so what the handler is handed
            # is the hostile bytes either way.
            client.get("/metrics/" + quote(hostile, safe="")),
            client.get("/metrics/sessions", params={"group": hostile}),
            client.get("/metrics/sessions", params={"since": hostile}),
            client.get(
                "/metrics/sessions", params={"group": "device", "device": hostile}
            ),
        ]

    for response in responses:
        assert response.status_code in (404, 422), response.text
        body = response.json()
        # The structured half names no field either: what these rules are
        # about is a path segment and a query argument, and neither is a
        # field of a body for what was sent to be reported against.
        assert paths(body) == []
        assert hostile not in response.text
    assert hostile not in _leaked(caplog)
    captured = capsys.readouterr()
    assert hostile not in captured.out + captured.err
    # And the store is exactly as it was, since nothing here writes.
    assert _get(client, "/metrics/sessions", since=DAY, until=DAY)["rows"] != []


def test_a_refused_request_opens_no_connection_at_all(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """What the closed mapping is worth, counted rather than asserted.

    A value nothing answers to must be refused before the store is
    reached, for two reasons that are one property. It is what makes the
    refusal honest: an unknown view is a 404 saying where the list is,
    and a 404 that turned into a 500 whenever the database was down
    would be telling a caller the store failed on a request the store
    never saw. And it is the strong half of the injection pin: bytes
    that reach no connection reach no statement, whatever anybody later
    changes about how the query is built.

    Counted at `read_engine`, which is the one door a read opens, so
    this holds however the connection is reached. The failing engine is
    what makes the count meaningful: with storage down, a refusal that
    opened anything would answer 500, and the last case proves the spy
    really is in the path by taking exactly that 500 on a request that
    is valid.
    """
    opens: list[Any] = []

    def failing(database: DatabaseConfig) -> None:
        opens.append(database)
        raise RuntimeError(f"the store is unreachable near {SENTINEL}")

    monkeypatch.setattr(conversations_api, "read_engine", failing)

    refused_with = [
        # Every request-controlled value, each broken on its own: the
        # view, the grouping, either day, and the rule about the pair.
        (404, client.get(f"/metrics/{SENTINEL}")),
        (422, client.get("/metrics/sessions", params={"group": SENTINEL})),
        (
            422,
            client.get(
                "/metrics/sessions", params={"group": "device", "device": SENTINEL}
            ),
        ),
        # And the filter sent without the grouping that admits it, which
        # is refused on the pair rather than on either value.
        (422, client.get("/metrics/sessions", params={"device": SENTINEL})),
        (422, client.get("/metrics/sessions", params={"since": SENTINEL})),
        (422, client.get("/metrics/sessions", params={"until": SENTINEL})),
        (
            422,
            client.get("/metrics/sessions", params={"since": "2026-05-15", "until": DAY}),
        ),
    ]

    for status, response in refused_with:
        assert response.status_code == status, response.text
        assert SENTINEL not in response.text
    assert opens == [], "a refused request opened the store"

    # And the spy is in the path: a request that passes every rule opens
    # it exactly once, and meets the failure this one was armed with.
    assert client.get("/metrics/sessions").status_code == 500
    assert len(opens) == 1


def test_the_gate_is_in_front_of_both_routes(api: FastAPI) -> None:
    """Whether or not there is anything behind them, and including the
    listing, which opens no store at all."""
    for path in ("/metrics", "/metrics/sessions"):
        assert TestClient(api).get(path).status_code == 401


# The storage switches


def test_a_deployment_that_never_recorded_answers_an_empty_list(
    client: TestClient, store: Any
) -> None:
    """Not a refusal and not a 404. The schema is migrated at every boot
    whether or not recording is on, so what a deployment that never
    recorded has is empty tables, and an empty list is the honest answer
    to a question about them (#283)."""
    for alias in ALIASES:
        answered = _get(client, f"/metrics/{alias}")
        assert answered["rows"] == [], alias
        assert answered["view"]["view"] == alias


def test_recording_off_still_serves_what_was_recorded_before(
    monkeypatch: pytest.MonkeyPatch, store: Any
) -> None:
    """Switching recording off stops the writer and not the reader.

    Driven through a real server composed with recording off, because
    that is the deployment the claim is about: there is no
    `ConversationStore` in it at all, and the read opens its own
    connection through `db.read_engine` rather than borrowing one.
    """
    monkeypatch.setenv("VINGA_API_SECRET", TOKEN)
    a_day(store, DAY)

    from vinga_server.app import create_app
    from vinga_server.config import Config

    app = create_app(Config())
    with TestClient(app) as client:
        answered = client.get(
            f"{MOUNT_PATH}/metrics/sessions",
            params={"since": DAY, "until": DAY},
            headers={"Authorization": f"Bearer {TOKEN}"},
        ).json()
        assert app.state.composition.conversations is None, "this server records nothing"

    assert [row["day"] for row in answered["rows"]] == [DAY]
    assert answered["rows"][0]["sessions"] == 1


def test_telemetry_off_is_not_one_behaviour(client: TestClient, store: Any) -> None:
    """The claim the surface must not flatten, asserted per view.

    A session stored under telemetry-off writes its session row and its
    turns and no events, and its turns carry no measured number. So the
    latency view has no row for that day at all, while the event-rate
    view keeps both of its denominators and loses both numerators, and
    the baseline view counts the session and says the switch was off.

    Written through the real `ConversationStore` rather than planted,
    because what is being asserted is what the writer does under the
    switch and not what a suite can insert.
    """
    writer = ConversationStore(DatabaseConfig(), telemetry=False)
    writer.start()
    try:
        writer.open_session(
            "dark",
            100.0,
            {
                "started_at": f"{DAY}T12:00:00+00:00",
                "device": {"mac": "aa:bb:cc:dd:ee:ff"},
                "agent": "sam",
            },
        )
        writer.record_event("dark", "provider_failed", logging.WARNING, {}, 100.0)
        writer.record_turn("dark", _a_turn())
        writer.close_session("dark", 12.5, "client")
    finally:
        writer.stop()

    windowed = {"since": DAY, "until": DAY}

    # No row at all: every stage column of that turn is null, so it
    # contributes to no stage.
    assert _get(client, "/metrics/stage-latency", **windowed)["rows"] == []

    # Both denominators, neither numerator.
    (rates,) = _get(client, "/metrics/event-rates", **windowed)["rows"]
    assert (rates["turns"], rates["sessions"]) == (1, 1)
    assert (rates["provider_failures"], rates["barge_in_suppressions"]) == (0, 0)
    # And zero over one is zero, which is a measurement: the null rule is
    # about a denominator of zero, not about a numerator of zero.
    assert rates["provider_failures_per_turn"] == 0.0

    # The turn counts, and neither token sum was recorded.
    (tokens,) = _get(client, "/metrics/tokens", **windowed)["rows"]
    assert tokens["turns"] == 1
    assert (tokens["input_measured_turns"], tokens["output_measured_turns"]) == (0, 0)
    # Null and not zero: nobody recorded these tokens, which is not the
    # same fact as an agent that consumed none.
    assert (tokens["input_tokens"], tokens["output_tokens"]) == (None, None)

    # And the baseline says the switch was off on that session, which is
    # the context the other three rows are read beside.
    (baseline,) = _get(client, "/metrics/sessions", **windowed)["rows"]
    assert (baseline["sessions"], baseline["telemetry_sessions"]) == (1, 0)
    assert baseline["turns"] == 1


def _a_turn() -> Any:
    """One turn with every measured number on it, so that what the
    telemetry switch drops is visible as a difference rather than as an
    absence the case arranged."""
    from vinga_server.conversations.records import TurnRecord

    return TurnRecord(
        at=101.2,
        conversation="9f0c1d2e3a4b5c6d7e8f90a1b2c3d4e5",
        agent="sam",
        heard="turn the light on",
        reply="Done.",
        asr_ms=210,
        first_token_ms=340,
        llm_ms=900,
        tts_first_audio_ms=260,
        input_tokens=512,
        output_tokens=24,
    )
