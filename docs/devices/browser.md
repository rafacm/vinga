# The browser client

A page your vinga server serves at `/try/`, which makes a web browser
on a computer a device: the computer's microphone is the device's
microphone, its speakers are the device's speaker, and the page is its
screen. It speaks to the server exactly as a board does, checking in
first and then holding the conversation over the same WebSocket, so
the agent that answers, its voice, its memory and the way it takes
turns are the ones a board gets. Nothing is installed: the server
ships the page, and the browser is the rest.

Every section below says where its facts come from, in one of three
ways: **checked in the browser lane**, which drives the page in
headless Chromium on every change to the server, with a sound file
standing in for the microphone (what that does and does not cover is
in [Which browsers were checked](#which-browsers-were-checked)); **read
from the page's code** and not checked in a browser; or **not checked
at all**, which is stated rather than guessed around.

What every device shares, and this guide does not repeat, is on the
[common page](README.md): what the two listening modes mean, and how a
device's own controls reach the assistant. It is written about boards
running the upstream firmware; where the browser differs, this guide
says so.

## Getting a browser onto your server

A browser becomes a device in one of two ways. Both need the server's
onboarding switched on, which is the default, since the page is not
served without it; a try link also needs the server to have a default
agent, which the link binds the browser to. Pairing needs no default
agent when the person claiming the code names the agent. The browser
lane joins both ways.

**With a try link.** Whoever runs the server runs `vinga info`, which
prints a new try link each time, an address ending in `/try/#`
followed by a long code. Opening it is the whole of joining: the page
tells the server, the server makes this browser a device bound to its
default agent, named `Browser` and the device's address, and the page
says:

> This browser is now a device of this server, bound to its default
> agent. Press Start to talk.

The page removes the code from the address bar as soon as it has read
it. A link works once, for ten minutes, and a restart of the server
ends every link nobody has opened yet; a link that cannot be used any
more says so on the page and asks for a new one. How links are issued,
and which address they name, is in
[Onboarding a device](../run/onboarding-a-device.md#a-browser-by-a-try-link).

**By pairing with a code.** Opened with no try link, the page asks for
the onboarding URL: the address `vinga info` prints for a board's
captive portal, which whoever runs the server can give you. Paste the
whole URL, press Join, then press Start. The page takes only a URL
naming the server it was itself opened from: one naming another
server, or a bare path with no server in it, is refused before
anything is sent, since the URL's key belongs to that server alone,
and the page says:

> That is not this server's onboarding address: paste the whole URL
> its operator gave you, and open this page at the address it names if
> it names another address than this one.

So open the page at the address the onboarding URL names, then paste
it. The page checks in and shows a six-digit
code with the words "Tell the person who runs this server this code,
so they can connect this browser"; once they claim it
(`vinga device pending claim <code>`, which binds this browser to the
server's default agent, or to the agent the command names), the
conversation starts by itself. With onboarding on, this works whether
or not the server has a default agent: a browser with no identity
pairs, as every new device does.

Either way the browser remembers that it is a device, and opening the
page at `/try/` again, without a link, offers Start straight away.

## Controls

Checked in the browser lane:

| Control | Effect |
| --- | --- |
| Start | Checks in with the server, opens the microphone, connects and listens. |
| Interrupt | Shown only while a reply is playing. Stops the reply at once, the way a board's button does while the assistant is speaking. |
| End | Ends the conversation. |
| Start again | Shown once a conversation has ended, for whatever reason. Checks in afresh and starts a new conversation. |

The browser asks permission for the microphone the first time Start
opens it. When the microphone cannot start, the page says "This page
cannot use the microphone. Allow it for this site and press Start
again.", stops every capture it was handed, and offers Start again;
the lane checks this with a microphone whose setup fails after the
browser granted it, and a refused permission takes the same path in
the page's code. There is no wake word. Read from the page's code:
nothing is listening before Start, the microphone is opened only once
the server has admitted the browser, and it is released when the
conversation ends.

## Listening, and interrupting a reply

The page asks the browser for its microphone with echo cancellation
and noise suppression on, and the browser's answer about echo
cancellation decides the listening mode for that conversation, as the
firmware's build does for a board.

- **Echo cancellation on: realtime.** The microphone stays open for the
  whole conversation, while the assistant speaks included, so speaking
  over a reply interrupts it, exactly as on a board with echo
  cancellation. Headless Chromium reports echo cancellation on, and
  the lane holds a realtime conversation in which a sentence spoken
  during a reply cuts into it.
- **Echo cancellation off: auto.** The page sends nothing while a reply
  plays, and listens again once the reply has finished playing, so it
  never hears itself. Speaking over a reply does nothing, and the page
  says so under its status line:

  > This browser cannot cancel its own echo, so speaking over a reply
  > does not interrupt it. Wait for the reply to finish, or press
  > Interrupt.

  The lane checks this mode by telling the page to treat its
  microphone as one without echo cancellation, since the fake
  microphone always reports it on. Which real browsers report it off
  has not been checked.

What realtime looks like in a room, with the reply coming out of the
computer's speakers and into its microphone, has not been checked: see
[What is not claimed](#what-is-not-claimed).

## The ending

Checked in the browser lane: in realtime the server hangs up on a
conversation nobody is speaking in, after its idle timeout (two minutes
by default, counted as the [common page](README.md#what-the-device-listens-to-and-when)
describes), and the page says:

> The conversation ended because nobody spoke for a while.

and offers Start again. Pressing End says "You ended the
conversation." Read from the page's code: any other close, such as the
network dropping or the server restarting, says "The conversation
ended." In auto mode the idle timeout does not apply, as on a board; a
conversation lasts until End, a lost connection, or the server's
session limit (an hour by default).

## What the page shows

Read from the page's code:

- **A status line** saying what is happening: checking in, listening,
  speaking, or how the conversation ended.
- **The transcript**: each thing the server heard you say, as a line
  starting `You:`, and each sentence of the reply as it starts, as a
  line starting `Reply:`. It stays on the page until the page is
  reloaded, and the page keeps none of it in the browser's storage.
- **The volume** the page plays replies at, from 0 to 100.

## Voice commands the device answers

The page publishes its own controls to the server, as a board does,
under the names the firmware uses for the same controls, so an agent
already knows them. Phrasings are examples; anything equivalent works.

- **"What is the volume?"** Reports the page's volume and whether it is
  listening.
- **"Set the volume to 40."** Sets the volume the page plays replies at,
  from 0 to 100. It acts on the page alone, on top of the computer's
  own volume. Checked in the browser lane: the server discovers both
  controls, and a call to this one changes both the volume the page
  shows and the gain its speaker applies.

The volume starts at 70 each time the page is loaded and is not kept
across a reload. Nothing a browser cannot honestly do (a screen's
brightness, a battery, the WiFi) is offered. As on every device, these
are available once the server has finished discovering them just after
a conversation opens, which a request in its first moment can beat;
asking again is the remedy
([the common page](README.md#talking-to-the-device-itself)).

## Where the page works: https or localhost

A browser lets a page use the microphone only in a secure context: a
page opened over `https://`, or on `localhost`, the address a browser
on the server's own computer reaches it at. Read from the page's code:
anywhere else the page says, and starts nothing:

> This browser cannot run vinga's client: it lacks a secure connection
> (open this page over https, or on localhost).

So a try link naming `localhost` works only in a browser on the
server's own computer, and a browser on another computer needs the
server reached over `https://`, which is the operator's to set up
([Exposing a deployment](../run/exposing-a-deployment.md)). The same
sentence names anything else a browser lacks that the page needs:
microphone access, AudioWorklet, WebCodecs audio, or WebCodecs' Opus
codec.

## What the browser keeps, and clearing it

Read from the page's code: the page keeps three things in the
browser's storage for the server's site, and nothing else. They are
this device's identity, which is an address the server made up for it
(one no board can have) and an id derived from it, and the onboarding
path it checks in at. It keeps no token: it checks in before every
conversation, as a board does when it starts, and holds what it is
handed only for that conversation.

That stored identity is the device. Clearing the site's data, or
opening the page in another browser, another browser profile, or a
private window, is a new browser to the server, with no identity: the
page asks for a try link or the onboarding URL again, and joins as a
new device, which from the onboarding URL means pairing by a code. Opening a fresh try link in a browser that is already a
device does the same, replacing its identity with a new one. The
device it was before stays on the server, named and bound as it was,
until whoever runs the server deletes it; no browser holds its
identity any more.

A browser that refuses to store anything for the site cannot join, and
the page says so. By then a try link has been spent, so ask for a new
one once storage is allowed.

## Which browsers were checked

Chromium alone, and only headless: the browser lane runs HeadlessChrome
153 (153.0.8010.12), the one Playwright 1.63's own container image
carries, against a server installed from the same build that ships.
Its microphone is a sound file, so it has never heard a room. Five
cases in it, on every change to the server: realtime, with a sentence
that cuts into a reply, Interrupt, End and the idle ending; auto mode,
listening again only once a reply has finished playing; the server
discovering and calling the page's two controls; a browser pairing by
its code, after refusing an onboarding URL from another server and a
bare path; and a microphone that fails to start, which the page
releases. The same Chromium has
also joined through a try link printed by `vinga info` and held a
conversation outside the lane.

No other browser has been checked: not Firefox, not Safari, not
desktop Chrome or Edge, and no browser on a phone or tablet. Whether
any of them runs the page is unknown. One that lacks something the
page needs says what, as above, and does nothing else.

## What is not claimed

- **Echo cancellation in a real room.** The lane's microphone is a
  file, which no echo from the speakers can reach, so whether a
  browser's echo cancellation keeps a reply coming out of a laptop's
  speakers from being heard as you speaking, and whether talking over
  a reply stops it promptly, has not been checked on any computer.
  Headphones avoid the question: with them, a reply never reaches the
  microphone.
- **Any browser but headless Chromium**, as above.
- **Latency and audio quality.** Nothing here measures how long a reply
  takes or how it sounds.
- **A page left in the background**, a computer going to sleep during a
  conversation, or a microphone switched mid-conversation: none has
  been checked.
