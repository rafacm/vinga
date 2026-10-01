# The metadata half of a turn's telemetry reaches every backend: implementation

Companion to
[`2026-10-01-telemetry-metadata-half.md`](2026-10-01-telemetry-metadata-half.md),
one section per milestone, appended in the same change that ticks the
milestone checklist. It records deviations from the plan, resolutions
of the plan's open questions, and discoveries.

## M2: the memory half, per round

**Attribution:** anthropic/claude-opus-5-5, thinking high; Claude Code 2.1.286; 2026-10-01.

### What landed

| Decision | Where | Commit |
| --- | --- | --- |
| 5, `PromptMemory` carries the ids it rendered | `memory/store.py` (`_block`, `_core`, `read_for_prompt`) | `Carry the rendered fact ids on PromptMemory` |
| 7 and 8, `FactIds`, `MemorySources`, `ScopeProvenance` and the `MEMORY_SOURCES` kind | `events/values.py`, `events_docgen.py`, `telemetry.py` (`SHAPES`), `docs/reference/events.md` regenerated | `Add the fact-id and scope-size value types` |
| 8, the `SEQUENCE` fold keeps a homogeneous int list | `telemetry.py` (`_as_attribute`) | `Let the sequence fold keep an integer list` |
| 7, `RoundPrompt` | `runtime/prompt.py` | `Account for one round's prompt in RoundPrompt` |
| 7, 7a and 9, the four fields on `LlmRound` and `ProviderFailed`, threaded by both failure routes | `events/catalog.py`, `events/assembly.py`, `runtime/provider_watch.py`, `runtime/pipeline.py`, `docs/reference/events.md` regenerated | `Carry a reply round's prompt on its events` |
| 8, the `llm` span attributes | `telemetry.py` (`ROUND_PROMPT_ATTRIBUTES`, `_round_prompt_attributes`) | `Put a round's prompt accounting on its llm span` |
| The provider watch's exact payload pins | `tests/unit/test_provider_watch_pins.py` | `Pin the round accounting in the watch's pins` |
| The documentation footprint and the changelog fragment | `docs/architecture/observability-surfaces.md`, `changelog.d/533-memory-half-per-round.md` | `Document the memory half's round accounting` |

### Plan amendments from review round 4

Delivered mid-milestone by the orchestrator and implemented as the
plan; recorded here as amendments, not deviations.

1. **`memory_characters` is counted where the blocks render, not as a
   text difference.** `RoundPrompt.memory_characters` sums each scope
   block of the sent `Assembled` plus the `JOIN` before it where one
   precedes it (none for a scope block that opens the prompt, which a
   blank persona produces). The know-how half is not always a prefix of
   the round's prompt: `_assembled` leaves a one-block prompt untouched
   and lstrips the first block once a second follows, so
   `know_how("  persona")` and its `with_scopes` disagree on the first
   characters. What `_assembled` sends is unchanged. Regression tests:
   `test_a_round_prompt_counts_the_scopes_as_sent_after_a_trimmed_persona`
   (the value) and
   `test_the_scopes_are_counted_as_sent_after_a_persona_that_was_trimmed`
   (against the string the provider received, through a session).
2. **The per-block sizes are flattened by a validated helper**,
   `_round_prompt_attributes`, the `_prompt_attributes` pattern: the
   mapping is built through `MemorySources`, so only `state`, `memory`
   and `device` can become an attribute name. It is composed into
   `_llm_span` and into the LLM branch of `_provider_failed`.
3. **`vinga.llm.memory.fact_count` exists exactly when the id list
   does**: derived from the list the same helper exported, so `0` for
   an attempted read that injected nothing and absent with memory off.
   The three states are tested on the event (assembly and provider
   watch) and on the span, finished and failed.

One consequence of amendment 1: `RoundPrompt` holds the sent
`Assembled` and `facts`, and not the know-how `Assembled` decision 7
listed. With the count taken from the sent blocks nothing reads the
half any more, and a field nobody reads fails the deletion test.

### Deviations from the plan

None in what was built beyond the amendments above. Choices the plan
left open:

