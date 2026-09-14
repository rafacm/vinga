# Telemetry backend parity implementation

Companion to
[`2026-09-14-telemetry-backend-parity.md`](2026-09-14-telemetry-backend-parity.md).
One section per milestone records what was built, deviations from the plan,
resolved questions and discoveries needed by later milestones.

Local baseline: not applicable. This work changes an optional export surface,
not a conversational capability.

## M1: canonical metadata and real failed operations

M1 establishes the metadata and failure contract that content attachment and
backend fanout will build on. It changes no deployment recipe and preserves
the existing transcript, LLM-input and recording paths for their later
milestones.

### What landed

**Generation identity and recap symmetry.** Every reply round now mints one
opaque invocation id before request assembly. The content staging seam and
the eventual success or failure event receive that same id, and the
first-token retry deliberately reuses it. Recap assembly follows the same
path with `purpose=recap`: success produces an ordinary `llm_round` event and
failure produces `provider_failed`, both of which fold into a real `llm`
span. A recap carries no reply-local `round` and does not call
`TurnUnderway.round_done`, so it changes none of the persisted reply counts,
latencies or token totals.

The recap's outer deadline has its own failure emission. A provider-raised
`TimeoutError` is already recorded by the watched stream, while
`asyncio.Timeout.expired()` distinguishes cancellation caused by the outer
deadline and records that once. This keeps the two failure sites
substitutive.

**Safe semantic failures.** Failed ASR, LLM, TTS and tool operations now end
as their own semantic spans with OpenTelemetry `ERROR` status and no status
description. `error.type` carries an exception class name selected at the
catch site. A returned tool error uses the closed `tool_error` token. The
fold consumes the catalog event instead of also attaching a span event to the
turn. The existing `vinga.asr.error` key remains as a compatibility copy.
A failed TTS drain continues to report `sentence_synthesized` on the declared
log surface, preserving its first-chunk and whole-stream measurements. Its
`provider_failed` event arrives immediately first, so the telemetry fold marks
that stream end as consumed and does not create a normal synthesis span beside
the failed one.

The tests use credential-shaped sentinels in nested exception messages and
causes, then inspect event messages, arguments, fields, log records, text and
JSON log rendering, span attributes and exception chains. Only the safe class
name reaches telemetry.

**Exact retained context.** Pinned session and turn contexts retain their
original trace flags, trace state and remoteness. Post-close work reconstructs
that exact parent, so a source sampler's decision and vendor trace-state
entries survive. An unsampled root remains non-recording when a later writer
tries to address it. The transcript and assembled-request exporters detect
that choice before building a batch and report their existing `no_trace`
reason; they do not ask the transport or misreport the omission as
`undelivered`.

**Compatibility and reference contract.** The canonical attributes gained
`vinga.llm.invocation.id`, `vinga.llm.purpose` and `error.type`. Existing
Langfuse usage aliases remain derived from the canonical ASR and TTS usage
attributes. The generated event reference declares the invocation syntax,
reply and recap `llm_round` variants, provider-failure correlation fields and
safe tool failure field. The server exporter contract and observability map
state the same topology, failure and compatibility rules.

### Deviations and decisions

There are no deviations from the reviewed M1 plan.

The event surface remains unchanged for a TTS stream that produced chunks and
then failed. `sentence_synthesized` still records the first-chunk and stream
timings in text and JSON logs. Substitution belongs to the telemetry fold:
`provider_failed` creates the failed `tts_stream` span and the immediately
following stream-end event creates no second span. This best preserves both
the declared event surface and the reviewed one-carrier trace contract.

The catalog makes `invocation` and `purpose` optional on the shared
`provider_failed` declaration because ASR and TTS failures use that same event
and have no generation identity. Runtime LLM failure paths always supply both.
The two `llm_round` variants make the success rule stricter: reply requires a
round, while recap cannot carry one.

A rejected barge-in confirmation can be a second real ASR attempt while the
interrupted turn is open. It now receives a second failed `asr` span instead
of a turn event. A second successful ASR result remains folded as before,
since one turn still has one accepted transcription.

All four semantic stage folds use the same missing-turn rule. The session span
is their parent when no turn is open, rather than changing a real operation
into a span event. This is what lets a recap remain an `llm` operation between
turns and matches the existing tool fallback.

### Verification

Run from `vinga-server/` unless noted otherwise:

- `uv run mypy`: clean.
- `uv run ruff check .`: clean.
- Focused unit and integration tests after the external review fixes: 252
  passed.
