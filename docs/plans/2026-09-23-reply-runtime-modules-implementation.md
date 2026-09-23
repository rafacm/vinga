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
withheld report's thunk. It is byte-unchanged from its commit: the
file has exactly one commit in its history (`git log --oneline --
vinga-server/tests/unit/test_session_tool_events.py` lists only "Pin
the records a round's tool calls produce"), a proof that survives the
rebase merge rewriting every hash, and `test_a_tool_exception_exports_only_its_class` is
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

### PR review round, PR #558

Automated external review of this PR's diff
(origin/feature/482-m2-provider-watch...36934dba). Reviewed 2026-09-23
by openai/gpt-5.6-sol, thinking high via codex CLI 0.156.0, read-only
sandbox, runtime 13m57s, at commit 36934dba. Verdict: mergeable after
the listed fixes. Resolutions by anthropic/claude-opus-5-5, thinking
high (the orchestrating session, since both are documentation).

1. **P2: the completed milestone still records no PR number.**
   Fixed in "Name PR #558 in M1's tick": the tick links #558.
2. **P2: the byte-unchanged proof names a pre-rebase commit.** Fixed in
   "State M1's pin proof without a rewritten hash". Replacing the hash
   with the rebased one would go stale again at the rebase merge, so
   the proof is now that the pin file has exactly one commit in its
   history, which every rewrite preserves; re-confirmed on the tree
   rebased onto `main` after #557 merged.

The branch was rebased onto `main` after #557 merged, before these
fixes. The one conflict was this document: #557's review-round section
and this milestone's section both appended after M2's verification,
and both are kept, M2's round first.

## M3: the reply in flight in `runtime/reply_in_flight.py`

**Attribution:** anthropic/claude-opus-5-5, thinking high; Claude Code 2.1.280; 2026-09-23.

The two shorter of a reply's three lifetimes are values now, each made
where its lifetime begins. `ReplyInFlight` is one started reply: its
task, its first-writer-wins outcome latch and the utterance it answers,
with `start`, `running`, `latch`, `cancel`, `drain` and `__await__`.
`SpeakingPass` is one pass of the speaking loop: the round count and
the spoke/withheld pair. `PipelineRuntime` holds the current one of
each as `_in_flight` and `_pass`, and loses `_reply_task`, `_outcome`,
`_utterance`, `_llm_round`, `_reply_spoke`, `_reply_withheld` and
`_latch`. `_turn` and `_remembering` stay, for the plan's reasons.
`runtime/pipeline.py` goes from 2,768 lines at M1's tip to 2,769 (the
class docstring's new paragraph and the rewritten entries weigh what
the removed fields and comments did); the new module is 152, most of
it docstrings.

### The commits

| Commit | What it is |
| --- | --- |
| `Pin what the reply in flight says before it moves` | Four pins, green against the runtime before the move (below) |
| `Add ReplyInFlight and SpeakingPass, one per lifetime` | `runtime/reply_in_flight.py` and `tests/unit/test_reply_in_flight.py`, nothing using them yet; the mutations are in the body |
| `Move the reply in flight into its two values` | The move, the test drivers and the regenerated reach-in manifest, as one commit so every commit is green |
| `Pin that a cancel keeps a reply started under it` | The session-level test of the conditional clear, with its mutation |
| `Say where the reply's lifetimes went in the docstring` | The class docstring's inventory, and one test helper's docstring |
| `Record M3 in the implementation doc` | This section and the tick |

### The values as built

The plan's names and signatures, unchanged. What the plan left open,
decided:

- **A value that is never started.** A direct drive hands `_reply` a
  `ReplyInFlight(None)` and runs the body on its own task, so the value
  has no task. It is never `running()`, `drain` answers True at once,
  `cancel` only latches (there is nothing to cancel), and awaiting it is
  an assertion failure, since there is nothing to wait for. A direct
  drive's value is only ever latched and read, since `replying`,
  `drain` and `cancel_reply` ask `_in_flight`; the rest is defined so
  that the value has no undefined state, and the unit tests hold the
  three that answer something.
- **`start` is once per value**, asserted: a second task would be a
  reply the value could no longer cancel or wait for.
- **`start_reply` installs, then starts.** The value is made with the
  minted id, `turn_started` is emitted reading the id off it, the value
  is installed as `_in_flight`, and `reply.start(self._reply(utterance,
  reply))` creates the task, with no await between any of them, as
  before.
- **`_pass` is made in `__init__` too**, counted at nothing, where the
  three fields used to be initialized: no pass has run, and a field
  that is always present needs no guard at its readers.

