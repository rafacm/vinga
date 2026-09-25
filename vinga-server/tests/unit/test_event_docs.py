"""The two documents the event surface has, and what each is held to.

The generated reference is held to everything: it IS the catalog
rendered, and CI regenerates it and diffs it byte for byte, so a field,
a token, a level or a bound that moves without the document moving with
it turns the lane red. The tests here are the completeness half of that,
which a diff cannot give: a generator that silently skipped an event
would produce a document CI is perfectly happy with.

The README index is held to names only, and deliberately so. It carried
field and token claims in prose once, which nothing parsed and nothing
could: prose can go stale while a name-level check stays green, and
half-checked documentation reads as checked. So the schema claims live
in the generated reference now and the index says what exists and when
it fires, which is exactly what these tests check it says: every
declared event in exactly one row, every row a declared event, and no
duplicates. A wording edit passes; a dropped, invented or duplicated row
does not.

Both halves read the catalog, which since #210 is the one place a
declaration lives. There is no second description to compare against and
none to fall out of step.
"""

import array
import fcntl
import io
import logging
import os
import re
import resource
import subprocess
import sys
import termios
import time
from enum import StrEnum
from pathlib import Path
from typing import Any

import pytest

from vinga_server import events_cli, events_docgen
from vinga_server.broken_pipe import BROKEN_PIPE_STATUS
from vinga_server.events.catalog import (
    SESSION_CHANNEL,
    Declaration,
    OtaCheckAgentNotLoaded,
    RejectedAgentNotLoaded,
    carried_values,
    rendered_values,
    tokens_of,
)
from vinga_server.events.values import (
    GRAMMARS,
    PROVIDER_ENTRY_OPTIONAL,
    PROVIDER_ENTRY_REQUIRED,
    SYNTAXES,
    ArgKind,
    DropReason,
    Kind,
)


def documented() -> dict[str, Declaration]:
    """Every event the reference describes, which is every event the
    catalog declares: the document has one source now."""
    return events_docgen.documented()

README = Path(__file__).resolve().parents[2] / "README.md"

COMMITTED = Path(__file__).resolve().parents[3] / "docs" / "reference" / "events.md"

REGENERATE = (
    "docs/reference/events.md is stale; regenerate it with "
    "`uv run vinga-server events reference > ../docs/reference/events.md`"
)

# Where the index starts in the README, and what the section it lives in
# is called. Matched on the header row rather than on the heading, since
# the heading covers the formats and the switch as well.
INDEX_HEADER = "| `event` | when |"


def index_rows() -> list[tuple[str, str]]:
    """The index as (event, when) pairs, in the order it lists them.

    The event cell is unwrapped from its backticks; the when cell is
    left as written, since these tests are about names and never about
    wording."""
    lines = README.read_text(encoding="utf-8").splitlines()
    start = lines.index(INDEX_HEADER)
    rows = []
    for line in lines[start + 1 :]:
        if not line.startswith("|"):
            break
        cells = [cell.strip() for cell in line.strip().strip("|").split("|")]
        if cells[0].startswith("---"):
            continue
        rows.append((cells[0].strip("`"), cells[1]))
    return rows


def logging_section() -> str:
    """The Logging section alone, flattened.

    Sliced at the next top-level heading rather than read to the end of
    the file, so an assertion about what this section says cannot be
    satisfied by a sentence three sections further down."""
    lines = README.read_text(encoding="utf-8").splitlines()
    start = lines.index("## Logging")
    end = next(
        position
        for position, line in enumerate(lines[start + 1 :], start=start + 1)
        if line.startswith("## ")
    )
    return flat("\n".join(lines[start:end]))


def flat(text: str) -> str:
    """The document with its line breaks flattened. Both documents wrap
    their prose, so a sentence asserted on here lands across two lines
    as soon as a word ahead of it changes, and an assertion that broke
    on rewrapping would be an assertion about the wrapping."""
    return " ".join(text.split())


# --- the reference, sliced so a row can be read against its own row ----

ARGUMENT_HEADER = "| # | Argument | Nullable | Constraint | Note |"

FIELD_HEADER = "| Field | Kind | Required | Nullable | Constraint | Note |"


