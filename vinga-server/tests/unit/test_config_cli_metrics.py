"""The `metric` noun: two verbs over the API, and what they print.

The fourth reading of the conversation record and the one that answers
about days. It reads it the way every other verb here does, as requests
through the client seam against a server built per command: there is no
local-database path and there is not going to be one, which is the rule
`config/cli.py` states and which the plan's review round put back after
a first draft promised a break-glass.

Four properties this file exists for.

- **The grammar is the one the cli-guide licenses.** The noun is
  singular because `show` addresses one entry, the verbs are core-set
  words rather than a noun in the verb slot, the view is a leading
  positional under the route's own parameter name, and the three things
  that bound the answer are flags because none of them addresses a view.
- **The caveats reach the terminal, asserted by what they say.** What a
  number here cannot be made to say is declared once on the view
  registry and carried by every answer, and this holds the rendering to
  printing it: the sentences are named here, so a renderer that dropped
  them fails even though it would still match its own output. A drift
  check would prove the opposite thing, that an artifact matches its
  generator, and never that the generator kept anything.
- **A refusal quotes nothing back.** The view is the one word in this
  grammar that selects a database relation, and the grouping is a closed
  vocabulary; both are refused by the API in its own fixed sentence, and
  this hunts the value that was typed through stdout, stderr and both
  shipped log formats.
- **An empty window is an answer rather than a refusal.** A window with
  nothing in it and a deployment that never recorded read the same way,
  which is the contract `conversations/api.py` states about empty shapes
  and which a CLI could quietly reverse by printing nothing.
"""

import contextlib
import io
import logging
from pathlib import Path
from typing import Any

import httpx
import pytest

from tests.support.config_cli import answering, runner
from tests.support.stores import plant_event, plant_session, plant_turn
from vinga_server import logs
from vinga_server.config import cli
from vinga_server.config.models import DatabaseConfig
from vinga_server.conversations.store import open_conversations
from vinga_server.conversations.views import COMMON, VIEWS

# The day the planted rows land on, and a window around it. A fixed day
# rather than today's, so a case that asserts an exact row asserts about
# what it planted rather than about when it ran.
DAY = "2026-05-14"

NEXT_DAY = "2026-05-15"

SINCE = "2026-05-01"

UNTIL = "2026-05-20"

# A window this deployment cannot have recorded anything in, used where
# the subject is what an empty answer reads like rather than what a
# missing table does.
EMPTY_SINCE = "2025-01-01"

EMPTY_UNTIL = "2025-01-31"

# Shaped so a substring check for it cannot match by accident, and
# planted wherever a refusal might carry it back out.
SENTINEL = "sk-test-91c4a7de-never-a-real-credential"

# Everything a terminal reads as an instruction rather than as text,
# planted in an agent name because an agent name is an operator's text
# and two of these views carry it in a cell.
STEERING = "\x1b[31mred\x1b[0m\x07\tone\rtwo\nthree"


