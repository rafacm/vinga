# Transcript export as the third optional telemetry layer: implementation

Companion to [`2026-09-12-transcript-export.md`](2026-09-12-transcript-export.md),
one section per milestone, appended in the same change that ticks the
milestone checklist. It records deviations from the plan, resolutions of
the plan's open questions, and discoveries.

## M1: rename attach_captures to export_audio

The mechanical sweep the plan sequenced first, so the new flag's prose,
refusal ordering and tests in M2 are written against the final
vocabulary once instead of twice. Semantics are untouched: same default
of off, same builder ordering, same three refusals, same no-op with
capture off. No alias machinery was added and none was found to remove;
a file still spelling `attach_captures` is refused at boot by the
telemetry section's existing `extra="forbid"`.

### What moved

| Site | What changed |
| --- | --- |
| `config/models.py` | the `TelemetryConfig` field and its description prose, the section docstring's sentence contrasting it with `enabled`, and the `BOOT_REFUSALS` registry comment's closing clause |
| `capture_upload.py` | `ATTACH_KEY`'s value, the builder docstring's step 3, the `attaching` read, and both refusal sentences (`ATTACHMENT_NEEDS_TELEMETRY` and `ATTACHMENT_NEEDS_AN_EXPORTER`, the latter through `ATTACH_KEY`) |
| `telemetry.py` | the vocabulary-exception note's sentence about when a media reference is written at all |
| `config.example.yaml`, `config.deploy.example.yaml` | the commented-out key in the telemetry block |
| `tests/unit/test_capture_upload.py` | 16 sites, including the pin that `ATTACH_KEY` ends in the key's own spelling |
| `tests/integration/test_capture_upload.py` | one `TelemetryConfig(...)` construction |
| `tests/integration/test_tier_closure.py` | the environment-variable spelling, `VINGA_SERVER__TELEMETRY__ATTACH_CAPTURES` |
| `docs/reference/server-config.md` | regenerated through its generator, never hand-edited |
| `docs/architecture/observability-surfaces.md` | the exported-capture-media row's switching clause |
| `docs/adr/2026-08-15-content-and-telemetry-are-separate-surfaces.md` | the 2026-09-12 amendment's key, plus one clause naming the rename |
| `.github/workflows/vinga-server.yml`, `vinga-server/pyproject.toml` | the two build comments that name the flag to explain why both image variants carry the observability extras |

`ATTACH_KEY` keeps its constant name. It names the role the constant
plays (the one spelling every refusal below it quotes), not the spelling
of the key it holds, so renaming it would have been churn with no reader
served.

Historical records kept their spelling, per the plan's documentation
rule: the two `2026-09-12-langfuse-backend*.md` files and the folded
`CHANGELOG.md` entry describe the repository on their own date.

### Deviations from the plan

One, and it is an addition to the census rather than a departure from a
decision.

- **A seventeenth site the plan's census did not name:**
  `tests/integration/test_tier_closure.py` sets the flag through the
  environment rather than through a file, as
  `VINGA_SERVER__TELEMETRY__ATTACH_CAPTURES`. The loader derives that
  variable's name from the field, so the rename moves it too and a
  missed one would have left that lane setting a key the model no longer
  has. Renamed with the rest; the lane passes.

Nothing else deviated. The plan's census was otherwise exact, and
`config/loader.py` holds no alias machinery to remove, as the plan said.

### Discoveries

- **The command-spellings census was already stale at the branch head,
  and not from the rename.** The unit lane's
  `test_the_manifest_is_the_census` failed on one missing row, and the
  spelling behind it is a sentence in this plan's own Goal paragraph:
  the sweep reads every tracked file and matches an invocation-shaped
  run of words after a program word, and ordinary prose naming the
  program and a noun looks exactly like one. So the census has been
  stale since the plan was committed, several commits before this
  milestone started. `docs/plans/` is a historical path, so the row is
  classified `historical` and nothing is asked to respell.
  Regenerated rather than hand-edited, which is what the row's
  presence then records.
