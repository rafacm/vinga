# The by-device views read the name a session recorded

**Date:** 2026-09-12

## Problem

The four per-device aggregate views shipped with a `name` column that
was `NULL::text` in every row. That was deliberate and temporary: the
column was declared so the shape a caller reads would not move on the
day a label arrived, and the label could not be a join, because
`deploy/postgres-init.sql` grants the read-only analyst role on `record`
and revokes it on `domain`. Nothing on the `record` side carried a name
yet.

Something does now. `record.sessions.device_name` holds what the board
was called at the instant the session opened, written for exactly this
reader: the analyst looking at a per-device breakdown who cannot look a
MAC up anywhere.

The question the follow-through had to answer is what a row is. The
recorded name is dated and never rewritten, so a board renamed in the
middle of a window has sessions carrying both names, and there is no one
label for the pair.

## Changes

### The name is read off the session, in all four views

Each per-device view selects `sessions.device_name` as `name` where it
selected the literal null. The four ungrouped views are untouched, as
they were by the migration that added the siblings.

### The name joins what makes a row one row

One row per `(day, device, name)` rather than per `(day, device)`, and
the column is declared `key=True`, which is what the reference's "one
row per" line and the read surface's ordering both read.

The alternative considered and rejected was the device's most recent
name in the window. It reads better on a dashboard and it is a lie about
the record: it stamps today's label onto numbers that were recorded
under a different one, and it leaves no rows behind from which the
original reading could be recovered. Splitting is recoverable in the
other direction, because a reader who wants the board whole groups on
`device`, which is the identity and survives any rename.

### A null name is a group, not an absence

Nothing backfilled `device_name`, so every session recorded before it
existed carries a null there, as does every board nobody has named.
Those rows keep aggregating into one row per device exactly as they did
when the column was the literal null. In the two views that combine
independently aggregated streams, that required carrying the name
through the spine and joining it with `IS NOT DISTINCT FROM`, the same
treatment the nullable device already gets: `=` does not match two
nulls, so an equality join would scatter such a group across its streams
and return zeroes with broken rates.

### The HTTP answer strips a URL credential from the name

The column is documented to keep what the operator wrote: `vinga_ro` is
granted the record schema on purpose, and a row is not a display. The
projection therefore belongs where a reader is answered, and now that a
metrics row carries the name, `_aggregated()` is a second such place
beside `read_session`. Every non-null `name` leaves through
`without_url_credential`, the same one rule that the session detail, the
display walk and the spoken identities read from (#381, #472).

Applied after the ordering rather than before it, so the page a caller
pages through stays ordered on what the view stores: two names differing
only in a credential are two rows there, and re-sorting on the stripped
form would move one of them. The CLI needs no change of its own, since
it renders the columns the answer carries.

### Migration `1009_views_read_the_name`

`CREATE OR REPLACE VIEW` for the four, with the same column list in the
same order, so no relation is dropped and no oid moves: a saved query, a
dashboard or a downstream view standing on one of them still stands. The
view comments move with the definitions, because the denominator
sentence now has to say what a row is one row of. The downgrade restores
the 1008 definitions and comments literally.

## Key parameters

| What | Value |
| --- | --- |
| Conversations chain head | `1009_views_read_the_name` |
| Views replaced | `metrics_stage_latency_by_device_daily`, `metrics_tokens_by_device_daily`, `metrics_event_rates_by_device_daily`, `metrics_sessions_by_device_daily` |
| Column read | `record.sessions.device_name` (nullable, dated, never rewritten) |
| Row grain | one row per `(day, device, name)` plus whatever the mirrored view was cut by |
| API and CLI shape | unchanged; `name` was already in the row contract, nullable |
| HTTP projection | every non-null `name` through `without_url_credential`, after the ordering |

## Verification

- `uv run ruff check .` passes.
- `uv run pytest tests/unit -q -n 4 --dist loadfile` passes.
- `uv run pytest tests/integration -q` passes.
- The agreement test (`pg_get_viewdef` of every declaration against the
  live view) was watched red between the module edit and the migration,
  which is what it exists to catch.
- The integration suite asserts the numbers: a board under two names on
  one day is two rows against an ungrouped total that did not move, and
  sessions recording no name at all still aggregate into one row with
  their own numbers and rates.
- The upgrade suite asserts a database that stood at `1006_metrics_views`
  reaches the new head, keeps the four original views by oid, and answers
  the siblings with the recorded name.
- A credential-bearing name planted in the record is absent from every
  metrics answer, from the CLI's rendering of one and from both shipped
  log formats, with the stripped address asserted present as the
  control; the stored column still holds it as written. Both cases were
  watched red with the projection removed.
- The wheel migration step runs only in CI and is not verified locally.

## Files modified

- `vinga-server/src/vinga_server/conversations/views.py`
- `vinga-server/src/vinga_server/conversations/api.py`
- `vinga-server/src/vinga_server/conversations/migrations/versions/1009_views_read_the_name.py`
- `vinga-server/tests/support/stores.py`
- `vinga-server/tests/unit/test_conversations_views.py`
- `vinga-server/tests/unit/test_conversations_metrics_api.py`
- `vinga-server/tests/unit/test_config_cli_metrics.py`
- `vinga-server/tests/unit/test_conversations_schema.py`
- `vinga-server/tests/integration/test_conversations_views.py`
- `vinga-server/tests/integration/test_metrics_views_upgrade.py`
- `docs/reference/metrics-views.md` (generated)
- `.github/workflows/vinga-server.yml`
- `changelog.d/474-by-device-names.md`
