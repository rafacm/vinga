"""The named aggregates over the record, declared once.

A view here is not a query somebody wrote down. It is a question with a
frozen answer shape: the columns it hands back, what each one means and
in what unit, when each one is null, and the formula that produces it.
That whole declaration is the module's content, and three callers read
it rather than restating it: `docgen.views_reference` renders
`docs/reference/metrics-views.md` from it, the agreement test compares
every live definition against it, and the analyst test iterates it to
prove `vinga_ro` may read each one.

The migration spells the same `CREATE VIEW` statements literally, as
frozen history must, and that is the one duplication this module does
not remove. It is pinned instead: `tests/integration/
test_conversations_views.py` builds a shadow view from every declaration
here and compares `pg_get_viewdef` of the shadow with `pg_get_viewdef` of
the live view, so the database itself does the normalizing and drift
between this module and the chain is a red test rather than a latent
lie.

Views live outside `schema.py`'s `MetaData` deliberately. Alembic's
autogenerate reflects tables, not views, so `compare_metadata` never
sees one and cannot propose dropping it; the agreement test above is the
drift guard in its place, and nobody should "fix" that by declaring a
view as a `Table`.

Three rules run through every definition, and each is here rather than
in four places:

- **Day is UTC.** `sessions.started_at` is UTC ISO-8601 text and turns
  and events carry `t_ms`, an offset from session open, so a row's day
  is `started_at::timestamptz AT TIME ZONE 'UTC'` plus that offset, cast
  to `date`. Every cast names UTC, so the reader's own session timezone
  cannot move a row to the day before.
- **Counting is per stored row.** Two provider failures in one turn are
  two. A view that deduplicated them would be answering a different
  question than the one its name asks.
- **A rate is null on a zero denominator**, never zero. Nothing happened
  and nothing could have happened are different facts.

Read-only, and deliberately so: nothing here opens a database.
"""

from dataclasses import dataclass

from vinga_server.conversations.schema import SCHEMA

# The four stages the latency view unpivots, in the order a turn passes
# through them. A closed set spelled in the SQL rather than derived from
# the columns, because it is the view's output vocabulary: a query may
# enumerate `stage`, which it could not do if the literals were assembled
# somewhere a reader cannot see.
STAGES = ("asr", "first_token", "llm", "tts_first_audio")

# The two event names the rate view counts, exactly as `events.name`
# stores them (`docs/reference/events.md`). `barge_in_suppressed` is one
# name whose three variants differ in `fields.reason`, and all three
# count, so there is no reason filter here.
PROVIDER_FAILED = "provider_failed"
BARGE_IN_SUPPRESSED = "barge_in_suppressed"


@dataclass(frozen=True)
class Column:
    """One output column, described the way a reader needs it.

    `units` is the unit of the value and not its SQL type:
    `milliseconds`, `turns`, `failures per turn`. A column whose value
    has no unit says `none`, so a blank cell is always a defect rather
    than sometimes a truth.
    """

    name: str
    type: str
    meaning: str
    units: str
    nullable: bool
    formula: str


@dataclass(frozen=True)
class View:
    """One named aggregate: its question, its columns, and its SQL."""

    name: str
    question: str
    denominator: str
    telemetry_off: str
    columns: tuple[Column, ...]
    body: str

    @property
    def qualified(self) -> str:
        """How SQL spells this view."""
        return f"{SCHEMA}.{self.name}"

    @property
    def comment(self) -> str:
        """What `COMMENT ON VIEW` carries, which is the question and the
        denominator sentence: the two things somebody reading `\\d+` in
        psql needs before they trust a number off it."""
        return f"{self.question} {self.denominator}"

    def create(self) -> str:
        """The `CREATE VIEW` statement this declaration defines."""
        return f"CREATE VIEW {self.qualified} AS\n{self.body}"

    def comment_statement(self) -> str:
        """The `COMMENT ON VIEW` statement, with its text as a literal.

        A literal rather than a bind parameter because `COMMENT` takes
        none: Postgres parses the text at parse time, so a placeholder
        is a syntax error rather than a value.
        """
        escaped = self.comment.replace("'", "''")
        return f"COMMENT ON VIEW {self.qualified} IS '{escaped}'"


