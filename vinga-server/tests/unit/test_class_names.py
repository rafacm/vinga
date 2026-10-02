"""What this server may call a caught exception's class (#565).

`class_names` holds the rule both paths keep: `ClassName` admits a
value by `is_class_name`, and `failure_name` says a class by it in every
sentence that is not a typed event. The sentinel is a class named like a
credential with a forged log line after it, which `type()` accepts as
readily as any identifier.
"""

import builtins

import pytest

from vinga_server.class_names import UNNAMED_FAILURE, failure_name, is_class_name
from vinga_server.events.values import ClassName, EventValueError

FORGED = type("ghp_Secret\nFORGED line", (Exception,), {})


def _raised(kind: type[BaseException]) -> BaseException:
    """One instance of a shipped exception class, built without its
    arguments where it allows that, since only its class is read."""
    if issubclass(kind, BaseExceptionGroup):
        inner = Exception() if issubclass(kind, Exception) else BaseException()
        return kind("a group", [inner])
    return kind.__new__(kind)


def test_a_lawful_name_is_said_exactly_as_python_spells_it() -> None:
    """Byte for byte what `type(exc).__name__` said, for every exception
    class Python ships, which is what lets a site that spelled that move
    onto the helper without a lawful name reading any differently."""
    shipped = [
        kind
        for kind in vars(builtins).values()
        if isinstance(kind, type) and issubclass(kind, BaseException)
    ]
    assert len(shipped) > 50

    for kind in shipped:
        assert failure_name(_raised(kind)) == kind.__name__


def test_a_name_that_is_not_an_identifier_is_not_said() -> None:
    """The fixed phrase, which carries nothing of the name, and never an
    exception of its own: the caller is in the middle of reporting a
    failure."""
    said = failure_name(FORGED("sk-test-565-never-a-real-credential"))

    assert said == UNNAMED_FAILURE
    assert "ghp_Secret" not in said
    assert "\n" not in said


@pytest.mark.parametrize(
    "text",
    ["", "two words", "ghp_Secret\nFORGED line", "Error\n", "1Error", "Fehleré", "a.b"],
)
def test_the_typed_path_and_the_sentence_path_refuse_the_same_names(text: str) -> None:
    """One rule, read by both: what `is_class_name` refuses, `ClassName`
    refuses too, and the phrase that stands in for it is itself
    refused, so it can never pass for a class on the typed path."""
    assert not is_class_name(text)
    with pytest.raises(EventValueError):
        ClassName(text)
    assert not is_class_name(UNNAMED_FAILURE)


@pytest.mark.parametrize("text", ["Error", "_Private", "HTTPError2", "x"])
def test_the_typed_path_and_the_sentence_path_admit_the_same_names(text: str) -> None:
    assert is_class_name(text)
    assert ClassName(text).carried() == text
