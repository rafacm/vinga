"""Neither half of a device record reaches a retained surface.

Review finding 5 of the #449 plan caught the plan treating the record's
two free-text fields as one trust class. They are two:

- `name` is operator-authored, like an agent's name or a prompt
  fragment;
- `location` is conversation-derived, because from M3 the agent writes
  it from something a person said out loud.

The maintainer's decision, taken after probing what the
content-and-telemetry contract actually forbids, is that NEITHER
reaches a structured event, a capture manifest or a span. Events and
the manifest keep the MAC, which is a trusted identifier, exactly as
before. `location` cannot go there because the observability map's
structured-events row is metadata only and a spoken string on a dated
event row would sit on the telemetry surface with telemetry retention
and no per-conversation erasure, unrewritten by any later correction.
`name` could, since far-side descriptors like `board` and `version`
already reach `session_open` through a bound, and it does not: the MAC
already identifies the device, so a name on every session row would
give one fact a second home and let it go stale after a rename.

So nothing is sanitized here, and the tests assert ABSENCE rather than
a bound. A device is configured with a credential-shaped name and a
credential-shaped location, a session is driven through it, and neither
sentinel appears in any event payload, in either log format, in the
capture manifest, or in a refusal sentence.

M5 is where a device NAME reaches the recorded sessions, on the
`record` chain and for an analyst who can never join to `domain`. That
is a different surface with a different retention, and it does not
weaken anything here: the assertions below are about the events, the
logs and the capture.
"""

import json
import logging
from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from tests.support.checkin import SYSTEM_INFO
from tests.support.config_cli import chain
from tests.support.configs import DEVICE_MAC, DEVICE_UUID
from tests.support.events import both_formats
from tests.support.wire import connect, say_something, shake_hands
from vinga_server.app import create_app
from vinga_server.config import Config
from vinga_server.config.models import DatabaseConfig
from vinga_server.config.secrets import MASTER_KEY_ENV, generate_key
from vinga_server.config.store import ConfigStore
from vinga_server.db import open_database
from vinga_server.events import Emission, attach_server_tap, detach_server_tap
from vinga_server.ota import OTA_PATH

# The two sentinels, one per field, shaped so a substring hunt for
# either cannot match by accident. They are what an operator's worst
# paste and an agent's worst transcription look like.
NAME = "sk-name-3f9c21ab-never-a-real-credential"
LOCATION = "sk-place-7d0e54bc-never-a-real-credential"

# A second board, for the refusals that need one to collide with.
OTHER_MAC = "11:22:33:44:55:66"

MOCK_PROVIDERS = {
    "llm": {"mock": {"type": "mock", "reply": "heard you"}},
    "asr": {"mock": {"type": "mock", "text": "hello"}},
    "tts": {"mock": {"type": "mock"}},
    "vad": {"mock": {"type": "mock"}},
}

MOCK_AGENT = dict.fromkeys(("llm", "asr", "tts", "vad"), "mock")


class Tap:
    """A server-scope consumer that keeps what it was handed.

    A log record is not the whole surface: `Emission.args` reaches every
    tap as the objects themselves, so a claim that a value reaches
    nobody is asserted here as well as at the log.
    """

    def __init__(self) -> None:
        self.seen: list[Emission] = []

    def emit(self, emission: Emission) -> None:
        self.seen.append(emission)

    def rendered(self) -> str:
        return "\n".join(
            "\n".join([str(one.payload), str(one.message), repr(one.args)])
            for one in self.seen
        )


@pytest.fixture
def tap() -> Iterator[Tap]:
    consumer = Tap()
    attach_server_tap(consumer)
    try:
        yield consumer
    finally:
        detach_server_tap(consumer)


def _config(tmp_path: Path) -> Config:
    """One agent, one board, and the board's record carrying both
    sentinels, with capture on so the manifest is written."""
    return Config(
        server={"capture": {"enabled": True, "dir": str(tmp_path / "captures")}},
        providers=MOCK_PROVIDERS,
        agents={"assistant": MOCK_AGENT},
        devices={
            DEVICE_MAC: {"name": NAME, "location": LOCATION, "agents": ["assistant"]}
        },
    )


def _manifest(tmp_path: Path) -> str:
    """Every capture manifest the run wrote, as text, so the claim is
    over the file rather than over one field of it."""
    return "\n".join(
        path.read_text(encoding="utf-8")
        for path in sorted((tmp_path / "captures").glob("*.json"))
    )


def test_a_driven_session_puts_neither_field_on_any_retained_surface(
    tmp_path: Path, tap: Tap, caplog: pytest.LogCaptureFixture
) -> None:
    """The whole claim in one drive, because the claim is about the
    surface rather than about one record of it: a check-in, a handshake
    and a turn, with the sentinels asserted absent from the events the
    tap saw, from both shipped log formats, and from the capture the
    session wrote."""
    with caplog.at_level(logging.DEBUG), TestClient(create_app(_config(tmp_path))) as client:
        checked_in = client.post(
            OTA_PATH,
            json=SYSTEM_INFO,
            headers={"Device-Id": DEVICE_MAC, "Client-Id": DEVICE_UUID},
        )
        assert checked_in.status_code == 200
        with connect(client) as websocket:
            shake_hands(websocket)
            spoken, _ = say_something(websocket)

    assert spoken, "the turn did not happen, so nothing was asserted about it"
    for sentinel in (NAME, LOCATION):
        assert sentinel not in tap.rendered()
        assert sentinel not in both_formats(caplog)
        assert sentinel not in _manifest(tmp_path)
        assert sentinel not in checked_in.text

    # The control beside the absences: the device IS identified on those
    # surfaces, by the MAC, which is a trusted identifier and stays
    # exactly as it was. Without this the four assertions above would
    # pass on a run that recorded nothing at all.
    assert DEVICE_MAC.lower() in _manifest(tmp_path)
    assert DEVICE_MAC.lower() in tap.rendered()


