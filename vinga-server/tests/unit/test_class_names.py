"""What this server may call a caught exception's class (#565).

`class_names` holds the rule both paths keep: `ClassName` admits a
value by `is_class_name`, and `failure_name` says a class by it in every
sentence that is not a typed event. The sentinel is a class named like a
credential with a forged log line after it, which `type()` accepts as
readily as any identifier.
"""

import builtins
import logging

import pytest

from vinga_server.class_names import UNNAMED_FAILURE, failure_name, is_class_name
from vinga_server.events import REFUSAL_MESSAGE, UNBUILT_LABEL, ServerEvents
from vinga_server.events.catalog import MCP_CHANNEL, McpCallDropped
from vinga_server.events.values import (
    ClassName,
    ClassNames,
    Count,
    EventValueError,
    Identifier,
    failure_class,
)
from vinga_server.logs import TEXT_FORMAT, JsonFormatter

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


# --- a class whose name is not even a string --------------------------
#
# A metaclass decides what `__name__` answers, so the name can be a
# number, a `str` subclass with its own idea of how it prints, or a
# lookup that raises (#565's review round). The helpers are called from
# inside an `except` arm, where anything they raised would carry the
# exception being reported as its `__context__`, credential-shaped
# message and all. So each of these is driven from inside one.

PLANTED = "sk-test-565-never-a-real-credential"


class _Printing(str):
    """A name that is an identifier until somebody prints it."""

    def __str__(self) -> str:
        return "Fine\nFORGED line"

    def __format__(self, spec: str) -> str:
        return "Fine\nFORGED line"


class _NamedByNumber(type):
    @property
    def __name__(cls) -> object:  # type: ignore[override]
        return 7


class _NamedBySubclass(type):
    @property
    def __name__(cls) -> object:  # type: ignore[override]
        return _Printing("Fine")


class _NamedByRaising(type):
    @property
    def __name__(cls) -> object:  # type: ignore[override]
        raise RuntimeError(PLANTED)


UNNAMEABLE = [
    pytest.param(_NamedByNumber("Numbered", (Exception,), {}), id="a-number"),
    pytest.param(_NamedBySubclass("Subclassed", (Exception,), {}), id="a-str-subclass"),
    pytest.param(_NamedByRaising("Raising", (Exception,), {}), id="a-raising-lookup"),
]


def _reported_from_an_except_arm(kind: type) -> tuple[str, object]:
    """Both helpers' answers about a failure of this class, asked the
    way every site asks: inside the arm that caught it.

    Anything either helper raised is turned into a test failure here,
    naming only its own (builtin) class, because the report pytest
    would otherwise render walks the chain into the very class whose
    name cannot be read."""
    escaped: type[BaseException] | None = None
    try:
        raise kind(PLANTED)
    except Exception as caught:
        try:
            return failure_name(caught), failure_class(caught)
        except Exception as raised:
            escaped = raised.__class__
    pytest.fail(f"a helper raised {escaped.__qualname__} while reporting a failure")


@pytest.mark.parametrize("kind", UNNAMEABLE)
def test_a_class_whose_name_is_not_a_plain_string_is_not_said(kind: type) -> None:
    said, valued = _reported_from_an_except_arm(kind)

    assert said == UNNAMED_FAILURE
    assert valued is None


@pytest.mark.parametrize("kind", UNNAMEABLE)
def test_the_typed_constructor_refuses_it_as_a_value_refusal(kind: type) -> None:
    """`ClassName.of` refuses with its own `EventValueError`, the one
    refusal the emitter's guard reports by a fixed label, rather than
    with whatever the lookup raised."""
    failure = kind(PLANTED)
    refused: BaseException | None = None
    try:
        ClassName.of(failure)
    except BaseException as raised:  # noqa: BLE001 - the class is the assertion
        refused = raised

    assert refused.__class__ is EventValueError
    assert PLANTED not in str(refused)
    assert refused.__context__ is None


def test_a_name_that_is_a_str_subclass_is_refused_as_text() -> None:
    assert not is_class_name(_Printing("Fine"))
    assert not is_class_name(7)  # type: ignore[arg-type]


# --- and the joined form reaches the log as plain text ----------------


@pytest.mark.parametrize(
    "text",
    [pytest.param("Fine", id="one-name"), pytest.param("Fine, Other", id="joined")],
)
@pytest.mark.usefixtures("refusals_are_expected")
def test_a_str_subclass_never_reaches_the_log_as_a_class_name(
    text: str, caplog: pytest.LogCaptureFixture
) -> None:
    """`ClassNames` splits a joined value into plain strings to check
    each part, so the check passing said nothing about the object it
    kept (#565's second review round). Through the real emitter and the
    log formats this server ships, a name that prints as a forged line
    is refused, reported by its fixed label, and never rendered."""
    with caplog.at_level(logging.DEBUG):
        ServerEvents(MCP_CHANNEL).emit(
            lambda: McpCallDropped(
                entry=Identifier("files"),
                position=Count(1),
                error=ClassNames(_Printing(text)),
            )
        )

    rendered = "\n".join(
        formatter.format(record)
        for record in caplog.records
        for formatter in (logging.Formatter(TEXT_FORMAT), JsonFormatter())
    )
    assert "FORGED" not in rendered
    assert [(record.msg, record.args) for record in caplog.records] == [
        (REFUSAL_MESSAGE, (UNBUILT_LABEL, "construction_failed"))
    ]

