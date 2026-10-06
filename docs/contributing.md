# Contributing to vinga

At the end of this page you will have a checkout that runs the server
from source against a local Postgres, and you will know the five lanes
a change is exercised in before it ships: the unit and integration
lanes, which CI runs on a change that touches the server, its
references or its deployment files (a documentation-only change runs
the documentation workflow instead, and which paths run which workflow
is the CI paragraph under [`AGENTS.md`'s Commands](../AGENTS.md#commands)),
the opt-in local lane that holds a real conversation on local engines,
the smoke lane that holds one with a running container, and the
browser lane that holds three with the browser client in headless
Chromium.

The workflow every change follows (branches, commits, plans and their
records, the changelog fragment) and the design and writing
conventions are in [`AGENTS.md`](../AGENTS.md). Running and
configuring a deployment, rather than changing the code, is the task
guides' subject, in [`run/`](run/README.md).

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
published image beside it, which reads `VINGA_API_SECRET` from a `.env`
beside the compose file, as the quick start writes it, and refuses to
start without one. A checkout that runs the server from source
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
they need no keys, no model downloads, and no network, apart from the
integration lane's tier-closure tests, which build throwaway installs
with `uv sync` and download packages when uv's cache is cold.

### The local lane: a real conversation

CI never touches real engines. To check the overall work with them, an
opt-in third lane holds one real conversation end to end: it starts a
real server on the fully local pipeline (Silero, faster-whisper, Ollama,
Piper), speaks a Piper-synthesized question through the device simulator,
and asserts the transcript and a coherent spoken reply. Two more tests
ride the same lane and the same summary: tool calling against the real
model, with a pre-flight of its own for a model that can call tools, and
two personas.

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
model). By default it talks to Ollama's OpenAI-compatible endpoint at
`http://localhost:11434/v1`, which is the form `VINGA_LOCAL_OLLAMA`
takes too, and prefers
`qwen3:8b`, falling back to the first installed model;
`VINGA_LOCAL_OLLAMA` and `VINGA_LOCAL_LLM_MODEL` override both. The
first run downloads the whisper model and Piper voice at server startup
and can take a few minutes; later runs finish in seconds. Without
`VINGA_LOCAL_LANE=1` the lane skips, so a bare `pytest` stays safe,
though even a skipping run needs the development database reachable,
since the lane provisions its stores when it is collected.

### The smoke lane: a conversation with a container

A fourth lane runs nothing itself. It points at a server that is already
up and holds one whole conversation with it: both probes, an OTA check whose
token it verifies, that the root and the interactive API documents answer
404, and a full utterance-to-audio exchange through the device
simulator, and, when `VINGA_SMOKE_REVISION` is set, that the container
names that build. CI runs it against the image it just built, seeding
that image's own CLI into the database it then reads, which is what
turns "a seeded database and one `docker run` serve a conversation"
into something checked rather than remembered.

Both containers below have to reach the same database, and a container
does not reach the development instance at `127.0.0.1`, since that
address is its own. Join them to the network compose made for it
(named after the project's directory, with `_default` after it, which
the block below asks compose for) and name the service instead, which is what `VINGA_DB_HOST` is doing here; CI
does the same thing with a network and a database container of its
own. The lane also gets a database of its own, `vinga_smoke`, because
the seed below writes a whole configuration and would otherwise replace
the development configuration in `vinga`; `createdb` runs inside the
compose database container, over its own socket.

```bash
# From vinga-server/. Once: the lane's own database.
docker compose exec postgres createdb -U vinga vinga_smoke

docker build -t vinga-server:local .

# The network compose made for the database. Compose names it after
# the project, which is the directory the compose file is in, so a
# checkout under another name has another network; ask compose.
net=$(docker compose config --format json | jq -r '.networks.default.name')

# Throwaway values for this run alone, never a deployment's. They reach
# the containers by name (-e NAME, value from this environment) rather
# than in docker's own arguments, which is how CI hands them over too.
export VINGA_AUTH_SECRET=smoke-secret VINGA_API_SECRET=smoke-api-token

# The domain half first, written by the CLI from the image itself into
# the database the server then reads. tests/smoke/seed.sh is what CI runs:
# it starts a server of its own inside this container, configures it over
# loopback, and stops it again, which is why the container gets what a
# server needs.
docker run --rm --network "$net" \
  -e VINGA_AUTH_SECRET \
  -e VINGA_API_SECRET \
  -e VINGA_DB_HOST=postgres \
  -e VINGA_DB_NAME=vinga_smoke \
  -v smoke-data:/data \
  -v "$PWD/tests/smoke:/smoke:ro" \
  -v "$PWD/tests/smoke/config.yaml:/config/config.yaml:ro" \
  --entrypoint sh vinga-server:local /smoke/seed.sh

docker run -d --name vinga-smoke -p 8003:8003 --network "$net" \
  -e VINGA_AUTH_SECRET \
  -e VINGA_API_SECRET \
  -e VINGA_DB_HOST=postgres \
  -e VINGA_DB_NAME=vinga_smoke \
  -v smoke-data:/data \
  -v "$PWD/tests/smoke/config.yaml:/config/config.yaml:ro" \
  vinga-server:local

VINGA_SMOKE_OTA_URL=http://127.0.0.1:8003/xiaozhi/ota/ \
  uv run pytest tests/smoke -v
```

The secret has to match the one the server under test was started with:
the lane verifies the token it is issued, and that needs the signing key.
It skips without `VINGA_SMOKE_OTA_URL`, so a bare `pytest` stays safe,
and it works against any reachable server, not only a container.

### The browser lane: the page in Chromium

The browser client is JavaScript the server ships, and no Python test
runs it, so a fifth lane loads the real page in headless Chromium and
holds three whole conversations with it: one in realtime with a
barge-in, an interruption and the idle timeout's ending; one with echo
cancellation unavailable, in auto mode; and one in which the server
discovers the page's device tools and calls one. The microphone is a
fake capture device playing a sentence the simulator ships
([`tests/browser/speech.wav`](../vinga-server/tests/browser/speech.wav),
written by `tests/browser/make_speech.py`), and what the lane asserts
it reads from outside the page where it can: the server's events and
log, the websocket frames Chromium saw, and the device record. That
the reply reached the speaker is the one thing only the page knows,
and it says so only when its address carries the lane's switch.

It serves the page from what ships rather than from the checkout:
[`tests/browser/run.sh`](../vinga-server/tests/browser/run.sh) builds
the wheel, installs it into an environment of its own constrained to
the lockfile, starts the server from that install on a database of
its own, and runs the cases. It runs inside Playwright's own image, at
the version the `browser` dependency group locks, because the browser
build and the system libraries it needs come with that image; it needs
no Node toolchain and installs nothing on your machine. CI runs it on
every server-workflow event, once against the wheel and once against
the image it built.

```bash
# From vinga-server/, with the development database up. The container
# joins the network compose made for it, as the smoke lane's do, and
# names the database service. The volume keeps uv's cache between runs.
net=$(docker compose config --format json | jq -r '.networks.default.name')
docker run --rm --network "$net" --ipc=host \
  -e VINGA_DB_HOST=postgres \
  -v "$PWD:/work" -w /work \
  -v vinga-browser-uv:/root/.cache/uv \
  mcr.microsoft.com/playwright/python:v1.63.0-noble \
  sh tests/browser/run.sh
```

Arguments after `run.sh` are pytest's (`-k auto`, `-x`). A failing
case prints what the page and the server were saying; set
`VINGA_BROWSER_KEEP_LOG` to a path under a mounted directory to keep
the server's whole log as well. The lane writes nothing into the
checkout, and nothing under `tests/browser/` is collected unless the
lane is run this way, so a bare `pytest` stays safe.

