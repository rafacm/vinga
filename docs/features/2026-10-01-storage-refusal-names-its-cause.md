# A storage refusal names its cause's class, and the connection sentence only connections

**Date:** 2026-10-01

**Local baseline:** not applicable. The change is to what a refusal
says, on every deployment alike; no capability is added or moved.

## Problem

`db.migration_failure` recognized two causes, a lock that did not
arrive and a database stamped at a revision a re-cut deleted, and
answered everything else with `UNREACHABLE`, the sentence that tells an
operator to check that the instance's host and port name something
running, that the database exists on it, and that the user and password
are the credentials it expects. The catch site above it,
`db.open_url`, is a bare `except Exception` around the whole of
`upgrade_to_head`, so that sentence reached failures on instances that
were up and accepting the credentials throughout: a privilege a
migration was refused, a migration script Alembic could not find, an
answer a server sent back on a connection that worked.

The instance that motivated #530 was the third kind. A tier-closure
install built from a stale `uv` cache lacked a recent migration and met
a database a fuller build had already stamped; Alembic raised `Can't
locate revision identified by '1010_turns_name_their_utterance'`, the
classifier fell through, and the operator (an agent, in that case) was
told the database could not be opened. The real cause was found only by
monkeypatching the classifier to print the exception it was about to
discard, and the wrong diagnosis reached a pull request body and an
implementation record before that.

The privacy rule that makes a storage refusal quote nothing of the
driver's text is right and stays: a psycopg connection error quotes the
DSN it tried, password included, and a statement error carries the
values bound to it. But the configuration store already answered the
same tension in its own storage refusal,
`config/store.py::_database_problem`, by saying the exception's class
name and nothing else. One question, what a storage refusal may say
about its cause, had two answers in two modules, and the weaker one was
on the boot path.

## Changes

### The connection sentence is said for connections

`_unreachable` decides, by type and walked to through `orig` the way
`is_busy` is, whether a failure is a connection that could not be made
or did not survive. It matches psycopg's bare `OperationalError` and
`ConnectionTimeout`, by exact type. Measured against the lane's
instance, every cause the sentence lists arrives as the bare class with
no SQLSTATE: a refused port, a host name that does not resolve, a
database, a role and a password the instance does not have or accept.
`ConnectionTimeout` is the one subclass psycopg raises on its own
account. Exact type rather than `isinstance`, because psycopg files the
SQLSTATEs of classes 53, 55 and 57 under the same `OperationalError`, so
a full disk or a lock timeout would otherwise be told to check that the
instance is running.

### Everything else names its class

A failure no arm has an answer for is now `MIGRATION_FAILED`: the
database could not be brought up to the schema this server runs on, the
exception's class name in parentheses, and why nothing else of the
failure is repeated. It prescribes nothing, which is what the
privilege-failure arm's design already asked of the general sentence:
a schema under the wrong owner or a missing table grant has no single
remedy, and the provisioning rerun named by `SCHEMA_NOT_PERMITTED`
would change nothing for either.

The class name is rendered by `db.failure_name`, through the events
catalog's `ClassName`, which admits an identifier and nothing else. A
class can be given any name at all, a line break and a forged sentence
after it included, so a name the value type refuses is replaced by the
fixed `UNNAMED_FAILURE` rather than printed, and rather than raised,
since a refusal that raised while being built would lose its sentence.

### An unlocatable revision points at the install

Alembic's `CommandError` with a `ResolutionError` on its cause chain is
now an arm of its own, `UNKNOWN_REVISION`, unless the revision is one
the closed `SUPERSEDED_REVISIONS` set names, which keeps its reset
sentence exactly as before. Classified by type and never by the
"Can't locate revision" text; the cause chain is walked rather than
only its first link (`_unlocatable`, which `_stranded` now asks too).

The sentence says the fault is in the install and not in the database,
names the two ways a database gets there (a newer build migrated it and
an older one is opening it, or this install is stale or partial and is
missing a migration its own release ships), and says not to drop or
reset the database. It does not name `uv` or its cache: a deployment
running the published image has neither, and "rebuild or reinstall it
from a clean state" is true of both.

