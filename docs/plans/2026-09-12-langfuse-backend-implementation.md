# Langfuse as an optional telemetry backend: implementation

Companion to [`2026-09-12-langfuse-backend.md`](2026-09-12-langfuse-backend.md),
one section per milestone, appended in the same change that ticks the
milestone checklist. It records deviations from the plan, resolutions of
the plan's open questions, and discoveries.

## M1: the mapping, verified against a live Langfuse

The milestone the plan sequenced first so the aliases would be findings
rather than guesses. One alias is necessary and is in
(`session.id`); the agent-as-a-tag alias the plan expected is NOT, and
the reason is recorded below rather than shipped. Three of the four
discovery answers changed something about how M2 and M3 will be built.

### The environment

| Piece | What ran |
| --- | --- |
| Langfuse | `docker.langfuse.com/langfuse/langfuse:4`, `/api/public/health` answering `{"status":"OK","version":"4.35.0"}`, digest `sha256:a5d8d2457702ab7e051bc0788d73871970caebd10aae6635e87cfb736e4067cd` |
| Worker | `docker.langfuse.com/langfuse/langfuse-worker:4`, digest `sha256:5e35e625a214dd868bb22adad90fc52e8f83cc856c3750e47f9a922622c207fb` |
| Rest of the stack | the official compose file's ClickHouse 25.12, Redis 7, Postgres 17 and MinIO, on a scratch directory outside the repository, project `vinga-67-langfuse`, every host port remapped off the defaults |
| Provisioning | headless, through `LANGFUSE_INIT_ORG_ID`, `LANGFUSE_INIT_PROJECT_ID`, `LANGFUSE_INIT_PROJECT_PUBLIC_KEY`, `LANGFUSE_INIT_PROJECT_SECRET_KEY` and the three `LANGFUSE_INIT_USER_*`, with throwaway values that never left the machine |
| vinga-server | this branch, `uv sync --extra otel --extra sim`, `server.telemetry.enabled: true`, its Postgres from the repository compose file on project `vinga-67-db` |
| Providers | the packaged mocks for VAD, ASR and TTS; the LLM stage an `openai_compatible` entry pointed at a throwaway chat-completions stub on loopback (see the deviation below) |
| Conversation | three utterances over ONE device websocket, with a `switch_agent` handover in the second |

Nothing Langfuse-deployment-shaped is committed: the compose file, its
override, the `.env` and the stub all lived in the session scratchpad
and were torn down with `docker compose -p vinga-67-langfuse down -v`.

### The OTLP path and the auth shape

The exporter is the #66 one as merged, configured entirely through the
environment the SDK already reads:

```
OTEL_EXPORTER_OTLP_ENDPOINT=http://localhost:53010/api/public/otel
OTEL_EXPORTER_OTLP_HEADERS="Authorization=Basic $(printf '%s:%s' "$PK" "$SK" | base64)"
```

The ingest path is `/api/public/otel/v1/traces`, asked of the running
instance rather than read off a page: a POST there answers 200, a POST
to `/api/public/otel` answers 404. The SDK appends `/v1/traces` to
`OTEL_EXPORTER_OTLP_ENDPOINT`, so the endpoint stops at
`/api/public/otel`. The credential is the project's public and secret
key as HTTP Basic, base64 of `pk:sk`, in `OTEL_EXPORTER_OTLP_HEADERS`.
No vinga configuration key is involved on either half, which is the #66
posture the plan kept.

### What failed first

- **The plan's read endpoints do not exist on a current self-hosted
  Langfuse.** `GET /api/public/traces` and `GET /api/public/sessions`,
  which the plan names as the citable evidence, both answer
  `{"message":"This endpoint is not available on deployments running in
  Langfuse v4 events_only mode. ..."}`, and so do
  `/api/public/observations` and `/api/public/metrics`. Self-hosted v4
  runs the `events_only` write mode by default, where the legacy
  trace-shaped read APIs are gone. The v4 replacement is
  `GET /api/public/v2/observations`, which is what every answer below is
  read from; it takes a `sessionId` filter, which is what makes the
  session-grouping claim checkable at all. Every ingest-side fact the
  plan assumed held; only the reading moved.
- **Port 5432 was already taken**, so the stack came up only after the
  host ports were remapped. Worth recording because the official compose
  file binds Postgres, ClickHouse, Redis and MinIO to fixed host ports,
  and `ports:` merges by CONCATENATION in a compose override: a plain
  override adds a second binding rather than replacing the first, and the
  stack fails on the default port anyway. `ports: !override` is what
  replaces the list.
- **The packaged mock LLM reports no token usage**, so the first run
  could not answer the `gen_ai.usage.*` question at all: the catalog
  answers an unreported fact with an absent field, correctly, and the
  round span carried no usage keys. Ollama's OpenAI-compatible endpoint
  does not answer with usage either unless asked with `stream_options`,
  and `stream_options` is one of the seven reserved request fields an
  `openai_compatible` entry may not pass through
  (`config/provider_options.py`). The deviation below is how that was
  resolved.

### The discovery answers

**(a) Do traces group into a Langfuse session as-is? No.** The #66
export exactly as merged, three turns and a handover: twenty
observations arrived across four traces (three turn traces plus the
session trace) and every one of them carried `"sessionId": ""`. The
four traces are four unrelated rows in the UI, which is the acceptance
criterion failing.

What the grouping keys on was then asked of the instance directly, with
a hand-made trace carrying one candidate attribute per span:

```
probe_root     langfuse.session.id=lfsession-p1   ->  sessionId "lfsession-p1"
probe_generic  session.id=generic-p1              ->  sessionId "generic-p1"
probe_tags     langfuse.trace.tags=[...]          ->  tags ["agent:alpha","agent:beta"]
```

So both spellings work and either would do. `session.id` is the one that
landed: it is the conventions' own name rather than a vendor's, which is
what makes an unconditional attribute on every span of every deployment
honest rather than a Langfuse-shaped mode switch in disguise.

**(b) Do `gen_ai.usage.*` attributes render as token counts on
generations? Yes, with nothing added.** A round span carrying the #66
correspondence table arrives as an observation of type `GENERATION`
(not `SPAN`), with the usage keys parsed into Langfuse's own fields:

```json
{"name": "llm", "type": "GENERATION", "model": "stub-1",
 "usageDetails": {"input": 61, "output": 7, "total": 68},
 "inputUsage": 61, "outputUsage": 7, "totalUsage": 68,
 "metadata": {"attributes.gen_ai.usage.input_tokens": 61,
              "attributes.gen_ai.usage.output_tokens": 7,
              "attributes.gen_ai.request.model": "stub-1",
              "attributes.gen_ai.provider.name": "openai_compatible"}}
```

