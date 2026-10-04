# Memory is read once per conversation: implementation

Companion to
[`2026-10-03-memory-per-conversation.md`](2026-10-03-memory-per-conversation.md),
one section per milestone, appended in the same change that ticks the
milestone checklist. It records deviations from the plan, resolutions
of the plan's open questions, and discoveries.

## M1: memory is read once per conversation

**Attribution:** anthropic/claude-opus-5-5, thinking high; Claude Code 2.1.288; 2026-10-04.

### What landed

| Decision | Where | Commit |
| --- | --- | --- |
| Pin before reshaping: what two rounds sent | `tests/unit/test_session_prompt.py` | `Pin that each round of a reply reads memory` |
| 6, the memory half: a read says whether it answered | `memory/store.py` (`PromptMemory.complete`, `NOTHING_READ`), `tests/unit/test_memory_store.py` | `Say whether a prompt read of memory answered` |
| 6, the device half | `device/bindings.py` (`RecordNow`, `record_now`, `resolve_record`), `runtime/pipeline.py` (`DeviceRecords`, `_device_record`, `_memory_context`), `tests/unit/test_device_bindings.py` | `Say whether a device record read answered` |
| 7 and round 3's first amendment: the erasure revision and its publication points | `memory/store.py` (`erasures`, `erased`, the permanent `forget`), `memory/api.py` (`ErasedDep`, `_erased`, `_cleared`), `config/api.py` (`ApiRuntime.memory_erased`), `app.py`, `docs/reference/api-openapi.json`, `tests/unit/test_memory_erasure_revision.py`, `tests/unit/test_app_lifespan.py` | `Publish hard deletions as a memory erasure revision` |
| 3 and round 3's fourth amendment: the framing, always present | `runtime/prompt.py` (`with_scopes(remembering=, marked=)`, `FRAMING_AT_START`, `FRAMING_AT_NOTE`, `REREAD_NOTE`, `NOTHING_SAVED`, `STATE_HEADING`), `app.py` (`_prompt_preview`), `runtime/pipeline.py`, `tests/support/prompts.py`, `tests/support/configs.py` (`forgetful`), the assembler's and the session suites' expectations | `Frame the memory section whenever an agent may remember` |
| 1, 2, 5, 6, 8 and round 3's second and third amendments: the keyed snapshot | `runtime/pipeline.py` (`_SnapshotKey`, `_Snapshot`, `_REREAD`, `_system_prompt`, `_mark_read`, `_activate_agent`, `_keep_round`, `_tool_loop`), `runtime/history.py` (`cleared_later`), `tests/unit/test_session_memory_snapshot.py`, the inverted pin and the clock tests that moved | `Read memory once per conversation, kept by its key` |
| The integration lane's tests that encoded the old clock or the bare persona | `tests/integration/` (four files) | `Move the integration suites to the memory snapshot` |
| 4 and the documentation footprint | `docs/architecture/observability-surfaces.md`, `docs/concepts.md`, `docs/architecture/design-guide.md`, `events/catalog.py` and `docs/reference/events.md` (regenerated), docstrings across `vinga_server` | `Document memory's conversation clock where it is stated` |
| The changelog fragment, this section, the tick | `changelog.d/536-memory-per-conversation.md` | this section's commit |

### Amendments from plan review round 3

Round 3 (terra) reached this milestone by message while it was in
flight, and its four amendments win over the plan text the worktree
was cut with (`d0c28d6e`). All four arrived before the snapshot commit,
so none needed a corrective commit.

1. **Decision 7: the model's permanent `forget` is a hard deletion.**
   `MemoryStore._forget` publishes the erasure revision after its
   `_written` transaction returned with `permanently` set; a soft forget
   publishes nothing. Tested at the store
   (`test_the_model_s_permanent_forget_publishes_once`, and that one
   which found nothing publishes nothing) and through two live sessions
   with the export on
   (`test_a_permanent_forget_leaves_both_live_conversations_prompts`).
2. **Decision 1: a fifth key component**, a session-local count of the
   memory writes whose answers the history will send cleared. The
   writes are `names.ORDERED_TOOL_NAMES`, which is exactly the seven the
   amendment lists (its own comment defines it as every write a
   conversation makes to something that outlives the round), and the
   size test is `history.cleared_later`, the one predicate `as_sent`
   now applies too, so the cap is never restated. Counted in
   `_keep_round`, where a round's answered calls are read off the turn's
   record. Tests: a large `set_state`, a large `forget` answer and a
   large `restore_memory`, each followed by a reply whose prompt carries
   the change; a small write does not count.
