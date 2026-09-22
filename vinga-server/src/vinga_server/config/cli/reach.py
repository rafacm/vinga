"""Reaching the API.

One request per command, over a client built behind a seam the
acceptance suite replaces with a test client, so the same entry point
runs against the real application with no socket. What the seam does
not cover is the addressing and the transport policy, which run in
front of it and are what those tests are checking.

What its callers stop knowing: the transport policy and where it is
applied, the sanitized-refusal rule, and how a long wait is narrated.
An act hands this a verb, a path and a body and is answered with what
the API said or with one of this grammar's sentences; that a plain
http:// connection to anything but a loopback address is never made,
that a refusal is relayed only when three things about it agree, and
that a wait longer than a database call draws one line on a terminal
and nowhere else are decisions taken here.

Named `reach` rather than `transport` because `config/transport.py`
already exists and is about what JSON can carry.
"""

import contextlib
import ipaddress
import logging
import os
import sys
import threading
import time
from collections.abc import Callable, Iterator, Mapping
from dataclasses import dataclass
from urllib.parse import urlencode, urlunsplit

import httpx
from pydantic import ValidationError

from vinga_server.config import entities
from vinga_server.config.loader import ConfigError, load_file_config
from vinga_server.config.models import API_MOUNT_PATH, FileConfig
from vinga_server.config.printing import parsed_url, printable, shown_url
from vinga_server.config.responses import (
    EVENT_STREAM_MEDIA_TYPE,
    PROBLEM_MEDIA_TYPE,
    PROBLEM_TITLES,
    Problem,
    RefusalReason,
)
from vinga_server.logs import quieted

from .invocation import Invocation

# Where the API is, when nothing says otherwise: the loopback address of
# this machine, on the port the server half of the configuration names,
# under the prefix the sub-application is mounted at. The port is read
# through the same machinery the server reads it with, so the two cannot
# disagree about it any more than they can about the database directory,
# and the prefix comes from the same constant the server mounts on.
API_URL_ENV = "VINGA_API_URL"

# How a command of this grammar is spelled in anything this repository
# generates: the committed CLI reference and its recipes, the export
# header and the secret commands at its foot, the reference intro, and
# the `command` strings the descriptors carry into the domain reference.
#
# One constant and not the invocation, and that is load-bearing rather
# than tidy. `docgen._quoted` picks the commands it publishes as recipes
# by matching each example file's comment lines against this prefix, so
# a name that varied with the entry point would render an empty recipes
# region through one of them and turn the drift check red on an
# unrelated change. A generated document may no more vary with the
# invocation than with the terminal.
PROGRAM = entities.PROGRAM

# The client's timeouts, explicit because the defaults would lie. The
# server holds a write for up to the database's busy timeout (10 s)
# before answering the retryable 409, and httpx's 5 second default would
# turn exactly that answer into a client-side transport error, replacing
# "nothing was changed; run the command again" with a sentence that says
# nothing about what happened. So: a bounded connect, and a read with
# margin above the busy timeout.
CONNECT_TIMEOUT_S = 5.0
READ_TIMEOUT_S = 30.0

# And what `events tail` waits, which is the same conclusion reached
# from the opposite direction.
#
# A read timeout bounds how long an answer may take to arrive. The event
# stream's answer never finishes arriving: it is the server saying what
# it is doing, and a deployment that is doing nothing at four in the
# morning is a stream with nothing on it, which is the reading an
# operator opened it for. Any finite number here would be a clock that
# ended a healthy tail and reported it as the server going away, which
# is the one thing this command's end-of-stream sentence must be able to
# mean.
#
# The keepalive is what makes that safe rather than merely intended: the
# stream writes a comment line on its own idle interval, so a connection
# that has genuinely died is a read that fails rather than a read that
# waits forever. The connect timeout stays bounded for the reason it
# always is, that a server which is not there must say so quickly.
STREAM_READ_TIMEOUT_S: float | None = None

# What the two long waits say while they are waiting, and how often.
#
# The waits are the two above that are not a database call: an import
# waits for a transaction whose length nothing bounds, and an apply
# waits up to a minute for a server to compose, validate and build a
# whole new world. Both are long enough that a terminal showing nothing
# is a terminal that looks hung, and neither has anything to print until
# it is answered.
#
# So a single line on stderr, and it is the interactive affordance the
# determinism practice licenses rather than an exception to it
# (`docs/architecture/cli-guide.md`). It is written only when stderr is
# a terminal, so a pipe, a redirect and a log file get the bytes they
# got before this existed, whole and in the order they got them. It
# re-presents only what the run reports anyway, which is that this
# client is waiting for the API's answer, so nothing is visible
# interactively that a script is not also told. And it carries no value
# of any kind: the no-leak posture applies to progress exactly as it
# applies to a refusal, so the document's path, an entry's name and the
# address reached are all as absent from it as they are from a sentence
# this module raises.
#
# `events tail` is deliberately not narrated. Its answer IS the wait,
# and a client drawing a line over a stream the server is writing to
# would be narrating the thing it is printing.
PROGRESS_PHASE = "waiting for the server"

# Once a second: slow enough that nothing is redrawn faster than it can
# be read, fast enough that the number visibly moves, and a whole number
# of seconds because a wait nobody can bound is not measured in
# milliseconds.
PROGRESS_CADENCE_S = 1.0

