# The cached share of a prompt is reported: implementation

Companion to
[`2026-09-25-cached-prompt-tokens.md`](2026-09-25-cached-prompt-tokens.md),
one section per milestone, appended in the same change that ticks the
milestone checklist. It records deviations from the plan, resolutions
of the plan's open questions, and discoveries.

## M1: the cached share of a prompt is reported

**Attribution:** anthropic/claude-opus-5-5, thinking high; Claude Code 2.1.282; 2026-09-25.

### What landed

| Decision | Where | Commit |
| --- | --- | --- |
| 1, `Usage.cached_prompt_tokens` and its meaning | `providers/base.py` | `Read the cached prompt share in both LLM adapters` |
| 2, the OpenAI-compatible read with the subset guard | `providers/openai_llm.py` (`usage_from`), `providers/kit.py` (`token_count`) | same |
| 3, the Anthropic fold | `providers/anthropic_llm.py` (`usage_from`) | same |
| 4, `cache_read_input_tokens` on `LlmRound` and `LlmRecap` | `events/catalog.py`, `events/assembly.py`, `docs/reference/events.md` regenerated | `Carry the cached input count on llm_round` |
| 6, `_reported` answers three counts | `runtime/provider_watch.py` | same |
| 5, one `LLM_ATTRIBUTES` entry, no `usage_details` | `telemetry.py` | `Map the cached count onto the llm span` |
| The `GEN_AI` row | `conversations/docgen.py`, `docs/reference/conversations-schema.md` regenerated | `Add the cached count to the GenAI correspondence` |
| The documentation footprint | `vinga-server/README.md`, `docs/architecture/observability-surfaces.md` | `Document the cached count where usage is described` |
| The changelog fragment | `changelog.d/536-cached-prompt-tokens.md`, `### Added` and `### Fixed` | `Add the changelog fragment for the cached count` |

### Deviations from the plan

None in what was built. Three choices the plan left open, and one test
the plan did not name:

- **`llm_rounded` takes the count as a keyword-only argument with a
  `None` default** rather than a positional one after `input_tokens`.
  Every existing call passes the counts positionally, so a new
  positional slot in the middle would have shifted the meaning of each
  of them silently; a keyword cannot. The missing-plumbing risk a
  default opens is what the event-baseline driver's carried set
  closes, and it does.
- **The count guard is one function, `providers/kit.token_count`,**
  used by both adapters: a non-negative `int` that is not a `bool`, or
  `None`. The OpenAI-compatible adapter adds the subset check over it;
  the Anthropic one needs only the type check, as the plan says, and
  has its own test for it (a negative, a `bool` and a float cache
  count are neither folded nor reported).
- **The adapters' usage reads are module-level `usage_from` functions**
  in each adapter module, beside the stream that calls them, so the
  vendor shape stays in the vendor's module.
- **A cross-check test the plan did not name:**
  `test_every_convention_the_llm_span_speaks_has_its_row` holds
  `docgen.GEN_AI` to `telemetry.LLM_ATTRIBUTES`: every `gen_ai.*` or
  `server.address` attribute the `llm` span maps a field to must have a
  row naming that field. It is the plan review's second finding made
  falsifiable (the drift check could not catch the omission), and it
  failed on exactly the one missing pair before the row was added.

The live measurement ran as the plan specifies. Its gate is reported
below under the plan's own rule, with the one ambiguity in that rule
stated rather than resolved.

### Discoveries

- **`FakeChunkUsage` had no user.** No test built an OpenAI usage chunk
  before this milestone, so the OpenAI adapter's usage read was
  untested end to end. The new `test_providers_llm_usage.py` is the
  first test of it, the pre-existing two counts included.
- **The recap driver in the event baseline reaches no `Usage`.** Its
  scripted model yields none, and its `LlmRecap` carried set has no
  `input_tokens` either, so that set is unchanged. The recap path's
  cached count is covered by the provider-watch and assembly tests
  instead.
- **The existing settled-keys span test is an exact set.**
  `test_one_round_is_one_span_with_the_settled_gen_ai_keys` asserts the
  whole foreign-prefixed key set; it now carries the cached key, so the
  correspondence table is pinned whole again.
- **On the live run, a write voided the whole prompt cache, not only
  what follows the memory block.** See the measurement's findings.

### Inventories

By `git grep`, untruncated, at the tree this section is committed with.

