# Running vinga in a container

At the end of this guide you will have one vinga-server container
running from the published image, on a database you provide, with a
provider written into its configuration and installed, and an image
tag chosen on purpose rather than the one that moves.

## The container

This is the single container and what it needs, which is what a
deployment composes into whatever it already runs. For a trial, the
`docker-compose.yml` at the repository root says all of it once, for
the server and its database together, and the project README's
[Getting Started](../../README.md#getting-started) fetches and runs it
in two commands; that file is the trial and development story rather
than the deployment story, and this guide and the others in
[`docs/run/`](README.md) are the one home for what a deployment has to
decide.

These guides stay that home, and
[`../deployment.md`](../deployment.md) is the worked path through
them: the same contract in a Docker Compose lane and a Kubernetes
lane, against the committed artifacts under
[`../../deploy/`](../../deploy/).

**Run one replica.** Everything a running server serves from is state
in its process: the pending activation codes new devices show, the
configuration generation an apply swaps in, and the `max_sessions`
count the door enforces. A second replica against the same database
would mint activation codes the first cannot claim, keep serving its
boot-time configuration after an apply lands on the other, and enforce
a separate session cap of its own. The two probes exist so an
orchestrator can manage this one replica's lifecycle (a rollout, a
restart, a drain), not so a balancer can spread devices across
several.

The default image carries both local engines, so one seeded database
serves a conversation. The database itself is the deployment's to
provide, and the server refuses to boot without one it can reach. It
starts on whatever that database holds (nothing, the first time, which
is a valid state to serve), and
the domain half is written into it over the API it is already serving,
with the `vinga` client on whichever machine administers this
deployment. The image ships that same client under the server's own
entry point, so a shell inside the running container is the alternative
where the API is not routed outward: the token and the loopback address
are already in its environment.

**A configuration file is optional.** Every key of the server half has a
default and every one of them is overridable with a `VINGA_`-prefixed
variable, so a container started with nothing mounted at `/config`
serves on those. Mount a YAML there and the image reads it, which is
what a deployment past a handful of keys wants; the two lines after it
write one provider into the domain half and install it:

```bash
docker run -d --name vinga \
  -p 8003:8003 \
  -e VINGA_API_SECRET \
  -e VINGA_AUTH_SECRET \
  -e VINGA_DB_HOST -e VINGA_DB_NAME -e VINGA_DB_USER -e VINGA_DB_PASSWORD \
  -v /path/to/config.yaml:/config/config.yaml:ro \
  -v vinga-data:/data \
  ghcr.io/rafacm/vinga-server:latest

vinga provider set llm claude type=anthropic model=claude-sonnet-5 api_key_env=ANTHROPIC_API_KEY
vinga apply
```

An entry that fits on a line is written on one, with no file to name and
no directory to be in. A credential is never one of those arguments:
arguments land in the shell's history and in the process list, which is
why the field above names the variable holding the key rather than the
key.

Past a screenful, the same entry comes from a file instead, and the
commented fragments under
[`vinga-server/examples/`](../../vinga-server/examples/) are what
those files look like. The two spellings write the same entry, and this
one is run from a checkout's `vinga-server/` directory, where the
fragment it names is:

```bash
vinga provider set llm claude -f examples/llm-anthropic.yaml
```

- `/config/config.yaml` is the server half, and mounting it is optional.
  The image's entrypoint names that path when a file is there and names
  nothing when it is not, so an unmounted container boots on the
  defaults and whatever `VINGA_SERVER__*` says. Mount it read-only;
  override any key of it with a `VINGA_`-prefixed environment variable.
  Setting `VINGA_CONFIG` yourself always wins, mounted file or not, and
  a path you name and that is not there is refused rather than ignored.
- `/data` is the volume every engine caches into (`HOME` points there):
  whisper models and Piper voices download at first start and survive a
  new image. Model weights are never baked in.
- The database is not on that volume and not in this container: the
  image sets no database variable at all, and the deployment points
  `VINGA_DB_HOST` and the rest of that family at the Postgres it
  provides. Both schemas are migrated on first open, so there is no
  init command to forget, and a database the server cannot reach is a
  boot that refuses with a sentence rather than a container that waits.
  Give it a restart policy, which is where that decision belongs.
