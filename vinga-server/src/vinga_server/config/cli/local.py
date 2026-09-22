"""The commands that reach no API.

Five commands that are not acts of the configuration API at all: one is
about onboarding a board, which happens before there is anything to
configure; three render the models and the API's own routes without
opening a database, reaching a server or needing a key; and one reads
the store the way a boot reads it, which needs the database and the
keys and needs no server at all.

What its callers stop knowing: which half of the distribution a command
needs installed, and what a missing one says. The gate is one function
here, and the sentence is its parameter rather than its own constant,
because the two halves send a reader to two different places: one is a
thing you go somewhere that has, the other is a thing you install.
"""

import sys
from collections.abc import Callable

from vinga_server.config import docgen, server_reference
from vinga_server.config.loader import (
    NEEDS_THE_SERVER_HALF,
    ConfigError,
    load_file_config,
)
from vinga_server.config.models import ServerConfig

from .invocation import Invocation
from .reach import PROGRAM

# What to do with the URL `ota-url` prints, said beside it on stderr so
# that stdout holds the URL and nothing else.
OTA_URL_GUIDANCE = (
    "Type this into the device's captive portal, under its advanced settings, as the "
    "server address. If the board then shows a six-digit activation code, it has no "
    "agent yet: bind "
    f"it with {PROGRAM} device pending claim <code> <agent>. A deployment with "
    "default_agent set covers every board already, so its boards show no code and start "
    "talking as soon as they connect."
)

# What this command does about onboarding being off. The sentence it
# goes into is `origin.ONBOARDING_OFF`, which is the derivation's own,
# and the fix is the asking command's.
ONBOARDING_OFF_FOR_URL = "Turn onboarding on for a URL short enough to type."



def _from_an_installed_half[T](answered: Callable[[], T], missing: str) -> T:
    """One command's answer, or the given sentence when the half it needs
    is not installed.

    The gate for every command in this grammar that reaches a module the
    default install does not carry. There are four: `ota-url`, `openapi`
    and `check` read the server half, and `simulator run` reads the
    websocket client behind the `sim` extra. Everything else is either a
    request, which needs no such module, or a render off the models,
    which are the client half.

    The SENTENCE is a parameter rather than this function's own constant,
    because the two halves send a reader to two different places: one is
    a thing you go somewhere that has, the other is a thing you install.
    A second copy of this function with its own constant would have been
    a second chance to get the ImportError containment wrong, on the one
    surface where getting it wrong relays a module path.

    Recorded inside the handler and raised outside it, the way every
    boundary in this module raises. An ImportError's text is the module
    path it could not find, and an exception raised while one is being
    handled carries it as `__context__` for anything walking the chain;
    raising after the handler leaves neither a cause nor a context.

    Only ImportError is caught, and only around the call: a
    `ConfigError` out of the answer itself is this grammar's own refusal
    and travels as one.
    """
    answers: list[T] = []
    try:
        answers.append(answered())
    except ImportError:
        pass
    if not answers:
        raise ConfigError(missing)
    return answers[0]


def _derived_ota_url(config: ServerConfig) -> tuple[str, object]:
    """The onboarding derivation, imported where it is used.

    Not at the top of this module, and it is the one import here that is
    deferred for weight rather than for a cycle. `onboarding/origin.py`
    imports `.keys`, which imports FastAPI, and naming either submodule
    runs the package's own `__init__`, which imports the aggregate; so
    the derivation is the server half however little of it this command
    wants. Extracting a FastAPI-free half of that package is a second
    responsibility and #287's, and until then this command is gated
    rather than thinned (the plan's decision 9 records why).
    """
    from vinga_server.onboarding.origin import onboarding_url

    return onboarding_url(config, ONBOARDING_OFF_FOR_URL)


def _ota_url(args: Invocation) -> None:
    """The URL to type into a board's captive portal.

    The one command here that talks to nothing: no server, no database,
    no encryption key and no API token, because none of them holds any
    part of the answer. It reads the file half the way every other
    command reads it, takes the device-auth secret from the environment
    the server takes it from, and derives the key and the origin with
    the functions the server itself calls, so what it prints is what
    that server answers on rather than a second opinion about it.

    It does need those functions to be installed, which is what makes it
    one of the three gated commands: it is a server-host command by
    nature, since the file half it reads is the one a laptop does not
    have. The laptop-side question it is confused with, whether that URL
    answers, is `vinga-server doctor`'s since #244.

    The URL goes to stdout alone, so it can be captured; what to do with
    it, and where its origin came from, go to stderr the way every
    other notice does.
    """
    config = _server_config(args)
    url, origin = _from_an_installed_half(
        lambda: _derived_ota_url(config), NEEDS_THE_SERVER_HALF
    )
    print(url)
    sys.stdout.flush()
    print(OTA_URL_GUIDANCE, file=sys.stderr)
    print(f"The URL above is {origin.provenance}.", file=sys.stderr)