@pytest.fixture
def run(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    return runner(monkeypatch)


@pytest.fixture
def store() -> Any:
    """The migrated store, on the lane's own database.

    Boot is what migrates the `record` schema on a deployment, and a
    suite that plants rows has to stand where boot stood. The autouse
    truncation between tests empties the tables and leaves the views.
    """
    engine = open_conversations(DatabaseConfig())
    try:
        yield engine
    finally:
        engine.dispose()


def a_day(store: Any, day: str, *, agent: str = "sam", session: str | None = None) -> None:
    """One session opened at noon on a named UTC day, with a measured
    turn and one counted event on it.

    Noon rather than midnight so the day a row lands on is the day that
    was asked for whichever way a reader's own timezone leans, which is
    the property the views are cut on.
    """
    named = session if session is not None else day
    with store.begin() as connection:
        plant_session(connection, named, f"{day}T12:00:00+00:00", agent=agent)
        plant_turn(
            connection, named, 0, agent=agent, asr_ms=120, input_tokens=7, output_tokens=3
        )
        plant_event(connection, named, 0, "provider_failed")


def leaked(caplog: pytest.LogCaptureFixture) -> str:
    """Everything this server and this command logged, in both shipped
    formats.

    Filtered to this project's own channels, and the reason is the test
    environment rather than a weakening of the claim: Starlette's
    TestClient is built on a vendored `httpx2` whose logger the CLI's
    own quieting does not name, and what it writes is the request line
    of the caller's own terminal rather than anything this code emitted.
    Against a real server the CLI quiets `httpx` and `httpcore` around
    every request, which is the same property on the shipped path.
    """
    return "".join(
        record.getMessage() + str(record.__dict__) + logs.JsonFormatter().format(record)
        for record in caplog.records
        if record.name.startswith("vinga_server")
    )


def plain(declared: str) -> str:
    """One declared statement as a terminal should read it, computed
    here rather than borrowed from the renderer.

    The statements are Markdown because two of the three surfaces that
    render them are: the committed reference and the API's contract. A
    terminal is the third and is not one, so the emphasis and the
    code-span markers come out. Written out in this file on purpose,
    because a case that asked the renderer what it does would agree with
    it whatever it did.
    """
    return declared.replace("**", "").replace("`", "")


def said(printed: str) -> str:
    """One rendering with its line breaks taken out.

    The declared statements are paragraphs, wrapped here at the width
    every other piece of generated prose in this repository is wrapped
    to, so a sentence a case names spans a line break wherever the
    wrapping happens to fall. What is being asserted is that the words
    are there, not where they broke.
    """
    return " ".join(printed.split())


def out(run, capsys: pytest.CaptureFixture[str], *argv: str) -> tuple[int, str, str]:
    capsys.readouterr()
    code = run(*argv)
    captured = capsys.readouterr()
    return code, captured.out, captured.err


def leaf(words: tuple[str, ...]) -> Any:
    """One command of the built tree, found by its own words."""
    found: Any = cli.command()
    for word in words:
        found = found.commands[word]
    return found


# The grammar, held to docs/architecture/cli-guide.md


def test_the_noun_is_singular_and_carries_two_core_set_verbs() -> None:
    """Singular because `show` addresses one entry, which is the guide's
    naming rule: a named view is an entry of a published vocabulary the
    way an agent is an entry of the configuration.

    And the verbs are `list` and `show` rather than a view name in the
    verb slot. `metric latency` reads shorter and is what the rule about
    a noun in the verb slot rejects; `agent preview` is the precedent
    for not granting that exception to the first command that asks.
    """
    words = {row.words for row in cli.COMMANDS if row.words[0].startswith("metric")}

    assert words == {("metric", "list"), ("metric", "show")}
    assert ("metric",) in cli.GROUPS
    assert not [path for path in cli.GROUPS if path[0] == "metrics"]
    assert {view.alias for view in VIEWS} & {row[1] for row in words} == set()


def test_the_view_leads_as_a_positional_and_the_window_follows_as_flags() -> None:
    """The address first, in the route's own parameter name, and the
    three things that bound the answer as flags behind it.

    `--since`, `--until` and `--group` address no view: two say which
    days to answer about and one says how to break the rows down, which
    is exactly what `--device` and `--limit` are to a session listing.
    A positional would make the line read as a four-part address.
    """
    shown = leaf(("metric", "show"))
    arguments = [
        parameter
        for parameter in shown.params
        if getattr(parameter, "param_type_name", "") == "argument"
    ]
    options = {
        name
        for parameter in shown.params
        if getattr(parameter, "param_type_name", "") == "option"
        for name in parameter.opts
    }

    assert [parameter.name for parameter in arguments] == ["view"]
    assert arguments[0].required
    assert {"--since", "--until", "--group"} <= options

    listed = leaf(("metric", "list"))
    assert not [
        parameter
        for parameter in listed.params
        if getattr(parameter, "param_type_name", "") == "argument"
    ]


def test_the_positional_is_the_whole_address_the_route_is_written_in() -> None:
    """One identity segment and no more, built by the act rather than by
    a string here, so the CLI's address and the document's path are the
    same address. The contract check holds the templated form; this
    holds a real word."""
    assert cli.SHOW_METRIC.path(cli.Invocation(view="stage-latency")) == "/metrics/stage-latency"
    assert cli.LIST_METRICS.path(cli.Invocation()) == "/metrics"


def asked(run, answer: dict[str, Any]) -> list[httpx.URL]:
    """Every address this runner's commands reach, with the answer they
    are given.

    Through the transport seam rather than by reading the query builder,
    so what is asserted is the request that actually leaves: a bound
    that never made it onto the wire would pass an inspection of the
    function that assembled it.
    """
    seen: list[httpx.URL] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request.url)
        return httpx.Response(
            200, json=answer, headers={"content-type": "application/json"}
        )

    answering(run, handler)
    return seen


