"""Which `Invocation` fields each CLI command reads, and which its
grammar sets.

Read-only. This is the second of the two measurements #488's plan was
drawn from, and the one M2 landed as its whole deliverable: the plan
settled that the CLI gets per-family invocation types only if the
measurement finds a command reading a field its grammar never sets, so
the numbers below are what decided that no such type is added.
Committing the tool is what makes that decision re-checkable from the
tree rather than remembered, which is why the plan asked for it under
`tests/tools/` beside its neighbours. It is not a test and asserts
nothing.

Run from `vinga-server/`::

    uv run python tests/tools/cli_fields.py
    uv run python -m tests.tools.cli_fields   # the same, as a module

Method, in one paragraph. The package is imported so the registry
(`grammar.COMMANDS`) and every callable on every row are real objects,
and every module of the package is parsed once with `ast`. Every
callable is mapped back to its `FunctionDef`/`Lambda` node by its code
object's file and `co_firstlineno`, which is what makes a closure such
as `_entity_path(kind).path` analysable: the node is found by line, and
the closure's cells are available for the one dynamic read
(`getattr(args, parameter) for parameter in descriptor.addressing`).
Reads are `Attribute` nodes whose value is the parameter that received
the invocation, collected over the whole function subtree (so a nested
lambda closing over `args` is caught). Calls are followed transitively,
across modules as readily as within one, since a callee is resolved
through the calling function's own `__globals__`: a call whose argument
is the invocation parameter, or `replace(<param>, k=...)`, hands the
invocation to the callee's matching parameter, and the callee is
analysed the same way, with the depth recorded so the report can say
what a one-level follow would have missed; a callee's other arguments
are bound from the call site where they are plain names (that is how
`_identity(descriptor, args)` evaluates `descriptor.addressing`). One
branch shape is pruned: `if <param>.kind == "<literal>"` is decided
from the row's own `kind`, so a provider-only read on the mcp-server
rows is not counted. Two shapes need a special case and both are named
in the output: `_act(x, ACT, reached)` dispatches through an `Act`
value, so the named act's path/query/body are analysed against `x`; and
`**_addressing(scope, owner)` in three grammars sets one of three
fields by scope, so those three are recorded as conditionally set. A
field read only off a `replace()` copy the handler itself built is
marked `+`.

The four global options (`config`, `api_url`, `force`, `no_input`) and
`kind` are set by `_invocation` itself for every command, from the
root/command merge and from the row, so they are excluded from
"read-not-set" and reported in their own section.

Adapted from the pre-plan run against the single file `config/cli.py`
by replacing that file's one parse with one parse per module of the
package `config/cli/`. Nothing else about the method changed, so the
totals are comparable with the ones the plan quotes.
"""

from __future__ import annotations

import ast
import dataclasses
import inspect
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path

import vinga_server.config.entities as entity_catalog
from vinga_server.config.cli import acts as acts_module
from vinga_server.config.cli import grammar
from vinga_server.config.cli import invocation as invocation_module

PACKAGE = Path(inspect.getsourcefile(grammar)).parent
SOURCES = {
    str(path): path.read_text(encoding="utf-8") for path in sorted(PACKAGE.glob("*.py"))
}
TREES = {path: ast.parse(source) for path, source in SOURCES.items()}

FIELDS = tuple(f.name for f in dataclasses.fields(invocation_module.Invocation))
GLOBALS = ("config", "api_url", "force", "no_input")
ROW_SET = ("kind",)  # set by `_invocation` from `row.kind`
IMPLICIT = set(GLOBALS) | set(ROW_SET)

VISITED: set[str] = set()

# Every function node in every module of the package, by file and first
# line, nested ones included. The pre-plan run keyed this by line alone
# because there was one file; a package needs the file too, and a code
# object carries it.
NODES_BY_LINE: dict[tuple[str, int], ast.AST] = {}
for path, tree in TREES.items():
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda)):
            NODES_BY_LINE.setdefault((path, node.lineno), node)


def node_of(fn) -> ast.AST | None:
    """The AST node of a Python function, by its code object's file and
    first line."""
    code = getattr(fn, "__code__", None)
    if code is None or code.co_filename not in SOURCES:
        return None
    return NODES_BY_LINE.get((code.co_filename, code.co_firstlineno))


