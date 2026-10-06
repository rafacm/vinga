"""The browser client, driven end to end (#613, Q5, Q5a, Q5b, D3a, D4, D9).

Four cases, one Chromium. Each is a fresh browser profile, so each is a
new device: three are bound by a fresh try link, and the fourth starts
from the onboarding URL and pairs by its code. All of them speak
through the same fake microphone loop (`lane.py` says what it is and
why its timing is what it is).

What a case asserts it observes from outside the page wherever it can:
the server's own events by name, the server's log, the API's record of
the device, and the websocket frames Chromium saw the page send and
receive. The page's own state is read where nothing else can see it,
which is the speaker: the running sum of what the playback processor
rendered, published only when the page's address carries the lane's
switch.
"""

import json
from collections.abc import Callable, Iterator
from dataclasses import dataclass, field
from typing import Any

import pytest
from lane import DIAGNOSTICS, LANE_AGENT, Server
from lane import wait_for as poll
from playwright.sync_api import Browser, Page, WebSocket

PLAIN_REPLY = {"type": "mock", "reply": "You said {text}."}

# What the device-tool case's model does: on hearing "hello", ask for
# the browser's volume tool, under the name the server publishes it as,
# then say so.
VOLUME = 37
TOOL_REPLY = {
    "type": "mock",
    "reply": "Volume set.",
    "tool_when": "hello",
    "tool_name": "self_audio_speaker_set_volume",
    "tool_arguments": {"volume": VOLUME},
}

OBSERVE = "test-observe=1"
NO_ECHO = "test-echo-cancellation=off"

ENDED_IDLE = "The conversation ended because nobody spoke for a while."
ENDED_BY_PERSON = "You ended the conversation."
NO_INTERRUPT = "speaking over a reply does not interrupt it"


@dataclass
class Visit:
    """One page, with what Chromium saw it say and send."""

    page: Page
    try_token: str
    console: list[str] = field(default_factory=list)
    # The websocket as Chromium saw it, in order: ("sent", "audio") for a
    # microphone frame, ("received", <type>, <state>) for a message.
    wire: list[tuple[str, ...]] = field(default_factory=list)
    device_tokens: list[str] = field(default_factory=list)

    def watch(self, socket: WebSocket) -> None:
        def sent(payload: Any) -> None:
            if isinstance(payload, bytes):
                self.wire.append(("sent", "audio"))
            else:
                message = json.loads(payload)
                self.wire.append(("sent", message.get("type", ""), message.get("state", "")))

        def received(payload: Any) -> None:
            if isinstance(payload, bytes):
                self.wire.append(("received", "audio"))
            else:
                message = json.loads(payload)
                self.wire.append(
                    ("received", message.get("type", ""), str(message.get("state", "")))
                )

        socket.on("framesent", sent)
        socket.on("framereceived", received)

    def wait_for(self, what: str, check: Any, timeout: float = 30.0) -> Any:
        """Poll with the page's own wait, so what Chromium reported
        meanwhile is delivered into this record."""
        return poll(
            what, check, timeout, lambda seconds: self.page.wait_for_timeout(seconds * 1000)
        )

    def identity(self) -> dict[str, str]:
        kept = self.page.evaluate("localStorage.getItem('vinga.browser')")
        assert kept is not None, "the page kept no identity"
        return json.loads(kept)

    def status(self) -> str:
        return self.page.locator("#status").inner_text()


def open_link(browser: Browser, server: Server, switches: str, link: bool = True) -> Visit:
    """A fresh try link, opened in a fresh browser profile; or, with
    `link` false, the page alone, as a person who was given only the
    onboarding URL opens it."""
    if link:
        path, _, token = server.api("POST", "/runtime/try-links")["page"].partition("#")
    else:
        path, token = "/try/", ""
    context = browser.new_context(permissions=["microphone"])
    page = context.new_page()
    visit = Visit(page, token)
    page.on("console", lambda message: visit.console.append(message.text))
    page.on("pageerror", lambda error: visit.console.append(str(error)))
    page.on("websocket", visit.watch)

    def checked_in(response: Any) -> None:
        if response.request.method == "POST" and "/x/" in response.url:
            try:
                body = response.json()
            except Exception:
                return
            token = body.get("websocket", {}).get("token") if isinstance(body, dict) else None
            if token:
                visit.device_tokens.append(token)

    page.on("response", checked_in)

    def describe() -> str:
        events = [
            {key: event.get(key) for key in ("event", "device", "reason", "outcome")}
            for event in server.events
        ][-60:]
        return "\n".join(
            [
                f"status: {page.locator('#status').inner_text()}",
                f"console: {visit.console}",
                f"wire: {visit.wire[-40:]}",
                f"events: {events}",
                "log tail:",
                server.log_text()[-6000:],
            ]
        )

    DIAGNOSTICS.append(describe)
    query = f"?{switches}" if switches else ""
    page.goto(f"{server.base}{path}{query}" + (f"#{token}" if token else ""))
    ready = "#start" if link else "#pair"
    visit.wait_for("the page to be ready", lambda: page.locator(ready).is_visible())
    return visit


