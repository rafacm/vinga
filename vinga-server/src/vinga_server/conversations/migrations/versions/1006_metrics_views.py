"""The record gains its named aggregate views

Four views over what already lands, and no storage change at all: no
column, no table, no row rewritten. `metrics_stage_latency_daily`,
`metrics_tokens_daily`, `metrics_event_rates_daily` and
`metrics_sessions_daily` are the aggregates the word "metrics" is
reserved for since #437, and what each one answers is in
`docs/reference/metrics-views.md`, rendered from the declarations in
`vinga_server/conversations/views.py`.

The SQL below is spelled out rather than imported from that module, for
the reason 1003 gives and 1005 repeats: a migration is a record of what
happened, and one reading its statements out of the current declaration
would rewrite its own history every time that declaration moved. What
keeps the two honest is not an import but a test:
`tests/integration/test_conversations_views.py` builds a shadow view
from every declaration and compares `pg_get_viewdef` of the shadow with
`pg_get_viewdef` of the view this migration created, so the database
does the normalizing and a divergence is red rather than silent.

`vinga_ro` needs no grant here. `deploy/postgres-init.sql` sets
`ALTER DEFAULT PRIVILEGES ... GRANT SELECT ON TABLES` for the server
role, which covers views that role creates later, and this migration
runs as the server role. The analyst half of the same suite asserts it
rather than assuming it.

Downgrade drops all four. A view holds no rows, so dropping one loses
nothing that was not derived from the tables underneath it.

Revision ID: 1006_metrics_views
Revises: 1005_providers_are_per_agent
Create Date: 2026-09-10
"""

from collections.abc import Sequence

from alembic import op

revision: str = "1006_metrics_views"
down_revision: str | None = "1005_providers_are_per_agent"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

SCHEMA = "record"

# The names, in the order they are created and the reverse of the order
# they are dropped. Written here so the downgrade cannot fall out of
# step with the upgrade by a name somebody added to one of them.
VIEWS = (
    "metrics_stage_latency_daily",
    "metrics_tokens_daily",
    "metrics_event_rates_daily",
    "metrics_sessions_daily",
)

CREATE: tuple[str, ...] = (
    """
CREATE VIEW record.metrics_stage_latency_daily AS
SELECT
    (s.started_at::timestamptz AT TIME ZONE 'UTC'
        + make_interval(secs => t.t_ms::double precision / 1000.0))::date AS day,
    t.agent AS agent,
    stage.name AS stage,
    count(*) AS measured_turns,
    percentile_cont(0.5) WITHIN GROUP (ORDER BY stage.ms::double precision) AS p50_ms,
    percentile_cont(0.95) WITHIN GROUP (ORDER BY stage.ms::double precision) AS p95_ms,
    max(stage.ms) AS max_ms
FROM record.turns t
JOIN record.sessions s ON s.session = t.session
CROSS JOIN LATERAL (
    VALUES
        ('asr'::text, t.asr_ms),
        ('first_token'::text, t.first_token_ms),
        ('llm'::text, t.llm_ms),
        ('tts_first_audio'::text, t.tts_first_audio_ms)
) AS stage(name, ms)
WHERE stage.ms IS NOT NULL
GROUP BY 1, 2, 3
""",
    """
CREATE VIEW record.metrics_tokens_daily AS
SELECT
    attribution.day AS day,
    attribution.agent AS agent,
    count(DISTINCT attribution.turn) AS turns,
    count(attribution.input_tokens) AS input_measured_turns,
    count(attribution.output_tokens) AS output_measured_turns,
    sum(attribution.input_tokens) AS input_tokens,
    sum(attribution.output_tokens) AS output_tokens
FROM (
    SELECT
        (s.started_at::timestamptz AT TIME ZONE 'UTC'
        + make_interval(secs => t.t_ms::double precision / 1000.0))::date AS day,
        t.id AS turn,
        CASE WHEN leg.entry IS NULL THEN t.agent
             ELSE leg.entry ->> 'agent' END AS agent,
        CASE WHEN leg.entry IS NULL THEN t.input_tokens
             ELSE (leg.entry ->> 'input_tokens')::integer END AS input_tokens,
        CASE WHEN leg.entry IS NULL THEN t.output_tokens
             ELSE (leg.entry ->> 'output_tokens')::integer END AS output_tokens
    FROM record.turns t
    JOIN record.sessions s ON s.session = t.session
    LEFT JOIN LATERAL json_array_elements(
        CASE WHEN json_typeof(t.legs) = 'array' THEN t.legs END
    ) AS leg(entry) ON true
) AS attribution
GROUP BY 1, 2
""",
    """
CREATE VIEW record.metrics_event_rates_daily AS
WITH turn_days AS (
    SELECT
        (s.started_at::timestamptz AT TIME ZONE 'UTC'
        + make_interval(secs => t.t_ms::double precision / 1000.0))::date AS day,
        count(*) AS turns
    FROM record.turns t
    JOIN record.sessions s ON s.session = t.session
    GROUP BY 1
), session_days AS (
    SELECT
        (s.started_at::timestamptz AT TIME ZONE 'UTC')::date AS day,
        count(*) AS sessions
    FROM record.sessions s
    GROUP BY 1
), failure_days AS (
    SELECT
        (s.started_at::timestamptz AT TIME ZONE 'UTC'
        + make_interval(secs => e.t_ms::double precision / 1000.0))::date AS day,
        count(*) AS provider_failures
    FROM record.events e
    JOIN record.sessions s ON s.session = e.session
    WHERE e.name = 'provider_failed'
    GROUP BY 1
), suppression_days AS (
    SELECT
        (s.started_at::timestamptz AT TIME ZONE 'UTC'
        + make_interval(secs => e.t_ms::double precision / 1000.0))::date AS day,
        count(*) AS barge_in_suppressions
    FROM record.events e
    JOIN record.sessions s ON s.session = e.session
    WHERE e.name = 'barge_in_suppressed'
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
    ON suppression_days.day = coalesce(turn_days.day, session_days.day, failure_days.day)
""",
    """
CREATE VIEW record.metrics_sessions_daily AS
WITH session_days AS (
    SELECT
        (s.started_at::timestamptz AT TIME ZONE 'UTC')::date AS day,
        count(*) AS sessions,
        count(*) FILTER (WHERE s.metrics) AS telemetry_sessions
    FROM record.sessions s
    GROUP BY 1
), turn_days AS (
    SELECT
        (s.started_at::timestamptz AT TIME ZONE 'UTC'
        + make_interval(secs => t.t_ms::double precision / 1000.0))::date AS day,
        count(*) AS turns
    FROM record.turns t
    JOIN record.sessions s ON s.session = t.session
    GROUP BY 1
)
SELECT
    coalesce(session_days.day, turn_days.day) AS day,
    coalesce(session_days.sessions, 0) AS sessions,
    coalesce(session_days.telemetry_sessions, 0) AS telemetry_sessions,
    coalesce(turn_days.turns, 0) AS turns
FROM session_days
FULL OUTER JOIN turn_days ON turn_days.day = session_days.day
""",
)

