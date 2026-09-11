"""The record gains a per-device sibling of each aggregate view

Four more views over what already lands, and no storage change at all:
no column, no table, no row rewritten. Each one mirrors a view 1006
created, with the device the session ran on and a label beside it added
to what a row is unique by:
`metrics_stage_latency_by_device_daily`,
`metrics_tokens_by_device_daily`,
`metrics_event_rates_by_device_daily` and
`metrics_sessions_by_device_daily`. What each one answers is in
`docs/reference/metrics-views.md`, rendered from the declarations in
`vinga_server/conversations/views.py`.

Additive rather than a redefinition, deliberately. The four views 1006
created are left exactly as they are, byte for byte: what selects from
them is somebody's saved query, dashboard or spreadsheet, and adding
two columns to a relation moves every one of those without asking.
`tests/integration/test_metrics_views_upgrade.py` upgrades a database
standing at 1006 and asserts the originals survive this migration and
still answer.

The `name` column is the literal null in every row of this release. The
analyst role is granted on `record` and revoked on `domain`, so a view
here cannot join `domain.devices` for a label at all, and what fills the
column is a copy of the label on the `record` side (#449). It is
declared and selected now so that the columns a caller reads do not move
on the day the label arrives.

The two views that combine independently aggregated streams take the
union of their (day, device) pairs as a spine and left join each stream
onto it, rather than chaining the full outer joins their ungrouped
siblings chain. Two reasons, and the second is what forced the shape.
A device key is null for a session rejected before a device was
understood, and `=` does not join two nulls, so every stream of a
null-device group would go unmatched and the group would come back with
zeroes and broken rates; `IS NOT DISTINCT FROM` is what says two nulls
are one key. And Postgres will not execute a full join on such a
condition ("FULL JOIN is only supported with merge-joinable or
hash-joinable join conditions"), so the union those joins existed to
produce is taken directly.

The SQL below is spelled out rather than imported from that module, for
the reason 1003 gives and 1005 repeats: a migration is a record of what
happened, and one reading its statements out of the current declaration
would rewrite its own history every time that declaration moved. The
agreement test is what keeps the two honest.

`vinga_ro` needs no grant here, exactly as 1006 needed none.
`deploy/postgres-init.sql` sets `ALTER DEFAULT PRIVILEGES ... GRANT
SELECT ON TABLES` for the server role, which covers views that role
creates later because Postgres counts a view as a relation of that
class, and this migration runs as the server role. The analyst half of
`tests/integration/test_provisioning.py` asserts it view by view rather
than assuming it.

Downgrade drops the four this migration created and leaves 1006's four
standing, which is what makes it the inverse of an additive change. A
view holds no rows, so dropping one loses nothing that was not derived
from the tables underneath it.

Revision ID: 1008_metrics_views_by_device
Revises: 1007_sessions_name_the_device
Create Date: 2026-09-11
"""

from collections.abc import Sequence

from alembic import op

revision: str = "1008_metrics_views_by_device"
down_revision: str | None = "1007_sessions_name_the_device"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

SCHEMA = "record"

# The names, in the order they are created and the reverse of the order
# they are dropped. Written here so the downgrade cannot fall out of
# step with the upgrade by a name somebody added to one of them.
VIEWS = (
    "metrics_stage_latency_by_device_daily",
    "metrics_tokens_by_device_daily",
    "metrics_event_rates_by_device_daily",
    "metrics_sessions_by_device_daily",
)