# The day a turn or an event belongs to, and the day a session belongs
# to. One home for the rule the module docstring states; every view below
# reads it from here so that four definitions cannot come to disagree
# about what a day is.
SESSION_DAY = "(s.started_at::timestamptz AT TIME ZONE 'UTC')::date"


def offset_day(alias: str) -> str:
    """The UTC day of a row that carries `t_ms`, given its table alias.

    The session it names has to be joined as `s`, which every definition
    below does.
    """
    return (
        "(s.started_at::timestamptz AT TIME ZONE 'UTC'\n"
        f"        + make_interval(secs => {alias}.t_ms::double precision / 1000.0))::date"
    )


STAGE_LATENCY = View(
    name="metrics_stage_latency_daily",
    question=(
        "How slow was each pipeline stage, by UTC day and by the agent the "
        "turn started with?"
    ),
    denominator=(
        "The denominator is the turns that measured that stage, never all "
        "turns, and it is `measured_turns` beside the percentiles rather "
        "than a number a reader has to go and find."
    ),
    telemetry_off=(
        "A turn stored under telemetry-off has every stage column null, so "
        "it contributes no row here at all. It still counts as a turn in "
        "`metrics_sessions_daily` and in the event view's denominator, "
        "which is what makes `measured_turns` worth reading beside a "
        "percentile."
    ),
    columns=(
        Column(
            name="day",
            type="date",
            meaning="The UTC day the turn was spoken on.",
            units="none",
            nullable=False,
            formula=(
                "The turn's session `started_at` converted to UTC, plus the "
                "turn's `t_ms`, cast to `date`."
            ),
        ),
        Column(
            name="agent",
            type="text",
            meaning=(
                "The agent the turn started with, which is `turns.agent`. A "
                "handover does not move it: the per-agent split of a turn is "
                "`turns.legs`, and latency is not attributed leg by leg "
                "because the stage timings are the turn's."
            ),
            units="none",
            nullable=True,
            formula="`turns.agent`, grouped. A turn with no agent groups as a null row.",
        ),
        Column(
            name="stage",
            type="text",
            meaning=(
                "Which stage the numbers are about, one of: "
                + ", ".join(f"`{stage}`" for stage in STAGES)
                + "."
            ),
            units="none",
            nullable=False,
            formula=(
                "A literal, unpivoted from the four measured columns "
                "`asr_ms`, `first_token_ms`, `llm_ms` and "
                "`tts_first_audio_ms`."
            ),
        ),
        Column(
            name="measured_turns",
            type="bigint",
            meaning=(
                "How many turns this row's percentiles were computed over. "
                "Read it first: a two-turn day's p95 is mostly interpolation."
            ),
            units="turns",
            nullable=False,
            formula="`count(*)` over the rows where that stage's column is not null.",
        ),
        Column(
            name="p50_ms",
            type="double precision",
            meaning="The median of that stage's measured durations.",
            units="milliseconds",
            nullable=False,
            formula="`percentile_cont(0.5)` within the group, which interpolates.",
        ),
        Column(
            name="p95_ms",
            type="double precision",
            meaning="The 95th percentile of that stage's measured durations.",
            units="milliseconds",
            nullable=False,
            formula="`percentile_cont(0.95)` within the group, which interpolates.",
        ),
        Column(
            name="max_ms",
            type="integer",
            meaning=(
                "The slowest measured duration in the group, as it was "
                "stored rather than interpolated."
            ),
            units="milliseconds",
            nullable=False,
            formula="`max()` over that stage's column.",
        ),
    ),
    body=f"""SELECT
    {offset_day("t")} AS day,
    t.agent AS agent,
    stage.name AS stage,
    count(*) AS measured_turns,
    percentile_cont(0.5) WITHIN GROUP (ORDER BY stage.ms::double precision) AS p50_ms,
    percentile_cont(0.95) WITHIN GROUP (ORDER BY stage.ms::double precision) AS p95_ms,
    max(stage.ms) AS max_ms
FROM {SCHEMA}.turns t
JOIN {SCHEMA}.sessions s ON s.session = t.session
CROSS JOIN LATERAL (
    VALUES
        ('{STAGES[0]}'::text, t.asr_ms),
        ('{STAGES[1]}'::text, t.first_token_ms),
        ('{STAGES[2]}'::text, t.llm_ms),
        ('{STAGES[3]}'::text, t.tts_first_audio_ms)
) AS stage(name, ms)
WHERE stage.ms IS NOT NULL
GROUP BY 1, 2, 3""",
)


