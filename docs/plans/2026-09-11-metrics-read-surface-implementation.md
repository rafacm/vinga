# A first-party read over the phase-1 aggregates: implementation

Companion to [`2026-09-11-metrics-read-surface.md`](2026-09-11-metrics-read-surface.md).
One section per milestone, appended in the same change that ticks the
milestone checklist: deviations from the plan, resolutions of its open
questions, and what was discovered on the way.

## M1: the aggregates on the API

PR #463.

### What landed

`GET /metrics` and `GET /metrics/{view}` on the gated `/api`, registered
from `conversations/api.py` by `config/api.py`'s `_application()` like
the session and thread reads beside them, so a route that is served is a
route the committed document carries.

`GET /metrics` is the registry rather than the store. It lists the four
views in declaration order, each with its alias, its schema-qualified
relation, its question, its denominator sentence, its own telemetry-off
sentence and its full column matrix, and it carries the statements that
hold for all of them. It takes no reader at all and opens no connection,
so it answers the same thing on a deployment that never recorded.

`GET /metrics/{view}` answers one view over one window. The request
contract as implemented:

| parameter | accepts | default | bound |
| --- | --- | --- | --- |
| `since` | a UTC day, `YYYY-MM-DD`, the window begins on it | 30 days before `until` | with `until`, at most 366 days |
| `until` | a UTC day, `YYYY-MM-DD`, the window ends on it | the server's current UTC day | not before `since`; with no `since`, not inside the calendar's first 30 days |
| `group` | a word from a closed set, `all` today | `all` | closed set |

Both ends are included, so a window of one day spans one day and the
default window is 31 days: the day named and the 30 before it. The cap
is 366, one leap year, and a wider window is **refused rather than
narrowed**: an answer trimmed to fit would be less than what was asked
for while nothing in it said so. The floor is stated beside it: an
`until` with fewer than thirty days of calendar behind it is refused
with a sentence saying to name a `since`, because the window that would
be implied begins before `0001-01-01`. The two days the answer used are
repeated in the body, so a caller that sent neither reads the defaults
off what came back instead of recomputing the server's own day.

Rows come back ordered by `day` descending and then by the view's other
key columns ascending with nulls last. An empty window is an ordinary
empty list with its window stated, and so is a deployment that never
recorded: no refusal, no 404.

Every request-controlled value is resolved before the store is reached.
The route takes the opener rather than an open connection, the way the
erasures already take their transaction's factory, and enters it around
the one statement it is for; a dependency that yields a connection is
resolved by the framework before the handler runs, which would mean
opening the store before looking at anything the caller sent.

The refusals are the module's existing rule, a fixed sentence that
quotes nothing back. An unknown view is a 404 saying that `GET /metrics`
lists the ones that are served; a day that is not an extended-form UTC
calendar day, a window whose ends are out of order or too far apart, and
a grouping nothing serves are 422s naming the argument whose rule was
broken. `METRICS_PROBLEMS_INSTEAD` gives this namespace its own 404, 422
and 500 sentences, because nothing here is addressed by an id and
nothing here writes.

### The five findings the review round turned into this milestone

**1. The closed mapping is derived from the registry.** `View.alias`
strips the `metrics_` prefix and the `_daily` suffix every view's name
carries and kebab-cases what is left, and `views.ALIASES` is
`{view.alias: view for view in VIEWS}`. `conversations/api.py:_view()`
is a `dict.get` on it and raises `UnknownEntityError` on a miss. Nothing
else in the request path touches the caller's bytes: the query is built
by `_relation()` from the declaration's own name and column names, so a
value that resolves to no declaration reaches no query builder, no
connection and no log, which is counted rather than asserted: with
`read_engine` replaced by a spy that fails, a broken view, grouping,
day or day-pair each performs zero opens and still answers its own 404
or 422, and a valid request opens exactly once and takes the failure,
which is what proves the spy is in the path. Deriving the mapping
rather than writing it beside the registry is what stops the servable
set drifting from the declared set, and a test asserts the derivation
and the four aliases.

