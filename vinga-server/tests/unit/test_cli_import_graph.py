"""The `config/cli` package imports itself in one direction only.

The split of `config/cli.py` rests on a definition graph that is
acyclic: every function calls only functions its module may reach, and
`tests/tools/cli_sections.py` re-measures that on demand. A package has
cycle mechanisms a definition graph cannot see, though, and all three
are about modules rather than about definitions: an import is executed
when the module is first loaded, the order the loads happen in decides
which names exist when, and `__init__.py` runs before any submodule a
caller asked for. So the definition measurement is supporting evidence,
and this is the proof.

What it reads is what is written down, which is what a cycle is made
of: every `import` and `from ... import` statement of every module of
the package, at any depth of its body, in both the relative and the
absolute spelling. A deferred import inside a function is an edge too,
since the module it names is loaded the first time that function runs,
and a cycle closed at that moment is a cycle.

Written once as a graph rather than as a list of allowed pairs. A list
would have to be maintained beside the package and would go stale the
first time a module stopped reaching a sibling; what is asserted here
is the property, which is that no module can reach itself by following
imports.
"""

import ast
from collections import defaultdict
from pathlib import Path

import pytest

PACKAGE = Path(__file__).resolve().parents[2] / "src" / "vinga_server" / "config" / "cli"

PACKAGE_NAME = "vinga_server.config.cli"

# What the package calls its own door. `__init__.py` is a module of the
# graph like any other: it imports the grammar and the input module, and
# the point of including it is that it runs first, so an edge from a
# submodule back to it would be a cycle a reader would never see by
# looking at either file alone.
INIT = "__init__"

# The package's own last word, which is what the two door spellings say
# instead of a module's name: `from .. import cli` and `from
# vinga_server.config import cli` both reach `__init__.py`, and a reader
# of either sees no package boundary being crossed at all.
DOOR = PACKAGE_NAME.rsplit(".", 1)[-1]


def _modules(package: Path = PACKAGE) -> list[str]:
    """Every module of the package, by the name an import would use."""
    return sorted(path.stem for path in package.glob("*.py"))


def _sibling(node: ast.ImportFrom | ast.Import, alias: ast.alias) -> str | None:
    """Which module of this package one import statement names, if any.

    Five spellings reach one and all five are read, because a cycle
    closed by any of them is a cycle. Inside the package, `from .reach
    import PROGRAM` names it in `node.module` and `from . import reach`
    names it in the alias; from anywhere, the absolute `from
    vinga_server.config.cli.reach import PROGRAM` and `import
    vinga_server.config.cli.reach` name it under the package's own
    dotted path.

    And the two that name no module at all, which is what makes them
    easy to miss: `from .. import cli` and `from vinga_server.config
    import cli` reach the package's DOOR, which is `__init__.py` and
    which runs before any submodule a caller asked for. Read as edges to
    `__init__` rather than as nothing, because a submodule that reaches
    back through the door is the cycle least visible from either end.

    A parent-relative import of anything else leaves the package, and a
    level of 3 or more leaves `config` as well, so both answer None.
    """
    if isinstance(node, ast.Import):
        name = alias.name
        if name.startswith(f"{PACKAGE_NAME}."):
            return name[len(PACKAGE_NAME) + 1 :].split(".")[0]
        return INIT if name == PACKAGE_NAME else None
    if node.level == 1:
        if node.module:
            return node.module.split(".")[0]
        return alias.name
    if node.level == 2:
        # `from .. import cli` is the door; `from ..cli import reach` is
        # a sibling spelled the long way round.
        if node.module is None:
            return INIT if alias.name == DOOR else None
        if node.module == DOOR:
            return alias.name
        if node.module.startswith(f"{DOOR}."):
            return node.module[len(DOOR) + 1 :].split(".")[0]
        return None
    if node.level:
        return None
    if node.module == PACKAGE_NAME:
        return alias.name
    if node.module and node.module.startswith(f"{PACKAGE_NAME}."):
        return node.module[len(PACKAGE_NAME) + 1 :].split(".")[0]
    # The door, named absolutely: `from vinga_server.config import cli`.
    if node.module == PACKAGE_NAME.rsplit(".", 1)[0] and alias.name == DOOR:
        return INIT
    return None