3. **The deletion guarantee, narrowed.** By construction: the key is
   compared once per leg, at its first round, so a leg validated before
   a deletion was published sends the fact in its remaining rounds.
   Tested with the deletion published after a cached-key hit and before
   the provider call
   (`test_a_deletion_after_a_cached_key_hit_is_sent_once_more_by_that_leg`),
   and documented on the observability page.
4. **`with_scopes` takes an explicit `remembering`**, keyword-only and
   required, from `_system_prompt` and from the preview route. The
   framing counts in `memory_characters` and in the size of the block it
   opens, and adds no provenance key, so `ScopeProvenance` (a closed
   set) is untouched. Tests: enabled-empty, disabled-empty, an enabled
   and a disabled preview.

### Deviations from the plan

- **Where the framing sits.** The plan leaves the framing's wording to
  the implementer and adds no provenance. It opens the first block of
  the memory section, separated by a blank line, and where every scope
  is empty the section is one `memory` block of the framing and
  `Nothing is saved in memory yet.` The sentence names the
  conversation's start, or, where the snapshot was read with turns
  already in the thread, the `(memory re-read here)` note. Both forms
  are one sentence. The framing covers the device's introduction too,
  since the record is read into the same snapshot.
- **`remembering=False` renders no memory section whatever it is
  handed**, keeping only the device's introduction. The amendment says
  memory-off omits the section; taking it literally (rather than
  rendering whatever scopes a caller passes) is what lets
  `test_an_agent_that_may_not_remember_leaves_the_cached_half_alone`
  assert identity with the half even when scopes are handed in.
- **One note at a time.** `_mark_read` takes an earlier note out of the
  history before placing a new one. The plan says a re-read inserts one
  note; it does not say what happens to the previous one, and two notes
  would leave the framing's "the note" ambiguous. The note is a module
  constant `Turn`, found by identity, so nothing a model said can be
  mistaken for it. It lives only in the session's history: the store
  never records it, and a resumed thread is marked by its first leg's
  read.
- **An incomplete memory read renders no section and places no note.**
  Decision 6 says such a round "sends exactly what it sends today";
  today that is the empty blocks with no memory section, and a section
  saying nothing is saved would be a claim about memory nobody read.
  An incomplete device read with a complete memory read renders the
  section, marked if the history calls for it, and is still not kept.
- **`record_now` changed too, not only `resolve_record`.** The plan
  names `resolve_record` as gaining the result; `record_now` is the
  synchronous half it wraps, and its only other callers were tests. A
  record with no identity, or a view with no database, answers from the
  served world as the authority and says complete; only the arm that
  fell back because the read raised says incomplete. The existing
  fallback test had to give its device an identity: without one, the
  failing engine was never reached by this read (its warning came from
  the attachment read before it).
- **`memory_unreadable`'s log line changed**, from "it remembers
  nothing of it this round" to "it remembers nothing of it until a read
  succeeds", beside the notes the plan names. The line now covers a leg
  rather than a round; no test pinned it.
- **Test support.** `tests/support/prompts.py` joins the assembler's own
  constants (`nothing_saved`, `FRAMED`, `EMPTY_SECTION`) so a suite that
  asserts a whole prompt does not restate the framing.
  `tests/support/configs.forgetful` turns every agent's memory off, for
  the suites that identify an agent by the mock model's `{system}` echo,
  which would otherwise read the section out as three more sentences.
- **The gate rig**, adapted from the placement experiment's
  (`aa462fd6.../scratchpad/ppgate/`), copied rather than edited:
  telemetry off, so nothing left but the OpenAI calls; a write verified
  by its successful `tool_call` and by the agent's memory listing after
  the session, since `memory_facts` no longer grows mid-conversation on
  the branch; a behavior script written for this plan's probes, with a
  second board for the concurrent session; and both trees exported with
  `git archive` (`main` at `62fa62d4`, the branch at `50b6c56b`), so
  later documentation commits could not change the code under test.
  "Three sessions each, the first starting with memory empty" is read
  as three behavior runs per arm, each on a fresh database verified
  empty before and after.