def an_empty_answer(alias: str) -> dict[str, Any]:
    """What the API answers for a window with nothing in it, built from
    the registry so the shape is the one the document declares."""
    [view] = [one for one in VIEWS if one.alias == alias]
    return {
        "view": {
            "view": view.alias,
            "relation": view.qualified,
            "question": view.question,
            "denominator": view.denominator,
            "telemetry_off": view.telemetry_off,
            "columns": [
                {
                    "name": column.name,
                    "type": column.type,
                    "meaning": column.meaning,
                    "units": column.units,
                    "nullable": column.nullable,
                    "formula": column.formula,
                    "key": column.key,
                }
                for column in view.columns
            ],
        },
        "common": [
            {"heading": group.heading, "notes": list(group.notes)} for group in COMMON
        ],
        "since": SINCE,
        "until": UNTIL,
        "group": "all",
        "rows": [],
    }


def test_only_the_bounds_that_were_written_travel(run, capsys) -> None:
    """The rule the session filters follow: an absent flag is an
    argument the request does not carry, so the API's own defaults are
    the defaults, said once and read back off the answer.

    A client that sent `since=` empty would be naming a day nothing can
    parse and would turn a bare `metric show` into a refusal.
    """
    seen = asked(run, an_empty_answer("sessions"))
    capsys.readouterr()

    assert run("metric", "show", "sessions") == 0
    assert seen[-1].params.multi_items() == []

    assert run("metric", "show", "sessions", "--since", SINCE, "--group", "all") == 0
    assert dict(seen[-1].params.multi_items()) == {"since": SINCE, "group": "all"}
    assert "until" not in seen[-1].params

    assert run("metric", "show", "sessions", "--until", UNTIL) == 0
    assert dict(seen[-1].params.multi_items()) == {"until": UNTIL}


def test_both_verbs_are_requests_with_no_second_way_in() -> None:
    """There is no `--local`, on either verb and anywhere in this
    grammar. A command that touches the record is a request like every
    other, which is the amendment to #190 and what the plan's review
    round restored after its first draft promised a break-glass."""
    for words in (("metric", "list"), ("metric", "show")):
        [row] = [one for one in cli.COMMANDS if one.words == words]
        assert row.acts()
        assert all(act.method == "GET" for act in row.acts())
        assert not row.destroys
        assert "--local" not in {
            name for parameter in leaf(words).params for name in parameter.opts
        }


# What the two verbs print


def test_the_listing_describes_every_view_the_registry_declares(run, capsys) -> None:
    """The vocabulary, in declaration order, each with the question it
    answers and the columns a row of it carries. Nothing here is written
    in the CLI: the words are the declaration's, carried through the
    answer, so a view added to the registry is described by this command
    the day it is added."""
    code, printed, err = out(run, capsys, "metric", "list")

    assert (code, err) == (0, "")
    listed = said(printed)
    for view in VIEWS:
        assert f"\n{view.alias}\n" in f"\n{printed}"
        assert view.qualified in printed
        # Every column of the view, in its order, each with the unit of
        # its value and not its SQL type: what a reader about to quote a
        # number needs is what the number is of. A column whose value
        # has no unit says so in the declaration and is printed bare
        # rather than with the word `none` after it.
        assert "columns: " + ", ".join(
            column.name if column.units == "none" else f"{column.name} ({column.units})"
            for column in view.columns
        ) in listed
    # Declaration order, which is the order a reader meets them in.
    assert [
        line for line in printed.splitlines() if line in {view.alias for view in VIEWS}
    ] == [view.alias for view in VIEWS]


def test_an_answer_is_a_borderless_table_of_the_columns_it_declares(
    run, store, capsys
) -> None:
    """The headings are the answer's own column names and nothing else,
    so a column added to a view arrives in this table without a word
    being written here. Columns rather than blocks because every cell of
    a metrics row is a number, a day or a short name."""
    a_day(store, DAY)
    [view] = [one for one in VIEWS if one.alias == "sessions"]

    code, printed, err = out(
        run, capsys, "metric", "show", "sessions", "--since", SINCE, "--until", UNTIL
    )

    assert (code, err) == (0, "")
    [heading] = [line for line in printed.splitlines() if line.startswith("DAY")]
    assert heading.split() == [column.name.upper() for column in view.columns]
    [row] = [line for line in printed.splitlines() if line.startswith(DAY)]
    assert row.split() == [DAY, "1", "1", "1"]
    # No borders and no trailing whitespace: a line ends where its last
    # cell does.
    assert all(line == line.rstrip() for line in printed.splitlines())


