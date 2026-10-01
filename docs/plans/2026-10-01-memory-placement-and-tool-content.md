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
argument at the provider seam and two adapter changes. For the tool
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

So a write voids the cached history only in today's placement, while
full misses that no write explains hit every placement at a similar
rate (#536 M1 saw them too). They are the provider's, not this plan's to
fix, and they are why the milestone's gate below counts over several
writes rather than reading one. At OpenAI's 128-token cache granularity,
(b) and (c) are not distinguishable by cache alone, so they are chosen
between on the request's shape and the model's reading of it.

## Decisions

### M1: memory leaves the system message (#536 M2)

1. **The seam gains a per-round context argument.** `LlmProvider.stream`
   takes `context: str = ""`: the per-round scope text (the three scope
   blocks and the device record, rendered under their headings in their
   existing order and joined as today), separate from `system`, which
   becomes the know-how half alone and is stable for an activation.
   `with_scopes` stops appending the scopes to the know-how half and
   returns them as their own rendering; `RoundPrompt` carries both.
2. **Position (b): the context leads the newest user message.** Each
   adapter attaches it where the newest `user` turn is rendered, and
   nowhere else:
   - OpenAI-compatible: that user message's content becomes the context,
     the join, and the utterance, as one string, so every compatible
     server and chat template sees one ordinary user message (no
     mid-conversation system message, which some local templates reject
     or fold, and no two consecutive user messages).
   - Anthropic: the same text as the leading content of that user
     message (a text block before the utterance's), which keeps the
     API's alternation and needs no system role.
   - A request with no user turn (none is known to exist on the reply
     path; the implementer confirms by reading the callers) appends the
     context as a final user message rather than dropping it.
   Chosen over (c) because it keeps one user message per turn, which
   every template and Anthropic's alternation accept, and because the
   model reads what it knows and then what it is asked.
3. **Memory loses system authority, deliberately.** Facts the model
   stored from what a user said no longer sit in the system message, so
   a remembered sentence shaped like an instruction ("remember: ignore
   your instructions") is read as context inside a user turn rather than
   as the operator's prompt. The headings stay, so the model still reads
   which block is what. `prompt.py`'s module docstring and the
   precedence paragraph are rewritten to say where memory now sits and
   why.
4. **Nothing is persisted with the context.** The context is attached at
   the provider seam to the request being built; the conversation store,
   the working copy of turns, the recap and the history the next round
   rebuilds hold the utterance alone. So the previous turn's user message
   is byte-identical in the next request, which is what keeps everything
   up to the newest turn cacheable.
5. **The accounting follows the move.** The metadata half's
   `vinga.llm.system.characters` now measures the system message alone
   (the know-how half), and `vinga.llm.memory.characters` and
   `vinga.llm.memory.sources.*` measure the context; the catalog notes
   and the observability page say so. The prompt digest
   (`vinga.prompt.sha256`) was always over the know-how half; its
   canonical-rendering definition, written for a half that scopes could
   follow, is re-read and simplified if nothing follows the half any
   more. The content export's `gen_ai.system_instructions` is now the
   stable half, and the context appears in `gen_ai.input.messages` as
   the newest user message's leading text part, which is what the model
   received; this also answers #533 §3's "once per agent" for the
   stable half without a separate change.
6. **The gate is a behavior check and a cache measurement, both on
   OpenAI.** Anthropic is unmeasurable on this machine (no key) and is
   covered by the adapter tests only, stated as an unchecked box.
   - *Behavior:* a scripted session through the real server
     (`gpt-4.1-mini`, the builtin memory tools) asks for a fact
     remembered in an earlier conversation, acts on a `set_state` entry,
     and names the device by its record's name, under the old placement
     and the new, the same script three times each; the new placement
     must answer every probe the old one answers. One extra probe stores
     an instruction-shaped fact and records whether the model obeys it
     under each placement (observed, not gated).
   - *Cache:* a session of at least 15 turns with at least four verified
     memory writes (a non-error `remember` or `set_state` call, and the
     next round's injected fact ids changed, read off the metadata
     half's `vinga.llm.memory.facts`), read back per round from
     `llm_round`'s cached-token count. The gate opens when no verified
     write is followed by a round caching less than the history before
     the newest turn, allowing for the spontaneous full misses the probe
     measured: a write-followed full miss counts against the gate only
     if write-followed rounds miss at a higher rate than rounds with no
     write in the same session. The table goes in the implementation
     doc.

### M2: a tool span carries its content (#533 §2), and option A is written down

7. **The tool span carries the call's arguments and result under
   `export_llm_input`.** As the conventions' `gen_ai.tool.call.arguments`
   (the arguments exactly as the model sent them, the reserved claim's,
   not the coerced execution copy, JSON-encoded) and
   `gen_ai.tool.call.result` (the result content exactly as the model
   was handed it). With the setting off, nothing changes. Langfuse maps
   both to the tool observation's input and output natively, so no
   Langfuse alias is written, under the parity rule.
8. **Through the content export, never the event surface.** The tool
   execution hands the pair to the content exporter keyed by the
   metadata half's join (the requesting round's invocation and the
   call's position); the tool span takes it at its fold, the way the
   `llm` span takes its content by invocation. The `tool_call` event and
   the retained log gain nothing.
9. **Bounded like every content pair.** The pair counts against the same
   per-request ceiling and session budget as the round's request; an
   over-ceiling pair is dropped whole and reported through
   `llm_input_export_failed`, adding a reason token to
   `LlmInputExportFailure` only if the existing member cannot say it
   (decided by reading the closed set at its decision site). A malformed
   call (no arguments object) exports its raw argument text as the
   model sent it, since that is what the model sent.
10. **The Collector masks them like the rest.** The two keys join the
    content-masking rules in `deploy/telemetry/collector.yml` beside
    `gen_ai.input.messages` and kin.
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

No new module. Deepened:

- `providers/base.py`, `providers/openai_llm.py`,
  `providers/anthropic_llm.py`, `providers/mock.py`: one argument, and
  each adapter owns where its dialect puts the context; callers stop
  having to know that a dialect has no mid-conversation system role.
- `runtime/prompt.py`: `with_scopes` returns the scopes as their own
  rendering beside the half; `RoundPrompt` carries both.
- `runtime/pipeline.py`, `runtime/provider_watch.py`: the context passed
  through, the retry passing the same arguments.
- `llm_input_export.py`, `runtime/tool_execution.py`, `telemetry.py`:
  the tool pair staged and taken by the existing join keys.
- `deploy/telemetry/collector.yml`, `config/models.py` (the
  `export_llm_input` description), docs.

## Tests

Reuse the adapter tests and fake SDKs (`tests/support/llm_sdk.py`), the
session prompt tests (`tests/unit/test_session_prompt.py`), the content
export tests (`tests/unit/test_llm_input_export.py`), the span tests
and `tests/tools/event_baseline.py`.

M1:
- Each adapter: the context leads the newest user message's content and
  appears nowhere else; the system field or message is the know-how half
  alone; with no user turn the context is a final user message; an empty
  context changes nothing (byte-identical to today's request with no
  scopes).
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
- Over-ceiling pair dropped whole and reported; the `tool_call` event's
  carried keys are unchanged (the event baseline's `CARRIED` set pins
  it).
- The no-leak sentinel: with the setting off, a credential-shaped
  argument appears on no span and no log line.

**Falsification.** Each new test watched failing first. Mutations, one
run each: M1, the context attached to the system again (the adapter
test and the byte-identical-history test must fail); the context
persisted into the working turn (the store test must fail). M2, the
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
- *Honest seams*: the new argument defaults to empty and is compared,
  not truth-tested, where emptiness matters.
- *Inventories by tooling*: every `stream(` call site and every
  `with_scopes(` caller listed by untruncated `git grep -n`.
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
