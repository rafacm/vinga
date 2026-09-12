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
