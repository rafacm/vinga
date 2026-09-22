"""The simulated board.

The one command here that stands where a device stands rather than
where an operator does. Everything it knows about the exchange is
`simulator.board`, and everything it knows about talking to a
device-facing address is `device_endpoint`; what is here is the
grammar's half, which is what is printed and which of the states is a
failure.

What its callers stop knowing: that two credentials stay apart, and
where the seam between them is. Without `--claim` no API token is read
and no API request is made, so the device side never touches the
operator-side credential; with it, the claim is the same act `device
pending claim` performs, so there is no second encoding of the claim
and no new row in the contract check's covered set.
"""

import sys
from dataclasses import replace

from vinga_server import device_endpoint
from vinga_server.config.loader import NEEDS_THE_SIM_EXTRA, ConfigError
from vinga_server.simulator import board, utterance

from .acts import _act
from .devices import ADD_DEVICE
from .invocation import Invocation
from .local import _from_an_installed_half
from .reach import PROGRAM, _reached

# Where the URL comes from, said on the help page, because there is
# deliberately no derivation behind it. The resolution order the guide
# asks for would end at `onboarding.origin`, which is the import that
# gates `ota-url` on the server half, and inheriting that gate would make
# this command refuse on the very install it exists for.
ENDPOINT_HELP = (
    f"the OTA URL to check in to: the address `{PROGRAM} ota-url` prints inside the "
    f"image, or the one already written into a board's NVS"
)

MAC_HELP = (
    f"the address this simulated board presents (default: {board.DEFAULT_MAC}, whose "
    f"leading octet is the locally-administered bit; a second board is "
    f"02:00:00:00:00:02)"
)

CLAIM_HELP = (
    "bind this board to an agent through the configuration API and check in again to be "
    "admitted; repeat the option for several agents (default: print the code and the "
    "command to run)"
)

# What is printed on stderr beside an activation code, which is the same
# advice `ota-url` gives beside its URL: what to do next is a notice, and
# stdout holds what the board was handed.
CLAIM_GUIDANCE = (
    f"This board is showing an activation code, the way a screen would. Bind it with "
    f"`{PROGRAM} device pending claim <code> <agent>`, or run this command again with "
    f"--claim <agent> to do both."
)

# What a claim needs and did not get. `--claim` is addressed by the six
# digits a board is showing, so a board that was not offered a code has
# nothing for the claim to address.
NOTHING_TO_CLAIM = (
    "--claim binds the board showing an activation code, and this check-in was not "
    "offered one. A board that is already bound needs no claim, and a board this "
    "deployment will not admit is not one a claim can help: run without --claim to see "
    "which of the two it is."
)

# And what a ceremony that ran its course without being admitted says.
# The claim went through, so this is the server not yet serving what the
# binding names.
NOT_ADMITTED_YET = (
    f"this board was claimed, and the activation poll was still answering keep-waiting "
    f"when the bound expired. A binding to an agent this server is not serving yet flips "
    f"at the apply that installs it: run `{PROGRAM} apply`, and then this command "
    f"again."
)

# What the reply's firmware block said, as this side read it. Three
# sentences over two booleans, and no far-side value in any of them: a
# real board's use of that block is a decision rather than a display, so
# the decision is what crosses and the version and the URL stay where
# every other far-side string in this command stays.
FIRMWARE_OFFERED = (
    "firmware: an image was offered, and nothing here fetches one: a simulated board "
    "has no partitions to write it to. Neither the version nor the address it named is "
    "repeated."
)

FIRMWARE_UP_TO_DATE = (
    "firmware: no image was offered, and the version named back is the one this board "
    "announced, which is how a deployment with nothing to offer says so."
)

FIRMWARE_UNEXPECTED_VERSION = (
    "firmware: no image was offered, and the version named back is not the one this "
    "board announced. A board reads that as up to date too, since there is nothing to "
    "fetch; the version is not repeated, being whatever that endpoint returned."
)