- **`LLM_ATTRIBUTES`**: two readers in the source, the declaration
  (`telemetry.py:1045`) and its one use in the `llm` span writer
  (`telemetry.py:2968`), and one in the tests, the new docgen
  cross-check. The other hits are dated plan records.
- **`Usage(` construction sites**: 26 hits in `vinga-server`. Two in
  production, one per adapter's `usage_from`; the pipeline's
  `case Usage():` matches the object and passes it through whole. The
  other 23 are tests, of which only the event-baseline driver and the
  new tests set `cached_prompt_tokens`; the rest keep its `None`
  default, which is what a provider that never reported one yields.

### Falsification

Each new test was run against the unchanged code first and watched
failing: the adapter tests (11 of 16 failed, the absence cases passing
as they must until the field exists), the assembly tests (2), the
provider-watch tests (2 of 3; the no-usage case passes vacuously
before and after, and is there for the mutation below), the event
baseline's carried-set check, the two span tests (`KeyError` on the
new attribute), and the docgen cross-check. Mutations, each run once
against the tests it targets, straight-line logic so one run proves
it:

| Mutation | Result |
| --- | --- |
| Anthropic fold removed (`prompt_tokens=reported.input_tokens`) | killed: `test_anthropic_cache_counts_fold_into_the_input_it_read` |
| OpenAI absence collapsed to `0` | killed: 9 tests, the three absence cases and the six not-a-subset cases |
| `LLM_ATTRIBUTES` entry removed | killed: 3 span tests |
| Over-total guard removed (`cached > prompt` dropped) | killed: the `over-the-total` case |
| Anthropic type guard removed (raw cache read used) | killed: all three cases of the type-guard test |

None survived.

### The live measurement

Run on agentpi, 2026-09-25 from 08:23 to 08:32 CEST, from an
uncommitted driver in the session's scratchpad: a server in process on
this branch's tree (at `f05cabe8`) with OpenAI ASR (`gpt-transcribe`),
the OpenAI-compatible LLM on `api.openai.com` with **`gpt-4.1-mini`**,
OpenAI TTS (`gpt-4o-mini-tts`), silero VAD, the builtin memory tools,
and telemetry on with `export_llm_input` (so the `llm` span carries
`gen_ai.system_instructions`) exporting to the project's Langfuse. The
spoken questions were synthesized once with OpenAI TTS, resampled to
16 kHz and sent through the xiaozhi-sdk client, one per turn, ten turns
per session. `llm_round` and `tool_call` were read off the server's
own session event log (a handler on `vinga_server.session`), and the
`llm` spans off a copy taken in front of the real OTLP exporter.

The agent's prompt was a garden-guide persona of 1,194 tokens
(`o200k_base`), and with the ten builtin tool definitions a first round
was 2,456 input tokens, clear of OpenAI's 1,024-token floor from round
one.

**Isolation.** Each session ran on its own board MAC, against a fresh
database created for the run. Before every session
`vinga memory list agent` and `vinga memory list device` both answered "nothing is
remembered under that scope"; after every session the agent's and the
board's memory were listed, deleted with `--all`, and listed empty
again. The treatment sessions left exactly their two facts
(`1: Their favorite flower is the blue poppy.`,
`2: The user's daughter is called Ingrid.`; then 3 and 4 in the second
treatment), the controls left none. The first round's system
instructions hashed identically in all four sessions (5,088 characters,
`sha256` prefix `b927b086d9765893`): the assembled system prompt was
byte-identical at the start of every arm. Conversations were not
stored, so no arm could inherit another's history.

**Counterbalancing.** Sessions ran back to back in the order control
(S1), treatment (S2), treatment (S3), control (S4), about a minute and
a half each. Treatment turns 3 and 6 asked the guide to remember
something; control turns 3 and 6 asked a garden question instead. The
other eight questions were identical.

**Per round**, `cache_read_input_tokens / input_tokens`, with what the
round's system instructions held of the two facts:

**S1-control**

| Turn | Round | `input_tokens` | `cache_read_input_tokens` | Fraction | Memory block holds |
| --- | --- | --- | --- | --- | --- |
| 1 | 1 | 2456 | 0 | 0.00 | nothing |
| 2 | 1 | 2483 | 2304 | 0.93 | nothing |
| 3 | 1 | 2519 | 0 | 0.00 | nothing |
| 4 | 1 | 2554 | 2432 | 0.95 | nothing |
| 5 | 1 | 2590 | 2432 | 0.94 | nothing |
| 6 | 1 | 2622 | 2432 | 0.93 | nothing |
| 7 | 1 | 2652 | 2560 | 0.97 | nothing |
| 8 | 1 | 2677 | 2560 | 0.96 | nothing |
| 9 | 1 | 2716 | 2560 | 0.94 | nothing |
| 10 | 1 | 2762 | 2688 | 0.97 | nothing |

