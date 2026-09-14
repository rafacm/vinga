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

### The external review round

Three findings, two P1, verdict not mergeable; the round is on the pull
request with the resolutions as replies. What each one changed:

- **The ASR usage was the utterance's length.** The first deviation
  above, and the one commit of this milestone that changes a
  measurement rather than a name.
- **The live gate had not run.** It has now, by the maintainer, and it
  is the section below. It made the fallback attribute necessary and
  moved the ASR unit to milliseconds.
- **The pricing procedure omitted the generation stage** while the
  acceptance claim covered three. The gate answered it without a price:
  the backend already knows well-known vendor models, so the section
  says how to check and what an unknown model needs.

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
| What the ear was sent | `providers/base.py`: `AsrResult.submitted_ms`, how much audio a call actually put on the wire; `providers/openai_asr.py` counts it per request, with `_retry_without_prompt` answering whether it re-sent; `events/catalog.py` declares `submitted_ms` on `heard` and `nothing_heard`, and `runtime/pipeline.py` passes it at both |
| The usage attributes | `telemetry.py`: `ASR_USAGE` (`gen_ai.usage.input_milliseconds`, off `submitted_ms`) and `TTS_USAGE` (`gen_ai.usage.input_characters`, off `characters`) beside the stage tables; `vinga.asr.duration_s` unchanged and deliberately not the usage |
| The spelling a backend can price | the same file: `OBSERVATION_USAGE_DETAILS` and `_priceable()`, one string of canonical JSON `{"input": N}` beside the conventions' name on both stage spans, whole numbers only |
| The events reference | `docs/reference/events.md`, regenerated with `uv run vinga-server events reference` |
| The operator procedure | `vinga-server/README.md`, a new "What a conversation cost" section between the capture and conversation-store ones, plus its bullet in the page index: what each stage reports, the generation stage that usually needs no definition and how to check, the four models with a published list price as pattern, unit and converted rate, the request that enters one, what a backend with none shows, and the models that deliberately get none |
| The map's row | `docs/architecture/observability-surfaces.md`: the exported-traces row says each stage reports what it was given, in its own unit, and that the cost is the backend's to compute |
| The fragment | `changelog.d/502-usage-accounting.md` (### Added) |
| The cases | `tests/unit/test_event_assembly.py` (the shape), `tests/unit/test_turn_lifecycle.py` (the emit site, driven through a real reply), `tests/unit/test_providers_openai_asr.py` (the floor, the retry and the ordinary call), `tests/unit/test_telemetry_spans.py` (both usage attributes, the priced spelling, and the two absences), with `characters` and `submitted_ms` added to `synthesize`, `hear` and `hear_nothing` in `tests/support/telemetry.py` and to the recorded payload in `tests/unit/test_event_baseline.py` |

### Deviations from the plan

Two, and both were forced by evidence the plan did not have.

- **The ASR usage is not `heard.duration_s`, and the plan said it
  was.** The plan's own sentence is "`gen_ai.usage.input_seconds` on
  the ASR span" from the duration the utterance carries, and the review
  round is right that this is a wrong billing number rather than an
  approximate one. The OpenAI adapter parts company with the utterance
  in both directions: a clip under the endpoint's floor returns an
  empty transcript having made no request at all, and a clip whose
  transcript comes back as the prompt is submitted a second time by the
  echo guard's retry. So a new declared measurement crosses the ASR
  seam (`AsrResult.submitted_ms`), the catalog declares it, and the
  span exports that. `vinga.asr.duration_s` is unchanged, which is the
  deviation's own point: what the user said and what a provider was
  billed for are two facts, and this milestone is where they separate.
  The first draft of this milestone instead spelled the `duration_s`
  table entry as a pair of names, which made the wrong number arrive
  under two of them.
- **The unit is milliseconds, not seconds.** The live gate found a
  non-integer usage value dropped outright by the backend on both
  ingestion paths, so a fractional measurement cannot be priced at all;
  whole seconds are then the coarsest integer available and would
  overstate a 0.4 second utterance by 150%. The attribute is named for
  the unit it carries. Authorized by the plan, which says the gate
  decides this and that the answer is recorded here with the
  observation JSON that shows it.

### Resolutions the plan left to this milestone

- **`characters` is required rather than absent-able.** Every emit
  site holds the sentence it synthesized, so a missing count would mean
  a caller that forgot rather than a measurement that could not be
  taken, and the catalog is where that distinction is declared.
- **The field sits between `index` and `stream_ms`.** It is a fact
  about the sentence, so it goes with the other one, and the two
  latencies stay together after it.
- **The TTS characters get no vinga spelling of their own**, and
  neither do the ASR milliseconds. Both are new facts nothing read
  before, so one conventions-shaped name is enough; `vinga.asr.duration_s`
  is not a second spelling of the usage but the answer to a different
  question, which is why it stays.
- **The priced spelling is read off the span's attributes rather than
  off the payload.** `_priceable()` takes the dictionary the stage
  table already produced and looks up the key it just wrote, so a value
  the declared-shape gate refused cannot reappear through the second
  spelling and the two names cannot drift apart. Two structures that
  must agree are one structure with a bug pending.
- **A generation gets no priced spelling.** The backend parses and
  prices `gen_ai.usage.input_tokens` and `output_tokens` already, so a
  second key there would be one fact twice for no reader.
- **Where the README section goes and what it is called.** "What a
  conversation cost", between "Capturing a session" and "The
  conversation store", which puts it in the run of operator sections
  the plan names and next to the other one that talks to a telemetry
  backend.
- **The generation stage gets a procedure and no price.** The plan
  asks for a definition per model with a real list price, and the live
  gate showed the backend pricing `gpt-4o-mini` with nothing entered at
  all, so the honest procedure for this stage is how to check whether
  yours is already known and what a model the backend does not know
  needs (two token rates rather than one, and `TOKENS` as the unit).
  No figure is quoted for any model whose published price this
  milestone did not read, which is the same rule the table keeps.

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
  for it. The same was done for the two cases that hold the review
  round's first finding (restoring the clip's length under the floor
  and dropping the retry's second hearing: both failed) and for the
  priced spelling (removing `_priceable` from the ASR fold: it failed).
- **Four of the echo retry's five endings put the clip on the wire a
  second time.** Only the skip above `RETRY_FLOOR_S` sends nothing; the
  deadline timeout, the confirmed echo, the confirmed silence and the
  recovered transcript all submitted it, the timeout included, because
  bytes a cancelled request already wrote are bytes the far side
  received. So the retry reports whether it SENT rather than what it
  concluded: a caller counting by outcome would miss the two endings
  that answer nothing at all, which are the ones a suspicious clip is
  most likely to produce.
- **A zero and an absence are both needed here, and they mean different
  things.** The floor's zero is a measurement (this ear submitted
  nothing); a local engine's absence is the lack of one. A backend
  reading the first prices it at nothing and reading the second knows
  not to price it, and collapsing them would lose whichever fact was
  collapsed into the other.
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
- [x] `uv run pytest tests/unit -q`: `7188 passed, 19 skipped in
      772.27s`, against the 7174 of M2's recorded run: five cases for
      the milestone as first written and nine more for the review
      round's three findings.
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
- [x] `uv run pytest tests/integration -q`: `341 passed in 480.77s`,
      unchanged in count, since nothing this milestone touches is
      driven there: the lane's mock ear reports no usage, which is the
      absence rule working.
