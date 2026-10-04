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

Measured at `677fd921` (`main` on 2026-10-03), and re-verified at
`62fa62d4` (2026-10-04, after #599): the reply loop still calls
`_system_prompt` on every round (`pipeline.py:1819`, the method at
`pipeline.py:2501`, its store read at `:2568`), so the premise holds;
line numbers below are from the first measurement and have shifted.
`with_scopes` has a second caller, the operator's prompt preview
(`app.py:1164`), which reads memory as a new session would; decision 3's
always-present memory section reaches it too, and its tests move with
it.

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
   one. The key is compared, and a snapshot built, only at the first
   round of a leg (the first round of a reply, and the first round after
   a move); every later round of the leg sends the leg's snapshot
   unchanged whatever happens meanwhile (review round 2, finding 1). So
   a snapshot is always read before anything this leg's model does, and
   its capture point is never in the middle of a leg's tool exchanges. There are no invalidation calls to forget. The key is four
   values, each with its own reason and its own test:
   - an **activation counter**, bumped by `_activate_agent` (so a
     handover, and a handover back to the same agent on the same
     conversation, rebuilds, as the know-how half already does);
   - the **conversation id** (so a rebind to another thread rebuilds
     and one thread's ledger is never served on another);
   - the **memory policy** the snapshot was built under (decision 5);
   - the **erasure revision** (decision 7), sampled before the
     snapshot's reads begin and stored with it, never replaced by a
     later value (review round 2, finding 3): an erasure that commits
     while the reads are in flight leaves the snapshot keyed with the
     older revision, so the next leg's first round finds the key stale
     and reads again. The reads may have caught the erasure or not;
     either way the stale key guarantees a re-read after it.
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

   The capture point is visible to the model, and whether it needs
   marking is decided from the thread's actual history, never from
   what caused the rebuild (review round 2, finding 2: a handover back
   to an agent resumes that agent's thread with its history, so "a
   handover starts clean" is not a rule the marker may rely on). A
   snapshot is built at a leg's first round, when the history ends with
   the turn that opened the leg (the user's words, or a move's seed).
   If nothing precedes that turn, the start is the point and no note is
   added. If anything does, the pipeline inserts one fixed note in the
   assistant's voice, `(memory re-read here)`, into the thread's history
   immediately before that opening turn, and the framing sentence names
   that note as the point. Since the snapshot is read before the leg's
   first round and nothing of the leg exists yet, every tool exchange
   before the note predates the read and every one after it follows
   the read, which is the precedence the framing states. A
   rebuild already changes the system prompt, so the provider cache is
   lost at that round either way, and the note changes only the
   history's tail. The note is a constant in `runtime/prompt.py` with
   the headings; the framing's exact wording is the implementer's,
   checked by the behavior gate.
4. **What is given up, stated where the contract was.** The
   `_system_prompt` and `with_scopes` docstrings, and the observability
   page's memory section, say the clock is per activation now and what
   that costs: a fact saved or a device moved during this conversation
   by a different live session's model, or by an operator's correction
   or device change, is seen from this session's next conversation,
   not its next reply. A hard deletion is not in that cost; decision 7
   makes it reach the next reply. An appended
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
   so does the device record read (review round 2, finding 5).
   `DeviceBindings.record_now` today answers `LiveDevice | None` and
   falls back to the served configuration's record when the database
   read fails, which a caller cannot tell from a real answer.
   `resolve_record` (its one async caller, `pipeline.py`'s device read
   for the prompt) gains a result that carries the same record it
   returns today, fallback included, beside `complete: bool`, false
   exactly on the arm that fell back because the read failed. The
   record the prompt uses is unchanged in every case; only whether the
   snapshot may be kept changes. A snapshot is kept only when both
   reads were complete, and the device read is still made, and still
   decides, when the agent's memory is off (the device block is part
   of the prompt either way). A round whose
   read was incomplete sends exactly what it sends today (the safe
   empty blocks, the reply happens) and caches nothing, so the next
   leg's first round reads again (decision 1: reads happen only
   there); the first complete read becomes the snapshot. A short outage
   therefore costs the replies it lasts, rather than the rest of the
   conversation.
7. **A hard deletion reaches the next reply; other operator changes
   reach the next conversation.** Review round 2 (finding 4) priced the
   general version: every operator door (memory API writes, device
   record changes through the config store, which the model's own
   relocation also uses, thread erasure through its own listener)
   would need its own publication point and its own exclusion of model
   writes. The problem round 1 raised is narrower than that: a deleted
   fact being sent, and exported, again. So only hard deletion
   publishes. `MemoryStore` gains an **erasure revision**, an integer
   held in the process-wide store instance with `erased()` to bump it
   and a property to read it. The four erase routes in `memory/api.py`
   (`erase_agent_fact`, `erase_device_fact`, `erase_agent_memory`,
   `erase_device_memory`, which share the two helpers around
   `store.erase_fact` and `store.erase_facts`) call it after the
   writer's transaction has committed and only when it removed
   something, through a callable the composition hands `ApiRuntime`
   (the same store instance every session reads). Nothing else bumps
   it: no model write, no correction through the API, no device change,
   no thread erasure, so none of them costs a live conversation its
   cache. One process is enough for this to be complete: the server
   runs one replica, as its topology ADR records (#316), and the API
   and every session share it. Operator corrections and device changes
   join decision 4's stated cost: seen from the next conversation.

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
  policy apply (decision 5), a hard deletion (decision 7); each
  rebuilds at the next leg, and nothing else does.
- The framing: the state heading no longer claims to be current; the
  memory section and its framing sentence are present whenever the
  agent may remember, including a conversation that starts with
  nothing saved (review round 1, finding 4); a snapshot built on a
  fresh conversation inserts no note, and one built with history (a
  rebind onto a resumed thread, and an off-to-on policy apply
  mid-conversation) inserts exactly one `(memory re-read here)` before
  the newest user turn; a handover away and back to an agent whose
  thread has history inserts the note too, and the gate-style probe
  (a value corrected between the two activations) shows the model
  preferring the snapshot over the older tool result before the note
  (review round 2, finding 2); an operator hard deletion landing
  between a memory tool's result and the same reply's continuation
  round changes nothing in that reply (the leg keeps its snapshot) and
  takes effect at the next reply's first round, with the note placed
  before that reply's user turn, after the earlier exchange (review
  round 2, finding 1).
- The round accounting repeats the snapshot's fact ids and sizes until
  a rebuild.
- The erasure revision moves on each of the four erase routes when they
  remove something, and stays put on an erase that removed nothing, on
  an API correction, on a device rename through the config API, on a
  thread erasure, and on the model's own `forget` and
  `set_device_location` (review round 2, finding 4).
- An erasure committed while a snapshot's reads are in flight (a
  controlled interleaving: the fake reader bumps the revision between
  the device read and the memory read) leaves that snapshot keyed with
  the older revision, and the next leg reads again (review round 2,
  finding 3).