def closure_namespace(fn) -> dict:
    """What a closure can see: its module's globals plus its own cells.

    Its module's, not the package's: a name a module imported from a
    sibling is in that module's globals under the name it spelled, so a
    call followed across a module boundary resolves the way the running
    code resolves it.
    """
    ns = dict(getattr(fn, "__globals__", {}))
    if getattr(fn, "__closure__", None):
        for name, cell in zip(fn.__code__.co_freevars, fn.__closure__, strict=True):
            try:
                ns[name] = cell.cell_contents
            except ValueError:
                pass
    return ns


def param_names(node: ast.AST) -> list[str]:
    a = node.args
    return (
        [p.arg for p in a.posonlyargs + a.args]
        + ([a.vararg.arg] if a.vararg else [])
        + [p.arg for p in a.kwonlyargs]
    )


@dataclass
class Read:
    field: str
    depth: int
    via: str  # the function it was read in
    how: str = "attr"  # attr | getattr(closure) | act-dispatch


@dataclass
class Analysis:
    reads: list[Read] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)
    max_depth: int = 0


def live_nodes(node: ast.AST, param_name: str, kind: str, out: Analysis, qual: str):
    """Every node under `node`, except the dead arm of an `if
    <param>.kind == "<literal>"` (or `!=`) for the row's own kind. The one
    branch shape the package puts on the invocation, and pruning it is
    what tells a provider row's read of `stage` from an mcp-server row's."""
    if isinstance(node, ast.If):
        t = node.test
        if (
            isinstance(t, ast.Compare)
            and len(t.ops) == 1
            and isinstance(t.ops[0], (ast.Eq, ast.NotEq))
            and isinstance(t.left, ast.Attribute)
            and isinstance(t.left.value, ast.Name)
            and t.left.value.id == param_name
            and t.left.attr == "kind"
            and isinstance(t.comparators[0], ast.Constant)
        ):
            equal = (kind == t.comparators[0].value)
            if isinstance(t.ops[0], ast.NotEq):
                equal = not equal
            live = node.body if equal else node.orelse
            out.notes.append(
                f"{qual}: `if {ast.unparse(t)}` pruned for kind={kind!r}, "
                f"walked only the {'true' if equal else 'false'} arm"
            )
            yield from live_nodes(node.test, param_name, kind, out, qual)
            for child in live:
                yield from live_nodes(child, param_name, kind, out, qual)
            return
    yield node
    for child in ast.iter_child_nodes(node):
        yield from live_nodes(child, param_name, kind, out, qual)


def analyse(fn, param_index: int | None, param_name: str | None, depth: int,
            out: Analysis, seen: set, presets: frozenset[str] = frozenset(),
            bound: dict | None = None, kind: str = "") -> None:
    """Collect the invocation reads of `fn`, whose invocation parameter is
    positional index `param_index` or keyword `param_name`.

    `presets` are fields the caller set on a `replace(...)` copy before
    handing it on, so a read of one of them in this callee is a read of a
    value the caller supplied and is recorded with that mark. `bound` are
    the callee's other parameters as the call site could evaluate them
    (a descriptor handed to `_identity`, for instance). `kind` is the
    row's kind, for pruning branches on it.
    """
    node = node_of(fn)
    if node is None:
        out.notes.append(
            f"depth {depth}: {getattr(fn, '__qualname__', fn)!r} has no source node "
            "in the cli package; not followed"
        )
        return
    names = param_names(node) if not isinstance(node, ast.Lambda) else param_names(node)
    if param_name is None:
        if param_index is None or param_index >= len(names):
            out.notes.append(
                f"depth {depth}: could not map the invocation onto a parameter "
                f"of {fn.__qualname__}"
            )
            return
        param_name = names[param_index]
    key = (fn.__code__, param_name, tuple(sorted((bound or {}).keys())))
    if key in seen:
        return
    seen.add(key)
    VISITED.add(fn.__qualname__.rsplit(".", 1)[-1])
    out.max_depth = max(out.max_depth, depth)
    ns = closure_namespace(fn)
    ns.update(bound or {})
    qual = fn.__qualname__

    # Comprehension bindings, for the one getattr read.
    comp_iters: dict[str, ast.AST] = {}
    for sub in ast.walk(node):
        if isinstance(sub, ast.comprehension) and isinstance(sub.target, ast.Name):
            comp_iters[sub.target.id] = sub.iter

    for sub in live_nodes(node, param_name, kind, out, qual):
        # args.<field>
        if (
            isinstance(sub, ast.Attribute)
            and isinstance(sub.value, ast.Name)
            and sub.value.id == param_name
        ):
            if sub.attr in FIELDS:
                how = "attr" if sub.attr not in presets else "attr(preset by caller's replace)"
                out.reads.append(Read(sub.attr, depth, qual, how))
            else:
                out.notes.append(
                    f"{qual}: reads .{sub.attr}, which is not an Invocation field"
                )
        # getattr(args, <expr>)
        if (
            isinstance(sub, ast.Call)
            and isinstance(sub.func, ast.Name)
            and sub.func.id == "getattr"
            and sub.args
            and isinstance(sub.args[0], ast.Name)
            and sub.args[0].id == param_name
        ):
            attr = sub.args[1]
            resolved = None
            if isinstance(attr, ast.Constant):
                resolved = [attr.value]
            elif isinstance(attr, ast.Name) and attr.id in comp_iters:
                try:
                    resolved = list(
                        eval(compile(ast.Expression(comp_iters[attr.id]), "<iter>", "eval"), ns)
                    )
                except Exception as exc:  # noqa: BLE001
                    out.notes.append(
                        f"{qual}: getattr over {ast.unparse(comp_iters[attr.id])} "
                        f"could not be evaluated: {exc!r}"
                    )
            if resolved is None:
                out.notes.append(
                    f"{qual}: dynamic getattr({param_name}, {ast.unparse(attr)}) not resolved"
                )
            else:
                for name in resolved:
                    out.reads.append(Read(
                        name, depth, qual,
                        f"getattr({ast.unparse(attr)}) over "
                        f"{ast.unparse(comp_iters[attr.id])} evaluated from the call-site binding",
                    ))
        # calls that hand the invocation on
        if isinstance(sub, ast.Call):
            follow_call(sub, param_name, ns, depth, out, seen, qual, kind)


