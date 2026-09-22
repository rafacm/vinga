"""Input: everything a command reads that did not ride argv.

The YAML a fragment or a document is written in, the inline values
written beside a key, the confirmation a destructive verb asks at a
terminal, the credential a secret write is given, and the content the
memory noun carries. None of it is an argument, and the two reasons are
the same one twice: an argument lands in shell history and in the
process list, and a value nobody has validated must not reach a library
whose business is to describe what it could not read.

What its callers stop knowing: which library parsed what, and what an
interactive failure is called. Every refusal here is a fixed sentence
of this grammar's own, built inside its handler and raised after it, so
nothing walking an exception chain finds the path, the bytes or the
document that was being read.
"""

import getpass
import os
import sys
from collections.abc import Callable, Mapping, Sequence
from pathlib import Path

import yaml

from vinga_server.config.loader import (
    UNPARSEABLE,
    YAML_NOT_QUOTED,
    ConfigError,
    stopped_at,
)

from .invocation import Invocation

# The one this grammar raises for itself as well as translating, so it
# is a name rather than a cell: a `set` given neither a fragment nor a
# key=value pair is missing a required argument, and Click cannot see
# that because either of the two satisfies it.
MISSING_ARGUMENT = "a required argument is missing"


def usage_line(sentence: str) -> str:
    """One usage sentence as it is printed, with the tail every one of
    them carries.

    Named because the boundary is not the only raiser: a mistake in the
    grammar that Click cannot see, because either of two arguments
    satisfies it, is still a mistake in the grammar and reads as one.
    """
    return f"{sentence}; run with --help for the grammar"


# Reading YAML
#
# The one place this CLI calls a parser, and therefore the one place a
# value nobody has validated meets a library whose business is to
# describe what it could not read. Both ways a YAML value reaches this
# group go through it: a fragment or a document read from a file or
# from stdin, and one inline value written beside a key.
#
# What a caller is told is fixed, plus at most the two integers saying
# where the parser stopped. Never the parser's own words: `problem`
# names the tag or the key it choked on, and `!<credential> value` is a
# document PyYAML answers by quoting the credential back. That leak was
# in the `-f` write from the beginning and is closed here for both
# callers at once, because there is one boundary now rather than two
# that happened to agree.
#
# What is caught is wider than `YAMLError`, which is the other half of
# the same fix, and it is `loader.UNPARSEABLE`: the boot path reads a
# file through the same parser, so the family, the sentence and the
# locator are one module's and are imported above.

# What the inline form calls the thing it could not read. Its own
# source name rather than a path, because there is no file: the value
# is one argument, and where the parser stopped is a column inside it.
PAIR_SOURCE = "an inline field's value"


def _parsed_yaml(text: str, source: str) -> object:
    """One YAML source read, or the fixed sentence for one that will
    not read.

    Recorded inside the handler and raised after it, the rule this
    module raises by: a PyYAML mark holds the whole buffer it was
    parsing, and an exception raised inside a handler keeps the one
    being handled as its `__context__` for anything walking the chain to
    find. What survives the arm is a string built from `source`, which
    is the caller's, and two integers.
    """
    problem: str | None = None
    parsed: object = None
    try:
        parsed = yaml.safe_load(text)
    except UNPARSEABLE as exc:
        problem = f"invalid YAML in {source}{stopped_at(exc)}. {YAML_NOT_QUOTED}"
    if problem is not None:
        raise ConfigError(problem)
    return parsed


# What a source that will not parse is called. Two names of this
# module's own, and neither is the path: `-f` takes one file, so the
# path adds nothing an operator does not have on the line they just
# typed, and a path is typed, which makes it the last place a refusal
# may repeat (#289). Where the parser stopped is a line and a column,
# which is what locates the mistake inside the file.
FILE_SOURCE = "the fragment file"

STDIN_SOURCE = "the fragment on stdin"


