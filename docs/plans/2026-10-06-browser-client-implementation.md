# A browser client served by the server: implementation

Companion to [`2026-10-06-browser-client.md`](2026-10-06-browser-client.md),
one section per milestone, appended in the same change that ticks the
milestone checklist. It records deviations from the plan, resolutions
of the plan's open questions, and discoveries.

## M1: the browser credential and the page's home

**Attribution:** anthropic/claude-opus-5-5, thinking high; Claude Code 2.1.289; 2026-10-06.

### What landed

| Decision | Where | Commit |
| --- | --- | --- |
| D1: a browser's identity, minted server side | `onboarding/browser.py` (`mint`, `BrowserIdentity`, `CLIENT_ID_NAMESPACE`), `tests/unit/test_browser_identity.py` | `Mint a browser's identity on the server` |
| Q3, Q3a, Q3b: the subprotocol credential, one identity value handed to the session, auth on and off | `ws.py` (`Credential`, `credential_of`, `presented`, `refusal_reason`), `device/handshake.py` (`Handshake`, `BROWSER_SUBPROTOCOL`), `device/session.py` (the `handshake` parameter and the accept), `tests/unit/test_ws_browser_credential.py` | `Accept a browser's credential as subprotocols` |
| Q2, D2, D2b, D4, D4a: the keyless page, its versioned modules, the unbound start and its refusal | `browser/` (`assets.py`, `router.py`, `static/index.html`, `static/page.js`), `app.py` (mounted with the alias), `config/models.py` (`BROWSER_MOUNT_PATH`, the `ota_path` reservation), `docs/reference/server-config.md` (regenerated), `tests/unit/test_browser_routes.py` | `Serve the browser page and mint an unbound identity` |
| The route-table inventory | `tests/unit/test_route_inventory.py` | `List every served route with what guards it` |
| D7a: the no-leak tests | `tests/unit/test_browser_no_leak.py` | `Hold a browser's token and identity to their homes` |
| The integration handshake | `tests/integration/test_browser_handshake.py` | `Shake hands as a browser through the real server` |
| Documentation footprint | `changelog.d/613-browser-credential.md`, this section | this section's commit |

### Deviations from the plan

1. **D2b: the module path's version is a digest of the served bytes,
   not the build revision.** The plan names
   `/try/static/<revision>/<file>` with `<revision>` the server's build
   revision. `build_info.revision()` answers `unknown` for every wheel
   install (no `VINGA_REVISION`, no checkout), which is how Q5a's lane
   and any `uv tool install` run the server, and a working tree's
   `git describe --dirty` does not move while its files are edited. In
   both places two different module sets would sit behind one
   `immutable` URL, which is the stale-module failure D2b exists to
   prevent. The segment is the first sixteen hex digits of a SHA-256
   over the allowlisted files' names, lengths and bytes
   (`Assets.version`), computed once from the same read the files are
   served from. The test D2b asks for is
   `test_a_new_version_is_a_new_path_and_the_old_one_is_refused`, with
   two builds of different bytes standing for the two releases; a
   mutation that substitutes the revision for the digest fails three
   tests. The URL shape is the plan's.
2. **`server.ota_path` now refuses `/try/` and anything under it.** Not
   in the plan. The OTA router is registered before the browser router,
   so an OTA path at `/try/` would answer the page's own GET; the
   validator already reserves every other fixed prefix for the same
   reason (`/api/`, `/x/`, the probes). `BROWSER_MOUNT_PATH` in
   `config/models.py` is the one constant both the validator and
   `browser/assets.py` read. The field description changed, so
   `docs/reference/server-config.md` was regenerated with
   `uv run vinga-server config reference server`; the domain reference
   and the OpenAPI document were regenerated to a scratch file and are
   unchanged. The changelog fragment carries an `Upgrade:` line for a
   deployment that used such a path.
3. **The identity value has a module of its own,
   `device/handshake.py`.** The plan has `ws.py` build the value and the
   session take it; `ws.py` imports the session, so the type cannot
   live in `ws.py` without a cycle. `ws.py` keeps the reading
   (`presented`, which owns the header precedence and the subprotocol
   rules) and `Credential`, the identity plus the token, which never
   leaves it; the session is handed the token-free `Handshake`.