def invocation_argument(arg: ast.AST, param_name: str) -> tuple[bool, frozenset[str]]:
    """Whether this call argument is the invocation, and which fields a
    `replace(param, k=...)` around it set."""
    if isinstance(arg, ast.Name) and arg.id == param_name:
        return True, frozenset()
    if (
        isinstance(arg, ast.Call)
        and isinstance(arg.func, ast.Name)
        and arg.func.id == "replace"
        and arg.args
        and isinstance(arg.args[0], ast.Name)
        and arg.args[0].id == param_name
    ):
        return True, frozenset(kw.arg for kw in arg.keywords if kw.arg)
    return False, frozenset()


NOT_FOLLOWED = (
    "replace", "isinstance", "bool", "str", "repr", "print",
    "getattr", "setattr", "hasattr", "tuple", "list", "dict", "set",
)
"""Builtins and the copy constructor: a call to one of these hands the
invocation nowhere a read could hide."""


def follow_call(call: ast.Call, param_name: str, ns: dict, depth: int,
                out: Analysis, seen: set, qual: str, kind: str) -> None:
    positions = []
    for i, a in enumerate(call.args):
        is_inv, presets = invocation_argument(a, param_name)
        if is_inv:
            positions.append((i, None, presets))
    for kw in call.keywords:
        is_inv, presets = invocation_argument(kw.value, param_name)
        if is_inv:
            positions.append((None, kw.arg, presets))
    if not positions:
        return
    if not isinstance(call.func, ast.Name):
        out.notes.append(
            f"{qual}: hands the invocation to a non-name callee "
            f"{ast.unparse(call.func)}; not followed"
        )
        return
    callee_name = call.func.id
    if callee_name in NOT_FOLLOWED:
        return
    callee = ns.get(callee_name)
    if callee is None:
        out.notes.append(f"{qual}: callee {callee_name} not in namespace; not followed")
        return
    for index, kwname, presets in positions:
        # Special case: `_act(x, ACT, reached)` dispatches through the Act.
        if callee is acts_module._act:
            act_expr = call.args[1] if len(call.args) > 1 else None
            act = ns.get(act_expr.id) if isinstance(act_expr, ast.Name) else None
            if not isinstance(act, acts_module.Act):
                out.notes.append(
                    f"{qual}: _act(...) with an act expression "
                    f"{ast.unparse(act_expr) if act_expr else '?'} "
                    "that is not a module-level Act; not followed"
                )
                continue
            out.notes.append(
                f"{qual}: _act(..., {act_expr.id}, ...) followed into that Act's "
                f"path/query/body at depth {depth + 1}"
                + (f" with {sorted(presets)} preset by replace()" if presets else "")
            )
            for part in ("path", "query", "body"):
                cb = getattr(act, part)
                if cb is not None:
                    analyse(cb, 0, None, depth + 1, out, seen, presets, None, kind)
            continue
        if not callable(callee) or not hasattr(callee, "__code__"):
            out.notes.append(f"{qual}: callee {callee_name} is not a plain function; not followed")
            continue
        # The callee's other arguments, as far as the call site can
        # evaluate them from names in the caller's namespace: what makes
        # `_identity(descriptor, args)` resolvable.
        cnode = node_of(callee)
        bound: dict = {}
        if cnode is not None:
            cparams = param_names(cnode)
            for i, a in enumerate(call.args):
                if i == index or i >= len(cparams):
                    continue
                if isinstance(a, ast.Name) and a.id in ns:
                    bound[cparams[i]] = ns[a.id]
            for kw in call.keywords:
                if (
                    kw.arg
                    and kw.arg != kwname
                    and isinstance(kw.value, ast.Name)
                    and kw.value.id in ns
                ):
                    bound[kw.arg] = ns[kw.value.id]
        analyse(callee, index, kwname, depth + 1, out, seen, presets, bound, kind)


