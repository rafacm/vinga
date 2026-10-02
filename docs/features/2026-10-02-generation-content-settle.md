# A generation's content pair is counted once its span took it

**Date:** 2026-10-02

**Local baseline:** not applicable. The change is to how an opt-in
export counts and releases what it staged; no capability is added or
moved, and nothing local changes.

## Problem

With `server.telemetry.export_llm_input` on, `LlmInputExport.finish`
rendered a round's request and output, staged the pair into
telemetry's `_llm_content` map, and emitted
`llm_input_exported(rounds=1)` at once. Only afterwards did the
provider watch emit the event whose fold writes the pair onto the
`llm` span: `llm_round` after a round that completed, `provider_failed`
after one that failed. `SessionEvents.emit` can refuse to build an
event without dispatching it, so when the round's event was refused:

- `rounds` had already counted a pair no span received;
- the staged slot was never taken, and stayed until the exporter shut
  down;
- nothing reported `llm_input_export_failed` for it.

The tool path had the same shape and was given a settle step in #587:
a tool pair is staged, its `tool_call` emission made exactly once, and
the handoff then settled, counted only once telemetry confirms the fold
attached it. The observability page recorded that the two kinds kept
two contracts. This brings the generation path to the tool path's.

## Changes

### Telemetry: one settle for both kinds

`Telemetry.settle_llm_content(invocation)` answers whether the
`llm_round` or `provider_failed` fold wrote the pair staged under that
invocation onto its span, and releases whatever is left of the slot
either way. It and `settle_tool_content` now share one implementation,
`_settle`, over one set of attached keys (`_attached`, which replaces
`_tool_attached`): a generation's key is its invocation string and a
tool call's the `(invocation, position)` pair, so the two kinds never
meet in it. The fold side is one helper too, `_attached_to_span`, which
records a key only after a non-empty pair was written onto a span the
fold ended. Both `llm` folds now take the slot on every path, the
no-trace one included, as the tool fold already did, and record it
attached only after the span ends.

### The export: the round's event is emitted between stage and settle

`LlmInputExport.finish(invocation, emit)` now takes the closing
event's emission, the way `stage_tool` takes the `tool_call` one. It
completes, bounds and stages the pair (`_finish`, the old body), calls
`emit` exactly once whatever became of the pair, and settles. The
count-or-report step is one helper, `_settled`, used by both kinds:
on confirmed attachment it emits `llm_input_exported` with the count
under the pair's own kind, and otherwise it emits
`llm_input_export_failed(kind, dropped)`, the slot having already been
released by the settle.

### The watch: both closing events take one path

`ProviderWatch` builds the `llm_round` emission in `_rounded` and the
`provider_failed` emission in `failed` as closures, and hands either to
`_closing`, which passes it to the export's `finish` where there is an
export and calls it directly where there is none. A failure of another
stage, or an LLM failure with no invocation, is emitted directly as
before. With the export off (`export_llm_input` false, or telemetry
off, in which case no export is built at all) each event is emitted
exactly as it was.

### The first-token retry

The retry lives in `ProviderWatch.reply_stream`. The pair is staged
once, in the pipeline where the round is assembled and before
`reply_stream` is entered; a stalled first attempt is cancelled by the
watchdog, and the cancellation is a `CancelledError` that `watched`'s
`except Exception` does not catch, so the stalled attempt reports
nothing and finishes nothing. Only the event that closes the round (an
`llm_round` after the retry answers, or the `provider_failed` that
`reply_stream` reports after a second stall) reaches `finish`, once.
That was true before this change and is unchanged by it; it is now
pinned.

## Key parameters

- `Telemetry.settle_llm_content(invocation) -> bool`: new, the
  generation's settle.
- `LlmInputExport.finish(invocation, emit)`: `emit` is new and
  required, so every caller decides who emits the round's event.
- `llm_input_exported` and `llm_input_export_failed`: no field, kind or
  reason changed, so `docs/reference/events.md` needed no regeneration.
  What changed is when `rounds` is counted, and that a refused round
  now produces `kind: generation, reason: dropped`.

## Inventory

- One caller of the export's `finish` in `src/`, inside
  `ProviderWatch._closing`, which has two callers (`_rounded` and
  `failed`):
  `grep -rn "llm_input\.finish(" src` and
  `grep -rn "self\._closing(" src`, run from `vinga-server/`.
- Two call sites of `_take_llm_content` (the `llm_round` and
  `provider_failed` folds), both recording attachment:
  `grep -rn "_take_llm_content(" src` returns three lines, the third
  its definition.
- Fifteen test calls of `finish("<invocation>", ...)`, thirteen in
  `tests/unit/test_llm_input_export.py` and two in
  `tests/tools/event_baseline.py`:
  `grep -rnE '\.finish\("[^"]+", ' tests`.

## What was checked and deliberately left

- **The event baseline's driver identities** still read
  `LlmInputExport.finish` and `LlmInputExport.stage_tool`, though the
  success event is now built in `_settled`. The identities are labels
  for the path a driver exercises, with no static walk behind them
  since #210, and both paths still produce the event; collapsing them
  into one `_settled` identity would have dropped a driver for one of
  the two kinds.