def test_the_manifest_says_which_board_and_not_what_it_is_called(
    tmp_path: Path,
) -> None:
    """The same claim read field by field, so a future manifest key
    holding the name is caught as a key rather than as a substring."""
    with TestClient(create_app(_config(tmp_path))) as client:
        client.post(
            OTA_PATH,
            json=SYSTEM_INFO,
            headers={"Device-Id": DEVICE_MAC, "Client-Id": DEVICE_UUID},
        )
        with connect(client) as websocket:
            shake_hands(websocket)
            say_something(websocket)

    written = json.loads(_manifest(tmp_path))
    assert written["device"]["mac"] == DEVICE_MAC.lower()
    assert set(written["device"]) <= {"mac", "uuid", "board", "firmware", "client", "client_id"}
    assert "name" not in written["device"]
    assert "location" not in written["device"]


# --- the refusal paths, which are the other half of the finding -------


@pytest.fixture
def store(monkeypatch: pytest.MonkeyPatch) -> Iterator[ConfigStore]:
    monkeypatch.setenv(MASTER_KEY_ENV, generate_key())
    engine = open_database(DatabaseConfig())
    try:
        yield ConfigStore(engine)
    finally:
        engine.dispose()


# What each half's rejected value is submitted to, and what refuses it.
#
# One table rather than a case per path, because the claim is the same
# claim for both trust classes and the review found it asserted at two
# different depths: the name's walked the exception chain and the
# location's read the sentence, so a future refusal carrying the
# rejected location behind it would have left that one green.
#
# Every sentinel here is a value a substring hunt can find. A refusal
# about a BLANK value is covered in `test_device_record.py` instead: the
# empty string is in every sentence ever written, so hunting for it
# would assert nothing.
CREDENTIAL_NAME = "https://user:pw-name-1d73ae05-never-real@example.invalid/desk"

CREDENTIAL_LOCATION = "https://example.invalid/room?api_key=pw-pl-60b2cd94-never-real"


def _taken_name(store: ConfigStore) -> None:
    store.rename_device(DEVICE_MAC, NAME)
    store.bind_device(OTHER_MAC, ["sam"])
    store.rename_device(OTHER_MAC, NAME.upper())


REJECTIONS = (
    # A name another board already answers to, folded. Both spellings
    # are hunted for, since the refusal is about the pair and naming
    # one of them would read as a claim about which was at fault.
    pytest.param(_taken_name, (NAME, NAME.upper()), id="a-name-another-board-holds"),
    # A name that is a URL carrying a credential, which is the shape a
    # paste one argument early really has.
    pytest.param(
        lambda store: store.rename_device(DEVICE_MAC, CREDENTIAL_NAME),
        (CREDENTIAL_NAME,),
        id="a-name-carrying-a-credential",
    ),
    # A location submitted for a board with no record at all, which is
    # the refusal a relocation meets first.
    pytest.param(
        lambda store: store.relocate_device(OTHER_MAC, LOCATION),
        (LOCATION,),
        id="a-location-with-no-record",
    ),
    # And a location that is a URL carrying a credential, which for this
    # field is a sentence somebody said out loud into a microphone.
    pytest.param(
        lambda store: store.relocate_device(DEVICE_MAC, CREDENTIAL_LOCATION),
        (CREDENTIAL_LOCATION,),
        id="a-location-carrying-a-credential",
    ),
)


@pytest.mark.parametrize(("reject", "submitted"), REJECTIONS)
def test_a_rejected_value_is_in_neither_the_refusal_nor_its_chain(
    store: ConfigStore,
    caplog: pytest.LogCaptureFixture,
    reject,
    submitted: tuple[str, ...],
) -> None:
    """A value a write REJECTED is the one most likely to be a pasted
    credential typed one argument early, or a sentence a person said out
    loud, so it is the one a refusal must not carry.

    Through `chain`, which is the renderer the CLI suites already hunt
    sentinels with: it walks `__cause__` and `__context__`, and renders
    each exception's `repr`, its `str`, its arguments and what its own
    attributes hold. A refusal raised inside a handler keeps the
    exception it was handling, and a validation error holds the whole
    rejected fragment, so the sentence alone was never the surface.
    """
    store.set_agent("sam", {"prompt": "You are Sam."})
    store.bind_device(DEVICE_MAC, ["sam"])

    with caplog.at_level(logging.DEBUG), pytest.raises(Exception) as caught:  # noqa: PT011
        reject(store)

    rendered = chain(caught.value)
    for value in submitted:
        assert value not in rendered
        assert value not in both_formats(caplog)
