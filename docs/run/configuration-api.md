# Using the configuration API

At the end of this guide you will be able to send an authenticated
request to a deployment's configuration API, you will know which
families of routes it serves and where every route, body and refusal
is specified, you will be able to read what a write's answer says
about when it takes effect, and you will know how the `vinga` client
finds a server and what it refuses to send.

## The contract and the token

The domain half is read and written over a REST API the server mounts at
`/api` on its own port. It is what `vinga-server config` talks to, and
it is the machine-readable way in for anything else. The contract is the
committed OpenAPI document,
[`docs/reference/api-openapi.json`](../reference/api-openapi.json):
every route, the schema of every body, and the refusals each route can
answer with. It is generated from the routes themselves by
`vinga-server config openapi`, and CI fails when the committed copy
differs from a fresh generation, so it cannot drift from what is
served. The API itself serves no interactive docs and no
live schema endpoint; the committed file is the contract.

**Every request carries a bearer token.** The API is always mounted and
there is no flag that turns it off, because an admin surface that can be
switched off by forgetting a key is a surface that ships unprotected.
The token is the value of the environment variable
`server.api.secret_env` names, `VINGA_API_SECRET` by default, and a
server started without it refuses to boot, naming the variable and the
fix. Generate it once, straight into the file the deployment keeps its
environment secrets in, readable by its owner alone (here `vinga.env`,
which `docker run --env-file` or a compose `env_file:` reads), so the
value is never expanded by the shell, where tracing would print it:

```bash
touch vinga.env && chmod 600 vinga.env
{ printf 'VINGA_API_SECRET='; openssl rand -hex 32; } >> vinga.env
```

A request with no token, or with the wrong one, is
answered 401 whichever path it asked for, whether or not that path is a
route: only an authenticated caller gets to learn which routes exist.
One request, for the shape of them, with the token in a curl
configuration file only you can read, so that its value is never
expanded into a command line, where the process table and shell
tracing would show it. Create the file empty with that mode:

```bash
install -m 600 /dev/null ~/.vinga-api.curl
```

then write the one line it holds in an editor, the token in place of
the placeholder:

```text
header = "Authorization: Bearer <the token>"
```

and name the file on every request:

```bash
curl -sS -K ~/.vinga-api.curl http://127.0.0.1:8003/api/config
```

## The routes

**One noun per entity kind**, addressed the way the entity is keyed (a
provider by its stage and its name, a device by its MAC): providers and
MCP servers, each with its secret slots; prompt fragments; agents,
which can also be renamed; the agent defaults; devices, which can also
be renamed, replaced by another board and given a location, beside the
boards waiting with an activation code; and the default agent. `GET
/api/config` reads the whole of it at once, and `POST /api/apply`
writes a whole document of it in one transaction, which is what
`config import` sends. Every route, the methods it takes, the schema of
every body and the refusals each can answer with are in
[the OpenAPI document](../reference/api-openapi.json), which is the
one list of them.

**And one namespace that is not about stored configuration at all**,
`/api/runtime/`, the running server's own state, kept apart from the
entity namespaces because an entity may legally be named after any word
a route might want.