def test_the_window_the_answer_used_is_stated_once_over_the_whole_answer(
    run, store, capsys
) -> None:
    """A boundary is said once over the group it is true of, and the two
    days are the ones the server used rather than the ones that were
    typed, so a caller that named neither reads its defaults here."""
    a_day(store, DAY)

    code, printed, _ = out(
        run, capsys, "metric", "show", "sessions", "--since", SINCE, "--until", UNTIL
    )

    assert code == 0
    [stated] = [line for line in printed.splitlines() if line.startswith(cli.METRIC_WINDOW)]
    assert stated == f"{cli.METRIC_WINDOW}: {SINCE} to {UNTIL}, {cli.METRIC_WINDOW_ENDS}"


def test_a_rate_with_no_denominator_prints_the_placeholder_and_never_a_zero(
    run, store, capsys
) -> None:
    """The declared rule, rendered rather than flattened. A rate whose
    denominator is zero is null and not zero, because nothing happened
    and nothing could have happened are different facts; a renderer that
    wrote `0` for one would report a blind day as a quiet one.

    A session and an event on a day with no turn is exactly that case:
    the failures are counted, the turns they would be divided by are
    zero, and the per-turn rate is null.
    """
    with store.begin() as connection:
        plant_session(connection, "quiet", f"{DAY}T12:00:00+00:00")
        plant_event(connection, "quiet", 0, "provider_failed")

    code, printed, _ = out(
        run, capsys, "metric", "show", "event-rates", "--since", SINCE, "--until", UNTIL
    )

    assert code == 0
    [row] = [line for line in printed.splitlines() if line.startswith(DAY)]
    [heading] = [line for line in printed.splitlines() if line.startswith("DAY")]
    cells = dict(zip(heading.split(), row.split(), strict=True))
    assert cells["TURNS"] == "0"
    assert cells["PROVIDER_FAILURES"] == "1"
    assert cells["PROVIDER_FAILURES_PER_TURN"] == cli.NOTHING_THERE


def test_the_rows_come_back_newest_day_first(run, store, capsys) -> None:
    """The order the API answers in, printed as it arrived: a reader of
    a trend wants the newest day at the top."""
    a_day(store, DAY)
    a_day(store, NEXT_DAY)

    code, printed, _ = out(
        run, capsys, "metric", "show", "sessions", "--since", SINCE, "--until", UNTIL
    )

    assert code == 0
    days = [line.split()[0] for line in printed.splitlines() if line[:1].isdigit()]
    assert days == [NEXT_DAY, DAY]


# An empty answer


def test_a_window_with_nothing_in_it_says_so_rather_than_printing_a_heading(
    run, store, capsys
) -> None:
    """An empty table with a heading over it reads as a rendering that
    failed. The sentence says what an empty answer means here, and the
    command leaves through zero: an empty window is an ordinary answer
    and never a refusal."""
    a_day(store, DAY)

    code, printed, err = out(
        run,
        capsys,
        "metric",
        "show",
        "sessions",
        "--since",
        EMPTY_SINCE,
        "--until",
        EMPTY_UNTIL,
    )

    assert (code, err) == (0, "")
    assert cli.NO_METRIC_ROWS in printed
    assert "DAY" not in printed


@pytest.mark.parametrize("alias", [view.alias for view in VIEWS])
def test_a_deployment_that_never_recorded_answers_the_same_way(run, capsys, alias) -> None:
    """No store fixture and nothing planted, which is the whole case: a
    deployment that has recorded nothing has migrated empty tables, and
    an empty list is the honest answer to a question about them. Not a
    404, not a refusal, and not silence."""
    code, printed, err = out(run, capsys, "metric", "show", alias)

    assert (code, err) == (0, "")
    assert cli.NO_METRIC_ROWS in printed


def test_the_vocabulary_answers_on_a_deployment_that_never_recorded(run, capsys) -> None:
    """`metric list` describes what the schema declares rather than what
    anybody wrote, so it says the same thing on an empty deployment as
    on a busy one."""
    code, printed, err = out(run, capsys, "metric", "list")

    assert (code, err) == (0, "")
    assert all(view.alias in printed for view in VIEWS)


