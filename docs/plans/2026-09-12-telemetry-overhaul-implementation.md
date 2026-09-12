# Telemetry overhaul: implementation

Companion to [`2026-09-12-telemetry-overhaul.md`](2026-09-12-telemetry-overhaul.md),
one section per milestone, appended in the same change that ticks the
milestone checklist. It records deviations from the plan, resolutions
of the plan's open questions, and discoveries.

## M1: the ADR amendment

Documentation only, and deliberately first: the milestone settles the
ladder's shape so that M5 and the two interleaved artifact issues are
built against a recorded rule rather than against each other. No code
moves, no flag is added, and nothing an operator can observe changes,
so there is no changelog fragment; the PR body says so rather than
leaving the absence to be noticed.

### What landed

| Piece | Where |
| --- | --- |
| The fourth amendment | `docs/adr/2026-08-15-content-and-telemetry-are-separate-surfaces.md`: three classes under one `export_` prefix with `attach_` decommissioned, the family rule stated once, artifacts riding their class and the announced widening that follows, the superset note, the fidelity boundary of `export_llm_input` and its cost, that class's local surface with the full retention answer and the crash consequence, the wire-fidelity tier dissolved, and fine-grained control left with #393 |
| The tier table | `docs/architecture/observability-surfaces.md`: two rows, metadata as the prerequisite and content by class, with the family's shared terms in the second row's terms column, the no-op arm first among them |
| The class table | the same section: one row per class, what leaves, the flag, and whether it has landed, with `export_llm_input` marked unlanded and attributed to this plan's fifth milestone |
| The two class properties | beside the tables: a class gaining an artifact widens an already-on flag and is announced, and a wider class may contain what a narrower one does |
| The two falsified sentences | the same page's contents bullet ("the three tiers content may leave this deployment on") and the exported-transcripts row's "wire fidelity is a future decision of its own" |

### Deviations from the plan

None. Every item the plan's M1 lists is in the table above, and the
ladder section kept its `#the-export-ladder` anchor, which the record
links and the link checker verifies. One addition was written and
then taken out by the review round below, which is recorded there and
in the discovery under it rather than as a deviation, since nothing
of it survives in the tree.

### Resolutions the plan left to this milestone

None outstanding. The plan resolved the wire-fidelity question, the
third class's local surface and retention answer, and the fidelity
boundary in its own open-questions sections, and the amendment records
those resolutions rather than taking them again. The one judgement
this milestone made on its own, a clause pointing forward from the
superseded amendment, the review round rejected and this branch
reverted; the discovery below says why it was written and which rule
it broke.

### Discoveries

- **The sentence the dissolution falsifies was one of two.** The
  exported-transcripts surface row said wire fidelity was a future
  decision of its own, and it now names the class that answers it. The
  contents bullet at the top of the same page promised three tiers as
  well, which the sweep found and the same commit fixed. Both are on
  the page the record keeps its tables on, which is the page that had
  to move.
- **The other "three tiers" in this repository are a different
  subject, and none of them moved.** The sweep over `docs/` and
  `vinga-server/` found the phrase in the configuration descriptors'
  three tiers (`config/entities.py` and its plan), in the dependency
  tiers the closure test walks (`tests/support/tiers.py`), and in the
  turn-taking split's three named files. None of them is an export
  ladder, and confusing them would have been a rename in search of a
  word rather than a correction.