# The grammar side: which fields `run` passes to `_invocation`.

ADDRESSING_FIELDS = ("name", "mac", "conversation")  # the literal in `_addressing`


def grammar_sets(row) -> tuple[set[str], set[str], list[str]]:
    """Fields the row's grammar passes to `_invocation` beyond the four
    globals: (unconditional, conditional, notes)."""
    run = row.declare(row)
    node = node_of(run)
    notes: list[str] = []
    if node is None:
        return set(), set(), ["grammar has no source node"]
    unconditional: set[str] = set()
    conditional: set[str] = set()
    calls = [
        c for c in ast.walk(node)
        if isinstance(c, ast.Call) and isinstance(c.func, ast.Name)
        and c.func.id == "_invocation"
    ]
    if len(calls) != 1:
        notes.append(f"grammar has {len(calls)} _invocation calls")
    for c in calls:
        # positional args after `row, context` are config, api_url, force, no_input
        extra_positional = len(c.args) - 2
        if extra_positional > 4:
            notes.append("grammar passes more than the four globals positionally")
        for kw in c.keywords:
            if kw.arg is None:
                src = ast.unparse(kw.value)
                if src.startswith("_addressing("):
                    conditional.update(ADDRESSING_FIELDS)
                    notes.append(
                        "**_addressing(scope, owner) sets exactly one of "
                        "name/mac/conversation by scope, or none"
                    )
                else:
                    notes.append(f"unresolved **{src}")
            elif kw.arg in IMPLICIT:
                pass
            else:
                unconditional.add(kw.arg)
    if row.kind:
        unconditional.add("kind")
    return unconditional, conditional, notes


# Per command.

@dataclass
class CommandReport:
    name: str
    family: str
    kind: str
    read_all: set[str]
    read_depth1: set[str]
    set_unconditional: set[str]
    set_conditional: set[str]
    globals_read: set[str]
    read_not_set: set[str]
    preset_only: set[str]
    max_depth: int
    notes: list[str]
    reads: list[Read]


def analyse_command(row) -> CommandReport:
    out = Analysis()
    seen: set = set()
    entry_points: list[tuple[str, object]] = []
    if callable(row.does) and not isinstance(row.does, (acts_module.Act, tuple)):
        entry_points.append(("handler", row.does))
    for act in row.acts():
        for part in ("path", "query", "body"):
            cb = getattr(act, part)
            if cb is not None:
                entry_points.append((part, cb))
    if row.selects is not None:
        entry_points.append(("selects", row.selects))
    if row.opens is not None:
        entry_points.append(("opens", row.opens))
    for _label, fn in entry_points:
        analyse(fn, 0, None, 0, out, seen, frozenset(), None, row.kind)
    read_all = {r.field for r in out.reads}
    read_depth1 = {r.field for r in out.reads if r.depth <= 1}
    # A field every read of which is of a value the handler itself put on
    # a replace() copy: read-not-set by the grammar, but not a silent
    # default either. Marked `+` in the table and counted apart.
    preset_only = {
        f for f in read_all
        if all("preset" in r.how for r in out.reads if r.field == f)
    }
    set_u, set_c, gnotes = grammar_sets(row)
    globals_read = read_all & IMPLICIT
    read_not_set = (read_all - IMPLICIT) - set_u - set_c
    return CommandReport(
        name=" ".join(row.words),
        family=row.words[0],
        kind=row.kind,
        read_all=read_all,
        read_depth1=read_depth1,
        set_unconditional=set_u,
        set_conditional=set_c,
        globals_read=globals_read,
        read_not_set=read_not_set,
        preset_only=preset_only,
        max_depth=out.max_depth,
        notes=out.notes + gnotes,
        reads=out.reads,
    )