# What a number here cannot be made to say


# The three limits, named by what they say rather than by where they
# live. Quoted here so that a renderer which dropped one fails: a check
# that compared the output against whatever the registry currently holds
# would pass over an empty registry and prove nothing about the sentence
# a reader needs.
ZERO_DENOMINATOR = "A rate is null when its denominator is zero, never zero."

RETENTION_FLOOR = "a rate read outside the events' own retention window is a floor"

MISSING_MEASUREMENT = (
    "A missing measurement has more than one cause, and these views cannot tell them "
    "apart."
)

A_DAY_IS_UTC = "A day is a UTC day."

COUNTING_IS_PER_ROW = "Counting is per stored row."

PERCENTILES_INTERPOLATE = "Percentiles interpolate."

THE_SWITCH_IS_NAMED_METRICS = "sessions.metrics is the telemetry switch"

READING_RULES = (
    A_DAY_IS_UTC,
    COUNTING_IS_PER_ROW,
    ZERO_DENOMINATOR,
    PERCENTILES_INTERPOLATE,
    RETENTION_FLOOR,
    MISSING_MEASUREMENT,
    THE_SWITCH_IS_NAMED_METRICS,
)


@pytest.mark.parametrize("rule", READING_RULES, ids=[rule[:32] for rule in READING_RULES])
def test_the_listing_says_what_a_number_cannot_be_made_to_say(run, capsys, rule) -> None:
    """The third consumer of the declared limitations, and the one a
    person reads. The reference renders them and the API's contract
    carries them; this is the surface an operator with no psql is on,
    which is who this whole namespace exists for."""
    code, printed, _ = out(run, capsys, "metric", "list")

    assert code == 0
    assert rule in said(printed)


@pytest.mark.parametrize("rule", READING_RULES, ids=[rule[:32] for rule in READING_RULES])
def test_an_answer_says_them_beside_the_numbers_they_qualify(run, store, capsys, rule) -> None:
    """Beside the numbers and not only on the vocabulary listing, because
    the moment a reader is most likely to be missing them is the moment
    they are about to quote one."""
    a_day(store, DAY)

    code, printed, _ = out(
        run, capsys, "metric", "show", "event-rates", "--since", SINCE, "--until", UNTIL
    )

    assert code == 0
    assert rule in said(printed)


def test_every_declared_statement_reaches_the_terminal(run, capsys) -> None:
    """And the completeness half: each of the registry's headings and
    each statement under it, so a caveat added to the one home arrives
    here without an edit. The named sentences above are what makes this
    pair worth having; this is what stops a new one going missing."""
    code, printed, _ = out(run, capsys, "metric", "list")

    assert code == 0
    for group in COMMON:
        assert group.heading in printed
        for note in group.notes:
            assert plain(note) in said(printed)


def test_each_view_says_what_telemetry_off_does_to_it_in_particular(run, capsys) -> None:
    """Per view rather than uniform, which the surface must not flatten:
    the latency view produces no row at all for a turn stored under the
    switch, while the event-rate view keeps its denominators and loses
    its numerators."""
    code, printed, _ = out(run, capsys, "metric", "list")

    assert code == 0
    joined = said(printed)
    for view in VIEWS:
        assert plain(view.telemetry_off) in joined
    assert "contributes no row here at all" in joined
    assert "raises both denominators and neither numerator" in joined


@pytest.mark.parametrize("alias", [view.alias for view in VIEWS])
def test_an_answer_carries_the_view_own_telemetry_off_sentence(
    run, store, capsys, alias
) -> None:
    """On `show` and per view, not only on the vocabulary listing: the
    numbers are what the sentence qualifies, and the listing is a page
    nobody re-reads at the moment they are about to quote one. Asserted
    for every view because the behaviour differs by view, which is
    exactly what a rendering that dropped the sentence would flatten."""
    a_day(store, DAY)
    [view] = [one for one in VIEWS if one.alias == alias]

    code, printed, _ = out(
        run, capsys, "metric", "show", alias, "--since", SINCE, "--until", UNTIL
    )

    assert code == 0
    assert plain(view.telemetry_off) in said(printed)


# Refusals, which quote nothing back


