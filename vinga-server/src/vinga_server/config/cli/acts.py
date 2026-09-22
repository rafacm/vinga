"""The acts: one request, and its answer printed.

One row per thing a command does: where the act is on the API and how
this command's arguments address it, what it sends, what it is answered
with, and how that answer is printed. `_act` is the only reader of a
row, and `_performed` is what runs the rows one invocation asked for.

What its callers stop knowing: how one act becomes one request and one
rendering. A family writes a row; that the body is built before the
narration opens and the answer rendered after it has closed, that a
sequence stops at the first refusal, and that an answer is read as the
shape the row declares before any renderer sees it are decided here. So
is which shape the answer leaves in, which is one parameter on `_act`
with a person as its default and no branch in any renderer.

Nothing entity-shaped lives here, and that is a boundary rather than an
omission: the per-kind tables name the entity renderers, so keeping
them here would make this module import the family that imports it.
"""

import contextlib
import io
import sys
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any
from urllib.parse import quote

from vinga_server.config.loader import ConfigError

from .answers import Output, _understood, encoded
from .invocation import Invocation
from .reach import _NOTHING, READ_TIMEOUT_S, UNRECOGNIZED_ANSWER, Reached, _call, narrated

# The three things a body can fail to be, said in the words each act has
# always said them in. Which one an act meets is a fact of the act, so it
# is written on its row rather than at the raise site.
UNREADABLE_READ = f"the configuration API answered a read with {UNRECOGNIZED_ANSWER}"

# A write is the one whose refusal has to say what is now unknown: the
# request may well have landed, and this client cannot tell.
#
# "Written" and not "applied", which is a correction rather than a
# style (#371). Every act carrying this sentence writes the store and
# installs nothing: the per-entity sets and deletes, the secret writes,
# the bindings, the memory writes and `import`. What is unknown after an
# unreadable acknowledgement is whether the store took it, and `apply`
# is now the word for the other thing, so the old wording would have had
# twenty refusals naming a command none of them makes.
UNREADABLE_WRITE = (
    f"the configuration API acknowledged the write with {UNRECOGNIZED_ANSWER}; "
    f"read the configuration back to see whether it was written."
)


def _path(*parts: str) -> str:
    """One resource's path, each identity as exactly one segment.

    Percent-encoded with nothing left safe, which is what lets a name
    carrying a space, a percent sign or a character outside ASCII be
    addressed with no second scheme. A name carrying a slash cannot be
    addressed at all, which is why the repository refuses to write one.
    """
    return "/" + "/".join(quote(part, safe="") for part in parts)



@dataclass(frozen=True, kw_only=True)
class Act:
    """One thing a `vinga-server config` command does."""

    # The request: the verb, the path this command's arguments address,
    # and the body it carries, where it carries one.
    method: str
    path: Callable[[Invocation], str]
    # The query arguments this request carries, where it carries any.
    # Apart from `path` on purpose: what identifies an operation is the
    # path the document is written in, and a filter or a selector is not
    # part of that identity. It is also what keeps the operator's own
    # query string, which can be a credential, from being re-encoded
    # alongside arguments this command built itself.
    query: Callable[[Invocation], dict[str, str]] | None = None
    body: Callable[[Invocation], object] | None = None

    # How long this one endpoint may take to answer. Every act but the
    # apply and the import takes the default, whose bound is the
    # database's; None is no bound, which is one act's answer.
    read_timeout_s: float | None = READ_TIMEOUT_S

    # Whether the wait for this act's answer is long enough to be worth
    # saying so at a terminal, which is the two acts above and nothing
    # else (`PROGRESS_PHASE`).
    #
    # A fact on the row rather than a reading of the bound beside it,
    # for the reason the confirmation is a fact on a command's row: the
    # two say different things. A bound is how long an endpoint may take
    # before this client gives up on it, and every act has one; this is
    # whether a person is left looking at nothing while it does. An act
    # that grew a bound of its own would not thereby become a wait
    # anybody sits through, and deriving one from the other would say it
    # had.
    narrates: bool = False

    # The shape the API declares for the body this act sends, or None
    # where it sends none. Declared and never validated against: a
    # fragment is the operator's YAML and the server is what refuses a
    # bad one, so a second refusal here would be a second encoding of
    # the same rule. What reads it is the contract check, which holds
    # every act's request against the committed document, and #287's
    # generator after it. A method and a path alone leave exactly the
    # four bodies with adapters in front of them free to drift.
    sends: object | None = None

    # The shape the API says it answers this act with, and the sentence
    # a body that is not one meets. Required, because every act has an
    # answer: a shape known only inside a renderer is a fact with no
    # home, and one nothing outside the closure can read is a contract
    # no test can hold to the document.
    answers: object
    refusal: str = UNREADABLE_READ

    # What is printed, given the answer.
    render: Callable[[Any], None]

    def read(self, answer: object) -> Any:
        """One answer, read as the shape this act says it is sent.

        On the act rather than in the renderer that used to do it, which
        is what makes the shape inspectable from the row: the same fact
        the contract check compares against the document is the one the
        command validates with, so the two cannot come apart.
        """
        return _understood(self.answers, answer, self.refusal)


