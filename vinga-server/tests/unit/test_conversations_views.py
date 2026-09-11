"""The view declarations, and the reference rendered from them.

The database half of these views is asserted where a database is:
`tests/integration/test_conversations_views.py` runs the numbers, the
agreement with the migrated chain, and the analyst's read. What is left
here is what needs no instance, and it is the half a reader of the
committed page depends on: that every column really is described, that
the rendering is deterministic and the committed copy matches it, and
that the page says the things a column table cannot (the retention
limit, the column that kept an old name).

One case here is not about documentation at all. The no-leak line says
what a person said never leaves the store as anything but content under
its own switch, and a view is a new way out of it, so the bodies are
swept for a reference to a content column. It is cheap, it is exact, and
it is the kind of thing that would otherwise be re-argued in every
review of a fifth view.
"""

from pathlib import Path

from vinga_server.conversations import docgen
from vinga_server.conversations.views import (
    ALIASES,
    BARGE_IN_SUPPRESSED,
    BY_DEVICE_VIEWS,
    COMMON,
    DAY,
    DEFINED,
    DEVICE,
    GROUPED,
    NAME,
    PROVIDER_FAILED,
    STAGES,
    VIEWS,
)

COMMITTED = Path(__file__).resolve().parents[3] / "docs" / "reference" / "metrics-views.md"

REGENERATE = (
    "docs/reference/metrics-views.md is stale; regenerate it with "
    "`uv run vinga-server conversations views > ../docs/reference/metrics-views.md`"
)

# The columns that hold what somebody said, spelled as a query would
# reach them. `sessions.text` is the text switch rather than an
# utterance, and it is in the list anyway: no view has a reason to read
# it, and a sweep with an exception in it is a sweep somebody widens.
CONTENT_REACHES = (
    ".heard",
    ".reply",
    ".title",
    ".result",
    ".arguments",
    ".text",
    "->> 'text'",
    "->>'text'",
)


def flat(text: str) -> str:
    """The document with its line breaks flattened, for the reason the
    schema docgen suite gives: the prose is wrapped at a fixed width, so
    an assertion that broke on rewrapping would be an assertion about
    the wrapping."""
    return " ".join(text.split())


def test_every_declared_column_is_described() -> None:
    """The matrix is the page's only source, so a column with a blank
    cell in it is invisible rather than merely undocumented. Every field
    is required, not only the prose ones: a column with no unit is one
    whose number a reader has to guess the meaning of."""
    holes = [
        f"{view.name}.{column.name}.{field}"
        for view in DEFINED
        for column in view.columns
        for field in ("type", "meaning", "units", "formula")
        if not getattr(column, field).strip()
    ]
    assert not holes, f"declarations with nothing in them: {', '.join(holes)}"


def test_every_view_states_its_question_and_both_sentences() -> None:
    """The three pieces of prose a number cannot carry: what the view is
    for, what its denominator is, and what telemetry-off does to it."""
    holes = [
        f"{view.name}.{field}"
        for view in DEFINED
        for field in ("question", "denominator", "telemetry_off")
        if not getattr(view, field).strip()
    ]
    assert not holes, f"views with nothing to say: {', '.join(holes)}"


def test_every_view_declares_what_a_row_is_unique_by() -> None:
    """The `GROUP BY`, as a declaration. The read surface orders a page
    on exactly these columns and nothing else makes that order total, so
    a view that declared none would be served in whatever order the
    planner felt like."""
    for view in DEFINED:
        names = [column.name for column in view.keys]
        assert names, f"{view.name} declares no key column"
        # The day first, because the read surface windows on it and
        # orders it descending while the rest ascend.
        assert names[0] == DAY, view.name


def test_every_alias_is_derived_from_the_name_and_unique() -> None:
    """The word a request spells, and the closed mapping behind it. It
    is derived rather than written down, which is what stops the set a
    caller may ask for drifting from the set declared here."""
    assert set(ALIASES) == {"stage-latency", "tokens", "event-rates", "sessions"}
    assert len(ALIASES) == len(VIEWS)
    for alias, view in ALIASES.items():
        assert view.alias == alias
        # Kebab-case, the spelling the CLI guide gives a word a person
        # types, and never the relation's own name.
        assert "_" not in alias and alias.islower()
        assert alias != view.name


def test_a_sibling_answers_to_the_word_the_view_it_mirrors_answers_to() -> None:
    """The infix comes off the alias, so a question is one question and
    the grouping is what picks the relation. Two declarations sharing an
    alias is exactly why `ALIASES` is built from `VIEWS` and not from
    every relation: a caller's word has to resolve to one thing."""
    for view, sibling in zip(VIEWS, BY_DEVICE_VIEWS, strict=True):
        assert sibling.alias == view.alias
        assert sibling.name != view.name
        assert sibling.name.endswith("_by_device_daily")
    assert len(ALIASES) == len(VIEWS)
    assert len({view.name for view in DEFINED}) == len(DEFINED)