- [x] The M3 live gate, run by the maintainer and recorded in the
      section below with the observation JSON. It changed two things in
      this milestone's design, both of which are in the deviations
      above. No model definition was created, updated or deleted by
      this milestone.
- [ ] Anything on a board. No protocol, no firmware-visible behavior
      and no device path moves in this milestone.

### The live gate

Run 2026-09-12 by the maintainer against the Langfuse project this
repository develops against, over three runs, after the milestone's
first pull request had opened. It answered the plan's open question,
and under it found a second thing the plan did not anticipate. Both
changed the design, which is why this section is upstream of two of
this milestone's commits rather than a record of them.

**An unrecognized `gen_ai.usage.*` key reaches `usageDetails` and is
never priced.** The plan's question was whether the key is dropped. It
is not: the suffix is lifted verbatim, which makes the attribute
readable and inert.

```json
{"name": "tts_stream",
 "usageDetails": {"input_characters": 29},
 "costDetails": {},
 "totalCost": null}
```

A model definition prices the keys `input`, `output` and `total` and no
others, so `input_characters` has no rate against it however carefully
the definition is written. **So the fallback the plan named is
required**, and it is added rather than considered:
`langfuse.observation.usage_details` carrying canonical JSON beside the
conventions' name, never instead of it.

**A non-integer usage value is dropped outright, on BOTH paths.** This
is the finding the plan did not anticipate, and it decided a unit. An
ASR stage reporting seconds arrived as
`attributes.gen_ai.usage.input_seconds: 4.08` and produced
`usageDetails: {}`; the same float sent through
`langfuse.observation.usage_details` produced `usageDetails: {}` as
well. Integers work on both. So a fractional measurement cannot be
priced at all, whichever spelling carries it.

