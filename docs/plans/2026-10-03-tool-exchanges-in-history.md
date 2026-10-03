# Tool exchanges stay in the history an agent is sent

Plan for [#599](https://github.com/rafacm/vinga/issues/599), as
Rafael decided it on 2026-10-03 in the issue body. Its companion is
`docs/plans/2026-10-03-tool-exchanges-in-history-implementation.md`,
one section per milestone, appended in the same change that ticks the
milestone. It reverses one decision of
`docs/plans/2026-08-02-m6-tools-and-mcp.md` ("History stays text-only;
tool exchanges are ephemeral") and changes what
`conversations/hydration.py` (#190) renders on a resume. #536's option B
waits on it.

**Local baseline:** not applicable. The model is sent more of what it
already did with the tools it already has; no conversational capability
joins or leaves the baseline.

**Cheapest alternative:** leaving the problem alone costs every agent
its own earlier tool results on every later reply, and costs #536 its
simpler design (memory read once per conversation), which failed its
plan review on exactly this. The cheapest change that removes that cost
is M1 alone: keep each finished reply's completed tool rounds in the
thread's history, clearing results over the cap and degrading calls to
tools no longer offered. It is one module of two pure functions and two
call sites in the reply loop; the provider seam and the adapters do not
change. M2 (measuring the cap) and M3 (rebuilding on resume) are
decisions 3 and 4, each a separate decision Rafael took, and each is
cut as its own milestone so it can be reviewed, and declined, alone.
Nothing in the plan is a number to measure ahead of time; the one
measurable question (does a provider refuse unoffered calls) was
measured in Step 0, below.

**Attribution:** anthropic/claude-opus-5-5, thinking medium; Claude Code 2.1.288; 2026-10-03.

## Where this starts from

Verified at `677fd921`, which is both `main`'s head and the commit the
issue pins ([Step 0 comment](https://github.com/rafacm/vinga/issues/599#issuecomment-5973019858)).

- `runtime/pipeline.py` `_tool_loop` copies the thread's history into
  `working` (L1772), appends `Turn("assistant", preamble,
  tool_calls=...)` (L1897) and `Turn("tool", "", tool_results=...)`
  (L1914) per round, and throws `working` away. What reaches the
  thread's history is `Turn("assistant", " ".join(spoken))`, at the end
  of a reply (L1476) and at the end of a leg that moved (L1607).
  `leg` is one round's heard sentences and `spoken` the whole reply's.
- `providers/base.py` `Turn` (L370) states the text-only rule, and
  `test_history_keeps_the_speech_and_not_the_tool_exchange`
  (`tests/unit/test_session_tools.py:211`) pins it. The pipeline's
  module docstring (L23) says it again.
- `conversations/hydration.py` renders a stored turn as `user` +
  `assistant` with `(tools used: <names>)` appended (`TOOL_NOTE`, L75).
  `records.StoredTurn.tools` carries names only; `threads.py` (L877)
  reads only `tool_invocations.name`. The store has name, arguments,
  result, `is_error`, `malformed` and `position` per call, the content
  three under the text switch. `position` restarts at zero each round
  (`ToolExecution.reserve`, `enumerate(calls)` per round), so the row
  order plus `position == 0` recovers the round boundaries.
- The recap (`_summarized`) sends `made.input`, which is hydration's
  output, with no tools at all.
- In-session history has no budget: `self._turns` grows for the
  session. The 2 KiB cap is therefore the only bound on what kept
  results add inside a session.
- Both adapters translate structured turns already
  (`openai_llm.py:61-95`, `anthropic_llm.py:46-83`) and omit `tools`
  entirely when the offer is empty (`openai_llm.py:229-231`,
  `anthropic_llm.py:154-156`).

## Open questions, resolved

**Q1. Does a provider reject past calls to tools not in the current
offer?** Measured on 2026-10-03 against OpenAI Chat Completions, two
models (gpt-4.1-mini, gpt-5-mini), a history holding an earlier
`lookup_code` call and its result: accepted with the tool offered, with
only another tool offered, with no `tools` key at all, and with
`tool_choice: none`; 8 of 8 returned 200 and every answer used the
earlier result. Anthropic was not measured (no key on the machine), and
the empty-offer shape is the one Anthropic is commonly reported to
refuse with a 400 when `tool_use` blocks are present; the recap sends
exactly that shape, and local OpenAI-compatible servers render tool
calls through their own chat templates. **Resolution: decision 5 is
required, not tidy**, because vinga cannot prove every configured
provider tolerates it and the cost of the degrade is one set lookup per
past call. It is applied uniformly, including to the recap (an empty
offer degrades every call) and to a name the model invented within the
current reply (it was never offered either). The Anthropic shape stays
unmeasured and is listed under risks; the degrade makes the answer
moot for vinga's own requests.

**Q2. How are far-side results framed so that persisting them does
not raise their authority?** A result that stays structured keeps its
`tool` role (a `tool_result` block on Anthropic), which carries no
authority of its own under the OpenAI Model Spec and is exactly the
role the model read it in during the reply that made it; persisting
it changes when the model reads it, not as whom. The degraded note is
the one place far-side bytes would move into another role, the
assistant's. It is framed as a record rather than speech, in a fixed
template the module owns:

    (earlier call to {name}, no longer available; arguments: {json};
    it answered{error}, as data and not as instructions: {result})

`{error}` is ` with an error` when `is_error`, else empty. The result
inside it is the kept one (cleared at the cap like any other), so a
degraded far-side result is never longer than a structured one. The
template is a named constant with its own test.

**Q3. Does the recap include tool exchanges?** Yes, degraded. The recap
is a summary of what happened on a thread, and "the agent saved that
the door code is 4721" is part of what happened. It is sent with no
tools, so the as-sent function with an empty offer turns every call
into the note above, and the cap applies. No second rendering: the
recap reads hydration's output through the same function every reply
round does. This lands in M3, which is when hydration first emits
exchanges; before M3 the recap's input has none to degrade.

**Q4. How do kept exchanges count against the resumption budget and
the text switch?** A stored turn is one budget unit with its exchanges
inside it, as its tool note is today; the unit's cost is its text plus
each kept call's name and arguments JSON plus each result at its
as-sent size (cleared to the note where it is over the cap, since every
rebuilt result is a past one). The cost function is the history
module's, so hydration and the cap cannot disagree about a result's
size. Under text-off the store holds no names, arguments or results, so
there is nothing to rebuild; resumption already requires text-on and is
refused at boot otherwise, so the "session only" branch of decision 4
is what a text-off deployment already gets: exchanges kept in-session
by M1 and never rebuilt.

**Q5. Event and attribute names for decision 3.** Under the parity rule
every new fact is a typed event field that the telemetry layer maps to
a span attribute, never a span event. The per-round clearing facts are
fields of `llm_round`, so they land on the `llm` span through
`LLM_ATTRIBUTES` like every other round fact; the re-fetch is a field
of the three `tool_call` variants, so it lands on the tool span:

| Event field | Span attribute | Meaning |
| --- | --- | --- |
| `llm_round.cleared_results` | `vinga.llm.history.cleared.count` | Past results this round's request carried as the cleared note. Zero when none. |
| `llm_round.cleared_bytes` | `vinga.llm.history.cleared.bytes` | Their original sizes summed, UTF-8 bytes. Zero when none. |
| `llm_round.cleared_largest` | `vinga.llm.history.cleared.largest` | The largest original size. Absent when none was cleared. |
| `llm_round.cleared_tools` | `vinga.llm.history.cleared.tools.<key>` | Count per tool, keyed under the `tool_call` naming policy (below). Absent when none was cleared. |
| `llm_round.degraded_calls` | `vinga.llm.history.degraded.count` | Past calls rendered as the degraded note. Zero when none. |
| `tool_call.refetch` | `vinga.tool.refetch` | This call repeats, by tool and canonical arguments, a past call whose result this round's request carried cleared. |

`cleared_tools` is a closed `EventValue` (`ClearedTools`, the shape of
`MemorySources`): every key is one of `builtin.<name>` (a builtin's own
name), `mcp.<entry>` (the configured MCP entry), `device`, or
`unoffered` (a call this round's offer no longer names, invented names
included, since the offer that would have named it is gone), every
value a positive count. The origin is read off the round's `Offer`
(`Offer.origins`), the same frozen provenance a withheld sentence is
named from; nothing far-side becomes a key. The prefixes keep a builtin
and an MCP entry that share a word apart.

`degraded_calls` is the one fact not in decision 3's list. It is one
count, and without it decision 5 is the one behavior change in this
plan nobody can see happen; an MCP reload that degrades a thread's
calls is exactly the event someone debugging a confused agent needs to
find. It is cut if review prefers the list as decided.

"Re-fetches counted per conversation" is the `refetch` flag grouped by
the `conversation` field every `tool_call` already carries, rather than
a counter on some event. A counter held in the session would restart
at every session boundary while the conversation it counts continues on
resume, so it would be wrong exactly where the question is asked; the
flag is per call and the aggregation is a query over the event store or
the backend.

`llm_round`'s `turns` field, documented as "the cheap proxy for payload
size", now counts tool turns too. Its note is amended to say so; the
number keeps meaning messages sent.

## Decisions, restated

As the issue has them, confirmed by Step 0.

1. All tools' exchanges stay in the history the agent is sent, builtins,
   MCP and device tools alike, for the rest of the conversation. A
   handover is unchanged: the incoming agent starts clean.
2. A cap of 2 KiB per kept result (`MAX_KEPT_RESULT_BYTES = 2048`,
   UTF-8 bytes, a named constant and not a config key). In the reply
   that made the call the model sees the result whole; on later replies
   a result over the cap is replaced by `(result of {name} cleared:
   {size} bytes)`, the name being the tool the model called.
3. The cap is measured, with no content on any surface (Q5).
4. A resumed conversation rebuilds its tool exchanges from
   `tool_invocations`, under the dialogue's token budget, where the
   store records text (Q4).
5. A call to a tool not offered on this request is degraded to the
   text note, checked by name against the round's offer on every
   request (Q1, Q2).

## Smaller decisions

**D1. One module owns the history's tool shape:
`runtime/history.py`.** Two pure functions, the two halves of one
rule:

- `kept_round(history, preamble, calls, results) -> list[Turn]`: what
  one completed round adds to its thread's history (D2), with its ids
  minted against the history it is appended to (D4). Empty when nothing
  in the round is kept, and then the preamble is the caller's to carry
  forward as heard speech (D3).
- `as_sent(turns, start, offered) -> Sent`: what one request carries,
  given the thread's history, which by then holds this reply's own
  completed rounds (`turns`), where this reply began (`start`), and the
  names this round offers.
  `Sent` holds the turns, the clearing facts (count, bytes, largest,
  and the cleared calls' names, which the caller keys from its offer,
  D7), the degraded count, and the set of cleared `(name, canonical
  arguments)` keys the re-fetch check reads.

What callers stop knowing: the cap, both notes, which results are
"past", how a degraded call folds into the assistant turn, how call ids
are minted, and what counts as a completed round. The pipeline calls
`kept_round` where a round completes and `as_sent` where a request is
built; hydration (M3) and the recap (M3) call `as_sent` and the
size function. Deletion test: inlined into `_tool_loop`, the rules
would sit in the 2,878-line pipeline beside the speech lookahead and
be testable only through a scripted session, which is how the
text-only rule ended up pinned by a session test. A module in
`runtime/` rather than `providers/` because the rule is the runtime's
policy about history, not a wire format; it imports only `Turn`,
`ToolCall` and `ToolResult`.

**D2. A round is committed the moment it completes, straight into the
thread's history.** Plan review round 1 (finding 1) found that the two
`Turn("assistant", said)` sites cannot see `working`, which is local to
`_tool_loop`, and that the reply site appends nothing when nothing was
spoken. So there is no commit at the end at all: `_tool_loop` stops
keeping a private `working` copy and appends each completed round to
`self._turns` (the active thread's history) at the point it would have
appended the tool turn to `working`, in the same synchronous stretch
with no await between the results arriving and the append. What a
cancellation, a provider failure in a later round, or a silent reply
leaves behind is therefore exactly the rounds that completed, with no
second path to forget: a `remember` that ran in round 1 of a reply whose
round 2 failed is in the history, which is the case the issue exists
for. The two end-of-reply sites keep appending only speech (D3).

A round is complete when every call that is not a move has its result.
Of a completed round, every call with a result is kept and the
successful move that ended a leg is not (it has no result; a refused
move has its error result and is kept). A malformed call is not kept
either: its raw bytes are not what the store holds, so keeping it would
make in-session and resumed history differ (finding 3), and the error
the model was told about it belongs to the reply that made it. A round
cut by a barge-in or a failure part-way through execution has no tool
turn and is not kept at all, even where some of its calls had answered
(the store will hold those answers; M3's rule, D9, drops that round on
resume as well). A round left with no kept call commits nothing, and
its preamble, which was heard, joins the speech that follows (D3).

**D3. Every sentence heard appears once.** Today the one assistant turn
is `" ".join(spoken)`, preambles included. With rounds kept, a round's
preamble lives in its own assistant turn's `content`, and the closing
assistant turn carries only what was heard after the last kept round:
the pipeline notes `len(spoken)` at each commit and the end-of-reply and
end-of-leg sites append the sentences after that mark, as today only
when there are any. A reply that only ran tools and was cut before
speaking leaves its rounds and no closing turn, so the next user turn
follows a tool turn; that is a shape providers accept (it is the shape
of every second round), and Step 0's probe sent it.
The stored record (`_record_turn(spoken)`) is unchanged: the store's
`reply` stays the whole reply, which is why M3's rebuild puts the
stored reply after the rebuilt rounds with empty preambles, the same
words in a slightly different split.

**D4. Call ids in history are minted by vinga.** On commit each kept
call and its result get `h<n>`, `n` counting the thread's kept calls
(the module derives it from the history it is handed, so no counter
lives in the session). Two reasons. An OpenAI-compatible server that
sends no ids gets `call_0` minted by the adapter for every round, so
two kept rounds would carry the same id; and the provider's id is
far-side bytes that the #533 work keeps off retained surfaces, so it
should not persist for a conversation either. M3 mints the same shape
for rebuilt calls. Because a round is committed when it completes
(D2), the next round of the same reply already carries the minted ids;
an id only pairs a call with its result, which the minted pair still
does, and Step 0's probe sent ids of its own choosing and was accepted.
`h<n>` matches Anthropic's `^[a-zA-Z0-9_-]+$` id pattern. The tests pin
that the request after a commit pairs every call id with exactly one
result.

**D5. Clearing applies to results before `start`; degrading applies to
every call.** `start` is `len(self._turns)` when the reply's
`_tool_loop` began, so a reply's own results are never cleared and a result is
cleared from the first request of the next reply. Degrading is not
bounded by `start`: a name the model invented in this reply was not
offered either, and handing it back structured is what decision 5
exists to stop. Today such a call is sent back structured with its
error result; after M1 it is the degraded note with the error, which
is the same information in a role every provider accepts.

**D6. A round with some calls degraded keeps the rest structured.** The
assistant turn's `content` becomes its preamble followed by the
degraded notes in call order; its `tool_calls` keep the offered ones;
the tool turn keeps their results; a tool turn left with no results is
dropped, and an assistant turn left with no calls becomes a plain text
turn. Adjacent plain assistant turns are not merged: two assistant
messages in a row is a shape a failed reply already produces today, and
merging would be a second rule about speech.

**D7. The per-origin keys are the caller's.** `as_sent` returns the
cleared calls' names; the pipeline, which holds the round's `Offer`,
maps each to its `ClearedTools` key. That keeps `runtime/history.py`
free of the tool namespaces, and the naming policy where it already
lives (`tool_execution.py`), as a small function beside
`_sentence_withheld`'s.

**D8. The re-fetch check rides the existing classification.** The
round's cleared keys go to `ToolExecution.run` with the invocation it
already receives; the variant builder sets `refetch` when the call's
`(name, canonical arguments)` is in the set. Canonical arguments are
`json.dumps(arguments, sort_keys=True, separators=(",", ":"))`; a
malformed call never matches. Computed from the history being sent
rather than remembered, so a resumed conversation's re-fetches count
the same way.

**D9. Hydration renders rounds, and the names note retires (M3).**
`StoredTurn.tools: tuple[str, ...]` becomes `calls:
tuple[StoredCall, ...]` (`position`, `name`, `arguments`, `result`,
`is_error`, `malformed`), read by `threads.py` from the same query
widened to those columns.

The read orders by turn and then by `tool_invocations.id`, never by
`position` (finding 2): `position` restarts at zero every round, so
sorting on it would put every round's first call ahead of every second
call. The id is the insertion order, and the writer inserts a turn's
rows in one `executemany` from `record.tools`, which `TurnUnderway.reserve`
appends in reservation order, round after round
(`conversations/store.py`, the `_tool_row` list comprehension). That is
true of every row already stored, so no migration and no new column;
an integration test pins it with two rounds of two calls each. The
name filter the read has today moves out of SQL: every row is read,
because dropping an unnamed row first could remove the `position == 0`
that marks a round's start (finding 3).

Hydration then groups the rows into rounds (a new round at each
`position == 0` in id order) and only then applies D2's rule, so the
resumed history is the in-session one. A round is kept when every row
in it that is not a successful move has a result, a name and well-formed
arguments; a successful move is a row whose name is one of the move
tools (`switch_agent`, `new_conversation`, `resume_conversation` naming
a conversation, read from `tools/names.py` as `_moves` reads them) and
whose result is null, and it is dropped from its kept round. A round
with any other null result is a round cut during execution (the
reservation filed every call, and only some were filled before the
cut), and it is dropped whole, exactly as the session dropped it; a
malformed row is dropped from its round as in-session (D2). A turn then
renders as `user`, per kept round an assistant turn with its calls and
a tool turn with their results, then the stored reply. `TOOL_NOTE` goes: its only input was the names, which sit under
the same switch as the results that now render whole. A turn joined
onto the answer before it (the first turn of a thread a move landed
on) renders its calls as degraded notes inside the joined text, which
keeps the joining rule's alternation and is rare enough that structure
buys nothing there.

## Out of scope, with reasons

- **A budget for in-session history.** It has none today and decision
  2 bounds what this adds. A session long enough to need one is a
  different issue whatever is in it.
- **Per-deployment cap configuration.** Decision 2 says a constant
  until data says otherwise; M2 is the data.
- **Carrying the handover's history to the incoming agent.** Decision
  1 keeps a handover clean.
- **#536.** It follows this, on its own plan.

## Module layout and design footprint

- **M1**: new `runtime/history.py` (D1), whose callers stop knowing
  the cap, the notes, the id minting and the completed-round rule.
  `runtime/pipeline.py` deepens nothing and loses the text-only rule:
  `_tool_loop` drops its private `working` copy, appends each completed
  round to the thread's history through `kept_round(...)` (D2), and
  sends `as_sent(...)`'s turns (to the provider partial, to
  `stage_reply` and to `reply_round_done`); the two end-of-reply sites
  append only the speech after the last commit (D3). No new seam; `Turn` and the adapters are
  untouched apart from the docstring.
- **M2**: `events/catalog.py` (`LlmRound` gains five fields, the three
  `tool_call` variants gain `refetch`), `events/values.py`
  (`ClearedTools`), `telemetry.py` (the table rows and the
  `ClearedTools` prefix expansion beside `MEMORY_SOURCES_PREFIX`),
  `runtime/tool_execution.py` (the key function, D7, and the re-fetch
  flag, D8), the watch's `reply_round_done` carrying the facts.
  Deepens the existing event and span tables; adds no module.
- **M3**: `conversations/records.py` (`StoredCall`), `threads.py` (the
  widened read), `conversations/hydration.py` (rounds, D9, cost via
  `history`), `runtime/pipeline.py` (`_summarized` sends `as_sent` of
  its input against an empty offer). Hydration deepens; nothing is
  added.

## Tests

Reuse the scripted-session harness of `test_session_tools.py`
(`ScriptedLlm`, `session_for`, `run_reply`, `history`) and the
hydration suite's builders; no new fixtures.

- **M1, the module** (`tests/unit/test_runtime_history.py`): a kept
  round survives commit; an incomplete round and a resultless call do
  not, their preamble does; every heard sentence appears once across
  the committed turns; ids are `h<n>` and pair; a result of exactly
  2048 bytes is kept and 2049 cleared (and a multibyte result is
  measured in bytes, not characters); this reply's results are never
  cleared; an unoffered call becomes the degraded note with its
  framing, error flag and capped result; a mixed round keeps the
  offered call structured; the cleared keys are canonical.
- **M1, the session**: the pinning test is rewritten to the new rule
  (`test_history_keeps_the_tool_exchange`); a two-reply session where
  reply 1 calls `remember` and reply 2's request carries the call and
  its result structured, and the scripted model answering from it
  makes no second call (the issue's first criterion: the scripted
  model's second reply is chosen by reading `seen`, so "answering from
  it" is asserted on what the provider was handed); a 3 KiB device
  tool result is whole in reply 1's second round and cleared in reply
  2; an MCP tool removed between replies (the registry replaced, the
  way `test_session_tools` already swaps an MCP registry) arrives as
  the degraded note; a barge-in mid-execution leaves no call of that
  round in history; a reply whose round 1 ran `remember` and whose
  round 2 provider call failed, speaking nothing, leaves round 1 in
  history and the next reply's request carries it; a barge-in after
  round 1 completed and before any speech does the same; a move leg
  keeps its plain calls and not the move; every request after a commit
  pairs each call id with exactly one result.
- **M1, the export**: the staged `llm` input is the as-sent turns, so
  the content export shows the cleared note and not the full result on
  a later reply.
- **M2**: field and attribute pins on `llm_round` and the `llm` span
  (zero and absent shapes included), `ClearedTools` validation
  (rejects an unknown key shape, a zero, a bool), the key mapping per
  namespace with a device tool named like a builtin; `refetch` true for
  a repeated call after its result was cleared, true when the repeat
  orders the same arguments differently, and false for a repeat of a
  result that was kept. A
  no-leak sentinel: a credential-shaped string in a cleared device
  result and in an MCP tool's far-side name appears in neither event
  format, any record arg, nor any span attribute. The generated event
  reference regenerates.
- **M3**: hydration groups rows into rounds in id order before
  filtering, drops a round with a non-move null result whole, drops a
  successful move and a malformed call from a kept round, mints ids, charges the as-sent cost to the budget
  (a turn with a 10 KiB result costs its cleared size), renders a
  joined turn's calls as notes; `threads.py` reads the widened row set
  in id order, two rounds of two calls each written through the store's
  own writer (integration, against Postgres); a reply cancelled after
  the first of two calls completed, then resumed, carries neither call; a resumed session's first
  request carries the stored exchange structured and a no-longer-offered
  one degraded (the issue's third criterion); the recap request carries
  every call degraded and no `tools`.

**Falsification.** Each new test is watched failing first, against
`main` for M1's session tests (which the text-only rule fails), and by
mutation for the rest: cap off by one, `start` ignored (own results
cleared), degrade skipped, ids not re-minted, `refetch` always false,
`position` boundaries ignored, budget charging the raw size. Each
mutation is run once (straight-line logic) and its outcome stated in
the commit body; a survivor is reported as a finding about the test.

## Risks

- **Anthropic's empty-offer refusal is unmeasured.** Decision 5
  removes the risk for every request vinga builds; what is left is a
  provider refusing structured calls to tools that ARE offered, which
  is the same shape as the second round of every tool-using reply
  today.
- **Prompt growth and the cache.** Kept exchanges make every request
  longer, bounded at 2 KiB per result. They are appended in history
  order and never rewritten after their first later reply, so the
  provider cache's prefix rule holds: a result is cleared once, on the
  first request after its reply, and stays cleared. A degrade is the
  one rewrite of the past, and it happens only when the offer changes,
  which already changes the `tools` that lead the cached prefix.
- **A model that over-trusts an old result.** That is what decision 3's
  re-fetch metric is the other side of; nothing here prevents a model
  from re-asking, and nothing should.
- **The `turns` proxy changes meaning.** Stated in its note (Q5);
  dashboards comparing across the change see a step.
- **Stacked-merge timing.** M2 and M3 both stack on M1 and touch
  disjoint files except `pipeline.py`, at different functions; the
  second to merge rebases.

## Standing lenses

- **No-leak**: no new surface carries content. The cleared note and
  the degraded note go only to the model and to the opt-in content
  export that already carries tool results. Every metric is a count, a
  size, or a naming-policy key built from `Offer.origins`; the
  sentinel test in M2 plants a credential-shaped value in a far-side
  name and a result.
- **Pin before reshaping**: the in-round shape is unchanged (D4), and
  the existing tool-loop suites stay green unmodified apart from the
  tests that pin the text-only rule, which change on purpose and are
  named in the PR.
- **Closed sets mapped to decision sites**: `ClearedTools` keys come
  from `Origin.source`, whose set is the classifier's; `unoffered` is
  decided where the offer lookup misses.
- **Honest seams**: `as_sent` takes the offered names as an argument
  rather than reading a registry, so an MCP reload is tested by
  passing a different set.
- **Inventories by tooling**: the commit sites are the two
  `self._turns.append(Turn("assistant", said))` lines found by `grep -n
  'Turn("assistant", said)'` on the pipeline, full output; the readers
  of `StoredTurn.tools` by `git grep -n '\.tools\b' -- vinga-server`
  full output, recorded in M3's section.
- **Proportion**: the cheapest alternative line above.
- **Falsify before claiming**: the mutation list under Tests.

## Documentation footprint

- **M1**: `providers/base.py` `Turn` docstring and the pipeline's module
  docstring state the new rule (both code); `docs/concepts.md` gains a
  bullet in the decided semantics, beside "A switch starts clean":
  an agent keeps its own tool exchanges for the conversation, results
  over 2 KiB cleared on later replies, calls to tools no longer offered
  turned into notes. `CHANGELOG` fragment `changelog.d/599-tool-exchanges-in-history.md`.
- **M2**: `docs/architecture/observability-surfaces.md` (the page that
  lists the `vinga.llm.*` round attributes) gains the clearing
  attributes and the tool span's `refetch`; the event reference
  regenerates through its generator. Fragment lines under Added.
- **M3**: `docs/concepts.md`'s resumption bullet says a resumed thread
  carries its tool exchanges; the conversations-schema reference's
  `tool_invocations` description, if its generator text mentions what
  hydration reads, regenerates. Fragment lines under Changed.

## Milestones

- [ ] **M1: keep completed tool rounds in history.** Decisions 1, 2
  and 5 (D1 to D6): `runtime/history.py`, the two commit sites and the
  per-round `as_sent`, the export staging the as-sent turns, the
  pinning test and the three documents above. The behavior change, alone
  in review.
- [ ] **M2: measure the cap.** Decision 3 (Q5, D7, D8): five
  `llm_round` fields and their `llm` span attributes, `ClearedTools`,
  the tool span's `refetch`, the observability page. Stacks on M1.
- [ ] **M3: rebuild exchanges on resume.** Decision 4 (Q3, Q4, D9):
  `StoredCall`, the widened thread read, hydration rendering rounds
  under the budget, the recap sent degraded, the concepts resumption
  bullet. Stacks on M1, independent of M2; closes #599.

## Plan review round

Reviewed 2026-10-03 by openai/gpt-6-sol, thinking high via codex CLI 0.160.0, read-only sandbox, runtime 5m05s, at commit 71af06b1, plan blob 898683fe.

---

1. **P1: The commit sites cannot access the tool rounds they must save.**
   **Evidence:** Plan D1 and M1 (`docs/plans/2026-10-03-tool-exchanges-in-history.md:195`) call `committed(working, ...)` at the reply and move commit sites. `working` is local to `_tool_loop` (`vinga-server/src/vinga_server/runtime/pipeline.py:1772`); the commit sites are outside it, and the reply site appends history only when `spoken` is nonempty (pipeline.py:1474 (`vinga-server/src/vinga_server/runtime/pipeline.py:1474`)).
   **Plan should say instead:** Define how completed rounds reach both commit sites, including when `_tool_loop` is cancelled, and commit completed tool exchanges even when no sentence was spoken. Test a tool-only failed reply as well as a barge-in.

   *Resolution:* accepted. There is no end-of-reply commit any more: D2 now commits each round into the thread's history at the moment it completes, in the synchronous stretch after its results arrive, so cancellation, a later failure and a silent reply all leave exactly the completed rounds. `working` goes; the end sites append only the speech after the last commit (D3); D4 says what the minted ids mean for the next round of the same reply. Tests add the tool-only failed reply and the barge-in before speech.

2. **P1: Sorting by position destroys round order on resume.**
   **Evidence:** Plan D9 (`docs/plans/2026-10-03-tool-exchanges-in-history.md:289`) keeps the read “ordered by turn and position” while treating `position == 0` as a new round. `reserve` (`vinga-server/src/vinga_server/runtime/tool_execution.py:412`) restarts position at zero each round; the current query (`vinga-server/src/vinga_server/conversations/threads.py:877`) sorts all zeros before all ones.
   **Plan should say instead:** Read calls in their insertion order, using `tool_invocations.id`, then use position to identify boundaries within that order. Test multiple rounds with more than one call each, including stored rows created before the upgrade.

   *Resolution:* accepted. D9 orders by turn and `tool_invocations.id`, and cites why that is reservation order for every row ever written (one `executemany` over `record.tools`, appended by `reserve`), so rows stored before the upgrade read the same way and need no migration. The integration test writes two rounds of two calls through the store's own writer, which is the path pre-upgrade rows took.

3. **P1: A stored result does not prove its interrupted round was complete.**
   **Evidence:** Plan D2 (`docs/plans/2026-10-03-tool-exchanges-in-history.md:223`) drops a round cut during execution, but D9 drops only rows with null results. Calls are reserved before execution (`vinga-server/src/vinga_server/runtime/pipeline.py:1869`) and filled individually (`vinga-server/src/vinga_server/runtime/turns.py:247`). A barge-in after one of two calls completes leaves one result in the store but no tool turn in `working`. Dropping the null row can also erase a `position == 0` boundary.
   **Plan should say instead:** Group rows into rounds before filtering, define how incomplete rounds and successful moves are distinguished, and make resumed history match the in-session rule. Test cancellation after the first of two calls completes, then resume that thread.

   *Resolution:* accepted. D9 reads every row, groups by `position == 0` in id order, and only then filters: a successful move is a move tool's row with a null result and is dropped from its round; any other null result marks a round cut during execution, dropped whole as the session drops it (D2). Malformed calls are dropped in both places now (D2 changed to match). The test cancels a reply after the first of two calls completes, then resumes the thread and asserts neither call is in the request.

4. **P1: The joined-turn exception violates the structured-history decision.**
   **Evidence:** Plan D9 (`docs/plans/2026-10-03-tool-exchanges-in-history.md:289`) degrades every call on a turn joined to the preceding answer, even when the tool is still offered. Issue decision 5 degrades calls *only* when their names are absent from the current offer; the resumed-request criterion requires still-offered calls to remain structured.
   **Plan should say instead:** Preserve structured exchanges while joining that turn to the preceding budget unit. Add a resume test for an answer-only turn that contains a still-offered tool call.

5. **P1: The degraded note gives untrusted bytes an assistant voice.**
   **Evidence:** Plan Q2 (`docs/plans/2026-10-03-tool-exchanges-in-history.md:89`) interpolates the raw tool name and result into assistant content. The phrase “as data and not as instructions” does not contain a result that starts with `)` and follows it with a forged assistant instruction. The adapters (`vinga-server/src/vinga_server/providers/openai_llm.py:61`) will send that content as assistant-authored text.
   **Plan should say instead:** Specify an escaped, clearly delimited representation for every interpolated far-side field, state its remaining authority risk, and test adversarial result and name strings through both provider translators.

6. **P2: Clearing metrics omit requests that fail and recap requests.**
   **Evidence:** Plan Q5 and M2 (`docs/plans/2026-10-03-tool-exchanges-in-history.md:129`) add fields only to `LlmRound`. A failed request emits `ProviderFailed` (`vinga-server/src/vinga_server/events/catalog.py:1997`), and a recap that the plan says carries cleared results emits `LlmRecap` (`vinga-server/src/vinga_server/events/catalog.py:1970`). Both have `llm` spans.
   **Plan should say instead:** Carry clearing facts on those event variants and their spans, or explicitly narrow “per round” and explain why these requests are excluded. Test a context-length failure after request assembly and a recap containing cleared results.

7. **P2: The clearing breakdown loses an MCP entry when its tool disappears.**
   **Evidence:** Plan D7 (`docs/plans/2026-10-03-tool-exchanges-in-history.md:274`) derives metric keys from the *current* `Offer`; Q5 assigns every unoffered call to `unoffered`. After an MCP reload, the prior entry is absent from that offer, although the issue requires the configured MCP entry to identify which tool was cleared. The store already records `source` and `entry` (`vinga-server/src/vinga_server/conversations/records.py:57`), but planned `StoredCall` omits them.
   **Plan should say instead:** Preserve the call-time trusted origin in session history and hydration, and use it for the clearing breakdown. Test a cleared MCP result after that entry is removed.

8. **P2: The resumption budget is priced before the final representation is known.**
   **Evidence:** Plan Q4 (`docs/plans/2026-10-03-tool-exchanges-in-history.md:116`) promises an as-sent cost, but `hydrated` (`vinga-server/src/vinga_server/conversations/hydration.py:112`) has no current offer. That offer decides whether each exchange is structured or becomes a potentially longer text note; the recap uses an empty offer. The planned tests price a cleared large result but do not test degradation changing whether a turn fits.
   **Plan should say instead:** Charge each unit using the actual representation for its request, or a documented conservative upper bound. Test a turn that fits while structured but exceeds the budget after degradation.

**Verdict:** Ready after the P1 and P2 amendments. The proposed `runtime/history.py` passes the deletion test on its stated responsibilities: removing it would put the cap, completion, ID, and degradation rules back into multiple callers.
