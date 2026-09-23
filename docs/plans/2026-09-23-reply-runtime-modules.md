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
watching, measured below) behind interfaces of five and six verbs, and
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
in flight gets one owner: a value made when a reply starts, holding the
task, the first-writer-wins outcome latch, cancel-and-await, drain and
the utterance id, beside a second value made when a speaking pass
starts, holding the round counter and the spoke/withheld pair, so that
two of the resets the class docstring asks a reader to hold in mind
become true by construction.

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
  touch none of them. M3 gives the first two lifetimes a value each and
  leaves the per-leg and per-move clocks where they are.
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
```

Five verbs and no more. How long a call may take is decided inside
`run` (today's `_timeout_for`, private), because its one caller moves
with it; a public `timeout_for` would be surface only a test reads. The
runtime holds the module as a private collaborator, `self._tools`, for
the same reason: nothing outside the runtime needs it, so it is not on
the runtime's interface.

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

**`runtime/reply_in_flight.py`: one value per lifetime.** The
re-scope's correction measured three lifetimes, and the first shape of
this plan folded two of them into one reset point on the argument that
a speaking pass is exactly one per reply. The plan review showed the
cost of that fold (finding 1): about twenty test files drive
`_speak_reply` directly through `run_reply`, and about a hundred calls
drive `_reply` directly through `drive_reply`, neither through
`start_reply`, so state that exists only once `start_reply` has run
would be absent on both paths. The amended design follows the
lifetimes instead of folding them, which is also what the correction
asked for: each lifetime that today is a set of fields reset by
discipline becomes a value whose creation is the reset.

Of the eight fields with a reply lifetime (`_utterance`, `_outcome`,
`_reply_task`, `_llm_round`, `_reply_spoke`, `_reply_withheld`, `_turn`,
`_remembering`), six move and two stay:

```python
class ReplyInFlight:
    """One started reply: its task and how it ended."""
    def __init__(self) -> None: ...          # mints the utterance id
    utterance: str                           # read-only property
    def start(self, body: Coroutine[Any, Any, None]) -> None
    def running(self) -> bool
    def latch(self, outcome: ReplyOutcome) -> None   # first writer wins
    outcome: ReplyOutcome | None             # read-only property
    async def cancel(self, outcome: ReplyOutcome) -> None  # latch, cancel, await
    async def drain(self, grace_s: float) -> bool
    def __await__(self)                      # the task's own result or exception

@dataclass
class SpeakingPass:
    """One pass of `_speak_reply`: rounds across its legs, and whether
    any sentence went out or was withheld."""
    round: int = 0
    spoke: bool = False
    withheld: bool = False
