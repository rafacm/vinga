# vinga-server

The Vinga conversation server (Python): a wire-compatible backend for
[78/xiaozhi-esp32](https://github.com/78/xiaozhi-esp32) devices, written
against the firmware's
[protocol docs](https://github.com/78/xiaozhi-esp32/blob/main/docs/websocket.md);
the device-token scheme follows
[xinnan-tech/xiaozhi-esp32-server](https://github.com/xinnan-tech/xiaozhi-esp32-server).

It implements the two endpoints a device needs:

- **HTTP OTA/config endpoint** (`/xiaozhi/ota/`): the device POSTs its
  identity and receives the WebSocket URL (and optionally firmware updates).
- **WebSocket endpoint** (`/xiaozhi/v1/`): the conversation channel,
  carrying Opus audio frames up, JSON control messages both ways, and Opus
  audio back.

Behind the WebSocket sits the conversation pipeline: VAD segments speech,
ASR transcribes it, the LLM streams a reply, and TTS speaks it back
sentence by sentence, every stage a pluggable provider chosen per agent.
Agents reach tools over MCP, both their own servers and the device's own
controls.

Those four acronyms are the vocabulary of the whole configuration, so in
full:

| Stage | | What it does |
| ----- | - | ------------ |
| `vad` | voice activity detection | Decides where speech starts and when the user has stopped, so the rest of the pipeline runs on an utterance rather than on a stream |
| `asr` | automatic speech recognition | Turns that utterance into text. Also called speech to text |
| `llm` | large language model | Writes the reply, and asks for tools |
| `tts` | text to speech | Turns each sentence of the reply back into audio |

They run strictly in that order, each waiting on the one before it, which
is why the latency of any one of them is latency the user hears.

Those two paths, the two probes `/healthz` and `/readyz`, and the
configuration API under `/api` are
everything the server exposes: the interactive API docs are turned off,
the WebSocket requires a device token the OTA endpoint issued, and every
request to `/api` carries a bearer token.

## On this page

- [Goals](#goals): what this server is for, and what it refuses to become.
- [Applying a change without a restart](#applying-a-change-without-a-restart): installing a stored change on the running server, and when a conversation sees it.
- [Stack](#stack) and [Development](#development): what it is built on, and the two lanes a change is exercised in before it ships.
- [Configuration](#configuration): the store, the API in front of it, and where a credential lives.
- [Security](#security): the defaults, the tokens, and what is exposed to whom.
- [Listening and barge-in](#listening-and-barge-in): how a turn ends, and what it takes to interrupt a reply.
- [Masking reply latency](#masking-reply-latency), [When a reply fails](#when-a-reply-fails), and [When a model writes a tool call into its speech](#when-a-model-writes-a-tool-call-into-its-speech): the three things that go wrong between a model and a speaker, and what the server does about each.
- [Logging](#logging) and [Capturing a session](#capturing-a-session): what a running server says about itself, and how to record a conversation for study.
- [What a conversation cost](#what-a-conversation-cost): the usage each stage reports, and the model definitions a backend needs before it can price them.
- [The conversation store](#the-conversation-store): what is kept of a turn after it ends.
- [Running in a container](#running-in-a-container): a pointer to the task guides in [`docs/run/`](../docs/run/README.md), which cover the image, its database, its limits and exposure, upgrading, recovery, onboarding a device, and choosing the providers, tools, memory and prompt an agent works with.
- [Status](#status): what works today, and what is still a promise.

## Goals

- Python, and one Postgres database holding everything this server
  stores: the domain half of the configuration in a `domain` schema,
  and the conversation record, when it is turned on, in a
  `record` schema beside it. Both are migrated at every boot,
  so a blank database is a valid state to start on and there is no
  init command to forget
- Configurable providers:
  - **LLM**: Anthropic, any OpenAI-compatible endpoint (Ollama, LM Studio,
    gateways)
  - **ASR**: local (faster-whisper) or cloud (OpenAI, and anything
    speaking the same dialect)
  - **TTS**: pluggable engines as optional extras (Piper)
  - **MCP**: attach any MCP servers as tools for the assistant, alongside
    the device's own
- Distributed as a multi-arch container image, deployable on your own
  infrastructure

## Applying a change without a restart

A running server serves one immutable snapshot of the domain half at a
time, so writing an entry and granting it to an agent used to cost a
restart and every conversation on the server. `vinga-server config
apply` builds the next snapshot and swaps to it instead:

```console
$ vinga-server config mcp-server set weather -f weather.yaml
wrote mcp-server weather
stored, not serving yet: run `vinga apply` to install it on the
running server, and `vinga diff` to list everything pending.
$ vinga-server config agent set house -f house.yaml
$ vinga-server config apply
mcp:
  connection started: weather
  connection kept: home
prompts:
  changed: house
fillers:
  filled pause kept: house, kids
providers:
  engine kept: asr.ears, llm.local, tts.voice, vad.gate
agents:
  added: house

home: connected since 2026-08-13T09:12:03.104213+00:00
  tools: home__turn_on_light, home__turn_off_light
  agents: house, kids
weather: connected since 2026-08-13T11:02:44.118902+00:00
  tools: weather__forecast
  agents: house
the stored configuration is installed and serving.
```

What it prints is what it did: an outcome with no name under it and a
kind with no outcome are absent rather than listed as empty, and the
words are the ones an operator uses rather than the field names of the
layer that did the work. An apply that moved nothing says so in one
sentence instead. The last line is on stderr, where a fact about this
invocation belongs, and it is the full stop: the command that changes
what the server is serving says that it did. The MCP status block above
it is printed only where there are entries to say something about; how
to configure one is what `mcp-server status` answers. The answer's own
field names are the API's and do not move: `POST
/api/runtime/config/reload` is the same document it was.

**An apply that is refused** says that the stored configuration was
refused and deliberately not where: a sentence composed over stored
state can quote a value somebody wrote into the wrong field, so a
reload's answer never carries one. Where is answered by
`vinga-server config check`, which reads the store the way a boot reads
it and prints the sentence a server started on it would refuse with,
naming the entry and the rule and no value. It runs on the server host,
serves nothing and writes no configuration, though it is not read-only:
a boot's read migrates the store, and this is a boot's read.
[`../docs/reference/cli.md`](../docs/reference/cli.md) is where it is
documented.

`config import` is the other half of the pair rather than a shortcut
past it: it writes a whole deployment to the store in one transaction
and stops there, and this is the command that installs what it wrote.
Two commands rather than one, which is what a rebuild needs anyway,
since a document's credentials go in between them. The per-entity
writes say which boundary they are waiting at for the same reason,
because nothing installs one until somebody asks. The boundary is what
travels between the two halves, as a token: a server ships in an image
and cannot know the grammar of the client somebody has installed beside
it, so it states the boundary, and the client says the whole of it in
its own words wherever it recognizes the set. A boundary the client
cannot name, which is what one from a newer server arrives as, is
answered with the server's sentence quoted instead.

**What it applies** is the whole domain half, re-read from the
configuration database: the `providers` entries and the `mcp_servers`
entries with the secrets stored on them, the agents' effective `mcp`
grant lists (`agents.<name>.mcp` and `agent_defaults.mcp`), the shared
`prompt_fragments`, the agents themselves and the `agent_defaults`
layer under them. An MCP entry that is new or newly referenced is
started, one whose fragment or whose stored secrets changed is stopped
and rebuilt (so rotating a credential applies here too), one that is
gone or no longer referenced is stopped, and an unchanged one keeps the
connection it had, untouched. The MCP outcomes come back with the status
document, so one command both applies and verifies, and the sections for
the kinds a later release will apply are named rather than missing.

An entry whose `instructions` is all that changed keeps the connection
it had (`unchanged` in the answer, a connection kept in the listing),
and that is a statement about the connection: nothing was reconnected,
and the new guidance is what the next activation reads. That is
deliberate. The
text configures a prompt and not a connection, so dropping a live one
to apply it (mid-call tools, a respawned stdio child) would be churn
without a cause.

**Filled pauses are re-synthesized, and only where they had to be.** A
clip is a configured phrase spoken by a configured voice, and the unit
of comparison is the whole effective `filler` section: an apply keeps
every clip whose section and whose voice are what they were, and
synthesizes the rest. So an edit to a prompt sends nothing to a
text-to-speech engine, and neither does an edit to a provider entry no
masked agent speaks through; but an edit to any field of the section
does, `delay_ms` included, even though the
audio that comes back is identical to what it replaced, and so does
rewriting the entry an agent's voice comes from, whose clips are spoken
again in the engine the apply built. That is
deliberate rather than an oversight: the section is one value, and a
comparison that covered part of it would be a second rule about what a
clip depends on. Synthesis is real work at the configured provider, and
may be billed there, so an apply of a deployment with many masked agents
costs what this says it does. The
`fillers` section names each agent under one of three outcomes, and an
agent whose synthesis failed is `disabled`: the apply installed, that
agent runs with the mask off, and the next apply tries again. A
text-to-speech hiccup never holds back a prompt fix.

**The engines are rebuilt, and only the ones that moved.** An entry
whose definition and stored credential are what they were is carried
into the new world as the object it already was, so an edit to a prompt
reloads no local model and rotating one provider's key does not touch
another's. A rewritten entry is built while the old one is still
serving, and the conversations that open after the apply speak through
the new one; one that a conversation is still speaking through is
released when that conversation ends, so applying a change to a local
model briefly holds two of it. The `providers` section names the entries
built, reused and retired. An entry that will not build, or that
`server.data_boundary` forbids, refuses the apply with nothing changed.

**The agent set moves with the rest.** An agent the store has added is
built with everything else the apply builds and is servable the instant
the request answers, so a device bound to it reaches it at its next
check-in with no restart between the write and the board; an agent it
has deleted is one no session can be opened as from that same instant,
while a conversation already talking as it finishes on the world it was
built from and is served that world's prompt to the end. The `agents`
section names both, and says whether `agent_defaults` moved. The one
thing an agent carries that an apply does not move is its memory, which
is keyed by its name, so the rows stay under the old name. The whole
`server` section (including the configuration file itself) is
start-time as it always was.

**No session is dropped**, and when one meets the change depends on
which half moved. The tools an agent may reach are snapshotted per
reply, so a conversation in progress meets the new tool world on its
next utterance; a tool call in flight on a server the apply stopped
fails into the same error result a server dropping mid-call produces,
which the assistant explains in its own words. Prompt text is assembled
once per activation and cached for it, so a rewritten prompt, fragment
or `instructions` reaches a conversation at its next activation, which
is a new session or an agent switch, and never mid-reply. Filler clips
are bound by a conversation when it opens, so a re-synthesized one
reaches the next conversation rather than changing what an open one is
masking with.

**Nothing is half applied.** The whole new world is composed, validated
and built before anything running is touched, so an unset `$VAR`, a
credential that will not decrypt, an entry `server.data_boundary` forbids,
or a stored configuration that will not compose into something this
server can serve refuses the apply and leaves it exactly as it was. A
server that merely will not connect is not that: it applies, shows
`down` with its reason, and is reconnected in the background like any
other. One apply runs at a time; a second is refused with the retryable
409 a contended write answers with, having changed nothing.

Over the API it is `POST /api/runtime/config/reload`.

## Stack

Python 3.12 with [FastAPI](https://fastapi.tiangolo.com), managed with
[uv](https://docs.astral.sh/uv/). Pydantic models validate both halves
of the configuration, the YAML file and the rows of the Postgres
database behind `vinga-server config` (SQLAlchemy Core over psycopg 3,
Alembic migrations run on open); the same types and the same repository
back the configuration API, of which the command grammar is a client.
Integration tests
drive the server with the [xiaozhi-sdk](https://pypi.org/project/xiaozhi-sdk/)
device simulator, so CI holds real conversations without hardware. The wire
protocol is kept isolated behind a small interface, separate from the
conversation pipeline.

## Development

```bash
# From the repository root: the Postgres both stores live in. The
# server refuses to boot on a database it cannot reach, so this comes
# first, and --wait is what makes "first" mean ready rather than
# started.
docker compose up -d --wait

# The rest, from vinga-server/:
uv sync                             # install dependencies, server half included
uv sync --extra faster-whisper --extra piper  # add the local ASR/TTS engines
uv run vinga-server                # run the server
uv run pytest tests/unit -q         # unit tests
uv run pytest tests/integration -q  # integration tests
uv run ruff check .                 # lint

# What CI runs both lanes as: distributed over worker processes,
# a file at a time. Reach for them to reproduce a failure that only
# shows up in CI. Local runs are serial by default.
uv run pytest tests/unit -q -n auto --dist loadfile
uv run pytest tests/integration -q -n auto --dist loadfile
```

**A Postgres is a prerequisite of running the server at all**, because
every schema it stores its state in lives in one, and the compose service at
the repository root is the development instance. Its defaults are the
server's own defaults (`127.0.0.1:5432`, database `vinga`, role
`vinga`, password `vinga`), so a checkout needs no configuration for
any of it, and the password being shipped in the open is exactly why
the service is published on loopback and nowhere else. Starting it
also runs [`../deploy/postgres-init.sql`](../deploy/postgres-init.sql)
once, which creates the three schemas and the read-only `vinga_ro` role
the conversation record is read through; the tables inside them are
Alembic's, made by the server on its first boot. `docker compose down
-v` throws the whole thing away, and the next `up` rebuilds it from
nothing.

That file also carries the server itself, behind a `server` compose
profile, which is what the project README's quick start starts. The
profile is what keeps the two apart: the command above selects no
profile and so starts the database alone, exactly as it always has,
and `docker compose --profile server up -d --wait` starts the
published image beside it. A checkout that runs the server from source
wants the first; there is nothing to opt out of.

The test lanes use that same instance, and refuse to run rather than
skipping when they cannot reach it, so a suite that has stopped
exercising storage cannot read green. They create databases of their
own to isolate a run, which is why the lane wants a role that may
create them (the compose superuser is one) while the server itself
never needs that privilege.

`uv sync` with no flags is deliberately the whole of it. The package's
default install is the configuration CLI, and the server half is the
`serve` extra; the dev dependency group names that extra, so a checkout
gets a runnable server from one command and there is no tier to
remember. The extras above are the two optional local engines, which is
what an extra flag is still for.

The test lanes run the whole pipeline on the built-in mock providers, so
they need no keys, no model downloads, and no network.

### The local lane: a real conversation

CI never touches real engines. To check the overall work with them, an
opt-in third lane holds one real conversation end to end: it starts a
real server on the fully local pipeline (Silero, faster-whisper, Ollama,
Piper), speaks a Piper-synthesized question through the device simulator,
and asserts the transcript and a coherent spoken reply.

```bash
uv sync --extra faster-whisper --extra piper
VINGA_LOCAL_LANE=1 uv run pytest tests/local -q
```

The run ends with a summary of the conversation it held, so a pass shows
its work rather than a green dot:

```
=========================== local lane conversation ============================
pipeline: silero + faster-whisper small + qwen3:8b + en_US-lessac-medium
question: "What is the capital of Sweden?" (1.6 s of audio)
heard   : "What is the capital of Sweden?" (+1.2 s)
reply   : "The capital of Sweden is Stockholm." (first sentence +3.8 s, 2.0 s of audio)
```

A pre-flight check runs first and fails with the command that fixes
whatever is missing (extras not installed, no Ollama answering, no usable
model). By default it talks to Ollama at `localhost:11434` and prefers
`qwen3:8b`, falling back to the first installed model;
`VINGA_LOCAL_OLLAMA` and `VINGA_LOCAL_LLM_MODEL` override both. The
first run downloads the whisper model and Piper voice at server startup
and can take a few minutes; later runs finish in seconds. Without
`VINGA_LOCAL_LANE=1` the lane skips, so a bare `pytest` stays safe.

### The smoke lane: a conversation with a container

A fourth lane runs nothing itself. It points at a server that is already
up and holds one whole conversation with it: both probes, an OTA check whose
token it verifies, and a full utterance-to-audio exchange through the
device simulator. CI runs it against the image it just built, seeding
that image's own CLI into the database it then reads, which is what
turns "a seeded database and one `docker run` serve a conversation"
into something checked rather than remembered.

Both containers below have to reach the same database, and a container
does not reach the development instance at `127.0.0.1`, since that
address is its own. Join them to the network compose made for it
(`docker network ls` lists it as your project's `_default`) and name
the service instead, which is what `VINGA_DB_HOST` is doing here; CI
does the same thing with a network and a database container of its
own.

```bash
docker build -t vinga-server:local .

# The network compose made for the database, named after the directory
# the compose file is in: `docker network ls` says which it is.
net=vinga_default

# The domain half first, written by the CLI from the image itself into
# the database the server then reads. tests/smoke/seed.sh is what CI runs:
# it starts a server of its own inside this container, configures it over
# loopback, and stops it again, which is why the container gets what a
# server needs.
docker run --rm --network "$net" \
  -e VINGA_AUTH_SECRET=smoke-secret \
  -e VINGA_API_SECRET=smoke-api-token \
  -e VINGA_DB_HOST=postgres \
  -v smoke-data:/data \
  -v "$PWD/tests/smoke:/smoke:ro" \
  -v "$PWD/tests/smoke/config.yaml:/config/config.yaml:ro" \
  --entrypoint sh vinga-server:local /smoke/seed.sh

docker run -d --name vinga-smoke -p 8003:8003 --network "$net" \
  -e VINGA_AUTH_SECRET=smoke-secret \
  -e VINGA_API_SECRET=smoke-api-token \
  -e VINGA_DB_HOST=postgres \
  -v smoke-data:/data \
  -v "$PWD/tests/smoke/config.yaml:/config/config.yaml:ro" \
  vinga-server:local

VINGA_SMOKE_OTA_URL=http://127.0.0.1:8003/xiaozhi/ota/ \
VINGA_AUTH_SECRET=smoke-secret \
  uv run pytest tests/smoke -v
```

The secret has to match the one the server under test was started with:
the lane verifies the token it is issued, and that needs the signing key.
It skips without `VINGA_SMOKE_OTA_URL`, so a bare `pytest` stays safe,
and it works against any reachable server, not only a container.

## Configuration

Configuration comes in two halves, kept in two places for one reason:
how the process runs is decided when it is deployed, and what it says
and to whom is decided while it runs.

**The server half is one YAML file.** `server:` (host, port, auth,
onboarding, limits, logging, capture, which database to connect to).
It is passed as
`--config /path/to/config.yaml` or through the `VINGA_CONFIG`
environment variable; with neither set, defaults apply, and it is
handled by
[pydantic-settings](https://docs.pydantic.dev/latest/concepts/pydantic_settings/).
[`../docs/reference/server-config.md`](../docs/reference/server-config.md)
is the complete contract: every key with its type, default, bounds and
description, the environment overrides, and the combinations refused at
boot, generated from the models by `vinga-server config reference
server` and diffed by CI.
[`config.example.yaml`](config.example.yaml) is the annotated starting
point to copy, with a comment per key in its own voice,
and [`config.deploy.example.yaml`](config.deploy.example.yaml) is a
ready-to-adapt profile for the container image behind a proxy on a small
CPU quota, holding values validated by latency measurements from a live
deployment. That profile's domain half is the runnable script beside it,
[`config.deploy.example.sh`](config.deploy.example.sh), which the test
suite runs against a real server, so its measured values are checked
rather than merely written down.

**The domain half lives in a database**, the `domain` schema of the
Postgres database `server.database` names, written with the `vinga`
CLI: named `providers` per stage (`llm`, `asr`, `tts`, `vad`), named
`mcp_servers`, named `prompt_fragments` holding the blocks of prompt
text agents share, `agent_defaults` holding what every agent uses
unless it says otherwise, `agents` combining a prompt with provider,
fragment and MCP references, `devices` binding MAC addresses to agents,
and `default_agent` for unknown devices.

The CLI writes it through the configuration API on the running server,
so these commands need one to be up, and an empty database is a valid
state for it to be up on. `vinga` is that CLI installed as a tool of its
own, which is the ordinary way in: install it on whichever machine
administers this deployment, name the API in `VINGA_API_URL` and carry
the token in `VINGA_API_SECRET`. The image ships the same client under
the server's own entry point, so a shell inside a running container
reaches it with the token and the loopback address already in its
environment, which is the alternative for a deployment that does not
route its API outward.
[`../docs/reference/cli.md`](../docs/reference/cli.md) is the CLI's own
page: installing it, reaching a server, rebuilding one, and every
command's help.

A whole deployment, from an empty database, is one document and two
commands. [`examples/presets/`](examples/presets/) holds two of them, a
deployment that reaches no vendor and the same thing on vendor APIs:

```bash
vinga import -f examples/presets/cloud-stack.yaml
vinga apply
vinga device bind aa:bb:cc:dd:ee:ff assistant
vinga list
```

Importing orders the writes for you. A write whose references do not
resolve is refused, which is what forces the creation order when
entities are written one at a time; a document is validated against the
state it would leave and written in one transaction, so the providers,
the defaults naming them and the agent inheriting them all arrive
together and nothing is ever half written. Importing is additive and
never deletes, and the same document twice changes nothing. What it
does not do is touch the running server: that is the `apply` on the
second line, which is
[Applying a change without a restart](#applying-a-change-without-a-restart),
and the gap between the two is where a document's credentials go.
[`examples/`](examples/) holds a commented fragment per entity for
writing one at a time with a noun's own `set`, which is what editing a
deployment looks like once it exists.

A board in front of you needs neither its MAC nor that `device bind`
line: `config device pending list` lists what is waiting and `config device pending claim`
binds one by the code on its screen. That is
[Onboarding a device](../docs/run/onboarding-a-device.md).

The rules about a runnable server (every stage of every agent
resolving, a default agent when nothing is bound) are checked at boot
rather than at write time, so a half-built database is a legitimate
state to be in and an illegitimate one to serve from.

**When the server will not start**, there is nothing to write through,
and the way back is to rebuild the store rather than to operate on it:
stop the server, delete the database, boot clean, import the export
taken while the deployment was healthy (`import -f`), re-enter the
credentials that export listed, and apply. That is
[Recovering a deployment that will not start](../docs/run/recovering-a-deployment.md),
in the task guides.

Every field of the domain half is documented in
[`../docs/reference/domain-config.md`](../docs/reference/domain-config.md),
generated from the models: `vinga-server config reference` prints that
same document, `vinga-server config reference server` prints the server
half's page beside it, and `vinga-server config schema [entity]` prints
the JSON Schema behind the domain one. The command line itself is
[`../docs/reference/cli.md`](../docs/reference/cli.md), whose command
pages and recipes are generated the same way, by `vinga-server config
cli-reference`. [`examples/`](examples/) holds a commented fragment per
entity and provider type, each naming the command that installs it, and
that is where the measured numbers and the field findings behind each
provider option are kept. `config list` and `config show` read back what
is stored, with every secret masked, and `config export` prints the same
content as a document `config import` takes back.

**The `server` section is what a start reads.** The port, the
directories, the limits and the barge-in tuning come out of the file
this process was launched with, and a change to any of them is picked up
when it is restarted. Nothing in the database is in that half.

**What a running server serves of the domain half is a generation:** an
immutable snapshot, validated whole, built entirely before anything
binds it. There is more than one of them over the life of a process, and
applying a change installs the next one rather than editing the one in
place, so a conversation goes on speaking the world it opened in while
new work binds the world that is current. A change reaches it in one of
two ways, and every mutating command says which.

**The apply installs the domain half, on request.** Writing a provider
entry or an MCP entry, rotating a secret on either, changing which
agents may reach an MCP server, editing a prompt fragment, writing an
agent, deleting one, or rewriting the `agent_defaults` layer under them
all takes effect when a running server is asked to install what is
stored, with no restart and no session dropped: that is [Applying a
change without a restart](#applying-a-change-without-a-restart). Those
writes name `vinga-server config apply`, whose own help says the three
moments a conversation already in progress meets an installed change
at: the tools an agent may reach at its next utterance, its prompt text
at its next activation, and the voice it speaks in and the clips it
masks with at the next conversation. An agent the apply added is one a
device can be bound to
and reach at its next check-in; one it deleted is one no session can be
opened as from the moment the request answers, while a conversation
already talking as it finishes on the world it was built from. The one
thing an agent carries that an apply does not move is its memory, which
is keyed by its name, so the rows stay under the old name.

**Device bindings are the other way, applied by being noticed.** A
running server reads the devices table and the default agent as a device
asks for them, so
binding a board, unbinding it, or changing the default agent applies
at that device's next OTA check or connection, with nothing asked of
the server at all. Those
writes say so instead. That ends where the agent does: a
binding naming an agent this server is not serving resolves to
nothing until the apply that installs it, and the
acknowledgement says that rather than promising otherwise. A
conversation already running is never touched by either.

Since a voice is a `tts` provider entry, two agents that should sound
different reference two entries, and a typical agent is a prompt plus a
voice. `agent_defaults` takes no prompt: a prompt is what makes an agent
that agent. A device is bound to one agent or to a list of them; with a
list, the first entry is the agent a conversation starts on, and the
rest are the ones `switch_agent` can reach.

Every key of the file half can be overridden with a `VINGA_`-prefixed
environment variable, nested keys joined with `__`:
`VINGA_SERVER__PORT=9000`, `VINGA_SERVER__LOG_FORMAT=text`.
Environment variables beat the YAML file, and a `.env` file in the
directory the server is started from is read at startup (real
environment variables beat `.env` too). This layering matches container
deployments: the YAML arrives as a mounted file, overrides and secrets
as environment variables. The domain half has no environment layer: a
`VINGA_` variable naming one of its sections, like a section left in
the file, refuses the boot and names the command that writes it now,
because a configuration that quietly stopped applying is worse than one
that will not start.

**The database is named by four keys and five variables.**
`server.database` carries `host` (`127.0.0.1`), `port` (`5432`), `name`
(`vinga`) and `user` (`vinga`), which are the compose service's own
values, so a checkout says nothing about any of it. Those four have
short environment names of their own, and those are the documented
spellings, because the compose file feeds the Postgres image from the
same four and a fact with two names is a fact with a disagreement
pending:

```bash
VINGA_DB_HOST=db.internal VINGA_DB_NAME=vinga_prod uv run vinga-server
```

The generic `VINGA_SERVER__DATABASE__HOST` spelling would otherwise
work by accident of the nesting scheme, so it is refused instead, with
a sentence naming the short one to use.

Two more variables have no configuration key at all, deliberately.
`VINGA_DB_PASSWORD` is the password, which a file that gets committed,
diffed and printed back is the wrong home for; it defaults to `vinga`
to match the compose service, and that default is a convenience on an
instance bound to loopback rather than anything to deploy on.
`VINGA_DB_URL` is the whole connection at once and wins over the other
five when it is set, accepting `postgresql://` and
`postgresql+psycopg://` and refusing everything else, because a second
storage backend is not a thing this server has.

The server reads all of it at boot, and the config commands read none
of it: they are clients of the API, and where the rows are kept is the
server's business.

**A database the server cannot reach is a boot that refuses**, with a
sentence naming those variables and telling a checkout to run `docker
compose up -d --wait`. It is never a traceback, and it quotes nothing
of the connection back, not even the parts that look harmless: a URL
carries a password in its authority and can carry another in its
query, so none of the five travels into a message or a log line.
Restarting is the orchestrator's job rather than the entrypoint's,
which is why the image waits for nothing and simply says why it
stopped.

### The configuration API

The domain half is read and written over a REST API the server mounts at
`/api` on its own port. It is what `vinga-server config` talks to, and
it is the machine-readable way in for anything else. The contract is the
committed OpenAPI document,
[`../docs/reference/api-openapi.json`](../docs/reference/api-openapi.json):
every route, the schema of every body, and the refusals each route can
answer with. It is generated from the routes themselves by
`vinga-server config openapi` and regenerated by CI, so it cannot drift
from what is served. The API itself serves no interactive docs and no
live schema endpoint; the committed file is the contract.

**Every request carries a bearer token.** The API is always mounted and
there is no flag that turns it off, because an admin surface that can be
switched off by forgetting a key is a surface that ships unprotected.
The token is the value of the environment variable
`server.api.secret_env` names, `VINGA_API_SECRET` by default, and a
server started without it refuses to boot, naming the variable and the
fix:

```bash
VINGA_API_SECRET=$(openssl rand -hex 32)
```

Generate it once and keep it where the deployment keeps its other
environment secrets. A request with no token, or with the wrong one, is
answered 401 whichever path it asked for, whether or not that path is a
route: only an authenticated caller gets to learn which routes exist.
One request, for the shape of them:

```bash
curl -sS -H "Authorization: Bearer $VINGA_API_SECRET" \
  http://127.0.0.1:8003/api/config
```

**One noun per entity kind**, addressed the way the entity is keyed (a
provider by its stage and its name, a device by its MAC):

```
GET                 /api/config
GET                 /api/providers
GET PUT DELETE      /api/providers/{stage}/{name}
    PUT DELETE      /api/providers/{stage}/{name}/secrets/{slot}
GET                 /api/mcp-servers
GET PUT DELETE      /api/mcp-servers/{name}
    PUT DELETE      /api/mcp-servers/{name}/secrets/{slot}
GET                 /api/agents
GET PUT DELETE      /api/agents/{name}
GET PUT             /api/agent-defaults
GET                 /api/devices
GET PUT DELETE      /api/devices/{mac}
GET PUT DELETE      /api/default-agent
```

**And one namespace that is not about stored configuration at all**,
kept apart from the entity namespaces because an entity may legally be
named after any word a route might want:

```
GET                 /api/runtime/agents/{name}/prompt
GET                 /api/runtime/config/diff
GET                 /api/runtime/mcp-servers
POST                /api/runtime/config/reload
```

The first answers the system prompt a session opening now as that agent
would be sent, block by block with the size of each, which [What the
model is actually sent](../docs/run/agents-and-prompts.md#what-the-model-is-actually-sent) describes and
`vinga-server config agent preview` prints. The second answers what the
database holds that this server is not serving, kind by kind: the names
added, removed and changed, and for each kind whether its changes reach
a conversation at the next apply or at a device's
next check-in, which is what makes it possible to say whether a write is
still waiting. It carries entity names and those labels and nothing
else, so a rotated credential shows up as the provider that holds it
being listed as changed. The third answers what each configured MCP
server is doing right now, which [What the MCP servers are
doing](../docs/run/tools-and-mcp.md#what-the-mcp-servers-are-doing) describes and `vinga-server
config mcp-server status` prints. The reload route installs what the stored
configuration holds on the running server, which [Applying a change
without a restart](#applying-a-change-without-a-restart) describes and
`vinga-server config apply` prints; it is the only route here that
changes what the server is doing rather than what is stored. The route
keeps the mechanism's name and the command names the act, which is a
deliberate crossing rather than a mismatch.

**And one namespace that reads the conversation record**, the store
[The conversation store](#the-conversation-store) describes:

```
GET DELETE          /api/sessions
GET DELETE          /api/sessions/{session}
GET                 /api/sessions/{session}/turns
GET                 /api/conversations
GET DELETE          /api/conversations/{conversation}
GET                 /api/conversations/{conversation}/turns
```

The first lists the sessions, newest first, filtered by `?device=` when
given. The second is one session whole: its row, with how many turns and
events hang off it. The third is one session's turns, oldest first, each
carrying its numbers and the tool calls it made nested in the order the
model issued them. The list and the timeline page on the monotonic row
ids the store was built with; the detail read is one session and takes
neither argument. `?limit=` holds 50 rows by default and 200 at most,
and `?cursor=` is a row id this API answered with, meaning the sessions
before it in the listing and the turns after it in a timeline, which is
the direction a client that has read up to a turn asks in. A page
answers `{"items": [...], "next_cursor": <id or null>}`, and the cursor
is null when there was nothing beyond that page. The conversations
rows are the same record read as threads: the list orders by a
conversation's last activity, filtered by `?agent=` when given, and
pages on the pair `?cursor_active=` and `?cursor_id=` this API
answered with, together or not at all, because an activity ordering
moves and a row id alone cannot page it; the detail is one thread with
its milestone count; the turns are its dialogue oldest first, across
every session it spanned. The three DELETE rows are the erasure verbs
[Deleting on demand](#the-conversation-store) below describes: one
named session, the selector purge (`?session=`, `?device=`,
`?before=`, at least one, combined with AND), and one named thread.
A deployment that never
recorded answers 404 naming `server.conversations.enabled`; one that
recorded and has since switched recording off still serves what it
recorded. The events themselves are deliberately not served here: the
database is that surface, and there is no analysis endpoint for the same
reason there is no analysis command.

`GET /api/config` is the whole domain configuration, masked, with the
location of every stored secret beside it, which is the JSON of what
`config show` prints. Every other read answers with the entity's masked
body and the slots holding a secret stored in the database, each marked
with the entity key its value displaces, which is the one thing a masked
entity cannot carry itself. A read is masked always, and a stored secret
is never read back by any route.

A PUT is create-or-replace, the CLI's `set`: the body is the same
fragment, as JSON rather than YAML, every reference it names has to
exist already, and the entity's stored secrets are left alone. A secret
is written by PUTting `{"secret": "..."}` to its slot, which is the only
plaintext this API accepts and the reason the whole of it belongs on a
loopback connection or behind TLS. Three writes take an argument rather
than a fragment: that one, a device binding (`{"agents": [...]}`), and
the default agent (`{"name": "..."}`), whose DELETE clears it.

**A successful write says when it takes effect.** It answers
`{"wrote": "...", "notice": "...", "applies": [...]}`: a sentence for a
reader, and the boundaries it is waiting at as the closed tokens the
comparison read publishes, which is the half a program branches on. A
device binding and the default agent carry the one about a device
asking, because a running server reads them as it asks: they apply at
that device's next OTA check or connection. Every other kind this API
writes, which is the whole of the rest of the domain half, carries the
one that says the write is stored and not yet serving, and leaves the
three moments a conversation meets an installed change at to the
installing command's own help. A binding naming an agent this server is
not serving yet carries a sentence of its own, and it is the one an
operator is most likely to need, because both halves of it are true at
once: the row is live, and the agent arrives at the apply that installs
it. A default agent naming an unserved agent carries its own for the
same pair of reasons and about the row it really wrote, which covers
every device that has no binding of its own. No sentence names a
command: which command crosses a boundary is a fact of the client's
grammar, and a client is a program this server neither ships nor
versions, so the CLI reads the tokens and says the whole of it in its
own words where it knows the set, and quotes the sentence where it does
not. Nothing about a running conversation changes when a write lands,
in any of these cases.

**A refusal is an RFC 9457 problem document**, served as
`application/problem+json`, and carries the sentence the CLI prints in
`detail`, with a status code: 404 for an entity that does not exist,
409 for the retryable busy database lock or a reload already running
(nothing was changed, so retry), 422 for a fragment or an address the
caller got wrong, 500 for stored state that cannot be read, and 503 for
a runtime action asked of an application with no server around it.
Beside `detail` are the status's standard reason phrase as `title`, the
status repeated, and `errors`: one `{path, message}` entry per field of
the submitted fragment the refusal names, `path` an RFC 6901 JSON
Pointer into it, so a form can mark the offending field rather than
quote the paragraph. `errors` is always present and empty where the
refusal names no field. A request body is never quoted back, on any
path, and neither is a traceback: a fragment can carry a credential
pasted where a variable name belongs, and a refusal that echoed it
would be the leak. **Neither are its keys.** A refusal names only fields
this server declares and positions in a list; a key the request invented
(an unrecognized one, an option a provider passes through, an entry of
an `env` or `headers` map) is as good a place to paste a credential as a
value is, so a refusal about one says which rule it broke and points at
the nearest enclosing place this server can name.

**`vinga-server config` is the ergonomic client**, and the shape of a
deployment's own use of the API. It finds the server in this order:

1. `--api-url`
2. `VINGA_API_URL`
3. `http://127.0.0.1:<server.port>/api`, the port read from the same
   YAML file the server was started with (`--config`, or
   `VINGA_CONFIG`), so the two cannot disagree about it

The token is the value of the variable `server.api.secret_env` names,
read from that same file, and a missing one is a sentence naming the
variable before any request is sent. On a deployment both fall out for
free: exec into the running container, and the token variable and the
loopback address are already in the environment. That is the intended
way to run these commands.

The token grants everything the API can do, so the client refuses a
plain `http://` connection to a host that is not a loopback address
(`127.0.0.1`, `::1` or `localhost`), and there is deliberately no flag
to override it: such a flag's only purpose would be
sending the token in clear. A URL carrying a username or a password is
refused outright, and any URL the client prints has that stripped. Its
timeouts are explicit (5 s to connect, 30 s to read) so that the
server's own retryable answer, which can take up to the database's ten
second lock timeout to arrive, reaches you as itself rather than as a
transport error. `import` is the exception, and deliberately: its
transaction loads the whole existing configuration and validates the
whole resulting one, whose size no request bound limits, so it waits for
the answer however long that takes rather than giving up on a write the
server may be about to commit. `apply` is a command of its own and
carries its own sixty seconds, because a bound belongs to the endpoint
rather than to the command that reached it.

The whole command line, including installing it away from a deployment
and every command's own help page, is
[`../docs/reference/cli.md`](../docs/reference/cli.md).

**There is no second way in.** Every command here is a request, so a
deployment whose server will not start is recovered by rebuilding its
store rather than by editing it: stop the server, delete the database,
boot clean, import a kept `config export` with `config import`,
re-enter each stored credential through the `secret set` commands that
export listed at its foot, and `config apply` to install what came
back. The full procedure is in the task guides, under
[Recovering a deployment that will not start](../docs/run/recovering-a-deployment.md).

### Secrets

A credential is never written in the configuration, in either half. Two
forms are supported:

- **An environment reference**, which is the only form a fragment may
  carry: a provider names the variable holding its key (`api_key_env:
  ANTHROPIC_API_KEY`), an MCP server writes `$NAME` where the secret
  goes, on its own or inside a larger value. The server reads the variable at startup and fails the boot when
  it is unset, rather than failing every conversation later.
- **A value encrypted in the database**, written with a noun's own
  `secret set`, which reads it from stdin (not echoed at a terminal) or
  from a named variable with `--from-env`, and never from an argument:

  ```bash
  vinga-server config provider secret set llm claude api_key
  ```

  Encryption uses `VINGA_MASTER_KEY`, one or more Fernet keys, newest
  first, comma separated. Generate one with:

  ```bash
  python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
  ```

  A stored secret takes precedence over an environment reference for the
  same slot, and `config show` marks the reference it displaces. With
  ciphertext stored and no key configured, or a key that does not open
  it, the server refuses to start naming the entity and the slot, and
  the API goes down with it, so the repair is the rebuild above: boot on
  an empty database and put the configuration back, entering each
  credential again under a key that works. A slot whose value is gone
  for good is left to its environment reference by writing the entity
  without the stored one.

Instance configs stay out of the repository; `*.local.yaml` and `.env`
are gitignored for local experiments, and the domain half of a local
experiment is a short script of `config <noun> set` calls against a
database of its own, which `VINGA_DB_NAME` is enough to give it.

## Security

**Which hosts a configuration reaches.** Worth reading before deploying
anywhere with an outbound allowlist, because a blocked host does not
announce itself: the server boots healthy, other stages keep working,
and the blocked stage waits out its `timeout_s` while the device plays
silence.

| Configured as | Reaches | Notes |
| --- | --- | --- |
| `llm: anthropic` | `api.anthropic.com` | |
| `llm: openai_compatible` | whatever `base_url` names | `api.openai.com` when pointed at OpenAI, a host on your own network when pointed at Ollama or vLLM |
| `asr: openai` | `api.openai.com` by default, else `base_url` | **Shares its host with an OpenAI LLM.** Adding cloud ASR to a deployment already using OpenAI for the LLM needs no new host |
| `tts: openai` | `api.openai.com` by default, else `base_url` | Same |
| `tts: elevenlabs` | `api.elevenlabs.io` | A separate host, and the one most likely to be missed |
| `asr: faster_whisper` | `huggingface.co` at first start only | Model weights, downloaded once into `/data` |
| `tts: piper` | the voice collection at first start only | Same |
| `vad: silero` | nothing | Weights ship with the package |
| `mcp_servers` (`streamable_http`) | whatever the entry's `url` names | Each entry is its own host |
| `mcp_servers` (`stdio`) | wherever the command it runs goes | Not knowable from the configuration |

The two local engines are the only entries that reach anything at
startup and then stop, which is why a deployment that has been running
for months can still be broken by an outbound rule: nothing re-reaches
those hosts until the volume is cleared.

**Devices authenticate, by default.** The OTA endpoint issues each device
a token, the firmware persists it to NVS, and the WebSocket handshake
checks it before accepting the upgrade. A connection with no token, a
forged one, an expired one, or one issued for a different device is
refused with HTTP 403 on the upgrade, which stock firmware handles by
retrying and picking up a fresh token at its next OTA check.

The token is upstream's scheme, `sig.ts`, where `sig` is HMAC-SHA256 over
`client_id|device_id|ts`. It is stateless: a restart does not lock out
every device holding a persisted token. Statelessness also means any
process sharing the secret accepts another's tokens, but that is a
property of the scheme rather than support for a second replica; the
supported topology is one server process (see
[Running vinga in a container](../docs/run/running-in-a-container.md)).

The secret comes from the environment, never from the config file:

```bash
VINGA_AUTH_SECRET=$(openssl rand -hex 32)
```

Generate it once and keep it. Changing the secret invalidates the token
every device has stored, and a device only refreshes at its next OTA
check, which it makes on boot: until then it is refused at the handshake
and plays an error tone with nothing on its screen. That is the intended
behaviour of a rotated secret, but it is worth doing deliberately rather
than by regenerating one inside a `docker run` you repeat.

**A missing secret fails the boot.** Authentication is enabled by default,
and starting with it enabled and no secret refuses to come up, naming the
variable and the fix. A deployment that forgot its secret must not look
exactly like a working one. For a trial on a network you trust, opting
out is one deliberate flag:

```yaml
server:
  auth:
    enabled: false
```

or `VINGA_SERVER__AUTH__ENABLED=false` in the environment.

**Who gets a token is the allowlist.** A token is only issued to a device
the configuration resolves to at least one agent. Omit `default_agent`
and the `devices` map becomes an allowlist: an unknown MAC is issued
nothing and turned away. There is no second list to keep in sync.

**The OTA endpoint is the token issuer, so it cannot require a token.**
What protects it instead is stingy issuance and a path you choose. It is
served at two of them, and both are the same handler:

- `/x/<key>/`, the short path an operator types into a board's captive
  portal, where the key is eight base32 characters derived from the
  device-auth secret. Derived, so nothing configures or stores it, it
  survives restarts, and it changes only when that secret does. With
  device authentication off there is no secret to derive from and the
  route is served keyless at `/x/`.
- `server.ota_path`, the legacy full path, for boards already carrying
  one in NVS. Exposed publicly it should be a long random segment
  (`openssl rand -hex 8`), and it is nullable, so a deployment whose
  boards have all been onboarded through the short path can unmount it:

  ```yaml
  server:
    ota_path: /xiaozhi/ota/8f3a9c2b1d4e5f60/   # or null to unmount
  ```

The two segments are treated differently on purpose. The derived key is
printed at startup and repeated in the log line a wrong key produces,
which is what makes a typo and a rotated secret diagnose themselves; it
is a deployment-scoped path segment rather than a per-device
credential, and that trade is deliberate and recorded. The `ota_path`
segment is never printed anywhere, and neither is any device token.

The WebSocket path never moves: the token is what protects it.

**Nothing else is exposed.** `/x/<key>/`, `/xiaozhi/ota/` (or wherever
you put it), each with an `activate` beneath it that a waiting board
polls, `/xiaozhi/v1/`, `/healthz`, `/readyz`, and the configuration API under
`/api/`, which answers 401 to anything not carrying its bearer token. FastAPI's
`/docs`, `/redoc`, and `/openapi.json` are turned off on both
applications, and `server.ota_path` refuses a path under `/api/`: the
OTA route is registered before the API is mounted, so it would be found
first and would answer a request the token gate never saw.

**Fully local is checked, not hoped for.** This section is how the
server keeps
[the first-class local deployment](../docs/architecture/product-promises.md#a-fully-local-deployment-is-first-class),
which is where the commitment itself is written down.
Every provider type declares how far session data (audio, transcripts,
replies) given to it travels: `host` for something that stays on this
machine, `network` for something that stays on your own network,
`internet` for anything else. `server.data_boundary` declares the
outermost reach you allow, and the server refuses to boot any provider
that exceeds it, naming the stage and provider. Under `host` the local
engines (Silero, faster-whisper, Piper) pass and an `anthropic` or
`elevenlabs` entry fails; under `network` a model server on your LAN
passes too. The key is absent by default, which declares no boundary
and refuses nothing on distance.

The three `base_url` types, `openai_compatible` for the LLM stage and
`openai` for both ASR and TTS, can each point at this machine, at a
server on your network, or at a cloud vendor, so under any declared
boundary they must carry your own declaration:

```bash
vinga-server config provider set llm local -f - <<'YAML'
type: openai_compatible
base_url: http://localhost:11434/v1
model: qwen3:8b
# Your assertion about where this endpoint is.
reach: host
YAML
```

That is also why declaring `internet` is a real choice rather than a
way of switching the mechanism off: it forbids nothing, and it still
refuses an entry that will not say where it goes.

MCP servers sit inside the same boundary, because tool arguments carry
conversation-derived data. No transport can know where they end up (a
stdio command may proxy anywhere, a URL may name localhost), so under
any declared boundary every MCP server an agent references must carry
its own `reach`, most often `reach: network`, asserting that whatever
its command or URL reaches stays on your own network.

The telemetry section carries one of its own, and it is your assertion
rather than anything this server checks. `server.telemetry.reach` says
how far this section's destinations lie, and there are three of them:

- the collector, in `OTEL_EXPORTER_OTLP_ENDPOINT`, which the traces and
  the exported transcripts ride;
- the Langfuse the recording upload talks to, in `LANGFUSE_HOST`;
- and wherever that Langfuse keeps its media. The upload asks it for an
  upload URL and PUTs the WAV, the manifest and each turn's clips to the
  presigned URL it answers with, so the bytes land in whatever object
  storage the backend is configured with. **A Langfuse on your own
  network can answer with a URL at a cloud vendor**, and this server
  hands the bytes over without reading it.

One key covers all three and means the outermost of them, so the tracing,
the transcript export, the recording upload and the LLM input export are
refused together rather than the one that would have been caught. That third bullet is
what makes this an assertion and not a formality: a LAN collector and a
LAN Langfuse are not enough to declare `network` unless that Langfuse's
object storage stays on your network too, and if you cannot say where
your backend stores media then you have not got a `network` deployment
to declare.

Absent, it is `internet`, which is what a deployment got before the key
existed: writing nothing changes nothing, and writing `host` or
`network` is what lets a bounded server export to a collector it can
reach without leaving your network.

```yaml
server:
  data_boundary: network
  telemetry:
    enabled: true
    # Your assertion about all three: the OTLP endpoint, the Langfuse
    # host, and the object storage that Langfuse hands out upload URLs
    # for. Nothing here checks any of them.
    reach: network
```

The checks run at boot, never at request time: a server that starts
inside its boundary stays inside it, and a config edit that would break
the promise stops the server from coming up instead of quietly shipping
audio to a vendor. Declarations are enforced and behaviour is not
verified: this is not a network sandbox, and it proves nothing about
what a remote endpoint does with what it was sent.

## Listening and barge-in

The firmware decides how it listens and the server follows. In `auto`
mode the device shuts its microphone off while a reply plays and sends a
fresh `listen start` afterwards. In `realtime` mode, which it picks when
its echo cancellation is on, it streams continuously and asks only once,
so the session here never stops listening: an utterance that ends while
a reply is playing cancels that reply and is answered instead. Talking
over the assistant stops it, which is what barge-in means.

```yaml
server:
  barge_in: true               # speech during a reply interrupts it
  barge_in_min_speech_ms: 500  # least classified speech that may interrupt
```

Turn it off for a board whose echo cancellation leaks the speaker back
into the microphone, typically a single-mic board, where a reply would
otherwise interrupt itself. Conversations stay multi-turn with it off;
only the interrupting goes. What says a board wants it: replies that
answer nothing at all, arriving just after the previous reply finished
speaking.

An interruption the endpointer hears is gated before it may cancel: a
reply is only cancelled on evidence of user speech. Speech shorter than
`barge_in_min_speech_ms` is a noise blip and never interrupts. Past
that floor, the reply pauses while ASR transcribes the interruption,
and only a non-empty transcript cancels; an empty one resumes the reply
where it stopped, about one ASR pass later. An interruption landing
while the reply is still transcribing merges with what it interrupted
instead, so one reply answers the whole sentence. Nothing is dropped
for arriving early in the playback: a refractory window used to do
that, and it turned out to catch only users finishing their own
sentence, since half a second of classified speech cannot come out of
the fraction of a second of reply the room has heard by then.
Every one of these decisions is a structured log event, which is what
the threshold is tuned from. A manual `listen stop` mid-reply is the
user holding the button and speaking, so it cancels unconditionally.

**Where a turn ends is one number, and it belongs to the agent rather
than to the server.** The endpointer ends an utterance after
`trailing_silence_ms` of silence, 700 ms by default, which is the right
bound for question-and-answer speech. Dictation is slower: telling an
agent things to remember pauses between clauses for longer than that,
so the turn ends mid-sentence, the reply answers a fragment, and the
rest of the sentence arrives as an interruption to it. Raising the
bound for the whole server would put the added latency on every turn of
every agent to fix one agent's usage pattern, and there is no need to.
The bound is an option on the VAD provider entry, and an agent binds
the entry it wants:

```yaml
providers:
  vad:
    quick:
      type: silero
    patient:
      type: silero
      trailing_silence_ms: 1200

agents:
  quizmaster:
    vad: quick
  archivist:
    vad: patient
```

Each agent's endpointer is built from the entry that agent binds, and a
handover mid-conversation builds a fresh one from the incoming agent's,
so the two agents above listen differently inside the same session.
What a longer bound cannot do is tell a thinking pause from a finished
sentence: every pause costs its full length before the reply starts,
which is why this is per agent rather than raised everywhere, and why
reading more than silence is its own piece of work
([end-of-turn detection](../docs/glossary.md#end-of-turn-detection)).

## Masking reply latency

The silence between the end of an utterance and the first audio of the
reply is where the assistant feels dead: healthy field turns run 1.5
to 3 s of it, and a slow provider stretches it well past the point
where users ask "are you there?". Humans hold exactly this gap with a
filled pause, and an agent can too:

```bash
vinga-server config agent-defaults set -f - <<'YAML'
filler:
  # off by default
  enabled: true
  delay_ms: 1800
  phrases:
    - "Hmm, let me see..."
    - "Good question..."
YAML
```

When a reply's first audio has not started within `delay_ms` of the
utterance being transcribed, the session plays one of the phrases,
rotating through them, and the real reply queues behind the clip's
tail. The clips are synthesized ahead of time in each agent's own voice
and cached as PCM, never at fire time: synthesis at the moment of
masking would add TTS latency to the exact gap being masked, and a
cached clip keeps working when the TTS provider is the thing being
slow. Ahead of time is the server start and every `vinga-server config
apply` after it, which re-synthesizes the agents whose effective
`filler` section or whose voice moved, whichever field of the section it
was, and hands the result to the next conversation; one already open
keeps the clips it opened with. A synthesis failure logs a
warning and leaves the feature off for that agent rather than failing
the boot or refusing the apply.

The filler is honest assistant speech: it moves the device into its
speaking state, counts as the turn's `speaking_started`, lands on
capture channel 1, and enters the barge-in gates like any reply audio,
so talking over it interrupts the reply, which is the correct reading.
One filler per turn, logged as a `filler_played` event; a turn that
outlives both the filler and the first-token watchdog resolves through
the watchdog's give-up path (see below), the filler being the soft
early threshold and the watchdog the hard late one. Write the phrases
in each agent's own language; an agent's own `filler` section replaces
the inherited one wholly, like the stage fields, and the reasoning
behind the default delay is in
[`examples/agent-defaults.yaml`](examples/agent-defaults.yaml).

The mask yields to the user. At fire time the timer stands down, with
a `filler_skipped` event, when the endpointer holds unresolved speech
or a barge-in confirmation has the outgoing frames paused. Both mean
the turn ended at a premature endpoint and the user is already mid
continuation: the reply in flight is about to be cancelled, and a
clip played into that would talk over them (field round 2 measured
exactly this on dictation-style turns). The skip consumes no phrase,
and the reply that answers the completed sentence arms its own timer.

## When a reply fails

The other end of the same turn. A reply that fails outright, on a
provider that is down or a model that never answers, used to be
silence: the failure was logged and nothing reached the speaker or the
display, so from the couch a broken pipeline and a slow one were the
same turn. Every agent therefore has a fixed phrase for it, cached the
same way the filled pauses above are:

```bash
vinga-server config agent-defaults set -f - <<'YAML'
fallback:
  # on by default
  enabled: true
  phrase: "I ran into a problem and could not answer. The server log has the details."
YAML
```

It is spoken and shown: the sentence goes out as a `tts sentence_start`,
so it renders on the display, and the cached clip follows it, so it is
heard. It is vinga's own words rather than the agent's, and it goes no
further than that turn: it never enters the reply's spoken sentences,
the conversation history or the stored conversation, and `replied`
keeps its meaning of model speech that went out. What says it happened
is a `reply_fallback` event, carrying the reason and whether the phrase
was heard as well as shown, never the words themselves. The phrase is
fixed configuration and is never the failure's own message, which
arrives from the far side of a network and is not this server's to
speak.

Only a terminal failure speaks. A device that went away is told
nothing, because there is nobody left to tell, and a reply cancelled by
a barge-in says nothing either, because a cancellation means the user
is talking. Neither reads the section.

**This one is on by default, unlike the filler above.** The silent turn
is at its worst during onboarding, where a misconfiguration is
likeliest and nobody has a log open, so a deployment that would rather
have silence is the one that says so: `fallback: {enabled: false}`, on
`agent_defaults` or on a single agent. Being on by default has a cost
worth knowing, and it is per start rather than per upgrade: **every**
server start synthesizes one short phrase for every agent that has not
switched the section off, through the configured TTS provider, before
the server begins serving. That is one provider call per agent, a few
seconds of startup, and, on a metered voice, a few seconds of billed
synthesis, paid again at every restart, redeploy and container
replacement. Nothing is cached across processes: a start has no previous
world to keep a clip from. What reuse there is lives inside one running
process, across `vinga apply`: an agent whose `fallback` section and
whose voice are both unchanged keeps the clip it already had, and each
of the two kinds of clip is re-synthesized only when its own section or
its voice moves, so applying a prompt edit costs no synthesis at all.
Synthesis is bounded per phrase, so a provider that hangs delays a start
by seconds rather than indefinitely; a phrase that will not synthesize
in time, or at all, degrades to the display alone, with a
`fallback_degraded` event naming the agent. That turn still shows the
sentence and still closes with its `tts stop`, and only the audio is
lost.

## When a model writes a tool call into its speech

A reply is spoken sentence by sentence, and every sentence is spoken
except one kind: a sentence shaped like a call to a tool this reply
actually offered. Some models, small local ones especially, write their
calls out as ordinary prose instead of issuing them, and read aloud
that is JSON in the assistant's voice on the one user-facing surface
with no filter on what a model produced.

The check is narrow, and it is anchored to the tools of the reply it is
in rather than to "looks like JSON": someone asking an agent to explain
a JSON snippet is a real conversation and gets an answer. A sentence is
withheld when it contains a complete JSON object that either names one
of the offered tools, in its own `name` or in the `name` under a
`function` key, or whose keys all fall inside the properties one
offered tool declared. The second is the shape the field actually
produces, where the name never made it out and only the arguments did
(`{"volume":"100"}`), so nothing about it can be matched by name; keys
are compared and values never are, since the observed one had the wrong
type for the schema it belonged to.

The sentence goes whole and the reply carries on. It is not spoken, not
shown, not added to the conversation this server keeps, and not stored,
and no event or log line carries a byte of it: what says it happened is
a `sentence_withheld` event, carrying its length in characters and
which tool it was shaped like, under the same naming rule `tool_call`
follows. A reply left with nothing at all to say, every sentence of it
withheld, says the fallback phrase above with the reason
`nothing_sayable`, because the alternative is the silence that phrase
exists to end.

**One bound, stated rather than hidden.** The test is on each sentence
as it arrives, because a sentence has already been handed to the voice
by then. Sentences are cut at newlines, so a pretty-printed call
arrives as a handful of fragments no JSON decoder can read, and those
fragments are spoken. Closing that would mean holding sentences back to
see what follows them, which puts a stall in front of live speech at
every ordinary `{` in every reply. The residue is left visible through
the event instead: an operator seeing `sentence_withheld` repeatedly,
or hearing the fragments, is reading a fact about the model this
deployment configured. The same event is what makes the cost of the
key-matching rule visible, since an agent reading out a JSON example
whose keys mirror an offered tool is withheld too.

## Logging

Two formats, one handler:

```yaml
server:
  log_format: text   # or json, which is the container image's default
  log_level: INFO
```

Every event is logged as a human sentence and, in `json` mode, as a line
of structured fields. Every record carries `event`; the ones a
conversation emits, on the `vinga_server.session` channel, carry
`session` and `device` beside it, and the server's own channels carry
either only where the record is about one.

Which fields an event carries, which tokens a reason field admits, what
each of them is held to and which sentence it renders are the generated
[event schema reference](../docs/reference/events.md), one section per
event and one subsection per shape it may be emitted in. It is generated
from the declarations themselves, so it cannot say anything they do not.
This index is the other half: what exists, and when it fires.

| `event` | when |
| --- | --- |
| `ota_check` | a device checks in (no session yet, so the record names the device) |
| `ota_check_body` | the whole of what a board reported at that check-in, at DEBUG, so `vinga events tail --level DEBUG` is how somebody asks for it |
| `activation_not_offered` | an unbound device is answered with no activation code, and why |
| `activation_complete` | a waiting device has been claimed; its next check hands it a token |
| `activation_pending` | a waiting device polls and is still waiting |
| `activation_refused` | a version-2 activation poll fails one of the checks this server can hold it to; nothing of the body is ever quoted |
| `ota_request_rejected` | a request this endpoint could not read, refused with one of three fixed sentences |
| `onboarding_banner` | where devices are configured, said once at startup |
| `onboarding_key_mismatch` | a request reaches the onboarding path carrying a key-shaped segment that is not this server's; neither is repeated |
| `onboarding_key_unshaped` | the same path, carrying something that is not key-shaped at all |
| `auth_rejected` | a handshake is refused before the accept; no device, since nothing is authenticated yet and the Device-Id header is whatever the caller sent |
| `session_rejected` | a device is turned away, either by the endpoint before a session can run (`vinga_server.ws`) or by the session after the accept (`vinga_server.session`) |
| `session_open` | a conversation starts |
| `session_limit` | the duration cap fires |
| `session_idle` | the idle timeout hangs up on a realtime session |
| `session_closed` | a conversation ends |
| `speaking_started` | the reply's first audio frame goes out |
| `speaking_finished` | the reply's last audio frame has gone out; with `speaking_started` it bounds the interval the frame pacer actually paces, and a reply that never spoke emits none |
| `frames_dropped` | one second of mic frames the edge's guards discarded before they could be decoded, counted by reason; at DEBUG, and counted whether or not this deployment records anything |
| `turn_started` | a reply attempt begins, stamped with the instant the user stopped speaking; `barge_in` says whether answering it interrupted a reply in flight |
| `reply_finished` | a reply ends, however it ended: exactly one per `turn_started`, with an outcome latched where the end was decided |
| `heard` | an utterance is transcribed. No transcript: what was said is the conversation store's |
| `nothing_heard` | an utterance is transcribed to nothing at all, which is one of the four ways an utterance's ASR stage ends, beside `heard`, `provider_failed` and `transcription_abandoned`; no text field, by type |
| `transcription_abandoned` | a transcription was given up on before it answered, because the reply it belonged to was cancelled with the call still running; deliberately not `provider_failed`, since nothing failed |
| `sentence_synthesized` | one sentence of a reply has finished streaming out of the voice: the provider's latency to its first chunk, and the stream's whole lifetime, which includes playback backpressure. At DEBUG |
| `replied` | a reply finishes |
| `agent_said` | one agent's part of a reply |
| `handover` | `switch_agent` succeeds |
| `conversation_resumed` | a stored conversation is picked up again: how much of it was rebuilt, how much could not be, and whether there was more of it than the budget had room for |
| `milestone_recorded` | a consented recap is stored as a checkpoint on its thread, after the user has heard it |
| `prompt_assembled` | the know-how half of a prompt is assembled and cached, with each block's size by provenance |
| `llm_retry` | the first-token watchdog cancels a stalled generation and retries the round once |
| `llm_round` | a generation call finishes |
| `provider_failed` | an ASR, LLM or TTS call fails; a round whose retry also stalled carries `FirstTokenTimeout` |
| `tool_call` | a tool returns |
| `tool_arguments_coerced` | a call went out with argument types this server corrected, because the model quoted a value its tool declares as a number or a boolean: how many were converted, and never which or to what |
| `sentence_withheld` | a sentence of a reply was shaped like a call to a tool this session offered, so it was dropped rather than spoken: how long it was and which tool it was shaped like, never a byte of it |
| `barge_in` | speech cuts a reply short |
| `barge_in_suppressed` | an interruption is dropped and the reply lives |
| `barge_in_merged` | an interruption merges with the utterance the reply was transcribing |
| `filler_skipped` | the filler timer fired but the user was there first, so no clip played |
| `filler_played` | the reply was slow, so a pre-synthesized filler clip masked the wait (its first frame is the turn's `speaking_started`) |
| `reply_fallback` | a turn said the agent's fixed fallback phrase instead of an answer, and why; `audio` says whether it was heard as well as shown |
| `asr_prompt_echo` | a transcript came back as the ASR prompt and the clip was retried once without it, on what the first request left of `timeout_s` (no session or device: providers serve them all) |
| `mcp_connected` | an MCP entry's connect finishes and its tools are published (no session or device: one entry serves every conversation, and the rest of this block is the same) |
| `mcp_down` | an MCP entry fails to come up, or its connection is given up. `stopped` is the intentional one (a shutdown or a reload) and the only one at INFO |
| `mcp_call_dropped` | a tool call failed and the connection was dropped because of it, always beside an `mcp_down` with `call_failed` |
| `mcp_tool_shadowed` | a published tool is dropped because a more specific entry owns its name |
| `mcp_reload` | a reload of the MCP servers finishes, whether or not the caller is still connected |
| `provider_reaches_loopback` | a provider entry built inside a container names this machine in its endpoint |
| `memory_unreadable` | one scope of an agent's memory could not be read, so it remembers nothing of that scope this round |
| `memory_unwritable` | a change an agent asked for could not be stored, so nothing was changed |
| `memory_cleanup_failed` | the memory of conversations that are gone could not be removed, so the next sweep takes it |
| `filler_disabled` | filler synthesis failed for one agent, so latency masking is off for it |
| `fallback_degraded` | the phrase a failed reply says would not synthesize for one agent, so its failed turns are shown on the display and not spoken |
| `capture_started` | a session is being recorded |
| `capture_declined` | a session is not being recorded, and why |
| `capture_limit` | a recording reaches its per-session ceiling |
| `capture_failed` | a recording stops after a write failed |
| `capture_pruned` | old recordings are removed to stay inside the disk budget |
| `capture_over_budget` | the disk budget is exceeded and nothing more can be pruned |
| `capture_enabled` | capture is on, said once at startup and at WARNING: recording room audio is not something to discover by accident |
| `capture_disabled` | capture is configured but off |
| `capture_uploaded` | a closed session's recording is beside its trace in the telemetry backend, with its sizes, how long it took and how many turn clips went to their turns |
| `capture_upload_failed` | a recording is not beside its trace, and why, from a closed set of reasons; also what a restart says about a job it found still staged |
| `capture_clips_incomplete` | a recording is beside its trace and some of its turns' clips are not on their turns: how many attached, had no turn, failed or were never tried, and the first failure's reason |
| `transcripts_exported` | acknowledged content was attached to an original turn root and enqueued for ordinary OTLP processing, with how long settlement took |
| `transcript_export_failed` | turn content was omitted before enqueue, and why, from a closed set of reasons |
| `llm_input_exported` | a complete input and raw-output pair was attached to its actual generation span and enqueued for ordinary OTLP processing |
| `llm_input_export_failed` | generation content was omitted before enqueue, and why, from a closed set of reasons |
| `conversations_enabled` | the conversation store opens at startup, which means this server is recording what is said to it (no session or device: it is said once, before anything connects) |
| `conversations_dropped` | the store is behind and events for one session are being dropped, said once per session at its first drop; the total lands on that session's row |
| `conversations_failed` | a write to the store failed and its batch was dropped, or a prune could not run |
| `conversations_pruned` | retention deleted the conversations that aged out of the window, and the session records nothing points at any more (at INFO: a policy doing its job) |
| `drain_started` | a shutdown begins draining |
| `drain_finished` | every reply finished speaking |
| `drain_incomplete` | a reply was cut, or a session hung |
| `device_bindings_unreadable` | the configuration database could not be read, so the answer is the served world's and may be older |
| `api_error` | the configuration API failed to handle a request; the class name and nothing else |
| `api_storage_error` | the configuration API met unreadable stored state |

No MCP event names a tool, and none of them can. Half of a published
tool name is whatever the far side called it, sanitizing replaces only
the characters both LLM APIs refuse, and an alphanumeric credential goes
through that untouched, so a server handed one of your own could put it
in the logs you keep by listing a tool under it. Every line about a
single tool therefore says which one by its position in that server's
listing. `vinga-server config mcp-server status` prints the names
themselves, to a terminal, when you ask it.

Every event above is declared: its channel, its level, the sentence it
renders, the arguments that sentence takes and every field it may carry,
with closed sets for the fields that hold a reason token. The reference
this index points at is those declarations rendered, and CI regenerates
it and refuses any difference. The emitters build each emission inside a
guard, so an emission that could not be built costs one line on the
emitter's own channel, naming a fixed label and a fixed code and nothing
about the emission itself; it is dropped rather than written in some
other shape, because a telemetry bug must never cost a reply.

### Watching a deployment as it runs

The table above is what gets written down. The same events are also
readable as they happen, over the configuration API and from wherever
the CLI already reaches, which is what the two moments that used to mean
reading the container's log on the server host are:

```bash
# Wait for the next event of one board, print it and exit: what to run
# after typing a URL into a captive portal.
vinga events tail --device aa:bb:cc:dd:ee:ff

# Or watch until you stop it, which is the diagnostic reading.
vinga events tail --follow
vinga events tail --follow --session 6f1a2b3c4d5e6f708192a3b4c5d6e7f8
vinga events tail --follow --level warning
```

One line per event: the clock time, the level unless it is `INFO`, the
event's name, and its own fields. Nothing is kept behind the stream, so
it carries what happens while it is open and a reader that reconnects
rejoins the present; what happened before is the conversation record's
to answer. A reader that falls behind loses its oldest events rather
than slowing a conversation down, and is told how many on stderr. The
stream ends when you stop it or when the server shuts down, and an end
you did not ask for is a sentence and exit 1 rather than a quiet
terminal, because nothing reconnects on its own: a tail that rejoined
across a gap would look continuous while missing what happened in it.

The same route is `GET /api/runtime/events`, behind the same bearer
token, answering `text/event-stream`.

These events are metadata, and metadata only. What was said is in the
conversation store, keyed by the same `session`: query `turns` there for
the transcript and the reply, and `tool_invocations` for what a tool was
asked and what it answered. Filtering the logs for it no longer works,
and that is the point (see the [content and telemetry
ADR](../docs/adr/2026-08-15-content-and-telemetry-are-separate-surfaces.md)):
a surface with no free-text field cannot leak one. What the events keep
is what a latency brief reads, which is every duration, every count and
every identifier they ever carried. Tokens are never logged, at any
level.

## Exporting traces

`server.telemetry.enabled` sends one backend-neutral OpenTelemetry model over
OTLP/HTTP protobuf. A session is the root of its own trace. Each conversation
turn is a separate root trace linked to that session and grouped with it by
`session.id`. The semantic operations are `asr`, `llm`, `tool`, `tts_stream`
and the existing playback operation. They are children of the open turn, or
of the session when provider work such as a recap happens between turns. The
exporter keeps the trace flags and trace state each root received; a later
post-close writer does not turn an unsampled trace back on. Transcript and
assembled-request exporters report that case as `no_trace` without asking the
OTLP transport, rather than calling a deliberate sampling decision a failed
delivery.

Each model call gets a server-minted `vinga.llm.invocation.id` before its
request is assembled. A retry keeps that identity, while the next logical
generation gets another. `vinga.llm.round` remains the reply-local ordinal.
A recap is also an `llm` operation, marked with
`vinga.llm.purpose=recap`, but has no reply ordinal and changes none of the
turn record's round, latency or token totals.

Failed ASR, LLM, TTS and tool work is represented by the semantic operation
span itself. It has OpenTelemetry `ERROR` status with no description and an
`error.type` containing only an exception class name. A tool that returned an
error without raising uses the fixed `tool_error` value. Exception messages,
tracebacks, tool arguments and tool results do not become failure metadata,
and there is no duplicate `provider_failed` or `tool_call` span event beside
the failed operation.

OpenTelemetry names are the canonical attributes. The existing
`langfuse.observation.usage_details` fields for ASR and TTS remain derived
copies of the canonical whole-number usage values so direct-to-Langfuse
deployments keep their pricing behavior. A live gate measured the condition
that alias is read under: Langfuse prices an observation only where it stored
one as a generation, which it decides from `gen_ai.request.model` or from a
`gen_ai.operation.name` it knows. Both paths to it are canonical attributes
rather than a backend hint, and the two stage kinds reach it differently. An
`llm` round always names its operation, so it is a generation whether or not
its provider reported a model. `asr` and `tts_stream` have no operation name
the backend recognizes, so they reach it only by the model a real provider
reports; against a provider that reports none, which in practice means the
mock providers the test lanes run on, they are stored as plain spans and are
not priced. With `export_transcripts`, acknowledged
text and ordered handover legs enrich the original turn root as
`vinga.turn.input`, `vinga.turn.output` and `vinga.turn.legs`. With
`export_llm_input`, the actual generation span receives
`gen_ai.system_instructions`, `gen_ai.input.messages`,
`gen_ai.output.messages`, `vinga.llm.tools` and `vinga.llm.tool_choice`.
Generated output is captured before speech filtering, so text withheld from the
user also leaves. The turn root also carries direct Langfuse input, output and
legs aliases derived from its transcript values; the generation span carries
none, because Langfuse maps the GenAI conventions itself and shows the system
prompt as the first message of the generation's input. The former `transcript`
and `llm_input` child spans no longer exist.

The ordinary trace path still has one bounded batch queue. A full queue drops
spans instead of delaying a reply, and a bounded shutdown gives the exporter a
last chance to flush. It holds 2,048 spans, schedules every five seconds and
exports at most eight spans per request. Each turn or generation content
projection is limited to 256 KiB, keeping a maximal request below 3 MiB.
`transcripts_exported` and `llm_input_exported` report attachment and enqueue,
not backend acknowledgement; ordinary exporter health owns downstream
delivery. Standard `OTEL_EXPORTER_OTLP_*` variables own the
destination, protocol and credentials; none becomes span content. This
repository provides three current trace paths. The Jaeger and Collector paths
are exercised in automated tests, and all three have been walked live under the
M2 turn-root and generation-content model: direct Jaeger against a Jaeger
instance, and both Langfuse destinations, the direct one and the Collector's
Langfuse branch, against a live Langfuse v4 project:

- direct Jaeger v2 over OTLP/HTTP protobuf;
- direct Langfuse v4 over OTLP/HTTP with Basic Auth and its ingestion-version
  header;
- one Collector Contrib pipeline that masks, samples and batches before it
  forwards the same attempted population to Jaeger and Langfuse.

The runnable Jaeger and fanout Compose add-ons are under
[`deploy/telemetry/`](../deploy/telemetry/README.md), with their worked
procedure in [the deployment guide](../docs/deployment.md#telemetry-backends).
The fanout source sampler is explicitly `always_on`; its Collector owns the
one trace-id sampling decision before split. Since a session and each turn
have independent trace IDs, partial sampling keeps or drops turns rather than
whole conversations. The walkthrough defaults to 100 percent so its topology
is complete.

For direct Langfuse, supply the v4 OTLP endpoint and both required headers to
the SDK-owned transport. The Authorization value is the word `Basic`, one
URL-encoded space, then base64 of `public-key:secret-key`:

```bash
export OTEL_EXPORTER_OTLP_ENDPOINT=https://cloud.langfuse.com/api/public/otel
export OTEL_EXPORTER_OTLP_PROTOCOL=http/protobuf
export OTEL_EXPORTER_OTLP_HEADERS="Authorization=Basic%20<base64-public-key-colon-secret-key>,x-langfuse-ingestion-version=4"
```

Fanout applies one policy decision and gives both exporters the same records.
It is not a transaction across two backends. A backend outage can still make
their stored populations differ, so compare trace IDs when diagnosing parity.
The Langfuse-only `capture` reference span is removed on the Jaeger branch.
Recording bytes (the WAV, the manifest and each turn's clips) never enter OTLP:
they remain on the separate Langfuse REST and object-storage upload path
governed by `export_audio`.

## Capturing a session

**This records room audio to disk.** It is off by default and off until
`enabled` says otherwise, and a warning at startup plus one line per
recorded session say when it is on. Turn it off again once the
recording has been taken.

```yaml
server:
  capture:
    enabled: false
    dir: /data/captures
    # stop capturing a session after this long
    max_session_s: 900
    # budget for the directory, oldest captures pruned first
    max_total_mb: 2000
    # refuse to start a capture below this much free space
    min_free_mb: 1000
```

The flag is the switch, rather than the presence of the section, so
turning capture off again does not mean deleting the directory and the
budgets along with it: the field workflow is to record, then stop, and
the tuning is worth keeping across that. `dir` is required even while
disabled, so switching on is one word rather than one word and
remembering where it writes. A section that is present but off says so
once at startup, because a configured capture that records nothing is
otherwise a silence to debug.

Because it is one flag, the env layer can do the flip on its own:
`VINGA_SERVER__CAPTURE__ENABLED=true` turns it on for one run without
editing the config the deployment mounts, and dropping the variable
turns it off again. That is usually the least disruptive way to take a
field recording.

It exists because acoustic problems cannot be reproduced in any test
lane. The unit lane feeds synthetic frames and the integration lane
drives a simulator, and both bypass the microphone, the board's echo
cancellation, and the room. Whether a reply interrupts itself turns on
how much of the assistant's own voice survives the board's cancellation
and reaches the endpointer, and no test can tell you that number.

Three files per session, sharing one timeline:

| File | What it holds |
| --- | --- |
| `<session>.wav` | Stereo 16 kHz s16le. Channel 0 is the microphone as decoded, channel 1 is what was paced out to the speaker. |
| `<session>.jsonl` | Every structured event, plus a `t_ms` offset into the audio, plus dropped frames per second and the endpointer's opinion per frame. |
| `<session>.json` | What the capture was made against: server revision, the firmware the device reported, the resolved providers verbatim, and the barge-in thresholds. |

Stereo rather than two files is the whole point: sample N in both
channels is the same instant, so echo leakage is a measurement (cross
correlate the channels and read off gain and delay) rather than a
guess, and the overlap is directly audible in any audio editor. A
channel that goes quiet is filled with silence rather than compressed,
so nothing slides against the events.

The microphone is captured before the session's own guards, so the
frames a configuration discards (not listening, or `barge_in: false`
during a reply) are in the file anyway. Those are the frames that
explain a misfire.

Storage is 64 kB/s, so a fifteen minute session is about 58 MB and the
2000 MB budget is around nine hours. Both bounds matter: the model
caches share the volume and grow underneath the budget, so capture
declines to start and says why rather than being the thing that fills
the disk.

A capture cut off by a restart stays readable. The WAV header carries
byte counts that are only patched on a clean close, so a truncated file
claims zero length, but everything after the 44 byte header is raw
interleaved PCM and the manifest's `complete: false` says the length has
to come from the file size. Both files are flushed as they are written,
so what is lost is at most the last fraction of a second.

In the field: turn it on, hold sessions in the conditions that actually
break things, and say a marker phrase aloud when something goes wrong.
It is on the WAV, and the `heard` event beside it in the decision track
points at the interesting twenty seconds instead of ten minutes of
scrubbing; with the conversation store on and `text: true`, the phrase
itself is one query away, since both records carry the same session id. Copy the three files off
after each session; a field recording is not repeatable.

## What a conversation cost

Every stage of a turn says what it was given, on its own span, in the
unit that stage is actually billed in:

| Stage | Span | What it reports |
| --- | --- | --- |
| Transcription | `asr` | `gen_ai.usage.input_milliseconds`, how much audio the ear was actually sent |
| Generation | `llm` | `gen_ai.usage.input_tokens` and `gen_ai.usage.output_tokens`, as the endpoint reported them, and `gen_ai.usage.cache_read.input_tokens` where the endpoint reported what its prompt cache served |
| Synthesis | `tts_stream` | `gen_ai.usage.input_characters`, the length of the sentence the voice was handed |

The milliseconds and the characters are both INPUT, read from the
model's side the way the OpenTelemetry GenAI conventions read the token
halves: an ear is given the audio and produces a transcript, a voice is
given the sentence and produces the audio. Those conventions name token
counts and nothing else, so the two units they have no word for state
that unit in the attribute name rather than being reported as tokens
they are not. Every value is a whole number, because a backend drops a
usage value that is not.

The cached count is part of the input count, never beside it: of the
`gen_ai.usage.input_tokens` a round reports, that many were served from
the provider's prompt cache. A backend that knows the key takes it out
of the input and prices it at the model's cached rate, which is
usually a fraction of the full one, so the round's cost is what the
provider actually charged rather than an upper bound on it. An endpoint
that does not say what it cached reports no cached count at all, rather
than a zero that would claim nothing was.

**The transcription number is what was SENT, not how long you spoke.**
The two come apart in both directions on a real endpoint: a clip under
the endpoint's own minimum is never sent at all and reports zero, and a
clip a prompt-echo retry has to send a second time reports twice its
length. How long the user spoke is a different question and stays where
it was, on `vinga.asr.duration_s`. An engine that cannot say what it
submitted, which is every local one, reports no usage rather than a
zero: an unmeasured call and a free call are different facts, and only
the second is worth nothing.

Usage is not a cost. A backend turns one into the other with a model
definition, which is a match pattern, a unit and a price per unit, and
**those are yours to enter.** This server never writes one. It holds no
admin credential for your backend, the OTLP path carries none, and a
deployment that provisioned prices at boot would be mutating a
third-party system on the strength of telemetry credentials, which is a
larger claim on your infrastructure than anything else here makes.

### The generation stage usually needs nothing

A backend ships managed definitions for well-known vendor models, so
the `llm` stage is normally priced the moment its spans arrive. On the
project this section was written against, `gpt-4o-mini` came back with
`costDetails` filled in from input and output token counts with no
definition entered by hand at all.

To check yours, hold one conversation with telemetry on, open the `llm`
observation of any turn, and look at whether it has a cost beside its
token counts. If it has, there is nothing to do for this stage, and a
definition of your own would only shadow one the backend maintains.

If it has not, the model is one the backend does not know: a
self-hosted model, a model behind a compatible endpoint, or a vendor
model under a name your deployment renamed. Then it needs a definition
like the ones below, with one difference: a generation reports tokens
in BOTH directions, so it takes `inputPrice` and `outputPrice` rather
than an input rate alone, `unit` is `TOKENS`, and the two rates are
whatever that model's own published price list says per token. This
page does not name them, because a price nobody has read is not a price.

### The definitions worth entering

These are the stages a backend has no managed definition for, because
the units are vinga's own. Prices as published on <https://developers.openai.com/api/docs/pricing>,
read 2026-09-12. A price is a fact with an as-of date; re-read it before
trusting a cost report made long after this one.

| Model | Match pattern | Unit | Input price | Published as |
| --- | --- | --- | --- | --- |
| `gpt-transcribe` | `(?i)^(gpt-transcribe)$` | `MILLISECONDS` | `0.000000075` | $0.0045 per minute |
| `whisper-1` | `(?i)^(whisper-1)$` | `MILLISECONDS` | `0.0000001` | $0.006 per minute |
| `tts-1` | `(?i)^(tts-1)$` | `CHARACTERS` | `0.000015` | $15.00 per 1M characters |
| `tts-1-hd` | `(?i)^(tts-1-hd)$` | `CHARACTERS` | `0.00003` | $30.00 per 1M characters |

The price column is the published one converted into the unit the span
reports, and nothing else: 0.0045 per minute is 0.000000075 per
millisecond, 15.00 per million characters is 0.000015 per character. An
exact conversion of a list price is still that list price. An estimate
is not, which is why the models below get no definition at all.

Milliseconds rather than seconds for the two speech models, because a
usage value has to be a whole number and whole seconds are too coarse
for what a voice assistant actually hears: rounding a 0.4 second "ja"
up to one second would overcharge it by 150%.

The match pattern is what the backend compares the span's
`gen_ai.request.model` against, and that value is whatever your provider
entry names as its model, so a definition only ever fires for a
deployment that configured that model.

### Entering one

Against a Langfuse backend, a model definition is a `POST` to
`/api/public/models` authenticated with the project's own key pair:

```bash
# The same three variables the recording upload already reads, and the
# same rule: they live in the environment, never in a configuration
# file, and this server never prints them back.
curl -sS -X POST "$LANGFUSE_HOST/api/public/models" \
  -u "$LANGFUSE_PUBLIC_KEY:$LANGFUSE_SECRET_KEY" \
  -H 'content-type: application/json' \
  -d '{
        "modelName": "tts-1",
        "matchPattern": "(?i)^(tts-1)$",
        "unit": "CHARACTERS",
        "inputPrice": 0.000015
      }'
```

One request per row of the table above. The backend's own settings page
does exactly the same thing through a form, which is usually the easier
way to enter four of them and to see what a project already has; the
request is here because a deployment that is rebuilt from files wants
the four in a file.

`unit` is a closed set (`TOKENS`, `CHARACTERS`, `MILLISECONDS`,
`SECONDS`, `REQUESTS`, `IMAGES`) and the price keys are `inputPrice`,
`outputPrice` and `totalPrice`. Both halves are why vinga reports its
seconds and characters as INPUT: a usage number under any other key has
no price beside it, however carefully it was measured.

### With none of them entered

Usage is present on every span, and every cost the backend cannot price
on its own reads zero. That is correct rather than broken: the server
measured what it was given and the backend was never told what a
millisecond of audio is worth. Enter the definitions before the run
whose cost you want to read, because whether a backend goes back and
prices traces it has already taken in is that backend's own behaviour
and not something this server can promise on its behalf.

### The models that deliberately get none

An estimate entered as a price is worse than an empty column, because it
is a number a report adds up.

- **`gpt-4o-transcribe` and `gpt-4o-mini-transcribe`** are billed per
  audio token ($2.50 and $1.25 per 1M input tokens). The `asr` span
  carries milliseconds, and converting would take a tokens-per-second
  assumption. Their transcriptions show usage and no cost.
- **`gpt-4o-mini-tts`** is billed per audio output token ($12.00 per 1M),
  and the `tts_stream` span carries the characters the voice was given.
  Same reason, same answer.
- **ElevenLabs** bills in credits whose value depends on the plan, so
  there is no list price to enter at all.
- **Piper and faster-whisper** run in this process. There is no rate
  because there is no vendor, which is a true answer rather than a gap:
  what a local voice costs is the machine it runs on. They also report
  no usage: a local engine does not count what it was sent, and this
  server will not count it on the engine's behalf.

## The conversation store

**This keeps what was said in a database.** It is off by default and off
until `enabled` says otherwise, and a warning at startup says when it is
on. It names nothing further: which database a server records into is
its own configuration's answer, given once, rather than a line per
start, and a connection is not a thing a log line may carry.

```yaml
server:
  conversations:
    enabled: false
    # store the structured events and every measured number
    telemetry: true
    # store conversation text, and tool names, arguments and results
    text: true
    # prune conversations inactive for longer than this; 0 keeps
    # everything
    retention_days: 90
    # find and resume a past conversation by describing it out loud
    resumption: false
    # how much of a resumed conversation is rebuilt into the model's
    # context, in tokens
    resumption_budget_tokens: 6000
```

What lands is the `record` schema of the same database the
domain half's `domain` schema is in, which means the same instance, the
same credentials and the same backup: one row per session (device,
agents, protocol, the resolved providers, when it opened, when and why
it closed), one row per conversation (its agent, the device it began
on, a title taken from the earliest utterance stored on it, and when it
was last spoken to), one row per turn (what was heard and what was replied, the ASR,
LLM and TTS timings, the rounds and the token counts), one row per tool
call a turn made (its source, its arguments and its result), and one
row per structured event, which is the same decision track the capture
writes beside its audio. A turn names both the session it was spoken in
and the conversation it belongs to, so the two are views of one set of
rows rather than two records: one session can touch several
conversations, and one conversation can span several sessions. Audio never enters it: the capture is the recording,
this is the queryable record. The columns are documented in
[`../docs/reference/conversations-schema.md`](../docs/reference/conversations-schema.md),
generated from the schema itself, and `vinga-server conversations
schema` prints the same document.

The section's absence, and `enabled: false`, both mean the same thing:
no writer is started and no row is ever written. The tables are still
brought up to the current schema at every start, because empty tables
are not a recording and switching recording off does not make what was
already recorded unreadable.

The two switches under the flag are independent, and all four
combinations are supported configurations:

| `telemetry` | `text` | What a session keeps |
| --- | --- | --- |
| on | on | everything: the events, every measured number, and what was said |
| on | off | the events and the numbers; the text columns, tool names, arguments and results are null |
| off | on | what was said, with no events rows and the numbers null: the transparency-first setting |
| off | off | the session spine and the shape of each turn, and nothing else |

Session and conversation rows land in every enabled configuration,
because retention and every read key on them, and their timestamps
survive both switches for the same reason. A conversation's title is
the exception and is content, because it is what somebody said: with
`text: false` a thread has no title. Each session row also records which way the switches
were set for it, so a null column is distinguishable from a column that
was never stored.

**`resumption` is the third switch and the only one that is not about
storage.** It decides whether an agent can find one of its own past
conversations and carry on with it, and it is off by default, because
recording a conversation and reading it back to a model are separate
decisions. It reads what the other two wrote, so a configuration that
asks for it with `enabled` or `text` off is refused at boot in a
sentence naming both keys and both ways out. What it changes, once on:
the two
[conversation tools](../docs/run/tools-and-mcp.md) stop refusing, and picking a
conversation rebuilds the model's context from the stored dialogue,
newest turns first, up to `resumption_budget_tokens`. That budget is
approximate by design (the count is estimated from the stored
characters), what it drops when a thread is longer than it are whole
turns oldest first, and a thread rebuilt from its tail is told so, as
is one whose record has holes in it. Arguments and results of the tools
a turn ran stay in the store: what a rebuilt conversation carries is
what was said, and the names of the tools that ran.

A thread longer than that budget is not silently trimmed. The tool
answers with the choice instead, for the agent to put to the user: a
short recap of the whole of it, or carrying on from the recent part.
Carrying on from the recent part is the paragraph above and stores
nothing. A recap is the agent summarizing the thread once, against its
own model, and speaking that summary out loud; only when the user has
heard it to the end is it stored, as a checkpoint on the conversation,
and every later resume is rebuilt from that checkpoint plus what was
said after it. A recap cut off by an interruption, a voice that failed
or a device that went away is not stored at all, and the next resume
offers the same choice again; so is one the model could not produce,
and the thread is picked up from its recent part with the agent told
why. Recap text is conversation content like the dialogue it
summarizes: it lives under the `text` switch, is served by the API, and
is retained and deleted with its thread.

Off, nothing about a conversation's behaviour changes at all: an
agent's working context is assembled inside one session and ends when
the session closes, which is what this server always did.

**The switches are deployment-wide, and they are the only privacy
control this release has.** Until per-user controls exist, enabling text
storage on a device a household shares stores what guests say to it,
which is the same statement the capture section makes about audio.
Attributing a session on a shared device to one member needs voiceprint
identification, which does not exist here yet, so the units deletion is
expressed in are the conversation and the session: the first is what
retention takes whole, and both are what the erasure API will address.
Erasing either on demand is an act of the API with a CLI verb in
front of it, which the deletion section below says in full. The session id is surfaced everywhere regardless: on the
events, on the capture triplet's filenames, and on every row the store
keeps.

Retention is 90 days by default, and what the window is measured
against is a conversation's last activity, because the conversation is
the unit this store retains. A thread inactive for longer than the
window is deleted whole, with its turns; the events of a session older
than the window go on the session's own age, whether or not its row
survives; and a session row goes once no turn names it any more, so a
session that began before the cutoff while its thread is still being
talked to keeps the row those turns cross-reference. The pass runs at
startup and at each session close, and a line says how many
conversations and how many session records went. `retention_days: 0`
keeps everything, which is a deliberate choice rather than a default,
because a store with no policy retains forever. In a deployment that
never resumes a conversation this is the behaviour it always had: a
thread never spans sessions there, so its age and its session's
coincide.

**Deleting on demand is an act of the API.** `DELETE
/api/sessions/{session}` erases one named session; `DELETE
/api/sessions` with at least one of `?session=`, `?device=` and
`?before=` (combined with AND, the day strict) is the purge, answering
how many of everything it took; `DELETE
/api/conversations/{conversation}` erases one named thread out of
every session it touched, leaving session rows and events alone. In
front of them stand `vinga session delete`, `vinga session purge` and
`vinga conversation delete`, each confirming at a terminal and taking
`--force`. Erasure outranks every copy the store derived, not only the
rows named: a thread whose title came from an erased turn is renamed
from its earliest surviving turn or loses its title, recap checkpoints
that summarized an erased turn go along with everything descended from
them, the activity stamp falls back to what the survivors support, and
a thread left with no turns is deleted whole, because a title and two
timestamps are not a conversation.

A session that is still running when its row goes stops being
recorded: the writer finds the row gone and stops writing for that
session, so what is said afterwards is not recorded. Capture files are a
separate instrument and are never touched by any of this; the session id
is the correlation key for whoever needs to remove the matching triplet.

What deletion means is worth stating exactly, because the database
server decides it rather than this one. A deleted row is invisible to
every transaction that begins after the deletion commits, the
read-only `vinga_ro` role's included. A repeatable-read transaction
that was already in flight when it committed keeps seeing the row
until that transaction ends, which is what multi-version concurrency
is and not something this server can prevent: a query left open in a
terminal is one such transaction. Reclaiming the space the row
occupied is the instance's own storage maintenance (autovacuum), not a
per-delete overwrite, so the interval between the delete and the
reclamation is yours to tune rather than this server's to promise.
There is no write-ahead log to truncate here and no sidecar file to
take with it, and copies that have already left the database (a
`pg_dump`, a filesystem snapshot, a replica) are yours to manage.

**Read it live, as `vinga_ro`.** There is nothing to copy first, and
nothing to copy safely: the store is SQL, and the way in is a
read-only session as the role
[`../deploy/postgres-init.sql`](../deploy/postgres-init.sql)
provisions. It has `SELECT` on every table in the `record`
schema, now and after the next migration, and nothing at all on the two
schemas beside it: `domain`, where the stored secrets' ciphertexts
live, and `memory`, whose read surface is the addressed API under
[`vinga memory`](../docs/run/memory.md#reading-and-correcting-what-it-kept)
rather than raw tables:

```bash
psql "postgresql://vinga_ro@127.0.0.1:5432/vinga" \
  -c 'select * from record.turns order by id desc limit 20'
```

Its password under compose is `vinga_ro`, which is a loopback-only
convenience in the same way the server's own default password is. The
role also carries a `statement_timeout` and an
`idle_in_transaction_session_timeout`, which are not tidiness: a
reader's locks hold off the schema changes a migration makes, so a
session left open inside a transaction is what would make the next
boot's migration wait out its lock timeout and refuse. A database
provisioned without that file simply has no analyst role, and serves
exactly the same.

There is deliberately no analysis command, and the ids on `sessions`,
`conversations`, `turns` and `events` are identity columns a sequence
never hands out twice, so a client that has read up to one can ask for what came after
it and cannot be handed a different row under the same number.

Writing never happens on the conversation's path. One background thread
does every database call behind a queue nothing on the session loop ever
waits on, and it commits at turn boundaries and at session close, so a
page opened mid conversation reads everything up to the last completed
turn. A database that is wedged or locked drops events, says so once per
session, and records the count on the session row, and it never delays a
reply.

Turns and closes are never refused at the queue, whatever the backlog:
they are the record's structural truth and they arrive at conversational
pace. That is not a promise that a close always lands. A close whose own
transaction fails leaves the session row open-shaped, with a null
`closed_at` and no close reason, which is the same incomplete state a
process killed mid-session leaves behind: it is readable, it is listed,
and retention prunes it on `started_at` like any other. A line at
warning level says so when it happens.

## Running in a container

This has moved to
[Running vinga in a container](../docs/run/running-in-a-container.md),
and every other deployment task has a guide of its own in
[`docs/run/`](../docs/run/README.md).

## Status

vinga-server serves conversations end to end: OTA and WebSocket
endpoints, the VAD/ASR/LLM/TTS pipeline on pluggable providers, agents
bound to devices, MCP tools on both sides, device authentication,
onboarding by a short URL and an activation code, limits,
structured logging, and a published multi-arch container image. The v1
plan and its per-milestone implementation notes live in
[`docs/plans/`](../docs/plans/); getting a device on your desk onto it
is in [`../docs/devices/`](../docs/devices/README.md), and the wire it
speaks is in [`../docs/xiaozhi-notes.md`](../docs/xiaozhi-notes.md).