**2. Transport models are in `config/responses.py`.** `MetricCaveats`,
`MetricColumn`, `MetricView`, `MetricViews` and `MetricRows`, beside the
conversation shapes and for the same reason: the CLI in M2 validates an
answer against the shape the API said it would send without importing
FastAPI, SQLAlchemy or the store. `GROUPINGS` lives there too, so the
set a request is held to and the set the document publishes are one
tuple rather than two that must agree.

**3. Conversations-off keeps serving.** Nothing was added to
`ApiRuntime` and no switch state is inferred from stored rows. The reads
take the existing per-request reader, which opens its own connection
through `db.read_engine`, so they work with recording off where there is
no `ConversationStore` to borrow an engine from. Two cases pin it: a
deployment that never recorded answers empty lists on all four views,
and a server composed with recording off (asserting
`app.state.composition.conversations is None`) still serves the rows
planted before the switch moved.

**4. Telemetry-off is asserted per view.** One case writes a session
through the real `ConversationStore` with `telemetry=False` and asserts
all four views in one breath: the latency view produces no row at all,
the event-rate view keeps both denominators and loses both numerators
(so its rate is 0.0, which is a measurement, because the null rule is
about a zero denominator and not a zero numerator), the token view
counts the turn with both sums null, and the baseline view counts the
session with `telemetry_sessions` at zero. Each view's own
`telemetry_off` sentence is what the surface reports, in the listing
body, in the answer body and in the document.

**5. The common limitations are declared metadata.** `views.COMMON` is a
tuple of `Caveats(heading, notes)`, carrying the four reading rules and
the three limits verbatim. `docgen.views_reference()` renders them
instead of spelling them, which is why the committed reference did not
move a byte for that half; `docgen.views_description()` renders them
again, with each view's question and telemetry-off sentence, as the 200
description of `GET /metrics/{view}`; and both routes serve them in
their bodies, which is the third consumer M2's CLI reads them through.
The retention-floor limit, which the round found unreachable from
anywhere but the renderer, is now on the API contract and in every
answer.

### Deviations from the plan

**`group` accepts `all` only, not `all` or `device`.** The plan's
request-contract table lists both, and its M3 delivers the per-device
views, the `group=device` behaviour and the `device` parameter. There
are no per-device relations until that migration lands, so a second
token could be documented but never answered, and a published
vocabulary that always refuses is worse than one that grows. So M1
publishes the parameter with the closed set it can serve, generated from
`GROUPINGS`, and M3 appends to that tuple: the refusal sentence, the
parameter description and the document's own enum are all built from it
and move together. The `device` parameter is M3's for the same reason.

**The ordering is generalized from "day descending, then device
ascending nulls last".** That ordering is not total on the four shipped
views, which have dimensions of their own: the latency view is one row
per day, agent and stage, and the token view one row per day and agent.
So `Column` gained a declared `key` flag, the view's `GROUP BY` said as
a declaration, and the read orders on `day` descending then every other
key column ascending with nulls last. On the shipped views that is
total; once M3's `device` is a key column it is exactly the ordering the
plan names. The reference states each view's keys, so the declaration is
documented rather than merely used.

**A third renderer in `docgen`.** The plan's module layout names no new
module and none was added, but `docgen` gained `views_description()`
beside `reference()` and `views_reference()`. It is the same
responsibility, writing a declaration out for a person, and the
alternative was a second copy of the caveats inside the transport code.
The route's own prose stays its docstring, which is the repository's
rule; the generated block is the operation's `response_description`,
which is where "what this answer means" belongs.

**Two test helpers moved to `tests/support`.** `plant_session`,
`plant_turn` and `plant_event` were local to
`tests/integration/test_conversations_views.py`. A second suite plants
now, so they moved to `tests/support/stores.py` under the repository's
rule that no test module imports another. Nothing about them changed.

### Discoveries

**`_before` and the metrics days are one rule.** The session purge's
`before` selector already parsed an extended-form UTC day, refusing the
`20260815` and `2026-W33-1` spellings `fromisoformat` would otherwise
accept. `since` and `until` need exactly that, so `_utc_day()` is one
home for it and `_before` now reads it rather than repeating it.