def _fragment(path: str) -> object:
    """One entity's YAML fragment or one whole document, from a file or
    from stdin. Parsed here and validated by the models in the
    repository, which is where the rule that a secret-bearing key may
    only name an environment variable already lives."""
    source = STDIN_SOURCE if path == "-" else FILE_SOURCE
    return _parsed_yaml(_piped() if path == "-" else _file(path), source)


# Inline values
#
# `set <kind> [identity] key=value...` assembles the fragment the YAML
# would, and nothing else: the pairs become a mapping, dotted keys nest,
# and what comes out enters the exact path a `-f` fragment enters, so
# the same check, the same request and the same acknowledgement follow.
#
# The parser is a no-leak boundary of its own, built the way `_fragment`
# is and, since the two share `_parsed_yaml` above, out of the same
# boundary: a value typed beside a key is where a paste lands, so every
# refusal below is a fixed sentence naming what was wrong with the shape
# and never what was written, and each is raised after its arm rather
# than inside it, so no exception chain carries the string that was
# being parsed.
#
# A value is held to one scalar. `yaml.safe_load` will happily read
# `[a, b]` or `{a: 1}` out of one argument, and the contract is that an
# inline value is a scalar: a structure belongs in a fragment, where it
# can be read.

PAIR_NEEDS_EQUALS = (
    "an inline field is written key=value, and one of these arguments has no =. "
    "Nothing typed is quoted back"
)

PAIR_EMPTY_KEY = (
    "an inline field's key is empty, or has an empty segment between two dots: write "
    "a.b rather than .a, a. or a..b. Nothing typed is quoted back"
)

PAIR_DUPLICATE_KEY = (
    "an inline field's key is given twice, and one write says one thing about a key. "
    "Nothing typed is quoted back"
)

PAIR_NESTED_KEY = (
    "one inline field's key nests inside another's, such as a.b beside a, which says "
    "two things about the same place. Nothing typed is quoted back"
)

PAIR_NOT_SCALAR = (
    "an inline field's value reads as a list or a mapping, and an inline value has to "
    "be one scalar; write a structure as a fragment with -f. Nothing typed is quoted "
    "back"
)

# The two ways of writing an entity are alternatives, so neither and
# both are each a mistake in the grammar. Neither is the missing
# argument Click cannot see, because either of the two satisfies it.
BOTH_INPUTS = (
    "a write takes either -f with a YAML fragment or key=value arguments, and this "
    "command was given both"
)


def _written_entity(args: Invocation) -> object:
    """The entity a write sends, from whichever of the two ways of
    writing one this command was given."""
    if args.file and args.pairs:
        raise ConfigError(usage_line(BOTH_INPUTS))
    if args.file:
        return _fragment(args.file)
    if args.pairs:
        return _pairs(args.pairs)
    raise ConfigError(usage_line(MISSING_ARGUMENT))


def _pairs(written: Sequence[str]) -> dict[str, object]:
    """Inline `key=value` arguments as the mapping they assemble.

    Split on the FIRST `=`, so a value holding one is a value: `=` is
    the separator and not a character the value may not contain. The
    keys are read and checked against each other before any value is
    parsed, because a key that is written twice or written inside
    another is a mistake about the whole set rather than about one pair.
    """
    keys = [_pair_key(pair) for pair in written]
    _distinct(keys)
    assembled: dict[str, object] = {}
    for key, pair in zip(keys, written, strict=True):
        _nest(assembled, key, _scalar(pair.partition("=")[2]))
    return assembled


def _pair_key(pair: str) -> tuple[str, ...]:
    """One pair's key, as the segments its dots name."""
    key, equals, _ = pair.partition("=")
    if not equals:
        raise ConfigError(PAIR_NEEDS_EQUALS)
    segments = tuple(key.split("."))
    if not all(segments):
        raise ConfigError(PAIR_EMPTY_KEY)
    return segments