### Discoveries

- **The model's own deleted fact survives in its history, and the
  note does not override it.** The behavior runs carried one probe
  beyond the plan's, as an observation: the model remembers "my car is
  red", an operator hard-deletes the fact through `vinga memory delete`,
  and the user asks the car's colour. On the branch the deletion was
  published and the next leg read again (the system prompt grew from
  5393 to 5663-5699 characters, now marked at the note); in all six
  runs, both arms, the model still answered "Your car is red", from its
  own `remember` exchange before the note. That is decision 7's stated
  limit (the history is not memory, and the observability page gives
  the order that prevents it), but it is also evidence about review
  round 2's handover-back probe: the framing ranks what came before the
  note as "already reflected" in the snapshot, and gpt-4.1-mini does not
  read the absence of a fact from the snapshot as overriding a tool
  result that stated it. The unit test pins the note's placement; the
  live behavior the plan hoped the framing would produce, for an
  absence, is not there. A correction (a value present in both) was
  probed live after the PR review asked for it, with the same result:
  see the handover-back probe below.
- **The device record is read by memory tool calls as well as by the
  prompt.** `_memory_context` resolves the address a device's facts are
  filed under on every memory tool call; that read stays per call and
  is not part of the snapshot. Its type changed with `RecordNow`, which
  the type checker in CI (the events package only) would not have
  caught; the session suites did.
- **Ordinary rounds cached slightly less on the branch in the gate**
  (mean 0.906 over twenty first rounds against 0.953 on `main`). One
  ordinary round (`c2-new` turn 11) was a full miss with the system
  prompt unchanged, which is the provider's cache rather than anything
  this change sends; without it the branch's mean over the other 19 is
  0.954.
- **The unit lane is green on agentpi** (8053 passed, 19 skipped),
  including the pipe-buffer test the machine's notes record as failing.

### Inventories

All taken untruncated, to files in the session's log directory, and
counted with `wc -l`.

**Callers** (`git grep -n -E "_system_prompt\b|with_scopes\(|read_for_prompt\b" -- vinga-server/src`,
15 lines after the change): `_system_prompt` has one caller,
`_tool_loop`, once per leg; `with_scopes` has three call sites, two in
`_system_prompt` and one pair in `app.py`'s `_prompt_preview` (memory
off, memory on); `read_for_prompt` has two callers, `_system_prompt`
and the preview. The remaining hits are the definitions and docstrings
naming them. Tests hold 84 further lines, all updated or passing as
they were.

**Per-round wording** (`git grep -n -i -E "per.round|every round|this round" -- vinga-server/src docs ':!docs/plans/*'`):
90 lines before, 54 after. Changed: the observability page's memory,
round accounting and export paragraphs; `docs/concepts.md`; the design
guide's prompt example; the catalog's `memory_characters`,
`memory_sources`, `memory_facts`, `prompt_assembled`,
`memory_unreadable` and `memory_unwritable` notes and the
`memory_unreadable` line, with `docs/reference/events.md` regenerated;
the docstrings and comments in `device/bindings.py`, `device/boundary.py`,
`device/placement.py`, `device/session.py`, `config/store.py` (two),
`app.py`, `memory/store.py` (seven), `events/values.py` (two),
`events_docgen.py`, `telemetry.py`, `tools/builtin.py`,
`runtime/prompt.py` and `runtime/pipeline.py`. Each of the 54 left
describes something else, by group:

- **The round accounting, which stays per round (decision 8):**
  `SYSTEM_CHARACTERS_NOTE` and its two rendered rows in
  `docs/reference/events.md`, the rows for `memory_characters` and
  `memory_facts` (whose new text says the value repeats), the
  observability page's sentence that every round repeats them,
  `RoundPrompt.system_characters`, and the pipeline's comments that
  every round's events carry the accounting.
- **What one round of the tool loop does, not memory:** the history and
  turn records (`conversations/hydration.py`, `records.py`,
  `threads.py`, `runtime/history.py`, `runtime/tool_execution.py`), the
  tool loop's own comments (`pipeline.py`'s offer, history, moves and
  switch ordering), `llm_input_export.py`'s per-round admission,
  `telemetry.py`'s staging order and recap purpose, `resumption.py`'s
  budget, `turns` in the catalog, the per-leg/per-round token sentence
  in `conversations/docgen.py` and its rendered row.
