# Every caught exception's class is named through one validated helper

**Date:** 2026-10-02

**Local baseline:** not applicable. The change is to what a log line,
a CLI sentence or an error message says about a failure whose class
name is not an identifier, on every deployment alike; no capability is
added, removed or moved off the machine.

## Problem

A failure is reported by its class and never by its words, because a
type name says what went wrong and a message says what a stranger
wrote. But a class name is not safe merely for being a class name:
`type(name, (Exception,), {})` accepts any string as `name`, a line
break and a forged log line after it included (recorded in PR #217's
review and in `events/__init__.py`). Probed again for this change,
`type("ghp_Secret\nFORGED line", (RuntimeError,), {})` keeps its line
break, and a raw site that logged it put the break in the record's
message, so the text log format printed a second line reading
`FORGED line` as though this server had written it.

The typed event path has guarded against this since #217: `ClassName`
admits an identifier and nothing else, and a value it refuses makes the
emission refused. Twenty-eight other sites in sixteen files spelled
`type(exc).__name__` (or `type(failure)`, `type(forgetting)`) straight
into a retained log line, a CLI sentence, or the message of an
exception rendered later, and nothing checked the string.

Two storage refusals already had the answer. #530 added
`db.failure_name` and `db.UNNAMED_FAILURE` (`ClassName`'s validation,
with a fixed phrase where it refuses), and #586 added `db.failure_class`
beside them, the same validation in value form. Both were scoped to
storage by name and docstring.

The exposure today is close to none: the provider SDKs raise fixed
classes, and MCP errors cross the transport as JSON rather than as
Python classes. This is defense in depth, closing the raw path before a
dependency that mints classes from remote data arrives.

## Changes

### One rule, in a leaf both paths can import

`vinga_server/class_names.py` is new, and imports only `re` and
`typing`. It holds `CLASS_NAME_PATTERN` (moved from `events/values.py`),
`is_class_name`, `class_name_of` (added in the review round, below),
and `UNNAMED_FAILURE` and `failure_name`, both moved out of `db`.
`ClassName.__post_init__` now admits a value by `is_class_name`,
so the typed path and the sentence path read one definition of a
sayable class name; `ClassNames` applies it to each part of a joined
group as before. `failure_class`, which returns a `ClassName`, stays in
`events/values.py` beside `ClassName.of`, and `db` no longer exports
any of the three.

The issue and its Step 0 comment named `events/values.py` as the home.
The import graph overruled that for the sentence half: two modules the
configuration CLI reaches at import, `device_endpoint` and
`protocol.messages`, name classes in their sentences, and importing
`events.values` from them pulls `events`, `events.catalog`,
`memory` and `memory.scopes` into the CLI, which
`tests/unit/test_cli_import_weight.py` refused on the first run of the
sweep. A leaf is the smallest home both the CLI tier and the event
vocabulary can import, and `vinga_server.class_names` joins `CLI_REACH`
with its reason written beside the others.

### The fallback is decided once

`UNNAMED_FAILURE` keeps the wording #530 gave it, "an exception whose
class name is not an identifier". Every sentence it can now land in was
read with it in place: after a colon (`session <id>: reply failed:
...`), inside parentheses (`the drain failed (...)`, `not valid JSON
(...)`), and after "failed with" (`<label>: the request failed with
...`). All read as English, so no site was reworded and there is one
fallback for every channel.

Two sites hand the name on to a `ClassName` rather than to a sentence:
`runtime/tool_execution.py`'s `error_type`, which becomes a
`tool_call` event's `error`, and `tools/mcp/transport.py`'s `_reason`,
which becomes the `failure` of `mcp_down` and the `error` of
`mcp_call_dropped` through `ClassNames`, as well as a status reason and
a log argument. For a forged name the
phrase is refused there exactly as the forged name was, so those
emissions are refused as before; `test_class_names.py` pins that the
phrase itself is never an admissible class name.

### The sweep

Every in-scope site now calls `class_names.failure_name`:

| Sites | File |
| --- | --- |
| 6 | `runtime/pipeline.py` (reply failure, endpointer forget, two turn-recorder skips, two recap failures) |
| 3 | `simulator/conversation.py` (`cannot_open`, two `cannot_speak`) |
| 2 each | `device_endpoint.py`, `providers/kit.py`, `device/placement.py`, `runtime/filler_runner.py`, `conversations/threads.py` |
| 1 each | `serving.py`, `runtime/turntaking.py`, `runtime/tool_execution.py`, `providers/world.py`, `providers/registry.py`, `protocol/messages.py`, `device/session.py`, `config/reload.py`, `tools/mcp/transport.py` |

That is the issue's table less `config/store.py`, which #530 had
already moved, and with `runtime/pipeline.py`'s sixth site the issue
listed separately.

### The guard

