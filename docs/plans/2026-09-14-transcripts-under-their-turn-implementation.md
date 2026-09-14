# Nest an exported transcript under the turn it describes: implementation

Companion to [`2026-09-14-transcripts-under-their-turn.md`](2026-09-14-transcripts-under-their-turn.md),
one section per milestone, appended in the same change that ticks the
milestone checklist. It records deviations from the plan, resolutions
of the plan's open questions, and discoveries.

## M1: an addressable transcript is a child of its turn

One behavior change and the three facts that carry it: the utterance
joins the store's transcript projection, crosses the exporter's seam
type, and decides which trace the span is written into. Where it cannot
decide anything, the span stays where every transcript used to go.

### What landed

| Piece | Where |
| --- | --- |
| The column on the read surface | `conversations/threads.py`: `turns.c.utterance` joins `TRANSCRIPT_COLUMNS`, with the comment saying why an opaque server-minted id passes the projection's own rule rather than widening it |
| The fact on the seam | `transcript_export.py`'s `_turns` copies the column; `telemetry.py`'s `TranscriptTurn` gains `utterance: str \| None = None`, last member, and its contract becomes "exactly these eight facts" |
| The parenting | `Telemetry._transcript_spans` resolves `self.turn_context(context, turn.utterance)` per turn and continues that pin, falling back to the passed session context; `_named` reads the pin actually used |
| The shared key | `UTTERANCE_ID = "vinga.utterance.id"` lifted out of `TURN_ATTRIBUTES` into one module constant, read by the live turn table and by `_transcript_attributes`, which writes it on the transcript span and omits it for a null |
| The unit cases | `tests/unit/test_telemetry_transcripts.py`: nested under its turn and not on the session's trace, two turns in two traces, a handover's two rows under one turn span, and the three fallbacks (null utterance, an utterance no turn was opened for, a turn evicted past `RETAINED_TURNS`), plus the attribute present and absent |
| The seam case | `tests/unit/test_transcript_export.py`: the column reaches `TranscriptTurn` unchanged, null included |
| The projection case | `tests/unit/test_conversations_threads.py`: the authorized column set grows `utterance`, against a real store, read back from a recorded turn |
| The wire case | `tests/integration/test_transcript_export.py`: both observations matched to the turn span carrying their own `vinga.utterance.id`, same trace, parent span id equal to that turn's, with neither side of the id faked |
| The fixtures | `tests/support/transcripts.py::a_row` and `test_telemetry_transcripts.py::a_turn` default to a real utterance, so the fallback path is what a case says out loud |
| The contracts in the source | `transcript_export.py`'s module docstring, `build_transcript_export`'s step 3, the `TRANSCRIPTS_NEED_TELEMETRY` refusal and the comment above it, `Telemetry.export_transcript`'s docstring, `TranscriptTurn`'s facts, the unit suite's module docstring and one of its comments, the integration suite's module docstring |
| The pages | `docs/architecture/observability-surfaces.md`'s "Exported transcripts", the `export_transcripts` field description in `config/models.py` with `docs/reference/server-config.md` regenerated, `config.example.yaml`'s comment, both event rows in `vinga-server/README.md` |
| The changelog | `changelog.d/506-transcripts-under-their-turn.md`, `### Fixed` |

### Deviations from the plan

Two, both forced by one measurement.

- **The wire case proves the many-to-one, not two traces.** The plan's
  review round resolved finding 2 by correcting its own premise: it
  recorded that the integration conversation produces two TURNS (the
  switching agent's silent reply and the second agent's answer) rather
  than one turn's two rows, and asked for the two observations to be
  asserted in two DIFFERENT traces. Measured on the wire, that premise
  is wrong in the other direction. The conversation opens ONE turn: the
  collector receives one `turn` span, and both transcript observations
  carry that span's `vinga.utterance.id`. What the handover produces is
  two store ROWS under one utterance, because the store writes one row
  per turn and conversation and the switch moved the conversation. So
  the case asserts what it can produce, which is the many-to-one at the
  wire with neither side faked, and the two-different-traces property is
  the exporter unit case next door, where two turns are actually opened.
  The case's own comment, which was the source of the review's premise,
  said "two turns" and now says two rows.
