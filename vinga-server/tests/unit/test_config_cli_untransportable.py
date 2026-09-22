"""What a fragment JSON cannot carry is told, and what it is not told.

The refusal that runs in front of validation is the one with the least
to go on: it is reached with a value nothing in this deployment has
looked at, in a document whose keys are bytes somebody wrote, addressed
by an identity that arrived on the command line. Every one of those is
a place a credential lands when it is pasted a line early, and the
mistake that produces this refusal most often is exactly that paste.

So the sentence names a fixed section, a fixed word for a field, and
list positions, and nothing else. This file plants a distinct
credential-shaped value in every field that could carry one, one per
field so a leak names its own source, and asserts absence on every
surface the refusal could reach: the two streams, the request the
client would have sent (its body and its headers), the log records
whole, and the exception chain a walker would find.

The request recorder is vacuous today, and deliberately kept: the check
runs before anything is sent, so there is nothing in it. If that order
ever changed, the fragment would be in a body and this is what would
say so.
"""

import ast
import io
import json
from collections.abc import Callable, Iterator
from pathlib import Path

import httpx
import pytest
from cryptography.fernet import Fernet, MultiFernet

from tests.support.config_cli import chain, logged, runner
from vinga_server.config import store as config_store
from vinga_server.config import transport
from vinga_server.config.cli import acts, deployment, entities, grammar, invocation, reach
from vinga_server.config.loader import ConfigError
from vinga_server.config.models import DatabaseConfig
from vinga_server.config.secrets import generate_key
from vinga_server.db import open_database

# One per field, none a real credential, each shaped so a substring
# check for it cannot match by accident.
STAGE_SENTINEL = "sk-stage-0d1e2f-never-a-real-credential"
NAME_SENTINEL = "sk-name-3a4b5c-never-a-real-credential"
KEY_SENTINEL = "api_key_sk-key-6d7e8f-never-a-real-credential"
NESTED_KEY_SENTINEL = "token_sk-nested-9a0b1c-never-a-real-credential"
VALUE_SENTINEL = "sk-value-2d3e4f-never-a-real-credential"

SENTINELS = (
    STAGE_SENTINEL,
    NAME_SENTINEL,
    KEY_SENTINEL,
    NESTED_KEY_SENTINEL,
    VALUE_SENTINEL,
)