The whole `vinga.*` vocabulary arrives beside it as `metadata`, prefixed
`attributes.`, and the resource as `resourceAttributes.`. So every fact
the #66 spans carry is present and filterable; nothing is dropped for
being unrecognized.

**(c) How does the handover span event read? It does not: Langfuse
ingests no span events at all.** The conversation handed over
(`handed over from agent alpha to beta` in the server log, the
`handover` span event on the turn span), and nothing of it reached
Langfuse: no observation of type `EVENT` exists in the project, no
observation is named `handover`, and no span event appears in any
observation's metadata. This is Langfuse's behavior rather than the
exporter's: the same probe trace whose attributes are quoted above also
carried `add_event("probe_event", ...)`, and querying the API by that
name answers `{"data":[],"meta":{}}`. `first_token` is gone the same
way, and the `timeToFirstToken` field on a generation stays null for the
same reason.

What IS followable is the agent: the turn the handover happened in
arrives as one trace holding TWO generations, the first
`vinga.agent: alpha` with `vinga.llm.round: 1` and the second
`vinga.agent: beta` with `vinga.llm.round: 2`, and the turns after it
carry beta throughout. A reader following a handover in Langfuse reads
the agent on the rounds, not an event.

**(d) The media-correlation answers, which M2 is designed from.**

- **The identifier is the OTel trace id, spelled exactly as the exporter
  spells it.** `POST /api/public/media` takes `traceId` (32 hex
  characters, optionally narrowed with `observationId`), plus `field`
  (`input`, `output` or `metadata`), `contentType` from a closed enum
  that includes `audio/wav` and `application/json`, `contentLength`, and
  `sha256Hash` as 44-character base64 (a hex digest is refused by
  pattern). It answers 201 with `{"uploadUrl": ..., "mediaId": ...}`,
  the upload is a plain PUT to the presigned URL, and
  `PATCH /api/public/media/{mediaId}` with `uploadedAt` and
  `uploadHttpStatus` closes the record. The whole round trip was run:
  201, PUT 200, PATCH 200, and `GET /api/public/media/{mediaId}` then
  answers with a download URL and an expiry.
- **A media request naming a trace that has not been ingested is
  accepted, not refused.** The same POST with
  `traceId=ffffffffffffffffffffffffffffffff`, a trace that never
  existed, also answers 201, and the association row appears immediately
  in Langfuse's own `trace_media` table with
  `origin = CLIENT_UPLOAD`. There is no foreign key to the trace and no
  404, so the race the plan feared (the batch exporter holding a
  session's spans for up to five seconds past close while the upload
  wins) is not a failure mode at all: the media record simply waits for
  its trace. **M2 therefore does not need an ordering retry**, and the
  bounded retry the plan sketched for that window can be dropped;
  `no_trace` stays a real reason only for the case where vinga itself
  has no trace id to name (telemetry off, or an evicted retention
  entry).
- **There is no attach-by-session-id path.** The request body is a union
  of a trace context and a dataset-item context; a body naming
  `sessionId` is refused with
  `invalid_union` listing `traceId` and `datasetId` as the alternatives.
  Session-level attachment does not exist in the API, which settles the
  plan's third question: the correlation vinga retains has to be a trace
  id.
- **Two extras worth having found.** `mediaId` is content-addressed: the
  same bytes posted against a second trace answer 201 with the SAME
  `mediaId` and `"uploadUrl": null`, meaning an already-uploaded asset is
  never uploaded twice and an idempotent retry is free. And what makes a
  media record RENDER rather than merely exist is a reference token,
  `@@@langfuseMedia:type=audio/wav|id=<mediaId>|source=bytes@@@`, placed
  in a trace's or observation's input, output or metadata; a probe span
  carrying that token in `langfuse.observation.output` and in
  `langfuse.observation.metadata.capture_wav` arrives with the token
  intact in both. So M3 has a second, span-side half to the attachment
  it had not planned for, and the plan's phrase "not called an
  attachment unless the walkthrough proves Langfuse renders it" now has
  a concrete mechanism to aim at.

### The alias, and the one that was not necessary

Added: `session.id`, beside `vinga.session.id`, on every span this
exporter makes (`SESSION_ATTRIBUTES`, `TURN_ATTRIBUTES`,
`CONTEXT_ATTRIBUTES`, which between them cover the session span, the
turn span and the four stage spans). An attribute table value may now be
a tuple of names, which is the whole of the mechanism: one payload field
exported under each of them, decided in the table rather than by a
second fold.

Not added, and this is a finding rather than an omission: **the agent as
a tag.** The plan expected `langfuse.trace.tags` carrying the agent.
`langfuse.trace.tags` does map (the probe above proves it), but it is a
TRACE-level field, and in this data model a turn trace's root is the
turn span, which carries the agent the turn OPENED with. A trace tag
built from it would say `alpha` for the very turn the handover happened
in, which is the opposite of the fact a reader wants. Tagging both
agents would mean the exporter accumulating the agents that spoke in a
trace and writing them at the root, which is machinery rather than an
alias, and the agent is already on every observation's metadata and
filterable there. So nothing was added, and M2 can revisit it as a
design question with this record behind it.

Nothing else needed a second spelling. In particular `userId` stayed
empty throughout, which is the plan's own rule holding by construction:
a Langfuse user is the person speaking, vinga does not know who that is,
and no attribute vinga sends is read as one.

### The same-project invariant

On the walkthrough checklist from the plan's review finding 11, and held
here trivially: one Langfuse, one project (`vinga-67`), and only the
OTLP half configured at all, since M1 uploads no media. The invariant
becomes checkable in M3, where the `LANGFUSE_*` family joins the
`OTEL_EXPORTER_OTLP_*` one; what M1 records for it is the shape of the
failure it prevents, namely that the media API accepts a `traceId` from
any project without complaint (it is the key pair that decides the
project, and an un-ingested id is accepted), so a mismatch would be two
successful requests and a recording nobody can find.

### The walkthrough, before and after

Recorded verbatim, the way #66's Jaeger record is, both runs against the
same instance and the same conversation.

