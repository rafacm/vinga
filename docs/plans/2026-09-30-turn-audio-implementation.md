# Each turn's audio, kept by the capture and filed on its turn: implementation

Companion to [`2026-09-30-turn-audio.md`](2026-09-30-turn-audio.md),
one section per milestone, appended in the same change that ticks the
milestone checklist. It records deviations from the plan, resolutions
of the plan's open questions, and discoveries.

## M1: a turn that is not opened is reported

**Attribution:** anthropic/claude-opus-5-5, thinking high; Claude Code 2.1.286; 2026-09-30.

`Telemetry._open_turn` keeps its early return when a turn span is
already open, and now says so: the first time it fires in a session it
logs one `logger.warning`,
`"session %s: a turn started while another was open, so its span was not opened"`,
with the session id as the only argument. The latch is a new field on
the session's own trace state, `_SessionTrace.reported_unopened`, so
each session reports its own first time and the latch leaves with the
session when `_close_session` pops it. No span event and no catalog
event, per the plan review's finding 6. The early return's condition
was split in two (`trace is None` returns silently as before, since a
turn for a session the exporter never opened is a different case the
plan does not touch), and the comment beside the return now says what
the case is, why the pipeline never produces it, why the open turn is
kept rather than closed, and why the report is a log line said once.

### The commits

| Commit | What it is |
| --- | --- |
| `b05a4bfd` Test that a turn the exporter declines is reported | The four M1 cases in `tests/unit/test_telemetry.py`, watched failing |
| `b99ddd17` Report a turn the exporter declines to open | The latch field, the split condition, the warning and the comment in `telemetry.py` |
| `4c7cf701` Add the changelog fragment for #517 | `changelog.d/517-turn-not-opened.md` under `### Fixed` |
| Record M1 of the turn audio plan | This file, created with its header, and the plan's tick |

### The tests, and how they were watched failing

In `tests/unit/test_telemetry.py`, under a new section beside the turn
context cases, driven through `session_events` into the in-memory
exporter as #517's own probe was:

- `test_a_turn_started_over_an_open_one_is_reported_and_not_opened`:
  `turn_started(A)`, `turn_started(B)`, `reply_finished`. One turn span,
  carrying A's utterance id, with no span events; `turn_context` answers
  for A and `None` for B; exactly one record from
  `vinga_server.telemetry`, at `WARNING`, with `record.msg` equal to the
  template and `record.args == (SESSION,)`, its one argument a `str`.
- `test_the_report_is_said_once_per_session_however_often_it_fires`:
  the start, start, finish sequence three times in one session, one
  warning.
- `test_each_session_gets_its_own_report`: the sequence in two sessions
  under one exporter, one warning each, in order, each naming its own
  session.
- `test_turns_in_the_ordinary_order_report_nothing`: start, finish,
  start, finish; two turn spans and no record from the exporter's
  logger at all.

Against the unchanged exporter, the three reporting cases failed on the
missing record alone (`assert 0 == 1`, and `[]` where the per-session
args were expected), with their span and `turn_context` assertions
already passing, which is the kept behavior they pin. The
ordinary-order case passed, as it should.

### Mutations

Each run once against `tests/unit/test_telemetry.py -k report`, the
source restored and touched after each:

| Mutation | Outcome |
| --- | --- |
| Remove the warning (plan) | Killed: the three reporting cases fail |
| Warn on every firing (plan: latch never set) | Killed: the once-per-session case fails |
| A process-wide latch on the exporter instead of the session (plan) | Killed: the second-session case fails |
| Reset the latch when a turn closes (added) | Killed: the once-per-session case fails, because its three firings each follow a close |
| Drop the early return, so the second turn opens over the first (added) | Killed: the kept-behavior case fails on the turn span's utterance id |

None survived.

### Documentation

- The `_open_turn` comment, rewritten as the plan asks, and a comment on
  the new `_SessionTrace` field.
