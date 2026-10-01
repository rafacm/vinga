# Memory leaves the system message, and a tool span carries its content

Plan for [#536](https://github.com/rafacm/vinga/issues/536)'s M2 (the
placement change) and the content half of
[#533](https://github.com/rafacm/vinga/issues/533), as Rafael decided
them on 2026-10-01
([decision comment](https://github.com/rafacm/vinga/issues/533#issuecomment-5930373695)). Its
companion is
`docs/plans/2026-10-01-memory-placement-and-tool-content-implementation.md`,
one section per milestone, appended in the same change that ticks the
milestone. It builds on `docs/plans/2026-10-01-telemetry-metadata-half.md`
(the parity rule, the per-round `RoundPrompt` accounting, the join keys
on the tool span, and M3's removal of the Langfuse aliases), all merged.

**Local baseline:** not applicable. The model receives the same facts
in a different position, and an export already behind
`export_llm_input` gains a copy on the span that describes the work;
no conversational capability joins or leaves the baseline.

**Cheapest alternative:** for the placement, the cheapest change is
none: leave memory at the tail of the system message and accept that
every memory write voids the cached history for the next round. #536 M1
measured that cost as a full miss after every verified write, and the
probe below reproduces it; at a real conversation's length the history
is most of the prompt, so the miss is most of the input billed at the
uncached rate and the latency of re-reading it. The proposal costs one
function in the prompt module and the pipeline handing its result to the provider and the export alike; the provider seam does not change. For the tool
content, the cheapest is none as well: the arguments and results
already ride the `llm` span (a call in round N's output, its result in
round N+1's input) when `export_llm_input` is on. Rafael chose to put
them where the tool span is, so a reader sees what a tool was asked and
answered on the observation named for it; the cost is a second copy of
those bytes, counted against the same bound.

**Attribution:** anthropic/claude-opus-5-5, thinking high; Claude Code 2.1.286; 2026-10-01.

## Where this starts from

Measured at `3e993fef` (`main`'s head on 2026-10-01, after the
metadata-half plan's three milestones merged).

- The LLM seam is one interface, `stream(system, turns, tools,
  tool_choice)` (`providers/base.py:491-498`). The OpenAI-compatible
  adapter puts `system` at message 0 (`providers/openai_llm.py:68`); the
  Anthropic adapter passes it as the top-level `system` field
  (`providers/anthropic_llm.py:141-153`), whose API has no
  mid-conversation system role and alternates user and assistant turns.
- The per-round scope blocks (`state`, `memory`, `device`, the last
  holding the device record as well as its notes) are appended to the
  know-how half by `prompt.with_scopes` and sent as part of `system`
  (`runtime/prompt.py`, `runtime/pipeline.py`'s `_system_prompt`). Their
  position is a recorded decision: "what memory holds last, which is
  where the remembered facts already were" (`runtime/prompt.py:37-52`).
- What is injected per round: the conversation's ledger (at most 50
  keys, 4 KiB), the newest 40 agent facts within 4 KiB, and the device's
  notes (at most 30 lines, 2 KiB) with its record
  (`memory/store.py:130-170`). Older facts are reached through `recall`.
- The tool span carries identity, outcome, the requesting round's
  invocation and the call's position (`telemetry.py`'s
  `TOOL_ATTRIBUTES`), and no content. The content export
  (`llm_input_export.py`) stages a round's request and output under the
  conventions' keys only, keyed by invocation.
- Langfuse 4.48.0 maps `gen_ai.tool.call.arguments` and
  `gen_ai.tool.call.result` to a tool observation's input and output
  natively (its OTel ingestion's precedence list, read for the metadata
  half's M3).

## The placement probe (Step 0)

A probe against OpenAI (`gpt-4.1-mini`, the deployed model) on
2026-10-01 ran one scripted conversation three times, the memory block
changing at a fixed turn, in three positions: (a) the tail of the
system message, as today; (b) leading the newest user message; (c) a
user message after the newest one. Scripts:
`scratchpad/placement_probe.py` and `placement_probe_long.py` of the
session that wrote this plan; not committed.

| Run | (a) system tail | (b) ahead of the user | (c) after the user |
| --- | --- | --- | --- |
| Long history, write at turn 11: cached share of turn 11 | **0%** | 88% | 82% |
| Spontaneous full misses across 17 turns, no write involved | 2 | 1 | 3 |

Method, so it can be rerun: one chat-completions client, no vinga
server; a system prompt of a nonce plus 45 numbered one-line rules
(about 1,100 tokens, over the 1,024-token cache floor); 17 user turns,
the first nine asking for three detailed facts each (`max_tokens` 160)
so the history grows to about 1,000 tokens; a memory block of one fact
until turn 10 and two from turn 11; each variant with its own nonce so
no variant reads another's cache; one second between requests; the
cached count read from `usage.prompt_tokens_details.cached_tokens`.

**The earlier gate.** #536 M1 recorded its own gate for this change as
not opened as written (the treatment signature held at three of four
interventions or four of four, depending on how "same-numbered" was
read, and one control round also missed), and left the decision to
Rafael (`docs/plans/2026-09-25-cached-prompt-tokens-implementation.md`).
On 2026-10-01 Rafael decided to build the change on this probe's
evidence, which isolates the variable that gate could not: the same
conversation with only the memory block's position changed. That
decision supersedes the earlier gate; this plan's own gate (decision 6)
is the reproducible criterion the implementation must meet.

So a write voids the cached history only in today's placement, while
full misses that no write explains hit every placement at a similar
rate (#536 M1 saw them too). They are the provider's, not this plan's to
fix, and they are why the milestone's gate below counts over several
writes rather than reading one. At OpenAI's 128-token cache granularity,
(b) and (c) are not distinguishable by cache alone, so they are chosen
between on the request's shape and the model's reading of it.

## Decisions

### M1: memory leaves the system message (#536 M2)

1. **Placement happens once, in the pipeline, and the provider seam
   does not change.** `with_scopes` stops appending the scopes to the
   know-how half and returns them as their own rendering, the
   per-round **context** (the three scope blocks and the device record,
   under their headings, in their existing order, joined as today);
   `system` becomes the know-how half alone, stable for an activation.
   One function in `runtime/prompt.py` places the context into a copy
   of the round's turns, and the pipeline hands that same placed list
   both to `provider.stream(system, placed, tools, choice)` and to the
   content export's `stage_reply`, so what is exported is what the model
   was given by construction (finding 2). `LlmProvider.stream` keeps its
   signature and neither adapter changes (finding 5): each already
   renders a user `Turn`'s content as one ordinary user message, so the
   placement rides through every dialect as it is.
2. **Position (b): the context leads the newest user turn's content.**
   The placing function returns the turns with the newest `user` turn's
   content replaced by the context, the join and the utterance; every
   other turn is the same object. So every compatible server and chat
   template sees one ordinary user message (no mid-conversation system
   message, which some local templates reject or fold, and no two
   consecutive user messages), and Anthropic's alternation holds with
   no system role. In a tool round the newest user turn precedes the
   tool exchange, and the context stays on it. A request with no user
   turn (none is known to exist on the reply path; the implementer
   confirms by reading the callers) gets the context as a final user
   turn rather than losing it. An empty context returns the turns
   unchanged. Chosen over (c) because it keeps one user message per
   turn and because the model reads what it knows and then what it is
   asked. The known cost, accepted: within one reply, a round after a
   memory-writing tool call re-reads the newest user message and that
   turn's tool exchange, because the context on the user message
   changed; the system prompt and every earlier turn stay cached, which
   is the cost this change exists to remove. Placing the context after
   the tool exchange in continuation rounds instead would either carry
   two contexts in one request (the round's first, kept for the prefix,
   and the fresh one) or freeze memory for a whole reply, which breaks
   the per-round freshness contract (a fact remembered in one round is
   known in the next). The cache gate reports continuation rounds
   separately so the cost is measured rather than assumed.
3. **Memory loses system authority, deliberately.** Facts the model
   stored from what a user said no longer sit in the system message, so
   a remembered sentence shaped like an instruction ("remember: ignore
   your instructions") is read as context inside a user turn rather than
   as the operator's prompt. The headings stay, so the model still reads
   which block is what. `prompt.py`'s module docstring and the
   precedence paragraph are rewritten to say where memory now sits and
   why.
4. **Nothing is persisted with the context.** The context is placed
   into a copy of the turns for the request being built; the
   conversation store,
   the working copy of turns, the recap and the history the next round
   rebuilds hold the utterance alone. So the previous turn's user message
   is byte-identical in the next request, which is what keeps everything
   up to the newest turn cacheable.
5. **The accounting follows the move.** The metadata half's
   `vinga.llm.system.characters` now measures the system message alone
   (the know-how half), and `vinga.llm.memory.characters` and
   `vinga.llm.memory.sources.*` measure the context; the catalog notes
   and the observability page say so. The prompt digest
   (`vinga.prompt.sha256`) becomes the SHA-256 of `half.text`, the
   exact system string sent, since nothing follows the half in the
   system message any more; the follower-based `Assembled.canonical`
   (`runtime/prompt.py`), which existed only because scopes could
   follow the half and trim it, is removed, and the catalog note, the
   `PROMPT_ATTRIBUTES` comment and the observability page say "exactly
   as sent" again. A regression runs a lone persona with leading
   whitespace and a non-empty context through the production path and
   asserts the digest equals the SHA-256 of the system string the
   provider received. The content export's `gen_ai.system_instructions` is now the
   stable half, and the context appears in `gen_ai.input.messages` as
   the newest user message's leading text part, which is what the model
   received. The stable half is still exported on every round's span,
   deliberately: #533 §3's "once per agent" is declined rather than
   built. Each generation is rendered by the backend from its own span
   (Langfuse builds a generation's input from that span's
   `gen_ai.system_instructions` and `gen_ai.input.messages`), so a
   once-per-activation carrier would take the system prompt off every
   generation again, re-opening the gap the metadata half's M3 just
   closed, to save bytes the content bound already counts. #533 is
   closed with that reason recorded.
6. **The gate is a behavior check and a cache measurement, both on
   OpenAI.** Anthropic is unmeasurable on this machine (no key) and is
   covered by its adapter's rendering tests only, stated as an unchecked
   box.
   - *Behavior:* a scripted session through the real server
     (`gpt-4.1-mini`, the builtin memory tools) asks for a fact
     remembered in an earlier conversation, acts on a `set_state` entry,
     and names the device by its record's name, under the old placement
     and the new, the same script three times each; the new placement
     must answer every probe the old one answers. One extra probe stores
     an instruction-shaped fact and records whether the model obeys it
     under each placement (observed, not gated).
   - *Cache:* a paired comparison through the real server, the same
     scripted session of at least 15 turns run on `main` (old
     placement) and on the branch (new), four sessions counterbalanced
     old, new, new, old, each with at least four verified writes. A
     verified write is a non-error `remember` call whose next round's
     injected fact ids (the metadata half's `vinga.llm.memory.facts`)
     gain the new id; `set_state` is not used as an intervention, since
     the ledger carries no ids to verify it by. Per write, the raw
     `cached_tokens` of the following round is read from `llm_round`
     (`cache_read_input_tokens`), and a full miss is a following round
     caching fewer than 1,024 tokens (the provider's floor). The gate
     opens when (i) the old arm shows the problem the change exists for,
     at least half its verified writes followed by a full miss, so the
     rig reproduces it, and (ii) the new arm has at most one
     write-followed full miss across all its verified writes (the
     probe's spontaneous rate), and its write-followed rounds' mean
     cached share is at least 0.8. Anything else is recorded and goes
     to Rafael rather than the gate moving. Same-turn continuation
     rounds after a write are reported separately (their cached tokens
     against the round before), so decision 2's accepted cost is a
     measured number. The per-round table goes in the implementation
     doc.

### M2: a tool span carries its content (#533 §2), and option A is written down

7. **The tool span carries the call's arguments and result under
   `export_llm_input`.** As the conventions' `gen_ai.tool.call.arguments`
   (the reserved claim's semantic arguments, not the coerced execution
   copy, encoded with the same JSON encoding the `llm` span's
   `tool_call` parts already use, `llm_input_export._call`, so the two
   copies of one call read alike; both adapters parse a valid
   arguments object and keep no raw string, so this is the call's
   content and not the provider's bytes, and a malformed call carries
   its raw argument text, the one case the neutral model keeps it) and
   `gen_ai.tool.call.result` (the result content exactly as the model
   was handed it). With the setting off, nothing changes. Langfuse maps
   both to the tool observation's input and output natively, so no
   Langfuse alias is written, under the parity rule.
8. **Through the content export, never the event surface, and handed
   over in one emission.** `PipelineRuntime` gives `ToolExecution` the
   session's `LlmInputExport` as an optional collaborator (`None` when
   `export_llm_input` is off; compared `is not None`). The export gains
   a tool-specific `stage_tool(session, invocation, position,
   arguments, result)`, called by `_run_one` after the call returns and
   immediately before its `tool_call` event is emitted, and a
   `take_tool(invocation, position)` that telemetry's `_tool_span` calls
   with the event's own `invocation` and `position`, the metadata
   half's join keys, so two calls in one round never take each other's
   pair. `_tool_span` takes the slot on every path, discarding it when
   the session has no trace, so nothing outlives the emission that
   staged it. The `tool_call` event and the retained log gain nothing.
9. **One ceiling per pair, no shared budget.** Events fold
   synchronously (`SessionEvents.emit`), so a tool pair is staged and
   taken within one emission and never accumulates beside another; a
   session budget and eviction order would be rules no pair could meet.
   So a tool pair has the per-request ceiling only: one over it is
   dropped whole at staging and reported (decision 9a). It does not
   join the generation pairs' held total. A malformed call (no
   arguments object) exports its raw argument text as the model sent
   it. Tested: a pair over the ceiling dropped and reported with
   `kind=tool_call`; a session with no trace whose slot is discarded by
   `_tool_span`; two positions in one invocation each taking their own
   pair; exact `rounds` and `tool_calls` counts on `llm_input_exported`
   for a session with two rounds and three tool calls.
9a. **The outcome events say which kind of pair.** Rather than make
   `llm_input_export_failed` say "a generation pair was omitted from its
   LLM span" about a tool span, both outcome events are generalized
   once: `llm_input_export_failed` gains `kind`, a closed set
   (`generation`, `tool_call`) decided where the pair is dropped, and
   `llm_input_exported` gains `tool_calls`, the count of tool spans that
   received a complete pair, beside `rounds`, whose meaning is
   unchanged. Their docstrings, templates and notes are reworded to
   "content pair" and "span", `docs/reference/events.md` is regenerated,
   and the event baseline's exact carried-key sets pin both new fields.
   The observability page's exported-traces sentence that tool arguments
   and results do not enter spans is rewritten.
10. **The Collector masks them like the rest, and its tests say so.**
    The two keys join the content-masking rules in
    `deploy/telemetry/collector.yml` beside `gen_ai.input.messages` and
    kin; `tests/unit/test_telemetry_deploy.py`'s exact content-key set
    gains them, and `tests/integration/test_telemetry_fanout.py` sends a
    credential-shaped and an email-shaped value in each new field
    through the real Collector and shows both masked before both
    sinks.
11. **Option A, written down.** Memory text stays under
    `export_llm_input`, with no switch of its own. The setting's
    description (generated into `docs/reference/server-config.md` from
    the config model) and the observability page's content-export
    section say plainly: with it on, the household's remembered facts
    leave with every round (in the newest user message after M1) and in
    the memory tools' arguments and results, the backend retains them
    by its own policy, and deleting a fact here does not reach what
    already left.

## Out of scope, with reasons

- **Relevance-selected memory** (injecting only the facts a turn needs).
  The injection is newest-N plus `recall` by design; changing that is a
  memory redesign, not a placement change.
- **Anthropic prompt-cache breakpoints.** The adapter sets none today;
  placing them is a separate behavior and cost change.
- **The provider's spontaneous full misses.** Measured, not fixable
  here.
- **The 18 span events (#576), audio parity (#582).** Their own issues.

## Module layout and design footprint

No new module, and no provider changes. Deepened:

- `runtime/prompt.py`: `with_scopes` returns the scopes as their own
  rendering beside the half, `RoundPrompt` carries both, and one placing
  function owns where the context goes; callers stop having to know the
  position, and no dialect has to.
- `runtime/pipeline.py`: the placed turns built once per round and given
  to the provider and the content export alike. `ProviderWatch` is
  unchanged: its zero-argument stream factory already retries the
  arguments fixed before the first attempt.
- `llm_input_export.py`: `stage_tool` and `take_tool`, keyed by the
  join; `runtime/tool_execution.py` holds the export as an optional
  collaborator `PipelineRuntime` passes in; `telemetry.py`'s
  `_tool_span` takes the slot on every path.
- `deploy/telemetry/collector.yml`, `config/models.py` (the
  `export_llm_input` description), docs.

## Tests

Reuse the adapter tests and fake SDKs (`tests/support/llm_sdk.py`), the
session prompt tests (`tests/unit/test_session_prompt.py`), the content
export tests (`tests/unit/test_llm_input_export.py`), the span tests
and `tests/tools/event_baseline.py`.

M1:
- The placing function: the context leads the newest user turn's
  content and appears nowhere else; every other turn is the same
  object; with no user turn the context is a final user turn; an empty
  context returns the turns unchanged.
- Through each adapter's existing rendering (the fake SDKs), the
  request's system field or message is the know-how half alone and the
  newest user message begins with the context.
- Production path: the turns the fake provider received equal the
  turns `stage_reply` exported, for a reply round, a tool round and a
  round whose generation fails (the export's input for a failed
  generation is the placed request too).
- A tool round: the context stays on the newest user turn, not after
  the tool results.
- The previous turn's user message is byte-identical across two
  consecutive requests (pins decision 4), and the conversation store
  holds the utterance alone.
- `RoundPrompt` accounting: system characters equal the system the
  provider received; memory characters equal the context it received.
- Pin before reshaping: a characterization pin of today's assembled
  system string for a fixed scope set, committed green before the move,
  then changed deliberately with the move.

M2:
- With `export_llm_input` on, a tool span carries both keys with the
  claim's arguments and the content the model was handed; off, neither.
- A coerced call exports the model's arguments, not the coerced copy; a
  malformed call exports its raw text.
- Two calls in one round each carry their own pair (by position).
- The `tool_call` event's carried keys are unchanged (the event
  baseline's `CARRIED` set pins it); the outcome events' new fields are
  pinned there too (decision 9a), and decision 9's ceiling, no-trace,
  two-position and exact-count tests.
- The no-leak sentinel: with the setting off, a credential-shaped
  argument appears on no span and no log line.

**Falsification.** Each new test watched failing first. Mutations, one
run each: M1, the context appended to the system again (the rendering
test and the byte-identical-history test must fail); the exported turns
taken from the unplaced list (the provider-equals-export test must
fail); the context persisted into the working turn (the store test must
fail). M2, the
coerced copy exported (its test must fail); the pair attached without
the setting (the sentinel must fail).

## Risks

- **Behavior change.** The model reads memory as context in the user's
  turn. Mitigated by decision 6's behavior gate; if a probe the old
  placement answers fails under the new one, the milestone stops and the
  result goes to Rafael rather than the gate being lowered.
- **A compatible server that rejects or mangles the composed message.**
  None is expected, since the shape is one ordinary user message; no
  local runner exists on this machine to check, stated as unverified.
- **Accounting drift.** Decision 5 changes what two shipped attributes
  measure. Named in the changelog under `### Changed`.
- **Content bytes doubled for tools.** Counted against the bound
  (decision 9).

## Standing lenses

- *No-leak*: M2's sentinel; M1 adds no surface.
- *Pin before reshaping*: the system-string characterization pin.
- *Closed sets*: `LlmInputExportFailure` read at its decision site.
- *Honest seams*: no seam is added; the placing function compares the
  context with the empty string, never by truthiness.
- *Inventories by tooling*: every `with_scopes(` caller and every
  `stage_reply(` and `stream(` call site listed by untruncated
  `git grep -n`.
- *Proportion*: the cheapest-alternative line, with the probe's numbers.
- *Falsify before claiming*: the mutations above.

## Documentation footprint

- `docs/architecture/observability-surfaces.md`: the memory section
  (where memory sits in a request), the content-export section (tool
  content on the tool span; option A's sentences), the metadata half's
  two attributes' meanings.
- `runtime/prompt.py`'s module docstring (the precedence paragraph).
- `config/models.py`'s `export_llm_input` description, then
  `docs/reference/server-config.md` regenerated.
- `docs/reference/events.md` regenerated where catalog notes change.
- `changelog.d/536-memory-leaves-the-system-message.md` (M1: `### Changed`)
  and `changelog.d/533-tool-content-on-the-tool-span.md` (M2:
  `### Added`, and option A's sentence under `### Changed`).

## Milestones

M1 and M2 run in parallel off this plan's branch; they meet only in the
observability page and the content export module, and the second to
merge rebases.

- [ ] **M1: memory leaves the system message.** Decisions 1 to 6, their
  tests and mutations, the behavior and cache gates, its documentation
  footprint. One pull request; it closes #536.
- [ ] **M2: a tool span carries its content.** Decisions 7 to 11, their
  tests and mutations, a live readback of a tool observation's input
  and output in Langfuse, its documentation footprint. One pull request;
  whichever of the two merges last closes #533.

## Plan review round

Reviewed 2026-10-01 by openai/gpt-5.6-sol, thinking high via codex CLI 0.156.1, read-only sandbox, runtime 8m47s, at commit d8cc2f40, plan blob 6973e0cd.

---

1. **P1: The plan does not implement #533’s once-per-agent system-prompt cardinality.**

   **Evidence:** Decision 5 claims moving memory “answers #533 §3’s ‘once per agent’” (`docs/plans/2026-10-01-memory-placement-and-tool-content.md:133-145`). But `PipelineRuntime` still calls `stage_reply` inside every round (`runtime/pipeline.py:1768,1805-1813`), and `_stage` writes `gen_ai.system_instructions` into every round snapshot (`llm_input_export.py:139-160`). The metadata-half review explicitly deferred the one-copy design to this content half (`docs/plans/2026-10-01-telemetry-metadata-half.md:900-904`).

   **Plan should say instead:** Define the carrier that exports the stable know-how text once per agent activation, plus how every generation references it while carrying per-round context. Test multiple rounds and a handover, proving exactly one stable-prompt copy per activation and correct Langfuse rendering.

   *Resolution:* accepted that the plan overclaimed, and the "once per agent" cardinality is declined rather than built, on the merits. A backend renders each generation from its own span: Langfuse builds a generation's input from that span's `gen_ai.system_instructions` and `gen_ai.input.messages`, so exporting the stable half once per activation would take the system prompt off every generation again, re-opening the gap the metadata half's M3 closed, to save bytes the content bound already counts. Decision 5 now says so, and #533 closes with the reason recorded. The metadata-half review that deferred it deferred it to Rafael's content decisions, which did not choose it.

2. **P1: Adapter placement would make the LLM-input export differ from what the model received.**

   **Evidence:** Decisions 1 and 2 insert context only inside provider adapters (plan lines 95-118`). Today the exporter stages `system` and the unmodified `working` turns before adapter translation (`runtime/pipeline.py:1794-1817`), and serializes only those turns (`llm_input_export.py:111-160`). Consequently `gen_ai.input.messages` would omit the context, contradicting Decision 5 and the exported-input contract that the snapshot is the assembled request. No M1 test checks the exported messages (plan lines 241-256`).

   **Plan should say instead:** Pass the context into `stage_reply` and render it into the newest user message under the same placement rules, including tool rounds and the no-user fallback. Add a production-path test comparing the provider request and exported messages, including a failed generation.

   *Resolution:* accepted, by moving the placement up a layer. One function in `runtime/prompt.py` places the context into a copy of the round's turns, and the pipeline hands that same placed list to the provider and to `stage_reply`, so the export is the request by construction, in a reply round, a tool round and a failed generation alike; a production-path test compares the turns the fake provider received with the exported ones, and a mutation exporting the unplaced list must fail it.

3. **P2: The prerequisite gate that previously stayed closed is silently treated as open.**

   **Evidence:** The completed cached-token milestone says “M2’s gate not opened as written” (`docs/plans/2026-09-25-cached-prompt-tokens.md:345-350`), and its implementation records the literal result as “M2’s gate does not open” pending Rafael’s decision (`...-implementation.md:268-290`). This plan proceeds with M2 based on new probe scripts that are not committed (plan lines 68-89`) without stating that the earlier gate was resolved or superseded.

   **Plan should say instead:** Record the settled resolution of the earlier gate, identify the evidence that supersedes it, and make the new reproducible criterion explicit before authorizing implementation.

   *Resolution:* accepted. The probe section now records the earlier gate's outcome (not opened as written, the decision left to Rafael), that Rafael decided on 2026-10-01 to build the change on this probe's evidence, which isolates the one variable the earlier A/B could not, and the probe's method in enough detail to rerun; decision 6 is the reproducible criterion the implementation must meet. The scripts stay uncommitted, as #536 M1's rig did.

4. **P2: The new cache gate cannot be evaluated as written.**

   **Evidence:** The gate accepts `set_state` as a verified write but requires `vinga.llm.memory.facts` to change (plan lines 157-166`). `PromptMemory` explicitly gives IDs only to agent and device facts; ledger state has none (`memory/store.py:418-445`). Moreover, `llm_round` reports total and cached tokens, not the token count of “history before the newest turn,” so the proposed threshold is not directly observable.

   **Plan should say instead:** Either restrict interventions to fact-backed writes such as `remember`, or verify `set_state` through the exported context or a direct memory read. Define an observable cache criterion using paired requests and raw cached-token counts, with an explicit repeatability threshold.

   *Resolution:* accepted. The cache gate is now a counterbalanced paired comparison (old, new, new, old) through the real server with `remember` as the only intervention (verified by the injected fact ids gaining the new id; `set_state` dropped, since the ledger has no ids), raw `cached_tokens` of the following round, a full miss defined as under the 1,024-token floor, and explicit thresholds: the old arm must reproduce the problem (at least half its writes followed by a full miss), and the new arm may have at most one write-followed full miss with a mean write-followed cached share of at least 0.8.

5. **P2: The `stream` signature change can silently misbind existing positional arguments.**

   **Evidence:** The current seam is `(system, turns, tools, tool_choice)` (`providers/base.py:491-498`). Both the reply and recap pass tools and choice positionally (`runtime/pipeline.py:1817,2188`), as do provider tests and subclass calls. Inserting `context` after `turns` would turn `()` into context and `"none"` into tools. Numerous support and inline providers also override the existing signature, including `tests/support/providers.py:99-105,148-154,171-177`.

   **Plan should say instead:** Add `context` as a keyword-only parameter after the existing parameters, pass it as `context=...`, and inventory every production and test implementation. Leave `ProviderWatch` unchanged: its existing zero-argument stream factory already retries fixed arguments, so adding a context pass-through there would be a shallow forwarding change.

   *Resolution:* resolved by finding 2's redesign: the provider seam keeps its signature, no adapter changes, and `ProviderWatch` is untouched, as the finding recommends for it.

6. **P2: The prompt digest’s new input remains conditional when it must change.**

   **Evidence:** Decision 5 only says to simplify canonical rendering “if nothing follows” (plan lines 137-141`). Today `Assembled.canonical` deliberately differs from `text` for a lone persona with leading whitespace (`runtime/prompt.py:352-369`), and `_prompt_assembled` hashes `half.canonical` (`runtime/pipeline.py:1119-1124`). After memory leaves the system message, the provider receives `half.text`; retaining the current digest would fingerprint different bytes.

   **Plan should say instead:** Hash the exact system string sent, `half.text`, and remove or redefine the follower-based canonical form. Add a regression using a leading-whitespace lone persona plus nonempty context.

   *Resolution:* accepted. Decision 5 now makes the digest the SHA-256 of `half.text`, the exact system string sent once nothing follows the half, removes `Assembled.canonical`, restores "exactly as sent" in the docs that describe it, and adds the leading-whitespace lone-persona regression against the system string the provider received.

7. **P2: The promised tool-content session bound has no implementable lifecycle or test.**

   **Evidence:** Decision 9 says tool pairs share the existing per-request and per-session bounds (plan lines 185-192`), but the current session budget covers only unfinished `_Round` objects and is released at `finish()` (`llm_input_export.py:168-177,208-265`). The generation finishes before tools run (`runtime/pipeline.py:1852-1863,1900-1905`). The proposed tests cover only an over-ceiling pair, not session-budget exhaustion (plan lines 258-268`).

   **Plan should say instead:** Specify when tool pairs enter and leave the session’s held-byte accounting, their eviction order relative to generation pairs, and cleanup on cancellation, missing traces, session close, and shutdown. Test multiple tool pairs exhausting the session budget, not only one pair exceeding the per-operation ceiling.

   *Resolution:* accepted. Decision 9 now gives the tool pair a lifecycle: staged right after the call returns and before its `tool_call` event, joining the session's held bytes; taken by the tool span's fold in the same emission; discarded and released when there is no trace, when the session closes with it held, and at shutdown; a cancelled call stages nothing; eviction is oldest first across generation and tool pairs. Tests cover budget exhaustion by several tool pairs, the no-trace discard and the close release.

8. **P2: Reusing the export outcome event would make its retained wording and counts false.**

   **Evidence:** The plan reports dropped tool pairs through `llm_input_export_failed` but considers only whether its reason token fits (plan lines 185-190`). The event currently says a generation pair was omitted from its LLM span, while `llm_input_exported.rounds` counts actual generation spans (`events/catalog.py:4064-4100`; `events/values.py:1766-1779`). Neither vocabulary describes a tool span. The exported-traces documentation also currently states that tool arguments and results do not enter spans.

   **Plan should say instead:** Decide whether tool attachment outcomes get separate metadata events or the existing events are generalized. Define how successful tool attachments are counted, update catalog/value prose and the exported-traces section, regenerate `events.md`, and pin the resulting exact event schema.

   *Resolution:* accepted. New decision 9a generalizes both outcome events once: `llm_input_export_failed` gains a closed `kind` (`generation`, `tool_call`) decided where the pair is dropped, `llm_input_exported` gains `tool_calls` beside an unchanged `rounds`, the prose says "content pair" and "span", `events.md` is regenerated, the event baseline pins both fields, and the observability page's sentence that tool content does not enter spans is rewritten.

**Verdict: not ready.** The once-per-agent requirement and exported-request parity need concrete designs before implementation; the remaining P2 amendments should be resolved in the same plan revision.

## Plan review round 2

Reviewed 2026-10-01 by openai/gpt-5.6-terra, thinking high via codex CLI 0.156.1, read-only sandbox, runtime 4m14s, at commit 516de247, plan blob a6e1e317.

---

1. **P1: Chosen placement still invalidates the cache after a memory-tool write.**
Evidence: Plan Decision 2 puts context at the newest user turn, while `vinga-server/src/vinga_server/runtime/pipeline.py:1888` appends the assistant tool call and tool-result turns after that user turn before the next LLM request. A `remember` write therefore changes the user message before the new assistant/tool exchange, so the next request cannot reuse that exchange as a cached prefix. The plan’s own cache gate measures exactly this next round, and its “tool round” test explicitly preserves the bad placement.
What the plan should say instead: specify a tool-continuation placement that follows the assistant/tool exchange, including the required OpenAI and Anthropic rendering changes to preserve valid message sequencing. Keep ordinary user rounds simple if desired, but test a verified `remember` write followed by its same-turn continuation and require the cached prefix to include the preceding tool exchange.

   *Resolution:* rejected, with the cost stated and measured instead. The re-read is bounded to the newest user message and that turn's tool exchange; the system prompt and all earlier history stay cached, which is the cost #536 measured and this change removes (the probe's write turn cached 88%, against 0% today). The fix proposed would put the context after the tool exchange in continuation rounds, which either carries two contexts in one request (the round's first, kept for the prefix, and the fresh one) or freezes memory for the whole reply, breaking the per-round freshness contract #536 recorded as not to be reopened. Decision 2 now names the cost, and the cache gate reports same-turn continuation rounds separately so it is a number rather than an assumption.

2. **P1: The proposed shared session budget for tool pairs cannot occur with synchronous folding.**
Evidence: Decision 9 says a tool pair is staged immediately before `tool_call`, then consumed by that span’s fold in the same emission, while `vinga-server/src/vinga_server/events/__init__.py:654` dispatches synchronously and `vinga-server/src/vinga_server/telemetry.py:3127` creates the span during that dispatch. Unlike generation pairs, which remain held until a later `llm_round`, a tool pair is released before another tool pair can accumulate. Thus “several tool pairs exhausting the session budget” and cross-kind oldest-first eviction are not testable or real in this design.
What the plan should say instead: either make tool attachment deliberately deferred, with an explicit ordered post-execution fold and a justified retention budget, or state that immediate tool pairs have only a per-pair ceiling and remove the shared-budget, eviction, and held-on-session-close claims and tests. Add exact assertions for the emitted `rounds` and `tool_calls` counts and for `kind` on each failure path.

   *Resolution:* accepted. Decision 9 now says what synchronous folding implies: a tool pair is staged and taken in one emission, so it has the per-request ceiling only, joins no shared budget, and has no eviction order or session-close hold; those claims and tests are removed. The tests now assert the over-ceiling drop with `kind=tool_call`, the no-trace discard, and exact `rounds` and `tool_calls` counts.

3. **P2: The plan promises raw valid arguments that the neutral model no longer retains.**
Evidence: Decision 7 says arguments are “exactly as the model sent them,” JSON-encoded. But `vinga-server/src/vinga_server/providers/openai_llm.py:96` parses valid JSON into a `dict` and discards the raw string; `vinga-server/src/vinga_server/providers/base.py:370` retain raw text only for malformed arguments. Anthropic likewise supplies parsed input. Re-encoding changes whitespace and can change key order.
What the plan should say instead: define the field as the reserved neutral claim’s semantic arguments, deterministically JSON-encoded, with malformed calls retaining their raw argument text. Do not claim byte-for-byte provider output unless the plan adds and carries a raw-arguments representation through both adapters, which would conflict with the established neutral-seam boundary.

   *Resolution:* accepted. Decision 7 now defines the arguments as the reserved claim's semantic arguments encoded with the same JSON encoding the `llm` span's `tool_call` parts use (`llm_input_export._call`), says plainly that neither adapter keeps a raw string for a valid call, and keeps raw text only for a malformed call; no byte-for-byte claim and no raw-arguments representation is added.

4. **P2: The tool-content handoff and no-trace release are not concretely plumbed.**
Evidence: `vinga-server/src/vinga_server/runtime/tool_execution.py:460` has no content-export collaborator; `vinga-server/src/vinga_server/runtime/pipeline.py:709` constructs it without one. Telemetry currently keys content only by invocation, and its no-trace tool route simply returns without consuming anything (`vinga-server/src/vinga_server/telemetry.py:3157`). The plan requires a distinct `(invocation, position)` content slot and explicit consumption on both traced and untraced folds, but does not name those changes.
What the plan should say instead: name the `PipelineRuntime` to `ToolExecution` wiring, the tool-specific stage/take/discard API, and a `(invocation, position)` key in telemetry. Require `_tool_span` to consume/discard the slot even when the session trace is absent, with tests covering the no-trace path and two positions in one invocation.

   *Resolution:* accepted. Decision 8 now names the plumbing: `PipelineRuntime` passes the session's `LlmInputExport` to `ToolExecution` as an optional collaborator; the export gains `stage_tool(session, invocation, position, ...)` called by `_run_one` just before the `tool_call` emit and `take_tool(invocation, position)` called by `_tool_span` with the event's own join keys; `_tool_span` takes the slot on every path, discarding it when the session has no trace. Tests cover the no-trace path and two positions in one invocation.

5. **P2: Collector masking is asserted without naming its enforced test surfaces.**
Evidence: Decision 10 adds two content attributes, but `vinga-server/tests/unit/test_telemetry_deploy.py:23` holds the collector’s complete content-key set exactly, and `vinga-server/tests/integration/test_telemetry_fanout.py:43` sends every declared content key through the real collector. Neither is in the plan’s test footprint.
What the plan should say instead: explicitly update both content-key inventories and the fanout test so a credential- and email-shaped value in each new tool field is masked before both sinks. This is the test that substantiates “like the rest,” rather than merely parsing the changed YAML.

   *Resolution:* accepted. Decision 10 names `tests/unit/test_telemetry_deploy.py`'s exact content-key set and `tests/integration/test_telemetry_fanout.py`'s real-Collector path, which sends credential- and email-shaped values in each new field and shows them masked before both sinks.

Verdict: **not ready**. Amend the two P1 design contradictions before implementation, then incorporate the P2 plumbing, fidelity, and masking requirements.
