# Tool exchanges stay in the history an agent is sent: implementation

Companion to
[`2026-10-03-tool-exchanges-in-history.md`](2026-10-03-tool-exchanges-in-history.md),
one section per milestone, appended in the same change that ticks the
milestone checklist. It records deviations from the plan, resolutions
of the plan's open questions, and discoveries.

## M1: keep completed tool rounds in history

**Attribution:** anthropic/claude-opus-5-5, thinking high; Claude Code 2.1.288; 2026-10-03.

### What landed

| Decision | Where | Commit |
| --- | --- | --- |
| D1, D4, D5, D6 and decision 2: the module, the cap, the notes, the ids; D7's two `ToolCall` fields | `runtime/history.py` (`kept_round`, `as_sent`, `Sent`, `Cleared`, `Pair`, `note_cost`, `canonical_arguments`, `MAX_KEPT_RESULT_BYTES`), `providers/base.py` (`ToolCall.source`, `.entry`), `tests/unit/test_runtime_history.py` | `Add the module that owns history's tool shape` |
| Round 3: Anthropic roles alternate after a tool-only reply | `providers/anthropic_llm.py` (`anthropic_messages`), `tests/unit/test_providers_llm_tools.py` | `Join consecutive user turns for Anthropic` |
| D2, D3 and decision 1: the per-round commit, the per-request `as_sent`, speech after the last kept round | `runtime/pipeline.py` (`_tool_loop`, `_run_tools`, `_keep_round`, `_keep_speech`, module docstring), `runtime/reply_in_flight.py` (`SpeakingPass.kept`), `providers/base.py` (`Turn` docstring), `providers/mock.py`, `tests/support/sessions.py`, `tests/support/providers.py`, `tests/unit/test_session_kept_tools.py`, the rewritten pinning test and four adjusted tests | `Keep each round's answered calls in the history` |
| The export stages the as-sent turns | `tests/unit/test_session_llm_input.py` (the code is the previous commit's) | `Pin that the export stages the history as sent` |
| The round's own sentence list, which the change left unread | `runtime/pipeline.py` (`_speak_after`, `_speak`, `_speak_and_record` removed) | `Drop the round's unread sentence list` |
| Documentation footprint | `docs/concepts.md`, `changelog.d/599-tool-exchanges-in-history.md` | this section's commit |

### Amendments from review rounds 2 and 3

Both arrived by message while the milestone was in flight, and both
win over the plan text this worktree was cut with (`70a28858`).
Round 2 arrived after `runtime/history.py` was drafted against the
round-1 text and before anything was committed, so no corrective
commit was needed; round 3 arrived before the pipeline commit.

1. **D5: degrade only before `start`.** Calls of the reply being
   answered go back structured, invented names included, so the round
   after an invented name continues from a structured call and its
   error result exactly as before #599. The offer stays the per-leg
   snapshot. Pinned by
   `test_this_replys_calls_stay_structured_whatever_the_offer` and
   `test_an_invented_name_is_structured_in_its_reply_and_degraded_after`;
   the two existing tests about an unknown tool
   (`test_an_unknown_tool_comes_back_as_an_error_result`,
   `test_a_whitespace_delta_is_not_a_tool_call`) pass unmodified.
2. **D2: the unit is the answered pair.** `_keep_round` runs in a
   `finally` around `_run_tools`, synchronously, and keeps every call
   whose result is on the turn's record (`TurnUnderway.reserved(slot)`),
   so a round cut part-way keeps its answered calls and not the rest.
   Nothing reads `_run_tools`'s results any more, so it now answers
   only the transition, and the refused moves' results come off the
   record the same way. The plan's "a barge-in mid-execution leaves no
   call of that round" expectation is gone; the test that replaced it
   cuts a round after `remember` (ordered, so it runs first and alone)
   answered and while a board call hangs, and asserts the next reply
   carries `remember` and not the board call.
3. **Malformed calls are kept** with `arguments={}` and no
   `malformed_arguments`, beside their error result: what the store
   holds. `kept_round` does the conversion, so the raw bytes go no
   further than the round that streamed them.
4. **D1: `kept_round(history, preamble, pairs)`**, a pair being
   `Pair(call, result, source, entry)`. Completion is the caller's; the
   module has no move vocabulary.
5. **Round 3: `anthropic_messages` joins a user turn onto a preceding
   user message** as a text block, converting a plain-string message
   first, so a tool-only failed or cut reply followed by an utterance
   (a shape D3 now leaves in history) alternates. `chat_messages` is
   unchanged. This means the plan's "the adapters do not change" and
   "`Turn` and the adapters are untouched apart from the docstring"
   no longer hold for the Anthropic translator.

### Deviations from the plan

Beyond the amendments above:

- **`_speak_and_record` is gone, and with it the round's `leg` list.**
  The tool loop kept `leg` only to build the asking turn's preamble,
  which is now `spoken[kept:]` (everything heard since the last kept
  round, so a preamble of a round that kept nothing joins the next
  one, D3). Left in place it would have been a list written per
  sentence and never read. `_speak` now appends to the reply's
  `spoken` directly, still only once the audio is out; the nine test
  stubs of `_speak` needed no change, since they append to the list
  they are handed. Its own commit, so review can drop it alone.
- **The degraded note escapes U+0085, U+2028 and U+2029 as well.**
  `json.dumps(..., ensure_ascii=False)` leaves them raw, and each is a
  line break to `str.splitlines` and to some renderers; escaping them
  keeps the JSON valid and the note one line. The adversarial test
  plants U+2028 beside `\n`, `)` and `"}` and asserts
  `len(content.splitlines()) == 1` through both translators.
