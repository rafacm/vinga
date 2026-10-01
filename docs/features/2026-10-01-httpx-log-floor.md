# The HTTP client's request line no longer reaches the log

**Date:** 2026-10-01

**Local baseline:** not applicable. The change moves two third-party
loggers' levels in the server's logging setup; no conversational
capability is added, removed or moved off the machine.

## Problem

A no-content audit of a running deployment's stdout (#445) found one
class of line that was neither a typed event nor this server's own
logger prose: httpx's INFO request line, one per outbound request.

```
INFO | httpx | HTTP Request: POST https://api.elevenlabs.io/v1/text-to-speech/<voice_id>/stream?output_format=pcm_24000 "HTTP/1.1 404 Not Found"
```

Nothing secret was in it. Every provider the server speaks to
authenticates in a header, and the configuration refuses a URL whose
query names a credential. But the line is composed by the library
rather than by code the no-leak work audited, it sits outside the closed
event vocabulary the rest of the log is held to, and a provider that one
day carries a key or a session id in a query string would have had it
logged verbatim, at the default level.

It was there on purpose. `VENDOR_LOG_FLOORS` in `logs.py` held `httpx`
and `httpcore` at INFO, and the comment above it argued that the line
was worth keeping: the method, the URL and the status, no headers and no
body. This change reverses that choice, which the issue's Step 0
confirmed with Rafael before any code moved.

## Changes

### Both HTTP client loggers are floored at WARNING