- **`docs/reference/events.md` moved.** The plan says it does not,
  because no event is added or changed, and no event was. But the
  `transcripts_exported` note ended "the trace it is on is the one
  already named by the session", and the `transcript_export_failed` note
  located a truncated export "beside this event on the same trace". Both
  are claims about where a span goes, both are false after this change,
  and the plan's own rule for the footprint is that such a sentence
  moves in the change that moves the span, wherever it lives. The two
  notes and one variant docstring were reworded in `events/catalog.py`
  and the reference regenerated with its own generator. No field, no
  variant, no reason token and no log template changed, so the events
  the server emits are byte for byte what they were.

### Resolutions the plan left to this milestone

None outstanding. The plan's six open questions were resolved in the
plan, and the milestone built what they say: option 2 rather than 1 or
3, the key crossing on the projection the exporter already reads, the
session-span fallback for a turn that cannot be addressed, no count of
un-nested transcripts, one shared correlation key rather than the turn's
trace and span ids, and the device name off the pin actually used.

### Discoveries

- **The integration conversation is a handover, not two turns.** Above,
  as a deviation, and worth keeping as a fact about the lane: the mock
  switch produces one turn and two rows. Anything later that wants two
  turns from the integration lane has to drive two utterances rather
  than assume the handover is one.
- **`_named(pinned)` and `_named(context)` cannot be told apart by any
  test.** Reported as a surviving mutation rather than left silent:
  swapping the pin for the session context leaves the whole telemetry
  suite green. It is an equivalent mutation rather than a gap, because
  `_pin_turn` copies `exported.name` onto every turn's pin at the open
  and a session's name never changes afterwards, so the two expressions
  evaluate to the same dictionary for every reachable input. A test
  asserting the device name on a nested transcript would pass under both
  spellings and so would not falsify anything. `_named(pinned)` is kept
  because it reads the pin the span is actually parented on, which is
  the locality rule; the equivalence is a fact about the pin, not a
  licence to read from somewhere else.

### Verification

Every new case was **watched failing before it was believed**, in the
direction that makes it a claim about the nesting rather than about
anything else.

- The three nesting cases were run with the parent forced back to the
  passed context (`pinned = context`). All three fail with the session's
  trace id where the turn's belongs; the wire case fails on the parent
  span id off the protobuf. The fallback cases stay green under that
  mutation, which is what says they are not the ones doing the work.