**With an integer under the fallback, both stages price exactly.**

```json
{"name": "tts_stream",
 "usageDetails": {"input": 29},
 "costDetails": {"input": 0.000435}}
```

29 x 0.000015 is 0.000435 to the last digit, which is the arithmetic
this milestone exists to make possible; the `asr` observation priced
the same way.

**The LLM stage was priced with no definition entered at all.**
`gpt-4o-mini` came back with `costDetails: {"input": 0.00022335,
"output": 0.000006}`, so the backend ships managed definitions for
well-known vendor models. That answers finding 3 of the review round
without inventing a price, and the README says so.

**What the gate changed, and what it did not.** The ASR usage moves
from seconds to milliseconds and the attribute is named for the unit it
carries (`gen_ai.usage.input_milliseconds`): whole seconds are the
coarsest integer available and would overstate a 0.4 second "ja" by
150%, on exactly the utterances a voice assistant is made of. That is a
deviation from the plan's `input_seconds`, authorized by the plan
itself, which says the gate decides and this section records the answer
with the observation JSON that shows it. What did not change is the
conventions' attribute: it stays on both spans as the vinga-native
spelling a backend that has never heard of this project can read.

**The acceptance criterion, met, and qualified as the plan settles
it.** Against a backend with the documented definitions entered, the
per-session per-stage cost query returns nonzero rows for `asr`, `llm`
and `tts_stream`. One session, every stage priced, each figure the
arithmetic it should be:

```json
{"name": "asr",        "usageDetails": {"input": 4019},
                       "costDetails": {"input": 0.0004019}}
{"name": "llm",        "usageDetails": {"input": 1462, "output": 13},
                       "costDetails": {"total": 0.0002271}}
{"name": "llm",        "usageDetails": {"input": 1489, "output": 9},
                       "costDetails": {"total": 0.00022875}}
{"name": "tts_stream", "usageDetails": {"input": 27},
                       "costDetails": {"input": 0.000405}}
```

4019 milliseconds at 1e-7 is 0.0004019, and 27 characters at 0.000015
is 0.000405. The ear and the voice are priced from this project's own
definitions; the generation stage is priced by the backend's managed
one, which is the subsection above demonstrated rather than asserted.

**How the wrong unit was corrected, which is worth recording.** Two
definitions were entered before the gate proved the integer rule, in
`SECONDS`, and the API refuses a second definition under an existing
model NAME. It does not refuse a second definition under an existing
match PATTERN, and a definition carries a `startDate`, which is the
backend's own mechanism for a price that changes on a date. So the
corrected one was added beside the superseded one under a display name
of its own and a start date, and the gate above is what proves it takes
precedence: the `asr` row is priced per millisecond and not per second.
Nothing was deleted and nothing was overwritten, which also means the
observations recorded under the old rate keep the cost they were
ingested with, and that is the honest history rather than a number
rewritten after the fact.

**What this milestone did not do.** It created no definition and it
deleted none: the four in that project are the maintainer's, entered by
hand outside this branch, and pricing stays the operator's, which is
the whole of what the plan decided here. A deployment that enters none
of them sees usage and no cost, which the README says where an operator
will look.

## M4a: post-close retention and pinning

The plan left this milestone's join key deliberately unsettled, named
two candidates and required M4a to prove one before building. Both are
dead, and what killed the second is a fact about this codebase that
outlives the key.

### The measurement, which came before any code

**Candidate B, the per-session `t_ms` offset both sides already carry,
is dead: the two sides stamp different instants.** `turn_started` is
stamped `utterance.ended_at`, the moment the user stopped speaking. The
store's `t_ms` derives from `heard_at`, the `heard` emission, which
lands after the ASR stage RETURNS. Driven on a real multi-turn session
over the wire against a real OTLP collector, the exporter's turn-span
offset and the store's `t_ms` sat **5 ms apart** with a near-instant
mock ASR and **407 ms apart** with 400 ms of latency injected into it.
The gap is the ASR stage: unbounded, and different every turn.