def variant_sections() -> dict[str, list[tuple[str, list[str]]]]:
    """The rendered document as event name to its variant subsections,
    each a heading and the lines under it.

    Slicing is what makes the assertions exact. A substring search over
    the whole document says a property is documented somewhere, which is
    true of almost anything in two thousand lines of tables."""
    events: dict[str, list[tuple[str, list[str]]]] = {}
    event: str | None = None
    heading: str | None = None
    body: list[str] = []

    def close() -> None:
        if event is not None and heading is not None:
            events[event].append((heading, body))

    for line in events_docgen.reference().splitlines():
        if line.startswith("### `"):
            close()
            event = line.removeprefix("### `").removesuffix("`")
            events[event] = []
            heading, body = None, []
        elif line.startswith("#### "):
            close()
            heading, body = line, []
        elif heading is not None:
            body.append(line)
    close()
    return events


def table(lines: list[str], header: str) -> list[list[str]]:
    """The rows under one table header, as stripped cells.

    Split on unescaped pipes only, since a cell may carry an escaped one
    and a naive split would turn one row into two halves of nothing."""
    start = lines.index(header)
    rows = []
    for line in lines[start + 2 :]:
        if not line.startswith("|"):
            break
        rows.append([one.strip() for one in re.split(r"(?<!\\)\|", line.strip())[1:-1]])
    return rows


def yes(value: bool) -> str:
    return "yes" if value else "no"


def cell(note: str) -> str:
    """A declared note as a table cell holds it: one line, pipes
    escaped."""
    return flat(note).replace("|", "\\|")


def token(value: str) -> str:
    """A declared token as the constraint column shows it: a code span,
    quoted where a code span alone would not show the value, which is
    the empty token and the ones with an edge space."""
    if value and value == flat(value):
        return f"`{value}`"
    return f"`'{value}'`"


def kind_named(declared: Any) -> str:
    """What one declaration says its field kind is.

    Read off the declaration here rather than through the catalog's
    accessor, for the reason the constraint check below gives: the
    generator calls that accessor, so an assertion built on it would be
    the same string computed twice and an accessor answering the wrong
    kind would move the document and this file together.
    """
    held = declared.type
    return Kind.TOKEN.name if issubclass(held, StrEnum) else held.KIND.name


def arg_kind_named(declared: Any) -> str:
    """And what it says its argument kind is."""
    held = declared.type
    return ArgKind.TOKEN.name if issubclass(held, StrEnum) else held.ARG_KIND.name


def check_constraint(rendered: str, declared: Any, kind: str, where: str) -> None:
    """What the constraint column has to say for one declaration.

    Built from the declaration here rather than from the generator's own
    helpers, so this is a second opinion about the cell and not the same
    string computed twice."""
    admitted = tokens_of(declared)
    if admitted:
        for one in sorted(admitted):
            assert token(one) in rendered, f"{where}: token {one!r} missing"
        # And no sixth token in a set of five: every code span in the
        # cell is one of the declared values.
        assert rendered.count("`") == 2 * len(admitted), where
        return
    if declared.type.SYNTAX is not None:
        assert f"`{declared.type.SYNTAX.name}`" in rendered, where
        if kind.endswith("_LIST"):
            assert "each element" in rendered, where
        return
    if declared.type.BOUNDS is not None:
        assert str(declared.type.BOUNDS.max_length) in rendered, where
        assert declared.type.BOUNDS.charset in rendered, where
        return
    if kind == "COMPOSED" and declared.type.GRAMMAR is not None:
        assert f"`{declared.type.GRAMMAR.name}`" in rendered, where
        return
    if declared.type.JOINED:
        assert "joined" in rendered, where
        return
    if kind == "SOURCES":
        assert "provenance" in rendered, where
        return
    if kind == "DROP_COUNTS":
        # The whole closed set, since a value type rather than an
        # enumeration is what carries it: the cell is where a reader
        # meets the reasons at all.
        for reason in sorted(DropReason):
            assert token(str(reason)) in rendered, f"{where}: reason {reason!r} missing"
        return
    if kind == "PROVIDER_ENTRIES":
        for name in PROVIDER_ENTRY_REQUIRED + PROVIDER_ENTRY_OPTIONAL:
            assert f"`{name}`" in rendered, f"{where}: entry key {name!r} missing"
        return
    # Nothing further is declared, so the cell claims nothing further.
    assert rendered == "", where


