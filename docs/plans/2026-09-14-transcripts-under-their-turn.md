# Nest an exported transcript under the turn it describes

Plan for [#506](https://github.com/rafacm/vinga/issues/506). Its
companion is
`docs/plans/2026-09-14-transcripts-under-their-turn-implementation.md`,
one section per milestone, appended in the same change that ticks the
milestone.

## Goal

Make a turn's trace carry what was said in it.

With `server.telemetry.export_transcripts` on, a closed session's turns
go out as `transcript` observations parented on the SESSION span. The
turn traces the same session emitted are a trace each, and every span
in them (`turn`, `asr`, `llm`, `tts_stream`, `playback`) has
`input: null` and `output: null`. So a reader gets the stage timings on
one trace, the dialogue on another, and no field on either naming the
other. That is the defect, confirmed from the outside by M3's live gate
run and recorded in the #502 implementation doc.

After this, every transcript whose turn can be addressed is a child of
the `turn` span of the turn it describes, inside that turn's own trace,
and carries the utterance id both sides already agree on, so the
correlation is readable as data and not only as a nesting. A turn that
cannot be addressed, which is a row with no utterance and a turn
evicted past the retention, keeps the parent it has today, the session
span. Both halves are the promise: the nesting where the addressing
exists, the session span and no invented parent where it does not.

This is M4a's first consumer and the end-to-end proof that the join
M4a built actually joins: M4a proved each side separately (the store's
two handover rows carry one id, the exporter retains a turn under a
given id) and deliberately left the join at the wire to this change.

**Local baseline:** not applicable. Nothing here changes a
conversational capability. It changes where an already exported span is
parented, on a surface that is off by default, refused under a
`server.data_boundary` narrower than `internet`, and never on the audio
path.

## What this inherits, and does not re-litigate

From the umbrella plan `docs/plans/2026-09-12-telemetry-overhaul.md`
and from M4a (PR #516):

- **The mechanism is the issue's own option 2**, decided in the
  umbrella plan on 2026-09-12: parent each transcript to its turn's
  retained context. The issue is sequenced directly behind M4a for that
  reason, and was impossible before it.
- **The join key is the utterance handle**, minted where `turn_started`
  is emitted, declared on that event, carried on the turn state into
  every `TurnRecord` the turn produces, and stored in `turns.utterance`.
  A handover writes two rows and both carry the same handle, which is
  the many-to-one the key is for.
- **Forbidden: an ordinal counted independently on each side.** The
  export's ordinal counts the turns it actually wrote, so a turn with no
  stored text shifts one side and not the other.
- **The addressing already exists.** `Telemetry.turn_context(context,
  utterance)` answers a turn's pinned context from a session's pinned
  context, takes `str | None`, and answers `None` for an utterance this
  exporter never opened a turn for, for one evicted past
  `RETAINED_TURNS` (256 per session, oldest first), and for no utterance
  at all. A turn pin is captured at the turn's OPEN, so a turn a barge-in
  or a failure ended early is pinned all the same.
- **A session's turn pins ride the session's own pin**, so a job that
  captured `retained_context` at admission holds every turn under it and
  no second window can age out between the two reads.

## Open questions, resolved

### Option 2 rather than option 1 or option 3

The issue lists three. Option 1 (put the turn's trace id on the
transcript as an attribute) makes the join possible for a reader with
an API and leaves the UI exactly as broken as it is now, which is the
half of the complaint that sent the issue in. Option 3 (defer the turn
span's end until the transcript exists) would trade a live-emission
property that the whole live surface is built on for a nesting; a turn
span that ends when its session closes reports nothing while the
conversation is happening, and a crash before the close would lose the
turn rather than lose its text.

Option 2 is what M4a already paid for. It costs the parenting argument
and nothing else at the wire: the spans are built the same way, ride the
same private tracer, deliver through the same bounded call.

What this plan takes from option 1 anyway is the ATTRIBUTE, for the case
option 2 cannot serve: see below.

### The key crosses on the seam the projection already is

`transcript_rows` is a narrow projection (`id`, `t_ms`, `agent`,
`heard`, `reply`, `legs`), and `TranscriptTurn` is the seam type it
becomes. The utterance joins both: one column in `TRANSCRIPT_COLUMNS`,
one member on `TranscriptTurn`, one line in `_turns`.

Not a second read and not a second map. The alternative would be the
exporter asking the store for a session's utterances and zipping them
against the rows it already has, which is two queries that must agree,
which is the repository's standing "two structures that must agree are
one structure with a bug pending".

The projection's own rule is unchanged and worth restating, because
growing it is exactly the move that rule exists to bound: what may cross
is what an export is authorized to carry. A server-minted opaque
identifier is metadata rather than content, which is the reading the
column's own comment records and which M4a settled.

### A transcript whose turn cannot be addressed still exports, under the session span

`turn_context` answers `None` in four cases, of which two are reachable
here: a row whose `utterance` is null (written before M4a, or by a turn
that opened no span because telemetry was off at the time), and a turn
evicted past `RETAINED_TURNS` in a session that ran more than 256 of
them.

Those transcripts are parented where they are parented today, on the
session span, and this is a deliberate deviation from what
`turn_context`'s own documentation prescribes for an ARTIFACT. A clip
filed against the wrong observation is worse than one that says it
could not be filed, because a reader listening to a clip believes the
turn it hangs under. A transcript is not in that position: the session
span is the transcript's own home today, it is true of the row that it
was spoken in that session, and dropping it instead would cost a
reader the words for the sake of a nesting. #495's promise is that a
reader can tell what was said; this change makes it more precise where
it can and never less complete.

The fallback is legible without being announced: a transcript under
`session` rather than under `turn` is visibly the un-nested case in the
same view that shows the nested ones.

### No count of un-nested transcripts is reported

Considered and rejected. `transcripts_exported` carries `turns` and
`elapsed_ms`, and a third field saying how many could not be nested
would be an operator-facing number nobody can act on and only half
knowable at the emit site: the exporter can see a null column, and
cannot see an eviction, which happens inside the module that owns the
retention. Reporting the half it can see as if it were the whole would
be the kind of claim wider than its evidence this repository keeps
catching.

Making it whole would mean widening `export_transcript`'s answer from
`Delivery` to a record carrying a count, and `Delivery` is a three-word
vocabulary two modules speak. A nesting failure is visible on the trace
that has the problem, which is where a reader is already looking.

### The utterance id rides the span as well as deciding its parent

One attribute, `vinga.utterance.id`, the name the turn span already
uses, on the transcript span too.

It is what makes the fallback case still joinable: a reader holding a
transcript that could not be nested can still find the turn trace by
querying that id, exactly as option 1 promised, and a reader holding a
stored row can find its transcript. It also makes the nesting
self-describing rather than implicit in a parent pointer, and it is the
attribute a wire test asserts to prove the two sides agree.

The name is spelled ONCE. It lives inline in `TURN_ATTRIBUTES` today;
this change lifts it to a module constant that both the turn's table and
the transcript's builder read, because two spellings of one identifier
is the drift `trace_of` exists to avoid one level up.

A row with a null utterance contributes no attribute, the absence rule
`_transcript_attributes` already keeps for every other optional half.

### The session trace stops carrying the words, and that is not a loss

After this, a session that was fully addressable has its `session` span,
its capture spans and its `transcripts_exported` span, and no dialogue.
The dialogue is one level down, in the turn traces.

What keeps the conversation readable as one thing is what already keeps
the turn traces readable as one thing: every transcript span carries the
session under both spellings (`session.id` and `vinga.session.id`), so
the backend's session view groups them with the turns they now sit in,
and the query a reader already makes still returns them. That grouping
is the same mechanism that makes a turn trace, which is a root trace of
its own, belong to its session at all.

### The device name keeps coming from the same place

`_named` takes any pinned context and `_pin_turn` copies the session's
`name` onto the turn's pin at the open, so a transcript parented on a
turn names the board exactly as it does today, including contributing
no attribute where the board is unnamed. Verified in the code rather
than assumed: `_pin_turn` sets `name=exported.name`.

## Module layout

No new module. Three existing ones get one fact each, and the depth
claim is that no caller learns anything new: the exporter still hands
over an opaque context and a list of turns and learns nothing about
pins, and the store's projection still answers one page of one
question.

| Module | Change |
| --- | --- |
| `conversations/threads.py` | `turns.c.utterance` joins `TRANSCRIPT_COLUMNS` |
| `transcript_export.py` | `_turns` carries the column onto the seam type |
| `telemetry.py` | `TranscriptTurn.utterance`; `_transcript_spans` resolves each turn's pin and parents there, falling back to the passed session context; `_transcript_attributes` writes the id; the attribute name becomes a shared constant |

Design footprint: one member on an existing seam type, one resolution
inside the module that owns the retention, one name lifted to its single
home. No new seam, no new interface method, nothing a caller must learn.
`turn_context` is called from inside `Telemetry` rather than from the
exporter deliberately: the exporter holds an opaque handle and the
retention is not its business, and routing the resolution through it
would put a pin-shaped object in a module whose whole seam is that it
never sees one.

## Tests

Reusing the existing assets rather than restating them: the unit lane's
fake SDK and its `a_row`/`reading` transcript support, and the
integration lane's real OTLP `Receiver` with a real device conversation
that already drives a handover.

**Unit, `tests/unit/test_telemetry_transcripts.py`.**

- A turn whose utterance is pinned becomes a span in THAT TURN's trace,
  as a child of the turn span, and not in the session's.
- Two turns of one page land in two different traces, which is the case
  a single context argument used to hide.
- A row whose utterance is null stays a child of the session span.
- An utterance this exporter never opened a turn for, and one evicted
  past `RETAINED_TURNS`, stay children of the session span too.
- A handover's two rows carry one utterance and both land under the one
  turn span, which is the many-to-one the key exists for.
- The utterance id is on the span under `vinga.utterance.id`, and a null
  one contributes no attribute.

**Unit, `tests/unit/test_transcript_export.py`.** The projection's
utterance reaches the seam type unchanged, including null, so a column
the store grew cannot be dropped silently between the read and the span.

**Integration, `tests/integration/test_transcript_export.py`.** The
wire claim, extended. The existing real-server, real-collector,
real-handover case writes TWO transcript observations, and the reason
matters for what this asserts: the mock-driven handover records two
TURNS, the switch itself and the answer, not one turn's two rows (the
case says so at its own assertion). So each observation is matched
against the turn span carrying its own `vinga.utterance.id`, selected
by that id rather than by span name, and both are asserted: same trace
id as its turn, parent span id equal to that turn's span id, and the
two observations in two DIFFERENT traces, which is the property a
single passed context used to make impossible.

The other half of the join, a handover's two rows resolving to one turn
span, is many-to-one and cannot be produced by that case. The store
side of it is already pinned through the real pipeline by M4a
(`tests/unit/test_session_record.py::test_a_handovers_two_rows_answer_one_utterance`),
and the exporter side is the unit case above, where two turns carrying
one utterance land under one span. Naming both here is what keeps the
integration case from being read as the proof of something it does not
produce.

The reason the integration lane is where the one-row join belongs is
that neither side is faked: the id on the span is the one the pipeline
minted and the id in the row is the one the store wrote.

**Falsification.** Every new case is watched failing before it is
believed. The nesting cases fail against the pre-change parenting with
the session's trace id where the turn's belongs. The fallback cases are
falsified the other way, by pinning the turn and watching the case that
asserts the session parent fail, so they pin the fallback and not merely
the absence of a pin.

## Documentation footprint

- `docs/architecture/observability-surfaces.md`, "Exported transcripts":
  "one observation each on the trace that session was exported under" is
  the sentence this change falsifies. It becomes the turn's trace, with
  the session's named as where an unaddressable turn's transcript still
  goes. This page is the authority for the surface, so the fact lands
  here and nowhere else.
- `vinga-server/src/vinga_server/config/models.py`, the
  `export_transcripts` field description, for the same sentence
  ("written onto the trace that session was exported under"). It
  regenerates `docs/reference/server-config.md`, and the generated
  references change only through their generators.
- `vinga-server/README.md`, the events table line for
  `transcripts_exported` ("a closed session's turns are on its trace,
  one observation each").
- `config.example.yaml` if and only if the field's comment quotes the
  changed sentence; checked rather than assumed.
- The command-spellings census is re-run after the documentation edits,
  and the manifest regenerated by its own generator if it moved.

No event is added or changed, so `docs/reference/events.md` does not
move.

**And the contracts in the source, which are documentation the same
way.** Every one of these says today that a transcript rides the trace
its SESSION was exported under, and every one is false after the
change. They are listed rather than left to a grep during the work
because the review found them and a milestone that names three pages
and leaves five sentences behind has not stated its footprint:

- `transcript_export.py`'s module docstring, and step 3 of
  `build_transcript_export`'s prose.
- `TRANSCRIPTS_NEED_TELEMETRY`, which is operator-facing: it is the
  sentence a refusing boot prints. The rewording is minimal, since what
  the refusal is ABOUT is unchanged (no exporter, no trace), and the
  pins and the generated reference that quote it move with it.
- `Telemetry.export_transcript`'s docstring, which states the parentage
  in its first paragraph.
- `TranscriptTurn`'s "exactly these seven facts", which becomes eight.
- The integration suite's module docstring and the parenting
  assertions under it, which are the wire claim being restated.
- Both event rows in `vinga-server/README.md`, the
  `transcripts_exported` one and the `transcript_export_failed` one,
  each of which says "its trace" meaning the session's.

The rule the list applies: a sentence that is load-bearing about where
a span goes moves in the change that moves the span, wherever it
lives.

## Risks

- **A session with more than 256 turns exports its oldest turns under
  the session span.** Accepted and documented: the bound is M4a's, it is
  per session, and the fallback is the honest answer rather than a wrong
  parent.
- **A reader's saved query that expected transcripts on the session
  trace stops matching.** The surface is off by default, landed on
  2026-09-12, and the session-id attributes that every such query is
  built on are unchanged. The changelog entry says the nesting moved.
- **The transcript span inherits the turn trace's sampling.** There is
  no sampler configured on this exporter, and the post-close writers
  build their parent context with the sampled flag set explicitly, so
  this is a non-risk here; named because it is the thing that would
  silently drop spans if a sampler were ever added.

## Milestones

- [ ] **M1: an addressable transcript is a child of its turn**. The
  utterance joins the projection, the seam type and the span's
  attributes; the span is parented on the turn's pinned context where
  there is one and on the session's where there is not, which is the
  milestone's acceptance in both directions and not a caveat on it; the unit cases above, the wire case in
  the integration lane, the three documentation edits and a
  `changelog.d/506-transcripts-under-their-turn.md` fragment under
  `### Fixed`. Design footprint: one member on an existing seam type,
  one resolution inside the module that owns the retention, one
  attribute name lifted to its single home; no new module and no new
  interface. Documentation footprint: the observability map's exported
  transcripts section, the `export_transcripts` field description with
  its regenerated reference, and the server README's events table line.

One milestone because this is one behavior change, and the house rule
is that a behavior change sits alone in review rather than that every
diff is cut until it is small. The whole of it is a parenting argument,
the fact that decides it, and the attribute that makes it readable.

## Verification beyond the lanes

The live check M4a deliberately did not run: the gate rig against a real
backend, a multi-turn conversation with the conversation store and
`export_transcripts` on, reading back whether the transcript really
renders under its turn in the backend's own UI rather than merely
arriving with the right parent id. The wire test is what gates the
MERGE, because it is in CI and it is the stronger claim about what
vinga emits.

The live run gates the ISSUE. #506 is a report about reading a
conversation in the backend's own UI, and a correct parent id does not
prove that the backend accepts a child observation exported separately
and long after its parent ended, nor that it renders it under the turn.
So the milestone merges on a green lane and the issue closes on one of
two things: a live run showing a transcript rendered under its turn,
or a closing note that narrows the claim in writing to the topology
vinga emits, naming the unproved half and leaving it open as its own
issue. A recorded "not run" is an answer about the check and never
about the defect.

## Plan review round

External review: codex CLI 0.154.0, model gpt-5.6-sol, read-only
sandbox, 2026-09-14, runtime 7m00s, reviewing commit 078e65ef. Verdict
as received: **ready after the P1/P2 amendments** (six findings, all
P2, no P1).

The prompt pasted every load-bearing excerpt inline and told the
reviewer to reach the two large files only through `grep` and narrow
windows, which is the shape the #502 round settled after two runs
exhausted their context and returned nothing.

Findings condensed but faithful; resolutions appended per amendment.
Every one was checked against the code before being accepted, and one
is accepted with its premise corrected.

### 1 (P2): the user-visible acceptance check is optional

The live backend check is written as recordable "not run", although the
issue is about reading a conversation in the backend's own UI. Correct
OTLP parent ids do not prove that the backend accepts a late,
separately exported child or renders it beneath the turn. The plan
should make the live check a completion gate, or narrow the goal
explicitly to the topology vinga emits.

### 2 (P2): the wire test does not cover both rows of the handover join

The plan compares one transcript span with one turn span, while the
integration case already produces two transcript observations and
M4a's key exists to make a handover's rows resolve to one turn. Both
should be asserted, and the turn should be selected by utterance id
rather than by span name.

*Resolution* (commit below): taken, with its premise corrected. Both
observations are asserted and the turn is selected by utterance id.
But the two observations that case produces are two TURNS rather than
a handover's two rows, which the case's own comment states: the
switching agent's reply spoke nothing and the second agent answered in
a turn of its own. So the wire case proves two transcripts in two
different traces, and the many-to-one is proved by the exporter unit
case beside M4a's store-side case, both named in the plan now.

### 3 (P2): the stated goal is impossible under the plan's own fallback

The goal promises "each transcript" is a child of its turn, and the
plan then leaves null, unknown and evicted turns on the session span.
The promise should be nesting for every ADDRESSABLE transcript, with
the fallback stated in the goal and in the milestone's acceptance.

*Resolution* (commit below): taken. The goal now promises the nesting
for every addressable transcript and states the session-span fallback
beside it, and the milestone's title and acceptance say both halves
rather than carrying the fallback as a caveat.

### 4 (P2): the impact inventory leaves false contracts behind

Beyond the three documentation edits the milestone names, the claim
that a transcript rides its session's trace is also made by
`transcript_export.py`'s module docstring, its builder's step 3, the
operator-facing `TRANSCRIPTS_NEED_TELEMETRY` refusal sentence,
`export_transcript`'s own docstring, `TranscriptTurn`'s "seven facts",
the integration suite's module docstring and its parenting assertions,
and both `transcripts_exported` and `transcript_export_failed` rows in
the server README.

*Resolution* (commit below): taken in full. All eight are enumerated in
the documentation footprint, with the note that the refusal sentence is
operator-facing and carries pins and a generated reference with it.

### 5 (P2): required projection and fixture work is absent

`test_the_transcript_projection_is_exactly_the_authorized_columns`
asserts the projection's column set exactly, `tests/support/transcripts.py`
builds every fake row without an utterance, and `TranscriptTurn` is
constructed directly in more than one suite. The plan should require a
real-store projection case with a non-null utterance, name the fixture
updates, and say whether the new member defaults.

### 6 (P2): the fallback's claimed equivalence to option 1 is false

Option 1 in the issue carries the turn's trace and span ids. The plan
carries `vinga.utterance.id` and calls it option 1's attribute. A null
row carries no attribute at all, a turn telemetry never opened has no
trace to find, and an evicted turn is reachable only if the backend can
filter on that attribute. It should be called a shared correlation key,
with the reachable cases named.

*Resolution* (commit below): taken. The live check is a completion
gate on the issue rather than an optional extra: the lane gates the
merge, the live run gates the close, and where it cannot run the
closing note narrows the claim to the emitted topology and leaves the
rendering half open rather than implying it.
