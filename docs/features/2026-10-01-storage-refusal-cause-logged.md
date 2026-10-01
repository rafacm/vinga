# An API storage refusal's log line names what failed

**Date:** 2026-10-01

**Local baseline:** not applicable. The change is to what one log line
says about a failure, on every deployment alike; no capability is added
or moved.

## Problem

Two API refusals told the operator where to look, and the place they
pointed did not have the answer (#586):

- a memory write the database refused: "memory could not be written,
  and nothing was changed. The details are in the server's log";
- a conversation erasure the database refused: "the conversation store
  could not be written, and nothing was deleted. The details are in the
  server's log".

Each refusal is built fresh in a bare `except Exception` and raised
after the block, deliberately, so none of the driver's text and no
exception chain travels: a driver error quotes the DSN it connected on
and carries the statement it ran with the values bound to it, which
here are an owner, a remembered fact and a key. The one line the
request then produced was the API refusal handler's `api_storage_error`,
whose class was `ClassName.of` the exception the handler was given. By
then that was the `StorageError` the site had built, so the line said
`StorageError` and the class of what actually failed was gone before
anything could record it.

The #530 feature doc found this while making the boot path's storage
refusal name its cause's class, and recorded it rather than fixing it,
because the fix is a change to the API's event surface.

Step 0 found the same promise in five more places: the 500 descriptions
of the committed OpenAPI document for the configuration, conversation,
thread, metrics and memory namespaces, each ending "The details are in
the server's log." And one sibling the issue did not name: the
configuration store's own storage refusal, which since #530 names the
cause's class in its sentence (so the 500's body says what failed)
while the log line for the same request still said `StorageError`.

## Changes

### The refusal carries its cause's class, and the handler logs it

`StorageError` takes a keyword-only `cause`: the class name of the
failure the refusal was decided from, as a validated `ClassName`, or
None. Never the exception: the value type admits an identifier and
nothing else, so nothing of the failure's words can ride on it, and
anything that walks the refusal's attributes finds a name.

It is set where the classifying happens, by a new `db.failure_class`,
which is `db.failure_name`'s validation in value form. `failure_name`
is now derived from it, so the sentence form and the value form cannot
disagree about which names are sayable; a class whose name is not an
identifier gives None, rather than raising while the refusal is being
built and losing its body.

The API's refusal handler names the refusal's `cause` where it carries
one and the refusal's own class otherwise:

```python
cause = exc.cause if isinstance(exc, StorageError) else None
named = cause if cause is not None else ClassName.of(exc)
events.emit(lambda: ApiStorageError(failure=named))
```

So a refusal with no cause is exactly what it was: a stored row that
will not read as configuration still logs
`StoredConfigUnreadableError`, and a forged class name leaves the line
naming `StorageError`.

### The sites that set it

| Site | Before | After |
| --- | --- | --- |
| `memory/api.py` `_written` | `StorageError` | the driver failure's class |
| `conversations/api.py` erasure | `StorageError` | the driver failure's class |
| `config/store.py` `_database_problem` | `StorageError` (body named the class) | the same class the body names |
| `app.py` reload rewrap | `StorageError` (cause dropped) | the store refusal's cause, passed on |
| `app.py` diff rewrap | `StorageError` (cause dropped) | the store refusal's cause, passed on |
| `config/reload.py` untyped failure | `StorageError` | the failure's class |

The last three answer "The failure is recorded in this server's log",
and the reload's comment said the class was "named by class in the
event beside this". The event beside it, `mcp_reload`, records the
refusal's kind as a token; nothing recorded the class. The comment now
says what is recorded and where.

No response body, sentence or status changes. The two sentences that
promise "the details" are response bodies and stay byte for byte; what
they point to is now true, and a comment above each says what "the
details" are.

### The OpenAPI descriptions say what the log holds

What the log holds for any 500 these routes answer is one line naming
a class: `api_storage_error` as above, or `api_error` for a failure
nothing handled, which the last-resort middleware has always logged by
class. "The details" promised more, so the five descriptions now end
"The server's log names the class of what failed, and nothing else of
it." The committed document is regenerated through
`vinga-server config openapi`; its diff is those 62 description lines.