```

- **`ReplyInFlight` owns the started-reply lifetime**: `_reply_task`,
  `_outcome` and `_utterance`. What its callers stop having to know:
  that the latch is fresh before the task starts rather than cleared
  inside it (a new value is fresh by construction, which retires the
  window `start_reply`'s comment argues about), that a cancel latches
  before it cancels and waits the task out, and that a drain waits
  without cancelling and treats a failed reply as finished. The session
  holds the current one as `self._in_flight: ReplyInFlight | None`;
  `replying`, `drain` and `cancel_reply` keep their signatures (they
  are `SessionInput`'s and `TurnTaking`'s) and become a line or two
  each over it. `start_reply` makes the value, emits `turn_started`
  from it, installs it, and starts `self._reply(utterance, reply)`.
- **The body takes its value as an argument**: `_reply(utterance,
  reply)`. Its three latch sites and its `finally`'s outcome read go to
  `reply`, not to `self._in_flight`, so the body never depends on which
  value is current. The utterance id reaches the first turn as an
  argument too: `_fresh_turn(utterance)` replaces the field read, and
  `_seeded_turn` carries the departing turn's `utterance`
  (`TurnUnderway.utterance`), which is exactly the value it reads today
  since the field outlives a handover on purpose. `_utterance` goes.
- **`SpeakingPass` owns the speaking-pass lifetime**: `_llm_round`,
  `_reply_spoke`, `_reply_withheld`. `_speak_reply` creates one where it
  resets the three fields today and holds it as `self._pass` for the
  loop, the fallback check and the withheld flag's runtime method; the
  round passed into M2's module reads it. A pass driven directly by
  `run_reply` creates its own, as it resets the fields today.
- **`_turn` and `_remembering` stay runtime fields.** `_turn` is
  replaced at reply start and at each move, and `run_reply` drives a
  pass on the turn installed at construction, so that turn stays;
  `_remembering` is resolved per leg and read through
  `_remembering_now` by a builtin source built once at construction.
  Neither has a lifetime that a value made at one point would own, and
  M1 and M2 already take the turn as an argument.
- **The test drivers, one by one.** `drive_reply` constructs a
  `ReplyInFlight` (public constructor, no runtime API) and calls
  `_reply(utterance, reply)`, still without `turn_started`; its reach-in
  stays one `_reply` site. `run_reply` and `test_tts_lookahead.py`'s
  `speak_a_reply` are unchanged. `reply_in_flight(session)` in
  `tests/support/sessions.py` answers `session.runtime._in_flight`, and
  its awaiting callers (`event_baseline.py` nine sites,
  `test_turn_lifecycle.py`, `test_session_barge_in.py`) await the value
  itself, whose `__await__` answers exactly what awaiting the task did,
  exception included; the identity checks (`is before`) hold because
  one value is made per started reply as one task was.
  `test_session_limits.py`'s `session_with` builds a value, starts it
  on a coroutine that awaits the test's task (so each of its three
  shapes, finished inside the grace, running past it, raising, is what
  the value reports), and installs it. The two `_reply_task` reach-in
  sites become two `_in_flight` sites; no site is added or removed, and
  the manifest is regenerated, never edited.
- **A behavior difference in direct drives, to be checked.** Today
  `_outcome` is cleared only by `start_reply`, so two `drive_reply`
  calls in one test share it: a latch in the first is reported by the
  second's `finally` if nothing clears it. A value per call ends that.
  The implementer inventories whether any test drives two replies
  directly and reads the second's `reply_finished`, and reports what it
  finds; a test that passes only because of the leak is a finding for
  the PR, not something to preserve.
- **One reply in flight at a time is inventoried, not asserted.**
  Every caller of `start_reply` (in `TurnTaking`) is listed in the
  implementation doc with the cancel or the not-replying check that
  precedes it. With the body holding its own value the invariant
  matters less than before (a second start no longer shares a latch
  with the first), but `self._in_flight` is still what `cancel_reply`
  reaches, so a path without a cancel is reported to the PR and to
  Rafael rather than silently fixed.
- **The #489 bookkeeping** is recorded here: for the eleven files the
  issue lists, whether any storage dependency became explicit in a
  signature, with the count either way. Expected zero, since neither
  value takes storage, and reported as measured.

## Module layout

- New: `src/vinga_server/runtime/tool_execution.py` (M1),
  `src/vinga_server/runtime/provider_watch.py` (M2).
- Changed: `runtime/pipeline.py` (both milestones: fields, the moved
  methods deleted, the call sites, the class docstring's inventory and
  the module docstring's paragraph on the tool loop), and the source
  prose named in the documentation footprint.
- New: `src/vinga_server/runtime/reply_in_flight.py` (M3:
  `ReplyInFlight`, `SpeakingPass`).
- M3 also changes `runtime/pipeline.py` (six fields, `start_reply`,
  `cancel_reply`, `_latch` removed, `replying`, `drain`, `_reply`'s
  signature, `_fresh_turn`, `_seeded_turn`, the class docstring's
  inventory, which loses the entries the values now own and says where
  they went), `tests/support/sessions.py` (`drive_reply`,
  `reply_in_flight`) and `tests/unit/test_session_limits.py`.

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
  public verbs, constructing a `ToolExecution` directly over the same
  sources the session would build (the MCP source over the test's
  `McpServers`, for the reload-mid-call case) and a turn of its own,
  rather than reading either off the runtime, so the manifest loses
  those lines and gains none. No production interface is added to reach
  them: not a public runtime attribute and not a public `timeout_for`.
  The timeout test (`test_session_tools.py` L1165, which today asks
  `_timeout_for` for the entry's 7.5 s) is rewritten through `run`,
  with the MCP entry's configured timeout set short and a tool that
  stalls past it while the module default is left long, so the timeout
  result can only have come from the entry the reservation named.
  `tests/census/reach-ins.txt` is regenerated, never edited.
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
  sentences and events are the same ones. Two existing sentinel tests
  are the pins and stay green unmodified in their assertions: for M1,
  `test_session_tools.py` L157,
  `test_a_tool_exception_exports_only_its_class`, which plants a
  credential-shaped exception message in a tool and holds it out of the
  `tool_call` event's structured fields and both log renderings, and
  which is the one test that drives the exception arm `_run_one` moves
  with; for M2, `test_event_surface_pins.py` L437,
  `test_a_failing_providers_own_words_reach_no_record`, the
  provider-failure class-name-only rule. If either has to change beyond
  a name the move renamed, that is a finding for the PR, not an edit.

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
- **M3 changes where the latch lives for a direct drive.** A value per
  `drive_reply` call stops two direct drives in one test from sharing a
  latch; the inventory under M3 decides whether any test leaned on it.
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
  inventory decides. Then the values with unit tests through their
  interface (latch first writer wins; cancel latches before the task
  sees `CancelledError`, proved by a body that reads the outcome in its
  `finally`; drain never cancels and answers False at the grace;
  awaiting the value re-raises the body's exception; each watched
  failing against a mutation, the cancel ordering run 20 times since it
  is a concurrency claim), then the move with the test drivers migrated
  as listed under M3, then the census regenerated. *Design footprint:*
  adds `ReplyInFlight` and `SpeakingPass`, whose callers stop knowing
  the latch's ordering, the cancel-and-await rule, and which fields
  reset when; `PipelineRuntime` loses six fields and one method. *Documentation
  footprint:* no page under `docs/`; the runtime's class docstring.
  Changelog: none. Records the #489 count.

## Plan review round

Reviewed 2026-09-23 by openai/gpt-5.6-sol, thinking high via codex CLI 0.156.0, read-only sandbox, runtime 15m06s, at commit 3c357043, plan blob a95baf69.

Verdict: ready after the P2 amendments.

1. **P2: M3 omits the migration path for reply test drivers.**
   `ReplyInFlight.start()` exposes no way to await the task, and tests
   bypass `start_reply`: `tests/support/sessions.py` calls
   `_speak_reply` (`run_reply`, L584) and `_reply` (`drive_reply`,
   L716), `test_tts_lookahead.py` L153 calls `_speak_reply`, and
   `sessions.py` L709 and `test_session_limits.py` L221 read or replace
   `_reply_task`. With the construction-time turn removed and all reply
   state on the value, those paths have no in-flight state. The plan
   also says six fields move where the source has eight (`_utterance`,
   `_turn`, `_llm_round`, `_remembering`, `_reply_spoke`,
   `_reply_withheld`, `_outcome`, `_reply_task`). Should name the
   migration for each helper and test (start, await, fail, drain)
   without test-only public runtime API, state the reach-in census
   change, and correct the count.

   *Resolution:* accepted, and it changed the design rather than only
   the test plan. The fold of two lifetimes into one reset point is
   withdrawn: M3 now makes one value per lifetime, `ReplyInFlight` for
   the started reply (`_reply_task`, `_outcome`, `_utterance`) and
   `SpeakingPass` for the speaking pass (`_llm_round`, `_reply_spoke`,
   `_reply_withheld`), so a pass driven directly by `run_reply` makes
   its own exactly as it resets the fields today. `_turn` and
   `_remembering` stay, with the reasons stated, and the construction
   turn stays because `run_reply` speaks on it. The body takes its
   value as an argument (`_reply(utterance, reply)`), `drive_reply`
   builds one through the public constructor, the value is awaitable
   for the helpers that awaited the task, and `test_session_limits.py`
   installs one around its task. The count is corrected to eight, six
   moving. Census: two `_reply_task` sites become two `_in_flight`
   sites, net zero, regenerated. Named under "M3" and in M3's
   milestone item.
2. **P2: `timeout_for` and the proposed runtime exposure are test-only
   public interfaces.** `_timeout_for`'s one caller is `_run_one`,
   which moves into the module, so a public `timeout_for` and a public
   runtime attribute for `ToolExecution` would be production surface
   no production caller needs, against the interface-as-test-surface
   rule. Should keep timeout selection private, keep the collaborator
   private on the runtime, construct `ToolExecution` directly in unit
   tests, and verify timeouts through `run`.

   *Resolution:* accepted. `timeout_for` is removed from the interface
   (five verbs), the runtime keeps the module private as `self._tools`,
   the reach-in rewrite constructs `ToolExecution` directly, and the
   timeout test is rewritten through `run` with a short entry timeout
   against a long default, so it still proves which entry the bound
   came from. Stated in M1's interface block and the Tests section.
3. **P2: the no-leak verification cites a test that does not exercise
   `_run_one`'s exceptions.** `test_event_surface_pins.py` L386 covers
   lossless coercion; the class-only exception pin is
   `test_session_tools.py` L157,
   `test_a_tool_exception_exports_only_its_class`, and the
   provider-failure pin is `test_event_surface_pins.py` L437. Should
   require the move to preserve the former with its sentinel checks
   against structured fields and both log renderings, and keep the
   latter for M2.

   *Resolution:* accepted; the citation was wrong. The Tests section's
   no-leak item now names `test_a_tool_exception_exports_only_its_class`
   (`test_session_tools.py` L157) as M1's pin, with its sentinel checks
   over structured fields and both log renderings, and
   `test_a_failing_providers_own_words_reach_no_record`
   (`test_event_surface_pins.py` L437) as M2's, both required to stay
   green with their assertions unmodified.

## Plan review round 2

Reviewed 2026-09-23 by openai/gpt-5.6-terra, thinking high via codex CLI 0.156.0, read-only sandbox, runtime 4m49s, at commit cc53c513, plan blob 9ef79d23.

A re-review of round 1's amendments, M3's rewrite above all. Verdict:
ready after the P2 amendments.

1. **P2: `drive_reply` would mint and export an utterance identity.**
   `ReplyInFlight.__init__` mints the id and `drive_reply` would build
   one, but today a direct drive bypasses `start_reply`, so
   `_fresh_turn` reads `_utterance` as None. That is load-bearing:
   `test_session_record.py` L834 relies on direct drives producing no
   `turn_started`, a minted id would change `TurnRecord.utterance`, and
   `TranscriptExport.turn_recorded` (`transcript_export.py` L120) would
   export a row it ignores today for None. Should say only
   `start_reply` creates an utterance-bearing value, give `drive_reply`
   an identity-less one, and pin that a direct drive records
   `utterance is None` and creates no transcript-export work.
2. **P2: `ReplyInFlight.cancel()` does not state the exception and
   cleanup contract.** Today `cancel_reply` suppresses exactly
   `CancelledError`, awaits, then clears the handle. "Latch, cancel,
   await" leaves open broader suppression and clearing a replacement
   value after the await. Should require suppressing exactly
   `asyncio.CancelledError` and preserving other task exceptions, and
   `cancel_reply` clearing the owner only if it is still the value it
   cancelled, with focused tests for both.
