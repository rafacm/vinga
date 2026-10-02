"""Every caught exception's class is named through one helper (#565).

A class can be given any name at all: `type(name, (Exception,), {})`
accepts any string, a line break and a forged log line after it
included. The typed event path has refused such a name since #217,
through `ClassName`; the sites that put a class into a retained log
line, a CLI sentence or an exception's message used to spell
`type(exc).__name__` and print whatever it held. They ask
`class_names.failure_name` now, which answers a lawful name exactly
as Python spells it and a fixed phrase for anything else.

Three representative sites are driven end to end here, one per kind of
surface: a log line (`device/placement.py`), an exception message
(`providers/kit.py`) and a CLI sentence (`device_endpoint.py`). Each is
pinned for a lawful name first, byte for byte, because the sweep that
moved them must not have changed what an operator reads on any
ordinary day, and then driven with the forged name.

What keeps the sweep swept is the guard at the end: an AST walk over
the production package that finds every `type(<x>).__name__` and every
`<x>.__class__.__name__` (and their `__qualname__` spellings) by shape,
whatever the variable is called, and holds the set to a written-down
allowlist. Two deliberate limits, stated rather than discovered later:

- A class reached any other way passes: `kind = type(exc)` and then
  `kind.__name__` two lines later, or `getattr(type(exc), "__name__")`.
  Nothing in the package does either, and following a value through
  assignments is a data-flow analysis rather than a guard.
- The scan is of the production package. Tests build forged classes on
  purpose, which is how this file plants the name it checks.
"""

import ast
import logging
from pathlib import Path

import pytest

import vinga_server
from vinga_server.class_names import UNNAMED_FAILURE
from vinga_server.device.placement import DevicePlacements
from vinga_server.device_endpoint import close_failed
from vinga_server.providers.kit import call_failure
from vinga_server.tools import builtin

# A class named like a credential with a forged log line after it. The
# message is credential-shaped as well, so a site that printed the
# exception rather than its class would show up too.
FORGED = type("ghp_Secret\nFORGED line", (RuntimeError,), {})
PLANTED = "sk-test-565-never-a-real-credential"


def _either(forged: bool) -> BaseException:
    return FORGED(PLANTED) if forged else RuntimeError(PLANTED)


def _named(forged: bool) -> str:
    return UNNAMED_FAILURE if forged else "RuntimeError"


def _clean(said: str) -> None:
    assert "\n" not in said
    assert "ghp_Secret" not in said
    assert "FORGED" not in said
    assert PLANTED not in said


# --- a retained log line ----------------------------------------------


class _RefusingStore:
    """A configuration store whose relocation raises what it was given."""

    def __init__(self, failure: BaseException) -> None:
        self._failure = failure

    def relocate_device_by_id(self, device: str, location: str) -> object:
        raise self._failure


@pytest.mark.parametrize("forged", [False, True], ids=["lawful", "forged"])
async def test_a_failed_relocation_logs_a_validated_class_name(
    forged: bool, caplog: pytest.LogCaptureFixture
) -> None:
    placements = DevicePlacements(_RefusingStore(_either(forged)))  # type: ignore[arg-type]

    with caplog.at_level(logging.WARNING), pytest.raises(ValueError) as caught:
        await placements.relocate("aa:bb:cc:dd:ee:ff", "the kitchen")

    assert str(caught.value) == builtin.PLACEMENT_FAILED
    [record] = [r for r in caplog.records if r.name == "vinga_server.device.placement"]
    assert record.msg == "a device relocation failed: %s"
    assert record.args == (_named(forged),)
    _clean(record.getMessage())


class _NamedByNumber(type):
    @property
    def __name__(cls) -> object:  # type: ignore[override]
        return 7


class _NamedByRaising(type):
    @property
    def __name__(cls) -> object:  # type: ignore[override]
        raise RuntimeError(PLANTED)


@pytest.mark.parametrize(
    "kind",
    [
        pytest.param(_NamedByNumber("Numbered", (RuntimeError,), {}), id="a-number"),
        pytest.param(_NamedByRaising("Raising", (RuntimeError,), {}), id="a-raising-lookup"),
    ],
)
async def test_a_class_whose_name_cannot_be_read_still_gets_the_refusal(
    kind: type, caplog: pytest.LogCaptureFixture
) -> None:
    """A metaclass decides what `__name__` answers (#565's review round).
    Whatever it answers, the site still refuses with its own sentence,
    raised outside the arm and so carrying no chain, and logs the fixed
    phrase. A helper that raised inside the arm would instead escape
    with the planted failure as its `__context__`."""
    placements = DevicePlacements(_RefusingStore(kind(PLANTED)))  # type: ignore[arg-type]

    escaped: type[BaseException] | None = None
    refusal: BaseException | None = None
    with caplog.at_level(logging.WARNING):
        try:
            await placements.relocate("aa:bb:cc:dd:ee:ff", "the kitchen")
        except ValueError as raised:
            refusal = raised
        except Exception as raised:  # noqa: BLE001 - reported by its class below
            escaped = raised.__class__
    if escaped is not None:
        # Outside the arm, and by the escaped class alone: pytest's own
        # report would walk the chain into the class it cannot name.
        pytest.fail(f"the relocation escaped with {escaped.__qualname__}")

    assert refusal is not None
    assert str(refusal) == builtin.PLACEMENT_FAILED
    assert refusal.__context__ is None
    assert refusal.__cause__ is None
    [record] = [r for r in caplog.records if r.name == "vinga_server.device.placement"]
    assert record.args == (UNNAMED_FAILURE,)
    _clean(record.getMessage())


