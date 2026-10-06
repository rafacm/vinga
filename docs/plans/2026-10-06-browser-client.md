# A browser client served by the server

Plan for [#613](https://github.com/rafacm/vinga/issues/613), the fourth
child of epic [#615](https://github.com/rafacm/vinga/issues/615) and the
second stage of #610's Getting Started. Its companion is
`docs/plans/2026-10-06-browser-client-implementation.md`, one section
per milestone, appended in the same change that ticks it. It builds on
the simulator (`docs/plans/2026-08-25-simulator.md`, #248), onboarding
and the activation ceremony (#40, #153), and the task guides #609
created.

**Local baseline:** outside, as the issue says: a new device client
changes no conversational capability, and a fully local deployment
serves it like any board.

**Cheapest alternative:** #301 as filed, a microphone tier in the CLI
simulator. It is smaller and ships no JavaScript, but it cannot barge in
(no echo cancellation) and needs an install before the first word, which
are the two things a front door is judged on. Inside this plan, the
cheapest shape of the client itself was measured in Step 0 and chosen:
the browser's own WebCodecs Opus codec rather than a 844 KB libopus
build or Pyodide (Q7).

**Operator surface:** a new route family (`/try/` with its token in the fragment, the page under
the onboarding path) and a new line in `vinga info` (the try link); no
new configuration key in M1 to M3 unless the plan review asks for one
(D6 names the one candidate); a device guide `docs/devices/browser.md`
(the Use door), a line in `docs/run/onboarding-a-device.md`, the
`/try/` step in `docs/run/with-a-coding-agent.md` (#611's D8), and the
glossary's Device entry widened to a browser. No upgrade action beyond
one sentence (D5e): a restart, an image upgrade included, ends every
unredeemed try link, so an operator issues a fresh one; a deployment
that never opens a try link behaves exactly as before.

**Attribution:** anthropic/claude-opus-5-5, thinking high; Claude Code 2.1.289; 2026-10-06.

## Where this starts from

Verified at `bbc12d6c` in the
[Step 0 comment](https://github.com/rafacm/vinga/issues/613#issuecomment-6009587713).

- `ws.py` gates the upgrade on `Authorization`, `Device-Id` and
  `Client-Id` headers (`refusal_reason`), which a browser's `WebSocket`
  cannot set. `auth.py`'s tokens are stateless HMACs over
  `client_id|device_id|ts`; device auth is on by default.
- vinga-server serves no HTML. uvicorn's access log is off
  (`serving.py`, `access_log=False`), so a path is not written to the
  server's own log by default; a reverse proxy in front may log it.
- The onboarding path `/x/<key>/` is a secret-derived alias of the OTA
  endpoint; the key is printed to the operator only (`vinga info`,
  `vinga-server config ota-url`) and never logged (`onboarding/keys.py`).
- The store binds with `bind_device` (creates or rebinds; a created row
  is named `Device <mac>`) and `claim_device` (only an unconfigured
  device, refused when a default agent is set).
- The simulator derives a client id from a MAC by UUIDv5
  (`simulator/board.py`, `Identity.of`, `CLIENT_ID_NAMESPACE`).
- Measured on agentpi, in Playwright 1.63's container: headless
  Chromium 153 grants a fake microphone with `echoCancellation: true`
  (48 kHz track), has `AudioWorkletNode`, and WebCodecs supports Opus
  encode at 16 kHz mono and decode at 24 kHz and 16 kHz.

## Decisions, restated

From the issue, as Step 0 confirmed them:

1. **A browser client served by vinga-server**, speaking stock xiaozhi
   over the existing WebSocket edge: OTA check-in, hello, `listen`, Opus
   both ways. The runtime, agents and turn-taking are a board's.
2. **Echo-cancelled capture** (`getUserMedia` with `echoCancellation`
   and `noiseSuppression`), which makes **realtime listening and
   barge-in** possible from a laptop.
3. **An honest preview**: the same runtime a board gets.
4. **Nothing to install** beyond the server.
5. **It is a device**: a guide in `docs/devices/`, no row in the
   hardware tables. The CLI simulator stays the operator's probe.
6. **Bound by the `/try/` link** `vinga info` prints: single-use,
   minutes long, kept out of every log; opening it binds the browser as
   a new device to the default agent before its first word. A browser
   keeps its identity in its own storage; a cleared browser is a new,
   unbound device, which gets what any unbound device gets. No loopback
   exception.
7. **Secure context**: `localhost` or HTTPS; the exposure guide says so.
8. **Constraints**: no bearer token in a URL; realtime sessions meet the
   idle timeout, which the page shows as an ending; a stable synthetic
   identity per browser; every surface reads a browser board as a board
   and leaks nothing the page stores; the capability table's refusals
   stay true of the CLI and the browser gets its own statement.

## Open questions, resolved

**Q1. Where the client lives.** Inside the `vinga-server` wheel, as
static files under `src/vinga_server/browser/static/` (packaged with the
rest of `src/vinga_server`, which `pyproject.toml` already does), served
by the existing app. A separate package would be a second release
artifact to version against the server it must match; the page is part
of the server's protocol surface, so it ships with it. The files are
plain ES modules, no bundler and no Node toolchain in the build: the
client is small enough (D3) that a build step would cost more than it
saves.

**Q2. How the page reaches the OTA route.** The page and its assets are
served at the keyless `/try/` (`/try/static/<file>`), and the onboarding
path reaches the page in the body of a response, never in a URL the
page is loaded from: the redeem response (D5) carries it for a browser
bound by a try link, and an unbound browser has the person paste the
onboarding URL `vinga info` printed, once, the issue's "typed once"
option. The page stores it beside the identity and uses it only as the
target of its OTA `fetch`, which is exactly the request a board makes
with the same key in it. So the key appears in a request target where a
board's check-in already puts it, and nowhere else: not in the page's
address, not in an asset request, not in a `Referer` (the page sets
`Referrer-Policy: no-referrer`). The exposure guide's existing advice
for the onboarding path covers the browser's check-in as it covers a
board's, and says so (D2a).

**Q3. The credential on the WebSocket handshake.** The
`Sec-WebSocket-Protocol` header, which is the one header a browser's
`WebSocket` lets a page set. The page offers a list:
`vinga.device.v1`, `vinga.mac.<12 hex>`, `vinga.client.<uuid>` and
`vinga.token.<token>` (every character of a MAC's hex, a UUID and the
token's urlsafe base64 and `.` is a legal subprotocol token character).
`ws.py` reads the identity and the token from those values only when the
three headers are absent, verifies them exactly as it verifies a
board's, and accepts the upgrade selecting `vinga.device.v1`, never
echoing a value that carries the token. Chosen over the alternatives:

- **The query string** puts the token in the URL, which proxies log,
  which the no-leak contract forbids.
- **A same-origin cookie** keeps the token out of JavaScript, but the
  page already holds the token, because the OTA reply hands it over in
  JSON as it does to a board; a cookie would add server-set state, a
  `Set-Cookie` on the OTA reply only for browsers, and a cross-site
  WebSocket hijacking surface to defend (cookies ride every request to
  the origin, including one a hostile page opens), for no secret the
  page does not already have.
- **The subprotocol** needs no server state, rides only the request the
  page itself opens, is not a URL, and is not logged by the server; a
  hostile page cannot present a token it does not hold. A reverse proxy
  that logs request headers wholesale would log it, as it would log a
  board's `Authorization`, and the exposure guide says so.

The token's lifetime and verification are unchanged; nothing about a
board's handshake changes.

**Q3b. With device authentication off.** The OTA reply then says
`access: open` with an empty token, and a board sends no
`Authorization`. The page follows the reply: it offers
`vinga.device.v1`, `vinga.mac.*` and `vinga.client.*` and no
`vinga.token.*`, and `ws.py`'s subprotocol path then behaves exactly as
its header path does with auth off (no token check, the identity read
from the offered values). Tests cover a browser session with auth on and
with auth off.

**Q3a. The verified identity reaches the session.** `DeviceSession`
reads `Device-Id` and `Client-Id` from the headers and accepts without a
subprotocol, so authenticating in `ws.py` alone would let a browser pass
the gate and then be turned away for a missing MAC. So the handshake's
result is one value, the verified identity (MAC, client id) and the
subprotocol to select, built in `ws.py` from whichever source it read,
headers or subprotocol, and handed to the session, which reads its
identity from that value rather than from the headers and accepts with
the selected subprotocol (none for a board, `vinga.device.v1` for a
browser). A board's path produces the same value from the same headers,
so its behavior is unchanged and its existing tests pin that. M1's tests
drive a complete browser hello through the session, not only the
upgrade.

**Q4. Echo cancellation unavailable.** The page reads the track's
`getSettings().echoCancellation`. True: it announces `realtime`. False
(a browser or device that cannot cancel): it announces `auto` and
behaves as a stock board in auto mode does, stopping its microphone
frames while the reply plays and re-arming after `tts stop`, and the
page says that interrupting is unavailable in this browser. The server
already serves both modes from boards, so this is client behavior, not
a server change.

**Q5. What a lane proves.** A containerized headless-Chromium lane
(`tests/browser/`, opt-in locally, a CI job) loads the real page from a
server started from the checkout, feeds a fake microphone from a WAV
file (`--use-file-for-fake-audio-capture`), and asserts the handshake
over the subprotocol credential, the OTA check-in, the hello and
`listen realtime`, Opus frames reaching the server (the `heard` event on
mock ASR), a reply's Opus frames decoded and played by the page, and the
try-link binding. The acoustic behavior (echo cancellation in a real
room, a real barge-in) is a manual checkpoint on a laptop, recorded in
the implementation doc; the capability statement claims only what the
lane drives, and says which parts were checked by hand.

**Q5a. The lane covers what ships, and runs on every server change.**
The lane installs the built wheel into a fresh environment and serves
the page from that install, so a static file missing from the wheel
fails it; one variant also runs against the image CI built. The page
exposes, for the lane only through an attribute set when the URL says
so, a running sum of the absolute PCM values the playback worklet has
rendered, and the lane asserts it is nonzero after a reply, which is the
proof that decoded audio reached the sink. The CI job runs on every
event the server workflow runs on, not on a path filter: the page
depends on `ws.py`, the session, OTA, the protocol models and the
packaging, and a filter narrower than those would let one of them break
it unseen. Its cost per run is measured in M3 and stated in the PR.

**Q5b. The lane's cases and its runtime.** Two cases beyond the
realtime one: an echo-cancellation-unavailable case (the page started
with a test-only switch that makes it treat the track's
`echoCancellation` as false, since the fake device always reports true)
asserting `listen auto`, no outbound microphone frames while a reply
plays, re-arming after `tts stop`, and the visible no-interrupt
sentence; and the device-tool case of D3a. The runtime is pinned and
provisioned: Playwright's Python package as a `browser` dependency group
in `pyproject.toml` (locked in `uv.lock`), run inside
`mcr.microsoft.com/playwright/python:v<the locked version>-noble` so the
browser binary and its system libraries match the package; the fake
microphone is a committed short WAV under `tests/browser/`; the server
under test is the built wheel installed in that container (and, in CI,
a second run against the image the image job built), reached on the
container's loopback. Locally: one documented command in
`docs/contributing.md` that runs the container with the worktree
mounted. In CI: a job in the server workflow using that image as its
job container. M3 records the job's measured time.

**Q6. #81's measurement harness.** Not built here. The browser client
produces realtime, echo-cancelled sessions that the server records like
any device's (capture and the conversation store are server-side), so
#81 can use it later without anything in this plan; the device guide
says nothing about it.

**Q7. JavaScript or Pyodide.** JavaScript, small and first-party. Step 0
measured the browser's own Opus codec (WebCodecs) and AudioWorklet in
the target engine, which removes the two heavy parts the issue weighed
(a libopus WebAssembly build and Pyodide's roughly 10 MB core); what
remains is the protocol's state machine, a few hundred lines. The
argument for Pyodide was one implementation of the device side, pinned
by the Python tests; the lane in Q5 is what pins the JavaScript instead,
by driving the real page against the real server. First-load size
decides it for a newcomer's first contact, as the issue says.

## Smaller decisions

**D1. A browser's identity is minted by the server, once.** A new
module `onboarding/browser.py` mints it: a random locally administered
unicast MAC (first octet with the `0x02` bit set and the `0x01` bit
clear, so it can never be a real board's address) and a client id by
UUIDv5 under a namespace of its own, the simulator's rule applied to a
different namespace so the two never collide. The page stores both in
`localStorage`. Minting happens in exactly two places, both server-side:
the `/try/redeem` request (D5) and the page's own "start" request when it
holds no identity (D4). No JavaScript mints a MAC.

**D2. The page and its assets.** `GET /try/` serves `index.html` and
`GET /try/static/<file>` serves the modules and the AudioWorklet
processors, from a fixed allowlist read from the package (no directory
listing, no path traversal), with `Content-Security-Policy` restricting
scripts and connections to the same origin, `Referrer-Policy:
no-referrer`, and `Cache-Control` tied to the server's revision (the
page itself `no-store`, D5). Nothing under `/try/` is secret, so none of
it needs a key; the routes are mounted whenever onboarding is enabled,
like the alias, since a browser needs the alias to check in.

**D2a. What a proxy sees.** A browser's requests carry the onboarding key
only in its OTA check-in and the activation poll, the same two requests
a board makes, and the identity-mint request (D4a), which the page sends
to the onboarding path for the same reason. `docs/run/exposing-a-
deployment.md` already has to say that a proxy logging request targets
records the onboarding key from boards' check-ins; this plan extends
that sentence to browsers and makes the rule required, not advisory: a
proxy in front of vinga must redact or suppress the request target of
every `/x/` route (the check-in, `activate`, the poll and
`try-identity`, for boards and browsers alike) before it logs, and the
guide gives the edge-configuration check that proves it (one request to
`/x/<key>/` through the proxy, then the proxy's own log searched for the
key, expecting no match). M2
writes it; nothing about it is new to boards.

**D2b. Assets are addressed by revision.** The page's `index.html`
(served `no-store`) references its modules and worklets under
`/try/static/<revision>/<file>`, where `<revision>` is the server's
build revision, and those responses are `Cache-Control: immutable` for a
long max-age; a request for another revision's path answers 404. So a
page loaded after an upgrade can only import the new set, and a cached
old module can never be imported by a new page. A test serves the page
at one revision, changes the revision, and asserts the new page names
the new paths and the old ones are refused.

**D3b. Where each audio part runs.** Two worklet processors in one
module, `audio-worklet.js`, registered under two names. The capture
processor collects 16 kHz samples into 960-sample (60 ms) blocks and
posts each block to the main thread as a transferred `Float32Array`; the
main thread owns the WebCodecs `AudioEncoder`, which is a window API and
is not assumed inside a worklet, and sends each encoded packet on the
WebSocket. Received packets go to the main thread's `AudioDecoder`; each
decoded `AudioData` is copied to a `Float32Array` and posted (transferred)
to the playback processor, which owns a jitter buffer (a queue of
blocks, starting playback once 120 ms are buffered, rendering silence on
underrun and reporting it), the gain the device tool sets (D3a), and the
running PCM sum the lane reads (Q5a). Messages to it are three: append
samples, set gain, flush (on a barge-in's `tts stop`).

**D3. The client's parts.** Four ES modules and one worklet, each with
one job: `identity.js` (storage, the start request), `ota.js` (the
check-in by `fetch` with the board's headers, which same-origin `fetch`
may set, and the activation poll while unbound), `wire.js` (the
WebSocket, the subprotocol credential, the hello, `listen`, the message
types the server sends), `audio.js` with `capture-worklet.js` (the
microphone at 16 kHz through an `AudioContext`, 60 ms frames to
WebCodecs `AudioEncoder` with Opus and a 60 ms frame duration, received
Opus to `AudioDecoder` at the rate the hello names, played through a
second worklet node with a jitter buffer), and `page.js` (what the
person sees: start, the transcript and reply text the server sends, the
six-digit code when unbound, the ending when the session closes, start
again). A browser without WebCodecs Opus or AudioWorklet gets a plain
sentence naming what is missing and nothing half-working; which engines
were checked is stated in the guide (Chromium measured; others named as
unverified until checked).

**D3a. The browser publishes device tools, as a board does.** The page
advertises MCP in its hello's features, so the server's background
discovery runs as it does for a board, and it answers the MCP exchange
the firmware answers: `initialize`, `tools/list` and `tools/call`, over
the same WebSocket. Its tools are the ones a browser can honestly
implement, named the way the firmware names its own so agents already
know them: `self.get_device_status` (the page's volume and whether it
is listening), `self.audio_speaker.set_volume` (the page's playback
gain, 0 to 100). Nothing it cannot do (a screen's brightness, a
battery) is published. M3's lane asserts the server discovered the
tools (`vinga mcp-server status` does not cover device tools, so the
assertion reads the discovery the session logs) and that one call made
by a scripted mock LLM reaches the page and changes its gain.

**D4. An unbound browser pairs.** A browser opening the page with no
stored identity (cleared storage, or the onboarding URL typed directly)
asks the server to mint one (`POST /x/<key>/try-identity`, on the
onboarding path the person pasted), checks in,
and is unbound unless a default agent covers it: today's rule, which
#612 will change to pairing only for every device. If the reply carries
an activation section, the page shows the six-digit code and polls, as
the firmware does, and the operator claims it with
`vinga device pending claim`. Nothing here anticipates #612; when it
lands, the page needs no change because it follows the reply.

**D4a. Until #612, a browser cannot pair where a default agent admits
everything.** Today a default agent admits an unknown MAC without a
code, which would let a cleared browser reach an agent unbound, against
the issue's rule. Rather than a browser-only exception to that rule
(a second rule #612 would then have to absorb), the page's own start
request (`POST /x/<key>/try-identity`) refuses to mint an identity while
a default agent is set, and the page tells the person to ask for a try
link. With no default agent set, it mints, checks in, and pairs with the
six-digit code as D4 describes. When #612 makes every unbound device
pairing-only, this refusal is removed in #612's own change and the start
request always pairs. Tests cover both: cleared storage with a default
agent set (refused, nothing minted, nothing admitted) and without (a
code shown).

**D5. The `/try/` link carries its token in the fragment, and a GET
spends nothing.** `POST /api/runtime/try-links` (operator bearer, like
every `/api` route) mints a token: 32 random bytes, urlsafe base64, held
in the server's process memory with an expiry (D6) and a used flag,
never written to the database or the event stream. `vinga info` calls it
and prints `<origin>/try/#<token>` (D5c says which origin). The token
travels in the URL's fragment, which a browser never sends to any
server, puts in no `Referer`, and no proxy or server access log can
therefore record, which is what keeps it out of every log rather than
out of the logs this server controls. `GET /try/` is an inert static
page with `Cache-Control: no-store` and `Referrer-Policy: no-referrer`:
a link preview, a prefetch or a scanner fetching it gets the page and
spends nothing, because the token never reached the server. The page's
script reads `location.hash`, clears it from the address bar and the
history entry (`history.replaceState`), and redeems it with a
same-origin `POST /try/redeem` carrying the token in the body. Redeeming
consumes the token (an unknown, expired or used token answers one fixed
refusal, indistinguishable between the three), mints an identity (D1),
binds and names the device in one operation (D5b), and answers the
identity and the onboarding path in the response body, which the page
stores and uses only as the target of its OTA, poll and identity
requests; the page itself stays at `/try/`. The
routes are outside `/api`, so never behind the operator token; the POST
body is never logged, and the sentinel tests plant a token through it.

**D5a. No default agent, no link.** The link's promise is that opening it
binds the browser before its first word, which needs an agent to bind
it to. So the refusal is at issuance: `POST /api/runtime/try-links`
refuses when no default agent is set, with a fixed sentence naming
`vinga default-agent set`, and `vinga info` prints that sentence where
the link would be. Redemption never meets the case (a default agent
removed between issuance and redemption is the one race, answered by
the same fixed refusal and no write). Pairing from the onboarding page
stays the separate route (D4).

**D5b. Bind and name in one operation.** A new store method creates the
device row bound to the default agent and named in the same
transaction, refusing (not merging) if the MAC already exists, so a
spent link can never leave a half-made device. The name is
`Browser <full MAC>`: the MAC is unique per row, so the name is too, and
it reads as a browser in every listing. A MAC collision (46 random bits)
is answered by minting again, up to a small bound, inside the same
redemption; failing that bound refuses with no write. A test injects a
failure between what are today two writes and asserts nothing remains.

**D5c. Which origin the link names, and who decides it.** The link must
open a secure context. The server and the CLI each know one half, so
each owns one: the issuance response carries the configured public
origin when `server.public_url` is set and is `https://` or names
`localhost` (validated server-side), and nothing otherwise; the CLI then
uses that origin, or, when the response carries none, derives
`http://localhost:<port>` only from its own API target when that target
is a loopback address, and otherwise prints no link and one sentence
asking for an HTTPS `server.public_url`. Never the listen address, never
a guess. Tests cover both sides, including a server listening on
`0.0.0.0` with no public URL reached by a CLI on a non-loopback address
(no link printed).

**D5d. One redemption wins.** The token store's `claim(token)` checks and
marks the token used in one synchronous step with no `await` between
them, which on the server's single event loop is linearizable; only
after it returns a winner does redemption mint and write. A loser gets
the fixed refusal and causes no write. A test fires several redemptions
of one token concurrently and asserts exactly one binding and the rest
refused; a mutation that moves the mark after an `await` must fail it.

**D5e. A restart ends every outstanding link.** The store lives in
process memory (one replica, as the deployment contract says), so a
restart or an image upgrade invalidates every unredeemed link before its
ten minutes are up. Redeeming one afterwards meets the same fixed
refusal; a test restarts the store and asserts it. The onboarding guide
and the upgrading guide say so in one sentence each: after a restart,
issue a fresh link with `vinga info`.

**D6. The try link's lifetime.** Ten minutes and one use, as constants,
not configuration: the issue says minutes, and a key nobody needs is
one more thing to document and refuse. The plan review may ask for a
key; if so it goes under `server.onboarding`, beside the alias it sits
with.

**D6a. Expired links are removed, not only refused.** `try_links.py`
owns expiry removal: every mint and every claim first prunes records
past their expiry, and the store holds at most a fixed number of live
links (a mint past the bound refuses with a fixed sentence), so neither
memory nor expired bearer material grows without limit. Tests advance
the injected clock and assert expired records are gone from the store,
not merely refused.

**D6b. Issuance refuses when onboarding is off.** With
`server.onboarding.enabled` false there is no alias for the redeem
response to hand over and no `/try/` page, so `POST /api/runtime/try-links`
refuses with a fixed sentence naming the setting, and `vinga info` prints
it in the link's place. API and CLI tests cover it beside D5a's.

**D7. Every surface reads a browser board as a board.** No new event
type and no new field: `ota_check`, `session_open` and the rest carry
the browser's MAC like any device's. The device record's name is how an
operator tells it apart. The page sends `board.type` `vinga-browser` in
its check-in body so the observed-facts surfaces name it, and nothing
the page stores (identity, the token) reaches any log: the OTA and
WebSocket paths already never log a token, the subprotocol values are
read and dropped, and the try token travels in a URL fragment, which no server or proxy ever receives
(access log off) and the exposure guide warns a proxy might.

**D7a. What each value may reach.** Two classes, each tested by the exact
fields it may appear in. **Device metadata**: the browser's MAC and
client id, which are bounded identifiers a board's events already carry
(`ota_check` names the MAC and the client id, the session events name
the MAC), and which the browser's may carry in exactly those fields and
no others. **Secrets**: the device token and the try token. The device token
appears in exactly the places a board's does (the OTA reply's body,
which hands it to its owner) plus the inbound `vinga.token.*`
subprotocol value, which is read and dropped. The try token appears in
exactly two: the issuance response to the operator's authenticated
request, and the inbound body of `POST /try/redeem`, plus the operator's
own terminal, where `vinga info` prints the link: an owner-facing
disclosure on stdout, never written to a server log, event, exception,
cache or any API response beyond issuance. Neither is logged,
retained beyond its expiry, echoed, returned by any other route, carried
in an accepted subprotocol, or written to any event field or exception
text, in either log format; sentinel tests plant credential-shaped
values for both and assert their absence everywhere else. D7's sentence
that nothing the page stores reaches a log is replaced by this
classification.

**D8. #301 and #305.** #305 is unchanged: the CLI simulator stays the
operator's probe. #301 is recommended, in a comment on it, to shrink to
`--from-file` and `--to-file` for the CLI with no live microphone, since
the browser client is now the live path; editing its scope is Rafael's
call, so the plan only recommends.

**D9. The idle timeout.** The page treats the server's close after the
idle timeout as an ending: it stops the microphone, says the
conversation ended because nobody spoke for a while, and offers to start
again, which reopens the socket with a fresh OTA check (the token may
have aged; the check-in renews it).

## Module layout and design footprint

- `onboarding/browser.py` (new): mints a browser identity; callers stop
  having to know the MAC rules and the namespace.
- `onboarding/try_links.py` (new): the single-use, expiring token store;
  callers stop having to know about expiry and reuse.
- `browser/` (new package): the routes for the page, its static files
  and the try link, and the static files themselves; the app mounts one
  router.
- `ws.py` (deepened): the subprotocol credential as a second way to
  present the same identity and token, behind the same `refusal_reason`.
- `config/api.py` and the CLI's `info`: one route, one printed line.

The seam is the existing one: the browser is a device behind
`device/boundary.py`, and nothing in the runtime knows it is a browser.

## Tests

- **Unit**: identity minting (the MAC's bits, the namespace, never a
  simulator collision); the try-link store (single use, expiry, unknown
  and reused tokens indistinguishable); the subprotocol parse (every
  malformed list refused with the existing reason tokens; headers win
  when both are present; the token value never echoed in the accepted
  subprotocol; a sentinel token absent from every log record); the page
  routes (wrong key 404, allowlist, no traversal, CSP present); the
  `/try/` routes (a GET spends nothing; redeeming binds and names once
  in one transaction; a reused, expired or unknown token gets one fixed
  refusal; issuance refuses without a default agent); `vinga info` printing the link.
  Written first and watched failing; mutations of the guards (single
  use, expiry, header precedence, the echo) each named with the test
  that catches it.
- **Integration**: an xiaozhi-sdk-free WebSocket handshake with the
  subprotocol credential against a running app, a board's handshake
  unchanged beside it.
- **Browser lane** (Q5): `tests/browser/`, Playwright's Python package
  driving the containerized Chromium against a server started from the
  checkout with mock providers; opt-in locally with the container, and a
  CI job in the server workflow using the same image. Its assertions are
  events by name plus the page's own state.
- **Manual checkpoint**: a real laptop, a real room, a real barge-in,
  recorded in the implementation doc with the browser and version.

## Risks

- **A token in a place it is logged.** Q3 keeps it out of the URL; the
  sentinel test plants a credential-shaped token through the subprotocol
  and asserts it is absent from every record, both log formats and the
  event stream.
- **Cross-site use of the edge.** A hostile page cannot present a token
  it does not hold, and no cookie rides its requests; the page's CSP
  restricts its own scripts. The `/try/` token is single-use and short.
- **Engines without WebCodecs Opus.** D3 refuses plainly; the guide
  names what was checked.
- **The 60 ms frame.** WebCodecs' Opus `frameDuration` must produce what
  the server's hello expects; measured in M3 before the rest is built on
  it.
- **The lane's weight in CI.** A container pull and a headless browser;
  measured in M3 and stated in the PR. It runs on every server-workflow
  event (Q5a); if it is slow, M3 makes it faster (a cached image, one
  browser launch per run), never narrower.

## Standing lenses

- **No-leak**: D7a's two classes. The identity is bounded device
  metadata, allowed exactly in the fields a board's identity uses; the
  device token and the try token are secrets, allowed only where D7a
  lists; sentinel tests as above.
- **Pin before reshaping**: `refusal_reason`'s header path is pinned by
  its existing tests, which must pass byte-unchanged with the
  subprotocol path added.
- **Closed sets**: the subprotocol path reuses `AuthRejection`'s
  members; no new reason token unless a decision site needs one, and
  then it is declared.
- **Honest seams**: the try-link store and the identity minter are
  injected with `is not None` checks; their default clock and randomness
  get their own pins.
- **Inventories by tooling**: every route the app serves is listed from
  the app's own route table in a test, so a new unauthenticated route is
  a test failure until it is named.
- **Proportion**: the "Cheapest alternative" line and Q7's measurement.
- **Falsify before claiming**: tests first; the lane's assertions watched
  failing against a page that does not send audio.

## Documentation footprint

M1 and M2: `docs/run/onboarding-a-device.md` (the browser as a device,
the try link), `docs/run/exposing-a-deployment.md` (the secure-context
rule, and that a proxy logging request headers would log a browser's
subprotocol token as it would a board's `Authorization`),
`docs/reference/` through its generators (the API route). M3 and M4:
`docs/devices/browser.md` (new, the Use door: what the page does, which
browsers were checked, realtime and auto, the ending), the glossary's
Device entry, `docs/run/with-a-coding-agent.md` (the `/try/` step, #611's
D8), `docs/devices/README.md` (a browser-client entry outside the board
table, with the page's board-only opening and heading reworded so the
directory reads as one guide per device, boards in the table and the
browser beside it), `docs/README.md`'s Use door, and
the changelog fragments. `concepts.md` gains a sentence that a device may
be a browser.

## Milestones

- [x] **[M1: the browser credential and the page's home](2026-10-06-browser-client-implementation.md#m1-the-browser-credential-and-the-pages-home)** ([PR #624](https://github.com/rafacm/vinga/pull/624)). The
  subprotocol credential in `ws.py` (Q3), identity minting (D1), the
  keyless `/try/` page and its revisioned static routes with a placeholder
  page (D2), the unbound start request (D4), the route-table inventory
  test, and the integration handshake test. A server change a reviewer
  can read alone.
- [ ] **M2: the try link.** The token store with its atomic claim (D5,
  D5d, D6), the API route and its no-default-agent refusal (D5a),
  `vinga info`'s line and its origin rule (D5c), the inert `GET /try/`
  page that reads the token from the fragment and clears it, the
  same-origin `POST /try/redeem` that binds and names in one transaction
  (D5b), their tests, and the onboarding and exposure guides.
- [ ] **M3: the client and its lane.** The modules and worklets (D3),
  realtime and the auto fallback (Q4), the ending (D9), the 60 ms frame
  measured first, the browser lane and its CI job (Q5).
- [ ] **M4: the device guide and the rest of the footprint.**
  `docs/devices/browser.md`, the coding-agent guide's step, the glossary
  and concepts sentences, the manual checkpoint recorded, and the #301
  recommendation comment (D8).

## Plan review round

Reviewed 2026-10-06 by openai/gpt-6-sol, thinking high via codex CLI 0.160.0, read-only sandbox, runtime 3m06s, at commit 48c0bf73, plan blob bf729cfd.

---

1. **P1: The subprotocol handshake cannot reach a conversation as written.** The plan changes only `ws.py` for the browser credential (plan:108 (`docs/plans/2026-10-06-browser-client.md:108`)), but `DeviceSession` still reads `Device-Id` and `Client-Id` from headers and calls `accept()` without selecting a subprotocol (session.py:440 (`vinga-server/src/vinga_server/device/session.py:440`)). A browser can pass the proposed auth check and then be rejected for its missing MAC. **Amend M1** to pass the verified identity and selected protocol into the session, and test a complete browser hello, not only an upgrade.

   *Resolution:* Accepted. Q3a: `ws.py` builds one verified-identity value (MAC, client id, the subprotocol to select) from headers or subprotocol, and `DeviceSession` takes its identity from that value and accepts with the selected subprotocol; a board yields the same value from its headers, pinned by its existing tests, and M1 tests a complete browser hello through the session.

2. **P1: Device MCP tools are missing.** The issue requires the browser to carry device MCP tools. The proposed `wire.js` and browser lane name hello, listen, audio and server messages, but no MCP initialize, tool listing or tool call (plan:195 (`docs/plans/2026-10-06-browser-client.md:195`), plan:146 (`docs/plans/2026-10-06-browser-client.md:146`)). The server discovers tools only when hello advertises MCP (session.py:981 (`vinga-server/src/vinga_server/device/session.py:981`)). **Amend M3** to name the browser tools it can implement, their MCP exchange and a lane assertion that discovers and calls one.

   *Resolution:* Accepted. D3a: the page advertises MCP in its hello and answers `initialize`, `tools/list` and `tools/call` like the firmware, publishing only tools a browser can honestly implement under the firmware's names (`self.get_device_status`, `self.audio_speaker.set_volume`); M3's lane asserts discovery and one scripted call changing the page's gain.

3. **P1: The try token is not kept out of every log.** The issue makes that a condition of putting the token in `/try/<token>`. The plan relies on uvicorn access logging being off, while acknowledging that a reverse proxy may log the path (plan:44 (`docs/plans/2026-10-06-browser-client.md:44`), plan:246 (`docs/plans/2026-10-06-browser-client.md:246`)). A warning does not satisfy the condition for an exposed deployment. **Amend the deployment procedure** with a required proxy rule that suppresses or redacts this path before access logging, and verify it through the documented proxy setup. Give the token response `Referrer-Policy: no-referrer` and `Cache-Control: no-store` so loading its script cannot repeat the URL in a same-origin `Referer` header or a cache.

   *Resolution:* Accepted, by a different mechanism than the finding proposes. Rather than require a proxy rule, D5 moves the token into the URL's fragment (`<origin>/try/#<token>`): a browser never sends a fragment to any server or in a `Referer`, so no proxy or server log can record it. `GET /try/` is inert (`no-store`, `no-referrer`), and the page redeems the token with a same-origin `POST /try/redeem`.

4. **P2: An ordinary GET can consume and bind a try link before the person opens it.** `GET /try/<token>` spends the sole use and writes a device row (plan:222 (`docs/plans/2026-10-06-browser-client.md:222`)). A link preview, prefetch or scanner can make that GET; the subsequent human visit receives 404. **Make the GET inert**, then redeem through a same-origin POST from the opened page, with a test that fetching or previewing the URL leaves it usable.

   *Resolution:* Accepted, by the same change as finding 3: the GET carries no token (the fragment is never sent), so a preview, prefetch or scanner spends nothing; redemption is a same-origin POST from the opened page. M2's tests fetch the page as a previewer would and assert the token still redeems.

5. **P2: The no-default-agent path contradicts itself and the link's guarantee.** D5 says it consumes the token and shows a page without binding; its unit-test list says the route *refuses* without a default agent (plan:235 (`docs/plans/2026-10-06-browser-client.md:235`), plan:293 (`docs/plans/2026-10-06-browser-client.md:293`)). The issue says opening the link binds before the first word. **Choose one refusal point**, preferably declining to issue a link when no default agent is set, with a fixed actionable message. Keep direct onboarding-page pairing as the separate route.

   *Resolution:* Accepted, the finding's preferred option: D5a refuses at issuance when no default agent is set, with a fixed sentence naming `vinga default-agent set` that `vinga info` prints in the link's place; a default agent removed between issuance and redemption meets the same fixed refusal with no write.

6. **P2: Cleared browsers can bypass the issue's pairing rule until #612 lands.** D4 explicitly follows today's default-agent behavior, which admits an unknown MAC without a code, while the issue says a cleared browser is new and unbound and gets pairing only (plan:212 (`docs/plans/2026-10-06-browser-client.md:212`)). **State #612 as a release dependency and test the cleared-storage case with a default agent set**, or implement the pairing rule for browser identities here.

   *Resolution:* Accepted, the second option in a form that adds no second admission rule: D4a refuses to mint an identity from the page while a default agent is set (the page asks for a try link instead), so no cleared browser reaches an agent unbound before #612; with no default agent it pairs by code. #612 removes the refusal in its own change. Both cases are tested.

7. **P2: Binding and naming can leave a spent link attached to a partly created device.** D5 uses `bind_device`, then `rename_device` (plan:227 (`docs/plans/2026-10-06-browser-client.md:227`)); those are separate writes (store.py:956 (`vinga-server/src/vinga_server/config/store.py:956`), store.py:1005 (`vinga-server/src/vinga_server/config/store.py:1005`)). Two random MACs can share their last six hex digits, so the unique browser name can fail after binding and token consumption. **Specify one atomic create-and-name operation**, a collision-free naming rule and retry behavior; test failure between the two current writes.

   *Resolution:* Accepted. D5b: one store method creates the row bound and named `Browser <full MAC>` in a single transaction, refusing rather than merging an existing MAC; a collision is re-minted within a small bound, else refused with no write; a test injects a failure between the two former writes and asserts nothing remains.

8. **P2: The browser lane does not cover the shipped client or its claimed playback.** It starts a server from the checkout and asserts events plus page state (plan:301 (`docs/plans/2026-10-06-browser-client.md:301`)); that cannot catch missing static files in the wheel, nor prove decoded PCM reached the playback worklet. The proposed CI shortcut would also skip changes in `device/session.py`, OTA, protocol or packaging (plan:323 (`docs/plans/2026-10-06-browser-client.md:323`)). **Load the installed artifact in one lane, assert nonzero PCM at the playback sink, and run the browser lane for changes to its server dependencies.**

   *Resolution:* Accepted. Q5a: the lane serves the page from the built wheel installed fresh (one variant against the CI image), asserts a nonzero running PCM sum at the playback sink after a reply, and runs on every server-workflow event with no path filter, its cost measured in M3.

9. **P2: The printed link may be unusable on the default local deployment.** D5 derives its origin like the onboarding URL (plan:226 (`docs/plans/2026-10-06-browser-client.md:226`)). With no configured public URL, that derivation can print the listen address `http://0.0.0.0:8003`, explicitly marked as a guess by the current code (origin.py:178 (`vinga-server/src/vinga_server/onboarding/origin.py:178`)). That does not provide the promised `localhost` secure context. **Specify how `vinga info` obtains a reachable `localhost` URL for a local trial, or refuse link issuance until a usable HTTPS public URL is configured.**

   *Resolution:* Accepted. D5c: `vinga info` prints `server.public_url` when it is https or localhost, else `http://localhost:<port>` when the CLI reached the API on loopback, else no link and a sentence asking for an HTTPS `server.public_url`; never the listen address and never a guess.

10. **P2: The plan's no-leak test asserts an impossible rule for identity.** D1 stores the MAC and client ID in the page; D7 says nothing stored by the page reaches a log, while also requiring the browser MAC in ordinary device events (plan:176 (`docs/plans/2026-10-06-browser-client.md:176`), plan:246 (`docs/plans/2026-10-06-browser-client.md:246`)). OTA already emits the MAC and client ID as device metadata (reply.py:574 (`vinga-server/src/vinga_server/ota/reply.py:574`)). **Classify identity as permitted, bounded device metadata and the token as secret**, then test the exact fields each may reach. If identity itself must remain secret, the proposed reuse of board events needs redesign.

   *Resolution:* Accepted. D7a classifies the MAC and client id as bounded device metadata allowed exactly in the fields a board's events already use, and the device token and try token as secrets that reach no record, field, body or subprotocol; tests assert each class by field, with sentinels for the secrets.

**Verdict: ready after the P1/P2 amendments.**

## Plan review round 2

Reviewed 2026-10-06 by openai/gpt-5.6-terra, thinking high via codex CLI 0.160.0, read-only sandbox, runtime 7m03s, at commit 66809d2b, plan blob 1d75cf3f.

---

1. **P1: M2 still reintroduces the rejected URL-token GET flow.** Evidence: D5 requires `GET /try/` with a fragment token to be inert and redemption by `POST /try/redeem` (plan lines 277-298 (`docs/plans/2026-10-06-browser-client.md:277`)), but M2 still says "`GET /try/<token>` with binding" (line 473 (`docs/plans/2026-10-06-browser-client.md:473`)). That would again leak the token in proxy logs and let previews consume it. The milestone must instead name inert `GET /try/`, fragment clearing, and same-origin `POST /try/redeem`; remove every `/try/<token>` spelling.

   *Resolution:* Accepted. M2's item now names the inert `GET /try/` page, the fragment read and cleared, and the same-origin `POST /try/redeem`; no `/try/<token>` spelling remains outside the recorded findings.

2. **P1: Single-use redemption has no atomicity requirement or concurrent test.** Evidence: D5 describes an in-process token record with a `used` flag (lines 277-295 (`docs/plans/2026-10-06-browser-client.md:277`)), while D5b makes each redemption mint and bind a device (lines 310-318 (`docs/plans/2026-10-06-browser-client.md:310`)). Two simultaneous POSTs can both observe an unused token unless the token-store operation claims it atomically before any await or database work. The plan should require a linearizable `claim(token)` operation, with one winner only, and a parallel-redemption test proving one binding and one fixed refusal.

   *Resolution:* Accepted. D5d: `claim(token)` checks and marks used in one synchronous step with no await between, which is linearizable on the single event loop; minting and writing happen only for the winner; a concurrent-redemption test asserts one binding and fixed refusals, and a mutation moving the mark after an await must fail it.

3. **P2: Authentication-disabled deployments have no defined browser handshake.** Evidence: Q3 always offers `vinga.token.<token>` (lines 108-117 (`docs/plans/2026-10-06-browser-client.md:108`)), but the existing OTA reply deliberately supplies an empty token with `access: open` when device authentication is disabled (auth.py (`vinga-server/src/vinga_server/auth.py:48`)). The plan should specify that an `open` reply omits the token subprotocol while retaining the version, MAC, and client-id subprotocols, and test both auth-enabled and auth-disabled browser sessions.

   *Resolution:* Accepted. Q3b: when the OTA reply says `access: open`, the page omits `vinga.token.*` and keeps the version, MAC and client-id values, and the subprotocol path behaves as the header path does with auth off; browser sessions are tested with auth on and off.

4. **P2: The amended no-leak rules still contradict the redeem flow and each other.** Evidence: D7a says secrets reach no API body beyond the issuing one (lines 345-354 (`docs/plans/2026-10-06-browser-client.md:345`)), yet the try token must reach `POST /try/redeem` in its request body (line 292 (`docs/plans/2026-10-06-browser-client.md:292`)). It also permits browser MAC/client ID in ordinary device event fields, while the standing lens still says identity never reaches a log or event (lines 431-433 (`docs/plans/2026-10-06-browser-client.md:431`)). The plan should explicitly allow the try token only in the issuance response and the inbound redeem body, neither logged, retained, echoed, or returned; it should replace the standing-lens sentence with D7a's metadata-versus-secret classification.

   *Resolution:* Accepted. D7a now lists exactly where each secret may appear: the try token in the issuance response and the inbound redeem body only, the device token in the OTA reply and the inbound subprotocol only, neither logged, retained, echoed or returned elsewhere; the standing no-leak lens now states D7a's two classes instead of the old sentence.

5. **P2: Serving every browser asset below `/x/<key>/` leaks the onboarding secret to normal proxy logs unless the deployment contract changes.** Evidence: D2 makes both the page and every module/worklet request contain the onboarding key (lines 213-220 (`docs/plans/2026-10-06-browser-client.md:213`)). The security guide classifies that key as sensitive and says neither onboarding path segment is written to a log (security.md (`docs/run/security.md:188`)). Uvicorn's disabled access log does not control a reverse proxy. The plan should require proxy redaction or suppression for the full `/x/<key>/...` route family, including request targets and `Referer`, and document that requirement in the exposure guide.

   *Resolution:* Accepted, by moving the page rather than requiring a new proxy rule for it: Q2 and D2 now serve the page and its assets at the keyless `/try/`, and the onboarding path reaches the page only in a response body (the redeem response, or pasted once by the person for an unbound browser). The key then appears only in the OTA check-in, the poll and the identity mint, the requests a board already makes with it. D2a extends the exposure guide's existing onboarding-path advice to browsers and states the rule: exclude `/x/` from request-target logging, or accept the key there as the deployment-scoped segment it is.

6. **P2: The browser lane's required coverage is contradicted by the Risk section.** Evidence: Q5a requires the browser lane on every event that triggers the server workflow because OTA, session, protocol, and packaging changes can break it (lines 172-183 (`docs/plans/2026-10-06-browser-client.md:172`)). The Risks section allows it to run only when `browser/` or `ws.py` changes (lines 425-427 (`docs/plans/2026-10-06-browser-client.md:425`)). The latter would repeat the settled coverage failure. Remove the conditional skip; optimize the lane without narrowing its trigger scope.

   *Resolution:* Accepted. The Risks line no longer narrows the trigger: the lane runs on every server-workflow event as Q5a decides, and if it is slow M3 makes it faster (a cached image, one browser launch per run), never narrower.

7. **P2: "No upgrade action" is false for outstanding try links.** Evidence: try links exist only in process memory (lines 277-281 (`docs/plans/2026-10-06-browser-client.md:277`)), while the operator surface claims no upgrade action (lines 24-31 (`docs/plans/2026-10-06-browser-client.md:24`)). A restart or image upgrade invalidates every unredeemed link before its advertised ten-minute lifetime. The plan should state this expiry condition in the operator and upgrade guidance, test restart invalidation as the same fixed refusal, and tell an operator to issue a fresh link after a restart.

   *Resolution:* Accepted. D5e: a restart or upgrade invalidates every unredeemed link (the store is in memory); redemption afterwards meets the same fixed refusal, tested, and the onboarding and upgrading guides each say to issue a fresh link after a restart. The operator-surface line is corrected to match.

Verdict: not ready. Address the P1 and P2 amendments before implementation.

## Plan review round 3

Reviewed 2026-10-06 by openai/gpt-5.6-terra, thinking high via codex CLI 0.160.0, read-only sandbox, runtime 6m05s, at commit 76efd88b, plan blob ddc48a8f.

---

1. **P1: D2a permits logging the onboarding secret.**
Evidence: D2a says a proxy may "accept that the key is in those logs"; security.md (`docs/run/security.md:220`) says neither onboarding segment is written to a log. This violates the no-leak contract.
Say instead: proxy request-target logging for every `/x/` route, including `try-identity` and `activate`, is required to redact or suppress the path. Remove the acceptance alternative and add an edge-configuration verification step.

   *Resolution:* Accepted. D2a no longer offers accepting the key in a log: redacting or suppressing the request target of every `/x/` route (check-in, activate, poll, try-identity; boards and browsers alike) is a required rule in the exposure guide, with an edge check that searches the proxy's own log for the key after one request and expects no match.

2. **P1: Expired try tokens have no deletion mechanism.**
Evidence: D5/D6 define an in-memory token record with expiry, while D7a promises it is not retained beyond expiry. No pruning, timer, or expiry sweep is specified. Issuing links indefinitely therefore retains expired bearer material and grows memory.
Say instead: `try_links.py` owns expiry removal, including a bounded pruning strategy or scheduled removal; tests must advance the injected clock and prove expired records are removed, not merely refused.

   *Resolution:* Accepted. D6a: every mint and claim prunes expired records first, and the store holds at most a fixed number of live links (refusing a mint past the bound), so expired tokens are removed; tests advance the injected clock and assert removal, not just refusal.

3. **P2: The origin rule has no implementable owner.**
Evidence: D5c says the link uses `localhost:<port>` "when the CLI reached the API on a loopback address," but the server cannot know the address the CLI used. Existing `RuntimeInfo` exposes an onboarding URL, not the safe public-origin value needed for this rule.
Say instead: define the issuance response and responsibility explicitly: the server returns a validated configured public origin when one exists; otherwise the CLI derives only a loopback origin from its own API target. Refuse all other cases. Test both sides, including a server listening on `0.0.0.0`.

   *Resolution:* Accepted. D5c now splits ownership: the server returns a validated configured origin (https or localhost) or none, and the CLI derives `http://localhost:<port>` only from its own loopback API target, refusing every other case; tests cover both halves, including a `0.0.0.0` server reached from a non-loopback CLI.

4. **P2: Try-link issuance is undefined when onboarding is disabled.**
Evidence: D2 mounts `/try/` only when onboarding is enabled; D5a refuses only for a missing default agent. A link could be issued even though redemption cannot return the required alias for OTA.
Say instead: refuse `POST /api/runtime/try-links` when onboarding is disabled, with a fixed actionable message, and cover it in `vinga info` and API tests.

   *Resolution:* Accepted. D6b: with onboarding disabled, issuance refuses with a fixed sentence naming `server.onboarding.enabled`, which `vinga info` prints in the link's place; API and CLI tests cover it.

5. **P2: The static-cache strategy can serve stale protocol code after an upgrade.**
Evidence: D2 serves fixed asset paths such as `/try/static/page.js`, while only saying `Cache-Control` is "tied to the server's revision." The page is `no-store`, but its module imports may remain cached under unchanged URLs.
Say instead: choose and specify either revisioned or content-hashed asset URLs, or `no-cache` plus a revision-derived validator. Add an upgrade/cache test showing a fresh `/try/` page cannot load an older module set.

   *Resolution:* Accepted, revisioned URLs: D2b serves modules and worklets at `/try/static/<revision>/<file>` (immutable), the `no-store` page names the current revision, another revision answers 404; a test changes the revision and asserts a fresh page cannot import the old set.

6. **P2: The audio design names only a capture worklet but requires a playback processor.**
Evidence: D3 specifies `capture-worklet.js`, then requires decoded audio to play through "a second worklet node with a jitter buffer." An `AudioWorkletNode` needs a registered processor; WebCodecs encoding also cannot be assumed to run inside that processor.
Say instead: specify the capture-to-main-thread encoder transfer and either a separate playback worklet or one explicitly dual-purpose worklet module, including its packet/PCM ownership and jitter-buffer message protocol.

   *Resolution:* Accepted. D3b specifies one worklet module with two registered processors: capture posts transferred 60 ms blocks to the main thread, which owns the WebCodecs encoder and decoder; decoded audio is transferred to the playback processor, which owns the jitter buffer (120 ms start, silence on underrun), the tool-set gain and the lane's PCM sum, and takes three messages (append, set gain, flush).

7. **P2: The test plan does not drive the claimed auto fallback.**
Evidence: Q4 promises `auto`, microphone pausing during reply playback, re-arming after `tts stop`, and a user warning; Q5 names only `listen realtime`. No JS unit harness or browser-lane case covers unavailable echo cancellation.
Say instead: add a fake-media case whose track reports echo cancellation unavailable and assert `listen auto`, no outbound mic frames during TTS, re-arm after `tts stop`, and the visible no-interrupt warning.

   *Resolution:* Accepted. Q5b adds the echo-cancellation-unavailable case (a test-only switch, since the fake device always reports true: `listen auto`, no mic frames during playback, re-arm after `tts stop`, the visible sentence) beside the device-tool case.

8. **P2: D7a omits the required CLI disclosure of the try token.**
Evidence: D5 requires `vinga info` to print `<origin>/try/#<token>`, while D7a says the try token appears in exactly the issuance response and redeem request body, and sentinel tests assert absence everywhere else.
Say instead: classify the operator's `vinga info` stdout as an explicitly allowed owner-facing disclosure, while requiring it not to enter server logs, events, exceptions, caches, or any API response beyond issuance.

   *Resolution:* Accepted. D7a lists `vinga info`'s stdout as the one owner-facing disclosure of the try token, and states it reaches no server log, event, exception, cache or API response beyond issuance.

9. **P2: The browser CI lane lacks a provisioned, pinned runtime.**
Evidence: M3 requires Playwright Python plus a Chromium container, but `pyproject.toml` has no Playwright dependency and the existing workflow has no browser-image setup. "Containerized Chromium" alone does not state where the test runner, browser binary, fake WAV, or server networking are installed.
Say instead: name the pinned Playwright/container version, dependency and lockfile changes, CI setup, local invocation, and the wheel/image server topology used by the lane.

   *Resolution:* Accepted. Q5b names the runtime: a `browser` dependency group locked in `uv.lock`, the Playwright container image pinned to the locked version, a committed WAV, the built wheel installed in the container (and the CI image in a second run), one local command in `docs/contributing.md`, and a CI job using the image as its job container, its time measured in M3.

10. **P3, settled round-2 finding #5: keyless-page wording still conflicts with D2.**
Evidence: Q2 and D2 correctly keep the page at keyless `/try/`, but M1 still says page assets are "under the onboarding path," and D5 says the page "moves" to the onboarding path after redemption. That would put the key back into an address/history and proxy request target.
Say instead: state consistently that the browser remains at `/try/`; redemption returns the alias only in a response body, stores it locally, and uses it only as the target of OTA and activation requests.

   *Resolution:* Accepted. M1's item now names the keyless `/try/` page and its revisioned static routes, and D5 says the redeem response hands over the onboarding path in its body, stored and used only as the target of the OTA, poll and identity requests, while the page stays at `/try/`.

11. **P3: The device-guide footprint does not repair the current board-only index.**
Evidence: M4 names only "a line" in docs/devices/README.md (`docs/devices/README.md:1`), whose heading, opening claim, and table all say the directory contains one guide per board. The issue requires a browser guide without a hardware-table row.
Say instead: add a separate browser-client entry outside the board table and revise the surrounding board-only wording so the new guide is discoverable without claiming it is hardware.

   *Resolution:* Accepted. The footprint now gives `docs/devices/README.md` a browser-client entry outside the board table and rewords its board-only opening and heading, so the guide is discoverable without claiming to be hardware.

**Verdict: not ready. Address the P1 and P2 amendments before implementation.**