- `docs/architecture/observability-surfaces.md`: checked, not edited.
  The one sentence about turn spans in "Exported traces" ("A session is
  one span, each turn a trace of its own linked to it, and inside a turn
  the stages that took the time") describes the trace's shape, not its
  completeness: it makes no claim that every started turn gets a span,
  and nothing in the file promises one. M1 changes no behavior the
  sentence describes (the early return is unchanged, and the case it
  covers is one the pipeline does not produce), and the new warning is a
  plain server log line rather than an exported span or event, so it
  belongs to no surface that page catalogs. Every other mention of
  "turn" there is about the store, the transcript export or sampling.
- `changelog.d/517-turn-not-opened.md`, under `### Fixed`, in final
  form: what the case is, that behavior is unchanged, the warning's text
  and its once-per-session rule, and that nothing is added to the trace.

### Deviations, resolutions and discoveries

No deviations from the plan. Two things the plan leaves implicit, decided
here:

- **The condition was split.** The plan speaks only of the case where
  `trace.turn is not None`; `trace is None` (a `turn_started` for a
  session the exporter holds no trace for) stays a silent return,
  because it is a different case from the one #517 describes and the
  plan asks for no change to it.
- **Two mutations beyond the three the plan names** were run (the latch
  reset on a turn's close, and a dropped early return), since the latch
  living on a state object that `_close_turn` also touches made the
  first a plausible regression, and the second is the behavior the plan
  says is kept.

One discovery, about formatting rather than behavior: `ruff format
--check` reports `telemetry.py` and `test_telemetry.py` as unformatted
before this change, on lines M1 does not touch. Formatting is not a CI
gate (lint is), so nothing was reformatted; the new warning's template
is kept on one line, which is how the formatter would place it and what
makes it greppable whole.

### Verification

All from `vinga-server/`, at `fdaab781`, the fragment's commit before
the rebase onto the final plan tip (this record adds prose only). That
rebase moved only plan-document commits beneath M1, and the same
commit is `4c7cf701` after it; the lanes were not rerun on the rebased
tree.

- `uv run ruff check .`: `All checks passed!`
- `uv run mypy`: `Success: no issues found in 5 source files`
- Unit lane, `-n auto --dist loadfile`:
  `7645 passed, 19 skipped in 895.00s (0:14:55)`
- Integration lane, `-n auto --dist loadfile`:
  `347 passed in 228.33s (0:03:48)`
- The generated-document drift checks, run as the workflow runs them
  (the domain, server, conversations-schema, metrics-views, events,
  OpenAPI and CLI references, and the CLI recipes): all eight identical
  to their committed copies. Nothing M1 touches reaches a generator.
- Census lane (`uv run pytest tests/census -q`), run last, after this
  record: `66 passed in 27.27s`, both manifests current.

Not verified locally: the image build and its smoke conversation, which
only CI runs. M1 changes nothing either of them exercises differently.

### PR review round, PR #571

Automated external review of this PR's diff (feature/turn-audio-plan...22e0b230).
Reviewed 2026-09-30 by openai/gpt-5.6-sol, thinking high via codex CLI 0.156.1, read-only sandbox, runtime 4m16s, at commit 22e0b230.
Verdict as received: **mergeable after the listed fixes**. Two
findings, both fixed here.

1. **P2: the completed milestone still named `PR TBD`.** The plan's M1
   item was ticked with the pull-request placeholder left in, where
   `AGENTS.md` asks for the milestone's PR number in the tick.

   *Resolution*: fixed in `ece2a3e9`. The item now links PR
   [#571](https://github.com/rafacm/vinga/pull/571), in the shape the
   other ticked plans use.

2. **P2: the new warning contradicted the module's own contract.** The
   `telemetry.py` module docstring said nothing in the module can state
   a fact the catalog does not declare, and that a tap's dispatch makes
   no syscall, while the #517 report is a non-catalog log line written
   synchronously from inside that dispatch. The reviewer asked for the
   catalog rule to be scoped to exported spans and span events, and for
   the once-per-session warning and its ordinary logging path to be
   acknowledged.

   *Resolution*: fixed in `4f431946`. The catalog rule now covers what
   the module exports, no span and no span event, and a new paragraph
   names the warning as the one exception to the reply-path rule: logged
   through the module's ordinary logger with whatever I/O its handlers
   do, never on a trace, at most once per session and only on an event
   order the runtime does not produce. The rest of the no-syscall claim
   was checked while there: the module's only other logger calls are on
   the shutdown path, not in the dispatch. Verified with
   `uv run ruff check .` (`All checks passed!`), the two telemetry test
   files (`144 passed in 179.65s (0:02:59)`, on a machine shared with a
   parallel lane, against 15.85s for the same files earlier), the doc
   link check and, last, the census lane.

The rebase onto the final plan tip moved every M1 commit, so the hashes
in the commit table above were rewritten to the rebased ones
(`b05a4bfd`, `b99ddd17`, `4c7cf701`) in the same change that added this
round. The verification section keeps `fdaab781`, the tree the lanes
actually ran on, and says so.