# What an admitted board was handed, in the two readings admission has.
#
# The state carries an empty token exactly where the reply said this
# deployment issues none (#369), so the emptiness of that one field is
# what tells the two apart, and it is read here rather than by asking the
# reply a second question. The value is never printed either way.
TOKEN_ISSUED = "device token: issued, and its value is never printed"

NO_TOKEN_ISSUED = (
    "device token: none, and none is needed: that deployment issues no device tokens, "
    "which is what turning device authentication off means on the wire"
)

# What a board that was handed neither a token nor a code is told.
#
# Enumerated from the decision sites that produce such a reply rather
# than from the sentence this replaced: `ota/reply.py` withholds the
# token whenever nothing this deployment serves resolves the board, and
# `onboarding/unbound.py` withholds the code for four separate reasons,
# one of which is that the deployment could not read its own record of
# what is bound and would not mint a claim ticket off a stale answer.
#
# The last reading is not a configuration at all. A server new enough to
# say why a token is empty never reaches this sentence for a board it
# admits (#369); one built before it answers an admitted board on a
# deployment that issues no tokens with exactly these bytes.
MAY_NOT_SPEAK = (
    f"It was issued no token and offered no activation code, which is what five "
    f"readings look like from here: onboarding is turned off on that deployment and "
    f"nothing resolves this MAC; or this MAC, or that deployment's default_agent, names "
    f"an agent it is not serving yet, which `{PROGRAM} apply` installs; or the table of "
    f"boards waiting to be claimed would not take another one; or that deployment could "
    f"not read its own record of what is bound, so it offered no code rather than one "
    f"for a board somebody has already claimed; or it issues no device tokens at all and "
    f"is too old to say so, which a newer one says outright."
)

NOT_ADMITTED_AFTER_CLAIM = (
    f"this board was claimed and the activation poll said it was activated, and the "
    f"check-in after it admitted nothing: no token, and no word saying none was needed. "
    f"Nothing here can go on from that: read what the deployment says about the MAC with "
    f"`{PROGRAM} device show <mac>`. One reading is not about the binding at all: a "
    f"deployment that issues no device tokens and is too old to say so answers a "
    f"just-claimed board in exactly these bytes."
)


def _simulator_check_in(args: Invocation) -> None:
    """Check in to an OTA URL as a board would, and say what it was told.

    Three of the four states are a command that worked, because a
    simulated board reporting the state it is in is the answer, and only
    a reply this client will not read as one is a failure.
    """
    endpoint = device_endpoint.Endpoint.parsed(
        args.endpoint, board.GIVEN_URL, device_endpoint.SUPPLIED_ENDPOINT
    )
    identity = board.Identity.of(args.mac)
    state = board.check_in(endpoint, identity)
    if args.agents:
        state = _claimed(args, endpoint, identity, state)
    _reported(state, endpoint)


def _claimed(
    args: Invocation,
    endpoint: "device_endpoint.Endpoint",
    identity: board.Identity,
    state: board.CheckIn,
) -> board.CheckIn:
    """The four-step ceremony a real board and an operator perform
    between them.

    Check in and read a code; claim it through the act the grammar
    already has; poll where a waiting board polls; and check in AGAIN.
    The fourth step is the one that makes the other three worth anything:
    a board showing a code is not admitted, and the poll route answers a
    status rather than a configuration, so the only thing that admits
    this board is a check-in reply. A socket opened on what step one
    handed back would be presenting the empty token an activating reply
    carries and would be refused at the handshake with no_token, which is
    the confusion `docs/xiaozhi-notes.md` warns about from the other
    side.

    The same MAC and the same client id cross all four requests, because
    the token is signed for the two of them together.
    """
    if not isinstance(state, board.Activating):
        if isinstance(state, board.Refused):
            return state
        raise ConfigError(NOTHING_TO_CLAIM)
    # The one request this command makes, and the one place it resolves
    # the operator-side credential: inside the `--claim` arm, which is
    # what keeps the device side clear of it.
    _act(replace(args, code=state.code), ADD_DEVICE, _reached(args))
    waited = board.polled(endpoint, identity, state.timeout_ms)
    if isinstance(waited, board.Refused):
        return waited
    if isinstance(waited, board.StillWaiting):
        raise ConfigError(NOT_ADMITTED_YET)
    admitted = board.check_in(endpoint, identity)
    if isinstance(admitted, board.Activating | board.Unwelcome):
        raise ConfigError(NOT_ADMITTED_AFTER_CLAIM)
    return admitted


