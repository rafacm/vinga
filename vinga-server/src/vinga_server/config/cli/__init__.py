"""The `vinga-server config` command group: a client of the API.

The grammar is the one it has always had, one noun per entity kind, YAML
fragments as the write payload; what changed underneath is that a
command is now a request to the configuration API rather than a write
into the database. Nothing here decides anything about the
configuration: parsing, validation, reference checks, existence and
secret handling all live in the repository, which the API mounts, so a
refusal reads the same whichever way it was reached. The API carries the
repository's sentence in `detail` and this prints `detail`, unchanged.

Nothing plaintext is ever an argument: a secret arrives on stdin (not
echoed when the terminal is interactive) or from a named environment
variable, because arguments land in shell history and in the process
list. It then crosses the connection in a request body, which is why the
transport policy in `reach.py` is a refusal rather than a
recommendation: the bearer token rides on every request and grants
everything the API can do, so a plain http:// connection to anything but
a loopback address is not made at all.

There is no second way in. Every command that touches the domain
configuration is a request, so this package opens no database, loads no
encryption key and knows nothing about how a row is stored. A
deployment whose server will not start is recovered by booting one on
an empty database and importing a kept `export`, which is the procedure
`docs/reference/cli.md` writes out; surgical access to the rows
themselves is ordinary SQL and not this grammar's business.

One command stands outside all of this, because onboarding a board
happens before there is anything to configure. `ota-url` derives the
string a person types into a captive portal from the file half and the
environment, and contacts nothing whatsoever. It is one of the two
commands here that need the server half installed, `openapi` being the
other; both answer one fixed sentence when it is not. What answers on that URL
is a question for `vinga-server doctor`, which since #244 is a command
of its own: diagnosing an endpoint is not a configuration concern, and
what the two share is where the URL comes from, which is
`onboarding.origin`.

Every failure leaves as a ConfigError printed to stderr with exit code
1, naming the location and the kind of failure without quoting the value
that caused it, and no traceback from pydantic, PyYAML, SQLAlchemy,
cryptography or httpx reaches the user.

This module is the door and nothing else: it turns an argument vector
into an exit code and one sentence, whichever of the two entry points it
came in by, and it re-exports nothing. The modules under it own the
rest, in the order they may import one another: `invocation` is the
seam every one of them reads, then `answers`, `reach`, `input`,
`output` and `acts` are the shared execution infrastructure, then
`entities`, `devices`, `deployment`, `records`, `local`, `simulator`
and `events` are the command families, and `grammar` is the registry
that names them all.
"""

import sys
from collections.abc import Sequence

from typer._click.core import Exit

# Typer ships its own copy of Click rather than importing the installed
# one, so a usage error arrives as a class of that copy: `click.UsageError`
# would catch none of them, and a boundary that caught nothing would let
# Click's own sentences out as a traceback. The same goes for the context
# a help page is rendered through, which has to be that copy's, and which
# `grammar.py` imports for that reason. Imported from where they actually
# are, named one by one rather than felt for through an ancestor, so a
# Typer release that moves them fails loudly at import instead of quietly
# widening what reaches an operator. That tripwire fired once: typer
# 0.27.2 moved Exit out of the vendored exceptions module, so Exit is
# imported from the core module beside Context, where both 0.27.1 and
# 0.27.2 define it as the same class typer exports publicly as typer.Exit.
from typer._click.exceptions import (
    BadArgumentUsage,
    BadOptionUsage,
    BadParameter,
    ClickException,
    MissingParameter,
    NoArgsIsHelpError,
    NoSuchOption,
)

from vinga_server.broken_pipe import reader_stopped_reading
from vinga_server.config.loader import ConfigError

from .grammar import _print_version, command
from .input import MISSING_ARGUMENT, usage_line

# And the two entry points this grammar has, as the fixed string each of
# them prints in a live help page or usage line. A closed map from a
# known entry point to a written-down name: `argv[0]` is never read and
# never interpolated, so a hostile one has no surface here at all.
#
# `main` is reached one of two ways. The console script calls it with no
# arguments, which is the short spelling; `vinga-server config` hands it
# `sys.argv[2:]`, which is the spelling inside the image. Anything that
# calls it some third way gets the canonical constant.
CONSOLE_SCRIPT = "vinga"

DISPATCHED = "vinga-server config"


