"""The per-device views read the name a session recorded

No storage change, no new relation and nothing dropped: the four views
1008 created are replaced where they stand, with `CREATE OR REPLACE
VIEW`, so that the `name` column selects `sessions.device_name` instead
of the literal null 1008 had to spell. The column list, its order and
its types are exactly what they were, which is what `CREATE OR REPLACE`
requires and, more to the point, what leaves every saved query,
dashboard and downstream view pointing at these four still pointing at
them. The four ungrouped views are not touched at all, here or in 1008.

The name is dated. `1007_sessions_name_the_device` writes it when the
session opens and nothing rewrites it, so a board renamed mid-window has
sessions carrying both names and there is no one label for the pair. So
it joins what makes a row one row: these views return one row per
(day, device, name), a rename splits a series rather than retitling the
numbers the old name earned, and a reader who wants the board whole
groups on `device`, which is the identity and survives the rename. The
alternative, stamping the most recent name over the window, would report
last week's numbers under a label they were never recorded with and
leave no rows behind to undo it.

Null is a group and not an absence, which matters twice as much now.
Nothing backfilled `device_name`, so every session recorded before 1007
carries a null there, as does every board nobody has named. The two
views that combine independently aggregated streams therefore carry the
name through their spine and join it with `IS NOT DISTINCT FROM`,
exactly as they already join the device: `=` does not match two nulls,
so an equality join would leave each stream of such a group unmatched by
every other and the group would come back with one stream's number,
zeroes where the others belong and broken rates. `UNION` dedupes the
spine and already treats two nulls as one value.

The SQL below is spelled out rather than imported from
`vinga_server/conversations/views.py`, for the reason 1003 gives and
1005, 1006 and 1008 repeat: a migration is a record of what happened,
and one reading its statements out of the current declaration would
rewrite its own history every time that declaration moved. The
agreement test in `tests/integration/test_conversations_views.py` is
what keeps the two honest, `pg_get_viewdef` against `pg_get_viewdef`.

`vinga_ro` needs no grant here. A replaced view keeps the privileges it
was created with, and the analyst half of
`tests/integration/test_provisioning.py` asserts the read view by view
rather than assuming it.

Downgrade restores 1008's definitions and 1008's comments literally,
which is what makes it a real inverse: the same four relations, with the
label back to the null they were shipped with, and no oid moved in
either direction.

Revision ID: 1009_views_read_the_name
Revises: 1008_metrics_views_by_device
Create Date: 2026-09-12
"""

from collections.abc import Sequence

from alembic import op

revision: str = "1009_views_read_the_name"
down_revision: str | None = "1008_metrics_views_by_device"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

