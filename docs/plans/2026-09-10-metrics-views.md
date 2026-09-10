# Named aggregate views over the conversation record

Plan for [issue #439](https://github.com/rafacm/vinga/issues/439).
Companion implementation doc:
`2026-09-10-metrics-views-implementation.md`, one section per
milestone, appended in the same change that ticks the milestone
checklist.

## Goal

"What is the p95 ASR latency this week" stops being a hand-written
query invented fresh each time. The record schema gains named,
commented aggregate views, added by migration and readable by
`vinga_ro`; a generated reference page states each view's question,
denominator and telemetry-off behavior; and a committed script
measures per-turn perceived latency from a capture, honestly, with
its precision stated in its own output. Nothing changes in what is
stored.

## The issue's decisions, restated

- Three deliverables, all reading what already lands: views by
  migration, per-view reference documentation, the capture
  perceived-latency script. No storage change.
- The API and CLI surface over the views is #440's, as are budgets,
  cost accounting and any retention question. No exporter or scrape
  endpoint arrives here; #66/#67 own export.
- Aggregates see back `retention_days`; nothing here touches
  retention.
- The views are the aggregates the word "metrics" is reserved for
  (#437 cleared the vocabulary).
- The script needs capture on (field-test practice) and answers
  "800 ms or 2.5 s", never milliseconds.

## Open questions, resolved

### The perceived-latency premise, corrected by the repo's own data

The issue says the capture's mic channel records the room including
the device's own speaker, so the reply's acoustic onset can be read
from channel 0. The repository's own field evidence contradicts
this: the #48 echo-leakage analysis (`scripts/echo_leakage.py`, its
figures in that issue's closing comment) found no measurable echo
path on the field-tested board, with the assistant's voice below
the ambient floor for all three voices, in quiet and in noise. The
board's echo canceller removes exactly the signal this script was
told to look for. And on a simulator capture the mic channel
definitively contains no reply audio at all: the simulator counts
reply frames without decoding them and never plays them back, so
the acceptance criterion "reports per-turn perceived latency on a
capture produced by the simulator" is unsatisfiable from channel 0
by construction.

The script therefore measures on the capture's shared timeline with
two paths, and says which it used, per turn:

- **The wire path, always available**: end of user speech read from
  channel 0 (the decoded microphone) diffed against the reply's
  onset in channel 1 (the wire-true reply channel: what was paced
  out, when it was paced out). This is the latency the server
  imposed, excluding only the device's own playout buffer, which is
  bounded and small next to the second-scale answers this script
  exists for; the exclusion is stated in the output.
- **The room path, attempted and reported when detectable**: the
  reply's acoustic onset in channel 0, for a board or a volume at
  which the canceller does leak the onset. When no onset rises
  above the ambient floor, the script says so instead of inventing
  one, which per #48 is the expected case on the tested board.

Both numbers answer the issue's question at the issue's stated
precision; the deviation from the issue's letter (the room path
cannot be the only path) is recorded here with its evidence, and a
comment stating the correction goes on the issue when the plan
lands, since the premise came from a decision recorded there.

### The views, and the one-home tension with frozen migrations

The repository convention is that migrations spell their SQL
literally rather than importing it (the 1003/1004 precedent:
migration files are frozen history), while the design rule says two
structures that must agree are one structure with a bug pending.
Both hold, as follows: a new module,
`src/vinga_server/conversations/views.py`, is the one home for what
a view *is*: name, SQL definition, the question it answers, its
denominator, and its telemetry-off behavior, as declared data. The
migration spells the same `CREATE VIEW` statements literally, as
frozen history must, and an integration test proves agreement: the
live definition of every declared view (`pg_get_viewdef`) matches
the declaration, so drift between the module and the migration
chain is a red test, not a latent lie. The docgen and the analyst
tests iterate the declarations; nothing iterates the migration.

The views themselves, first cut (the plan's list; the milestone may
adjust names, never semantics, and the implementation doc records
any adjustment):

- **`metrics_stage_latency_daily`**: per day, per agent, per stage
  (asr_ms, first_token_ms, llm_ms, tts_first_audio_ms), count,
  p50/p95/max via `percentile_cont`, over turns whose stage value
  is non-null. Postgres 17 is the floor everywhere, so ordered-set
  aggregates are safe; these are the repository's first views and
  first ordered-set aggregates, noted so nobody hunts for
  precedent.
- **`metrics_tokens_daily`**: per day, per agent: turns, summed
  input_tokens and output_tokens over non-null rows, and
  `measured_turns` so a consumer can see how much of the day the
  sum covers.
- **`metrics_event_rates_daily`**: per day: provider failures,
  barge-in suppressions (all three variants), discarded
  transcripts, each as a count beside the day's turn and session
  denominators, computed from the events rows joined to their
  sessions' days.
- **`metrics_sessions_daily`**: per day: sessions, telemetry-on
  sessions (`sessions.metrics`, the column that deliberately keeps
  the old name), turns, so every other view's denominator has a
  stated baseline beside it.

### Telemetry-off, in every view

A turn stored under telemetry-off has every measured column null
and its session has no events rows at all (`sessions.metrics =
false`, the store nulls the nine measured columns and writes no
events). Each view therefore counts explicitly: latency and token
views aggregate over non-null values and carry `measured_turns`
beside `turns`, so the denominator never silently shrinks; the
event-rate view's documentation states that a telemetry-off
session contributes to the session and turn denominators while
contributing no numerator events, which is a property of the data,
not a bug in the view, and the reference page says exactly that
sentence.

### The retention skew, stated rather than hidden

Events rows and their session's other rows age out on the same
session-age rule, but a rate whose numerator and denominator age
independently can see a boundary week where one side is partly
deleted. The daily grain bounds the skew to the boundary days of
the retention window; the reference page carries the caveat and the
views do not try to be cleverer than the data.

### `vinga_ro` reads the views without a new grant

The role's default privileges (`ALTER DEFAULT PRIVILEGES ... GRANT
SELECT ON TABLES`) cover views created later by the server role,
and the migration runs as the server role, which is the existing
provisioning precedent (the analyst-inherits-a-later-table case in
`tests/integration/test_provisioning.py`). The analyst-read tests
currently iterate `schema.TABLES`; they gain the view declarations
as a second iterated list so every view's readability is asserted,
not assumed.

### The migration and the CI pin

One migration, `1005_metrics_views` (well under the 32-character
`alembic_version` limit), on the conversations chain: `CREATE VIEW`
per view with `COMMENT ON VIEW`, downgrade drops them. The CI
wheel-migration step's conversations head pin moves from
`1004_telemetry_names_the_switch` to `1005_metrics_views`,
deliberately, in the same change; the step's expected-table
assertion is untouched because `get_table_names` does not return
views, verified rather than assumed in the milestone.

### The reference page is generated, like the directory it joins

`docs/reference/` is classified whole as generated-and-diffed by
the authority taxonomy, so the per-view documentation is a new
generated page, `docs/reference/metrics-views.md`, rendered from
the `views.py` declarations by the existing conversations docgen
machinery (a sibling renderer beside the schema page, not a second
convention): per view, the question, the columns, the denominator,
the telemetry-off sentence, and the shared caveats (retention
boundary, the `metrics` column's old name). The rendering needs a
CLI home for the drift check to invoke: the conversations noun's
`schema` verb renders one document today, so the page gets a
sibling verb (`views` beside `schema`) unless the cli-guide
checklist, run in the milestone, prefers a selector on the
existing verb; the choice is recorded in the implementation doc.
The page enters the CI drift checks beside the
schema page and the docs index in the same commit, per the
taxonomy's own rule.

### The script

`scripts/perceived_latency.py`, in the committed-script house style
(`upstream_watch.py`: docstring with a usage block, explicit exit
codes 0/1/2, output that never echoes stray values) rather than the
looser `echo_leakage.py` shape, because it lands with tests and
runs in CI against a fixture. Stdlib only (`wave`, `array`
arithmetic at 16 kHz mono is enough for energy envelopes); no numpy
dependency, so it runs under `uv run` with no extras. Per turn it
reports: end of user speech (channel 0 energy fall confirmed by the
JSONL decision track's utterance boundary when present), wire reply
onset (channel 1 energy rise), the wire-path latency, the room-path
onset when detectable with its threshold, and the standing
precision sentence in its own output, per the acceptance
criterion. Unit tests cover the envelope arithmetic and the
output discipline on synthetic WAV fixtures; the integration proof
is below.

### The end-to-end proof needs a capture that does not exist yet

No integration test currently produces a capture at all; capture
coverage is unit-lane through a test client. The milestone adds one
integration case: a real server with capture enabled, one simulator
conversation, then the script over the produced triplet, asserting
it reports a wire-path latency for the turn and prints its
precision caveat. This is the acceptance criterion made runnable,
and it doubles as the repository's first end-to-end capture proof.

## Module layout

- `src/vinga_server/conversations/views.py`: the declarations (name,
  SQL, question, denominator, telemetry-off sentence). Callers stop
  having to know SQL or where views are defined: docgen renders it,
  tests iterate it, the agreement test compares the database against
  it. Deletion test: inlining it into docgen would make the analyst
  tests and the agreement test read documentation code for data;
  inlining into the migration is forbidden by frozen history.
- `src/vinga_server/conversations/migrations/versions/1005_metrics_views.py`:
  frozen literal DDL.
- The docgen renderer beside the schema one, reading `views.py`.
- `scripts/perceived_latency.py` with its unit tests.

No new package, no new config, no API change.

## Tests

- **Integration, numbers**: seed by driving conversations the
  `test_conversations.py` way (mock providers, deterministic
  timings), including turns under telemetry-off; assert each view's
  rows against the known inputs via the existing `read()` pattern:
  percentiles over a known distribution, token sums with
  `measured_turns` smaller than `turns`, event rates with the
  telemetry-off session in the denominator only.
- **Integration, agreement**: every declared view exists live with
  a definition matching `views.py` (`pg_get_viewdef` normalized),
  and is commented.
- **Integration, analyst**: `vinga_ro` selects from every declared
  view (the `_as_analyst` helper over the declarations list).
- **Integration, wheel/CI**: the chain-head pin moves; the
  expected-tables assertion stays green with views present.
- **Integration, end to end**: the capture-producing simulator case
  feeding the script, as above.
- **Unit**: docgen drift for the new page; the script's envelope
  arithmetic, per-turn report shape, caveat sentence, and exit
  codes on missing or incomplete captures.

## Risks

- **First views in the repo**: autogenerate must not try to manage
  them. Views live outside `schema.py`'s metadata, so
  `compare_metadata` never sees them; the agreement test is the
  drift guard instead. Stated so nobody "fixes" it later by adding
  them to metadata.
- **Percentile semantics under tiny samples**: `percentile_cont`
  interpolates; a day with two turns reports a p95 that is mostly
  arithmetic. The reference page says percentiles are read with
  their count beside them.
- **The script's onset detection in a room is genuinely imprecise**:
  bounded by design; the output's precision sentence is the
  mitigation, and the wire path does not share the problem.
- **Parallel work**: #66's milestone train touches the CHANGELOG,
  the census manifest and the generated events docs on the same
  days; every rebase re-runs the generators on the rebased tree
  rather than merging generated text.

## Milestones

- [ ] **M1: the views, the reference and the proof.** `views.py`,
  migration `1005_metrics_views`, the docgen renderer and generated
  `docs/reference/metrics-views.md` (docs index and CI drift check
  in the same change), the CLI selector decision recorded, the CI
  chain-head pin move, and the integration tests: numbers,
  agreement, analyst, wheel. Design footprint: deepens the
  conversations package with one declarations module; the migration
  is frozen history; no new seam. Documentation footprint: the new
  generated page, `docs/README.md` reference index,
  `docs/architecture/observability-surfaces.md` five-surfaces table
  rows for events ("feedstock for 5" becomes served) and the
  conversation store, CHANGELOG.
- [ ] **M2: perceived latency from a capture.** The script in house
  style with unit tests, the capture-producing simulator
  integration case feeding it, and the issue comment correcting the
  mic-channel premise with the #48 evidence once merged.
  Design footprint: one committed script, no server change.
  Documentation footprint: the script's usage block is its page;
  the capture section of the glossary gains nothing (the format is
  unchanged); CHANGELOG.