# --- the README index, at name level ----------------------------------


def test_every_declared_event_has_a_row() -> None:
    listed = [event for event, _ in index_rows()]
    missing = sorted(set(documented()) - set(listed))
    assert not missing, f"declared events with no row: {', '.join(missing)}"


def test_every_row_names_a_declared_event() -> None:
    """The other direction, which containment alone would not give: a
    row for an event that no longer exists is documentation of a surface
    this server does not have."""
    listed = [event for event, _ in index_rows()]
    invented = sorted(set(listed) - set(documented()))
    assert not invented, f"rows naming nothing declared: {', '.join(invented)}"


def test_no_event_is_listed_twice() -> None:
    """`session_rejected` is the one that tempts a second row, since it
    rides two channels. It stays one row whose prose names both."""
    listed = [event for event, _ in index_rows()]
    twice = sorted({event for event in listed if listed.count(event) > 1})
    assert not twice, f"events listed more than once: {', '.join(twice)}"
    assert len(listed) == len(documented())


def test_the_two_channel_event_is_one_row_naming_both() -> None:
    when = dict(index_rows())["session_rejected"]
    assert "vinga_server.ws" in when
    assert SESSION_CHANNEL in when


def test_the_base_field_claim_is_scoped_to_the_session_channel() -> None:
    """It was not, and was false for every server channel: those records
    carry `event` and name a session or a device only where the record
    is about one."""
    lead = logging_section().split(INDEX_HEADER)[0]
    assert f"on the `{SESSION_CHANNEL}` channel" in lead
    assert "carry `session` and `device`" in lead


def test_the_index_points_at_the_generated_reference() -> None:
    """The index makes no schema claim of its own, so it has to say
    where the schema claims are."""
    assert "(../docs/reference/events.md)" in logging_section()


# --- what a record may tell an operator to do -------------------------
#
# The drift check below holds the committed document to the catalog, and
# it is exactly as right as the catalog is: a template that names the
# wrong remedy passes it byte for byte. These say what the records have
# to MEAN, which is the one thing a diff cannot check, and they are
# here because the sentence in a warning is what an operator acts on:
# restarting a server for a change a request applies is a maintenance
# window spent on nothing, and it is the exact mistake these two records
# invited for as long as the agent set was start-bound (#191).
#
# The word itself is not banned. A reload restarts MCP entries, and the
# count it reports is the honest word for what happened to them; what
# may not appear is a record telling the person reading it to restart
# this server.

# The declarations whose templates may say "restart", and what they say
# it about: entries a reload stopped and started again, which is a
# lifecycle this server performed rather than an instruction to anyone.
RESTARTS_SOMETHING_ELSE = frozenset({"mcp_reload"})


def templates() -> list[tuple[str, str]]:
    """Every declared template, with the event it belongs to."""
    return [
        (name, variant.TEMPLATE)
        for name, spec in documented().items()
        for variant in spec.variants
    ]


def test_no_record_sends_an_operator_to_a_restart() -> None:
    """The general net, over every event there is, so a template written
    tomorrow is held to this without anybody remembering to add it."""
    sending = {
        name for name, template in templates() if "restart" in template.lower()
    }

    assert sending <= RESTARTS_SOMETHING_ELSE, sorted(sending - RESTARTS_SOMETHING_ELSE)


def test_a_device_bound_to_an_agent_this_server_is_not_serving_names_the_reload() -> None:
    """And the two records that state the case, at both edges a device
    reaches: the binding is live and the agent is one apply away, so the
    action is the reload that installs it. Read out of the committed
    document rather than off the catalog, because what is pinned is what
    an operator is shipped."""
    published = COMMITTED.read_text(encoding="utf-8")

    for template in (
        RejectedAgentNotLoaded.TEMPLATE,
        OtaCheckAgentNotLoaded.TEMPLATE,
    ):
        assert template in published
        assert "is not serving" in template
        assert "vinga-server config apply" in template


