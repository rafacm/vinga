# Setting limits and probes

At the end of this guide you will have sized the three bounds on what
one server holds, given a shutdown long enough for the replies it
gives, and pointed an orchestrator's restart and traffic decisions at
the probe each one is for.

Every key named here has its type, default and bounds in the server
configuration reference, under
[`server`](../reference/server-config.md#server) and
[`server.limits`](../reference/server-config.md#serverlimits); this
guide says what the numbers do and when to change them.

## Limits

Three numbers bound what one server holds, and none is visible in normal
use: a device refused a slot, or closed by either time bound, reconnects
on its next wake word.

```yaml
server:
  limits:
    # concurrent conversations
    max_sessions: 8
    # one session's maximum life
    max_session_s: 3600
    # how long a realtime session may go without conversing
    idle_timeout_s: 120
  drain_s: 20             # how long a shutdown waits for replies to finish
```

`idle_timeout_s` is the one users actually meet. A realtime device asks
to listen once and then streams its mic for the rest of the connection,
and nothing in the firmware ever closes that channel, so walking away
mid-conversation used to leave a mic running until the hour was up. The
clock counts from the end of the last utterance or the end of the last
reply, whichever is later; arriving audio does not reset it, because a
realtime session streams silence too. Two minutes by default: long
enough to think, read something out, or answer the door.

It applies to realtime sessions only. An auto-mode device stops
listening after each reply and re-arms per turn, so it is not streaming
a room to anybody, and `max_session_s` is its bound. There is no off
switch; a deployment that wants none sets `idle_timeout_s` near
`max_session_s`.

`max_sessions` is a count with no queue behind it, because a
conversation waiting in line is worse than one that never started.

**Shutting down drains.** On SIGTERM the server stops admitting sessions,
lets every reply in flight finish speaking, and closes those sockets with
1001, all inside `drain_s`. A second signal forces the exit. Give
`docker stop` a `-t` above `drain_s`; its default is ten seconds.

`drain_s` is the whole budget a reply gets, so raise it if your replies
are long: a spoken answer is paced at the frame rate, so thirty seconds
of speech takes thirty seconds to deliver. When a reply outlasts the
budget its socket is still closed politely, but the drain logs
`drain_incomplete` with `cut_mid_reply`, which is the signal that
`drain_s` is too short for the replies this server gives.

**Two probes, and which one to point at what.** `/healthz` is liveness:
this process is alive and serving its control surface. `/readyz` is
admission: this process may be handed a new device conversation. An
orchestrator with two probe slots points restart at `/healthz` and
traffic admission at `/readyz`. A draining server answers 200 on the
first and 503 on the second, which is exactly what a redeploy wants: the
pod is left running to finish the conversations it has, and no new device
is sent to it. Both are unauthenticated, and neither says anything about
a provider or an MCP server.

`/readyz` answers `200 {"status": "ok"}`, or 503 with one word for why
not:

| Status | What it means |
| ------ | ------------- |
| `ok` | serving, and there is room for another conversation |
| `draining` | shutting down: what is in flight is finishing, and nothing new is admitted |
| `full` | every one of the `max_sessions` slots is taken |
| `unavailable` | there is no serving composition to admit anything to |

Readiness dips at capacity and recovers as slots free. That is what
readiness is for rather than a flap: a device refused a slot retries on
its own next wake word, and an orchestrator withholding new traffic from
a full pod is precisely the behavior being asked for. The cost is worth
knowing when sizing `max_sessions`, though: under an orchestrator that
routes by readiness, a full pod's configuration API leaves the traffic
set along with its WebSocket.

`unavailable` is narrower than it sounds. Uvicorn binds its listener only
once the lifespan's startup has finished, and that startup is what builds
the composition (a provider loading a model can hold it for minutes), so
a probe against a starting server meets a connection failure rather than
this answer, and every prober treats that as not ready. What answers
`unavailable` is an application that was described and never served, and
one whose shutdown has already released what it was serving with.

The image's own `HEALTHCHECK` is `/healthz`, deliberately. Docker has one
health slot and it is not a restart trigger: an unhealthy container is
surfaced and gated on (`--wait`, `depends_on: service_healthy`) rather
than replaced, so a container going unhealthy while it drains would turn
every redeploy into a reported failure.

**A stalled generation is retried, then dropped.** An LLM whose stream
shows no sign of life within `llm_first_token_timeout_s` (ten seconds
by default) has its request cancelled and the round retried once,
logged as `llm_retry`; a second stall gives the round up as a
`provider_failed` with `error: FirstTokenTimeout` and the session goes
back to listening, so the worst a stalled provider can cost is one
turn, and that turn says so out loud (see
[When a reply fails](../../vinga-server/README.md#when-a-reply-fails))
rather than passing in silence. Only the
wait for the stream to begin is bounded: a long reply that is already
streaming runs to the end, a round that streams nothing but a tool call
counts as delivering too, and barging in still cancels a stalled round
the way it cancels anything else. The default is worth raising for one
case in particular: a local model served by Ollama or llama.cpp loads
its weights on the first request after a cold start, which routinely
takes longer than ten seconds on a machine that has just booted or has
evicted the model, so the first turn of the day gives up before the
model has finished loading. Keeping the model resident, or raising this
value on a deployment that runs one locally, is the remedy. The
reasoning behind the default is in
[`config.example.yaml`](../../vinga-server/config.example.yaml).