- Logs default to `json` in the image, which is the only default that
  differs from running it directly. Override with
  `VINGA_SERVER__LOG_FORMAT=text`.
- The healthcheck assumes the default port; change `server.port` and
  override `--health-cmd` too.
- A read-only root filesystem works: add `--read-only --tmpfs /tmp` and
  keep the two mounts.
- Stop it with `docker stop -t 30 vinga`, above `drain_s`, so
  conversations in flight finish their sentence.

**The container refuses to boot without `VINGA_API_SECRET`.** The
configuration API is always mounted and always gated, so the boot error
names the variable and prints a way to generate a value
(`openssl rand -hex 32`). Keep it wherever the deployment keeps
`VINGA_AUTH_SECRET`; `server.api.secret_env` renames the variable for a
deployment whose convention is another one.

Behind a TLS-terminating proxy, either set `server.websocket_url`
explicitly or pass the proxy's address in `FORWARDED_ALLOW_IPS`, which
uvicorn honours from the environment.

## Choosing an image

Two variants are published, built from one Dockerfile so they cannot
drift. They are the same server; the only difference is which optional
extras are installed.

| Variant | Tags | Carries | Use it when |
| --- | --- | --- | --- |
| default | `latest`, `2026-08-03-120015`, `sha-3f9362a2b1c8` | both local engines | any config naming `faster_whisper` or `piper`, and anything fully local |
| slim | `slim`, `2026-08-03-120015-slim`, `sha-3f9362a2b1c8-slim` | neither | ASR and TTS both name external providers |

The default variant is the unsuffixed one, following the convention
that an unqualified tag is the batteries-included image (as in
`python:3.12` against `python:3.12-slim`). Nothing about `latest`
changed when slim arrived.

Slim is 494 MB against the default's 883 MB, a saving of 389 MB, and it
contains no GPL component. The saving is mostly not piper: `faster-whisper`
brings its own inference stack, which is why the reduction is much larger
than the size of the engines themselves.

`silero` VAD is in both. It is a core dependency rather than an optional
extra, it is light, and it runs on every audio frame whichever ASR
provider is configured, so a slim deployment still segments speech
locally.

A slim image given a config that names a local engine refuses to start,
naming the extra it lacks:

```
providers.asr.whisper: type "faster_whisper" needs the faster-whisper
extra; install it with: uv sync --extra faster-whisper
```

That message is written for a source checkout. In a container the answer
is not to install anything but to pull the default variant instead.

Both variants are published for amd64 and arm64, and each has passed the
unit, integration, and smoke lanes: the same whole-conversation smoke
test runs against both. What a tag names is what was smoked, by digest:
each architecture is built exactly once, pushed to the registry
addressed by the digest of those bytes, and pulled back by that digest
for the smoke, and the manifest a tag points at is assembled from the
digests rather than from a rebuild of the same source.

The moving tag is the only one that moves, `latest` for the default
variant and `slim` for slim, so it is the tag to pull when trying the
server and the wrong one to deploy from. Before moving one, CI reads
which commit the image it currently points at was built from, and
leaves the tag where it is when that commit is the newer one or when
it cannot tell. That is a check rather than a lock: two merges
publishing in the same instant can both read the tag before either
writes, so a moving tag can still end up on the older of them until
the next push moves it on. It moves under whatever is pulling it
either way, which is the reason it is the wrong tag to deploy from.
The dated and
SHA tags are never reused: several merges can land on one day, and
each gets its own timestamp to the second, so a rollback names the
build it wants.

**Pair the two variants by their SHA tag, not their dated one.** Each
variant's dated tag is the second its own manifest was assembled, and
the two are assembled by jobs that start together, so the two
timestamps now usually agree and are not guaranteed to. The dated tag
is honest about when each image was published; `sha-<revision>` is the
one that says which commit, and it is equal across both variants by
construction.

The default image contains `piper-tts` (GPL-3.0) alongside the MIT
server. That is aggregation, not a derived work; the slim variant
contains no GPL component at all. See
[`THIRD_PARTY_LICENSES.md`](../../THIRD_PARTY_LICENSES.md).