# --- the generated reference, held to the catalog for completeness ----
#
# The drift step regenerates this document and diffs it byte for byte,
# which catches a declaration that moved and the document that did not.
# What a diff cannot catch is a generator that silently skipped
# something: the document would be exactly what the generator writes,
# and CI would be perfectly happy with it.
#
# So this is the completeness half, and it is complete in the plan's own
# terms: every event, every variant, every template byte for byte, every
# argument position with the field it renders, its kind, nullability,
# constraint and note, every payload field with its kind, requiredness,
# nullability, constraint and note, every declared token inside those
# constraints, every syntax, bound and grammar, and every prose note the
# catalog carries. Read off the declarations rather than off the generator's own
# helpers, so each assertion is a second opinion about a cell rather
# than the same string computed twice.


def test_the_reference_is_deterministic() -> None:
    assert events_docgen.reference() == events_docgen.reference()


def test_the_committed_reference_matches_the_catalog() -> None:
    """The same check CI runs, run here too: locally it fails in the
    suite rather than after a push."""
    assert COMMITTED.read_text(encoding="utf-8") == events_docgen.reference(), REGENERATE


def test_the_reference_renders_every_event() -> None:
    rendered = events_docgen.reference()
    for name in documented():
        assert f"### `{name}`" in rendered, f"{name} has no section"
        assert f"| `{name}`" in rendered, f"{name} has no index row"


def test_every_event_renders_exactly_its_declared_variants() -> None:
    """The drift step guards the content of what is rendered; this
    guards that everything is, and nothing else. A generator that
    stopped at an event's first variant would produce a document CI
    diffs happily."""
    rendered = variant_sections()
    assert set(rendered) == set(documented())
    for name, spec in documented().items():
        assert [heading for heading, _ in rendered[name]] == [
            f"#### Variant {position}: `{variant.CHANNEL}` at "
            f"{logging.getLevelName(variant.LEVEL)}"
            for position, variant in enumerate(spec.variants, start=1)
        ], name


def test_the_reference_carries_every_template_byte_for_byte() -> None:
    """The sentence is half the record, and the half a payload rule
    would leave undocumented."""
    rendered = variant_sections()
    for name, spec in documented().items():
        for (heading, body), variant in zip(rendered[name], spec.variants, strict=True):
            assert body[body.index("```text") + 1] == variant.TEMPLATE, f"{name} {heading}"


def test_every_argument_row_matches_its_declaration() -> None:
    """Row for row against the variant it belongs to, rather than by
    hunting for a substring somewhere in a two-thousand-line document.
    A global search is what let the one nullable argument position go
    undocumented while the suite stayed green: every property it
    claimed was true of some other row."""
    rendered = variant_sections()
    for name, spec in documented().items():
        for (heading, body), variant in zip(rendered[name], spec.variants, strict=True):
            where = f"{name} {heading}"
            rendered_args = rendered_values(variant)
            if not rendered_args:
                assert ARGUMENT_HEADER not in body, where
                assert "No arguments: the sentence is fixed." in body, where
                continue
            rows = table(body, ARGUMENT_HEADER)
            assert len(rows) == len(rendered_args), where
            for position, (row, arg) in enumerate(
                zip(rows, rendered_args, strict=True), start=1
            ):
                index, argument, nullable, constraint, note = row
                assert index == str(position), where
                kind_name = arg_kind_named(arg)
                # Name as well as kind: `ARGS` is an ordered tuple of
                # field names, so two same-kinded positions swapped would
                # render identical cells and move nothing committed.
                assert argument == f"`{arg.name}` (`{kind_name}`)", (
                    f"{where} argument {position}"
                )
                assert nullable == yes(arg.nullable), f"{where} argument {position}"
                assert note == cell(arg.rendered_note), f"{where} argument {position}"
                check_constraint(
                    constraint, arg, kind_name, f"{where} argument {position}"
                )


