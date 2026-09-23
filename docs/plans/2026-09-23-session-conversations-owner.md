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
is one module of roughly 150 lines and its unit tests, and no second
PR beyond the two the pair alone would already want (see the
milestones for why the move is two).

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
milestones prove with pins committed before each move.

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

**The edge constructs it and hands it to the runtime factory** (M2),
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

### The events object after M2

`SessionEvents.agent` and `.conversation` are deleted. Nothing inside
`events/` reads them (its `_identities` stamps session and device
only; measured, the only reads are outside the package), so the
object needs no replacement: every emitter already builds its payload
at the emit site, `Identifier(...)`, `ConversationId(...)`, and after
M2 it reads the pair from the owner there. The `FillerRunner` is
constructed with the owner beside the events object and reads the
active agent there (its clip lookups by agent and its three emits).

### `_turns` stays, as a one-line read

`PipelineRuntime._turns` becomes `return self._conversations.history()`.
Kept rather than inlined at its five sites because three tests reach
it (census: `tests/support/sessions.py` 2, `test_boundary_contract.py`
1), and M1 is a move that should leave the reach-in manifest
byte-unchanged. #482 M3 inherits the question of whether the reply
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

### Why two milestones

M1 moves state that only the runtime reads; M2 changes the
device/runtime seam (the factory signature, `SessionEvents`' shape,
the stub runtime that proves the boundary) and supersedes one bullet
of an ADR. A reviewer of M2 should be reading a seam change and
nothing else. M1 leaves one explicit transitional line: after each
transition the runtime copies the owner's pair onto the events object
in one helper, so the edge and filler runner keep reading what they
read today. The owner is the single source of truth from M1 on; the
events object is a mirror written by exactly one call site, and M2
deletes both the mirror and its fields. This is the one intermediate
state `main` sees, and it violates no settled decision: there is one
writer and one truth.

## Module layout

- New: `src/vinga_server/session_conversations.py`
  (`SessionConversations`, `Active`, `mint`, `RESUME_ACKNOWLEDGEMENT_S`).
- Changed: `runtime/pipeline.py` (fields, `_activate_agent`,
  `_move_to`, `_select`, `_settled` removed, the recording site, the
  close purge, `_device`, the class docstring's field list),
  `runtime/resumption.py` (its "deliberately NOT here" paragraph points
  at the owner), and in M2 `device/session.py`, `device/boundary.py`
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
  thread and waits on the handle with `RESUME_ACKNOWLEDGEMENT_S` for an
  acknowledged one (a recording fake handle, which pins the timeout
  value as the default-construction policy); `current_threads()` lists each
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
  M2 adds the same pin for the edge's `speaking_started` and the
  capture manifest's `agent`, and for the filler runner's three emits,
  if not already pinned.
- **Falsification.** Each new owner test is watched failing against a
  mutation of the rule it names (continue becomes always-mint; install
  aliases instead of copies; `settled` skips the wait; `reactivate`
  rebinds a different agent), one run each since all four are
  straight-line logic, and the commit body says so. A mutation that
  survives is reported as a finding about the test.
- The stub runtime in `tests/support/boundary.py` activates its first
  agent through the owner in M2, which is the proof that a runtime
  that is not a pipeline learns the owner's interface and nothing of
  the event subsystem's; `test_boundary_contract.py`'s two reads of
  `runtime.events.agent`/`.device` move to the owner.
- The reach-in census: M1 should leave `reach-ins.txt` unchanged
  (`_turns` stays; `_acknowledged`'s one reach in
  `test_session_conversations.py` line 994 becomes a call to
  `acknowledge` through the owner, which removes a line). M2 may move
  lines. Regenerate, never hand-edit.

## Risks and mitigations

- **A pair read in the window between two writes.** Today the pair is
  written in two statements (`_agent`, then `_conversation`); after
  this change the owner sets one frozen `Active`, so no reader can see
  a new agent with the old thread. That is strictly tighter; the pins
  confirm nothing depended on the gap.
- **The mirror outliving M1.** M2 deletes it; the M2 checklist names
  the grep that proves no `events.agent`/`events.conversation` remains
  in `src/` or `tests/`, run without truncation.
- **Hidden readers of the events fields.** The inventory above is a
  grep over `src` and `tests` at `0fcc5c26`; M2 reruns it on its own
  base and records the count, and deleting the attributes turns any
  missed reader into an `AttributeError` the lanes catch.
- **The factory signature is a seam other code constructs against.**
  Two builders exist (`bespoke_runtime_factory`, the stub); M2 greps
  for every `RuntimeFactory` implementer and call site.
- **No-leak.** Conversation ids are server-minted metadata and the MAC
  is already an event identity; no new value reaches any surface.
  Nothing here composes an exception message.

## Documentation footprint

- **M1:** the `PipelineRuntime` class docstring's field list (in
  code), `resumption.py`'s module docstring. No hand-maintained page
  under `docs/` describes where these fields live: the glossary's
  *Handover* entry describes behavior, which is unchanged, and
  `docs/system-overview.md` says nothing about placement. Stated here
  so the footprint is explicit rather than implied.