REPLACE: tuple[str, ...] = (
    """
CREATE OR REPLACE VIEW record.metrics_stage_latency_by_device_daily AS
SELECT
    (s.started_at::timestamptz AT TIME ZONE 'UTC'
        + make_interval(secs => t.t_ms::double precision / 1000.0))::date AS day,
    s.device AS device,
    s.device_name AS name,
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
GROUP BY 1, 2, 3, 4, 5
""",
    """
CREATE OR REPLACE VIEW record.metrics_tokens_by_device_daily AS
SELECT
    attribution.day AS day,
    attribution.device AS device,
    attribution.name AS name,
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
        s.device_name AS name,
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
GROUP BY 1, 2, 3, 4
""",
    """
CREATE OR REPLACE VIEW record.metrics_event_rates_by_device_daily AS
WITH turn_days AS (
    SELECT
        (s.started_at::timestamptz AT TIME ZONE 'UTC'
        + make_interval(secs => t.t_ms::double precision / 1000.0))::date AS day,
        s.device AS device,
        s.device_name AS name,
        count(*) AS turns
    FROM record.turns t
    JOIN record.sessions s ON s.session = t.session
    GROUP BY 1, 2, 3
), session_days AS (
    SELECT
        (s.started_at::timestamptz AT TIME ZONE 'UTC')::date AS day,
        s.device AS device,
        s.device_name AS name,
        count(*) AS sessions
    FROM record.sessions s
    GROUP BY 1, 2, 3
), failure_days AS (
    SELECT
        (s.started_at::timestamptz AT TIME ZONE 'UTC'
        + make_interval(secs => e.t_ms::double precision / 1000.0))::date AS day,
        s.device AS device,
        s.device_name AS name,
        count(*) AS provider_failures
    FROM record.events e
    JOIN record.sessions s ON s.session = e.session
    WHERE e.name = 'provider_failed'
    GROUP BY 1, 2, 3
), suppression_days AS (
    SELECT
        (s.started_at::timestamptz AT TIME ZONE 'UTC'
        + make_interval(secs => e.t_ms::double precision / 1000.0))::date AS day,
        s.device AS device,
        s.device_name AS name,
        count(*) AS barge_in_suppressions
    FROM record.events e
    JOIN record.sessions s ON s.session = e.session
    WHERE e.name = 'barge_in_suppressed'
    GROUP BY 1, 2, 3
), spine AS (
    SELECT day, device, name FROM turn_days
    UNION
    SELECT day, device, name FROM session_days
    UNION
    SELECT day, device, name FROM failure_days
    UNION
    SELECT day, device, name FROM suppression_days
)
SELECT
    spine.day AS day,
    spine.device AS device,
    spine.name AS name,
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
    AND turn_days.name IS NOT DISTINCT FROM spine.name
LEFT JOIN session_days
    ON session_days.day IS NOT DISTINCT FROM spine.day
    AND session_days.device IS NOT DISTINCT FROM spine.device
    AND session_days.name IS NOT DISTINCT FROM spine.name
LEFT JOIN failure_days
    ON failure_days.day IS NOT DISTINCT FROM spine.day
    AND failure_days.device IS NOT DISTINCT FROM spine.device
    AND failure_days.name IS NOT DISTINCT FROM spine.name
LEFT JOIN suppression_days
    ON suppression_days.day IS NOT DISTINCT FROM spine.day
    AND suppression_days.device IS NOT DISTINCT FROM spine.device
    AND suppression_days.name IS NOT DISTINCT FROM spine.name
""",
    """
CREATE OR REPLACE VIEW record.metrics_sessions_by_device_daily AS
WITH session_days AS (
    SELECT
        (s.started_at::timestamptz AT TIME ZONE 'UTC')::date AS day,
        s.device AS device,
        s.device_name AS name,
        count(*) AS sessions,
        count(*) FILTER (WHERE s.metrics) AS telemetry_sessions
    FROM record.sessions s
    GROUP BY 1, 2, 3
), turn_days AS (
    SELECT
        (s.started_at::timestamptz AT TIME ZONE 'UTC'
        + make_interval(secs => t.t_ms::double precision / 1000.0))::date AS day,
        s.device AS device,
        s.device_name AS name,
        count(*) AS turns
    FROM record.turns t
    JOIN record.sessions s ON s.session = t.session
    GROUP BY 1, 2, 3
), spine AS (
    SELECT day, device, name FROM session_days
    UNION
    SELECT day, device, name FROM turn_days
)
SELECT
    spine.day AS day,
    spine.device AS device,
    spine.name AS name,
    coalesce(session_days.sessions, 0) AS sessions,
    coalesce(session_days.telemetry_sessions, 0) AS telemetry_sessions,
    coalesce(turn_days.turns, 0) AS turns
FROM spine
LEFT JOIN session_days
    ON session_days.day IS NOT DISTINCT FROM spine.day
    AND session_days.device IS NOT DISTINCT FROM spine.device
    AND session_days.name IS NOT DISTINCT FROM spine.name
LEFT JOIN turn_days
    ON turn_days.day IS NOT DISTINCT FROM spine.day
    AND turn_days.device IS NOT DISTINCT FROM spine.device
    AND turn_days.name IS NOT DISTINCT FROM spine.name
""",
)