```
# the stack, in a scratch directory outside the repository
curl -sSL -o docker-compose.yml \
  https://raw.githubusercontent.com/langfuse/langfuse/main/docker-compose.yml
# plus an override remapping every host port and an .env with the
# LANGFUSE_INIT_* values
docker compose -p vinga-67-langfuse up -d --wait

curl -s http://localhost:53010/api/public/health
#  {"status":"OK","version":"4.35.0"}

# the server's own database
VINGA_DB_PORT=55467 docker compose -p vinga-67-db up -d postgres --wait

# the server, telemetry on, pointed at Langfuse's OTLP ingest
VINGA_DB_PORT=55467 VINGA_API_SECRET=... \
OTEL_EXPORTER_OTLP_ENDPOINT=http://localhost:53010/api/public/otel \
OTEL_EXPORTER_OTLP_HEADERS="Authorization=Basic <base64 pk:sk>" \
  uv run vinga-server --config config.yaml

uv run vinga-server config import -f document.yaml --config config.yaml
uv run vinga-server config apply --config config.yaml --force
# two agents (alpha, beta), one device bound to both, mocks for ASR,
# TTS and VAD, the LLM stage on the stub

python drive.py 8167 aa:bb:cc:dd:ee:67 3
#  turn 1: heard: hello there, this is utterance 1439 | This is Alpha speaking. | I heard you.
#  turn 2: heard: hello there, this is utterance 1860 | This is Beta speaking. | I heard you.
#  turn 3: heard: hello there, this is utterance 1680 | This is Beta speaking. | I heard you.
```

**The first run, the exporter as merged.** Twenty observations, four
traces, and:

```
tts_stream   type=SPAN       trace=10dc01fa session='' user=''
playback     type=SPAN       trace=10dc01fa session='' user=''
llm          type=GENERATION trace=10dc01fa session='' user=''
turn         type=SPAN       trace=10dc01fa session='' user='' root=True
asr          type=SPAN       trace=10dc01fa session='' user=''
...
session      type=SPAN       trace=d804f347 session='' user='' root=True
```

Everything is there and nothing is grouped. The generations already
carry their token counts, which is the half of the acceptance that
needed no change.

**The second run, after the alias.** The same commands, and the session
is now a question the API can be asked:

```
curl -s -u "$PK:$SK" \
  "$LF_HOST/api/public/v2/observations?limit=100&sessionId=688e38f2499e41e8820d12ad97bb4c9e"

observations with this sessionId: 20
distinct traces: 4
  trace 7a19ba2d root=turn    spans=[asr, llm, playback, tts_stream, tts_stream, turn]
  trace 3be60501 root=turn    spans=[asr, llm, llm, playback, tts_stream, tts_stream, turn]
  trace f617cff0 root=turn    spans=[asr, llm, playback, tts_stream, tts_stream, turn]
  trace 16af3e9b root=session spans=[session]

  llm agent=alpha round=1 usage={'input': 23, 'output': 7, 'total': 30}
  llm agent=alpha round=1 usage={'input': 36, 'output': 9, 'total': 45}
  llm agent=beta  round=2 usage={'input': 48, 'output': 7, 'total': 55}
  llm agent=beta  round=1 usage={'input': 61, 'output': 7, 'total': 68}
```

The three acceptance criteria this milestone owns, live: one session
grouping its three turn traces and the session trace; token counts on
the generations; and the handover followable, as the two rounds of trace
`3be60501` with a different agent on each. The session span itself
arrives carrying both spellings of the id:

```json
"attributes.vinga.session.id": "688e38f2499e41e8820d12ad97bb4c9e",
"attributes.session.id":       "688e38f2499e41e8820d12ad97bb4c9e"
```

Torn down afterwards: `docker compose -p vinga-67-langfuse down -v`,
`docker compose -p vinga-67-db down -v`, the server and the stub
stopped.

### Deviations from the plan

1. **The read API is `GET /api/public/v2/observations`, not
   `/api/public/traces` and `/api/public/sessions`.** Forced, not
   chosen: see "What failed first". The plan's evidence requirement
   (citable and scriptable rather than screenshots) is met by the
   replacement.
2. **The conversation was driven by the integration suite's device
   driver rather than by `vinga simulator run`.** The packaged simulator
   holds exactly one utterance per connection, which is one turn per
   session, and session grouping across turns is precisely what M1 has
   to see. The driver is the same `xiaozhi_sdk` websocket client
   `tests/integration/test_telemetry_export.py` uses, speaking three
   times over one connection. The simulator's own path is unchanged and
   untested here.
3. **The LLM stage ran on a throwaway chat-completions stub rather than
   a mock or Ollama.** The reason is in "What failed first": neither can
   report token usage through this repository's own configuration, and
   the usage question is one of the four. The stub is an
   `openai_compatible` endpoint on loopback that streams a reply and a
   final usage chunk, so the path under test is the merged
   `openai_llm` provider reading a real `Usage` off a real stream; only
   the model is a fake. It also scripts the `switch_agent` call, which
   is what makes the handover deterministic.
4. **No ordering retry is needed in M2.** The plan's hypothesis was that
   a media request arriving before its trace would have to be retried;
   the instance accepts it and holds the association. Recorded here so
   M2 is designed from the answer rather than from the fear.
5. **The agent-as-a-tag alias was not added**, for the reason under "The
   alias, and the one that was not necessary". The plan explicitly
   admits this outcome ("an empty finding deletes that half of M1"); it
   is half empty rather than whole.

### Tests

`tests/unit/test_telemetry_spans.py` gains
`test_every_span_spells_the_session_id_under_both_names`, which drives a
whole turn and pins both names with the same value on all six span
shapes, and its five closed foreign-prefix sets gain the alias by name
(`GROUPING`) rather than loosening to a prefix match: what those
assertions exist to catch is a key a backend reads by name arriving
without anybody having chosen it, and that stays true.

`tests/integration/test_telemetry_export.py` gains
`test_the_session_id_arrives_under_the_grouping_alias_too`, which is the
same claim off the wire, decoded from the protobuf a collector actually
received, and the gen_ai case's closed set gains the alias for the same
reason.

Both were watched red first, against the exporter with the alias
reverted: six unit cases failing on `'session.id'` and the wire case on
`KeyError: 'session.id'`.

### Verification

- `uv run ruff check .`: All checks passed!
- `uv run pytest tests/unit -q -n 4 --dist loadfile`: 6902 passed, 19 skipped
- `uv run pytest tests/integration -q`: 305 passed
- `python3 scripts/fold_changelog.py check .`: checked 1 fragments, 0 failures
- `python3 scripts/check_doc_links.py .`: checked 231 files, 0 failures
- `uv run pytest tests/unit/test_command_spellings.py -q`: 52 passed
- The live walkthrough above, both runs, recorded rather than asserted.