# --- an exception's message, rendered later ---------------------------


@pytest.mark.parametrize("forged", [False, True], ids=["lawful", "forged"])
def test_a_provider_call_failure_names_a_validated_class(forged: bool) -> None:
    failure = call_failure("llm openai", _either(forged))

    assert str(failure) == f"llm openai: the request failed with {_named(forged)}"
    _clean(str(failure))


# --- a CLI sentence ---------------------------------------------------


class _UnclosableClient:
    """An HTTP client whose close raises what it was given."""

    def __init__(self, failure: BaseException) -> None:
        self._failure = failure

    def close(self) -> None:
        raise self._failure


@pytest.mark.parametrize("forged", [False, True], ids=["lawful", "forged"])
def test_a_connection_that_would_not_close_names_a_validated_class(forged: bool) -> None:
    said = close_failed(_UnclosableClient(_either(forged)), "http://vinga.example:8000")  # type: ignore[arg-type]

    assert said == (
        f"http://vinga.example:8000 answered, but the connection to it could not be closed "
        f"({_named(forged)}), so no verdict is printed: a probe that did not "
        f"finish cleanly is not one to call an endpoint healthy from. What the "
        f"library said is not repeated here."
    )
    assert said is not None
    _clean(said)


# --- and nowhere else -------------------------------------------------


PACKAGE = Path(vinga_server.__file__).parent

# Every place the package may read a type's name directly, as (file,
# enclosing definition, the expression whose type is named). The set is
# held exactly: a new site fails, and so does an entry here that no
# longer matches anything, because a stale allowlist is worth less than
# none.
ALLOWED = {
    # The one read the rule is concentrated into. `class_name_of`
    # contains a lookup that raises and refuses anything but a plain
    # identifier; `failure_name` and `ClassName.of` both ask it.
    ("class_names.py", "class_name_of", "failure"),
    # Program types, which #565 puts out of scope: none of these is a
    # caught exception, and each is a class this server's own code or
    # its parsers made.
    #
    # A configured provider's factory answered something that is not a
    # provider, and which class it built is the whole of the bug report.
    ("providers/registry.py", "construct_provider", "provider"),
    # An event variant naming itself in a catalog refusal.
    ("events/catalog.py", "Variant.verify", "self"),
    # An event tap this server's composition attached, named when it
    # breaks; the exception it raised is deliberately not even bound.
    ("events/__init__.py", "_offer", "tap"),
    # The shape a parsed configuration document has where a mapping was
    # wanted: `dict`, `list`, `str` and the other types a YAML or JSON
    # parser builds.
    ("config/loader.py", "_check_config_file", "data"),
    ("config/store.py", "_readable", "fragment"),
    ("config/transport.py", "untransportable", "key"),
    ("config/transport.py", "untransportable", "value"),
}

NAME_ATTRIBUTES = frozenset({"__name__", "__qualname__"})


def type_name_reads(tree: ast.AST) -> list[tuple[str, str, int]]:
    """Every direct read of a type's name in `tree`, as (enclosing
    definition, the expression whose type is named, line)."""
    found: list[tuple[str, str, int]] = []

    def visit(node: ast.AST, scope: tuple[str, ...]) -> None:
        for child in ast.iter_child_nodes(node):
            inner = scope
            if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                inner = (*scope, child.name)
            if isinstance(child, ast.Attribute) and child.attr in NAME_ATTRIBUTES:
                of = child.value
                named: ast.expr | None = None
                if (
                    isinstance(of, ast.Call)
                    and isinstance(of.func, ast.Name)
                    and of.func.id == "type"
                    and len(of.args) == 1
                ):
                    named = of.args[0]
                elif isinstance(of, ast.Attribute) and of.attr == "__class__":
                    named = of.value
                if named is not None:
                    found.append((".".join(scope), ast.unparse(named), child.lineno))
            visit(child, inner)

    visit(tree, ())
    return found


def reads_in_package() -> dict[tuple[str, str, str], list[int]]:
    reads: dict[tuple[str, str, str], list[int]] = {}
    for path in sorted(PACKAGE.rglob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for scope, named, line in type_name_reads(tree):
            key = (path.relative_to(PACKAGE).as_posix(), scope, named)
            reads.setdefault(key, []).append(line)
    return reads


def test_a_caught_exception_s_class_is_named_only_through_the_helper() -> None:
    reads = reads_in_package()

    unexplained = {key: lines for key, lines in reads.items() if key not in ALLOWED}
    assert unexplained == {}, (
        "name a caught exception's class with class_names.failure_name, or "
        "explain a program type in ALLOWED"
    )
    assert set(reads) == ALLOWED
    assert all(len(lines) == 1 for lines in reads.values())


@pytest.mark.parametrize(
    "spelling",
    [
        "type(exc).__name__",
        "type(problem).__qualname__",
        "exc.__class__.__name__",
        "self._failure.__class__.__name__",
        "type(task.exception()).__name__",
    ],
)
def test_the_walk_finds_a_read_by_its_shape_and_not_its_name(spelling: str) -> None:
    """The variable is anything at all. Matching on a variable's name
    instead is the weakness #531 found in this repository's own test
    walkers."""
    tree = ast.parse(f"def report(exc, problem, task):\n    log({spelling})\n")

    [(scope, _, line)] = type_name_reads(tree)

    assert (scope, line) == ("report", 2)


def test_the_walk_ignores_a_name_that_is_not_a_type_s() -> None:
    tree = ast.parse("logger = getLogger(__name__)\nkind.__name__\ntype(a, b, c).__name__\n")

    assert type_name_reads(tree) == []
