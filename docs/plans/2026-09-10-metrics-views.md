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
columns, denominator and telemetry-off behavior; and a committed
script measures per-turn latency from a capture, honestly, with its
precision stated in its own output. Nothing changes in what is
stored. The script milestone is blocked on a maintainer decision
recorded below; the views milestone is not.

## The issue's decisions, restated

- Three deliverables, all reading what already lands: views by
  migration, per-view reference documentation, the capture
  latency script. No storage change.
- The API and CLI surface over the views is #440's, as are budgets,
  cost accounting and any retention question. No exporter or scrape
  endpoint arrives here; #66/#67 own export.
- Aggregates see back what retention keeps; nothing here touches
  retention.
- The views are the aggregates the word "metrics" is reserved for
  (#437 cleared the vocabulary).
- The script needs capture on (field-test practice) and answers
  "800 ms or 2.5 s", never milliseconds.

## Open questions, resolved

### The perceived-latency premise fails on the repository's own evidence, and the resolution is the maintainer's

The issue says the capture's mic channel records the room including
the device's own speaker, so the reply's acoustic onset can be read
from channel 0. Two repository facts contradict it:

- The #48 echo-leakage analysis (`scripts/echo_leakage.py`, figures
  in that issue's closing comment) found no measurable echo path on
  the field-tested board: the assistant's voice sits below the
  ambient floor for all three voices, in quiet and in noise. The
  board's echo canceller removes exactly the signal the script was
  told to look for.
- A simulator capture's mic channel contains no reply audio at all,
  by construction: the simulator counts reply frames without
  decoding them and never plays anything back. The acceptance
  criterion "reports per-turn perceived latency on a capture
  produced by the simulator" is unsatisfiable from channel 0.

The only measurement available on every capture is the wire path:
end of user speech in channel 0 diffed against the reply's onset in
channel 1 (what was paced out, when). That is a real and useful
number, but it is not perceived latency: it excludes downlink
transport and device playback, not merely a small playout buffer,
and calling it perceived would be false labeling. The plan
therefore does not relabel it. The decision is the issue author's,
with three honest shapes: (a) rename the deliverable to wire
response latency and keep the simulator criterion; (b) authorize a
simulator acoustic-loopback facility so channel 0 carries a
synthetic room and the acoustic algorithm has a lab fixture; (c)
keep the acoustic-onset deliverable as a board-capture tool, drop
the simulator criterion, and accept that on the tested board the
expected answer is "no onset above ambient". A comment stating the
contradiction and the three shapes goes on the issue when this plan
lands; milestone 2 waits for the answer and its section below
records what is fixed regardless of it.

### The views, and the one-home tension with frozen migrations

The repository convention is that migrations spell their SQL
literally rather than importing it (the 1003/1004 precedent:
migration files are frozen history), while the design rule says two
structures that must agree are one structure with a bug pending.
Both hold, as follows: a new module,
`src/vinga_server/conversations/views.py`, is the one home for what
a view *is*: name, the full output contract (every column with
type, meaning, units, nullability and formula), the SQL definition,
the question it answers, its denominator sentence and its
telemetry-off sentence, as declared data. The migration spells the
same `CREATE VIEW` statements literally, as frozen history must,
and an integration test proves agreement: the live definition of
every declared view (`pg_get_viewdef`, normalized) matches the
declaration, so drift between the module and the migration chain is
a red test, not a latent lie. The docgen, the analyst tests and the
number tests iterate the declarations; nothing iterates the
migration. Views live outside `schema.py`'s metadata, so
`compare_metadata` and autogenerate never see them; the agreement
test is the drift guard instead, stated so nobody "fixes" that
later.

### The view contracts, frozen

Shared definitions. **Day** is UTC, computed as
`(sessions.started_at::timestamptz AT TIME ZONE 'UTC' +
make_interval(secs => t.t_ms / 1000.0))::date` for turns and
events (both carry `t_ms` as an offset from session open), and as
the session's own `started_at` date in UTC for session membership;
every cast names UTC explicitly so the reader's session timezone
cannot move a row. **Counting** is per stored row: two provider
failures in one turn are two, deliberately. **Rates** are numerator
divided by denominator as `float`, `NULL` when the denominator is
zero. Percentiles use `percentile_cont` (Postgres 17 is the pinned
floor everywhere; these are the repository's first views and first
ordered-set aggregates).

- **`metrics_stage_latency_daily`**
  `(day date, agent text, stage text, measured_turns bigint,
  p50_ms double precision, p95_ms double precision, max_ms int)`.
  One row per day, starting agent and stage; `stage` is a literal
  from the closed set `('asr', 'first_token', 'llm',
  'tts_first_audio')` unpivoted from the four measured columns;
  rows exist only where the stage value is non-null, and
  `measured_turns` is that count. Question: how slow was each
  stage. Denominator: measured turns for that stage, never all
  turns. Percentiles are read with their count beside them; a
  two-turn day's p95 is mostly interpolation.
- **`metrics_tokens_daily`**
  `(day date, agent text, turns bigint, input_measured_turns
  bigint, output_measured_turns bigint, input_tokens bigint,
  output_tokens bigint)`. Attribution: when a turn's `legs` JSON is
  present, each leg contributes its own `agent` and token counts
  and the turn-level totals are not counted for that turn (no
  double counting); when absent, the turn row's `agent` and totals
  count. `input_measured_turns` and `output_measured_turns` are
  independent, because the store writes the two usage sums
  independently and either can be null alone. Question: what did
  each agent consume. Denominator: the two measured counts, stated
  separately.
- **`metrics_event_rates_daily`**
  `(day date, turns bigint, sessions bigint, provider_failures
  bigint, barge_in_suppressions bigint, provider_failures_per_turn
  double precision, suppressions_per_session double precision)`.
  Numerator predicates, exact: `events.name = 'provider_failed'`
  for failures; for suppressions, the catalog's suppression event
  name(s) as `docs/reference/events.md` enumerates the three
  variants, all reasons counted together, the predicate frozen in
  `views.py` and proven by the agreement and number tests.
  Denominators: the day's turns and the day's sessions (by their
  UTC membership above), joined without multiplication (numerators
  and denominators aggregate separately and join on day). Rates
  NULL on zero denominators. The issue's third numerator,
  discarded transcripts, is not derivable from what lands today:
  the prompt-echo discard is a process-wide provider event with no
  session, so no `record.events` row exists for it, and
  suppression-without-transcript means ASR returned nothing, which
  is a different fact. It is deliberately absent; the #66 plan's
  `nothing_heard` event is the stored fact it needs, and a
  follow-up migration adds the column once that vocabulary lands
  (recorded on #440's phase as the natural rider).
- **`metrics_sessions_daily`**
  `(day date, sessions bigint, telemetry_sessions bigint, turns
  bigint)`. `telemetry_sessions` counts `sessions.metrics` true,
  the column that deliberately keeps the old name. Question: what
  baseline sits under every other view's numbers.

### Telemetry-off, in every view

A turn stored under telemetry-off has every measured column null
and its session has no events rows at all (`sessions.metrics =
false`). The latency and token views aggregate over non-null values
with the measured counts beside the totals, so the denominator
never silently shrinks; the event-rate view's documentation states
that a telemetry-off session contributes to the session and turn
denominators while contributing no numerator events, a property of
the data the view reports rather than hides.

### Retention makes historical event rates unreliable, and the views say so

Turns survive with their conversation by `last_active_at` while
events are deleted by their session's `started_at` age, so a
recently resumed conversation can hold turns from arbitrarily old
sessions whose events are gone, and the database cannot distinguish
"zero events" from "events already pruned". The event view is
therefore defined as raw surviving counts, and its reference
section states the limitation in exactly those terms: a rate read
outside the events' own retention window is a floor, not a
measurement. No windowing cleverness is attempted in SQL; the
honest sentence is the design.

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

One migration, `1005_metrics_views` (under the 32-character
`alembic_version` limit), on the conversations chain: `CREATE VIEW`
per view with `COMMENT ON VIEW`, downgrade drops them. The CI
wheel-migration step's conversations head pin moves from
`1004_telemetry_names_the_switch` to `1005_metrics_views`,
deliberately, in the same change; the step's expected-table
assertion is untouched because `get_table_names` does not return
views, verified in the milestone rather than assumed.

### The reference page is generated, and its command is decided now

`docs/reference/` is classified whole as generated-and-diffed by
the authority taxonomy, so the per-view documentation is a new
generated page, `docs/reference/metrics-views.md`, rendered from
the `views.py` declarations by a sibling renderer beside the schema
one: per view, the question, the full column table from the frozen
contract, the denominator sentence, the telemetry-off sentence, and
the shared caveats (the retention limitation, the `metrics`
column's old name). The generation command is a sibling verb:
`vinga-server conversations views`, beside `schema` under the same
noun, because it renders a second document and the existing verb
renders exactly one; this is documentation generation from
declarations, not #440's deferred data-read surface, which will
query the views live. The change moves the pins that hold the
current shape: the CLI test pinning `schema` as the sole
conversations command, the CLI help texts, the workflow's drift
check list (the new page diffed beside the schema page), the docs
index, and the command-spellings manifest, each named here so the
milestone carries them deliberately.

### The script (milestone 2, blocked on the maintainer decision)

Whichever shape the maintainer picks, these hold and are recorded
now:

- `scripts/perceived_latency.py` (renamed if shape (a) is chosen)
  in the committed-script house style (`upstream_watch.py`:
  docstring with a usage block, explicit exit codes 0/1/2, output
  that never echoes stray values), stdlib only (`wave` plus array
  arithmetic at 16 kHz), with unit tests.
- A hostile-input refusal boundary: argument parsing, file access,
  WAV validation, JSON and JSONL decoding and the arithmetic sit
  behind one fixed-message refusal per failure class; sentinel
  tests prove that bad arguments, hostile paths and filenames,
  malformed content, OS errors and nested exception context never
  reach stdout or stderr.
- The speech-end algorithm is specified, not hand-waved: end of
  user speech comes from channel-0 energy fall corroborated by the
  capture JSONL's `vad` samples (`speech_ms` returning to zero
  while `listening`), with `heard.duration_s` as a consistency
  bound rather than a timestamp (the `heard` event stamps
  transcription completion, not speech end); turns pair with the
  next reply onset; empty transcripts, replies with no audio,
  barge-ins, filler audio and multi-turn captures each have a
  stated per-turn report (measured, or a named reason no number
  exists).
- The end-to-end proof is an integration case producing a real
  capture (a server with capture enabled, one simulator
  conversation), then the script over the triplet; what it can
  assert depends on the chosen shape and is recorded when the
  milestone unblocks. No integration test currently produces a
  capture at all, so this case is the repository's first either
  way.

## Module layout

- `src/vinga_server/conversations/views.py`: the declarations (name,
  frozen column contract, SQL, question, denominator and
  telemetry-off sentences). Callers stop having to know SQL or
  where views live: docgen renders it, tests iterate it, the
  agreement test compares the database against it. Deletion test:
  inlining it into docgen would make the analyst, agreement and
  number tests read documentation code for data; inlining into the
  migration is forbidden by frozen history.
- `src/vinga_server/conversations/migrations/versions/1005_metrics_views.py`:
  frozen literal DDL.
- The docgen renderer beside the schema one, reading `views.py`,
  and the `views` verb beside `schema` in the conversations CLI.
- `scripts/perceived_latency.py` with its unit tests (M2).

No new package, no new config, no API change.

## Tests

- **Integration, numbers**: seeded by writing exact rows (sessions,
  turns with and without `legs`, tool invocations, events) through
  SQL inserts in the test, not by driving mock conversations, since
  wall-clock measurement makes driven timings unknowable; assert
  exact view rows: percentile interpolation over a known
  distribution, independent input/output token nullability, a
  multi-agent handover turn proving leg attribution with no double
  count, a session crossing UTC midnight under a non-UTC database
  session timezone, telemetry-off rows in denominators only,
  multiple matching events in one turn and unrelated events beside
  them proving no join multiplication, and zero-denominator days
  yielding NULL rates.
- **Integration, agreement**: every declared view exists live with
  a definition matching `views.py` (`pg_get_viewdef` normalized)
  and carries its comment.
- **Integration, analyst**: `vinga_ro` selects from every declared
  view.
- **Integration, wheel/CI**: the chain-head pin moves; the
  expected-tables assertion stays green with views present.
- **Unit**: docgen drift for the new page; the CLI verb (help,
  refusal pins move deliberately); the script's envelope
  arithmetic, per-turn report shape, caveat sentence, refusal
  boundary and exit codes on synthetic fixtures (M2).

## Risks

- **First views in the repo**: the autogenerate boundary above.
- **Percentile semantics under tiny samples**: counts beside
  percentiles, stated on the page.
- **The maintainer decision gates M2**: the milestone is marked
  blocked and the issue comment carries the three shapes; M1 has no
  dependency on the answer.
- **Parallel work**: #66's milestone train touches the CHANGELOG
  and the census manifest on the same days; every rebase re-runs
  the generators on the rebased tree rather than merging generated
  text. The discarded-transcript successor explicitly waits for
  #66's vocabulary rather than racing it.

## Milestones

- [ ] **M1: the views, the reference and the proof.** `views.py`
  with the frozen contracts, migration `1005_metrics_views`, the
  docgen renderer, the `views` CLI verb with its moved pins, the
  generated `docs/reference/metrics-views.md` joining the CI drift
  checks and the docs index, the CI chain-head pin move, and the
  integration tests: numbers (seeded rows), agreement, analyst,
  wheel. Design footprint: deepens the conversations package with
  one declarations module; the migration is frozen history; no new
  seam. Documentation footprint: the new generated page;
  `docs/README.md` reference index; in
  `docs/architecture/observability-surfaces.md` the five-surfaces
  table rows for events (feedstock now served) and the conversation
  store, and the still-open list entry for #439 (leaving #440
  named); the three `docs/concepts.md` anchors move from future to
  landed while budgets, users and cost stay future; CHANGELOG.
- [ ] **M2 (blocked): latency from a capture.** Blocked on the
  maintainer's choice among the three shapes in the
  perceived-latency section; the script's fixed requirements
  (house style, refusal boundary, specified speech-end algorithm,
  the capture-producing integration case) are recorded there and
  land with the milestone once unblocked. Documentation footprint:
  the script's usage block is its page; CHANGELOG.

## Plan review round

External review: codex CLI 0.154.0, model gpt-5.6-sol, read-only
sandbox, 2026-09-10, runtime 8m03s, reviewing commit 0922c8c2.
Verdict as received: **not ready**. Findings condensed but
faithful; resolutions appended per amendment.

1. **P1: The wire-path fallback does not satisfy the settled
   perceived-latency decision.** Channel-1 send onset excludes
   downlink transport and device playback, not "only the playout
   buffer"; labeling it perceived latency is false, and the
   simulator criterion and the acoustic-onset decision cannot both
   be met by the current simulator. Treat as a blocker requiring
   correction of the settled issue or an authorized loopback
   facility.

   *Resolution.* Adopted as a blocker. The plan no longer labels
   the wire interval perceived latency; the section now states the
   contradiction with both evidence sources, offers the three
   honest shapes, blocks M2 on the maintainer's choice, and the
   issue gets the comment when the plan lands. M1 proceeds
   independently.

2. **P1: "Discarded transcripts" cannot be derived from stored
   event rows.** The prompt-echo variants are process-wide with no
   session, so no `record.events` row exists; suppression without
   transcript is a different fact.

   *Resolution.* Adopted. The numerator is deliberately absent
   from the view, with the reason stated in the contract section;
   the #66 plan's `nothing_heard` is named as the stored fact a
   follow-up migration will read once that vocabulary lands, so
   this issue keeps its reading-what-lands decision intact.

3. **P1: The retention analysis was false.** Turns survive by
   conversation `last_active_at` while events die by session
   `started_at`, so a resumed conversation retains turns whose
   events are gone across arbitrary history, and zero cannot be
   told from pruned.

   *Resolution.* Adopted. The retention section is rewritten: raw
   surviving counts, the exact limitation sentence on the
   reference page, no SQL windowing cleverness.

4. **P2: Token totals grouped by `turns.agent` would misattribute
   handover usage.** `agent` is the starting agent; `legs` holds
   the split truth.

   *Resolution.* Adopted. The tokens contract uses legs when
   present, the turn row otherwise, no double counting, with a
   handover fixture named in the tests.

5. **P2: One `measured_turns` cannot describe both token sums.**
   Input and output usage accumulate independently.

   *Resolution.* Adopted: `input_measured_turns` and
   `output_measured_turns`, with input-only, output-only,
   both-null and telemetry-off fixtures.

6. **P2: The daily boundary was undefined.** Timestamps are UTC
   ISO text plus `t_ms` offsets; a bare date cast follows the
   reader's session timezone.

   *Resolution.* Adopted. Day is UTC, derived from
   `started_at + t_ms` with explicit UTC conversion, session
   membership by started date, and a midnight-crossing fixture
   under a non-UTC session timezone.

7. **P2: The event view specified counts, not rates or
   semantics.**

   *Resolution.* Adopted. The contract now freezes columns,
   formulas, exact numerator predicates, per-row counting, the
   separate-aggregation join, and NULL on zero denominators, with
   anti-multiplication fixtures.

8. **P2: Driven mock conversations cannot yield known numbers.**
   Wall-clock measurement makes timings nondeterministic and the
   needed event mix never occurs naturally.

   *Resolution.* Adopted. The number tests seed exact rows by SQL
   insert and assert exact view rows; the driven-conversation
   pattern is not used for numbers.

9. **P2: The view contract was not concrete enough to generate the
   reference safely, and names were left adjustable.**

   *Resolution.* Adopted. Names and full column contracts (type,
   meaning, nullability, formula) are frozen in this plan and live
   in the one declared structure docgen and tests consume.

10. **P2: The documentation command was left undecided and its
    test/census work unnamed.**

    *Resolution.* Adopted. The verb is decided (`conversations
    views`, documentation generation rather than #440's data
    surface, reasons stated), and the moved pins are enumerated:
    the sole-command CLI test, help texts, the workflow drift
    list, the docs index, the spellings manifest.

11. **P2: The script's no-leak verification did not cover its
    hostile input boundary.**

    *Resolution.* Adopted into the blocked M2's fixed
    requirements: one fixed-message refusal boundary per failure
    class with sentinel tests over arguments, paths, malformed
    content, OS errors and exception context.

12. **P2: The capture track has no utterance-end event matching
    the proposed algorithm.** `heard` stamps transcription
    completion, not speech end.

    *Resolution.* Adopted into the blocked M2's fixed
    requirements: the speech-end algorithm is specified from
    channel-0 energy corroborated by the JSONL `vad` samples, with
    `heard.duration_s` as a bound, and the per-turn report is
    defined for every edge case listed in the finding.

13. **P2: M1 left authoritative status documentation stale.**

    *Resolution.* Adopted. M1's documentation footprint now names
    the still-open list entry and all three `docs/concepts.md`
    anchors alongside the five-surfaces table rows.
