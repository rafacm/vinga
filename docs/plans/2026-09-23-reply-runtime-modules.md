# Give tool execution, provider watching and the reply in flight owners

Plan for [#482](https://github.com/rafacm/vinga/issues/482), as
re-scoped on 2026-09-23 (issue comment of 05:26Z, which supersedes the
withdrawn narrowing above it). Its companion is
`docs/plans/2026-09-23-reply-runtime-modules-implementation.md`, one
section per milestone, appended in the same change that ticks the
milestone.

**Local baseline:** not applicable. No conversational capability
changes: every milestone is behavior-preserving, and what moves is
which module owns a responsibility the runtime already has.

**Cheapest alternative:** leaving the clusters where they are and
making the reach-ins honest by renaming the five tool methods the
tests call (`_reserve_tools`, `_run_one`, `_classified`,
`_timeout_for`, `_for_execution`) to public names on
`PipelineRuntime`. That is about ten lines and removes six reach-in
sites from the manifest. What it does not buy is the thing the issue
is about: `PipelineRuntime` would still be 3,517 lines whose reader
holds tool execution's nine fields and provider watching's seven in
mind while reading the reply, and the public names would widen the
runtime's interface with verbs no caller but a test needs, which is
depth going the wrong way. The two modules below take roughly 780 lines
out of the class (505 for tool execution with its helpers, 277 for
watching, measured below) behind interfaces of six and six verbs, and
the tests land on those. For M3 the cheapest alternative was priced
before this plan and chosen: see "M3: the reply in flight" below, where
the re-scope's full extraction of the reply core is the rejected
alternative and its numbers are recorded.

**Attribution:** anthropic/claude-opus-5-5, thinking high; Claude Code
2.1.280; 2026-09-23.

## Goal

`runtime/pipeline.py` loses two responsibilities it holds today by
discipline, each to a module of its own whose callers stop having to
know how it works: executing one round's tool calls, and watching a
provider call for failure and for a stalled first token. Then the reply
in flight gets one owner: a value made when a reply starts and dropped
when the next one does, holding the task, the first-writer-wins outcome
latch, cancel-and-await, drain, and the reply's own state, so that the
resets the class docstring asks a reader to hold in mind become true by
construction.

Nothing a person running vinga can observe changes: no event, field,
log line, stored row, spoken sentence or timing bound. Each milestone
proves that with pins committed before its move.

## The issue's decisions, restated

From the issue body and the re-scope comment, not re-litigated here:

- **Depth is the measure** (`docs/architecture/design-guide.md`):
  callers learn less while a cohesive implementation owns more.
- **Not the direction:** scattering individual methods into small
  classes; a universal runtime framework; a declared state machine (the
  analysis on #31: the task handle is the source of truth, and a
  machine would be a second copy of it).
- **The existing seams are preserved:** `TurnTaking`, `FillerRunner`,
  prompt assembly, `ToolSource`, `CaptureAudio`, `ReplyPacer`,
  `IdleWatchdog`.
- **Three milestones.** M1 tool execution, M2 provider watching, both
  independent of #484 and of each other. M3 the reply core onto #484's
  owner, gated on the reach-back measured after #484 being a handful of
  methods; if it is not, M3 stops and says so. The gate was measured for
  this plan and passes (below); what M3 then builds was narrowed by
  Rafael on 2026-09-23, before this plan was committed, to the reply in
  flight, on the numbers recorded under M3.
- **Per-reply state has three lifetimes**, as the re-scope's correction
  measured: task, outcome latch and utterance id per started reply
  (`start_reply`); round counter and the spoke/withheld pair per
  speaking pass (`_speak_reply`); the memory permission per agent leg
  (`_tool_loop`). The turn record is replaced at every move. M1 and M2
  touch none of them. M3 keeps the per-leg and per-move clocks and
  folds the first two into one, on a measured argument (under M3) that
  a speaking pass is exactly one per reply today; that is the one
  place this plan refines a statement in the issue thread, and it says
  so there.
- **The #489 bookkeeping** is recorded when M3 lands (or when M3 stops),
  since M1 and M2 move no storage into any signature.

## Measurements this plan rests on

Taken at `612030fe` (after #484), by reading the source and by the
commands named with each number; the M3 reach-back by an AST script
recorded in the implementation doc's M3 gate section.

- `runtime/pipeline.py` is **3,517 lines**, 81 top-level and method
  definitions (`grep -n -E '^    (async )?def |^class |^def |^async
  def '`, full output counted).
- **Tool execution**, the M1 cluster: `_tool_snapshot` (L2257),
  `_for_execution` (L2276), the plain half of `_run_tools` (L2316),
  `_run_one` (L2820), `_reserve_tools` (L2876), `_classified` (L2884),
  `_dispatch` (L2910), `_timeout_for` (L2962), `_offered_origins`
  (L3063), `_withheld` (L3096), `_report_withheld` (L3117), and the
  module-level `_coercions`, `_tool_fragment`, `_tool_arguments_coerced`,
  `_tool_called`, `_Origin`, `_UNKNOWN_ORIGIN`, `_sentence_withheld`,
  `DEFAULT_TOOL_TIMEOUT_S`. It reads `_sources`, `_output` (only
  `device_tools()`), `_mcp_servers` (only `owner_of`), `_events`,
  `session_id`, `_turn`, the active pair, and `_remembering_now`; it
  writes one field, `_reply_withheld`, from `_report_withheld`.
- **Provider watching**, the M2 cluster: `_watching` (L1122),
  `_watched_stream` (L1143), `_watchdog_stream` (L1178),
  `_llm_round_done` (L1272), `_provider_failed` (L1346), and
  `FirstTokenTimeout`. It reads `_events`, `_llm_input`,
  `_server.llm_first_token_timeout_s`, the active pair, `_llm_round`,
  and writes the turn record through `_turn.round_done`. Its callers:
  the reply's ASR (L1525), the tool loop's reply stream (L2166) and its
  round report (L2202), the recap round (L2614, L2630, L2654), the
  sentence synthesis (L3172), and `confirm_transcript` (L3381).
- **Tests that reach these by name** (`grep -rn -E` over `tests/` for
  every name above, 45 lines written to a file and counted, then read
  in full): `test_session_tools.py` calls `_reserve_tools` (2),
  `_run_one` (1), `_classified` (1), `_timeout_for` (1) and
  `_for_execution` (1), which are the manifest's six reach-in sites in
  this territory; `test_tts_lookahead.py` replaces `_run_tools` (1);
  `tests/tools/event_baseline.py` and `test_event_baseline.py` name six
  emit identities by qualname (`PipelineRuntime._watchdog_stream`,
  `._llm_round_done`, `._provider_failed`, `._for_execution`,
  `._run_one`, `._report_withheld`); `test_session_tools.py` also
  monkeypatches `pipeline_module.DEFAULT_TOOL_TIMEOUT_S` and reads
  `pipeline_module.MAX_TOOL_ROUNDS`. The remaining hits are prose, or a
  same-named helper in an unrelated file (`test_memory_api.py`'s
  `_watching`, the census's `_classified`).
- **Documentation footprint**, measured with `git grep` over everything
  outside `tests/`, `docs/plans/` and `CHANGELOG.md`: no hand-maintained
  page under `docs/` describes these methods as current behavior.
  What names them is source prose: `events/assembly.py` (L29, L187
  name `pipeline.py`'s `_tool_fragment` as the naming decision's home),
  `providers/base.py` L313 (`_watchdog_stream` consumes
  `StreamStarted`), `runtime/turntaking.py` L405 (`_watching("asr",
  ...)`), `tests/support/providers.py` L86, and the class docstring's
  own field inventory. `docs/features/2026-08-19-no-leak-sweep.md`
  names `_watching` and is a dated feature doc, historical by the
  taxonomy in `docs/README.md`, so it is left alone.

## Resolutions and design decisions

### M1: `runtime/tool_execution.py`

**What its callers stop having to know:** how a call is classified,
reserved, coerced, bounded, dispatched to the source that owns it,
reported, and filed on the turn's record; where an offered tool came
from; and what a withheld sentence is reported as. The reply knows it
has an offer, calls, and results.

The interface, named so the review can price it (the implementer may
rename within this intent and records any rename):

```python
@dataclass(frozen=True)
class Offer:
    """What one agent leg offers, taken once: the tools, their declared
    schemas by published name, and each one's origin."""
    tools: tuple[ToolDef, ...]
    schemas: Mapping[str, dict[str, Any]]
    origins: Mapping[str, Origin]

class ToolExecution:
    def __init__(
        self,
        sources: tuple[ToolSource, ...],
        device_tools: Callable[[], Sequence[ToolDef]],
        owner_of: Callable[[str], str | None],
        events: SessionEvents,
        conversations: SessionConversations,
        remembering: Callable[[], bool],
    ) -> None: ...
    def offer(self, agent: str) -> Offer
    def withheld(self, sentence: str, offer: Offer) -> bool
    def reserve(self, turn: TurnUnderway, calls: Sequence[ToolCall]) -> list[int]
    def for_execution(self, turn, call, slot, offer) -> ToolCall
    async def run(self, turn, calls: Sequence[tuple[int, ToolCall]]) -> list[ToolResult]
    def timeout_for(self, classified: ToolInvocation) -> float
```

Decisions inside it:

- **`Offer` replaces three parallel values.** `_tool_loop` takes
  `tools`, then `schemas` from them, then `origins` from them, on three
  lines whose comments each argue they must be taken together. One
  frozen value built by one method makes "taken on the same line" true
  by construction, and it is what `withheld` and `for_execution` take.
- **The turn is an argument, not a field.** Every method that files on
  the record takes the `TurnUnderway` it files on. Today it reads
  `self._turn`, which is replaced at a move; within one round's
  execution it is the same object (a move's replacement happens at the
  boundary in `_speak_reply`, after `_run_tools` has returned), so
  passing it is equivalent, and it removes the one piece of reply state
  the module would otherwise need a back-reference for.
- **The moves stay in the runtime.** `_run_tools` keeps its split of
  plain calls from moves and its move loop, because a move rebinds
  conversations and ends the loop, which is reply-core work; it hands
  the plain half, with slots, to `run`, which keeps today's order
  exactly: `names.ORDERED_TOOL_NAMES` one at a time in issue order,
  then the rest concurrently, results back in the model's order.
  `test_tts_lookahead.py`'s replacement of `_run_tools` stays valid.
- **The withheld flag stays reply state.** `withheld` reports and
  answers True; the runtime's two sentence sites set `_reply_withheld`
  through one small runtime method that asks the module, because the
  flag spans legs (an offer is per leg) and belongs to M3's territory,
  not to tool execution's. That method is not a pass-through: it is
  where a leg's answer becomes a reply-wide fact.
- **Collaborators narrowed to the questions asked.** The module is
  handed `device_tools` and `owner_of` as callables rather than the
  whole `DeviceOutput` and `McpServers`, since those are the only two
  things it asks of them, both asked at the moment of asking (a board
  can rediscover and an apply can replace the registry between two
  calls, which is why they are callables and not snapshots). The
  sources tuple is still built in `PipelineRuntime.__init__`, since
  `BuiltinTools` is handed runtime methods (`_memory_context`,
  `_remembering_now`) and the resumption state; the module receives it.
- **The pair is read at emit time**, through `conversations.active`
  inside each emit's thunk, exactly as `self._agent` is read today.
  Captured earlier, a handover landing between reservation and result
  would change which agent an event is attributed to.
- **Moves with it:** `DEFAULT_TOOL_TIMEOUT_S` (the runtime imports it
  back for `BuiltinTools`, `DeviceTools`, `McpTools` and `Resumption`,
  so it keeps one home), `_coercions`, `_tool_fragment`,
  `_tool_arguments_coerced`, `_tool_called`, `_Origin` (as `Origin`,
  since `Offer` exposes it), `_UNKNOWN_ORIGIN`, `_sentence_withheld`.
  The unparseable-arguments warning line moves with `_dispatch`, and
  its `session_id` comes from `events.session_id`. `MAX_TOOL_ROUNDS`
  stays in the runtime: it bounds the loop, not an execution.

### M2: `runtime/provider_watch.py`

**What its callers stop having to know:** how a failing provider call
is reported without being swallowed, how an LLM stream is told apart
from its consumer's failures, how the first token is bounded and
retried once, and what a finished round reports and files.

```python
class FirstTokenTimeout(TimeoutError): ...

class ProviderWatch:
    def __init__(
        self,
        events: SessionEvents,
        conversations: SessionConversations,
        first_token_timeout_s: float,
        llm_input: "LlmInputExport | None",
    ) -> None: ...
    @asynccontextmanager
    async def watching(self, stage: str, provider: object) -> AsyncIterator[None]
    def watched(self, provider, events, *, invocation, purpose) -> AsyncIterator[Any]
    def reply_stream(self, provider, make_stream, *, invocation, round_: int) -> AsyncIterator[LlmEvent]
    def reply_round_done(self, turn, round_: int, provider, working, began, first_token_at, usage, *, invocation) -> None
    def recap_round_done(self, provider, working, began, first_token_at, usage, *, invocation) -> None
    def failed(self, stage, provider, exc, elapsed, *, invocation=None, purpose=None) -> None
```

Decisions inside it:

- **The round counter is an argument.** `_watchdog_stream` reads
  `self._llm_round` for the retry line and `_llm_round_done` reads it
  for the round's number. Both become a `round_` the tool loop passes,
  the value it has just incremented. The counter itself stays reply
  state (per speaking pass), for M3.
- **Two round reports, not one with a flag.** `_llm_round_done` today
  takes a `purpose` and an optional `round_`, and three of the four
  combinations are meaningful only by convention: a reply round counts
  on the turn and numbers itself from the counter, a recap round does
  neither and reports no round number. Two methods make the invalid
  combinations unrepresentable: `reply_round_done` takes the turn and
  the round and files `round_done` on it; `recap_round_done` takes
  neither. The events they emit are byte-identical to today's, which
  the pins below prove.
- **The first-token bound is taken at construction.** It is read from
  the server section, the file half that no reload replaces (the
  constructor comment on `_server` says so), so a constructor value is
  the same answer at every call.
- **The pair is read at emit time**, as in M1, for the same reason.
- **`FirstTokenTimeout` moves with it**, and `pipeline.py` does not
  re-export it: its only readers outside the module are prose and the
  `error` string it produces, which is the class's `__name__` and does
  not change.

### The per-reply state the two milestones leave behind

Neither M1 nor M2 moves `_turn`, `_llm_round`, `_reply_withheld`,
`_remembering` or anything else with a reply lifetime: each is passed
in at the call. That is deliberate. Moving them is M3's question, and
answering it in M1 or M2 would be the bundling the re-scope rejected,
done by accident.

### M3: the reply core, gated

**The gate, measured.** An AST walk of `PipelineRuntime` at `612030fe`
(the script and its full output are recorded in M3's implementation-doc
section) over the 34 reply-core methods, the 11 tool methods and the 5
watch methods. The reply core is **1,611 lines**; the tools cluster 505
with its helpers; watching 277; the 14 methods left over 445, of which
`__init__` is 249. What the core calls outside itself and the two
clusters is **5 methods**: `_activate_agent` and `_world_of`, which hold
logic, and `_agent`, `_conversation` and `_device`, which are one-line
reads of `conversations`. The gate asked for a handful, and passes.

**What passing does not settle, and what was decided instead.** The
gate measures calls, and the full extraction's cost is elsewhere: the
core reads 25 fields, 15 of them collaborators set once in `__init__`
(so a frozen context of fifteen), writes `_asr_language`, which is
session-scoped and read by `confirm_transcript` (so a mutable holder
beside the conversations owner), reads `_providers` and `_know_how`,
which a handover rewrites mid-reply (so the activation callback must
answer them), and carries **17 test reach-ins** (`_speak` 11,
`_speak_reply` 2, `_turns` 3, `_reply` 1) that a per-reply object would
move out of reach of the session the tests hold, needing a speaking-step
seam that exists for tests. Priced against that, the part of the
re-scope that the class docstring's inventory is actually about is
small: the fields with a reply lifetime and the task that bounds it.
Rafael chose that smaller M3 on 2026-09-23. The full extraction is not
refused; it is left to be argued from what remains after this issue,
with these numbers as its starting point.

**`runtime/reply_in_flight.py`, class `ReplyInFlight`.** What its
callers stop having to know: that the outcome latch must be cleared
before the task starts rather than inside it, that a cancel latches
before it cancels and waits the task out, that a drain waits without
cancelling and treats a failed reply as a finished one, and which
fields reset when. It is a new domain concept (the reply now running,
distinct from the session that runs replies), so it gets a module
rather than a class at the bottom of a 2,700-line file.

```python
class ReplyInFlight:
    """One started reply: its task, how it ended, and its own state."""
    utterance: str                   # minted here, read by the turn it opens
    turn: TurnUnderway               # replaced at each move, by the reply path
    round: int                       # LLM rounds across every leg
    spoke: bool
    withheld: bool
    remembering: bool | None         # resolved per leg, None before the first
    def start(self, body: Coroutine[Any, Any, None]) -> None
    def running(self) -> bool
    def latch(self, outcome: ReplyOutcome) -> None   # first writer wins
    @property
    def outcome(self) -> ReplyOutcome | None
    async def cancel(self, outcome: ReplyOutcome) -> None  # latch, cancel, await
    async def drain(self, grace_s: float) -> bool
```

Decisions inside it:

- **One reset point, and why it is now safe.** The re-scope's
  correction said the per-reply fields have three lifetimes and must not
  be reset at one point. Read again for this plan: `_speak_reply`, which
  resets `_llm_round`, `_reply_spoke` and `_reply_withheld`, is called
  from exactly one site (`_reply`, L1658), so it runs at most once per
  reply, and nothing reads those three fields between `start_reply` and
  that reset (the ASR leg, the no-transcript path and the failure arm
  read none of them; the watch cluster reads the round only inside a
  round). So initializing them when the reply is made gives every read
  the value it gets today. The implementer re-proves both halves by AST
  on the rebased tree (one caller of `_speak_reply`; no read of the
  three before it) and records the output; if either fails, the reset
  stays where it is and the field is still owned by the value.
  `remembering` keeps its own clock (assigned per leg in `_tool_loop`)
  and `turn` its own (replaced at each move); they live on the value
  because their lifetime ends with the reply, not because they reset
  with it.
- **The session holds the current one**, `self._in_flight:
  ReplyInFlight | None`, and every reply-state read in the runtime goes
  through it. `replying`, `drain` and `cancel_reply` keep their
  signatures (they are `SessionInput`'s and `TurnTaking`'s) and become
  one line each over it. `start_reply` makes the value, emits
  `turn_started` from it, and starts it.
- **The turn installed at construction goes.** `__init__` installs a
  turn today (L858) that "records nothing because nothing was heard on
  it". With the turn on the value there is no turn outside a reply, and
  nothing reads one there: the implementer proves it by AST (every read
  of the turn is inside the reply path or passed into M1's and M2's
  modules from it) and by a test that closes a session that never
  replied. If a read outside a reply turns up, the plan's answer is to
  report it rather than to invent a turn for it.
- **One reply in flight at a time is inventoried, not asserted.**
  Reading `self._in_flight` deep in the loop is correct only if a new
  reply never starts while the previous one still runs. Every caller of
  `start_reply` (in `TurnTaking`) is listed in the implementation doc
  with the cancel or the not-replying check that precedes it. No
  assertion is added: if the inventory finds a path without one, that
  is today's behavior too (two tasks sharing the fields), and the
  finding goes to the PR and to Rafael rather than into a silent fix.
- **The #489 bookkeeping** is recorded here: for the eleven files the
  issue lists, whether any storage dependency became explicit in a
  signature, with the count either way. Expected zero, since the value
  takes no storage, and reported as measured.

## Module layout

- New: `src/vinga_server/runtime/tool_execution.py` (M1),
  `src/vinga_server/runtime/provider_watch.py` (M2).
- Changed: `runtime/pipeline.py` (both milestones: fields, the moved
  methods deleted, the call sites, the class docstring's inventory and
  the module docstring's paragraph on the tool loop), and the source
  prose named in the documentation footprint.
- New: `src/vinga_server/runtime/reply_in_flight.py` (M3).
- M3 also changes `runtime/pipeline.py` (the reply-lifetime fields,
  `start_reply`, `cancel_reply`, `_latch` removed, `replying`, `drain`,
  the class docstring's inventory, which loses the entries the value now
  owns and says where they went).

## Tests

- **Pins before each move, committed green first and byte-unchanged
  after.** For every emit site a milestone moves, one pin asserting
  what a consumer sees: `record.msg`, `record.args` as typed values,
  and the structured payload's keys and values, with timing fields
  (`duration_ms`, `first_token_ms`, `elapsed`) pinned by type and
  presence rather than value. M1's sites: `tool_call` in each of its
  three shapes, `tool_arguments_coerced`, `sentence_withheld` in each of
  its three shapes, and the unparseable-arguments warning line. M2's:
  `llm_retry`, `llm_round` for a reply round and for a recap round,
  and `provider_failed` from each of its four callers' paths (ASR
  through `watching`, the reply stream, the recap timeout, TTS). The
  implementer first inventories which of these existing suites already
  assert at that strength (`test_session_tools.py`,
  `test_session_withheld.py`, `test_session_watchdog.py`,
  `test_session_reply_failures.py`, `test_event_surface_pins.py`) and
  adds pins only where none does, recording the inventory in the
  implementation doc. The event-baseline drivers are reused as drivers
  where they already reach a site.
- **Turn-record pins**, because two of the moved methods write the
  record: a reply round's `round_done` numbers (rounds, summed
  duration, token totals) and a recap round's absence from them; and a
  call's reserved and executed slot (`reserved(slot).entry`, the
  executed content, error flag and duration presence). Existing tests
  cover most of this (`test_session_tools.py` L1008-L1030); the
  inventory decides.
- **Reach-ins move to the interface.** The six manifest sites in
  `test_session_tools.py` are rewritten against `ToolExecution`'s
  public verbs, with the turn constructed by the test rather than read
  off the runtime's `_turn`, so the manifest loses those lines and gains
  none. Whether the test reaches the module through a public attribute
  on the runtime or constructs its own over the same sources is the
  implementer's call, recorded; what is refused is a new underscore
  name. `tests/census/reach-ins.txt` is regenerated, never edited.
- **The event-baseline identities** for the six moved emit sites are
  renamed to the new qualnames in `tests/tools/event_baseline.py` and in
  `CARRIED`, one to one, and the driver count stays 106.
- **New unit tests for each module through its interface**, where the
  existing session-level tests do not already reach a behavior through
  the module's verbs: for M1 at least the ordered-then-concurrent run
  order and the result order, and `offer`'s origins for an MCP, a
  device and a builtin tool; for M2 the retry-once-then-give-up path
  and the passthrough of a provider's own `TimeoutError` before the
  deadline (`expired()`), both with a fake stream and no session. Each
  is watched failing against a mutation before it is claimed: swapping
  the ordered and concurrent phases, and dropping the `expired()` check,
  run once each (straight-line logic); the concurrency of the ordered
  phase is not a new claim and gets no new mutation.
- **No-leak.** Nothing new reaches a retained surface: the moved
  sentences and events are the same ones. The existing sentinel tests
  (`test_event_surface_pins.py` L386's exception-text rule for
  `_run_one`, and the `provider_failed` class-name-only rule) are the
  pins, and their identity strings follow the rename.

## Risks and mitigations

- **A lazily read value becomes eagerly read.** Every emit in both
  clusters reads the active pair inside a thunk the emitter calls; a
  move that computed the pair at construction or at call entry would
  attribute a handover-straddling event to the wrong agent. Mitigation:
  the design above says "read at emit time" for both modules, and the
  handover tests in `test_session_tools.py` and
  `test_session_conversations.py` stay green; the implementer names in
  the implementation doc which existing test exercises an emit across a
  handover, or adds one.
- **The watchdog's cancellation semantics.** A barge-in cancels the
  reply task, and that cancellation lands in the watchdog's
  `asyncio.timeout` wait. Moving the generator into another object
  changes no await, but an `async for` over a method of another object
  that wraps the generator in a second one would add an await point.
  Mitigation: `reply_stream` returns the generator itself, and
  `test_session_watchdog.py`'s barge-in-during-the-wait case stays
  green unmodified.
- **The generator's finalization.** `_watched_stream` pulls the stream
  by hand so a consumer's failure closes the generator rather than
  passing through the guard. Mitigation: moved verbatim, and the
  existing test that a TTS failure is not blamed on the LLM stays green.
- **Stacking.** M1 and M2 edit `pipeline.py` in disjoint regions and
  are implemented in parallel on two branches off the plan branch; M3
  stacks on M2. Whichever lands later rebases onto what landed, and the
  expected conflicts are the class docstring, the imports and the
  `_tool_loop` lines where M1 passes the turn and M3 changes where it
  lives.
- **M3 changes when a field resets.** Its safety rests on two facts
  about today's code (one caller of `_speak_reply`, no early read),
  which the plan states and the implementer re-proves by AST rather
  than trusting this paragraph.
- **Census drift.** M1 changes `tests/`, so the reach-in census moves;
  M1 and M2 both move names that documents quote, so the spellings
  census may move. Both are regenerated on the rebased tree.

## Milestones

- [ ] **M1: tool execution in `runtime/tool_execution.py`.** Pins for
  the moved emit sites and record writes first, then the module and
  its unit tests, then the move (one commit), then the reach-ins
  rewritten against the interface and the census regenerated.
  *Design footprint:* deepens nothing existing; adds
  `ToolExecution`, whose callers stop knowing classification,
  reservation, coercion, timeouts, dispatch and withheld reporting,
  and the `Offer` value. *Documentation footprint:* no page under
  `docs/`; source prose in `events/assembly.py` and the runtime's
  docstrings. Changelog: none (no behavior change), stated in the PR.
- [ ] **M2: provider watching in `runtime/provider_watch.py`.** Pins
  first, then the module and its unit tests, then the move.
  *Design footprint:* adds `ProviderWatch`, whose callers stop
  knowing how a failure is reported without being swallowed, how the
  first token is bounded and retried, and what a round reports.
  *Documentation footprint:* no page under `docs/`; source prose in
  `providers/base.py`, `runtime/turntaking.py`,
  `tests/support/providers.py` and the runtime's docstrings.
  Changelog: none.
- [ ] **M3: the reply in flight in `runtime/reply_in_flight.py`.**
  Stacked on M2's branch (it changes the round counter M2 turns into an
  argument); M1 runs beside both, and whichever of M1 and M3 lands
  second rebases. Pins first: the outcome each boundary latches
  (barge-in, device abort, close, failure, completed) as `reply_finished`
  carries it, the round numbers across a handover, and the spoke/withheld
  fallback both ways; most exist in `test_turn_lifecycle.py`,
  `test_session_withheld.py` and `test_session_barge_in.py`, and the
  inventory decides. Then the value with unit tests through its
  interface (latch first writer wins; cancel latches before the task
  sees `CancelledError`, proved by a body that reads the outcome in its
  `finally`; drain never cancels and answers False at the grace; each
  watched failing against a mutation, the cancel ordering run 20 times
  since it is a concurrency claim), then the move, then the
  construction-time turn removed with its proof. *Design footprint:*
  adds `ReplyInFlight`, whose callers stop knowing the latch's
  ordering, the cancel-and-await rule, and which fields reset when;
  `PipelineRuntime` loses six fields and one method. *Documentation
  footprint:* no page under `docs/`; the runtime's class docstring.
  Changelog: none. Records the #489 count.