## The shape, and what the other would have cost

The issue left two shapes open: the refusal carries the cause's class
as a structured attribute the handler reads, or each site emits a typed
event of its own before raising.

The attribute won on the proportion test. It is one code path: one
keyword at each of six sites and one read in the handler, with no new
catalog entry, and the reload and diff rewraps join it by passing one
attribute on. The typed event would have been a new catalog declaration
(or a widened existing one), an emission at every site, and a second
line per failure beside the `api_storage_error` the handler still
writes, so an operator would read two lines about one 500, the first
naming the cause and the second still naming `StorageError`. It would
also have put an emission inside `config/store.py`'s classifier, which
a CLI invocation runs too, where no API line follows it.

Within the attribute shape, the existing `failure` value carries the
cause rather than a second field beside it. Where a cause is carried,
the refusal's own class is `StorageError` at every site that sets one,
which says nothing the event's name does not, so a second field would
have spent a new closed value on a constant. The field's rendered note
in the catalog now states the rule, and the generated events reference
moved with it. `failure` is `carried=False` (rendered into the sentence
rather than kept in the payload), so the change reaches both log
formats through the sentence; a payload-only field would have been
invisible in the default text format.

The cost of that choice is a value change, which the changelog states:
a consumer matching `(StorageError)` for these failures now sees the
cause's class. The precedent is #507, which changed the same value from
`StorageError` to `StoredConfigUnreadableError` and recorded it the
same way.

The `ClassName` annotation on `StorageError` is imported under
`TYPE_CHECKING`: the event vocabulary package imports the event
catalog, and a configuration client that never logs an event should
not load it. The value is always built on the server side, by
`db.failure_class`.

## Key parameters

- `StorageError.cause`: `ClassName | None`, keyword-only, default None.
- `db.failure_class(exc) -> ClassName | None`: the validated class name,
  or None for a name `ClassName` refuses. `db.failure_name` is derived
  from it.
- `api_storage_error`'s `failure`: the refusal's `cause` where set,
  else `ClassName.of` the refusal. Template, level and payload keys are
  unchanged.
- The 500 description sentence: "The server's log names the class of
  what failed, and nothing else of it."

## What was found and deliberately left

- **The configuration store's refusal carries the driver error on its
  `__context__`.** `ConfigStore`'s transaction translates a database
  failure inside a generator context manager, and an exception raised
  while `__exit__` handles another takes that one as its context,
  wherever in the generator it is raised; the transaction's docstring
  says the refusal is raised "so that the exception holding them is not
  attached to it either", which is not so. Probed against the code
  before this change: the refusal's `__context__` is SQLAlchemy's
  `ProgrammingError`, with psycopg's `RaiseException` under it, both
  holding the planted value. Nothing that answers or logs a refusal
  walks the chain today (the API handler names a class, the CLI prints
  the sentence), so no retained surface carries it, but the
  configuration case below asserts the body and every log record and
  says in a comment why it does not assert the chain. Left for its own
  issue: the fix is a restructuring of every store write's transaction,
  not a line here.
- **`api_storage_error`'s sentence** says "the configuration API met
  unreadable stored state" for a memory write or an erasure the
  database refused, neither of which is configuration or unreadable.
  The handler also emits it for the 503 `NoRuntimeError`, which is not
  a storage failure at all. Both predate this change and both are the
  event's template and declaration, a separate decision about a
  committed surface.