- **And a census row must not be quoted back into a tracked page.**
  The first draft of the paragraph above reproduced the row and the
  sentence behind it verbatim. The next sweep matched the quotations
  too, and the line break inside one of them produced a SECOND,
  shorter row, so the manifest grew a spelling that existed only
  because this page described the first one. The paragraph now names
  the row without reproducing it. Worth knowing before writing about
  the census anywhere: quoting it edits it.
- **The unknown-key refusal names the section, not the key.** The
  milestone brief expected the refusal to name `attach_captures`. It
  does not, and deliberately: `config/models.py` renders pydantic's
  `extra_forbidden` in this repository's own words and relocates the
  error from the key to the parent it was written under, because an
  unknown key's spelling is operator input and this loader does not
  print input. So an operator who still writes the dead key is told
  `server.telemetry: an unrecognized key is not permitted`. The new test
  pins what the loader actually does rather than what the brief
  expected, and asserts in the same breath that the value the dead key
  carried never reaches the message and that nothing is chained behind
  it.

### The falsification

The new case, `test_the_old_attachment_key_is_refused_at_boot` in
`tests/unit/test_config.py`, was written before the rename and run
against the pre-rename tree, where it failed:

```
assert 'server.telemetry: an unrecognized key is not permitted' in
  'invalid config in the config file --config names:
   - server.telemetry.attach_captures: Input should be a valid boolean,
     unable to interpret input'
```

That is the discriminating failure and not an accident of the fixture:
the key's value is the credential-shaped `PARSER_SENTINEL`, so a
pre-rename tree raises `ConfigError` too, for a boolean type error. Only
the assertion on the unrecognized-key sentence separates the two, which
is why it is the one asserted.

After the rename it passes. It was then falsified a second time from the
other side: the test body pointed at `export_audio`, the live key, and
re-run. It failed with the same shape of message
(`server.telemetry.export_audio: Input should be a valid boolean`),
which proves it pins the old key's retirement rather than merely that
some `ConfigError` is raised. The body was restored to
`attach_captures`, the file touched to defeat any `.pyc` staleness, and
the whole file re-run green (150 passed).

### Verification

- [x] `uv run ruff check .`: all checks passed.
- [x] `uv run mypy` (the events package's strict check, the workflow's
      spelling): success, no issues found in 5 source files.
- [x] `uv run pytest tests/unit -q -n 4 --dist loadfile`: 6999 passed,
      19 skipped, 1 failed on the first run,
      `test_command_spellings.py::test_the_manifest_is_the_census`,
      on a row this branch's plan commits had already made stale (see
      the discovery above). Regenerated with
      `uv run python -m tests.unit.test_command_spellings` in the same
      commit as the last doc edit, per the repository's rule; that
      file's own suite is green afterwards.
- [x] `uv run pytest tests/integration -q`: 325 passed, against a
      Postgres 17 from the committed compose file on its own project and
      port.
- [x] `python3 scripts/check_doc_links.py .`: checked 234 files, 0
      failures.
- [x] `python3 scripts/fold_changelog.py check .`: checked 1 fragment, 0
      failures.
- [x] The committed server reference is current: regenerated with
      `uv run vinga-server config reference server > ../docs/reference/server-config.md`
      and held by `tests/unit/test_server_reference.py`, which the unit
      lane above ran.
- [x] Both example configs still parse and still cover every leaf:
      `tests/unit/test_config_examples.py`, in the lane above.
- [ ] The image lane's extras checks, which quote the flag in a comment
      only. Not run here: they build both image variants and the comment
      they carry is not executable. CI runs them on everything but a
      pull request.
- [ ] Anything on a board. This milestone changes no protocol, no
      firmware-visible behavior and no device path, so there is nothing
      a device checkpoint could falsify.

### PR review round, PR #497