- **`MemorySources` has a kind of its own, `MEMORY_SOURCES`,** rather
  than reusing `SOURCES`, whose reference row says "keyed by the
  grammar below" and whose grammar is the know-how half. Its `SHAPES`
  row is `JSON`, which only a span event would use; the `llm` span
  flattens it through amendment 2's helper. The reference's field-row
  oracle (`test_event_docs.py`) learned the kind and holds the cell to
  the three scope names.
- **The closed set is `ScopeProvenance`, a `StrEnum` restated in
  `events/values.py`** and held equal to `runtime/prompt.SCOPES` by a
  test, the pattern the module's other closed sets follow (the events
  package cannot import `runtime`). `SCOPES` and `JOIN` are new named
  constants in `runtime/prompt.py`; `_assembled` joins with `JOIN`.
- **`FactIds` declares a `fact_id` syntax** (`[1-9][0-9]{0,18}`, noted
  as carried as a JSON integer), because the `ID_LIST` kind's reference
  cell names the element syntax. The kind's meaning row now says an
  element is a string or, where the syntax says so, an integer.
- **`events.assembly` takes the accounting through a structural
  `RoundAccounting` protocol** rather than importing `RoundPrompt`: the
  module's contract is that it imports the catalog and the value
  vocabulary and no subsystem. `RoundAccounting` joins the module's
  pinned interface list. One private helper, `_accounted`, derives the
  four fields for both builders.
- **The accounting is required where it always exists and refused
  where it never does.** `reply_stream` and `reply_round_done` take
  `prompt` as a required keyword (the eight existing direct calls in
  `test_provider_watch.py` pass one); `llm_rounded` refuses one on a
  recap, and `provider_failure` refuses one for any stage but `llm` or
  any purpose but `reply`.
- **`memory_sources` is present and empty (`{}`) on a round with no
  scope block**, like the other sizes, rather than absent: the sizes
  describe the prompt sent, and that prompt had no scope block.
- **Decision 9's bound is stated as numbers in the note** (at most 70:
  the agent block's newest 40 and the device scope's cap of 30), since
  the catalog cannot import `memory/store.py`, which emits events. A
  test holds the numbers to `CORE_LINES` and `DEVICE_LINES`.

### Discoveries

- **The plan's prefix assumption was false**, found here before round
  4 named it: a one-block persona with leading whitespace, and a blank
  persona with a scope block, both make the know-how half's text a
  non-prefix of the round's prompt. Amendment 1 is the fix.
- **Langfuse stores an empty integer array as `{"arrayValue": {}}`**,
  not as `[]`, while a non-empty one comes back as a JSON array of
  integers (see the live gate). The OTLP side is correct (the SDK keeps
  `()`), and `vinga.llm.memory.fact_count` is `0` beside it, which is
  the attribute a backend filters on; flagged rather than worked around.
- **The fact-count mutation that reads the wrong list survived one
  case by coincidence**: with three ids and three scope blocks, a count
  taken from the size mapping's length equals the right one. The empty
  and at-cap cases killed it.
- **The mixed-type arm of the widened `SEQUENCE` fold is unreachable
  through the declared types**, since `_Rule.accepts` constructs the
  value type first and none admits a mixed list. It is defence in
  depth and has no test through the interface.
- **`test_a_reader_who_stops_reading_mid_chunk_gets_no_traceback`
  fails on agentpi with this milestone's reference, and the cause is
  the machine.** It passes at the plan commit and fails
  deterministically here ("the pipe holds 253952 of 262144 bytes", one
  stream buffer short). The test pre-fills a pipe so that exactly the
  document's whole-chunk part (its length less the remainder modulo
  8,192) fits. agentpi runs a 16 KiB-page kernel, where a pipe fills by
  16 KiB slot, so the construction holds only when that part is a
  multiple of 16,384: 131,072 at the plan commit (passes), 139,264 here
  (fails). Padding the document by 8,192 characters on a scratch copy
  (whole-chunk part 147,456) made it pass again. On 4 KiB pages, CI's,
  every multiple of 8,192 is a multiple of the page, so CI is expected
  to stay green; M1's own growth of the reference can move it either
  way on this machine. The test's construction is the thing to fix,
  and it is outside this milestone.