# What a store that composes is answered with, on stderr, because it is
# a fact about this run rather than an artifact: `check` produces no
# document, and its refusal goes to stderr as every refusal of this
# grammar does, so its two answers leave by the same door and the exit
# code is what a script reads.
#
# It says what was not tried as well as what was, because the boot it
# stands in for goes further than this: `load_boot_config` stops at the
# composed snapshot, and building the providers and connecting the MCP
# servers happen after it, inside a server that is starting.
COMPOSES = (
    "the stored configuration composes, which is as far as a boot gets before it "
    "builds anything: what a provider or an MCP server does when it is started is a "
    "running server's answer."
)

CHECK_HELP = (
    "say whether the stored configuration composes into one a server could boot on, "
    "naming the entry and the rule behind anything that does not; it reads the store "
    "the way a boot reads it and serves nothing"
)


def _boot_read(path: str | None) -> None:
    """The boot's own read of both halves, imported where it is used.

    Deferred for weight rather than for a cycle, the way
    `_derived_ota_url` is: `config/boot.py` opens the database and
    migrates it, so naming it pulls in SQLAlchemy and the migration
    chain, which the configuration client does not have. The import is
    inside this function so that the gate around it is what a client-only
    install meets, rather than an ImportError at module scope on every
    command of the grammar.

    What comes back is discarded on purpose. The answer this command
    gives is whether the read refused, and the composed configuration
    itself is a snapshot of the whole domain half: nothing may print it,
    and holding it would be the one way something could.
    """
    from vinga_server.config.boot import load_boot_config

    load_boot_config(path)


def _check(args: Invocation) -> None:
    """Whether a server would get past reading this store, and what it
    would refuse on.

    The command #443 asked for, and the reason it is this shape. An
    `apply` that the stored configuration will not satisfy is refused
    with a sentence that names no location, deliberately: what a reload
    refuses on is arbitrary stored state, and a sentence composed over
    it can quote a value that was written into the wrong field. A boot
    refuses on the same state and names the location and the rule
    without the value, because it is composing the snapshot rather than
    answering a request about it. Before this command the only way to
    read that sentence was to start a second server against the same
    store and watch it fail.

    So this runs the boot's own read and prints what it says. Not a
    second composition and not a second formatter: `load_boot_config` is
    the function `vinga_server.serving.run` calls, its `ConfigError` is
    the sentence that server would print, and the boundary in `main`
    prints it and exits 1 exactly as `run` does. A rule that changed on
    one side could not change on the other, because there is one side.

    What it does NOT do is serve: no application is built, no provider
    is constructed, no MCP server is connected and no port is opened. It
    reads the file half, opens and migrates the database, loads the
    snapshot, verifies every stored secret and composes the two halves,
    which are the five steps `config/boot.py` documents, and then stops.

    So it is not read-only, and saying "it only reads" would be the one
    false sentence available here. It writes no domain configuration,
    which is what an operator is asking about; the migration is part of
    the read rather than an extra this command performs, because what a
    boot would meet is the answer being asked for and a check that read
    an unmigrated store would be answering about a store no server will
    ever see. On a deployment mid-upgrade, running this is the same act
    as starting the new image, and the reference says so.

    No value reaches either stream on either path. The success line is
    fixed, and the refusal is whatever the boot composed, which is the
    same sentence a server prints in front of an operator's terminal.
    """
    _from_an_installed_half(lambda: _boot_read(args.config), NEEDS_THE_SERVER_HALF)
    print(COMPOSES, file=sys.stderr)


def _schema(args: Invocation) -> None:
    """The JSON Schema of one entity kind, of one provider type's
    options when a stage and a type follow `provider`, or of the whole
    domain configuration. Reads the models and the registry and nothing
    else: no database, no configuration file, no encryption key, no
    server."""
    print(docgen.schema(args.entity, args.stage, args.type_name), end="")


def _reference(args: Invocation) -> None:
    """One half's markdown reference, the same documents CI diffs the
    committed copies against.

    Dispatched through the halves registry rather than branched on here,
    so the accepted names, the positional's help and the refusal for a
    name that is neither all read one tuple. Reads the models and nothing
    else, whichever half is asked for: no database, no configuration
    file, no encryption key, no server.
    """
    print(server_reference.render(args.half), end="")


def _openapi(args: Invocation) -> None:
    """The configuration API's OpenAPI document, the other artifact CI
    diffs its committed copy against. Rendered from the routes, so it
    opens no database and needs no token: the application is built, its
    document is taken, and nothing of it is served.

    The routes are the server half, so this is the second of the three
    gated commands. What it renders is committed at
    `docs/reference/api-openapi.json`, which is where a client-only
    installation reads the contract instead."""
    print(_from_an_installed_half(docgen.openapi, NEEDS_THE_SERVER_HALF), end="")


# What `ota-url` reads the deployment out of, and its only caller.
#
# The derivation itself lives in `onboarding.origin`, beside the origin
# resolution it composes, so that this and `vinga-server doctor` cannot
# come to disagree about what a person is supposed to type. What is
# here is the read in front of it.


def _server_config(args: Invocation) -> ServerConfig:
    """The file half's `server` section, read the way every command
    reads it. No database is opened and no config file has to exist:
    without one the field defaults and the VINGA_ environment are the
    whole answer."""
    return load_file_config(args.config).server