# What a cadence has to be, and it is a programmer's mistake rather than
# an operator's: no command line reaches this number, and the callers
# are this module and the tests that drive it faster than a second.
#
# Zero is the value the rule exists for. An event waited on with a
# timeout of zero answers at once, so a redraw loop asked for it would
# spin a core and rewrite the terminal as fast as the stream took it,
# which is the opposite of the thing being built.
PROGRESS_CADENCE_RULE = "the progress line's cadence has to be more than zero seconds"

# How long the way out waits for a redraw that is already inside the
# stream before it gives up on taking the line off the screen.
#
# It exists because a terminal can stop accepting writes and never start
# again, which is what flow control on one is, and the write that orders
# the two threads is then the write the command would be stuck behind.
# A command whose request has been answered must still be able to say
# so, so the wait is bounded and the erase is what is given up.
#
# A second is orders of magnitude above what a live stream takes and is
# a delay nobody will read as a hang, which is the whole of how it was
# chosen. Giving up costs the erase and never the ordering:
# `_ProgressLine.finish` says why.
PROGRESS_ERASE_WAIT_S = 1.0

# Said when the API answered something this client cannot read as an
# answer. The body is deliberately not quoted: what a proxy, a gateway
# or a captive portal returns is not this API's sanitized output, and
# relaying it as though it were is how a middlebox's page ends up looking
# like a configuration error.
UNRECOGNIZED_ANSWER = "a body this client does not recognize"

# And what the event stream says when it stops, which is the same
# sentence whether the body ended cleanly or the connection under it
# died: to whoever is watching, both are the tail going quiet, and a
# client that told them apart would be reporting on a distinction it
# cannot actually make from this side.
#
# It is a failure, and it exits 1 in both modes, because the alternative
# is worse than an error: a tail that ended on a server restart and said
# nothing would be a quiet terminal that looks exactly like a quiet
# deployment. Nothing reconnects on its own for the same reason. A tail
# that rejoined across a gap would go on looking continuous while having
# missed whatever happened in it, and there is no buffer behind the
# stream for it to catch up from.
STREAM_ENDED = (
    "the event stream ended: the server closed it, or something between here and it "
    "did. Nothing has been reconnected, because a tail that rejoined across a gap "
    "would look continuous while missing what happened in it; run the command again "
    "to watch from now on."
)

# And what a 200 that is not the event stream says.
#
# A success is not by itself a reason to read a body. A proxy, a captive
# portal or a gateway answers 200 with a body of its own, and this
# command prints the fields of what it reads, so a body that merely
# parsed as JSON would put a stranger's values on an operator's
# terminal. The media type is the first of the two things that stand
# between those and stdout, and the frame shape is the second. Neither
# what answered nor what it called itself is repeated here, for the
# reason no unreadable answer in this module is.
NOT_THE_EVENT_STREAM = (
    "the address answered, but not with this API's event stream: the response does "
    "not carry the stream's media type, so none of it is read and none of it is "
    "printed. What answered is not quoted back, because a body that is not this "
    "API's output is not this API's to relay. Check that the address names the "
    "configuration API and that nothing in front of it is answering in its place."
)


# The libraries that would narrate the request, and how quiet they are
# held while it is made.
#
# `httpx` writes one line per request at INFO carrying the method, the
# URL and the status, and `logs.py` keeps that deliberately where it
# floors the vendor libraries: for every other caller in this server the
# URL it names says nothing that is not already public. For this one it
# is the address an operator typed, which is accepted with its query
# string whole and can carry `?token=<secret>` in it, so the record the
# library writes is the one surface `Address` exists to keep the
# credential off. A log record is retained in a way a terminal is not.
# `httpcore` traces the connection underneath and is held with it. The
# same two loggers, at the same level and for the same reason, as
# `doctor.py`'s probe; neither module may import the other, so the
# reason is stated in both rather than shared through one.
#
# Held for every request rather than only for an address whose two forms
# differ. The rule is then one rule: this command's own sentences are
# what an operator reads, and no request of its making narrates itself.
# Nothing is lost that anybody needs, because the request is one call
# whose outcome the command reports either way, and a conditional would
# make the quiet part of the value rather than part of the command.
REQUEST_LOGGERS = ("httpx", "httpcore")

# WARNING rather than off, so a library with something genuinely wrong
# to say can still say it, and scoped to the request rather than set
# once, so nothing here changes what a process that imported this logs
# afterwards.
QUIET_LEVEL = logging.WARNING


def build_client(base_url: str, token: str) -> httpx.Client:
    """The connection to the configuration API.

    The one seam in this module. `cli.main()` is and stays synchronous,
    and httpx's ASGI transport is async-only, so the tests replace this
    with Starlette's TestClient: itself a synchronous `httpx.Client`
    subclass that drives an ASGI application through its own portal.

    The token is required rather than defaulted, because every caller
    resolves one before it builds a client and a seam's untaken branch
    is a branch nobody is checking. The one caller that wanted a client
    without an Authorization header was `doctor`, which has its own seam
    now (#244) and no way to carry a credential at all.
    """
    return httpx.Client(
        base_url=base_url,
        headers={"Authorization": f"Bearer {token}"},
        timeout=httpx.Timeout(READ_TIMEOUT_S, connect=CONNECT_TIMEOUT_S),
    )


_NOTHING = object()