External review: codex CLI 0.154.0, model gpt-5.6-sol, read-only
sandbox, 2026-09-12, runtime 3m31s, reviewing origin/main...a8de0b83.
Verdict as received: **mergeable after the listed fix**. One finding.

1. **P2: The old-key refusal test does not pin suppression of the
   rejected key.** The test's comment claims the refusal names only
   the section, but the assertions only exclude the sentinel value,
   so a refusal echoing `attach_captures` (itself rejected operator
   input) would pass. Fix: assert the old key's spelling absent from
   the refusal beside the value and chain assertions.

   *Resolution.* Adopted; `assert "attach_captures" not in refusal`
   joins the case. Falsified by running the assertion against a
   constructed key-carrying refusal sentence, which fails it; the
   suite file re-run green (150 passed).

## M2: the flag, the exporter, the vocabulary, the record

The milestone the plan gated on a live rendering question, so the gate
is first here too. It passed, and one of its answers changed what the
record claims rather than what the code does.

### The rendering gate

Run before a line of the exporter was written, against a self-hosted
Langfuse on a scratch directory outside the repository (project
`vinga-495-lf`, every host port remapped, headless `LANGFUSE_INIT_*`
provisioning with throwaway values, `/api/public/health` answering
`{"status":"OK","version":"4.35.0"}`). One hand-made trace, two spans,
carrying the three attributes the design rests on.

```
langfuse.observation.input             = "probe heard text 495"
langfuse.observation.output            = "probe reply text 495"
langfuse.observation.metadata.legs     = [{"agent":"alpha","text":"This is Alpha speaking."},
                                          {"agent":"beta","text":"This is Beta finishing."}]
```

Read back through `GET /api/public/v2/observations?sessionId=...&fields=io,metadata`:

```json
{"id": "44b103f99433920b", "type": "SPAN",
 "input":  "probe heard text 495",
 "output": "probe reply text 495",
 "metadata": {"legs": [{"agent": "alpha", "text": "This is Alpha speaking."},
                       {"agent": "beta",  "text": "This is Beta finishing."}],
              "attributes.vinga.turn.index": 1,
              "attributes.vinga.turn.id": 4242}}
```

**Both halves render as the acceptance requires.** `input` and `output`
are the observation's OWN fields rather than metadata keys, which is the
whole of what the gate was for and the one thing the plan reserved the
right to stop the milestone over.

And one answer the plan did not ask for: the canonical JSON string is
**parsed back into structured metadata**. The wire carries one string
attribute, because span attributes take primitives and never mappings,
and a reader meets `metadata.legs` as an array of objects. So the
encoding is not a compromise a reader has to decode by hand, which is
worth recording because it is the reason no second spelling is needed.

### What landed

| Piece | Where |
| --- | --- |
| The close barrier | `Close` carries an `Acknowledgement`, `close_session` returns it, the writer settles it from the outcome that wrote the close row, and `Acknowledgement` generalizes from "its own turn" to "its own record" with the barrier documented where the barrier is |
| The read | `threads.transcript_rows` (six named columns, `id > after`, ordered by `id`, limited) and `Reads.transcript_rows`; `conversations/api.py` untouched |
| The span | `Telemetry.retained_context`, `Telemetry.export_transcript`, `TranscriptTurn` as the seam type, `Delivery` as the answer, the retention bound derived from the configured capacity, and content as the second stated exception to the module's vocabulary rule |
| The worker | `src/vinga_server/transcript_export.py`: the builder and its four-step decision order, the bounded queue, the lazy daemon worker, the interruptible acknowledgement wait, the page-read-and-deliver loop, the ordered teardown and the quieting lease |
| The vocabulary | `TranscriptExportFailure` (five members), `TranscriptsExported` and `TranscriptExportFailed` on `vinga_server.transcript_export`, both joining `AFTER_THE_CLOSE`, with their drivers and the regenerated events reference |
| The flag | `TelemetryConfig.export_transcripts`, both example configs, the regenerated server reference |
| The wiring | `app.py` builds it and registers its shutdown behind every teardown it unwinds in front of; `device/session.py` forwards the acknowledgement `_stop_recording` now returns |
| The record | the observability map's eighth surface and the export-ladder table, the content-and-telemetry ADR's third amendment, `changelog.d/495-transcript-export.md` |