`PipelineRuntime` loses six fields and one method, as the plan says,
and gains the two fields that hold the values, which the plan's text
also names; the net is four fields fewer.

### The pins, and what they pinned

The inventory the milestone asked for, per fact, of what an existing
suite held before M3:

- **The outcome each boundary latches, as `reply_finished` carries
  it.** `test_turn_lifecycle.py:182` drives six paths and asserts the
  set of words, so two sites that traded words would pass it.
  Individually pinned already: `nothing_heard` and `failed`
  (`test_turn_lifecycle.py:327` and `:695`), `device_gone` (`:512`),
  `barged_in` for the merge (`:465`), and first-writer-wins at session
  level, a failure then a barge-in reporting `failed` (`:582`). Not
  pinned: `completed` alone, the device abort's `aborted`, and the
  close, which no test drove at all. Pin added:
  `test_each_boundary_reports_the_outcome_it_latched` (`:239`), all
  seven paths, each asserted alone.
- **Round numbers across a handover.** Pinned by
  `test_session_events.py:435` (poet 1, tutor 2). That the count starts
  again at the next reply was not. Pin added:
  `test_the_next_reply_counts_its_rounds_from_one_again` (`:454`).
- **The spoke/withheld fallback both ways.** Within one reply, pinned by
  `test_session_withheld.py:151`, `:208`, `:224` and `:245`. That
  neither fact outlives its reply was not. Pins added:
  `test_a_withholding_does_not_outlive_its_reply` (`:266`) and
  `test_speech_does_not_outlive_its_reply_either` (`:283`).
- **A direct drive records `utterance` None and hands the transcript
  export no row.** `test_session_record.py:835` is a note that relies
  on it, and no test held it. Pin added:
  `test_a_reply_driven_past_the_door_answers_no_utterance` (`:948`): the
  stored record's utterance is None, the transcript collaborator is
  handed one final record answering no utterance (which
  `TranscriptExport.turn_recorded` returns on at its first line) and no
  `turn_missing`, and no `turn_started` is emitted.

Each pin was watched failing against a mutation of the runtime before
the move: removing the three resets at the top of `_speak_reply` fails
the round pin and both withheld pins; latching `barged_in` in `close()`
fails the outcome pin while the set test stays green; minting an
utterance in `_fresh_turn` fails the record pin. The four pins pass
after the move unchanged: from the commit titled "Pin what the reply
in flight says before it moves" to the branch tip, the four files it
touched receive additions only (zero removed lines), and the one
addition is the separate cancel pin in `test_turn_lifecycle.py`. The
commit is named by title rather than hash because the rebase merge
rewrites hashes. No pin adds a reach-in.

### The values' own tests, and the mutations

`tests/unit/test_reply_in_flight.py` drives both values with bodies
written for the test and no session: the latch (first writer wins),
running until the body is done, the cancel latching before the body
sees `CancelledError` (a body that reads the outcome in its `finally`),
a cancel that ends the reply as asked raising nothing, a cancel
re-raising anything else the task ended in, a cancel of an unstarted
value only latching, a drain that answers False at the grace and never
cancels (the body is released afterwards and runs to its own end), a
drain counting a failed reply as finished, and awaiting the value
re-raising the body's exception. The session-level
`test_a_reply_started_while_a_cancel_waits_stays_the_reply_in_flight`
(`test_turn_lifecycle.py:657`) is `cancel_reply`'s conditional clear.

Each claim was watched failing against a mutation first, the file
copied aside, mutated, copied back and touched after each:

| Mutation | Result |
| --- | --- |
| `latch` last writer wins | the first-outcome test fails |
| `cancel` latches after its await | the cancel-ordering test fails; 20 runs against the mutation, 20 failed; 20 runs as built, 20 passed |
| `drain` cancels at the grace | the never-cancels test fails |
| `drain` awaits the task | the failed-reply drain test fails (and the never-cancels one) |
| `__await__` swallows the body's exception | the awaiting test fails (and the failed-reply drain one) |
| `cancel` suppresses `Exception` as well | the re-raise test fails |
| `running` ignores `done()` | three tests fail |
| an unstarted `cancel` returns before latching | its test fails |
| `cancel_reply` clears `_in_flight` unconditionally, after the move | the conditional-clear test fails, 5 runs of 5; as built, 5 of 5 pass |

### The test drivers