- **The plan's review sections carry five links the link check
  refuses** (`docs/plans/2026-10-01-telemetry-metadata-half.md`, the
  round 3 section, absolute paths into a session worktree). They are
  in the plan commit this branch starts from, not in this milestone's
  changes.
- **The `recap` round needs no session-level test of its own**: its
  builder refuses an accounting, `recap_round_done` has no parameter
  for one, and the provider-watch and span tests assert a recap carries
  none of the fields.

### Inventories

By `git grep -n`, untruncated, at this section's tree.

- **`PromptMemory(`**: 25 hits. Two in production, both in
  `memory/store.py` (`NOTHING_REMEMBERED` and `read_for_prompt`'s
  `read`); one in the plan; 22 in tests (`test_runtime_prompt.py` 17,
  and one each in `test_config_api_runtime.py`, `test_memory_store.py`,
  `test_event_assembly.py`, `test_provider_watch.py`,
  `test_telemetry_spans.py`). Every test site passes the rendered
  strings by keyword or position and keeps the ids' `()` default unless
  the case is about ids, so none changed meaning.
- **The accounting's call sites in `vinga-server/src`**: 10 hits for
  `_system_prompt()`, `reply_round_done(`, `reply_stream(` and
  `.failed(`. `_system_prompt` has one caller (`pipeline.py`, the reply
  loop), which passes the one `RoundPrompt` to `reply_stream` and
  `reply_round_done`. Of the five `failed` calls, the two in
  `provider_watch.py` that end a reply round (`watched`'s and the
  watchdog's direct one) carry it; `watching`'s (ASR, TTS), the
  pipeline's recap timeout and the pipeline's TTS call carry none.

### Falsification

Each new test was run against the code before its change and watched
failing: the store's id tests (3 failed on `PromptMemory`'s missing
fields), the value tests (collection error on the missing kind), the
`RoundPrompt` tests (5), the assembly tests (7), the provider-watch
tests (12, the eight existing calls among them on the new keyword), the
four session tests and the device test (against `pipeline.py` and
`provider_watch.py` at the plan commit), and the span tests (7 of 9;
the recap and unaccounted case passes vacuously before and is there for
the mutations). The `SessionIds` regression pin passed before the fold
changed, which is what a pin is for, and after it. Three existing pins
in `test_provider_watch_pins.py` failed on the first unit lane, as an
exact-payload pin should when a payload grows, and were updated to hold
the new fields.

