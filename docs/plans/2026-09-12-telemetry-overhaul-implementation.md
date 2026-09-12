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
## M2: trace completeness

Four facts a trace could not carry, added to the module that already
owns the fold. No configuration key moves, no event is declared or
changed, and nothing an operator switches on or off appears: what
changes is what an already-exporting deployment's spans say.

### What landed

| Piece | Where |
| --- | --- |
| `vinga.device.name` on every span | `telemetry.py`: the constant, an entry in `SESSION_ATTRIBUTES` and one in `CONTEXT_ATTRIBUTES`, the optional name on the retained `_Exported` record, and `_named()` as the one absence rule the three post-close writers share |
| The turn span's identity | the same file: `_open_turn` now merges the retained identity ahead of its own table, which is what the plan's enumeration assumed it already did (see the deviation below) |
| The tool span | `TOOL_SPAN`, `TOOL_ATTRIBUTES`, `GEN_AI_OPERATION`/`EXECUTE_TOOL` and `_tool_span`, registered in the fold map under `tool_call`, which therefore produces a span and no span event |
| The prompt's provenance | `PROMPT_PREFIX`, `PROMPT_ATTRIBUTES`, `_prompt_attributes()`, `_SessionTrace.prompts`, the `_prompt_assembled` fold, the `PENDING_PROMPTS` hold and its claim in `_open_session`, and the stamp in `_open_turn` |
| The after-close names | `AFTER_THE_CLOSE_ATTRIBUTES`, read by `_after_the_close` in place of the shared `_event_attributes` |
| The map's row | `docs/architecture/observability-surfaces.md`: the exported-traces row names the tool call among what a turn holds |
| The fragment | `changelog.d/502-trace-completeness.md` (### Added) |
| The cases | `tests/unit/test_telemetry.py` (the name enumeration, the provenance, the after-close names) and `tests/unit/test_telemetry_spans.py` (the tool span), with `open_session(device_name=...)`, `assemble_prompt(agent=...)`, `call_tool` and the transcript-outcome emitter added to `tests/support/telemetry.py` |

### Deviations from the plan

Three, and the first two are corrections to the plan's own text
rather than departures from its intent.

- **The plan's span-constructor enumeration is wrong about
  `_open_turn`.** Its table says the turn span gets the device name
  from "the retained identity (`CONTEXT_ATTRIBUTES`)". It did not:
  `_open_turn` built its attributes from `TURN_ATTRIBUTES` off the
  `turn_started` payload, which names the session and the device and
  knows nothing about what the board is CALLED, plus the agent's
  provider entries. The retained identity reached the four stage spans
  through `_context` and never reached the turn. Found by the
  enumeration case failing on the turn span alone after the tables
  moved, which is what that case is for. The turn span now merges
  `trace.identity` ahead of its own table; the two facts it did carry
  arrive under the same names with the same values, so this widens
  what the span says without changing anything it said.
- **The after-close table has five entries, not three.** The plan
  names `elapsed_ms`, `audio_bytes` and `manifest_bytes`. But
  `_attributes` iterates the TABLE rather than the payload, so a key
  left out of it is not exported at all, and a table of three would
  have deleted `reason` from both failure spans and `turns` from the
  transcript one. `reason` is the only fact a failed export's span
  carries. So all five fields the four after-close events declare are
  in the table, each under `vinga.export.`, and the two extra
  respellings are named here rather than discovered in review.
- **The tool span carries the retained identity and NOT the provider
  entries.** `_open_playback`, the nearest precedent, takes the full
  `_context`, which would have put what the session opened against on
  every tool span too. A tool call ran on no pipeline stage, so those
  entries say nothing about it, and the plan's own description of the
  span is an enumeration that does not include them. Pinned by a case
  that asserts no `vinga.provider.` attribute is on the span.

### Resolutions the plan left to this milestone

- **What an MCP entry is spelled as.** The plan settles
  `gen_ai.operation.name` and says nothing about the two name fields.
  A builtin's `tool` is the tool's own name, which the GenAI
  conventions have a key for, so it lands on `gen_ai.tool.name`. An
  MCP call's `entry` is deliberately NOT that: what the variant may
  say is the entry an operator configured and never the far side's own
  tool name, so it keeps `vinga.tool.entry`. That is the same split
  the round span already makes, where `model` is the conventions' and
  the configured provider entry is vinga's word.
- **The tool span's name is `tool`.** Not the tool's own name: a span
  name is what a backend groups a list by, and one per configured tool
  would make that list as long as the deployment's tool table.
- **The after-close prefix is `vinga.export.`.** One prefix for both
  pairs, because a recording's trip to the backend and a page of
  transcripts are the same kind of thing under this ladder, and what
  tells the two spans apart is their own names.
- **The held prompt is an emission rather than an (epoch, emission)
  pair.** The capture hold keeps pairs because a server event is
  stamped on the server clock and the conversion belongs where the
  clock is known. `prompt_assembled` is a SESSION event and the
  session clock's offset is one number for the process once it exists,
  so the stamp resolves to the same instant whenever it is read.

### Discoveries

- **The pre-open ordering is exactly as the plan's review described
  it**, confirmed in the worktree before anything was built for it:
  `runtime/pipeline.py` line 851 emits `prompt_assembled` through
  `_activate_agent` inside `PipelineRuntime.__init__`, and
  `device/session.py` builds that runtime at line 497 against a
  `SessionOpen` emitted at line 565. The case that drives the
  production ordering fails against the pre-milestone fold for the
  reason the plan gives, the event reaching no trace at all.
- **The claim is folded through `_prompt_assembled` itself** rather
  than beside it in `_open_session`, so the retention rule and the
  span event are written once and the claim changes only whether there
  is a trace to place them on. The capture hold's own claim cannot do
  this, because its held events are replayed with a stamp the fold
  does not recompute.
- **`prompt_assembled` keeps its span event.** Only `tool_call` loses
  one, and only because the plan decides that for it: when a prompt was
  assembled is a fact about this session's timeline, and the existing
  case pinning the mapping's canonical JSON on that span event is the
  proof it still lands.
- **The fold map is fourteen names now**, up from twelve, and the two
  comments that counted them (the module's own and the stage suite's
  docstring) moved with it.

### Verification

- [x] `uv run ruff check .`: `All checks passed!`
- [x] `uv run pytest tests/unit -q`: `7174 passed, 19 skipped in 789.41s`,
      against the 7154 of the last recorded run, which is this
      milestone's eighteen cases and the two the support module's own
      helpers gained.
- [x] `uv run pytest tests/unit/test_command_spellings.py -q`:
      `52 passed`, the manifest unchanged by this milestone.
- [x] `python3 scripts/check_doc_links.py .`:
      `checked 239 files, 0 failures`.
- [x] `uv run pytest tests/integration -q`: `1 failed, 340 passed` on
      the first run, then `5 passed` for the repaired file. The failure
      is recorded rather than smoothed over, because it is the lane
      doing its job: `test_the_upload_outcome_reaches_the_collector_too`
      asserted `held["audio_bytes"]` on the outcome SPAN, which is
      exactly the bare spelling this milestone replaced, so the rename
      landed with one pin still naming the old attribute. The pin now
      reads the three `vinga.export.` names and says in a comment why
      the bare ones are gone. Nothing of the module changed to make it
      pass. The full lane is re-run by CI on the pull request rather
      than a second time here, and that run is the one the PR's box is
      checked against.
- [x] The M2 live gate, run and recorded in the section below.
- [ ] Anything on a board. No protocol, no firmware-visible behavior
      and no device path moves in this milestone.

### The live gate

Run 2026-09-12 against the Langfuse project this repository develops
against, on revision `9883315f`. One real conversation on real
providers: `openai` ASR (`whisper-1`), `openai_compatible` LLM
(`gpt-4o-mini` on api.openai.com), `openai` TTS (`tts-1`), Silero, and
the lane's own stdio MCP server, driven through the xiaozhi-sdk
simulator with the question spoken by a real voice. The conversation
held: the ear heard "Ask the tool for the secret word, then tell me
what it is.", the model called the MCP tool, and the voice said "The
secret word is 'rhubarb.'" Session `03552ae435e54191ab768fc90452d8f4`.

The rig deviates from the plan's in one way, recorded because it is a
trap rather than a choice: the lane synthesizes its spoken question
with Piper, and the `piper-tts` wheel in this environment carries an
espeak-ng data path from the machine that built it and cannot
synthesize at all. The question was spoken by the vendor's own voice
instead. What the gate needs is real audio of real speech, so which
voice says it is incidental.

**The tool call arrives as a TOOL observation, from the conventions'
attribute alone.** This was the gate's open question and the answer is
the plan's first choice: no `langfuse.observation.type` is needed and
none is added.

```json
{"id": "62d5d8f1c05f4ba5", "name": "tool", "type": "TOOL",
 "metadata": {"attributes.gen_ai.operation.name": "execute_tool",
              "attributes.vinga.tool.entry": "secrets",
              "attributes.vinga.tool.source": "mcp",
              "attributes.vinga.tool.is_error": false,
              "attributes.vinga.agent": "assistant"}}
```

The naming policy survives the trip: an MCP call names the entry an
operator configured (`secrets`) and never the far side's tool name.

**The flattened prompt sources arrive as metadata on the turn span**,
one numeric field per provenance token, with the total beside them:
`"attributes.vinga.prompt.sources.persona": 203` and
`"attributes.vinga.prompt.characters": 203`. Numbers rather than a
quoted blob, which is what the flattening was for.

**The after-close span carries the `vinga.export.` names**:
`"attributes.vinga.export.turns": 1` and
`"attributes.vinga.export.elapsed_ms": 344` on `transcripts_exported`.

**An unnamed board contributes no attribute rather than a null.** The
turn span carries `attributes.vinga.device.id` and no
`vinga.device.name` at all. Only the ABSENCE half is gated live, and
the reason is worth recording: this lane serves from a `Config` object
while the device record lives in the domain database, which has no
agents in it here, so `claim_device` refuses and no board in this lane
can have a name. The presence half stays pinned by the unit lane
against a `session_open` payload that carries one.

**One thing the gate saw that is not this milestone's**, recorded
because it is [#506](https://github.com/rafacm/vinga/issues/506)
confirmed from the outside: the turn's trace holds `turn`, `asr`, two
`llm` generations, the new `tool` and `tts_stream` and `playback`,
while `transcript` and `transcripts_exported` hang off the SESSION
span on a different trace. A reader of the turn trace gets the timings
and not a word of what was said, which is exactly what that issue
reports, and what M4a plus #506 are sequenced to fix.


## M3: cost accounting

One declared field, two table entries, and the half the plan review
forced: the procedure an operator follows to turn usage into money,
because the server never writes a price. What changes for a deployment
is that all three conversation stages report what they were given
instead of one, and that a documented set of backend model definitions
can price two of them.

### What landed

| Piece | Where |
| --- | --- |
| `characters` on the synthesis event | `events/catalog.py`: a declared `Count` on `SentenceSynthesized`, with the note saying it is the length of the sentence handed to the voice and never a byte of it |
| The measurement at the emit site | `events/assembly.py` `sentence_synthesized` takes the number, and `runtime/pipeline.py` passes `len(sentence)` from `_speak_after`, which is where the string already is; `_sentence_synthesized` gains the parameter and no access to the text |
| The usage attributes | `telemetry.py`: `ASR_USAGE` and `TTS_USAGE` beside the stage tables, `duration_s` exported under its vinga name AND `gen_ai.usage.input_seconds`, and `characters` under `gen_ai.usage.input_characters` |
| The events reference | `docs/reference/events.md`, regenerated with `uv run vinga-server events reference` |
| The operator procedure | `vinga-server/README.md`, a new "What a conversation cost" section between the capture and conversation-store ones, plus its bullet in the page index |
| The map's row | `docs/architecture/observability-surfaces.md`: the exported-traces row says each stage reports what it was given, in its own unit, and that the cost is the backend's to compute |
| The fragment | `changelog.d/502-usage-accounting.md` (### Added) |
| The cases | `tests/unit/test_event_assembly.py` (the shape), `tests/unit/test_turn_lifecycle.py` (the emit site, driven through a real reply), `tests/unit/test_telemetry_spans.py` (both usage attributes and the absence), with `characters` added to `synthesize` in `tests/support/telemetry.py` and to the recorded payload in `tests/unit/test_event_baseline.py` |

### Deviations from the plan

One, and it is a widening rather than a departure.

- **The ASR usage attribute rides the table entry `duration_s`
  already has, so every ASR outcome that measured the audio reports
  it.** The plan and the brief both say the seconds come from
  `heard.duration_s`. `ASR_ATTRIBUTES` is one table for all four ASR
  ends, and `_attributes` already exports one value under several
  names, so spelling the entry as a pair gives `nothing_heard` and
  `transcription_abandoned` the usage too. That is the honest answer
  rather than an accident: the ear was given that many seconds of audio
  whatever came back from it, and a vendor bills for the call that
  returned an empty transcript. A second code path that exported the
  seconds only for `heard` would have been a second home for one fact
  and would have under-reported what a deployment was charged.

### Resolutions the plan left to this milestone

- **`characters` is required rather than absent-able.** Every emit
  site holds the sentence it synthesized, so a missing count would mean
  a caller that forgot rather than a measurement that could not be
  taken, and the catalog is where that distinction is declared.
- **The field sits between `index` and `stream_ms`.** It is a fact
  about the sentence, so it goes with the other one, and the two
  latencies stay together after it.
- **The TTS characters get no vinga spelling of their own.** The ASR
  seconds keep `vinga.asr.duration_s` because that name was already
  exported and read; the count is new and nothing read it before, so
  one name is enough and a second would be the same fact twice.
- **Where the README section goes and what it is called.** "What a
  conversation cost", between "Capturing a session" and "The
  conversation store", which puts it in the run of operator sections
  the plan names and next to the other one that talks to a telemetry
  backend.

### Discoveries

- **A failed transcription carries no `duration_s` at all**, which is
  what makes the absence case real rather than synthetic. The field is
  declared `carried=False` on `ProviderFailed`: it is rendered into the
  sentence the log line prints and never put in the payload. So the
  span for a failed ASR call reports no usage rather than zero seconds,
  and the existing comment on `ASR_ATTRIBUTES` already said as much,
  that `duration_s` is on three of the four outcomes.
- **That case passes against the pre-milestone code**, because it is an
  absence assertion, and it was proved by mutation instead of by
  watching it fail: `attributes.setdefault(ASR_USAGE, 0.0)` in the ASR
  fold makes it fail, and it passes again with the mutation reverted.
  Recorded because "written to fail first" cannot be honestly claimed
  for it.
- **Three closed-set pins moved with the tables.** The two quartet
  cases and the one about an outcome that names no ear each assert the
  exact set of foreign-prefixed keys on a span, so a usage attribute is
  exactly the kind of arrival they exist to catch. They subtract the
  new names by name rather than by loosening to a prefix match, which
  is the property that makes them worth keeping.
- **The unit lane run under CI's own distribution fails here for
  reasons that are not this milestone's.** `-n auto --dist loadfile`
  produced database errors across `test_memory_schema.py`,
  `test_db_open.py`, `test_session_device_location.py` and others, and
  every one of those files passes on its own and in a serial run. The
  compose Postgres this worktree reaches is shared with another session
  in this repository, so the parallel lane contends with it. Recorded
  as an environment fact, not as a result.
- **The published pricing URL has moved.** `platform.openai.com/docs/pricing`
  answers 301 to `developers.openai.com/api/docs/pricing`, and the
  README cites the destination so a reader does not follow a redirect
  to find out whether the price is still there.

### Verification

- [x] `uv run ruff check .`: `All checks passed!`
- [x] `uv run mypy` (the events package's strict lane, which this
      milestone's new field is inside): `Success: no issues found in 5
      source files`.
- [x] `uv run pytest tests/unit -q`: `7179 passed, 19 skipped in
      769.98s`, against the 7174 of M2's recorded run, which is this
      milestone's five cases.
- [x] `uv run pytest tests/unit/test_command_spellings.py -q`:
      `52 passed`, the manifest unchanged by this milestone's
      documentation.
- [x] The events reference drift check
      (`uv run pytest tests/unit/test_event_docs.py tests/unit/test_event_baseline.py -q`):
      `30 passed`, after regenerating with the generator.
- [x] `python3 scripts/check_doc_links.py .`:
      `checked 239 files, 0 failures`.
- [x] `python3 scripts/fold_changelog.py check .`:
      `checked 2 fragments, 0 failures`.
- [x] `uv run pytest tests/integration -q`: `341 passed in 483.49s`.
- [ ] The M3 live gate, which is the section below. It belongs to
      whoever holds the backend's credentials: this milestone must not
      create a model definition in anyone's project, and did not.
- [ ] Anything on a board. No protocol, no firmware-visible behavior
      and no device path moves in this milestone.

### The live gate

Not run here, and deliberately: the gate enters model definitions in a
real backend and then reads a cost query back, which is a write to a
third-party system and needs credentials this milestone declines to
acquire. What it asks, in the plan's own order:

- does an unrecognized `gen_ai.usage.*` key reach `usageDetails`, or is
  it dropped, in which case the recorded fallback is
  `langfuse.observation.usage_details` carrying canonical JSON beside
  the conventions' name and never instead of it;
- do the ASR and TTS observations arrive as `GENERATION`;
- does a definition entered through `createModel` price them;
- and the issue's stated acceptance, qualified as the plan settles it:
  against a backend with the documented definitions entered, the
  per-session per-stage cost query returns nonzero rows for `asr`,
  `llm` and `tts_stream`.

The four definitions to enter are the README's table, which is written
so the gate can be run from it without reading this section.