`tests/unit/test_class_name_sites.py` walks the production package's
AST for every `type(<x>).__name__` and `<x>.__class__.__name__`, and
their `__qualname__` spellings, matching the shape whatever the
variable is called, and holds the set of reads to an allowlist with a
reason per entry, both ways, so a stale entry fails as well as a new
site. The allowlist is the one read the rule is concentrated into,
`class_names.class_name_of` (before the review round it was two,
`failure_name` and `ClassName.of`), and seven program-type reads the issue puts out of
scope: a provider factory's product (`providers/registry.py`), an event
variant naming itself (`events/catalog.py`), an event tap
(`events/__init__.py`), and four parsed configuration shapes
(`config/loader.py`, `config/store.py`, two in `config/transport.py`).

Two limits are stated in the file: a class reached any other way
(`kind = type(exc)` and then `kind.__name__`, or `getattr`) passes, and
tests are not scanned, since they build forged classes on purpose.

### The house rule

The implement-issue skill's no-leak lens said "Render exception classes,
never their words". It now says render validated class names, and names
how: `class_names.failure_name(exc)` in a sentence, `ClassName.of` or
`failure_class` in an event, never a bare `type(exc).__name__`. The
external-review PR prompt's no-leak bullet carries the same clause.
`docs/architecture/observability-surfaces.md` states no
class-rendering rule of its own, so it did not change.

## Key parameters

- `class_names.CLASS_NAME_PATTERN`: `[A-Za-z_][A-Za-z0-9_]*`, unchanged,
  anchored at both ends by `is_class_name`.
- `class_names.UNNAMED_FAILURE`: "an exception whose class name is not
  an identifier", unchanged from #530.
- `class_names.is_class_name(text)`: a plain `str` (never a subclass)
  that matches the pattern.
- `class_names.class_name_of(exc) -> str | None`: the one total read of
  a failure's class name, which never raises.
- `class_names.failure_name(exc) -> str` and
  `events.values.failure_class(exc) -> ClassName | None`: the sentence
  form and the value form, both reading through `class_name_of`, as
  `ClassName.of` does.

No configuration key, event field, API response or generated reference
changed.

## Verification

- **Inventory**, untruncated, from `vinga-server/` at `4f768b16`:
  `grep -rnE "type\((exc|failure|raised|forgetting)\)\.__name__" src`
  returned 31 lines: the 28 sites above, `ClassName.of`, and two
  docstrings. Widened to `grep -rnE
  "type\([^()]*\)\.__name__|\.__class__\.__name__|__qualname__" src`
  (38 lines), the seven extra lines are the program-type reads the
  guard allowlists. The guard's own AST walk is the inventory from here
  on: at this branch's head it finds exactly the eight allowlisted reads.