As the plan lists them. `drive_reply` builds `ReplyInFlight(None)`
through the public constructor and calls `_reply(utterance, reply)`;
its reach-in stays one `_reply` site. `reply_in_flight` answers
`session.runtime._in_flight`, and its awaiting callers (the nine in
`event_baseline.py`, `wait_for_reply`) await the value; the identity
checks in `test_turn_lifecycle.py` and `test_session_barge_in.py` hold
unchanged. `test_session_limits.py`'s `session_with` starts a value on
a body awaiting the test's own task and installs it, and installs
nothing for the no-reply case, since the runtime starts with none.
`run_reply` and `test_tts_lookahead.py`'s `speak_a_reply` are
unchanged. The reach-in manifest moved by two lines, regenerated:
`tests/support/sessions.py  _reply_task  1` and
`tests/unit/test_session_limits.py  _reply_task  1` became the same
two paths with `_in_flight  1`. The command-spellings manifest did not
move.

`test_session_limits.py`'s failing-reply case prints "Task exception
was never retrieved" when the task is collected, as it did before the
move (checked
on a worktree at the pre-move commit): the drain deliberately does not
retrieve a failed reply's exception, and what goes unretrieved is now
the value's task rather than the test's.

### The inventories

**(a) Every caller of `start_reply`, and whether one can land during
`cancel_reply`'s await.** One caller: `TurnTaking.finish_utterance`
(`turntaking.py:314`). What precedes it, path by path, keyed on
`interrupting = self._reply.replying()` (`:288`):

- Nothing in flight (`interrupting` False): `start_reply` directly.
  Nothing awaits between the check and the start (a log line), so no
  reply can start or become in flight in between. A reply that finished
  on its own is still installed, done, and is replaced.
- In flight, `barge_in` off: the utterance is dropped, no start.
- In flight, a manual stop: `cancel_reply(BARGED_IN)` (`:307`), then
  the start.
- In flight, endpointed, through `_gate_barge_in`: under the floor or a
  failed or empty confirmation returns None and nothing starts; the
  mid-ASR merge (`:386`) and a confirmed barge-in (`:438`) cancel, then
  the caller starts. The confirmation is awaited before its cancel, so
  the reply can finish on its own meanwhile; the cancel then latches a
  word on a finished value, which reported its own outcome already and
  is replaced next, exactly as the old field was latched and cleared.

Every path that starts a reply with one in flight cancels it first, so
no path lacks a cancel. The interleaving is **not reachable in a served
session**: every `cancel_reply` caller (the three above,
`device_aborted` at `pipeline.py:929` and `close` at `:957`) and the
one `start_reply` caller run on the device session's own task, in turn.
`_serve` awaits `runtime.audio`, `listen_stopped` and `device_aborted`
one message at a time (`device/session.py:1226`, `:1259`, `:1264`),
and `close` runs in `run`'s `finally` after `_serve` has returned
(`:688`). The other tasks that reach a session (the idle watchdog and
the shutdown drain, through `request_shutdown`) call only
`runtime.drain` (`:783`), which never cancels. So the conditional clear
changes nothing a served session does; the test above constructs the
interleaving deliberately.

**(b) The shared-latch leak.** No test drives two replies directly and
reads the second's `reply_finished`. An AST scan over `tests/` found
134 call sites of `drive_reply`, `reply_with` and `_reply` in 19 files;
eleven functions call them more than once (none in a loop), and none of
the eleven reads `reply_finished` or an outcome. A second scan for a
function mixing a direct drive with anything that latches
(`start_reply`, `cancel_reply`, `device_aborted`, `close`,
`end_utterance`) found eight, none reading an outcome, and the one that
cancels a started reply and then drives directly
(`test_session_recap.py:472`) drives a different session. So no test
passed only because of the leak, and none changed.

**(c) The #489 bookkeeping.** Of the eleven files the issue lists,
**0** had a storage dependency become explicit in a signature. Three
changed: `test_turn_lifecycle.py` and `test_session_withheld.py` gained
pins and tests, `test_session_barge_in.py` one docstring line; no
signature in any of them, nor in the drivers they use, gained a
parameter, and neither value takes storage. One thing worth knowing
for #489 all the same: the new outcome pin's close path runs the
runtime's purge against the lane's memory store, as every
`runtime.close()` on a session built without a conversation store
does, so that test touches storage without saying so in any signature,
as its file already did through `session_for`.

### Deviations and discoveries

- **The move, the drivers and the census are one commit.** The brief
  ordered them as separate steps; `_reply`'s new argument breaks
  `drive_reply` and the renamed field breaks `session_with` the moment
  the move lands, and the census fails until regenerated, so apart
  they would be three red commits.
- **A direct drive after a started reply on the same session no longer
  inherits its utterance.** `_seeded_turn` carries the departing turn's
  utterance, which in every production path is the value the old field
  held. The two differ only where a test starts a reply and then drives
  the body directly on the same session: before, the drive's turns
  carried the earlier reply's id; now they carry None, as a direct
  drive's first turn always did. The scans under (b) found no test that
  does this.
