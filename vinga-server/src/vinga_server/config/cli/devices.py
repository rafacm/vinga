"""The device noun: a board's record, its binding, and the boards waiting.

A binding and the two halves of the record beside it are domain-level
fields written with their own verbs (bind, claim, delete, rename,
replace, relocate) rather than from a fragment, so these rows are
written out rather than built from a kind's descriptor.

What its callers stop knowing: that a board is addressed two ways and
which one a verb takes. `device bind` addresses the MAC an operator
already has and `device pending claim` addresses the six digits on a
screen, and both send the same binding to the same store; everything
else about a device is the record, which is read through the entity
renderer the commanded kinds use. A browser is the third way a device
arrives, by `device invite`, which addresses nothing: it asks the
running server for a link that binds whichever browser opens it, and
which origin that link names is half this client's to decide.
"""

import sys
from collections.abc import Mapping
from urllib.parse import urlsplit

from vinga_server.config.loader import ConfigError
from vinga_server.config.printing import printable
from vinga_server.config.responses import (
    Acknowledgement,
    DeviceBinding,
    DeviceLocation,
    DeviceRename,
    DeviceReplacement,
    Envelope,
    Invite,
    InviteRequest,
    PendingClaim,
    PendingDevice,
)

from .acts import UNREADABLE_WRITE, Act, _path, _printed
from .entities import _print_entity
from .invocation import Invocation
from .output import UNBOUNDED, _acknowledged, _columns, _short
from .reach import Address, _loopback

# The pending listing's columns. Headings a person reads rather than
# field names: what the body has to carry to be read as a listing at all
# is `PendingDevice`, one import below this one.
PENDING_COLUMNS = ("code", "device", "board", "firmware", "expires")

NOTHING_PENDING = (
    "no device is waiting to be claimed. A board shows its code within a couple of "
    "minutes of being pointed at this server, and codes are forgotten when the server "
    "restarts, so a board that has been waiting a while shows a fresh one"
)


def _pending_listing(entries: Mapping[str, Mapping[str, str]]) -> str:
    """The devices waiting to be claimed, one line each.

    Columns rather than YAML, because the question this answers is
    which of several boards is the one being held, and the answer is
    read across a line: the code to type, the MAC it will bind, and the
    board and firmware that tell two boards apart.
    """
    if not entries:
        return f"{NOTHING_PENDING}\n"
    return _columns(
        [PENDING_COLUMNS]
        + [
            (code, entry["mac"], entry["board"], entry["firmware"], entry["expires_at"])
            for code, entry in entries.items()
        ]
    )


# What `device invite` says on stderr once the link is on stdout (#612,
# Q11): that it worked, and what the link does. Fixed, so it repeats no
# agent name the command was given, and it carries no token: the token
# is a credential, and stdout is the one place it is printed.
INVITED = (
    "invite issued: the link above opens this deployment in a browser once, within ten "
    "minutes, and binds that browser before its first word"
)

# And what the command fails with when neither end can name an origin a
# browser can open the page on: the server has no `https://` public URL
# configured, and this CLI reached the API somewhere other than this
# machine's loopback, so `localhost` would name the wrong machine. A
# link with a guessed origin would open nothing, or a page with no
# microphone, so there is none, and stdout stays empty: a caller holding
# `$(vinga device invite)` holds nothing rather than a sentence.
NO_LINK_ORIGIN = (
    "no link is printed, because this server names no origin a browser can open it on "
    "and this CLI did not reach it on this machine. Set server.public_url to the "
    "deployment's https:// origin, or run this command on the server's own machine."
)


def _situated_link(link: Mapping[str, object], address: Address) -> Mapping[str, object]:
    """An invite link with its origin named, where this client can name it.

    The server names its configured public origin when it has one a
    browser can use, and nothing otherwise; what it cannot know is the
    address this client reached it on. When that is this machine's
    loopback, the page is at `localhost` on the same port, which is a
    secure context for the browser on this machine. Anything else is
    left unnamed, and the renderer refuses (#613, D5c).

    The scheme and port are the API target's own, so a loopback TLS
    terminator stays `https`. `localhost` rather than the literal the
    target was typed with, because that is the name every browser
    treats as a secure context.
    """
    if link["origin"] is not None:
        return link
    parts = urlsplit(address.base)
    if parts.hostname is None or not _loopback(parts.hostname):
        return link
    port = parts.port
    authority = "localhost" if port is None else f"localhost:{port}"
    return {**link, "origin": f"{parts.scheme}://{authority}"}


def _invite_link(link: Mapping[str, object]) -> None:
    """The link alone on stdout, and that it worked on stderr; or, with
    no origin to name, the refusal and nothing on stdout.

    Made printable like every other value an answer carries; not
    bounded, because a truncated link is a wrong one. The token in it
    is a credential, and the operator's own stdout is the one place it
    is printed (#613, D7a). Flushed between the two halves, for the
    reason every two-stream renderer here flushes: stderr is unbuffered
    and stdout is not.
    """
    if link["origin"] is None:
        raise ConfigError(NO_LINK_ORIGIN)
    print(printable(f"{link['origin']}{link['page']}", UNBOUNDED))
    sys.stdout.flush()
    print(INVITED, file=sys.stderr)


