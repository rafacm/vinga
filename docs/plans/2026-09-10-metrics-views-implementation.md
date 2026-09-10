# Named aggregate views over the conversation record: implementation

Companion to [`2026-09-10-metrics-views.md`](2026-09-10-metrics-views.md).
One section per milestone, appended in the same change that ticks the
milestone checklist: deviations from the plan, resolutions of its open
questions, and what was discovered on the way.

## M1: the views, the reference and the proof

PR TBD.

### What landed

`src/vinga_server/conversations/views.py` is the one home for what a
view is: name, question, denominator sentence, telemetry-off sentence,
a per-column declaration matrix (name, type, meaning, units,
nullability, formula), and the SQL body. Four views, exactly the ones
the plan freezes, with the frozen column names and types. The three
shared rules the plan states (a UTC day derived from
`started_at::timestamptz AT TIME ZONE 'UTC'` plus the row's `t_ms`,
counting per stored row, a null rate on a zero denominator) live in
that module as one `SESSION_DAY` constant and one `offset_day` helper
that every definition reads, so four definitions cannot come to
disagree about what a day is.

Migration `1006_metrics_views` spells the same `CREATE VIEW` statements
literally, with a `COMMENT ON VIEW` carrying each view's question and
denominator, and a downgrade that drops all four.

`docgen.views_reference()` renders `docs/reference/metrics-views.md`
from the declarations, and `vinga-server conversations views` prints
it. The moved pins the plan enumerated all moved: the CLI test that
pinned `schema` as the sole command, the group's help text and its
refusal sentence, the workflow's drift-check list, the docs index, and
the spellings manifest.

Tests: eight integration cases seeded by exact SQL rows, an agreement
case, a live-column-list case, a comment case, and the analyst cases in
`test_provisioning.py`; a unit suite over the declarations and the
rendered page.

### Deviations

- **The migration is `1006_metrics_views`, not `1005_metrics_views`.**
  The plan was written before PR #442 merged, and that PR took the 1005
  slot on the conversations chain with `1005_providers_are_per_agent`,
  a column-comment migration. So this one is 1006 and its
  `down_revision` is `1005_providers_are_per_agent`. The id is 18
  characters, well under the 32-character `alembic_version` limit. The
  CI wheel step's chain-head pin therefore moves from
  `1005_providers_are_per_agent` to `1006_metrics_views` rather than
  from `1004_telemetry_names_the_switch`, and the unit suite's `HEAD`
  constant moves with it. Nothing else about the migration changed.

- **The renderer is a second function in `docgen.py`, not a second
  module.** The plan says "a sibling renderer beside the schema one",
  which reads either way. A new module would have needed its own copy
  of `_paragraph` and `_cell`, and two copies of the wrapping rule are
  two things that must agree about what a committed page looks like:
  exactly the shape the design guide's locality rule rejects. The
  module is still one responsibility, documenting this store, and its
  docstring now says both documents and their two sources.

- **The workflow's "five generated-document drift checks" comment lost
  its number instead of gaining one.** The count was already wrong
  before this change (six documents were checked, not five), so
  incrementing it would have replaced one wrong number with another.
  The sentence now names no count, with the reason written beside it:
  the steps are the list.

- **One test written and then removed.** A case asserting that
  `vinga_ro` cannot `delete from record.metrics_sessions_daily` came
  back `55000` (object not in prerequisite state) rather than `42501`
  (insufficient privilege): an aggregate view is not automatically
  updatable, so Postgres refuses on the view's shape before it consults
  a privilege. The case would have been asserting Postgres's own
  updatability rule rather than anything the provisioning file
  promises, and the base-table refusal is already covered by
  `test_the_analyst_role_cannot_write_what_it_can_read`, so it was
  dropped rather than reworded.

Everything else follows the plan and its two review rounds as written.
No column name, type or predicate departs from the frozen contracts.

### Discoveries

- **The stored event names are the ones the plan freezes.** Verified
  against `docs/reference/events.md` and
  `vinga_server/events/catalog.py`: `provider_failed` and
  `barge_in_suppressed` are stored exactly so, and the catalog carries
  one `barge_in_suppressed` name at INFO with three variants that
  differ in `fields.reason`. No correction was needed, and the
  predicates are the plan's literals with no reason filter.

- **`get_table_names` really does exclude views, verified rather than
  assumed.** On a database migrated to `1006_metrics_views`,
  `inspect(engine).get_table_names(schema="record")` returns the six
  tables plus `alembic_version` and none of the four views, while
  `get_view_names` returns exactly the four. So the CI wheel step's
  expected-table assertion needs no change, and
  `compare_metadata(context, schema.metadata)` still returns `[]` with
  the views present, which is what keeps the baseline-equality test
  green and is why views deliberately stay outside `schema.py`'s
  `MetaData`.

- **`ALTER DEFAULT PRIVILEGES ... GRANT SELECT ON TABLES` covers a
  view.** Postgres counts a view as a relation of the `TABLES` class,
  so `vinga_ro` reads all four with no new grant in
  `deploy/postgres-init.sql`, asserted by iterating the declarations in
  `test_provisioning.py` rather than assumed.

- **The agreement test needed no normalizer of its own.** Rather than
  comparing two formatted strings, it creates a shadow view from the
  declaration inside a savepoint, reads `pg_get_viewdef` of both the
  shadow and the migrated view, and rolls the savepoint back. Postgres
  does the normalizing, so the comparison survives whitespace and
  survives the planner rewriting a construct into its own spelling.
  A savepoint rather than a transaction, because reading the live
  definition first has already autobegun one on that connection.

- **`json_array_elements` needs its guard inside the call, not in the
  join condition.** A `LEFT JOIN LATERAL ... ON json_typeof(legs) =
  'array'` still evaluates the function before applying the condition
  and would error on a turn whose `legs` is a JSON object. The guard is
  a `CASE` inside the argument instead, which hands the strict
  set-returning function a NULL and yields zero rows, so the left join
  falls back to the turn row.

- **Two view comments were reworded to avoid an apostrophe.** A
  `COMMENT ON VIEW` takes no bind parameter, so its text is a SQL
  literal in frozen history; rewording ("the traffic of the same day",
  "the numbers in every other view") keeps the migration free of
  doubled quotes rather than freezing an escaping subtlety.

- **The percentile numbers are worth pinning as literals.** Over 100,
  200, 300 and 400 ms, `percentile_cont` gives 250.0 and 385.0 where
  `percentile_disc` would give 200 and 400. The integration case
  asserts the interpolated pair, so a later change of aggregate is a
  red test rather than a quietly different number.
