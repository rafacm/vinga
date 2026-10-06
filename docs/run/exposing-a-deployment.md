# Exposing a deployment

At the end of this guide you will have the two device endpoints
reachable by your boards, the configuration API reachable only from
where you decided, and, if a reverse proxy sits in front, one that
tells boards the right address and keeps their conversations open.

## Ports and topology

Both endpoints share one port
([`server.port`](../reference/server-config.md#server), default 8003),
because vinga-server is a single ASGI app. Upstream splits them across two (HTTP
8003, WebSocket 8000).

The advertised WebSocket URL is deliberately independent of the listening
topology, which is what keeps this from being a one-way door: whatever the
process listens on, `server.websocket_url` decides what devices are told to
connect to.

What one port buys:

- A LAN deployment needs no configuration at all. The WebSocket URL is
  derived from the address the device reached the OTA endpoint on. With two
  ports that is impossible, since the request tells you the HTTP port and not
  the other one.
- One firewall rule, one container port, one certificate, one route.

What it costs:

- No separation at the network layer. Exposing one endpoint and not the
  other, or giving them different idle timeouts, has to be done by path
  rather than by port. This matters in practice: a WebSocket carrying a
  conversation needs a long idle timeout, an OTA check wants a short one.
- No independent scaling or lifecycle. WebSocket connections are long-lived
  and stateful while OTA requests are short and stateless, but they share a
  process, so they share a worker pool, a restart, and a crash.

### Behind a reverse proxy

One port and two paths means a proxy in front has to treat those paths
differently. Four things to get right:

- **Set `server.websocket_url` explicitly, or trust the proxy.** The
  derived URL is wrong behind a proxy that terminates TLS: uvicorn only
  trusts `X-Forwarded-Proto` from `forwarded_allow_ips`, which defaults to
  `127.0.0.1` and so will not match the proxy's address. The reply then
  says `ws://` where it should say `wss://`, and devices fail to connect
  with nothing obviously misconfigured. Either name the URL yourself, or
  put the proxy's address in the `FORWARDED_ALLOW_IPS` environment
  variable, which uvicorn reads when the setting is not passed. There is
  no config key for it: `server.websocket_url` is the explicit answer, and
  the environment variable covers the rest without a second way to say the
  same thing. `vinga-server doctor` is what says this has
  happened: it names a `ws://` websocket URL behind an `https://` OTA
  URL as the fault it is, rather than leaving a board failing at the
  handshake with every other line looking right.
- **Set `server.public_url` too.** TLS ends at the proxy, so nothing a
  request carries says what a person should type; without it the
  onboarding URL is derived from `server.websocket_url`, and failing
  that from the address the request reached the OTA endpoint on, which
  behind a proxy is the address the proxy used rather than the one a
  person has. The startup line has no request to read at all and
  guesses from the listen address, saying that it is a guess.
- **One idle timeout is enough, above 20 seconds.** The server pings every
  connected device every 20 seconds, so a conversation WebSocket is never
  actually idle even when nobody is speaking. A proxy therefore needs only
  a read timeout above that interval, and the two paths need no different
  treatment.
- **Allow the upgrade and turn off response buffering** on the WebSocket
  path. A proxy that buffers, or that does not pass `Upgrade` and
  `Connection` through, either breaks the handshake or adds latency to every
  spoken reply.
- **Restarts end conversations.** Every open WebSocket dies with the
  process, and the OTA endpoint shares that process, so neither can be
  restarted without the other. The server drains on SIGTERM (see
  [Setting limits and probes](limits-and-probes.md)); give whatever
  stops it a grace period above `drain_s`.

## The configuration API in a deployment

Two more things, about the surface that writes the configuration. What
the API is and what it serves is under
[The configuration API](../../vinga-server/README.md#the-configuration-api)
in the server README; this is what a deployment has to decide about
it. Its secret, without which the server does not boot, is in
[Running vinga in a container](running-in-a-container.md#the-container).

**Decide what happens to `/api/` at the edge.** It is on the same port
as the device endpoints, because the server is one process, so anything
routing that port outward routes the admin surface with it unless it is
told otherwise. Three answers, in the order they are worth reaching for:

- **Do not route it externally at all.** The device endpoints are the
  only two that need to be reachable from outside, so route
  `/xiaozhi/ota/` and `/xiaozhi/v1/` and let `/api/` be reachable only
  from inside. Configure it by exec into the running container, or by
  forwarding the port to your own machine for the length of a session.
  This is the default worth defending: the surface with the most
  authority is the one nothing outside can address.
- **Route it separately and restrict it**, when a front end or an
  operator genuinely needs it from outside: a route of its own for the
  `/api/` prefix, TLS on it, and whatever source restriction the edge
  can express, so that the bearer token is not the only thing between
  the internet and the configuration.
- Route the port as one thing and rely on the token alone. That is what
  happens by accident, and it is worth choosing deliberately if it is
  what you want, because a token in a client's environment is a token
  in more places than a private address is.

**Loopback or TLS, for the whole API and not only for secret writes.**
The bearer token rides on every request and grants everything the API
can do, a secret set included, so a plain `http://` request to it from
another machine puts the token on the wire in clear. This is a rule the
client enforces rather than recommends: `vinga-server config` refuses a
plain `http://` URL whose host is not a loopback address, with no flag
to override it. The machine's own address on the network is not one of
those, and neither is a name that resolves to loopback: the check reads
the host as written. Reach the API over `https://`, through a tunnel
that terminates TLS, or on loopback from inside the container, which is
the case the default address is built for.