- **Discovery, not fixed: a cancel swallows its caller's own
  cancellation.** `cancel` suppresses exactly `CancelledError`, as the
  plan requires and as the old `cancel_reply` did, and that includes a
  cancellation of the task awaiting it. Measured with a scratch script
  on `ReplyInFlight`: a canceller task cancelled while it waits returns
  normally and carries on (`cancelling()` stays 1), and inside
  `asyncio.timeout` the deadline is lost and the block runs past it.
  The old code has the same shape, so this is preserved behavior, not
  M3's. In a served session it is reachable in principle: the session
  cap's `asyncio.timeout` wraps `_serve`, and if it fires while `_serve`
  is waiting a barge-in's or an abort's cancelled reply out (the
  reply's `finally` settles the filler and sends the closing `tts
  stop`), the cap's cancellation is swallowed, the answering reply
  starts, and the session outlives its cap until the device closes or
  the idle timeout ends it. Reported to the PR rather than fixed: a fix
  changes the cancel contract the plan settled.
- **The gate measurement, recorded as the plan promised.** The plan
  says the M3 gate's AST script and its full output are recorded here.
  They are below, as the plan session left them; re-run at `612030fe`
  for this section, the output is byte-identical.
- **Rebased onto M1.** M3 was built on M2 alone and then rebased onto
  M1's branch, which stacks on M2. Two commits conflicted, each
  resolved by reading it. The move: the imports keep M1's three lines
  and add `reply_in_flight`'s, and the withheld flag's write, which M1
  moved from `_report_withheld` into the runtime's `_withheld`, is
  `self._pass.withheld = True` there. The docstring commit: M1's
  paragraph naming `ToolExecution` is kept with "the reply in flight"
  where it said "the reply task", the lifetimes paragraph follows it,
  the `_pass` entry names `_withheld`, and the module count reads four
  where it still read three after `ToolExecution` joined. `_tool_loop`
  merged without a conflict (M1's `self._tools.reserve(self._turn,
  calls)` beside the pass's round), the reach-in manifest auto-merged
  to exactly what a fresh render produces (the regeneration changed
  nothing), and this document keeps M2's section, then M1's, then this
  one. The four pins' patch is identical before and after.
- **Nothing else deviates.** The signatures, the utterance only
  `start_reply` mints, the body holding its value, the cancel contract,
  the conditional clear, `_turn` and `_remembering` staying, and the
  drivers are as planned.

<details>
<summary>The gate script (run against <code>pipeline.py</code> at <code>612030fe</code>)</summary>

```python
"""Measure the reply core's field and method coupling inside PipelineRuntime."""
import ast
import sys
from collections import defaultdict

SRC = sys.argv[1]
tree = ast.parse(open(SRC).read())

CORE = """_reply _record_turn _speak_reply _nothing_sayable _move_to _tool_loop _moves
_move _select _picked_up _recapped _summarized _speak_text _store_recap _resumed_seed
_recapped_seed _refuse_handover _speak_after _sentence_synthesized _speak
_speak_and_record _send_reply_audio _system_prompt _device_record _prompt_assembled
start_reply cancel_reply _latch _fresh_turn _seeded_turn _turns _memory_context
_remembering_now _resolved_memory""".split()
TOOLS = """_tool_snapshot _for_execution _run_tools _run_one _reserve_tools _classified
_dispatch _timeout_for _offered_origins _withheld _report_withheld""".split()
TOOLS_MOD = "_coercions _tool_fragment _tool_arguments_coerced _tool_called _Origin _sentence_withheld".split()
WATCH = "_watching _watched_stream _watchdog_stream _llm_round_done _provider_failed".split()
WATCH_MOD = ["FirstTokenTimeout"]

cls = next(n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == "PipelineRuntime")
methods = {m.name: m for m in cls.body if isinstance(m, (ast.FunctionDef, ast.AsyncFunctionDef))}
props = {n for n, m in methods.items()
         if any(isinstance(d, ast.Name) and d.id == "property" for d in m.decorator_list)}
module_defs = {n.name: n for n in tree.body if isinstance(n, (ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef))}

missing = [n for n in CORE + TOOLS + WATCH if n not in methods] + \
          [n for n in TOOLS_MOD + WATCH_MOD if n not in module_defs]
print("MISSING:", missing)
print("PROPERTIES:", sorted(props))

def scan(fn):
    """Return reads, writes, mutations(self.x[..]= / self.x.attr=), method refs (called or not), module-name refs."""
    reads, writes, sub_writes, refs, modrefs = set(), set(), set(), set(), set()
    for node in ast.walk(fn):
        if isinstance(node, ast.Attribute) and isinstance(node.value, ast.Name) and node.value.id == "self":
            a = node.attr
            if a in methods:
                refs.add(a)
            elif isinstance(node.ctx, (ast.Store, ast.Del)):
                writes.add(a)
            else:
                reads.add(a)
        # self.x[k] = ..., self.x.y = ..., del self.x[k]
        if isinstance(node, (ast.Subscript, ast.Attribute)) and isinstance(node.ctx, (ast.Store, ast.Del)):
            v = node.value
            if isinstance(v, ast.Attribute) and isinstance(v.value, ast.Name) and v.value.id == "self":
                sub_writes.add(v.attr)
        if isinstance(node, ast.AugAssign):
            t = node.target
            if isinstance(t, ast.Attribute) and isinstance(t.value, ast.Name) and t.value.id == "self":
                writes.add(t.attr)
        if isinstance(node, ast.Name) and node.id in module_defs:
            modrefs.add(node.id)
    return reads, writes, sub_writes, refs, modrefs

info = {n: scan(m) for n, m in methods.items()}

# fields assigned in __init__ vs elsewhere
init_writes = info["__init__"][1]
writers = defaultdict(set)
for n, (r, w, sw, refs, mr) in info.items():
    if n == "__init__":
        continue
    for a in w:
        writers[a].add(n)
mutators = defaultdict(set)
for n, (r, w, sw, refs, mr) in info.items():
    for a in sw:
        mutators[a].add(n)

def lines(names):
    return sum(methods[n].end_lineno - methods[n].lineno + 1 +
               (methods[n].lineno - min([methods[n].lineno] + [d.lineno for d in methods[n].decorator_list]))
               for n in names)

def report(label, group, groupmods=()):
    g = set(group)
    reads, writes, subw, refs, mrefs = set(), set(), set(), set(), set()
    for n in group:
        r, w, sw, rf, mr = info[n]
        reads |= r; writes |= w; subw |= sw; refs |= rf; mrefs |= mr
    fields = reads | writes
    print(f"\n===== {label}: {len(group)} methods, {lines(group)} lines =====")
    col = sorted(a for a in fields if a in init_writes and not writers.get(a))
    mut = sorted(a for a in fields if writers.get(a))
    other = sorted(a for a in fields if a not in init_writes and not writers.get(a))
    print(f"(i) collaborators set only in __init__ ({len(col)}):", col)
    print(f"(ii) reassigned outside __init__ ({len(mut)}):")
    for a in mut:
        inside = sorted(writers[a] & g); outside = sorted(writers[a] - g)
        rw = ("R" if a in reads else "") + ("W" if a in writes else "")
        print(f"    {a} [{rw} here] writers in-group={inside} outside={outside}")
    if other:
        print("(?) fields never assigned on self in class:", other)
    print(f"container/attr mutation via self.x[..]= or self.x.y= ({len(subw)}):",
          {a: sorted(mutators[a]) for a in sorted(subw)})
    outside_refs = refs - g
    tc = sorted(outside_refs & set(TOOLS)); wc = sorted(outside_refs & set(WATCH))
    cc = sorted(outside_refs & set(CORE))
    reach = sorted(outside_refs - set(TOOLS) - set(WATCH) - set(CORE))
    print(f"calls into tools cluster ({len(tc)}):", tc)
    print(f"calls into watch cluster ({len(wc)}):", wc)
    print(f"calls into reply core ({len(cc)}):", cc)
    print(f"REACH-BACK to other PipelineRuntime methods ({len(reach)}):", reach)
    print("module-level names referenced from tools/watch module sets:",
          sorted(mrefs & set(TOOLS_MOD + WATCH_MOD)))
    # per-method callers into this group
    callers = defaultdict(set)
    for n, (r, w, sw, rf, mr) in info.items():
        if n in g:
            continue
        for x in rf & g:
            callers[x].add(n)
    print("callers into this group from other PipelineRuntime methods:")
    for x in sorted(callers):
        print(f"    {x} <- {sorted(callers[x])}")
    # who touches this group's mutable state from outside
    return fields, writes

core_fields, core_writes = report("REPLY CORE", CORE)
tool_fields, _ = report("TOOLS (a)", TOOLS)
watch_fields, _ = report("WATCH (b)", WATCH)

# module-level helper users
print("\n===== module-level helpers: who references them =====")
for name in TOOLS_MOD + WATCH_MOD:
    users = sorted(n for n, i in info.items() if name in i[4])
    musers = sorted(m.name for m in tree.body if isinstance(m, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef))
                    and m.name != name and any(isinstance(x, ast.Name) and x.id == name for x in ast.walk(m)))
    print(f"  {name}: methods={users} module-level={musers}")