def test_a_sibling_is_the_view_it_mirrors_plus_the_device_and_its_label() -> None:
    """Derived rather than restated, which is what stops the pair coming
    to describe the same number two ways. The day stays first and the
    two new columns go directly behind it, so the read surface's
    ordering is the day, then the device, then whatever the mirrored
    view was already cut by."""
    for view, sibling in zip(VIEWS, BY_DEVICE_VIEWS, strict=True):
        assert [column.name for column in sibling.columns] == [
            view.columns[0].name,
            DEVICE,
            NAME,
            *[column.name for column in view.columns[1:]],
        ], sibling.name
        assert [column.name for column in sibling.keys][:2] == [DAY, DEVICE]
        # The label is not part of what makes a row one row: it is
        # whatever the device is called, which is not an identity.
        assert NAME not in [column.name for column in sibling.keys]
        # Everything the mirrored view said about a column, said once.
        assert sibling.columns[3:] == view.columns[1:]
        assert sibling.telemetry_off == view.telemetry_off
        assert sibling.question.startswith(view.question)


def test_the_label_is_declared_null_rather_than_left_out() -> None:
    """Null in every row until a copy of the label lands on the `record`
    side, and selected as a literal so the columns a caller reads do not
    move on the day it arrives. The analyst role is revoked on `domain`,
    so this cannot be a join and nobody should turn it into one."""
    for sibling in BY_DEVICE_VIEWS:
        [label] = [column for column in sibling.columns if column.name == NAME]
        assert label.nullable
        assert "NULL::text AS name" in sibling.body, sibling.name
        assert "domain" not in sibling.body


def test_both_combining_views_join_their_streams_null_safely() -> None:
    """The two that combine independently aggregated streams, and the
    join that makes a null device one group rather than one row per
    stream.

    Asserted on the declaration as well as on the numbers, because this
    is a rule about how the next view of this shape is written: `=` is
    what would be wrong, and the numbers case next door is what catches
    it having been written.
    """
    from vinga_server.conversations.views import (
        EVENT_RATES_BY_DEVICE,
        SESSIONS_BY_DEVICE,
    )

    for view in (EVENT_RATES_BY_DEVICE, SESSIONS_BY_DEVICE):
        assert "IS NOT DISTINCT FROM spine.device" in view.body, view.name
        assert "IS NOT DISTINCT FROM spine.day" in view.body, view.name
        # No `=` join on either key, which is the thing being ruled out.
        assert "= spine.device" not in view.body, view.name
        assert "= spine.day" not in view.body, view.name
        # And a full join is not how the union is taken, because
        # Postgres will not execute one on this condition.
        assert "FULL OUTER JOIN" not in view.body, view.name


def test_every_grouping_the_document_publishes_has_a_relation_behind_it() -> None:
    """Two structures that must agree, held together by the one thing
    that can: a test.

    The vocabulary a request is held to lives in `config/responses.py`,
    which is on the CLI's import path, and the relations that answer it
    live here, which is not: a client that imported this registry to
    find out would be a client the bare wheel cannot run. So the words
    are spelled twice and asserted to be one set, in both directions,
    with the same questions under each.
    """
    from vinga_server.config.responses import GROUPINGS

    assert tuple(GROUPED) == GROUPINGS
    for grouping, relations in GROUPED.items():
        assert set(relations) == set(ALIASES), grouping
    # And the two groupings answer from different relations, which is
    # what makes the second token a different question rather than a
    # second name for the first.
    assert {view.name for view in GROUPED[GROUPINGS[0]].values()}.isdisjoint(
        {view.name for view in GROUPED[GROUPINGS[-1]].values()}
    )


def test_the_common_prose_is_declared_and_not_written_in_the_renderer() -> None:
    """The three limits and the four rules are metadata on the registry,
    because the renderer is not their only reader: the API serves them
    in its descriptions and in its bodies, and the CLI prints what the
    API sent. Before this they lived in `docgen` alone, which is the one
    place a caller could never reach them from.

    The sentences themselves are pinned against the rendered page by the
    cases below. What this pins is that they are reachable without
    rendering anything.
    """
    declared = " ".join(flat(note) for group in COMMON for note in group.notes)

    assert "a rate read outside the events' own retention window is a floor" in declared
    assert "A missing measurement has more than one cause" in declared
    assert "A rate is null when its denominator is zero**, never zero" in declared
    assert [group.heading for group in COMMON] == [
        "What is true of every one of them",
        "Three limits worth knowing before quoting a number",
    ]


def test_the_reference_states_what_a_row_is_unique_by() -> None:
    flattened = flat(docgen.views_reference())

    assert "**One row per** `day`, `agent`, `stage`." in flattened
    assert "**One row per** `day`." in flattened


def test_no_view_reads_a_content_column() -> None:
    """The no-leak line, asked of the aggregates.

    These views exist to be read by an analyst role and, later, served
    over an API, so a body that reached a transcript would move
    conversation content onto a surface that has no switch of its own.
    None of them needs one: what they aggregate is durations, counts and
    agent names.
    """
    found = [
        f"{view.name}: {reach}"
        for view in DEFINED
        for reach in CONTENT_REACHES
        if reach in view.body
    ]
    assert not found, f"a view reaches conversation content: {', '.join(found)}"


