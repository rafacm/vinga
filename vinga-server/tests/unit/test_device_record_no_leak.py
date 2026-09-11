"""Neither half of a device record reaches a retained surface.

Review finding 5 of the #449 plan caught the plan treating the record's
two free-text fields as one trust class. They are two:

- `name` is operator-authored, like an agent's name or a prompt
  fragment;
- `location` is conversation-derived, because from M3 the agent writes
  it from something a person said out loud.

The two halves of that finding settled on different timescales, and M5
is where they part company.

**`location` is settled forever.** It reaches no structured event, no
span and no capture file, because the observability map's
structured-events row is metadata only and a spoken string on a dated
event row would sit on the telemetry surface with telemetry retention
and no per-conversation erasure, unrewritten by any later correction.
Nothing in this milestone or any later one moves it, and the first test
below is that claim over every surface at once.

**`name` was settled for M1 to M4 only**, and M5 revised it, which the
implementation doc's M2 section says to expect. The argument that kept
it off the events was that the MAC already identifies a device, so a
copy would be a second home for one fact. What M5 found is a reader for
whom that is false: `deploy/postgres-init.sql` grants `vinga_ro` USAGE
and SELECT on `record` and explicitly REVOKES both on `domain`, so an
analyst, or a dashboard reading as that role, can never resolve a MAC
to a name. The name is now on `session_open` and on
`record.sessions.device_name`, bounded at its decision site the way
`board` and the client id beside it are, and dated: nothing rewrites
either, so a rename splits a series rather than retitling what is
already recorded.

Nothing was weakened to do it. The rule that decides both halves is
unchanged, and it is about provenance: `name` is what an operator
wrote, `location` from M3 is what a person said out loud. The second
test below is what keeps the revision narrow, asserting that the name
is on `session_open` and on no other record, and
`test_the_manifest_says_which_board_and_not_what_it_is_called` is what
keeps the capture manifest out of it: a capture is a file on the
operator's own disk with the domain store an SQL statement away, so it
needs no copy of a name. Its decision track is the exception that
proves the rule, and it is not an exception at all: that file is the
events, so it carries what the events carry.

The refusal cases at the foot of the file are untouched by any of this.
A value a write REJECTED is nowhere on either side, whichever field it
was submitted to.
"""

import json
import logging
from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from tests.conftest import TEST_API_SECRET
from tests.support.checkin import SYSTEM_INFO
from tests.support.config_cli import chain
from tests.support.configs import DEVICE_MAC, DEVICE_UUID
from tests.support.events import both_formats, fields_of
from tests.support.stores import rows
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


def _capture(tmp_path: Path) -> str:
    """The manifest and the decision track together: the two text files
    a capture leaves behind, the audio being the third and carrying no
    field at all."""
    return "\n".join(
        path.read_text(encoding="utf-8")
        for path in sorted((tmp_path / "captures").iterdir())
        if path.suffix in {".json", ".jsonl"}
    )


def _drive(client: TestClient) -> None:
    """A check-in, a handshake and a turn, which is every surface this
    file is about in one pass."""
    checked_in = client.post(
        OTA_PATH,
        json=SYSTEM_INFO,
        headers={"Device-Id": DEVICE_MAC, "Client-Id": DEVICE_UUID},
    )
    assert checked_in.status_code == 200
    assert NAME not in checked_in.text and LOCATION not in checked_in.text
    with connect(client) as websocket:
        shake_hands(websocket)
        spoken, _ = say_something(websocket)
    assert spoken, "the turn did not happen, so nothing was asserted about it"


def test_a_driven_session_puts_no_location_on_any_retained_surface(
    tmp_path: Path, tap: Tap, caplog: pytest.LogCaptureFixture
) -> None:
    """The permanent half, over the whole surface rather than over one
    record of it: the events the tap saw, both shipped log formats, and
    every file the capture wrote, manifest and decision track alike.

    Absence, not sanitization. Nothing takes a location to any of these,
    so there is nothing to clean on the way.
    """
    with caplog.at_level(logging.DEBUG), TestClient(create_app(_config(tmp_path))) as client:
        _drive(client)

    assert LOCATION not in tap.rendered()
    assert LOCATION not in both_formats(caplog)
    assert LOCATION not in _capture(tmp_path)

    # The control beside the absences: the device IS identified on those
    # surfaces, by the MAC, which is a trusted identifier and stays
    # exactly as it was. Without this they would pass on a run that
    # recorded nothing at all.
    assert DEVICE_MAC.lower() in _manifest(tmp_path)
    assert DEVICE_MAC.lower() in tap.rendered()