# Reverse: non-core methods touching core mutable state
core_mut = {a for a in core_fields if writers.get(a)}
print("\n===== REVERSE: methods outside core touching the core's mutable fields =====")
rest = [n for n in methods if n not in CORE]
for n in rest:
    r, w, sw, rf, mr = info[n]
    tr = sorted((r | w | sw) & core_mut)
    if tr:
        rw = [f"{a}({'R' if a in r else ''}{'W' if a in w else ''}{'M' if a in sw else ''})" for a in tr]
        grp = "tools" if n in TOOLS else "watch" if n in WATCH else "other"
        print(f"  [{grp}] {n}: {rw}")
print("\n===== REVERSE: shared mutable fields also read by non-core (all fields, incl. collaborators) =====")
for a in sorted(core_fields):
    outside = sorted(n for n in rest if a in (info[n][0] | info[n][1] | info[n][2]) and n != "__init__")
    if outside:
        print(f"  {a}: {outside}")
print("\n===== line counts =====")
other = [n for n in methods if n not in CORE + TOOLS + WATCH]
print("core", lines(CORE), "tools methods", lines(TOOLS), "watch methods", lines(WATCH),
      "other methods", lines(other), "(others:", len(other), ")")
def modlines(names):
    return sum(module_defs[n].end_lineno - module_defs[n].lineno + 1 for n in names)
