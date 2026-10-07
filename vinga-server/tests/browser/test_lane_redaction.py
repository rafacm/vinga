"""What the lane prints is held to the rule the client is: no credential
value in any output (#613, PR #626's review).

The lane's diagnostics carry the server's log, the page's console and
the websocket record, and those are exactly where a leak the lane exists
to catch would sit, so they pass through `lane.redact` before anything
is printed. These cases pin the redactor itself: a value the lane
registered, and the two token shapes this server issues, whether or not
the lane ever saw them, are gone; ordinary identifiers stay readable.
"""

import secrets

from lane import REDACTED, Redactor

# What an invite token is: 32 random bytes, urlsafe base64, unpadded.
INVITE_TOKEN = secrets.token_urlsafe(32)

# What a device token is: a 43-character urlsafe signature, a dot, and
# the second it was issued.
DEVICE_TOKEN = f"{secrets.token_urlsafe(32)}.1791273600"


def test_a_registered_value_is_redacted_wherever_it_appears() -> None:
    redact = Redactor()
    redact.register("not-shaped-like-any-token")

    said = redact("before not-shaped-like-any-token after")

    assert "not-shaped-like-any-token" not in said
    assert said == f"before {REDACTED} after"


def test_both_token_shapes_are_redacted_unregistered() -> None:
    redact = Redactor()
    text = (
        f'{{"page": "/talk/#{INVITE_TOKEN}"}} '
        f"Authorization: Bearer {DEVICE_TOKEN} "
        f"offered vinga.token.{DEVICE_TOKEN}"
    )

    said = redact(text)

    assert INVITE_TOKEN not in said
    assert DEVICE_TOKEN not in said
    assert DEVICE_TOKEN.split(".")[0] not in said


def test_ordinary_identifiers_stay_readable() -> None:
    redact = Redactor()
    text = (
        "session 5d17d9f008534174b822eb3db5d110fe device 02:41:9c:7d:3e:58 "
        "client 3d9e1f5a-6b2c-5d8e-9f1a-0c4b6d8e2f7a "
        "digest 6edd0d5cb85ac5f983eb9275dad577ac01ed7e396fe2b6a43f42b66e44a50d77"
    )

    assert redact(text) == text