class _Discarded(io.TextIOBase):
    """A stdout for an arm that has already written the answer.

    What it is for is below: the machine arm runs the act's own renderer
    for the notices it writes to stderr, and the rendering it writes to
    stdout is the one thing that arm has already answered in another
    shape. Writing and dropping rather than not rendering at all, so
    there is one renderer under both arms and nothing to keep in
    agreement with it.

    A writer of its own rather than a `StringIO`, because a rendering
    nobody will read is a rendering nobody should hold: a listing is
    bounded by a page and a prompt is not, and the point of this arm is
    that those bytes are not wanted.
    """

    def writable(self) -> bool:
        return True

    def write(self, text: str) -> int:
        return len(text)


# One of them, because it holds nothing: what a write costs here is the
# length it answers with.
_DISCARDED = _Discarded()


def _act(args: Invocation, act: Act, reached: Reached, output: Output = Output.HUMAN) -> None:
    """One act: one request, and its answer printed.

    The acknowledgement and the notice are the API's, read as the shape
    the act says it is answered with and handed to the act's renderer.

    `reached` is handed in rather than resolved here, so that the acts
    of one command all go to one place and a command that says where it
    is going says it truly: see `Reached`.

    What the act carries is built before the narration opens and its
    answer is rendered after that narration has closed, so the line the
    two long waits draw covers the wait and nothing else. Reading a
    document off standard input is not waiting for a server, and a
    rendering printed under a line still being redrawn would be a
    rendering nobody can read.

    `output` is where this grammar would put a `--json`, and it is
    defaulted here rather than declared anywhere a command can reach:
    every command runs under `Output.HUMAN` today, and adopting the flag
    is the grammar setting this parameter and nothing else.

    The machine arm is the data and then the notices, which is the order
    a person reads them in too: the encoded model goes to stdout and is
    flushed, and then the act's own renderer runs with stdout bound to a
    sink that drops what it writes. What that buys is that there is no
    second structure listing which acts have a notice. Four renderers
    write to stderr and they render for far more than four acts, so a
    projection attached per act construction would be a table every one
    of those constructions has to keep in agreement with its renderer,
    and the one left off it would lose its notice silently. Here a
    notice a renderer prints tomorrow is on stderr under both arms with
    nobody attaching anything, `Act` gains no field, and no renderer is
    edited.
    """
    body = act.body(args) if act.body is not None else _NOTHING
    query = act.query(args) if act.query is not None else {}
    with narrated(act.narrates):
        answer = _call(
            reached,
            act.method,
            act.path(args),
            body,
            read_timeout_s=act.read_timeout_s,
            query=query,
        )
    if output is Output.HUMAN:
        act.render(act.read(answer))
        return
    print(encoded(act.answers, answer, act.refusal, output), end="")
    # Flushed before the renderer runs, for the reason the renderers
    # flush between their own two halves: stderr is unbuffered and
    # stdout is not, so a notice would otherwise land above the document
    # it is about.
    sys.stdout.flush()
    with contextlib.redirect_stdout(_DISCARDED):
        act.render(act.read(answer))


def _performed(args: Invocation, acts: "tuple[Act, ...]", reached: Reached) -> None:
    """One invocation's acts, in the order it makes them, stopping at
    the first that is refused.

    Stopping is what makes a sequence honest about what ran: a refused
    read never reaches the second read behind it, because the refusal is
    the whole answer.

    The refusal is raised outside the handler that caught it, the way
    every boundary in this module raises: an exception raised while
    another is being handled carries that one on `__context__` for a
    chain walker to find, and what a refusal quotes is this module's own
    words rather than whatever the failure was carrying.
    """
    problem: str | None = None
    for act in acts:
        try:
            # The default said out loud, because this is where a format
            # a command asked for would be handed on and there is no
            # such format yet: every act of every invocation is rendered
            # for a person.
            _act(args, act, reached, Output.HUMAN)
            continue
        except ConfigError as refused:
            problem = str(refused)
        break
    if problem is not None:
        raise ConfigError(problem)


def _printed(listing: Callable[[Any], str]) -> Callable[[Any], None]:
    """A renderer that answers the whole of its output at once. Each
    listing ends in its own newline, so nothing is added after it."""

    def render(answer: Any) -> None:
        print(listing(answer), end="")

    return render