def test_the_name_is_on_session_open_and_on_no_other_record(
    tmp_path: Path, tap: Tap, caplog: pytest.LogCaptureFixture
) -> None:
    """The half M5 revised, pinned as the narrow thing it is.

    One event carries the name, and it is the one an analyst and a log
    reader both start from. Every other record of the same run carries
    the MAC and not the name, which is what keeps this a second home for
    one fact rather than a habit.
    """
    with caplog.at_level(logging.DEBUG), TestClient(create_app(_config(tmp_path))) as client:
        _drive(client)

    every = [fields_of(record) for record in caplog.records]
    assert every, "nothing was logged, so nothing was checked"
    carrying = {
        str(fields.get("event"))
        for fields in every
        if any(isinstance(held, str) and NAME in held for held in fields.values())
    }
    assert carrying == {"session_open"}
    # More than one event was written, so the set above is a selection
    # rather than the whole of what the run produced.
    assert {str(fields.get("event")) for fields in every} > carrying
    # And nothing before a session: the check-in identifies the same
    # board and has no conversation to name it for.
    assert NAME not in tap.rendered()


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


# --- a stored name carrying a credential, and what the surfaces say ---


# A name that is a URL carrying every credential shape `url_credential`
# knows: a JWT-shaped userinfo password, a token-named query parameter
# and an authorization-named one. The write path refuses this name (the
# `a-name-carrying-a-credential` case below), so it is planted through
# the configuration-file path, which no repository write guards: exactly
# what a value that got in around the rule, or before it, looks like.
#
# The first secret sits inside the 64 characters `bounded_descriptor`
# keeps, so an event that carried the name as written would carry it;
# the other two sit past the bound, so the surface that would carry them
# is the session-detail answer, which is not bounded at all.
JWT_SECRET = "eyJhbGciOiJub25lIn0.eyJuZXZlciI6InJlYWwifQ.sig-1f2e3d"

TOKEN_SECRET = "sk-tok-91d4e7fa-never-a-real-credential"

AUTHORIZATION_SECRET = "Bearer-br-77aa02cd-never-a-real-credential"

SECRET_PARTS = (JWT_SECRET, TOKEN_SECRET, AUTHORIZATION_SECRET)

CREDENTIAL_URL_NAME = (
    f"https://u:{JWT_SECRET}@example.invalid/desk"
    f"?token={TOKEN_SECRET}&authorization={AUTHORIZATION_SECRET}"
)

# What `without_url_credential` leaves of it, which is what every
# surface says instead: the address without the userinfo and without
# the credential-named parameters.
STRIPPED_NAME = "https://example.invalid/desk"

BEARER = {"Authorization": f"Bearer {TEST_API_SECRET}"}


def test_a_credential_a_stored_name_carries_reaches_no_surface_as_written(
    tmp_path: Path, tap: Tap, caplog: pytest.LogCaptureFixture
) -> None:
    """The surfaces M5 added speak the same safe projection every other
    stored string reaches a reader through.

    One rule with one home, `without_url_credential`, and this is its
    fourth reader beside the display walk (#381), the provider build
    (#413) and the spoken identities (#414): the session_open copy is
    stripped at its decision site before it is bounded, so the log, the
    event store's rows and the capture's decision track all carry the
    projection, and the session-detail answer strips the recorded column
    on the way out exactly as `views.device_body` strips the record it
    was copied from. The dated column itself keeps the name as written:
    the grant trusts `vinga_ro` with the record schema, and a row is not
    a display.
    """
    config = Config(
        server={
            "capture": {"enabled": True, "dir": str(tmp_path / "captures")},
            "conversations": {"enabled": True},
        },
        providers=MOCK_PROVIDERS,
        agents={"assistant": MOCK_AGENT},
        devices={DEVICE_MAC: {"name": CREDENTIAL_URL_NAME, "agents": ["assistant"]}},
    )
    with caplog.at_level(logging.DEBUG), TestClient(create_app(config)) as client:
        _drive(client)

    for secret in SECRET_PARTS:
        assert secret not in tap.rendered()
        assert secret not in both_formats(caplog)
        assert secret not in _capture(tmp_path)

    # The control beside the absences: the stripped address IS the name
    # the surfaces speak, so a run that dropped the field could not pass.
    assert STRIPPED_NAME in both_formats(caplog)

    # The dated column keeps what the operator wrote. Storage is not a
    # surface: `vinga_ro` is granted this schema on purpose, and the
    # projection is applied where a reader is answered, not where a row
    # is kept.
    (row,) = rows("sessions")
    assert row["device_name"] == CREDENTIAL_URL_NAME

    # The event store's rows are the same events the log carried, so
    # they hold the same projection. Serialized whole, nested values
    # included, before the hunt.
    opens = rows("events", session=row["session"], name="session_open")
    assert opens, "no session_open row was recorded, so nothing was checked"
    written = json.dumps([one["fields"] for one in opens], default=repr)
    for secret in SECRET_PARTS:
        assert secret not in written
    assert STRIPPED_NAME in written

    # And the HTTP answer over the column, which is where the two
    # secrets past the event bound would surface if anywhere.
    with TestClient(create_app(config)) as reader:
        answered = reader.get(f"/api/sessions/{row['session']}", headers=BEARER)
    assert answered.status_code == 200
    for secret in SECRET_PARTS:
        assert secret not in answered.text
    assert answered.json()["device_name"] == STRIPPED_NAME


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