- **Still true as written:** `config/models.py`'s `export_llm_input`
  description and its rendered row in `docs/reference/server-config.md`
  ("the memory each round's request carries goes with every round",
  which is the snapshot every round sends), the observability page's
  export paragraph saying the same, the design guide's
  `RecordingLlm` sentence, and the new text itself (the snapshot's
  docstrings saying it is no longer read on every round).
- **Unrelated uses of "round":** three feature documents about review
  rounds and provider rounds.

### Tests and mutations

The new suite, `tests/unit/test_session_memory_snapshot.py`, holds 22
tests. Watched failing first: against the previous commit's pipeline,
17 of them failed. The five that passed describe outcomes the per-round
read also had (a hard deletion leaving the next reply, the start's
framing, both export cases, the device scope's address) and are held by
the mutations below instead. Elsewhere: the pin was committed green
before the change and inverted with it; the incomplete-read and
erasure-revision tests failed with their source change stashed or
mutated.

Mutations, one run each, every one killed:

| Mutation | Run on | Failed |
| --- | --- | --- |
| Re-read every round (cache off, read per round) | snapshot, prompt suites | 21, the byte-identical and read-count tests among them |
| Activation dropped from the key | snapshot, prompt, kept-tools, policy suites | the handover-back test and the accounting test |
| Conversation dropped | same | the rebind test and the resume test |
| Memory switch dropped | same | the policy-apply test and four policy suite tests |
| Erasure revision dropped | same | the six deletion tests |
| Oversized count dropped | same | the three oversized-write tests |
| Oversized count bumped at any size | snapshot suite | the small-write and byte-identical tests |
| Incomplete reads kept | snapshot, prompt, kept-tools suites | the memory-failure and both device-fallback tests |
| Never mark the read point | same | six note tests |
| Always frame at the start | same | the same six |
| Earlier notes kept | same | the handover-back test's second read |
| The fallback arm says complete | `test_device_bindings.py` | the fallback test |
| No publication from an addressed erase route | `test_memory_erasure_revision.py` | the two addressed-route tests |
| A whole-scope erase publishes unconditionally | same | the found-nothing test |
| No publication from the permanent forget | same | that test |
| The composition's wiring dropped | `test_app_lifespan.py` | the app-level test |
| The nothing-saved block dropped | assembler and policy suites | 20, the enabled-empty tests among them |
| Scopes rendered with memory off | same | 13, the disabled tests among them |

No survivors.

### The gate

Run through the real server, in process, on gpt-4.1-mini (OpenAI ASR
and TTS, silero VAD), from a fresh database per session (`vinga_m536_<label>`
on the lane's Postgres, dropped after), with all three memory scopes
listed empty through `vinga memory list` before every session and
again after its teardown deleted what it wrote. The OpenAI key came
from the repository's `.env` and was never printed. No container was
started. Runs 2026-10-04 05:01 to 05:28 CEST, order
`c1-old c2-new c3-new c4-old`, then `b1-old b1-new b2-old b2-new b3-old b3-new`.

**Cache: passes.** A 16-turn session with five `remember` turns; every
write verified by its successful `tool_call` and by five facts in the
listing after the session. The write-followed round is the second round
of a `remember` turn.

| Arm | Write-followed rounds | Mean cached share | Full misses (< 1024) | System prompt unchanged across the write | Ordinary first rounds, mean share |
| --- | --- | --- | --- | --- | --- |
| `main` (c1, c4) | 10 | 0.000 | 10 | 0 of 10 | 0.953 (20) |
| branch (c2, c3) | 10 | 0.968 | 0 | 10 of 10 | 0.906 (20) |

Per write (input tokens, cached tokens of the write-followed round):

| Turn | c1-old | c4-old | c2-new | c3-new |
| --- | --- | --- | --- | --- |
| 3 | 2625 / 0 | 2627 / 0 | 2641 / 2560 | 2648 / 2560 |
| 6 | 2780 / 0 | 2771 / 0 | 2771 / 2688 | 2781 / 2688 |
| 9 | 2925 / 0 | 2917 / 0 | 2899 / 2816 | 2914 / 2816 |
| 12 | 3074 / 0 | 3057 / 0 | 3031 / 2944 | 3060 / 2944 |
| 15 | 3209 / 0 | 3194 / 0 | 3157 / 3072 | 3191 / 3072 |

On `main` the system prompt grew at every write (5200 to 5389
characters over c1); on the branch it was 5393 characters for the whole
session.

**Behavior: passes.** Three runs per arm. Conversation 1 on the main
board; a concurrent session on a second board says "Please remember that
my dog is called Rufus." between its turns 9 and 10; conversation 3 is
a new connection on the main board. Answers as spoken (the probe marked
`*` is not gating):

| Probe | `main` b1 / b2 / b3 | branch b1 / b2 / b3 |
| --- | --- | --- |
| A fact remembered two turns earlier ("What is my favourite flower?") | blue poppy, all three | blue poppy, all three |
| A ledger value changed mid-conversation (marigold, then tulip) | tulip, all three | tulip, all three |
| A fact forgotten mid-conversation ("Am I allergic to bees?") | "You are not allergic to bees according to what I remember / I know / you told me." | "...according to what I currently remember." / "...according to what you told me." / "You are not remembered as allergic to bees." |
| A concurrent session's fact, mid-conversation (the stated cost) | Rufus, all three | "I do not know your dog's name.", all three |
| The concurrent session's fact, next conversation | Rufus, all three | Rufus, all three |
| `*` A fact the model remembered, then an operator hard-deleted | "Your car is red.", all three | "Your car is red.", all three |

The branch answers every gating probe `main` answers, and differs only
on the concurrent session's fact mid-conversation, which is the stated
cost. The observation probe is the first discovery above.

**The handover-back precedence probe** (the plan's test list; run live
after external review round 1, finding 2). A copy of the rig
(`gate/handback.py`) adds a second agent, the keeper, bound to the same
board after the guide, with a line in each persona telling it to hand
over with `switch_agent` when the visitor asks for the other. One
connection, four turns: (1) "Please remember that my appointment at the
garden is on Monday", which the guide stores with `remember`; (2) "Can
I speak to the keeper, please?", a handover; then, while the keeper
holds the floor, an operator correction through `vinga memory set` of
that fact to "The user's appointment at the garden is on Thursday.";
(3) "Thank you. Please put me back through to the guide.", the
handover back onto the guide's own thread; (4) "When is my
appointment?". The correction is an operator's and not another
agent's because agent memory is per agent, so the keeper cannot write
the guide's fact; and it is a correction rather than a hard delete plus
re-add because the handover back reads memory again whatever moved it,
so a committed correction is in the snapshot the guide is sent from
turn 3 on. The rig records every request the model was sent, which
confirms it: on the branch the guide's final request held the memory
section read at the note, `- The user's appointment at the garden is
on Thursday.`, with `(memory re-read here)` at index 5 of 11 turns,
after the `remember` exchange that said Monday (indexes 1 and 2) and
before the handover seed. `main` was run too, because it makes the
comparison meaningful: it re-reads memory every round, so its prompt
also held Thursday, with no framing and no note. Fresh database per
run, all three scopes listed empty before and after, runs
2026-10-04 06:04 to 06:11 CEST (`gate/handback-tables.txt`).

| Run | Answer to "When is my appointment?" | Prompt held | Re-read note in the history |
| --- | --- | --- | --- |
| branch h1 | "Your appointment at the garden is on Monday." | Thursday, framed at the note | yes, index 5 of 11 |
| branch h2 | "Your appointment at the garden is on Monday." | Thursday, framed at the note | yes, index 5 of 11 |
| branch h3 | "Your appointment at the garden is on Monday." | Thursday, framed at the note | yes, index 5 of 11 |
| main h1 | "Your appointment at the garden is on Monday." | Thursday, no framing | none |
| main h2 | "Your appointment at the garden is on Monday." | Thursday, no framing | none |
| main h3 | "Your appointment at the garden is on Monday." | Thursday, no framing | none |

**Finding: gpt-4.1-mini prefers the older tool result over the
snapshot, 0 of 3 on the branch.** The framing and the note were in
place exactly as decision 3 specifies, and the model answered from its
own `remember` exchange rather than from the corrected memory. It is
not a regression: `main`, whose prompt also held the corrected value on
every round, answered Monday in all three runs as well, so the model
weighs a tool result in its history above the system prompt whether or
not the prompt says when it was read. Since #599 that exchange is in the
history on both arms. The framing was not tuned in response, as the
brief directs; whether to try another wording, a different note, or to
accept it is Rafael's decision. One side observation, the same on both
arms: answering the handover seed, the guide called `switch_agent`
again (refused, one move per reply) and then introduced itself as the
keeper, reading the last request in its own thread, "Can I speak to the
keeper", as still open.

### Verification

From `vinga-server/` on agentpi, logs in the session's log directory
(`m536-logs/`), after the last code commit:

- `uv run ruff check .`: all checks passed (`final-ruff.log`).
- `uv run mypy`: no issues found in 5 source files (`final-mypy.log`).
- `uv run pytest tests/unit -q -n auto --dist loadfile`: 8053 passed,
  19 skipped in 900.60s (`final-unit.log`).
- `uv run pytest tests/integration -q -n auto --dist loadfile`: 350
  passed in 214.86s (`final-integration.log`). The first integration
  run, before the integration commit, was 8 failed, 342 passed
  (`lane-integration-1.log`).
- Every generated-document drift check the workflow runs (domain and
  server configuration, conversation schema, metrics views, events,
  OpenAPI, CLI reference and recipes) diffed clean (`drift/drift.log`);
  `docs/reference/events.md` and `docs/reference/api-openapi.json` were
  regenerated by their generators.
- From the repository root, `python3 scripts/check_doc_links.py .`:
  297 files, 0 failures (`doc-links.log`); `python3
  scripts/fold_changelog.py check .`: 1 fragment, 0 failures
  (`fold-check.log`).
- `uv run pytest tests/census -q`, last, after the final prose edit:
  recorded on the pull request.
- Not verified: anything on a board, and the gate on a model other than
  gpt-4.1-mini.

### PR review round 1

Reviewed 2026-10-04 by openai/gpt-6-sol, thinking high via codex CLI 0.160.0, read-only sandbox, runtime 5m13s, at commit 2c99dc40

1. **P1: a legal large restore disappears from the next request.** A
   restored fact over the agent block's 4 KiB cap is left out of the
   rebuilt snapshot, and its `restore_memory` answer over 2 KiB is
   cleared on later replies, so neither carries its text.

   *Resolution* (the coordinator, on the PR): rejected, no code change.
   The block's cap (`CORE_BYTES = 4096`, enforced by `_core`) already
   kept a fact over 4 KiB out of every prompt on `main`; `recall` is
   its path, and the cleared note names the tool so the model calls it
   again, which #599's `refetch` measures. A second representation for
   oversized facts would be a change to the block's cap, a separate
   decision.

2. **P2: the promised handover precedence probe was not run.** The
   unit test scripts its answer and checks only the prompt and the
   note's place; the plan's test list asks for the model's choice.

   *Resolution:* run live, three times on the branch and three on
   `main`, as recorded under the gate above. The model answered from
   the older tool result in all six runs; reported as a finding, the
   framing untouched. Recorded in this section's commit.

3. **P2: the deletion export tests omit two claimed paths.** The
   operator-deletion test preloaded the fact and only recalled it, and
   the permanent-forget test gave the concurrent session no exporter.

   *Resolution:* fixed in `5a003f1c`. Both tests now have the model
   store the fact in a real `remember` exchange and recall it later,
   assert that the fact leaves every exported system prompt after the
   deletion (both sessions' for the permanent forget), and that the
   `remember` and `recall` exchanges are still in the exported history.
   One mutation each: dropping the erasure revision from the key fails
   both, the permanent-forget test at the concurrent session's export;
   not keeping a round's exchanges fails both at the history assertion.

Lanes after the round's fixes, from `vinga-server/`, logs in
`m536-logs/r1-*`: `uv run ruff check .`, all checks passed
(`r1-ruff.log`); the unit lane, 8053 passed, 19 skipped in 906.58s
(`r1-unit.log`); the integration lane, 350 passed in 216.45s
(`r1-integration.log`); `python3 scripts/check_doc_links.py .`, 297
files, 0 failures (`r1-doc-links.log`); the census lane last, after
this section's last edit (`r1-census.log`).