print("tools module helpers", modlines(TOOLS_MOD), "watch module helpers", modlines(WATCH_MOD))
print("class total", cls.end_lineno - cls.lineno + 1)
print("other methods:", other)
for n in CORE + TOOLS + WATCH:
    m = methods[n]
    print(f"  {n} {m.lineno}-{m.end_lineno}")
```

</details>

<details>
<summary>Its full output</summary>

```text
MISSING: []
PROPERTIES: ['_agent', '_conversation', '_device', '_turns']

===== REPLY CORE: 34 methods, 1611 lines =====
(i) collaborators set only in __init__ (15): ['_agents', '_attached', '_devices', '_events', '_filing', '_filler', '_llm_input', '_memory', '_output', '_recorder', '_resumption', '_transcripts', '_turntaking', 'conversations', 'session_id']
(ii) reassigned outside __init__ (11):
    _asr_language [RW here] writers in-group=['_reply'] outside=[]
    _know_how [R here] writers in-group=[] outside=['_activate_agent']
    _llm_round [W here] writers in-group=['_speak_reply', '_tool_loop'] outside=[]
    _outcome [RW here] writers in-group=['_latch', 'start_reply'] outside=[]
    _providers [R here] writers in-group=[] outside=['_activate_agent']
    _remembering [RW here] writers in-group=['_tool_loop'] outside=[]
    _reply_spoke [RW here] writers in-group=['_speak_reply'] outside=[]
    _reply_task [RW here] writers in-group=['cancel_reply', 'start_reply'] outside=[]
    _reply_withheld [RW here] writers in-group=['_speak_reply'] outside=['_report_withheld']
    _turn [RW here] writers in-group=['_reply', '_speak_reply'] outside=[]
    _utterance [RW here] writers in-group=['start_reply'] outside=[]
container/attr mutation via self.x[..]= or self.x.y= (1): {'_turn': ['_reply']}
calls into tools cluster (6): ['_for_execution', '_offered_origins', '_reserve_tools', '_run_tools', '_tool_snapshot', '_withheld']
calls into watch cluster (5): ['_llm_round_done', '_provider_failed', '_watchdog_stream', '_watched_stream', '_watching']
calls into reply core (0): []
REACH-BACK to other PipelineRuntime methods (5): ['_activate_agent', '_agent', '_conversation', '_device', '_world_of']
module-level names referenced from tools/watch module sets: []
callers into this group from other PipelineRuntime methods:
    _fresh_turn <- ['__init__']
    _memory_context <- ['__init__']
    _move <- ['_run_tools']
    _moves <- ['_run_tools']
    _prompt_assembled <- ['_activate_agent']
    _remembering_now <- ['__init__', '_dispatch']
    cancel_reply <- ['close', 'device_aborted']

===== TOOLS (a): 11 methods, 375 lines =====
(i) collaborators set only in __init__ (5): ['_events', '_mcp_servers', '_output', '_sources', 'session_id']
(ii) reassigned outside __init__ (2):
    _reply_withheld [W here] writers in-group=['_report_withheld'] outside=['_speak_reply']
    _turn [R here] writers in-group=[] outside=['_reply', '_speak_reply']