def test_the_event_predicates_name_the_stored_event_names() -> None:
    """Written as constants and asserted in the body, because a
    numerator that filters on a name the writer never stores counts zero
    forever and reads as a healthy deployment.

    The suppression predicate carries no reason filter on purpose: the
    catalog stores one name whose three variants differ in
    `fields.reason`, and all three are suppressions.
    """
    from vinga_server.conversations.views import EVENT_RATES

    assert f"e.name = '{PROVIDER_FAILED}'" in EVENT_RATES.body
    assert f"e.name = '{BARGE_IN_SUPPRESSED}'" in EVENT_RATES.body
    assert "reason" not in EVENT_RATES.body


def test_the_reference_is_deterministic() -> None:
    assert docgen.views_reference() == docgen.views_reference()


def test_the_committed_reference_matches_the_declarations() -> None:
    """The same check CI runs, run here too: locally it fails in the
    suite rather than after a push."""
    assert COMMITTED.read_text(encoding="utf-8") == docgen.views_reference(), REGENERATE


def test_the_reference_names_every_view_and_every_column() -> None:
    rendered = docgen.views_reference()
    for view in DEFINED:
        assert f"### `{view.name}`" in rendered
        for column in view.columns:
            assert f"| `{column.name}` |" in rendered, f"{view.name}.{column.name} is missing"


def test_the_reference_carries_each_views_two_sentences() -> None:
    flattened = flat(docgen.views_reference())
    for view in DEFINED:
        assert flat(view.denominator) in flattened, view.name
        assert flat(view.telemetry_off) in flattened, view.name


def test_the_reference_states_the_retention_limit_in_its_own_terms() -> None:
    """The one sentence an analyst has to read before quoting an event
    rate from last quarter. Turns outlive their sessions' events, so the
    database cannot tell a quiet week from a pruned one, and the page
    says exactly that rather than implying the numbers are complete."""
    flattened = flat(docgen.views_reference())

    assert "a rate read outside the events' own retention window is a floor, not a" in (
        flattened
    )
    assert "zero cannot be told from pruned" in flattened
    # And the design decision beside it, so nobody adds the windowing
    # cleverness the sentence exists instead of.
    assert "No windowing cleverness is attempted" in flattened


def test_the_reference_says_the_metrics_column_kept_an_old_name() -> None:
    """The column is `sessions.metrics` and the switch is `telemetry`.
    A reader who does not know that reads `telemetry_sessions` as
    deriving from a column that is not there."""
    flattened = flat(docgen.views_reference())

    assert "`sessions.metrics` is the telemetry switch" in flattened
    assert "column keeps the old spelling deliberately" in flattened


def test_the_reference_refuses_to_diagnose_a_missing_measurement() -> None:
    """The page used to say a gap between `turns` and a measured count
    was the telemetry switch being off, and offered `telemetry_sessions`
    as the way to tell. Both were wrong: the schema documents a null
    token count for two causes, telemetry-off and a provider that
    reported no usage, and the store writes them identically, so a
    metrics-on turn with no usage and a metrics-off turn are the same
    row here. The integration suite seeds exactly that pair.

    So the page states the ambiguity and refuses the diagnosis, and this
    pins both halves: the two causes named as alternatives, and
    `telemetry_sessions` described as same-day session-level context
    rather than as a discriminator.
    """
    flattened = flat(docgen.views_reference())

    assert "A missing measurement has more than one cause" in flattened
    assert (
        "A null token count means telemetry storage was off OR the provider "
        "reported no usage" in flattened
    )
    assert "coverage and never its reason" in flattened
    assert "Read a measured count as a denominator, never as a diagnosis" in flattened
    # And the column that used to be offered as the way to tell.
    assert (
        "session-level context for the day a session opened rather than a "
        "discriminator" in flattened
    )
    # The claims the page may no longer make.
    assert "is a day the switch was off, not a day the provider went quiet" not in (
        flattened
    )
    assert "tells a day with the switch off from a day with nothing to measure" not in (
        flattened
    )


def test_the_reference_states_the_three_shared_rules() -> None:
    """Day, counting and rates: the three things that are true of all
    four views, said once at the top rather than four times."""
    flattened = flat(docgen.views_reference())

    assert "A day is a UTC day" in flattened
    assert "Counting is per stored row" in flattened
    assert "A rate is null when its denominator is zero**, never zero" in flattened
    # And the reason a percentile is read with its count beside it.
    assert "Percentiles interpolate" in flattened


def test_the_reference_enumerates_the_stage_vocabulary() -> None:
    """`stage` is a closed set, and the whole value of the column is
    that a query may enumerate it."""
    rendered = docgen.views_reference()
    for stage in STAGES:
        assert f"`{stage}`" in rendered
