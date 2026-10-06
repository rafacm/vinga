# Onboarding a device

At the end of this guide you will have a board connected to your
server and talking to one of its agents, admitted by a code read off
its screen rather than by its MAC address, and with no cable where its
firmware allows it.

A device running stock xiaozhi firmware knows one thing about its
backend: the OTA URL, held in NVS (namespace `wifi`, key `ota_url`).
Everything else reaches it from the reply to that URL: the WebSocket
URL, its token and protocol version, and the wall clock. So onboarding
a board is two questions: what URL does it get, and which agent does it
talk to.

Both are answered without a cable and without looking up a MAC address.

**1. Ask for the URL to type.**

```bash
vinga-server config ota-url
# http://192.168.1.10:8003/x/AB2C4D5E/
```

The command contacts nothing: it reads the same config file the server
reads and derives the same key from the same device-auth secret, so it
answers before the first start and while a board waits on a bench. On
stderr it says where the origin came from, and an origin nobody
configured reads as the guess it is: set `server.public_url` to name the
deployment exactly.

There are two places the URL is printed and this is the offline one.
The other is `vinga info`, which reads it back over the configuration
API and is what a deployment administered from somewhere other than its
own host uses; both derive it the same way, because there is one
derivation. The running server's startup line is deliberately neither:
it names the origin and points here rather than repeating the URL, since
a log line is kept, shipped and read by everyone who can read logs. A
GET of the endpoint repeats it only to whoever already reached it. The
key stands in front of the endpoint that issues device tokens, which is
what all three of those sentences are about.

The two inputs are the file and the secret, so it runs wherever both
are. Inside the container they already are:

```bash
docker exec -i vinga vinga-server config ota-url
```

In a checkout they are too, and that is the other place it runs:

```bash
uv run vinga-server config --config ./config.yaml ota-url
```

Those are the two, and the list is shorter than it used to be. This
command used to be reachable through `uvx --from git+...` as well, and
it is not any more: the default install of this package is the
configuration CLI, and this derivation reads the onboarding package,
which is the server half. On that install the command is in the grammar
and answers one sentence saying which half is missing. It is a
server-host command by nature, since the file half it reads is the one a
workstation does not have, and the question a workstation actually has
about a URL, whether anything answers on it, is `vinga-server doctor`'s.

Eight characters, in an alphabet with no `0`/`O` and no `1`/`I`/`l`,
because this string gets typed on a phone keyboard off a small display.
It is derived rather than stored, so it survives restarts and changes
only when the device-auth secret does.

**2. Check what answers there**, before typing it into anything:

```bash
vinga-server doctor
# http://192.168.1.10:8003/x/AB2C4D5E/ is vinga-server 0.1.0, and sends
# devices to ws://192.168.1.10:8003/xiaozhi/v1/ (protocol version 1).
```