### Deviations from the plan

1. **The bounded call's ceiling is the exporter's own deadline, not a
   fixed 30 s.** The plan says the call's bound is "the export-timeout
   posture (30 s)". The OTLP HTTP exporter takes its whole deadline,
   retries included, from `OTEL_EXPORTER_OTLP_TIMEOUT` (ten seconds
   unless an operator says otherwise), and passing a number would
   overwrite an operator-written environment fact that this module's
   entire discipline is not to touch. So the instance is constructed
   with no arguments, the #66 posture, and the plan's substance holds:
   the call IS bounded, it bounds the retries with it, and the
   blackhole case asserts the failure event inside that bound with the
   variable shortened from the outside rather than from the code.
2. **The dedicated exporter is reached through `_otlp_exporter` rather
   than through a new `_Sdk` field.** The plan says "through the
   existing `_Sdk` seam"; `_otlp_exporter` is the existing seam for
   constructing that exporter specifically, and it is already what the
   egress case substitutes to prove nothing is built under
   `local_only`. `_Sdk` gained one name, `SpanExportResult`, because
   reading the answer needs it and no module-level import may name an
   OpenTelemetry symbol.
3. **The transcript spans need no span processor at all.** The plan
   says they are "collected in memory rather than queued". A
   `TracerProvider` with no processor still builds and ends real spans,
   and an ended span is exactly what an exporter takes, so the page is
   a list the builder returns. A collecting processor was written first
   and taken out: the SDK calls a private `_on_ending` hook on every
   processor, so a duck-typed one would have leaned on a private name
   for nothing.
4. **The exporter's shutdown is registered beside the uploader's
   rather than after the composition's attribute removal.** The plan
   says "pushed onto the exit stack LAST, so it unwinds FIRST, while
   the store, the event tap and telemetry are all still up". The
   clause after the comma is the property, and it holds here: the two
   registrations that come after this one release nothing (an
   attribute is removed, the MCP managers are stopped), so this is the
   last TEARDOWN registered. A case drives it rather than asserting
   it, and was watched red against the registration removed.
5. **`Acknowledgement` gained `settled`.** Not in the plan, and found
   by the worker that needed it: `wait` answers false for "not yet"
   and for "no" alike, so a poller watching a stop flag in short
   slices could not tell them apart and a record the writer had
   already refused would cost the worker its whole thirty seconds,
   for every session a drain closes.
6. **The walkthrough's handover records two turns, not one split
   reply.** The packaged mock LLM says nothing on the round it calls a
   tool, so a successful `switch_agent` leaves the first agent with no
   text at all: the store records the tool-only turn and the new
   agent's reply as two rows, and the first row's `legs` carries its
   agent and no text. That is the pipeline's own shape rather than
   anything this milestone chose, so the live record says what it saw;
   the two-text-leg canonical string is pinned in the unit lane
   against the store's own column shape, and the gate above confirmed
   that exact string rendering live.

### The ordinal convention, settled