@pytest.fixture
def visits(browser: Browser, server: Server) -> Iterator[Callable[..., Visit]]:
    """Opens fresh try links, and closes every profile they opened, and
    with it that profile's microphone and socket, when the case ends."""
    opened: list[Visit] = []

    def opener(switches: str, link: bool = True) -> Visit:
        visit = open_link(browser, server, switches, link)
        opened.append(visit)
        return visit

    yield opener
    for visit in opened:
        visit.page.context.close()


def said_in_session(server: Server, mac: str, sentence: str) -> bool:
    """Whether the server's log has this sentence about the device's
    latest session: what it logs as `session <id>: <sentence>`."""
    opened = server.said("session_open", device=mac)
    if not opened:
        return False
    return f"session {opened[-1]['session']}: {sentence}" in server.log_text()


def frames_while_speaking(wire: list[tuple[str, ...]]) -> list[int]:
    """How many microphone frames the page sent inside each reply, from
    the `tts start` it received to the `tts stop` that ended it."""
    counts: list[int] = []
    inside = False
    for entry in wire:
        if entry[:2] == ("received", "tts") and entry[2] == "start":
            inside = True
            counts.append(0)
        elif entry[:2] == ("received", "tts") and entry[2] == "stop":
            inside = False
        elif entry == ("sent", "audio") and inside:
            counts[-1] += 1
    return counts


def assert_no_leak(server: Server, visit: Visit) -> None:
    """D7a: neither the try token nor the device token reaches the
    server's log, the page's console, its document, its storage or its
    address."""
    secrets = [secret for secret in (visit.try_token, *visit.device_tokens) if secret]
    assert visit.device_tokens, "the lane saw no device token to look for"
    log = server.log_text()
    console = "\n".join(visit.console)
    document = visit.page.content()
    storage = visit.page.evaluate("JSON.stringify(Object.entries(localStorage))")
    places = {
        "the server's log": log,
        "the page's console": console,
        "the page's document": document,
        "the page's storage": storage,
        "the page's address": visit.page.url,
    }
    # Said by place and never by value: a failure here is a credential
    # in the open, and the report of it must not be one more.
    leaked = sorted(
        {place for place, text in places.items() for secret in secrets if secret in text}
    )
    if leaked:
        pytest.fail(f"a token reached {', '.join(leaked)}", pytrace=False)


def test_a_realtime_conversation_with_barge_in_and_an_ending(
    visits: Callable[..., Visit], server: Server
) -> None:
    server.seed(PLAIN_REPLY)
    visit = visits(OBSERVE)
    page = visit.page
    mac = visit.identity()["mac"]

    # The try link bound it: a device record, named for a browser, bound
    # to the default agent before it said anything.
    record = server.api("GET", f"/devices/{mac}")["entity"]
    assert record["name"] == f"Browser {mac}"
    assert record["agents"] == [LANE_AGENT]

    page.locator("#start").click()
    visit.wait_for("the check-in", lambda: server.said("ota_check", device=mac))
    visit.wait_for("the session", lambda: server.said("session_open", device=mac))
    assert not page.locator("#no-interrupt").is_visible()
    visit.wait_for(
        "realtime listening", lambda: said_in_session(server, mac, "listening (realtime mode)")
    )

    # Opus frames reached the server and were heard, and a reply came
    # back and was played: the speaker rendered something that was not
    # silence.
    visit.wait_for("the first utterance heard", lambda: server.said("heard", device=mac))
    visit.wait_for(
        "reply audio rendered",
        lambda: float(page.evaluate("document.documentElement.dataset.vingaPcmSum || '0'")) > 0,
    )
    # The microphone stayed open through the reply, and the second
    # sentence cut into it.
    visit.wait_for("a barge-in", lambda: server.said("barge_in", device=mac))
    assert any(count > 0 for count in frames_while_speaking(visit.wire))

    # Then nobody speaks, and the server hangs up: the page says so.
    visit.wait_for(
        "the idle ending", lambda: page.locator("#status").inner_text() == ENDED_IDLE, 30
    )
    visit.wait_for(
        "the idle close", lambda: server.said("session_closed", device=mac, reason="idle")
    )

    # Start again: a fresh check-in and a second session; the person
    # interrupts a reply, then ends the conversation.
    checked = len(server.said("ota_check", device=mac))
    opened = len(server.said("session_open", device=mac))
    page.locator("#start").click()
    visit.wait_for("a fresh check-in", lambda: len(server.said("ota_check", device=mac)) > checked)
    visit.wait_for(
        "a second session", lambda: len(server.said("session_open", device=mac)) > opened
    )
    visit.wait_for("a reply to interrupt", lambda: page.locator("#interrupt").is_visible())
    page.locator("#interrupt").click()
    visit.wait_for(
        "the abort reaching the server",
        lambda: server.said("reply_finished", device=mac, outcome="aborted"),
    )
    page.locator("#end").click()
    visit.wait_for("the person's ending", lambda: visit.status() == ENDED_BY_PERSON)

    assert_no_leak(server, visit)