@pytest.mark.parametrize(
    "hostile",
    [
        SENTINEL,
        # A relation name and the punctuation that would end a
        # statement, which the closed mapping exists to make impossible.
        "record.sessions",
        "sessions; drop schema record cascade",
        "sessions' or '1'='1",
        # And control characters, which corrupt a log line rather than
        # inject through it.
        "sessions\r\nlevel=CRITICAL",
    ],
)
def test_a_hostile_view_reaches_no_stream_and_no_log(
    run, store, capsys, caplog, hostile
) -> None:
    """The view is the one word in this grammar that selects a database
    relation, so what is asserted is that it comes back out of nothing.

    Hunted through stdout, stderr and both shipped log formats, because
    a value that reached a record as an argument is a value the
    formatter puts back into the line. Which of two fixed sentences the
    refusal is depends on how far the value got: a word reaches the
    route and meets the API's own 404, while one carrying an encoded
    newline does not match the mount at all and meets this client's
    sentence for a body it does not recognize. Neither quotes anything,
    which is the property, and asserting on the wording of one of them
    is the case below.
    """
    with caplog.at_level(logging.DEBUG):
        code, printed, err = out(run, capsys, "metric", "show", hostile)

    assert code == 1
    assert printed == ""
    assert err.endswith("\n") and len(err.splitlines()) == 1
    for where in (printed, err, leaked(caplog)):
        assert hostile not in where


def test_an_unknown_view_is_told_where_the_list_of_them_is(run, store, capsys) -> None:
    """The API's own sentence, relayed unchanged: what a caller needs is
    where the vocabulary is published rather than an echo of the word it
    sent, which is the rule `conversations/api.py` already states for
    this surface."""
    code, printed, err = out(run, capsys, "metric", "show", "latency")

    assert code == 1
    assert printed == ""
    assert "GET /metrics" in err
    assert "latency" not in err


@pytest.mark.parametrize(
    "hostile",
    [
        SENTINEL,
        # And control characters, the way the view above gets them: a
        # CRLF that would append a log line, a NUL, and a CSI sequence
        # that would steer the terminal a refusal is read on. The
        # grouping travels as a query argument, so it reaches the API
        # percent-encoded and meets the API's own refusal.
        "device\r\nlevel=CRITICAL",
        "device\x00all",
        "device\x1b[31mall",
    ],
)
def test_an_unknown_grouping_is_refused_without_quoting_it(
    run, store, capsys, caplog, hostile
) -> None:
    """Refused rather than ignored: a caller asking for a breakdown and
    quietly answered with the ungrouped rows could not tell the two
    apart. The vocabulary is the API's closed set, said in the API's own
    sentence, so this client keeps no copy of it to fall out of step.
    Hunted through both streams and both shipped log formats, the way
    every refusal in this file is."""
    with caplog.at_level(logging.DEBUG):
        code, printed, err = out(
            run, capsys, "metric", "show", "sessions", "--group", hostile
        )

    assert code == 1
    assert "group" in err
    assert printed == ""
    for where in (printed, err, leaked(caplog)):
        assert hostile not in where
        assert "\x1b" not in where and "\x00" not in where and "\x07" not in where


@pytest.mark.parametrize("flag", ["--since", "--until"])
@pytest.mark.parametrize(
    "value",
    [
        SENTINEL,
        # Spellings `fromisoformat` accepts and this API does not, so
        # the documented form and the accepted form are one form.
        "20260514",
        "2026-W20-4",
        "2026-13-01",
    ],
)
def test_a_day_that_is_not_a_utc_calendar_day_is_refused_without_quoting_it(
    run, store, capsys, caplog, flag, value
) -> None:
    """No second parser in front of the API's: what a day has to be is
    the API's rule, said in the API's own fixed sentence, and a rule
    restated here would be a second vocabulary for one refusal."""
    with caplog.at_level(logging.DEBUG):
        code, printed, err = out(run, capsys, "metric", "show", "sessions", flag, value)

    assert code == 1
    assert flag.removeprefix("--") in err
    assert printed == ""
    for where in (printed, err, leaked(caplog)):
        assert value not in where


def test_a_window_wider_than_the_cap_is_refused_rather_than_narrowed(
    run, store, capsys
) -> None:
    """An answer trimmed to fit would be less than what was asked for
    while nothing in it said so, which is the decision the plan records
    and this holds the client to relaying rather than softening."""
    code, printed, err = out(
        run, capsys, "metric", "show", "sessions", "--since", "2020-01-01", "--until", UNTIL
    )

    assert code == 1
    assert printed == ""
    assert "366" in err


# Nothing an answer carries can steer a terminal