- **The command-spellings census was already stale at the branch
  head, and not from this milestone.** The census test failed on one
  missing row, and the row is a line-wrapped fragment of a sentence in
  this plan's own opening paragraph: the sweep reads every tracked
  file line by line, and ordinary prose naming the program and a noun
  looks exactly like an invocation. It was confirmed to predate the
  milestone by restoring the tree to the branch head (the two plan
  files copied aside first, per the repository's restore rule) and
  re-running the test, which failed identically. So the census has
  been stale since the plan was committed. Regenerated with its own
  generator rather than hand-edited, in a commit of its own; the row
  is classified historical, because `docs/plans/` is a historical
  path, and nothing is asked to respell. The row is described here
  and not reproduced, which is the trap #495's own M1 recorded:
  quoting a census row into a tracked page adds one.
- **A superseded amendment may not be told that it was superseded.**
  The first draft of this milestone put one clause into the third
  amendment's tier bullet, saying its third tier had not survived the
  day and where the decision that replaced it was. The reasoning was
  navigational: both amendments carry the same date, so a reader who
  opened the record at the third one would meet "Three tiers" and
  "deliberately unspecced" with only the ordering to correct them.
  The review round rejected it and is right. The authority taxonomy
  says of the decisions directory that a record is superseded by a
  later one and never edited into agreement, and a clause describing
  what a table contains "now" is exactly such an edit however light it
  reads. The clause is reverted whole. Current policy is the fourth
  amendment's and the maintained map's, and the map links both
  amendments, which is where navigation belongs: an index may point
  at a record, a record may not be updated to point at its successor.
  Worth knowing before the fifth amendment, because the same
  temptation arrives with it.
- **Dated execution records keep their spelling, and two of them
  carry the dissolved tier.** The transcript-export plan describes the
  ladder it was written against, and the folded changelog describes
  the day it landed. Both are dated execution records under the
  authority taxonomy, evidence about a change rather than current
  guidance, so neither is rewritten. What a reader follows from either
  is the record, which now says what the ladder is.

### Verification

- [x] `python3 scripts/check_doc_links.py .`: checked 239 files, 0
      failures. This is the check the anchor rule rests on: the record
      links the ladder section by anchor, and the map links the new
      amendment by anchor.
- [x] `uv run pytest tests/unit/test_command_spellings.py -q` from
      `vinga-server/`: 1 failed, 51 passed on the first run, on a row
      that was already stale at the branch head (see the discovery
      above). Regenerated with the module's own generator
      (`uv run python -m tests.unit.test_command_spellings`), which
      added exactly one historical row and moved nothing else; the
      file's suite is green afterwards, 52 passed.
- [ ] Anything executable. This milestone changes no code, so there is
      no lint, unit or integration lane that can observe it; the two
      checks above are the whole of what a documentation change can be
      held to.
- [ ] Anything on a board. No protocol, no firmware-visible behavior
      and no device path moves here, so there is nothing a device
      checkpoint could falsify.

### PR review round, PR #505

External review: codex CLI 0.154.0, model gpt-5.6-terra, read-only
sandbox, 2026-09-12, runtime 6m50s, reviewing origin/main...6cd4ce36.
Verdict as received: **mergeable after the listed fixes**. Two
findings, both adopted, each fixed in a commit of its own.

1. **P2: the family rule contradicts the landed flags' no-op
   ordering.** The rule said every content flag requires
   `server.telemetry.enabled` and is refused under a narrower
   `server.data_boundary`, but `build_capture_upload` returns its
   documented no-op before either check when `server.capture` is
   absent or off, and `build_transcript_export` does the same when
   conversations are absent, off, or storing no text. The generated
   field prose promises those no-ops. Fix: state the rule
   conditionally, preserving the established no-op precedence.

   *Resolution.* Adopted, and confirmed against both builders: each
   tests its class's own switch first, logs once at startup when the
   flag is on with nothing to export, and returns. The rule now
   carries that arm and carries it first, in the record's family-rule
   bullet and in the map's tier table alike, with the telemetry
   prerequisite and the boundary refusal behind it. The reason is
   stated rather than just the ordering: a deployment that keeps
   nothing has nothing to export, which is a choice rather than a
   misconfiguration. Both places also now say that the arm cannot
   arise for `export_llm_input`, whose local surface no second switch
   governs, since M5 is the reader most likely to infer one.

2. **P2: the forward clause mutates an immutable decision record
   while claiming not to.** The clause appended current-state text to
   the third amendment, changing what that record says its table now
   contains, and the authority taxonomy says a record is superseded
   by a later one and never edited into agreement. Fix: remove it,
   and let the fourth amendment and the maintained map carry current
   policy.

   *Resolution.* Adopted, reverted whole, and recorded as a discovery
   above rather than as a deviation, since nothing of it survives in
   the tree. The navigation it was reaching for exists already: the
   map links both amendments, and an index may point at a record where
   the record may not be updated to point at its successor.