4. **`refusal_reason` takes the `Credential` rather than the
   websocket.** One reading per upgrade, shared by the gate and the
   session, rather than two parses of the same scope. Its return
   annotation, which `test_event_values.py` pins, is unchanged.
5. **D4a asks the bindings about the minted MAC instead of reading the
   default agent.** `try_identity` mints, resolves the new MAC through
   `DeviceBindings.resolve`, and refuses when it resolves to any name,
   which for a MAC nobody has seen is exactly a default agent being
   set. It is the check-in's own question, so the refusal and what the
   check-in would have done cannot come apart. The minted value is
   discarded on a refusal: nothing is handed over and nothing written.
   The refusal is HTTP 409 with `{"error": <fixed sentence>}`, the
   shape the OTA endpoint's own refusals use; it emits no event, since
   D7 adds no event type.
6. **Small additions to D2's headers.** Every response under `/try/`
   also carries `X-Content-Type-Options: nosniff`, and the modules
   carry `Referrer-Policy: no-referrer` as the page does. The policy is
   `default-src 'none'; script-src 'self'; connect-src 'self';
   style-src 'self'; img-src 'self'; base-uri 'none'; form-action
   'none'; frame-ancestors 'none'`. M3 may need to widen it (a worklet
   module is governed by `script-src`, which `'self'` already covers).

### Resolutions

- **Closed sets.** No new `AuthRejection` member. In a browser's list
  a fact counts only when exactly one value offers it; none or two is
  the fact missing, which the existing checks answer as they answer a
  board missing it: no token is `no_token`, an identity that is not
  the one the token was signed for is `bad_token`, and with device
  authentication off an unusable MAC is answered by the session after
  the accept with the board's close reason and `RejectedBadDeviceId`.
- **Header precedence.** Any one of `Authorization`, `Device-Id` and
  `Client-Id` present makes the request a board's, read off its
  headers alone; so does a list without `vinga.device.v1`, which is
  what keeps a headerless request meeting the refusal it always met.
- **The accept.** A board's session calls `accept()` with no argument,
  as before; a browser's calls `accept(subprotocol=...)` with the
  constant the `Handshake` carries, never an offered value. The split
  is spelled out because the suites' fake sockets take no argument, and
  `subprotocol=None` would have changed every one of them.
- **The minted MAC's format.** Lowercase colon form, which is what
  `normalize_mac` returns and what a board's events carry; the page
  will send it in `Device-Id` on its check-in and as twelve bare hex
  digits in `vinga.mac.*`, where a colon is not a legal character.

### Discoveries

- **FastAPI 0.140 keeps included routers nested.** `app.routes` holds
  `_IncludedRouter` objects rather than the routes, so a walk over it
  lists the probes and nothing else. The inventory reads the table
  through `fastapi.routing.iter_route_contexts`, the public iterator
  the OpenAPI builder uses, and checks the guards it names by request
  rather than by label.
- **uvicorn traces the `Sec-WebSocket-Protocol` header at DEBUG.**
  With the vendor floor lifted off `uvicorn.error`
  (`tests.support.leaks.unfloored`), the integration case finds the
  browser's token in uvicorn's header trace and fails; with the floor
  `create_app` applies, it does not. The floor is therefore what keeps a
  browser's token out of a DEBUG log, exactly as it keeps a board's
  `Authorization` out. Removing the test's own `quiet_vendor_libraries`
  call changes nothing, because `create_app` applies the floor itself
  (`logs.quiet_vendor_libraries()` at its top).
- **Path traversal never reaches the handler through the test client.**
  httpx resolves a literal `..` before sending, so the escaped forms
  (`%2e%2e`, `..%2F...`) are the ones that exercise the allowlist; the
  mutation that served from the directory instead was caught by those
  and by `index.html`.

### Tests first, and the mutations

The identity tests were written first and watched failing (an
`ImportError` on `vinga_server.onboarding.browser`). For the
credential, the page routes and the mint, the implementation was
drafted before the tests that pin it, so the falsification is the
mutation runs below, one run each against the named tests, every one
killed. Logs are in the worktree's `.logs/mutations-*.log`.

