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
