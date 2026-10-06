# Giving an agent tools

At the end of this guide you will have connected an agent to MCP
servers, narrowed which of their tools each agent may call, written
the guidance the model is given about them, and be able to see which
servers are connected and which tools each agent can reach.

Every field of an MCP server entry is in the domain configuration
reference under [MCP server](../reference/domain-config.md#mcp-server),
and the object form of a grant under
[MCP grant](../reference/domain-config.md#mcp-grant). The status
command is in the CLI reference under
[`vinga mcp-server status`](../reference/cli.md#vinga-mcp-server-status).
The memory tools have a guide of their own,
[Configuring what an agent remembers](memory.md), and the whole prompt
an agent is sent, guidance included, is
[Composing what an agent is told](agents-and-prompts.md).

## Tools

Beyond speaking, an agent reaches three kinds of tool, merged into one
list the model sees and told apart by the shape of their names.

**MCP servers** are named entries under `mcp_servers`, the way providers
are, and an agent references them through an `mcp` list that
`agent_defaults` can supply. Naming a list replaces the inherited one
rather than extending it, so `mcp: []` is how an agent opts out of tools
its siblings have. Each server's tools are offered under its entry name
(`home__turn_on_light`), which is why an entry name has to be a plain
`[A-Za-z0-9_-]+` name and cannot be `self` or a builtin's name
(`switch_agent`, `remember`, `update_memory`, `forget`,
`restore_memory`, `recall`, `set_state`, `clear_state`,
`new_conversation`, `resume_conversation`, `set_device_location`). Both
transports the
specification defines are supported:

```bash
vinga-server config mcp-server set home -f - <<'YAML'
transport: stdio
command: mcp-proxy
args: ["http://homeassistant.local:8123/mcp_server/sse"]
env:
  API_ACCESS_TOKEN: $HOME_ASSISTANT_TOKEN
YAML

vinga-server config mcp-server set weather -f - <<'YAML'
transport: streamable_http
url: http://localhost:8000/mcp
headers:
  Authorization: Bearer $WEATHER_TOKEN
tool_timeout_s: 15
YAML
```

**SSE-only servers** are reached through a bridge rather than a
transport of their own. Point `mcp-proxy` at the endpoint and configure
the result as the stdio server it now is, which is what the `home` entry
above does:

```yaml
transport: stdio
command: mcp-proxy
args: ["https://example.invalid/mcp_server/sse"]
```

vinga implements no SSE transport of its own; an SSE-only server is
reached through the `mcp-proxy` bridge. The specification moved its
HTTP story to streamable HTTP and left SSE deprecated, which is why the
bridge, rather than a third transport, is the way in. The bridge is
one line of configuration and everything else about the entry,
secrets, reach, grants, the timeout, is the same as any other stdio
server's.

**Per-tool grants.** An `mcp` entry is either the entry name on its own,
which is the whole server, or an object naming the server and the tools
of it that layer may reach:

```bash
vinga-server config agent set kids -f - <<'YAML'
prompt: You are the assistant in the kids' room.
mcp:
  - weather
  - server: home
    tools: [turn_on_light, turn_off_light]
YAML
```

The tools are named the way the model is given them minus the entry
prefix (`turn_on_light` for `home__turn_on_light`), which is the name
`vinga-server config mcp-server status` prints, so an operator writes
down the name they read; what the server called the tool before the publishing
rule got to it is never a name this side answers to. Leaving `tools` out
of the object means the whole server, the same as the string form, and
an empty list is refused: "granted, nothing allowed" is a confusing
spelling of `mcp: []`. It is an allow list and there is no deny list,
because a denied set fails open: a kitchen-sink server that adds a tool
would silently grant it to every agent that denied the old ones, which
is exactly wrong on the shared family device the feature exists for. The
same grant is checked again when a call arrives, so a tool an agent was
not offered is refused rather than run if the model asks for it anyway.

An allow list cannot be checked when it is written, since only a live
connection knows what a server publishes. A name that matches nothing is
logged when the server's tools come out of the publishing rule, and
`config mcp-server status` shows each agent's allowed tools beside the
published ones, so the mismatch is answerable in one read. The comparison is
against what published rather than against what the server listed: a
tool dropped for a name collision or for being too long once prefixed is
exactly as unreachable as one that was never offered.

Secrets follow the same rule as everywhere else: `$NAME` is read from
that environment variable at startup, and any secret-looking key
(`token`, `api_key`, `authorization`, ...) must reference a variable
somewhere in its value. The reference may be the whole value or sit
inside a larger one, so `Authorization: Bearer $WEATHER_TOKEN` keeps the
word `Bearer` in the configuration instead of inside the secret. An
unset variable fails the boot of an entry some agent references (one
nobody references is never connected, so its variables are never
read), as does an unknown reference or a reserved entry name. A server that is merely unreachable does not: it
logs a warning, contributes no tools, and reconnects in the background
when a session that would use it opens.

**Guidance for a server's tools.** A tool's own description says what
it does; how this deployment wants it used is the operator's, and it
belongs beside the server rather than copied into every persona that
was granted it. An entry's `instructions` is that text, injected into
the system prompt of every agent the entry is granted to:

```bash
vinga-server config mcp-server set home -f - <<'YAML'
transport: stdio
command: mcp-proxy
args: ["http://homeassistant.local:8123/mcp_server/sse"]
instructions: |
  The lights, the blinds and the front door are on this server. Turn
  lights on and off freely. Always ask the user to confirm before
  unlocking the door.
YAML
```

It is stored and injected as written, its indentation and its own blank
lines included, and it goes into the prompt under a heading naming the
prefix its tools carry (`home__`), so the model can tie the paragraph to
the names it can call. The only bytes trimmed are whitespace at the two
ends of the whole assembled prompt, and what
[the prompt preview](agents-and-prompts.md#what-the-model-is-actually-sent)
reports is trimmed with them: what it counts is what the model receives.

The grant is the whole condition. Every agent granted the entry is told
about it, whether or not the server is connected and whatever an allow
list narrows its tools to; an agent with `mcp: []` is told none of it.
That means guidance about a tool a particular agent cannot reach is
noise in that agent's prompt, and the answer is to write about the
surface the agents are actually granted, not to expect the server to
work it out. Guidance is whole-entry: an entry whose tools want two
different paragraphs is two entries.

Editing it does not restart the connection, since it is prompt text the
connection never sees, so an apply reports the entry as `unchanged` and
the tools do not blink. What that costs is stated rather than hidden:
the new text reaches a conversation at its **next activation**, a new
session or an agent switch, and a conversation already running keeps
the text it was activated with until it ends. Sessions are minutes
long, so what an edit buys is the next one.

**Guidance the server ships about itself** is a different thing, and it
is off. A server has two channels of its own: the `instructions` of its
handshake, which the specification describes as how to use the server
and its features, and the prompts it publishes. Both are a third party
writing part of your agent's system prompt, so each is an explicit
opt-in on the entry, and there is no way to turn them on for a whole
deployment at once:

```yaml
use_server_instructions: true
inject_prompts: [forecast_style]
```

`use_server_instructions` injects the handshake's text. What a server
ships is captured on every connect whether or not the entry opted in,
so turning it on applies at the next apply with no reconnection, and
turning it off stops the injection while the connection stands.

`inject_prompts` names published prompts, one at a time, by the name
the server lists them under. Wholesale is not offered: the
specification defines prompts as user-controlled templates and a server
may publish dozens, so the operator who read its documentation names
the ones that are standing guidance. The names are checked against the
server's own listing before anything is fetched, and a name it does not
publish, a prompt that declares required arguments, and one that
renders anything but text are each skipped with a warning naming the
entry and the **position in the list**, never the name: a prompt name
is a string the server chose and you copied, so it may hold anything,
and the same is true of every byte of what it publishes. None of it is
ever written to a log. Editing the list changes what a connect fetches,
so applying it does restart the connection.

**One thing is taken back out.** Whatever this deployment gave the
entry in its `env` or `headers` is replaced with `[redacted]` in what
the server ships back, before any of it is stored. Opting in is a
decision about a third party's words, not a decision to let that server
hand your own credential back through a prompt or a gated read, and a
careless server that echoes what it was configured with is the ordinary
case rather than the hostile one. Values shorter than eight characters
are left alone, since an `env` holds ports and locales too, unless the
value is known to be a credential: one read from the variable a
secret-bearing key references, and a stored secret, are replaced
whatever their length.

Both channels are capped at 4000 characters per block, and a longer one
is skipped whole rather than truncated: half an instruction is an
instruction nobody reviewed. What is injected appears under
`server_instructions:<entry>` and `server_prompt:<entry>:<position>` in
[the prompt preview](agents-and-prompts.md#what-the-model-is-actually-sent),
with a heading in the prompt itself saying the
server is the one talking, so neither you nor the model has to guess
whose words they are. The prompts are re-fetched on every reconnect,
which reaches new sessions and switched-in agents the way an apply's
guidance does.

**The device's own tools** need no configuration. A board whose hello
advertises `features.mcp` is asked for its tools over the same socket
the audio runs on, and they arrive under their firmware names with the
dots replaced (`self_audio_speaker_set_volume`), because both LLM APIs
restrict tool names to `[A-Za-z0-9_-]`.

**Builtins** are `switch_agent`, offered when the device is bound to
more than one agent; the memory family (`remember`, `update_memory`,
`forget`, `restore_memory`, `recall`) and the conversation ledger's
`set_state` and `clear_state`, offered to every agent whose `memory`
section leaves them on, which is every agent that does not say
otherwise; and `new_conversation`, `resume_conversation` and
`set_device_location`, which records where the board now is when
somebody says it has been moved, always offered.

A successful `switch_agent` ends the current agent's reply: the new
agent greets the user in its own prompt and its own voice, on its own
conversation. It does not read what was said to the outgoing agent,
because a conversation is a thread between a user and exactly one agent
and each agent keeps its own; switching back returns an agent to what
it was saying.

`new_conversation` and `resume_conversation` move the session between
threads of the agent that is already speaking, and both need
[`server.conversations.resumption`](../reference/server-config.md#serverconversations).
Without it they answer a
fixed sentence saying this server does not keep conversations that can
be picked up again, which the agent reads out, and nothing moves.
`resume_conversation` takes a `description` of what the user is looking
for and answers a short list of the agent's own past conversations to
read out, then takes the one the user picked; only a conversation the
tool has just offered can be resumed, so a model cannot reach a thread
by guessing an id, and never one belonging to another agent. A thread
too long to hand over whole answers with a choice rather than with the
thread, and the third argument, `start_from`, is the user's answer to
it; it is honoured only for the conversation the tool actually asked
about, so a model cannot consent to a recap on the user's behalf.

A tool that fails, times out, or does not exist comes back to the model
as an error result rather than ending the reply, so the assistant says
what went wrong in its own voice and the user's language. The device
hears silence while a tool runs, bounded by the entry's
[`tool_timeout_s`](../reference/domain-config.md#mcp-server).

**What a tool answers with is speakable text.** The output of this
pipeline is a voice and its history is text throughout, so text is what
a result contributes. A server that answers with an image, or with
anything else the specification allows, has that part rendered as a
named placeholder (`[unsupported image content]`) rather than dropped:
the model can then say what it was given and that it cannot use it,
which is better than a reply that reads as though the tool was ignored.
The device path renders speech and nothing else, so no result carries
structured content to the board.

## What the MCP servers are doing

The configuration says what should be running; `vinga-server config
mcp-server status` says what is:

```console
$ vinga-server config mcp-server status
home: connected since 2026-08-13T09:12:03.104213+00:00
  tools: home__turn_on_light, home__turn_off_light, home__unlock_door
  agents: house, kids (turn_on_light, turn_off_light)
weather: down since 2026-08-13T10:41:57.882014+00:00 (ConnectionRefusedError)
  tools: (none)
  agents: house
archive: unused since 2026-08-13T09:12:02.991044+00:00
  tools: (none)
  agents: (none)
```

Three states. **connected** is offering the tools listed under it.
**down** is not, with the reason beside it: the class of the failure, or
`DroppedAfterFailedCall` for a connection dropped after a tool call
failed on it, which is what a server restarting looks like from here. A
down server contributes no tools and is reconnected in the background
when a session that would use it opens, so this is a diagnosis rather
than a chore. **unused** is configured and referenced by no agent, so no
connection was ever built for it: the answer to "why does the agent not
have that tool" when the entry looks right, and invisible everywhere
else.

Each agent under `agents:` is named on its own when it may reach the
whole server, and with its allowed tools in parentheses when it was
granted only some of them. That list sits beside the published one, so
an allowed name the server does not actually offer is answerable in one
read.

It is a read of the running server rather than of the database, which is
why what it says cannot disagree with what is actually connected. Over
the API it is `GET /api/runtime/mcp-servers`, keyed by entry name. The `/runtime`
namespace is separate from the entity namespaces on purpose: an
`mcp_servers` entry may legally be named `status`, and a runtime route
under `/mcp-servers/` would have shadowed it. The CLI's
`mcp-server status` has no such problem and is not an exception to it:
there the word is a verb of the grammar, in the slot a verb is read
from, and an entry name is only ever an argument after one.

The tool lists are published names and nothing else, deliberately: a
description, or the name a server listed before the publishing rule got
to it, is bytes that server chose, and a server holding one of this
deployment's credentials could reflect it in either. Published names
are the exception because the model has to be given them and an
operator has to be able to write one down.
