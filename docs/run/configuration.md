# Configuring a deployment

At the end of this guide you will know which half of the configuration
a setting belongs to and where each half is kept, you will be able to
write a whole deployment from one document with two commands, and you
will know when an edit made to a running deployment takes effect,
which of the two ways it gets there, and how to install a stored
change on the running server without a restart.

## The two halves

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
[`docs/reference/server-config.md`](../reference/server-config.md)
is the complete contract: every key with its type, default, bounds and
description, the environment overrides, and the combinations refused at
boot, generated from the models by `vinga-server config reference
server` and diffed by CI.
[`config.example.yaml`](../../vinga-server/config.example.yaml) is the annotated starting
point to copy, with a comment per key in its own voice,
and [`config.deploy.example.yaml`](../../vinga-server/config.deploy.example.yaml) is a
ready-to-adapt profile for the container image behind a proxy on a small
CPU quota, holding values validated by latency measurements from a live
deployment. That profile's domain half is the runnable script beside it,
[`config.deploy.example.sh`](../../vinga-server/config.deploy.example.sh), which the test
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
[`docs/reference/cli.md`](../reference/cli.md) is the CLI's own
page: installing it, reaching a server, rebuilding one, and every
command's help.

A whole deployment, from an empty database, is one document and two
commands. [`examples/presets/`](../../vinga-server/examples/presets/) holds two of them, a
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
[`examples/`](../../vinga-server/examples/) holds a commented fragment per entity for
writing one at a time with a noun's own `set`, which is what editing a
deployment looks like once it exists.

A board in front of you needs neither its MAC nor that `device bind`
line: `config device pending list` lists what is waiting and `config device pending claim`
binds one by the code on its screen. That is
[Onboarding a device](onboarding-a-device.md).

The rules about a runnable server (every stage of every agent
resolving, a default agent when nothing is bound) are checked at boot
rather than at write time, so a half-built database is a legitimate
state to be in and an illegitimate one to serve from.

**When the server will not start**, there is nothing to write through,
and the way back is to rebuild the store rather than to operate on it:
stop the server, delete the database, boot clean, import the export
taken while the deployment was healthy (`import -f`), re-enter the
credentials that export listed, and apply. That is
[Recovering a deployment that will not start](recovering-a-deployment.md),
in the task guides.

Every field of the domain half is documented in
[`docs/reference/domain-config.md`](../reference/domain-config.md),
generated from the models: `vinga-server config reference` prints that
same document, `vinga-server config reference server` prints the server
half's page beside it, and `vinga-server config schema [entity]` prints
the JSON Schema behind the domain one. The command line itself is
[`docs/reference/cli.md`](../reference/cli.md), whose command
pages and recipes are generated the same way, by `vinga-server config
cli-reference`. [`examples/`](../../vinga-server/examples/) holds a commented fragment per
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

## An edit changes nothing until it is applied

This is the trap of a configuration a running server is not re-reading
on its own: **an edit is stored and changes nothing until something
applies it.** A `config
set` against a running deployment is accepted by that server and is not
in effect when the command returns, which both the command and the API's
answer say every time they write. There are two ways it becomes
effective, and each write says which case it is in: everything in the
domain half, from a provider entry to an agent to the defaults under
them, reaches a running server when it is asked to apply; a device
binding and the default agent reach it at that device's next check-in,
with nothing asked of the server. Renaming an agent is the one write here
that is not an edit of the document: it moves the stored references in
one transaction, its memory and its conversation threads with them, so
nothing is left behind under the old name. What it shares with every
other domain write is the window above, and that window is where the
exception to "nothing left behind" lives: the running server goes on
serving the old name until an apply installs the new one, so a
conversation still in flight remembers under the old name until then,
and `vinga memory list agent` is where such a row shows up.

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
[`docs/reference/cli.md`](../reference/cli.md) is where it is
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
