# The metadata half of a turn's telemetry reaches every backend

Plan for the metadata half of
[#533](https://github.com/rafacm/vinga/issues/533), as scoped by its
Step 0
([comment](https://github.com/rafacm/vinga/issues/533#issuecomment-5923391053)).
Its companion is
`docs/plans/2026-10-01-telemetry-metadata-half-implementation.md`, one
section per milestone, appended in the same change that ticks the
milestone. The content half of the issue (whether the `tool` span
copies arguments and results, and whether memory content earns an
export switch of its own) is Rafael's to decide and is not planned
here; neither pull request closes #533.

**Local baseline:** not applicable. Every change is a count, an
identity, a digest or a timing on an exported span; no conversational
capability moves.

**Cheapest alternative:** for three of the five pieces this plan is
already the cheapest change (one `LLM_ATTRIBUTES` entry for the first
token, one field and one attribute for the fingerprint, one catalog
note for `language_confidence`). Two pieces cost more than the
cheapest thing that would also help, and say what they buy:

- *The tool join.* The cheapest is the provider's call id alone. It
  is not unique within a turn: the OpenAI-compatible adapter mints
  `call_{index}` when a server sends no id
  (`providers/openai_llm.py:127`), so two rounds of one turn can both
  hold a `call_0`. Adding the requesting round's invocation id, which
  the server mints and already exports on the `llm` span, makes the
  join exact for one more field.
- *The memory half.* The cheapest is per-round block sizes, which the
  per-round `Assembled` already holds and the pipeline throws away
  after taking `.text` (`runtime/pipeline.py:2421,2428`); no store
  change. It answers how big the memory half was and not which facts
  were in it, which is the issue's question ("which memory produced a
  given output"). Ids cost one change to `PromptMemory`, whose reads
  already have them and drop them at rendering
  (`memory/store.py:928-945`). The plan takes both: the sizes are
  free and the ids are the point.

Leaving it alone was priced in Step 0: the first token never reaches
the backend this surface exists for, a tool span cannot be tied to the
call it ran, two sessions' prompts cannot be told apart when their
sizes match, and the one size a backend has about a prompt
under-reports it by the whole memory half.

**Attribution:** anthropic/claude-opus-5-5, thinking high; Claude Code 2.1.286; 2026-10-01.

## The parity rule

Decided with Rafael on 2026-10-01 and binding on every milestone here:
**every fact this plan adds to a trace is a span attribute**, so a
plain OTLP backend and Langfuse see the same carrier and a query
written against one runs on the other. Langfuse ingests no span events
at all (established in #67, which is why the tool span replaced its
span event). So where a fact already rides a span event, it is
replaced, not mirrored: the first token below is the case, and it goes
the way #67's tool call went.

## Where this starts from

Measured at `c277d023` (`main`'s head on 2026-10-01).

- `first_token_ms` is on `LlmRound` and `LlmRecap`
  (`events/catalog.py:1883,1922`); `telemetry._llm_span` turns it into
  a `first_token` span event (`telemetry.py:3029-3031`, the constant at
  `telemetry.py:311`), and `LLM_ATTRIBUTES` (`telemetry.py:1058-1072`)
  has no entry for it. TTS carries `vinga.tts.first_chunk_ms` and ASR
  `vinga.asr.duration_s` as attributes.
- `TOOL_ATTRIBUTES` (`telemetry.py:1128-1136`) is agent, conversation,
  source, `is_error`, tool, entry and error. The three `tool_call`
  variants (`BuiltinToolCall`, `McpToolCall`, `UnnamedToolCall`,
  `events/catalog.py:1977` onward; built in `events/assembly.py:220,
  243,273`) carry no call id and no invocation. The executor holds the
  provider's id (`runtime/tool_execution.py:539`). Providers mint ids
  as `call_...` (OpenAI), `toolu_...` (Anthropic), or the adapter's
  `call_{index}` fallback.
- `PromptAssembled` (`events/catalog.py:1748`) carries `characters` and
  `sources` for the know-how half, once per agent activation
  (`runtime/pipeline.py:1092-1118`, whose docstring records why memory
  is outside it: per-round emission would double a round's log volume,
  and `llm_round` already carries per-round numbers). The turn span
  carries them as `vinga.prompt.characters` and `vinga.prompt.sources.*`
  (`telemetry.py:595-597,669-693`). No digest.
- The memory half is read per round (`runtime/pipeline.py:2405-2428`,
  `MemoryStore.read_for_prompt`), rendered to three strings in
  `PromptMemory` (`memory/store.py:418`), and appended by
  `prompt.with_scopes` (`runtime/prompt.py:412-450`) as blocks with
  provenances `state`, `memory`, `device` (`runtime/prompt.py:111-113`).
  The agent block is the newest `CORE_LINES = 40` facts trimmed to a
  byte cap (`_newest`, `_core`); the device block is the device's
  active facts plus the device record; the state block is the
  conversation's ledger (at most `STATE_KEYS = 50` entries). Fact ids
  are in hand at `_newest` and `_active` and dropped by `_rendered` and
  `_core`. The pipeline keeps only `.text` of the per-round
  `Assembled`.
- The recap round's system prompt is `RECAP_INSTRUCTION`, with no
  memory (`runtime/pipeline.py:2153,2162`).
- `_as_attribute` keeps only `str` elements of a sequence
  (`telemetry.py:914-917`), so an integer id list would export as
  nothing through the generic path.
- `language_confidence`: faster-whisper populates it from
  `language_probability` (`providers/faster_whisper.py:146`); the
  OpenAI-compatible transcription provider never does
  (`providers/openai_asr.py:91`). The catalog field
  (`events/catalog.py:1594`) has no note saying so.

## Decisions

### M1: the round and the tool call

1. **First token becomes a round attribute.** `LLM_ATTRIBUTES` gains
   `"first_token_ms": "vinga.llm.first_token_ms"`; the `first_token`
   span event, `FIRST_TOKEN` and the `_after` call that places it are
   removed, and `_llm_span`'s docstring is rewritten to the parity
   reasoning (it currently argues for the event as an instant). It
   applies to a recap round as well as a reply round, since both
   variants carry the field. Absent stays absent: a round that only
   asked for a tool has no attribute, never `0`. Before removing the
   event, `git grep -n first_token` over `vinga-server/` and `docs/`
   (untruncated) lists every reader of the span event, recorded in the
   implementation doc; the expectation from Step 0 is tests only.
2. **The tool span carries the call it ran.** Each `tool_call` variant
   gains two fields, and `TOOL_ATTRIBUTES` maps them:
   - `call_id: ToolCallId | Absent`, exported as the conventions'
     `gen_ai.tool.call.id`. `ToolCallId` is a new `MachineId`-style
     value type with a tight syntax (`[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}`,
     to be confirmed against the three id shapes above and widened only
     with a reason). The provider's id is far-side bytes, and an
     emission whose value fails its type is refused whole, so the
     builder in `events/assembly.py` passes `ABSENT` for an id that
     does not match rather than letting the event fail: a malformed id
     must cost the attribute, never the event.
   - `invocation: InvocationId`, the server-minted id of the round
     that asked for the call, exported under the same
     `LLM_INVOCATION_ID` key the `llm` span uses, so the join is one
     key equal on both spans. One fact, one attribute name. Required,
     not optional: every dispatched call came from a round, and the
     implementer confirms that by reading where `reserve` and dispatch
     run (`runtime/pipeline.py:1838`, `runtime/tool_execution.py`). If
     some path dispatches without a round in hand, the field becomes
     `| Absent` and the path is named in the implementation doc.
   Both are metadata: an opaque provider id and a server-minted id.
   They also reach the retained `tool_call` log line, which is the
   catalog's single home for the event; neither appears in the
   `TEMPLATE`.
3. **The know-how half gets a fingerprint.** `PromptAssembled` gains
   `sha256: Sha256` (a new value type, exactly 64 lowercase hex
   characters), the SHA-256 of the know-how half's text as assembled
   (`half.text`, UTF-8), computed where the event is built. The turn
   span carries it as `vinga.prompt.sha256` beside
   `vinga.prompt.characters`, through `PROMPT_ATTRIBUTES`. Unkeyed and
   unconditional, as the issue asks: the know-how half is
   operator-authored configuration (persona, fragments, MCP guidance),
   not personal data, so a confirmation oracle over it reveals nothing
   an operator does not already hold. That argument does NOT extend to
   the memory half; see decision 6.
4. **`language_confidence` says who fills it.** A `note=` on the
   catalog field: faster-whisper reports it when it detected the
   language rather than being pinned to one; the OpenAI-compatible
   transcription provider never does, so an alert on it never fires
   there. It reaches `docs/reference/events.md` through the generator.

### M2: the memory half, per round

5. **`PromptMemory` carries the ids it rendered.** Two fields beside
   the rendered strings, `agent_ids` and `device_ids`, tuples of the
   fact ids actually injected: for the agent block, the ids of the
   lines `_core` kept after its byte cap, not every id `_newest` read;
   for the device block, the ids of the active facts rendered. The
   rendering functions return the kept ids with the text so the two
   cannot disagree (one structure, derived once). The ledger has no
   ids, and its keys are model-written text, so it contributes no
   identity at all.
6. **No memory fingerprint.** A digest of the memory half is a
   confirmation oracle over low-entropy personal content: one short
   fact ("the child's name is X") is guessable by hashing candidates.
   Ids join a trace to the local store without disclosing anything to
   whoever holds the trace, which is the property the issue argued
   for. What a fingerprint would add (did the memory half change
   between two rounds) the ids answer for facts and the per-block
   sizes approximate for the ledger; the ledger case a size cannot see,
   a `set_state` that keeps its length, is recorded as the known gap.
7. **The round carries it.** `LlmRound` (not `LlmRecap`, whose prompt
   holds no memory) gains, all `| Absent` and absent where memory was
   not read this round (memory off for the agent, no conversation):
   - `system_characters: Count`, the whole system prompt this round
     sent (know-how half, scope blocks and joins), so the per-round
     prompt size is no longer under-reported;
   - `memory_sources`: each scope block's size by provenance (`state`,
     `memory`, `device`), from the per-round `Assembled.sizes()`
     restricted to those three provenances, with a block that is not
     present absent from the mapping rather than `0`; reusing
     `PromptSources` if its grammar admits the three tokens, otherwise
     a closed mapping type whose keys are exactly those three, decided
     by reading `SOURCE_KEY_PATTERN` (`events/values.py:502`);
   - `memory_facts: FactIds`, the agent and device ids in reading
     order, as a new `ID_LIST`-kind value type modeled on `SessionIds`
     (`events/values.py:772`), whose elements are positive integers.
   The emission point stays `ProviderWatch.reply_round_done`, which
   gains one keyword argument carrying the round's memory accounting;
   `_system_prompt` returns the per-round `Assembled` and the ids
   instead of `.text` alone, and the caller takes `.text` where it
   needs the string. Per-round emission adds fields to an event that
   already fires per round, which is the reason `_prompt_assembled`'s
   docstring gives for keeping memory off `prompt_assembled`, so it
   holds and the docstring gains one sentence pointing here.
8. **The `llm` span carries it under the round's own names.**
   `vinga.llm.system.characters`, `vinga.llm.system.sources.<provenance>`
   and `vinga.llm.memory.facts` (the ids), plus
   `vinga.llm.memory.fact_count`, the length of the id list, derived in
   the fold rather than carried as a second field, because a backend
   can filter on a number and cannot on an array's length. Deliberately
   NOT the turn span's `vinga.prompt.*` names: those describe the
   know-how half once per agent, and the same name meaning "half" on
   one span and "whole" on another is the ambiguity this repository's
   one-fact-one-name rule exists to prevent. Ids are exported as
   integers if the attribute fold can carry an integer sequence; since
   `_as_attribute` keeps only strings (`telemetry.py:914-917`), the
   implementer either widens the `SEQUENCE` shape to admit the
   element type the declaration names, or renders ids as decimal
   strings, choosing by what keeps the declaration the single rule and
   recording which.
9. **Bounded.** The id list is bounded by `CORE_LINES` plus the
   device scope's own cap, both named constants in `memory/store.py`;
   the implementer states the bound in the catalog note and adds a
   test that a scope at its cap still yields an emission that is
   accepted (a 40-plus-N element list must not trip any size guard on
   the event or the span).

## Out of scope, with reasons

- **The content half of #533** (arguments and results on the tool
  span; a separate switch for memory text). Rafael's decisions; the
  issue stays open for them.
- **Moving the memory blocks out of the system-prompt head** (#536's
  M2). Closed with #536 and tracked nowhere; M2 here is the
  instrument that would separate write-triggered from spontaneous
  cache misses, and the summary of this run says so.
- **The other session-channel span events.** Of the catalog's 80
  events, 14 are folded into spans; 18 session-channel events
  (`agent_said`, `barge_in`, `barge_in_merged`, `barge_in_suppressed`,
  `conversation_resumed`, `filler_played`, `filler_skipped`,
  `frames_dropped`, `handover`, `llm_retry`, `milestone_recorded`,
  `replied`, `reply_fallback`, `sentence_withheld`, `session_idle`,
  `session_limit`, `session_rejected`, `tool_arguments_coerced`) plus
  `capture_started` reach a trace only as span events, so Langfuse
  shows none of them. Under the parity rule that is a gap, and a
  larger one than this plan: it needs a shape decision (zero-length
  child spans, or attributes on the span the event belongs to) for
  nineteen events. Raised with Rafael as a follow-up issue, not
  folded in. Counted at `c277d023` with a script over `catalog()`
  against the `_folds` table, reproduced in the implementation doc.
- **Langfuse's own time-to-first-token field**
  (`langfuse.observation.completion_start_time`). It would light up
  Langfuse's latency view, and it is a backend-specific alias the
  parity rule exists to avoid; noted for the follow-up above.

## Module layout and design footprint

No new module, seam or config key.

- `events/values.py`: three new value types, `ToolCallId`, `Sha256`,
  `FactIds`, each one rule in one place; possibly a closed mapping for
  the scope sizes (decision 7).
- `events/catalog.py`, `events/assembly.py`: fields on `tool_call`'s
  three variants, `PromptAssembled` and `LlmRound`; builders that drop
  a malformed provider id to `ABSENT` at the boundary.
- `telemetry.py`: `LLM_ATTRIBUTES`, `TOOL_ATTRIBUTES`,
  `PROMPT_ATTRIBUTES` entries; the span event removed; the derived fact
  count. What a backend reader stops having to know: which span a
  timing hides in, and which `llm` content part a tool span ran.
- `memory/store.py`: `PromptMemory` deepens by the ids it rendered;
  callers stop having to re-read the store to learn which facts a
  prompt held.
- `runtime/pipeline.py`, `runtime/provider_watch.py`,
  `runtime/tool_execution.py`: the round's memory accounting and the
  call's invocation threaded to their emission points.

## Tests

Reuse: the span drivers and assertions in
`tests/unit/test_telemetry_spans.py` and `tests/support/telemetry.py`,
the builders' tests in `tests/unit/test_event_assembly.py`, the memory
store tests, the `drive_llm_round` and tool drivers in
`tests/tools/event_baseline.py` with the exact carried-key sets in
`tests/unit/test_event_baseline.py`'s `CARRIED` (which exist to catch
an optional field going missing on the production path), and
`tests/integration/test_telemetry_export.py`.

M1:
- A reply round and a recap round with a first token carry
  `vinga.llm.first_token_ms` and no span events; one without carries
  neither.
- A tool span carries `gen_ai.tool.call.id` and the invocation id equal
  to the requesting `llm` span's; two calls in one round, and two
  rounds each with a `call_0`, are told apart by the pair.
- A provider id that fails `ToolCallId` (a newline, 129 characters, an
  empty string, a credential-shaped value with a space) yields an
  accepted event with the field absent, and the value appears nowhere:
  not in the log line in either format, not on the span (the no-leak
  sentinel).
- `prompt_assembled` carries the digest of exactly the know-how text;
  a persona edit that preserves length changes it.
- The carried-key sets for `tool_call` and `prompt_assembled` gain the
  new fields, driven through the production path.

M2:
- `read_for_prompt` returns the ids of exactly the facts rendered,
  including when `_core`'s byte cap drops some of the newest forty
  (the dropped ids absent) and when the device scope is empty.
- A round after a `remember` carries the new id; a round with memory
  switched off carries none of the M2 fields; a recap carries none.
- `system_characters` equals the length of the system string the
  provider was handed in that round (asserted against what the fake
  provider received, not against a recomputation).
- The span carries the id list, the derived count and the per-block
  sizes; a scope at its cap is still accepted (decision 9).
- The `LlmRound` carried-key set gains the fields, driven through the
  production session path.
- Generated `docs/reference/events.md` regenerates; its drift check is
  the test.

**Falsification, per the lens.** Each new test is watched failing
first. Mutations, one run each (straight-line logic), reported in the
implementation doc: M1, the `LLM_ATTRIBUTES` entry removed; the
malformed-id guard removed (the event-refused test must fail, not
pass); the digest computed over the full prompt instead of the half;
the invocation taken from the wrong round. M2, `_core`'s kept ids
replaced by `_newest`'s read ids (the byte-cap test must fail); the
recap given the fields; the fact count taken from a stale list.

## The live gate

Run on agentpi with the OpenAI providers and the Langfuse export on,
from a scratch driver that is not committed (the #536 rig shape,
`tests/local/test_real_conversation.py` as the model): one session of
a few turns in which the model calls a builtin tool and a `remember`.
Read back through the Langfuse API (or the Langfuse MCP) and record in
the implementation doc, per milestone:

- M1: the `llm` observation shows `vinga.llm.first_token_ms`; the tool
  observation shows `gen_ai.tool.call.id` and the invocation id equal
  to its round's; the turn shows `vinga.prompt.sha256`.
- M2: the round after the `remember` shows the new id in
  `vinga.llm.memory.facts`, and the count and sizes; whether Langfuse
  renders an integer array (or the string rendering decision 8 chose)
  legibly is recorded as observed.
- Observed, not gated: whether Langfuse renders `gen_ai.system_instructions`
  anywhere when `export_llm_input` is on. This is the open question
  from Step 0's §3 row and it informs the content half's decision; it
  costs one more readback.

## Risks

- **A far-side id refuses an event.** The one way M1 can make telemetry
  worse than today, since a refused `tool_call` loses the whole log
  line and span. Mitigated by decision 2's drop-to-absent at the
  builder and its test.
- **Log volume.** M2 adds up to `CORE_LINES` plus the device cap of
  integers to every reply round's retained line. Bounded by decision
  9; the implementer measures one real round's line length before and
  after and records both.
- **A memory read that fails** answers `NOTHING_REMEMBERED` today. The
  fields must then be absent or empty consistently with what the model
  received (no ids for facts it never saw); a test covers the failed
  read.
- **No-leak.** The new string-valued facts are a provider's tool-call
  id (validated, dropped when malformed) and a hex digest; ids are
  integers. No ledger key, no fact text, no prompt byte reaches any
  surface.

## Standing lenses

- *No-leak*: the malformed-id sentinel in M1; M2 adds no string.
- *Pin before reshaping*: `_system_prompt`'s return change and the
  rendering functions' new tuple returns are covered by the existing
  memory and prompt-assembly tests, which must pass byte-unchanged on
  the rendered text; a pin on the exact text `with_scopes` produces
  for a fixed `PromptMemory` is committed before the reshape if none
  exists.
- *Closed sets*: the scope provenances are the three constants in
  `runtime/prompt.py`; no new reason token.
- *Honest seams*: none added.
- *Inventories by tooling*: the `first_token` readers, the `tool_call`
  builder call sites and the `PromptMemory(` construction sites are
  listed by `git grep -n`, untruncated, in the implementation doc.
- *Proportion*: the cheapest-alternative line above.
- *Falsify before claiming*: the mutations above.

## Documentation footprint

- `docs/architecture/observability-surfaces.md`, "Exported traces":
  the first token is an attribute of the generation; a tool call names
  the call and the round that asked for it; a turn carries the
  know-how half's digest; a reply round carries its whole system size,
  the memory blocks' sizes and the ids of the facts injected, with the
  reason ids and not a digest; the parity rule in one sentence. M1
  writes the first three, M2 the rest.
- `vinga-server/README.md`, if its telemetry or cost table names the
  first-token mark or prompt size (checked, and left alone if not).
- `docs/reference/events.md` regenerated; `conversations/docgen.py`'s
  `GEN_AI` table gains `gen_ai.tool.call.id` from `tool_call`, then
  `docs/reference/conversations-schema.md` regenerated (the drift
  check alone cannot see a missing row, as #536's review found).
- `changelog.d/533-tool-and-round-attributes.md` (M1: `### Added` the
  call id, invocation and digest; `### Changed` the first token from a
  span event to an attribute) and
  `changelog.d/533-memory-half-per-round.md` (M2: `### Added`).

## Milestones

M1 and M2 are implemented in parallel off this plan's branch: they
touch the same catalog, telemetry and generated files but different
variants, so the second to merge rebases and regenerates.

- [ ] **M1: the round and the tool call.** Decisions 1 to 4, their
  tests and mutations, the M1 rows of the live gate, its documentation
  footprint. One pull request.
- [ ] **M2: the memory half, per round.** Decisions 5 to 9, their
  tests and mutations, the M2 rows of the live gate, its documentation
  footprint. One pull request; neither closes #533.
