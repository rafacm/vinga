# Named aggregate views over the conversation record: implementation

Companion to [`2026-09-10-metrics-views.md`](2026-09-10-metrics-views.md).
One section per milestone, appended in the same change that ticks the
milestone checklist: deviations from the plan, resolutions of its open
questions, and what was discovered on the way.

## M1: the views, the reference and the proof

PR #447.

### What landed

`src/vinga_server/conversations/views.py` is the one home for what a
view is: name, question, denominator sentence, telemetry-off sentence,
a per-column declaration matrix (name, type, meaning, units,
nullability, formula), and the SQL body. Four views, exactly the ones
the plan freezes, with the frozen column names and types. The three
shared rules the plan states (a UTC day derived from
`started_at::timestamptz AT TIME ZONE 'UTC'` plus the row's `t_ms`,
counting per stored row, a null rate on a zero denominator) live in
that module as one `SESSION_DAY` constant and one `offset_day` helper
that every definition reads, so four definitions cannot come to
disagree about what a day is.

Migration `1006_metrics_views` spells the same `CREATE VIEW` statements
literally, with a `COMMENT ON VIEW` carrying each view's question and
denominator, and a downgrade that drops all four.

`docgen.views_reference()` renders `docs/reference/metrics-views.md`
from the declarations, and `vinga-server conversations views` prints
it. The moved pins the plan enumerated all moved: the CLI test that
pinned `schema` as the sole command, the group's help text and its
refusal sentence, the workflow's drift-check list, the docs index, and
the spellings manifest.

Tests: eight integration cases seeded by exact SQL rows, an agreement
case, a live-column-list case, a comment case, and the analyst cases in
`test_provisioning.py`; a unit suite over the declarations and the
rendered page.

### Deviations

- **The migration is `1006_metrics_views`, not `1005_metrics_views`.**
  The plan was written before PR #442 merged, and that PR took the 1005
  slot on the conversations chain with `1005_providers_are_per_agent`,
  a column-comment migration. So this one is 1006 and its
  `down_revision` is `1005_providers_are_per_agent`. The id is 18
  characters, well under the 32-character `alembic_version` limit. The
  CI wheel step's chain-head pin therefore moves from
  `1005_providers_are_per_agent` to `1006_metrics_views` rather than
  from `1004_telemetry_names_the_switch`, and the unit suite's `HEAD`
  constant moves with it. Nothing else about the migration changed.

- **The renderer is a second function in `docgen.py`, not a second
  module.** The plan says "a sibling renderer beside the schema one",
  which reads either way. A new module would have needed its own copy
  of `_paragraph` and `_cell`, and two copies of the wrapping rule are
  two things that must agree about what a committed page looks like:
  exactly the shape the design guide's locality rule rejects. The
  module is still one responsibility, documenting this store, and its
  docstring now says both documents and their two sources.

- **The workflow's "five generated-document drift checks" comment lost
  its number instead of gaining one.** The count was already wrong
  before this change (six documents were checked, not five), so
  incrementing it would have replaced one wrong number with another.
  The sentence now names no count, with the reason written beside it:
  the steps are the list.

- **One test written and then removed.** A case asserting that
  `vinga_ro` cannot `delete from record.metrics_sessions_daily` came
  back `55000` (object not in prerequisite state) rather than `42501`
  (insufficient privilege): an aggregate view is not automatically
  updatable, so Postgres refuses on the view's shape before it consults
  a privilege. The case would have been asserting Postgres's own
  updatability rule rather than anything the provisioning file
  promises, and the base-table refusal is already covered by
  `test_the_analyst_role_cannot_write_what_it_can_read`, so it was
  dropped rather than reworded.

Everything else follows the plan and its two review rounds as written.
No column name, type or predicate departs from the frozen contracts.

### Discoveries