The injection is the part worth keeping. A mock-only run rounds the two
into the same millisecond and reports a match, so the honest version of
this measurement had to make the stage cost something first. A key
adopted on the unlatenced run would have passed every test in this
repository and misfiled artifacts on every real deployment.

**Candidate A, the store's own turn id reaching the exporter, is dead
as written**, because at `turn_started` no store row exists yet, and by
the turn's end there may be two.

**Why there may be two, which is the finding underneath both.** The
store's turn and the exporter's turn are different concepts and both
are right. The exporter opens one turn span per USER UTTERANCE. The
store writes one row per (turn x conversation): `_record_turn` has
exactly two call sites, the reply's `finally` (once per reply, however
it ended) and the handover boundary. So records per turn = 1 +
handovers, and `switches_left` is 1 per turn with a second switch
refused, which bounds it at two rows per turn.

Measured rather than reasoned about, because the same instinct had
already been wrong once: **a barge-in does NOT split the record** (two
turns, one record and one turn span each, in two distinct traces) and
**neither does a reply that failed mid-stream** (one record). Only a
handover splits it. The committed suite already proved the record half
of the barge-in case: `test_a_cancelled_reply_records_what_its_finally_saw`
drives `ReplyOutcome.BARGED_IN` and asserts `only_record`.

**And nothing linked a handover's two rows.** The second comes from
`_seeded_turn`, a fresh turn state whose `at` is a new clock reading,
on another thread, with another agent, carrying no utterance of its
own.

### What was built instead

An **utterance handle**, minted where `turn_started` is emitted,
declared on that event, carried on the turn state into every
`TurnRecord` that turn produces, and written to a new nullable
`record.turns.utterance` column by migration `1010`. The exporter
retains each turn's context under it, and it is on the turn span as
`vinga.utterance.id` so that a reader of the trace can use the
correlation rather than only the server that minted it.

It is named for the UTTERANCE rather than the turn deliberately. The
store models a handover as two turns on two threads and is right to:
the seeded turn has nothing heard on it. A handle claiming those rows
are one turn would contradict a model that is correct for its own
purpose, where what is actually true of them is that they answer one
utterance.

### Deviations from the plan

- **The plan's join key was replaced rather than chosen.** The plan
  offered candidates A and B and said M4a settles it with evidence; the
  evidence killed both, so a third shape was built. That is the
  milestone's own mandate discharged, not a scope change, but it is the
  plan's most load-bearing paragraph and it was rewritten in place
  before implementation began.
- **The plan's regression case was misdescribed and has been
  corrected.** It called for a case that a second `turn_started`
  arriving before its predecessor's `reply_finished` "does not silently
  discard the second turn's span". That is not today's behavior:
  `_open_turn` early-returns when a turn is already open, which is
  deliberate, and probed directly the second turn's span IS lost. What
  protects it is that `reply_finished` is the reply `finally`'s first
  statement and a barge-in awaits the cancelled reply through it. So
  the case pins that ORDER, in the module that decides it.
- **One addition beyond the plan's letter:** `vinga.utterance.id` on
  the turn span. The plan described the handle only as a retention key,
  which would have left the correlation readable by this process and by
  nothing else. One line, metadata, and it is what makes the join
  checkable from outside.
- **The compatibility stance was stated too strongly at first, and the
  external review caught it.** The changelog fragment said an existing
  database was "not carried across this release" and then described
  what happens to its preserved rows, which contradicts itself. What
  the recorded stance actually licenses is the absence of a backfill,
  not a refusal to boot: an existing database upgrades and keeps every
  row, and the pre-M4a ones read null and cannot name a trace.

  The review proposed going the other way, making the column non-null
  and sending old stores down a reset path. That was not taken, for
  three reasons. A null here is not a new state for a reader: it is the
  same "no target" the correlation already answers with for a context
  that has aged out of the retention, and it is handled by the same one
  path, so there is no branch to inherit. The re-review was right that
  this last part was a claim and not yet a fact, because
  `turn_context` took `str` and a consumer would have had to narrow the
  type before it could ask. It now takes `str | None`, so the claim is
  true of the code rather than of the prose around it: one call, one
  no-target answer, however the target came to be missing. Non-null would force every
  store-driving suite and every double to mint telemetry-adjacent ids
  for rows that have no utterance, which weakens exactly the
  content-and-telemetry separation that made this design preferable to
  putting trace ids on the record. And forcing a reset is a change of
  posture rather than a defect fix, so it is the maintainer's call and
  not a reviewer's or an implementer's. The wording was corrected
  instead, in the fragment and in the plan.