`VENDOR_LOG_FLOORS["httpx"]` and `VENDOR_LOG_FLOORS["httpcore"]` move
from `logging.INFO` to `logging.WARNING`. The mechanism is unchanged:
`quiet_vendor_libraries` holds each logger at the higher of its floor
and the server's level, `logs.configure` applies it with the configured
level, and the two entry points (`main()` and `create_app`, plus the
configuration grammar's command boundary) apply it before anything opens
a socket. So the line is gone at every `server.log_level`, DEBUG
included.

The comment above the mapping now argues the other way. What holding
the line back loses is a line per request, and a failed call's HTTP
status code with it. What it keeps is `provider_failed`, whose fields
are closed (the stage, the provider entry with its type and model, the
host, the duration and the exception's class name), and whose `host` is
the one part of the URL worth retaining. httpcore writes nothing above
DEBUG at the pinned version (1.0.9); it is held with httpx so that
whatever it ever says at INFO about the same connection meets the same
rule.

The escape hatch is unchanged and its sentence is kept accurate: there
is no configuration key, and a diagnosis raises the logger by name in
the process that needs it, after the floor has been applied, since the
floor would otherwise raise it straight back.

### The request boundaries stay, and say why

`config/cli/reach.py` and `device_endpoint.py` each hold httpx and
httpcore at WARNING around a request whose URL is a secret
(`logs.quieted`): an operator's `--api-url`, which may carry
`?token=`, and an OTA URL, which may be the deployment's secret
`ota_path`. Both comments justified that against a floor that kept the
request line deliberately. With the floor at WARNING and applied by
both entry points first, the deletion test asks whether the boundaries
should go.

They stay. The floor is a standing, process-wide setting that `logs.py`
deliberately leaves liftable by name, and a request whose URL is a
secret has to stay quiet when it has been lifted. The two comments now
say that instead.

### The boundary tests run with the floor lifted

Removing a boundary has to fail a test, and after this change it no
longer did: with `quieted` replaced by a null context in `reach.py`,
both narration tests in `test_config_cli_transport.py` passed, because
the CLI's entry point applies the floor before the request and the floor
held the line back in the boundary's place.

They were partly blind before this change too, in an order-dependent
way. Each kills that mutation when run alone under the old INFO floor,
but run in their own file's order a level an earlier case left on httpx
did the boundary's job: `test_config_cli_transport.py` (as the first
file of a batch) and `test_doctor.py` both passed whole with their
boundary removed under the old floor, and
`test_the_quiet_lasts_exactly_as_long_as_the_request` failed when run
alone at `main`.

`tests/support/leaks.unfloored(names)` takes the floor off the named
loggers and clears their own levels for the length of a block, then puts
both back. That is the state of a process that lifted the floor by name,
which is exactly the case the boundary now uniquely covers. The two
narration cases, the level-restore case and the doctor's URL case run
inside it. The level-restore case also gives each logger a distinct
level of its own below WARNING first, so a boundary that never restores
and one that restores NOTSET both fail it; inside the helper alone,
"before" would always read NOTSET and the second would pass.

### The floor tests prove the behavior, not the mapping

The test that pinned the old choice
(`test_the_one_request_line_httpx_writes_survives`) is replaced by
end-to-end tests through `logs.configure`. Each writes through the
handler `configure` installs and reads what it printed:

- a real httpx request, through a mock transport, to a URL whose query
  carries a credential-shaped sentinel, at INFO and at DEBUG: neither
  the sentinel nor `HTTP Request` is printed, while a line of the
  server's own written beside it is, so the absence is the floor and not
  a capture that saw nothing;
- the same request with httpx's level cleared: the sentinel is printed,
  which is the load-bearing half;
- a stand-in INFO record under `httpcore.http11`, carrying the URL,
  since httpcore writes nothing at INFO a real request could show.

A direct pin of `VENDOR_LOG_FLOORS["httpx"] == WARNING` was priced
against this and rejected. It costs the same one test, and it would go
on passing if the request line ever arrived under a name the mapping
does not reach, or if `configure` stopped applying the floor at all;
what is claimed is that the line is not printed, and only a test
through the configured handler says that. The existing
`test_configure_applies_the_floor` already reads every entry of the
mapping back after `configure`.

The boot-path subprocess test reported httpx's level to show that the
floor never makes a quiet process louder. httpx's own floor is now the
level it reported, so it proved nothing there any more; it reports
`openai` instead, whose INFO floor still sits below the WARNING an
unconfigured process runs at.

### Deviations from the Step 0 comment

None in the decisions: both loggers at WARNING, the comment rewritten to
the new reasoning, the escape hatch kept accurate. Two things were done
that Step 0 did not name, both forced by the change: the two boundary
comments in `reach.py` and `device_endpoint.py`, which stated the
reversed reasoning as their own; and the boundary tests, which the new
floor made blind. One correction to the issue's own wording: it lists
`provider_failed`'s fields as `stage`, `provider`, `host`, `outcome`,
`error`, and `outcome` is an argument of the event's sentence rather
than a field. The comment and the changelog name the fields the catalog
declares.

### Discoveries, not acted on

- **uvicorn's per-connection INFO line names the path with its query
  string.** `uvicorn.error` stays floored at INFO, and at INFO uvicorn's
  websockets protocol logs `<client> - "WebSocket <path?query>"
  [accepted]` for every device connection. That is the same class of
  line this change removes on the outbound side: composed by a library,
  outside the event vocabulary. A device authenticates in a header and
  the path is fixed, so nothing secret is known to ride it, but whatever
  a client puts in the query of its upgrade request is printed. Out of
  this issue's scope, which is the HTTP clients.
- **The SDKs have an INFO line of their own.** The openai and anthropic
  clients log `Retrying request to <path> in <n> seconds` at INFO. It
  does not fire today, since every provider builds its client with
  `MAX_RETRIES = 0` (`providers/kit.py`), and it names the endpoint's
  path rather than its query, so the comment above the mapping keeps
  the SDKs at INFO and says why.

## Key parameters

| What | Value |
| --- | --- |
| `VENDOR_LOG_FLOORS["httpx"]` | `logging.INFO` to `logging.WARNING` |
| `VENDOR_LOG_FLOORS["httpcore"]` | `logging.INFO` to `logging.WARNING` |
| Unchanged floors | `anthropic`, `openai`, `uvicorn.error` at INFO; `sqlalchemy` at WARNING |
| Configuration | none added; no key lifts a floor |
| Library versions read | httpx 0.28.1 (INFO request line in `_client.py`), httpcore 1.0.9 (DEBUG only, in `_trace.py`) |

## Verification

- `uv run ruff check .` passes.
- `uv run pytest tests/unit -q -n auto --dist loadfile`: 7697 passed,
  19 skipped in 897.39s.
- `uv run pytest tests/integration -q -n auto --dist loadfile`: 349
  passed in 284.29s.
- `python3 scripts/check_doc_links.py .` and
  `python3 scripts/fold_changelog.py check .` pass.
- Mutations, each run and restored by copy, never by checkout:
  - httpx's floor back at INFO fails both parametrized cases of
    `test_the_request_line_httpx_writes_never_reaches_the_log`;
  - httpcore's floor back at INFO fails
    `test_whatever_httpcore_says_at_info_is_held_with_httpx`;
  - `quieted` replaced by a null context in `reach.py` fails both
    narration cases, in the whole file and alone;
  - the same in `device_endpoint.py` fails
    `test_the_probe_leaves_the_supplied_url_in_no_log_record` in the
    whole of `test_doctor.py`, and
    `test_two_overlapping_requests_neither_unquiet_the_other`;
  - `quieted` restoring NOTSET rather than the saved level fails
    `test_the_quiet_lasts_exactly_as_long_as_the_request`.

## Files modified

- `vinga-server/src/vinga_server/logs.py`
- `vinga-server/src/vinga_server/config/cli/reach.py` (comment)
- `vinga-server/src/vinga_server/device_endpoint.py` (comment)
- `vinga-server/tests/support/leaks.py`
- `vinga-server/tests/unit/test_logs.py`
- `vinga-server/tests/unit/test_config_cli_transport.py`
- `vinga-server/tests/unit/test_doctor.py`
- `changelog.d/445-httpx-log-floor.md`
- `docs/features/2026-10-01-httpx-log-floor.md`