@dataclass(frozen=True, kw_only=True)
class Address:
    """Where the API is, in the three forms that are not one string.

    `base` is what the client is built on: the scheme, the host and the
    path, and no query. `query` is the query string the operator's
    address carried, which every request puts back after its own path.
    `shown` is the address with its credentials taken out, bounded and
    made printable, and it is the only one any sentence here may name:
    an accepted URL is not a safe one to print, since the policy below
    refuses the userinfo but says nothing about a query string, and
    `...?token=<secret>` is the other form vendors accept.

    The query is held apart rather than left on the base because a
    client joins an endpoint's path onto the base's whole raw path,
    query included: a base of `https://host/api?token=x` used to send
    `GET /api?token=x/agents`, which is the endpoint's name inside the
    credential's value. `endpoint` below is the composition that was
    missing.

    One type rather than three arguments travelling together, because
    every function that names an address had a plain string to reach for
    and reached for the wrong one (#290): a transport failure and an
    unreadable answer both printed the URL they were given. What crosses
    now is this, and `.shown` is the only field a message can read
    without saying what it is doing.
    """

    base: str
    query: str
    shown: str

    def endpoint(self, path: str, query: str = "") -> str:
        """One endpoint's path under this address, with the arguments
        this request carries and then the query the operator's address
        did.

        The operator's half is reattached as it was written rather than
        re-encoded, since what it holds can be a credential a gateway
        compares literally, and `%20` and `+` are the same space to a
        reader and two different strings to a comparison. The request's
        own half is encoded here, because it is built from what was
        typed at the command rather than parsed out of a URL.
        """
        parts = [part for part in (query, self.query) if part]
        return f"{path}?{'&'.join(parts)}" if parts else path


@dataclass(frozen=True, kw_only=True)
class Reached:
    """Where one invocation's requests go, and what they carry.

    The two answers to "where to reach, in a stated order" (the flag,
    then the environment, then a default derived from the file half),
    resolved once for a whole command rather than once per request.

    Once matters as soon as a command makes more than one request. Each
    of them used to re-read the configuration file and re-resolve the
    address and the token off it, so a file changing under a running
    command could send its second request somewhere its first did not
    go, and `info`, which prints the address it reached before it
    reaches it, could name one endpoint and print another's answer. What
    a command reports about where it went has to be true of where it
    went.

    Frozen and carried rather than re-derived, which is the design
    guide's locality rule applied to a fact with three readers: the line
    `info` opens with, every request's client, and every sentence that
    names an address after a failure.
    """

    address: Address
    token: str


def _reached(args: Invocation) -> Reached:
    """Where this invocation reaches the API, resolved.

    The one read of the file half on the request path, and the one
    resolution of the address and the token off it. A missing token is
    still a sentence before any request is sent, and it is now one
    sentence before the FIRST request rather than before whichever
    request reached this next.
    """
    file_config = load_file_config(args.config)
    return Reached(address=_address(args, file_config), token=_token(file_config))


class _ProgressLine:
    """The one line a long wait draws, and the two rules it is written
    to, which cannot both be absolutes.

    Two threads write it: the command's own, which draws it once and
    finishes it at the end, and the writer, which redraws it while the
    request is in flight.

    **No redraw may land after the line is finished**, because it would
    sit on top of whatever printed next, which for a refused import is
    the one sentence the command has to say. **And the command may never
    wait without a bound to say so**, because a wait an operator sits
    through after the server has already answered is the very ambiguity
    the unbounded read timeout exists to prevent, arrived at from the
    other side.

    Those two are in tension on a stream that can stop accepting writes
    for ever, which a terminal under flow control really does. Holding
    the lock across the write is what orders the two threads, and it is
    therefore also what a wedged write would hold the command behind. So
    the second rule wins and the first is kept as far as it can be:

    - `finished` is set BEFORE anything else, and it is read inside the
      lock, so no redraw that has not already begun can ever write
      again. That half is absolute.
    - The erase then waits for the lock under a bound. Getting it means
      a redraw in flight has finished, so the erase is the last thing
      written and the line comes off. Not getting it means one write is
      wedged inside the stream, and the erase is abandoned rather than
      raced: the command returns, and if that terminal ever recovers the
      wedged redraw lands, with nothing after it that this line wrote.

    What the operator is left with in that case is the line still on the
    screen and the command's own next sentence printed after it rather
    than under it. That is the named degradation, and it is on a
    terminal that had already stopped accepting output.
    """

    def __init__(self) -> None:
        self.lock = threading.Lock()
        # How wide the line last drawn was, so the erase covers what was
        # written rather than a guessed width. Too narrow leaves digits
        # on the screen; too wide writes spaces past the end of the
        # line, which on a narrow terminal is a second line of them.
        self.width = 0
        self.finished = threading.Event()

    def draw(self, seconds: int) -> None:
        """Draw the line where it already is, unless the wait is over.

        The `finished` read is inside the lock and the write is inside
        it too, which is what makes the ordering hold: a redraw that
        acquires the lock after the wait ended sees that it did and
        writes nothing.

        A carriage return and no newline, so the terminal rewrites the
        one line rather than scrolling: what an operator watches is a
        number changing in place. No colour, no spinner and no emoji,
        which the determinism practice rejects outright.
        """
        with self.lock:
            if self.finished.is_set():
                return
            line = f"{PROGRESS_PHASE}: {seconds}s"
            self.width = len(line)
            _to_stderr(f"\r{line}")

    def finish(self, wait_s: float) -> None:
        """End the wait: no more redraws, and the line off the screen if
        the stream will take it within `wait_s`.

        The flag first and the lock second, and that order is the whole
        design. Setting it first means no redraw can start after this
        point whatever happens next, so abandoning the wait below costs
        the erase and never the ordering.

        Nothing here catches anything. A `KeyboardInterrupt` while the
        lock is being waited for is the operator asking for the command
        to stop, and it leaves as itself; the flag is already set, so it
        leaves no redraw behind it either.
        """
        self.finished.set()
        if not self.lock.acquire(timeout=wait_s):
            return
        try:
            _to_stderr(f"\r{' ' * self.width}\r")
        finally:
            self.lock.release()