TOKENS = View(
    name="metrics_tokens_daily",
    question="What did each agent consume, by UTC day?",
    denominator=(
        "The unit is the attribution row, not the turn: a turn with `legs` "
        "contributes one attribution row per leg and its turn-level totals "
        "are not counted, and a turn without `legs` contributes one "
        "attribution row from the turn itself. `input_measured_turns` and "
        "`output_measured_turns` are counts of attribution rows whose "
        "respective token field is not null, stated separately because the "
        "store writes the two sums independently."
    ),
    telemetry_off=(
        "Under telemetry-off both token fields are null, so the attribution "
        "row still lands and still counts in `turns` while adding nothing to "
        "either measured count and nothing to either sum. A day whose "
        "`turns` far exceeds its measured counts is a day the switch was "
        "off, not a day the provider went quiet."
    ),
    columns=(
        Column(
            name="day",
            type="date",
            meaning="The UTC day the turn was spoken on.",
            units="none",
            nullable=False,
            formula=(
                "The turn's session `started_at` converted to UTC, plus the "
                "turn's `t_ms`, cast to `date`."
            ),
        ),
        Column(
            name="agent",
            type="text",
            meaning=(
                "The agent the attribution row belongs to: the leg's own "
                "`agent` where the turn had legs, and `turns.agent` where it "
                "did not."
            ),
            units="none",
            nullable=True,
            formula=(
                "Grouped. A leg whose `agent` is null groups as a null row "
                "rather than vanishing, so usage nobody can attribute is "
                "still visible."
            ),
        ),
        Column(
            name="turns",
            type="bigint",
            meaning=(
                "How many physical turns own at least one attribution row in "
                "this group. A turn split across two agents counts once in "
                "each of their rows and is never double counted inside one."
            ),
            units="turns",
            nullable=False,
            formula="`count(DISTINCT turns.id)` over the group's attribution rows.",
        ),
        Column(
            name="input_measured_turns",
            type="bigint",
            meaning="How many attribution rows in this group carried an input count.",
            units="attribution rows",
            nullable=False,
            formula="`count()` over the attribution rows whose input field is not null.",
        ),
        Column(
            name="output_measured_turns",
            type="bigint",
            meaning="How many attribution rows in this group carried an output count.",
            units="attribution rows",
            nullable=False,
            formula="`count()` over the attribution rows whose output field is not null.",
        ),
        Column(
            name="input_tokens",
            type="bigint",
            meaning=(
                "Input tokens consumed by this agent on this day, OTel's "
                "`gen_ai.usage.input_tokens`."
            ),
            units="tokens",
            nullable=True,
            formula=(
                "`sum()` over the non-null input fields. Null when the group "
                "measured none, which is what `input_measured_turns` of zero "
                "says in a number."
            ),
        ),
        Column(
            name="output_tokens",
            type="bigint",
            meaning=(
                "Output tokens produced for this agent on this day, OTel's "
                "`gen_ai.usage.output_tokens`."
            ),
            units="tokens",
            nullable=True,
            formula=(
                "`sum()` over the non-null output fields. Null when the group "
                "measured none."
            ),
        ),
    ),
    body=f"""SELECT
    attribution.day AS day,
    attribution.agent AS agent,
    count(DISTINCT attribution.turn) AS turns,
    count(attribution.input_tokens) AS input_measured_turns,
    count(attribution.output_tokens) AS output_measured_turns,
    sum(attribution.input_tokens) AS input_tokens,
    sum(attribution.output_tokens) AS output_tokens
FROM (
    SELECT
        {offset_day("t")} AS day,
        t.id AS turn,
        CASE WHEN leg.entry IS NULL THEN t.agent
             ELSE leg.entry ->> 'agent' END AS agent,
        CASE WHEN leg.entry IS NULL THEN t.input_tokens
             ELSE (leg.entry ->> 'input_tokens')::integer END AS input_tokens,
        CASE WHEN leg.entry IS NULL THEN t.output_tokens
             ELSE (leg.entry ->> 'output_tokens')::integer END AS output_tokens
    FROM {SCHEMA}.turns t
    JOIN {SCHEMA}.sessions s ON s.session = t.session
    LEFT JOIN LATERAL json_array_elements(
        CASE WHEN json_typeof(t.legs) = 'array' THEN t.legs END
    ) AS leg(entry) ON true
) AS attribution
GROUP BY 1, 2""",
)