**Which side the revision id comes from, and why it is validated.** The
id is `ResolutionError.argument`, which is the database's stored stamp
from `alembic_version` that the packaged scripts could not resolve. It
is therefore stored data, not this install's own constant, and is
repeated only when it has the shape every committed revision has:
`REVISION_ID_PATTERN`, four digits then lowercase snake-case words, and
at most `REVISION_ID_MAX` (32) characters, the width of the
`version_num` column Alembic creates. Anything else (a credential
pasted into the wrong table, a line break, a different case, a bare
prefix, an overlong value) is replaced by `UNSHAPED_REVISION`. A test
holds every committed revision of all three chains, and the superseded
one, to the pattern, so a migration named some other way fails a lane
rather than being quietly left out of the sentence on the day an
install lacks it. The packaged head was not added to the sentence:
`migration_failure` is not told which chain failed, and the stored id
alone is what tells the two causes apart from outside.

### The two storage refusals agree

`config/store.py::_database_problem` now renders its class name through
the same `db.failure_name`, where it spelled `type(exc).__name__`. Its
sentence is unchanged for every real class name.

## Key parameters

- `db.MIGRATION_FAILED`, `db.UNNAMED_FAILURE`, `db.failure_name`: the
  general sentence, the phrase for a class name that is not an
  identifier, and the one renderer both storage refusals ask.
- `db.UNKNOWN_REVISION`, `db.UNSHAPED_REVISION`,
  `db.REVISION_ID_PATTERN`, `db.REVISION_ID_MAX`: the install-pointing
  sentence and the shape a stored stamp must have to be named in it.
- `db._unreachable` and `_CONNECTION_FAILURES`
  (`{psycopg.OperationalError, psycopg.errors.ConnectionTimeout}`): the
  closed set the connection sentence is said for.
- `db.UNREACHABLE`: unchanged text, narrower use.

No configuration key, event, API response or generated reference
changed. `tests/unit/test_server_reference.py` reads `db.UNREACHABLE`
only to check the variable names it spells, and the new sentences spell
none.

## The sites that answer this question, and the two that disagree

The issue asked whether a third refusal suppresses a safe cause the
same way. Measured over `src/` at this branch's base, four sites catch
a storage failure and classify it with `is_busy`:

| Site | Says the class name? |
| --- | --- |
| `config/store.py::_database_problem` | yes, through `db.failure_name` |
| `db/__init__.py::migration_failure` | yes, through `db.failure_name` |
| `memory/api.py` `_MEMORY_FAILED` | no, deliberately |
| `conversations/api.py` `_ERASURE_FAILED` | no, deliberately |

The last two are left as they are, and the disagreement is recorded
here rather than resolved, for the reason the issue's own non-goals
give: they are operator-facing API responses, and widening what a
refusal says "in any operator-facing API response" is out of scope.
They differ in kind as well as in surface. The two sites that now agree
are refusals raised out of a boot or a CLI invocation, read by the
operator of the process that failed; the other two are 500 bodies
returned to an API client, which is a caller of the server rather than
its operator. No code comment claimed the four agree, so none needed
correcting.

One thing found while checking them is recorded rather than fixed,
because it is outside this change's surface. Both sentences end "The
details are in the server's log". What reaches the log for them is the
API's `api_storage_error` event, whose `failure` is
`ClassName.of(exc)` of the exception the route handler is given, and by
then that is the `StorageError` the site built, raised outside its
handler so the driver's exception is not on its chain. So the log says
`StorageError` and not the cause's class, which is less than the
sentence promises. Closing that gap means the two sites carrying the
cause's class to the event rather than to the response, which the
non-goal does not forbid but which is a change to the API's event
surface and is left for its own issue.

## What was checked and deliberately left

- **`AGENTS.md`'s stale-`uv`-cache section** quotes the old sentence
  (`cannot open the vinga database`) as what the trap reads as. That is
  now false: the trap reads as `UNKNOWN_REVISION` naming the revision.
  The paragraph was not edited by this change; see the pull request.