- **The mock LLM reads only the current reply's results**
  (`providers/mock.py`, the results after the last user turn). It took
  any tool result anywhere in the turns as its second beat, so with
  results kept every later utterance went to `_then` and spoke without
  calling; `test_the_turns_and_their_tool_calls_land_with_their_numbers`
  (two utterances, each meant to call `remember`) caught it. Not in the
  plan's footprint; it is the integration lane's model.
- **`results_of` and `errors_of` count each result once**
  (`tests/support/providers.py`): the results a round was handed back,
  which are its request's last turn when that is a tool turn. Reading
  every turn of every request counted an earlier reply's results again
  per later request; three tests in `test_session_conversations.py`
  failed on it. The device-swap suite's own `said` now reads
  `results_of`.
- **Tests changed on purpose**, beyond the pinning test: two
  forget-then-restore tests in `test_session_tools.py` read the last
  request rather than every request, and the lookahead test's
  `_run_tools` stub returns the new shape.
- **A degraded note joins its turn's preamble with a space**, the
  plan saying only "followed by".
- **`Sent` already carries M2's facts**: `cleared` (name, source,
  entry and original size per cleared result, with `cleared_bytes` and
  `cleared_largest`), `degraded`, and `refetchable`, the canonical
  `(name, arguments)` keys. They are pinned in the module tests;
  nothing emits them, and `llm_round.turns`, which now counts earlier
  replies' tool turns too, keeps its catalog note for M2 to amend.
- **Test placement.** The plan's session tests are in a new
  `tests/unit/test_session_kept_tools.py` beside the tool-loop suite,
  reusing its harness; the pinning test is rewritten in place in
  `test_session_tools.py`. One new white-box reach, the board's tool
  client (`session._device_tools`), follows the tool-loop suite's
  existing one for the reason it states, in two new tests.

### Discoveries

- The cap off by one survives every session test, because they drive
  3 KiB, and is killed by the module's 2048/2049 test. The commit with
  the `finally` removed is killed by the mid-round barge-in test alone:
  the barge-in before speech cuts the reply after round 1 committed
  normally, so it does not reach the cancellation path. Both drivers
  reach their conditions; neither is a weak assertion.