def _distinct(keys: Sequence[tuple[str, ...]]) -> None:
    """No key written twice, and no key written inside another.

    The second is the one worth saying out loud: `a.b=1 a=2` asks for a
    mapping and a scalar at one place, and whichever of them a parser
    happened to apply last would be an answer the operator did not
    choose.
    """
    for position, key in enumerate(keys):
        for other in keys[position + 1 :]:
            if key == other:
                raise ConfigError(PAIR_DUPLICATE_KEY)
            if key[: len(other)] == other or other[: len(key)] == key:
                raise ConfigError(PAIR_NESTED_KEY)


def _scalar(value: str) -> object:
    """One pair's value, read as YAML reads it and held to a scalar.

    Read through the same boundary a fragment is read through, so that
    the two ways of writing an entity meet one sentence for a source
    that will not parse and one set of failures is caught for both:
    everything PyYAML raises rather than the documented `YAMLError`
    alone, which for one argument matters as much as for a file, since
    an integer of five thousand digits fits on a command line.

    What is not refused here is everything JSON cannot carry, which a
    scalar can still be: a bare date, `.nan`. Those meet
    `check_transportable`'s own sentence a step later, which is where
    that rule lives for a fragment too.
    """
    parsed = _parsed_yaml(value, PAIR_SOURCE)
    if isinstance(parsed, (Mapping, list, tuple, set, frozenset)):
        raise ConfigError(PAIR_NOT_SCALAR)
    return parsed


def _nest(under: dict[str, object], key: Sequence[str], value: object) -> None:
    """One dotted key's value, put where its dots nest it, making the
    mappings on the way.

    Nothing on the way can be anything but a mapping this made or a
    place nothing has written yet, because `_distinct` has already
    refused a key that nests inside another.
    """
    head, rest = key[0], key[1:]
    if not rest:
        under[head] = value
        return
    below = under.setdefault(head, {})
    if not isinstance(below, dict):  # pragma: no cover - _distinct rules it out
        raise ConfigError(PAIR_NESTED_KEY)
    _nest(below, rest, value)


# What a fragment file that cannot be read says. One fixed sentence per
# failure, and none of them holds the path, the operating system's
# wording or a byte of the file (#289).
#
# The path is typed, and this CLI's whole no-leak posture is about what
# was typed: a fragment lives next to the deployment it configures, and
# `-f` is one option away from the secret paths. The library's own
# `strerror` is not passed through for the reason Click's sentences are
# not: a message this code did not write is a message it cannot promise
# carries no value.
FILE_NOT_FOUND = (
    "there is no file at the path -f names. It is not quoted back: a refusal here "
    "names the rule rather than what was typed"
)

FILE_NOT_READABLE = (
    "the file -f names cannot be read: check that it is a file this user may read, "
    "rather than a directory or one belonging to somebody else. Neither the path nor "
    "the system's own wording is quoted back"
)

FILE_NOT_TEXT = (
    "the file -f names is not UTF-8 text, so there is no YAML in it to read. Nothing "
    "it holds is quoted back, and nothing of it is decoded far enough to be: a file "
    "that fails to decode is as likely to be a key or an archive as a mistyped "
    "fragment"
)

FILE_UNREADABLE = (
    "the file -f names could not be read. Neither the path nor the system's own "
    "wording is quoted back"
)

# Ordered, first match wins, and a subclass comes before the class it
# extends. The decoding family is here because `UnicodeDecodeError` is a
# `ValueError` rather than an `OSError`: the read succeeds and the
# decoding is what fails, which is why it used to leave as a traceback,
# and the exception it leaves as holds the buffer it could not decode.
# Caught as the whole family, which is what `docgen`'s reader of the
# example fragments catches for the same reason.
_FILE_PROBLEMS: tuple[tuple[type[BaseException], str], ...] = (
    (FileNotFoundError, FILE_NOT_FOUND),
    (NotADirectoryError, FILE_NOT_FOUND),
    (IsADirectoryError, FILE_NOT_READABLE),
    (PermissionError, FILE_NOT_READABLE),
    (UnicodeError, FILE_NOT_TEXT),
    (OSError, FILE_UNREADABLE),
)