## M2: the correlation and the vocabulary

The milestone designed from M1's recorded answers. Its first half
landed as planned and is smaller than the plan feared, because the
media API accepts a trace that has not been ingested yet and no
ordering retry is needed. Its second half did NOT land here, and the
reason is a repository invariant the plan's milestone cut did not
account for: it is recorded in full below, with the declarations as
designed, so M3 lands them whole rather than rediscovering them.

### `Telemetry.trace_of`, and what it retains

One method, and nothing else on the surface:

```python
def trace_of(self, session: str) -> str | None:
```

- **Recorded when the session span opens**, not at the close. That is
  where the id exists, and a session the process later loses (a span
  left unended) is still one a reader may ask about.
- **Spelled by the SDK's own `format_trace_id`**, bound in `__init__`
  beside the three OTel names the span lifecycle already binds. The
  thirty-two lowercase hex characters an OTLP request carries are the
  same characters `POST /api/public/media` takes back, which M1's
  walkthrough established by running the round trip; a second spelling
  written out here would be the drift `trace_of` exists to prevent.
- **Retained past the close pop**, which is the whole point: the span
  map is popped at `session_closed` and the capture triplet is only
  final after it, so an id that lived as long as the span would be gone
  at the one moment it is wanted.
- **Bounded at `RETAINED_TRACES = 64`, oldest evicted first**, the
  `PENDING_CAPTURES` posture and the same number: what a late reader
  wants is the session that just ended, and a map that grew with every
  session a process ever ran would be a slow leak in the one object a
  server holds for its whole life.
- **A session this exporter never saw answers None**, which is what
  makes the uploader's `no_trace` a real answer rather than an invented
  id.

**The synchronization, stated rather than implied.** Everything else
`Telemetry` holds is written and read on the session loop, which is why
the span map and the pending-capture hold need no lock. This map is
written there and read from the uploader's worker thread, so it has a
lock of its own (`_retained_lock`) and the two operations a write is
(record, then evict) are held together rather than left to the
interpreter's own atomicity to imply. The module's existing discipline
for cross-thread state is exactly this: a `threading.Lock` around the
state, and `_claim`/`_QUIETING` are the precedents.

### Why the two catalog events are not here

The plan gives M2 the vocabulary and M3 the uploader that emits it.
The repository refuses that split, and the refusal is deliberate rather
than incidental:

```
tests/unit/test_event_baseline.py::test_every_catalog_variant_on_a_scoped_channel_is_produced
AssertionError: assert ['capture_upl...oadAbandoned'] == []
  Left contains 3 more items, first extra item: 'capture_uploaded: CaptureUploaded'
```

Every variant the catalog declares has to be produced by some driver's
run, where a driver drives a real emit path in the production package
and names it by module, function and ordinal. The rule's own words are
that "a declaration nothing can produce is a permanent enlargement of
what this server may say", and the suite carries no exemption list on
purpose ("Nothing is exempt any more"). A milestone PR merges to `main`
on its own, so declaring the vocabulary here would put an unproducible
declaration on `main` for the whole of M3's development, which is the
state the rule exists to refuse. Faking a driver against a module that
does not exist yet, or adding an exemption, would both be papering over
it.

So the declarations move to M3 and land in the same change as the
uploader that emits them. Nothing about them changes; the catalog-first
discipline the plan cites from #66 M1 is preserved exactly as #66 kept
it, where the declarations landed with the decision sites that emit
them and ahead of the exporter that reads them.

### The declarations, as designed and ready for M3

Written and driven against the catalog's own import-time checks before
being taken back out, so M3 lands a design that has been through them
rather than a sketch. The draft diff is not committed; this is its
content.

**A new channel**, `CAPTURE_UPLOAD_CHANNEL = "vinga_server.capture_upload"`,
joining `SERVER_CHANNELS` in channel-name order. A channel is the
emitting module's own name and the reference says so ("an event declared
on one channel and emitted from another is a violation even when its
fields are lawful"), so the uploader's module needs one and the
`abandoned` sweep, which lives in `CaptureStore`, keeps the capture
channel.

**The closed set**, `CaptureUploadFailure` in `events/values.py`, the
plan's eight members with the reason each is told apart by, plus the
`Literal` narrowing the catalog's own convention asks for:

```python
AttemptedUpload = Literal[UNREACHABLE, REFUSED, TOO_LARGE, NO_TRACE,
                          DROPPED, STAGING_LOST, INCOMPLETE]
```

`abandoned` is outside it because it is not an attempt's outcome: it is
what a restart finds staged and removes, said by the recording surface
that opens the directory whether or not an uploader was built at all.
The module's comment above the closed sets counts the narrowings and
moves from three to four.

**Three variants, two declarations.**

| Variant | Channel | Level | Template |
| --- | --- | --- | --- |
| `CaptureUploaded` | capture_upload | INFO | `session %s: capture attached to its trace, %.1f MB in %d ms` |
| `CaptureUploadFailed` | capture_upload | WARNING | `session %s: capture not attached to its trace (%s)` |
| `CaptureUploadAbandoned` | capture | WARNING | `session %s: capture staged for upload was left by a previous run and has been removed` |

`capture_uploaded` carries `session`, `audio_bytes` and
`manifest_bytes` (the two files exactly, which is what a reader
compares against what the backend holds), and `elapsed_ms`; the
sentence renders the pair's total as megabytes through a `carried=False`
field, the way `capture_over_budget` renders what it carries. No URL and
no far-side id, for the reasons the declaration's own note gives: a
presigned URL is a credential in a query string, and an id minted over
there is a fact about a store this server does not own.
`capture_upload_failed` carries `session` and `reason` and never an
exception's words. Both spell the session in their own sentence, which
is the server-channel rule: on a server channel `session` is an
ordinary field rather than one the emitter owns.

**What lands with them in M3**, none of it optional: the two rows in
`vinga-server/README.md`'s logging index, the regenerated
`docs/reference/events.md` (75 events in 104 variants, from 73 in 101),
the drivers in `tests/tools/event_baseline.py` with their `CARRIED`
rows and the driver count, and the `SERVER_CHANNELS` count in the
generated reference's channels section. The exporter's `APPROVED` table
needs nothing: it derives from the catalog, and
`test_the_approved_table_covers_the_whole_catalog` is the pin that
proves it picks them up by construction.

### Tests

`tests/unit/test_telemetry.py` gains five cases in a section of their
own:

- the id is readable after the close that popped the span, and it
  equals `format_trace_id` of the exported span's own trace id, thirty
  two lowercase hex characters;
