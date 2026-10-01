# Memory leaves the system message, and a tool span carries its content: implementation

Companion to
[`2026-10-01-memory-placement-and-tool-content.md`](2026-10-01-memory-placement-and-tool-content.md),
one section per milestone, appended in the same change that ticks the
milestone checklist. It records deviations from the plan, resolutions
of the plan's open questions, and discoveries.

## M2: a tool span carries its content

**Attribution:** anthropic/claude-opus-5-5, thinking high; Claude Code 2.1.286; 2026-10-01.

### What landed

| Decision | Where | Commit |
| --- | --- | --- |
| 9a, the outcome events say which kind of pair | `events/values.py` (`LlmInputExportKind`), `events/catalog.py`, `llm_input_export.py` (`_failed` takes the kind at every site), `docs/reference/events.md` regenerated, `tests/unit/test_event_baseline.py` | `Say which span a content outcome event is about` |
| 7 and 8, telemetry's slot keyed by `(invocation, position)`, taken on every path | `telemetry.py` (`GEN_AI_TOOL_CALL_ARGUMENTS`, `GEN_AI_TOOL_CALL_RESULT`, `stage_tool_content`, `_take_tool_content`, `_tool_span`) | `Hold a tool call's content for the span that ran it` |
| 7, 9 and round 3's admission budget, `stage_tool` | `llm_input_export.py`, `tests/support/llm_input.py`, a baseline driver for the new emit site | `Stage a tool call's pair through the content export` |
| 8, the session-bound staging callable and the call site | `runtime/tool_execution.py` (`StageToolContent`, `_asked`, `_run_one`), `runtime/pipeline.py` | `Hand each tool call's content to its tool span` |
| 10, the Collector mask | `deploy/telemetry/collector.yml`, `tests/unit/test_telemetry_deploy.py`, `tests/integration/test_telemetry_fanout.py` | `Mask tool call content in the Collector` |
| 11, option A in the setting | `config/models.py`, `docs/reference/server-config.md` regenerated, `config.example.yaml` | `Say that remembered facts leave with the export` |
| 9a's prose and 11 on the page | `docs/architecture/observability-surfaces.md` | `Describe tool content on the observability page` |
| The changelog fragment | `changelog.d/533-tool-content-on-the-tool-span.md`, `### Added` and `### Changed` | this section's commit |

### Round 3 amendments

Two binding amendments from the plan's third review round arrived
while this milestone was in flight, before any tool pair was staged, so
neither needed a corrective commit.

1. **Ownership of the handoff.** The plan's decision 8 named a
   `take_tool(invocation, position)` on the export that telemetry's
   `_tool_span` would call. That would have had telemetry call back
   into a module that imports it. The amendment follows the generation
   path's existing direction instead, and that is what was built:
   `Telemetry` owns a second map keyed by `(invocation, position)`
   under the generation map's lock, with `stage_tool_content` (refused
   without a live trace, like `stage_llm_content`) and the fold's
   `_take_tool_content`, which `_tool_span` calls before it looks the
   trace up, so the untraced path discards. `LlmInputExport.stage_tool`
   renders and bounds the pair and stages it into telemetry; a refusal
   is reported as `llm_input_export_failed` with `kind=tool_call` and
   `reason=dropped`, the closed set's one member. `ToolExecution` gets
   no export: `PipelineRuntime` hands it
   `functools.partial(llm_input.stage_tool, self.session_id)`, or
   `None` with the export off, compared `is not None` at the one call
   site. No public discard method was added, since nothing calls one:
   the fold's take on the untraced path is the discard.
2. **An admission budget per round.** One round's admitted tool pairs
   together may not pass the per-request ceiling; a pair that would is
   dropped whole and reported with `kind=tool_call`. It is held as one
   `(invocation, bytes)` entry per session rather than one per round,
   because a session's rounds run one after another and a round's calls
   all finish before the next round is asked, so a pair for a new
   invocation means the previous round is over. The entry is forgotten
   at session close and at shutdown. Tested with five under-ceiling
   pairs against a ceiling of three and a half: the first three attach,
   the last two are dropped and reported, and the next round starts
   from nothing, with the exact outcome sequence asserted.

### Deviations from the plan

None beyond the two amendments above. Choices the plan left open:

- **The arguments' encoding.** `_json(arguments)`, the encoder the
  round's whole `tool_call` part goes through, so on the tool span the
  value is byte-identical to the `arguments` substring of the asking
  round's `gen_ai.output.messages` (a test asserts the substring). A
  malformed call's raw text passes through unencoded.
- **Where the semantic arguments are read.** The reserved claim
  (`turn.reserved(slot).arguments`), which `_classified` built from the
  model's own call before `for_execution` derived the coerced copy.
  `_run_one` only holds the copy, so the claim is the one place the
  model's values are in reach there; the raw text of a malformed call
  comes off the copy, which `for_execution` returns unchanged for one.