- **M2:** a new ADR, `docs/adr/2026-09-23-the-session-owns-its-conversations.md`,
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

Recorded in M2's implementation-doc section: for each of the seven
files the #489 comment lists, whether it names storage in a signature
before and after, and the count. The prediction written down now, so
it can be wrong: **the count does not move.** The owner takes no
storage, and those tests reach the database through the recorder and
the resumption flow, neither of which this issue touches. If that
holds, it is evidence against #489's premise for this seam, and the
implementation doc says so in those words.

## Milestones

- [ ] **M1: the owner, inside the runtime.** Pins first. Then
  `session_conversations.py` with its unit tests, and `PipelineRuntime`
  moves `_conversations`, `_histories`, `_acknowledged`, `_settled` and
  the pair's writes onto it: `_activate_agent` calls `activate`,
  `_move_to` calls `start_new` or `reactivate`, `_select` and
  activation mint through the module, the recording site calls
  `acknowledge`, the close purge reads `threads()`, `_agent` and
  `_conversation` read `active`. One helper copies the pair onto
  `SessionEvents` after each transition, so the edge and filler runner
  are untouched. The runtime constructs the owner in M1 (with
  `device=events.device`, read once at construction, which is after the
  handshake wrote it). Design footprint: deepens nothing existing; adds
  one module whose callers stop having to know that a thread has a
  history, a write handle and an agent binding kept in three maps
  that must agree, and in what order a move updates them. Documentation
  footprint as above.