def test_every_field_row_matches_its_declaration() -> None:
    """The same, for the payload half: every declared field in its
    declared order, with the kind, requiredness, nullability, constraint
    and note that field declares and nothing else."""
    rendered = variant_sections()
    for name, spec in documented().items():
        for (heading, body), variant in zip(rendered[name], spec.variants, strict=True):
            where = f"{name} {heading}"
            rows = table(body, FIELD_HEADER)
            carried = carried_values(variant)
            assert [row[0] for row in rows] == [f"`{one.name}`" for one in carried], where
            for row, declared in zip(rows, carried, strict=True):
                field = declared.name
                _, kind, required, nullable, constraint, note = row
                kind_name = kind_named(declared)
                assert kind == f"`{kind_name}`", f"{where} {field}"
                assert required == yes(declared.required), f"{where} {field}"
                assert nullable == yes(declared.nullable), f"{where} {field}"
                assert note == cell(declared.note), f"{where} {field}"
                check_constraint(constraint, declared, kind_name, f"{where} {field}")


def test_both_generations_say_the_same_about_their_cached_count() -> None:
    """A reply round and a recap carry `cache_read_input_tokens` for one
    reason and mean one thing by it (#536), so the reference says the
    same thing on both, absence included: a reader of the recap row alone
    must not take a missing count for a zero."""
    notes = [
        row[5]
        for _, body in variant_sections()["llm_round"]
        for row in table(body, FIELD_HEADER)
        if row[0] == "`cache_read_input_tokens`"
    ]
    assert len(notes) == 2
    assert notes[0] == notes[1]
    assert "Absent where the endpoint did not say" in notes[0]
    assert "`gen_ai.usage.cache_read.input_tokens`" in notes[0]


def test_the_reference_renders_every_declared_prose_note() -> None:
    """The event and variant notes, which are paragraphs rather than
    cells: the field and argument notes are asserted by the two row
    tests above, exactly rather than by presence."""
    rendered = flat(events_docgen.reference())
    for name, spec in documented().items():
        notes = [spec.note, *[variant.NOTE for variant in spec.variants]]
        for note in notes:
            if note:
                assert flat(note) in rendered, f"{name}: a declared note is not rendered"


def test_the_reference_describes_every_kind_it_may_print() -> None:
    """A new kind arrives with its sentence rather than as a bare word
    in a table, which is what makes the taxonomy readable by somebody
    who has not read the registry."""
    rendered = events_docgen.reference()
    for kind in Kind:
        assert kind in events_docgen.KIND_MEANING
        assert f"| `{kind.name}` |" in rendered
    for kind in ArgKind:
        assert kind in events_docgen.ARG_KIND_MEANING
        assert f"| `{kind.name}` |" in rendered


def test_the_reference_prints_every_syntax_and_grammar() -> None:
    """The field tables name these rather than repeating them, so a
    named one the document does not print is a dangling reference."""
    rendered = events_docgen.reference()
    for syntax in SYNTAXES.values():
        assert f"| `{syntax.name}` |" in rendered
    for grammar in GRAMMARS.values():
        assert f"| `{grammar.name}` |" in rendered
        for builder in grammar.builders:
            assert f"`{builder}`" in rendered


def test_a_pattern_that_begins_with_a_space_keeps_it() -> None:
    """Three grammars match a leading space, and both a bare code span
    and the whitespace flattening every other cell gets would eat it,
    which would document a fragment nothing produces."""
    rendered = events_docgen.reference()
    assert "`' from entry \"[\\s\\S]+\"'`" in rendered


def test_the_reference_says_it_is_generated_and_how() -> None:
    """The header every generated document in this repository carries,
    because the first thing a reader does with a wrong line is edit it."""
    rendered = flat(events_docgen.reference())
    assert (
        "Generated from the declarations by `vinga-server events reference`"
        in rendered
    )
    assert "Do not edit this file by hand" in rendered


# --- the command, and a reader who stops reading ------------------------
#
# Three tests, and they are three because the failure has three parts
# that can break separately: the command has to raise where something
# catches it, the catch has to leave nothing that can raise again, and
# the composition of the two has to survive the real command writing a
# real document into a real pipe. A single case covering all three would
# say only that something is wrong.
#
# This first one is the narrow half of the pair the configuration CLI
# carries the other half of. `test_config_cli_events._ClosedPipe` raises
# from `write`, which is the failure a command meets while it is still
# printing; this one raises from `flush`, which is the failure it meets
# only when what it has already printed is pushed out. The second is the
# one that was reaching nobody: a writer that gets a partial write from
# a pipe whose reader has gone keeps the remainder in its buffer and
# returns as if it had printed everything.