CREATE: tuple[str, ...] = (
    """
CREATE VIEW record.metrics_stage_latency_by_device_daily AS
SELECT
    (s.started_at::timestamptz AT TIME ZONE 'UTC'
        + make_interval(secs => t.t_ms::double precision / 1000.0))::date AS day,
    s.device AS device,
    NULL::text AS name,
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
GROUP BY 1, 2, 4, 5
""",
    """
CREATE VIEW record.metrics_tokens_by_device_daily AS
SELECT
    attribution.day AS day,
    attribution.device AS device,
    NULL::text AS name,
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
        s.device AS device,
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
GROUP BY 1, 2, 4
""",
    """
CREATE VIEW record.metrics_event_rates_by_device_daily AS
WITH turn_days AS (
    SELECT
        (s.started_at::timestamptz AT TIME ZONE 'UTC'
        + make_interval(secs => t.t_ms::double precision / 1000.0))::date AS day,
        s.device AS device,
        count(*) AS turns
    FROM record.turns t
    JOIN record.sessions s ON s.session = t.session
    GROUP BY 1, 2
), session_days AS (
    SELECT
        (s.started_at::timestamptz AT TIME ZONE 'UTC')::date AS day,
        s.device AS device,
        count(*) AS sessions
    FROM record.sessions s
    GROUP BY 1, 2
), failure_days AS (
    SELECT
        (s.started_at::timestamptz AT TIME ZONE 'UTC'
        + make_interval(secs => e.t_ms::double precision / 1000.0))::date AS day,
        s.device AS device,
        count(*) AS provider_failures
    FROM record.events e
    JOIN record.sessions s ON s.session = e.session
    WHERE e.name = 'provider_failed'
    GROUP BY 1, 2
), suppression_days AS (
    SELECT
        (s.started_at::timestamptz AT TIME ZONE 'UTC'
        + make_interval(secs => e.t_ms::double precision / 1000.0))::date AS day,
        s.device AS device,
        count(*) AS barge_in_suppressions
    FROM record.events e
    JOIN record.sessions s ON s.session = e.session
    WHERE e.name = 'barge_in_suppressed'
    GROUP BY 1, 2
), spine AS (
    SELECT day, device FROM turn_days
    UNION
    SELECT day, device FROM session_days
    UNION
    SELECT day, device FROM failure_days
    UNION
    SELECT day, device FROM suppression_days
)
SELECT
    spine.day AS day,
    spine.device AS device,
    NULL::text AS name,
    coalesce(turn_days.turns, 0) AS turns,
    coalesce(session_days.sessions, 0) AS sessions,
    coalesce(failure_days.provider_failures, 0) AS provider_failures,
    coalesce(suppression_days.barge_in_suppressions, 0) AS barge_in_suppressions,
    coalesce(failure_days.provider_failures, 0)::double precision
        / nullif(coalesce(turn_days.turns, 0), 0) AS provider_failures_per_turn,
    coalesce(suppression_days.barge_in_suppressions, 0)::double precision
        / nullif(coalesce(session_days.sessions, 0), 0) AS suppressions_per_session
FROM spine
LEFT JOIN turn_days
    ON turn_days.day IS NOT DISTINCT FROM spine.day
    AND turn_days.device IS NOT DISTINCT FROM spine.device
LEFT JOIN session_days
    ON session_days.day IS NOT DISTINCT FROM spine.day
    AND session_days.device IS NOT DISTINCT FROM spine.device
LEFT JOIN failure_days
    ON failure_days.day IS NOT DISTINCT FROM spine.day
    AND failure_days.device IS NOT DISTINCT FROM spine.device
LEFT JOIN suppression_days
    ON suppression_days.day IS NOT DISTINCT FROM spine.day
    AND suppression_days.device IS NOT DISTINCT FROM spine.device
""",
    """
CREATE VIEW record.metrics_sessions_by_device_daily AS
WITH session_days AS (
    SELECT
        (s.started_at::timestamptz AT TIME ZONE 'UTC')::date AS day,
        s.device AS device,
        count(*) AS sessions,
        count(*) FILTER (WHERE s.metrics) AS telemetry_sessions
    FROM record.sessions s
    GROUP BY 1, 2
), turn_days AS (
    SELECT
        (s.started_at::timestamptz AT TIME ZONE 'UTC'
        + make_interval(secs => t.t_ms::double precision / 1000.0))::date AS day,
        s.device AS device,
        count(*) AS turns
    FROM record.turns t
    JOIN record.sessions s ON s.session = t.session
    GROUP BY 1, 2
), spine AS (
    SELECT day, device FROM session_days
    UNION
    SELECT day, device FROM turn_days
)
SELECT
    spine.day AS day,
    spine.device AS device,
    NULL::text AS name,
    coalesce(session_days.sessions, 0) AS sessions,
    coalesce(session_days.telemetry_sessions, 0) AS telemetry_sessions,
    coalesce(turn_days.turns, 0) AS turns
FROM spine
LEFT JOIN session_days
    ON session_days.day IS NOT DISTINCT FROM spine.day
    AND session_days.device IS NOT DISTINCT FROM spine.device
LEFT JOIN turn_days
    ON turn_days.day IS NOT DISTINCT FROM spine.day
    AND turn_days.device IS NOT DISTINCT FROM spine.device
""",
)