- a session the exporter never saw answers None;
- the retention keeps `RETAINED_TRACES` and evicts the oldest, asserted
  on both sides of the boundary rather than as a range;
- a reader thread that is not the session loop, driven as contention
  (forty sessions opening while a thread of its own reads) with every
  answer either nothing yet or exactly that session's id;
- and the synchronization itself: the map is held and a reader on
  another thread is asserted not to answer until it is let go.

The last one is the only case that can falsify the lock at all, since
the GIL hides an unguarded read, and it is why it reaches for
`_retained_lock` by name.

`tests/support/telemetry.py`'s `session_events` takes the session id as
an argument now, defaulting to the fixed one: a claim about the
retention is a claim about several sessions at once, and a fixed id
could not state it.

All five were watched red first: `AttributeError: 'Telemetry' object
has no attribute 'trace_of'`, and the synchronization case on
`_retained_lock`.

### Deviations from the plan

1. **The two catalog events moved to M3**, for the reason under "Why the
   two catalog events are not here". The plan's M2 and M3 checklist
   items, its module-layout line for `events/catalog.py` and its "What
   the upload writes back" section move with them. This is a milestone
   cut correction rather than a design change: the declarations are
   unchanged and recorded above.
2. **No ordering retry, as M1 already recorded.** The plan's hypothesis
   that a media request arriving before its trace would need a bounded
   retry was falsified live in M1, so nothing in `trace_of` or its
   retention is shaped by that window.
3. **The changelog fragment is `67-capture-trace-retention.md`** rather
   than a vocabulary-named one, because the vocabulary is not what this
   milestone shipped.

### Verification

- `uv run ruff check .`: All checks passed!
- `uv run mypy` (strict over `src/vinga_server/events`): Success: no
  issues found in 5 source files