def fmt(s: set[str], cond: set[str] = frozenset(), preset: set[str] = frozenset()) -> str:
    items = sorted(f"{x}+" if x in preset else x for x in s - cond) + [
        f"{x}?" for x in sorted(cond)
    ]
    return ",".join(items) if items else "-"


def main() -> None:
    reports = [analyse_command(row) for row in grammar.COMMANDS]
    reports.sort(key=lambda r: r.name)
    p = print
    p("# Invocation field usage per command of vinga_server.config.cli")
    p(f"# Modules parsed ({len(TREES)}): "
      f"{', '.join(sorted(Path(x).name for x in TREES))}")
    p(f"# Invocation fields ({len(FIELDS)}): {', '.join(FIELDS)}")
    p("# Set for every command by _invocation itself, so excluded from read-not-set: "
      f"{', '.join(sorted(IMPLICIT))}")
    p("# Columns: command | read (all depths; globals marked *) | set by grammar "
      "(x? = conditionally, via **_addressing) | read-not-set (x+ = every read is of a "
      "value the handler itself put on a replace() copy)")
    p()
    for r in reports:
        read = ",".join(sorted(f + ("*" if f in IMPLICIT else "") for f in r.read_all)) or "-"
        p(f"{r.name} | {read} | {fmt(r.set_unconditional, r.set_conditional)} "
          f"| {fmt(r.read_not_set, frozenset(), r.preset_only)}")
    p()
    p("# Totals")
    p(f"commands: {len(reports)}")
    empty = [r for r in reports if not r.read_not_set]
    nonempty = [r for r in reports if r.read_not_set]
    p(f"read-not-set empty: {len(empty)}")
    p(f"read-not-set non-empty: {len(nonempty)}")
    preset_rows = [r for r in nonempty if r.read_not_set <= r.preset_only]
    p("  of the non-empty, those whose read-not-set is entirely handler-preset "
      f"via replace() (x+): {len(preset_rows)}")
    p("  of the non-empty, those with a genuinely silent default: "
      f"{len(nonempty) - len(preset_rows)}")
    by_field: dict[str, list[str]] = defaultdict(list)
    for r in nonempty:
        for f in r.read_not_set:
            by_field[f].append(r.name)
    p(f"distinct fields ever in read-not-set: {len(by_field)}")
    for f in sorted(by_field):
        p(f"  {f}: {', '.join(sorted(by_field[f]))}")
    p()
    p("# Follow depth")
    p(f"max call depth followed over all commands: {max(r.max_depth for r in reports)}")
    deeper = [
        (r.name, sorted(r.read_all - r.read_depth1))
        for r in reports if r.read_all - r.read_depth1
    ]
    p(f"commands with reads only found beyond one level of call following: {len(deeper)}")
    for name, fields in deeper:
        p(f"  {name}: {','.join(fields)}")
    p()
    p("# Read provenance (field <- function @ depth, how), for every command")
    for r in reports:
        if not r.reads:
            p(f"{r.name}: (no invocation reads)")
            continue
        seen_lines: set[str] = set()
        lines = []
        for rd in r.reads:
            line = f"{rd.field} <- {rd.via} @ {rd.depth} ({rd.how})"
            if line not in seen_lines:
                seen_lines.add(line)
                lines.append(line)
        p(f"{r.name}: " + "; ".join(lines))
    p()
    p("# Notes on what was special-cased or not resolved statically")
    any_note = False
    for r in reports:
        for n in dict.fromkeys(r.notes):
            any_note = True
            p(f"{r.name}: {n}")
    if not any_note:
        p("none")
    p()
    p("# Globals (set by the root/command merge in _invocation, read by whichever "
      "code reads them)")
    p("Set by: _root -> Globals -> Globals.merged(command's own copies) -> "
      "_invocation(config, api_url, force=bool, no_input=bool); kind from row.kind.")
    p("Framework reads on Command.perform, not attributed per command above: "
      "_permitted_to_destroy reads force,no_input when row.destroys; _reached reads "
      "config and (via _address) api_url when the row has acts.")
    destroys = sorted(" ".join(r.words) for r in grammar.COMMANDS if r.destroys)
    with_acts = sorted(" ".join(r.words) for r in grammar.COMMANDS if r.acts())
    p(f"rows with destroys=True ({len(destroys)}): {', '.join(destroys)}")
    p(f"rows with acts, so _reached runs ({len(with_acts)}): {', '.join(with_acts)}")
    gl: dict[str, list[str]] = defaultdict(list)
    for r in reports:
        for f in r.globals_read:
            gl[f].append(r.name)
    p("globals read inside a command's own code (handler, act callables, helpers), by field:")
    for f in sorted(IMPLICIT):
        p(f"  {f}: {', '.join(sorted(gl[f])) if gl[f] else '-'}")
    p()
    p("# Families, by the first word of the noun path (the registry's own grouping: "
      "GROUPS keys and the flat verbs)")
    fam: dict[str, list[CommandReport]] = defaultdict(list)
    for r in reports:
        fam[r.family].append(r)
    grouped = [f for f in fam if (f,) in grammar.GROUPS]
    flat = [f for f in fam if (f,) not in grammar.GROUPS]
    p(f"distinct first words: {len(fam)}; of which noun groups (a GROUPS key): "
      f"{len(grouped)}; flat verbs: {len(flat)}")
    p("GROUPS keys in the registry (noun paths, sub-nouns included): "
      f"{len(grammar.GROUPS)}: {', '.join(' '.join(k) for k in grammar.GROUPS)}")
    p("family | commands | union of fields set (x? conditional) | union of fields read "
      "(globals excluded) | union of read-not-set")
    for f in sorted(fam):
        rs = fam[f]
        su = set().union(*(r.set_unconditional for r in rs))
        sc = set().union(*(r.set_conditional for r in rs)) - su
        ra = set().union(*(r.read_all for r in rs)) - IMPLICIT
        rn = set().union(*(r.read_not_set for r in rs))
        p(f"{f} | {len(rs)} | {fmt(su, sc)} | {fmt(ra)} | {fmt(rn)}")
    p()
    p("# Families by grammar shape (the `declare` function), which is what sizes a "
      "per-shape invocation type")
    shapes: dict[str, list[CommandReport]] = defaultdict(list)
    ordered = sorted(grammar.COMMANDS, key=lambda x: " ".join(x.words))
    for row, r in zip(ordered, reports, strict=True):
        shapes[row.declare.__name__].append(r)
    p(f"distinct declare functions: {len(shapes)}")
    p("shape | commands | fields set (x? conditional) | union of fields read "
      "(globals excluded) | union of read-not-set")
    for name in sorted(shapes):
        rs = shapes[name]
        su = set().union(*(r.set_unconditional for r in rs)) - {"kind"}
        sc = set().union(*(r.set_conditional for r in rs)) - su
        ra = set().union(*(r.read_all for r in rs)) - IMPLICIT
        rn = set().union(*(r.read_not_set for r in rs))
        p(f"{name} | {len(rs)}: {', '.join(r.name for r in rs)} | {fmt(su, sc)} "
          f"| {fmt(ra)} | {fmt(rn)}")
    p()
    p("# Coverage: every function in the package with a parameter annotated "
      "`Invocation`, and whether the analysis reached it")
    takers = []
    for path, tree in sorted(TREES.items()):
        for n in ast.walk(tree):
            if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)):
                annotated = n.args.posonlyargs + n.args.args + n.args.kwonlyargs
                for a in annotated:
                    if a.annotation is not None and ast.unparse(a.annotation) == "Invocation":
                        takers.append(f"{Path(path).stem}.{n.name}")
                        break
    reached = [t for t in takers if t.split(".", 1)[1] in VISITED]
    unreached = [t for t in takers if t.split(".", 1)[1] not in VISITED]
    p(f"functions taking an Invocation: {len(takers)}; reached by the per-command "
      f"analysis: {len(reached)}; not reached: {len(unreached)}")
    p("not reached (framework, or entry points the rows do not name): "
      f"{', '.join(unreached) if unreached else '-'}")
    p()
    p("# Per-kind act tables (the other grouping the registry draws): entity kinds "
      "and their addressing")
    for k in entity_catalog.ENTITIES:
        p(f"  {k.name}: addressing={k.addressing}, has_delete={k.has_delete}")
    p("  tables: SET_ENTITY, SHOW_ENTITY, EXPORT_ENTITY, DELETE_ENTITY (one Act per kind each); "
      "_MEMORY_LISTINGS, _MEMORY_CORRECTIONS, _MEMORY_DELETIONS (memory, by scope)")


if __name__ == "__main__":
    main()
