"""The invite link's token store (#613, D5, D5d, D6, D6a).

An invite link is a bearer token held in this process's memory: minted for
the operator, redeemed once by the browser that opens the link, and
gone after ten minutes whether or not anybody opened it. What the store
promises is four things, each pinned here by what a caller can see:

- a token is claimed at most once, and the claim is one step;
- an unknown, an expired and a spent token are one answer;
- expired records are removed, not merely refused, and the store never
  holds more than its capacity;
- the clock and the randomness are the injected ones when given and the
  operating system's when not.
"""

import base64
import secrets
import time

import pytest

import vinga_server.onboarding as onboarding
from vinga_server.config.loader import InviteRefusedError
from vinga_server.onboarding.invites import CAPACITY_REACHED, Invites


class Clock:
    """A clock a test moves by hand."""

    def __init__(self, now: float = 1000.0) -> None:
        self.now = now

    def __call__(self) -> float:
        return self.now


def counting():
    """Randomness that answers a different 32 bytes on every draw, and
    records how many it was asked for."""
    asked: list[int] = []

    def draw(length: int) -> bytes:
        asked.append(length)
        return len(asked).to_bytes(length, "big")

    draw.asked = asked  # type: ignore[attr-defined]
    return draw


def test_a_token_is_thirty_two_drawn_bytes_in_urlsafe_base64() -> None:
    draw = counting()
    links = Invites(randomness=draw)

    token = links.issue()

    assert draw.asked == [32]  # type: ignore[attr-defined]
    assert token == base64.urlsafe_b64encode((1).to_bytes(32, "big")).rstrip(b"=").decode()
    assert "=" not in token
    assert len(token) == 43


def test_an_issued_token_is_claimed_exactly_once() -> None:
    links = Invites(clock=Clock())
    token = links.issue()

    assert links.claim(token) is True
    assert links.claim(token) is False
    assert links.claim(token) is False


def test_a_spent_token_is_gone_from_the_store() -> None:
    """Spent is not a flag kept beside the token: the record leaves with
    the claim, so nothing of a used link stays in memory."""
    links = Invites(clock=Clock())
    token = links.issue()
    links.issue()

    links.claim(token)

    assert links.held == 1


@pytest.mark.parametrize(
    "token",
    ["", "never-issued", "A" * 43, None, 42, ["a list"], {"a": "map"}, "x" * 10_000],
)
def test_anything_that_is_not_an_issued_token_is_refused(token: object) -> None:
    links = Invites(clock=Clock())
    links.issue()

    assert links.claim(token) is False
    assert links.held == 1


def test_a_token_expires_after_ten_minutes() -> None:
    clock = Clock()
    links = Invites(clock=clock)
    early, late = links.issue(), links.issue()

    clock.now += onboarding.INVITE_TTL_S - 0.001
    assert links.claim(early) is True

    clock.now += 0.001
    assert links.claim(late) is False


def test_the_lifetime_is_ten_minutes() -> None:
    assert onboarding.INVITE_TTL_S == 600.0


def test_expired_records_are_removed_by_the_next_issue() -> None:
    clock = Clock()
    links = Invites(clock=clock)
    links.issue()
    links.issue()
    clock.now += onboarding.INVITE_TTL_S

    # Nothing has asked yet, so nothing has been pruned: the count is
    # what is held, not what is live.
    assert links.held == 2
    links.issue()

    assert links.held == 1


def test_expired_records_are_removed_by_the_next_claim() -> None:
    clock = Clock()
    links = Invites(clock=clock)
    links.issue()
    links.issue()
    clock.now += onboarding.INVITE_TTL_S

    assert links.claim("never-issued") is False

    assert links.held == 0


def test_a_mint_past_the_capacity_is_refused_and_holds_nothing_more(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(onboarding, "INVITE_CAPACITY", 3)
    draw = counting()
    links = Invites(clock=Clock(), randomness=draw)
    for _ in range(3):
        links.issue()

    with pytest.raises(InviteRefusedError) as refused:
        links.issue()

    assert str(refused.value) == CAPACITY_REACHED
    assert links.held == 3
    # Refused before drawing: a refusal mints nothing.
    assert draw.asked == [32, 32, 32]  # type: ignore[attr-defined]


def test_expiry_frees_capacity(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(onboarding, "INVITE_CAPACITY", 2)
    clock = Clock()
    links = Invites(clock=clock)
    links.issue()
    links.issue()
    clock.now += onboarding.INVITE_TTL_S

    links.issue()

    assert links.held == 1


def test_a_claim_frees_capacity(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(onboarding, "INVITE_CAPACITY", 1)
    links = Invites(clock=Clock())
    links.claim(links.issue())

    links.issue()

    assert links.held == 1


def test_a_new_store_knows_no_token_of_an_old_one() -> None:
    """A restart is a new store: every unredeemed link of the old
    process meets the same answer an unknown token does (D5e)."""
    before = Invites(clock=Clock())
    token = before.issue()

    after = Invites(clock=Clock())

    assert after.claim(token) is False


def test_the_default_randomness_is_the_operating_systems(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Read at the call, so the default is the one thing a test can pin
    it to: `secrets`, never a seeded generator."""
    draw = counting()
    monkeypatch.setattr(secrets, "token_bytes", draw)

    Invites().issue()

    assert draw.asked == [32]  # type: ignore[attr-defined]


def test_the_default_clock_is_monotonic(monkeypatch: pytest.MonkeyPatch) -> None:
    """Monotonic rather than wall time: nothing about a link is
    published as an instant, and a wall clock stepped back would
    lengthen every live link's life."""
    clock = Clock()
    monkeypatch.setattr(time, "monotonic", clock)
    links = Invites()
    token = links.issue()

    clock.now += onboarding.INVITE_TTL_S

    assert links.claim(token) is False


def test_two_default_tokens_differ() -> None:
    links = Invites()

    assert links.issue() != links.issue()
