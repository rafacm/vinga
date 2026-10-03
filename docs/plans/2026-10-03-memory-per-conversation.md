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

1. **One snapshot per agent activation on a conversation.** The
   `RoundPrompt` (device record, the three scopes, the fact ids the
   metadata half reports) is built at the first round after the agent
   is activated or the session rebinds to another conversation, and
   reused for every later round of that activation on that
   conversation. It is invalidated, and rebuilt at the next round, by
   exactly two events: `_activate_agent` (which also rebuilds the
   know-how half, so the system prompt changes there anyway) and the
   conversation rebind. Keyed by the pair it belongs to (agent,
   conversation), checked where it is read, so a missed invalidation
   cannot serve one conversation another's ledger.
2. **What the model writes mid-conversation reaches it as the messages
   it already is.** No re-read and no added message: each memory tool's
   result in the history states the change. Decision 3 tells the model
   so.
3. **The framing says when the snapshot was taken.** The state block's
   heading stops claiming to be current, and the memory section gains
   one sentence: what it shows is as it stood when this conversation
   started, and anything saved, changed or forgotten in the
   conversation since is more recent and wins. The headings stay
   constants in `runtime/prompt.py`; the exact wording is the
   implementer's, checked by the behavior gate.
4. **What is given up, stated where the contract was.** The
   `_system_prompt` and `with_scopes` docstrings, and the observability
   page's memory section, say the clock is per activation now and what
   that costs: a fact saved or a device moved by a different session, or
   by an operator, during this conversation is seen from this session's
   next conversation, not its next reply. An appended update message
   for those changes is a possible later step, not this plan.
5. **The memory switch keeps its own clock.** Whether the agent may
   remember (`_remembering_now`) is still resolved per reply for the
   tools; the snapshot follows the value it was built under, and the
   snapshot is rebuilt if that value changes between replies (a config
   apply), so the blocks and the offered tools cannot disagree.
6. **The metadata half's accounting stays truthful.** Every round still
   reports the size and fact ids of the prompt it actually sent; with a
   frozen snapshot they repeat until the snapshot is rebuilt, which is
   what the model received.

## Tests

Reuse the session prompt tests (`tests/unit/test_session_prompt.py`),
the memory tool tests, and the event baseline.

- A second round of the same reply, and a second reply on the same
  conversation, send a byte-identical system prompt even after a
  `remember`, a `forget`, a `set_state` and a device rename in between.
- The memory store is read once per activation on a conversation, not
  per round (a counting fake).
- A handover and a conversation rebind each rebuild the snapshot: the
  next round's system prompt reflects a write made before them.
- A snapshot built for one (agent, conversation) is never served for
  another, even with the invalidation deliberately skipped (the key
  check).
- The framing: the state heading no longer claims to be current, and
  the snapshot sentence is present whenever a memory block is.
- The round accounting repeats the snapshot's fact ids and sizes until
  a rebuild.

**Falsification.** Each new test watched failing first. Mutations, one
run each: the snapshot re-read every round (the byte-identical and
read-count tests must fail); the rebind invalidation removed (the
rebind test must fail); the key check removed with the invalidation
also removed (the cross-conversation test must fail).

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
- **Behavior:** three sessions each: a fact remembered two turns
  earlier is used; a `set_state` value changed mid-conversation is used
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
  clock, and the content-export sentence that memory "is read per round".
- `changelog.d/536-memory-per-conversation.md` under `### Changed`.

## Milestones

- [ ] **M1: memory is read once per conversation.** Decisions 1 to 6,
  their tests and mutations, the gate, the documentation footprint. One
  pull request; it closes #536.
