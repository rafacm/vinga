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

## M3: rebuild exchanges on resume

**Attribution:** anthropic/claude-opus-5-5, thinking high; Claude Code 2.1.288; 2026-10-03.

### What landed

| Decision | Where | Commit |
| --- | --- | --- |
| Decision 4, D9, Q4: `StoredCall`, the widened read, rounds rebuilt under the budget, `TOOL_NOTE` retired | `conversations/records.py` (`StoredCall`, `StoredTurn.calls`), `conversations/threads.py` (`backlog`), `conversations/hydration.py`, `tests/unit/test_conversations_hydration.py`, `tests/unit/test_conversations_threads.py` | `Rebuild a resumed thread's tool rounds` |
| Q3: the recap sent through `as_sent` | `runtime/pipeline.py` (`_summarized`), `tests/support/stores.py` (`a_backlog(calls=...)`), `tests/unit/test_session_recap.py` | `Send the recap its thread's exchanges as notes` |
| The issue's third criterion, the cut-then-resume comparison, the rebuilt shape through the Anthropic translator | `tests/unit/test_session_kept_tools.py` | `Pin a resumed thread's first request` |
| Q4's price against M1's reviewed `note_cost`, and `countable` results | `conversations/hydration.py` (`_cost`), `tests/unit/test_conversations_hydration.py` | `Charge each rebuilt call its note bound and join` |
| Anthropic roles alternate after a degraded round (the discovery below, fixed) | `providers/anthropic_llm.py` (`anthropic_messages`), `tests/unit/test_providers_llm_tools.py`, `tests/unit/test_session_kept_tools.py` | `Join consecutive assistant turns for Anthropic` |
| Documentation footprint | `docs/concepts.md` (the "Resuming elsewhere" bullet, and the tool-exchanges bullet M1's review scoped to the session widened back), `changelog.d/599-tool-exchanges-on-resume.md` (its own fragment: M1's was folded into `CHANGELOG.md` when PR #600 merged, so the rebase onto `main` moved M3's entries, and the assistant-join entry that had amended M1's Anthropic bullet, into a new fragment rather than editing the folded text) | this section's commit |

The branch was cut from M1's head before its review (`81cfca37`),
rebased onto the head after its first review round (`c6e60ace`) once
that round's fixes landed, and again onto M1's final head (`1f90cce7`,
which added `Keep a call's own strings as encodable text`); the second
rebase conflicted only where both sides appended, in
`test_session_kept_tools.py` and in this document, and both were
resolved by keeping both sides. At the first rebase: `note_cost` became an ASCII-escaped bound and `kept_round`
began storing results in their `countable` form. The rebase dropped
one commit of this branch (`Retire note_cost for the as-sent unit
price`, which removed `note_cost` before it changed), resolved one
textual conflict by keeping both sides (M1's lone-surrogate session
test and this milestone's resume section, both appended to
`test_session_kept_tools.py`), and added the pricing commit above.

The conversations-schema reference was not regenerated: no generator
text describes what hydration reads (the `tool_invocations` rows say
what each column holds, not who reads it), and its drift check is
clean.

### Deviations from the plan

- **Each call is charged `note_cost` plus one character.** Q4 names
  `note_cost(call, result)` summed per call. That misses what joins a
  note to its turn: `as_sent` puts a space between a turn's text and
  each degraded note, so a round of two calls is one character longer
  than its two notes (measured: 389 against 388). Small, but it breaks
  the property the price exists for, that a unit which fit is never
  exceeded by the form a later request sends. Each kept call is
  charged `note_cost(call, result) + len(" ")`, the space named once in
  hydration (`_NOTE_JOIN`) beside what it is for. Before the rebase this
  branch priced a whole unit as `as_sent` sends it with nothing offered,
  and removed `note_cost` as unused; M1's review then made `note_cost`
  count non-ASCII escaped, which the raw as-sent text does not, so that
  form stopped being the largest and `note_cost` became the right
  primitive again.
- **No second `countable` in hydration.** The brief's amendment asked
  for rebuilt result text to go through `countable`. It does, by
  `kept_round`, which places every rebuilt round; an explicit call in
  hydration's own row conversion was added, survived the mutation that
  removed it, and was therefore not kept. The lone-surrogate hydration
  test kills the mutation that removes `countable` from `kept_round`.
- **The store-writer test is in the unit lane.** The plan calls the
  two-rounds-of-two-calls test "integration, against Postgres". It is
  `test_the_backlog_reads_every_call_in_the_order_it_was_written` in
  `tests/unit/test_conversations_threads.py`, beside the backlog test
  it replaces, because that is where this repository drives the real
  writer against Postgres: the unit lane provisions a database per
  worker, and `tests/integration` boots whole deployments. It writes
  through `ConversationStore.record_turn` and reads with
  `threads.backlog`, which is the path the plan asks for. The
  cut-then-resume test does the same round trip from a session's own
  records.