### What the external review changed

Three findings, all taken, and two of them were holes in the tests
rather than in the code. They are worth recording because both holes
have the same shape: a case that passes for a reason weaker than the
claim it is named after.

- **The eviction cases did not prove the pin is taken at ADMISSION.**
  They ran against a double whose eviction fired inside
  `retained_context`, so moving that call from admission onto the
  worker, which restores the first race outright, left both green. They
  now drive the REAL retention: a job ahead of the target holds the only
  worker, the target is admitted behind it, and enough later sessions
  are opened to evict it for real. Both were then re-falsified against
  the mutation each is actually about, moving the pin onto the worker
  for the first window and restoring the session-keyed
  `reference_media` for the second, and each fails against its own.
  The double's eviction machinery was deleted rather than left
  unused, since a fake that cannot tell those two apart has no business
  looking as though it can.
- **Nothing proved the stored handle is the handle the exporter was
  given.** The store cases proved the rows agree with each other and
  the exporter cases injected a synthetic id, so a runtime emitting one
  uuid and storing another would have left every case green while
  misfiling every artifact in the field. One case now drives a handover
  through the real pipeline with both the recorder and the exporter's
  tap attached, and insists the two stored rows, the span attribute and
  the retention key are one string. Verified by mutation: emitting a
  different id fails it.
- **The compatibility claim contradicted itself**, which is the
  deviation recorded above.

### Verification

The two eviction windows are two cases and both were **falsified before
being trusted**: with the pre-M4a addressing restored, each fails with
the `no_trace` this milestone exists to remove. The turn retention has
its cap asserted on both sides of itself, a turn a barge-in ended is
shown pinned all the same (captured at the open, not the close), and a
media reference addressed by a turn's context is shown landing in that
turn's own trace rather than its session's.

### Left alone deliberately

The cross-side join is proved on each side separately: the store rows
share one id, and the exporter retains a turn under a given id. Joining
them at the wire belongs with #506, which is the first consumer that
actually performs the join, and proving it there rather than here keeps
this milestone's diff to the mechanism.

## M4b: the operator's collector reach

The plan answered this milestone's three open questions in a section of
its own, so there was nothing left to decide here and the work is the
shape that section describes: one field, one argument at three existing
call sites, and one more fact in a sentence that already existed.

### What landed

| Piece | Where |
| --- | --- |
| `server.telemetry.reach`, in the `Reach` vocabulary, defaulting to `internet` | `config/models.py` `TelemetryConfig` |
| The declaration the refusal names, one spelling beside the rule | `boundary.py` `FEATURE_REACH_KEY` |
| The refusal sentence, gaining the declaration and losing nothing | `boundary.py` `check_feature` |
| The section's reach passed instead of a fixed `Reach.INTERNET` | `telemetry.py`, `transcript_export.py`, `capture_upload.py`, each `_boundary_refusal` and its one caller |
| The suite that owns the joining up | `tests/unit/test_telemetry_reach.py` |

### Deviations from the plan

- **The default is the field's own, not a translation at the call
  sites.** The plan says "absent by default" and "absent means
  `internet`". Those are one fact, and it has one home: the field is
  `Reach` rather than `Reach | None`, with `Reach.INTERNET` as its
  pydantic default. A nullable field plus three `or Reach.INTERNET`
  spellings would have been the same decision written four times, which
  is the rule about two structures that must agree. The key is still
  absent from a configuration by default, which is what an operator
  sees; what changes is that nothing downstream has to know what its
  absence means. The generated reference now states the default
  outright, which is the upgrade note rendering itself.
- **The declaration's spelling is a module constant rather than a
  fourth argument.** `check_feature` names `server.telemetry.reach` in
  its sentence, and the string lives in `boundary.py` beside the rule,
  the way each caller's switch key lives beside its own builder. Every
  feature of this shape is on one section, so an argument would be a
  parameter with one possible value at three call sites. The comment
  says what turns it into an argument: a second section growing a
  feature of this shape, arriving with the caller that needs it.