@contextlib.contextmanager
def narrated(
    narrates: bool,
    cadence_s: float | None = None,
    clock: Callable[[], float] | None = None,
    erase_wait_s: float | None = None,
) -> Iterator[None]:
    """One line on stderr for as long as a long wait lasts, at a
    terminal and nowhere else.

    Two of this grammar's requests are answered after a wait an operator
    watches with nothing on the screen, and `PROGRESS_PHASE` above says
    which and why. Whether a given act is one of them is a fact on its
    row rather than a rule guessed here, because a bound and a wait
    worth narrating are different facts: every act waits, and a read
    bounded by the database's busy timeout is not a wait anybody sits
    through.

    Nothing at all happens off a terminal, and that is the whole of the
    licence this affordance runs under. The check is made once, on the
    way in, so a non-terminal run does not so much as construct the
    thread: there is no writer to be scheduled, no clock to be read, and
    no path by which a byte could reach a redirected stream.

    Three seams, all for tests and all read as None rather than as false
    values, because absent and zero are two different answers.
    `cadence_s` is how often the line is redrawn, so that a test can
    drive several redraws without waiting seconds for them; `clock` is
    where elapsed time comes from, so that a test can assert the number
    on the line moves rather than that something was drawn three times;
    `erase_wait_s` is how long the way out waits for a redraw that is
    inside the stream, so that a test can drive both sides of that bound
    without sitting through the real one. The clock's default is
    monotonic, because what is displayed is a duration and a wall clock
    stepping backwards mid-import would show one that ran backwards with
    it.

    A cadence at or below zero is refused where it is read: an event
    waited on for zero seconds answers at once, so a loop asked for it
    would spin a core and rewrite the terminal as fast as the stream
    took it. No command line reaches that number, so the refusal is a
    programmer's rather than one of this grammar's sentences. Zero is a
    coherent answer for the other bound and is not refused: it means do
    not wait at all for a wedged write, which is a thing a caller may
    honestly want.

    The first line is drawn here rather than by the writer, so that a
    wait shorter than one cadence still says what it is waiting for and
    still takes back what it said. That is the one place this can block
    on a terminal that has stopped accepting output, and it is left
    where it is deliberately: nothing has happened yet when it does, so
    there is no completed work going unreported, and it is the same
    block any command already has at its first write to such a stream.
    What must not happen is a command whose request has been answered
    unable to say so, and that is `finish`'s bound.

    Everything after the first line is the thread's, and the thread is a
    daemon that stops on the line's own event: an interpreter shutting
    down mid-wait is not held open by a line it was drawing, and the
    wait itself is bounded by the request's own timeout rather than by
    anything here.

    **A writer that cannot be started changes nothing about the
    command.** An interpreter out of thread stacks raises from `start`,
    and this catches it, takes the line it had already drawn back off
    the screen and runs the request with no narration at all. The
    affordance is best effort by nature, and the alternative is what
    this had before: a traceback out of a boundary that catches two
    exception classes, a line left standing, and a request never made
    over a progress line that could not be drawn.
    """
    if not narrates or not _stderr_at_a_terminal():
        yield
        return
    cadence = PROGRESS_CADENCE_S if cadence_s is None else cadence_s
    if cadence <= 0:
        raise ValueError(PROGRESS_CADENCE_RULE)
    erase_wait = PROGRESS_ERASE_WAIT_S if erase_wait_s is None else erase_wait_s
    now = time.monotonic if clock is None else clock
    started = now()
    line = _ProgressLine()
    line.draw(0)

    def redraw_until_finished() -> None:
        # One event for both halves of "the wait is over", because they
        # are one fact: it stops the loop here and it stops a redraw
        # writing there. `wait` returns True the moment it is set, so
        # the thread leaves on the answer rather than on the next tick.
        while not line.finished.wait(cadence):
            line.draw(int(now() - started))

    try:
        writer = threading.Thread(target=redraw_until_finished, daemon=True)
        writer.start()
    except RuntimeError:
        # An interpreter that will not give out another thread, which is
        # the one thing here that can fail loudly. Everything else on
        # this path is a write, and a write that fails says nothing.
        line.finish(erase_wait)
        yield
        return
    try:
        yield
    finally:
        # A `finally`, because an answer and a refusal leave the same
        # screen behind: a sentence printed over half a progress line is
        # a sentence nobody can read, and the refusal is the one thing
        # this command still has to say.
        #
        # The writer is not joined, and `finish` is where the two rules
        # it has to keep are reconciled: no redraw after this point, and
        # no unbounded wait to get there.
        line.finish(erase_wait)


def _stderr_at_a_terminal() -> bool:
    """Whether the stream this line would be drawn on is a terminal.

    Answered rather than assumed, and answered False for a stream that
    cannot say: `sys.stderr` is None where an interpreter was started
    without one, and a stream that has been closed raises rather than
    answering. Neither is a terminal, and neither is a reason to fail a
    command over an affordance.
    """
    stream = sys.stderr
    if stream is None:
        return False
    try:
        return bool(stream.isatty())
    except (OSError, ValueError):
        return False