container/attr mutation via self.x[..]= or self.x.y= (0): {}
calls into tools cluster (0): []
calls into watch cluster (0): []
calls into reply core (3): ['_move', '_moves', '_remembering_now']
REACH-BACK to other PipelineRuntime methods (2): ['_agent', '_conversation']
module-level names referenced from tools/watch module sets: ['_Origin', '_coercions', '_sentence_withheld', '_tool_arguments_coerced', '_tool_called', '_tool_fragment']
callers into this group from other PipelineRuntime methods:
    _for_execution <- ['_tool_loop']
    _offered_origins <- ['_tool_loop']
    _reserve_tools <- ['_tool_loop']
    _run_tools <- ['_tool_loop']
    _tool_snapshot <- ['_tool_loop']
    _withheld <- ['_tool_loop']

===== WATCH (b): 5 methods, 271 lines =====
(i) collaborators set only in __init__ (3): ['_events', '_llm_input', '_server']
(ii) reassigned outside __init__ (2):
    _llm_round [R here] writers in-group=[] outside=['_speak_reply', '_tool_loop']
    _turn [R here] writers in-group=[] outside=['_reply', '_speak_reply']
container/attr mutation via self.x[..]= or self.x.y= (0): {}
calls into tools cluster (0): []
calls into watch cluster (0): []
calls into reply core (0): []
REACH-BACK to other PipelineRuntime methods (2): ['_agent', '_conversation']
module-level names referenced from tools/watch module sets: ['FirstTokenTimeout']
callers into this group from other PipelineRuntime methods:
    _llm_round_done <- ['_summarized', '_tool_loop']
    _provider_failed <- ['_speak_after', '_summarized']
    _watchdog_stream <- ['_tool_loop']
    _watched_stream <- ['_summarized']
    _watching <- ['_reply', 'confirm_transcript']

===== module-level helpers: who references them =====
  _coercions: methods=['_for_execution'] module-level=['PipelineRuntime']
  _tool_fragment: methods=['_dispatch'] module-level=['PipelineRuntime']
  _tool_arguments_coerced: methods=['_for_execution'] module-level=['PipelineRuntime']
  _tool_called: methods=['_run_one'] module-level=['PipelineRuntime']
  _Origin: methods=['_offered_origins', '_report_withheld', '_withheld'] module-level=['PipelineRuntime']
  _sentence_withheld: methods=['_report_withheld'] module-level=['PipelineRuntime']
  FirstTokenTimeout: methods=['_watchdog_stream'] module-level=['PipelineRuntime']

===== REVERSE: methods outside core touching the core's mutable fields =====
  [other] __init__: ['_asr_language(W)', '_know_how(W)', '_llm_round(W)', '_outcome(W)', '_providers(W)', '_remembering(W)', '_reply_spoke(W)', '_reply_task(W)', '_reply_withheld(W)', '_turn(W)', '_utterance(W)']
  [other] replying: ['_reply_task(R)']
  [other] drain: ['_reply_task(R)']
  [watch] _watchdog_stream: ['_llm_round(R)']
  [watch] _llm_round_done: ['_llm_round(R)', '_turn(R)']
  [other] _activate_agent: ['_know_how(RW)', '_providers(RW)']
  [tools] _for_execution: ['_turn(R)']
  [tools] _run_tools: ['_turn(R)']
  [tools] _run_one: ['_turn(R)']
  [tools] _reserve_tools: ['_turn(R)']
  [tools] _report_withheld: ['_reply_withheld(W)']
  [other] confirm_transcript: ['_asr_language(R)', '_providers(R)']

===== REVERSE: shared mutable fields also read by non-core (all fields, incl. collaborators) =====
  _agents: ['_activate_agent']
  _asr_language: ['confirm_transcript']
  _events: ['_for_execution', '_llm_round_done', '_provider_failed', '_report_withheld', '_run_one', '_watchdog_stream']
  _know_how: ['_activate_agent']
  _llm_input: ['_llm_round_done', '_provider_failed']
  _llm_round: ['_llm_round_done', '_watchdog_stream']
  _output: ['_classified', '_offered_origins']
  _providers: ['_activate_agent', 'confirm_transcript']
  _reply_task: ['drain', 'replying']
  _reply_withheld: ['_report_withheld']
  _turn: ['_for_execution', '_llm_round_done', '_reserve_tools', '_run_one', '_run_tools']
  _turntaking: ['_activate_agent', 'audio', 'device_aborted', 'listen_started', 'listen_stopped']
  conversations: ['_activate_agent', '_agent', '_conversation', '_device', 'close']
  session_id: ['_dispatch', 'device_aborted']