# What `run` says beyond what `check-in` says.
#
# The conversation is what this verb exists for, so the transcript and
# the reply's sentences go to stdout as they arrive: they are far-side
# text, and they are the artifact the command exists to print. Everything
# else about the exchange is a count, a duration or a name this side
# chose.

RUN_HELP = (
    "check in to an OTA URL as a board would, then hold one conversation over the "
    "websocket: say the packaged sentence, and print the transcript and the reply as "
    "they arrive"
)

# What a board that may not speak is told when it was asked to speak.
# `check-in` reports those two states and exits 0, because reporting the
# state a board is in is the answer; `run` was asked for a conversation
# and cannot have one, so the same states are a refusal here.
CANNOT_CONVERSE = (
    "this board is not admitted, so there is no conversation to hold. Run "
    f"`{PROGRAM} simulator check-in` against the same address to see which state it is "
    f"in and what that state means. If it is showing an activation code, --claim <agent> "
    f"binds the board showing one; if it is not, a claim has nothing to address and the "
    f"check-in's own answer is where to start."
)


def _simulator_run(args: Invocation) -> None:
    """Check in as a board, then hold one turn of a conversation.

    Everything before the socket is `check-in`'s, exactly: the same
    endpoint, the same identity, the same four-step ceremony behind
    --claim. The token and the websocket address this opens with are the
    LAST check-in reply's, which is the only reply that admits anything.
    That token is empty where the deployment issues none, which is an
    admission the reply states and this half reads (#369) rather than a
    board that may not speak.

    Everything this command needs of its own INSTALLATION is settled
    before anything about the arguments, and both are settled before
    anything reaches the network. The extra is the first of those and the
    packaged utterance is the second: a board with nothing to say cannot
    hold a conversation whatever the address answers, and finding that
    out after a check-in, a claim and an activation poll would mean a
    command that could not speak had already rebound a device and spent
    a ceremony to say so.

    So the order is: what is installed, then what was typed, then what
    the network says.
    """
    held = _from_an_installed_half(_the_conversation_half, NEEDS_THE_SIM_EXTRA)
    said = utterance.packaged()
    endpoint = device_endpoint.Endpoint.parsed(
        args.endpoint, board.GIVEN_URL, device_endpoint.SUPPLIED_ENDPOINT
    )
    identity = board.Identity.of(args.mac)
    state = board.check_in(endpoint, identity)
    if args.agents:
        state = _claimed(args, endpoint, identity, state)
    if isinstance(state, board.Refused):
        raise ConfigError(state.problem)
    if not isinstance(state, board.Admitted):
        raise ConfigError(CANNOT_CONVERSE)
    print(
        f"{device_endpoint.SUPPLIED_ENDPOINT} admitted this board, and the conversation is "
        f"open on {device_endpoint.REPORTED_WEBSOCKET}, which is not printed.\n"
        f"protocol version: {state.protocol_version}\n"
        f"{_firmware(state.firmware)}\n"
        f"saying: {said.sentence}"
    )
    sys.stdout.flush()
    _conversed(held, state, identity, said)


def _the_conversation_half():
    """The websocket half of the simulator, imported here and nowhere
    else in this module.

    That is the whole of what makes `sim` an extra: `conversation.py`
    holds the only `websockets` import in the package, nothing imports it
    at module scope, and a bare install reaching this line gets an
    ImportError the gate turns into a sentence naming the extra.
    """
    from vinga_server.simulator import conversation

    return conversation