def _to_stderr(text: str) -> None:
    """Write, and say nothing when the stream will not take it.

    Best effort on purpose. This is an affordance rather than an answer:
    a stream closed under a running command, or one whose other end went
    away, must not turn into a failure of the command, and the failure
    it would turn into is one raised from a thread nothing is waiting
    on. The two ways a Python stream refuses are an `OSError` from the
    file descriptor under it and a `ValueError` from a closed object,
    and neither carries anything worth saying.
    """
    stream = sys.stderr
    if stream is None:
        return
    try:
        stream.write(text)
        stream.flush()
    except (OSError, ValueError):
        pass


def _call(
    reached: Reached,
    method: str,
    path: str,
    body: object = _NOTHING,
    read_timeout_s: float | None = READ_TIMEOUT_S,
    query: Mapping[str, str] | None = None,
) -> object:
    """One request, and its answer as this client understands it.

    `reached` is where this whole invocation is talking to, resolved
    once by the row that is performing rather than here: see `Reached`.

    `read_timeout_s` is how long this one endpoint may take to answer,
    which for all but the apply and the import is the same bound the
    client is built with; None is no bound at all, which is what one
    endpoint has and `IMPORT_READ_TIMEOUT_S` says why.

    Set on the client rather than passed with the request: a
    per-request timeout is what httpx would want, and Starlette's
    TestClient refuses one outright, which would take the seam the whole
    acceptance suite runs through with it. Each call builds a client,
    makes one request and closes it, so the two are the same thing here.

    The whole of the request is inside a logging boundary, and that is
    the one thing here that is not about what reaches a terminal: the
    client library writes a line per request naming the URL it was
    given, which for this caller is an operator's address with its query
    string whole. `REQUEST_LOGGERS` above says which loggers and why.
    The token is resolved before the boundary opens, and now before the
    command's first request, so a missing one is still the sentence it
    was.
    """
    with quieted(REQUEST_LOGGERS, QUIET_LEVEL):
        response = _sent(
            method,
            path,
            body,
            reached.address,
            reached.token,
            read_timeout_s,
            urlencode(query or {}),
        )
    return _answer(response, reached.address)


def _sent(
    method: str,
    path: str,
    body: object,
    address: Address,
    token: str,
    read_timeout_s: float | None,
    query: str = "",
) -> httpx.Response:
    """The request, with everything that can go wrong making it turned
    into a sentence.

    Building the client is inside the boundary with the request and the
    close, which is where `doctor.py`'s probe already puts it and for the
    same reason: httpx validates the address when it is handed one, so
    construction is where an address this module's own policy accepted
    and the library then refuses would otherwise leave as a traceback
    with what was typed in it. An IDNA hostname is the shape that does
    it, and it arrives as a `UnicodeError` from under the library rather
    than as anything httpx names, which is why the arm is that wide.

    Every message is built inside a handler and raised after all of
    them: an exception raised while another is being handled carries
    that one as its context, and httpx's exceptions carry the request,
    whose URL is one of the two things this whole policy exists to keep
    out of sight.

    The close is a step of the request rather than tidying after it, so
    it answers a sentence instead of raising: an exception out of a
    `finally` leaves this boundary altogether, taking whatever a driver
    wrote into its message with it, and it would replace a refusal
    already in flight. Whatever failed first is what is reported.
    """
    problem: str | None = None
    client: httpx.Client | None = None
    answered: httpx.Response | None = None
    try:
        try:
            client = build_client(address.base, token)
            client.timeout = httpx.Timeout(read_timeout_s, connect=CONNECT_TIMEOUT_S)
            endpoint = address.endpoint(path, query)
            answered = (
                client.request(method, endpoint)
                if body is _NOTHING
                else client.request(method, endpoint, json=body)
            )
        except httpx.HTTPError:
            problem = _unreachable(address)
        except (httpx.InvalidURL, ValueError):
            problem = _unopenable(address)
    finally:
        # Unconditionally, and the first problem still wins: the `or`
        # this was read as though it did both, and a request that failed
        # skipped its own close for it. The streaming sibling had the
        # identical line and the identical hole, which is why both are
        # written this way now rather than only the one a review found.
        closing = _close_failed(client, address)
        problem = problem if problem is not None else closing
    if answered is None or problem is not None:
        raise ConfigError(problem)
    return answered


def _unreachable(address: Address) -> str:
    return (
        f"cannot reach the configuration API at {address.shown}: the request did not "
        f"complete. Check that the server is running and that this is the address "
        f"it serves. A deployment whose server will not start at all is recovered "
        f"by booting one on an empty database and importing a kept export."
    )


def _unopenable(address: Address) -> str:
    """What an address this module accepted and the library would not
    open says. The transport policy is about the scheme, the host and
    the credential; whether a host can be encoded at all is the
    library's rule, and this is where its refusal becomes one of ours."""
    return (
        f"no connection can be opened to {address.shown}: the address passed the "
        f"transport policy, and the library that would carry the request will not "
        f"accept it. A hostname holding a character no name may hold is what does "
        f"this. Neither the address as it was typed nor the library's own wording is "
        f"repeated here."
    )


def _close_failed(client: httpx.Client | None, address: Address) -> str | None:
    """Give the connection back, and say so when it will not go.

    Answered rather than raised, for the reason the caller states, and
    named by nothing at all rather than quoted, because a transport
    failing on its way out can put the address, a header or a driver's
    own text into its message."""
    if client is None:
        return None
    try:
        client.close()
    except Exception:
        return (
            f"the configuration API at {address.shown} answered, but the connection to "
            f"it could not be closed, so what it said is not printed: an answer this "
            f"client could not finish reading is not one to act on. What the library "
            f"said is not repeated here."
        )
    return None


