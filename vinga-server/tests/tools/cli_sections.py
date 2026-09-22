"""Measure the definition graph of the `config/cli` package.

Read-only. Parses every module of the package with `ast`, assigns each
top-level definition to the module that defines it, and records every
reference from a definition's body to a top-level name defined in
another module (`ast.Name` loads anywhere in its body, which covers
attribute bases because `Attribute.value` is a `Name`).

This is the measurement the split of `config/cli.py` was drawn from,
adapted from one file with section headers to a package with modules.
It is supporting evidence about the definitions rather than the cycle
proof: a package has cycle mechanisms a definition graph cannot see,
namely module imports, initialization order and `__init__.py` running
first, and `tests/unit/test_cli_import_graph.py` is what proves those
acyclic on every change.

Names bound locally inside a definition (parameters, assignment
targets, for/with/except/comprehension targets, nested def/class names)
are NOT counted as references to a same-named top-level name, unless the
definition declares them `global`; the shadowings this excludes are
listed at the end so the exclusion can be audited.

Import-bound names (`import x`, `from y import z`) are not definitions
and are not in the matrix: a name a module imports from a sibling is
counted as a reference to that sibling's definition, which is the fact
the matrix is about.

Usage, from `vinga-server/`::

    uv run python -m tests.tools.cli_sections
"""

from __future__ import annotations

import ast
from collections import defaultdict
from pathlib import Path

PACKAGE = Path(__file__).resolve().parents[2] / "src/vinga_server/config/cli"

# The order the modules may import one another in, lowest first. It is
# the package's own claim about itself, and the acyclicity report below
# says whether the definitions keep it: an edge that points forward in
# this list is an edge that would have to become a cycle.
ORDER = [
    "invocation",
    "answers",
    "reach",
    "input",
    "output",
    "acts",
    "entities",
    "devices",
    "deployment",
    "records",
    "local",
    "simulator",
    "events",
    "grammar",
    "__init__",
]


def bound_targets(target: ast.AST) -> list[str]:
    if isinstance(target, ast.Name):
        return [target.id]
    if isinstance(target, (ast.Tuple, ast.List)):
        return [name for element in target.elts for name in bound_targets(element)]
    if isinstance(target, ast.Starred):
        return bound_targets(target.value)
    return []


def top_level_definitions(tree: ast.Module):
    """Yield (name, node) for every top-level definition.

    Descends into top-level `if`/`try`/`with` blocks, which is where a
    guarded definition would live, so that no definition is missed.
    """

    def walk(body):
        for node in body:
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                yield node.name, node
            elif isinstance(node, ast.Assign):
                for target in node.targets:
                    for name in bound_targets(target):
                        yield name, node
            elif isinstance(node, (ast.AnnAssign, ast.AugAssign)):
                for name in bound_targets(node.target):
                    yield name, node
            elif isinstance(node, ast.If):
                yield from walk(node.body)
                yield from walk(node.orelse)
            elif isinstance(node, ast.Try):
                yield from walk(node.body)
                for handler in node.handlers:
                    yield from walk(handler.body)
                yield from walk(node.orelse)
                yield from walk(node.finalbody)
            elif isinstance(node, (ast.With, ast.AsyncWith)):
                yield from walk(node.body)

    yield from walk(tree.body)


def locally_bound(node: ast.AST) -> tuple[set[str], set[str]]:
    """Names bound inside a definition, and names it declares global."""
    bound: set[str] = set()
    globals_: set[str] = set()
    for sub in ast.walk(node):
        if isinstance(sub, (ast.FunctionDef, ast.AsyncFunctionDef)):
            if sub is not node:
                bound.add(sub.name)
            args = sub.args
            for argument in [*args.posonlyargs, *args.args, *args.kwonlyargs]:
                bound.add(argument.arg)
            if args.vararg:
                bound.add(args.vararg.arg)
            if args.kwarg:
                bound.add(args.kwarg.arg)
        elif isinstance(sub, ast.Lambda):
            args = sub.args
            for argument in [*args.posonlyargs, *args.args, *args.kwonlyargs]:
                bound.add(argument.arg)
            if args.vararg:
                bound.add(args.vararg.arg)
            if args.kwarg:
                bound.add(args.kwarg.arg)
        elif isinstance(sub, ast.ClassDef):
            if sub is not node:
                bound.add(sub.name)
        elif isinstance(sub, ast.Name) and isinstance(sub.ctx, (ast.Store, ast.Del)):
            bound.add(sub.id)
        elif isinstance(sub, ast.ExceptHandler) and sub.name:
            bound.add(sub.name)
        elif isinstance(sub, ast.Global):
            globals_.update(sub.names)
        elif isinstance(sub, (ast.Import, ast.ImportFrom)):
            for alias in sub.names:
                bound.add(alias.asname or alias.name.split(".")[0])
        elif isinstance(sub, ast.MatchAs) and sub.name:
            bound.add(sub.name)
        elif isinstance(sub, ast.MatchStar) and sub.name:
            bound.add(sub.name)
    return bound, globals_


def loads(node: ast.AST):
    """(name, line) for every `ast.Name` load inside the node."""
    for sub in ast.walk(node):
        if isinstance(sub, ast.Name) and isinstance(sub.ctx, ast.Load):
            yield sub.id, sub.lineno


