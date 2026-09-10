# The conversations storage switch is named telemetry

**Date:** 2026-09-10

## Problem

The storage switch under `server.conversations` that nulls every
measured number and skips the events rows was named `metrics` (#437).
It is a storage privacy switch: nothing aggregates what it keeps and
nothing exports it. The word is promised twice elsewhere: the
observability map reserves "metrics" for need 5, the future aggregation
surface, and #66 introduces a `server.telemetry` section for export.
Once that lands, `metrics: true` under conversations, near a telemetry
section, reads as an export switch, and the API already had to fight
the confusion in prose (the thread `incomplete` description went out of
its way to say it sits outside the switch).

The repository owns the right word: the content-and-telemetry ADR names
exactly this split, and the `ConversationsConfig` docstring called the
switch's subject "the behavioural telemetry". So the pair becomes
`text` (the content) and `telemetry` (the behaviour). Storing beside
exporting under one word is acceptable adjacency: the substance is the
same and only the verb differs.

## Changes

- `ConversationsConfig.metrics` is `ConversationsConfig.telemetry`. No
  alias and no shim, per the pre-release stance: `extra="forbid"`
  refuses a config still saying `metrics:` at boot with the existing
  unknown-key error, and a new test pins that refusal.
- The session detail response serves `telemetry`, and every
  "metrics-off" phrase in the response field descriptions now says
  "telemetry-off". An API-breaking rename, made while it costs nothing.
- `vinga session show` prints `telemetry:` in the session block.
- The store's constructor parameter and attribute follow
  (`ConversationStore(telemetry=...)`), because the composition passes
  the config switches by name and one seam should not keep the old
  vocabulary alive.
- The `sessions.metrics` column keeps its name: column names are a
  compatibility surface, and this renames configuration and API
  vocabulary, not storage. `read_session` translates the column to the
  response field, and the schema reference says the column kept the
  switch's original name rather than leaving the mismatch to the
  reader.
- The schema's column comments spelled the old word in fourteen places;
  they are committed DDL, so `1004_telemetry_names_the_switch` moves
  them in migrated databases the way `1003_rename_moves_ownership`
  moved the thread ownership comment. It spells the old texts out and
  states the new ones as the three phrase replacements the rename is.
  The wheel-migration check's expected head moves with it.
- Both example configs, the server README's yaml block and switch
  table, and the observability map's switch pair say `telemetry`. The
  three generated documents (`server-config.md`,
  `conversations-schema.md`, `api-openapi.json`) are regenerated.

Untouched, deliberately: historical plans, implementation docs and
ADRs, which record what was true when written; the record schema's
table and column names; and migrations 1002 and 1003, which keep the
comment texts of their own moments.

## Key parameters

| Parameter | Value |
| --- | --- |
| Config key | `server.conversations.telemetry`, default `true` |
| Old key | `server.conversations.metrics`, refused at boot |
| API field | `telemetry` on the session detail response |
| Column | `sessions.metrics`, unchanged |
| Migration | `1004_telemetry_names_the_switch`, comments only |

## Verification

- `uv run ruff check .` clean.
- `uv run pytest tests/unit -q -n auto --dist loadfile`: 5974 passed,
  19 skipped.
- `uv run pytest tests/integration -q`: 245 passed.
- All five generated-document drift checks clean (domain and server
  config references, conversations schema, events, OpenAPI).
- The baseline-equality test compares column comments through Alembic's
  autogeneration, so the migrated database and the declarations moving
  together is proven rather than hoped.

## Files modified

- `vinga-server/src/vinga_server/config/models.py`
- `vinga-server/src/vinga_server/config/responses.py`
- `vinga-server/src/vinga_server/config/cli.py`
- `vinga-server/src/vinga_server/conversations/store.py`
- `vinga-server/src/vinga_server/conversations/schema.py`
- `vinga-server/src/vinga_server/conversations/api.py`
- `vinga-server/src/vinga_server/conversations/docgen.py`
- `vinga-server/src/vinga_server/conversations/records.py`
- `vinga-server/src/vinga_server/conversations/migrations/versions/1004_telemetry_names_the_switch.py` (new)
- `vinga-server/src/vinga_server/app.py`
- `vinga-server/config.example.yaml`, `vinga-server/config.deploy.example.yaml`
- `vinga-server/README.md`, `docs/architecture/observability-surfaces.md`
- `docs/reference/server-config.md`, `docs/reference/conversations-schema.md`,
  `docs/reference/api-openapi.json` (regenerated)
- `.github/workflows/vinga-server.yml` (wheel check's expected head)
- Unit tests across `tests/unit/test_config*.py` and
  `tests/unit/test_conversations_*.py`