- **The stored event names are the ones the plan freezes.** Verified
  against `docs/reference/events.md` and
  `vinga_server/events/catalog.py`: `provider_failed` and
  `barge_in_suppressed` are stored exactly so, and the catalog carries
  one `barge_in_suppressed` name at INFO with three variants that
  differ in `fields.reason`. No correction was needed, and the
  predicates are the plan's literals with no reason filter.

- **`get_table_names` really does exclude views, verified rather than
  assumed.** On a database migrated to `1006_metrics_views`,
  `inspect(engine).get_table_names(schema="record")` returns the six
  tables plus `alembic_version` and none of the four views, while
  `get_view_names` returns exactly the four. So the CI wheel step's
  expected-table assertion needs no change, and
  `compare_metadata(context, schema.metadata)` still returns `[]` with
  the views present, which is what keeps the baseline-equality test
  green and is why views deliberately stay outside `schema.py`'s
  `MetaData`.

- **`ALTER DEFAULT PRIVILEGES ... GRANT SELECT ON TABLES` covers a
  view.** Postgres counts a view as a relation of the `TABLES` class,
  so `vinga_ro` reads all four with no new grant in
  `deploy/postgres-init.sql`, asserted by iterating the declarations in
  `test_provisioning.py` rather than assumed.

- **The agreement test needed no normalizer of its own.** Rather than
  comparing two formatted strings, it creates a shadow view from the
  declaration inside a savepoint, reads `pg_get_viewdef` of both the
  shadow and the migrated view, and rolls the savepoint back. Postgres
  does the normalizing, so the comparison survives whitespace and
  survives the planner rewriting a construct into its own spelling.
  A savepoint rather than a transaction, because reading the live
  definition first has already autobegun one on that connection.

- **`json_array_elements` needs its guard inside the call, not in the
  join condition.** A `LEFT JOIN LATERAL ... ON json_typeof(legs) =
  'array'` still evaluates the function before applying the condition
  and would error on a turn whose `legs` is a JSON object. The guard is
  a `CASE` inside the argument instead, which hands the strict
  set-returning function a NULL and yields zero rows, so the left join
  falls back to the turn row.

- **Two view comments were reworded to avoid an apostrophe.** A
  `COMMENT ON VIEW` takes no bind parameter, so its text is a SQL
  literal in frozen history; rewording ("the traffic of the same day",
  "the numbers in every other view") keeps the migration free of
  doubled quotes rather than freezing an escaping subtlety.

- **The percentile numbers are worth pinning as literals.** Over 100,
  200, 300 and 400 ms, `percentile_cont` gives 250.0 and 385.0 where
  `percentile_disc` would give 200 and 400. The integration case
  asserts the interpolated pair, so a later change of aggregate is a
  red test rather than a quietly different number.

### PR review round

External review of PR #447: one P2, no P1, mergeable after it. Adopted.

- **P2: the telemetry-coverage prose over-claimed.** It said a gap
  between `turns` and a measured token count meant telemetry was off
  rather than that the provider reported no usage, and offered
  `telemetry_sessions` as the way to tell. `schema.py` documents a null
  token count for both causes, this milestone's own seeded case plants
  a metrics-on turn with no usage beside a metrics-off turn and they
  are the same row here, and `telemetry_sessions` could not
  discriminate anyway: it counts sessions by the day they opened while
  token rows count turns by the day they were spoken, and it carries no
  agent. Fixed by stating the ambiguity instead: the declaration
  matrix and the per-view sentences now say a missing measurement means
  telemetry-off or absent provider usage, indistinguishably, and the
  shared reference gained a third limit saying a measured count is a
  denominator and never a diagnosis. `telemetry_sessions` is described
  as same-day session-level context throughout. The page was
  regenerated through the generator, the docgen drift test carries a
  new pin on the corrected sentences with the two retired claims
  asserted absent, and the seeded case's docstring says what the pair
  of rows is evidence of.

## M2: wire response latency from a capture

PR #448.

### What landed