def _conversed(
    held, state: board.Admitted, identity: board.Identity, said: utterance.Utterance
) -> None:
    """One turn, and what is said about it afterwards.

    `held` is the module the gate handed back, passed in rather than
    imported here so that this function names no module the client half
    does not have. Its `Reply` is unannotated for the same reason, which
    is the gate's cost rather than an omission.
    """
    reply = held.converse(
        target=state.websocket,
        token=state.token,
        identity=identity,
        version=state.protocol_version,
        said=said,
        say=_as_it_arrives,
    )
    print(
        f"reply: {reply.packets} frames, {reply.audio_bytes} bytes, about "
        f"{reply.audio_ms} ms of audio, which is counted rather than decoded\n"
        f"the conversation reached: {reply.state}\n"
        f"close: {reply.closed}"
    )
    for surprise in reply.surprises:
        print(f"out of order: {surprise}", file=sys.stderr)


def _as_it_arrives(line: str) -> None:
    """One line of the conversation, as it happens rather than at the
    end. Flushed, because the whole point is watching it."""
    print(line)
    sys.stdout.flush()


def _reported(state: board.CheckIn, endpoint: "device_endpoint.Endpoint") -> None:
    """What the board was handed, on stdout, and what to do about it on
    stderr.

    Everything read out of the reply goes out through the endpoint's own
    door: the code, the message and the challenge are the artifact this
    command exists to show, and they are still whatever that address
    returned, so they are bounded, made printable, and stripped of any
    part of the supplied address they hand back. That last rule is why
    the endpoint is a parameter here rather than the state alone. A
    refusal quotes nothing, so these three fields are the only route a
    supplied URL has to a surface at all, and reflecting a request target
    into an answer is what a proxy, a captive portal and an error page
    each do by default.

    The device token and the websocket URL are not that artifact and are
    named by their stand-ins. The firmware block is neither: what is
    said about it is this side's own reading of it, per `_firmware`.
    """
    if isinstance(state, board.Refused):
        raise ConfigError(state.problem)
    if isinstance(state, board.Activating):
        print(
            f"{device_endpoint.SUPPLIED_ENDPOINT} answered, and this board is not "
            f"claimed yet.\n"
            f"activation code: {endpoint.repeated(state.code)}\n"
            f"what a screen would show: {endpoint.repeated(state.message)}\n"
            f"challenge: {endpoint.repeated(state.challenge)}\n"
            f"{_firmware(state.firmware)}"
        )
        sys.stdout.flush()
        print(CLAIM_GUIDANCE, file=sys.stderr)
        return
    if isinstance(state, board.Admitted):
        print(
            f"{device_endpoint.SUPPLIED_ENDPOINT} answered, and this board is admitted.\n"
            f"{TOKEN_ISSUED if state.token else NO_TOKEN_ISSUED}\n"
            f"websocket: {device_endpoint.REPORTED_WEBSOCKET}, which is not printed "
            f"either: it is what a token would be sent to\n"
            f"protocol version: {state.protocol_version}\n"
            f"{_firmware(state.firmware)}"
        )
        return
    print(
        f"{device_endpoint.SUPPLIED_ENDPOINT} answered, and this board may not speak.\n"
        f"{MAY_NOT_SPEAK}\n"
        f"{_firmware(state.firmware)}"
    )


def _firmware(read: board.Firmware) -> str:
    """What the reply said about an image, as this side read it.

    Three sentences over two booleans, and no far-side value in any of
    them. What a real board does with that block is decide rather than
    display, so the decision is what survives the crossing: an image was
    named or it was not, and the version named back is this board's own
    or it is not. A deployment with nothing to offer echoes the version
    it was told, which is how the firmware reads "up to date", and a
    version that comes back changed with no image behind it is the one
    combination worth saying out loud.
    """
    if read.offered:
        return FIRMWARE_OFFERED
    return FIRMWARE_UP_TO_DATE if read.announced else FIRMWARE_UNEXPECTED_VERSION