EVENT_RATES = View(
    name="metrics_event_rates_daily",
    question=(
        "How often did a provider fail and how often was a barge-in "
        "suppressed, against the traffic of the same day?"
    ),
    denominator=(
        "Failures are per turn and suppressions are per session, both by "
        "their UTC day, and both denominators are columns of this view "
        "rather than numbers a reader has to fetch from somewhere else. "
        "Each of the four streams is aggregated on its own and the four are "
        "joined over the union of their days, so an event on a day with no "
        "session start and no turn still gets a row."
    ),
    telemetry_off=(
        "A telemetry-off session writes no `events` rows at all, while its "
        "session and its turns still count. It therefore raises both "
        "denominators and neither numerator, which is a property of the "
        "data this view reports rather than hides: read it beside "
        "`metrics_sessions_daily.telemetry_sessions`."
    ),
    columns=(
        Column(
            name="day",
            type="date",
            meaning="The UTC day, from whichever of the four streams has one.",
            units="none",
            nullable=False,
            formula="`coalesce()` across the four streams' days.",
        ),
        Column(
            name="turns",
            type="bigint",
            meaning="How many turns were spoken on this day.",
            units="turns",
            nullable=False,
            formula=(
                "`count(*)` over turns by their UTC day, coalesced to zero on "
                "a day that has events and no turns."
            ),
        ),
        Column(
            name="sessions",
            type="bigint",
            meaning="How many sessions opened on this day.",
            units="sessions",
            nullable=False,
            formula=(
                "`count(*)` over sessions by their `started_at` day, coalesced "
                "to zero."
            ),
        ),
        Column(
            name="provider_failures",
            type="bigint",
            meaning=(
                "How many `provider_failed` events landed on this day. Per "
                "stored row: two failures in one turn are two."
            ),
            units="events",
            nullable=False,
            formula=f"`count(*)` where `events.name = '{PROVIDER_FAILED}'`, coalesced to zero.",
        ),
        Column(
            name="barge_in_suppressions",
            type="bigint",
            meaning=(
                "How many `barge_in_suppressed` events landed on this day, "
                "all three of the name's reason variants together."
            ),
            units="events",
            nullable=False,
            formula=(
                f"`count(*)` where `events.name = '{BARGE_IN_SUPPRESSED}'`, with no "
                "filter on `fields.reason`, coalesced to zero."
            ),
        ),
        Column(
            name="provider_failures_per_turn",
            type="double precision",
            meaning="Provider failures divided by the day's turns.",
            units="failures per turn",
            nullable=True,
            formula="Null when the day has no turns, never zero.",
        ),
        Column(
            name="suppressions_per_session",
            type="double precision",
            meaning="Barge-in suppressions divided by the day's sessions.",
            units="suppressions per session",
            nullable=True,
            formula="Null when the day has no sessions, never zero.",
        ),
    ),
    body=f"""WITH turn_days AS (
    SELECT
        {offset_day("t")} AS day,
        count(*) AS turns
    FROM {SCHEMA}.turns t
    JOIN {SCHEMA}.sessions s ON s.session = t.session
    GROUP BY 1
), session_days AS (
    SELECT
        {SESSION_DAY} AS day,
        count(*) AS sessions
    FROM {SCHEMA}.sessions s
    GROUP BY 1
), failure_days AS (
    SELECT
        {offset_day("e")} AS day,
        count(*) AS provider_failures
    FROM {SCHEMA}.events e
    JOIN {SCHEMA}.sessions s ON s.session = e.session
    WHERE e.name = '{PROVIDER_FAILED}'
    GROUP BY 1
), suppression_days AS (
    SELECT
        {offset_day("e")} AS day,
        count(*) AS barge_in_suppressions
    FROM {SCHEMA}.events e
    JOIN {SCHEMA}.sessions s ON s.session = e.session
    WHERE e.name = '{BARGE_IN_SUPPRESSED}'
    GROUP BY 1
)
SELECT
    coalesce(turn_days.day, session_days.day, failure_days.day, suppression_days.day)
        AS day,
    coalesce(turn_days.turns, 0) AS turns,
    coalesce(session_days.sessions, 0) AS sessions,
    coalesce(failure_days.provider_failures, 0) AS provider_failures,
    coalesce(suppression_days.barge_in_suppressions, 0) AS barge_in_suppressions,
    coalesce(failure_days.provider_failures, 0)::double precision
        / nullif(coalesce(turn_days.turns, 0), 0) AS provider_failures_per_turn,
    coalesce(suppression_days.barge_in_suppressions, 0)::double precision
        / nullif(coalesce(session_days.sessions, 0), 0) AS suppressions_per_session
FROM turn_days
FULL OUTER JOIN session_days ON session_days.day = turn_days.day
FULL OUTER JOIN failure_days
    ON failure_days.day = coalesce(turn_days.day, session_days.day)
FULL OUTER JOIN suppression_days
    ON suppression_days.day = coalesce(turn_days.day, session_days.day, failure_days.day)""",
)