- Five focused falsification tests for context preservation, four provider
  failure kinds, successful recap accounting, recap outer timeout and nested
  tool exception leakage: passed.
- Affected runtime, recap, telemetry and event-baseline modules before the
  external review round: 137 passed.
- `uv run pytest tests/unit -q -n 4 --dist loadfile`: 7,526 passed, 2 skipped.
- `uv run pytest tests/integration -q`: 345 passed.
- The integration receiver decoded the emitted OTLP protobuf and confirmed
  failed `llm` and `tool` spans were present while their `provider_failed` and
  `tool_call` turn span events were absent.
- The domain, server, conversation schema, metrics views, events, OpenAPI,
  full CLI reference and CLI recipes regenerated byte-identically.
- `uv run pytest tests/unit/test_command_spellings.py -q`: 52 passed.
- `python3 scripts/check_doc_links.py .` from the repository root: 247 files,
  0 failures.

The local verifier used the existing synced `uv` environment with the M1
worktree source explicitly first on `PYTHONPATH`, plus an isolated PostgreSQL
test service on port 55523. This avoids changing dependency or deployment
files for a telemetry-only milestone.

The first CI-shaped unit attempt used `-n auto` and reached 7,275 passes before
the local PostgreSQL service terminated connections across workers, followed
by cascading fixture teardown errors. The container did not restart or run out
of memory and was healthy immediately afterward. The complete four-worker
distributed runs stayed inside that local service's concurrency envelope and
finished green.

## PR review round, M1 (PR #524)

