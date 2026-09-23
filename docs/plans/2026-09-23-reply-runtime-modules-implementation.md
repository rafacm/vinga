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
