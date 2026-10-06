"""What the browser lane knows about the server it drives (#613).

The lane talks to the server under test only as an operator and a
device would: the configuration API to seed it and issue try links,
its event stream to watch what it says, its log, and the page. This
module is that reach, and the timing the cases depend on. It imports
the standard library and nothing of the server: the runner's
environment is Playwright and pytest alone, and the server is a
separate install, or a container.
"""

import json
import socket
import subprocess
import threading
import time
import urllib.error
import urllib.request
import wave
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest

SPEECH = Path(__file__).with_name("speech.wav")

# How long a realtime session may sit quiet before the server hangs up.
# Short, so the lane meets the ending (D9) within one loop of the
# microphone. The lane starts its own server with it, and CI starts the
# image it runs against with the same value.
IDLE_TIMEOUT_S = 2

# The microphone's loop: the sentence, GAP_S of silence, the sentence
# again, TAIL_S of silence. Read with the reply's length beside it
# (REPLY_MS_PER_CHAR). The first sentence ends at about 1.7 s and its
# utterance about 0.7 s later, when the reply starts and sounds for
# three seconds; the second sentence starts a second after the first
# and ends while that reply is still sounding, which in realtime is a
# barge-in; and the silence after it outlasts the reply to the second
# sentence by more than the idle timeout, so a realtime session is hung
# up on before the loop speaks again. In auto mode the same loop is a
# sentence heard, a reply the microphone is closed for, and the loop's
# next sentence heard once it opens again.
GAP_S = 1.0
TAIL_S = 7.0

# How long the mock voice speaks per character: "You said hello." is
# fifteen, so a reply sounds for three seconds.
REPLY_MS_PER_CHAR = 200

LANE_AGENT = "assistant"

# What a failed case prints about itself: each entry answers a section
# of text, and the conftest's report hook reads them on a failure and
# empties the list after every case.
DIAGNOSTICS: list[Callable[[], str]] = []


def free_port() -> int:
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        return probe.getsockname()[1]


def compose_microphone(into: Path) -> Path:
    """The fake microphone's loop, composed from `speech.wav`."""
    with wave.open(str(SPEECH), "rb") as source:
        rate = source.getframerate()
        width = source.getsampwidth()
        channels = source.getnchannels()
        speech = source.readframes(source.getnframes())

    def silence(seconds: float) -> bytes:
        return b"\x00" * (int(rate * seconds) * width * channels)

    loop = into / "microphone.wav"
    with wave.open(str(loop), "wb") as out:
        out.setnchannels(channels)
        out.setsampwidth(width)
        out.setframerate(rate)
        out.writeframes(speech + silence(GAP_S) + speech + silence(TAIL_S))
    return loop


def wait_for(
    what: str,
    check: Callable[[], Any],
    timeout: float = 30.0,
    pause: Callable[[float], None] = time.sleep,
) -> Any:
    """Poll until `check` answers something truthy, and answer it.

    `pause` is how to wait between polls. A case watching a page passes
    the page's own wait: Playwright's synchronous API delivers what the
    browser reported (a websocket frame, a console line) only while it
    is being called, so a plain sleep would poll a record that never
    moves."""
    deadline = time.monotonic() + timeout
    while True:
        found = check()
        if found:
            return found
        if time.monotonic() > deadline:
            pytest.fail(f"timed out waiting for {what}", pytrace=False)
        pause(0.1)


def wait_ready(base: str, process: subprocess.Popen | None, log: Path | None) -> None:
    """Until the server answers `/readyz`, or it has exited."""
    deadline = time.monotonic() + 90
    while True:
        try:
            with urllib.request.urlopen(f"{base}/readyz", timeout=5):
                return
        except (urllib.error.URLError, OSError):
            pass
        if process is not None and process.poll() is not None:
            tail = log.read_text()[-4000:] if log is not None and log.exists() else ""
            pytest.fail(f"the server exited before it was ready:\n{tail}", pytrace=False)
        if time.monotonic() > deadline:
            pytest.fail(f"no server became ready at {base}", pytrace=False)
        time.sleep(0.5)


class Server:
    """The server under test, as the lane reaches it."""

    def __init__(self, base: str, token: str, log: Path | None) -> None:
        # The page's origin: `localhost`, a secure context, whatever
        # loopback spelling the server was named by.
        self.base = base.replace("127.0.0.1", "localhost").rstrip("/")
        self.token = token
        self.log = log
        self.events: list[dict[str, Any]] = []
        self.lock = threading.Lock()

    def api(self, method: str, path: str, body: Any = None) -> Any:
        request = urllib.request.Request(
            f"{self.base}/api{path}",
            method=method,
            data=None if body is None else json.dumps(body).encode(),
            headers={
                "Authorization": f"Bearer {self.token}",
                "Content-Type": "application/json",
            },
        )
        with urllib.request.urlopen(request, timeout=30) as answer:
            text = answer.read()
        return json.loads(text) if text else None

    def log_text(self) -> str:
        if self.log is None or not self.log.exists():
            return ""
        return self.log.read_text(encoding="utf-8", errors="replace")

    def follow_events(self) -> None:
        """Read the server's event stream into `events`, in a thread of
        its own, for the rest of the run."""
        ready = threading.Event()

        def read() -> None:
            request = urllib.request.Request(
                f"{self.base}/api/runtime/events",
                headers={"Authorization": f"Bearer {self.token}"},
            )
            with urllib.request.urlopen(request, timeout=3600) as stream:
                ready.set()
                for raw in stream:
                    line = raw.decode("utf-8", errors="replace").strip()
                    if not line.startswith("data:"):
                        continue
                    try:
                        event = json.loads(line[len("data:") :])
                    except ValueError:
                        continue
                    with self.lock:
                        self.events.append(event)

        threading.Thread(target=read, daemon=True).start()
        if not ready.wait(30):
            pytest.fail("the server's event stream did not open", pytrace=False)

    def said(self, name: str, **fields: Any) -> list[dict[str, Any]]:
        """Every event of that name whose fields match."""
        with self.lock:
            seen = list(self.events)
        return [
            event
            for event in seen
            if event.get("event") == name
            and all(event.get(key) == value for key, value in fields.items())
        ]

    def seed(self, llm: dict[str, Any]) -> None:
        """The domain half a case runs on: mock providers throughout,
        one agent, and that agent as the default, applied to the running
        server. `llm` is the mock model's entry, which is what the cases
        differ in."""
        self.api("PUT", "/providers/llm/mock", llm)
        self.api("PUT", "/providers/asr/mock", {"type": "mock", "text": "hello"})
        self.api("PUT", "/providers/tts/mock", {"type": "mock", "ms_per_char": REPLY_MS_PER_CHAR})
        self.api("PUT", "/providers/vad/mock", {"type": "mock"})
        self.api(
            "PUT",
            "/agent-defaults",
            {"llm": "mock", "asr": "mock", "tts": "mock", "vad": "mock"},
        )
        self.api("PUT", f"/agents/{LANE_AGENT}", {"prompt": "The browser lane's assistant."})
        self.api("PUT", "/default-agent", {"name": LANE_AGENT})
        self.api("POST", "/runtime/config/reload")