SESSIONS = View(
    name="metrics_sessions_daily",
    question="What baseline sits under the numbers in every other view?",
    denominator=(
        "There is no ratio here: these are the counts the other views "
        "divide by. Sessions are counted by the UTC day they opened on and "
        "turns by the UTC day they were spoken on, so a session that "
        "crossed midnight lands on one day and its later turns on the next."
    ),
    telemetry_off=(
        "`telemetry_sessions` counts `sessions.metrics`, which is the "
        "telemetry switch and keeps the name it had before the switch was "
        "renamed. Subtract it from `sessions` to get the sessions that "
        "could not have contributed a measured number or an event to any "
        "other view."
    ),
    columns=(
        Column(
            name="day",
            type="date",
            meaning="The UTC day.",
            units="none",
            nullable=False,
            formula="`coalesce()` across the session and turn streams' days.",
        ),
        Column(
            name="sessions",
            type="bigint",
            meaning="How many sessions opened on this day.",
            units="sessions",
            nullable=False,
            formula=(
                "`count(*)` over sessions by their `started_at` day, coalesced "
                "to zero on a day that only has turns."
            ),
        ),
        Column(
            name="telemetry_sessions",
            type="bigint",
            meaning=(
                "How many of them had telemetry storage on, so a null number "
                "elsewhere can be told from a number nobody stored."
            ),
            units="sessions",
            nullable=False,
            formula="`count(*) FILTER (WHERE sessions.metrics)`, coalesced to zero.",
        ),
        Column(
            name="turns",
            type="bigint",
            meaning="How many turns were spoken on this day.",
            units="turns",
            nullable=False,
            formula="`count(*)` over turns by their UTC day, coalesced to zero.",
        ),
    ),
    body=f"""WITH session_days AS (
    SELECT
        {SESSION_DAY} AS day,
        count(*) AS sessions,
        count(*) FILTER (WHERE s.metrics) AS telemetry_sessions
    FROM {SCHEMA}.sessions s
    GROUP BY 1
), turn_days AS (
    SELECT
        {offset_day("t")} AS day,
        count(*) AS turns
    FROM {SCHEMA}.turns t
    JOIN {SCHEMA}.sessions s ON s.session = t.session
    GROUP BY 1
)
SELECT
    coalesce(session_days.day, turn_days.day) AS day,
    coalesce(session_days.sessions, 0) AS sessions,
    coalesce(session_days.telemetry_sessions, 0) AS telemetry_sessions,
    coalesce(turn_days.turns, 0) AS turns
FROM session_days
FULL OUTER JOIN turn_days ON turn_days.day = session_days.day""",
)


# Declaration order, which is also the order the reference documents them
# in: the two views that answer "how slow" and "how much", the rates that
# need both, and the baseline underneath all of them.
VIEWS = (STAGE_LATENCY, TOKENS, EVENT_RATES, SESSIONS)


__all__ = [
    "BARGE_IN_SUPPRESSED",
    "PROVIDER_FAILED",
    "SESSION_DAY",
    "STAGES",
    "VIEWS",
    "Column",
    "View",
    "offset_day",
]