| Mutation | Result |
| --- | --- |
| `_core`'s kept ids replaced by `_newest`'s read ids | killed: `test_the_prompt_read_names_exactly_the_facts_it_rendered` |
| The recap refusal removed from `llm_rounded` (the recap given the fields) | killed: `test_a_recap_refuses_a_prompt_accounting` |
| The stage and purpose guard removed from `provider_failure` | killed: 3 cases of `test_only_a_reply_round_failure_takes_a_prompt_accounting` |
| The watchdog's direct `failed` without `prompt` | killed: `test_a_round_given_up_by_the_watchdog_carries_the_prompt_it_was_sending` |
| The `JOIN` dropped from `memory_characters` | killed: 3 `RoundPrompt` tests |
| Fact count as `len(payload.get("memory_facts", []))`, unconditional | killed: the two memory-off span cases and the recap case |
| Fact count from a stale list (the size mapping's length) | killed: the empty-list cases and the at-cap case; the three-id case survived by coincidence (see Discoveries) |

None survived as a mutation.

### The live gate

Run on agentpi, 2026-10-01 05:47 to 05:49 CEST, from an uncommitted
driver in the session's scratchpad: a server in process on this
branch's working tree, whose source was then committed unchanged as
`7bd8fecf` and `e270f025`, with OpenAI ASR
(`gpt-4o-mini-transcribe`), the OpenAI-compatible LLM on
`api.openai.com` with `gpt-4.1-mini`, OpenAI TTS (`gpt-4o-mini-tts`),
silero VAD, the builtin tools, and telemetry on with
`export_llm_input`, exporting directly to the project's Langfuse
(`/api/public/otel`, ingestion version 4). Three spoken questions,
synthesized with OpenAI TTS and resampled to 16 kHz, went through the
xiaozhi-sdk client; the second asked the guide to remember a favourite
herb, and the model called `remember` (one `tool_call`). Session
`d53eef68dd4f4a50a9ebd9c27d79e35d`, read back through
`GET /api/public/v2/observations?sessionId=...&fields=core,basic,metadata`.

| Observation | Round | `memory.facts` | `fact_count` | `system.characters` | `memory.characters` | `sources.memory` |
| --- | --- | --- | --- | --- | --- | --- |
| `95c9893ce570f858` | turn 1, round 1 | `{"arrayValue": {}}` | 0 | 216 | 0 | absent |
| `b52b3202dbabd9cc` | turn 2, round 1 (calls `remember`) | `{"arrayValue": {}}` | 0 | 216 | 0 | absent |
| `8ced6d164b2aa69c` | turn 2, round 2 | `[1]` | 1 | 305 | 89 | 87 |
| `0b8edd8af35b622c` | turn 3, round 1 | `[1]` | 1 | 305 | 89 | 87 |

**The gate passes on integer arrays.** The round after the `remember`
(`8ced6d164b2aa69c`, invocation `788d450c13b9480d9c61df0185208d4f`)
returns `attributes.vinga.llm.memory.facts` as the JSON array `[1]`,
element and type intact, with the count and the sizes beside it as
numbers; `1` is the id the store gave the remembered fact in the run's
fresh database. The decimal-string fallback was not needed. The same
values were on the server's own `llm_round` lines, which the driver
captured. The empty array's rendering is the discovery above. The
pre-implementation probe, a hand-built span with `(3, 17, 1, 11)` beside
the string form, came back as `[3, 17, 1, 11]` (observation
`ff7e11dc9f6330ce`).

`memory.characters` is 89 against a block of 87: the two characters
are the blank line joining the block to the persona, which is what
amendment 1 counts.

**Observed, not gated.** With `export_llm_input` on,
`gen_ai.system_instructions` appeared neither in the observation's
`input` (which holds the user and assistant messages only) nor in its
metadata keys; the system prompt is not visible through this API on
Langfuse as configured.

**Log volume.** The `llm_round` JSON line, formatted by the server's
`JsonFormatter`, with and without the four fields: 780 against 688
characters (turn 1, no scope block, empty list) and 793 against 687
(turn 2 round 2, one block, one id), so about 90 to 110 characters per
round at this size. At the bound (70 ids of a few digits each) the list
adds a few hundred more.

### Lanes

From `vinga-server/`, on agentpi (shared with another implementer),
both lanes with `-n auto --dist loadfile`:

- `uv run ruff check .`: all checks passed; `uv run mypy`: no issues in
  5 source files.
- Unit, first run (at `094cba21`): `4 failed, 7745 passed, 19 skipped
  in 1600.07s`. Three were the exact-payload pins in
  `test_provider_watch_pins.py`, fixed by `cb20a033` (the file then
  `8 passed in 45.51s`); the fourth is the pipe test in Discoveries.
- Unit, final (at `cb20a033`): `1 failed, 7748 passed, 19 skipped in
  1722.27s`, the one failure being that pipe test.
- Integration (at `094cba21`; nothing after it touches what that lane
  runs): `349 passed in 618.10s`.
- `python3 scripts/check_doc_links.py .`: `checked 280 files, 5
  failures`, the five pre-existing plan links in Discoveries, the same
  count at the plan commit.
- `uv run pytest tests/census -q`: run last, after this section; its
  result is in the pull request's verification list.

## M1: the round and the tool call

**Attribution:** anthropic/claude-opus-5-5, thinking high; Claude Code 2.1.286; 2026-10-01.

### What landed

| Decision | Where | Commit |
| --- | --- | --- |
| 1, the first token as `vinga.llm.first_token_ms`, the `first_token` span event removed | `telemetry.py` (`LLM_ATTRIBUTES`, `_llm_span`; `FIRST_TOKEN` and `_after` deleted) | `Carry the first token as a round attribute` |
| 2, `invocation` and `position` on the three `tool_call` variants, mapped by `TOOL_ATTRIBUTES` | `events/catalog.py`, `events/assembly.py`, `runtime/tool_execution.py`, `runtime/pipeline.py`, `telemetry.py`, `docs/reference/events.md` regenerated | `Name the round and place of a tool call on its span` |
| 2, the exact-payload tests the full lane found | `tests/unit/test_session_tool_events.py`, `tests/unit/test_tts_lookahead.py` | `Pin a tool call's round and place in its line` |
| 4, the `language_confidence` note | `events/catalog.py`, `docs/reference/events.md` regenerated | `Say which engines report language_confidence` |
| The `GEN_AI` guard over `TOOL_ATTRIBUTES`, and the row it found missing | `tests/unit/test_conversations_docgen.py`, `conversations/docgen.py`, `docs/reference/conversations-schema.md` regenerated | `Hold the GenAI table to the tool span's mapping too` |
| The documentation footprint and the changelog fragment | `docs/architecture/observability-surfaces.md`, `changelog.d/533-tool-and-round-attributes.md` | `Document M1 of #533 and tick it` |

### Plan amendment from review round 4

Decision 3, the keyed prompt digest, was withdrawn from the plan by its
fourth review round while this milestone was being implemented, and
deferred to Rafael (the plan's decision 3 now says why). It is an
amendment to the plan, not a deviation from it: none of it was written
here. No `Digest` value type, no `digest` field on `PromptAssembled`,
no `vinga.prompt.digest`, no master-key subkey and no composition
change exist on this branch, and the digest tests, sentinel, mutation
and live-gate row went with the decision. The branch was rebased onto
the amended plan (`01d1b11c`) before this section was written.

### Deviations from the plan

One, in how decision 2's position travels.

- **The position is read off the reservation, not threaded as a new
  value.** The plan says to enumerate `calls` before `_run_tools`
  partitions them and carry the index "through `_run_tools`,
  `ToolExecution.run`, `_run_one`, `_tool_called` and the three
  assembly builders". That enumeration already exists:
  `ToolExecution.reserve` files every call of a round on the turn's
  record as a frozen `conversations.records.ToolInvocation` whose
  `position` is `enumerate(calls)` over the model's own list, before
  the partition, and `_run_one` already reads that record back by slot
  (`turn.reserved(slot)`) to classify the call it emits. `executed`
  replaces the record with `dataclasses.replace`, which keeps the
  position. So `_tool_called` takes `classified.position`, and a second
  carrier of the same number beside the slot would be the
  two-structures-that-must-agree shape the design conventions name.
  The property the plan asks for holds and is pinned the way it asked:
  the move-gap test fails under the plan's mutation (below). A side
  effect is that the span's position is the same number the call's
  `tool_invocations` row records, which the catalog note states
  without claiming the row is unique by it (a turn's rounds repeat
  positions, and the row carries no round).
- The invocation is threaded exactly as the plan says: `_run_tools`
  gains it as a parameter, `ToolExecution.run` as a required keyword,
  `_run_one` and `_tool_called` as an argument, and the builders take
  `invocation` and `position` keyword-only after their existing
  defaulted `error_type`, so no existing positional call could shift.

### Resolutions of what the plan left open

- **The tests' home.** The production-path join tests live in
  `tests/unit/test_telemetry_spans.py` beside the tool-span fold tests,
  driving a real session (`session_for` with a scripted model) whose
  events are tapped by an in-memory `Telemetry`, because what they
  assert is a span attribute.
- **Which calls the tests use.** `recall` and `set_state`, two
  builtins, so the spans carry `gen_ai.tool.name` and the n-th exported
  call can be matched to its span by name; and a refused
  `switch_agent` (to an agent the board is not bound to) as the move.
  `set_state` is one of the ordered memory writes and runs before
  `recall`, so in the content-export test the tool spans end in
  neither the model's order nor each other's, and the position is the
  only thing tying each span to its part.
- **The integration lane's first-token assertion** is now that the
  mock round carries `vinga.llm.first_token_ms` as an integer and the
  `llm` span carries no span event, off the wire.
- **`vinga-server/README.md`**: checked, and left alone. Its
  "Exporting traces" section names neither the first-token mark nor a
  prompt size.

### Discoveries

- **The `GEN_AI` guard found a missing row as soon as it was
  extended.** `TOOL_ATTRIBUTES` has mapped a builtin's `tool` to
  `gen_ai.tool.name` since #67, and `conversations/docgen.py`'s table
  never had the row, so the reference's correspondence was incomplete
  while its drift check stayed green. The parametrized guard failed on
  exactly that pair before the row was added.
- **Two provider ids for two calls in one round need not differ.** The
  scripted model's `call()` helper mints `c-<name>`, so the same-entry
  test's two calls carry one id, which is the OpenAI-compatible
  adapter's `call_{index}` fallback in miniature: a join on the
  provider's id would have named one call twice.
- **Langfuse stores the new integers as strings.** On the live gate
  `vinga.tool.call.position` and `vinga.llm.first_token_ms` came back
  as `"0"`, `"561"`: the observation's `metadata.attributes` holds every
  attribute as a string, the existing `vinga.llm.round` included. That
  is the backend's rendering of a scalar, not a property of this
  change, and it is M2's gate (integer arrays) that has to measure
  whether it matters; for scalars a string compare is still exact.
- **Langfuse renamed the tool observations.** The builtin calls
  arrived as observations named `remember` and `recall`, their
  `gen_ai.tool.name`, rather than the span's own name `tool`, typed
  `TOOL`. Only builtins were observed, so what an MCP or device call
  is named there is not measured.

- **Three tests outside the targeted runs pinned the old shape.** The
  first full unit lane failed three: two in
  `tests/unit/test_session_tool_events.py` hold the `tool_call` line's
  payload to an exact dictionary, and
  `tests/unit/test_tts_lookahead.py` stubs `_run_tools` by its
  signature. They are fixed in their own commit rather than folded
  into the change that broke them, so the decision-2 commit alone is
  red on those three; the exact payloads now assert the invocation
  against the round's own `llm_round` record and each call's place
  (0 and 2 for the two `remember` calls, 1 and 3 for the unnamed ones,
  0 and 1 for the MCP pair), which makes them production-path pins of
  the join as well.

### Inventories

By `git grep -n`, untruncated, at `4c669b40` (the plan commit this
branch started from), counted with `wc -l` and read in full.

- **`first_token`** in `vinga-server/` and `docs/`: 166 lines, 116
  outside `docs/plans/`. The readers of the span event are five lines:
  the `FIRST_TOKEN` constant and its `add_event` in `telemetry.py`, and
  three test assertions (`tests/unit/test_telemetry_spans.py:648,745`,
  `tests/integration/test_telemetry_export.py:405`). No document read
  it. The other 111 are the `first_token_ms` event field and turn
  column (the catalog, assembly, `provider_watch.py`, `turns.py`, the
  store, the API responses, the migrations and the metrics views'
  `first_token` stage label), the `llm_first_token_timeout_s` setting
  (15 lines), the generated references and two dated feature docs and
  an ADR quoting the field. All of them are about the field or the
  setting, which this milestone does not change. The expectation from
  Step 0 (tests only) held.
- **`tool_call` builder call sites** (`builtin_tool_called(`,
  `mcp_tool_called(`, `unnamed_tool_called(`): 12 lines, the three
  definitions, the three production calls in
  `runtime/tool_execution.py:_tool_called`, the three in
  `tests/support/telemetry.py:call_tool` and three assertions in
  `tests/unit/test_event_assembly.py`. All updated.
- **`ToolExecution.run` call sites**: one production caller,
  `runtime/pipeline.py:1924` in `_run_tools`, whose one caller is the
  reply loop with the round's `invocation` in scope; four direct test
  calls (`tests/unit/test_session_tools.py:1051,1196`,
  `tests/unit/test_tool_execution.py:115,142`), which now pass a fixed
  `INVOCATION`.

### Falsification

Each new and changed test was run against `HEAD`'s source first (the
five changed source files swapped for their committed versions,
restored by copy and `touch`) and watched failing: the three
first-token span tests (the no-token case passes before and after, as
an absence must), the three builder tests, the fold test and all four
production-path tests (`test_a_tool_span_joins_the_round_that_asked_for_it`,
`test_a_move_keeps_its_place_in_the_round`,
`test_the_nth_exported_call_is_the_span_at_position_n`,
`test_the_provider_s_call_id_reaches_no_metadata_surface`), and the
extended docgen guard (on the missing `gen_ai.tool.name` row).
Mutations, one run each, restored by copy-aside, copy-back and
`touch`:

| Mutation | Result |
| --- | --- |
| `LLM_ATTRIBUTES`' `first_token_ms` entry removed | killed: 3 span tests (reply, recap, retry) |
| Position taken from the partitioned list (`enumerate` over `run`'s `calls`) | killed: the move-gap test and the n-th-exported-call test |
| Invocation taken from the wrong round (the first round's, for every round) | killed: `test_a_tool_span_joins_the_round_that_asked_for_it` |
| Not in the plan: the provider's call id passed as the invocation (a credential-shaped id satisfies the invocation syntax) | killed: the no-leak sentinel |

None survived.

### The live gate

Run on agentpi, 2026-10-01 from 03:15:39 to 03:16:19 UTC, from an
uncommitted driver in the session's scratchpad: a real server in
process on this branch's tree (at `43dc13df` plus the uncommitted
documentation), with OpenAI ASR, the OpenAI-compatible LLM on
`api.openai.com` with `gpt-4.1-mini`, OpenAI TTS, silero VAD, the
builtin memory tools, and telemetry on with `export_llm_input`,
exporting directly to the project's Langfuse over OTLP/HTTP. Two
questions, synthesized with OpenAI TTS and resampled to 16 kHz, were
sent through the xiaozhi-sdk client on one connection, so one session
of two turns. Both turns' first rounds called two tools in one round,
which is the case the position exists for. The observations were read
back through the Langfuse public API (`GET /api/public/observations`,
17 observations from the run's start).

| Observation | Id | `vinga.llm.invocation.id` | `vinga.tool.call.position` | `vinga.llm.first_token_ms` |
| --- | --- | --- | --- | --- |
| turn 1, `llm` round 1 | `f5cd81f69cef1be2` | `6033c654...` | | absent (tools only) |
| turn 1, `remember` | `af33cd62f151502a` | `6033c654...` | `0` | |
| turn 1, `remember` | `b611a2d6fe1ff407` | `6033c654...` | `1` | |
| turn 1, `llm` round 2 | `edd1616945ed81fd` | `e3ffc5ed...` | | `561` |
| turn 2, `llm` round 1 | `751bf6c325b9fd87` | `a5331404...` | | absent (tools only) |
| turn 2, `recall` | `16afc2cb85002626` | `a5331404...` | `0` | |
| turn 2, `recall` | `b529810692d29bd7` | `a5331404...` | `1` | |
| turn 2, `llm` round 2 | `493a3151a3a16532` | `c51e8898...` | | `552` |

Every M1 row passes: the speaking rounds carry the first token as an
attribute and the tool-only rounds carry none; each tool observation
carries the invocation id of the round that asked for it, equal to
that round's own, and its position, and the two calls of one round
differ by position. No observation carries an `events` key. The two
asking rounds' exported output holds two `call_...` provider ids each,
and none of the four appears anywhere on a tool observation.

### Lanes

On agentpi, shared with two other implementers' lanes while these ran.

- `uv run ruff check .`: all checks passed.
- `uv run pytest tests/unit -q -ra -n auto --dist loadfile`, first run:
  `3 failed, 7698 passed, 19 skipped in 1851.07s (0:30:51)`, the three
  tests in Discoveries. After their commit:
  `7701 passed, 19 skipped in 1521.05s (0:25:21)`.
- `uv run pytest tests/integration -q -ra -n auto --dist loadfile`:
  `349 passed in 824.15s (0:13:44)`.
- `python3 scripts/check_doc_links.py .`: 280 files checked, 5 failures,
  all five in the plan's own "Plan review round 3" record, whose
  evidence links are absolute paths into the reviewing session's
  scratch worktree (`/tmp/...`). They come from the plan branch, not
  from this milestone, and are left for the plan's owner to fix, since
  the text is a verbatim review record. Nothing this milestone wrote
  fails the check.
- `uv run pytest tests/census -q`, run last, after the final prose
  edit: recorded in the pull request.