External review of the PR diff `origin/main...fb4b199d`: claude CLI 2.1.270,
read-only tool set, model `claude-opus-5`, 2026-09-14, runtime 11m53s,
[posted on the PR](https://github.com/rafacm/vinga/pull/524#issuecomment-5668711562).
Verdict: mergeable after the listed fixes. The reviewer found six P2 and five
P3 issues. It confirmed the core invocation, retry, recap-accounting,
outer-timeout and no-leak mechanics while requiring the following corrections.

1. **P2: two telemetry comments described the deleted failure-fold rule.**
   They still said non-ASR provider failures became turn events and that every
   stage without an open turn fell through to an event.

   *Resolution* (`9342992b`): both comments now state the substitutive
   three-stage failure rule, the common missing-turn parent, and the explicit
   unknown-stage fallback.

2. **P2: an unknown `provider_failed.stage` was silently discarded.** The
   event field admits any identifier, while the exporter returned for every
   value outside `asr`, `llm` and `tts`.

   *Resolution* (`9342992b`): an unknown stage now uses the default span-event
   fold, with a regression test for a future `embedding` stage.

3. **P2: sampled-away content was misreported as `undelivered`.** Preserving
   retained trace flags lets the private tracer produce non-recording spans,
   which the OTLP encoder could not accept and the containment mislabeled as a
   transport failure.

   *Resolution* (`9342992b`): both content exporters drop non-recording spans
   before OTLP encoding and answer `Delivery.NO_TRACE`; their workers emit the
   existing `no_trace` reasons. Tests cover unsampled session and independently
   sampled turn roots. The operator contract is recorded in `a28c6bbb`.

4. **P2: failed TTS spans could erase retained provider context.** Four absent
   identity fields from an unbuilt voice suppressed the session's configured
   TTS identity without replacing it.

   *Resolution* (`9342992b`): failed LLM and TTS folds use `_speaks_for`, just
   like the established ASR and successful TTS folds, so absent failure
   identity preserves the retained provider quartet.

5. **P2: the promised decoded-wire substitution assertion was missing.** Unit
   tests covered the in-memory spans, but no integration test decoded OTLP and
   proved the old turn events absent.

   *Resolution* (`9342992b`): the real OTLP/HTTP protobuf receiver now asserts
   failed `llm` and `tool` spans, their error status and safe `error.type`, and
   the absence of `provider_failed` and `tool_call` events on the decoded turn.

6. **P2: suppressing `sentence_synthesized` changed the declared log event
   surface.** A stream that produced chunks and then failed lost its
   first-chunk and whole-stream timings even when telemetry was disabled.

   *Resolution* (`9342992b`): the runtime emits the stream-end event again.
   Telemetry consumes it after the immediately preceding failed TTS operation,
   preserving one trace carrier without removing the event from text or JSON
   logs. `a28c6bbb` records why substitution belongs at the telemetry fold.

7. **P3: successful and failed operations used different missing-turn
   fallbacks.** Failed spans and tools could parent to the session, while
   successful LLM and TTS work degraded to span events despite the documented
   semantic-operation topology.

   *Resolution* (`9342992b`): ASR, LLM, TTS and tool operations all remain real
   spans and parent to the session when no turn is open. `a28c6bbb` states that
   rule in the server contract and implementation record.

8. **P3: LLM purpose and invocation attribute names were repeated as string
   literals.** The purpose constant already existed, but the two attribute
   tables bypassed it and no invocation constant existed.

   *Resolution* (`9342992b`): both tables use `LLM_PURPOSE` and the new
   `LLM_INVOCATION_ID`, beside a comment that generation and input spans share
   the same correlation vocabulary.

9. **P3: the reply-accounting switch used an unvalidated purpose string.** A
   typo could skip `round_done` and fail event construction without static type
   checking, despite the existing `LlmPurpose` enum.

   *Resolution* (`9342992b`): runtime generation paths and LLM-input staging
   carry `LlmPurpose`; the accounting branch compares directly with
   `LlmPurpose.REPLY`.

10. **P3: the plan placed both review verdicts after the re-review.** The first
    review section had no verdict, and the re-review appeared to conclude
    twice.

    *Resolution* (`a28c6bbb`): the 17-finding verdict now closes the first plan
    review, while the 15-finding verdict alone closes the re-review.

11. **P3: the changelog omitted the removed turn span events.** It named the
    replacement failed spans without warning operators that saved event
    filters for `provider_failed` and failed `tool_call` would stop matching.

    *Resolution* (`a28c6bbb`): the fragment has a `Removed` entry naming both
    former turn events and directing readers to failed `asr`, `llm`,
    `tts_stream` and `tool` spans.
## M2: content on the operations it describes

M2 moves opt-in content from private post-close observation spans onto the
canonical operations it describes. It changes no deployment recipe and leaves
both content flags off by default.

### What landed

**Synchronous generation pairing.** `llm_input_export.py` now renders one
allowlisted input snapshot per server-minted invocation, observes raw semantic
output before speech filtering, and completes the pair immediately before the
matching `llm_round` or LLM `provider_failed` emission. Telemetry consumes that
pair while creating the actual `llm` span. Reply and recap generations use the
same path, watchdog retries keep one logical pair, and generated text withheld
from speech remains in the authorized raw output. Tool schemas, choice, calls,
arguments and results use structured GenAI message shapes. A complete operation
is limited to 256 KiB and is dropped whole rather than truncated.

**Acknowledged turn-root settlement.** Each live `TurnRecord` and its store
acknowledgement now reach `transcript_export.py`, including every row produced
by a handover. The final reply boundary closes the utterance group. The worker
waits for all acknowledgements, composes the heard text, complete reply and
ordered per-agent legs, then asks Telemetry to enrich and end the original
`turn` root at the reply-finished timestamp. A false or missing acknowledgement,
timeout, conflicting rows, admission refusal or shutdown releases the same root
metadata-only. Earlier turns therefore leave while a long session remains open.

Telemetry owns the terminal transition under `_held_turns_lock`: settlement,
overflow and shutdown contenders pop under the lock, and only the winner
mutates and ends the span outside it. The process-wide ledger holds at most
4,096 logically finished roots. The next root releases the oldest metadata-only
and reports the omission.

**One ordinary OTLP path.** The private processorless content exporter and its
`Delivery` answer are gone. The ordinary `BatchSpanProcessor` retains its
2,048-span queue, five-second schedule, finite timeout and bounded shutdown,
with a content-safe batch size of eight. A serializer test fills eight maximal
content spans and keeps the real protobuf request below 3 MiB; content wire
receivers reject a request at or above that limit. Existing outcome names remain,
but now mean content was attached and enqueued, or omitted before enqueue. They
do not claim that a backend acknowledged delivery.

**Canonical content and compatibility.** Turn roots carry
`vinga.turn.input`, `vinga.turn.output` and canonical JSON
`vinga.turn.legs`. Generation spans carry `gen_ai.system_instructions`,
`gen_ai.input.messages`, `gen_ai.output.messages`, `vinga.llm.tools` and
`vinga.llm.tool_choice`. The direct Langfuse input, output and legs attributes
are derived aliases from those canonical values. The separate `transcript` and
`llm_input` spans, transcript row index, database id and relative timestamp,
session-parent fallback, private exact-delivery answer and `undelivered` reason
were removed.

### Deviations and decisions

PR review made one deliberate event-schema deviation from the reviewed M2
plan. `llm_input_exported` retains only `session` and the measured `rounds`
count. Its four legacy `elapsed_ms`, `oversized`, `over_budget` and
`unrenderable` fields were always emitted as zero, so the implementation could
not support the measurements their generated notes promised. Individual
omissions continue to use `llm_input_export_failed` with their exact closed
reason. The generated event reference and changelog fragment record the
smaller truthful schema.

The existing content modules remain because their responsibilities are deep:
LLM input and raw-output rendering plus operation bounds belong together, while
transcript acknowledgement truth, handover composition and worker admission
belong together. Telemetry alone owns span lifecycle and SDK mechanics.

The transcript content outcome variants retain their existing field schema for
consumer compatibility. Successful content events are emitted per settled
operation, and omissions use the remaining closed reason set. Their source
notes and generated reference define attachment and enqueue semantics exactly.
All four content outcomes remain metadata-only spans beside the retained
session after it closes, as well as structured log events, so a trace with
intentionally absent content still explains the omission.

The content-and-telemetry ADR replaces its former separate-span invariant. The
event fold still never reads content, but a built and explicitly flagged content
collaborator may enrich a fold-made span through a server-minted correlation key
and an allowlisted projection.

The acceptance review found three terminal edges where the first implementation
did not yet make that ownership complete. A final reply boundary that produced
no new row now closes and settles any earlier handover rows for the utterance,
instead of releasing their root and leaving the group until session close.
Telemetry records a bounded, key-only tombstone when ledger overflow ends a
root and returns an explicit `OMITTED` settlement result, so a queued worker does
not report the same operation again as `no_trace`. The tombstone uses the same
lock and bound as held-root ownership. The overflow callback transfers the
cancellation to the transcript collaborator, so a delayed job consumes it even
after the telemetry tombstone is acknowledged. Emitted events still carry no
utterance or other content identifier.

Generation staging remains keyed only by the server-minted invocation. Its
interface now also receives the session as a live-trace admission guard:
missing or closed sessions refuse the snapshot and produce the existing
`dropped` omission outcome. In the runtime, `finish()` and the matching event
emit are consecutive synchronous calls, and event taps fold inline, so session
close cannot interleave after admission. Both LLM event folds still
defensively consume a staged snapshot if an out-of-order interface caller has
lost its session trace, so that misuse cannot retain content until process
shutdown.

### Verification

Run from `vinga-server/` unless noted otherwise:

- `uv run ruff check .`: clean through the synced local environment.
- `uv run mypy`: clean, 5 source files checked.
- Focused generation, turn-root, recap and exporter tests: 45 passed.
- Transcript exporter unit tests: 33 passed.
- Transcript decoded-wire integration tests: 4 passed.
- App composition and event-driver tests: 33 passed.
- Acceptance follow-up telemetry and exporter tests: 140 passed.
- Acceptance follow-up runtime recording, handover, recap and generation tests:
  112 passed.
- Acceptance follow-up decoded-wire and content integration tests: 12 passed.
- Generated server reference, event reference and configuration-example drift
  tests: 212 passed.
- `uv run pytest tests/unit -q -n 4 --dist loadfile`: 7,426 passed, 2 skipped.
- `uv run pytest tests/integration -q`: 343 passed with the synced server
  environment first on `PATH`.

The first integration invocation inherited a globally installed client-only
`vinga-server` executable in smoke subprocesses. The application and telemetry
tests in the same lane were green. The final complete invocation kept the
synced server environment first while retaining the local `uv` and `psql`
directories, exercised all 343 integration cases, and passed without a source
change.

## PR review round, M2 (PR #525)

Automated external review of the PR diff `origin/main...773efd8c`: claude CLI
2.1.270, read-only tool set, model `claude-opus-5`, 2026-09-14, runtime 12m25s,
[posted on the PR](https://github.com/rafacm/vinga/pull/525#issuecomment-5670383145).
Verdict: mergeable after the listed fixes. The reviewer found seven P2 and
eight P3 issues. It required the following corrections.

1. **P2: the four content outcomes had disappeared from traces without a
   recorded surface change.** Removing them from the after-close fold also
   left five unreachable attribute mappings and made the observability map's
   trace-diagnosis promise false.

   *Resolution* (`49043480`): all four outcomes remain metadata-only
   after-close spans beside the session, the event fold documents that rule,
   and the observability surface records both trace and structured-log
   visibility.

2. **P2: `llm_input_exported` claimed four measurements its emitter always
   reported as zero.** The generated event reference therefore described
   durations and omission counters the implementation never measured.

   *Resolution* (`00709f82`, `d7bc2a57`): the success event now carries only
   `session` and measured `rounds`; the dead attribute mappings, source notes,
   generated reference and changelog contract were updated. Per-operation
   omission detail remains on `llm_input_export_failed`.

3. **P2: cancellation between `reply_finished` and the final transcript
   notification could strand a held turn beyond session close.** A zero-row
   root was invisible to transcript grouping and otherwise lived until
   overflow or process shutdown.

   *Resolution* (`83503eec`): the reply boundary now reports `turn_missing`
   from the cancellation path before re-raising. The earlier acceptance fix in
   `ca093e50` already settled a final no-row boundary when a prior handover row
   existed; the review found the distinct skipped-boundary path and added its
   runtime regression test.

4. **P2: each generated text delta re-rendered all accumulated output.** That
   made streaming accounting quadratic on the reply path.

   *Resolution* (`58597dc1`): staged rounds count each text or tool delta once,
   then perform one authoritative render and full projection-size check at
   `finish()`.

5. **P2: the `ASR_STAGE` comment had reverted to the deleted M1 failure-fold
   rule.** It contradicted the real LLM and TTS failure spans immediately
   below it.

   *Resolution* (`04befd4c`): the comment again states the three substitutive
   provider stages and reserves the ordinary span-event fold for an unknown
   future stage. The prior `a752ea0b` correction covered a separate stage-span
   parentage comment, not this reverted constant comment.

6. **P2: the receiving agent's handover attribution was absent from the
   canonical turn legs.** A row with no nested legs contributed reply text but
   no agent, despite the changelog's preservation claim.

   *Resolution* (`066e0fe0`, `9733d572`): a contributing row without nested
   legs now supplies one leg from its own agent and reply. Unit and decoded-wire
   tests cover both handover sides and an ordinary single-agent turn.

7. **P2: malformed tool arguments were silently replaced by an empty value in
   exported model content.** That erased the exact provider output needed to
   diagnose a schema mismatch.

   *Resolution* (`5890587f`): input and output tool-call projections retain the
   provider's malformed argument string when parsed arguments are unavailable.

8. **P3: the held-root concurrency test raced two callers of the same seam,
   not worker settlement against overflow or shutdown ownership.** It could
   not falsify a missing cross-site lifecycle guard.

   *Resolution* (`f0cc96b3`, `4993ec2b`): shutdown waits for roots whose worker
   or overflow contender already claimed ownership under the lifecycle lock
   before the provider stops. A repeated real shutdown-versus-settlement race
   proves one terminal end, with each iteration's contenders bound explicitly.
   The earlier `ca093e50` overflow test continues to prove a queued job cannot
   emit a second failure outcome after eviction.

9. **P3: `Telemetry.release()` stopped the provider without releasing held
   roots or staged LLM content.** Only the ordinary `shutdown()` door performed
   that cleanup.

   *Resolution* (`3027be6a`): shared completion now releases held roots and
   clears staged generation content for both doors, including thread-start
   failure, with a release-path regression test.

10. **P3: duplicate invocation staging could desynchronize the LLM maps and
    make budget eviction loop forever.** The ordered list could retain an id
    after its single map entry was removed.

    *Resolution* (`f92e2068`): synchronous staging refuses a duplicate server
    invocation, preserves the first snapshot and reports the second operation
    as dropped.

11. **P3: two transcript failure member comments described the retired store
    read seam and retention model.** They no longer matched the decisions that
    emit `unreadable` and `no_trace`.

    *Resolution* (`ac3eb9d9`): the comments now name conflicting handover
    acknowledgement and a missing held root respectively.

12. **P3: transcript and LLM exporter builders accepted retired bounds and
    dependencies, then discarded them.** Tests could appear to exercise a
    configured seam that no longer existed.

    *Resolution* (`7690b9a8`, `83bcb1e6`): the dead LLM backlog and shutdown
    arguments and transcript database, read and batch arguments were removed
    from builders, constructors and all callers.

13. **P3: two telemetry tests passed canonical attribute names where the
    projection seam expects `input` and `output`.** They attached no content
    while asserting only unrelated device metadata.

    *Resolution* (`15dcdecd`): the tests now exercise the caller-facing keys
    and assert the resulting `vinga.turn.input` and `vinga.turn.output`
    attributes.

14. **P3: an empty transcript projection still emitted
    `transcripts_exported` with `turns=1`.** The event falsely claimed that a
    root received complete acknowledged content.

    *Resolution* (`f26c5501`): an empty projection releases its root
    metadata-only, consumes any overflow cancellation token and emits no
    success or failure outcome.

15. **P3: transcript legs were walked generically and their size was measured
    before the downstream allowlist.** A future dataclass field could affect
    the 256 KiB decision without ever reaching the span.

    *Resolution* (`066e0fe0`): transcript composition now projects the four
    published leg fields explicitly and weighs exactly the JSON sent to
    telemetry.

### Review-fix verification

Run from `vinga-server/` unless noted otherwise:

- Combined LLM, transcript, telemetry, turn-lifecycle and decoded-wire
  falsification suite: 241 passed.
- `uv run ruff check .`: clean.
- `uv run mypy`: clean, 5 source files checked.
- Full four-worker unit lane: 7,425 passed, 19 skipped.
- `uv run pytest tests/integration -q`: 344 passed with the synced M2 server
  environment and the PostgreSQL client first on `PATH`.
- Generated domain, server, conversation schema, metrics view, event and
  OpenAPI reference drift tests: 152 passed.
- Command-spellings census: 52 passed.
- Documentation links and anchors: 247 files checked, 0 failures.
- Changelog fragment validation: 1 fragment checked, 0 failures.

The first CI-shaped unit attempt used `-n auto` against the shared default
PostgreSQL service. It reached 86 percent before that service terminated
connections across workers, followed by cascading storage-fixture failures.
The isolated four-worker rerun on port 55523 completed cleanly. The first full
integration attempt put the plan worktree's client-only executable first on
`PATH` and omitted the local `psql` directory, so packaging and provisioning
tests refused their environment. After `uv sync --frozen`, the complete rerun
used this M2 worktree's own server environment and the local libpq directory,
and all 344 cases passed without a source change.

### CI timing follow-up

Unit CI run 34898537774, job 104158571120 exposed a test-only scheduler
assumption in the one-slot transcript backlog case. The test slept for 100 ms
and assumed the worker had dequeued the first job. Under CI load it had not, so
the second job was refused instead of occupying the now-free pending slot. The
same assumption in the decoded-wire handover test let its two-second
acknowledgement deadline expire before the test settled the final row.

Both tests now use an `Acknowledgement` test double whose public `wait()` method
sets a `wait_entered` event. The backlog test fills the pending slot only after
the worker has entered the first job's acknowledgement wait. The wire test
settles the final handover row only after the worker has entered that row's
wait. Production queueing and acknowledgement bounds are unchanged, and no
test-only hook enters production code.

The finalized backlog case passed 20 consecutive runs, its complete unit file
passed 36 tests, and the four-worker transcript and lifecycle slice passed 56.
The finalized decoded-wire case passed 10 consecutive runs, and its complete
integration file passed 4 tests.

Post-merge main workflow 34907373708, unit job 104187064933 found the remaining
instance of the same assumption in
`test_handover_rows_wait_independently_and_compose_once`; the other 7,430 tests
passed. That test slept for 100 ms before settling its final handover row. Under
load the worker's unchanged 250 ms acknowledgement bound expired first, so it
correctly reported `unrecorded` and the test later found no attached input.

*Resolution* (`87dd1592`): the final row now uses the existing observed
acknowledgement and the test waits for its public `wait_entered` signal before
asserting that nothing settled early and supplying the answer. No production
code, sleep or acknowledgement bound changed. The exact test passed 25
consecutive runs, the transcript unit file passed 36 tests, the four-worker
transcript and lifecycle slice passed 56, and the complete four-worker unit
lane passed 7,431 tests with 19 skips.

## M3: direct Jaeger and one processed fanout

M3 makes Jaeger a supported direct OTLP/HTTP destination and adds one optional
Collector path that applies policy before it splits canonical traces between
Jaeger and Langfuse. No server module or production deployment topology
changed.

### What landed

**Pinned runnable paths.** `deploy/telemetry/docker-compose.jaeger.yml` adds
Jaeger v2 to the root trial stack and points vinga directly at its OTLP/HTTP
protobuf receiver. `docker-compose.fanout.yml` adds the same Jaeger plus
Collector Contrib and points vinga at the Collector with `always_on` source
sampling. Both images use immutable multi-platform digests. The adjacent
README records that the pins were verified on 2026-09-14 against the upstream
release APIs and OCI indexes: Jaeger 2.20.0 and Collector Contrib 0.160.0.

**One policy decision before split.** The committed Collector graph has one
common trace pipeline in the fixed order content mask, trace-id probabilistic
sampler, batch. Two named forward connectors hand those same processed records
to backend sink pipelines. The Jaeger sink drops the entire Langfuse-only
`capture` span and every `langfuse.*` attribute. The Langfuse sink preserves
the already-masked compatibility aliases and adds Basic Auth plus the literal
ingestion-version 4 header at its OTLP/HTTP exporter.

The mask names every canonical turn and generation content field and every
derived content alias explicitly. Its email-shaped sample rule applies to all
of them. A defense-in-depth credential rule covers all span attributes and the
status message before fanout. The behavioral test injects raw email and
credential sentinels into content and a deliberately invalid status message,
then scans both complete protobuf streams and the Collector log for the raw
values.

**Credential isolation and sampling truth.** The ignored
`deploy/telemetry/.env` is attached only to the Collector and has a committed
dummy `.env.example`. The root `.env` remains vinga's file and receives no
Langfuse name. The default Collector sample percentage is 100 for complete
walkthroughs and may be overridden for capacity tests. Documentation states
that sampling is per trace id, so it samples independent turns rather than
whole sessions and can leave one side of a session link absent. It also states
that common preprocessing gives both exporters identical attempted records,
not transactional delivery to two independent backends.

**Maintained acceptance.** The pull-request integration lane now runs a
source-tree server through a simulated conversation against the pinned Jaeger
container and queries Jaeger's API for the session, turn and semantic children.
A second Docker-backed test sends 64 deterministic trace IDs through the exact
committed Collector config to two recording OTLP receivers at a 25 percent
ratio. It asserts a nonempty proper subset, identical trace-ID populations and
canonical projections, common masked values, branch-only headers and aliases,
and complete capture removal from Jaeger. The non-PR image job repeats the
direct Jaeger path against both built image variants.

The server README carries the exact direct Langfuse v4 header recipe:
`Authorization=Basic%20<base64-public-key-colon-secret-key>,x-langfuse-ingestion-version=4`.
The deployment guide carries the direct Jaeger and processed fanout commands,
the 100 percent live default, partial-sampling consequence, privacy boundary,
trace-ID comparison and independent-outage limit. The observability map makes
the Langfuse-only media exception explicit: the `capture` reference span is
removed from Jaeger, while WAV and manifest bytes stay on the separate
Langfuse REST and object-storage path.

### Deviations and decisions

Two reviewed live acceptance gates remain deviations because no Langfuse
project credentials are available in this environment:

- [ ] Direct Langfuse v4: send the M2 turn-root and generation-content model
  with the maintained Basic Auth and ingestion-version header recipe, then
  record its accepted generation and turn rendering.
- [ ] Collector fanout to Langfuse v4: send the same model through the
  committed common policy pipeline, then compare its real Langfuse rendering
  and trace-ID population with Jaeger.

Until those gates run, the direct Langfuse recipe is maintained but its
rendering under the M2 content model is not claimed as live-verified.

Jaeger's published latest release on the implementation date was 2.20.0 even
though its upstream release schedule named later tentative versions. The pin
follows the release API and published OCI index, not the schedule. Collector
Contrib 0.160.0 was likewise the latest published release on that date.

The common mask also replaces Langfuse-shaped credential tokens in all span
attributes and status messages. Vinga's own allowlists and safe error types
remain the primary privacy boundary; this is a defensive Collector rule and
does not authorize content capture when either content flag is off.

### Verification

Run from `vinga-server/` unless noted otherwise:

- The pinned Collector binary accepted the exact committed configuration.
- Both telemetry compose overlays resolved with separate dummy root and
  Collector env files; the fully resolved graph put all three Langfuse names
  on the Collector and none on vinga.
- `uv run ruff check .`: clean.
- `uv run mypy`: clean, 5 source files checked.
- `uv run pytest tests/unit/test_telemetry_deploy.py -q`: 6 passed. The
  strengthened structural and fanout selection later ran together as 7
  passing cases.
- `uv run pytest tests/integration/test_telemetry_fanout.py -q`: 1 passed. It
  exercised the exact pinned Collector and two real recording receivers.
- The source-tree direct Jaeger acceptance: 1 passed against the pinned image
  and live Jaeger query API.
- The existing decoded-wire topology case plus the fanout acceptance: 2
  passed, proving the shared source-server fixture still exports normally.
- `uv run pytest tests/unit -q -n 4 --dist loadfile`: 7,431 passed, 19
  skipped.
- `uv run pytest tests/integration -q`: 346 passed, including both new Docker
  acceptances.
- Configuration examples, generated references and command-spelling census:
  136 passed.
- Generated-document drift checks ran inside the full unit and integration
  lanes and stayed byte-identical.
- `python3 scripts/check_doc_links.py .` from the repository root: 247 files,
  0 failures.
- `python3 scripts/fold_changelog.py check .`: 1 fragment, 0 failures.
- Credential checks scanned both received protobuf streams, Collector output,
  the resolved service environments and the committed secret locations. Raw
  sentinels were absent and no Langfuse name reached vinga.
- The built-image Jaeger repetition was not run locally because it belongs to
  the non-PR image job after an image build.

## PR review round, M3 (PR #526)

Automated external review of the PR diff `origin/main...cede7850`: claude CLI
2.1.271, read-only tool set, model `claude-opus-5`, 2026-09-14, runtime 14m40s,
[posted on the PR](https://github.com/rafacm/vinga/pull/526#issuecomment-5671704462).
Verdict: mergeable after the listed fixes. The reviewer found three P2 and
four P3 issues. It confirmed that the pinned Collector config validated, the
two-receiver fanout exercised the central policy and backend adapters, the
resolved graph isolated credentials, and the mask inventory named every
content alias, while requiring the following corrections.

1. **P2: the behavioral fanout covered only two of eleven content masks.** The
   raw-sentinel check was vacuous for nine fields, and the structural test
   accepted any regex that still used the expected replacement token.

   *Resolution* (`3ef9f381`): every synthetic span now plants the same email
   and credential sentinels in all eleven canonical and compatibility content
   attributes. Both branches assert every field they retain has both values
   masked, and the structural test requires one identical email regex literal
   across all eleven statements.

2. **P2: the direct Jaeger stop instruction erased the trial volumes.** The
   documented `down -v` removed both the database and downloaded-data volumes,
   and the fanout walkthrough had no stop or reset guidance.

   *Resolution* (`f9824f52`): both walkthroughs now use ordinary `down` to
   remove containers and the network while preserving named volumes. They
   identify `down -v` separately as an intentional full reset and name the
   configuration, conversation, model and voice data it erases.

3. **P2: direct Langfuse was called supported before its required live gates
   ran.** The record said M3 had no deviation even though neither the direct
   nor fanout Langfuse rendering gate had project credentials.

   *Resolution* (`5344a1ea`): the implementation record now carries two named,
   unchecked Langfuse acceptance items under deviations, and the plan names
   them as unchecked. The server README calls the direct recipe maintained
   while stating that the M2 turn-root and generation-content rendering has
   not yet been re-verified against a live project.

4. **P3: six independent image-pin copies could drift while tests stayed
   green.** The workflow, integration tests and provenance README were not
   cross-checked against the two Compose artifacts.

   *Resolution* (`2667cfea`): the deployment test reads both Compose image
   references, proves their versioned digest shapes, reads the two integration
   constants through the Python syntax tree, and matches the workflow and
   provenance README to those same references.

5. **P3: direct Jaeger overstated its telemetry reach as `network`.** The only
   destination is a container on the same machine, so the example would also
   be refused under the tightest truthful `host` data boundary.

   *Resolution* (`ced90a8a`): the direct overlay, built-image acceptance path,
   structural assertion and deployment explanation now consistently declare
   `host`. Fanout remains `internet` because its farthest destination is the
   Langfuse backend.

6. **P3: a cold image pull could time out and orphan a smoke container.** Both
   tests let `docker run` perform a pull under the short readiness deadline,
   before entering the cleanup scope.

   *Resolution* (`110ab8c2`): both fixtures pre-pull their pinned image with a
   five-minute download budget, then run the named container inside the
   cleanup `try` so every start outcome reaches the forced removal.

7. **P3: readiness checks could spin and hide container stderr.** An
   unsuccessful HTTP response did not always sleep, and failure diagnostics
   printed only stdout even though both images write their logs to stderr.

   *Resolution* (`355f9f18`): every unsuccessful readiness iteration now
   sleeps, and both early-exit and deadline diagnostics join stdout and stderr.
   The direct Jaeger and exact-config fanout acceptances passed together after
   the change.
