# Securing a deployment

At the end of this guide you will know where each credential a
deployment uses is kept, and you will have a master key generated for
the credentials vinga stores encrypted, escrowed apart from the
database and its backups, with a way to rotate it. You will also know
which hosts your configuration reaches, how devices authenticate and
what protects the endpoint that issues their tokens, everything the
server exposes, and how to declare how far session data may travel,
which the server then enforces.

## Secrets

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
  first, comma separated; [The master key](#the-master-key) below
  generates one, says where it is kept, and rotates it.

  A stored secret takes precedence over an environment reference for the
  same slot, and `config show` marks the reference it displaces. With
  ciphertext stored and no key configured, or a key that does not open
  it, the server refuses to start naming the entity and the slot, and
  the API goes down with it, so the repair is the rebuild under
  [Recovering a deployment that will not start](recovering-a-deployment.md): boot on
  an empty database and put the configuration back, entering each
  credential again under a key that works. A slot whose value is gone
  for good is left to its environment reference by writing the entity
  without the stored one.

Instance configs stay out of the repository; `*.local.yaml` and `.env`
are gitignored for local experiments, and the domain half of a local
experiment is a short script of `config <noun> set` calls against a
database of its own, which `VINGA_DB_NAME` is enough to give it.

## The master key

**The master key is generated once and escrowed.** Set
`VINGA_MASTER_KEY` wherever the deployment keeps its environment
secrets, alongside `VINGA_AUTH_SECRET`:

```bash
python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
```

It is only needed once a credential is stored encrypted; a deployment
whose keys are all environment references never needs one. Once
ciphertext exists, losing the key means losing those credentials: the
server refuses to start with a stored secret it cannot open, naming the
entity and the slot. That refusal takes the API with it, so the way back
is the rebuild under
[Recovering a deployment that will not start](recovering-a-deployment.md):
boot on an empty database, import a kept export, enter the credentials
again and apply, which leaves no unopenable envelope behind. The key
the credentials are then entered under need not be the lost one; what
the next boot needs is a key list that opens every envelope stored, and
after a rebuild every one of them was written under the key in use.

**Rotation adds a key, and no command retires one.**
`VINGA_MASTER_KEY` holds a comma-separated list, newest first;
encryption always uses the newest and decryption tries them in order. A
new key therefore only affects secrets written after it, so every old
key must stay in the list for as long as any token written under it
remains in the database. Re-running `config <kind> secret set` for
each stored secret rewrites it under the newest key, which is how an
old key stops being needed: no command re-encrypts the stored secrets
for you.

## Which hosts a configuration reaches

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

## Device authentication

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
[Running vinga in a container](running-in-a-container.md)).

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

## The OTA endpoint

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

## What is exposed

**Nothing else is exposed.** `/x/<key>/`, `/xiaozhi/ota/` (or wherever
you put it), each with an `activate` beneath it that a waiting board
polls, `/xiaozhi/v1/`, `/healthz`, `/readyz`, and the configuration API under
`/api/`, which answers 401 to anything not carrying its bearer token. FastAPI's
`/docs`, `/redoc`, and `/openapi.json` are turned off on both
applications, and `server.ota_path` refuses a path under `/api/`: the
OTA route is registered before the API is mounted, so it would be found
first and would answer a request the token gate never saw.

## The data boundary

**Fully local is checked, not hoped for.** This section is how the
server keeps
[the first-class local deployment](../architecture/product-promises.md#a-fully-local-deployment-is-first-class),
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
