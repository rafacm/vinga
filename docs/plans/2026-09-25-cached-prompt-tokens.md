# The cached share of a prompt is reported

Plan for [#536](https://github.com/rafacm/vinga/issues/536) M1 only,
as scoped by its Step 0
([comment](https://github.com/rafacm/vinga/issues/536#issuecomment-5827438060)).
Its companion is
`docs/plans/2026-09-25-cached-prompt-tokens-implementation.md`, one
section per milestone, appended in the same change that ticks the
milestone. M2, moving the volatile memory blocks out of the
system-prompt head, stays gated on the number this milestone produces
and is not planned here; the pull request for M1 does not close #536.

**Local baseline:** not applicable. The change reports a count the
provider already sends; no conversational capability moves.

**Cheapest alternative:** the issue's own M1 minus its second spelling,
which is what this plan is. The issue proposed carrying the cached
count twice, once under the conventions' name and once in the
backend's `usage_details`, on the grounds that the backend would lift
the conventions' key verbatim and never price it. Step 0 measured that
against the live backend and it does not hold: the conventions' key
alone is mapped, subtracted from `input` and priced at the cached rate,
while a `usage_details` string replaces the mapping wholesale. So the
second spelling buys nothing and costs a second structure that must
agree with the first. Leaving the problem alone was priced there too:
an LLM cost that is an upper bound on every deployment, overstated by
the cached share times the rate gap (three quarters of the cached
tokens' price on `gpt-4.1`), and no way to tell a working cache from
none.

**Attribution:** anthropic/claude-opus-5-5, thinking high; Claude Code 2.1.282; 2026-09-25.

## Where this starts from

Measured at `ca0e24c2` (`main`'s head on 2026-09-25).

- `Usage` carries `prompt_tokens` and `completion_tokens` only
  (`providers/base.py:341-342`).
- The OpenAI-compatible adapter builds it from `chunk.usage`
  (`providers/openai_llm.py:273-276`) and never reads
  `prompt_tokens_details`. It asks for usage only when the host is
  OpenAI's (`_ask_for_usage`, line 197), and reads usage a compatible
  server volunteers unasked.
- The Anthropic adapter builds it from `message.usage.input_tokens`
  and `output_tokens` (`providers/anthropic_llm.py:199-202`). Anthropic's
  `input_tokens` excludes both `cache_read_input_tokens` and
  `cache_creation_input_tokens`. The adapter sets no `cache_control`
  anywhere, and caching on that API is opt-in by breakpoint, so its
  read count is expected to be zero today; that is inferred from the
  API's documented behavior, not measured, since this machine holds no
  Anthropic key.
- The counts reach the event through one function,
  `runtime/provider_watch._reported` (line 53), into
  `events/assembly.llm_rounded` (line 414), which builds `LlmRound` or
  `LlmRecap` (`events/catalog.py`, the two variants' `input_tokens` and
  `output_tokens` fields).
- `telemetry.LLM_ATTRIBUTES` (line 1037) maps the event's fields onto
  the `llm` span. The span carries no `usage_details`, and
  `test_a_round_is_not_given_a_second_usage_spelling`
  (`tests/unit/test_telemetry_spans.py:1210`) already pins that.

**The backend gate (Step 0, five spans, `gpt-4.1`, input 2000, output
10).** With `gen_ai.usage.cache_read.input_tokens: 1500` alone the
backend stored `input 500, input_cached_tokens 1500, output 10` and
priced it at $0.00183; the same with no cache attribute cost $0.00408.
A `usage_details` of `{"input":2000,"input_cached_tokens":1500,...}`
double counted ($0.00483), and one of `{"input_cached_tokens":1500}`
dropped `input` and `output` entirely. The table is in the Step 0
comment.

## Decisions

The issue's M1 decisions, as Step 0 confirmed or amended them.

1. **`Usage` gains `cached_prompt_tokens: int | None = None`.** The
   SDK-shaped name, like its siblings, because `Usage` is not surface
   (`provider_watch`'s docstring says so). Its meaning is fixed in the
   docstring: the part of `prompt_tokens` the provider served from its
   prompt cache, so always a subset of `prompt_tokens`, never a
   sibling. `None` means the endpoint did not say, which is a
   different fact from `0`, the endpoint saying nothing was cached.
2. **The OpenAI-compatible adapter** reads
   `chunk.usage.prompt_tokens_details.cached_tokens`, where either
   level may be absent: `prompt_tokens_details` is `None` from many
   compatible servers, and `cached_tokens` inside it may be `None`
   too. Either absence yields `None`. `prompt_tokens` is untouched,
   since OpenAI's already includes the cached prefix. Nothing changes
   in what is asked for: `stream_options` stays OpenAI-host-only, and
   a compatible server that does not volunteer usage yields no
   `Usage` at all, exactly as today.
3. **The Anthropic adapter normalizes on the OpenAI reading.**
   `prompt_tokens` becomes `input_tokens + (cache_read_input_tokens or
   0) + (cache_creation_input_tokens or 0)`, and `cached_prompt_tokens`
   is `cache_read_input_tokens` as reported (`None` when the SDK field
   is `None`). Creation tokens join the input total because they are
   input the model read; they are not exported as a count of their own
   (see "Out of scope"). While the adapter sets no breakpoints both
   cache fields read zero or absent and the reported input is
   unchanged; the fold is what keeps it correct the day they do not.
4. **The event field is `cache_read_input_tokens`,** on both
   `LlmRound` and `LlmRecap`, `Count | Absent`, default `ABSENT`,
   declared right after `input_tokens`. The name is the conventions'
   `gen_ai.usage.cache_read.input_tokens` adapted to the field style
   the siblings already use (`input_tokens` from
   `gen_ai.usage.input_tokens`), and its note says it is a subset of
   `input_tokens` and that absence is a fact about the endpoint. A
   recap reports it for the same reason it reports the other two: it
   is a generation that cost something.
5. **The `llm` span carries it as
   `gen_ai.usage.cache_read.input_tokens`,** one more entry in
   `LLM_ATTRIBUTES`, and nothing else. No `usage_details` on the `llm`
   span, for the reason the gate gives, and the existing pin that says
   so stays and gains the cached case.
6. **`_reported` returns three counts,** and `ProviderWatch`'s round
   method passes the third to `llm_rounded`. What `rounded` returns to
   its caller does not change shape, so no migration, no store column
   and no view moves. Its input count is the adapter's `prompt_tokens`,
   though, which `reply_round_done` files on the turn
   (`turn.round_done`, summed in `runtime/turns.py` into `turns` and
   `turns.legs`, stored, and summed by the metrics views). So decision
   3's fold DOES reach stored accounting: once an Anthropic entry
   caches, its turns' `input_tokens`, the API reads of them and the
   token metrics count the cached and created input they omitted
   before. Rows already stored are not rewritten, so an Anthropic token
   series has a discontinuity at the upgrade the day caching becomes
   active; today, with no breakpoints set, nothing moves. It is named
   in the changelog fragment and the PR's compatibility note, and a
   turn-accounting test pins that the turn's input total is the
   normalized `prompt_tokens`, the cached share neither added a second
   time nor subtracted.

## Out of scope, with reasons

- **A cached column on the stored turn or in the metrics views.** The
  issue's M1 names `llm_round` and the span; a stored total is a
  migration and a generated-reference change for a number whose worth
  M1 exists to find out.
- **A cache-write count** (`gen_ai.usage.cache_write.input_tokens`,
  Anthropic's `cache_creation_input_tokens`). No adapter can produce a
  non-zero one today, since nothing sets a breakpoint, and the backend
  mapping for it was not gated. It is folded into input (decision 3)
  and stops there.
- **Setting Anthropic `cache_control` breakpoints.** A behavior change
  of its own, and only worth an issue if M1's OpenAI number says
  caching matters.
- **M2**, as the issue says.

## Module layout and design footprint

No new module, seam or config key. Deepened, each by one field and
one read:

- `providers/base.py`: `Usage` gains the field and its meaning.
- `providers/openai_llm.py`, `providers/anthropic_llm.py`: each
  adapter reads its provider's cached count and, for Anthropic,
  normalizes input to include it. What callers stop having to know
  stays what it was: which vendor's usage shape they are reading.
- `events/catalog.py`, `events/assembly.py`: one field on two variants
  and one argument to `llm_rounded`.
- `runtime/provider_watch.py`: `_reported` grows by one count.
- `telemetry.py`: one `LLM_ATTRIBUTES` entry.

## Tests

Reuse the existing assets: `tests/support/llm_sdk.py`'s fake SDK
chunks and usage objects (extended with the details fields, defaulting
to what they produce today), the `round_done`/`finish_reply` span
drivers in `tests/unit/test_telemetry_spans.py`, and the assembly and
provider-watch tests beside them.

- **Adapters, OpenAI-compatible:** a usage chunk with
  `prompt_tokens_details.cached_tokens` yields it; one with no
  details, and one with details but `cached_tokens: None`, yield
  `None`, never `0`; `prompt_tokens` is what the chunk said; a
  cached count above `prompt_tokens`, a negative, a `bool` and a
  non-integer each yield `None` (the subset invariant, see Risks).
- **Adapters, Anthropic:** cache read and creation fold into
  `prompt_tokens` and the read count is `cached_prompt_tokens`; both
  fields `None` leaves `prompt_tokens` equal to `input_tokens` and
  `cached_prompt_tokens` `None`.
- **Event:** `llm_rounded` carries the count on a reply round and on a
  recap; `None` is `ABSENT`, `0` is `Count(0)`.
- **Provider watch:** a round whose `Usage` carries a cached count
  emits it; one with no `Usage` emits none.
- **Span:** the `llm` span carries
  `gen_ai.usage.cache_read.input_tokens` beside `input_tokens`, carries
  no key for it when the event had none (not `0`), and still carries
  no `usage_details`.
- **The event-path inventory:** `tests/tools/event_baseline.py`'s
  `drive_llm_round` gives its `Usage` a non-zero
  `cached_prompt_tokens` (below its `prompt_tokens`), and
  `cache_read_input_tokens` joins the exact `LlmRound` carried-key set
  in `tests/unit/test_event_baseline.py`'s `CARRIED`. That driver runs
  the production session path, so this is what proves the field
  survives the reply loop rather than only the builder; the table
  exists to catch exactly optional usage plumbing going missing.
  Whether the recap driver there reaches a `Usage` is checked, and if
  it does, its `LlmRecap` set gains the field too.
- The catalog reference (`docs/reference/events.md`) regenerates
  through its generator; the drift check is the test.

**Falsification, per the lens.** Each new test is watched failing
before the code that satisfies it, and three mutations are run once
each (straight-line logic, so one run proves it) and reported: the
Anthropic fold removed (the `prompt_tokens` assertion must fail), the
OpenAI `None` collapsed to `0` (the absence test must fail), and the
`LLM_ATTRIBUTES` entry removed (the span test must fail).

## The live measurement

M1 is a measurement milestone with a code deliverable; the issue's
verification list is the milestone's, less the question Step 0
already answered. Run on agentpi against OpenAI, with the Langfuse
export on, from a scratch driver that is not committed.

**The rig.** A server on the implementer's worktree with OpenAI ASR,
LLM and TTS, one agent with the builtin memory tools, telemetry on.
The driver follows `tests/local/test_real_conversation.py`: questions
synthesized to 16 kHz PCM once (OpenAI TTS), sent through the
xiaozhi-sdk client one per turn, the `llm_round` events read off the
server's event stream. OpenAI caches only a prompt of 1024 tokens or
more, so the agent's prompt is sized to clear that from round one
(the observed deployment session was already 6363 tokens by turn 20),
and the model is stated in the record.

- **Cached fraction per round across a session**: at least eight
  turns, `cache_read_input_tokens / input_tokens` per `llm_round`,
  tabulated in the implementation doc.
- **Whether a memory write voids the cache, as a controlled
  comparison.** Two arms, identical agent, prompt and questions: a
  control arm that never writes, and a treatment arm asked to remember
  something at turns three and six.
  - *Isolation.* Every arm starts from memory verified empty (the
    agent's memory listed through the CLI before the first turn and
    the listing recorded), and memory is cleared after every arm, so
    no arm inherits another's facts through `remember`'s persistence
    across conversations. With memory empty the assembled system
    prompt is byte-identical at the start of every arm.
  - *Counterbalancing.* Four sessions in the order control,
    treatment, treatment, control, so neither arm always runs on the
    warmer cache and a TTL or eviction effect shows up in both arms
    rather than posing as the treatment.
  - *The intervention is verified, not assumed.* A treatment turn
    counts only when the round carried a non-error `tool_call` for
    `remember` or `set_state`, read off the events, and the next
    round's system instructions (the `llm` span's
    `gen_ai.system_instructions`, telemetry text on) are shown to
    contain the new fact. A turn where the model declined is re-asked
    once and otherwise recorded as a failed intervention, not a data
    point.
  - *What is expected, stated before the run.* A provider prompt cache
    matches the longest common prefix, so a write should make the
    NEXT round miss everything after the start of the memory block,
    and the round after that should cache again against the new
    prefix. The expected signature is therefore one near-uncached
    round per write, not a fraction that stays down; the per-round
    table shows which it is.
  - *The gate.* M2's gate opens when, at every verified intervention
    in both treatment sessions (four in all), the round after the
    write reports cached tokens no larger than the prompt ahead of the
    memory block, while the control sessions' same-numbered rounds
    cache at least half their input. Anything less, including a
    signature that holds at some interventions and not others, is
    recorded as not reproduced and M2 stays closed. The record also
    states what the gate does not measure: how often real sessions
    write memory, which is what turns one uncached round per write
    into a cost.
- **The endpoint reports the field**: OpenAI's does or does not,
  recorded. A self-hosted compatible endpoint cannot be checked on
  this machine (no local runner installed), so that box stays
  unchecked with the reason; "no number available" is the expected
  honest answer there and the tests already pin that it renders as
  absence rather than zero.
- **The price is right on a real span**: one `llm` observation from
  the run read back from the backend, its `usageDetails` showing
  `input` net of `input_cached_tokens` and its cost at the cached
  rate, confirming the Step 0 gate on a span the server wrote rather
  than one a script did.

## Risks

- **Double counting.** The one way this change can make the reported
  cost worse than today. Mitigated by decisions 1 and 5 (subset
  semantics, no second spelling), the pinned absence of
  `usage_details`, and the live readback above.
- **The Anthropic input figure moves** once breakpoints exist, upward
  by the cached and created share. A correction rather than a
  regression; it goes in the PR description and the changelog entry.
- **A compatible server that sends malformed details** (a
  `prompt_tokens_details` object without the attribute, or a
  non-integer, or a cached count larger than the prompt it is part
  of). Read with `getattr(..., None)` and kept only when both
  `prompt_tokens` and `cached_tokens` are non-negative `int`s (not
  `bool`s) and `cached_tokens <= prompt_tokens`; otherwise the cached
  count is `None`. Two reasons: the event's `Count` raises on a
  negative or a non-integer, and decisions 1 and 5 rest on the count
  being a subset, since the backend subtracts it from input, so an
  over-total count would export a negative uncached input and a wrong
  price. The adapter is where a vendor's malformed value stops. Tested
  case by case: `None`, negative, `bool`, non-integer, and over-total.
  The Anthropic count is a subset by construction after the fold, so
  it needs only the type guard. The existing two counts have no such
  guard today; that asymmetry is recorded, not fixed here.
- **No-leak.** Counts only; nothing string-valued is added to any
  surface.

## Standing lenses

- *No-leak*: nothing new is a string; no test needed beyond the
  existing surfaces'.
- *Pin before reshaping*: nothing is moved; `_reported`'s widening is
  covered by the provider-watch tests that exist plus the new one.
- *Closed sets*: none added.
- *Honest seams*: the details reads compare `is not None`, never
  truthiness, which is exactly the `0` versus `None` distinction.
- *Inventories by tooling*: the `LLM_ATTRIBUTES` consumers and every
  `Usage(` construction site are listed by `git grep -n` in the
  implementation doc, untruncated.
- *Proportion*: the cheapest-alternative line above, measured.
- *Falsify before claiming*: the three mutations above.

## Documentation footprint

- `vinga-server/README.md`, "What a conversation cost": the
  Generation row gains the cached count and one sentence that it is
  part of the input count, which the backend prices at its cached
  rate.
- `docs/architecture/observability-surfaces.md`, the paragraph that
  lists what each provider stage carries (around line 211): the
  generation's cached count, and that it is the conventions' name
  alone because the backend maps it.
- `docs/reference/events.md`: regenerated, never hand-edited.
- `conversations/docgen.py`'s `GEN_AI` table, which owns the
  project-field-to-OTel-attribute correspondence: one row,
  `cache_read_input_tokens` to `gen_ai.usage.cache_read.input_tokens`,
  found on the `llm_round` event; then `docs/reference/conversations-schema.md`
  regenerated through its generator. The drift check alone would stay
  green without this, since the table is the generator's input.
- A `changelog.d/536-cached-prompt-tokens.md` fragment under
  `### Added` (the count) and `### Fixed` (the Anthropic input total,
  with the stored-accounting discontinuity from decision 6).

## Milestones

- [x] **[M1: the cached share of a prompt is reported](2026-09-25-cached-prompt-tokens-implementation.md#m1-the-cached-share-of-a-prompt-is-reported)**
  (PR TBD; M2's gate not opened as written, see the measurement). Decisions 1 to
  6, the tests and mutations above, the documentation footprint, and
  the live measurement recorded in the implementation doc with the
  per-round table and the two-session comparison. One pull request;
  it does not close #536, and its body says whether M2's gate opened.

## Plan review round

Reviewed 2026-09-25 by openai/gpt-5.6-sol, thinking high via codex CLI 0.156.1, read-only sandbox, runtime 6m21s, at commit 550a2530, plan blob 88033235.

---

1. **P2: Anthropic normalization does change stored turn accounting.**
   **Evidence:** The plan says turn accounting is “untouched” (`docs/plans/2026-09-25-cached-prompt-tokens.md`, Decisions 3 and 6, lines 91-118). In reality, `ProviderWatch.reply_round_done` passes normalized `prompt_tokens` into `TurnUnderway.round_done` (`runtime/provider_watch.py:295-309`), which accumulates it into turn and leg totals (`runtime/turns.py:156-177`) that are persisted (`conversations/store.py:1909,1927`) and summed by the metrics views. Existing rows are not rewritten, so Anthropic token time series change semantics at the upgrade boundary once caching is active.
   **Plan should say instead:** No schema migration or cached-token column is needed, but normalized Anthropic totals deliberately change `turns.input_tokens`, `turns.legs[*].input_tokens`, API reads, and token metrics. Name that historical discontinuity, cover it with a turn-accounting/storage assertion, and include it in the changelog and PR compatibility notes.

   *Resolution:* accepted. Decision 6 now says the fold reaches `turns`, `turns.legs`, the API reads and the metrics views through `reply_round_done`, names the discontinuity at the upgrade (inert until an Anthropic entry caches), and adds a turn-accounting test pinning the turn's input total to the normalized `prompt_tokens`. The changelog fragment and the PR carry the compatibility note.

2. **P2: The generated GenAI correspondence reference is missing from the documentation footprint.**
   **Evidence:** `conversations/docgen.py:74-88,385-395` owns the table mapping project event fields to OpenTelemetry attributes; it already includes event-only mappings such as `model`, `type`, and `host`. The proposed `cache_read_input_tokens` mapping belongs there, but the plan’s documentation footprint (`docs/plans/...`, lines 257-269) names only the README, observability page, and `events.md`. Leaving the generator unchanged produces a green drift check while the generated correspondence table remains incomplete.
   **Plan should say instead:** Add `cache_read_input_tokens → gen_ai.usage.cache_read.input_tokens`, located on `llm_round`, to `conversations/docgen.py`, then regenerate `docs/reference/conversations-schema.md`.

   *Resolution:* accepted. The documentation footprint names the `GEN_AI` row and the regenerated `conversations-schema.md`, with the reason the drift check cannot catch the omission.

3. **P2: The live A/B cannot attribute a cache drop to memory as written.**
   **Evidence:** The plan uses one agent for two sessions, merely “asks” one session to remember, and treats a difference as causal (`docs/plans/...`, lines 192-209). `remember` explicitly persists facts across conversations (`tools/builtin.py:199-224,770-792`), so whichever session runs second can inherit the treatment. A model may also decline or fail to call the tool, and two sequential runs do not control for TTL or cache eviction despite the plan claiming they do. No repeatability threshold defines when M2’s gate opens.
   **Plan should say instead:** Start both arms from verified empty memory and isolate their namespaces or databases while keeping byte-identical prompts; interleave or counterbalance their turns; require a successful non-error `tool_call` for `remember` or `set_state`; verify that the next assembled request actually changed; repeat the intervention; and define the gate as a reproducible treatment-only drop of a stated magnitude, not any single observed drop.

   *Resolution:* accepted, and it exposed a second error in the plan: prefix caching predicts one uncached round per write, not a fraction that "stays down", so the old wording would have misread a correct result. The measurement is now two arms from verified-empty memory cleared after each, counterbalanced as control, treatment, treatment, control, with two verified interventions per treatment session (a non-error `remember`/`set_state` call and the fact visible in the next round's system instructions), the expected signature stated in advance, and a gate defined over all four interventions against the control arms. Isolation is by clearing rather than by separate namespaces, since a second agent or database would change the prompt the arms are meant to share.

4. **P2: The promised cached-subset invariant is not enforced.**
   **Evidence:** Decisions 1 and 5 rely on cached tokens always being a subset because the backend subtracts them from input (`docs/plans/...`, lines 75-80 and 109-113). The malformed-input handling only checks that the value is a non-negative integer (`lines 231-238`). `Count` validates only `int >= 0` (`events/values.py:840-852`), so a compatible endpoint reporting 1,500 cached tokens with 1,000 prompt tokens would be exported and could create negative uncached input or invalid pricing.
   **Plan should say instead:** At the OpenAI-compatible adapter, retain the cached count only when both counts are valid integers and `0 <= cached_tokens <= prompt_tokens`; otherwise report the cached count as absent. Add an over-total test in addition to the null, negative/non-integer, and boolean cases.

   *Resolution:* accepted as written. The malformed-input risk now keeps the cached count only when both counts are valid and `0 <= cached <= prompt`, states why the subset is load-bearing for the price, and the adapter tests list the over-total case beside the null, negative, boolean and non-integer ones.

5. **P2: The event-path inventory will not exercise the new optional field.**
   **Evidence:** `tests/tools/event_baseline.py:663-672` drives the production `llm_round` path with a `Usage` that has only input and output counts. `tests/unit/test_event_baseline.py:333-344,438-533` explains that its exact carried-key inventory exists specifically to catch optional usage plumbing silently disappearing. The plan names assembly and provider-watch tests but not this driver or its `CARRIED` declaration.
   **Plan should say instead:** Give `drive_llm_round` a non-zero `cached_prompt_tokens`, add `cache_read_input_tokens` to the corresponding exact `LlmRound` carried-key set, and verify that the production session path, not only direct builder calls, emits it.

   *Resolution:* accepted. The tests section gains the event-path inventory item: the driver's `Usage` carries a cached count, the `LlmRound` carried set gains the field, and the recap driver is checked for the same.

**Verdict:** ready after the P2 amendments.