# What `\d+` in psql shows beside each view, and what a reader has to
# have before they trust a number off one: the question it answers and
# the denominator its numbers are against.
COMMENT: tuple[str, ...] = (
    (
        "COMMENT ON VIEW record.metrics_stage_latency_daily IS "
        "'How slow was each pipeline stage, by UTC day and by the agent the turn "
        "started with? The denominator is the turns that measured that stage, never "
        "all turns, and it is `measured_turns` beside the percentiles rather than a "
        "number a reader has to go and find.'"
    ),
    (
        "COMMENT ON VIEW record.metrics_tokens_daily IS "
        "'What did each agent consume, by UTC day? The unit is the attribution row, "
        "not the turn: a turn with `legs` contributes one attribution row per leg and "
        "its turn-level totals are not counted, and a turn without `legs` contributes "
        "one attribution row from the turn itself. `input_measured_turns` and "
        "`output_measured_turns` are counts of attribution rows whose respective "
        "token field is not null, stated separately because the store writes the two "
        "sums independently.'"
    ),
    (
        "COMMENT ON VIEW record.metrics_event_rates_daily IS "
        "'How often did a provider fail and how often was a barge-in suppressed, "
        "against the traffic of the same day? Failures are per turn and suppressions "
        "are per session, both by their UTC day, and both denominators are columns of "
        "this view rather than numbers a reader has to fetch from somewhere else. "
        "Each of the four streams is aggregated on its own and the four are joined "
        "over the union of their days, so an event on a day with no session start and "
        "no turn still gets a row.'"
    ),
    (
        "COMMENT ON VIEW record.metrics_sessions_daily IS "
        "'What baseline sits under the numbers in every other view? There is no ratio "
        "here: these are the counts the other views divide by. Sessions are counted "
        "by the UTC day they opened on and turns by the UTC day they were spoken on, "
        "so a session that crossed midnight lands on one day and its later turns on "
        "the next.'"
    ),
)


def upgrade() -> None:
    for statement in CREATE:
        op.execute(statement)
    for statement in COMMENT:
        op.execute(statement)


def downgrade() -> None:
    for name in reversed(VIEWS):
        op.execute(f"DROP VIEW IF EXISTS {SCHEMA}.{name}")