- [ ] **M2: the pair leaves the events object.** Pins first for the
  edge's and filler runner's reads. The edge constructs
  `SessionConversations(device=mac)` and passes it to the runtime
  factory; `RuntimeFactory`, `bespoke_runtime_factory` and the stub
  runtime take it; the runtime stops constructing its own; the edge,
  the filler runner and the test support read the owner;
  `SessionEvents.agent` and `.conversation` and M1's mirror helper are
  deleted; the runtime's `_device` reads the owner. The ADR and the
  status-line note. #489's count. Design footprint: changes one seam
  (the factory now hands the runtime the session's conversations
  alongside its events, which is what #92's second runtime learns),
  and makes `SessionEvents` shallower in the good direction: it stops
  holding domain state it never read.

## Plan review round

Reviewed 2026-09-23 by openai/gpt-5.6-sol, thinking high via codex CLI 0.156.0, read-only sandbox, runtime 14m47s, at commit ca7b9e8a, plan blob bfb72f2a.

---

1. **P1: `threads()` changes shutdown behavior by purging historical threads.** Evidence: the plan says `threads()` lists “every thread minted or installed” (`Tests`, lines 231-242), but today `PipelineRuntime.close()` purges only `self._conversations.values()`, the current thread for each agent (`runtime/pipeline.py:1123-1125`). `start_new` and `reactivate` replace that per-agent value (`runtime/pipeline.py:2083-2090`). Returning every historical thread would delete additional memory rows when recording is disabled, contradicting the behavior-preserving and “no stored row changes” claims. The plan should define this as `current_threads()` returning exactly `tuple(current_by_agent.values())`, with a test proving a replaced thread is excluded. Purging all touched threads belongs in a separate behavior-change issue.

   *Resolution:* Accepted. Renamed `current_threads()`, defined as each agent's current thread, with a test that a replaced thread is excluded. Measured while resolving: the divergence is not reachable today, since the purge is wired only where nothing is recorded (`bespoke_runtime_factory` passes `memory.purge_threads` only when `conversations is None`) and the thread reads that enable `start_new`/`reactivate` exist only when something is (`app.py` line 635). The two sets are therefore equal on every deployment that purges, and the rename keeps them so by definition rather than by that coincidence.

2. **P1: The proposed MAC placement still has multiple authorities.** Evidence: the plan stores the MAC in `SessionConversations.device`, a new edge `_mac` field, and `SessionEvents.device` (`The device MAC`, lines 149-169). The issue explicitly rejects duplicated identity state. The rationale that rejection events occur before an owner can exist is false: normalization completes at `device/session.py:433`, while agent rejection occurs at `device/session.py:478-491`, and the proposed owner constructor needs only the normalized device. The plan should construct the owner immediately after successful normalization, use `owner.device` for subsequent edge work and the factory, avoid a persistent edge `_mac` copy, and make the event value a write-once observability snapshot. The invalid-Device-Id path can continue emitting with no owner and no device.

   *Resolution:* Accepted as proposed. The owner is constructed at normalization, it is the device's one authority after that, the edge keeps no copy, and `SessionEvents` takes the value once through a write-once method in place of a settable attribute. Its `device` is now `str`, not `str | None`: there is no owner before a device.

3. **P2: M1 lands the duplication the issue says not to introduce.** Evidence: M1 stores the active pair in the owner while mirroring it into mutable `SessionEvents` fields, which the edge and `FillerRunner` continue reading (`Why two milestones`, lines 201-214; M1, lines 326-337). Those reads include clip selection, so this is not merely an immutable emission snapshot. The plan should wire the owner through the factory and remove the event pair atomically in one milestone, or otherwise ensure no independently stored pair is merged to `main`.

4. **P2: The pins do not exercise pair reads across existing await boundaries.** Evidence: `DeviceSession.send_audio()` awaits `_pacer.transmit()` before `_speaking_started()` rereads the active pair (`device/session.py:1423-1426`, `1278-1304`). `FillerRunner` also reads the pair at different points around output awaits (`runtime/filler_runner.py:196-288`, `451-497`). A reply can hand over while the separate filler task is suspended. The listed tests cover a handover completed before playback, not a transition while delivery is held. The plan should require deterministic gated tests that change the owner while pacing or filler playback is suspended and assert the exact pre-existing attribution at each emission point. A mutation that snapshots the pair on entry rather than at the present read site must fail.

5. **P2: The acknowledgement test would not catch event-loop blocking.** Evidence: current `_settled()` explicitly uses `asyncio.to_thread(landed.wait, RESUME_ACKNOWLEDGEMENT_S)` (`runtime/pipeline.py:2802-2822`). The proposed recording fake only verifies that `wait(2.0)` was called; a direct blocking call would pass both it and the existing 50 ms `LateStore` case (`test_session_conversations.py:939-999`). The plan should state that `settled()` retains the off-loop wait and add a gated-handle plus heartbeat test proving the loop continues while also asserting the exact timeout argument.

6. **P2: The changed factory contract is not specified concretely enough.** Evidence: `RuntimeFactory` is currently a positional callable with an optional final device argument (`device/boundary.py:261-291`), and direct callers omit that final argument (`test_boundary_contract.py:298-304`). The plan says only that the factory “takes” the owner. It should state the exact signature, with a required `SessionConversations` beside `SessionEvents` and before the optional device argument, and explicitly forbid a default that constructs a fallback owner inside a runtime. The boundary test should assert that the runtime received the identical owner held by the edge.

7. **P2: The required #489 inventory is unavailable from the plan.** Evidence: `#489's bookkeeping`, lines 313-322, refers to “the seven files the #489 comment lists” without naming them or giving a reproducing command. That list is not recorded elsewhere in this checkout, so the milestone cannot be completed or reviewed from the repository alone. The plan should enumerate all seven paths and state the exact before/after classification and counting command.

8. **P3: The reach-in census expectation contradicts itself.** Evidence: the plan says M1 leaves `reach-ins.txt` byte-identical (`_turns stays`, lines 182-189; `Tests`, lines 265-269), then says the `_acknowledged` reach-in is removed. Reaching the owner through a private runtime field may also add a replacement reach-in. The plan should state the expected M1 manifest delta and regenerate it, rather than claim byte identity.

**Verdict: ready after the P1/P2 amendments.**