- **The boot path's migration refusal** names its class in its own
  sentence (#530) and does not set `cause`: it is raised to stderr at
  boot or by the standalone API's lifespan, never through the API's
  refusal handler, so nothing would read it.
- **#565**, which owns one helper for every rendered exception class
  name beside `ClassName.of`, is not pre-empted: `db.failure_class` is
  the storage refusals' helper over the existing value type, and folds
  into #565's when it lands, as `failure_name` does.

## Inventory

Every claim in the tracked tree that the details of a failure are in the
log, found with `git grep -n -i -E "details are in" -- .`, read in full:
70 lines. 62 are the generated OpenAPI document's 500 descriptions
(regenerated), 5 are the source of those descriptions (`config/api.py`
1, `conversations/api.py` 3, `memory/api.py` 1, all reworded), 2 are
the two response sentences (`memory/api.py`, split across two string
lines, and `conversations/api.py`; made true, unchanged), and 1 is the
#530 feature doc's record of the gap (a dated record, left as written).

The sibling phrasing "recorded in its log" / "recorded in this server's
log", found with `git grep -n -i -E "server's log|in (its|the) log" --
vinga-server/src` (read in full), has four sentences: the last-resort
500's `_UNEXPECTED` (already true: `api_error` names the class), and
the reload's and the diff's unreadable sentences in `app.py` and
`config/reload.py`, which now carry the cause as above. The rest of
that search is the five descriptions above, one OpenAPI description
saying nothing sent is quoted back in the log (a different claim, and
true), and comments about other logs.

## Verification

- Pins first: the three response bodies (memory, erasure, configuration
  write) were pinned byte for byte against the code before the change,
  green, and the pins were not edited afterwards.
- New cases, each failing before the change it belongs to: the memory
  and erasure routes log `(OperationalError)` for a planted SQLAlchemy
  `OperationalError` (both logged `(StorageError)` before); the
  configuration write logs `(ProgrammingError)` for a real trigger's
  refusal (logged `(StorageError)` before); the reload keeps the
  class of a storage refusal and of an untyped failure, and the diff of
  a storage refusal (all three came back None with `app.py` and
  `config/reload.py` restored to the commit before). The existing
  memory API case that asserted `(StorageError)` now asserts
  `(ProgrammingError)`.
- Forged class names, per site: memory and erasure through the API,
  the store through its forged-class case, the reload through a forged
  untyped failure. Each answers its usual body and leaves the line
  naming the refusal.
- The sentinel: a credential-shaped value planted in the failing
  exception's message (a DSN in the driver error), in the statement and
  its bound parameters, and on its `__cause__`, held absent from the
  body, every log record in both formats and the record object
  (`leaks.renderings`), and, for memory and erasure, everything the
  refusal carries (`leaks.chain`) with no `__cause__` or `__context__`.
  For the configuration write the value is in the trigger's words, the
  driver error and the bound body; the chain is not asserted there, as
  recorded above.
- Mutations, each applied to a copy, run against the targeted set and
  restored, eleven in all and every one killed: the handler ignoring
  the cause; each of the four sites spelling
  `ClassName(type(exc).__name__)` instead of `db.failure_class`; the
  memory site reading `exc.__cause__`, the store reading `exc.orig` and
  the erasure reading the wrong local; the memory site holding the
  exception itself (the event refuses to build, so no line is logged);
  `db.failure_class` without its validation; and the diff dropping the
  cause it was handed.

## Files modified

- `vinga-server/src/vinga_server/config/loader.py`
- `vinga-server/src/vinga_server/db/__init__.py`
- `vinga-server/src/vinga_server/config/api.py`
- `vinga-server/src/vinga_server/config/store.py`
- `vinga-server/src/vinga_server/config/reload.py`
- `vinga-server/src/vinga_server/app.py`
- `vinga-server/src/vinga_server/memory/api.py`
- `vinga-server/src/vinga_server/conversations/api.py`
- `vinga-server/src/vinga_server/events/catalog.py`
- `vinga-server/tests/unit/test_api_storage_refusals.py` (new)
- `vinga-server/tests/unit/test_memory_api.py`
- `vinga-server/tests/unit/test_config_refusals.py`
- `vinga-server/tests/unit/test_config_reload.py`
- `vinga-server/tests/unit/test_config_diff_read.py`
- `docs/reference/events.md` (generated)
- `docs/reference/api-openapi.json` (generated)
- `changelog.d/586-storage-refusal-cause-logged.md`
- `docs/features/2026-10-01-storage-refusal-cause-logged.md`
