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

**Operator surface:** a new route family (`/try/<token>`, the page under
the onboarding path) and a new line in `vinga info` (the try link); no
new configuration key in M1 to M3 unless the plan review asks for one
(D6 names the one candidate); a device guide `docs/devices/browser.md`
(the Use door), a line in `docs/run/onboarding-a-device.md`, the
`/try/` step in `docs/run/with-a-coding-agent.md` (#611's D8), and the
glossary's Device entry widened to a browser. No upgrade action; a
deployment that never opens a try link behaves exactly as before.

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

**Q2. How the page reaches the OTA route.** The page is served under the
onboarding path, at `/x/<key>/try/` (and `/x/try/` where onboarding is
keyless because auth is off), so it reaches the OTA endpoint it is
served beside by a relative URL and the key is never typed, never put
in the page's source by the server for a different path, and never
printed beyond where it is today. Anyone holding the onboarding URL can
already check in as a board; loading the page grants nothing more. The
`/try/<token>` link (D5) redirects there after binding.

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
the `/try/<token>` route (D5) and the page's own "start" request when it
holds no identity (D4). No JavaScript mints a MAC.

**D2. The page and its assets.** `GET /x/<key>/try/` serves
`index.html`; `GET /x/<key>/try/static/<file>` serves the modules and
the AudioWorklet processor, with a strict set of files (no directory
listing, no path traversal: a fixed allowlist read from the package),
`Content-Security-Policy` restricting scripts to the same origin, and
`Cache-Control` tied to the server's revision. A wrong key answers the
stock 404, as the OTA alias does. Mounted only when onboarding is
enabled, exactly like the alias.

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
asks the server to mint one (`POST /x/<key>/try/identity`), checks in,
and is unbound unless a default agent covers it: today's rule, which
#612 will change to pairing only for every device. If the reply carries
an activation section, the page shows the six-digit code and polls, as
the firmware does, and the operator claims it with
`vinga device pending claim`. Nothing here anticipates #612; when it
lands, the page needs no change because it follows the reply.

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
identity and the onboarding page's path, to which the page moves. The
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

**D5c. Which origin the link names.** The link must open a secure
context. `vinga info` prints `server.public_url` when it is set and is
`https://` or names `localhost`; otherwise, when the CLI reached the API
on a loopback address, it prints `http://localhost:<port>/try/#…` from
the port it used, which is a secure context on the machine running the
server; otherwise it prints no link and one sentence saying to set
`server.public_url` to an HTTPS address. It never prints the listen
address, and never a guess.

**D6. The try link's lifetime.** Ten minutes and one use, as constants,
not configuration: the issue says minutes, and a key nobody needs is
one more thing to document and refuse. The plan review may ask for a
key; if so it goes under `server.onboarding`, beside the alias it sits
with.

**D7. Every surface reads a browser board as a board.** No new event
type and no new field: `ota_check`, `session_open` and the rest carry
the browser's MAC like any device's. The device record's name is how an
operator tells it apart. The page sends `board.type` `vinga-browser` in
its check-in body so the observed-facts surfaces name it, and nothing
the page stores (identity, the token) reaches any log: the OTA and
WebSocket paths already never log a token, the subprotocol values are
read and dropped, and `/try/<token>` is a path the server does not log
(access log off) and the exposure guide warns a proxy might.

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
  `/try/` route (binds once, names the device, answers 404 to reuse,
  refuses without a default agent); `vinga info` printing the link.
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
  measured in M3 and stated in the PR. If it costs more than a few
  minutes per run, it runs only when `browser/` or `ws.py` changes.

## Standing lenses

- **No-leak**: the subprotocol token, the try token and the identity
  never reach a log, an event, an exception text or an API body beyond
  the one that issues them; sentinel tests as above.
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
D8), `docs/devices/README.md` (a line), `docs/README.md`'s Use door, and
the changelog fragments. `concepts.md` gains a sentence that a device may
be a browser.

## Milestones

- [ ] **M1: the browser credential and the page's home.** The
  subprotocol credential in `ws.py` (Q3), identity minting (D1), the
  page and static routes under the onboarding path with a placeholder
  page (D2), the unbound start request (D4), the route-table inventory
  test, and the integration handshake test. A server change a reviewer
  can read alone.
- [ ] **M2: the try link.** The token store (D5, D6), the API route,
  `vinga info`'s line, `GET /try/<token>` with binding and the address
  bar cleared, its tests, and the onboarding and exposure guides.
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

7. **P2: Binding and naming can leave a spent link attached to a partly created device.** D5 uses `bind_device`, then `rename_device` (plan:227 (`docs/plans/2026-10-06-browser-client.md:227`)); those are separate writes (store.py:956 (`vinga-server/src/vinga_server/config/store.py:956`), store.py:1005 (`vinga-server/src/vinga_server/config/store.py:1005`)). Two random MACs can share their last six hex digits, so the unique browser name can fail after binding and token consumption. **Specify one atomic create-and-name operation**, a collision-free naming rule and retry behavior; test failure between the two current writes.

8. **P2: The browser lane does not cover the shipped client or its claimed playback.** It starts a server from the checkout and asserts events plus page state (plan:301 (`docs/plans/2026-10-06-browser-client.md:301`)); that cannot catch missing static files in the wheel, nor prove decoded PCM reached the playback worklet. The proposed CI shortcut would also skip changes in `device/session.py`, OTA, protocol or packaging (plan:323 (`docs/plans/2026-10-06-browser-client.md:323`)). **Load the installed artifact in one lane, assert nonzero PCM at the playback sink, and run the browser lane for changes to its server dependencies.**

9. **P2: The printed link may be unusable on the default local deployment.** D5 derives its origin like the onboarding URL (plan:226 (`docs/plans/2026-10-06-browser-client.md:226`)). With no configured public URL, that derivation can print the listen address `http://0.0.0.0:8003`, explicitly marked as a guess by the current code (origin.py:178 (`vinga-server/src/vinga_server/onboarding/origin.py:178`)). That does not provide the promised `localhost` secure context. **Specify how `vinga info` obtains a reachable `localhost` URL for a local trial, or refuse link issuance until a usable HTTPS public URL is configured.**

10. **P2: The plan's no-leak test asserts an impossible rule for identity.** D1 stores the MAC and client ID in the page; D7 says nothing stored by the page reaches a log, while also requiring the browser MAC in ordinary device events (plan:176 (`docs/plans/2026-10-06-browser-client.md:176`), plan:246 (`docs/plans/2026-10-06-browser-client.md:246`)). OTA already emits the MAC and client ID as device metadata (reply.py:574 (`vinga-server/src/vinga_server/ota/reply.py:574`)). **Classify identity as permitted, bounded device metadata and the token as secret**, then test the exact fields each may reach. If identity itself must remain secret, the proposed reuse of board events needs redesign.

**Verdict: ready after the P1/P2 amendments.**