def test_without_echo_cancellation_the_page_listens_in_auto_mode(
    visits: Callable[..., Visit], server: Server
) -> None:
    server.seed(PLAIN_REPLY)
    visit = visits(f"{OBSERVE}&{NO_ECHO}")
    page = visit.page
    mac = visit.identity()["mac"]

    page.locator("#start").click()
    visit.wait_for("the session", lambda: server.said("session_open", device=mac))
    assert NO_INTERRUPT in page.locator("#no-interrupt").inner_text()
    assert page.locator("#no-interrupt").is_visible()
    visit.wait_for("auto listening", lambda: said_in_session(server, mac, "listening (auto mode)"))

    # A sentence heard, a reply the microphone stays closed for, and the
    # loop's next sentence heard after it opened again.
    visit.wait_for("two utterances heard", lambda: len(server.said("heard", device=mac)) >= 2, 45)
    replies = frames_while_speaking(visit.wire)
    assert replies, "no reply was received"
    # At most the one frame that can be in flight when `tts start`
    # arrives: Chromium reports the message received before the page's
    # handler has run.
    assert all(count <= 1 for count in replies), replies
    starts = [entry for entry in visit.wire if entry[:3] == ("sent", "listen", "start")]
    assert len(starts) >= 2, "the page never asked to listen again after a reply"
    assert float(page.evaluate("document.documentElement.dataset.vingaPcmSum || '0'")) > 0

    page.locator("#end").click()
    visit.wait_for("the person's ending", lambda: visit.status() == ENDED_BY_PERSON)
    assert_no_leak(server, visit)


def test_the_server_discovers_and_calls_the_browsers_device_tools(
    visits: Callable[..., Visit], server: Server
) -> None:
    server.seed(TOOL_REPLY)
    # No switches at all: the page as a person opens it.
    visit = visits("")
    page = visit.page
    mac = visit.identity()["mac"]

    page.locator("#start").click()
    visit.wait_for("the session", lambda: server.said("session_open", device=mac))
    visit.wait_for(
        "the device tools discovered",
        lambda: said_in_session(
            server,
            mac,
            "2 device tool(s): self_get_device_status, self_audio_speaker_set_volume",
        ),
    )
    visit.wait_for(
        "the volume tool's call", lambda: page.locator("#volume").inner_text() == f"Volume {VOLUME}"
    )
    visit.wait_for("the reply after the call", lambda: server.said("replied", device=mac))

    # The lane's switches are inert unless the address names them: the
    # echo canceller decides the mode, and the speaker publishes nothing.
    assert said_in_session(server, mac, "listening (realtime mode)")
    assert not page.locator("#no-interrupt").is_visible()
    assert page.evaluate("document.documentElement.dataset.vingaPcmSum") is None

    page.locator("#end").click()
    visit.wait_for("the person's ending", lambda: visit.status() == ENDED_BY_PERSON)
    assert_no_leak(server, visit)


def test_an_unbound_browser_pairs_with_a_code(visits: Callable[..., Visit], server: Server) -> None:
    """D4: with no default agent set, a browser holding no identity and
    no link starts from the onboarding URL, is minted an identity, shows
    the six-digit code its check-in carries, and is in a conversation
    once the operator claims the code."""
    server.seed(PLAIN_REPLY)
    server.api("DELETE", "/default-agent")
    onboarding = server.api("GET", "/runtime/info")["onboarding_url"]
    visit = visits(OBSERVE, link=False)
    page = visit.page

    page.locator("#onboarding").fill(onboarding)
    page.locator("#join").click()
    visit.wait_for("an identity", lambda: page.locator("#start").is_visible())
    mac = visit.identity()["mac"]

    page.locator("#start").click()
    code = visit.wait_for(
        "a code", lambda: page.locator("#code").is_visible() and page.locator("#code").inner_text()
    )
    assert len(code) == 6 and code.isdigit(), code
    assert not server.said("session_open", device=mac)
    server.api("POST", f"/devices/pending/{code}", {"agents": [LANE_AGENT]})

    visit.wait_for("the claimed browser's session", lambda: server.said("session_open", device=mac))
    visit.wait_for("it was heard", lambda: server.said("heard", device=mac))
    assert not page.locator("#code").is_visible()
    page.locator("#end").click()
    visit.wait_for("the person's ending", lambda: visit.status() == ENDED_BY_PERSON)
    assert_no_leak(server, visit)
