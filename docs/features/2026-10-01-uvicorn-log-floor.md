# A websocket handshake's query no longer reaches the log

**Date:** 2026-10-01

**Local baseline:** not applicable. The change moves one third-party
logger's level in the server's logging setup; no conversational
capability is added, removed or moved off the machine.

## Problem

uvicorn writes one line per websocket handshake on its `uvicorn.error`
logger at INFO, accepted or refused, and the line carries the request
path with its query string verbatim (#578). `VENDOR_LOG_FLOORS` in
`logs.py` held that logger at INFO, and the comment above the mapping
said what uvicorn writes at that level was worth keeping and carried
none of the near side's secrets. Turning off the access log
(`serving.uvicorn_config`) does not reach these lines, because they come
from the websockets protocol on `uvicorn.error` rather than from the
access logger.

No client of this server puts a credential in that query today: the
firmware and the Python simulator authenticate in the `Authorization`
header, and the device edge reads only headers. But upstream's
convention carries the token in the query (xiaozhi-esp32-server reads
`device-id`, `client-id` and `authorization` as query parameters,
because a browser's WebSocket API cannot set a header), the planned
browser client is exactly that client, and refusing the connection does
not help: uvicorn prints the 403 line before any of this server's code
runs.

It is the class of line #445 removed on the outbound side
([the httpx log floor](2026-10-01-httpx-log-floor.md), whose
"Discoveries" section first noted this one): composed by a library,
outside the closed event vocabulary, and carried by stdout into whatever
log collection a deployment runs.

## What uvicorn writes at INFO, measured

A real boot through `vinga-server --config` (so `serving.run`, with
`log_config=None` and `access_log=False` as a deployment runs it),
against a fresh database, at `server.log_level: INFO` in the text
format, then one handshake refused for lack of a token and one accepted
with a valid token in its header, both with a credential-shaped sentinel
in the query, then SIGTERM. uvicorn 0.51.0 and websockets 16.1.1. Every
`uvicorn.error` line the run printed, verbatim, with the server's own
lines between them for orientation (marked `vinga`) and the migration
lines omitted:

```
uvicorn.error: Started server process [669946]
uvicorn.error: Waiting for application startup.
  vinga:       device onboarding is on: devices are configured on http://127.0.0.1:18578 (guessed from the listen address (server.host and server.port), ...
uvicorn.error: Application startup complete.
uvicorn.error: Uvicorn running on http://127.0.0.1:18578 (Press CTRL+C to quit)
  vinga:       refused a websocket handshake from an unidentified client: no_token
uvicorn.error: 127.0.0.1:43106 - "WebSocket /xiaozhi/v1/?device-id=aa:bb&authorization=Bearer%20sk_live_SENTINEL578" 403
uvicorn.error: connection rejected (403 Forbidden)
uvicorn.error: 127.0.0.1:43112 - "WebSocket /xiaozhi/v1/?device-id=aa:bb&authorization=Bearer%20sk_live_SENTINEL578" [accepted]
uvicorn.error: connection open
  vinga:       session cf9fc3d0... rejected: device 11:22:33:44:55:01 has no agent: ...
  vinga:       shutting down: draining conversations for up to 20 s
uvicorn.error: Shutting down
uvicorn.error: Waiting for application shutdown.
uvicorn.error: Application shutdown complete.
uvicorn.error: Finished server process [669946]
```

The JSON format printed the same twelve messages, the `Started`,
`Finished` and `Uvicorn running` records adding a `color_message` field
of uvicorn's own. `connection open` and `connection rejected` are the
websockets library's, written through the logger uvicorn hands it.

Read from the source rather than seen in the run, uvicorn can also write
at INFO: `Waiting for connections to close.` and `Waiting for background
tasks to complete.` when a shutdown finds either still open, a third
handshake template
(`"WebSocket <path>" <status>`) for an application that sends an HTTP
denial response, which this server never does, and the reload and
multi-worker supervisors' notices, which this server never runs.

## Changes

### uvicorn's logger is floored at WARNING

`VENDOR_LOG_FLOORS["uvicorn.error"]` moves from `logging.INFO` to
`logging.WARNING`. The mechanism is unchanged: `quiet_vendor_libraries`
holds the logger at the higher of its floor and the server's level,
`logs.configure` applies it with the configured level, and both entry
points apply it before anything opens a socket. So the handshake line is
gone at every `server.log_level`, DEBUG included, and the client's
address goes with it, which is metadata the access log was turned off
for alongside the rest.

### What that costs, priced

Every other INFO line above goes too. Most of what they say, the
server says some other way or the operator already holds; the table
says where, and the paragraphs after it say what is said nowhere now:

| uvicorn line | Where the fact still is |
| --- | --- |
| `<address> - "WebSocket <path>" 403`, `connection rejected` | `auth_rejected`, or `session_rejected` for a server that is full or draining, each with its reason |
| `... [accepted]`, `connection open` | `session_open`, emitted only once a valid hello has arrived and the setup after it has succeeded (the server's hello sent, the recording opened), or `session_rejected` with its reason when the session turns the device away after the accept and before the hello (a Device-Id that is not a MAC, no agent, an agent not loaded). A transport that ends before a valid hello has no event; see below |
| `Started server process [<pid>]`, `Finished server process [<pid>]` | Nowhere in the log. The process id is the container's or the supervisor's to report |
| `Waiting for application startup.`, `Application startup complete.` | The onboarding banner (`onboarding_banner`) is written from the started callback, just before `Application startup complete.`; `/readyz` answers readiness |
| `Uvicorn running on <scheme>://<host>:<port>` | The banner's `origin`, which is the listen address unless `server.public_url` or `server.websocket_url` names a better one; otherwise `server.host` and `server.port` in the file the operator wrote |
| `Shutting down`, `Waiting for application shutdown.`, `Application shutdown complete.` | `shutting down: draining conversations for up to <n> s` (`vinga_server.serving`) opens the shutdown; no line closes it |

Step 0 recorded that no catalog event carries the listen address. The
measurement corrects that in part: `onboarding_banner` carries it as its
`origin` whenever nothing better is configured, and says it is a guess.
What is genuinely gone from the log is the bind address on a deployment
that has named its public origin, the process id, and the last line of a
clean shutdown. None was judged worth a vinga line of its own: the
first is in the configuration, the second is the runtime's, and a
shutdown that did not complete shows as a missing exit rather than as a
missing log line.

Also gone, and the larger loss: that a connection was accepted at all,
when it ends before a valid hello. Read from `device/session.py`,
`session_open` is emitted only after `DeviceSession._receive_hello`
returns a hello, the server's hello has been sent, and the recording has
opened (the capture and the conversation store's session row). A
connection lost while the server's hello is being sent has no event of
the server's own, and a failure while the recording opens is followed
by `session_closed` with reason `error` and no `session_open`. Before
any of that, `_receive_hello` returns with no event when the client
disconnects before its first frame, when no frame arrives
within the first-contact window (`HELLO_TIMEOUT_S`, 10 s), when the
first frame is not text, or when the first message is not a hello, or
is a hello whose transport is not `websocket`, whose audio format is not
`opus`, or whose protocol version is unsupported. Each of those closes
the socket (the timeout and the invalid hellos with a protocol-error
close code and a reason sent to the device) and logs nothing. A first
message of a type the protocol does not know counts as not a hello. The
one exception is a first text frame the message parser refuses (not
JSON, not an object, no string `type`, or a known type that fails its
model), which is logged as a plain warning (`session <id>: malformed
hello: ...`) rather than as a catalog event. Before this change
uvicorn's `[accepted]` and `connection open` were the only trace of the
rest; now a device that connects and fails its hello in any of those
ways is invisible in the log. This change adds no event for them, as
the review round decided; whether the server should say so in an event
of its own is a separate decision.

A server started as `uvicorn vinga_server.app:app` loses the same lines,
since `create_app` applies the floor before uvicorn writes its first
one. That entry point is not one the documentation offers an operator.

What the floor keeps, at a `server.log_level` of WARNING or below, is
everything uvicorn says at WARNING and above. The floor is the higher of
the configured level and WARNING, so a server configured at ERROR or
CRITICAL prints none of uvicorn's warnings either, which was equally
true under the INFO floor. Read from the source at 0.51.0, what is kept
is: a request that would not parse (`Invalid HTTP request received.`), an unsupported upgrade, the
concurrency limit, a bind that failed (the `OSError` itself), a startup
or shutdown the lifespan failed, an exception in the application with
its traceback, an application that returned without answering, a
frame that is not valid UTF-8, and a graceful shutdown that ran out of
time; and from the websockets library, a handshake or a frame parser
that failed. The tests below drive one WARNING and one ERROR of these
through the floor.

What the floor does not cover is what those kept records say. An ERROR
record with a traceback, such as uvicorn's `Exception in ASGI
application` or the websockets library's `opening handshake failed`,
renders the exception's message and its chain as they were raised, and
this floor does not sanitize them: it decides which levels reach the
handler, not what a record that reaches it carries. Whether an
exception on those paths can quote the request line, or anything else
a client sent, was not established here. The server's own code renders
no traceback at all: a search of `vinga-server/src` finds no
`logger.exception` and no `exc_info=True`, and the sites that report a
failure name its class and say why they do not repeat its message
(`serving._report_drain`, the reply pipeline, turn-taking, the filler
runner). So uvicorn's kept tracebacks are an exception to the server's
own rule rather than an instance of it. They reached the log the same
way under the INFO floor, so this change neither opens nor closes them,
and whether to strip them is left as a separate decision.

### The shape not taken: a filter on the handshake line

A `logging.Filter` on `uvicorn.error` that cut the query (and the
address) out of the handshake records and kept the rest was priced
against the floor. It would depend on uvicorn's message layout: the
template `'%s - "WebSocket %s" [accepted]'` and its two siblings, with
the address and the path as `record.args[0]` and `record.args[1]`,
spelled out separately by each of uvicorn's three websocket
implementations (`websockets_sansio_impl`, which `ws="auto"` selects
when websockets is installed and which wrote the lines above, and the
`websockets_impl` and `wsproto_impl` a configuration can name
instead). It would need a pin that fails when an upgrade moves any of
them, since a filter that stops matching fails open, printing the query
again with nothing to say so. What it would buy is the lines in the
table above, which no code here reads. Among them is `connection open`,
the only trace of a connection that fails its hello, so the filter
would have kept that and the floor does not. That loss was found in
review after the choice was made, and is now stated rather than priced
away: a scrubbed copy of a library's line is a weaker carrier for it
than an event of the server's own would be, and the proportion test
still picks the floor, one map value and its comment against a filter,
its pin and a recurring upgrade check.

Typed handshake events of the server's own, in place of uvicorn's lines,
are the direction #567 takes for HTTP requests and are left to it.

### The comment above the mapping

The paragraph that kept uvicorn at INFO for its "startup and
per-connection lines" and said they carried none of the near side's
secrets is gone. In its place the comment says what the handshake line
carries, why no client of this server is affected today and why that is
not enough, what the floor costs and where each fact still is, what it
keeps, and why the filter was rejected. The SDKs keep their own INFO
paragraph, now about them alone.

### Tests

`tests/unit/test_logs.py` drives a real uvicorn, under
`serving.uvicorn_config` on an ephemeral port, serving a stand-in
application with the two answers that decide what uvicorn prints: a
route that closes before the accept when there is no `Authorization`
header, as `ws.py` refuses a device without a token, and accepts
otherwise; and a route that raises. The server's own application is not
used here because it needs a database to start. Through the handler
`logs.configure` installs:

- `test_a_handshake_query_is_printed_on_no_line`, at INFO and DEBUG in
  both formats: a refused (403) and an accepted (101) handshake whose
  query carries the sentinel print neither the sentinel nor the word
  `WebSocket`, while a line of the server's own written after uvicorn
  stops is printed, so the absence is the floor and not a capture that
  saw nothing. The client's own `websockets.client` logger, which writes
  the request line it sends at DEBUG, is held at WARNING for the length
  of the run, since what is under test is what the server prints;
- `test_without_the_floor_uvicorn_prints_the_query`, the load-bearing
  half: with `uvicorn.error` left to inherit, the same two handshakes
  print the sentinel on exactly two lines, ending `403` and
  `[accepted]`;
- `test_what_uvicorn_says_above_info_still_reaches_the_log`: a request
  that will not parse prints `Invalid HTTP request received.`
  (WARNING), and the raising route prints `Exception in ASGI
  application` and the exception's class name (ERROR). The exception's
  message is deliberately not asserted: what a kept traceback carries
  is the uncovered case above, not a property to pin.

The external-runner boot test's expected `uvicorn.error` level moves
from INFO to WARNING.

`tests/integration/test_access_logs.py`'s DEBUG test now opens its
device websocket with a credential in the query, refused by `ws.py`'s
own close-before-accept and accepted beside the header that
authenticates it, and asserts the credential is in neither format. That
holds the floor against the server's real route, the one a browser
client would reach.

### Discoveries, not acted on

- **The implementation that writes the line is not the one the issue
  cites.** The issue links `websockets_impl.py`; at 0.51.0, `ws="auto"`
  selects `websockets_sansio_impl.py` when websockets is installed,
  which is what `connection open` (the sans-I/O `ServerProtocol`'s line)
  confirms. The template and the argument order are the same in both,
  and in `wsproto_impl.py`, so the finding stands as stated.
- **What the DEBUG-level records narrate is unchanged.** uvicorn's trace
  and the websockets library's frame records were already held by the
  INFO floor, as `test_access_logs.py` documents; WARNING holds them
  too.

## Key parameters

| What | Value |
| --- | --- |
| `VENDOR_LOG_FLOORS["uvicorn.error"]` | `logging.INFO` to `logging.WARNING` |
| Unchanged floors | `anthropic`, `openai` at INFO; `httpcore`, `httpx`, `sqlalchemy` at WARNING |
| Configuration | none added; no key lifts a floor |
| Library versions read and run | uvicorn 0.51.0 (handshake lines in `protocols/websockets/websockets_sansio_impl.py`, which `ws="auto"` selects when websockets is installed), websockets 16.1.1 (`connection open` and `connection rejected` in `server.py`) |

## Verification

- A real `vinga-server --config` boot, two handshakes and a shutdown,
  in both log formats, before the change: the lines above.
- `uv run ruff check .` passes.
- `uv run pytest tests/unit -q -ra -n 2 --dist loadfile`: 1 failed,
  7812 passed, 19 skipped in 1784.86s. The one failure is
  `test_event_docs.py::test_a_reader_who_stops_reading_mid_chunk_gets_no_traceback`,
  which fails the same way alone, three runs of three, and alone at
  `main` (c6d6aa6b) on the same machine, whose pipe holds 256 KiB; it
  reads no logger this change touches.
- `uv run pytest tests/integration -q -ra -n 2 --dist loadfile`: 350
  passed in 858.88s.
- `python3 scripts/check_doc_links.py .` and
  `python3 scripts/fold_changelog.py check .` pass.
- `uv run pytest tests/census -q` passes, run last.
- Mutations, each run and restored by copy, never by checkout:
  - the floor back at `logging.INFO` fails all four cases of
    `test_a_handshake_query_is_printed_on_no_line`, and
    `test_debug_puts_no_request_line_and_no_frame_back` on its query
    assertion;
  - the `uvicorn.error` entry removed from the mapping fails the same
    four unit cases;
  - the floor at `logging.ERROR`, or at `logging.CRITICAL`, fails
    `test_what_uvicorn_says_above_info_still_reaches_the_log`;
  - `configure` no longer calling `quiet_vendor_libraries` fails the
    four handshake cases along with the httpx and httpcore floor tests
    and `test_configure_applies_the_floor`, in the whole of
    `test_logs.py`.

## Files modified

- `vinga-server/src/vinga_server/logs.py`
- `vinga-server/tests/unit/test_logs.py`
- `vinga-server/tests/integration/test_access_logs.py`
- `changelog.d/578-ws-query-off-uvicorn-log.md`
- `docs/features/2026-10-01-uvicorn-log-floor.md`