- **The new enumeration's name.** `LlmInputExportKind`, beside
  `LlmInputExportFailure`. `_failed` takes it as a required argument
  rather than defaulting to `generation`, so every one of the ten drop
  sites names its kind (seven `GENERATION`, three `TOOL_CALL`).
- **The catalog comment.** The block above the two events still
  described three counts the exported event had not carried since
  #502's review; it is rewritten to describe the two kinds instead.
- **Option A's wording.** Written without saying where in the request
  memory sits ("the memory each round's request carries"), so it is
  true before and after M1 moves it; the description's existing "the
  system prompt with its memory and know-how blocks" is M1's sentence
  to change and is left alone here.

### Inventories

Untruncated `git grep -n` at this section's commit, counted rather than
excerpted.

- `ToolExecution(`: 3 sites. One production (`runtime/pipeline.py`,
  which passes the staging callable), two tests
  (`tests/unit/test_session_tools.py`, `tests/unit/test_tool_execution.py`)
  that take the default `None`, which is the flag off.
- `stage_tool(`: 1 production call (the partial in
  `runtime/pipeline.py`), 1 definition, 1 baseline driver, 8 unit-test
  calls.
- `stage_tool_content`: 1 production call (`llm_input_export.py`), 1
  definition, 1 fake (`tests/support/llm_input.py`), 4 test calls.
- `self._failed(` in `llm_input_export.py`: 10, each naming its kind.

### Tests and mutations

Every new test was watched failing first: the telemetry cases on the
missing import and then each against a mutation below, the export cases
on the missing `stage_tool`, the production-path cases with the
pipeline's staging callable forced to `None` (four of five fail; the
sentinel, correctly, passes), and the two Collector inventories
against the unchanged config.

| Mutation | Expected to fail | Outcome |
| --- | --- | --- |
| The coerced execution copy exported instead of the claim (plan) | `test_a_coerced_call_exports_the_model_s_arguments` | killed, that test alone |
| The pair attached without the setting: `build_llm_input_export` ignores `export_llm_input` (plan) | the no-leak sentinel | killed, that test alone |
| `_tool_span` takes the slot only after the trace check | the no-trace discard test | killed |
| Telemetry's take keyed by invocation alone | the two-positions test | killed |
| No round budget (per-pair ceiling only) | the round-budget test | killed |
| The round budget kept across a session close | the close test | killed |
| The round budget never reset for a new invocation | the round-budget test | killed |
| Every generation drop site reports `tool_call` | the two generation failure tests | killed, both |

No mutation survived. The sentinel's driver reaches its condition: the
mutated builder returns an export, the session stages through it, and
the credential-shaped argument lands on the tool span, which is what
fails it.

The fanout test ran locally: Docker and the pinned
`otel/opentelemetry-collector-contrib:0.160.0` image are on this
machine, and it failed against the old config (the Jaeger side's
canonical content carried an unmasked email in the two new keys) and
passed against the new one.

### Live gate

One real session on 2026-10-01 against the project's Langfuse (EU
cloud) with `export_llm_input` on: OpenAI ASR, `gpt-4.1-mini` and
OpenAI TTS through the real server and a xiaozhi-sdk client, three
spoken turns, the model calling the builtin `remember` and then the
builtin `recall`. Session `683052f5121b46e093bcf5a53e0d26f3`. The
driver was a scratch copy of the metadata half's M3 gate, placed in the
integration directory for the run, removed after it, never committed.
The first attempt ended in an `httpx.ReadTimeout` before any readback
and was not diagnosed further; the rerun passed.

The ledger: seven `llm_input_exported` records, `(rounds, tool_calls)`
of `(1,0)` five times and `(0,1)` twice, and no failure.

Readback through `/api/public/observations/{id}`:

| Observation | Langfuse name, type | Input | Output | Join |
| --- | --- | --- | --- | --- |
| `dcc72cfe6fdccd0d` | `remember`, `TOOL` | `{"text": "The user's favorite herb is basil."}` | `"Remembered [1]: The user's favorite herb is basil."` | invocation `ab38f46d…`, position 0 |
| `1091731e8bef952d` | `recall`, `TOOL` | `{"query": "favorite herb"}` | `"- [1] The user's favorite herb is basil."` | invocation `2b41afe9…`, position 0 |

Both inputs and outputs are exactly the staged `gen_ai.tool.call.arguments`
(parsed) and `gen_ai.tool.call.result`, recorded on the way in. Neither
observation carries a `langfuse.*` attribute, and the two conventions'
keys do not reappear in its metadata attributes: Langfuse consumed them
into input and output natively, with no alias of vinga's.

**Discovery.** Langfuse names a tool observation after its
`gen_ai.tool.name` (`remember`, `recall`), not after the span's name
`tool`; a readback filtering on `name == "tool"` finds nothing, which
is how the gate's first readback came back empty. Its type is `TOOL`.

### Lanes