def main(argv: Sequence[str] | None = None) -> int:
    """Run one config command. Returns the process exit code.

    Parsing is inside the boundary, so a mistake in the grammar answers
    the way a mistake in a fragment does: a sentence on stderr and exit
    1. --help still leaves through an exit 0 of its own, because asking
    for help is not a failure.

    An absent `argv` is the console script, which is the whole of what
    tells the two entry points apart here: `vinga-server` hands this
    `sys.argv[2:]` and the script hands it nothing. What that decides is
    one string in a help page, and nothing else.

    The `.env` file is read for this group rather than only in
    `vinga-server.main`, because both spellings have to behave
    identically and the console script never reaches that function. It
    is read where a command is about to run (`_Verbatim.invoke`) rather
    than in front of the parse, so that an invocation which runs no
    command needs no readable environment: a bare `vinga` gets its help
    page whatever the `.env` in the working directory is, which is the
    one moment a reader is least able to act on a sentence about a file
    they may not have written. Every command still runs with the
    environment loaded, because nothing here reads it earlier.

    It is read INSIDE the boundary, which is the whole of why the read
    is a function of the loader's rather than two library calls: a
    `.env` that will not open or will not decode is a failure on a path
    nobody validated, holding the variables an API token and the
    provider credentials come from, and outside the boundary it would
    leave as a traceback with those bytes on the exception. The read has
    moved down the call stack and not out of the boundary: it is still
    inside this `try`, one frame further in.

    And one invocation is answered in front of the parse as well as the
    read, because it has to be answerable when nothing else is: see
    `_version_asked`.
    """
    if _version_asked(sys.argv[1:] if argv is None else argv):
        _print_version()
        raise SystemExit(0)
    try:
        _parsed(
            sys.argv[1:] if argv is None else argv,
            CONSOLE_SCRIPT if argv is None else DISPATCHED,
        )
        # The buffer is emptied inside the boundary, for the reason
        # `events_cli.main` states at the same line: a reader who closed
        # the pipe while the last partial chunk was still buffered
        # raises at interpreter shutdown otherwise, where no arm can
        # catch it, and the process prints `Exception ignored` and exits
        # 120 rather than answering the status below.
        sys.stdout.flush()
    except BrokenPipeError:
        # A reader that stopped reading, which is not a failure and is
        # not this grammar's sentence either: `broken_pipe.py` says what
        # the status is and why stdout has to be redirected before this
        # returns. Here for `events tail | head -n 1`, which is how a
        # script waits for one event, and it is caught for every command
        # because `export | head` is the same shape and had the same
        # traceback waiting in it.
        return reader_stopped_reading()
    except ConfigError as exc:
        print(exc, file=sys.stderr)
        return 1
    return 0


def _parsed(argv: Sequence[str], spelled: str) -> None:
    """The command line, parsed and run.

    Click is driven directly rather than through its standalone mode,
    which prints a usage error itself and exits 2: this group's contract
    is one sentence on stderr and exit 1, and a failure that bypassed it
    would bypass the sanitizing with it. `--help` is the one invocation
    that is not a failure, and it leaves through the exit code Click
    asked for, which is 0.

    Both answers are recorded inside their handler and raised after it,
    the way every other boundary in this module raises. A Click
    exception holds the context it was raised from and that context
    holds the argument list, so an exception raised while one is being
    handled would carry the whole command line as its `__context__` for
    anything walking the chain to find, which for this CLI is where a
    secret typed as an argument would be.

    That applies to `--help` as much as to a refusal, which is why the
    exit code is carried out of the arm rather than raised in it.
    `raise ... from None` sets `__suppress_context__`, which stops a
    traceback being printed and stops nothing else: the Typer exception
    is still on `__context__`, and this module's whole no-leak
    discipline is about what a chain walker finds rather than about what
    is displayed.

    One invocation is answered with a page rather than a sentence, and
    it leaves through the same door as every other: an invocation that
    named no command at all, told apart BY CLASS. `NoArgsIsHelpError` is
    raised by `_Grouped` below and by nothing else in this grammar, and
    it carries the group that was left without a verb, so its page is
    the page the reader stopped at rather than the root's.

    By class rather than by wording, and that distinction is the whole
    of this arm. Every other shape here is a sentence of Click's about
    something that was typed, so a reading that matched on words would
    be a reading a caller could satisfy: `vinga "Missing command"` is an
    unknown command whose name is the marker, and it gets the refusal
    every other unknown command gets.
    """
    problem: str | None = None
    asked_for: int | None = None
    try:
        grammar = command()
        with grammar.make_context(spelled, list(argv)) as context:
            grammar.invoke(context)
        return
    except Exit as asked:
        asked_for = asked.exit_code
    except NoArgsIsHelpError as bare:
        problem = bare.ctx.get_help()
    except ClickException as exc:
        problem = _usage_problem(exc)
    if asked_for is not None:
        raise SystemExit(asked_for)
    raise ConfigError(problem)


# What a mistake in the grammar says
#
# Click's own sentences quote what was typed: an unknown option comes
# with a did-you-mean built from it, a bad value is repeated back, an
# unknown command names the word. A secret is never an argument of this
# CLI, and the mistake that would make one (typing the value after
# `provider secret set ... api_key`) lands in exactly those sentences, so none of
# them is passed through. Each shape gets a fixed sentence of this
# grammar's own, and a shape not recognized gets the vague one, because
# a message this code has not seen is a message that may carry a value.
#
# Two tables, because Click states its usage errors two ways. The
# subclasses are chosen BY CLASS, which is the reading that cannot be
# fooled by wording; the base `UsageError` is one class for three
# different mistakes, so those are told apart by Click's own fixed
# words, which are the part of the sentence carrying no value.
#
# The sentence one of them answers with, `MISSING_ARGUMENT`, is
# `input.py`'s: this grammar raises it for itself as well as
# translating it, from the one mistake Click cannot see, so it is
# defined beside that raise rather than here.