`scripts/wire_latency.py` reads a directory of session captures and
reports, per turn, the interval between the end of user speech on
channel 0 and the first reply audio paced out on channel 1. Stdlib
only: `wave` a frame at a time, `array` for the samples, and the RMS
arithmetic in Python, so `python3 scripts/wire_latency.py <directory>`
is the whole invocation and no environment has to be prepared. That
choice is stated in the usage block rather than left to the reader.

The metric is the decided shape (a). Every run prints two standing
sentences under the numbers: the precision sentence, saying the answer
is read in 20 ms frames and reported to a tenth of a second and so
answers 800 ms or 2.5 s and never a count of milliseconds; and the
exclusion sentence, saying the number excludes downlink transport and
device playback and is therefore what the server contributed rather
than what the room waited. The word "perceived" appears nowhere in the
script, and a unit case asserts its absence from the output.

Speech end is the end of the last channel-0 frame carrying speech
energy at or before the endpointer's decision, where the decision comes
from the `vad` samples (a run of samples counting speech while
listening, ending where `speech_ms` returns to zero, where the samples
stop, or after a gap). `heard.duration_s` bounds the pairing rather
than timing it: a speech end outside `[heard - duration - slack, heard
+ slack]` reports no number. What counts as sound is a channel's own
20th-percentile floor plus 12 dB, never under an absolute -60 dBFS, so
a noisy room and a digitally silent simulator capture are both read on
their own terms without a codec's dither being promoted to speech.

Seven closed reasons cover every turn that cannot be measured:
`nothing_transcribed`, `no_transcription_event`, `no_speech_energy`,
`outside_heard_bound`, `reply_already_playing` (a barge-in over audio
already in flight), `filler_audio_first` and `no_reply_audio`. Each is
a module-level literal, and a unit case pins the closed set against the
source so a reason can never be built from what was read.

The refusal boundary follows `upstream_watch.py`: a `_FixedMessageParser`
that never repeats what was typed, one `Refusal` per failure class
(unreadable files, a recording in another format, an empty recording,
an unfinished capture, a decision track that is not UTF-8, a malformed
track, a malformed manifest, timings that do not make sense), raised
after its `except` arm rather than inside it, and `main` as the one
exception boundary so no traceback ever prints the locals. Exit codes
are `check_doc_links.py`'s: 0, 1 for a capture that could not be read
or a directory with none, 2 for a bad invocation.

Tests: 23 unit cases over captures built sample by sample, run as a
subprocess with both streams read whole, and one integration case that
records a real session (a server with capture enabled, one simulator
conversation through the `simulate` fixture) and runs the script over
the triplet. It is the repository's first capture-producing test.

### Deviations

- **Captures are numbered, not named, in the output.** The plan asks
  for output that never echoes stray values; the no-leak lens asks that
  hostile filenames never reach a stream. A capture's filename is its
  session id, and the file is a recording of somebody's room that this
  tool was merely handed, so the report says "capture 1" in the
  directory's sorted order and leaves identity where it was read from.
  The cost is real (an operator maps the number by listing the
  directory in the same order) and is stated in the docstring.

- **The measured interval starts at the energy fall, not at the
  endpointer's decision.** The plan specifies the fall corroborated by
  the `vad` samples, and this is what corroboration turned out to mean
  in code: the samples give the window, the envelope gives the instant
  inside it. The consequence is deliberate and worth stating, because
  it makes the number bigger: the endpointer's trailing silence sits
  inside the measured interval, which is right, since the user waited
  through it.

- **A partial line in the decision track is skipped, not refused.** A
  track is written by a live session that can be killed mid-write, and
  one line missing its `t_ms` is not a reason to refuse a recording
  somebody went out to make. A line that is not JSON at all is still a
  malformed track and still a refusal.

### Discoveries