class _EmptiedIntoAClosedPipe(io.StringIO):
    """A stdout that takes the document and fails when it is emptied.

    Which is what a stream holding a partial chunk really is once the
    reader has closed: the write that filled the pipe succeeded, and
    nothing has yet tried to move the rest.
    """

    def flush(self) -> None:
        raise BrokenPipeError(32, "Broken pipe")


def test_a_reader_who_stops_reading_between_chunks_gets_the_status(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """The command answers the shell's own status for a reader who has
    read enough, and says nothing about it, even when the failure
    arrives at the flush rather than at the write.

    What this pins is the flush inside the `try`. Without it `main`
    returns 0 here, the buffer is still full, and the interpreter's own
    flush on the way out raises where no arm of this function is left to
    catch it.
    """
    monkeypatch.setattr(sys, "stdout", _EmptiedIntoAClosedPipe())

    assert events_cli.main(["reference"]) == BROKEN_PIPE_STATUS

    printed = capsys.readouterr()
    assert printed.out == ""
    assert printed.err == ""


# --- the command, in a process of its own ------------------------------


# Setting a pipe's capacity is a Linux command and not a portable one:
# macOS has no equivalent and `fcntl` does not export the name there,
# which is why the absence is read from the module rather than from a
# list of platforms somebody has to keep current.
#
# Both tests below want it, and neither is entitled to the other's
# answer to its absence. The first narrows a pipe it would otherwise
# inherit, and without the command it inherits it: a 64 KiB default the
# document still overflows, which is a worse-chosen regime rather than
# no regime, so it runs anyway. The second needs a pipe larger than the
# document and there is no way to ask for one, so it has nothing to run
# and says so. Each states which it is where it is.
SET_PIPE_SIZE = getattr(fcntl, "F_SETPIPE_SZ", None)


def narrowed_pipe() -> tuple[int, int]:
    """A pipe the document below cannot fit into, whatever the host.

    What decides whether the child is cut off is the pipe's capacity
    and not the document's length, so a test that inherits the
    platform's pipe is asserting something about the machine it runs
    on. This one used to, and on a kernel with 16 KiB pages it is
    false: a default pipe is sixteen pages, 262,144 bytes, against a
    reference of 133,861, so the child writes the lot, exits 0, and the
    only thing the failure says is `assert 0 == 141`. Measured on a
    Raspberry Pi 5 (2026-09-21), the same document through the same
    code: cut off at 16,384 and at 65,536, finished cleanly at 262,144.

    So the capacity is stated here instead, one page, which is the
    narrowest a kernel grants. Where it cannot be stated the platform's
    default stands and this test still runs, because a default of
    64 KiB is a pipe this document overflows too, and it is what every
    machine this test has run green on already had. That is a different
    judgement from the near-fit test further down, which skips on such
    a platform: it needs a pipe *larger* than the document, and there
    is no way to ask for one.

    The order of operations is the whole of it. Handing `Popen` a
    `subprocess.PIPE` would have it create the pipe, and by the time
    the parent could reach `child.stdout` to resize it the child is
    already writing into the capacity it was born with. So the pipe is
    made, sized, and its fallback decided here, before there is a child
    at all, and the sized write end is what the child is given.
    """
    read_fd, write_fd = os.pipe()
    if SET_PIPE_SIZE is not None:
        try:
            fcntl.fcntl(write_fd, SET_PIPE_SIZE, resource.getpagesize())
        except OSError:
            # A kernel that refuses the size leaves its default in
            # place, which is the same fallback as not having the
            # command, and the assertion below is what checks it.
            pass
    return read_fd, write_fd


def test_a_reader_who_stops_reading_gets_no_traceback(tmp_path: Path) -> None:
    """`vinga-server events reference | head` is an ordinary thing to
    do with a document this long, and the pipe it goes through here is
    narrower than the document, so the write really does fail rather
    than finishing into the buffer unnoticed. What the reader must
    never see for it is a traceback: a closed pipe is a reader who has
    read enough, and the answer is the shell's own status for one."""
    read_fd, write_fd = narrowed_pipe()
    child = subprocess.Popen(
        [sys.executable, "-m", "vinga_server.main", "events", "reference"],
        cwd=tmp_path,
        env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1"},
        stdout=write_fd,
        stderr=subprocess.PIPE,
        text=True,
    )
    # The child holds the only write end now, so the reader below sees
    # the pipe close when the child goes rather than waiting on a copy
    # this process forgot it had.
    os.close(write_fd)
    assert child.stderr is not None
    reader = os.fdopen(read_fd, "r")
    first = reader.readline()
    # What `head` does: stop reading and close, while the writer is
    # still going.
    reader.close()
    errors = child.stderr.read()
    status = child.wait()
    child.stderr.close()

    assert first == "# Event schema reference\n"
    assert "Traceback" not in errors
    # And not the other spelling either: an unflushable stream at
    # interpreter shutdown prints a complaint without a traceback.
    assert "Exception ignored" not in errors
    assert errors == ""
    assert status == BROKEN_PIPE_STATUS, (
        "the child was never cut off: it wrote the whole document into the "
        "pipe and exited cleanly, so this run proved nothing about a reader "
        "who stops reading. What moved is the buffer rather than the code, "
        "so narrow the pipe further in narrowed_pipe. Widening this to "
        "`status in (0, 141)`, or skipping on capacity, would leave the test "
        "green and empty."
    )


# --- the real command, through the regime that was reaching nobody ----
#
# Which failure a reader who stops reading meets is decided by the
# pipe's capacity against the document's size, and there are three
# answers. A pipe much smaller than the document cuts the writer off
# mid-write, which every version of this code has answered; that is the
# regime the test above asks for by narrowing its pipe to one page. A
# pipe that fits the document reaches no failure at all. The one in
# between is the reported bug.
#
# That middle regime cannot be reached by choosing a capacity and
# hoping, because how much a reader happens to drain before closing
# decides how much the writer gets to absorb: the same capacity and the
# same document answered 120 through a text reader and 0 through a
# binary one, five runs each.
#
# So it is built rather than hoped for, and the construction is the
# plan's, measured there:
#
#   1. A pipe whose capacity is the next power of two above the
#      document, pre-filled so the free space is exactly the document's
#      whole-chunk part.
#   2. A child that writes the document into it, and a parent that reads
#      nothing at all.
#   3. The child fills the free space exactly and blocks. When the
#      parent closes the read end, the kernel hands that blocked write
#      back the bytes it did place, which is a short write rather than a
#      failure, and the remainder is under one buffer, so the stream
#      keeps it and the command returns believing it printed everything.
#
# That remainder is the whole bug. Without a flush inside the boundary
# it is the interpreter's own flush that meets the closed pipe, and it
# meets it where no `except` is left: `Exception ignored` on stderr and
# exit 120.

# How long the parent will wait for the child to stop adding to the
# pipe, and how still it has to be before the parent believes it. A
# child that has filled the pipe is asleep in a write syscall, so the
# count goes from the pre-fill to full and stays there; the deadline is
# generous because what it guards against is a hang, not a slow start.
SETTLE_POLL_S = 0.02
SETTLE_STILL_SAMPLES = 10
SETTLE_DEADLINE_S = 60.0


def queued(read_fd: int) -> int:
    """How many bytes are sitting in the pipe, unread."""
    counted = array.array("i", [0])
    fcntl.ioctl(read_fd, termios.FIONREAD, counted, True)
    return counted[0]


def settled(read_fd: int, filled: int, child: subprocess.Popen[str]) -> int:
    """The pipe's byte count once the child has stopped adding to it.

    Stillness alone would not do, because the child has an interpreter
    to start before it writes its first byte and a parent that sampled
    through that would conclude the child had finished before it began.
    So the count has to move off the pre-fill first, and only then is
    stillness read as the child having written everything it is going to
    write. A child that exited without writing is not waited for either:
    it has nothing more to add and its stderr is what the caller wants
    to see.
    """
    deadline = time.monotonic() + SETTLE_DEADLINE_S
    previous = filled
    moved = False
    still = 0
    while time.monotonic() < deadline:
        time.sleep(SETTLE_POLL_S)
        now = queued(read_fd)
        moved = moved or now != filled
        still = still + 1 if now == previous else 0
        previous = now
        if child.poll() is not None:
            return now
        if moved and still >= SETTLE_STILL_SAMPLES:
            return now
    raise AssertionError(
        f"the child never stopped writing: {previous} bytes in the pipe after "
        f"{SETTLE_DEADLINE_S}s. Nothing reads this pipe, so a child still "
        "moving is a child writing more than the construction left room for."
    )


def test_a_reader_who_stops_reading_mid_chunk_gets_no_traceback(tmp_path: Path) -> None:
    """The real command, through the real failure, answering 141 with
    nothing on stderr.

    This is the only test here that runs `events reference` through the
    near-fit regime, and it is here because the three narrow ones cannot
    see it. They pin that `main` flushes and that the redirect holds a
    retained buffer; a change in how the entry point dispatches, wraps,
    encodes or buffers could put exit 120 back with all three still
    green.

    Two guards make it a regression test rather than a hopeful one. The
    regime is chosen rather than inherited: the free capacity is the
    document's whole-chunk part, derived from the document this test
    just rendered, so it holds whatever the catalog has grown to. And
    the poll's conclusion is checked: the pipe must end exactly full,
    which is what the construction predicts and what a poll that fired
    early cannot produce, since a child still writing leaves it short.
    That assertion is known to be able to fail; the same construction
    against the much larger `config openapi` document comes up one
    buffer short, because a larger document retains more than one
    buffer's worth.
    """
    if SET_PIPE_SIZE is None:
        pytest.skip("setting a pipe's capacity is a Linux command")

    document = events_docgen.reference().encode("utf-8")
    retained = len(document) % io.DEFAULT_BUFFER_SIZE
    assert retained, (
        "the document is an exact multiple of the stream's buffer, so this "
        "construction leaves nothing retained and reaches the wrong regime. "
        "Make the free capacity one buffer smaller than the whole-chunk part "
        "and assert the pipe ends one buffer short of full."
    )
    free = len(document) - retained

    read_fd, write_fd = os.pipe()
    child: subprocess.Popen[str] | None = None
    try:
        try:
            capacity = fcntl.fcntl(write_fd, SET_PIPE_SIZE, 1 << len(document).bit_length())
        except OSError as refused:
            pytest.skip(f"this pipe's capacity could not be set: {refused}")
        # Pre-filled, so what is left is exactly the whole-chunk part
        # however big the document has become.
        filled = capacity - free
        while filled > queued(read_fd):
            os.write(write_fd, b"\0" * (filled - queued(read_fd)))

        environment = {**os.environ, "PYTHONDONTWRITEBYTECODE": "1"}
        # Block buffering is the regime, not an incidental default: an
        # unbuffered stream retains nothing and raises inside `write`,
        # which is the failure the test above reaches.
        environment.pop("PYTHONUNBUFFERED", None)
        child = subprocess.Popen(
            [sys.executable, "-m", "vinga_server.main", "events", "reference"],
            cwd=tmp_path,
            env=environment,
            stdout=write_fd,
            stderr=subprocess.PIPE,
            text=True,
        )
        os.close(write_fd)
        write_fd = -1

        # And the parent reads nothing, ever. What ends the child's
        # write is the read end closing, not a byte leaving the pipe.
        standing = settled(read_fd, filled, child)
        os.close(read_fd)
        read_fd = -1
        errors = child.communicate()[1]
        status = child.returncode
    finally:
        for descriptor in (read_fd, write_fd):
            if descriptor != -1:
                os.close(descriptor)
        if child is not None and child.poll() is None:
            child.kill()
            child.wait()

    assert standing == capacity, (
        f"the pipe holds {standing} of {capacity} bytes, so the child had not "
        "finished writing when the reader closed. That is the mid-write "
        f"regime and not this test's: {errors!r}"
    )
    assert "Traceback" not in errors
    assert "Exception ignored" not in errors, (
        "the remainder the child kept reached the interpreter's own flush, "
        "which is exactly the reported bug: suspect the sys.stdout.flush() "
        "inside the try in events_cli.main"
    )
    assert errors == ""
    assert status == BROKEN_PIPE_STATUS, (
        f"a reader who stopped reading got {status} rather than "
        f"{BROKEN_PIPE_STATUS}"
    )