**S2-treatment**

| Turn | Round | `input_tokens` | `cache_read_input_tokens` | Fraction | Memory block holds |
| --- | --- | --- | --- | --- | --- |
| 1 | 1 | 2456 | 1792 | 0.73 | nothing |
| 2 | 1 | 2483 | 2304 | 0.93 | nothing |
| 3 | 1 | 2524 | 1792 | 0.71 | nothing |
| 3 | 2 | 2585 | 0 | 0.00 | blue poppy |
| 4 | 1 | 2571 | 2432 | 0.95 | blue poppy |
| 5 | 1 | 2608 | 2432 | 0.93 | blue poppy |
| 6 | 1 | 2642 | 2560 | 0.97 | blue poppy |
| 6 | 2 | 2689 | 0 | 0.00 | blue poppy, Ingrid |
| 7 | 1 | 2676 | 2560 | 0.96 | blue poppy, Ingrid |
| 8 | 1 | 2710 | 2560 | 0.94 | blue poppy, Ingrid |
| 9 | 1 | 2749 | 2560 | 0.93 | blue poppy, Ingrid |
| 10 | 1 | 2784 | 2688 | 0.97 | blue poppy, Ingrid |

**S3-treatment**

| Turn | Round | `input_tokens` | `cache_read_input_tokens` | Fraction | Memory block holds |
| --- | --- | --- | --- | --- | --- |
| 1 | 1 | 2456 | 2304 | 0.94 | nothing |
| 2 | 1 | 2483 | 2304 | 0.93 | nothing |
| 3 | 1 | 2523 | 2432 | 0.96 | nothing |
| 3 | 2 | 2587 | 0 | 0.00 | blue poppy |
| 4 | 1 | 2571 | 0 | 0.00 | blue poppy |
| 5 | 1 | 2605 | 2432 | 0.93 | blue poppy |
| 6 | 1 | 2639 | 2432 | 0.92 | blue poppy |
| 6 | 2 | 2686 | 0 | 0.00 | blue poppy, Ingrid |
| 7 | 1 | 2673 | 0 | 0.00 | blue poppy, Ingrid |
| 8 | 1 | 2707 | 2560 | 0.95 | blue poppy, Ingrid |
| 9 | 1 | 2746 | 2560 | 0.93 | blue poppy, Ingrid |
| 10 | 1 | 2791 | 2688 | 0.96 | blue poppy, Ingrid |

**S4-control**

| Turn | Round | `input_tokens` | `cache_read_input_tokens` | Fraction | Memory block holds |
| --- | --- | --- | --- | --- | --- |
| 1 | 1 | 2456 | 1792 | 0.73 | nothing |
| 2 | 1 | 2483 | 2304 | 0.93 | nothing |
| 3 | 1 | 2517 | 2432 | 0.97 | nothing |
| 4 | 1 | 2557 | 2432 | 0.95 | nothing |
| 5 | 1 | 2597 | 2432 | 0.94 | nothing |
| 6 | 1 | 2629 | 2560 | 0.97 | nothing |
| 7 | 1 | 2659 | 2560 | 0.96 | nothing |
| 8 | 1 | 2688 | 2560 | 0.95 | nothing |
| 9 | 1 | 2727 | 2560 | 0.94 | nothing |
| 10 | 1 | 2765 | 2688 | 0.97 | nothing |

Whole sessions: S1 19,968 of 26,031 input tokens cached (0.77), S2
23,680 of 31,477 (0.75), S3 19,712 of 31,467 (0.63), S4 24,320 of
26,078 (0.93).

**The endpoint reports the field.** OpenAI's did, on every one of the
44 rounds, as a number (including `0`); no round carried the key
absent. A self-hosted compatible endpoint could not be checked on this
machine, which has no local runner; the unit tests pin that such an
endpoint's silence renders as absence rather than zero.

**The interventions, verified.** All four counted, none needed a
re-ask. Each treatment turn 3 and 6 produced a `tool_call` event for
`remember` with `is_error` false, followed by a second round of the
same reply whose `gen_ai.system_instructions` contained the new fact,
under a `You remember these facts about past conversations:` block. The
write reaches the prompt within the reply: the round after the write is
round 2 of the same turn, not the next turn's first round. No control
turn called any tool.