# What the arm catches, read off the table rather than written beside
# it: a shape the table answers and the arm does not catch is a
# traceback, which is the half of #289 that was not about echoing.
_FILE_FAILURES = tuple(shape for shape, _ in _FILE_PROBLEMS)


def _file(path: str) -> str:
    """One fragment file's text, or the fixed sentence for a file that
    will not give any.

    The sentence is chosen by the class of the failure, which is the
    reading that cannot be fooled by wording, and is raised after the
    arm rather than inside it: the exception being handled holds the
    path and, for a file that will not decode, the bytes it was
    decoding, and an exception raised inside a handler keeps that one on
    its `__context__` for anything walking the chain to find.
    """
    problem: str | None = None
    try:
        return Path(path).read_text(encoding="utf-8")
    except _FILE_FAILURES as exc:
        problem = next(
            sentence for shape, sentence in _FILE_PROBLEMS if isinstance(exc, shape)
        )
    raise ConfigError(problem)


# What `-f -` says when it is run at a terminal with nothing piped in.
#
# It used to block: the read is unconditional, so a person who typed
# `import -f -` at a prompt met a cursor and no explanation, which is the
# same rule as the secret prompt broken from the other side, by never
# asking whether there is anybody there. The published answer is to quit
# and point at the help, and this grammar's shape for that is one
# sentence with the usage tail every other mistake in it carries.
STDIN_AT_A_TERMINAL = (
    "-f - reads from standard input, and standard input here is a terminal with "
    "nothing piped into it. Pipe the document in, or name a file with -f"
)


def _stdin() -> str:
    """Standard input, read whole."""
    return sys.stdin.read()


def _piped() -> str:
    """The document `-f -` names, or the sentence for a terminal with
    nothing piped into it.

    The one place this grammar asks whether there is anybody there
    before reading, and it is the document path alone. A credential's
    read asks the same question the other way round, by prompting when
    there is somebody and reading plainly when there is not, so it
    already has an answer for a terminal and does not want this one.
    """
    if sys.stdin is not None and sys.stdin.isatty():
        raise ConfigError(usage_line(STDIN_AT_A_TERMINAL))
    return _stdin()


# What a `--from-env` naming nothing says, and what it deliberately does
# not say: which name it was given (#289). A variable name is typed on
# the command line, and the mistake that produces this refusal most
# often is typing the secret itself where the name belongs, which is the
# one value this whole command exists never to see. The rule is named
# instead, since that is what tells an operator what to look at.
FROM_ENV_NOT_SET = (
    "--from-env names a variable that is not set in this environment, or is set to an "
    "empty value. The name is not quoted back: what follows --from-env is typed, and "
    "typing the secret there instead of the variable holding it is the mistake this "
    "refusal meets most. Check the spelling, and that the variable is exported"
)


# What a destructive verb asks, and the two sentences it answers with
#
# Every one of the three is a fixed constant carrying no address and no
# other value from the command line. That is a real usability cost, paid
# knowingly: a prompt that cannot say which entry it means is worse to
# read than one that can. It is paid because the address is built from
# `stage`, `name`, `mac`, `code` and `slot`, all typed, and a mistyped
# command is exactly where a credential lands in an address field, which
# is the mistake these sentences exist not to repeat. The answer to
# "which entry is this" is a `show` before the delete, not a sentence
# that quotes back what was typed.
#
# The question goes to stderr rather than to stdout, which is where
# every other thing about a run goes and what keeps `> file` clean; it
# is asked only when stdin is a terminal, so the non-terminal path is
# complete without it.
CONFIRMATION = (
    "This deletes what the command addresses, and nothing in this grammar puts it "
    "back: an export taken beforehand is the only copy. Type y to go ahead: "
)

DECLINED = "nothing was deleted, because the confirmation was not answered with y"