- With `export_llm_input` on, an operator hard-deleting a fact through
  the memory API between two replies: the next round's exported system
  prompt no longer carries it and its ids leave the round's
  `memory_facts` (review round 1, finding 3); the model's own earlier
  `remember` exchange for it, if any, is still in the exported history,
  which is the documented behavior.
- A read that fails (the store's reader raising) sends the safe empty
  blocks on that round and is not cached: the next leg reads again,
  and once the store recovers its snapshot holds the facts (failure
  then recovery, review round 1, finding 2). The same for a device
  read that fell back to the served configuration: that leg sends the
  fallback record, the next leg reads again and the snapshot then
  holds the stored record, with memory on and with memory off (review
  round 2, finding 5). An empty memory that read
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

## Plan review round 2

Reviewed 2026-10-04 by openai/gpt-6-sol, thinking high via codex CLI 0.160.0, read-only sandbox, runtime 5m03s, at commit f8d57d6c, plan blob 7022fc4c.

---

1. **P1: The re-read marker can put an older tool result after the snapshot boundary.** Evidence: the plan places `(memory re-read here)` immediately before the newest user turn (plan, decision 3 (`docs/plans/2026-10-03-memory-per-conversation.md:113`)). A tool exchange can follow that user turn before the next round (pipeline.py:1819 (`vinga-server/src/vinga_server/runtime/pipeline.py:1819`), pipeline.py:1930 (`vinga-server/src/vinga_server/runtime/pipeline.py:1930`)). If an operator changes or deletes memory between those rounds, the old exchange appears *after* the marker and falsely outranks the new snapshot under the plan’s own framing. **Amendment:** place the boundary at the actual read point in the outgoing history. Test an operator correction and hard deletion between a memory tool’s result and the same reply’s continuation request.

   *Resolution* (2026-10-04, anthropic/claude-opus-5-5, thinking medium): accepted by moving the read rather than the marker. Decision 1 now builds or replaces a snapshot only at a leg's first round, before anything of the leg exists, and later rounds of the leg keep it; so the read point is always just before the leg's opening turn, which is where decision 3 places the note, and no exchange can sit after the note while predating the read. A failed read is therefore retried at the next leg rather than the next round (decision 6 updated). The test drives a hard deletion between a tool result and the same reply's continuation.

2. **P1: A handover back does not start with clean history.** Evidence: the plan exempts handovers from the re-read marker because they “start clean” (plan:113 (`docs/plans/2026-10-03-memory-per-conversation.md:113`)), but `SessionConversations.activate` resumes that agent’s existing conversation and history (session_conversations.py:176 (`vinga-server/src/vinga_server/session_conversations.py:176`)). The plan itself requires rebuilding on a handover back. **Amendment:** decide whether a marker is needed from the thread’s actual history, including on return to an agent, and test precedence as well as the rebuilt system prompt.

   *Resolution* (2026-10-04, anthropic/claude-opus-5-5, thinking medium): accepted. Decision 3 now decides the note from the history alone: if anything precedes the leg's opening turn, the note goes in, whatever caused the rebuild. The handover-back test checks the note and the model's precedence, not only the system prompt.

3. **P1: The revision key needs an ordering rule around the reads.** Evidence: the plan promises that hard deletion leaves the next round’s prompt (plan:153 (`docs/plans/2026-10-03-memory-per-conversation.md:153`)), while `_system_prompt` awaits a device read and then a memory read (pipeline.py:2562 (`vinga-server/src/vinga_server/runtime/pipeline.py:2562`)). If the revision is captured *after* those reads, a deletion can commit between the read and key capture; stale content is then cached under the new revision. **Amendment:** specify that the key’s revision is sampled before either read and never replaced by a later value, or retry when it changes during construction. Add a controlled interleaving test with a deletion.

   *Resolution* (2026-10-04, anthropic/claude-opus-5-5, thinking medium): accepted as the first option. Decision 1's key samples the erasure revision before the reads and keeps it, so a deletion during the reads leaves a stale key and a re-read at the next leg. The interleaving test bumps the revision between the device read and the memory read.

4. **P2: Operator revision publication needs named integration points.** Evidence: memory API writes use `ApiRuntime.memory_writes`, not `MemoryStore` (memory/api.py:415 (`vinga-server/src/vinga_server/memory/api.py:415`)); device config writes use another store, whose relocation path the model also uses (config/api.py:2765 (`vinga-server/src/vinga_server/config/api.py:2765`), config/store.py:1036 (`vinga-server/src/vinga_server/config/store.py:1036`)); thread erasure publishes through its own listener path. The plan names these doors but does not say how each publishes only after commit while excluding model writes. Its single operator-write test cannot establish that coverage. **Amendment:** name the callback wiring and publication point for each door, including thread purge and device record changes, and test each class of write plus a model relocation that must leave the revision unchanged.

   *Resolution* (2026-10-04, anthropic/claude-opus-5-5, thinking medium): accepted by narrowing rather than wiring every door, which the proportion test favors. Only hard deletion publishes, because a deleted fact being re-sent is the problem round 1 raised; corrections, device changes and thread erasure join decision 4's stated next-conversation cost. Decision 7 names the one publication point (the four erase routes in `memory/api.py`, after commit and only when something was removed, through a callable the composition hands `ApiRuntime`, bumping `MemoryStore`'s erasure revision). The test checks each erase route moves it and that every other write class, the model's relocation included, leaves it alone.