| Guard | Mutation | Killed by |
| --- | --- | --- |
| MAC bit rule | drop the `0x02` set | `test_the_first_octet_is_locally_administered_and_unicast` (3 cases), `test_the_default_randomness_is_the_operating_systems` |
| MAC bit rule | drop the `0x01` clear | `test_the_first_octet_is_locally_administered_and_unicast` (4 cases), `test_the_mac_is_normalized_and_the_client_id_is_derived_from_it` |
| Default randomness | `os.urandom` for `secrets.token_bytes` | `test_the_default_randomness_is_the_operating_systems` |
| Distinct namespace | the simulator's namespace | `test_a_browser_and_a_simulated_board_never_share_a_client_id` |
| Header precedence | subprotocols read even with headers present | `test_any_one_credential_header_makes_the_request_a_boards` (3), `test_headers_win_over_a_valid_subprotocol_credential`, `test_a_board_offering_subprotocols_is_still_a_board` |
| The token never echoed | accept the first offered value | `test_the_token_value_is_never_the_selected_protocol` |
| The token never echoed | accept the `vinga.token.*` value | `test_an_accepted_token_reaches_only_the_reply_that_handed_it_over` and five handshake tests |
| The token check | skipped for a browser | `test_a_missing_or_bad_token_never_reaches_the_accept` (4), `test_a_token_for_another_identity_is_refused` (3) |
| Q3a | session not handed the handshake | five handshake tests; the integration case |
| Ambiguous lists | a duplicated fact accepted | `test_a_malformed_list_reads_as_the_fact_missing` (2), `[values3-no_token]`, `[two macs]` |
| No leak | the offered list logged at DEBUG | both token no-leak tests; the integration case |
| No leak | the token in `Credential`'s repr | `test_the_token_is_not_in_a_credentials_representation` |
| No leak | a refusal logging the credential's repr | `test_a_refused_token_reaches_nothing` (the offered MAC; the token itself stays out of the repr, so the first version of this test, which hunted only the token, let it survive) |
| No leak | the browser's MAC in a field a board's is not in | `test_a_browsers_identity_reaches_exactly_the_fields_a_boards_does` |
| Allowlist | serve any name from the static directory | `test_only_the_allowlist_is_served` (7), the module and upgrade tests |
| D2b | version not checked | `test_another_version_is_not_served`, `test_a_new_version_is_a_new_path_and_the_old_one_is_refused` |
| D2b | the revision for the digest | three version tests |
| D2 | page cacheable; CSP removed; `Referrer-Policy` removed | the page header tests |
| D4a | the refusal removed | `test_with_a_default_agent_the_mint_refuses_and_admits_nothing` |
| Key guard | `try-identity` unguarded | `test_a_wrong_key_meets_the_alias_stock_404` (3), `test_every_key_guarded_route_meets_a_wrong_key_with_the_stock_404` (2) |
| Mounting | not mounted; mounted with onboarding off | nine route tests; `test_nothing_is_mounted_with_onboarding_off` |
| Reservation | the `/try/` check removed | `test_an_ota_path_under_the_page_is_refused` (2) |
| Inventory | an unnamed route added | `test_every_route_is_named_with_what_guards_it` |

One survivor, recorded rather than counted as a kill: the integration
case still passed with its own `quiet_vendor_libraries` call removed,
which is the discovery above, and it fails once the floor is lifted.

### Verification

Run on agentpi (four cores), each line quoted from the log written in
the worktree's `.logs/`:

- `uv run ruff check .`: `All checks passed!`
- `uv run pytest tests/unit -q -n auto --dist loadfile`:
  `8208 passed, 19 skipped in 912.58s (0:15:12)`
- `uv run pytest tests/integration -q -n auto --dist loadfile`:
  `354 passed in 212.47s (0:03:32)`
- The six generated references the server workflow diffs were
  regenerated to a scratch directory and compared: only
  `server-config.md` moved, and it matches the committed regeneration.
- The wheel built with `uv build --wheel` carries
  `vinga_server/browser/static/index.html` and `static/page.js`.
- `python3 scripts/check_doc_links.py .`: `checked 333 files, 0 failures`
- `uv run pytest tests/census -q`, last, after this section: `66 passed in 27.61s`

Not verified here: the page in a real browser. The placeholder only
proves the routes; M3's lane is the first to load it in Chromium.
