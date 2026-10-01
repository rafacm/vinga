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
note for `language_confidence`). Two cost more than the cheapest thing
that would also help, and say what they buy:


- *The tool join.* The cheapest would be the provider's call id
  alone, and it is not available: it is far-side bytes, which the
  content and telemetry ADR keeps off metadata surfaces, and it is not
  even unique within a turn (the OpenAI-compatible adapter mints
  `call_{index}` when a server sends none, `providers/openai_llm.py:127`).
  The plan joins on two server-minted values instead, the requesting
  round's invocation id and the call's position in that round, which
  is exact and discloses nothing.
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
   This is a breaking change to the exported trace schema and is named
   as one: a query, alert or dashboard over the `first_token` span
   event stops matching. No deprecation period, deliberately: the
   parity decision is that one fact has one carrier, the project is
   pre-release with no third-party installation known
   (`docs/adr/2026-08-20-database-upgrades-have-a-compatibility-floor.md`,
   lines 27-28), and an event kept
   "for a while" is the two-carrier state the decision rejects. The
   changelog's `### Changed` entry and the observability page carry the
   migration in one sentence: read `vinga.llm.first_token_ms` on the
   `llm` span, and where an instant is wanted, it is the span's start
   plus that many milliseconds.
2. **The tool span carries the call it ran, in server-minted terms
   only.** The provider's call id is far-side bytes, and the content
   and telemetry ADR keeps far-side bytes off every metadata surface
   (`docs/adr/2026-08-15-content-and-telemetry-are-separate-surfaces.md`);
   the executor's own docstring says the tool boundary keeps "nothing
   far-side" (`runtime/tool_execution.py:185-190`). A syntax check does
   not make it safe, since a credential-shaped id passes any pattern.
   So the join is made from two values the server owns, and the
   provider id stays where it already is, inside the opt-in content
   export. Each `tool_call` variant gains two fields, and
   `TOOL_ATTRIBUTES` maps them:
   - `invocation: InvocationId`, the server-minted id of the round
     that asked for the call, exported under the same
     `LLM_INVOCATION_ID` key the `llm` span uses, so the join is one
     key equal on both spans. One fact, one attribute name. Required:
     the event has one production emission path,
     `ToolExecution._run_one` (`runtime/tool_execution.py:527-537`),
     reached only through `ToolExecution.run`, whose one caller is the
     reply loop (`runtime/pipeline.py:1924`) with the round's
     `invocation` in scope. `run` gains an `invocation` keyword and
     passes it down; the implementer's inventory confirms the single
     call site with an untruncated `git grep -n`.
   - `position: Whole`, the zero-based index of the call in the list
     the model returned for that round (`calls` in the reply loop),
     exported as `vinga.tool.call.position`. It is fixed by enumerating
     `calls` BEFORE `_run_tools` partitions them into executable calls
     and agent moves (`runtime/pipeline.py:2295`), and carried as an
     immutable value with each execution candidate through
     `_run_tools`, `ToolExecution.run`, `_run_one`, `_tool_called` and
     the three assembly builders; enumerating anywhere after the
     partition would number the executable list instead and silently
     close the gaps a move leaves. With the invocation it names exactly
     one call: the content export renders a round's tool calls in that
     order, which the implementer confirms against
     `llm_input_export.py` and pins with a test that the n-th
     `tool_call` part of a round's exported output is the call whose
     span carries position n. Where the model asked for the same
     entry twice in one round, the two spans differ by position.
   Both are server-minted metadata and reach the retained `tool_call`
   log line, the catalog's single home for the event; neither appears
   in the `TEMPLATE`. The conventions' `gen_ai.tool.call.id` is not
   used, because its value would be the provider's id.
3. **The know-how half gets an unkeyed fingerprint** (Rafael,
   2026-10-01, after review rounds 2 to 4 had escalated it to a keyed
   digest and then deferred it). `PromptAssembled` gains
   `sha256: Sha256` (a new value type, exactly 64 lowercase hex
   characters): the SHA-256 of the know-how half's text exactly as
   sent (`half.text`, UTF-8, the whole half including MCP-supplied
   blocks), computed where the event is built. That rendered text is
   the one canonical byte sequence (assembly has already trimmed the
   ends and joined the blocks), so no framing or normalization is
   added. The turn span carries it as `vinga.prompt.sha256` beside
   `vinga.prompt.characters`, through `PROMPT_ATTRIBUTES`, and it
   rides the `prompt_assembled` span event exactly as `characters` and
   `sources` already do; whether that event keeps its span-event half
   is #576's question, not this plan's.
   - **Why unkeyed is within the record.** The content and telemetry
     ADR bars conversation text, far-side bytes and exception message
     text from metadata surfaces; operator configuration is not in its
     content class, and telemetry already exports configuration
     (agent and entry names, models, hosts, per-block prompt sizes
     keyed by fragment name). The observability page's "the system
     prompt with its memory and know-how blocks" is content because
     the whole assembled request carries conversation history and
     memory, not because the know-how half alone is. A digest carries
     none of an MCP block's bytes, so the far-side rule is not engaged
     either.
   - **The residual risk, stated rather than engineered away.** A
     digest of the whole ~3.9 KB half confirms a guess only when the
     guesser already holds every other byte, so the realistic case is a
     persona copied from a known template with one personal slot
     filled in. The observability page says so in one sentence: personal
     facts belong in memory, which is never digested (decision 6), not
     in the persona.
   - **Tested:** the digest of exactly the know-how text; a persona
     edit that preserves length changes it; two activations on the same
     prompt carry the same value; a change to MCP-supplied text changes
     it; the turn span carries it on every turn that agent speaks.
     Mutation: the digest computed over something other than
     `half.text` (for example the persona alone) must fail the MCP-text
     test.
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
   for. The join is to the store's CURRENT state and is best effort,
   and the catalog note and the observability page say so: a corrected
   fact keeps its id with new text (`memory/store.py:983-1025`), a
   pruned or deleted one leaves no row, and deletion through the API is
   a hard delete. What the model actually read at the time is the
   content export's to carry (`export_llm_input`), not this field's. No
   row version rides beside each id: it would double the list to answer
   a historical question the content export already answers for any
   deployment that wants it. What a fingerprint would add (did the memory half change
   between two rounds) the ids answer for facts and the per-block
   sizes approximate for the ledger; the ledger case a size cannot see,
   a `set_state` that keeps its length, is recorded as the known gap.