**Where the memory block sits.** At the end of the system message, not
its head: the memory-free and the memory-bearing system instructions
share their first 5,071 characters, and the text ahead of the block is
1,194 tokens. The ten tool definitions were identical, in the same
order, with `tool_choice` `auto`, on the round before and the round
after a write (read back from both observations). So longest-prefix
caching predicts a write round that still hits on at least the
1,024-token floor (more if the provider renders the tool definitions
ahead of the system message).

**What was expected, and what happened.** Stated in the plan before the
run: one near-uncached round per write, then caching again against the
new prefix. Observed:

- The round after every write cached **nothing**: 0 of 2,585, 2,689,
  2,587 and 2,686. That is a larger loss than the longest-common-prefix
  reading predicts, since the 1,194 tokens of system text ahead of the
  block were unchanged.
- S2 recovered on the next request both times (0.95, 0.96), the
  signature the plan predicted. S3 did not: the next turn's first round
  also cached nothing, twice (turns 4 and 7), and recovered the round
  after that.
- Misses happen without any write. S1's first round was cold (the
  run's first request), which is expected; S1 turn 3 cached nothing with
  an unchanged prompt; and S2 and S4 opened at 1,792 of 2,456 rather
  than the 2,304 S3 opened with.

**The gate.** The plan's rule: at every verified intervention in both
treatment sessions, the round after the write reports cached tokens no
larger than the prompt ahead of the memory block, while the control
sessions' same-numbered rounds cache at least half their input.

- The treatment half holds at all four interventions: 0 cached, below
  the 1,194 tokens ahead of the block.
- The control half depends on what "same-numbered" means, since a
  control turn has no round 2. Read as the controls' rounds at the same
  turn numbers (turns 3 and 6), it holds at three of four and fails at
  one: S1 turn 3 cached 0 of 2,519. Read as the controls' next request
  after the same turn (turns 4 and 7), it holds at all four (0.95,
  0.97, 0.95, 0.96).

Under the plan's rule, "anything less ... is recorded as not
reproduced", the literal reading gives **not reproduced: M2's gate
does not open as written.** The alternative reading opens it. Which
reading the rule meant is the orchestrator's and Rafael's to say, not
this milestone's; both are recorded so the call is made on the numbers.
Two facts bear on it: the treatment effect was 4 of 4 total misses
against 1 total miss in 18 non-first control rounds, and a control can
lose its whole cache without any write, which is exactly why the rule
asks for all four comparisons rather than any one.

**What the gate does not measure.** How often a real session writes
memory, which is what turns one (or, as S3 shows, two) uncached rounds
per write into a cost. At `gpt-4.1-mini`'s rates as the backend priced
them below, one uncached round of about 2,600 tokens where about 2,450
would have been cached costs about $0.0007 more; the backend has the
counts to price any real session's writes now.

**The price on a real span.** Two `llm` observations from S2 turn 3,
read back from the backend through its API:

| Observation | Round | `usageDetails` | Cost (`costDetails`) |
| --- | --- | --- | --- |
| `e3da756cb8428096` (trace `76291e8a87ed184f6c79ee5b889fbcba`) | 1, before the write | `input 732, input_cached_tokens 1792, output 22, total 2546` | input $0.0002928, cached $0.0001792, output $0.0000352, total $0.0005072 |
| `2d39b15d3546a779` (same trace) | 2, after the write | `input 2585, input_cached_tokens 0, output 14, total 2599` | input $0.001034, cached $0, output $0.0000224, total $0.0010564 |

The span the server wrote carried `gen_ai.usage.input_tokens: 2524` and
`gen_ai.usage.cache_read.input_tokens: 1792` and no usage details; the
backend stored `input` net of the cached share (732 is 2,524 less 1,792)
and priced the cached tokens at a quarter of the input rate ($0.10
against $0.40 per million). That is the Step 0 gate's case A, confirmed
on a span this server wrote. Without the cached count the same round
would have cost $0.0010448, so the reported cost of that round halves.
None of the 44 exported `llm` spans carried a `usage_details` key.

### Verification

All from `vinga-server/`.