- **The changed sentences in the observability map are the Status
  paragraphs, not only the Retention and access ones.** The plan's
  documentation footprint named the latter. The falsified sentence,
  "refused under any `server.data_boundary` narrower than `internet`",
  is in all three Status paragraphs, so those are where the fact
  actually lived and where it moved. The Retention and access
  paragraphs gained the assertion itself, written out once in the
  exported-traces section that owns the transport and cited from the
  other two.

### Verification

**The absent-key case was falsified against a mutation of the
default**, which is the one upgrade-breaking mistake available here. It
is pinned twice and each pin catches a different way of making it: a
table asserting admitted-or-refused at all four boundary states and at
all three sites, and a differential case holding the refusal sentence
equal to the one `check_feature(key, Reach.INTERNET, boundary)`
composes. With the field's default changed to `Reach.NETWORK` the table
fails at the `network` row (the boot is admitted where it was refused)
and the sentence case fails everywhere; with `Reach.HOST` the table
fails at two rows. Neither survives.

The other cases were watched failing before the implementation existed:
the declared-reach admissions and the wider-reach refusals against a
section with no such key (`extra="forbid"` refuses the file), and the
sentence cases against the pre-M4b wording, which names the switch, the
reach and the boundary and not the declaration.

Every case runs against all three features rather than against the one
it was written for, which is the plan's "one assertion covers every
destination" turned into a run: a per-site suite would pass equally
against three keys.

The no-leak case drives each refusal with the five variables either
transport reads set to credential-shaped values, and hunts the sentinel
in the sentence, in both log formats with the typed `record.args`
behind them, and in every emission an attached server tap was offered.

### Left alone deliberately

- **`check_feature`'s shape.** It took the reach as an argument from
  the day it was written, with a docstring saying that is what makes
  this follow-up a change of argument. It was, and the function's
  signature is unchanged.
- **The live gate.** The plan asks for a server bounded at `network`
  with an asserted LAN reach booting and exporting against a local
  collector. It is not run here and the PR box stays unchecked with
  that reason: what the gate would show is a boot that the unit lane
  drives at every one of its decision points, and the collector this
  gate wants is the one piece of the rig that is not in the worktree.

### PR review round, PR #521

External review: codex CLI 0.154.0, model gpt-5.6-sol, read-only
sandbox, 2026-09-14, runtime 7m57s, reviewing main...6f48300c. Verdict
as received: **not mergeable**. One finding, adopted, fixed across the
commits below.

1. **P1: the reach declaration omits the actual media-upload
   destination.** `config/models.py:881-886` says there are only two
   destinations and that recordings ride `LANGFUSE_HOST`, but
   `capture_upload.py:868-901` obtains a presigned `upload_url` from
   that host and sends the WAV or manifest directly to it. A
   network-local Langfuse can therefore return an internet-hosted
   object-storage URL; the new `reach: network` admission then sends
   room audio beyond a `network` boundary despite the operator
   following the documented assertion. Fix: keep the one-key design,
   but define its value as the outermost reach of OTLP,
   `LANGFUSE_HOST`, and every presigned media-upload target returned by
   Langfuse. Correct the plan, generated reference, README, examples,
   observability map, and changelog wherever they say "two"
   destinations or imply the bytes are uploaded to `LANGFUSE_HOST`.

   *Resolution.* Adopted whole, and confirmed against the code before
   adopting: `_attach` calls `client.media.get_upload_url(...)`, reads
   `upload_url` off the answer, and PUTs the payload to it with
   `x-amz-checksum-sha256` and `x-ms-blob-type` headers, which are
   object-storage headers and name the kind of place the bytes go. The
   design does not move: one key, absent meaning `internet`, the
   outermost of what the section sends, the refusal ordering and the
   value-free sentence all stand, and this is not an argument for a key
   per destination. What moves is the count, the case the rounding has
   to survive, and the weight the "assertion, not a proof" framing
   carries. The field's prose now says the third destination does not
   exist until the backend names it, one request before the bytes go,
   and says the consequence in the words the finding implies: an
   operator who cannot say where their backend stores media has not got
   a `network` deployment to declare. Corrected in the plan's M4b
   section (amended, with a dated note, the plan review round
   untouched), the field description and its regenerated reference,
   `export_audio`'s own description, `capture_upload.py`'s refusal
   helper, `boundary.py`'s `check_feature`, the server README, both
   example configurations, the observability map in both surfaces that
   describe this transport, and the changelog fragment.

   *No test was added, deliberately.* The defect was prose and the fix
   is prose: what the key means cannot be asserted against the code,
   because the whole point of the correction is that the third
   destination is a fact about the operator's backend that this server
   cannot observe. A case pinning a sentence would pin the wording
   without proving the claim, which is the shape this repository
   rejects elsewhere.