- **#565**, which owns validating every rendered exception class name
  through one helper beside `ClassName.of`, is not pre-empted.
  `db.failure_name` is a storage-local helper over the existing value
  type, used by the two storage refusals only; when #565 lands its
  helper, this one becomes a call to it or is folded into it.
- **`tests/conftest.py`'s own `UNREACHABLE`** is the test lane's
  sentence, written to the same rule and not a copy, and
  `CaptureUploadFailure.UNREACHABLE` is an unrelated enum member.
  Neither moved.
- **"A resolution failure"** in the issue's second criterion is read as
  Alembic's revision resolution, the failure the issue is about. A host
  name that does not resolve is a connection failure and keeps the
  connection sentence, which a test pins.

## Verification

- Pins first: three connection causes (an unresolvable host, an
  unknown role, a wrong password) were added as tests and passed
  against the unchanged code, beside the two already pinned (a refused
  port, a missing database), and stayed green untouched after the
  reshape.
- The assertions that pinned `UNREACHABLE` were sorted by what they
  drive. The issue's comment counted four occurrences in
  `tests/unit/test_db_open.py`; one is the import, and the three
  equality assertions are two real connection failures (a refused port,
  a missing database), which keep it, and one constructed privilege
  failure, updated deliberately to `MIGRATION_FAILED`. Beyond that file
  the inventory (`git grep`, read in full) found two more that changed:
  the integration lane's wrong-owner case in `test_provisioning.py`,
  updated the same way and confirmed against the real refusal
  (`ProgrammingError`), and `test_conversations_boot.py`'s newer-build
  case, which asserted the revision was absent and now asserts the
  install-pointing sentence naming it. The rest (tier closure, boot
  recovery, `config check`) drive a port nothing listens on and keep
  the connection sentence, and `test_config_refusals.py` asserts a busy
  refusal is not it.
- New cases: a real non-connection failure through `open_at` names
  `CommandError`; a real stamp moved to `9999_from_a_newer_build` is
  told `UNKNOWN_REVISION` naming it and is not `UNREACHABLE`; four
  stored stamps the shape refuses and one overlong one are not
  repeated; a `ResolutionError` one link further down is still found;
  `DiskFull` under `OperationalError` is not the connection sentence and
  `ConnectionTimeout` is; a forged class name is replaced, at both
  storage sites; every committed revision has the shape.
- The sentinel: a credential-shaped value planted in a DSN inside the
  driver's message, in the statement and its bound parameters, and on
  `__cause__`, held absent from the refusal, its arguments, everything
  `tests.support.leaks.chain` walks, stderr, and every log record in
  both formats plus the record object (`leaks.renderings`), at the boot
  door (`serving.run`) and the lifespan door (`create_app`).
- Mutations, each restored by copy and touched afterwards, sixteen in
  all and every one killed: the fallthrough back to `UNREACHABLE`;
  `isinstance` for the exact-type match; `ConnectionTimeout` dropped
  from the set; a raw `type(exc).__name__` in `failure_name`; the
  connection arm removed; its `orig` walk removed; `str(exc)` in place
  of the class; a log line carrying the failure (killed by the
  sentinel's log half); the unknown-revision arm removed; the stamp
  always named; the length bound removed; the pattern admitting
  uppercase; the chain walk cut to its first link; the new arm ahead of
  the superseded one; the pattern unanchored at its end; and the
  store's site put back to the raw class name.

## Files modified

- `vinga-server/src/vinga_server/db/__init__.py`
- `vinga-server/src/vinga_server/config/store.py`
- `vinga-server/tests/unit/test_db_open.py`
- `vinga-server/tests/unit/test_conversations_boot.py`
- `vinga-server/tests/unit/test_config_refusals.py`
- `vinga-server/tests/integration/test_provisioning.py`
- `changelog.d/530-storage-refusal-names-its-cause.md`
- `docs/features/2026-10-01-storage-refusal-names-its-cause.md`