# What `\d+` in psql shows beside each view, and what a reader has to
# have before they trust a number off one: the question it answers and
# the denominator its numbers are against.
COMMENT: tuple[str, ...] = (
    (
        "COMMENT ON VIEW record.metrics_stage_latency_by_device_daily IS "
        "'How slow was each pipeline stage, by UTC day and by the agent the turn "
        "started with? Broken down by the device the session ran on. The "
        "denominator is the turns that measured that stage, never all turns, and "
        "it is `measured_turns` beside the percentiles rather than a number a "
        "reader has to go and find. Every denominator here is that device''s own: "
        "the rows are split by device before anything is counted, so a column "
        "means what it means on the ungrouped view with the day narrowed to one "
        "device. A session whose device was never understood groups as a "
        "null-device row rather than vanishing, the way a null agent already "
        "does.'"
    ),
    (
        "COMMENT ON VIEW record.metrics_tokens_by_device_daily IS "
        "'What did each agent consume, by UTC day? Broken down by the device the "
        "session ran on. The unit is the attribution row, not the turn: a turn "
        "with `legs` contributes one attribution row per leg and its turn-level "
        "totals are not counted, and a turn without `legs` contributes one "
        "attribution row from the turn itself. `input_measured_turns` and "
        "`output_measured_turns` are counts of attribution rows whose respective "
        "token field is not null, stated separately because the store writes the "
        "two sums independently. Every denominator here is that device''s own: "
        "the rows are split by device before anything is counted, so a column "
        "means what it means on the ungrouped view with the day narrowed to one "
        "device. A session whose device was never understood groups as a "
        "null-device row rather than vanishing, the way a null agent already "
        "does.'"
    ),
    (
        "COMMENT ON VIEW record.metrics_event_rates_by_device_daily IS "
        "'How often did a provider fail and how often was a barge-in suppressed, "
        "against the traffic of the same day? Broken down by the device the "
        "session ran on. Failures are per turn and suppressions are per session, "
        "both by their UTC day, and both denominators are columns of this view "
        "rather than numbers a reader has to fetch from somewhere else. Each of "
        "the four streams is aggregated on its own and the four are joined over "
        "the union of their days, so an event on a day with no session start and "
        "no turn still gets a row. Every denominator here is that device''s own: "
        "the rows are split by device before anything is counted, so a column "
        "means what it means on the ungrouped view with the day narrowed to one "
        "device. A session whose device was never understood groups as a "
        "null-device row rather than vanishing, the way a null agent already "
        "does.'"
    ),
    (
        "COMMENT ON VIEW record.metrics_sessions_by_device_daily IS "
        "'What baseline sits under the numbers in every other view? Broken down by "
        "the device the session ran on. There is no ratio here: these are the "
        "counts the other views divide by. Sessions are counted by the UTC day "
        "they opened on and turns by the UTC day they were spoken on, so a "
        "session that crossed midnight lands on one day and its later turns on "
        "the next. Every denominator here is that device''s own: the rows are "
        "split by device before anything is counted, so a column means what it "
        "means on the ungrouped view with the day narrowed to one device. A "
        "session whose device was never understood groups as a null-device row "
        "rather than vanishing, the way a null agent already does.'"
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