# And what a terminal that cannot be read says. The question is asked
# and the answer never arrives: a stream that has gone, or bytes the
# terminal's encoding will not decode, which is an ordinary thing for a
# pasted answer to be. Neither is quoted, and the decoding failure is
# the reason: what it retains is the bytes it could not read, which came
# off a terminal an operator is typing a delete into.
CONFIRMATION_UNREADABLE = (
    "the confirmation could not be read from this terminal, so nothing was deleted. "
    "What could not be read is not repeated here. Run it again, or run it with "
    "--force, which answers the question without asking it"
)

NO_INPUT_REFUSED = (
    "a destructive command asks for a confirmation at a terminal, and --no-input "
    "disables every prompt. Run it again with --force, which answers the question "
    "this would have asked"
)


def _permitted_to_destroy(args: Invocation) -> None:
    """Whether a destructive verb may go ahead, asked at a terminal.

    Five answers and one rule under them: never block a pipe, and never
    take the only door away. `--force` answers the question, so it
    proceeds whatever else was given; `--no-input` takes the asking away
    and refuses, because a confirmation has no second way to be
    answered, which is exactly why a secret set is not refused by the
    same flag: a secret has three doors and disabling one leaves two.
    A stream that is not a terminal has nobody to ask, so it proceeds.
    """
    if args.force:
        return
    if sys.stdin is None or not sys.stdin.isatty():
        return
    if args.no_input:
        raise ConfigError(NO_INPUT_REFUSED)
    print(CONFIRMATION, end="", file=sys.stderr, flush=True)
    if _answered().strip().lower() != "y":
        raise ConfigError(DECLINED)


# What an interactive read can fail as, and the shape every one of them
# is made behind.
#
# Three reads in this grammar ask a person for something: the
# confirmation before a destructive verb, the no-echo prompt a secret is
# typed at, and the plain read of a piped one. Each of them can fail in
# ways no argument of theirs decides. `EOFError` is what a prompt raises
# when the stream ends under it, and it is not an `OSError`; a stream
# that has gone is an `OSError`; bytes the encoding will not decode
# leave as a `UnicodeError`, which is a `ValueError` and not an
# `OSError` at all. An arm catching one family lets the other two out.
#
# What they carry is why they are caught rather than merely handled: a
# decoding failure holds the bytes it could not read, and those bytes
# came off a terminal somebody was typing a credential or a delete into.
# So the sentence is built inside the handler and raised after it, and
# nothing walking the chain finds the failure, or what it held, behind
# the refusal.
_INPUT_FAILURES = (EOFError, OSError, UnicodeError, ValueError)


def _read_from(reader: Callable[[], str], problem: str) -> str:
    """One interactive read, or this grammar's own sentence for a stream
    that would not give one.

    One shape for the three, because they differ only in the sentence:
    what a caller cannot supply is the boundary, and three copies of it
    would be three chances to catch two families out of three.
    """
    failed: str | None = None
    try:
        return reader()
    except _INPUT_FAILURES:
        failed = problem
    raise ConfigError(failed)


def _answered() -> str:
    """What was typed at the confirmation, or the sentence for a
    terminal that would not give it.

    The one read in this grammar that happens after something has
    already been printed, which is the whole of what makes its sentence
    its own rather than the secret read's.
    """
    return _read_from(sys.stdin.readline, CONFIRMATION_UNREADABLE)


# What an empty secret says. Named rather than written at its raise
# site, because two paths answer with it now: a read that gave nothing,
# and a terminal that was never read because prompting was disabled.
# What a secret that could not be read at all says. Distinct from the
# empty one, because they are different facts about a run: an empty
# secret is a stream that answered with nothing, and this is a stream
# that did not answer. Neither says what it held.
SECRET_UNREADABLE = (
    "the secret could not be read from this terminal, and nothing was stored. What "
    "could not be read is not repeated here, and neither is what the system said "
    "about it. Pipe the value in, or name the variable holding it with --from-env"
)

SECRET_EMPTY = (
    "the secret is empty; pipe it in, type it at the prompt, or name the "
    "variable holding it with --from-env"
)