def _device_summary(body: Mapping[str, object]) -> str:
    """One device as the tree shows it: what it is called, where it
    stands when it stands anywhere, and the agents it reaches.

    Beside the five kinds' summaries rather than in `_SUMMARY` with
    them, because a device is not an entity and its body is not a
    fragment: `_summarized` is asked by kind, and there is no kind here
    to ask by.

    The id is not on this line. It is what the record is FOR rather
    than something anybody reads off a tree, it is thirty-two
    indistinguishable hex digits, and `device show <mac>` prints it
    where whoever wants it can find it.

    Read one key at a time through the display door, like every other
    renderer here: what answered is an API body, and a name that is not
    a string is a value nothing has vouched for.
    """
    said = [_short(body.get("name"))]
    location = body.get("location")
    if location is not None:
        said.append(f"in {_short(location)}")
    bound = body.get("agents")
    reached = (
        ", ".join(_short(agent) for agent in bound)
        if isinstance(bound, list) and bound
        else "(nothing)"
    )
    return f"{', '.join(said)} -> {reached}"


# A device binding and the default agent are domain-level fields written
# with their own verbs (bind, claim, delete, set, clear) rather than from
# a fragment, so their rows are written here rather than built from a
# kind's descriptor.


def _device_path(args: Invocation) -> str:
    return _path("devices", args.mac)


def _invites_path(args: Invocation) -> str:
    return _path("runtime", "invites")


def _binding(args: Invocation) -> object:
    return {"agents": list(args.agents)}


def _device_rename_path(args: Invocation) -> str:
    return _path("devices", args.mac, "rename")


def _device_location_path(args: Invocation) -> str:
    return _path("devices", args.mac, "location")


def _device_replace_path(args: Invocation) -> str:
    return _path("devices", args.mac, "replace")


def _device_name(args: Invocation) -> object:
    """The name a rename is to give the device it addresses, sent as it
    was typed, for the reason `_new_name` is."""
    return {"to": args.to}


def _device_location(args: Invocation) -> object:
    return {"location": args.location}


def _device_replacement(args: Invocation) -> object:
    """The address the record is to answer at, sent as it was typed, for
    the reason `_device_name` is: the canonical spelling is the
    repository's to decide and it decides it once."""
    return {"to": args.to}


def _claim_path(args: Invocation) -> str:
    return _path("devices", "pending", args.code)


def _waiting_path(args: Invocation) -> str:
    return _path("devices", "pending")


DELETE_DEVICE = Act(
    method="DELETE",
    path=_device_path,
    answers=Acknowledgement,
    refusal=UNREADABLE_WRITE,
    render=_acknowledged,
)

SHOW_DEVICE = Act(
    method="GET",
    path=_device_path,
    answers=Envelope,
    render=_print_entity,
)

BIND_DEVICE = Act(
    method="PUT",
    path=_device_path,
    body=_binding,
    sends=DeviceBinding,
    answers=Acknowledgement,
    refusal=UNREADABLE_WRITE,
    render=_acknowledged,
)

# The same binding, addressed by the six digits on a board's screen
# instead of by a MAC nobody has had to find. The body is the binding's
# own shape, and an empty agent list is what `PendingClaim` reads as
# none named: the default agent.
ADD_DEVICE = Act(
    method="POST",
    path=_claim_path,
    body=_binding,
    sends=PendingClaim,
    answers=Acknowledgement,
    refusal=UNREADABLE_WRITE,
    render=_acknowledged,
)

# The two halves of the record beside the binding, each with its own
# verb: what an operator names, and where a conversation may say the
# board stands.
RENAME_DEVICE = Act(
    method="POST",
    path=_device_rename_path,
    body=_device_name,
    sends=DeviceRename,
    answers=Acknowledgement,
    refusal=UNREADABLE_WRITE,
    render=_acknowledged,
)

# The third act on the record, and the one about the hardware rather
# than about what the household calls it: the board underneath a device
# is replaced and the record stays.
REPLACE_DEVICE = Act(
    method="POST",
    path=_device_replace_path,
    body=_device_replacement,
    sends=DeviceReplacement,
    answers=Acknowledgement,
    refusal=UNREADABLE_WRITE,
    render=_acknowledged,
)

RELOCATE_DEVICE = Act(
    method="PUT",
    path=_device_location_path,
    body=_device_location,
    sends=DeviceLocation,
    answers=Acknowledgement,
    refusal=UNREADABLE_WRITE,
    render=_acknowledged,
)

CLEAR_DEVICE_LOCATION = Act(
    method="DELETE",
    path=_device_location_path,
    answers=Acknowledgement,
    refusal=UNREADABLE_WRITE,
    render=_acknowledged,
)

# An invite link, issued for whoever runs `device invite` (#612, Q11).
# An action of the running server rather than a write to the store:
# each run is a new single-use link, held in that server's memory, and
# the device it binds is written only when a browser opens it. The one
# act whose answer leaves part of itself to the client, which names a
# loopback origin when the server names none (#613, D5c).
INVITE = Act(
    method="POST",
    path=_invites_path,
    # The binding's own body, `{"agents": [...]}`: what the API reads as
    # the agents the browser is bound to, and with none named an empty
    # list, which it reads as the default agent. Always sent, since the
    # API requires a body.
    body=_binding,
    sends=InviteRequest,
    answers=Invite,
    render=_invite_link,
    completes=_situated_link,
)

PENDING = Act(
    method="GET",
    path=_waiting_path,
    answers=dict[str, PendingDevice],
    render=_printed(_pending_listing),
)
