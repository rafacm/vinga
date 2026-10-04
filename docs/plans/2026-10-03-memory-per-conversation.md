# Memory is read once per conversation

Plan for [#536](https://github.com/rafacm/vinga/issues/536), as Rafael
decided it on 2026-10-03 ("option B" in the
[decision comment](https://github.com/rafacm/vinga/issues/536#issuecomment-5972618241)): the
memory a prompt carries is read once when an agent starts speaking on a
conversation and kept for that conversation, instead of being re-read on
every round. Its companion is
`docs/plans/2026-10-03-memory-per-conversation-implementation.md`, one
section for the one milestone, appended in the change that ticks it.

**Local baseline:** not applicable. The model receives the same memory
in the same place; only when it is read changes.

**Cheapest alternative:** leaving it alone. Today every memory write
makes the next round (the same-turn continuation after the tool call)
miss the provider's prompt cache entirely, after which caching recovers;
measured on gpt-4.1-mini, 8 of 8 write-followed rounds cached nothing,
and ordinary rounds cached 0.85 (#536 decision comment). That is one
uncached round per write, a small and bounded cost, and Rafael weighed
it. This plan buys its removal for one cached value and a refresh rule,
and it brings vinga to the pattern the systems surveyed for #536 use
(memory placed once per conversation, anything newer arriving as
messages). The placement change, per-turn retrieval and pgvector were
measured and are not pursued.

**Attribution:** anthropic/claude-opus-5-5, thinking high; Claude Code 2.1.286; 2026-10-03.
Revised after #599 landed by anthropic/claude-opus-5-5, thinking medium; Claude Code 2.1.288; 2026-10-04.

## Where this starts from

Measured at `677fd921` (`main` on 2026-10-03).

- `PipelineRuntime._system_prompt` (`runtime/pipeline.py:2400-2477`)
  runs on every round (its one caller is the reply loop,
  `pipeline.py:1803`). It reads the device record, then, when the agent
  may remember, all three memory scopes in one store read
  (`MemoryStore.read_for_prompt`), and assembles them after the
  know-how half with `prompt.with_scopes`. Its docstring records the
  per-round clock as a contract: "a fact remembered in one session is
  known to a concurrent one on its next reply and a note written in one
  round is read in the next", and the device record is read per round
  so "a device relocated between two replies has moved for the second
  of them".
- The know-how half has a different clock: built in `_activate_agent`
  (`pipeline.py:1046-1093`) at each agent activation, including a
  handover.
- A session can also rebind to another conversation without changing
  agent (`pipeline.py` around 1722, the `transition.conversation`
  path), which changes the ledger scope.
- **Since #599 (merged 2026-10-04, PRs #600 to #602), tool exchanges
  stay in the history an agent is sent**: every call that answered is
  committed into the thread's history as it answers, sent structured on
  every later reply of the session (results over 2 KiB cleared to a
  note, which no memory write's answer approaches), and rebuilt from
  `tool_invocations` when a thread is resumed. This is what review
  round 1's finding 1 found missing, and it is now the mechanism
  decision 2 relies on.
- Every memory write the model makes leaves a tool message in the
  history that states what changed: `remember` answers
  `Remembered [<id>]: <text>`, `forget` answers `Forgot [<id>]: ...`,
  `set_state` answers `Noted <key>: <value>`, `clear_state` answers
  `Forgot <key>` (`tools/builtin.py:792-1074`), and `update_memory` and
  `set_device_location` answer in kind.
- The state block's heading claims precedence that a frozen block
  cannot keep: "The current state of this conversation. When anything
  below disagrees with this, this is current" (`runtime/prompt.py:89-92`).

## Decisions

1. **One snapshot per agent activation on a conversation, valid by
   its key and nothing else.** The `RoundPrompt` (device record, the
   three scopes, the fact ids the metadata half reports) is built at
   the first round after the agent is activated or the session rebinds
   to another conversation, and reused for every later round while it
   stays valid. Validity has exactly one mechanism (review round 1,
   finding 6): the snapshot carries the key it was built under, and
   `_system_prompt` reuses it only when that key equals the current
   one. There are no invalidation calls to forget. The key is four
   values, each with its own reason and its own test:
   - an **activation counter**, bumped by `_activate_agent` (so a
     handover, and a handover back to the same agent on the same
     conversation, rebuilds, as the know-how half already does);
   - the **conversation id** (so a rebind to another thread rebuilds
     and one thread's ledger is never served on another);
   - the **memory policy** the snapshot was built under (decision 5);
   - the store's **operator revision** (decision 7).
2. **What the model writes mid-conversation reaches it as the messages
   it already is.** No re-read and no added message: each memory tool's
   result in the history states the change. Decision 3 tells the model
   so.
3. **The framing says when the snapshot was taken, and is always
   there.** The state block's heading stops claiming to be current.
   Wherever the agent may remember, the prompt carries a memory section
   even when every block is empty (review round 1, finding 4: today
   `with_scopes` returns the know-how half unchanged when all blocks
   are empty, so a conversation that starts with nothing saved would
   carry no framing at all); empty, it says nothing is saved yet. Its
   one framing sentence ties precedence to the snapshot's actual
   capture point rather than to the conversation's start: what it
   shows is memory as it stood when it was read; memory tool results
   that come after that point in the conversation are newer and win,
   and those before it are already reflected in it.

   The capture point is visible to the model. A snapshot built at the
   start of a conversation, or after a handover (which starts clean),
   has nothing before it but the user's first words, so the start is
   the point. A snapshot built while the thread already has history (a
   rebind onto a resumed thread, a policy apply, an operator's change,
   the first complete read after a failed one) is marked: the pipeline
   inserts one fixed note in the assistant's voice, `(memory re-read
   here)`, into the thread's history immediately before the newest user
   turn, and the framing sentence names that note as the point. A
   rebuild already changes the system prompt, so the provider cache is
   lost at that round either way, and the note changes only the
   history's tail. The note is a constant in `runtime/prompt.py` with
   the headings; the framing's exact wording is the implementer's,
   checked by the behavior gate.
4. **What is given up, stated where the contract was.** The
   `_system_prompt` and `with_scopes` docstrings, and the observability
   page's memory section, say the clock is per activation now and what
   that costs: a fact saved or a device moved by a different live
   session's model during this conversation is seen from this session's
   next conversation, not its next reply. An operator's change is not
   in that cost; decision 7 makes it reach the next round. An appended
   update message for other sessions' writes is a possible later step,
   not this plan.
5. **The memory switch keeps its own clock.** Whether the agent may
   remember (`_remembering_now`) is still resolved per reply for the
   tools; the snapshot follows the value it was built under, and the
   snapshot is rebuilt if that value changes between replies (a config
   apply), so the blocks and the offered tools cannot disagree.
6. **A failed read is never kept.** `MemoryStore._read` answers a
   database it cannot read with `NOTHING_REMEMBERED`, the same value as
   an empty memory, and says so only on the event stream (review round
   1, finding 2). `read_for_prompt` therefore states which it was:
   `PromptMemory` gains `complete: bool` (true by default; the failure
   path returns a `NOTHING_REMEMBERED` that says `complete=False`), and
   the device record read says the same where it can fail. A round whose
   read was incomplete sends exactly what it sends today (the safe
   empty blocks, the reply happens) and caches nothing, so the next
   round reads again; the first complete read becomes the snapshot. A
   short outage therefore costs the rounds it lasts, as it does today,
   rather than the rest of the conversation.
7. **An operator's change reaches the next round.** The operator doors
   (the memory API's writes and hard deletions in `memory/api.py`, a
   device-record change through the config API, a thread purge) bump a
   process-wide **operator revision** on the store after their write
   commits; the model's own writes through the memory tools do not, so
   they cost the cache nothing. The revision is part of the snapshot's
   key (decision 1), so the next round of every live conversation
   rebuilds its snapshot from the store as it now is. One process is
   enough for this to be complete: the server runs one replica, as its
   topology ADR records (#316), and the API and every session share
   that process. What remains stale is only a write made by another
   live session's model, decision 4's stated cost.

   What the revision cannot reach, stated on the observability page's
   deletion section rather than left implied (review round 1, finding
   3): if this session's model itself wrote the fact (`remember` in this
   conversation), its own call and answer are in this conversation's
   history since #599, and the history is not memory. Hard-deleting the
   fact stops it being sent as memory from the next round, and the
   tool exchange that wrote it keeps being sent, and exported when
   `export_llm_input` is on, until the session ends; a resumed thread
   rebuilds it from `tool_invocations`, which a thread deletion removes.
   The operator's way to stop both is the existing one: delete the
   conversation's thread (`vinga conversation delete`), which removes
   its stored turns and calls, and end the live session (the device
   disconnecting, or a server restart). The page says this in that
   order.
8. **The metadata half's accounting stays truthful.** Every round still
   reports the size and fact ids of the prompt it actually sent; with a
   frozen snapshot they repeat until the snapshot is rebuilt, which is
   what the model received.

## Tests

Reuse the session prompt tests (`tests/unit/test_session_prompt.py`),
the memory tool tests, and the event baseline.

- A second round of the same reply, and a second reply on the same
  conversation, send a byte-identical system prompt even after a
  `remember`, a `forget`, a `set_state` and a `set_device_location` by
  the model in between, and the later reply's request carries those
  four exchanges structured although neither the utterance nor the
  spoken answer repeats the values (review round 1, finding 1).
- The memory store is read once per activation on a conversation, not
  per round (a counting fake).
- A handover and a conversation rebind each rebuild the snapshot: the
  next round's system prompt reflects a write made before them.
- Each key component has a test of its own in which only that
  component changes: a handover away and back to the same agent on the
  same conversation (activation counter), a rebind (conversation), a
  policy apply (decision 5), an operator write (decision 7); each
  rebuilds, and nothing else does.
- The framing: the state heading no longer claims to be current; the
  memory section and its framing sentence are present whenever the
  agent may remember, including a conversation that starts with
  nothing saved (review round 1, finding 4); a snapshot built on a
  fresh conversation inserts no note, and one built with history (a
  rebind onto a resumed thread, and an off-to-on policy apply
  mid-conversation) inserts exactly one `(memory re-read here)` before
  the newest user turn.
- The round accounting repeats the snapshot's fact ids and sizes until
  a rebuild.
- With `export_llm_input` on, an operator hard-deleting a fact through
  the memory API between two replies: the next round's exported system
  prompt no longer carries it and its ids leave the round's
  `memory_facts` (review round 1, finding 3); the model's own earlier
  `remember` exchange for it, if any, is still in the exported history,
  which is the documented behavior.
- A read that fails (the store's reader raising) sends the safe empty
  blocks on that round and is not cached: the next round reads again,
  and once the store recovers its snapshot holds the facts (failure
  then recovery, review round 1, finding 2). An empty memory that read
  successfully IS cached (a read-count test), so the two are told
  apart.

**Falsification.** Each new test watched failing first. Mutations, one
run each: the snapshot re-read every round (the byte-identical and
read-count tests must fail); and each key component dropped from the
key in turn (exactly that component's test must fail, which is the
point of one mechanism: removing a component has a distinct, observable
effect).

## The gate (blocking)

Through the real server on gpt-4.1-mini, the rig the placement
experiment used, from a fresh database per session with memory verified
empty before and after:

- **Cache:** a 16-turn session with at least four verified `remember`
  writes, run on `main` and on the branch (old, new, new, old). The
  gate opens when the branch's write-followed rounds cache like its
  ordinary rounds (mean write-followed cached share at least 0.8, at
  most one full miss across its writes), while `main`'s reproduce the
  miss.
- **Behavior:** three sessions each, the first of them starting with
  memory empty: a fact remembered two turns earlier is used; a `set_state` value changed mid-conversation is used
  in its new form, not the snapshot's; a fact `forget`-ten
  mid-conversation is not asserted as true; and a fact saved by a
  second, concurrent session is NOT expected mid-conversation and IS
  present in the next conversation. The branch must answer every probe
  `main` answers, except the concurrent-session one, which is the
  stated cost.

If a gate does not pass, the milestone stops and the result goes to
Rafael.

## Risks

- **A stale ledger read as current.** The main behavioral risk of
  freezing: the model reads the snapshot's old value over the newer
  tool message. Decision 3's framing and the gate's `set_state` probe
  address it.
- **A missed invalidation.** Decision 1's key check makes it a rebuild
  instead of a wrong answer.
- **Concurrent sessions.** The stated cost (decision 4).

## Standing lenses

- *No-leak*: nothing new reaches any surface.
- *Pin before reshaping*: the per-round read is pinned by a test of what
  two rounds send today, committed before the change and inverted with
  it.
- *Closed sets*: none added.
- *Honest seams*: the snapshot slot is compared `is not None`.
- *Inventories by tooling*: every caller of `_system_prompt`,
  `with_scopes` and `read_for_prompt` listed by untruncated `git grep -n`.
- *Proportion*: the cheapest-alternative line above.
- *Falsify before claiming*: the mutations above.

## Documentation footprint

- `runtime/pipeline.py` and `runtime/prompt.py` docstrings (decision 4).
- `docs/architecture/observability-surfaces.md`: the memory section's
  clock, the content-export sentence that memory "is read per round",
  and the deletion section's statement of what a hard deletion stops
  and what it does not (decision 7).
- `docs/concepts.md` (the `set_device_location` paragraph, "the
  record says so from the very next reply"): the record still does;
  what the agent is told is the tool's answer in the conversation,
  and the device block in its prompt follows at its next snapshot.
- `docs/architecture/design-guide.md` (the prompt module's worked
  example: the pipeline "appends memory per round"): per activation on
  a conversation, by key.
- The event catalog's notes that describe memory as a per-round read
  (`events/catalog.py`, around the `llm_round` memory fields, the
  prompt-assembled note and `memory_unreadable`'s "this round"), with
  `docs/reference/events.md` regenerated through its generator, never
  by hand. The inventory is taken with an untruncated
  `git grep -n -i -E "per.round|every round|this round" -- vinga-server/src docs ':!docs/plans/*'`
  recorded in the implementation section, and each hit is either
  changed or noted as describing the round accounting, which stays
  per round (decision 8).
- `changelog.d/536-memory-per-conversation.md` under `### Changed`.

Historical plans keep their wording; they describe what was decided
when they were written.

## Milestones

- [ ] **M1: memory is read once per conversation.** Decisions 1 to 6,
  their tests and mutations, the gate, the documentation footprint. One
  pull request; it closes #536.

## Plan review round

Reviewed 2026-10-03 by openai/gpt-6-sol, thinking high via codex CLI 0.160.0, read-only sandbox, runtime 5m13s, at commit d5a83f2f, plan blob 5f930cf6.

---

1. **P1: Tool results do not survive into the next reply.** Evidence: the plan says memory tool results remain in history (`docs/plans/2026-10-03-memory-per-conversation.md:50`). The runtime keeps structured tool turns only in a reply-local `working` copy (`vinga-server/src/vinga_server/runtime/pipeline.py:1772`); an existing test explicitly confirms they are absent from later history (`vinga-server/tests/unit/test_session_tools.py:211`). With a frozen snapshot, a later reply can receive neither the new fact nor the result that announced it. **The plan should specify how memory changes remain visible across independent replies**, including corrections and removals, and test the provider’s actual request on a later reply whose user utterance and spoken answer do not repeat the changed value.

   *Resolution* (2026-10-04, anthropic/claude-opus-5-5, thinking medium): resolved by #599, merged as PRs #600 to #602. Memory tool calls and their answers now stay in the history, structured, for the rest of the session and are rebuilt on resume; "Where this starts from" says so. The test the finding asks for is added: a later reply's provider request, after a turn whose utterance and spoken answer do not repeat the value, carries the `remember`, `set_state` and `forget` exchanges that changed it, while the system prompt is byte-identical to the snapshot's.

2. **P2: A failed first read becomes a conversation-long empty snapshot.** Evidence: `MemoryStore._read` reports a failure by class and returns `NOTHING_REMEMBERED` (`vinga-server/src/vinga_server/memory/store.py:681`); the plan caches the resulting `RoundPrompt` until activation or rebind (`docs/plans/2026-10-03-memory-per-conversation.md:62`). A short database outage would therefore make memory disappear for the rest of a long conversation, even after recovery. **The plan should distinguish a successful empty read from a failed read**, keep the current safe empty reply on failure, and retry snapshot construction on a later reply. Test failure followed by recovery.

   *Resolution* (2026-10-04, anthropic/claude-opus-5-5, thinking medium): accepted as decision 6. `PromptMemory` says whether its read completed; an incomplete read sends today's safe empty blocks and is never cached, so the next round retries and the first complete read becomes the snapshot. Tests cover failure then recovery, and a successful empty read being cached.

3. **P2: Hard deletion gains an undocumented future disclosure path.** Evidence: the plan defers operator changes until the next conversation and claims nothing new reaches a surface (`docs/plans/2026-10-03-memory-per-conversation.md:84`). Today the operator API is the hard-deletion door (`docs/architecture/observability-surfaces.md:183`), while enabled LLM input export sends each round’s prompt outward (`docs/architecture/observability-surfaces.md:541`). A frozen prompt can send a *new copy* of a deleted secret on every later round. **The plan should state this consequence and give operators a concrete way to stop an affected live conversation before deleting sensitive content**, then test the documented behavior with export enabled.

   *Resolution* (2026-10-04, anthropic/claude-opus-5-5, thinking medium): accepted, and narrowed rather than only documented. Decision 7 bumps an in-process operator revision on every operator write, hard deletion included, and the snapshot's key carries it, so a deleted fact leaves the prompt and the export from the next round (one replica, per the topology ADR, makes an in-process signal complete). What it cannot reach is stated on the observability page: an exchange this session's model wrote stays in the session's history and export until the session ends, and the operator's way to stop it is deleting the thread and ending the session. Tested with export enabled.

4. **P2: The proposed framing can be absent or give the wrong precedence.** Evidence: `with_scopes` returns the know-how half unchanged when all scope blocks are empty (`vinga-server/src/vinga_server/runtime/prompt.py:528`), but the plan requires its new snapshot sentence only when a memory block exists (`docs/plans/2026-10-03-memory-per-conversation.md:116`). Its gate starts with empty memory. Also, a memory-policy change rebuilds the snapshot mid-conversation (`docs/plans/2026-10-03-memory-per-conversation.md:91`), making “as it stood when this conversation started” false; older history updates need not outrank that new snapshot. **The plan should define framing for an empty snapshot and describe precedence relative to the snapshot’s actual capture time.** Test both an initially empty conversation and an off-to-on policy apply.

   *Resolution* (2026-10-04, anthropic/claude-opus-5-5, thinking medium): accepted. Decision 3 renders the memory section whenever the agent may remember, empty included, and ties precedence to the capture point rather than the conversation's start; a snapshot built while the thread has history is marked by one fixed `(memory re-read here)` note before the newest user turn, which the framing names. Tests cover an initially empty conversation and an off-to-on policy apply, and the gate's first behavior session starts empty.

5. **P2: The documentation footprint leaves live claims false.** Evidence: `docs/concepts.md` promises a renamed or moved device is reflected in the very next reply (`docs/concepts.md:170`). The event catalog and its generated reference call memory a per-round read (`vinga-server/src/vinga_server/events/catalog.py:2720`); the design guide describes the same clock (`docs/architecture/design-guide.md:205`). None is in the plan’s documentation footprint. **The milestone should update current-facing clock and device-freshness claims and regenerate the event reference**; historical plans can remain historical.

   *Resolution* (2026-10-04, anthropic/claude-opus-5-5, thinking medium): accepted. The documentation footprint now names `docs/concepts.md`'s device paragraph, the design guide's prompt example and the event catalog's per-round memory notes (with the event reference regenerated by its generator), plus an untruncated grep whose hits are each changed or noted in the implementation section. Historical plans stay as written.

6. **P2: One required falsification cannot fail as specified.** Evidence: the plan requires both a `(agent, conversation)` check at read time and explicit rebind invalidation (`docs/plans/2026-10-03-memory-per-conversation.md:62`), then says removing rebind invalidation *must* fail the rebind test (`docs/plans/2026-10-03-memory-per-conversation.md:121`). The key check would rebuild on that rebind, so the test should still pass. **The plan should assign rebind safety to one mechanism and test its removal**, or name a same-key scenario in which explicit invalidation has a distinct effect.

   *Resolution* (2026-10-04, anthropic/claude-opus-5-5, thinking medium): accepted. Decision 1 now has one mechanism, the key, with no invalidation calls. The key is an activation counter, the conversation id, the memory policy and the store's operator revision; each component has a test in which only it changes, and the falsification drops each component in turn, so each mutation has exactly one test that must fail.

**Verdict: not ready.** The plan’s across-reply behavior depends on history that the runtime deliberately does not retain.

**Status (2026-10-03):** finding 1 (tool results do not survive into the next reply) is the premise this plan relied on, and it is false today. Rafael decided to revise that rule first, as #599; this plan resumes once #599 has landed, and findings 2 to 6 are resolved then.