@pytest.fixture
def run(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[Callable[..., int]]:
    """One command, against a server of this test's own, with every
    request it would have sent recorded."""
    driver = runner(monkeypatch)
    sent: list[httpx.Request] = []
    built = reach.build_client

    def recording(base_url: str, token: str) -> object:
        client = built(base_url, token)
        client.event_hooks["request"] = [sent.append]
        return client

    monkeypatch.setattr(reach, "build_client", recording)
    driver.sent = sent
    yield driver


def _requests(sent: list[httpx.Request]) -> str:
    """Everything the client put on the wire, as anything reading it
    would: the method and the URL, every header including the bearer
    token's own, and the body."""
    return "\n".join(
        "\n".join(
            [
                f"{request.method} {request.url}",
                "\n".join(f"{name}: {value}" for name, value in request.headers.items()),
                request.content.decode("utf-8", "replace"),
            ]
        )
        for request in sent
    )


# A fragment carrying an untransportable value under a credential-shaped
# key, at two depths: directly, and inside a list, which is the path a
# structural position has to describe.
FLAT = f"type: anthropic\n{KEY_SENTINEL}: 2026-01-01\n"
NESTED = (
    "type: anthropic\n"
    "options:\n"
    "  - a: 1\n"
    f"  - {NESTED_KEY_SENTINEL}: 2026-01-01\n"
)
UNDER_A_VALUE = f"type: anthropic\n{KEY_SENTINEL}:\n  - !!binary |\n    AAEC\n"


@pytest.mark.parametrize(
    ("what", "fragment"),
    [("a flat key", FLAT), ("inside a list", NESTED), ("under a value", UNDER_A_VALUE)],
)
def test_the_refusal_names_no_key_and_no_identity(
    run: Callable[..., int],
    capsys: pytest.CaptureFixture[str],
    caplog: pytest.LogCaptureFixture,
    what: str,
    fragment: str,
) -> None:
    with caplog.at_level(0):
        exit_code = run(
            "provider", "set", STAGE_SENTINEL, NAME_SENTINEL, "-f", "-", stdin=fragment
        )

    assert exit_code == 1, what
    captured = capsys.readouterr()
    assert "JSON has no way to write" in captured.err, (what, captured.err)
    assert "Traceback" not in captured.err, what

    surfaces = {
        "stdout": captured.out,
        "stderr": captured.err,
        "requests": _requests(run.sent),
        "logs": logged(caplog),
    }
    for sentinel in SENTINELS:
        for where, surface in surfaces.items():
            assert sentinel not in surface, (what, where, sentinel)

    # And nothing was sent at all, which is why the request surface
    # above is empty rather than merely clean.
    assert run.sent == [], what


def test_the_refusal_says_where_structurally(
    run: Callable[..., int], capsys: pytest.CaptureFixture[str]
) -> None:
    """What is left after the keys go: the section, the fixed field
    word, and the positions. An operator can count the steps to the
    value; a log holding the line holds nothing of it."""
    assert run("provider", "set", "llm", "claude", "-f", "-", stdin=NESTED) == 1

    said = capsys.readouterr().err
    assert said.startswith("invalid providers:"), said
    # `options` is a field, its second entry is position 1, and the key
    # under that entry is a field again.
    assert f"the fragment.{transport.FIELD}.1.{transport.FIELD}" in said, said


def test_the_section_is_the_whole_of_what_is_addressed(
    run: Callable[..., int], capsys: pytest.CaptureFixture[str]
) -> None:
    """The refusal names the section and stops. It used to name
    `providers.<stage>.<name>`, built out of the two words the command
    line carried."""
    assert run("provider", "set", STAGE_SENTINEL, NAME_SENTINEL, "-f", "-", stdin=FLAT) == 1

    said = capsys.readouterr().err
    assert said.startswith("invalid providers:"), said
    assert "providers." not in said, said


def test_the_refusal_carries_no_chain_holding_the_fragment() -> None:
    """The fourth surface, read where a walker would find it. Driven at
    the boundary because `cli.main` prints the sentence and returns, so
    the exception is not reachable through it."""
    fragment = {
        KEY_SENTINEL: {NESTED_KEY_SENTINEL: {VALUE_SENTINEL}},
    }

    with pytest.raises(ConfigError) as refused:
        transport.check_transportable("providers", fragment)

    walked = chain(refused.value)
    for sentinel in (KEY_SENTINEL, NESTED_KEY_SENTINEL, VALUE_SENTINEL):
        assert sentinel not in walked, sentinel
    assert refused.value.__cause__ is None
    assert refused.value.__context__ is None


def test_the_stored_row_walk_names_no_key_either() -> None:
    """The other caller of the same walk. A stored row is asked about
    its numbers only, and the path it reports is built the same way, so
    a hand-edited row holding a credential-shaped key does not put that
    key in a storage failure."""
    problem = transport.untransportable(
        {KEY_SENTINEL: [{NESTED_KEY_SENTINEL: float("nan")}]}, numbers_only=True
    )

    assert problem is not None
    assert "not a finite number" in problem
    assert KEY_SENTINEL not in problem
    assert NESTED_KEY_SENTINEL not in problem
    assert f"the fragment.{transport.FIELD}.0.{transport.FIELD}" in problem


# What every production caller passes, held two ways
#
# The round that produced this file left one hole, and the re-review
# found it: the vocabulary was checked and the CALLERS were not, so a
# call site that went back to passing `providers.<stage>.<name>` stayed
# green. Both halves are here now. The walk reads what is written, which
# catches a reintroduced address the moment it is typed even on a path
# no test drives; the spies read what arrives, which catches an address
# assembled somewhere the walk cannot see.

SOURCE = Path(__file__).resolve().parents[2] / "src" / "vinga_server"

CLI_PACKAGE = SOURCE / "config" / "cli"

# The package's own modules, as filenames, so the walk below can say
# "the CLI, wherever in it" without naming a module of it.
_CLI_MODULES = frozenset(path.name for path in CLI_PACKAGE.glob("*.py"))

GUARDED = "check_transportable"

# The argument expressions a call to it may pass, as they are written.
# A closed set of source text rather than a rule about shapes: the
# question here is what a reviewer would read on the line, and three
# spellings is a short enough list to say out loud.
#
# `APPLY_LOCATION` is the applied document's own fixed word.
# `descriptor.moved_key` is a section this repository declared on a
# registry entry, which no caller can influence.
FIXED_ARGUMENTS = frozenset(
    {
        "APPLY_LOCATION",
        "transport.APPLY_LOCATION",
        "descriptor.moved_key",
    }
)


def _calls(tree: ast.AST, name: str) -> list[ast.Call]:
    """Every call to one function in a module, however it is spelled."""
    found = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        called = node.func
        if isinstance(called, ast.Attribute) and called.attr == name:
            found.append(node)
        elif isinstance(called, ast.Name) and called.id == name:
            found.append(node)
    return found


def _enclosing(tree: ast.AST, call: ast.Call) -> ast.FunctionDef | None:
    """The function a call sits inside, which is what a forwarded
    argument has to be resolved against."""
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and any(
            inner is call for inner in ast.walk(node)
        ):
            return node
    return None


def _forwarded(tree: ast.AST, holder: ast.FunctionDef, parameter: str) -> list[str]:
    """What every caller of `holder` puts in the position `parameter`
    occupies, as written.

    One hop, which is all this tree has: the store's `_readable` takes
    the section and hands it on, so a guard that stopped at the direct
    call would be reading a parameter name and calling it fixed.
    """
    names = [argument.arg for argument in holder.args.args]
    position = names.index(parameter)
    passed = []
    for call in _calls(tree, holder.name):
        for keyword in call.keywords:
            if keyword.arg == parameter:
                passed.append(ast.unparse(keyword.value))
                break
        else:
            passed.append(
                ast.unparse(call.args[position]) if position < len(call.args) else "<absent>"
            )
    return passed or ["<no caller found>"]


def _sections_passed() -> dict[str, list[str]]:
    """Every production call to the guard, and the section expression it
    receives, resolved through one forwarding hop."""
    received: dict[str, list[str]] = {}
    for path in sorted(SOURCE.rglob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for call in _calls(tree, GUARDED):
            if not call.args:
                received.setdefault(path.name, []).append("<no argument>")
                continue
            written = ast.unparse(call.args[0])
            if written in FIXED_ARGUMENTS or written.startswith("'"):
                received.setdefault(path.name, []).append(written)
                continue
            holder = _enclosing(tree, call)
            if holder is None or written not in [a.arg for a in holder.args.args]:
                received.setdefault(path.name, []).append(written)
                continue
            received.setdefault(path.name, []).extend(_forwarded(tree, holder, written))
    return received


def test_every_written_call_passes_a_fixed_section() -> None:
    """The static half: what the source says, on every path, driven or
    not.

    The client side is stated over the registry below rather than over a
    filename: which module of the CLI package holds a body is that
    package's business, and a test that named one would break on the day
    it moved while proving nothing about the guard. What is named here
    is the repository's own caller, which is one file and stays one.

    A call site that disappeared fails here too: a walk that finds
    nothing is a guard that proves nothing.
    """
    received = _sections_passed()

    assert "store.py" in received, received
    assert set(received) - _CLI_MODULES == {"store.py"}, received
    for module, expressions in received.items():
        for written in expressions:
            assert written in FIXED_ARGUMENTS, (module, written)


def test_the_walk_would_see_an_address_if_one_came_back() -> None:
    """The walk, held to biting.

    A guard over source text is worth exactly what it rejects, so it is
    shown rejecting the expression this finding was about: the addressed
    form the CLI used to build, and the parameter name a forwarding hop
    would otherwise have been mistaken for a fixed word.
    """
    for reintroduced in (
        "'.'.join((descriptor.moved_key, *_identity(descriptor, args)))",
        "location",
        "f'{descriptor.moved_key}.{name}'",
    ):
        assert reintroduced not in FIXED_ARGUMENTS


# Every body the registry carries, and which of them parse YAML
#
# The property this file used to state was a filename: the guarded call
# sites are exactly `{"cli.py", "store.py"}`. That was true of a tree
# with one CLI module in it and says nothing about what the guard is
# for, which is that a fragment somebody wrote is refused before it
# travels.
#
# So the client side is derived instead. The CLI calls its YAML parser
# in exactly one place, and a body that cannot reach that parser cannot
# be handed a value YAML says and JSON cannot: `_binding`, `_new_name`,
# `_secret_body` and their like build a scalar or a record out of
# arguments and carry nothing to smuggle. The set that CAN reach it is
# read off the call graph and pinned, so a new YAML-derived body is a
# diff line here rather than a silent widening, and every member of it
# is asserted to reach the guard.
#
# Reachability is not order, which is the half a call graph cannot
# answer: a guard in an unreachable branch, or one after an early
# return, reaches just as well and runs never. So the ordering is proven
# at run time, per discovered member, by driving the act and watching
# the request not be made.

PARSE_SITE = "yaml.safe_load"


def _module_trees() -> dict[str, ast.Module]:
    return {
        path.name: ast.parse(path.read_text(encoding="utf-8"))
        for path in sorted(CLI_PACKAGE.glob("*.py"))
    }


_TREES = _module_trees()

# Every function node of the package by (file, first line), which is how
# a callable the registry holds is resolved to its source, and the
# top-level definition each of them sits in, which is what names it.
_NODES: dict[tuple[str, int], ast.AST] = {}
_NAMED: dict[int, str] = {}
for _name, _tree in _TREES.items():
    for _top in _tree.body:
        if not isinstance(_top, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        for _inner in ast.walk(_top):
            if isinstance(_inner, (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda)):
                _NODES.setdefault((_name, _inner.lineno), _inner)
                _NAMED.setdefault(id(_inner), _top.name)

# Every top-level function of the package by name, which is what a bare
# call resolves through. The names are unique across the package, which
# the AST-identity run that landed the split reported.
_TOP: dict[str, tuple[str, ast.AST]] = {
    node.name: (module, node)
    for module, tree in _TREES.items()
    for node in tree.body
    if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
}


def _node_of(called: object) -> ast.AST | None:
    """The source of one callable the registry holds."""
    code = getattr(called, "__code__", None)
    if code is None:
        return None
    return _NODES.get((Path(code.co_filename).name, code.co_firstlineno))


def _reaches(node: ast.AST, target: str, seen: set[int] | None = None) -> bool:
    """Whether one callable can reach a name by following its calls.

    A bare call resolves to the package's own definition of that name; a
    dotted one is compared as it is written, which is how the parser
    site (`yaml.safe_load`) is recognized without resolving the library.
    """
    seen = set() if seen is None else seen
    if id(node) in seen:
        return False
    seen.add(id(node))
    for inner in ast.walk(node):
        if not isinstance(inner, ast.Call):
            continue
        called = inner.func
        if isinstance(called, ast.Attribute) and isinstance(called.value, ast.Name):
            if f"{called.value.id}.{called.attr}" == target:
                return True
            spelled = called.attr
        elif isinstance(called, ast.Name):
            spelled = called.id
        else:
            continue
        if spelled == target:
            return True
        if spelled in _TOP and _reaches(_TOP[spelled][1], target, seen):
            return True
    return False


def _registry_bodies() -> dict[str, object]:
    """Every body callable the registry carries, by the definition it
    was written in, with one act that carries it."""
    found: dict[str, object] = {}
    for row in grammar.COMMANDS:
        for act in row.acts():
            if act.body is None:
                continue
            node = _node_of(act.body)
            assert node is not None, act
            found.setdefault(_NAMED[id(node)], act)
    return found


BODIES = _registry_bodies()

PARSING = sorted(
    name for name, act in BODIES.items() if _reaches(_node_of(act.body), PARSE_SITE)
)


def test_the_registry_carries_the_bodies_this_file_is_about() -> None:
    """The walk found something, stated first because every claim under
    it is about a subset: an empty registry would satisfy the two below
    perfectly."""
    assert len(BODIES) == 11, sorted(BODIES)
    assert "_fragment_body" in BODIES
    assert "_document_body" in BODIES


def test_exactly_two_bodies_can_reach_the_yaml_parser() -> None:
    """Which bodies carry something nobody has validated.

    The others build a scalar or a record out of arguments the grammar
    read, so there is nothing in them for YAML to have said and JSON to
    be unable to carry. A third arriving here is a body that takes a
    fragment, and it is a diff line rather than a silent widening.
    """
    assert PARSING == ["_document_body", "_fragment_body"]


@pytest.mark.parametrize("name", PARSING)
def test_every_body_that_parses_yaml_reaches_the_guard(name: str) -> None:
    """The property, over the set the call graph discovered rather than
    over a list written beside it."""
    assert _reaches(_node_of(BODIES[name].body), GUARDED), name


# What each discovered body is handed to prove the ordering, keyed by
# the body's own name so that a body discovered above with no builder
# here is an error rather than a skip: the pin and the runtime cases
# move together or the pin stops meaning anything.
def _nan_fragment(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> invocation.Invocation:
    monkeypatch.setattr("sys.stdin", io.StringIO(f"type: anthropic\n{KEY_SENTINEL}: .nan\n"))
    return invocation.Invocation(kind="provider", stage="llm", name="claude", file="-")


def _nan_document(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> invocation.Invocation:
    document = tmp_path / "document.yaml"
    document.write_text(
        f"providers:\n  llm:\n    claude:\n      type: anthropic\n      {KEY_SENTINEL}: .nan\n"
    )
    return invocation.Invocation(file=str(document))


BUILDERS = {"_fragment_body": _nan_fragment, "_document_body": _nan_document}

NOWHERE = reach.Reached(
    address=reach.Address(base="http://127.0.0.1:1", query="", shown="http://127.0.0.1:1"),
    token="never-a-real-token",
)


@pytest.mark.parametrize("name", PARSING)
def test_the_guard_runs_before_the_request_is_made(
    name: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The ordering, at run time, because a call graph cannot answer it.

    The act is driven through the dispatcher, which is the one caller of
    a body and the one place a request is made, with the request seam
    replaced by a recorder. A guard in a branch nothing takes, or one
    written after the body has already returned, reaches in the graph
    above and leaves a record here.
    """
    assert name in BUILDERS, f"{name} was discovered and has no invocation to drive it"
    args = BUILDERS[name](tmp_path, monkeypatch)
    made: list[object] = []
    monkeypatch.setattr(acts, "_call", lambda *arguments, **keywords: made.append(arguments))

    with pytest.raises(ConfigError) as refused:
        acts._act(args, BODIES[name], NOWHERE)

    said = str(refused.value)
    # The guard's own composition, and the walk's own sentence for the
    # value it was handed: both halves, so a ConfigError raised by
    # anything else on the way cannot pass for this one.
    assert said.startswith("invalid "), said
    assert "cannot be written as JSON" in said, said
    assert made == [], name


@pytest.fixture
def spy(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    """Every section a production call actually receives, whichever
    module made the call."""
    received: list[str] = []

    def recording(section: str, fragment: object) -> None:
        received.append(section)
        transport.check_transportable(section, fragment)

    monkeypatch.setattr(entities, "check_transportable", recording)
    monkeypatch.setattr(deployment, "check_transportable", recording)
    monkeypatch.setattr(config_store, "check_transportable", recording)
    return received


def test_the_cli_entity_path_receives_the_section_alone(
    run: Callable[..., int], spy: list[str]
) -> None:
    """The runtime half, on the path the finding named: a write
    addressed by two credential-shaped words, and what the guard is
    handed is the section."""
    assert run("provider", "set", STAGE_SENTINEL, NAME_SENTINEL, "-f", "-", stdin=FLAT) == 1

    assert spy == ["providers"]
    for sentinel in (STAGE_SENTINEL, NAME_SENTINEL):
        assert not [section for section in spy if sentinel in section]


def test_the_cli_import_path_receives_the_document_word(
    run: Callable[..., int], spy: list[str], tmp_path: Path
) -> None:
    """And the other CLI caller, whose subject is the whole document."""
    document = tmp_path / "document.yaml"
    document.write_text(f"providers:\n  llm:\n    {NAME_SENTINEL}:\n      type: anthropic\n")

    run("import", "-f", str(document))

    assert spy[0] == transport.APPLY_LOCATION
    for section in spy:
        assert NAME_SENTINEL not in section


def test_the_store_path_receives_the_section_alone(
    tmp_path: Path, spy: list[str]
) -> None:
    """The repository's own caller, which is the one that holds the
    addressed location for every OTHER refusal it makes. It hands this
    guard the section and keeps the address for itself."""
    engine = open_database(DatabaseConfig())
    try:
        store = config_store.ConfigStore(engine, MultiFernet([Fernet(generate_key())]))
        store.set_provider("llm", NAME_SENTINEL, {"type": "anthropic"})
    finally:
        engine.dispose()

    assert spy == ["providers"]


def test_a_fragment_json_can_carry_still_travels(
    run: Callable[..., int], capsys: pytest.CaptureFixture[str]
) -> None:
    """The other half: this check refuses what JSON cannot say and
    nothing else, so a credential-shaped key holding an ordinary string
    is written and sent."""
    fragment = f"type: anthropic\n{KEY_SENTINEL}_env: SOME_VARIABLE\n"

    assert run("provider", "set", "llm", "claude", "-f", "-", stdin=fragment) == 0
    capsys.readouterr()
    assert run.sent, "nothing was sent"
    body = json.loads(run.sent[-1].content)
    assert f"{KEY_SENTINEL}_env" in body