class Terminal(io.StringIO):
    """A stream that says it is a terminal, which is the one thing the
    interactive branches read."""

    def isatty(self) -> bool:
        return True


def test_a_cell_an_operator_wrote_cannot_steer_the_terminal(run, store, capsys) -> None:
    """An agent name is an operator's text and two of these views carry
    it in a cell, so every cell goes through the same bounding the
    session listing's do. The two streams are compared byte for byte at
    a terminal and through a pipe, because what may not vary with the
    terminal is the data itself."""
    a_day(store, DAY, agent=STEERING)

    code, printed, _ = out(
        run, capsys, "metric", "show", "tokens", "--since", SINCE, "--until", UNTIL
    )
    piped = printed

    assert code == 0
    assert "\x1b" not in printed
    assert "\x07" not in printed
    assert "\t" not in printed

    capsys.readouterr()
    with contextlib.redirect_stdout(Terminal()) as terminal:
        assert run("metric", "show", "tokens", "--since", SINCE, "--until", UNTIL) == 0
    assert terminal.getvalue() == piped


def test_a_heading_an_answer_wrote_cannot_steer_the_terminal(run, capsys) -> None:
    """The headings are the answer's own column names, so they are an
    answer's text the way a cell is and go through the same bounding.
    A synthetic response rather than a planted row, because no store
    this server runs can put a control character into a column name:
    the case is a compromised or impersonated API, which is exactly
    what the cell rule is for.

    The planted name carries a clear-screen sequence, a bell, a
    carriage return and a newline; asserted the way the cell case is,
    by hunting the instruction bytes through the whole rendering."""
    hostile = "day\x1b[2Jcleared\x07\rone\ntwo"
    answer = an_empty_answer("sessions")
    answer["view"]["columns"][0]["name"] = hostile
    answer["rows"] = [
        {
            column["name"]: DAY if column["name"] == hostile else 1
            for column in answer["view"]["columns"]
        }
    ]
    asked(run, answer)

    code, printed, err = out(run, capsys, "metric", "show", "sessions")

    assert (code, err) == (0, "")
    assert "\x1b" not in printed
    assert "\x07" not in printed
    assert "\r" not in printed
    # The other headings still arrive, so the bounding mangled the one
    # hostile name rather than dropping the table.
    assert "SESSIONS" in printed and "TURNS" in printed


@pytest.mark.parametrize("broken", ["missing", "extra", "null"])
def test_a_row_that_breaks_its_own_declaration_is_refused_not_softened(
    run, capsys, caplog, broken
) -> None:
    """The declaration the answer itself carries is what a row is held
    to: a row missing a declared column, one carrying an undeclared
    key, and a null in a column declared non-nullable are all bodies
    this client cannot read, not data.

    The missing case is the one that lies rather than crashes: the
    renderer prints the placeholder for an absent value, and the
    placeholder means null, so a response missing the non-null `turns`
    would report a legitimate null nobody sent. Refused with the same
    fixed sentence every unreadable answer meets, nothing of the body
    in it and no traceback behind it."""
    answer = an_empty_answer("sessions")
    row: dict[str, Any] = {
        column["name"]: 1 for column in answer["view"]["columns"]
    }
    row["day"] = DAY
    # A value of the row planted where a refusal might quote it back.
    row["sessions"] = SENTINEL
    if broken == "missing":
        del row["turns"]
    elif broken == "extra":
        row["undeclared"] = SENTINEL
    else:
        row["turns"] = None
    answer["rows"] = [row]
    asked(run, answer)

    with caplog.at_level(logging.DEBUG):
        code, printed, err = out(run, capsys, "metric", "show", "sessions")

    assert code == 1
    assert printed == ""
    assert cli.UNREADABLE_READ in err
    assert err.endswith("\n") and len(err.splitlines()) == 1
    for where in (printed, err, leaked(caplog)):
        assert SENTINEL not in where


def test_a_read_says_nothing_about_the_run_it_made(run, store, capsys) -> None:
    """Stdout carries the thing a caller came for and stderr carries
    everything about the run that produced it. A read produced nothing
    about its own run, so stderr is empty and the answer redirects
    whole."""
    a_day(store, DAY)

    for argv in (("metric", "list"), ("metric", "show", "sessions")):
        code, printed, err = out(run, capsys, *argv)
        assert (code, err) == (0, "")
        assert printed.endswith("\n")
