"""What the shared exception walk promises, pinned where the walk lives.

The suites whose exception surface is `leaks.chain` assert a secret
absent from a refusal against it, and none of them can fail if the walk
weakens: no exception this server raises carries a value where only the
stronger walk looks, so a walk that stopped reading attributes, or
followed one link where there are two, would leave all of them green.
So each reading the walk promises is pinned here, once, with a sentinel
planted in that place and nowhere else.

Not every secret-absence assertion about an exception goes through
`chain`. `test_mcp_composed_reference.py`'s `chained` keeps a renderer
of its own, each exception's formatted traceback and its `repr`,
because a traceback's source lines and frames are a surface no
rendering of the exception reproduces; it reuses only the traversal,
`links`. What these pins hold for it is that traversal, pinned below,
and not its rendering.
"""

import os
import subprocess
import sys
from pathlib import Path

import pytest

from tests.support.leaks import chain, links

SENTINEL = "sk-planted-4f1d9b2e"

# The cycle case, run in a child process of its own. A walk that lost
# its seen set would loop for ever on this graph, and in-process that is
# a test that never returns: a wedged xdist worker rather than a
# failure, since the suite has no per-test timeout. In a child it is a
# process this file can stop. The child exits 0 only when the walk
# returned and read nothing it should not have.
CYCLE = f"""
from tests.support.leaks import chain

first, second = Exception("first"), Exception("second")
first.__cause__ = first.__context__ = second
second.__cause__ = second.__context__ = first
if {SENTINEL!r} in chain(first):
    raise SystemExit("the walk read a value nothing planted")
"""

# How long the child gets. It spends about half a second idle, most of
# it importing, so this is twenty times that for a loaded runner, and
# still a bound: the case fails at it rather than hanging. Not longer,
# because a walk that lost its seen set also grows its pending list
# without end, measured at about 40 MB a second, and the bound is what
# caps that too.
CYCLE_BOUND_S = 10.0

# Where `tests.support.leaks` is importable from.
SERVER_ROOT = Path(__file__).resolve().parents[2]


class Refusal(Exception):
    """An exception whose own text says nothing."""

    def __str__(self) -> str:
        return "a refusal that quotes nothing"

    def __repr__(self) -> str:
        return "Refusal()"


class Mark:
    """The PyYAML mark shape: an object hung off an exception, whose
    `buffer` is the whole source that was being parsed."""

    def __init__(self, buffer: str) -> None:
        self.buffer = buffer

    def __repr__(self) -> str:
        return "<Mark>"


class SaysOnlyInRepr(Exception):
    """An exception whose `repr` alone carries the value: no arguments,
    no attributes, and a `str` that says nothing."""

    def __str__(self) -> str:
        return "a refusal that quotes nothing"

    def __repr__(self) -> str:
        return f"SaysOnlyInRepr({SENTINEL!r})"


class SaysOnlyInStr(Exception):
    """The other way round: its `str` carries the value and its `repr`
    does not."""

    def __str__(self) -> str:
        return SENTINEL

    def __repr__(self) -> str:
        return "SaysOnlyInStr()"


class Masked:
    """An argument whose `repr` says what its `str` does not, the mirror
    of `Revealing` below."""

    def __str__(self) -> str:
        return "masked"

    def __repr__(self) -> str:
        return f"Masked({SENTINEL!r})"


class Revealing:
    """An argument whose `str` says what its `repr` does not."""

    def __str__(self) -> str:
        return SENTINEL

    def __repr__(self) -> str:
        return "Revealing()"


def raised(outer: BaseException, *, cause=None, context=None) -> BaseException:
    """`outer` as it is after being raised with these links."""
    outer.__cause__ = cause
    outer.__context__ = context
    return outer


def test_an_attribute_of_the_exception_is_read() -> None:
    refusal = Refusal()
    refusal.detail = SENTINEL

    assert SENTINEL in chain(refusal)


def test_an_attribute_of_an_object_the_exception_holds_is_read() -> None:
    refusal = Refusal()
    refusal.problem_mark = Mark(f"key: {SENTINEL}\n")

    assert SENTINEL in chain(refusal)


def test_the_name_of_an_attribute_of_the_exception_is_read() -> None:
    refusal = Refusal()
    setattr(refusal, SENTINEL, None)

    assert SENTINEL in chain(refusal)


def test_the_name_of_an_attribute_of_a_held_object_is_read() -> None:
    held = Mark("")
    setattr(held, SENTINEL, None)
    refusal = Refusal()
    refusal.problem_mark = held

    assert SENTINEL in chain(refusal)


def test_an_argument_whose_str_reveals_what_its_repr_hides_is_read() -> None:
    # Two arguments, so the exception's own str is the tuple's repr and
    # the only place the value shows is the argument's own str.
    refusal = ValueError("a sentence", Revealing())

    assert SENTINEL not in repr(refusal)
    assert SENTINEL not in str(refusal)
    assert SENTINEL in chain(refusal)


def test_the_repr_of_the_exception_is_read() -> None:
    assert SENTINEL in chain(SaysOnlyInRepr())


def test_the_str_of_the_exception_is_read() -> None:
    assert SENTINEL in chain(SaysOnlyInStr())


def test_an_argument_whose_repr_reveals_what_its_str_hides_is_read() -> None:
    # Raised on a `Refusal`, whose own repr and str are fixed, so the
    # only rendering that reaches the argument's repr is the arguments
    # tuple's.
    refusal = Refusal("a sentence", Masked())

    assert SENTINEL not in repr(refusal)
    assert SENTINEL not in str(refusal)
    assert SENTINEL in chain(refusal)


def test_the_cause_of_an_exception_is_read() -> None:
    refusal = raised(Refusal(), cause=ValueError(SENTINEL))

    assert SENTINEL in chain(refusal)


def test_the_context_of_an_exception_is_read() -> None:
    refusal = raised(Refusal(), context=ValueError(SENTINEL))

    assert SENTINEL in chain(refusal)


def test_a_context_is_read_when_the_exception_has_a_cause_as_well() -> None:
    refusal = raised(Refusal(), cause=Refusal(), context=ValueError(SENTINEL))

    assert SENTINEL in chain(refusal)


def test_a_graph_with_a_cycle_through_both_links_ends() -> None:
    child = subprocess.Popen(
        [sys.executable, "-c", CYCLE],
        cwd=SERVER_ROOT,
        env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1"},
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    try:
        _, errors = child.communicate(timeout=CYCLE_BOUND_S)
    except subprocess.TimeoutExpired:
        child.terminate()
        child.communicate()
        pytest.fail(f"the walk of a cyclic graph did not return within {CYCLE_BOUND_S} s")

    assert child.returncode == 0, errors


def test_every_exception_of_a_branching_graph_is_visited_exactly_once() -> None:
    # Two branches from the top that meet again at the bottom, so one
    # exception is reachable three ways. The left branch is `raise ...
    # from error` inside `except error`, the commonest shape there is,
    # which makes one exception both the cause and the context of
    # another. No cycle, on purpose: without its seen set the walk
    # still ends here, visiting the bottom three times, so this fails
    # rather than hangs. Termination is the cycle case's, bounded above.
    top, left, right, bottom = Refusal(), Refusal(), Refusal(), Refusal()
    raised(top, cause=left, context=right)
    raised(left, cause=bottom, context=bottom)
    raised(right, cause=bottom)

    visited = links(top)

    assert visited[0] is top
    assert sorted(map(id, visited)) == sorted(map(id, (top, left, right, bottom)))