def _streamed(
    reached: Reached, path: str, query: Mapping[str, str] | None = None
) -> Iterator[str]:
    """The lines of one answer that does not finish arriving.

    `_sent`'s sibling, and a sibling rather than a flag on it because
    what the two do with a response is opposite: that one reads a body
    and hands it back, this one hands back a body that has no end. What
    they share is everything else, and it is not optional. A stream is
    the one request in this grammar that can fail AFTER a response has
    opened, which is exactly where a bare `build_client` preserves none
    of the boundary: the request loggers are quiet for the whole length
    of the stream and not only for its opening, a failure at any point
    of it is a sanitized sentence naming `Address.shown` and nothing
    else, no exception raised here carries the request URL in its chain,
    and the client is given back however the reader leaves.

    Quieting for that length has a consequence worth stating, because it
    is invisible from here: `quieted` holds a process-global lock for
    the span it covers (`logs.py` says why, and the level it is holding
    is the process's whatever guards it), so this block holds it for as
    long as the stream is open. Every other request boundary in this
    package waits behind it. On a deployment that costs nothing, since a
    tail is a process watching one thing; in a test it means the tail
    cannot share a process with what it is watching, which is why the
    live lane runs it as a subprocess.
    """
    with quieted(REQUEST_LOGGERS, QUIET_LEVEL):
        yield from _reading(reached, path, query)


def _reading(
    reached: Reached, path: str, query: Mapping[str, str] | None
) -> Iterator[str]:
    """One open stream, line by line, and every way it can end.

    It always ends by raising, which is the shape of the thing rather
    than a decision taken here: a stream that stopped is either a
    failure this says a sentence about, or the stream having ended,
    which is `STREAM_ENDED` and is also a failure. A reader that has
    read enough leaves by closing this generator, and the `finally`
    below gives the connection back on that path exactly as it does on
    the others.

    The three arms are `_sent`'s three, for its reasons: httpx validates
    an address when it is handed one, so construction is inside the
    boundary; every message is built inside a handler and raised after
    all of them, because an exception raised while another is being
    handled carries that one as its context and httpx's exceptions carry
    the request; and the close answers a sentence rather than raising,
    so whatever failed first is what is reported.
    """
    address = reached.address
    problem: str | None = None
    client: httpx.Client | None = None
    opened: httpx.Response | None = None
    try:
        try:
            client = build_client(address.base, reached.token)
            client.timeout = httpx.Timeout(STREAM_READ_TIMEOUT_S, connect=CONNECT_TIMEOUT_S)
            endpoint = address.endpoint(path, urlencode(query or {}))
            opened = client.send(client.build_request("GET", endpoint), stream=True)
        except httpx.HTTPError:
            problem = _unreachable(address)
        except (httpx.InvalidURL, ValueError):
            problem = _unopenable(address)
        if opened is not None and problem is None:
            if not opened.is_success:
                _refused_stream(opened, address)
            if _media_type(opened) != EVENT_STREAM_MEDIA_TYPE:
                # Checked before a single line is read, because reading
                # is what this command does with what it reads: see
                # `NOT_THE_EVENT_STREAM`.
                problem = NOT_THE_EVENT_STREAM
        if opened is not None and problem is None:
            try:
                yield from opened.iter_lines()
            except httpx.HTTPError:
                # The connection died with the stream open, which from
                # here is the stream ending: see `STREAM_ENDED`.
                problem = STREAM_ENDED
    finally:
        # Unconditionally, and the first problem still wins. `or` read
        # as though it were both, and it is not: a transport failure
        # sets `problem` before this runs, and the short circuit then
        # skipped the close altogether, leaving the connection open on
        # exactly the paths where something had already gone wrong with
        # it. What is kept is the ordering, which is `_sent`'s: a real
        # failure over a close failure, and a close failure over the
        # stream merely having ended.
        closing = _close_failed(client, address)
        problem = problem if problem is not None else closing
    raise ConfigError(problem if problem is not None else STREAM_ENDED)


def _refused_stream(response: httpx.Response, address: Address) -> None:
    """A stream that never opened, said the way every other refusal is.

    A refusal has a body and an end, so it is read whole and handed to
    `_answer`, which is what keeps one vocabulary whichever way an
    operator reached this API: a 401 here says what a 401 says anywhere
    else in this grammar. Reading it is itself a request that can fail,
    which is why the read is inside the boundary too.
    """
    problem: str | None = None
    try:
        response.read()
    except httpx.HTTPError:
        problem = _unreachable(address)
    if problem is not None:
        raise ConfigError(problem)
    # Always a refusal, because the caller asked only for what is not a
    # success, and `_answer` raises on every one of them.
    _answer(response, address)


def _answer(response: httpx.Response, address: Address) -> object:
    """What the API said, or a sentence about why it cannot be read.

    A refusal's `detail` is the repository's own message and is passed
    through untouched, which is what keeps one vocabulary whichever way
    an operator reached the command. Anything else is reported as a
    status code and a fixed sentence: a body this client did not
    recognize did not come from the API's sanitized output, and relaying
    it would put a middlebox's page where a configuration error belongs.

    Which of the two an answer is is decided by `_refusal` below, and
    the decision is narrow on purpose: only a validated
    `application/problem+json` body whose status and title match the
    response is relayed, because a JSON object with a string `detail`
    in it is a shape anything in front of this API can write, and
    every other body is suppressed for the fixed sentence.
    """
    payload = _payload(response)
    if response.is_success:
        if payload is _NOTHING:
            raise ConfigError(_unreadable(response, address))
        return payload
    detail = _refusal(response, payload)
    raise ConfigError(detail if detail is not None else _unreadable(response, address))