**What the round is really worth recording.** The presigned leg was not
undocumented: `capture_upload.py`'s module docstring says the upload
goes to a presigned URL, and `events/catalog.py` gives it as the reason
the HTTP stack is quieted. Both say it as a CREDENTIAL fact, which is
what it was needed for at the time, and neither draws the other
consequence, that the bytes therefore have a destination no
configuration of this server names. So every page that described where
content goes had a hole in exactly the shape of the key M4b was adding.
The lesson is narrow and worth keeping: a fact recorded for one
property (this URL is a secret) does not answer a question about
another (where does this URL point), and a page describing a data
boundary has to trace the bytes rather than the request that asks about
them.

## M5: `export_llm_input`

The plan settled this milestone in four sections of its own (the
fidelity boundary, the bound, what is staged and where, and the module's
own shape), so there was nothing left to decide here beyond the two
things a milestone always decides: what each new sentence says, and
which mutation each new case is held against.

### What landed

| Piece | Where |
| --- | --- |
| `server.telemetry.export_llm_input`, with its prose and its refusal order | `config/models.py` `TelemetryConfig` |
| The module: the stage, the byte bound, the drop accounting, the worker, the events | `llm_input_export.py` |
| `Telemetry.export_llm_input`, `LlmInputRound`, the span's attribute names | `telemetry.py` |
| The two outcome events and their closed reason set of three | `events/catalog.py`, `events/values.py` |
| Staging at both LLM call shapes, each labelled with its purpose | `runtime/pipeline.py` `_tool_loop` and `_summarized` |
| The hand-over at the close, and the constructor argument | `device/session.py` |
| The collaborator closed over, and the shutdown registered | `runtime/pipeline.py` `bespoke_runtime_factory`, `app.py`, `composition.py`, `ws.py` |
| The suites | `tests/unit/test_llm_input_export.py`, `tests/unit/test_telemetry_llm_input.py`, `tests/unit/test_session_llm_input.py`, `tests/integration/test_llm_input_export.py` |
| The ninth surface | `docs/architecture/observability-surfaces.md` |

### Deviations from the plan

- **The staging seam is two verbs rather than one taking a purpose.**
  The plan says both call shapes are staged, "each labelled with its
  purpose", without saying how the label crosses. It is
  `stage_reply` and `stage_recap`, because the alternative was a
  vocabulary the pipeline would have to import: the purpose becomes a
  span attribute, so an enumeration for it belongs to the exporter, and
  a caller passing one would be the reply path learning how this
  surface spells its own words. Both forward to one private `_stage`,
  so the accounting exists once.
- **The seam type carries the request already serialized.**
  `TranscriptTurn` carries the store's columns and lets `telemetry.py`
  render them; `LlmInputRound` carries a string. That is the bound's
  own requirement rather than a preference: the ceilings are measured
  on the serialized form that would actually be exported, so the
  rendering has to happen before the bound can be applied, and a type
  carrying provider objects would be rendered twice, once to measure
  and once to write. Two renderings that must agree are the trap this
  repository has a rule about.
- **The observations answer to the SESSION span rather than to a
  turn.** The plan's live gate says "on the trace the session was
  exported under" and the milestone says nothing else about the parent,
  so this is the plan implemented rather than a departure from it, but
  it is worth the sentence because #506 moved the transcripts the other
  way. The reason it stays here: a recap round belongs to no turn at
  all, a reply round is several requests inside one turn, and the
  question a reader arrives with is what the model saw in this
  conversation.
- **One bounded call per job rather than the transcript export's page
  loop.** That module alternates a page read with a page export because
  nothing bounds a session's turn count. What this holds was weighed
  against a byte budget before it was held at all, so a job is a
  bounded request by construction and paging it would be machinery
  guarding a number that is already guarded.