===== line counts =====
core 1611 tools methods 375 watch methods 271 other methods 445 (others: 14 )
tools module helpers 130 watch module helpers 6
class total 2860
other methods: ['__init__', '_agent', '_conversation', '_device', '_world_of', 'audio', 'listen_started', 'listen_stopped', 'device_aborted', 'replying', 'drain', 'close', '_activate_agent', 'confirm_transcript']
  _reply 1480-1845
  _record_turn 1847-1890
  _speak_reply 1892-1989
  _nothing_sayable 1991-2028
  _move_to 2030-2079
  _tool_loop 2081-2255
  _moves 2399-2415
  _move 2417-2446
  _select 2448-2494
  _picked_up 2496-2527
  _recapped 2529-2569
  _summarized 2571-2664
  _speak_text 2666-2701
  _store_recap 2703-2751
  _resumed_seed 2753-2767
  _recapped_seed 2769-2780
  _refuse_handover 2782-2818
  _speak_after 3150-3178
  _sentence_synthesized 3180-3218
  _speak 3220-3268
  _speak_and_record 3270-3283
  _send_reply_audio 1106-1119
  _system_prompt 2977-3040
  _device_record 3042-3061
  _prompt_assembled 1453-1478
  start_reply 3285-3327
  cancel_reply 3329-3347
  _latch 3349-3358
  _fresh_turn 987-1006
  _seeded_turn 1008-1024
  _turns 975-985
  _memory_context 943-972
  _remembering_now 899-917
  _resolved_memory 919-923
  _tool_snapshot 2257-2274
  _for_execution 2276-2314
  _run_tools 2316-2397
  _run_one 2820-2874
  _reserve_tools 2876-2882
  _classified 2884-2908
  _dispatch 2910-2960
  _timeout_for 2962-2975
  _offered_origins 3063-3094
  _withheld 3096-3115
  _report_withheld 3117-3148
  _watching 1122-1141
  _watched_stream 1143-1176
  _watchdog_stream 1178-1270
  _llm_round_done 1272-1344
  _provider_failed 1346-1395
```

</details>

### Documentation footprint

No page under `docs/`, as planned. The runtime's own prose moved with
the code: the class docstring's opening paragraphs and inventory, and
the docstrings of `_fresh_turn`, `_seeded_turn`, `_reply`,
`_speak_reply`, `drain`, `start_reply` and `cancel_reply`. In the
tests: the notes on `reply_in_flight` and `drive_reply` in
`tests/support/sessions.py`, `session_with`'s comment in
`test_session_limits.py`, and one helper docstring in
`test_session_barge_in.py`. "The reply task" stays in the prose that
means the task itself, which still exists and is the value's.

**Changelog:** none. No event, field, log line, stored row, spoken
sentence or timing bound changed, so no `changelog.d/` fragment.

### Verification

Run on the tree after the rebase onto M1, at the commit titled "Say
where the reply's lifetimes went in the docstring" plus this section,
on this machine:

- [x] `uv run ruff check .`: all checks passed.
- [x] `uv run pytest tests/unit -q -ra -n 4 --dist loadfile`: 7,530
  passed, 19 skipped (the faster-whisper and piper extras, not
  installed here), 25m26s. Before the rebase, on M2 alone: 7,522
  passed, 19 skipped.
- [x] `uv run pytest tests/integration -q -ra`: 347 passed, 9m09s.
- [x] `uv run pytest tests/census -q`: 66 passed. The reach-in manifest
  moved by two lines (above), regenerated; the command-spellings
  manifest did not move.
- [x] `python3 scripts/check_doc_links.py .`: 268 files, 0 failures.

### PR review round, PR #560

Automated external review of this PR's diff
(origin/feature/482-m1-tool-execution...28c2291c). Reviewed 2026-09-23
by openai/gpt-5.6-sol, thinking high via codex CLI 0.156.0, read-only
sandbox, runtime 7m55s, at commit 28c2291c. Verdict: mergeable after
the listed fix.
Resolutions by anthropic/claude-opus-5-5, thinking high (the
orchestrating session, since both are documentation).

1. **P2: the completed milestone still names `PR TBD`.** Fixed in
   "Name PR #560 in M3's tick".

One more fix, not a finding of this round: PR #558's round found M1's
section proving its pins against a pre-rebase hash, and this section
did the same twice. Fixed in "State M3's pin proof without a rewritten
hash", which names the pin commit by title and proves it by the pin
files receiving additions only since.

The branch was rebased onto M1 after M1 was rebased onto `main` (#557
merged). The one conflict was this document, where M1's review round
and this section both append; both are kept, M1's round first.