# What this client says to do about a state the API states
#
# The other half of the boundary vocabulary above, for refusals (#386).
# The rule is the same one, and it is the same rule for the same reason:
# a remedy is a command, a command is a word of THIS grammar, and the
# server neither ships this program nor versions it, so a sentence
# composed there naming a command prescribes a spelling an image built
# before a rename no longer has. The server says which state it refused
# in, as a closed token; this side owns the grammar, so this side names
# what to type.
#
# Read exactly like `SPOKEN`: the sentence stands alone, names the state
# nowhere (the server's `detail` has already said it) and the command
# once. A token with no line here, and a token this client cannot name
# at all, both print `detail` by itself, which is what a refusal from a
# server newer than this client arrives as. The rule either way is the
# one the whole client keeps: an unknown state is quoted, never guessed
# at.
#
# What holds that spelling true is a test rather than the
# command-spellings census, which reads the tree as text and cannot see
# a sentence composed from `PROGRAM`: measured, by regenerating both
# manifests after this table landed and finding neither had moved.
# `test_every_remedy_names_a_command_this_grammar_has` is the same
# guard over the table, holding every invocation quoted here to a row
# of the registry, so a rename that missed one fails a test in this
# checkout rather than reaching an operator through an old image.
#
# Every member has a line, because every member is a state with
# something to run about; `test_the_remedies_cover_the_whole_vocabulary`
# holds the two sets equal, so a token added on one side alone is red.
REMEDIES: dict[RefusalReason, str] = {
    RefusalReason.CODE_NOT_PENDING: (
        f"`{PROGRAM} device pending list` lists the codes this server is showing "
        f"right now."
    ),
    RefusalReason.AGENTS_UNKNOWN: f"Run `{PROGRAM} list` to see the agents that exist.",
    RefusalReason.AGENT_NOT_SERVING: (
        f"`{PROGRAM} apply` installs an agent written since; `{PROGRAM} list` shows "
        f"the agents that are stored."
    ),
    RefusalReason.DEVICE_ALREADY_BOUND: (
        f"Read what it is bound to with `{PROGRAM} device show <mac>`, or bind it "
        f"again by its MAC."
    ),
    RefusalReason.PROVIDER_MISSING: f"Create it first with `{PROGRAM} provider set`.",
    RefusalReason.MCP_SERVER_MISSING: f"Create it first with `{PROGRAM} mcp-server set`.",
}

# The tokens this client can name, as the strings a body spells them
# with, which is what the reading below compares against.
_KNOWN_REASONS = frozenset(member.value for member in RefusalReason)

# And what a body whose `reason` is there and is not a token reads as,
# which is not a body at all. A sentinel rather than the payload
# unchanged, because `RefusalReason | None` accepts one such value,
# `null`, so leaving it to the validation below would relay a
# middlebox's `detail` to a terminal on the strength of a member's type.
_UNNAMEABLE = object()


def _nameable(payload: object) -> object:
    """A refusal body with a state this client cannot name taken out of
    it, or `_UNNAMEABLE` when what is in that member is not a state.

    Three cases, and the difference between the first two is what a
    strict reader gets wrong. A member that is ABSENT is what a server
    older than the vocabulary sends, and it stays absent. A member
    holding a token this build does not know is a server newer than it,
    and it is read as that same silence, so a state added later meets
    the fallback rather than the sentence reserved for a page nobody
    vouched for. That is `_declared`'s rule one shape up.

    A member that is PRESENT and is not a string is neither of those,
    and it is the arm this was missing. Nothing bounds what a body puts
    where a token belongs, and a list, an object or a number there is
    refused by the validation below whatever this function does; an
    explicit `null` is not, because the field's type admits it. So a
    body carrying `"reason": null` would have had its `detail` printed
    on a terminal, and `detail` is the one field of this shape whose
    words a middlebox chooses. Present and not a string is therefore
    decided here and decided the same way for all of them: this is not
    a refusal this API wrote.
    """
    if not isinstance(payload, Mapping) or "reason" not in payload:
        return payload
    reason = payload["reason"]
    if not isinstance(reason, str):
        return _UNNAMEABLE
    if reason in _KNOWN_REASONS:
        return payload
    return dict(payload) | {"reason": None}


def _refusal(response: httpx.Response, payload: object) -> str | None:
    """The sentence this API wrote, or None when what answered is not
    this API's refusal.

    Three things have to agree before a body's own words are relayed to
    a terminal, and they are three because a middlebox can produce any
    one of them by itself:

    - the media type is exactly `application/problem+json`, which is
      what this API answers a refusal with and what a proxy answering
      `application/json` is not;
    - the body validates as the `Problem` model, which forbids extra
      members, so a page carrying a `detail` beside anything else is
      not one;
    - the status in the body is the status of the response and the
      title is the phrase this API gives that status, so a body lifted
      from one refusal and replayed under another is not one either.

    Anything short of all three is `_unreadable`'s fixed sentence, with
    nothing of the body in it. The model is the one in
    `config/responses.py`, which is the half a generated client would
    substitute for; the validation error is dropped inside the arm and
    never raised from, because pydantic puts the input it rejected into
    its own message.

    A fourth thing has to agree since the body grew a state: what is in
    that member, where there is one, has to be a token rather than
    whatever else JSON can hold. `_nameable` decides it, because one of
    those values is `null`, which the model itself accepts.

    What is relayed is the sentence plus this client's own remedy where
    the body states a state it knows, and the sentence alone where it
    does not. The remedy is appended rather than replacing it, unlike a
    write's boundary line above: a refusal's `detail` is the whole of
    what was refused and this side knows only what to do next, so
    replacing it would drop the half nothing else says.
    """
    if _media_type(response) != PROBLEM_MEDIA_TYPE:
        return None
    title = PROBLEM_TITLES.get(response.status_code)
    if title is None:
        return None
    readable = _nameable(payload)
    if readable is _UNNAMEABLE:
        return None
    try:
        problem = Problem.model_validate(readable)
    except ValidationError:
        return None
    if problem.status != response.status_code or problem.title != title:
        return None
    remedy = REMEDIES.get(problem.reason) if problem.reason is not None else None
    return problem.detail if remedy is None else f"{problem.detail} {remedy}"