def _graph(package: Path = PACKAGE) -> dict[str, set[str]]:
    """Which module of the package each module of it imports.

    A self-edge is kept. It used to be dropped as the uninteresting case
    and it is the shortest cycle there is: a module that imports itself
    is a module whose import runs while its own body is half executed,
    and a test that filtered it out reported that as no cycle at all.
    """
    known = set(_modules(package))
    edges: dict[str, set[str]] = defaultdict(set)
    for module in known:
        tree = ast.parse((package / f"{module}.py").read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if not isinstance(node, (ast.Import, ast.ImportFrom)):
                continue
            for alias in node.names:
                reached = _sibling(node, alias)
                if reached in known:
                    edges[module].add(reached)
    return edges


def _cycles(edges: dict[str, set[str]]) -> list[list[str]]:
    """Every module that can reach itself, with the path that does it.

    A depth-first walk that carries its own path, so a failure names the
    cycle rather than only reporting that there is one: what a reader
    needs from a red run here is which import to take out.
    """
    found: list[list[str]] = []
    finished: set[str] = set()

    def walk(module: str, path: list[str], on_path: set[str]) -> None:
        for reached in sorted(edges.get(module, ())):
            if reached in on_path:
                found.append([*path[path.index(reached) :], reached])
                continue
            if reached in finished:
                continue
            walk(reached, [*path, reached], on_path | {reached})
        finished.add(module)

    for module in sorted(edges):
        if module not in finished:
            walk(module, [module], {module})
    return found


def test_the_package_has_every_module_in_the_graph() -> None:
    """The graph is of the package rather than of part of it.

    Stated first because every claim below it is about a set: a module
    the walk did not find is a module no cycle could be reported
    through, and an empty graph passes an acyclicity assertion
    perfectly.
    """
    modules = _modules()
    assert INIT in modules
    assert len(modules) == 15
    edges = _graph()
    reached = set(edges) | {module for reachable in edges.values() for module in reachable}
    assert reached == set(modules)


def test_the_package_imports_itself_in_one_direction_only() -> None:
    """The cycle proof.

    `__init__.py` included, because it is the module that runs first and
    therefore the one whose cycles are least visible from either end.
    """
    assert _cycles(_graph()) == []


# The four spellings a cycle can be closed by, three of which this walk
# used to answer "no cycle" to
#
# Each is planted in a package of this test's own rather than in the one
# under test, so the case is a statement about the walk rather than a
# mutation somebody has to remember to undo. The clean one is here for
# the reason every inventory in this file states its own totals first: a
# walk that found no edges at all would report no cycle beautifully.
CLEAN = {
    "__init__.py": "from .grammar import command\n",
    "grammar.py": "from .reach import PROGRAM\n",
    "reach.py": "PROGRAM = 'vinga'\n",
}

PLANTED = {
    "a module importing itself": ("reach.py", "from .reach import PROGRAM\n"),
    "the door, relatively": ("reach.py", "from .. import cli\n"),
    "the door, absolutely": ("reach.py", "from vinga_server.config import cli\n"),
    "the door, as a whole module": ("reach.py", "import vinga_server.config.cli\n"),
}


def _planted(tmp_path: Path, where: str, line: str) -> Path:
    package = tmp_path / "cli"
    package.mkdir()
    for name, source in CLEAN.items():
        package.joinpath(name).write_text(source + (line if name == where else ""))
    return package


def test_a_package_with_no_cycle_in_it_reports_none(tmp_path: Path) -> None:
    """The control. Without it the three cases below would pass against
    a walk that read nothing at all."""
    package = _planted(tmp_path, "nothing.py", "")

    assert set(_modules(package)) == {INIT, "grammar", "reach"}
    assert _cycles(_graph(package)) == []


@pytest.mark.parametrize(("what", "planted"), sorted(PLANTED.items()), ids=sorted(PLANTED))
def test_every_spelling_of_a_cycle_is_read_as_one(
    what: str, planted: tuple[str, str], tmp_path: Path
) -> None:
    """One case per spelling, because each is missable for its own
    reason.

    Three of the four went unread. The self-import was filtered out as
    the uninteresting edge, and it is the shortest cycle there is: a
    module whose import runs while its own body is half executed. The
    two door spellings that name no module of the package, `from ..
    import cli` and `from vinga_server.config import cli`, showed a
    reader nothing crossing a boundary, while what they reach is
    `__init__.py`, which runs before any submodule a caller asked for
    and therefore closes a cycle visible from neither end.

    The fourth, `import vinga_server.config.cli`, was read correctly
    already. It is here because a spelling that works is exactly the one
    a later edit breaks while the three beside it keep passing.
    """
    where, line = planted
    package = _planted(tmp_path, where, line)

    found = _cycles(_graph(package))

    assert found, what
    # The module the line was planted in is in the cycle it closed,
    # which is what says the walk found THIS edge rather than some other.
    assert any(where.removesuffix(".py") in cycle for cycle in found), (what, found)