# Ordered, first match wins, and a subclass comes before the class it
# extends: `MissingParameter` is a `BadParameter`, and an argument that
# is absent is not an argument that is wrong.
_USAGE_PROBLEMS: tuple[tuple[type[BaseException], str], ...] = (
    (NoSuchOption, "that is not an option of this command"),
    (MissingParameter, MISSING_ARGUMENT),
    (BadOptionUsage, "an option was given without its value"),
    (BadArgumentUsage, "an argument was given in a shape this command does not take"),
    (BadParameter, "an argument was given a value this command does not take"),
)

# The mistake whose sentence has to say more than what went wrong,
# because the value it would have echoed is the one thing this CLI is
# built never to see: typing the secret after the slot is where an
# operator meets this, and where Click would have quoted it back.
SECRET_NEVER_AN_ARGUMENT = (
    "unrecognized extra arguments. A secret is never given as an argument: a secret "
    "set reads it from stdin, or from the variable named with --from-env"
)

_USAGE_SHAPES: tuple[tuple[str, str], ...] = (
    ("Got unexpected extra argument", SECRET_NEVER_AN_ARGUMENT),
    ("No such command", "that is not a command"),
    # The third has no route through this grammar any more: `_Grouped`
    # decides that case before Click can state it, and answers it with a
    # page. The sentence stays because the marker is still Click's
    # wording for a real mistake, and a Typer release that reached it by
    # some path this module has not seen should meet the sentence for it
    # rather than the vague fallback. It is unreachable, not wrong, and
    # the boundary suite drives it directly.
    ("Missing command", "a command is missing"),
)

# What an unrecognized shape gets. Deliberately vague about the mistake
# rather than specific with Click's words in it.
_USAGE_UNKNOWN = "the command line could not be parsed"


def _usage_problem(exc: ClickException) -> str:
    """One usage mistake, in this grammar's words.

    Never in Click's: the message is read only to tell three shapes of
    one class apart, on markers that are Click's fixed words, and what
    it goes on to quote is exactly what the fixed sentences replace.
    """
    for shape, sentence in _USAGE_PROBLEMS:
        if isinstance(exc, shape):
            return usage_line(sentence)
    stated = exc.format_message()
    for marker, sentence in _USAGE_SHAPES:
        if marker in stated:
            return usage_line(sentence)
    return usage_line(_USAGE_UNKNOWN)


# What is answered before the environment is read
#
# `--version` has to succeed whatever else is wrong, and that is the
# whole of its contract: it is the question an operator asks when they
# are already comparing two halves of a deployment that disagree, which
# is exactly when the rest of a machine is not in a state to be relied
# on. A `.env` that will not decode is one such state, and reading it
# first made the one command that must always answer exit 1 with a
# sentence about a file it was never asked about.
#
# So the root position is recognized without a parser, and recognizing
# it is possible because the root's options are a closed set: everything
# before the first command word is either `--version`, one of the root
# flags, or one of the root options and its value. The sets are read off
# the built tree rather than listed, so an option added to the root
# joins them by being declared, and anything this does not recognize
# ends the scan and goes to the parser, which is the answer that was
# always there.
#
# `--config path --version` therefore answers, and `--config --version`
# does not, because there the word is the option's value and not the
# root's. That distinction is the reason this reads the parameters
# rather than searching the list for a string.


def _root_options() -> tuple[frozenset[str], frozenset[str]]:
    """The root's flags and its value-taking options, by every spelling
    each of them answers to."""
    flags: set[str] = set()
    valued: set[str] = set()
    for parameter in command().params:
        into = flags if getattr(parameter, "is_flag", False) else valued
        into.update(parameter.opts)
    return frozenset(flags), frozenset(valued)


def _version_asked(argv: Sequence[str]) -> bool:
    """Whether this command line asks the root for its version.

    Read left to right, consuming what the root accepts, and stopping at
    the first word it does not: a command word means whatever follows is
    that command's business, and this grammar declares `--version`
    nowhere but the root.
    """
    flags, valued = _root_options()
    skip = False
    for word in argv:
        if skip:
            skip = False
            continue
        if word == "--version":
            return True
        if word in valued:
            skip = True
            continue
        if word not in flags:
            return False
    return False


# What this module answers to. Only what it defines: the package
# re-exports nothing, so a name that used to be reached through
# `cli.<name>` is reached in the module that defines it.
__all__ = ["main"]
