"""A browser's identity, minted by the server (#613, D1).

A browser has no MAC of its own, so the server mints one: random,
locally administered and unicast, which is the one range no board's
burned-in address can occupy. The client id beside it is the
simulator's rule (UUIDv5 over the normalized MAC) under a namespace of
its own, so a browser and a simulated board holding the same MAC still
present two client ids.
"""

import secrets
import uuid

import pytest

from vinga_server.config.models import normalize_mac
from vinga_server.onboarding import browser
from vinga_server.simulator import board


def fixed(octets: bytes):
    """Randomness that answers these bytes, and records what it was
    asked for."""
    asked: list[int] = []

    def draw(length: int) -> bytes:
        asked.append(length)
        return octets

    draw.asked = asked  # type: ignore[attr-defined]
    return draw


@pytest.mark.parametrize(
    ("first", "expected"),
    [
        # Every bit pattern of the low two bits, so the rule is pinned
        # in both directions: 0x02 always set, 0x01 always clear, the
        # other six bits as drawn.
        (0x00, 0x02),
        (0x01, 0x02),
        (0x02, 0x02),
        (0x03, 0x02),
        (0xFF, 0xFE),
        (0xAD, 0xAE),
    ],
)
def test_the_first_octet_is_locally_administered_and_unicast(first: int, expected: int) -> None:
    minted = browser.mint(fixed(bytes([first, 1, 2, 3, 4, 5])))

    assert minted.mac.split(":")[0] == f"{expected:02x}"
    assert minted.mac.split(":")[1:] == ["01", "02", "03", "04", "05"]


def test_the_mac_is_normalized_and_the_client_id_is_derived_from_it() -> None:
    minted = browser.mint(fixed(bytes([0xAB, 0xCD, 0xEF, 0x01, 0x23, 0x45])))

    assert minted.mac == "aa:cd:ef:01:23:45"
    assert normalize_mac(minted.mac) == minted.mac
    assert minted.client_id == str(uuid.uuid5(browser.CLIENT_ID_NAMESPACE, minted.mac))
    # A pure function of the MAC, so the same MAC is the same client id.
    assert browser.mint(fixed(bytes([0xAB, 0xCD, 0xEF, 0x01, 0x23, 0x45]))) == minted


def test_six_bytes_are_drawn() -> None:
    draw = fixed(bytes(6))

    browser.mint(draw)

    assert draw.asked == [6]  # type: ignore[attr-defined]


def test_a_browser_and_a_simulated_board_never_share_a_client_id() -> None:
    """The two namespaces differ, so the one MAC the two could share
    still yields two client ids, and a token signed for one is never
    valid for the other."""
    minted = browser.mint(fixed(bytes([0x02, 0, 0, 0, 0, 1])))
    simulated = board.Identity.of(minted.mac)

    assert browser.CLIENT_ID_NAMESPACE != board.CLIENT_ID_NAMESPACE
    assert simulated.mac == minted.mac
    assert simulated.client_id != minted.client_id


def test_the_default_randomness_is_the_operating_systems(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The pin on the default: with nothing injected the draw comes from
    `secrets`, read at call time, and not from a seeded generator."""
    draw = fixed(bytes([0x10, 0x20, 0x30, 0x40, 0x50, 0x60]))
    monkeypatch.setattr(secrets, "token_bytes", draw)

    minted = browser.mint()

    assert draw.asked == [6]  # type: ignore[attr-defined]
    assert minted.mac == "12:20:30:40:50:60"


def test_two_default_mints_differ() -> None:
    assert browser.mint() != browser.mint()