- **`turn_started` already stamps the end of user speech**, in its own
  `speech_ms` field and, per its catalog note, at the instant the user
  stopped. It is not used: the plan specifies the energy fall, and the
  event's stamp is the endpointer's decision rather than the acoustic
  end, which is exactly the difference the fall exists to capture. It
  is recorded here as the obvious cross-check if a later reading ever
  disagrees with this one.

- **A simulator capture's timeline is arrival-paced, not
  realtime.** The sdk sends a second of tone as fast as the socket
  takes it, and the capture places audio by when it arrived, so the
  mic channel can still be receiving frames of an utterance the
  endpointer already ended: in a recorded run, `heard.duration_s` was
  1.74 s over 0.57 s of wall clock. This is why the transcription
  bound is one-sided (the speech end may not sit after the transcript,
  and may not sit further back than the utterance's own duration) and
  why the integration case asserts the shape of a measurement rather
  than its value.

- **The end-to-end number on mock providers is 0.0 s**, correctly: the
  mock LLM answers in 26 ms and the mock TTS synthesizes immediately,
  so the whole wire path fits inside one reported tenth of a second.
  The integration case therefore matches the line's shape rather than
  a figure, and the arithmetic that would catch a regression lives in
  the unit lane.

### PR review round

External review of PR #448: one P1 and three others, mergeable after
fixes. All four adopted, one commit each.

- **P1: hostile JSON escaped the refusal boundary.** Both decoders
  caught `json.JSONDecodeError` only, and that is not the whole of what
  the parser raises: an integer past the interpreter's 4300-digit limit
  raises a plain `ValueError` and nesting past the recursion limit
  raises `RecursionError`. Neither was caught anywhere, and both
  messages quote the document they choked on, so a capture with either
  in it printed a traceback whose locals are that capture. Fixed as
  prescribed: both decoders catch all three, and a last door under the
  whole of one capture's analysis refuses anything still unexpected
  with the generated capture number alone. Four sentinel cases over
  both files pin it, checking both streams. Verified against the live
  parser first, so the cases are load-bearing rather than decorative:
  `9` times twenty thousand raises `ValueError` and two hundred
  thousand brackets raise `RecursionError`, neither of them a
  `JSONDecodeError`.

- **P2: two turns a fraction of a second apart merged into one.** The
  splitter needed a non-speaking sample or a second of silence, and
  `turntaking.finish_utterance` emits neither: it reads the endpointer
  and resets it in the same breath, so the next frame emits a sample
  already counting the speech after it. A user answering a short reply
  straight away left two positive samples 200 ms apart with no zero
  between them, read as one utterance, both turns lost. Fixed by the
  reviewer's first option: a `heard` or `nothing_heard` between two
  positive samples ends the run, which the capture's own track carries.
  The new fixture is the producer's real shape and was confirmed red
  against the previous script (one turn reported, the first one gone).

- **P2: the threshold could sit above the signal.** The floor was the
  channel's own twentieth percentile plus twelve dB, which assumes the
  channel is mostly quiet; a reply filling most of a recording is its
  own percentile, and the threshold landed above it, so a capture of
  one long answer reported `no_reply_audio`. Of the two options
  offered, the known-quiet region was taken rather than a bare absolute
  floor, because a field capture's floor is the room's and worth
  measuring: the floor now comes from the frames before the endpointer
  first counted speech, the one stretch of a recording that neither the
  user nor an answer to them can be in, and both channels are read
  against their own floor in it. The absolute floor stays as the lower
  guard, and a second guard keeps the threshold at least six dB under
  the loudest frame the channel carries, so a capture that starts
  mid-reply cannot set a threshold nothing could rise above. The
  fixture is a reply filling 83% of the recording, also confirmed red
  against the previous script.

- **P3: refusal cases read one stream.** Several read only the stream
  they expected the failure on, which cannot see content republished on
  the other. One helper, `quiet_about`, now reads stdout and stderr
  together and takes the values that must appear in neither, and every
  subprocess result in the suite goes through it.