With no argument it checks the URL above; give it one to check any
other. It is a GET and never a POST, so it mints nothing, and it
reports what a device would be told: nothing answers there, something
other than vinga-server answers, vinga-server answers but sends
devices to a plain `ws://` URL from behind TLS (see
[Behind a reverse proxy](exposing-a-deployment.md#behind-a-reverse-proxy)),
or it is healthy.
Healthy exits 0 and the rest exit 1.

**3. Type it into the board's captive portal.** A board with no Wi-Fi
provisioning brings up its own access point; join it, and the portal
offers the network form plus an advanced section holding the server
address. Put the URL there. Which button starts that portal and what
the board shows while it waits are per-board facts, and they are in
[`devices/`](../devices/README.md).

A portal that saves the address without its trailing slash is fine:
every device-facing route answers both spellings itself, and none of
them redirects, because the firmware does not follow a redirect on
these requests.

**4. Read the six digits off the board, if it shows any.** A device the
configuration resolves to no agent is answered with an activation code
instead of a token: the firmware shows it and speaks it, and re-checks
every half minute to two minutes, so the number on the screen is always
the current one. A board a `default_agent` already covers shows no code
and connects straight away, which is the case just below.
`vinga-server config device pending list` lists every board waiting, with the board
type and firmware version each one reported, which is how two boards on
one desk are told apart.

**5. Bind it, by the code rather than by the MAC:**

```bash
vinga-server config device pending claim 418293 assistant
# wrote device aa:bb:cc:dd:ee:ff bound to assistant
```

The device polls every three seconds while it waits, so it connects
seconds later with no restart and no power cycle. `device bind` is the
same write for a MAC you already know; `device pending claim` is for the
board in front of you.

**Which devices are offered a code.** Exactly those the database
resolves to nothing: no binding row of their own, and no
`default_agent` set. A deployment with a default agent covers every
unknown board by design, so its devices are handed a token straight
away and never see a code, which is also why nothing changes for a
deployment that upgraded into this. Turning `server.onboarding.enabled`
off removes both the short URL and the code ceremony.

**On a fresh deployment, write the agent and apply it.** A server
serves the world it last installed, so an agent written into an empty
database is not being served yet: bind a board to it and the
acknowledgement says which command installs it rather than promising
otherwise. `vinga-server config apply` is that command, and from there
the board connects at its next check-in, seconds later; no step of a
deployment's life needs a restart once the process is up.

**Already-provisioned boards keep working.** A board carrying a full
`ota_url` in NVS reaches `server.ota_path` exactly as before, and both
routes serve the same endpoint. Rewriting NVS wipes a board's Wi-Fi
provisioning, so there is no need to move a fleet at all; a board that
is being reprovisioned anyway can be given the short URL instead. Once
no board needs it, `ota_path: null` unmounts the legacy route and
leaves one way in.

**A rotated device-auth secret changes the key**, because the key is
derived from it. Boards already connected do not care: they hold their
own full URL. What needs the old key is a board being onboarded through
the URL somebody wrote down before the rotation, and
`server.onboarding.key` pins it for exactly that. A wrong key answers
404, byte for byte what a path that was never served answers, and the
server's log repeats neither key: it records an
[`onboarding_key_mismatch`](../reference/events.md#onboarding_key_mismatch)
carrying only how long the attempt was, or an
[`onboarding_key_unshaped`](../reference/events.md#onboarding_key_unshaped)
when the segment could not have been typed at a key at all. A run of
mismatches is the sign of a typo or a rotation; the URL to compare
against is what `vinga-server config ota-url` prints on your own
terminal.

## A browser, by a try link

A browser can be a device too: the server serves a page at `/try/`
that joins the deployment the way a board does, checking in at the
short URL and talking over the same WebSocket. What a board gets from
its captive portal and a claimed code, a browser gets from one link,
which `vinga info` prints each time it runs:

```console
$ vinga info
...
try link (opens this deployment in a browser, once, within ten minutes):
http://localhost:8003/try/#Xq3b...
```

Opening it binds that browser to the default agent before it says a
word: the server creates a device named `Browser <its MAC>` (a MAC the
server makes up, which no board can have), the page keeps the identity
in the browser's own storage, and `vinga list` shows it among the
devices beside the boards. The page's conversation client is not built
yet, so today opening the link binds the browser and stops there.

The link is a credential, and it is short-lived on purpose. It works
once: a second browser opening the same link is told it cannot be
used. It expires ten minutes after it was printed if nobody opens it,
and a restart of the server, an upgrade included, ends every link not
yet opened, so after one run `vinga info` again for a fresh link. The
token is the part after `#`, which a browser never sends to any server
or proxy, so opening the link puts it in no access log; a link preview
or a scanner fetching the URL gets the page and spends nothing. Only
the page's own script reads it, clears it from the address bar, and
hands it back to the server once.

Which address the link names follows from where a browser's
microphone works, which is a secure context: an `https://` origin or
`localhost`. When `server.public_url` is an `https://` origin (or a
loopback one), the link names it. Otherwise `vinga info` names
`localhost` on the port it reached the API on, when it reached it on
this machine, and prints no link at all when it did not, asking for an
`https://` `server.public_url` instead. It never names the listen
address.

`vinga info` prints a sentence in the link's place, and carries on,
when the server will not issue one: with no default agent set (set one
with `vinga default-agent set <name>`, since a link binds to it), with
`server.onboarding.enabled` off, and while as many links are waiting to
be opened as the server holds.

**The WebSocket URL** is derived from the address the device reached
the OTA endpoint on, so a LAN deployment needs no extra configuration.
Set `server.websocket_url` when the server sits behind a proxy or a
name the request headers do not carry.

vinga-server serves no firmware images: the reply always tells the
device it is up to date.

The ceremony above has been driven end to end against a simulated
device and a served server, and validated on hardware on 2026-08-13, on
both of the boards available: the Waveshare factory AMOLED-2.16
onboarded from its portal with no cable, and the stock-firmware
Touch-LCD-1.54 pointed at the same server over USB-written NVS. That is
what turns "the firmware shows the code" from a reading of upstream's
sources into an observation, and the evidence is recorded with the
ceremony in
[`xiaozhi-notes.md`](../xiaozhi-notes.md#activation-the-6-digit-code-ceremony).
The serial procedures a board needs, writing its NVS and reading it
back, are in
[`devices/README.md`](../devices/README.md#writing-the-servers-address-into-nvs).