COMMENT: tuple[str, ...] = (
    (
        "COMMENT ON VIEW record.metrics_stage_latency_by_device_daily IS 'How slow "
        "was each pipeline stage, by UTC day and by the agent the turn started "
        "with? Broken down by the device the session ran on. The denominator is the "
        "turns that measured that stage, never all turns, and it is "
        "`measured_turns` beside the percentiles rather than a number a reader has "
        "to go and find. Every denominator here is that device''s own: the rows are "
        "split by device and by the name that device recorded before anything is "
        "counted, so a column means what it means on the ungrouped view with the "
        "day narrowed to one of them. A session whose device was never understood "
        "groups as a null-device row rather than vanishing, the way a null agent "
        "already does, and so does a session that recorded no name. The name is in "
        "that split because it is dated: a board renamed inside the window is one "
        "row per name it was recorded under rather than one series retitled.'"
    ),
    (
        "COMMENT ON VIEW record.metrics_tokens_by_device_daily IS 'What did each "
        "agent consume, by UTC day? Broken down by the device the session ran on. "
        "The unit is the attribution row, not the turn: a turn with `legs` "
        "contributes one attribution row per leg and its turn-level totals are not "
        "counted, and a turn without `legs` contributes one attribution row from "
        "the turn itself. `input_measured_turns` and `output_measured_turns` are "
        "counts of attribution rows whose respective token field is not null, "
        "stated separately because the store writes the two sums independently. "
        "Every denominator here is that device''s own: the rows are split by device "
        "and by the name that device recorded before anything is counted, so a "
        "column means what it means on the ungrouped view with the day narrowed to "
        "one of them. A session whose device was never understood groups as a "
        "null-device row rather than vanishing, the way a null agent already does, "
        "and so does a session that recorded no name. The name is in that split "
        "because it is dated: a board renamed inside the window is one row per name "
        "it was recorded under rather than one series retitled.'"
    ),
    (
        "COMMENT ON VIEW record.metrics_event_rates_by_device_daily IS 'How often "
        "did a provider fail and how often was a barge-in suppressed, against the "
        "traffic of the same day? Broken down by the device the session ran on. "
        "Failures are per turn and suppressions are per session, both by their UTC "
        "day, and both denominators are columns of this view rather than numbers a "
        "reader has to fetch from somewhere else. Each of the four streams is "
        "aggregated on its own and the four are joined over the union of their "
        "days, so an event on a day with no session start and no turn still gets a "
        "row. Every denominator here is that device''s own: the rows are split by "
        "device and by the name that device recorded before anything is counted, so "
        "a column means what it means on the ungrouped view with the day narrowed "
        "to one of them. A session whose device was never understood groups as a "
        "null-device row rather than vanishing, the way a null agent already does, "
        "and so does a session that recorded no name. The name is in that split "
        "because it is dated: a board renamed inside the window is one row per name "
        "it was recorded under rather than one series retitled.'"
    ),
    (
        "COMMENT ON VIEW record.metrics_sessions_by_device_daily IS 'What baseline "
        "sits under the numbers in every other view? Broken down by the device the "
        "session ran on. There is no ratio here: these are the counts the other "
        "views divide by. Sessions are counted by the UTC day they opened on and "
        "turns by the UTC day they were spoken on, so a session that crossed "
        "midnight lands on one day and its later turns on the next. Every "
        "denominator here is that device''s own: the rows are split by device and "
        "by the name that device recorded before anything is counted, so a column "
        "means what it means on the ungrouped view with the day narrowed to one of "
        "them. A session whose device was never understood groups as a null-device "
        "row rather than vanishing, the way a null agent already does, and so does "
        "a session that recorded no name. The name is in that split because it is "
        "dated: a board renamed inside the window is one row per name it was "
        "recorded under rather than one series retitled.'"
    ),
)