7. **The round carries it.** `LlmRound` (not `LlmRecap`, whose prompt
   holds no memory) gains the fields below. The sizes describe the
   prompt actually sent, so they are present on every completed reply
   round whatever the agent's memory setting: with memory off the
   prompt still holds the know-how half and may hold a device block
   carrying the live device record (`runtime/pipeline.py:2417-2421`).
   The fact list says what memory contributed, so it is present, and
   possibly empty, wherever this round read memory (`_remembering_now()`
   true), and absent where memory is switched off for the agent, which
   is a different fact from "read, and held nothing". A read that failed
   answers `NOTHING_REMEMBERED` today and the model saw no fact, so its
   list is empty; the failure itself is already `memory_unreadable`'s
   to report.
   - `system_characters: Count`, the whole system prompt this round
     sent (know-how half, scope blocks and joins), so the per-round
     prompt size is no longer under-reported;
   - `memory_characters: Count`, the exact number of characters
     `with_scopes` appended to the know-how half this round: the scope
     blocks and the joins that precede each of them in the full text,
     reported by prompt assembly itself where it renders them and
     carried on `RoundPrompt`. Never a subtraction of the half's text
     from the full text: `_assembled` leaves a one-block prompt as it
     is but `lstrip`s the first block once scopes add a second, so the
     full text need not begin with `half.text`. Never a sum of block
     sizes either, which omits the joins. What `_assembled` sends the
     model does not change. A regression test assembles a one-block
     half with a leading-whitespace persona plus a memory block and
     checks the count against the string the provider received.
     The device block holds the device record as well as the device's
     notes (`runtime/prompt.py:470-485`), so this is the per-round half
     of the prompt rather than remembered facts alone, and its note
     says so;
   - `memory_sources`: each scope block's size by provenance (`state`,
     `memory`, `device`), from the `Assembled` actually sent, restricted
     to those three provenances, with a block that is not present absent
     from the mapping rather than `0` (so a memory-off round with a
     device record reports its `device` block). The type is
     `MemorySources`, a new closed mapping value type whose keys are
     exactly the three provenance constants of `runtime/prompt.py` and
     whose values are character counts; not `PromptSources`, whose
     grammar is deliberately know-how-only
     (`events/values.py:1113-1138` and `prompt_assembled`'s note);
   - `memory_facts: FactIds`, the agent and device ids in reading
     order, as a new `ID_LIST`-kind value type modeled on `SessionIds`
     (`events/values.py:772`), whose elements are positive integers.
   The handoff is one value, `RoundPrompt`, a frozen dataclass in
   `runtime/prompt.py` built where `with_scopes` is called: the
   per-round `Assembled` that was sent, the know-how `Assembled` it was
   built on, and `facts: tuple[int, ...] | None`, where `None` means
   this round did not read memory (`_remembering_now()` false) and `()`
   means it read and injected nothing, including a read that failed
   and fell back to `NOTHING_REMEMBERED`. `PromptMemory` cannot carry
   that distinction (a failed read and an empty one are the same value
   there), and it does not need to: whether a read was attempted is
   known at the call site, which is where `None` is chosen.
   `_system_prompt` returns a `RoundPrompt` instead of `.text`, the
   caller takes `.text` where it needs the string, and the event fields
   are derived from the one value on both the success path
   (`ProviderWatch.reply_round_done`, one new keyword) and the failure
   path (decision 7a), so the two cannot disagree. Per-round emission adds fields to an event that
   already fires per round, which is the reason `_prompt_assembled`'s
   docstring gives for keeping memory off `prompt_assembled`, so it
   holds and the docstring gains one sentence pointing here.
7a. **A failed reply round carries it too.** A round that fails after
   its request was assembled is the case where prompt size most often
   matters (a context-length refusal), and today it emits
   `provider_failed` instead of `llm_round`. So `ProviderFailed` gains
   the same optional fields, populated only for an LLM-stage failure of
   a reply round and absent for every other stage and for a recap. The
   path: `reply_stream` gains a keyword carrying the round's
   `RoundPrompt`, built once before the stream starts, and it reaches
   `failed` by BOTH routes that end a reply round in failure: through
   `watched`, for a failure the stream raises, and directly, for the
   watchdog's second first-token timeout, which `reply_stream` reports
   with its own `self.failed(...)` call
   (`runtime/provider_watch.py:253`). `failed` hands it to
   `assembly.provider_failure` beside the `invocation` it already
   passes.
   The first-token watchdog's retry re-sends arguments fixed before the
   first attempt (`runtime/pipeline.py:1785-1792`), so a second-attempt
   failure carries the same accounting, which is correct. The failed
   `llm` span (`telemetry.py`'s `_provider_failed`) maps the same
   attributes as decision 8. Tested: a provider failure after the
   request was assembled, and the watchdog's direct second-timeout
   branch (driven so that `reply_stream`'s own `failed` call is the
   one that fires, not a stream-raised failure), each carrying the
   accounting; an ASR and a TTS failure
   carrying none.
8. **The `llm` span carries it under the round's own names.**
   `vinga.llm.system.characters`, `vinga.llm.memory.characters`,
   `vinga.llm.memory.sources.<provenance>` (the three scope blocks
   only; the know-how half's blocks are the turn span's
   `vinga.prompt.sources.*`, and the whole total is
   `vinga.llm.system.characters`, which the children are not meant to
   sum to) and `vinga.llm.memory.facts` (the ids), plus
   `vinga.llm.memory.fact_count`, the length of the id list, derived in
   the fold rather than carried as a second field, because a backend
   can filter on a number and cannot on an array's length. The count
   is emitted only when the fact list is present: `0` for a read that
   injected nothing, absent when memory was off, never
   `len(payload.get(..., []))`, which would turn "off" into "empty".
   The per-provenance keys cannot come from the generic fold, which
   exports a mapping value as one JSON attribute
   (`telemetry.py:771-793`), and the attribute tables cannot name a
   wildcard suffix; so a validated helper analogous to
   `_prompt_attributes` flattens `MemorySources` into exactly the three
   provenance keys, and both `_llm_span` and the LLM branch of
   `_provider_failed` compose it. Deliberately
   NOT the turn span's `vinga.prompt.*` names: those describe the
   know-how half once per agent, and the same name meaning "half" on
   one span and "whole" on another is the ambiguity this repository's
   one-fact-one-name rule exists to prevent. Ids are exported as
   integers. `_as_attribute` keeps only the strings of a sequence today
   (`telemetry.py:914-917`), so its `SEQUENCE` arm is widened to keep a
   sequence that is homogeneously `str` or homogeneously `int` (a
   `bool` is not an `int` here), after the declared value type has
   accepted it as now, and to export nothing for a mixed one. A
   regression test pins that a `SessionIds` value exports exactly as
   it does today.
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
  nineteen events. Filed as #576 on 2026-10-01, not
  folded in. Counted at `c277d023` with a script over `catalog()`
  against the `_folds` table, reproduced in the implementation doc.
- **Langfuse's own time-to-first-token field**
  (`langfuse.observation.completion_start_time`). It would light up
  Langfuse's latency view, and it is a backend-specific alias the
  parity rule exists to avoid; noted for the follow-up above.

## Module layout and design footprint

No new module, seam or config key.

- `events/values.py`: three new value types, `Sha256`, `FactIds` and
  `MemorySources`, each one rule in one place.
- `events/catalog.py`, `events/assembly.py`: fields on `tool_call`'s
  three variants, `PromptAssembled`, `LlmRound` and `ProviderFailed`.
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
- A tool span carries the invocation id equal to the requesting `llm`
  span's and its position in that round; two calls to the same entry
  in one round differ by position, and two rounds' first calls differ
  by invocation. A round of executable calls on both sides of an
  agent move emits positions that keep the move's gap (0 and 2, not 0
  and 1). With content export on, the n-th exported `tool_call`
  part of a round is the call whose span carries position n.
- The no-leak sentinel: a provider call id that is credential-shaped
  and syntactically clean (`sk_live_` followed by 24 alphanumerics) is
  absent from the `tool_call` log line in both formats and from every
  attribute of the tool span, with content export off.
- The carried-key sets for `tool_call` and `prompt_assembled` gain the
  new fields, driven through the production path.

M2:
- `read_for_prompt` returns the ids of exactly the facts rendered,
  including when `_core`'s byte cap drops some of the newest forty
  (the dropped ids absent) and when the device scope is empty.
- A round after a `remember` carries the new id; a round with memory
  switched off carries the sizes (including a `device` block when the
  device has a record) and no fact list; a round whose memory read
  failed carries an empty fact list; a recap carries none of the
  fields.
- `system_characters` equals the length of the system string the
  provider was handed in that round (asserted against what the fake
  provider received, not against a recomputation), and
  `memory_characters` equals the characters of the scope blocks and
  their preceding joins in that string; a round with two scope blocks
  proves the joins are counted, and the leading-whitespace one-block
  case proves the count survives the trim.
- The span carries the id list, the derived count and the per-block
  sizes as individual `vinga.llm.memory.sources.*` attributes, on a
  successful and on a failed reply span; a scope at its cap is still
  accepted (decision 9).
- Facts, empty and disabled, each on the event and the span, on the
  success and failure paths: the count is the length, `0`, and
  absent respectively.
- The `LlmRound` carried-key set gains the fields, driven through the
  production session path.
- Generated `docs/reference/events.md` regenerates; its drift check is
  the test.

**Falsification, per the lens.** Each new test is watched failing
first. Mutations, one run each (straight-line logic), reported in the
implementation doc: M1, the `LLM_ATTRIBUTES` entry removed; the
position taken from the partitioned list instead of the model's
(the move-gap test must fail); the invocation taken from the wrong round. M2, `_core`'s kept ids
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
  observation shows the invocation id equal to its round's and its
  position; the turn shows `vinga.prompt.sha256`.
- M2, **blocking**: the round after the `remember` shows the new id in
  `vinga.llm.memory.facts`, and the count and sizes, read back through
  the Langfuse public API as values a query can use (the id array
  returned with its elements, not dropped, stringified as one opaque
  blob, or truncated). If integer arrays fail that, the encoding falls
  back to the one alternative that can meet the same gate, an array
  of decimal strings (the fold's existing string-sequence path),
  re-gated the same way, with the event type, the attribute fold and
  the catalog note changed in the same milestone. A single joined
  string is not an option: it is the opaque blob the gate rejects. If
  neither array passes, M2 stops and the finding goes to Rafael rather
  than lowering the gate. M2's pull request does not open until one
  encoding passes; which one, and
  the observation ids, are recorded in the implementation doc. The
  same readback is taken from the fake-tracer test's OTLP side only as
  a validity check, since it cannot speak for the backend.
- Observed, not gated: whether Langfuse renders `gen_ai.system_instructions`
  anywhere when `export_llm_input` is on. This is the open question
  from Step 0's §3 row and it informs the content half's decision; it
  costs one more readback.

## Risks

- **Log volume.** M2 adds up to `CORE_LINES` plus the device cap of
  integers to every reply round's retained line. Bounded by decision
  9; the implementer measures one real round's line length before and
  after and records both.
- **A memory read that fails** answers `NOTHING_REMEMBERED` today. The
  fields must then be absent or empty consistently with what the model
  received (no ids for facts it never saw); a test covers the failed
  read.
- **No-leak.** The one new string-valued fact is a hex digest of
  operator configuration (decision 3, with its residual risk stated);
  positions and ids are integers, and the invocation is
  server-minted. No ledger key, no fact text, no prompt byte reaches any
  surface.

## Standing lenses

- *No-leak*: the credential-shaped call-id sentinel in M1; M2 adds
  no string.
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
  the call by its round and its position in that round; a turn
  carries the know-how half's SHA-256, with the one-sentence residual
  risk; a reply round carries its whole system size,
  the memory blocks' sizes and the ids of the facts injected, with the
  reason ids and not a digest, and that an id resolves against the
  store's current state only; the parity rule in one sentence. M1
  writes the first three, M2 the rest.
- `vinga-server/README.md`, if its telemetry or cost table names the
  first-token mark or prompt size (checked, and left alone if not).
- `docs/reference/events.md` regenerated. No new conventions' key is
  added (decision 2 dropped `gen_ai.tool.call.id`), but the guard that
  keeps `conversations/docgen.py`'s `GEN_AI` table complete covers only
  the `llm` span today
  (`tests/unit/test_conversations_docgen.py:241-253`), so M1 extends it
  to every conventions-prefixed key `TOOL_ATTRIBUTES` maps, which today
  includes `gen_ai.tool.name`. Any row the extension shows missing is
  added and `docs/reference/conversations-schema.md` regenerated
  through its generator (the drift check alone cannot see a missing
  row, as #536's review found).
- `changelog.d/533-tool-and-round-attributes.md` (M1: `### Added` the
  tool call's round and position, and the prompt digest; `### Changed` the first token from a
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

## Plan review round

Reviewed 2026-10-01 by openai/gpt-5.6-sol, thinking high via codex CLI 0.156.1, read-only sandbox, runtime 6m01s, at commit b13d1437, plan blob 36e71b0d.

---

1. **P1: M2 never exports the memory character total required by §5.**
   **Evidence:** Issue #533 §5 requires memory identity, count, and character total. The plan exports the whole system length plus individual block lengths (`docs/plans/2026-10-01-telemetry-metadata-half.md`, Decisions 7–8, lines 185–224). `Assembled.sizes()` counts block text only (`runtime/prompt.py:339-342`), excluding blank-line joins, while the device block also includes the device record rather than only remembered facts (`runtime/prompt.py:470-485`). Consequently neither the individual sizes nor their sum is the exact memory-half character total.
   **Plan should say instead:** Add a specifically defined `memory_characters` field and `vinga.llm.memory.characters` attribute, computed from the exact incremental text `with_scopes` added to the know-how half, including joins. Test it against the actual system string supplied to the provider.

   *Resolution:* accepted. Decision 7 adds `memory_characters`, the exact text `with_scopes` appended to the know-how half, joins included, computed as a difference of the two texts with the prefix asserted; decision 8 exports it as `vinga.llm.memory.characters`; the tests pin it against the string the provider received with two blocks present. Its note says it includes the device record, since that shares the device block, so it is the per-round half of the prompt rather than remembered facts alone.

   *Resolution:* accepted, by the first alternative. Decision 2 no longer exports the provider's call id at all: the tool span joins its round on two server-minted values, the requesting round's invocation id (already on the `llm` span) and the call's position in the list the model returned, which names exactly one call and discloses nothing. The provider id stays inside the opt-in content export, where it already is; `gen_ai.tool.call.id` is not used. The sentinel now plants a syntactically clean credential-shaped id (`sk_live_` plus 24 alphanumerics) and asserts it reaches neither log format nor any span attribute; `ToolCallId` and its drop-to-absent builder are gone, and so is the risk they mitigated.

   *Resolution:* accepted, by the keyed alternative. Decision 3 now exports `vinga.prompt.digest`, an HMAC-SHA256 of the know-how half exactly as sent, keyed by a labelled subkey of the newest `VINGA_MASTER_KEY` entry (the `onboarding/keys.py` derivation pattern), derived once at composition and injected. Lifecycle stated: no master key, no digest; a rotation changes every digest from that boot on. The sentinel asserts the value matches neither the public SHA-256 of the prompt nor of a planted guess, and that neither key appears on any surface. Because a keyed digest is not an oracle, round 2's restriction to authored blocks is reversed and the whole half is covered. Flagged to Rafael as a decision taken in review: the fingerprint now exists only on deployments that set a master key.

   *Resolution:* accepted, by obtaining the decision rather than weakening the requirement silently: decision 3 is withdrawn from this plan and deferred to Rafael with the three shapes priced (a stored installation key generated at first boot, a digest only where a master key is set, or none). Nothing in this plan emits a digest, so the issue's "unconditionally" is not contradicted, only not yet delivered; the Step 0 comment and the PR say so.

2. **P2: The memory-off test contradicts both the field definition and current prompt behavior.**
   **Evidence:** Decision 7 defines `system_characters` as the whole system prompt, but makes every M2 field absent when memory is off; the tests repeat that expectation (`docs/plans/...`, lines 185–205 and 309–317). `_system_prompt` still assembles and sends the know-how prompt when memory is off, and may still append the live device record through `with_scopes(..., NOTHING_REMEMBERED, record)` (`runtime/pipeline.py:2417-2428`; `runtime/prompt.py:412-453`). Thus a real system prompt, and potentially a `device` block, exists in precisely the case the proposed test requires all accounting to disappear.
   **Plan should say instead:** Make `system_characters` present on every completed reply generation. Derive source sizes from the actual `Assembled` sent, so a device block remains reported when present even with remembered facts disabled. Specify separately whether an unread or disabled fact list is absent or empty.

   *Resolution:* accepted. Decision 7 now splits the two kinds of field: the sizes describe the prompt actually sent and are present on every completed reply round, memory on or off, so a device block carrying the live record is reported either way; the fact list is present (possibly empty) wherever the round read memory and absent where memory is switched off, and a failed read yields an empty list because the model saw no fact. The memory-off and failed-read tests are rewritten to match.

   *Resolution:* accepted, by the first alternative. The premise was wrong: the know-how half holds `server_instructions:` and `server_prompt:` blocks an MCP server supplied. Decision 3 now digests only the operator-authored blocks (`persona`, `fragment:`, `instructions:`), classified by provenance kind with any future kind excluded by default, and exports it as `vinga.prompt.authored.sha256` so the name says what it covers. MCP-supplied text stays visible only as sizes. The tests add the sentinel the finding asks for: a low-entropy value planted in `ServerInstructions` text changes no exported digest, and the mutation that digests the whole half must fail it.

   *Resolution:* accepted. Decision 2 fixes the position by enumerating `calls` before `_run_tools` partitions them, and carries it immutably through `_run_tools`, `ToolExecution.run`, `_run_one`, `_tool_called` and the builders. A new test puts executable calls on both sides of an agent move and asserts the gap survives (0 and 2), and the mutation now targets that test, which the same-entry case could not expose.

   *Resolution:* accepted. Decision 7 now has prompt assembly report the scope contribution where it renders the blocks (scope blocks plus their preceding joins), carried on `RoundPrompt`, with no subtraction and no change to what the model is sent. The leading-whitespace one-block regression case is added. Also sent to the M2 implementer while it runs.

3. **P2: Fact IDs do not provide the stable historical join the plan claims.**
   **Evidence:** The plan says IDs let a trace join back to the local store and answer which facts produced an output (`docs/plans/...`, lines 32–40 and 176–184). Existing facts are mutable under the same ID (`memory/store.py:983-1025`), are deleted by cap pruning (`memory/store.py:1924-1971`), and can be permanently or operator-deleted; the observability contract explicitly says facts last only until corrected and that API deletion is hard deletion (`docs/architecture/observability-surfaces.md`, Memory, lines 183–196). A later lookup can therefore return changed text or no row at all.
   **Plan should say instead:** Describe the IDs as a best-effort correlation to current local state, not historical identity. If historical version identity is required, carry a non-content row version such as the fact’s update timestamp and acknowledge that deleted or superseded content remains unreconstructible without the content export. Add correction, pruning, and hard-deletion tests for the documented behavior.

   *Resolution:* accepted in part. Decision 6 now states that the id join is best effort and to the store's current state (a correction keeps the id with new text, pruning and API deletion leave no row), and the catalog note and the observability page say the same; the historical text is the content export's to carry. Rejected: a per-id row version, which doubles the list to answer a historical question `export_llm_input` already answers, and new correction, prune and delete tests, since those behaviors belong to the memory store and its existing tests pin them; nothing in this plan changes them.

   *Resolution:* accepted. Decision 7 now defines the handoff as one value, `RoundPrompt` (the sent `Assembled`, the know-how `Assembled`, and `facts: tuple[int, ...] | None`, `None` for no read attempted and `()` for a read that injected nothing, a failed read included), chosen at the call site where the attempt is known, and derived into the event fields on both the success path and decision 7a's failure path.

   *Resolution:* accepted. Decision 7a now threads `RoundPrompt` to `failed` by both routes: through `watched` for a stream-raised failure, and directly into `reply_stream`'s own retry-exhaustion `self.failed(...)` call. The watchdog test is specified to drive that direct branch.

   *Resolution:* moot after finding 1's resolution: with no digest there is no key to derive, so no composition change and no secrets API is added. The finding's correction stands for whichever shape Rafael picks: the composition root is the lifespan in `app.py`, and `config/secrets.py` would need a narrow derivation function rather than exposing key material.

4. **P2: Failed LLM requests lose all proposed per-round memory metadata.**
   **Evidence:** M2 adds fields only to `LlmRound` and threads them only through `reply_round_done` (`docs/plans/...`, lines 185–208). A stream failure emits `ProviderFailed` instead (`runtime/provider_watch.py:134-166,409-458`), and telemetry turns that into the actual failed `llm` span (`telemetry.py:2952-2990`). The existing LLM-content export deliberately finishes and attaches the failed request by invocation, but the planned memory accounting has no equivalent path. The proposed tests cover successful rounds and recaps only.
   **Plan should say instead:** Decide how reply memory accounting reaches an LLM `ProviderFailed` event and span, then name the required changes to `reply_stream`/`watched`/`failed` or an invocation-keyed staging mechanism. Test provider failure after request assembly and the second-watchdog failure.

   *Resolution:* accepted. New decision 7a: `ProviderFailed` gains the same optional fields for an LLM-stage reply-round failure only, threaded `reply_stream` to `watched` to `failed` to `assembly.provider_failure` beside the invocation those already carry, and the failed `llm` span maps them. Tests cover a failure after assembly, a second-attempt watchdog failure, and ASR and TTS failures carrying none.

   *Resolution:* accepted. M1 extends `test_every_convention_the_llm_span_speaks_has_its_row`'s guard to every conventions-prefixed key `TOOL_ATTRIBUTES` maps. Since finding 1's resolution removed `gen_ai.tool.call.id`, the extension adds no new key, but it covers the existing `gen_ai.tool.name`; any row it finds missing is added and `conversations-schema.md` regenerated.

   *Resolution:* accepted. The collision came from round 2's concatenation of selected blocks, which finding 1's resolution removed: the digest input is now `half.text` exactly as sent, the one canonical sequence, already trimmed and joined by assembly, with no further normalization. Tests added for a boundary-moving edit and for whitespace both inside a block and at a trimmed end.

   *Resolution:* accepted. Decision 8 adds a validated flattening helper beside `_prompt_attributes` that emits exactly the three `vinga.llm.memory.sources.*` keys, composed into `_llm_span` and the LLM branch of `_provider_failed`, with tests on successful and failed reply spans. Sent to the M2 implementer while it runs.

5. **P2: Several schema decisions are still deferred to implementation.**
   **Evidence:** The plan leaves the tool-ID grammar “to be confirmed,” invocation requiredness conditional on later discovery, the source mapping type conditional on reading a pattern that already explicitly excludes memory, and integer versus decimal-string fact IDs undecided (`docs/plans/...`, lines 126–143, 191–200, 218–224). `PromptSources` confirms that its grammar is intentionally know-how-only (`events/values.py:1113-1138`), while `_as_attribute` currently strips integers from every sequence (`telemetry.py:896-917`). These choices determine the public event and OTLP schemas and cannot safely be implementation notes.
   **Plan should say instead:** Commit to a separate closed memory-source mapping, integer-valued `FactIds`, and a sequence fold that preserves homogeneous integers after the declared value type accepts them, with a regression test that existing string `SessionIds` remain unchanged. Also settle the accepted tool-ID grammar and make invocation definitively required on the only production emission path.

   *Resolution:* accepted. Settled in the plan: a new closed `MemorySources` mapping (not `PromptSources`, which is know-how-only by design); integer `FactIds` with the `SEQUENCE` fold widened to homogeneous `str` or `int` sequences, `bool` excluded, mixed exporting nothing, and a `SessionIds` regression pin; the tool-call id grammar `[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}`; and `invocation` required, with the single production emission path named (`_run_one` via `run`, one caller at `pipeline.py:1924`).

   *Resolution:* accepted. The M2 rows of the live gate are now blocking: the id array must come back through the Langfuse public API as usable values, and if integer arrays fail, the encoding falls back to decimal strings, then to one comma-joined string, each re-gated, with the event type, fold and note changed in the same milestone. M2's pull request does not open until one encoding passes.

   *Resolution:* accepted. The comma-joined fallback is removed; the only fallback is an array of decimal strings, re-gated the same way, and if neither array passes M2 stops and the result goes to Rafael rather than the gate being lowered.

   *Resolution:* moot after finding 1's resolution: `PromptAssembled` gains no field, so nothing new reaches its span event. The point carries to the deferred decision: a digest on `prompt_assembled` must be excluded from the span-event projection, or it is two carriers.

6. **P2: Removing the first-token event creates an unhandled upgrade break.**
   **Evidence:** Decision 1 deletes the existing precisely timestamped `first_token` event (`docs/plans/...`, lines 113–123), although issue #533 §4 proposed an attribute alongside the event and its common notes call the changes backward compatible. Current OTLP consumers can query or visualize that event (`telemetry.py:2994-3032`). Repository grep can find tests and documentation, but cannot inventory dashboards, alerts, or downstream collectors in running deployments. The changelog entry records the change but supplies no compatibility period or migration guidance.
   **Plan should say instead:** Preserve the event while adding the attribute, at least for a documented deprecation period. If the parity decision intentionally permits immediate removal, state that it is a breaking telemetry-schema change, document the query migration, and test both the retained temporal mark and the new backend-portable attribute.

   *Resolution:* accepted in part. Decision 1 now names the removal as a breaking change to the exported trace schema and gives the migration in one sentence (read `vinga.llm.first_token_ms`; the instant is the span start plus that many milliseconds), carried by the changelog's `### Changed` entry and the observability page, and the span test asserts the round carries no span event. Rejected: keeping the event for a deprecation period. Rafael decided on 2026-10-01 that one fact has one carrier so OTLP backends and Langfuse see the same thing; the project is pre-release with no third-party installation known (the compatibility-floor ADR, lines 27-28); and an event kept for a while is the two-carrier state that decision rejects. The issue's "alongside" wording predates the decision, which the Step 0 comment records.

   *Resolution:* accepted. Decision 8 states the count is emitted only when the fact list is present, `0` for an empty read and absent when memory is off, and the tests cover all three states on the event and the span, success and failure paths. Sent to the M2 implementer while it runs.

7. **P2: `vinga.llm.system.sources.*` falsely presents a partial source inventory as the whole system’s sources.**
   **Evidence:** The plan pairs `vinga.llm.system.characters`, defined as the whole system prompt, with `vinga.llm.system.sources.*`, populated only from `state`, `memory`, and `device` (`docs/plans/...`, lines 188–197 and 209–217). Persona, fragments, and MCP guidance are also system-prompt sources but are deliberately excluded. A backend reader will reasonably expect the children of `system.sources` to account for `system.characters`; they cannot.
   **Plan should say instead:** Name the restricted mapping `vinga.llm.memory.sources.*` or export the complete source inventory under `system.sources.*`. Keep the whole-system total separate and document whether joins are represented by the explicit memory total from finding 1.

   *Resolution:* accepted. The per-round block sizes export as `vinga.llm.memory.sources.<provenance>`, the three scope blocks only, beside `vinga.llm.memory.characters` (finding 1), which is the exact per-round total including joins; `vinga.llm.system.characters` stays the whole prompt with no `system.sources` children, so nothing invites summing a partial inventory to it.

**Verdict:** not ready.

## Plan review round 2

Reviewed 2026-10-01 by openai/gpt-5.6-terra, thinking high via codex CLI 0.156.1, read-only sandbox, runtime 4m29s, at commit 544a1b6a, plan blob f8a7ceaa.

---

1. **P1: Raw provider call IDs violate the no-leak boundary.**
   **Evidence:** Plan Decision 2 exports `ToolCall.id` after only a character-pattern check. That value comes directly from OpenAI-compatible fragments and Anthropic `block.id` (`providers/openai_llm.py:126-132`, `providers/anthropic_llm.py:194-196`). The existing tool boundary explicitly says it keeps “nothing far-side” (`runtime/tool_execution.py:185-190`), and the telemetry ADR forbids far-side bytes on retained surfaces (`docs/adr/2026-08-15-content-and-telemetry-are-separate-surfaces.md:12-14, 49-54`). The proposed regex accepts credential-shaped or user-derived strings without whitespace, including `sk_live_...`; the planned sentinel only tests one containing a space.
   **Plan should say instead:** Do not place the raw provider ID on metadata surfaces. Use a server-minted per-call correlation key, or explicitly change the governing no-leak decision with an approved exception and test valid-syntax secret-shaped IDs as well as malformed ones. If raw-ID correlation is required, keep that mapping only in the existing opt-in LLM-content export.

2. **P1: The unconditional prompt hash can disclose MCP-server content.**
   **Evidence:** Decision 3 calls the entire know-how half “operator-authored configuration,” then exports its SHA-256 unconditionally. That premise is false: `prompt.know_how()` includes `ServerInstructions` and `ServerPrompt` text supplied by a connected MCP server (`runtime/prompt.py:262-294, 345-381`), and the module deliberately avoids putting server-chosen prompt names on metadata surfaces (`runtime/prompt.py:304-307`). A deterministic hash is a confirmation oracle, exactly the reason Decision 6 rejects a memory hash. The proposed hash test covers only a persona edit, not remote supplied text.
   **Plan should say instead:** Resolve the trust classification before implementation. Either restrict the unconditional digest to demonstrably operator-owned blocks, put a digest of any server-supplied prompt material behind the content-export policy, or amend the telemetry/content boundary deliberately. Add a sentinel test using an MCP-supplied low-entropy secret that proves it cannot be confirmed from an exported trace when content export is off.

   *Superseded 2026-10-01:* decision 3 is restored as an unkeyed SHA-256 of the whole know-how half, on Rafael's decision after he questioned the premise. The content and telemetry ADR bars conversation text, far-side bytes and exception message text from metadata surfaces, and operator configuration is in none of those classes; a digest of the whole ~3.9 KB half confirms a guess only when every other byte is already known, which is stated as a residual risk in the observability page rather than engineered away with key management. This finding's restriction to authored blocks is withdrawn with it: a digest carries none of an MCP block's bytes.

3. **P2: The memory-fact absent-versus-empty contract has no representable handoff.**
   **Evidence:** Decision 7 requires an absent list when memory is disabled and an empty list after a failed read, but says `_system_prompt` returns only the `Assembled` prompt and “the ids” (`docs/plans/2026-10-01-telemetry-metadata-half.md:215-251`). `PromptMemory` currently represents an unreadable read as the same `NOTHING_REMEMBERED` value used for no facts (`memory/store.py:418-442, 898-945`). A tuple of IDs alone cannot preserve the required distinction.
   **Plan should say instead:** Define the accounting handoff explicitly, for example `memory_facts: tuple[int, ...] | None`, where `None` means no memory read was attempted and `()` means a read produced no injected facts. Thread that single accounting value through successful and failed reply paths.

4. **P2: The required generated GenAI documentation row is not protected by the planned tests.**
   **Evidence:** The plan correctly notes that reference drift cannot detect an omitted `GEN_AI` row (`docs/plans/2026-10-01-telemetry-metadata-half.md:477-480`), but M1 names no test for it. The existing completeness test checks only `LLM_ATTRIBUTES` against `docgen.GEN_AI` (`tests/unit/test_conversations_docgen.py:241-253`), not `TOOL_ATTRIBUTES`; regeneration alone remains green if `gen_ai.tool.call.id` is never added.
   **Plan should say instead:** Add a test extending the completeness check to every convention-prefixed mapping on both `LLM_ATTRIBUTES` and `TOOL_ATTRIBUTES`, then regenerate `conversations-schema.md`.

5. **P2: Integer-array backend support is treated as an observation, not an acceptance criterion.**
   **Evidence:** Decision 8 commits to integer `vinga.llm.memory.facts`, while the live gate says that whether Langfuse renders it legibly will merely be “recorded as observed” (`docs/plans/2026-10-01-telemetry-metadata-half.md:274-291, 419-422`). This plan’s stated outcome is metadata reaching every supported backend. The fake-tracer tests can establish OTLP validity but cannot establish Langfuse ingestion or queryability.
   **Plan should say instead:** Set a pass/fail requirement for the supported backend before M2 lands. If integer arrays are not returned and usable through its API, choose and document a portable scalar encoding, update the event type and attribute fold accordingly, and make the live gate block completion rather than merely record the result.

Verdict: **not ready.**

## Plan review round 3

Reviewed 2026-10-01 by openai/gpt-5.6-terra, thinking high via codex CLI 0.156.1, read-only sandbox, runtime 4m22s, at commit a4d42a46, plan blob 071320d8.

---

1. **P1: The unkeyed prompt digest is a content-confirmation oracle.**
Evidence: Plan Decision 3 calls for an unconditional SHA-256 of persona, fragments, and operator `instructions:` blocks, while rejecting a memory digest for exactly that oracle risk. Those blocks are prompt content and can contain low-entropy sensitive values; exported traces are an off-host metadata surface. [observability-surfaces.md](/tmp/claude-1001/-home-rafa-agents-Develop-projects-vinga/aa462fd6-7d97-495a-affb-5a7676a882e0/scratchpad/wt/533/docs/architecture/observability-surfaces.md:435) says the system prompt is content exported only under `export_llm_input`; the content/telemetry ADR requires source-side exclusion of content.
What the plan should say instead: retain the unconditional, comparable fingerprint decision, but make it a stable installation-private keyed digest, with explicit key lifecycle and rotation semantics. Add a no-leak test proving that hashing a guessed operator prompt or secret with public SHA-256 cannot reproduce the exported fingerprint.

   *Superseded 2026-10-01:* decision 3 is restored as an unkeyed SHA-256 of the whole know-how half, on Rafael's decision after he questioned the premise. The content and telemetry ADR bars conversation text, far-side bytes and exception message text from metadata surfaces, and operator configuration is in none of those classes; a digest of the whole ~3.9 KB half confirms a guess only when every other byte is already known, which is stated as a residual risk in the observability page rather than engineered away with key management. The finding is rejected in substance: it classified the know-how half as content by reading the observability page's description of the whole assembled request.

2. **P1: The proposed tool-position plumbing loses the only position the plan promises.**
Evidence: Decision 2 says `ToolExecution.run` merely gains an `invocation` keyword. Today `PipelineRuntime._run_tools` partitions the original `calls` into `plain` and `moves`, then calls `ToolExecution.run(self._turn, plain)`; `ToolExecution.run` and `_run_one` receive only `(slot, call)` ([pipeline.py](/tmp/claude-1001/-home-rafa-agents-Develop-projects-vinga/aa462fd6-7d97-495a-affb-5a7676a882e0/scratchpad/wt/533/vinga-server/src/vinga_server/runtime/pipeline.py:2295), [tool_execution.py](/tmp/claude-1001/-home-rafa-agents-Develop-projects-vinga/aa462fd6-7d97-495a-affb-5a7676a882e0/scratchpad/wt/533/vinga-server/src/vinga_server/runtime/tool_execution.py:444)). Enumerating there produces a position in the partitioned executable list, not in the provider-returned list. The specified “two calls to the same entry” test does not expose this unless a move is interleaved.
What the plan should say instead: carry an immutable original `call_position` with every execution candidate from the enumeration of `calls` before partitioning, through `_run_tools`, `ToolExecution.run`, `_run_one`, `_tool_called`, and the assembly builders. Add a test with executable calls on both sides of a move, asserting the emitted positions retain the original gaps, plus the content-export correspondence.

3. **P2: The failed-watchdog route named in the plan does not carry the new accounting.**
Evidence: Decision 7a says `reply_stream` passes accounting to `watched`, which passes it to `failed`. But a second first-token timeout calls `self.failed(...)` directly inside `ProviderWatch.reply_stream`, not via `watched` ([provider_watch.py](/tmp/claude-1001/-home-rafa-agents-Develop-projects-vinga/aa462fd6-7d97-495a-affb-5a7676a882e0/scratchpad/wt/533/vinga-server/src/vinga_server/runtime/provider_watch.py:253)). The plan nevertheless claims that this exact failure has prompt accounting.
What the plan should say instead: thread `RoundPrompt` into both `watched(...)` and the direct retry-exhaustion `self.failed(...)` call, then through `failed`, `assembly.provider_failure`, and `_provider_failed`. Make the watchdog test exercise the direct second-timeout branch, not only a provider-raised stream failure.

4. **P2: The digest’s byte representation is underspecified and can collide for different prompts.**
Evidence: Decision 3 says eligible blocks are “joined in assembly order” but does not specify delimiters, trimming, or provenance framing. Actual prompt assembly trims end blocks and joins blocks with `"\n\n"` ([prompt.py](/tmp/claude-1001/-home-rafa-agents-Develop-projects-vinga/aa462fd6-7d97-495a-affb-5a7676a882e0/scratchpad/wt/533/vinga-server/src/vinga_server/runtime/prompt.py:514)). Concatenating `["ab", "c"]` and `["a", "bc"]` gives the same digest input despite distinct rendered prompts. The proposed same-length persona-edit test does not catch this.
What the plan should say instead: define one canonical byte sequence, derived after assembly, with an unambiguous delimiter or length framing for each eligible rendered block. Add a test for a boundary-changing edit with identical concatenation, plus a test covering leading/trailing whitespace normalization.

   *Superseded 2026-10-01:* the input is `half.text` as sent, as this finding's resolution already settled; it carries over to the restored unkeyed digest unchanged.

5. **P2: The final Langfuse fallback contradicts its own acceptance gate.**
Evidence: The live gate requires `vinga.llm.memory.facts` to arrive as queryable individual values, “not … stringified as one opaque blob,” yet its final fallback is one comma-joined decimal string. That fallback is necessarily one opaque attribute and cannot meet the stated gate.
What the plan should say instead: remove the comma-joined fallback, or explicitly change the contract and prove a delimiter-safe backend query for an individual ID, including IDs such as `1` versus `11`. Keep the typed-array or decimal-string-array alternatives as the only encodings that satisfy the present requirement.

Verdict: **not ready** until the P1 findings are resolved; then ready after the P2 amendments.

## Plan review round 4

Reviewed 2026-10-01 by openai/gpt-5.6-terra, thinking high via codex CLI 0.156.1, read-only sandbox, runtime 4m07s, at commit 4c669b40, plan blob 4af184e1.

---

1. **P1: The fingerprint is not unconditional as the issue requires.**
Evidence: Issue #533 §3 requires “a fingerprint, unconditionally.” Plan Decision 3 instead makes `vinga.prompt.digest` absent whenever `VINGA_MASTER_KEY` is unset. `config/secrets.py:146-180` explicitly permits that common deployment state.
What the plan should say instead: provide a durable installation-private key for every deployment, with storage, rotation, and upgrade behavior specified, or obtain an explicit issue-level decision to weaken the unconditional requirement. Do not silently turn it into a master-key-only feature.

   *Superseded 2026-10-01:* decision 3 is restored as an unkeyed SHA-256 of the whole know-how half, on Rafael's decision after he questioned the premise. The content and telemetry ADR bars conversation text, far-side bytes and exception message text from metadata surfaces, and operator configuration is in none of those classes; a digest of the whole ~3.9 KB half confirms a guess only when every other byte is already known, which is stated as a residual risk in the observability page rather than engineered away with key management. "Unconditionally" is met: the digest needs no key.

2. **P1: The proposed memory-character calculation fails for valid prompts.**
Evidence: Plan Decision 7 defines `memory_characters` as `len(full.text) - len(half.text)`, guarded by an assertion that `half.text` is a prefix. But `runtime/prompt.py:_assembled` preserves a one-block prompt unchanged while trimming the first block with `lstrip()` when scopes create a second block. Thus `know_how("  persona")` followed by `with_scopes(...memory...)` produces a full prompt that does not begin with `half.text`.
What the plan should say instead: make prompt assembly return the scope contribution as part of its own result, with an explicit rule for any normalization it performs, or change assembly so appending scopes preserves the cached half byte-for-byte. Add a leading-whitespace one-block regression case.

3. **P2: The key derivation is assigned to the wrong module and lacks a safe key interface.**
Evidence: The plan’s module layout assigns derivation to `composition.py`, but that file is only the `Composition` resource declaration. The actual composition root is the lifespan in `vinga-server/src/vinga_server/app.py`, which builds `bespoke_runtime_factory`. Meanwhile `config/secrets.py:146-180` exposes only `MultiFernet`, not the newest raw key material required by the specified HMAC derivation.
What the plan should say instead: name `app.py` as the composition site, add a narrowly scoped secrets API that derives the labelled subkey without exposing key material, and name the factory/runtime constructor and test-fixture plumbing that receive it.

4. **P2: The memory-source attributes cannot be produced by the stated generic fold.**
Evidence: Decision 8 requires separate keys such as `vinga.llm.memory.sources.state`. The existing generic mapping fold emits any `Kind.SOURCES` value as one deterministic JSON attribute (`telemetry.py:771-793`, `_as_attribute`), while only `_prompt_attributes` has bespoke flattening logic. `LLM_ATTRIBUTES` and `FAILED_PROVIDER_ATTRIBUTES` cannot express a wildcard suffix.
What the plan should say instead: add and name a validated memory-attribute helper, analogous to `_prompt_attributes`, that flattens only `state`, `memory`, and `device`; compose it into both `_llm_span` and the LLM branch of `_provider_failed`. Test the individual attributes on successful and failed reply spans.

5. **P2: The digest violates the plan’s own one-carrier parity rule.**
Evidence: Adding `digest` to `PromptAssembled` makes it reach the existing `prompt_assembled` span event through `_span_event`, while Decision 3 also puts it on turn-span attributes through `_prompt_attributes` (`telemetry.py:2595-2628`). The plan says newly added trace facts must be span attributes and that a fact should be replaced, not mirrored, when span events are not portable.
What the plan should say instead: explicitly exclude the digest from the prompt span-event projection while retaining it as a turn attribute, or record and justify an exception to the parity rule. Test the selected carrier, including its absence from the other.

   *Superseded 2026-10-01:* with the digest restored it rides the `prompt_assembled` span event exactly as `characters` and `sources` already do, so it adds no carrier its siblings lack; whether that event keeps its span-event half is #576's question.

6. **P2: The fact-list absence semantics are not pinned through the derived count.**
Evidence: Decision 7 distinguishes disabled memory (`memory_facts` absent) from an attempted empty or failed read (`memory_facts: []`). Decision 8 derives `memory.fact_count` in telemetry, but the tests only require “no fact list” for memory-off. A straightforward `len(payload.get("memory_facts", []))` implementation exports `0` for disabled memory, erasing the distinction the plan says matters.
What the plan should say instead: specify that `vinga.llm.memory.fact_count` is emitted only when the fact-list field is present, is `0` for an attempted empty read, and is absent when memory was disabled. Test all three states on both event and span projections.

Verdict: **not ready.**