**A one-token `Literal` is `const` in JSON Schema, not `enum`.**
Pydantic renders `Literal["all"]` as `{"const": "all"}` and only
switches to `enum` with a second member. The document pin reads either
spelling, so it keeps holding when M3 adds the second grouping.

**The listing needs no 500.** It declares 401 and nothing else, because
it opens no store and cannot fail for a reason that is not the
caller's.

### Verification

- `uv run ruff check .` and `uv run mypy` clean; `uv run pytest
  tests/unit -q -n 4 --dist loadfile` 6237 passed, 19 skipped; `uv run
  pytest tests/integration -q` 282 passed. The lane runs `-n 4` rather
  than `-n auto` on this machine, which exceeds the compose Postgres's
  connection limit.
- `uv run vinga-server conversations views` and `uv run vinga-server
  config openapi` diffed against the committed references, which is what
  CI's two drift checks run.
- The document pins in `tests/unit/test_api_openapi.py`: the two routes,
  every field of the five shapes required, `MetricColumn`'s fields held
  equal to the registry's `Column`, the four parameter descriptions, the
  grouping vocabulary, and the semantic assertion that the
  zero-denominator rule, the retention-floor warning, the
  missing-measurement ambiguity and each view's own question and
  telemetry-off sentence are in the contract a client reads.

### PR review round

External review of PR #463: one P1, one P2, mergeable after fixes. Both
adopted.

- **P1: invalid requests opened the database before being refused, and
  the pin did not prove otherwise.** The route took `ReaderDep`, which
  FastAPI resolves before the handler runs, so an unknown view answered
  500 rather than 404 whenever the store was unwell, and the claim in
  this document that a refused request reached no connection was false.
  The case that was supposed to prove it asserted something weaker than
  its own docstring: it re-read the store afterwards, which only shows
  that nothing was written. Fixed by taking the opener rather than an
  open connection, the shape the erasures already had, validating every
  request-controlled value first and entering the connection around
  `_aggregated` alone. The new case counts opens at `read_engine` with
  a spy that fails, so a refusal that opened anything would answer 500
  and be caught; it was written first and run against the unfixed code,
  where it failed on the unknown view answering 500.

  The defect and the weak test are the same mistake in two places: the
  assertion in this document came first, and the case was written to
  agree with it rather than to try to break it. What a claim about a
  property is worth is whatever would have caught it being false.

- **P2: a valid but early `until` crashed the default-window
  calculation.** `0001-01-01` is a well-formed UTC day and passes the
  day rule, so it is not a malformed value at all; subtracting the
  default thirty days from it raises `OverflowError`, which answered
  500 about a request nothing was wrong with. The malformed-day cases
  could not have caught it, because the value is a boundary rather than
  a mistake. Fixed by checking the room behind `until` rather than
  catching the arithmetic, with a sentence that names the calendar's own
  first day, quotes nothing the caller sent, and says to name a `since`
  instead. The bound is stated with the 366-day cap on the parameter's
  description, in the changelog and in the table above, and the cases
  cover the boundary with an explicit `since` (an ordinary window), with
  none (refused), and at the calendar's far end, which needs no room
  ahead of it because the window is always put behind `until`.

### Not done here

M2's CLI and M3's device dimension, as planned. The observability map
still records #440 as open, which M3 closes.

## M2: the CLI in front of it

PR #469.

### What landed

`vinga metric list` and `vinga metric show <view>` in
`config/cli.py`, through the `Act`, transport, validation and
registration machinery that module already has. Two rows in
`COMMANDS`, one group in `GROUPS`, two acts, one declaration
function, four new fields on `Invocation` and two renderers. No new
module, which is what the plan's module layout says, and no seam.

The grammar as registered, and what holds it there:

| the line | why it is that shape |
| --- | --- |
| `vinga metric list` | the noun is this repository's own word for the surface, reserved for it by #437's rename; `list` is a core-set verb |
| `vinga metric show <view>` | singular because `show` addresses one entry; the view is the whole address, in the route's own parameter name |
| `--since DAY`, `--until DAY` | neither addresses a view: they bound the answer, the way `--limit` bounds a session listing |
| `--group HOW` | the same, and its vocabulary is the API's closed set rather than a copy here |

