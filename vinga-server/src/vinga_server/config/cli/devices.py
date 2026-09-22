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
renderer the commanded kinds use.
"""

from collections.abc import Mapping

from vinga_server.config.responses import (
    Acknowledgement,
    DeviceBinding,
    DeviceLocation,
    DeviceRename,
    DeviceReplacement,
    Envelope,
    PendingDevice,
)

from .acts import UNREADABLE_WRITE, Act, _path, _printed
from .entities import _print_entity
from .invocation import Invocation
from .output import _acknowledged, _columns, _short

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
# instead of by a MAC nobody has had to find.
ADD_DEVICE = Act(
    method="POST",
    path=_claim_path,
    body=_binding,
    sends=DeviceBinding,
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

PENDING = Act(
    method="GET",
    path=_waiting_path,
    answers=dict[str, PendingDevice],
    render=_printed(_pending_listing),
)