- `uv run pytest tests/unit -q -n 4 --dist loadfile`: 6907 passed, 19
  skipped (6902 in M1, plus this milestone's five)
- `uv run pytest tests/integration -q`: 305 passed, against Postgres
  from the committed compose file on `VINGA_DB_PORT=55672`
- `python3 scripts/fold_changelog.py check .`: checked 2 fragments, 0
  failures
- `python3 scripts/check_doc_links.py .`: checked 231 files, 0 failures
- `uv run pytest tests/unit/test_command_spellings.py -q`: 52 passed
- The five new cases watched red before the method existed, quoted
  under "Tests" above.

### Fix round, PR #480

External review of the PR diff came back mergeable after two P2s, both
correct and both about the same hole: the five cases pinned what the
retention ANSWERS and not where it is written or what the lock is for,
so two mutations of the implementation passed the whole suite. One
commit each, each new case watched red against the mutation the finding
names.

- **P2, the lock was pinned on the reader's side only** (`0d08845a`).
  The existing case holds the map and watches a reader wait, which a
  `_retain` with no lock passes untouched, and the forty-session
  contention case never reached the sixty-four bound, so the compound
  record-then-evict the lock is held across was driven by nothing. The
  new case fills the map to exactly `RETAINED_TRACES`, holds the lock
  and opens a session on a thread of its own: the open must not get
  through, nothing of it may land while the lock is held, and once it
  does the map has moved exactly once, newcomer in and oldest out.
  Red against the lock taken out of `_retain` and nothing else:
  `AssertionError: a session recorded its trace while the map was
  held`, with the other four green, which is the finding restated by
  the suite itself. Fifty consecutive runs of the three thread-driving
  cases, zero failures, because one green run of a concurrency pin is
  not evidence.
- **P2, recording at the open was claimed and not tested**
  (`d3154097`). Every positive case closed the session before asking,
  so `_retain` moved to the close path would have passed while breaking
  a stated deliverable: the open is what makes a session the process
  never closes still answerable. The new case opens and asks
  immediately, asserts a canonical id (thirty-two lowercase hex, not
  the invalid one), then closes and asserts that same id is what the
  exported span went out under. Red against the moved `_retain`:
  `AssertionError: an open session has no trace to be named by`.

Re-verified after the round, same Postgres:

- `uv run ruff check .`: All checks passed!
- `uv run mypy` (strict over `src/vinga_server/events`): Success: no
  issues found in 5 source files
- `uv run pytest tests/unit -q -n 4 --dist loadfile`: 6918 passed, 19
  skipped, the round's two new cases included
- `uv run pytest tests/integration -q`: 311 passed
- `python3 scripts/fold_changelog.py check .`: checked 1 fragments, 0
  failures
- `python3 scripts/check_doc_links.py .`: checked 232 files, 0 failures
- `uv run pytest tests/unit/test_command_spellings.py -q`: 52 passed
- The three thread-driving cases, fifty consecutive runs: zero failures.

## M3: the uploader and the vocabulary

The milestone both review rounds hardened, and the one surface in this
server that deliberately sends content off the host. It landed as
planned with two deviations of substance, both recorded below: which
half of the Langfuse SDK the upload goes through, and what the
attachment can honestly be said to do in the UI.

### The module, and what its callers stop knowing

`src/vinga_server/capture_upload.py`. The composition asks
`build_capture_upload(config.server, telemetry=..., local_only=...)`
for one object or for nothing, hands it to the capture store, and puts
its `shutdown` on the exit stack. It knows nothing of hardlinks,
queues, media APIs or presigned URLs.

**The decision order is the contract**, and the review's first finding
is what fixed it:

1. **Capture first.** `server.capture` absent, or present with
   `enabled` off, answers None and none of the checks below run, so a
   capture-off deployment boots identically with or without the extra,
   the telemetry section or `local_only`. It is said out loud exactly
   when there is something to say: with the flag on and nothing being
   recorded, one value-free info line naming the two keys. With the
   flag off as well there is no no-op to explain and nothing is said.
2. **The flag.** Off, or no telemetry section, answers None silently.
3. **Telemetry.** The cross-field refusal turned out to belong to
   `TelemetryConfig` itself rather than to the builder: both keys are
   in one model, which is exactly the `ConversationsConfig` shape the
   plan named as the preferred branch. It is `_check_attachment`, it
   joins `BOOT_REFUSALS`, and the generated reference publishes its
   sentence. What is left in the builder is the assertion that keeps
   the function total for a composition built by hand.
4. **Egress**, through `check_feature(ATTACH_KEY, egress=True, ...)`,
   before any import, any construction and any thread.
5. **The extra**, imported there and not at module scope.

Each refusal is a `ConfigError` with a fixed value-free sentence,
raised outside the handler that read it so nothing is chained.

### The seam, which is two halves

`CaptureStore` gained `session_closed(session)` beside `finished()`,
and the staging moved into `finished()` itself, ahead of the prune on
the line below it. That is the delta round's first finding and it is
not a refinement: `finished()` is where a capture's files become final
AND where they become prune candidates, so any later moment is one a
capture can already have been unlinked in. The device session's close
ordering calls `session_closed` last, after `self._capture_audio.close()`,
which is the only signal that the conversation is over rather than that
a recording's files are final.

A capture whose manifest says `complete: false` is never staged and its
session records `incomplete` when it closes. Staging is a per-job
subdirectory under `<capture.dir>/upload-staging/`, built under a
dotted name and committed by one rename, so a directory that appears
there has both its links in it.

The sweep is `CaptureStore.startup()`, called by the composition
whenever a capture directory is opened, with an uploader or without
one. It says one `capture_upload_failed` with reason `abandoned` per
leftover job before removing it, and skips any job younger than the
process, which is what keeps sequential lifespans in one process from
adopting each other's work in flight. A boot with no capture section
builds no store and leaves the directory untouched.

### The worker

A daemon thread of its own, started at the first job rather than at
build, over a `queue.Queue` bounded at `server.limits.max_sessions`.
A job the bound turns away has its links removed in the same breath as
its `dropped` event. The request timeout is 30 s, the ceiling is two
retries with a doubling wait, and the classification reads a status
code rather than a message.

The quieting lease moved out of `telemetry.py` into `quieting.py` in
its own commit, with the namespaces as its argument: the reference
counting and the one-snapshot rule are the part that must not be
written twice, and getting them wrong leaves a server either
permanently silent or loudly printing somebody's endpoint. The
uploader's instance covers `langfuse`, `httpx`, `httpcore` and
`backoff`. The HTTP stack is the half that matters: `httpx` logs a
request line carrying its URL, and the URL of an upload's second
request is a presigned one, which is a credential in a query string.
The lease is taken by the worker before it does anything at all and
given back from its own `finally`, so it outlives a bounded shutdown's
expiry.

### Deviations from the plan

1. **The upload goes through the SDK's generated REST client, not its
   tracing client, and vinga reads the three `LANGFUSE_*` variables
   itself.** The plan's words are that the credentials are "read by the
   SDK"; `Langfuse()` does read them, and it also constructs a tracer
   provider, a span processor, one or more background consumer threads,
   a process-global singleton keyed by public key, an `os.register_at_fork`
   handler and an `atexit.register(self.shutdown)`, and it does all of
   that with `tracing_enabled=False` as well. An `atexit` hook that can
   wait on a wedged upload is exactly the hazard the plan's own worker
   design rejects `asyncio.to_thread` for, and a second tracer provider
   is a second exporter beside the one #66 owns. So the upload uses
   `langfuse.api.client.LangfuseAPI`, whose media half is the three
   calls M1's walkthrough discovered, and which constructs one
   `httpx.Client` and nothing else. The cost is that this module reads
   `LANGFUSE_HOST` (or `LANGFUSE_BASE_URL`), `LANGFUSE_PUBLIC_KEY` and
   `LANGFUSE_SECRET_KEY` with `os.environ.get`. The substance of the
   plan's position is kept: they are not configuration keys, they are
   never printed, they are not validated (a missing key goes to the far
   side as an unauthenticated request and comes back `refused`), and a
   missing endpoint is an upload failure rather than a boot refusal.
   There is deliberately no default endpoint, and specifically not the
   SDK's own, which is a vendor's hosted cloud.
2. **The presigned PUT is made with `httpx` directly.** The plan says
   layer 2 reuses httpx "for nothing". What it reuses it for is the one
   request the generated client does not make: the media API hands back
   a presigned URL on a storage host, and the SDK's own uploader PUTs to
   it with its own httpx client for the same reason. One client is
   constructed, handed to `LangfuseAPI` and used for the PUT, so there
   is one HTTP stack and one timeout.
3. **`_Sdk` is public as `Sdk`.** It is the module's test seam, the
   shape `build_telemetry(exporter=...)` established, and a support
   module reaching an underscore name would have been the review flag
   the design guide names.
4. **The failure classification reads the exception's CLASS as well as
   its status code.** The generated client raises a typed error
   carrying no status code at all for each status it names (401, 403,
   404, 405), so a classification that read the code alone reported
   every rejected credential as an endpoint nobody could reach. Found
   while writing the integration lane, and the unit case for `refused`
   plants an error with no code because of it.
5. **A session id that cannot be a directory name is refused on the
   module's own logger rather than as an event.** That event carries a
   `SessionId`, and an id this refuses is by definition not one, so
   there is no lawful event to say it with. The ids this server mints
   are hex, so nothing real reaches it; the guard exists because a
   separator arriving as a session id is the one way a name could reach
   outside the staging root.
6. **`too_large` has a server-side ceiling as well as a far-side one.**
   `MAX_ATTACHMENT_BYTES` is 512 MB, past which this server does not
   ask. The default per-session capture bound is about 57 MB of stereo
   16 kHz, and an operator may raise it.
7. **The reference is a span rather than an ingestion request**, for the
   reason under "Playability" below: the ingestion route refuses a trace
   upsert on a current self-hosted deployment and names OTLP as the
   supported path. The review round's suggested shape was the request;
   the evidence says otherwise, and the span is cheaper on every axis.
8. **The closed set has nine members rather than eight.**
   `unreferenced` is the ninth, for a recording whose bytes landed with
   nothing pointing at them.

### The review round, and what it changed

Five P1s, all genuine, and two of them changed a decision rather than a
line.

1. **One quieting claim for the process, not one per uploader.** The
   uploader built a `Quieting` of its own, which is the one way to get
   that class wrong: overlapping uploaders are routine, because a wedged
   worker outlives its shutdown's bound and a redeploy builds the next
   one behind it. A's release would then restore the original logging
   while B was still uploading, putting B's presigned URL in the
   retained log, and B's own release would restore A's already-quiet
   snapshot and silence the namespaces permanently. The module holds one
   instance now, and the regression case drives the overlap in order.
2. **The cross-field refusal left `TelemetryConfig`.** There it fired
   unconditionally, so a file with the attachment on and capture off did
   not parse at all and the capture-first no-op could never run. That is
   the decision order broken where it matters most: an operator turning
   capture off is mid-toggle, not misconfigured. It went to
   `ServerConfig`, which can see all three keys, and the DELTA round then
   showed that residence had a cost of its own; it is the builder's now,
   and the section below says why.
3. **The sweep answers to the capture SECTION, from in front of every
   boot refusal.** It was `CaptureStore.startup()`, and a store is only
   built where capture is ENABLED, with the uploader's builder ahead of
   it and able to refuse; all four configurations the sweep exists for
   reached neither. It is `sweep_upload_staging(directory)` now, called
   by the composition right after the event hub, and the four boots are
   composition-level cases with a job staged before each.
4. **`LANGFUSE_BASE_URL` is gone.** The SDK's tracing client honors it
   ahead of `LANGFUSE_HOST`, but that client is not the one this uses,
   nothing here documented the alias, and a variable an operator never
   wrote taking precedence over the one they did is a way for room audio
   to reach a deployment nobody named.
5. **The attachment is playable**, which is the section below.

Two things the round did not ask for and the work found. Binding
`SpanContext` to `self._context` shadowed a method of that name and
silently stopped the exporter making stage spans; the integration lane
caught it and twenty-seven unit cases would have. And `Receiver` with
its two readers moved from the export suite into
`tests/support/telemetry.py`, because a second suite needs them and
`test_support_boundaries.py` refuses a test module that imports
another.

### Tests

`tests/unit/test_capture_upload.py`, forty-eight cases, with the far
side faked at `Sdk` and nothing else faked: real hardlinks on a real
filesystem, the real bounded queue, the real daemon worker, the real
retries and the real classification. `tests/support/uploads.py` holds
the seam and the recorder behind it.

Six properties were watched red against a deliberately broken tree, and
**two of those mutations survived the first version of their case**,
which is the part worth recording:

- The prune-survival case first drove a storm over a single recording,
  and `prune()` never drops the newest finished capture, so the storm
  bit nothing and the REFUTED design (staging at the session's close)
  passed it. With a second, later recording in the directory the storm
  really unlinks the early-finished triplet, the case asserts that it
  did, and the refuted design fails.
- The lease case first observed the namespace at the client's
  construction, which passed a mutation that took the lease one line in
  front of that constructor. It observes at the first thing the worker
  does for a job now, which kills it.

The four that failed their case first time: the sweep adopting a job
younger than the process, a dropped job keeping its links, an
incomplete capture being staged anyway, and a refusal being retried.
The two concurrency cases (the full backlog and the max-sessions drain
with the backlog already occupied) were run six times over.

`tests/integration/test_capture_upload.py` carries the three claims the
unit lane cannot make: the whole path against a media endpoint on a
socket in this process, driven by a real device conversation through
the real close ordering; the blackhole, with the three latencies
asserted separately; and the real-SDK late-failure sentinel, with a
credential in the SDK's environment and an endpoint that fails after
the bounded shutdown has given up.

`tests/integration/test_tier_closure.py` gains the fifth tier's own
environment, its closure comparison, a bite, the serve-half negatives,
the positive import, the overlap with `[otel]` written down, and the
extra-less refusal boot in the one environment it is reachable in:
`[serve,otel]`, because a `[serve]` install asked for telemetry refuses
for the OTEL extra first.

The catalog vocabulary is M2's recorded design unchanged, landed here
with its three drivers. The baseline was watched red on exactly the
assertion M2 recorded before the drivers existed.

### The delta round: the refusal moved once more

One P1 and one P2, both genuine.

**The rule is the builder's, not a validator's.** Putting it on
`ServerConfig` fixed the capture-off no-op and introduced a subtler
version of the same class of bug: a model validator raises while the
file is being PARSED, so the one configuration whose refusal is about
the attachment (capture on, the exporter off) never reached a
composition, and the staging sweep that runs in front of every other
refusal did not run for it. A previous run's staged room audio stayed on
disk in exactly the configuration an operator writes to stop exporting.

Two shapes were on offer: catch the `FieldProblemsError` at composition
after sweeping, or move the rule into the builder. The builder, because
the sol round's own finding already offered it ("or perform it in the
builder"), because catching a parse error after the fact means the
loader's refusal path and the composition's would both have to know
about this one rule, and because it puts all three of the attachment's
refusals in one place and one documented order.

What that costs is the row in the reference's cross-field section, which
publishes only refusals a model validator provably raises: the registry
is checked by provoking each row through `model_validate`, so a row
whose rule is not a validator cannot be held to anything. It is not a
loss of documentation. The `attach_captures` field's own prose already
says the attachment needs `enabled` and is refused at boot without it,
and no other builder refusal in this repository is in that section
either: not the missing extra, not either egress refusal. The registry's
comment now says why this one is not.

Three cases, all red against the validator: the refused configuration
PARSES, which is the finding from the loader's end; neither model
refuses it, asserted on both because the rule has lived on each and a
validator returning to either would silently stop the sweep; and the
boot matrix's fifth row, a staged job with capture on, the attachment on
and telemetry off, with the sweep proven to run and the refusal
preserved.

**And the description said the wrong thing about the credentials.** It
said the three `LANGFUSE_*` variables are ones "the SDK reads", which
was true of the design the plan wrote and stopped being true with
deviation 1: the generated REST client takes its base URL and its
credentials as arguments, so this module reads them. The sentence had
reached the generated reference, the example config and the
observability map. All four now say what is true and keep what matters:
transport credentials read from the environment, never a vinga
configuration key, never stored, never rendered back, with the OTLP
half's own attribution spelled out beside them because that one IS read
by its SDK.

### The live walkthrough

Self-hosted Langfuse again, the M1 stack on project
`vinga-67-langfuse`, the same `LANGFUSE_INIT_*` provisioning and the
same remapped ports, plus `LANGFUSE_S3_MEDIA_UPLOAD_ENDPOINT` so the
presigned URLs point at a MinIO the host can reach. The server ran with
capture on, telemetry on and `attach_captures` on, both variable
families pointed at the one deployment and the one project, which is
the invariant the review's finding 11 asked to be held rather than
assumed.

```
docker compose -p vinga-67-langfuse up -d --wait
curl -s http://localhost:53010/api/public/health
#  {"status":"OK","version":"4.35.0"}

VINGA_DB_PORT=55673 docker compose -p vinga-67m3 up -d postgres --wait

LANGFUSE_HOST=http://localhost:53010 \
LANGFUSE_PUBLIC_KEY=$PK LANGFUSE_SECRET_KEY=$SK \
OTEL_EXPORTER_OTLP_ENDPOINT=http://localhost:53010/api/public/otel \
OTEL_EXPORTER_OTLP_HEADERS="Authorization=Basic <base64 pk:sk>" \
  <one recorded simulator conversation>
#  capture bc873d61af0e4a34b6107a8a4ebfeba5, staging empty afterwards
```

What the instance then held, read through its own APIs:

```
GET /api/public/v2/observations?sessionId=bc873d61af0e4a34b6107a8a4ebfeba5
  6 observations: session (root, trace 346ac4a7...),
                  turn (root, trace 4f3f0417...), asr, llm, tts_stream, playback

select m.id, tm.trace_id, tm.field, m.content_type, m.content_length,
       m.upload_http_status from trace_media tm join media m ...
  jFz9MlxuwO_R1n_1oz5H_B | 346ac4a7... | metadata | application/json |   1258 | 200
  HApOlHzawOpXJvESB25s6X | 346ac4a7... | metadata | audio/wav        | 173464 | 200

GET /api/public/media/HApOlHzawOpXJvESB25s6X
  {"contentType": "audio/wav", "contentLength": 173464,
   "uploadedAt": "...", "url": "http://localhost:59090/langfuse/media/vinga-67/...",
   "urlExpiry": "..."}
```

The downloaded WAV is byte-identical to the capture on disk, and opens
as a two-channel 16 kHz file of 43355 frames, 2.71 s, which is the
duration the manifest states. The manifest downloaded through the same
API has `complete: true` and the same eleven top-level keys the local
one has. Both attachments are against the SESSION trace, which is the
trace `trace_of` retains and the one the session grouping keys on.

Torn down afterwards with `docker compose -p vinga-67-langfuse down -v`
and `docker compose -p vinga-67m3 down -v`. Nothing Langfuse-shaped is
committed.

**Playability, and how it was settled.** The first version of this
milestone uploaded the pair and stopped there, and recorded that the
acceptance's "playable in the UI" could not be claimed: M1 established
that what makes a media record RENDER is a reference token in a trace's
or an observation's own field, and by the time a capture is final the
span it would go on has been ended and exported. The review round called
that the milestone not delivering what it was for, and it was right.

The mechanism was settled by the backend rather than chosen. The
candidate was a trace upsert through the ingestion API, and a current
self-hosted deployment refuses it:

```
POST /api/public/ingestion  ->  207
{"successes":[],"errors":[{"id":"e1","status":400,
  "message":"Event type not accepted",
  "error":"Event type \"trace-create\" is not accepted by
   /api/public/ingestion when LANGFUSE_MIGRATION_V4_WRITE_MODE is
   events_only. This endpoint only accepts score and log events.
   Upgrade the client or integration to a v4-compatible SDK or OTLP
   ingestion path. ..."}]}
```

`events_only` is the default write mode for self-hosted v4, and the
refusal names the supported path: OTLP. Which is a path this server
already owns, so the reference needs no second transport, no second
credential and no second timeout, and the reviewer's instruction to
bound an extra request with the timeout-and-retry discipline turned out
to have nothing to bound: there is no extra request.

So `Telemetry.reference_media(session, references)` writes ONE span in
the trace the session was exported under, as a child of that session's
span, carrying each token under its own
`langfuse.observation.metadata.<name>` key and all of them in
`langfuse.observation.output`. Two spellings because the backend
resolves a reference wherever it finds one and the two render
differently, and both were confirmed live. The retention now holds the
session span's identity as well as its trace id, because a span written
after every span of a trace has ended needs its parent's identity rather
than a rendering of half of it.

It answers False for a session this exporter never saw, one aged out of
the retention, and an exporter that has stopped accepting, and the
uploader reports a False as `capture_upload_failed` with the closed
set's ninth member, `unreferenced`: bytes that landed with nothing
pointing at them are the gap this surface exists to close wearing a
success, and `capture_uploaded` would overclaim.

**A note about the vocabulary rule.** `telemetry.py` says that nothing
it writes can say a fact `catalog.py` does not declare. A media
reference is the one exception, and the module states it as one: the
token is not a fact about the conversation, it is an opaque identifier
the BACKEND minted for bytes an operator already authorized to leave,
and no session gets one unless `attach_captures` is on.

**What was verified live, on the re-run.**

```
GET /api/public/v2/observations?sessionId=<session>&fields=io,metadata
  7 observations. One of them, in the SESSION trace (1f16e6fa...) and
  parented on the session span (64bef03c...):

  output:   @@@langfuseMedia:type=audio/wav|id=QCtzrxSW5nQtsPfFuf9GD3|source=bytes@@@
            @@@langfuseMedia:type=application/json|id=YISgYI1gwBJDV4UPrdCVvR|source=bytes@@@
  metadata: capture_audio, capture_manifest, both carrying their token

select m.id, tm.trace_id, m.content_type, m.content_length,
       m.upload_http_status from trace_media tm join media m ...
  YISgYI1gwBJDV4UPrdCVvR | 1f16e6fa... | application/json |   1265 | 200
  QCtzrxSW5nQtsPfFuf9GD3 | 1f16e6fa... | audio/wav        | 173676 | 200

GET /api/public/media/QCtzrxSW5nQtsPfFuf9GD3  ->  a download URL
  the file behind it: 2 channels, 16 kHz, 43408 frames, 2.71 s, and
  byte-identical to the capture on disk
```

So the tokens a reader meets in the trace name exactly the two records
the upload made, and the ids in them resolve. What remains outside this
record is the rendering itself, which is a claim about a browser: the
token is the documented and confirmed mechanism, it is in the two fields
the backend reads it from, and the asset it names is downloadable and
decodable. Nothing here asserts a pixel.

### Verification

- `uv run ruff check .`: All checks passed!
- `uv run mypy` (strict over `src/vinga_server/events`): Success: no
  issues found in 5 source files
- `uv run pytest tests/unit -q -n 4 --dist loadfile`: 6995 passed, 19
  skipped (6907 in M2, plus this milestone's eighty-eight)
- `uv run pytest tests/integration -q`: 324 passed, against Postgres
  from the committed compose file on `VINGA_DB_PORT=55673`
- `python3 scripts/fold_changelog.py check .`: checked 1 fragments, 0
  failures
- `python3 scripts/check_doc_links.py .`: checked 232 files, 0 failures
- `uv run pytest tests/unit/test_command_spellings.py -q`: 52 passed
- Both generated documents regenerated and unchanged after the commits
  that changed them (`config reference server`, `events reference`)
- The live walkthrough above, recorded rather than asserted, with the
  UI-playability claim left unmade for the reason stated