`metric latency` was excluded though it reads better: a noun in the
verb slot reads as a possessive and hides what the command does, and
`agent preview` is this repository's precedent for not granting that
exception to the first command that asks for it. The plural spelling
was excluded by the plan's review round, which is where the singular
rule was applied to this noun.

Neither verb has a local path. `config/cli.py` states the rule ("a
command that touches the record is a request like every other, and
there is no second way in") and the acts carry it: two `GET`s and
nothing else. The plan's first draft promised a break-glass and the
review round took it out.

**What the two verbs print.** `metric list` is a block per view: the
alias, the question, the denominator sentence, the view's own
telemetry-off sentence, its columns with the unit of each where it has
one, and the relation to select from. `metric show` is the view's alias
and question, the window it was answered over stated once, a borderless
table, and the caveats under it. A null cell is the placeholder `-` that
every other listing here prints, never a zero. An empty window prints
one sentence and leaves through zero, and so does a deployment that
never recorded: the same answer for the reason `conversations/api.py`
gives about empty shapes.

The table has prose above it and below it, which the pending and session
listings do not, and that is deliberate rather than overlooked. The
guide's borderless table is defended by one entry per line, which holds:
a row is a line, and `grep` still picks the day out of it. What does not
hold is `wc -l` as a row count, and it would not have held for a header
block alone; the whole of what a number here cannot say is worth more
than a count somebody can take with `grep -c`. Everything printed is
about the artifact rather than about the run, which is why it is on
stdout: the export's own header and footer are the precedent, and the
rule is that a document explaining itself is still the document.

**The declared limitations reach the CLI through the answer.** M1 made
`views.COMMON` the one home and gave it two consumers, the committed
reference and the OpenAPI descriptions; this is the third, and it reads
them the way a client must, out of the body both routes serve rather
than by importing the registry. `config/cli.py` could import
`conversations.views` today (it already imports `config.docgen` for its
widths), and taking that shortcut would have made the CLI a second
reader of the server's own module rather than a client of the API,
which `test_cli_import_weight.py` exists to prevent. Every view's own
telemetry-off sentence travels the same way, per view, so the surface
does not flatten a behaviour that is not uniform.

### Deviations from the plan

**`--group` is registered here rather than in M3.** The plan's M3 bullet
says "`group=device` on the API and its CLI flag", which reads as the
flag arriving with the token. It arrives now, for a reason the M1
deviation makes: the grouping vocabulary is one tuple, `GROUPINGS`, and
M1 built the refusal sentence, the parameter description and the
document's enum from it so they move together. With the flag already
here, M3 appends a token to that tuple and changes nothing else on
either surface; with the flag deferred, M3 would have to add both and
the CLI could not exercise the API's grouping refusal at all until it
did. The cost is a flag with one legal value for one milestone, which is
a published parameter of the API today.

**The caveats are printed on both verbs rather than on one.** The plan
says the CLI's "output or help" is the third consumer and does not say
where. The API serves them in both bodies, so both renderings print
them: a reader who ran `metric list` to find out what the numbers are is
reading exactly the material `list` is for, and a reader about to quote
one off `show` is at the moment they are most likely to be missing it.

**Markdown markers are removed for a terminal.** The statements are
declared as Markdown because two of the three surfaces that render them
are: the committed reference and the API's contract. A terminal is the
third and is not one, so `**` and backticks come out and nothing else
does. The words, their order and their punctuation are the registry's,
and the removal happens after `printable` has already turned every
character a terminal would obey into a question mark, so it cannot hide
anything. A paragraph is then wrapped at `docgen.PROSE_WIDTH`, the width
every other piece of generated prose here is written to, which keeps the
answer the same bytes through a pipe and onto a screen.

### Discoveries

**A path carrying an encoded newline never reaches the route.** A view
spelled `sessions\r\nlevel=CRITICAL` is percent-encoded by the client
and then fails to match the sub-application's mount, so what answers is
Starlette's own `application/json` 404 rather than the API's
`application/problem+json` one. The client suppresses it, exactly as
`_refusal` is written to: three things have to agree before a body's
words are relayed, and a media type that is not
`application/problem+json` is the first of them. The value still leaves
no trace, which is the property; which of two fixed sentences a caller
meets depends on how far the value got, so the no-leak case asserts the
property over every hostile value and a separate case asserts the API's
own sentence on an ordinary unknown word.

**The test client's vendored `httpx2` logger is not the CLI's to
quiet.** `config/cli.py` quiets `httpx` and `httpcore` around every
request, and `tests/support/config_cli.logged` deliberately reads every
record, so a no-leak sweep driven through `TestClient` finds the request
line its own vendored client wrote. This suite filters to
`vinga_server` channels and says why, which is the shape
`test_config_cli_sessions.py` already uses for the same reason.

### Both installed lanes had to gain a case

`tests/integration/test_cli_live.py` and
`tests/integration/test_cli_wheel.py` derive their coverage from
`cli.COMMANDS` rather than from a list beside it, so the two new rows
turned three cases red before a line was written for them: the live
lane's completeness claim, the wheel lane's, and the closure that says
every family of the grammar has a refusal whose sentence has been seen
to cross a connection. All three are what those tests exist to catch.

The wheel lane's case is the one worth reading. The declared statements
live on a module of the serve tier, so a client that imported the
registry to print them would be a client the bare wheel cannot run, and
it would fail there and in no other lane.

### Verification

- `uv run ruff check .` and `uv run mypy` clean; `uv run pytest
  tests/unit -q -n 4 --dist loadfile` and `uv run pytest
  tests/integration -q` green.
- One integration case,
  `test_smoke_seeds.py::test_a_seeding_script_reports_a_server_that_will_not_start`,
  failed once under a lane sharing the machine with a parallel unit run
  and passed on its own immediately afterwards. It touches nothing this
  milestone changed.
- The CLI reference regenerated through `vinga-server config
  cli-reference` and diffed the way CI diffs it, and the spelling census
  regenerated rather than edited.
- Each new pin was run against a deliberately broken renderer before it
  was trusted, and the ten breakages and what each one fails are
  recorded in the commit that adds the cases.

### PR review round

External review of PR #469: three P1s, two P2s, not mergeable. All
adopted, one in part.

- **P1: `metric show` dropped the view's telemetry-off sentence.** The
  claim above that both verbs print the sentence was true of the code
  for `list` alone, and the test held only `list`, so removing the
  sentence from `show` passed. The claim and its weak pin are the M1
  round's lesson repeating: this document said it first and the case
  was written to agree. The renderer now prints the sentence under the
  question on `show`, and a per-view case drives `show` for every
  declared view; it was written first and failed on all four.
- **P1: a response-controlled column heading bypassed the cell
  bounding.** Headings went to the column layout with only an
  uppercase on them, so a structurally valid answer with a CSI
  sequence, a bell or a newline in a column name reached stdout
  verbatim, which the cli-guide's terminal rule allows no exception
  for. Fixed by passing the uppercased heading through the same cell
  bounding, and pinned with a synthetic response whose column name
  carries a clear-screen sequence, a bell, a carriage return and a
  newline; the case failed on the escape byte before the fix.
- **P1: a malformed row read as a meaningful null.** `MetricRows.rows`
  was bare dicts under a description claiming each row carries exactly
  the declared keys, and the renderer prints the placeholder for an
  absent value, so a body missing the non-null `turns` validated and
  printed the null placeholder: a legitimate null nobody sent. A model
  validator now derives the rule from the answer's own `view`: key set
  equal to the declared columns, and no null in a column declared
  non-nullable. A breach meets the fixed unreadable-answer sentence
  with nothing of the body in it. Three cases (missing, undeclared,
  null in non-nullable) were written first with a planted sentinel
  value and all exited 0 before the validator.
- **P2: the `--group` help called the default "ungrouped".** It is
  not: `group=all` still groups by the view's own dimensions. The help
  now says so, and the generated reference and the spelling census
  moved with it.
- **P2: the grouping refusal was pinned with the plain sentinel
  only.** The plan requires control characters through `group` as well
  as through `{view}`, and only the view had them. The refusal case is
  now parameterized with a CRLF log-forging value, a NUL and a CSI
  sequence, hunted through both streams and both shipped log formats.
  All four pass on the existing behaviour, so this closed a coverage
  hole rather than a defect. The round also asked for a live-client
  case pinning URL logging; not adopted, because that boundary is held
  suite-wide by `test_config_cli_transport.py`, which writes records
  under `httpx` and `httpcore` while a request is in flight and
  asserts they are dropped, and the quieting lives in the shared
  transport seam per request rather than per command.
- **P2: the ticked milestone said `PR TBD`.** Both the plan's
  checklist entry and this section's heading line now record PR #469,
  the way M1 records PR #463.

### Not done here

M3's device dimension, as planned: the four sibling views, `group=device`
as a token the API answers, and the `device` and `name` columns. The
observability map still records #440 as open, which M3 closes.

## M3: the device dimension

PR TBD.

### What landed

Four more views in the `record` schema, one per question, added by
`1008_metrics_views_by_device` (numbered 1007 when this milestone was
cut, renumbered in the final rebase behind #472's
`1007_sessions_name_the_device`):
`metrics_stage_latency_by_device_daily`, `metrics_tokens_by_device_daily`,
`metrics_event_rates_by_device_daily` and
`metrics_sessions_by_device_daily`. Each is the view it mirrors with the
device a session ran on and a label beside it added to what makes a row
one row, and the four that were already there are untouched.

`GET /metrics/{view}?group=device` and `vinga metric show <view> --group
device` answer from them. The word in the path does not change, because
the question is one question and the grouping is what says which
relation answers it; `View.alias` therefore strips the `_by_device`
infix the way it already strips the prefix and the suffix, `ALIASES`
stays the four words a request may spell, and `views.GROUPED` is the
pair of mappings a resolved word and a resolved grouping index into.

A row carries `device`, the MAC, which is the stable key, and `name`,
which is the literal null `NULL::text` in every row of this release.
Nothing in this milestone depends on #449's M5: `record.sessions.device`
already held the MAC, and the label is declared and selected now so that
the columns a caller reads do not move on the day a copy of it lands on
the `record` side. It cannot be a join: `deploy/postgres-init.sql`
grants the analyst role on `record` and revokes it on `domain`, so no
view here can reach `domain.devices` at all.

`device` on the API and `--device` on the command narrow a per-device
answer to one board, by MAC in any spelling, normalized by
`normalize_mac` the way `/sessions` normalizes the same argument. Sent
without the grouping that gives it meaning it is refused rather than
ignored and rather than taken as a grouping of its own: the ungrouped
rows are not one device's, so a filter on them would answer a different
question in a shape the caller could not tell apart, and inferring the
grouping from the filter would let one argument change what another
means.

### The four things the plan's review round settled for this milestone

**1. Additive siblings, and a test that can tell.** The four shipped
views are not redefined, because what selects from them is somebody's
saved query, dashboard or downstream object and a redefinition moves
every one of them without asking. `tests/integration/
test_metrics_views_upgrade.py` stands a database at `1006_metrics_views`
and migrates it forward.

The first draft of that test compared `pg_get_viewdef` before and after,
which cannot make the claim: a view dropped and recreated from the same
SQL has the same definition. So it compares the **oids**, which is what
every dependent object in the database points at, and it plants an
analyst's own view on `metrics_sessions_daily` at the baseline and
asserts it still answers afterwards, which is what `DROP VIEW ...
CASCADE` would have taken silently. Both were run against a variant of
`1007` that rebuilds the four from identical SQL: the oids differ and
the saved view is gone, while the definition comparison alone stays
green. The version stamp is asserted at both ends, so a fixture that had
quietly migrated to head could not make any of it trivially true.

**2. Null-safe joins, and the shape they forced.** A device key is null
for a session rejected before a device was understood, and two SQL nulls
are not equal, so the two views that combine independently aggregated
streams join on `IS NOT DISTINCT FROM` on both the day and the device.

They do not chain full outer joins the way their ungrouped siblings do,
and that is not a preference: **Postgres refuses to execute a full join
whose condition is not merge- or hash-joinable**, which
`IS NOT DISTINCT FROM` is not ("FULL JOIN is only supported with
merge-joinable or hash-joinable join conditions"). The union those joins
existed to produce is therefore taken directly, as a `spine` CTE of
every (day, device) pair any stream has, with each stream left joined
onto it. `UNION` already treats two nulls as one value, so the spine has
exactly one row per group before anything is joined to it.

That changes what the null-device case has to assert, and the plan named
the trap in its original form. With a spine, an equality join does
**not** produce three rows: it produces exactly one, filled with zeroes
where the other streams' numbers should have been and with null rates.
A case asserting only that one row came back, or that no device was
invented, would pass on precisely that. So
`test_a_session_with_no_device_is_one_group_and_not_one_row_per_stream`
asserts the numbers: one session, one turn, one counted failure, all on
a device nobody knows, and the row says one, one, one and a rate of one
failure per turn. Run with `=` in place of
`IS NOT DISTINCT FROM` in both the declaration and the migration, that
case and the one that puts a named board beside the unknown one both
fail, and the rest of the file stays green.

**3. Downgrade and the `vinga_ro` grants.** `vinga_ro` needs no grant,
for the reason 1006 needed none: `deploy/postgres-init.sql` sets
`ALTER DEFAULT PRIVILEGES ... GRANT SELECT ON TABLES` for the server
role, Postgres counts a view as a relation of that class, and this
migration runs as the server role. Nothing has to be rerun on a
deployment. It is asserted rather than assumed: the analyst half of
`test_provisioning.py` now iterates `views.DEFINED`, every relation
rather than the four questions, so a sibling is covered by being
declared. The downgrade drops the four it created and leaves the four it
found, which is the inverse of an additive change, and that is asserted
beside the upgrade.

**4. The documentation that recorded #440 as open.** Both pages M1 and
M2 named were checked rather than trusted.
`docs/architecture/observability-surfaces.md` listed the read surface
under "still open, each with its owner", and its conversation-store row
described #439's four views with no reader in front of them: the first
is gone and the second now says where the surface is and that each view
has a per-device sibling. `docs/concepts.md` had three mentions, and
they were three different claims: the cost paragraph said the read
surface "is #440's", which is now "implemented today" with the command
that answers it; the conversation section said "its read surface is
#440's", now landed; and the users-and-budgets paragraph said the
aggregation "is served by #440", which was already true and gains what
the rows are keyed by.

### Deviations from the plan

**The `device` filter is here, though M3's own bullet does not mention
it.** The plan's request-contract table has four parameters and M1's
implementation note says the fourth "is M3's for the same reason" as the
second grouping token: there were no per-device relations to filter.
There are now, and M3 is the last milestone of #440, so the parameter
lands here or the published contract stays a milestone short. It is the
one request-controlled value on this surface that travels, as a bound
parameter on a column of the relation the view and the grouping already
chose, and the no-leak sweep covers it on both surfaces.

**The two combining views do not use full outer joins.** The plan's M3
bullet says "two of these views combine independent streams with full
outer joins" and prescribes `IS NOT DISTINCT FROM`, "coalescing the day
and the device keys". Postgres will not run the first two together, as
above. The rule the round was protecting is kept, on left joins onto an
explicit union spine, and the semantics are the union of the streams'
keys either way. The coalescing goes with the full joins and is not
missing: it was there to recover the group's day and device from
whichever stream had matched, and the spine carries both already.

**`COMMON`'s first heading is no longer "What is true of all four".** It
is "What is true of every one of them", because the page it heads now
renders eight relations. The statements themselves did not move, and the
heading travels from the same one home to the reference, the API
contract and the CLI.

**The listing is still the four questions.** `GET /metrics` and `metric
list` describe the views a request may name, not every relation the
schema holds, so a per-device sibling is not a fifth entry there. What
the grouping does, and that the answer carries the sibling's own
columns, is on the `group` parameter's description, which is where a
client reads what an argument does. The committed reference is the
other way round and documents all eight, because its reader is an
analyst selecting from the schema.

### Discoveries

**Postgres will not full-join on `IS NOT DISTINCT FROM`.** Recorded
above because it is the milestone's one real surprise, it is not in the
error's first line (`FeatureNotSupported`), and the next person writing
a view of this shape meets it the same way: only when a row is selected,
never when the view is created.

**A definition check cannot see a rebuild.** Recorded above, and worth
generalizing: an agreement test that compares a declaration with what
the database says is green whether the relation was left alone or
recreated from the same text, so "the views survive" needs the identity
and a dependent, not the definition.

**Two structures that must agree, kept apart on purpose.** The grouping
vocabulary lives in `config/responses.py` and the relations that answer
it in `conversations/views.py`, and the two spell the same two words.
Deriving one from the other would put a module of the serve tier on the
CLI's import path, which `test_cli_import_weight.py` exists to prevent
and which the wheel lane would fail on. So they are held together by a
test instead, in both directions and with the same questions under each
grouping, which is the remaining way to keep one fact in two places
honest.

### Verification

- `uv run ruff check .` and `uv run mypy` clean; `uv run pytest
  tests/unit -q -n 4 --dist loadfile` 6740 passed, 19 skipped; `uv run
  pytest tests/integration -q` 303 passed. The lane runs `-n 4` rather
  than `-n auto` on this machine, which exceeds the compose Postgres's
  connection limit.
- All three generated references regenerated through their own
  generators and diffed the way CI diffs them: `vinga-server
  conversations views`, `vinga-server config openapi` and `vinga-server
  config cli-reference`. The spelling census was regenerated rather than
  edited.
- The conversations chain pin in `.github/workflows/vinga-server.yml`
  moved to `1008_metrics_views_by_device`, and so did `HEAD` in
  `tests/unit/test_conversations_schema.py`. The CI check is the only
  place the first would have failed, which is why it is worth saying
  twice.
- Every new pin was run against a deliberately broken implementation
  before it was trusted, and each commit body says which breakage and
  what it fails.

### PR review round

External review of PR #471: two P2 and one P3, mergeable after fixes.
All three adopted.

- **P2: an explicitly empty `--device` was silently treated as no
  filter.** The option site defaulted the value with `device or ""`
  and the window builder dropped every falsy entry, so `--device ''`
  answered with every board instead of meeting a refusal: the
  narrowest question the flag can ask, widened by a mistake in the
  spelling of it. Fixed by keeping absent and empty apart, with
  `Invocation.mac` becoming `str | None` and the empty value
  travelling to the API, whose fixed MAC sentence refuses it the way
  it refuses any other non-MAC. The new case plants two boards, asks
  with the empty filter and asserts nothing comes back; it was written
  first and failed on the unfixed code with exit 0 and both boards'
  rows.

- **P2: the CLI no-leak sweep did not cover hostile device values.**
  The plan requires hostile and control-character values through the
  view, the group and the device on both transports, and this
  document's deviations note claimed the device was covered on both
  surfaces; on the CLI it was covered by one credential-shaped
  sentinel, so the claim was ahead of the proof. The view matrix
  gained a sibling through `--group device --device VALUE`: the
  sentinel, a bound-parameter injection pair, a log-forging CR/LF and
  a terminal-steering escape sequence, hunted through stdout, stderr
  and every captured record in both shipped log formats. The pin was
  proven to bite by quoting the value into the API's MAC refusal,
  where all five cases fail.

- **P3: the 1007 migration named the wrong upgrade test.** The
  survival assertion it credits to `test_conversations_views.py`
  lives in `test_metrics_views_upgrade.py`; the filename is
  corrected, and a reader following the pointer now finds the proof
  it promises.

### Not done here

Nothing of #440. The label is null until a copy of a device's name
reaches the `record` schema, which is #449's M5 and not this issue's:
the column, the API field and the rendering are all in place for the day
it lands, and nothing here waits on it.
