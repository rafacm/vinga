# Give the session's conversations one owner

Plan for [#484](https://github.com/rafacm/vinga/issues/484), as widened
on 2026-09-23 (issue comment 5789579615). Its companion is
`docs/plans/2026-09-23-session-conversations-owner-implementation.md`,
one section per milestone, appended in the same change that ticks the
milestone.

**Local baseline:** not applicable. No conversational capability
changes: every transition keeps its current behavior, and what moves is
where the state that decides it lives.

**Cheapest alternative:** moving only the active pair off
`SessionEvents`, as the issue's original direction literally reads.
Measured at `0fcc5c26`: the pair is written at 3 sites, all in
`PipelineRuntime` (`_activate_agent` twice, `_move_to` once), and read
through two properties at 59 sites in `runtime/pipeline.py`, 7 in
`device/session.py` and 11 in `runtime/filler_runner.py`. Moving it
alone is those two properties' bodies, the edge's three properties, the
filler runner's eleven reads, the stub runtime's two writes and the
factory's signature. It leaves the other conversation state where it
is: `_conversations`, `_histories` and `_acknowledged` plus
`_settled`'s bounded wait, 17 sites in `pipeline.py`, with the three
transitions coded in `_activate_agent`, `_move_to` and `_select`. What
the widened owner buys over that is the one thing #482 M3 needs and the
pair alone does not give: the extracted reply core reaches those 17
sites, so without this owner it would have to take a temporary protocol
over four runtime fields, which this issue would then redo. The price
is one module of roughly 150 lines and its unit tests, inside the one
PR the pair alone would also need.

**Attribution:** anthropic/claude-opus-5-5, thinking high; Claude Code
2.1.280; 2026-09-23.

## Goal

One object owns the live side of a session's conversations: which
thread each agent is on, the in-memory history of every thread the
session has been on, the store's handle for the last turn written to
each, and which agent and thread are active now. Its transitions are
its methods, each holding its own ordering. The events object stops
being where that state lives and takes what it emits as values at the
emit site, which is what every emitter already does. The device edge
and any second runtime (#92) learn the owner's interface rather than
the event subsystem's.

Nothing a person running vinga can observe changes: no event, field,
log line, stored row or spoken sentence. That is a claim the
milestone proves with pins committed before the move.

## The issue's decisions, restated

- **One owner, one source of truth.** Duplicating the pair on the
  device and runtime objects is explicitly not the fix.
- **The owner holds** the per-agent current thread (`_conversations`),
  the per-thread histories (`_histories`), the write handles
  (`_acknowledged`), and the active pair.
- **Its transitions are its methods:** continue an agent's own thread
  on a handover, start a new one, reactivate a past one with the
  history the store returned.
- **Stays outside:** agent activation (providers, prompt know-how,
  endpointer), the offer protocol `resumption.py` owns, and storage,
  which stays in `conversations/threads.py`.
- **No user concept.** Keyed per device session and per agent. The
  issue says a user "can later sit above it without reshaping it", and
  that is not quite so, stated here rather than inherited: on a shared
  device the current-thread map's key becomes (speaker, agent), and
  `activate` gains a speaker. The owner stays one per device session;
  its key widens. Nothing here models a user now.
- **#489's bookkeeping** is recorded as the issue asks, count either
  way.

## Resolutions and design decisions

### Where the owner lives, and who constructs it

`vinga_server/session_conversations.py`, class `SessionConversations`:
the conversations of one **device session**. A session in vinga is one
connection episode from one device (the glossary's *Session*): powering
the board off ends it, and the next connect is a new session that
starts a new conversation with the device's default agent. A past
conversation comes back only through the conversation tools (#190), so
this object's lifetime is exactly the connection's. Its docstring says
"device session" in those words, because vinga has no user concept and
a bare "session" invites a reader to supply one.

A top-level module, beside `boundary.py` and `generation.py`, rather
than inside a package, for two measured reasons (raised by Rafael
before the review round landed). **Not `conversations/`:** that package
is the conversation store; its `__init__` imports `store.py` and with
it SQLAlchemy, the database layer and the background writer, so a
module placed there drags storage into every import of an object that
takes none. The one type it needs from there, `Acknowledgement`, is
imported under `TYPE_CHECKING`, since `conversations.records` runs the
same `__init__`. And `session.py` would be a second module of that name
beside the edge's `device/session.py`. **Not `runtime/`:** the import
direction today runs one way, `runtime/` imports `device/boundary.py`
and nothing under `device/` imports `runtime/`, and the edge constructs
this owner, so a home under `runtime/` would invert it. At the top
level both sides import it and neither imports the other.

**The edge constructs it and hands it to the runtime factory**,
beside the `SessionEvents` it already hands over. Rejected: the runtime
constructing it and exposing it on `SessionInput`. The reason is #92,
the issue this one gates: a session spans agents, and #92 selects a
runtime per device and per agent, so a handover can cross runtimes.
The conversations belong to the session and must outlive whichever
runtime is serving the active agent; the connection is the only object
with that lifetime. A second reason is the edge's own reads: it stamps
`speaking_started` and writes the capture manifest's `agent` about a
pair it never chose, and reading it off the object it constructed is
honest where reading it off the runtime would make the edge ask the
runtime about the session.

### The interface

Named here so the review can price it; the implementer may rename
within the plan's intent and records any rename.

```python
@dataclass(frozen=True)
class Active:
    agent: str
    conversation: str

class SessionConversations:
    def __init__(self, device: str) -> None: ...
    device: str                       # read-only property
    active: Active | None             # read-only property
    def history(self) -> list[Turn]   # the active thread's, mutable
    def activate(self, agent: str) -> Active
    def start_new(self, conversation: str) -> None
    def reactivate(self, conversation: str, history: Sequence[Turn]) -> None
    def acknowledge(self, conversation: str, handle: Acknowledgement) -> None
    async def settled(self, conversation: str) -> None
    def current_threads(self) -> tuple[str, ...]
```

- `activate` is the handover and the connect: the agent's thread in
  this session, minted the first time and continued on every later
  activation, becomes active. It is today's `setdefault` line, moved.
- `start_new` and `reactivate` are the two moves that change which
  thread the active agent is on. Both rebind the agent's current
  thread, set the active pair, and install a history (a fresh empty
  list, or a copy of what the store returned), in one synchronous
  call with no await inside, which is the ordering rule today's
  `_move_to` keeps by being synchronous and now keeps by construction.
- **Minting.** Today a conversation id is minted in two places,
  `_activate_agent` and `_select`, each `uuid.uuid4().hex`. Both move
  into this module, as one module-level `mint()` that `activate` also
  uses. `_select` must still decide the id before the boundary,
  because the `_Transition` it returns carries it and the turn that
  ends the leg is recorded before the move applies; so the
  new-conversation arm keeps carrying an id, gets it from `mint()`
  rather than from `uuid` directly, and `start_new` takes that id
  rather than minting a second one. One shape of id, one home for it.
- `acknowledge` and `settled` are `_acknowledged`'s write and
  `_settled`'s bounded wait, with `RESUME_ACKNOWLEDGEMENT_S` moving
  beside them. The issue asks that reactivation go "through the one
  method that also knows about the pending write". It cannot be one
  method, and the plan says why rather than papering over it: the wait
  must precede the store read, the read is `resumption.py`'s, and the
  history the read returns is what `reactivate` installs, so the read
  sits between the two by necessity. What the owner does give is one
  home for both halves of the rule, which today are 1,000 lines apart
  in `pipeline.py`.
- `current_threads()` answers the close path's purge (`pipeline.py`
  line 1125), which today reads `self._conversations.values()`: each
  agent's CURRENT thread, not every thread the session touched. The
  name says so, and a test pins that a thread replaced by `start_new`
  or `reactivate` is excluded. Whether the purge should reach replaced
  threads is a behavior question and not this issue's.
- `device` is the session identity half of the issue title. See the
  next decision.

### The factory's new signature

`RuntimeFactory` (`device/boundary.py`) is a positional callable, and
the owner takes the third position, directly after the events object
it stands beside and before everything it does not:

```python
RuntimeFactory = Callable[
    [DeviceOutput, SessionEvents, SessionConversations, Sequence[str],
     "Generation", "LiveDevice | None"],
    SessionInput,
]
# bespoke_runtime_factory's inner builder:
def build(output, events, conversations, agents, generation, device=None): ...
```

The owner is required, with no default at any layer: not in the
protocol, not in `build`, not in `PipelineRuntime.__init__`, and no
runtime ever constructs a fallback owner of its own, because a runtime
that could make one would be a second authority the moment a caller
forgot to pass it. The trailing `device` record keeps its `None`
default, so direct callers that omit it today (`test_boundary_contract.py`
lines 298-304) change only by the one inserted argument. The comment
above the protocol gains the owner's paragraph, in the style of the
two it already has. The runtime holds it as a public attribute,
`conversations`, as the stub already holds `events`, so tests reach it
through the interface. `test_boundary_contract.py` asserts that the
runtime the edge built holds the identical object the edge constructed
(`is`, not equality), which is the proof that one owner crosses the
seam rather than a copy.

### The device MAC

Today the edge writes the MAC to `SessionEvents.device` at the
handshake (`device/session.py` line 433), `SessionEvents._identities`
stamps every event with it, and the runtime reads it back through a
property (`pipeline.py` `_device`) as the fallback address for device
memory where no device record was resolved.

Decision: **the owner is constructed by the edge the moment the MAC is
normalized, it is the one authority for the device from then on, and
the events object takes a write-once snapshot of it for emission.**

- The edge constructs `SessionConversations(device=mac)` on the line
  that normalizes the MAC today (`device/session.py` line 433), which
  is before the binding lookup and the no-agent rejection
  (lines 478-491) that name the device; the owner needs nothing but
  the normalized value. Every later edge read (the rejections, the
  capture manifest, the factory call) reads `owner.device`. The edge
  keeps no `_mac` copy: its `_mac` property reads the owner, and
  answers None only before normalization, where there is no owner.
- `SessionEvents.device` stops being a settable attribute. The edge
  hands it the owner's value once, through a write-once method
  (`identify(device)`, name the implementer's), which refuses a second
  call; `_identities` keeps stamping from it. That is a snapshot in the
  literal sense: taken once from the authority, never written back,
  never read by domain code.
- The runtime's `_device` fallback reads the owner. Nothing outside
  `events/` reads `SessionEvents.device` afterwards, which the
  milestone's closing grep proves.
- A connection whose Device-Id does not normalize never gets an owner
  and emits its rejection with no device, as today.

Rejected: keeping the runtime's read of `events.device`, the hidden
seam this issue exists to close; and the plan's first shape, an edge
field plus an owner value plus a settable events attribute, which the
review round showed was three copies resting on a false premise (that
the rejections precede any possible owner).

### The events object afterwards

`SessionEvents.agent` and `.conversation` are deleted. Nothing inside
`events/` reads them (its `_identities` stamps session and device
only; measured, the only reads are outside the package), so the
object needs no replacement: every emitter already builds its payload
at the emit site, `Identifier(...)`, `ConversationId(...)`, and afterwards
it reads the pair from the owner there. The `FillerRunner` is
constructed with the owner beside the events object and reads the
active agent there (its clip lookups by agent and its three emits).

### `_turns` stays, as a one-line read

`PipelineRuntime._turns` becomes `return self._conversations.history()`.
Kept rather than inlined at its five sites because three tests reach
it (census: `tests/support/sessions.py` 2, `test_boundary_contract.py`
1), and inlining it would add three reach-in lines for no gain. #482 M3 inherits the question of whether the reply
core takes the owner directly, which is where it belongs.

### What does not change, deliberately

In-session reactivation rebuilds a thread from the store rather than
from the in-memory copy, so a thread has two histories kept in step
only by the bounded wait. Rebuilding from the store is the general
case, not the exception: a conversation from an earlier device session
has no in-memory copy at all, and coming back to one is the ordinary
way a user resumes. The in-session return is the special case where a
second copy happens to exist. The owner makes that visible in one place
and the plan records it there in the module docstring, but it does not
change it: preferring the in-memory copy is a behavior change (the
store's copy is budgeted and hydrated; the in-memory one is not) and
belongs to its own issue if anyone wants it.

### One milestone, cut into reviewable commits

The plan first proposed two: M1 moving the state inside the runtime
with a one-helper mirror onto the events object, M2 taking the pair
off the events object. The review round showed M1 would have merged
exactly the duplication the issue forbids, and not a harmless one: the
filler runner selects its clips by the mirrored agent, so the mirror
is domain state, not an emission stamp. The move is therefore one
milestone and one PR, with no intermediate state on `main`. What the
two-milestone cut was for, a reviewer reading the seam change apart
from the state move, is kept inside the milestone instead: the pins and the owner module
land as commits of their own, and the move itself is one commit whose
body walks the seam change before the state move. Each commit is green
on its own.

## Module layout

- New: `src/vinga_server/session_conversations.py`
  (`SessionConversations`, `Active`, `mint`, `RESUME_ACKNOWLEDGEMENT_S`).
- Changed: `runtime/pipeline.py` (fields, `_activate_agent`,
  `_move_to`, `_select`, `_settled` removed, the recording site, the
  close purge, `_device`, the class docstring's field list),
  `runtime/resumption.py` (its "deliberately NOT here" paragraph points
  at the owner), `device/session.py`, `device/boundary.py`
  (the `RuntimeFactory` protocol), `runtime/filler_runner.py`,
  `events/__init__.py`, `tests/support/boundary.py`,
  `tests/support/telemetry.py`.

## Tests

- **New unit tests for the owner**, `tests/unit/test_conversation_owner.py`,
  through its interface only: activation mints then continues (A, B,
  back to A is A's first thread); `start_new` and `reactivate` rebind
  only the active agent's thread and install their history; the
  installed history is a copy (mutating the source afterwards changes
  nothing); `history()` answers the active thread's list and appends
  land there; `settled` returns immediately for an unacknowledged
  thread, and for an acknowledged one waits OFF the event loop, as
  `_settled` does today with `asyncio.to_thread(landed.wait, ...)`. Its
  test uses a handle whose `wait` blocks on a `threading.Event` the test
  controls and records its argument, runs a heartbeat task on the loop
  while `settled` is pending, asserts the heartbeat advanced before the
  handle is released, then releases it and asserts the recorded
  argument is exactly `RESUME_ACKNOWLEDGEMENT_S` (which pins the timeout
  as the default policy). Falsified by a mutation that calls `wait`
  directly on the loop: the heartbeat stalls and the test fails; `current_threads()` lists each
  agent's current thread and excludes one a move replaced. No storage: the module takes none, and
  a test needing a database here is a design defect.
- **Pins before each move**, committed green first and byte-unchanged
  after. The existing suites already drive the transitions end to end
  (`test_session_conversations.py`, `test_conversations_session.py`,
  `test_session.py`, `test_boundary_contract.py`); the implementer
  inventories which of these assert the `(agent, conversation)` pair on
  the emitted events across connect, handover, handover back, new and
  resume, and adds one characterization pin where that sequence is not
  already asserted exactly (typed payload values, not rendered text).
  The same holds for the edge's `speaking_started` and the
  capture manifest's `agent`, and for the filler runner's three emits,
  if not already pinned.
- **Pair reads across an await, gated.** Two readers take the pair
  after an await a handover can land in: the edge's `send_audio`
  awaits `_pacer.transmit()` before `_speaking_started()` reads the pair
  (`device/session.py` lines 1423-1426 and 1278-1304), and the filler
  runner, a task of its own, reads it at several points around its
  output awaits (`runtime/filler_runner.py` lines 196-288 and
  451-497). Today each read is of the present value at its site. The
  pins hold that deterministically: the test suspends the pacer's
  transmit (and, separately, the filler's output) on an
  `asyncio.Event`, changes the active pair while it is held, releases
  it, and asserts the exact typed attribution of every emission after
  the gate, which today is the pair as it stands at the read. Written
  and green against today's code in the pins commit, byte-unchanged
  after. Falsified by a mutation that snapshots the pair on entry to
  `send_audio` (and to the filler's fire) instead of reading it at the
  emit site: that mutation must fail the pin, one run each, since the
  gate makes the interleaving deterministic rather than probable.
- **Falsification.** Each new owner test is watched failing against a
  mutation of the rule it names (continue becomes always-mint; install
  aliases instead of copies; `settled` skips the wait; `settled` waits on the loop; `reactivate`
  rebinds a different agent), one run each since all four are
  straight-line logic, and the commit body says so. A mutation that
  survives is reported as a finding about the test.
- The stub runtime in `tests/support/boundary.py` activates its first
  agent through the owner, which is the proof that a runtime
  that is not a pipeline learns the owner's interface and nothing of
  the event subsystem's; `test_boundary_contract.py`'s two reads of
  `runtime.events.agent`/`.device` move to the owner.
- The reach-in census, expected delta stated rather than claimed
  byte-identical: `tests/unit/test_session_conversations.py
  _acknowledged 1` is removed, because line 994 becomes
  `session.runtime.conversations.acknowledge(...)`, a public attribute
  and a public method, which adds no line. `_turns` stays, so its
  three lines stay. Any other added or removed line is a deviation the
  implementation doc explains, most likely a new test that reached a
  private name, which is a review flag rather than a manifest update.
  Regenerated with `uv run python -m tests.census.test_reach_ins`,
  never hand-edited, and the command-spellings manifest checked the
  same way since the plan adds an ADR.

## Risks and mitigations

- **A pair read in the window between two writes.** Today the pair is
  written in two statements (`_agent`, then `_conversation`); after
  this change the owner sets one frozen `Active`, so no reader can see
  a new agent with the old thread. That is strictly tighter; the pins
  confirm nothing depended on the gap.
- **A reader of the old fields left behind.** The milestone closes
  on a grep, run without truncation, proving no
  `events.agent`/`events.conversation`/`events.device` read remains
  in `src/` or `tests/` outside `events/`.
- **Hidden readers of the events fields.** The inventory above is a
  grep over `src` and `tests` at `0fcc5c26`; the milestone reruns it on its own
  base and records the count, and deleting the attributes turns any
  missed reader into an `AttributeError` the lanes catch.
- **The factory signature is a seam other code constructs against.**
  Two builders exist (`bespoke_runtime_factory`, the stub); the
  milestone greps, untruncated, for every `RuntimeFactory` implementer
  and every call site, and records the count, so an argument inserted
  in the wrong position is found by a type check or a lane rather than
  by a positional mix-up that happens to type-check.
- **No-leak.** Conversation ids are server-minted metadata and the MAC
  is already an event identity; no new value reaches any surface.
  Nothing here composes an exception message.

## Documentation footprint

- The `PipelineRuntime` class docstring's field list (in
  code), `resumption.py`'s module docstring. No hand-maintained page
  under `docs/` describes where these fields live: the glossary's
  *Handover* entry describes behavior, which is unchanged, and
  `docs/system-overview.md` says nothing about placement. Stated here
  so the footprint is explicit rather than implied.
- A new ADR, `docs/adr/2026-09-23-the-session-owns-its-conversations.md`,
  recording that the active pair left the events object and why the
  2026-08-10 placement's rationale (both sides must see one activation
  at one moment) is kept by the owner rather than by the events
  object. `docs/adr/2026-08-10-normalize-the-hardware-edge.md` keeps
  its body and gains a status-line note that its "active-agent
  attribution" clause is superseded, the partial-supersession shape
  `2026-08-04-json-logs-are-the-observability-surface.md` already
  uses. The `SessionEvents` docstring. No generated reference changes,
  since no event or field changes.
- **Changelog:** none. Nothing a person running vinga can observe
  changes, and the changelog records notable changes to what they run.

## #489's bookkeeping

The seven files the #489 comment (on this issue, 2026-09-20) assigns to
this issue's territory, all under `vinga-server/tests/unit/`:
`test_session_events.py`, `test_session_conversations.py`,
`test_conversations_session.py`, `test_session_close_reason.py`,
`test_session_recap.py`, `test_session_memory_policy.py`,
`test_events_live_wiring.py`.

The instrument, fixed here so before and after are measured the same
way, run from `vinga-server/tests/unit`:

```bash
RE='support\.stores|support import stores|clean_store|blank_database|throwaway_database|module_database|spare_database|packaged_database|ConversationStore|vinga_server\.db\b|vinga_server\.conversations\.store|\bstore_at\b'
for f in test_session_events.py test_session_conversations.py \
         test_conversations_session.py test_session_close_reason.py \
         test_session_recap.py test_session_memory_policy.py \
         test_events_live_wiring.py; do
  printf '%s %s\n' "$(grep -cE "$RE" "$f")" "$f"
done
```

Baseline at `0fcc5c26`: 0, 1, 12, 0, 1, 2, 1 matching lines in that
order, so **five of the seven name a storage helper or import
somewhere**. That already disagrees with the comment's premise that
these files "name no storage at all", measured on `10dfb58f` with an
instrument the comment does not record. The matches are mostly
`tests.support.stores` imports (`StoredThreads`, the lane's memory
store), which name storage at the file's top and not in any signature
of the subject under test. So the milestone records two columns per
file: (a) the count above, mechanical; and (b) whether storage reaches
the object under test through a parameter the test visibly passes,
judged per file with the line cited. Column (b) is the one #489's
mechanism is about.

The prediction written down now, so it can be wrong: **neither column
moves.** The owner takes no storage, and these tests reach the
database through the recorder and the resumption flow, neither of
which this issue touches. If that holds, it is evidence against #489's
premise for this seam, and the implementation doc says so in those
words, together with the instrument disagreement above.

## Milestones

- [ ] **M1: the session's conversations get one owner.** Commits in
  this order, each green on its own:
  1. Pins: the characterization and gated tests under "Tests" that
     the existing suites do not already cover, green against today's
     code.
  2. `session_conversations.py` and its unit tests, falsified as
     "Tests" states.
  3. The move, as ONE commit, because no split of it can be green
     without the fallback owner or the mirror this plan forbids: the
     runtime cannot read a required owner before the factory passes
     one, and the factory cannot pass one before the edge constructs
     it. In that commit: the edge constructs the owner at
     normalization and passes it to the factory; `RuntimeFactory`,
     `bespoke_runtime_factory`, `PipelineRuntime` and the stub runtime
     take it; `_conversations`, `_histories`, `_acknowledged` and
     `_settled` leave `PipelineRuntime`; `_activate_agent` calls
     `activate`, `_move_to` calls `start_new` or `reactivate`,
     `_select` and activation mint through the module, the recording
     site calls `acknowledge`, the close purge reads
     `current_threads()`, and `_agent`, `_conversation` and `_device`
     read the owner; the edge, the filler runner and the test support
     read it; `SessionEvents.agent` and `.conversation` are deleted and
     `.device` becomes write-once. The commit body walks the diff in
     that order (seam, runtime state, readers, events object) so a
     reviewer can read the seam change apart from the state move, which
     is what the earlier two-commit split was for.
  4. The ADR and the 2026-08-10 status-line note; the docstrings in
     the documentation footprint; the census manifest regenerated;
     #489's count in the implementation doc.

  Design footprint: adds one module whose callers stop having to know
  that a thread has a history, a write handle and an agent binding
  kept in three maps that must agree, and in what order a move
  updates them; changes one seam, the factory, which now hands a
  runtime the device session's conversations beside its events, and
  which is what #92's second runtime learns; makes `SessionEvents`
  shallower in the right direction, since it stops holding domain
  state. Documentation footprint as above.

## Plan review round

Reviewed 2026-09-23 by openai/gpt-5.6-sol, thinking high via codex CLI 0.156.0, read-only sandbox, runtime 14m47s, at commit ca7b9e8a, plan blob bfb72f2a.

---

1. **P1: `threads()` changes shutdown behavior by purging historical threads.** Evidence: the plan says `threads()` lists “every thread minted or installed” (`Tests`, lines 231-242), but today `PipelineRuntime.close()` purges only `self._conversations.values()`, the current thread for each agent (`runtime/pipeline.py:1123-1125`). `start_new` and `reactivate` replace that per-agent value (`runtime/pipeline.py:2083-2090`). Returning every historical thread would delete additional memory rows when recording is disabled, contradicting the behavior-preserving and “no stored row changes” claims. The plan should define this as `current_threads()` returning exactly `tuple(current_by_agent.values())`, with a test proving a replaced thread is excluded. Purging all touched threads belongs in a separate behavior-change issue.

   *Resolution:* Accepted. Renamed `current_threads()`, defined as each agent's current thread, with a test that a replaced thread is excluded. Measured while resolving: the divergence is not reachable today, since the purge is wired only where nothing is recorded (`bespoke_runtime_factory` passes `memory.purge_threads` only when `conversations is None`) and the thread reads that enable `start_new`/`reactivate` exist only when something is (`app.py` line 635). The two sets are therefore equal on every deployment that purges, and the rename keeps them so by definition rather than by that coincidence.

2. **P1: The proposed MAC placement still has multiple authorities.** Evidence: the plan stores the MAC in `SessionConversations.device`, a new edge `_mac` field, and `SessionEvents.device` (`The device MAC`, lines 149-169). The issue explicitly rejects duplicated identity state. The rationale that rejection events occur before an owner can exist is false: normalization completes at `device/session.py:433`, while agent rejection occurs at `device/session.py:478-491`, and the proposed owner constructor needs only the normalized device. The plan should construct the owner immediately after successful normalization, use `owner.device` for subsequent edge work and the factory, avoid a persistent edge `_mac` copy, and make the event value a write-once observability snapshot. The invalid-Device-Id path can continue emitting with no owner and no device.

   *Resolution:* Accepted as proposed. The owner is constructed at normalization, it is the device's one authority after that, the edge keeps no copy, and `SessionEvents` takes the value once through a write-once method in place of a settable attribute. Its `device` is now `str`, not `str | None`: there is no owner before a device.

3. **P2: M1 lands the duplication the issue says not to introduce.** Evidence: M1 stores the active pair in the owner while mirroring it into mutable `SessionEvents` fields, which the edge and `FillerRunner` continue reading (`Why two milestones`, lines 201-214; M1, lines 326-337). Those reads include clip selection, so this is not merely an immutable emission snapshot. The plan should wire the owner through the factory and remove the event pair atomically in one milestone, or otherwise ensure no independently stored pair is merged to `main`.

   *Resolution:* Accepted, by the first of the two remedies offered: one milestone and one PR, no mirror, nothing duplicated on `main` at any point. The reviewer's point that the filler runner selects clips by the mirrored agent is what decides it: the mirror would have been domain state. The separation the two milestones were for is kept as an ordered commit sequence inside the milestone. This also removes one PR round from the wall time.

4. **P2: The pins do not exercise pair reads across existing await boundaries.** Evidence: `DeviceSession.send_audio()` awaits `_pacer.transmit()` before `_speaking_started()` rereads the active pair (`device/session.py:1423-1426`, `1278-1304`). `FillerRunner` also reads the pair at different points around output awaits (`runtime/filler_runner.py:196-288`, `451-497`). A reply can hand over while the separate filler task is suspended. The listed tests cover a handover completed before playback, not a transition while delivery is held. The plan should require deterministic gated tests that change the owner while pacing or filler playback is suspended and assert the exact pre-existing attribution at each emission point. A mutation that snapshots the pair on entry rather than at the present read site must fail.

   *Resolution:* Accepted. The Tests section now requires gated pins for the two readers that cross an await, the pacer and the filler runner, asserting present-read attribution after a pair change while suspended, with the snapshot-on-entry mutation as the falsification. One run each is stated as sufficient because the gate removes the scheduling nondeterminism rather than sampling it.

5. **P2: The acknowledgement test would not catch event-loop blocking.** Evidence: current `_settled()` explicitly uses `asyncio.to_thread(landed.wait, RESUME_ACKNOWLEDGEMENT_S)` (`runtime/pipeline.py:2802-2822`). The proposed recording fake only verifies that `wait(2.0)` was called; a direct blocking call would pass both it and the existing 50 ms `LateStore` case (`test_session_conversations.py:939-999`). The plan should state that `settled()` retains the off-loop wait and add a gated-handle plus heartbeat test proving the loop continues while also asserting the exact timeout argument.

   *Resolution:* Accepted. `settled` keeps the off-loop wait, and its test is now a gated handle plus a loop heartbeat, asserting both that the loop kept running and the exact timeout argument; the on-loop mutation is added to the falsification list.

6. **P2: The changed factory contract is not specified concretely enough.** Evidence: `RuntimeFactory` is currently a positional callable with an optional final device argument (`device/boundary.py:261-291`), and direct callers omit that final argument (`test_boundary_contract.py:298-304`). The plan says only that the factory “takes” the owner. It should state the exact signature, with a required `SessionConversations` beside `SessionEvents` and before the optional device argument, and explicitly forbid a default that constructs a fallback owner inside a runtime. The boundary test should assert that the runtime received the identical owner held by the edge.

   *Resolution:* Accepted. The plan now states the exact signature (owner third, after `SessionEvents`, before the agents; the trailing device record keeps its default), forbids a default or a runtime-constructed fallback owner at every layer, makes the owner a public `conversations` attribute on the runtime, and requires the boundary test to assert identity with `is`.

7. **P2: The required #489 inventory is unavailable from the plan.** Evidence: `#489's bookkeeping`, lines 313-322, refers to “the seven files the #489 comment lists” without naming them or giving a reproducing command. That list is not recorded elsewhere in this checkout, so the milestone cannot be completed or reviewed from the repository alone. The plan should enumerate all seven paths and state the exact before/after classification and counting command.

   *Resolution:* Accepted. The seven paths are enumerated and the counting command is committed with its baseline (0, 1, 12, 0, 1, 2, 1 at 0fcc5c26). Measuring it surfaced a disagreement worth recording: five of the seven already name a storage helper, against the #489 comment's "name no storage at all", so the plan records two columns, the mechanical count and a per-file judgement of whether storage reaches the subject through a visible parameter, which is the one #489's mechanism concerns.

8. **P3: The reach-in census expectation contradicts itself.** Evidence: the plan says M1 leaves `reach-ins.txt` byte-identical (`_turns stays`, lines 182-189; `Tests`, lines 265-269), then says the `_acknowledged` reach-in is removed. Reaching the owner through a private runtime field may also add a replacement reach-in. The plan should state the expected M1 manifest delta and regenerate it, rather than claim byte identity.

   *Resolution:* Accepted. The expected delta is stated: one line removed, none added, because the owner is reached as a public attribute (finding 6's resolution) through public methods. Anything else is recorded as a deviation.

**Verdict: ready after the P1/P2 amendments.**

## Plan review round 2 (re-review of the resolutions)

Reviewed 2026-09-23 by openai/gpt-5.6-terra, thinking high via codex CLI 0.156.0, read-only sandbox, runtime 4m24s, at commit e7f3f75b, plan blob 81a4d5d0.

---

1. **P1: The promised green commit sequence cannot supply the required owner.**

   *Resolution:* Accepted. The runtime move and the seam move are one commit (step 3), with its body ordered seam, runtime state, readers, events object, so the separation a reviewer wanted survives as reading order rather than as commits that could not each be green. The pins and the owner module stay separate commits before it.
Evidence: Plan “The factory’s new signature” says `SessionConversations` is required in `PipelineRuntime.__init__`, `build`, and the protocol, with no fallback (lines 176-205). But M1 step 3 moves the runtime to read that owner, while step 4 only later changes `DeviceSession`, `RuntimeFactory`, and `bespoke_runtime_factory` to construct and pass it (lines 467-486). Today the factory has no owner parameter and constructs `PipelineRuntime` itself (`vinga-server/src/vinga_server/runtime/pipeline.py:3529`); the edge is the only proposed constructor (`vinga-server/src/vinga_server/device/session.py:504`). Step 3 therefore either fails from a missing required argument or needs exactly the fallback/mirror the plan forbids.
What the plan should say instead: make the runtime move and seam/edge move one atomic green commit, including factory signature, owner construction, all readers, and deletion of event-pair fields. Retain the preceding owner-module and pin commits as separate green commits.

2. **P2: The write-once event snapshot has no test.**
Evidence: The MAC decision requires `SessionEvents.identify(device)` to refuse a second call (plan lines 215-230), yet the Tests section specifies owner, transition, and await-boundary tests only (lines 308-375). Existing event tests cover an initially absent device and a single assignment, not that a later write cannot replace it (`vinga-server/tests/unit/test_event_typed_emit.py:209`, `vinga-server/tests/unit/test_event_typed_emit.py:234`). An implementation that accidentally permits a later `identify` to overwrite the event identity would satisfy the named tests.
What the plan should say instead: add a `SessionEvents` unit test that identifies once, verifies emitted identity, attempts a second identification, verifies the defined refusal and that a subsequent emission still carries the first device. The refusal must use a fixed, value-free message if it raises.

Verdict: ready after the P1/P2 amendments.