- **The recap's clearing facts are M2's.** `HistorySent` does not
  exist on this base (M1's reviewed head, `c6e60ace`), so `_summarized` builds the `Sent`
  and uses only its turns; handing its accounting to the recap's
  `watched` call, and the test that `llm_recap` carries the clearing
  facts, land with whichever of M2 and M3 merges second, as the plan
  says. The recap test here asserts the request: no tools, every call
  degraded, a 3000-byte result cleared inside its note.
- **The hydration docstring's alternation rule is restated.** "What
  comes out alternates" no longer holds of the output once a round is
  a tool turn: a reply cut before it spoke leaves a tool turn followed
  by the next user turn, in the session and on resume alike. The rule
  is now that the output opens with the user and an assistant turn
  never follows another one; a turn that kept an exchange and spoke
  nothing is a unit ending on its tool turn rather than a hole (before
  M3 it was a unit too, carried by its tool note). The "Content is what
  was said and that tools ran" rule is gone, replaced by the rebuild
  rule.
- **A joined answer after a tool-only turn** follows that turn's tool
  turn as a plain assistant turn; only an assistant text directly in
  front of another assistant turn is folded into it (D9's newline
  join), which covers both two answers and an answer before a joined
  turn's round.
- **The Anthropic translator joins consecutive assistant turns.** The
  plan says adjacent plain assistant turns are not merged (D6), and the
  history still keeps them apart; only `anthropic_messages` joins them,
  the way M1 (D3) joins user turns. An assistant turn after a plain
  assistant message is appended to it as a text block; one that asks
  for tools takes that message's text as its leading blocks, before
  its own preamble and its `tool_use` blocks. An assistant message
  that asks for tools is never followed by another assistant turn,
  because `as_sent` drops a tool turn only where no structured call is
  left in the turn before it; the translator relies on that rather
  than handling it, and the new translator test asserts it over
  `as_sent`'s output. OpenAI's translation is unchanged, and pinned so
  in the same test. Commit `Join consecutive assistant turns for
  Anthropic`; the changelog's Anthropic bullet says assistant turns
  join too.
- **The M1 changelog entry's "a resumed conversation does not rebuild
  its exchanges yet" is removed**, and the M3 entry is a new bullet
  under `### Changed` in the same fragment.

### Discoveries

- **A degraded past round followed by its reply is two assistant turns
  in a row, and M1's Anthropic translator sent them as two assistant
  messages.** D6 leaves adjacent plain assistant turns unmerged in the
  history, and M1's translator rule joined only user turns. It is not
  new in M3: a session whose MCP reload removed a tool between replies
  sends the same shape after M1. What M3 changed is reach, since every
  resume of a thread whose tool is gone produces it. The first version
  of the resumed-request test asserted the shape as D6's; on the
  orchestrator's instruction it is now fixed in M3, in its own commit
  (see the deviation below), and the test asserts alternating roles.
- The unanswered device call in the cut-then-resume test reaches the
  hydrator as a row with a null result and is dropped there, not in
  SQL; with the result filter mutated away and an empty result
  tolerated, it comes back as a degraded note in the resumed request,
  which is what makes the comparison with the session's own next
  request fail. The driver reaches the condition.

### Inventories

Untruncated `git grep`, written to a file and counted.

`git grep -n '\.tools\b' -- vinga-server` at `81cfca37`: 213 lines,
byte-identical at M1's reviewed head `c6e60ace`; at this milestone's
code: 210. Compared by content with line numbers
stripped, exactly three lines are gone and none were added, and those
three are every reader `StoredTurn.tools` had:

- `vinga-server/src/vinga_server/conversations/hydration.py:219` and
  `:220` (`_assistant`, the tool note);
- `vinga-server/tests/unit/test_conversations_threads.py:496` (the
  backlog test, rewritten).

The other 210 are module paths (`vinga_server.tools`, `tests.tools`),
`TurnRecord.tools` (the writer and the record suites), an `Offer`'s,
a published listing's or a grant's `tools`, a config entry's, and the
attribute name `vinga.llm.tools`. The full output at `c6e60ace`:

<details>
<summary>213 lines</summary>

```text
vinga-server/README.md:2808:`gen_ai.output.messages`, `vinga.llm.tools` and `vinga.llm.tool_choice`.
vinga-server/src/vinga_server/app.py:64:from vinga_server.tools.mcp import McpConfigError, McpServers
vinga-server/src/vinga_server/composition.py:37:from vinga_server.tools.mcp import McpServers
vinga-server/src/vinga_server/config/models.py:56:from vinga_server.tools import names
vinga-server/src/vinga_server/config/models.py:3323:    if entry.tools is not None:
vinga-server/src/vinga_server/config/models.py:3324:        body["tools"] = list(entry.tools)
vinga-server/src/vinga_server/config/reload.py:99:from vinga_server.tools.mcp import McpServers
vinga-server/src/vinga_server/config/reload.py:100:from vinga_server.tools.mcp import reload as mcp
vinga-server/src/vinga_server/conversations/hydration.py:219:    if turn.tools:
vinga-server/src/vinga_server/conversations/hydration.py:220:        parts.append(TOOL_NOTE.format(names=", ".join(turn.tools)))
vinga-server/src/vinga_server/conversations/store.py:1756:                self._tool_row(session_id, turn_id, call) for call in item.record.tools
vinga-server/src/vinga_server/conversations/store.py:1913:            "tool_calls": len(record.tools),
vinga-server/src/vinga_server/device/placement.py:70:from vinga_server.tools import builtin
vinga-server/src/vinga_server/device/session.py:124:from vinga_server.tools.device import DeviceToolClient
vinga-server/src/vinga_server/device/session.py:1237:        return () if self._device_tools is None else self._device_tools.tools()
vinga-server/src/vinga_server/events/catalog.py:170:MCP_CHANNEL = "vinga_server.tools.mcp"
vinga-server/src/vinga_server/protocol/mcp.py:11:tools lives in `vinga_server.tools.device`.
vinga-server/src/vinga_server/runtime/pipeline.py:136:from vinga_server.tools import builtin, names
vinga-server/src/vinga_server/runtime/pipeline.py:137:from vinga_server.tools.mcp import McpServers
vinga-server/src/vinga_server/runtime/pipeline.py:138:from vinga_server.tools.source import (
vinga-server/src/vinga_server/runtime/pipeline.py:1784:        offered = frozenset(tool.name for tool in offer.tools)
vinga-server/src/vinga_server/runtime/pipeline.py:1834:                    tools=offer.tools,
vinga-server/src/vinga_server/runtime/pipeline.py:1840:                    functools.partial(providers.llm.stream, system, carried, offer.tools, choice),
vinga-server/src/vinga_server/runtime/prompt.py:67:from vinga_server.tools import names
vinga-server/src/vinga_server/runtime/resumption.py:52:from vinga_server.tools import builtin
vinga-server/src/vinga_server/runtime/tool_execution.py:40:from vinga_server.tools import names
vinga-server/src/vinga_server/runtime/tool_execution.py:41:from vinga_server.tools.arguments import with_lossless_coercions
vinga-server/src/vinga_server/runtime/tool_execution.py:42:from vinga_server.tools.source import ToolSource, no_such_tool, withheld
vinga-server/src/vinga_server/runtime/tool_execution.py:378:            sentence, offer.tools, functools.partial(self._report_withheld, offer.origins)
vinga-server/src/vinga_server/runtime/turns.py:30:from vinga_server.tools import names
vinga-server/src/vinga_server/telemetry.py:403:LLM_TOOLS = "vinga.llm.tools"
vinga-server/src/vinga_server/tools/builtin.py:60:from vinga_server.tools import names
vinga-server/src/vinga_server/tools/device.py:23:from vinga_server.tools.publish import PublishedTools, publish
vinga-server/src/vinga_server/tools/device.py:58:        return list(self._published.tools)
vinga-server/src/vinga_server/tools/device.py:104:            len(self._published.tools),
vinga-server/src/vinga_server/tools/device.py:105:            ", ".join(tool.name for tool in self._published.tools) or "none",
vinga-server/src/vinga_server/tools/mcp/__init__.py:37:halves. This `__init__` IS the module `vinga_server.tools.mcp`: it
vinga-server/src/vinga_server/tools/mcp/__init__.py:154:# `vinga_server.tools.mcp` means what it meant when this was one file.
vinga-server/src/vinga_server/tools/mcp/manager.py:46:from vinga_server.tools import names
vinga-server/src/vinga_server/tools/mcp/manager.py:47:from vinga_server.tools.publish import PublishedTools, publish
vinga-server/src/vinga_server/tools/mcp/manager.py:279:        return list(self._published.tools)
vinga-server/src/vinga_server/tools/mcp/manager.py:346:        published = {names.unqualified(self._name, tool.name) for tool in self._published.tools}
vinga-server/src/vinga_server/tools/mcp/manager.py:501:                        for tool in listed.tools
vinga-server/src/vinga_server/tools/mcp/manager.py:518:                published = len(self._published.tools)
vinga-server/src/vinga_server/tools/mcp/registry.py:34:from vinga_server.tools import names
vinga-server/src/vinga_server/tools/mcp/registry.py:171:            return manager.tools()
vinga-server/src/vinga_server/tools/mcp/registry.py:173:        for tool in manager.tools():
vinga-server/src/vinga_server/tools/mcp/slice.py:33:from vinga_server.tools import names
vinga-server/src/vinga_server/tools/mcp/slice.py:67:    if grant.tools is None:
vinga-server/src/vinga_server/tools/mcp/slice.py:69:    allowed = set(grant.tools)
vinga-server/src/vinga_server/tools/mcp/slice.py:276:            agent: (None if grant.tools is None else list(grant.tools))
vinga-server/src/vinga_server/tools/mcp/slice.py:341:            return grant.tools is None or names.unqualified(entry, published) in grant.tools
vinga-server/src/vinga_server/tools/mcp/slice.py:355:            if grant.server == entry and grant.tools is not None
vinga-server/src/vinga_server/tools/mcp/slice.py:356:            for name in grant.tools
vinga-server/src/vinga_server/tools/publish.py:38:from vinga_server.tools import names
vinga-server/src/vinga_server/tools/source.py:44:from vinga_server.tools import builtin, names
vinga-server/src/vinga_server/tools/source.py:45:from vinga_server.tools.mcp import McpServers
vinga-server/tests/census/reach-ins.txt:10:# `uv run python -m tests.tools.reach_ins --by-site`.
vinga-server/tests/census/test_reach_ins.py:45:from tests.tools.reach_ins import (
vinga-server/tests/integration/test_startup_failure.py:90:    f"mcp_servers.tools: mcp_servers.tools.env.API_TOKEN: references ${UNSET_VARIABLE}, "
vinga-server/tests/integration/test_telemetry_fanout.py:54:    "vinga.llm.tools",
vinga-server/tests/support/device_tools.py:18:from vinga_server.tools.device import DeviceToolClient
vinga-server/tests/support/isolation.py:67:        "vinga_server.tools",
vinga-server/tests/support/isolation.py:68:        "vinga_server.tools.names",
vinga-server/tests/support/providers.py:45:from vinga_server.tools.mcp import McpServers
vinga-server/tests/support/records.py:32:from vinga_server.tools.mcp import McpServers
vinga-server/tests/support/sessions.py:63:from vinga_server.tools.mcp import McpServers
vinga-server/tests/support/tools_mcp.py:47:from vinga_server.tools.mcp import McpServerManager, McpServers
vinga-server/tests/support/tools_mcp.py:60:MANAGER_LOGGER = "vinga_server.tools.mcp"
vinga-server/tests/tools/cli_ast_identity.py:20:    uv run python -m tests.tools.cli_ast_identity [<base-commit>]
vinga-server/tests/tools/cli_fields.py:17:    uv run python -m tests.tools.cli_fields   # the same, as a module
vinga-server/tests/tools/cli_sections.py:35:    uv run python -m tests.tools.cli_sections
vinga-server/tests/tools/driver_times.py:12:    uv run python -m tests.tools.driver_times
vinga-server/tests/tools/driver_times.py:28:from tests.tools.event_baseline import DRIVERS, listening
vinga-server/tests/tools/event_baseline.py:201:from vinga_server.tools.mcp import McpServers
vinga-server/tests/tools/event_baseline.py:202:from vinga_server.tools.mcp.reload import ReloadInProgressError
vinga-server/tests/tools/event_baseline.py:2250:MANAGER = "vinga_server.tools.mcp.manager"
vinga-server/tests/tools/event_baseline.py:2251:MCP_REGISTRY = "vinga_server.tools.mcp.registry"
vinga-server/tests/tools/event_baseline.py:2252:RELOAD = "vinga_server.tools.mcp.reload"
vinga-server/tests/tools/reach_ins.py:22:    uv run python -m tests.tools.reach_ins            # summary
vinga-server/tests/tools/reach_ins.py:23:    uv run python -m tests.tools.reach_ins --by-site  # file:line per site
vinga-server/tests/tools/reach_ins.py:24:    uv run python -m tests.tools.reach_ins --json     # the whole census
vinga-server/tests/tools/reach_ins.py:70:    "# `uv run python -m tests.tools.reach_ins --by-site`.\n"
vinga-server/tests/tools/utterance.py:16:    uv run python -m tests.tools.utterance
vinga-server/tests/unit/test_agent_rename_in_flight.py:85:from vinga_server.tools.mcp import McpServers
vinga-server/tests/unit/test_app_lifespan.py:67:from vinga_server.tools.mcp import McpServers
vinga-server/tests/unit/test_boundary_contract.py:56:from vinga_server.tools.device import DeviceToolClient
vinga-server/tests/unit/test_boundary_contract.py:57:from vinga_server.tools.mcp import McpServers
vinga-server/tests/unit/test_capture_session.py:78:from vinga_server.tools.mcp import McpServers
vinga-server/tests/unit/test_class_name_sites.py:44:from vinga_server.tools import builtin
vinga-server/tests/unit/test_cli_import_weight.py:162:        "vinga_server.tools",
vinga-server/tests/unit/test_cli_import_weight.py:163:        "vinga_server.tools.names",
vinga-server/tests/unit/test_config_api_runtime.py:72:from vinga_server.tools.mcp import (
vinga-server/tests/unit/test_config_cli_progress.py:44:from vinga_server.tools.mcp import McpServers
vinga-server/tests/unit/test_config_cli_rendering.py:80:from vinga_server.tools.mcp import McpServers
vinga-server/tests/unit/test_config_cli_transport.py:33:import vinga_server.tools.mcp as mcp_module
vinga-server/tests/unit/test_config_diff_read.py:59:from vinga_server.tools.mcp import McpServers
vinga-server/tests/unit/test_config_entities.py:182:        "vinga_server.tools",
vinga-server/tests/unit/test_config_entities.py:183:        "vinga_server.tools.names",
vinga-server/tests/unit/test_config_reload.py:84:from vinga_server.tools.mcp import RELOAD_REFUSED, McpServers
vinga-server/tests/unit/test_config_tools.py:11:from vinga_server.tools import names
vinga-server/tests/unit/test_config_tools.py:309:    return [(grant.server, grant.tools) for grant in config.mcp_for_agent(agent)]
vinga-server/tests/unit/test_config_url_credential_display.py:80:from vinga_server.tools.mcp import McpConfigError, McpServers
vinga-server/tests/unit/test_config_url_credential_display.py:81:from vinga_server.tools.mcp import manager as mcp_manager
vinga-server/tests/unit/test_conversations_session.py:55:from vinga_server.tools.mcp import McpServers
vinga-server/tests/unit/test_conversations_threads.py:496:    assert found.turns[0].tools == ("remember",)
vinga-server/tests/unit/test_driver_times.py:17:from tests.tools.driver_times import report, timed
vinga-server/tests/unit/test_event_baseline.py:49:from tests.tools.event_baseline import (
vinga-server/tests/unit/test_event_baseline.py:296:            "vinga_server.tools.mcp",
vinga-server/tests/unit/test_event_baseline.py:1119:    "vinga_server.tools.mcp.manager:McpServerManager._run #1": (
vinga-server/tests/unit/test_event_baseline.py:1122:    "vinga_server.tools.mcp.manager:McpServerManager._run #2": (
vinga-server/tests/unit/test_event_baseline.py:1125:    "vinga_server.tools.mcp.manager:McpServerManager._run #3": (
vinga-server/tests/unit/test_event_baseline.py:1128:    "vinga_server.tools.mcp.manager:McpServerManager._mark_down #1": (
vinga-server/tests/unit/test_event_baseline.py:1131:    "vinga_server.tools.mcp.manager:McpServerManager._mark_down #2": (
vinga-server/tests/unit/test_event_baseline.py:1134:    "vinga_server.tools.mcp.registry:McpServers._reachable #1": (
vinga-server/tests/unit/test_event_baseline.py:1137:    "vinga_server.tools.mcp.reload:_refused #1": (
vinga-server/tests/unit/test_event_baseline.py:1140:    "vinga_server.tools.mcp.reload:_apply #1": (
vinga-server/tests/unit/test_event_surface_pins.py:79:from tests.tools.event_baseline import Failing, failing_reply, turned_away
vinga-server/tests/unit/test_event_surface_pins.py:82:from vinga_server.tools.mcp import McpServers
vinga-server/tests/unit/test_event_values.py:573:    from vinga_server.tools.mcp import transport
vinga-server/tests/unit/test_event_values.py:593:    from vinga_server.tools.mcp import reload
vinga-server/tests/unit/test_events_live_wiring.py:45:from vinga_server.tools.mcp import McpServers
vinga-server/tests/unit/test_generation_binding.py:30:from vinga_server.tools.mcp import McpServers
vinga-server/tests/unit/test_mcp_composed_reference.py:43:from vinga_server.tools.mcp import CONNECTED, REDACTED, McpServers
vinga-server/tests/unit/test_mcp_pending.py:34:from vinga_server.tools.mcp import CONNECTED, McpServers
vinga-server/tests/unit/test_mcp_status_reflection.py:50:from vinga_server.tools.mcp import CONNECTED, REDACTED, McpServers, transport
vinga-server/tests/unit/test_mcp_status_reflection.py:64:MANAGER_LOGGER = "vinga_server.tools.mcp"
vinga-server/tests/unit/test_memory_store.py:60:from vinga_server.tools import builtin
vinga-server/tests/unit/test_memory_store.py:61:from vinga_server.tools.builtin import (
vinga-server/tests/unit/test_onboarding_import_weight.py:52:    "vinga_server.tools.mcp",
vinga-server/tests/unit/test_provider_watch_pins.py:50:from tests.tools.event_baseline import failing_reply
vinga-server/tests/unit/test_providers_boundary.py:422:        check_mcp_server("mcp_servers.tools", entry, boundary)
vinga-server/tests/unit/test_providers_boundary.py:425:        check_mcp_server("mcp_servers.tools", entry, boundary)
vinga-server/tests/unit/test_providers_boundary.py:435:        check_mcp_server("mcp_servers.tools", entry, Reach.HOST)
vinga-server/tests/unit/test_secret_resolution.py:33:from vinga_server.tools.mcp import McpServerManager
vinga-server/tests/unit/test_session_conversations.py:47:from vinga_server.tools import builtin
vinga-server/tests/unit/test_session_conversations.py:793:    assert [invocation.result for invocation in record.tools] == [answer]
vinga-server/tests/unit/test_session_conversations.py:884:    assert [invocation.name for invocation in asked.tools] == ["resume_conversation"]
vinga-server/tests/unit/test_session_conversations.py:890:    assert seeded.tools == ()
vinga-server/tests/unit/test_session_device.py:74:from vinga_server.tools.mcp import McpServers
vinga-server/tests/unit/test_session_device_location.py:60:from vinga_server.tools import builtin
vinga-server/tests/unit/test_session_kept_tools.py:30:from vinga_server.tools.mcp import McpServers
vinga-server/tests/unit/test_session_memory_policy.py:48:from vinga_server.tools.mcp import McpServers
vinga-server/tests/unit/test_session_recap.py:56:from vinga_server.tools import builtin
vinga-server/tests/unit/test_session_record.py:78:from vinga_server.tools.mcp import McpServers
vinga-server/tests/unit/test_session_record.py:129:    assert record.tools == ()
vinga-server/tests/unit/test_session_record.py:488:    calls = {invocation.position: invocation for invocation in record.tools}
vinga-server/tests/unit/test_session_record.py:522:    assert all(invocation.duration_ms is not None for invocation in record.tools)
vinga-server/tests/unit/test_session_record.py:533:    (invocation,) = record.tools
vinga-server/tests/unit/test_session_record.py:553:    (invocation,) = asked.tools
vinga-server/tests/unit/test_session_record.py:571:    assert [(invocation.position, invocation.is_error) for invocation in asked.tools] == [
vinga-server/tests/unit/test_session_record.py:575:    assert "already been handed over" in (asked.tools[1].result or "")
vinga-server/tests/unit/test_session_record.py:622:    assert [invocation.name for invocation in record.tools] == ["ghost_tool"]
vinga-server/tests/unit/test_session_record.py:656:    (invocation,) = only_record(spy).tools
vinga-server/tests/unit/test_session_record.py:676:    (invocation,) = record.tools
vinga-server/tests/unit/test_session_record.py:741:    assert len(record.tools) == 4
vinga-server/tests/unit/test_session_tool_events.py:46:from vinga_server.tools.mcp import McpServers
vinga-server/tests/unit/test_session_tools.py:59:from vinga_server.tools import builtin
vinga-server/tests/unit/test_session_tools.py:60:from vinga_server.tools.builtin import switch_agent_tool
vinga-server/tests/unit/test_session_tools.py:61:from vinga_server.tools.mcp import McpServers
vinga-server/tests/unit/test_session_tools.py:62:from vinga_server.tools.source import DeviceTools, McpTools, ToolSource
vinga-server/tests/unit/test_session_tools.py:1291:    (invocation,) = only_record(spy).tools
vinga-server/tests/unit/test_session_withheld.py:40:from vinga_server.tools.mcp import McpServers
vinga-server/tests/unit/test_session_withheld.py:453:    published = board.client.tools()[0].name
vinga-server/tests/unit/test_session_withheld.py:519:    published = board.client.tools()[0].name
vinga-server/tests/unit/test_telemetry_deploy.py:30:    "vinga.llm.tools",
vinga-server/tests/unit/test_tool_arguments.py:24:from vinga_server.tools.arguments import with_lossless_coercions
vinga-server/tests/unit/test_tool_execution.py:21:from vinga_server.tools import names
vinga-server/tests/unit/test_tool_execution.py:185:    assert [tool.name for tool in offer.tools] == [names.REMEMBER, "self_lamp", "home__lamp"]
vinga-server/tests/unit/test_tool_execution.py:191:    assert dict(offer.schemas) == {tool.name: tool.input_schema for tool in offer.tools}
vinga-server/tests/unit/test_tool_names.py:6:from vinga_server.tools import names
vinga-server/tests/unit/test_tools_device.py:28:    assert [tool.name for tool in device.client.tools()] == [
vinga-server/tests/unit/test_tools_device.py:32:    assert device.client.tools()[0].input_schema == VOLUME["inputSchema"]
vinga-server/tests/unit/test_tools_device.py:44:    assert [tool.name for tool in device.client.tools()] == [
vinga-server/tests/unit/test_tools_device.py:61:    assert [tool.name for tool in device.client.tools()] == ["self_a_b"]
vinga-server/tests/unit/test_tools_device.py:68:    assert [tool.name for tool in device.client.tools()] == ["self_audio_speaker_set_volume"]
vinga-server/tests/unit/test_tools_device.py:109:    import vinga_server.tools.device as device_module
vinga-server/tests/unit/test_tools_device.py:115:    assert device.client.tools() == []
vinga-server/tests/unit/test_tools_mcp.py:38:from vinga_server.tools import names
vinga-server/tests/unit/test_tools_mcp.py:39:from vinga_server.tools.mcp import (
vinga-server/tests/unit/test_tools_mcp.py:73:        offered = {tool.name for tool in manager.tools()}
vinga-server/tests/unit/test_tools_mcp.py:76:        (add,) = [tool for tool in manager.tools() if tool.name == "tools__add"]
vinga-server/tests/unit/test_tools_mcp.py:109:        assert manager.tools() == []
vinga-server/tests/unit/test_tools_mcp.py:390:    assert "mcp_servers.tools" in str(excinfo.value)
vinga-server/tests/unit/test_tools_mcp.py:404:    assert "mcp_servers.tools" in message
vinga-server/tests/unit/test_tools_mcp.py:496:        offered = {tool.name for tool in manager.tools()}
vinga-server/tests/unit/test_tools_mcp.py:498:        assert all(names.TOOL_NAME_PATTERN.match(tool.name) for tool in manager.tools())
vinga-server/tests/unit/test_tools_mcp.py:511:            len(tool.name) <= names.MAX_TOOL_NAME_LENGTH for tool in manager.tools()
vinga-server/tests/unit/test_tools_mcp.py:513:        assert not [tool for tool in manager.tools() if "bbbb" in tool.name]
vinga-server/tests/unit/test_tools_mcp.py:1126:        published = len(manager.tools())
vinga-server/tests/unit/test_tools_mcp.py:1330:        assert [tool.name for tool in servers.manager_of("home").tools()].index(
vinga-server/tests/unit/test_tools_mcp_http.py:35:from vinga_server.tools.mcp import (
vinga-server/tests/unit/test_tools_mcp_http.py:43:from vinga_server.tools.mcp import (
vinga-server/tests/unit/test_tools_mcp_http.py:49:MANAGER_LOGGER = "vinga_server.tools.mcp"
vinga-server/tests/unit/test_tools_mcp_http.py:151:        offered = {tool.name for tool in manager.tools()}
vinga-server/tests/unit/test_tools_mcp_http.py:153:        (listed,) = [tool for tool in manager.tools() if tool.name == "tools__add"]
vinga-server/tests/unit/test_tools_mcp_http.py:179:            assert manager.tools() == []
vinga-server/tests/unit/test_tools_mcp_http.py:235:            assert {tool.name for tool in manager.tools()} == {
vinga-server/tests/unit/test_tools_mcp_prompts.py:27:import vinga_server.tools.mcp as mcp_module
vinga-server/tests/unit/test_tools_mcp_prompts.py:39:from vinga_server.tools.mcp import (
vinga-server/tests/unit/test_tools_mcp_prompts.py:62:MANAGER_LOGGER = "vinga_server.tools.mcp"
vinga-server/tests/unit/test_tools_mcp_reload.py:58:from vinga_server.tools.mcp import (
vinga-server/tests/unit/test_tools_mcp_reload.py:76:from vinga_server.tools.mcp import manager as manager_module
vinga-server/tests/unit/test_tools_mcp_reload.py:689:        with caplog.at_level(logging.WARNING, logger="vinga_server.tools.mcp"):
vinga-server/tests/unit/test_tools_publish.py:10:from vinga_server.tools import names
vinga-server/tests/unit/test_tools_publish.py:11:from vinga_server.tools.publish import publish
vinga-server/tests/unit/test_tools_publish.py:37:    assert [tool.name for tool in result.tools] == [published]
vinga-server/tests/unit/test_tools_publish.py:49:    assert publish(listing(bare)).tools
vinga-server/tests/unit/test_tools_publish.py:50:    assert publish(listing(bare), prefix="server").tools == []
vinga-server/tests/unit/test_tools_publish.py:57:    assert [tool.name for tool in result.tools] == ["a_b", "a-b"]
vinga-server/tests/unit/test_tools_publish.py:63:    assert [tool.name for tool in result.tools] == ["___", "kept"]
vinga-server/tests/unit/test_tools_publish.py:128:    assert [tool.name for tool in result.tools] == ["ha__first", "ha__third"]
vinga-server/tests/unit/test_tools_publish.py:136:    (tool,) = publish([("do.it", "the description", SCHEMA)], prefix="ha").tools
```

</details>

### Tests and mutations

The new tests cannot be run against M1's code, which has no
`StoredCall` and fails them at import, so each was falsified by
mutation instead, every mutation run once against the suite it
targets. The pricing rows were run after the rebase, against the
repriced `_cost`; the rest before it, against code the rebase did not
change apart from `_cost`:

| Mutation | Outcome |
| --- | --- |
| The read ordered by `position` instead of `tool_invocations.id` | killed, 1 (the store-writer backlog test) |
| Rows filtered before they are grouped into rounds | killed, 1 |
| Resultless rows kept | killed, 2 (hydration); 1 in the session suite, crashing; 1 there again with the crash tolerated, on the unexecuted call reappearing |
| Round boundaries ignored | killed, 2 |
| Ids minted per unit rather than across the history | killed, 1 |
| The budget charging the structured size | killed, 4 |
| The budget charging a result's raw size beside its note | killed, 1 |
| The join space not charged | killed, 2 |
| The note measured raw rather than escaped (in `note_cost`) | killed, 1 |
| `note_cost` handed no result | killed, 3 |
| `countable` dropped from `kept_round` | killed, 1 (the lone-surrogate hydration test) |
| The Anthropic assistant join disabled | killed, 3 (both new translator tests and the resumed-request test) |
| An explicit `countable` in hydration's row conversion, removed | survived: `kept_round` already applies it, so the call was not kept |
| A joined turn's calls degraded | killed, 1 |
| Hydration rebuilding no rounds | killed, 2 (both session tests) |
| The recap sent with `start=0` | killed, 1 |
| The recap sent the raw hydrated input | killed, 1 |

One mutation survived, and it is the finding the deviation above
records: the code it removed was redundant and is not in the branch.
Budget assertions that moved on the rebase: one,
`test_a_large_result_is_charged_at_its_cleared_size`, whose expected
charge gained the one-character join through the shared helper
(`_charged`, which also counts non-ASCII escaped). Two existing hydration tests pinned the tool note
and were replaced on purpose
(`test_the_tools_a_turn_ran_are_named_and_nothing_else_about_them`,
`test_a_turn_that_only_ran_tools_still_has_an_assistant_half`), and the
backlog test `test_the_backlog_names_the_tools_a_turn_ran` was rewritten
to the widened read. Every other existing hydration test, the budget
walk, holes, joins and milestone head among them, passes unmodified.

### Verification

All on agentpi, from `vinga-server/`, at `238aacff` (the code as
committed after the second rebase, onto `1f90cce7`, and the Anthropic
assistant join; this section's commit changes only prose):

- `uv run ruff check .`: clean. `uv run mypy` (the events package):
  no issues in 5 source files.
- `uv run pytest tests/unit -q -n auto --dist loadfile`: 7984 passed,
  19 skipped in 1193.30s. Earlier runs of the same lane: at `8ad9eb69`
  before any rebase, 7946 passed in 1106.08s; at `f0dd5f6d` after the
  first, 7954 passed in 2642.88s with M2's lanes running beside it.
- `uv run pytest tests/integration -q -n auto --dist loadfile`: 350
  passed in 404.34s.
- The eight generated-document checks CI's `integration` job runs
  (domain, server, conversations schema, metrics views, events,
  OpenAPI, the CLI reference and its recipes): none drifted.
- `scripts/check_doc_links.py`: 295 files, 0 failures;
  `scripts/fold_changelog.py check`: 1 fragment, 0 failures.
- `uv run pytest tests/census -q`: run last, after this section; its
  outcome is in the hand-back rather than here.

Not verified locally: the image build and its smoke conversation (CI's
`image` job), and any live provider. The resumed request's shape
through the Anthropic translator is pinned but was not sent to the
Anthropic API (no key on this machine), including the joined
assistant messages the deviation above describes. The recap's clearing facts on
`llm_recap` wait on M2.

### PR review round 1

Reviewed 2026-10-04 by openai/gpt-6-sol, thinking high via codex CLI 0.160.0, read-only sandbox, runtime 5m05s, at commit e3278145.

No findings; verdict mergeable as is.

A correction was posted on PR #601: the M3 implementer's unit-lane line
was read from a `unit3.log` that M2's implementer also wrote, and the
surviving file was M2's, so CI's unit job is the evidence for M3's unit
lane.

## M2: measure the cap

**Attribution:** anthropic/claude-opus-5-5, thinking high; Claude Code 2.1.288; 2026-10-04.

Cut from M1's head `81cfca37`, in parallel with M3, and rebased onto
`main` at `c0c91715` once M1 merged as PR #600.

### What landed

| Decision | Where | Commit |
| --- | --- | --- |
| Q5: the per-tool mapping as a closed value | `events/values.py` (`ClearedTools`, `Kind.CLEARED_TOOLS`), `events_docgen.py`, `telemetry.py` (`SHAPES` row), `tests/unit/test_event_values.py`, `tests/unit/test_event_docs.py` | `Add the ClearedTools event value` |
| Q5 and D7: the five facts on `llm_round`, `llm_recap` and the LLM-stage `provider_failed`, by every failure route, and on their `llm` spans; `llm_round.turns`'s note | `runtime/history.py` (`HistorySent`, `NOTHING_LOST`, `Sent.accounting`), `runtime/tool_execution.py` (`cleared_key`), `runtime/pipeline.py` (`_tool_loop`), `runtime/provider_watch.py`, `events/catalog.py`, `events/assembly.py` (`HistoryAccounting`), `telemetry.py` (`HISTORY_ATTRIBUTES`, `CLEARED_TOOLS_PREFIX`, `_history_attributes`), `tests/unit/test_history_measured.py`, `tests/unit/test_provider_watch.py` | `Report what each request's history lost` |
| D8: `refetch` on the three `tool_call` variants and `vinga.tool.refetch` on the tool span | `events/catalog.py`, `events/assembly.py`, `runtime/tool_execution.py` (`_refetches`, `run`), `runtime/pipeline.py` (`_run_tools`), `telemetry.py` (`TOOL_ATTRIBUTES`), `tests/unit/test_history_measured.py` | `Flag a tool call that re-fetches a cleared result` |
| After the rebase: one key for a repeat, in the history's own form | `runtime/history.py` (`repeat_key`), `runtime/tool_execution.py` (`_refetches`), `tests/unit/test_history_measured.py` | `Match a repeated call in the history's own form` |
| The recap pin the unit lane caught | `tests/unit/test_session_recap.py` | `Pin the recap's zero history counts` |
| Documentation footprint | `docs/architecture/observability-surfaces.md`, `changelog.d/599-tool-history-measured.md` (`### Added`), `docs/reference/events.md` (regenerated in each of the three code commits) | `Document the history facts and the re-fetch flag` |

### What the re-fetch metric excludes (D8)

Moves are not measured. A handover, a new conversation and a resume
are partitioned out of a round before `ToolExecution.run` and emit no
`tool_call`, so a model that repeats a refused move after its result
was cleared produces no `refetch: true` anywhere. The exclusion is the
plan's round-3 resolution, kept: a refused move's result is a sentence
this server wrote (`builtin.ALREADY_MOVED`, the handover refusals),
never data the model fetched and in practice far under 2 KiB, so it is
not what the cap clears; a model repeating a move is a different signal
that would need a `tool_call` for moves. A malformed call is never a
re-fetch either: it has no arguments to compare. Both are stated in the
field's catalog note, on the observability page and in the changelog.

### Deviations from the plan

- **`HistorySent` lives in `runtime/history.py`**, not beside the watch.
  The module layout names `provider_watch.py` as what carries it, and
  it does; it is defined with the `Sent` it is derived from, through
  `Sent.accounting(key)`, where `key` is the caller's function from a
  cleared call to its `ClearedTools` key. That keeps D1's promise that
  the history module knows no tool namespace, and leaves D7's key
  function (`cleared_key`) in `tool_execution.py` beside
  `_sentence_withheld`, as the plan places it. `assembly.py` reads it
  through a `HistoryAccounting` protocol, the shape `RoundAccounting`
  already has, so the events package imports nothing from `runtime/`.
- **The recap is plumbed, and `_summarized` is untouched.** M3 is
  rewriting `_summarized` in parallel and its tree has no `HistorySent`,
  so `recap_round_done(..., history=...)` defaults to `NOTHING_LOST`
  and `watched(..., history=...)` to None. Before M3 that default is
  the truth: a recap's input is hydration's output, which holds no
  exchange to clear. **Whichever of M2 and M3 merges second wires the
  recap**: `_summarized` passes `as_sent(...).accounting(cleared_key)`
  to `recap_round_done` and the same value as `history=` to its
  `watched` call, and the session-level recap test (a resumed thread
  with an over-2-KiB stored result, the facts on `llm_recap`) lands
  with that wiring, as the plan's M2 test list says. What M2 does test
  of the recap: the watch carries a handed-in accounting onto
  `llm_recap` and a recap's `provider_failed`, the default is zeros, and
  a recap request built the way the plan builds it (`start` at the end,
  no offer) over a constructed thread with a 3 KiB board result reaches
  the recap's `llm` span as one cleared, one degraded, keyed `device`
  (`test_a_recap_over_a_cleared_result_carries_it_on_its_record_and_its_span`).
- **A recap's failure may carry the facts; its prompt accounting still
  may not.** `provider_failure` refuses `history` for a non-LLM stage
  only, since the plan has M3 hand the recap's accounting to its
  `watched` call; `prompt` stays reply-only, as #533 left it.
- **`cleared_largest` and `cleared_tools` have no default on
  `llm_round` and `llm_recap`.** They are optional in the schema
  (absent when nothing was cleared) but every construction states them,
  so the five fields sit together after `turns` and a builder cannot
  forget two of them. `provider_failed` declares all five optional
  with `ABSENT` defaults, at the end, beside the prompt accounting.
- **`cleared_key` answers `unknown` for an origin nobody recorded**: an
  MCP source without an entry, or no source at all. Neither comes out
  of the classifier; a stored row M3 reads could in principle carry
  either, and `unknown` is the naming policy's word for a name it may
  not print.
- **The re-fetch check reads the reservation's arguments**, the model's
  own values, rather than the execution copy, which may have been
  coerced to the declared types. That is what the history kept of the
  earlier call (M1 keeps the model's originals), so the two sides of the
  comparison are the same kind of value.
- **`refetchable` is a required argument of `ToolExecution.run`**, and
  of `PipelineRuntime._run_tools`, rather than defaulting to empty, so
  a caller that forgets it does not report every call as no re-fetch.
  The five direct `run` callers in the unit suites pass an empty set,
  and the lookahead test's `_run_tools` stub takes the new parameter.
- **The changelog entry is a fragment of its own**,
  `changelog.d/599-tool-history-measured.md`. M1's fragment was folded into
  `CHANGELOG.md` on `main` before this branch was rebased, so the
  `### Added` block written into it moved to a new file rather than
  resurrecting the folded one.
- **The stdio test server gains a `long_answer` tool**, published only
  when an entry's `env` sets `VINGA_TEST_LONG_ANSWER` to a size, the
  way `VINGA_TEST_SHADOWED_TOOL` already gates its planted name: no
  tool the server publishes by default returns more than a few bytes,
  and the integration lane pins the default tool set.
- **Test placement.** The session, span and pure tests are one new
  file, `tests/unit/test_history_measured.py`, to keep this milestone
  out of the files M3 is editing; the watch's routes extend
  `test_provider_watch.py` and the value's refusals
  `test_event_values.py`. Tests changed on purpose: the three
  `test_provider_watch_pins.py` LLM pins gain the three zero counts,
  `test_session_recap.py`'s whole-payload `llm_recap` pin gains the
  same zeros (its own commit, after the unit lane caught it), the five
  `test_session_tool_events.py` payload pins gain
  `refetch: False`, `test_event_baseline.py`'s carried shapes gain the
  new keys (six LLM shapes, three tool shapes), `test_event_assembly.py`'s
  expected variants gain the fields, and every `reply_stream` and
  `reply_round_done` call in the watch suites passes `history=`.

No other deviation: the five field names, the six attribute names and
`ClearedTools`'s four key shapes are the plan's table exactly, and
`degraded_calls` was kept, as review did not cut it.

### Discoveries

- **A malformed `ClearedTools` key would cost the whole round event,
  not just the mapping.** The value is built inside the emit thunk, so
  a key function that produced an invalid shape would have the
  emitter's guard refuse the `llm_round` as `construction_failed`. The
  mutation that keyed a board's result by its name produced a lawful
  shape (`builtin.<name>`) and was killed by value; the guard is what
  keeps the other kind of key bug from becoming a leak.
- **Only a removed entry can tell the call's origin from the current
  offer.** The mutation keying cleared results off the leg's `Offer`
  survived every test but one: the session test that removes the MCP
  entry between replies. While the tool is still offered both readings
  agree, which is why that test has to exist rather than only the pure
  one.
- **The `turns` step is visible in the pins.** The second reply's
  request over one kept round is five messages (user, the asking turn,
  its tool turn, the answer, user) where it was three before #599;
  `test_a_round_says_what_its_history_cleared` pins it, and the catalog
  note says so.

- **The rebase found a disagreement M1's review introduced.** PR #600
  made `kept_round` keep a call's name and arguments in their
  `countable` form (a lone surrogate becomes U+FFFD), so the cleared
  calls' keys were built from normalized strings while the re-fetch
  check compared the model's raw ones, and a repeat whose arguments
  held a lone surrogate read as no re-fetch. `repeat_key` is now the
  one function both sides go through. The test that pins it failed on
  the rebased tree before the fix (`[False, False]` for
  `[False, True]`).

### Tests and mutations

The new tests were run against M1's source first, where all three
touched suites fail at import (`HistorySent`, `ClearedTools`, the new
builders' arguments do not exist); behaviour was then pinned by
mutation. Each mutation was applied to the source, run once against
the six targeted suites (`test_history_measured.py`,
`test_provider_watch.py`, `test_event_assembly.py`,
`test_event_values.py`, `test_provider_watch_pins.py`,
`test_session_tool_events.py`, 205 tests, `-n 4`), and restored.

| Mutation | Outcome |
| --- | --- |
| The pipeline hands the round `NOTHING_LOST` | killed, 3 |
| `reply_stream` hands `watched` no history (both stream routes) | killed, 6 |
| The watchdog's own report omits history | killed, 3 |
| `watched` reports its failure without history | killed, 7 |
| A recap ignores the history it is handed | killed, 2 |
| `provider_failure` drops a failure's history | killed, 10 |
| Keys from the current offer instead of the call's origin | killed, 1 |
| A board's result keyed by its name | killed, 7 |
| `cleared_largest` stated as zero when nothing was cleared | killed, 8 |
| The failure span skips the history attributes | killed, 2 |
| The round span skips them | killed, 3 |
| The per-tool counts are not flattened | killed, 5 |
| `ClearedTools` accepts any string key | killed, 7 |
| `ClearedTools` accepts a zero | killed, 1 |
| `refetch` always false | killed, 3 |
| Canonical arguments not sorted | killed, 1 |
| A malformed call compared as no arguments | killed, 1 |
| The pipeline hands the execution no cleared keys | killed, 3 |
| The tool span drops `refetch` | killed, 1 |
| The builders ignore `refetch` | killed, 6 |

No mutation survived. The no-leak sentinel
(`test_no_cleared_result_and_no_far_side_name_reaches_a_record_or_a_span`)
plants a credential in a cleared board result and in an MCP tool's
published name, removes the entry so the call is degraded, re-asks the
board, and asserts both values reached the model and neither reached
any rendering of any record, any record's fields or any span's
attributes.

### Verification

On agentpi, from `vinga-server/`, after the rebase onto `main`
(`c0c91715`), at `6eb807b5`, the code as committed (the commit that
records this changes only prose):

- `uv run ruff check .`: clean. `uv run mypy` (the events package):
  no issues in 5 source files.
- `uv run pytest tests/unit -q -n auto --dist loadfile`: 7984 passed,
  19 skipped in 1193.30s. Before the rebase, at the recap pin's commit,
  it was 7977 passed, 19 skipped in 909.02s; the run before that one
  failed only the `llm_recap` whole-payload pin in
  `test_session_recap.py`, fixed by `Pin the recap's zero history
  counts`.
- `uv run pytest tests/integration -q -n auto --dist loadfile`: 350
  passed in 312.16s.
- The eight generated-document checks CI's `integration` job runs
  (domain, server, conversations schema, metrics views, events,
  OpenAPI, the CLI reference region and its recipes): none drifted.
  `docs/reference/events.md` was regenerated through its generator in
  each code commit.
- `python3 scripts/check_doc_links.py .`: 295 files, 0 failures;
  `scripts/fold_changelog.py check`: 1 fragment, 0 failures.
- `uv run pytest tests/census -q`: run last, after this section; its
  outcome is in the hand-back rather than here.

Not verified locally: the image build and its smoke conversation (CI's
`image` job), any live provider or OTLP backend (the spans are read
from the SDK's in-memory exporter), and the session-level recap with a
cleared result, which needs M3's rebuilt exchanges and lands with
whichever of M2 and M3 merges second.