- **`llm_input_export_failed.reason`'s catalog description**, "Why this
  server omitted the pair before the matching span ended", reads
  slightly loosely for a refused event, where the matching span never
  existed. It is a catalog string with a generated reference behind it,
  and nothing it says became false, so it was left.
- **`discard_llm_content`** is still called by the export's `_drop`
  for rounds evicted or dropped before they finished. Those were never
  staged into telemetry, so the call is defensive; it was left as it
  is, since it is outside this contract.

## Verification

- Pins first: two cases in
  `tests/unit/test_generation_span_content.py` drive a real session and
  the real exporter through a first-token retry that answers and one
  given up twice, and assert one `llm_input_exported(rounds=1)`, no
  failure, and one `llm` span carrying the pair. Both passed against
  the unchanged code. Under a mutation that finishes the round when the
  first attempt stalls, the retried case fails (the staged pair lacks
  the retry's output); the older snapshot-counting case in
  `test_session_llm_input.py` survives that mutation.
- The refusal cases, one per closing event (`llm_round` refused by a
  negative token count a provider reported, `provider_failed` by an
  error class whose name is not an identifier), were watched failing
  against the unfixed code: both counted `exported 1, 0` where `failed
  generation dropped` was due. They assert no success count, one
  failure, and no content on a later `llm` span under the same
  invocation, which is the observable form of no retained slot. Since
  the review round below they drive a whole reply through a real
  session, and also assert that neither the round's content nor the
  rejected class name reaches either log rendering or stderr.
- Exactly-once emission is pinned at two levels: the export's `finish`
  with the pair attached, over the ceiling, refused by telemetry and
  never staged; and the watch, for both closing events, with the export
  off, telemetry off, the pair attached, unstaged, and staged for a
  session telemetry holds no trace for.
- Telemetry's settle is pinned directly in
  `test_telemetry_llm_input.py`: true once and only once for an
  attached pair from either fold, false and released for a pair no
  event consumed, false for a pair folded with no trace, and false for
  a span written with no pair.
- Mutations, each run once against the six content-export unit
  modules, all killed: count before settle (the old order); skip the
  slot discard on refusal; skip the failure event; emit the round event
  twice, in the watch and separately in the export; emit nothing for an
  unstaged pair; settle before emitting. On the telemetry side, also
  killed: no attachment mark on either `llm` fold, a mark for an empty
  pair, a settle that keeps the slot, and a settle that keeps the mark.
- Lanes, at `-n 2 --dist loadfile` on the shared four-core machine:
  unit `7860 passed, 19 skipped in 1679.97s`, the skips being the
  optional-provider suites (faster-whisper, piper, provider lifecycle
  and boundary); integration `350 passed in 472.27s`. Both ran on the
  source as committed; the two later commits touch only
  `test_generation_span_content.py`, which was rerun on its own
  afterwards (16 passed). `ruff check .` is clean, and the census lane
  ran last.

## Review round

The external review of PR #596 (openai/gpt-5.6-sol at 504b74b2) found
one P1. The refused `provider_failed` case called `ProviderWatch.failed`
directly, and production does more after a refused event: the stream's
guard re-raises the failure, and the reply's catch in
`runtime/pipeline.py` logs `reply failed: <class name>` from the raw
`type(exc).__name__`. So the very value `provider_failed` refused to
carry still reached the retained log, by a route the test never took.

Resolved by test here and by code in #565, which lands first. That log
line is one of the sites #565 moves onto its validated class-name
helper, so this branch does not fix it a second time. The refusal
cases now run a whole reply: `ScriptedLlm` raises an exception placed
in a round's list, after delivering what came before it, and
`provider_failed` is refused by a class whose name is a sentinel. On
this branch alone the `provider_failed` case fails, naming the `reply
failed` line; on a throwaway branch merging #565's branch (at
`5613d5fe`) it and the rest of the file pass, along with the five
sibling content-export modules (78 passed). The throwaway merge was not
committed. The `llm_round` case passes either way, since nothing on
that path names a class.

#565 merged (PR #597) with more than that throwaway merge saw: a total
`class_names.class_name_of`, an exact-`str` check in `is_class_name`
and `ClassName`, and `TextValue.carried()` handing out
`str.__str__(value)`. This branch was rebased onto `main` after it, and
both refusal cases pass there with nothing on this branch changed for
it; the reply's catch now logs `failure_name(exc)`, which renders the
rejected class as the fixed fallback. Nothing about the dependency
changed: the site was fixed once, by #565, and this branch carries the
test.

## Files modified

- `vinga-server/src/vinga_server/telemetry.py`
- `vinga-server/src/vinga_server/llm_input_export.py`
- `vinga-server/src/vinga_server/runtime/provider_watch.py`
- `vinga-server/tests/support/llm_input.py`
- `vinga-server/tests/support/providers.py`
- `vinga-server/tests/unit/test_generation_span_content.py` (new)
- `vinga-server/tests/unit/test_llm_input_export.py`
- `vinga-server/tests/unit/test_telemetry_llm_input.py`
- `vinga-server/tests/unit/test_tool_span_content.py`
- `vinga-server/tests/tools/event_baseline.py`
- `docs/architecture/observability-surfaces.md`
- `changelog.d/588-generation-content-settle.md`