5. **P2: Device-read failure cannot currently be distinguished from its fallback.** Evidence: decision 6 says the device read reports completeness (plan:141 (`docs/plans/2026-10-03-memory-per-conversation.md:141`)), but `resolve_record` returns only `LiveDevice | None`; `record_now` silently uses the served-world fallback when the database read fails (device/bindings.py:364 (`vinga-server/src/vinga_server/device/bindings.py:364`)). A transient failure could freeze that fallback even if the later memory read succeeds. The proposed failure test exercises only the memory reader. **Amendment:** specify a device-read result that carries completeness without losing the existing fallback, and test device failure followed by recovery, including with agent memory switched off.

   *Resolution* (2026-10-04, anthropic/claude-opus-5-5, thinking medium): accepted. Decision 6 now has `resolve_record` return the same record as today, fallback included, beside `complete`, false only on the arm that fell back because the read failed; a snapshot is kept only when both reads completed. The test covers device failure then recovery with memory on and off.

6. **P2: The deletion guidance describes too narrow a history path and an unsafe action order.** Evidence: decision 7 discusses only a fact this session wrote with `remember`, then tells the operator to delete the thread and end the live session “in that order” (plan:166 (`docs/plans/2026-10-03-memory-per-conversation.md:166`)). A retained `recall` result can also contain the fact (builtin.py:889 (`vinga-server/src/vinga_server/tools/builtin.py:889`)); deleting the stored thread leaves the live history available for another exported round. **Amendment:** document all retained exchanges that can carry deleted content, and say to stop the live session before deleting its stored thread when the aim is to prevent another disclosure. Test a prior `recall` as well as `remember`.

7. **P2: The only milestone omits two required decisions.** Evidence: M1 explicitly includes “Decisions 1 to 6” yet says its PR closes #536 (plan:310 (`docs/plans/2026-10-03-memory-per-conversation.md:310`)). Decisions 7 and 8 require operator freshness and truthful round accounting. **Amendment:** make both explicit M1 deliverables with their tests and documentation.

**Verdict: ready after the P1/P2 amendments.**