The plan's two sentences about `vinga.turn.index` admit two readings
("derived from the projection's `id`-ascending ordering" and "any
session's first exported turn is index 1"), and they part company for a
session whose first turn has no text at all. The second is what shipped
and what the tests pin: the ordinal counts the turns this export
actually WROTE, so it is 1-based, gapless, and 1 for the first
observation a reader meets. A turn with neither text half is exported
as no span and consumes no ordinal. Correlation back to the store is
`vinga.turn.id`'s job, which is why the two are separate facts.

### Tests

`tests/unit/test_conversations_durable.py` gains six cases for the
barrier, and they drive both sides of its stated limit: a close whose
own transaction fails answers `False`, and a close committing after an
earlier turn was dropped-and-counted answers `True` with the stored
turns readable.

`tests/unit/test_conversations_threads.py` gains seven for the
projection, including a row family carrying tool arguments and a tool
result with none of them selected, and both answers of the read seam.

`tests/unit/test_telemetry_transcripts.py` is new, seventeen cases: the
captured context surviving its own eviction, the retention derived from
capacity with every session live, the attribute set pinned exactly, the
exact canonical legs string, the allowlist dropping the token halves,
the three delivery answers, and the one that is the transport half of
the design, which is that a transcript span never reaches the shared
batch queue.

`tests/unit/test_transcript_export.py` is new, forty-three cases: the
build-nothing set, the refusals value-free and unchained, the decision
order driven with `local_only` on, the paging arithmetic, the five
failure reasons each at its decision site, the drain with every job
accounted for, the close that does not wait on a wedged worker, the
shutdown that interrupts a job sitting in the acknowledgement wait, and
the two sentinel families with opposite claims, the second of them
planted in a real store and read through the real `Reads`.

`tests/integration/test_transcript_export.py` is new, five cases: the
wire claim off protobuf a collector received, the sentinel counted in
the collector's own bytes, the flag off exporting nothing, the
blackholed backend with three latencies asserted separately, and a real
conversation writer parked at its gate so the barrier genuinely never
settles.

Every new case was watched red first. Four mutations were driven, each
failing exactly the case that names it and nothing else:

- the private provider replaced by the shared tracer, which fails
  `test_a_transcript_span_never_rides_the_shared_batch_queue`;
- the context looked up at export time instead of used, which fails
  `test_a_context_captured_at_admission_survives_its_own_eviction`;
- the interruptible wait replaced by one bounded `wait`, which fails
  both shutdown cases and nothing else;
- the ordinal reset per page, which fails the oversized-session case
  and the drain's own count;
- and the projection widened to `select(turns)`, which fails the
  threads case that names its columns.

No mutation survived its case. The concurrency-driving cases (the
drain, the full backlog, the wedged close and the two shutdown cases)
were run twenty times over, zero failures.

### The live walkthrough

The same stack as the gate, with the server this branch builds pointed
at it. Recorded verbatim, the way #66's Jaeger record and #67's are.

```
# the stack, in a scratch directory outside the repository
docker compose -p vinga-495-lf up -d --wait
curl -s http://localhost:53010/api/public/health
#  {"status":"OK","version":"4.35.0"}

# the server's own database
VINGA_DB_PORT=55496 docker compose -p vinga-495-m2 up -d postgres --wait

# the server: conversations on, telemetry on, export_transcripts on
VINGA_DB_PORT=55496 VINGA_API_SECRET=... \
OTEL_EXPORTER_OTLP_ENDPOINT=http://localhost:53010/api/public/otel \
OTEL_EXPORTER_OTLP_HEADERS="Authorization=Basic <base64 pk:sk>" \
  uv run vinga-server --config config.yaml

uv run vinga-server config import -f document.yaml --config config.yaml
uv run vinga-server config apply --config config.yaml --force
#  two agents (alpha, beta), one device bound to both, mocks throughout,
#  alpha's LLM scripted to hand over to beta

python drive.py 8495 aa:bb:cc:dd:ee:95 3
#  turn 1: heard: tell me the secret about the kitchen light | BETA here, and I heard you.
#  turn 2: heard: tell me the secret about the kitchen light | BETA here, and I heard you.
#  turn 3: heard: tell me the secret about the kitchen light | BETA here, and I heard you.

#  the server log, after the close:
#  session 3a873f69...: handed over from agent alpha to beta
#  session 3a873f69...: 4 turn transcripts exported to its trace in 66 ms
```

What the instance then held, read through its own API:

```
GET /api/public/v2/observations?sessionId=3a873f696a484c818558e5b329766f75

22 observations, 4 traces
  8f9de8cf  session, transcript x4, transcripts_exported
  a3d6b986  turn, asr, llm, llm, playback, tts_stream     <- the handover turn
  c8b07d73  turn, asr, llm, playback, tts_stream
  5787f60b  turn, asr, llm, playback, tts_stream

...&fields=io,metadata
  turn index 1  id 1  agent alpha
     input : 'tell me the secret about the kitchen light'
     output: None
     legs  : [{"agent": "alpha"}]
  turn index 2  id 2  agent beta
     input : None
     output: 'BETA here, and I heard you.'
  turn index 3  id 3  agent beta
     input : 'tell me the secret about the kitchen light'
     output: 'BETA here, and I heard you.'
  turn index 4  id 4  agent beta
     input : 'tell me the secret about the kitchen light'
     output: 'BETA here, and I heard you.'
```

The acceptance this milestone owns, live: each turn's text is in the
observation's own RENDERED input and output fields, the four
observations are in the SESSION's trace beside the session span rather
than in traces of their own, the ordinal runs 1 to 4 with the store's
row ids beside it, and the handover is followable as `vinga.agent`
moving from alpha to beta with the leg attribution rendering as
structured metadata on the turn it happened in. The outcome event is
there too, as an observation beside them.

The thin part is recorded rather than glossed: the mock's handover
speaks nothing for alpha, so that leg has an agent and no text. The
gate above is where the two-text-leg rendering was confirmed.

Torn down afterwards with `docker compose -p vinga-495-lf down -v` and
`docker compose -p vinga-495-m2 down -v`, the server stopped. Nothing
Langfuse-deployment-shaped is committed: the compose file, its override,
the `.env`, the two configuration halves and the driver all lived in the
session scratchpad.

### Verification

- `uv run ruff check .`: All checks passed!
- `uv run mypy` (strict over `src/vinga_server/events`): Success: no
  issues found in 5 source files
- `uv run pytest tests/unit -q -n 4 --dist loadfile`: 7075 passed, 19
  skipped (6999 before this milestone, plus its seventy-six)
- `uv run pytest tests/integration -q`: 330 passed, against Postgres
  from the committed compose file on `VINGA_DB_PORT=55496`
- `python3 scripts/fold_changelog.py check .`: checked 2 fragments, 0
  failures
- `python3 scripts/check_doc_links.py .`: checked 235 files, 0 failures
- `uv run pytest tests/unit/test_command_spellings.py -q`: 52 passed
- Both generated documents regenerated through their generators and
  unchanged afterwards (`config reference server`, `events reference`)
- The rendering gate and the live walkthrough above, recorded rather
  than asserted

### PR review round, PR #498

External review of the PR diff: codex CLI 0.154.0, model gpt-5.6-sol,
read-only sandbox, 2026-09-12, runtime 6m33s, reviewing commit
`b43a436b`. Verdict as received: **mergeable after the listed fixes**.
Four findings, all genuine, one commit each. Findings condensed but
faithful; resolutions appended per fix.

1. **P1: Production telemetry ignores the configured session
   capacity.** `build_telemetry` derives the retention bound from
   `max_sessions`, and the composition never passed it, so every
   production server retained the bare sixty-four of slack: a
   deployment above that capacity can evict a LIVE session's context
   and report `no_trace` for a healthy export. Pass
   `max_sessions=config.server.limits.max_sessions` and add a
   composition-level regression above capacity 64.

   *Resolution.* Adopted as prescribed. The seam was tested and the
   wiring was not, which is this repository's own "two structures that
   must agree" trap caught one level up: the derivation was correct and
   inert. The regression is at the composition rather than at the
   builder, driven at the size the derivation exists for, and it reads
   the retention through the exporter the app actually built. Red first:
   `AssertionError: 40 live sessions lost the trace they opened under`.

2. **P1: Shutdown does not interrupt an in-flight multi-page export.**
   The stop flag was read inside the acknowledgement wait and nowhere
   else, so the page loop read and delivered every remaining page of a
   long session through a shutdown, spending the join budget on them
   and emitting the outcome after the event tap and telemetry had been
   torn down. Check `_stopping` before every page read and immediately
   after each delivery, returning `dropped`.

   *Resolution.* Adopted as prescribed, with the ORDER of the two checks
   at the bottom of the loop as the part that needed deciding: the short
   page that ends the session returns first, so a job that really
   finished is never reported as dropped for having finished late. A
   second case pins that side, because an interrupt bought by failing
   healthy jobs is not an interrupt. Red first, with one page held open
   and a shutdown begun behind it: `AssertionError: a page was delivered
   after the stop flag / assert 3 == 1`. The nine concurrency-driving
   cases were run twenty times over, zero failures.

3. **P2: The close acknowledgement settles before all earlier records
   are resolved.** A marker is two transactions and the close was
   settled between them, so the barrier answered `True` while this
   session's own queued events were still in front of a lock they can
   wait on and can still fail. Defer the close acknowledgement until the
   event transaction and the late-loss accounting finish, and add a
   gated test proving it stays unsettled while the event half is
   blocked.

   *Resolution.* Adopted as prescribed. **One premise corrected, and it
   does not change the fix.** The finding describes "the database's
   serialized write transactions and 10-second busy timeout", which is
   SQLite's vocabulary; this tree is on Postgres, where the number is
   `LOCK_TIMEOUT_MS = 10_000`, a per-acquisition `lock_timeout` on the
   chain's advisory gate (`db/__init__.py`), and the serialization is
   one writer thread over one queue rather than anything the database
   does. The window, the ten seconds a lock wait can take and the
   failure that can follow are all real under that mechanism, so the
   hole is real and the substance of the fix stands unchanged. What the
   close ANSWERS did not move either: the durable half's outcome. The
   events half is the lossy class, so a transaction that failed there is
   a record dropped and counted rather than one still on its way, which
   is what the barrier's stated limit already covers, and a second case
   pins that side so the deferral cannot quietly become a stricter
   promise. Red first, with the gate standing in front of the EVENTS
   half: `AssertionError: the close answered while its session's events
   were still unresolved / assert True is False`. The eight close cases
   were run twenty times over, zero failures.

4. **P2: Worker creation failure escapes onto the session close path.**
   `_worker` was assigned before `Thread.start()` and the start was
   uncontained, so a process out of threads sent the error up through
   `session_closed` into the device session's cleanup, and a later
   shutdown would try to join a thread that never ran. Start a local
   thread inside an unbound exception boundary, assign after success,
   and have admission emit `dropped` when startup fails.

   *Resolution.* Adopted as prescribed. `_start` answers whether there
   is a worker, admission turns a False into the job's own outcome, and
   the field is assigned only once the start has succeeded, which is
   what keeps the teardown harmless as well. Red first, both cases, with
   `Thread.start` refusing this module's own worker: `RuntimeError:
   can't start new thread`, out of `session_closed` in the first and out
   of the teardown in the second.

#### Re-verified after the round

- `uv run ruff check .`: All checks passed!
- `uv run mypy` (strict over `src/vinga_server/events`): Success: no
  issues found in 5 source files
- `uv run pytest tests/unit -q -n 4 --dist loadfile`: 7082 passed, 19
  skipped (7075 before the round, plus its seven)
- `uv run pytest tests/integration -q`: 330 passed, against Postgres
  from the committed compose file on `VINGA_DB_PORT=55496`
- `python3 scripts/fold_changelog.py check .`: checked 1 fragments, 0
  failures (the M1 fragment folded on `main` in the meantime)
- `python3 scripts/check_doc_links.py .`: checked 235 files, 0 failures
- `uv run pytest tests/unit/test_command_spellings.py -q`: 52 passed
- Both generated documents regenerated and unchanged