`GET /api/runtime/agents/{name}/prompt` answers the system prompt a
session opening now as that agent would be sent, block by block with
the size of each, which
[What the model is actually sent](agents-and-prompts.md#what-the-model-is-actually-sent) describes and
`vinga-server config agent preview` prints. `GET
/api/runtime/config/diff` answers what the
database holds that this server is not serving, kind by kind: the names
added, removed and changed, and for each kind whether its changes reach
a conversation at the next apply or at a device's
next check-in, which is what makes it possible to say whether a write is
still waiting. It carries entity names and those labels and nothing
else, so a rotated credential shows up as the provider that holds it
being listed as changed. `GET /api/runtime/mcp-servers` answers what
each configured MCP server is doing right now, which
[What the MCP servers are doing](tools-and-mcp.md#what-the-mcp-servers-are-doing) describes and `vinga-server
config mcp-server status` prints. `POST /api/runtime/config/reload`
installs what the stored configuration holds on the running server,
which
[Applying a change without a restart](configuration.md#applying-a-change-without-a-restart) describes and
`vinga-server config apply` prints; it is the only route here that
changes what the server is doing rather than what is stored. The route
keeps the mechanism's name and the command names the act, which is a
deliberate crossing rather than a mismatch.

**And the namespaces that read the conversation record**,
`/api/sessions` and `/api/conversations`, the store
[Recording conversations](conversation-store.md)
describes.

`GET /api/sessions` lists the sessions, newest first, filtered by
`?device=` when given. `GET /api/sessions/{session}` is one session
whole: its row, with how many turns and events hang off it. `GET
/api/sessions/{session}/turns` is one session's turns, oldest first, each
carrying its numbers and the tool calls it made nested in the order the
model issued them. The list and the timeline page on the monotonic row
ids the store was built with; the detail read is one session and takes
neither argument. `?cursor=` is a row id this API answered with,
meaning the sessions before it in the listing and the turns after it in
a timeline, which is the direction a client that has read up to a turn
asks in; how many rows a page holds, and the shape a page answers with,
are in the OpenAPI document. The conversations
rows are the same record read as threads: the list orders by a
conversation's last activity, filtered by `?agent=` when given, and
pages on the pair `?cursor_active=` and `?cursor_id=` this API
answered with, together or not at all, because an activity ordering
moves and a row id alone cannot page it; the detail is one thread with
its recap checkpoints and their count; the turns are its dialogue oldest first, across
every session it spanned. The three erasures, `DELETE
/api/sessions/{session}`, `DELETE /api/sessions` and `DELETE
/api/conversations/{conversation}`, are the verbs
[Deleting on demand](conversation-store.md#deleting-on-demand)
describes: one named session, the selector purge (`?session=`, `?device=`,
`?before=`, at least one, combined with AND), and one named thread.
A deployment that never
recorded answers the same empty shapes as one with nothing in it yet,
since the schema is migrated at every boot whether or not recording is
on; one that
recorded and has since switched recording off still serves what it
recorded. The recorded event rows themselves are not served here, and
a session's detail only counts them: what the running server emits is
streamed live at `GET /api/runtime/events`, the named daily aggregates
over the record are read at `/api/metrics` (`vinga metric`), and
anything beyond those is a query against the database.

## Reads and writes

`GET /api/config` is the whole domain configuration, masked, with the
location of every stored secret beside it, which is the JSON of what
`config show` prints. Every other entity read answers with the entity's masked
body and the slots holding a secret stored in the database, each marked
with the entity key its value displaces, which is the one thing a masked
entity cannot carry itself. A read is masked always, and a stored secret
is never read back by any route.

A PUT is create-or-replace, the CLI's `set`: the body is the same
fragment, as JSON rather than YAML, every reference it names has to
exist already, and the entity's stored secrets are left alone. A secret
is written by PUTting `{"secret": "..."}` to its slot, which is the only
plaintext this API accepts and the reason the whole of it belongs on a
loopback connection or behind TLS. The writes that are not an entity
fragment take a small argument body instead: that one, a device
binding (`{"agents": [...]}`), a claim (the same body, whose `agents`
may be left out or empty to bind the board to the default agent), the
default agent
(`{"name": "..."}`, whose DELETE clears it), a rename or a device's
replacement (`{"to": "..."}`), a device's location
(`{"location": "..."}`), and a corrected memory (`{"fact": "..."}`).

**A successful write says when it takes effect.** It answers with a
sentence for a reader, `notice`, and the boundaries it is waiting at as
`applies`, the closed tokens the comparison read publishes, which is
the half a program branches on; the whole answer is the
`Acknowledgement` schema in the OpenAPI document, and `POST /api/apply`
answers the same two for each entry it wrote. A
device binding carries the one about a device asking, because a
running server reads it as the device asks: it applies at that device's
next OTA check or connection, and so do a claim, a device's rename, its
replacement and its location. The default agent carries a sentence of
its own on the same token: the next claim that names no agent reads it,
and no device already bound changes. Every other kind this API
writes, which is the whole of the rest of the domain half, carries the
one that says the write is stored and not yet serving, and leaves the
three moments a conversation meets an installed change at to the
installing command's own help. A binding naming an agent this server is
not serving yet carries a sentence of its own, and it is the one an
operator is most likely to need, because both halves of it are true at
once: the row is live, and the agent arrives at the apply that installs
it. A default agent naming an unserved agent carries its own, waiting at
the install alone: a default agent reaches no device's check-in, only
the devices claimed onto it afterwards. No sentence names a
command: which command crosses a boundary is a fact of the client's
grammar, and a client is a program this server neither ships nor
versions, so the CLI reads the tokens and says the whole of it in its
own words where it knows the set, and quotes the sentence where it does
not. Nothing about a running conversation changes when a write lands,
in any of these cases.

## Refusals

**A refusal is an RFC 9457 problem document**, served as
`application/problem+json`. It carries the sentence the CLI prints in
`detail`, and one entry in `errors` for each field of the submitted
fragment the refusal names, so a form can mark the offending field
rather than quote the paragraph. Its members are the `Problem` schema
in the OpenAPI document, and which status each route answers with, and
when, is in that route's responses there. A 409 says that something
else held or occupied what the request needed and nothing was changed;
a busy lock or a reload already running is worth retrying, a name
already taken is not, and the sentence says which. A request body is never quoted back, on any
path, and neither is a traceback: a fragment can carry a credential
pasted where a variable name belongs, and a refusal that echoed it
would be the leak. **Neither are its keys.** A refusal names only fields
this server declares and positions in a list; a key the request invented
(an unrecognized one, an option a provider passes through, an entry of
an `env` or `headers` map) is as good a place to paste a credential as a
value is, so a refusal about one says which rule it broke and points at
the nearest enclosing place this server can name.

## The command-line client

**`vinga-server config` is the ergonomic client**, and the shape of a
deployment's own use of the API. It finds the server in this order:

1. `--api-url`
2. `VINGA_API_URL`
3. `http://127.0.0.1:<server.port>/api`, the port read from the same
   YAML file the server was started with (`--config`, or
   `VINGA_CONFIG`), so the two cannot disagree about it

The token is the value of the variable `server.api.secret_env` names,
read from that same file, and a missing one is a sentence naming the
variable before any request is sent. On a deployment both fall out of
the running container, which is the intended way to run these
commands, with one thing to say on the way in: the image names its
mounted file to the server process alone, so a shell started with
`docker exec` reads no file and falls back to the defaults, port 8003
and `VINGA_API_SECRET`. That is enough where the mounted file changes
neither. Where it sets `server.port` or `server.api.secret_env`, name
the file in the exec command:

```bash
docker exec -e VINGA_CONFIG=/config/config.yaml vinga vinga-server config list
```

`--config /config/config.yaml` after `config` does the same.

The token grants everything the API can do, so the client refuses a
plain `http://` connection to a host that is not a loopback address
(any address in `127.0.0.0/8`, `::1` or `localhost`), and there is deliberately no flag
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
[`docs/reference/cli.md`](../reference/cli.md).

**There is no second way in.** Every command here is a request, so a
deployment whose server will not start is recovered by rebuilding its
store rather than by editing it: stop the server, delete the database,
boot clean, import a kept `config export` with `config import`,
re-enter each stored credential through the `secret set` commands that
export listed at its foot, and `config apply` to install what came
back. The full procedure is in the task guides, under
[Recovering a deployment that will not start](recovering-a-deployment.md).
