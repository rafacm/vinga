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

PACKAGE = Path(__file__).resolve().parents[2] / "src" / "vinga_server" / "config" / "cli"

PACKAGE_NAME = "vinga_server.config.cli"

# What the package calls its own door. `__init__.py` is a module of the
# graph like any other: it imports the grammar and the input module, and
# the point of including it is that it runs first, so an edge from a
# submodule back to it would be a cycle a reader would never see by
# looking at either file alone.
INIT = "__init__"


def _modules() -> list[str]:
    """Every module of the package, by the name an import would use."""
    return sorted(path.stem for path in PACKAGE.glob("*.py"))


def _sibling(module: str, node: ast.ImportFrom | ast.Import, alias: ast.alias) -> str | None:
    """Which module of this package one import statement names, if any.

    Three spellings reach a sibling and all three are read. `from
    .reach import PROGRAM` names it in `node.module`; `from . import
    reach` names it in the alias, with no module at all; and the
    absolute `from vinga_server.config.cli.reach import PROGRAM` and
    `import vinga_server.config.cli.reach` name it under the package's
    own dotted path. A level of 2 or more cannot reach a sibling, since
    it leaves the package altogether.
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
    if node.level:
        return None
    if node.module == PACKAGE_NAME:
        return alias.name
    if node.module and node.module.startswith(f"{PACKAGE_NAME}."):
        return node.module[len(PACKAGE_NAME) + 1 :].split(".")[0]
    return None


def _graph() -> dict[str, set[str]]:
    """Which module of the package each module of it imports."""
    known = set(_modules())
    edges: dict[str, set[str]] = defaultdict(set)
    for module in known:
        tree = ast.parse((PACKAGE / f"{module}.py").read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if not isinstance(node, (ast.Import, ast.ImportFrom)):
                continue
            for alias in node.names:
                reached = _sibling(module, node, alias)
                if reached in known and reached != module:
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
