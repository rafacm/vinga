# Give tool execution, provider watching and the reply in flight owners: implementation

Companion to `docs/plans/2026-09-23-reply-runtime-modules.md`
([#482](https://github.com/rafacm/vinga/issues/482)). One section per
milestone, appended in the change that ticks it, recording deviations
from the plan, resolutions of its open questions, and discoveries; a
milestone with none says so. M1 and M2 run in parallel, so each appends
its own section below this line and a rebase keeps both.

## M2: provider watching in `runtime/provider_watch.py`

**Attribution:** anthropic/claude-opus-5-5, thinking high; Claude Code 2.1.280; 2026-09-23.

Provider watching has one owner, `runtime/provider_watch.py`'s
`ProviderWatch`: how a failing provider call is reported without being
swallowed, how an LLM stream's own failure is told apart from its
consumer's, how the first token is bounded and retried once, and what a
finished round reports and files. `PipelineRuntime` builds one in its
constructor as the private `self._watch` and every watched call goes
through it. `runtime/pipeline.py` goes from 3,517 lines to 3,233;
the new module is 443, most of it the moved docstrings.

### The commits

| Commit | What it is |
| --- | --- |
| `Pin what provider watching says before it moves` | `tests/unit/test_provider_watch_pins.py` and three recap pins in `tests/unit/test_session_recap.py`, green against the code before the move |
| `Add ProviderWatch, the provider-watching module` | `runtime/provider_watch.py` and `tests/unit/test_provider_watch.py`, nothing using it yet; the mutations run against it are in the body |
| `Hand the recap suite its export at construction` | Three recap tests stop assigning `_llm_input` after construction (below); green before and after the move; reach-in manifest regenerated |
| `Move provider watching into ProviderWatch` | The move as one commit: the runtime's call sites, its field, the deletions, and the runtime's own prose |
| `Rename the watch's emit identities in the baseline` | The three event-baseline identities, one to one |
| `Name the watch where source prose named the runtime` | The documentation footprint outside the runtime |
| `Record M2 in the implementation doc` | This section and the tick |

### The interface as built

The plan's names, unchanged: `FirstTokenTimeout`, and `ProviderWatch`
with `watching`, `watched`, `reply_stream`, `reply_round_done`,
`recap_round_done` and `failed`, each with the plan's signature. Two
private additions the plan did not name:

- `_rounded`, the one emit site both round reports go through. It
  computes the elapsed time, the first token and the token counts,
  finishes the round on the LLM input export, emits `llm_round`, and
  answers the numbers; `reply_round_done` then files them on the turn
  it was handed, and `recap_round_done` drops them. Why one site and
  not two is under the baseline identities below.
- `_agent()` and `_conversation()`, the pair read off
  `conversations.active` at the moment of asking, called inside each
  emission's thunk: the `FillerRunner` shape, for the same reason.

`_reported`, the usage-to-numbers helper whose only caller was the
round report, moved with it. `FirstTokenTimeout` is not re-exported
from `pipeline.py`; nothing imported it from there.

`reply_stream` is itself the async generator the tool loop iterates,
so the `async for` over it is the same single generator the runtime's
`_watchdog_stream` was and the barge-in cancellation still lands in the
`asyncio.timeout` wait. `watched` is `_watched_stream` with its body
unchanged. The round the retry line and `llm_round` name is `round_`,
passed by the tool loop from `self._llm_round`, which stays a runtime
field for M3; the turn `reply_round_done` files on is `self._turn`,
passed at the call.

### The pins, and what they pinned

The inventory the plan asked for, per moved emit site, of what an
existing suite asserted before M2. None asserted the unrendered
sentence, the typed arguments and the whole payload together, so every
site got a pin at that strength; the timing fields (`duration_ms`,
`first_token_ms`, and the seconds among the arguments) are held by type
and presence.

- **`llm_retry`:** `test_session_watchdog.py:78` asserted the agent,
  round, stage, provider and a `duration_ms` at least the bound. Pin
  added: `test_a_retried_round_says_llm_retry`.
- **`llm_round`, a reply round:** the round number
  (`test_session_watchdog.py:78`), a tool-only round's absent
  `first_token_ms` (`test_session_tools.py:66`), the pair across every
  transition (`test_pair_attribution.py:94`). Pin added:
  `test_every_reply_round_says_llm_round_and_files_itself_on_the_turn`,
  two rounds of one reply, a tool-only one and a speaking one.
- **The turn record's `round_done` numbers:** `test_session_record.py`
  asserted `rounds`, the token totals, and `first_token_ms <= llm_ms`
  (L113, L133, L450). The same pin now also holds `rounds == 2`,
  `llm_ms` equal to the sum of the two events' `duration_ms`, the
  record's `first_token_ms` equal to the speaking round's (the first
  round had none), and the token totals summed across both.
- **`llm_round`, a recap round, and its absence from the record:**
  `test_session_recap.py:702`'s staging test asserted no `round`, the
  invocation, and `rounds` summing to 2 across the turns. Pin added:
  `test_a_recap_round_says_llm_round_without_a_round_and_files_nothing`,
  which also holds the turns' summed `llm_ms` to the reply rounds'
  durations alone.
- **`provider_failed`, the reply's ASR through `watching`:**
  `test_event_surface_pins.py:462` asserted the error class and the
  absence of the entry fields for a provider the registry never built,
  beside its sentinel. Pin added:
  `test_a_failing_ear_says_provider_failed_at_the_asr_stage`.
- **`provider_failed`, the reply's LLM stream through `watched`:**
  `test_event_surface_pins.py:437` asserted the error class, stage,
  provider, host and model beside its sentinel. Pin added:
  `test_a_failing_stream_says_provider_failed_at_the_llm_stage`.
- **`provider_failed`, a round the watchdog gave up:**
  `test_session_watchdog.py:103` asserted the stage, the error, the
  agent and "timed out" in the sentence. Pin added:
  `test_a_round_given_up_says_provider_failed_as_first_token_timeout`.
- **`provider_failed`, the recap timeout:** `test_session_recap.py:586`
  asserted the error, the invocation and no `round`. Pin added beside
  it: `test_a_recap_that_ran_long_says_provider_failed_as_a_timeout`.
- **`provider_failed`, a recap stream that failed through `watched`:**
  `test_session_recap.py:532` asserted the same three fields plus the
  no-leak sentinel. Pin added:
  `test_a_recap_stream_that_failed_says_provider_failed_as_its_class`.
  This path is not in the plan's list of four; it is a separate caller
  of `watched` with its own `purpose`, so it got its own pin.
- **`provider_failed`, TTS:** `test_session_reply_failures.py:158`
  asserted the stage and the error class. Pin added:
  `test_a_failing_voice_says_provider_failed_at_the_tts_stage`.
- **`provider_failed`, `confirm_transcript`:**
  `test_session_barge_in.py:292` asserted the stage, provider, host,
  error and wording of a failed confirmation. Pin added:
  `test_a_failing_confirmation_says_provider_failed_and_still_raises`.

The recap pins live in `test_session_recap.py` rather than the new file
because that suite already sets up the offer a recap needs; reaching
for it from a new file would have added reach-ins. Neither file adds
one. The pins passed unmodified after the move, and
`git diff 83b708e9 HEAD` shows no change to any of them.

**An emit across a handover.** The plan's risk section asks which test
exercises one of the moved emits across a handover, or for one to be
added. `test_pair_attribution.py:94` holds every `llm_round` pair
through connect, a handover, the handover back, a new conversation and
a resume, but each of those rounds starts after its transition, so it
cannot tell a pair read at emit time from one read at call entry. One
pin added that can:
`test_a_confirmation_failing_across_a_handover_names_the_pair_it_ends_on`,
a confirmation suspended inside its transcription while the session
hands over to the tutor, whose failure must name the tutor. The module
suite's `test_a_failure_names_the_pair_standing_when_it_is_said` is the
same claim without a session, and is the one mutation C below fails.

The two tests the brief named stay green with their assertions
unmodified: `test_event_surface_pins.py:437`,
`test_a_failing_providers_own_words_reach_no_record`, and
`test_session_watchdog.py:199`,
`test_a_cancel_during_the_watchdog_window_still_lands`.

### The module's own tests, and the mutations

`tests/unit/test_provider_watch.py` builds a watch over a
`SessionEvents`, a `SessionConversations` and nothing else, with
streams scripted per attempt. Beyond the plan's two
(retry-once-then-give-up and the `expired()` passthrough) it covers
the retry that answers, `watching` reporting and re-raising, a
consumer's failure not blamed on the stream, the pair read when the
failure is said, and a reply round filed on its turn where a recap
round is not.

Each claimed behavior was watched failing against a mutation first,
the file copied aside and copied back after each:

| Mutation | Result |
| --- | --- |
| A: drop the `expired()` check | `test_a_providers_own_timeout_before_the_deadline_passes_through` fails: the SDK's `TimeoutError` inside the window came back as `FirstTokenTimeout` after a retry |
| B: one attempt only (`("retry",)`) | the retry-answers test and the give-up test fail: one call where two were due |
| C: the agent read at construction | `test_a_failure_names_the_pair_standing_when_it_is_said` fails: the failure named `poet` after the activation of `tutor` |
| D, after the move: `watching` reports the pair standing at its entry | the session-level `test_a_confirmation_failing_across_a_handover_names_the_pair_it_ends_on` fails: the failure named `poet`, not `tutor` |

Every suite green again after each restore, and the restored file
byte-identical to the committed one.

### The event-baseline identities

Renamed one to one in `tests/tools/event_baseline.py` (with a new
`PROVIDER_WATCH` module constant) and in `CARRIED`:

- `PipelineRuntime._watchdog_stream #1` to `ProviderWatch.reply_stream #1`
- `PipelineRuntime._llm_round_done #1` to `ProviderWatch._rounded #1`
- `PipelineRuntime._provider_failed #1` to `ProviderWatch.failed #1`

The brief warned that splitting `_llm_round_done` into two methods
might split its identity. It does not, because both public methods emit
through the one private `_rounded`: `drive_llm_round` still drives a
reply round and a recap round through the same site, the produced
shapes are unchanged, and the driver count stays 106. Giving each
public method an emit of its own would have made two identities and
needed a 107th driver for a site that says nothing the first does not.

### Deviations and discoveries

- **The recap suite's export moved to construction.** Three tests in
  `test_session_recap.py` attached the LLM input export by assigning
  `session.runtime._llm_input` and `session._llm_input` after the
  session was built. That worked only while every reader of the export
  was a runtime method reading the field at call time. The watch is
  handed the export at construction, as the plan's signature says, so
  after the move a replaced field reached the runtime's staging and not
  the watch's `finish`, and the three tests failed on a missing
  snapshot. They now pass the export through `session_for`'s
  `llm_input`, which is how a deployment hands one over, with their
  assertions unchanged, in a commit of its own ahead of the move and
  green on both sides of it. The reach-in manifest loses the six
  `_llm_input` sites in that file. This is the plan's own reach-in rule
  applied: the tests were pinning when a collaborator is read, which is
  a detail the move was free to change.
- **One more `provider_failed` caller path than the plan listed:** a
  recap stream that fails goes through `watched` with `purpose=recap`.
  Pinned (above).
- **`FirstTokenTimeout` no longer carries a chain**, from the review
  round below (P1). The watchdog's `raise failure from exc` came across
  verbatim from the runtime, so the failure left with asyncio's
  `TimeoutError` as its cause and the `CancelledError` behind it. It is
  now raised outside the arm that caught the expiry, without `from`, so
  `__cause__` and `__context__` are both None. That is a behavior
  change to the exception object, and the one place this milestone's
  `reply_stream` is not the runtime's body copied over. It reached no
  retained surface: `_reply`'s generic arm logs the class name with no
  `exc_info`, `provider_failed` is built from the failure before it is
  raised and carries its class name only, the reply task catches it so
  no asyncio handler sees it, and the telemetry export reads event
  payloads, never exceptions. No test walked it either: the chain
  walkers in `test_session_reply_failures.py` and `test_turntaking.py`
  walk exceptions those tests build, and every `exc_info` assertion in
  the reply path's suites says None.
- **Nothing else deviates.** The signatures, the round as an argument,
  the two round reports, the constructor-time bound, the pair read at
  emit time and `FirstTokenTimeout` not re-exported are all as planned.

### Documentation footprint

No page under `docs/`, as measured. The runtime's own prose moved in the
move commit: the class docstring's list of modules and its
`_llm_round` entry, the ASR cancellation comment, the handover emit
comment and `confirm_transcript`'s docstring. Outside the runtime:
`providers/base.py`, `runtime/turntaking.py` and
`tests/support/providers.py` as the plan listed, plus two test
docstrings the plan's sweep did not list (`test_session_tools.py:79`
naming `_watchdog_stream`, and `test_turn_lifecycle.py:410` naming
`_watching`). `docs/features/2026-08-19-no-leak-sweep.md` keeps its
historical name.

**Changelog:** none. No event, field, log line, stored row, spoken
sentence or timing bound changed, so no `changelog.d/` fragment. The
chain `FirstTokenTimeout` no longer carries (above) reached none of
those surfaces, so it gets no fragment either.

### Verification

Run on the tree at `74e6e9b0` (`8cd335e8` after the rebase onto the
amended plan branch) plus this section, on this machine,
with the lanes distributed the way CI runs them (`-n 4 --dist
loadfile`):

- [x] `uv run ruff check .`: all checks passed.
- [x] `uv run pytest tests/unit -q -ra -n 4 --dist loadfile`: 7,504
  passed, 19 skipped (the faster-whisper and piper extras, not
  installed here), 14m05s.
- [x] `uv run pytest tests/integration -q -ra -n 4 --dist loadfile`:
  347 passed, 4m46s.
- [x] `uv run pytest tests/census -q`: 66 passed. The reach-in manifest
  moved by one line, `tests/unit/test_session_recap.py  _llm_input  6`
  removed, regenerated; the command-spellings manifest did not move.
- [x] `python3 scripts/check_doc_links.py .`: 268 files, 0 failures.

### PR review round, PR #557

Automated external review of this PR's diff (origin/main...5ee32be2).
Reviewed 2026-09-23 by openai/gpt-5.6-sol, thinking high via codex CLI 0.156.0, read-only sandbox, runtime 8m36s, at commit 5ee32be2.
Verdict as received: **mergeable after the listed fixes**. Three
findings, all adopted.

1. **P1: the watchdog leaked a library timeout chain.**
   `reply_stream` caught the `TimeoutError` `asyncio.timeout()`
   synthesizes and raised `FirstTokenTimeout` with `raise failure from
   exc`, retaining that `TimeoutError` and the `CancelledError` behind
   it, asyncio's and the provider's frames included, and
   `test_provider_watch.py` checked only the class and the event.

   *Resolution*: accepted, in `5c5f07f3`. The arm now only records the
   second expiry; the report and the raise happen after the `try`
   statement, outside any handler and without `from`.
   `test_a_round_given_up_carries_no_chain_behind_it` asserts
   `__cause__` and `__context__` are both None. It was run against the
   `from exc` code first and failed on `__cause__`; the review's remark
   that `from None` inside the handler is not enough was measured too,
   and that variant fails the same test on `__context__`. The
   `expired()` mutation was re-run against the restructured loop and
   still fails the passthrough test. The line predates M2, which moved
   it verbatim; it is recorded as a deviation above, with what the
   chain reached, which is nothing retained, so no changelog fragment.

2. **P2: the completed milestone still recorded "PR TBD".**

   *Resolution*: accepted, in `054636f4`. The tick names PR
   [#557](https://github.com/rafacm/vinga/pull/557); the link checker
   reports 0 failures.

3. **P3: the moved `watching` docstring said a traceback is logged.**
   It said "the traceback is still logged where it was", while
   `_reply`'s generic arm logs the class name with no `exc_info`.

   *Resolution*: accepted, in `32c407cc`. The sentence now says the
   "reply failed" line is still logged, naming the class and nothing
   else, with no traceback.

After all three: `ruff check .` clean; `tests/census` 66 passed; the
targeted files (`test_provider_watch.py`, `test_provider_watch_pins.py`,
`test_session_watchdog.py`, `test_session_reply_failures.py`,
`test_event_surface_pins.py`, `test_session_filler.py`,
`test_event_baseline.py`) 76 passed; the full unit lane with `-n 4
--dist loadfile` 7,505 passed and 19 skipped (the extras not installed
here), 26m12s, one more than before the round: the new chain test.

## M1: tool execution in `runtime/tool_execution.py`

**Attribution:** anthropic/claude-opus-5-5, thinking high; Claude Code 2.1.280; 2026-09-23.

Executing one round's tool calls has its own module,
`vinga_server/runtime/tool_execution.py`: `ToolExecution` with the five
verbs the plan named (`offer`, `withheld`, `reserve`, `for_execution`,
`run`), the frozen `Offer` and `Origin` values, and
`DEFAULT_TOOL_TIMEOUT_S`. The runtime holds it privately as
`self._tools`, passes it the turn it files on at every call, and keeps
the round loop, the moves and the reply-wide withheld flag.
`runtime/pipeline.py` went from 3,517 lines to 3,053 before M1 was
stacked on M2, and from M2's 3,233 to 2,768 after; the new module is
606.

### The commits

| Commit | What it is |
| --- | --- |
| `Pin the records a round's tool calls produce` | `tests/unit/test_session_tool_events.py`, green against the code before the move |
| `Add ToolExecution, which runs one round's calls` | The module and `tests/unit/test_tool_execution.py`, nothing using it yet |
| `Ask ToolExecution, not the runtime, in tool tests` | The reach-ins in `test_session_tools.py` rewritten against the module's verbs, and the reach-in manifest regenerated |
| `Move tool execution out of PipelineRuntime` | The move as one commit, with the source prose naming `_tool_fragment`'s home |
| `Name the moved tool emit paths by their new home` | The three driver identities in `event_baseline.py` and `CARRIED` |

### Deviations from the plan

- **The reach-in rewrite landed before the move, not after it.** The
  rewritten tests need only the module, which exists from the second
  commit, so landing them third keeps every commit on the branch green;
  after the move the old reach-ins would have raised `AttributeError`
  for one commit. They were run against the pre-move runtime before
  that commit was made.
- **No interface renames.** `ToolExecution`, `Offer` and `Origin` and
  the five verbs are the plan's names. The timeout rule stays private
  as `_timeout_for`, per the review round's finding 2.
- **`owner_of` is a lambda over the runtime's field, not the
  registry's bound method.** The plan says "callables"; which callable
  turned out to matter. `test_session_withheld.py`'s
  `test_an_apply_that_moves_an_entry_mid_reply_names_the_entry_that_offered_it`
  replaces `session.runtime._mcp_servers` mid-reply to stand for an
  apply, and every read of the registry went through that field before
  the move. Measured: with a mutation that classifies a withheld
  sentence's origin at the moment it is withheld rather than at the
  offer, the test fails with the lambda (`('mcp', 'intruder') !=
  ('mcp', 'tools')`) and passes with the bound method, so the bound
  method would have taken that test's teeth out.
- **`stage_reply` and `_stage` in `llm_input_export.py` take a
  `Sequence[ToolDef]`.** `Offer.tools` is a tuple; both only iterate it.
  A one-word annotation change outside the documentation footprint.
- **Two docstrings split where the responsibility did.**
  `_report_withheld`'s first sentence ("and remember for this reply
  that one was") moved to the runtime's `_withheld`, which is now what
  sets the flag; `_run_tools`'s three paragraphs on the ordered writes
  moved to `run`, and `_run_tools` points at it. The comments in
  `_tool_loop` arguing that tools, schemas and origins must be taken on
  one line became `Offer`'s docstring. Everything else moved verbatim.
- **`_sources` is a constructor local.** Nothing but the moved methods
  read it. The `assert self._agent is not None` that `_tool_snapshot`
  began with now precedes the `offer` call in `_tool_loop`.
- **The manifest lost eight sites, not six.** The plan counted the six
  tool-method sites; the same three tests also read `_turn` twice, and
  a turn of their own replaced both. Six lines removed from
  `reach-ins.txt`, none added.

### The pins, and what they pinned

The inventory of what existing suites asserted about the moved emit
sites, at the plan's strength (channel and level, `record.msg`, typed
`record.args`, payload keys and values, timings by type):

- **The driver suite** (`test_event_baseline.py`) holds each path to
  its variant, and so to its template and its key set, for all three
  `tool_call` shapes, `tool_arguments_coerced` and all three
  `sentence_withheld` shapes. It asserts no value.
- **`test_session_tools.py`, `test_session_events.py`,
  `test_event_surface_pins.py` and `test_session_withheld.py`** assert
  individual fields (`source`, `entry`, `tool`, `error`, `characters`,
  `coerced`), the key set of one device coercion, and substrings or
  suffixes of the rendered warning line. None asserts an unrendered
  sentence or its arguments.
- **The turn record** is already pinned whole for every branch:
  `test_every_source_is_classified_and_positioned` (source, name,
  entry, arguments, malformed flag, result, error flag, duration
  presence, for builtin, device, MCP, unknown and malformed calls),
  `test_a_call_cancelled_while_it_ran_is_recorded_unexecuted` (a
  reservation left as reserved), and the refused and successful moves.
  Nothing added.
- **Attribution across a move:** `test_pair_attribution.py` pins a
  `tool_call` on the thread a `new_conversation` moved to, which holds
  the conversation half. No test held the agent half, since no tool
  event there follows a handover.

So one pin file was added, `test_session_tool_events.py`, five tests:
`tool_call` in its builtin, MCP and unnamed shapes (success and
failure), `sentence_withheld` in its builtin, MCP and unnamed shapes,
`tool_arguments_coerced` in its named shape, the unparseable-arguments
warning in all three name shapes, and every tool record after a
handover naming the tutor and the tutor's thread. It was watched
failing against a mutation naming the session's first agent in the
withheld report's thunk. It is byte-unchanged from its commit
(`git diff fab578a6 HEAD -- vinga-server/tests/unit/test_session_tool_events.py`
is empty), and `test_a_tool_exception_exports_only_its_class` is
unmodified and green.

### The falsification runs

One run each, every mutation applied to a copy-restored file and
touched after restoring.

| Mutation | Result |
| --- | --- |
| The withheld report's thunk names the session's first agent | the handover pin fails |
| `run` dispatches the concurrent half before the ordered writes | the run-order test fails |
| `run` answers in completion order | the result-order test fails |
| `offer` classifies against an empty board | the origins test fails |
| `offer` asks no registry owner | the origins test fails |
| Every owned call bounded by the module default | the separator test's rewritten tail fails, the call taking 15013 ms |
| A withheld origin classified late, with `owner_of` a lambda over the field | the MCP apply-mid-reply test fails |
| The same, with `owner_of` the registry's bound method | the same test passes, which is the finding above |

The plan's ordered-then-concurrent claim is covered by the first two
module rows; the concurrency of the concurrent half is not a new claim
and got no mutation.

### Discoveries

- **The default-timeout monkeypatch still takes effect.**
  `test_a_tool_that_never_answers_becomes_a_timeout_result` patches
  `pipeline_module.DEFAULT_TOOL_TIMEOUT_S`. The runtime imports the
  name back and reads it when it builds the sources, so the patched
  value still reaches `BuiltinTools`, which is what bounds that test's
  `remember`. The module's own fallback, for a name no source owns, is
  not reached by that test. Left unchanged.
- **The per-entry timeout test now waits one out.** Its old tail asked
  `_timeout_for` for 7.5 s, and its comment rejected waiting as "a
  seven-and-a-half second test". Through `run` it waits one second:
  the entry is configured for 1 s against the 15 s default, a stalled
  `slow_answer` comes back timed out, and its recorded duration lies
  between the two, which only the entry's bound can produce.
- **Two lanes on one Pi.** M2's full unit lane ran beside this
  milestone's targeted runs on the same compose Postgres, and
  `DROP DATABASE ... WITH (FORCE)` sat waiting on checkpoints for
  minutes, which made two short runs look hung. Each lane has its own
  databases, so nothing was shared but the disk.

### Changelog

None. No event, field, log line, stored row or timing changes, so
there is no fragment; the PR says so.

### Verification

Run on the Pi, from `vinga-server/`, after M1 was rebased onto M2
(`feature/482-m2-provider-watch`), on the rebased tree:

- `uv run ruff check .`: all checks passed.
- `uv run pytest tests/census -q -ra`: 66 passed; both manifests
  regenerated on the rebased tree and unchanged by their generators.
- The targeted files (`test_session_tools.py`,
  `test_session_tool_events.py`, `test_tool_execution.py`,
  `test_provider_watch.py`, `test_provider_watch_pins.py`,
  `test_session_recap.py`, `test_event_baseline.py`,
  `test_session_withheld.py`, `test_tts_lookahead.py`): 131 passed.
- `uv run pytest tests/unit -q -ra -n 4 --dist loadfile`: 7512 passed,
  19 skipped (the optional provider extras), in 14m37s.
- `uv run pytest tests/integration -q -ra`: 347 passed, in 10m06s.
- `uv run python ../scripts/check_doc_links.py ..`: 268 files, 0
  failures.

Before the rebase, on M1 alone and serially, the same lanes gave 7494
unit passed and 19 skipped, and 347 integration passed.