def _media_type(response: httpx.Response) -> str:
    """What an answer says it is, without the parameters that follow it.

    One home for the reading because two readers ask it and both decide
    whether to read a body on the answer: a refusal is relayed only from
    `application/problem+json`, and the event stream is read only from
    its own type. `charset=` and whatever else a server appends are not
    part of the comparison, and the case is not either, since neither is
    part of the type.
    """
    return response.headers.get("content-type", "").split(";")[0].strip().lower()


def _payload(response: httpx.Response) -> object:
    """The response's JSON body, or `_NOTHING` when it has none this
    client can read. No exception escapes, so nothing that walks an
    exception chain later finds the body attached to it."""
    if "json" not in response.headers.get("content-type", ""):
        return _NOTHING
    parsed: object = _NOTHING
    try:
        parsed = response.json()
    except ValueError:
        parsed = _NOTHING
    return parsed


def _unreadable(response: httpx.Response, address: Address) -> str:
    return (
        f"the configuration API at {address.shown} answered {response.status_code} with "
        f"{UNRECOGNIZED_ANSWER}. It is not quoted back: what a proxy or a gateway "
        f"returns is not this API's own output."
    )


def _address(args: Invocation, file_config: FileConfig) -> Address:
    """Where the API is: the flag, then the environment, then this
    machine on the port the server half names.

    The last of the three is this module's own string and carries
    nothing to take out, so both of its forms are the same one."""
    if args.api_url:
        return _permitted(args.api_url, "--api-url")
    named = os.environ.get(API_URL_ENV, "").strip()
    if named:
        return _permitted(named, API_URL_ENV)
    local = f"http://127.0.0.1:{file_config.server.port}{API_MOUNT_PATH}"
    return Address(base=local, query="", shown=local)


def _permitted(url: str, source: str) -> Address:
    """The transport policy, which is about the token before it is about
    any secret body.

    The bearer token crosses every request and grants everything the API
    can do, secret writes included, so loopback-or-TLS is the rule for
    the whole client rather than a secret-write footnote. There is
    deliberately no flag to override it: such a flag's only purpose would
    be sending the token in clear.

    An accepted URL leaves as an `Address` rather than as itself, and
    the display form it carries is the one computed here: the policy
    refuses a credential in the userinfo but says nothing about a query
    string, so an accepted address can still hold `?token=<secret>`, and
    the transport failures further up print the address they were given.
    """
    parsed = parsed_url(url, source)
    # Bounded and made printable as well as stripped, because this is
    # the form every sentence below names and a typed address is text
    # nobody has vouched for: `urlsplit` deletes tabs and newlines and
    # leaves every other control character where it was, and a hostname
    # the library goes on to refuse is exactly the one carrying one.
    shown = printable(shown_url(parsed))
    if parsed.scheme not in ("http", "https") or not parsed.hostname:
        raise ConfigError(
            f"{source} is not an http:// or https:// URL with a host: {shown}"
        )
    if parsed.username or parsed.password:
        raise ConfigError(
            f"{source} carries a username or a password in the URL, which is refused: "
            f"this API's credential is a bearer token sent as a header, and anything in "
            f"a URL ends up in shell history, process lists and access logs. The "
            f"address without it is {shown}."
        )
    if parsed.scheme == "http" and not _loopback(parsed.hostname):
        raise ConfigError(
            f"{source} names {shown}, a plain http:// connection to a host that is not "
            f"a loopback address (127.0.0.1, ::1 or localhost), and the bearer token "
            f"would cross it in clear along with anything a secret write sends. Use "
            f"https://, put a TLS-terminating tunnel in front, or exec into the "
            f"running container and reach the API on loopback. There is deliberately "
            f"no flag to override this."
        )
    # Rebuilt from the parsed parts rather than trimmed as a string,
    # which is what takes the query off the base and the fragment with
    # it. The userinfo cannot survive either, and is refused above in
    # any case.
    return Address(
        base=urlunsplit((parsed.scheme, parsed.netloc, parsed.path.rstrip("/"), "", "")),
        query=parsed.query,
        shown=shown.rstrip("/"),
    )


def _loopback(host: str) -> bool:
    if host.lower() == "localhost":
        return True
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return False


def _token(file_config: FileConfig) -> str:
    """The bearer token, from the variable `server.api.secret_env` names.

    On a deployment that is exactly the variable the server itself was
    started with, so exec into the running container and the CLI has the
    token and the loopback address for free. Resolved before any request
    is sent, so a missing one is a sentence rather than a 401.
    """
    name = file_config.server.api.secret_env
    token = os.environ.get(name, "").strip()
    if not token:
        raise ConfigError(
            f"{name} is not set, and every request to the configuration API carries its "
            f"value as a bearer token. It is the same variable the server was started "
            f"with: exec into the running container and it is already in the "
            f"environment."
        )
    return token