- **The round cap reports `over_budget`.** The plan asks for two
  reasons and three limits. The cap is the entry half of the same
  budget, so a round it evicts is reported as the session holding more
  than it may, and the two reasons stay the two the plan named: one
  request was too large to carry, or the conversation outgrew what may
  be held for it.
- **The rendered request carries four keys and not five.** The purpose
  is vinga's own label for which call shape assembled a round rather
  than something the model was handed, so it rides the span as an
  attribute and stays out of the request. The class's enumeration in
  the ADR is exactly the four provider arguments, and a class whose
  value is that it is what was sent must not quietly grow a field the
  model never saw.
- **A rendering that fails is a third absence, and it is not counted.**
  `_stage` contains every exception, because it runs inside a reply.
  The two counts are the bound's own vocabulary and mean something
  exact to a reader; a request that could not be rendered at all is a
  defect in this server rather than a conversation that outgrew its
  budget, so it is one value-free warning line and no count.
- **M4b's `reach` prose gained a word.** Its field description said
  "all three features are refused"; there are four exports behind that
  one assertion now. The count is corrected in the model, in
  `config.example.yaml` and in the server README, and nothing about the
  key's mechanism is touched.
- **`_private_tracer` is an extraction.** The lazily built
  processor-less provider was inline in `_transcript_spans`; two
  content exporters need the same object for the same reason now, and a
  provider built twice would be two resources to keep in step. The
  lock's name moved with it, from `_transcript_lock` to `_private_lock`.

### What the mutations found

Every new case was watched failing, and each is held against a mutation
that makes the specific mistake it exists to catch.

The bound: admitting oversized requests fails four cases; dropping
newest-first fails both ordering cases; counting an oversized drop as
over budget fails three. The containment: logging the assembled request
fails all three sentinel cases. The transport: routing the spans
through the shared `self._tracer` puts two spans on the session trace
and fails the batch-queue case. The attributes: copying the request
into a metadata field as well fails the pinned-attribute case and the
one-attribute sentinel.

**The one-observation-per-round claim is held against a mutation that
stages per attempt**, which is the shape the plan's finding is about:
moving the staging call inside the partial the first-token watchdog
re-invokes. Two cases fail, the watchdog one and the failed-provider
one, which is what says the claim is about where the call sits rather
than about how many rounds a reply has.

Two mutations SURVIVED, and both are findings rather than reliefs.

- **Replacing the close's `pop` with a `get`** left a session holding
  the whole of what its model saw for the life of the process, and
  passed everything: the case asserted that nothing was exported, which
  is true of a held stage too. It is now driven by closing twice, which
  is the only way to ask from outside whether anything is still held,
  on the clean path and on the traceless one, and the mutation fails
  both.
- **Removing the device session's hand-over entirely** passed the whole
  unit lane, because the unit case called `session_closed` itself. That
  proved the exporter and not the wiring. The integration lane is where
  it is proved now: a real server, a real conversation, a real close,
  and an OTLP collector on a socket, with nothing in the file reaching
  into the server. The mutation fails two of its three cases.

### Verification

`ruff check`, `mypy`, the unit lane, the integration lane, the
generated-document drift checks, `scripts/check_doc_links.py` and
`scripts/fold_changelog.py check` all run and pass. The command
spellings census was run after every documentation edit.

### Left alone deliberately

- **The live gate.** The plan asks whether an assembled request arrives
  rendered as an observation's input, with tool arguments and results
  present, on the trace the session was exported under. It is not run
  here and the PR box stays unchecked with that reason: the collector
  and the backend the gate wants are the one piece of the rig that is
  not in the worktree. What IS certified is the same attributes on the
  same encoding, one hop short of a backend: the integration lane runs
  a real server against a real OTLP receiver in-process and decodes the
  protobuf it received.
- **Per-turn parentage.** #506 moved the transcripts under their turns
  and this could follow, but the two have different shapes: a recap
  round has no turn, and a reply's rounds are several inside one. An
  issue that wants them nested is a decision of its own.
- **The vendor's own request body.** The plan rejects a provider-side
  snapshot with a reason of its own, and nothing here revisits it: a
  content surface built out of an SDK's call arguments would put the
  no-leak contract behind a per-adapter exclusion list maintained
  forever.