def tarjan_scc(nodes, edges):
    index: dict[str, int] = {}
    low: dict[str, int] = {}
    stack: list[str] = []
    on: set[str] = set()
    out: list[list[str]] = []
    counter = [0]

    def strong(v):
        index[v] = low[v] = counter[0]
        counter[0] += 1
        stack.append(v)
        on.add(v)
        for w in edges.get(v, ()):
            if w not in index:
                strong(w)
                low[v] = min(low[v], low[w])
            elif w in on:
                low[v] = min(low[v], index[w])
        if low[v] == index[v]:
            component = []
            while True:
                w = stack.pop()
                on.discard(w)
                component.append(w)
                if w == v:
                    break
            out.append(component)

    for v in nodes:
        if v not in index:
            strong(v)
    return out


def read() -> tuple[dict[str, ast.AST], dict[str, str]]:
    """Every definition of the package, and the module that defines it."""
    defs: dict[str, ast.AST] = {}
    home: dict[str, str] = {}
    for module in ORDER:
        tree = ast.parse((PACKAGE / f"{module}.py").read_text())
        for name, node in top_level_definitions(tree):
            if name in defs:
                print(f"  DUPLICATE {name}: {home[name]} and {module}")
                continue
            defs[name] = node
            home[name] = module
    return defs, home


def main() -> int:
    print(f"package: {PACKAGE}")
    defs, home = read()

    per_module: dict[str, list[str]] = defaultdict(list)
    for name in defs:
        per_module[home[name]].append(name)

    print()
    print("== Definitions per module ==")
    for module in ORDER:
        names = per_module[module]
        kinds: dict[str, int] = defaultdict(int)
        for name in names:
            kinds[type(defs[name]).__name__] += 1
        spelled = ", ".join(f"{kind}={count}" for kind, count in sorted(kinds.items()))
        lines = len((PACKAGE / f"{module}.py").read_text().splitlines())
        print(f"  {module:12s} {len(names):4d} definitions, {lines:5d} lines ({spelled})")
    print(f"  {'total':12s} {len(defs):4d}")

    edges: dict[tuple[str, str], dict[str, list[tuple[str, int]]]] = defaultdict(
        lambda: defaultdict(list)
    )
    shadowed: list[tuple[str, str, str]] = []
    for name, node in defs.items():
        module = home[name]
        bound, globals_ = locally_bound(node)
        seen: set[str] = set()
        for ref, line in loads(node):
            if ref not in home or ref == name:
                continue
            if ref in bound and ref not in globals_:
                if ref not in seen:
                    seen.add(ref)
                    shadowed.append((name, ref, home[ref]))
                continue
            other = home[ref]
            if other != module:
                edges[(module, other)][ref].append((name, line))

    print()
    print("== Matrix: distinct names referenced (rows reference, columns are referenced) ==")
    width = max(len(module) for module in ORDER) + 1
    print("  " + " " * width + "".join(f"{module[:4]:>6s}" for module in ORDER) + "   total")
    for a in ORDER:
        row = []
        total = 0
        for b in ORDER:
            count = len(edges.get((a, b), {})) if a != b else 0
            total += count
            row.append(f"{count if count else '.':>6}")
        print(f"  {a:{width}s}" + "".join(row) + f"{total:>8d}")

    print()
    print("== Names each module takes from each other module ==")
    for a in ORDER:
        for b in ORDER:
            if a == b or (a, b) not in edges:
                continue
            names = edges[(a, b)]
            print(f"  {a} <- {b}: {len(names)} names")
            for ref in sorted(names):
                sites = names[ref]
                referrers = sorted({referrer for referrer, _ in sites})
                print(f"      {ref}  ({len(sites)} sites, via {', '.join(referrers)})")

    graph: dict[str, set[str]] = defaultdict(set)
    for a, b in edges:
        graph[a].add(b)

    print()
    print("== Module graph ==")
    for a in ORDER:
        out = sorted(graph.get(a, ()), key=ORDER.index)
        print(f"  {a:12s} -> {', '.join(out) or '(nothing)'}")

    components = [c for c in tarjan_scc(ORDER, graph) if len(c) > 1]
    position = {module: index for index, module in enumerate(ORDER)}
    forward = [
        (a, b, sorted(edges[(a, b)]))
        for a, b in sorted(edges, key=lambda pair: (position[pair[0]], position[pair[1]]))
        if position[b] >= position[a]
    ]

    print()
    if components:
        print("== Acyclic: NO ==")
        for component in components:
            print(f"  strongly connected: {', '.join(sorted(component, key=ORDER.index))}")
    else:
        print("== Acyclic: YES ==")
    if forward:
        print("== Edges against the stated order ==")
        for a, b, names in forward:
            print(f"  {a} -> {b}: {' '.join(names)}")
    else:
        print("== The stated order is a topological order: no edge points forward ==")

    print()
    print("== Shadowings excluded (definition, local name that is also a top-level name) ==")
    if shadowed:
        for referrer, ref, module in sorted(shadowed):
            print(f"  {referrer}: {ref} (top-level in {module})")
    else:
        print("  none")
    return 0 if not components else 1


if __name__ == "__main__":
    raise SystemExit(main())