- The three fallback cases were falsified the other way, by pinning the
  turn each one names (the null utterance and the unknown one replaced
  by the session's real one, the evicted one by the youngest). All three
  then fail, so each pins the fallback rather than the absence of a pin.
- The projection case was run with `turns.c.utterance` taken back out of
  `TRANSCRIPT_COLUMNS`: it fails on the column set. The seam case was
  run with `_turns` no longer copying the column: it fails with `assert
  None == 'an-utterance'`.

Lanes and checks, from `vinga-server/` unless said otherwise:

- [x] `uv run ruff check .`: all checks passed.
- [x] `uv run mypy`: success, no issues found in 5 source files.
- [x] `uv run pytest tests/unit -q`: 7340 passed, 19 skipped, 13m29s.
      Serial, which is how this machine runs it; the distributed lane
      CI runs is not reproducible here, because the compose database is
      shared with another session.
- [x] `uv run pytest tests/integration -q`: 341 passed, 8m10s.
- [x] The generated references, each regenerated by its own generator
      and never by hand, and every committed one diffed against a fresh
      render afterwards: `domain-config.md`, `server-config.md`,
      `conversations-schema.md`, `metrics-views.md`, `events.md`,
      `api-openapi.json` and `cli.md` are all current. Two of them
      moved, `server-config.md` and `events.md`.
- [x] `uv run pytest tests/unit/test_command_spellings.py -q` after the
      documentation edits: green, and the manifest did not move, so
      nothing was regenerated.
- [x] `python3 scripts/check_doc_links.py .` from the checkout root:
      checked 243 files, 0 failures.
- [x] `python3 scripts/fold_changelog.py check .`: checked 1 fragment,
      0 failures.
- [x] The live backend check, which the plan makes the gate on the
      ISSUE rather than on this milestone. Run after the lanes were
      green; the measurement is below.
- [ ] Anything on a board. No protocol, no firmware-visible behavior and
      no device path moves here, so there is nothing a device checkpoint
      could falsify.

### The live gate

Run 2026-09-14 on commit `ad9f8fb4`, with the conversation store and
`server.telemetry.export_transcripts` on, against the backend this
repository develops against. Two turns, session
`7a855a1b1d004c2485faa919cba218c0`, which is two turn traces.

What the backend holds, read back from it rather than from what vinga
sent:

| Turn trace | `turn` span | `transcript` observation |
| --- | --- | --- |
| `b13e566e565a2f04dde92c62f82d29e9` | `5b3759655940f512` | `e9680a1e91d9bd1f` |
| `ada1fd178636f6330371f99c178a1234` | `410f6a04303b9353` | `8f6e0a8bce93c73e` |

Each observation's `parentObservationId` is its own trace's `turn`
span. On the first row, both spans carry `vinga.utterance.id`
`e6048f4ce696489e9ba68ea52736a2fb`, which is the join read back out of
the backend rather than off the wire, and that observation's input and
output are that turn's words.

**What this proves, and only this.** The backend accepts a child
observation exported separately and long after its parent span ended,
and nests it under that parent. That is the half the wire test cannot
make: a correct parent id in the protobuf says what vinga emitted, not
what a backend does with it, and #506 is a report about reading a
conversation in the backend's own UI.

**What it does not prove.** One backend, one deployment, two turns. It
says nothing about another backend's ingestion, about a session long
enough to evict a turn pin, or about how any of this renders at a
hundred turns. The unaddressable fallback was not exercised live; it is
pinned in the unit lane.

### PR review round, PR #518

External review: codex CLI 0.154.0, model gpt-5.6-sol, read-only
sandbox, 2026-09-14, runtime 4m10s, reviewing `main...ad9f8fb4`.
Verdict as received: **mergeable after the listed fix**. One finding,
adopted, fixed in a commit of its own.

1. **P2: transcript export messages still describe the removed
   session-trace topology.** `TranscriptsExported.TEMPLATE` still logs
   "exported to its trace" and `TranscriptExportFailed`'s docstring and
   TEMPLATE say the turns did not reach "its trace"; the same claim is
   made by `TranscriptExportFailure`'s opening line in `values.py` and
   twice in `transcript_export.py`, where the delivered pages and the
   failure event are described as sharing one trace. Addressable
   transcripts now occupy potentially many turn traces while the
   outcome event remains on the session's. The generated reference
   repeats the two templates. Fix: reword the templates and the related
   prose, regenerate `docs/reference/events.md`, and update any
   exact-message test and the census if affected.

   *Resolution.* Adopted, and every site confirmed in the tree before
   it was touched. The two operator-facing lines name the destination
   they can honestly name and drop the locative that was the false
   half: "%d turn transcripts exported to telemetry in %d ms" and
   "transcripts not exported to telemetry (%s)". The failure variant's
   docstring and the failure enum's opening line say the telemetry
   backend rather than a trace; the `reason` field's note now locates a
   truncated export on the turns that did go out, as the highest index
   any of them carries, which is where it actually is. Both places in
   `transcript_export.py` say what holds: the delivered pages stand,
   each under the turn it describes, and the failure event is on the
   session's own trace rather than beside them. `values.py`'s second
   sentence was left exactly as it was, since a reader looking at a
   trace with stage timings, no words and no way to learn any were
   meant to be there is if anything more apt now than before. No field,
   no variant and no reason token moved, so nothing a parser reads
   changed; `docs/reference/events.md` was regenerated by its own
   generator. No test pinned either message: the suites match on
   `record.event` rather than on rendered text, and the census manifest
   did not move.