- `uv run ruff check .`: all checks passed.
- `uv run mypy` (the events package's type check): no issues in 5
  source files.
- Unit lane, `uv run pytest tests/unit -q -ra -n auto --dist loadfile`:
  **7640 passed, 19 skipped in 875.60s**, on the tree of
  `Add the changelog fragment for the cached count`.
- Integration lane, `uv run pytest tests/integration -q -ra -n auto --dist loadfile`:
  **347 passed in 217.56s**, on the same tree.
- The generated-document drift checks, as CI spells them: the domain
  and server configuration references, the conversations schema, the
  metrics views, the events reference and the OpenAPI document each
  regenerated and compared, all six current. The two this milestone
  moved were regenerated through their generators and committed. The
  CLI reference check was not run; nothing it renders changed.
- Census lane, `uv run pytest tests/census -q`: 66 passed, before and
  after this document; neither manifest moved.

  *Correction, 2026-09-25.* The "after" run was on a draft, before the
  measurement's memory-listing spellings were written into this
  section, and the commit that added them staled the spellings
  manifest. CI caught it; see the PR review round below.
- `python3 scripts/check_doc_links.py .` from the checkout root: 275
  files, 0 failures. `python3 scripts/fold_changelog.py check .`: one
  fragment, no failures.
- Not verified here: the image build and its smoke lane, which run in
  CI only; and a self-hosted compatible endpoint's report, for the
  reason above.

### PR review round, PR #570

Automated external review of this PR's diff (origin/main...47760de2). Reviewed 2026-09-25 by openai/gpt-5.6-sol, thinking high via codex CLI 0.156.1, read-only sandbox, runtime 5m45s, at commit 47760de2. Posted verbatim by the review run itself; resolutions follow as replies.

Verdict as received: **mergeable after the listed fix**. There was one
finding, fixed here in a commit of its own, and one CI failure on the
same commit, fixed in another.

1. **P2: the recap schema omitted the absent-versus-zero contract.**
   `LlmRecap.cache_read_input_tokens` carried only "the part of
   `input_tokens` served from the provider's prompt cache", so the
   generated recap row in `docs/reference/events.md` did not say that
   an absent count means the endpoint did not report one rather than
   zero, nor name the conventions' attribute. The plan (decision 4)
   asks for that note on both variants.

   *Resolution*: accepted, in `54d1fd98`. The note is one constant,
   `CACHE_READ_INPUT_TOKENS_NOTE`, declared once in `events/catalog.py`
   and named by both fields, so the two rows cannot drift apart again;
   `docs/reference/events.md` is regenerated through
   `vinga-server events reference`, and only the recap row moves. A new
   test, `test_both_generations_say_the_same_about_their_cached_count`
   in `test_event_docs.py`, reads the generated reference and holds the
   two rows' notes equal, with the absence sentence and the
   conventions' name in them. Run once with the old recap note restored,
   it failed; with the shared note it passes.

**CI fix: the command-spellings census.** The `docs` workflow failed on
`47760de2` at `test_the_manifest_is_the_census`. This section's
measurement quotes the memory-listing commands, and it was written
after the census had last been run, so the hand-back's "neither
manifest moved" described an earlier tree (corrected in place above).
Of the two new spellings, one was wrong: the code span
`vinga memory list agent` had been wrapped across a line break, and
the census read its first line as the listing command with no scope at
all, which the CLI refuses: its help says `SCOPE` is required. The
spelling is not quoted here, since quoting it would record it again.
The span is
now on one line. The other, `vinga memory list device`, is a spelling
the CLI accepts (a scope with no owner lists who is remembering
anything in it). Resolved in `24705e09`: the doc's span unwrapped and
`tests/census/command-spellings.txt` regenerated with
`uv run python -m tests.census.test_command_spellings`, which adds
exactly that one line, classified `historical` since it sits in a dated
plan record.

Verification after the round, from `vinga-server/`:

- `uv run ruff check .`: `All checks passed!`
- `uv run mypy`: no issues in 5 source files.
- `uv run pytest tests/unit/test_event_docs.py tests/unit/test_event_assembly.py tests/unit/test_event_baseline.py tests/unit/test_provider_watch.py -q -ra -n 4`:
  `64 passed in 64.82s`.
- The events-reference drift check (`vinga-server events reference`
  against the committed file): current.
- `uv run pytest tests/census -q -ra`: `66 passed`, rerun on the tree
  this section is committed with.
- `python3 scripts/check_doc_links.py .` from the checkout root:
  `checked 276 files, 0 failures`.
- The full unit and integration lanes were not rerun: the change is
  one note's text, one generated row, one test and one manifest line.