- Lint: `uv run ruff check .`, all checks passed.
- Unit, `-n auto --dist loadfile`: `1 failed, 7802 passed, 19 skipped in 1551.22s (0:25:51)`. The one failure is
  `tests/unit/test_event_docs.py::test_a_reader_who_stops_reading_mid_chunk_gets_no_traceback`,
  the agentpi-only #584 (16 KiB pages) the brief names as known on this
  machine; it measures a pipe buffer and touches nothing this milestone
  changed.
- Integration, `-n auto --dist loadfile`: `350 passed in 404.08s (0:06:44)`, the fanout test included.
- Docs link check: `checked 285 files, 0 failures`.
- Census, run last after every prose edit: `66 passed in 28.50s`, both manifests current.

### PR review round, PR #587

Automated external review of this PR's diff (origin/main...e76a1be2). Reviewed 2026-10-01 by openai/gpt-5.6-sol, thinking high via codex CLI 0.156.1, read-only sandbox, runtime 5m43s, at commit e76a1be2. Posted verbatim by the review run itself; resolutions follow as replies.

Verdict as received: **mergeable after the listed fixes**. Two findings,
each fixed in a commit of its own.

1. **P1: a rejected `tool_call` emission left content orphaned and
   reported false success.** `stage_tool` staged the pair and emitted
   `llm_input_exported` before the `tool_call` emission meant to
   consume it, and `SessionEvents.emit` can refuse to build that event
   (an exception class whose name is not an identifier, carried as
   `error.type`). The slot then stayed in telemetry until shutdown, and
   the ledger counted a pair that never reached a span. This is the
   exposure the milestone's hand-back had named as accepted, by analogy
   with the generation path; the review was right that the plan's
   definition of `tool_calls` does not allow it.

   *Resolution*: accepted, in `8368dd37`, by making the stager own the
   emission, the smallest shape that settles the handoff where it is
   decided. The session-bound callable also takes the `tool_call`
   emission as a thunk; `stage_tool` stages the pair, makes the
   emission exactly once on every path (a dropped pair keeps its
   event), and then asks telemetry's new
   `settle_tool_content(invocation, position)`, which releases whatever
   is left under the keys and answers whether a fold wrote the pair
   onto a span (`_tool_span` records that when it attaches content).
   Only then is the pair counted in `tool_calls` and charged to the
   round's admission budget, so a refused emission has nothing to roll
   back; otherwise it is `llm_input_export_failed` with
   `kind=tool_call`. Considered and not chosen: a separate confirm or
   discard call made by `_run_one` after the emit, which would put the
   same two steps in two modules and let a future call site forget the
   second. Regression
   (`test_a_refused_tool_call_event_reports_failure_and_keeps_nothing`):
   a source failing with an unnameable exception makes the `tool_call`
   construction refuse; no `tool_call` record, one `tool_call`/`dropped`
   failure, no success record, and a later span under the same join
   keys carries no content. A second test holds the emission to exactly
   once whether the pair attaches, is over the ceiling, or is refused.
   Watched failing on the old handoff. Mutations, all killed: counting
   without settling (the regression), settling without releasing the
   slot (the regression's later-span assertion), and skipping the
   emission when the pair is dropped (the emit-once test, two of its
   three cases).

   Left as it was, and named: a generation's pair is still counted in
   `rounds` once staged for its span, immediately before `llm_round`,
   so a refused `llm_round` construction would leave that slot until
   shutdown and the count would be the stage, not the attachment. The
   finding is scoped to the tool handoff, and the page says the two
   conditions differ.

2. **P2: the observability page's Status paragraph still said content
   travels only on the generation span**, pairing only before
   `llm_round` or `provider_failed`.

   *Resolution*: accepted, in `89fcecd9`. The paragraph now covers both
   carriers: a generation's pair counted in `rounds` once staged before
   its event, a tool call's pair counted in `tool_calls` only once its
   event's fold wrote it onto the span and discarded at once otherwise,
   and every pre-enqueue omission that becomes
   `llm_input_export_failed` with what its `kind` says. The
   tool-content paragraph above it gains the settle step.

Verification for the round: `uv run ruff check .`, all checks passed;
the affected unit files (`test_llm_input_export`,
`test_tool_span_content`, `test_telemetry_llm_input`,
`test_session_llm_input`, `test_tool_execution`, `test_session_tools`,
`test_telemetry_spans`, `test_event_baseline`, `test_session_recap`),
`-n auto --dist loadfile`: `210 passed in 96.45s (0:01:36)`; the
integration files touching tool execution or telemetry export
(`test_llm_input_export`, `test_telemetry_export`,
`test_telemetry_fanout`, `test_telemetry_hardening`, `test_tools`,
`test_mcp_reload`, `test_transcript_export`), `-n auto --dist
loadfile`: `32 passed in 76.17s (0:01:16)`; docs link check, `checked
285 files, 0 failures`; census, run last after this record:
`66 passed in 29.33s`. The live gate above ran before finding 1's fix
and was not repeated: the fix changes when a pair is counted and what
happens to one that is not consumed, not what an attached pair
carries, and the attached path is the one the production-path tests
still exercise.