RESTORE: tuple[str, ...] = (
    """
CREATE OR REPLACE VIEW record.metrics_stage_latency_by_device_daily AS
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
CREATE OR REPLACE VIEW record.metrics_tokens_by_device_daily AS
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
CREATE OR REPLACE VIEW record.metrics_event_rates_by_device_daily AS
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
CREATE OR REPLACE VIEW record.metrics_sessions_by_device_daily AS
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

RESTORE_COMMENT: tuple[str, ...] = (
    (
        "COMMENT ON VIEW record.metrics_stage_latency_by_device_daily IS 'How slow "
        "was each pipeline stage, by UTC day and by the agent the turn started "
        "with? Broken down by the device the session ran on. The denominator is the "
        "turns that measured that stage, never all turns, and it is "
        "`measured_turns` beside the percentiles rather than a number a reader has "
        "to go and find. Every denominator here is that device''s own: the rows are "
        "split by device before anything is counted, so a column means what it "
        "means on the ungrouped view with the day narrowed to one device. A session "
        "whose device was never understood groups as a null-device row rather than "
        "vanishing, the way a null agent already does.'"
    ),
    (
        "COMMENT ON VIEW record.metrics_tokens_by_device_daily IS 'What did each "
        "agent consume, by UTC day? Broken down by the device the session ran on. "
        "The unit is the attribution row, not the turn: a turn with `legs` "
        "contributes one attribution row per leg and its turn-level totals are not "
        "counted, and a turn without `legs` contributes one attribution row from "
        "the turn itself. `input_measured_turns` and `output_measured_turns` are "
        "counts of attribution rows whose respective token field is not null, "
        "stated separately because the store writes the two sums independently. "
        "Every denominator here is that device''s own: the rows are split by device "
        "before anything is counted, so a column means what it means on the "
        "ungrouped view with the day narrowed to one device. A session whose device "
        "was never understood groups as a null-device row rather than vanishing, "
        "the way a null agent already does.'"
    ),
    (
        "COMMENT ON VIEW record.metrics_event_rates_by_device_daily IS 'How often "
        "did a provider fail and how often was a barge-in suppressed, against the "
        "traffic of the same day? Broken down by the device the session ran on. "
        "Failures are per turn and suppressions are per session, both by their UTC "
        "day, and both denominators are columns of this view rather than numbers a "
        "reader has to fetch from somewhere else. Each of the four streams is "
        "aggregated on its own and the four are joined over the union of their "
        "days, so an event on a day with no session start and no turn still gets a "
        "row. Every denominator here is that device''s own: the rows are split by "
        "device before anything is counted, so a column means what it means on the "
        "ungrouped view with the day narrowed to one device. A session whose device "
        "was never understood groups as a null-device row rather than vanishing, "
        "the way a null agent already does.'"
    ),
    (
        "COMMENT ON VIEW record.metrics_sessions_by_device_daily IS 'What baseline "
        "sits under the numbers in every other view? Broken down by the device the "
        "session ran on. There is no ratio here: these are the counts the other "
        "views divide by. Sessions are counted by the UTC day they opened on and "
        "turns by the UTC day they were spoken on, so a session that crossed "
        "midnight lands on one day and its later turns on the next. Every "
        "denominator here is that device''s own: the rows are split by device "
        "before anything is counted, so a column means what it means on the "
        "ungrouped view with the day narrowed to one device. A session whose device "
        "was never understood groups as a null-device row rather than vanishing, "
        "the way a null agent already does.'"
    ),
)


def upgrade() -> None:
    for statement in REPLACE:
        op.execute(statement)
    for statement in COMMENT:
        op.execute(statement)


def downgrade() -> None:
    for statement in RESTORE:
        op.execute(statement)
    for statement in RESTORE_COMMENT:
        op.execute(statement)