- **A lawful name renders byte for byte as before**, proved two ways.
  An AST comparison of each of the sixteen swept files against its
  pre-sweep self, with every `failure_name(x)` read back as
  `type(x).__name__` and the new import dropped, found all sixteen
  identical (and reported a difference when one log sentence was
  reworded in a copy, so the comparison has teeth). And three sites are
  pinned end to end for a lawful name and driven with the forged one,
  one per kind of surface: a log line (`device/placement.py`, as
  `record.msg` and typed `record.args`), an exception message
  (`providers/kit.py`'s `call_failure`) and a CLI sentence
  (`device_endpoint.close_failed`). Against the raw sites the three
  forged cases failed and the three lawful ones passed; after the
  sweep all six pass. `test_class_names.py` also names every builtin
  exception class Python ships through `failure_name` and compares it
  with `__name__`.
- **Mutations**, each restored by copy and touched, one run each, all
  killed: `failure_name` returning the raw name (3 failures, including
  the two forged-name storage tests that were already there); the pattern unanchored (15);
  `failure_class` without its `except` (2); a raw `type(exc).__name__`
  reintroduced in `device/placement.py` and a
  `forgetting.__class__.__name__` in `runtime/pipeline.py` (the guard,
  naming the file, scope and line each time); a stale allowlist entry
  (the guard).
- **Lanes**, at the code this branch ends on, on a shared 4-core
  machine with `-n 2 --dist loadfile`: unit `7861 passed, 19 skipped in
  1481.48s`, the skips being the faster-whisper and piper extras, which
  are not installed; integration `350 passed in 398.49s`. `ruff check`
  clean, and the census lane run last.

## Review round

One external review round (openai/gpt-5.6-sol, at `5613d5fe`) found one
P1, and it was right. `failure_name` passed `type(failure).__name__`
straight to the pattern, and a metaclass decides what `__name__`
answers. A number made the helper raise `TypeError`, and a lookup that
raised escaped as itself; both happened inside the caller's `except`
arm, so the failure being reported rode out as `__context__`, its
message with it. Driven end to end at `device/placement.py`'s
relocation, the unfixed helper let `TypeError` and the lookup's own
`RuntimeError` (carrying the planted credential) escape instead of the
site's refusal. #530's storage helper had gone through `ClassName`,
which refused a non-string, so this was a regression as well as a gap.

The fix makes the read total, in one place: `class_names.class_name_of`
contains a raising lookup (`Exception` only, so a cancellation or an
interpreter exit still propagates) and answers None for anything but a
plain identifier. `failure_name`, `failure_class` and `ClassName.of`
all read through it, so a class whose name cannot be read is the fixed
phrase in a sentence, None as a value, and an `EventValueError` from
the typed constructor, which is the refusal the emitter's guard
reports by a fixed label.

It goes one step further than the finding. `is_class_name` now refuses
a `str` subclass, not only a non-string: a subclass can match the
pattern and still print a forged line through its own `__format__` and
`__str__`, and the unfixed helper returned one as the name.

Sentinels for all three shapes (a number, a `str` subclass, a raising
lookup), each raised and reported from inside an active `except` with
a credential-shaped message, at the helpers and end to end at the
relocation site, were watched failing against the unfixed helper (six
helper cases, both site cases). Four mutations of the fix, one run
each, were all killed: the lookup uncontained (3 failures), the
plain-string check dropped (6), `isinstance` in place of the exact type
(3), and `ClassName.of` reading the name raw again (3, the AST guard
among them). The unit lane was rerun on the fix at `-n 2 --dist loadfile`: `7870 passed, 19 skipped in 1264.86s`.

## What was checked and deliberately left

- **Identifier-shaped secrets** pass the pattern, on the typed path and
  the helper's alike (`sk_live_abc123`). Out of scope by the issue.
- **What a broken log handler prints** is #564's.
- **`tool_execution`'s tool result text** still interpolates
  `str(exc)` into what the model is told (`the tool "<name>" failed:
  <exc>`). That is conversation content rather than a retained log line
  or a class name, and it is not this issue's surface.
- **The two `ClassName`-bound sites** keep refusing a forged name's
  emission rather than emitting it without the class. Emitting the
  event with an absent `error` or `failure` would be a change to the
  event vocabulary, which this sweep does not make.
- **The historical feature docs of #530 and #586** name
  `db.failure_name` and `db.failure_class`, which is what those changes
  did; they are records and were not rewritten.
- **The Step 0 comment** credited both helpers to #586; `failure_name`
  and `UNNAMED_FAILURE` came with #530 (`93afdf0d`), and #586 added
  `failure_class` (`b9f07fdc`).

## Files modified

- `vinga-server/src/vinga_server/class_names.py` (new)
- `vinga-server/src/vinga_server/events/values.py`
- `vinga-server/src/vinga_server/db/__init__.py`
- `vinga-server/src/vinga_server/config/loader.py`
- `vinga-server/src/vinga_server/config/reload.py`
- `vinga-server/src/vinga_server/config/store.py`
- `vinga-server/src/vinga_server/conversations/api.py`
- `vinga-server/src/vinga_server/conversations/store.py`
- `vinga-server/src/vinga_server/conversations/threads.py`
- `vinga-server/src/vinga_server/memory/api.py`
- `vinga-server/src/vinga_server/memory/store.py`
- `vinga-server/src/vinga_server/device/placement.py`
- `vinga-server/src/vinga_server/device/session.py`
- `vinga-server/src/vinga_server/device_endpoint.py`
- `vinga-server/src/vinga_server/protocol/messages.py`
- `vinga-server/src/vinga_server/providers/kit.py`
- `vinga-server/src/vinga_server/providers/registry.py`
- `vinga-server/src/vinga_server/providers/world.py`
- `vinga-server/src/vinga_server/runtime/filler_runner.py`
- `vinga-server/src/vinga_server/runtime/pipeline.py`
- `vinga-server/src/vinga_server/runtime/tool_execution.py`
- `vinga-server/src/vinga_server/runtime/turntaking.py`
- `vinga-server/src/vinga_server/serving.py`
- `vinga-server/src/vinga_server/simulator/conversation.py`
- `vinga-server/src/vinga_server/tools/mcp/transport.py`
- `vinga-server/tests/unit/test_class_names.py` (new)
- `vinga-server/tests/unit/test_class_name_sites.py` (new)
- `vinga-server/tests/unit/test_cli_import_weight.py`
- `vinga-server/tests/unit/test_api_storage_refusals.py`
- `vinga-server/tests/unit/test_config_refusals.py`
- `vinga-server/tests/unit/test_db_open.py`
- `vinga-server/tests/unit/test_event_values.py`
- `.claude/skills/implement-issue/SKILL.md`
- `.claude/skills/external-review/pr-review-prompt.md`
- `changelog.d/565-validated-class-names.md`
- `docs/features/2026-10-02-validated-class-names.md`