def _read_secret(args: Invocation) -> str:
    """The secret itself, from a named environment variable or from
    stdin. Never from an argument: arguments land in shell history and
    in the process list. An interactive terminal is read without echo;
    a pipe or a redirect is read plainly, which is what scripts use.

    `--no-input` does not refuse: what that flag disables is prompting,
    and a value is still reachable two other ways. What it does at a
    terminal is answer immediately rather than read, and that is not a
    third answer but the same one arrived at without hanging first. A
    terminal is where somebody types, so a terminal with the typing
    disabled has nothing in it: reading one waits for an end-of-file
    only a person can send, which is the block `-f -` used to have and
    the thing the whole prompt rule is about. The value such a read
    would yield is the empty one, and this is that answer without the
    wait.

    A destructive verb is refused by the same flag rather than answered,
    because its confirmation has no other way to be given.
    """
    if args.from_env:
        secret = os.environ.get(args.from_env, "")
        if not secret:
            raise ConfigError(FROM_ENV_NOT_SET)
        return secret

    at_a_terminal = sys.stdin is not None and sys.stdin.isatty()
    if at_a_terminal and args.no_input:
        raise ConfigError(SECRET_EMPTY)
    if at_a_terminal:
        secret = _read_from(
            lambda: getpass.getpass("Secret (not echoed): "), SECRET_UNREADABLE
        )
    else:
        secret = _read_from(_stdin, SECRET_UNREADABLE)
    # The trailing newline is the shell's, not the secret's.
    secret = secret.rstrip("\r\n")
    if not secret:
        raise ConfigError(SECRET_EMPTY)
    return secret


# The content the memory noun carries, which is never an argument
#
# A corrected fact is what somebody said in a room and a ledger key is a
# word a model chose, so both are held to the rule a credential is held
# to rather than to a weaker one: an argument lands in shell history and
# in the process list, where a value cannot be taken back, and either of
# these can be exactly the value that matters. They arrive from a file
# or from standard input, and the command refuses rather than blocking
# where there is nobody to read from.

MEMORY_TEXT_AT_A_TERMINAL = (
    "the corrected fact is read from a file named with -f or from standard input, "
    "never from an argument, and standard input here is a terminal with nothing piped "
    "into it. Pipe the text in, or name a file with -f"
)

MEMORY_TEXT_EMPTY = (
    "nothing was read to correct the fact with, and nothing was changed. A correction "
    "says what the fact should say instead, so an empty read is refused rather than "
    "stored"
)

MEMORY_KEY_AT_A_TERMINAL = (
    "the entry to clear is read from standard input, never from an argument, and "
    "standard input here is a terminal with nothing piped into it. Pipe the name in, "
    "or clear the whole ledger with --all"
)

MEMORY_KEY_EMPTY = (
    "nothing was read to name the entry to clear, and nothing was changed. Pipe the "
    "name in, or clear the whole ledger with --all"
)

# And what a stream that would not give one says. Its own sentence
# rather than the secret read's, because what it is about is a fact
# rather than a credential, and neither of them repeats what it could
# not read: a decoding failure retains the bytes it failed on.
MEMORY_UNREADABLE = (
    "what this command was to carry could not be read, and nothing was changed. What "
    "could not be read is not repeated here, and neither is what the system said about "
    "it"
)


def _typed(args: Invocation, at_a_terminal: str, empty: str) -> str:
    """One piece of content this command carries, from the file `-f`
    names or from standard input.

    `-f -` is standard input, the spelling this grammar already has for
    it. A terminal with nothing piped into it is answered with one
    sentence and the usage tail rather than a cursor, which is the
    mistake `import -f -` used to make from the other side.

    The trailing newline is the shell's rather than the content's, and
    what is left after it is refused where it is empty: an empty read is
    a command that was given nothing, not a command that was given the
    empty value.
    """
    if args.file and args.file != "-":
        text = _file(args.file)
    elif sys.stdin is None or sys.stdin.isatty():
        raise ConfigError(usage_line(at_a_terminal))
    else:
        text = _read_from(_stdin, MEMORY_UNREADABLE)
    text = text.strip()
    if not text:
        raise ConfigError(empty)
    return text
