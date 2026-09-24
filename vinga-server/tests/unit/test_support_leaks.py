"""What the shared exception walk promises, pinned where the walk lives.

Every suite that asserts a secret is absent from a refusal asserts it
against `leaks.chain`, and none of those suites can fail if the walk
weakens: no exception this server raises carries a value where only the
stronger walk looks, so a walk that stopped reading attributes, or
followed one link where there are two, would leave all of them green.
So each reading the walk promises is pinned here, once, with a sentinel
planted in that place and nowhere else.
"""

from tests.support.leaks import chain, links

SENTINEL = "sk-planted-4f1d9b2e"


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
    first, second = Refusal(), Refusal()
    raised(first, cause=second, context=second)
    raised(second, cause=first, context=first)

    assert SENTINEL not in chain(first)


def test_every_exception_of_a_branching_graph_is_visited_exactly_once() -> None:
    # Two branches from the top that meet again at the bottom, plus a
    # link back up, so both a shared node and a cycle are in the graph.
    # The left branch is `raise ... from error` inside `except error`,
    # the commonest shape there is, which makes one exception both the
    # cause and the context of another.
    top, left, right, bottom = Refusal(), Refusal(), Refusal(), Refusal()
    raised(top, cause=left, context=right)
    raised(left, cause=bottom, context=bottom)
    raised(right, cause=bottom)
    raised(bottom, context=top)

    visited = links(top)

    assert visited[0] is top
    assert sorted(map(id, visited)) == sorted(map(id, (top, left, right, bottom)))