- `test_a_whitespace_delta_is_not_a_tool_call` and
  `test_an_unknown_tool_comes_back_as_an_error_result` would have
  changed under the round-1 D5 (degrading this reply's invented names);
  under round 2 they are unmodified.

### Inventories

Untruncated `grep`/`git grep`, counted.

- `Turn("assistant", said)` in `runtime/pipeline.py`: 2 at `677fd921`
  (L1476, the reply's end; L1607, the leg's end), 0 now. Both are
  `self._keep_speech(spoken)`, the method's only callers besides the
  `run_reply` test helper.
- `results_of(` / `errors_of(`: 32 lines in 4 files
  (`tests/support/providers.py`, `test_session_conversations.py`,
  `test_session_device_swap.py`, `test_session_recap.py`), all reading
  the new once-per-result semantics.
- Reads that still flatten every turn of every request
  (`for turns, _, _ in ...seen`): 30 lines in 8 files, each over a
  single reply, where each result appears once; the unit lane is green
  over all of them.

### Tests and mutations

Every new session test was watched failing first against the
text-only pipeline: the ten in `test_session_kept_tools.py` and the
rewritten pinning test, 11 of 11, and again 10 of 10 in a scratch
worktree at `3e9668fb` (module present, pipeline unchanged) with the
final file. The export test failed there too, on the cleared note.
The two Anthropic translator tests failed against the old translator.
The module tests were checked by mutation.

| Mutation | Outcome |
| --- | --- |
| The cap off by one (`>=` for `>`) | killed, 1 (the module's 2048/2049 test) |
| `start` ignored: the request built as if this reply were past | killed, 5 |
| Degrade skipped | killed, 8 |
| Ids not re-minted | killed, 6 |
| Commit only at the reply's end (a staged copy written back on a normal return) | killed, 3: the failed round and both barge-ins |
| No commit on cancellation (`finally` removed) | killed, 1: the mid-round barge-in |
| The speech mark never set | killed, 2 |
| Malformed calls keep their raw arguments | killed, 2 |
| The export stages the raw history | killed, 1 |
| The Anthropic join disabled | killed, 3 |

No mutation survived.

### Verification

All on agentpi, from `vinga-server/`, at `1b899823` (the code as
committed; this section's commit changes only prose):

- `uv run ruff check .`: clean. `uv run mypy` (the events package):
  no issues in 5 source files.
- `uv run pytest tests/unit -q -n auto --dist loadfile`: 7935 passed,
  19 skipped in 866.31s. An earlier run, before the four on-purpose
  test adjustments and the mock fix, failed six tests; each is named in
  the deviations above.
- `uv run pytest tests/integration -q -n auto --dist loadfile`: 350
  passed in 240.85s, which is the mock LLM's change exercised end to
  end.
- The seven generated-document drift checks CI's `integration` job
  runs (domain, server, conversations, metrics views, events, OpenAPI,
  CLI): none drifted.
- `scripts/check_doc_links.py`: 295 files, 0 failures;
  `scripts/fold_changelog.py check`: 1 fragment, 0 failures.
- `uv run pytest tests/census -q`: run last, after this section; its
  outcome is in the hand-back rather than here.

Not verified locally: the image build and its smoke conversation (CI's
`image` job), and any live provider. The Anthropic shape (two user
messages after a tool-only reply, and the joined form) is pinned
through the real translator but was not sent to the Anthropic API: no
key on this machine, as in Step 0.

### PR review round 1

Reviewed 2026-10-03 by openai/gpt-6-sol, thinking high via codex CLI 0.160.0, read-only sandbox, runtime 7m34s, at commit d3ca5e11.

Three P2 findings, all accepted, each fixed in its own commit with its
test watched failing first.

1. **P2: `note_cost` undercounted non-ASCII arguments.** It priced the
   degraded note as sent, which keeps non-ASCII text raw, while the
   OpenAI translator escapes each such character in a structured
   call's arguments to six characters (twelve outside the BMP): 294
   against 609 for 100 CJK characters, so M3's budget could be
   exceeded. *Resolution:* `bcbfc811`. `note_cost` measures the note
   serialized with ASCII escaping, which holds the arguments in exactly
   OpenAI's form and the name and result at least as long as any wire
   form. Signature unchanged; the value is unchanged for ASCII-only
   calls and larger otherwise. The test prices CJK, emoji and mixed
   text against both translators' renderings and the degraded note
   (2 of 3 cases failed before).
2. **P2: a lone surrogate in a device result broke every later reply.**
   JSON accepts an escaped `\ud800`, the device channel keeps it, and
   `as_sent` raised `UnicodeEncodeError` measuring it. *Resolution:*
   `57f6e261`. `kept_round` stores a result in the new public
   `countable` form (lone surrogates to U+FFFD, split pairs joined),
   and every size the module takes is of that form, so a raw string
   from elsewhere is measured rather than raised on. Tests: a device
   result through a real session to the next reply's request, and a
   module test. Mutations: retention unnormalized (killed, 2), size of
   the raw text (killed, 1), pairs not joined (killed, 1).
3. **P2: `docs/concepts.md` claimed conversation-long persistence.**
   A resumed conversation does not rebuild its exchanges until M3.
   *Resolution:* `796f71f1`. The bullet says the exchanges last as long
   as the session and marks the rebuild as decided direction.

Lanes after the fixes, on agentpi at `796f71f1`, both `-n auto --dist
loadfile`: ruff clean; unit 7940 passed, 19 skipped in 906.84s; integration 350
passed in 972.29s (four times the earlier run's 240.85s, on a machine
running M3's lanes beside it); the seven drift checks clean; doc links
295 files, 0 failures. The census lane ran last, after this
subsection.

### PR review round 2

Reviewed 2026-10-03 by openai/gpt-5.6-terra, thinking high via codex CLI 0.160.0, read-only sandbox, runtime 3m51s, at commit c6e60ace.

1. **P2: a lone surrogate in a kept call's own strings still broke a
   later degraded request.** Round 1 normalized only the result; a
   call's name, argument keys and argument values were kept verbatim,
   and once the call was no longer offered the degraded note put them
   into the assistant's text with `ensure_ascii=False`, which cannot be
   encoded as UTF-8. *Resolution:* `c73e660f`. `kept_round` stores the
   name and every key and string value of the arguments, recursively
   through mappings, lists and tuples, in the `countable` form. The
   session test (an invented name, a top-level key and value, a nested
   list item and a nested key, each holding `\ud800`) failed first with
   `UnicodeEncodeError`; the next reply now proceeds and every turn of
   its request encodes. Mutation: normalizing the top level only
   killed, that test fails.

Lanes after the fix, on agentpi at `c73e660f`, `-n auto --dist
loadfile`: ruff clean; the `history or kept_tools or session_tools`
selection 91 passed in 85.98s; the full unit lane 7941 passed, 19 skipped in
2686.38s (three times the round 1 run, on a machine running M3's lanes
beside it). The
census lane ran last, after this subsection.
