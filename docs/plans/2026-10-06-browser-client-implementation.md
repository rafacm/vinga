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

### PR review round

Reviewed 2026-10-06 by openai/gpt-6-sol, thinking high via codex CLI 0.160.1, read-only sandbox, runtime 7m24s, at commit c63718b1 ([the round](https://github.com/rafacm/vinga/pull/624#issuecomment-6010633017)). The fixes are by anthropic/claude-opus-5-5, thinking high, a fresh implementer, since M1's own had finished.

1. **P1: a refused module path echoed its input in `Location`.** The
   static route was registered only in its slashless spelling, so
   Starlette's slash redirect answered `/try/static/<invalid>/page.js/`
   with a 307 repeating the invalid version and the query before
   `Assets.file()` could refuse it. *Resolution:* the route is
   registered in both spellings through `spellings()`, the idiom the
   page and the mint already used; a refused module is the stock 404
   in either spelling with no `Location` and the sentinel query nowhere
   in the answer, and the inventory gains a check that every HTTP route
   is served in both spellings, which found no other route with the
   shape and will hold M2's `/try/redeem` to it. Watched failing: three
   307s, and the new check naming the static route (`6b48650c`).
2. **P1: an unreadable bindings answer let the mint proceed.** When
   the database read fails, `DeviceBindings.resolve` answers from the
   snapshot with `authoritative=False`, and a snapshot without a
   default agent let the mint hand out an identity a database default
   agent would later admit unpaired. *Resolution:* after the D4a check,
   a non-authoritative answer refuses with 503 and a fixed `no-store`
   body ("cannot check right now ... try again"), the order and the
   reasoning of `onboarding/unbound.py`'s `unreadable` arm; 503 rather
   than D4a's 409 because nothing is known about a default agent and a
   retry may succeed. The test fails the read, gets the 503 with the
   failure's sentinel absent, then recovers and mints, or gets the 409
   with a default agent stored. Watched failing: both cases minted.
   One survivor, left unpinned: a non-empty non-authoritative answer
   answered 503 instead of 409 still passes; both refuse and hand
   nothing over, so the choice is wording (`b67ef060`).
3. **P1: a default agent set after a mint admits that browser
   unpaired.** *Resolution:* declined, with the window stated in
   `browser/router.py`'s docstring. D4a is a product rule (a cleared
   browser pairs), not an access boundary: under a default agent
   `onboarding/unbound.py` gives a token to every unknown MAC by
   design, so whoever holds the onboarding path already reaches the
   default agent with a made-up MAC through the stock check-in, and an
   identity minted earlier adds nothing to that. Closing the window
   here would take a per-MAC pairing marker that admission enforces,
   which is the second admission rule D4a's plan-review resolution
   rejected; #612 closes it by making every unbound device pair
   (`677d4695`).
4. **P3: the route inventory could not see a duplicate.** *Resolution:*
   the collector counts, and any route registered more than once fails
   the inventory by name. Watched: a planted duplicate `GET /try/`
   passed the set and failed the count (`abc6b115`).

Verification after the round, from the worktree's `.logs/`:

- `uv run ruff check .`: `All checks passed!`
- `uv run pytest tests/unit -q`, serially:
  `2 failed, 8215 passed, 19 skipped in 1867.44s (0:31:07)`. The two
  are `test_logs.py::test_without_the_floor_uvicorn_prints_the_query`
  and `test_what_uvicorn_says_above_info_still_reaches_the_log`, which
  pass alone (`27 passed`) and fail after `test_drain.py` in the same
  process at c63718b1 and on `main` at bbc12d6c (`2 failed, 50 passed`), so they predate this
  round; CI's `--dist loadfile` keeps the two files on separate
  workers. Recorded as a follow-up candidate.
- `uv run pytest tests/integration -q`, serially: `354 passed in 632.85s (0:10:32)`
- `uv run pytest tests/census -q`, last: `66 passed in 30.01s`

## M2: the try link

**Attribution:** anthropic/claude-opus-5-5, thinking high; Claude Code 2.1.291; 2026-10-06.

### What landed

| Decision | Where | Commit |
| --- | --- | --- |
| D5, D5d, D6, D6a: the token store, single use, expiring, bounded | `onboarding/try_links.py` (`TryLinks`), the bounds in `onboarding/__init__.py` (`TRY_LINK_TTL_S`, `TRY_LINK_CAPACITY`, `TRY_LINK_MINTS`), `config/loader.py` (`TryLinkRefusedError`), `tests/unit/test_try_links.py` | `Hold try links in memory, single use and expiring` |
| D5b: bind and name in one transaction | `config/store.py` (`enroll_device`, an `enrolling` condition on `_device_write`), `tests/unit/test_store_enroll_device.py` | `Create a browser's device bound and named at once` |
| D5, D5a, D5c (the server's half), D6b: issuance | `onboarding/try_links.py` (`Issuer`, `link_origin`), `config/api.py` (`POST /runtime/try-links`), `config/responses.py` (`TryLink`, `RefusalReason.NO_DEFAULT_AGENT`), two description files, `composition.py` and `app.py` (one `TryLinks` shared by the API and the page), `docs/reference/api-openapi.json` (regenerated), `tests/unit/test_try_link_issue.py` | `Issue a try link from the configuration API` |
| D5, D5b, D5d, D5e: the inert page and the redemption | `browser/router.py` (`POST /try/redeem`, `same_origin`), `onboarding/try_links.py` (`redeem`), `browser/static/page.js` and `index.html`, the route inventory, `tests/unit/test_try_link_redeem.py` | `Redeem a try link from the page` |
| D5c (the CLI's half): `vinga info`'s line | `config/cli/deployment.py` (`TRY_LINK`), `config/cli/acts.py` (`Act.completes`, `Act.declined`), `config/cli/reach.py` (`Refused`, the `no-default-agent` remedy), `config/cli/grammar.py`, `docs/reference/cli.md` (regenerated), `tests/unit/test_config_cli_try_link.py` | `Print a try link in vinga info` |
| D7a: the try token's two homes | `tests/unit/test_try_link_no_leak.py` | `Hold a try link's token to its two homes` |
| D2a, D5e, the guides | `docs/run/onboarding-a-device.md`, `exposing-a-deployment.md`, `upgrading.md`, `security.md`, `README.md` | `Document the try link and the edge rules it needs` |
| Changelog, this section | `changelog.d/613-try-link.md` | this section's commit |

### Design footprint

What `try_links.py`'s callers stop having to know: when a token
expires, that a spent one is removed rather than flagged, that expired
ones are pruned at every issue and claim, how many may be held, what a
token is made of, and that the claim is one step; when a link may be
issued at all and in which order the four refusals are asked; which
origin a link may name; and what a redemption writes, including the
redraw of a taken MAC and its bound. The API route is four lines (no
runtime, read the default agent, `issuer.issue`, `no-store`); the
redeem route asks the origin, reads the body and hands both to
`redeem`. Neither knows a lifetime, a bound, a name format or a MAC
rule. The store learned one condition (`enrolling`) on the device
write path every device write already takes, rather than a sixth path.

### Deviations from the plan

1. **The server's refusal does not name `vinga default-agent set`; the
   CLI does.** D5a asks for "a fixed sentence naming `vinga
   default-agent set`". A sentence composed on the server must not
   name a command (#386: the server neither ships nor versions the
   client grammar), so the API's 409 says the state in words and
   carries a new reason token, `no-default-agent`, and the CLI's
   `REMEDIES` appends "Set one with `vinga default-agent set <name>`".
   What `vinga info` prints in the link's place is therefore the
   sentence D5a describes. The token is declared at its one decision
   site (`Issuer.issue`) and is in the remedy table, whose coverage
   test holds the two sets equal.
2. **Issuance also refuses on a server with no store behind it.** Not
   in the plan. A server composed from a configuration handed to it
   reads its bindings from that snapshot, so a browser a link wrote
   into the store would not be bound by anything the server reads.
   `SnapshotOnlyError` (409) with a sentence of its own, asked after
   onboarding and before the default agent. Production servers always
   compose from the store; this is the test lane's and an embedded
   caller's state.
3. **A spent token is removed, not flagged.** D5 describes "a used
   flag". Removing the record at the claim is the same answer to every
   caller (spent and unknown are already one refusal) and leaves no
   spent bearer material in memory, which D6a wants anyway.
4. **The claim takes a lock as well as having no await.** D5d's
   argument is the single event loop. The issuing API route is a plain
   `def`, like every route that reads the store, so it runs on a
   worker thread while redemptions claim on the loop; the store's
   `threading.Lock` is what makes issue, prune and claim atomic against
   each other there. The claim itself is still made on the loop with
   nothing between check and removal.
5. **`vinga info` prints the link between the onboarding URL and the
   counts, and its refusal does not fail the command.** The plan says
   "prints that sentence where the link would be". Two new `Act` fields
   carry it: `completes` (the CLI's origin half, which needs the
   address the invocation reached, without making the renderer read
   anything but its argument) and `declined` (print an API refusal in
   place and go on). Only a refusal this API wrote is declined: `reach`
   now raises `Refused`, a `ConfigError` subclass, for a validated
   problem body, and a transport failure still ends `info`. The
   loopback origin keeps the API target's scheme and port (an `https`
   loopback terminator stays `https`) and names `localhost`.
6. **Same-origin is `Sec-Fetch-Site: same-origin`, and nothing else.**
   The plan says "same-origin" without a mechanism. A redemption is
   admitted exactly when the browser's own fetch metadata says
   `same-origin`; an absent header gets the same fixed 403. The first
   version fell back to `Origin` against the `Host` the request
   reached, comparing the authority only (a TLS-terminating proxy hands
   the server `http`), which let a page on `http://host` post to
   `https://host`; PR #625's review found it, and the fallback is gone
   rather than rebuilt with the scheme, because every engine that can
   run the client (WebCodecs Opus: Chromium 94+, Firefox 130+, Safari
   26) sends fetch metadata. Origin and body are both checked before
   the claim, so a refused request spends nothing. The body is read up
   to 1 KiB.
7. **The redeem refusal is 403 `{"error": ...}`**, the body shape M1's
   mint uses, one sentence for every way of not redeeming, `no-store`.

### Resolutions

- **D6's constants:** ten minutes, 32 live links, 3 mints per
  redemption, in `onboarding/__init__.py` beside the activation
  ceremony's bounds and read through the package, the rule that file
  states. No configuration key; the plan review did not ask for one.
- **What the redeem answers:** `mac`, `client_id` and
  `onboarding_path`, `no-store`, with `Referrer-Policy: no-referrer`
  and `nosniff` on either answer. `onboarding_path` is relative to the
  deployment's root (`x/<key>/`, or `x/` keyless), not to the server's,
  because `server.public_url` may carry a path prefix a proxy strips.
  The page resolves it against its own base minus `try/` (the base is
  two levels above its module, `new URL("../../", import.meta.url)`)
  and stores the path that results on its origin, prefix included,
  which is what M3's check-in and WebSocket use. Every other URL the
  page uses is relative to it the same way: the module (rendered
  `static/<version>/page.js` for `/try/` and `try/static/...` for
  `/try`, since a relative reference resolves against the directory)
  and the redemption (`redeem` against the base).
- **The default agent read for issuance** is the store's, in the
  request: the store is what a redemption's transaction reads, so the
  two cannot disagree about which default exists. The redemption reads
  no bindings at all, only the store inside its own write transaction,
  so the coordinator's rule from M1's review round (an unreadable
  bindings answer must never bind) holds by construction: a store that
  cannot be read refuses the write.
- **`link_origin` accepts a loopback IP literal** as well as
  `localhost` (`http://127.0.0.1`, `http://[::1]`), since browsers
  treat all three as secure contexts.

### Discoveries

- **A redundant expiry check hid behind the prune.** The first claim
  pruned expired records and then also compared the expiry; the
  mutation that removed the comparison survived, because the prune
  always ran first and the comparison could never be reached. The
  comparison is gone and expiry is the prune alone, which the
  mutations of the prune now kill (three tests each).
- **The network concurrency case reaches its condition about half the
  time.** Eight redemptions against a real uvicorn killed the
  check-await-mark mutation on 5 of 10 runs: whether the requests
  overlap within one loop iteration is up to the network. The
  deterministic case (`gather` over `redeem` itself, every claim made
  before any write returns) killed it on 10 of 10, so it is the one
  that pins D5d; the network case stays as the end-to-end shape and
  passed 25 of 25 unmutated.
- **`info`'s determinism test made a claim the link breaks.** Two runs
  against one state are no longer byte-identical, by design. The test
  now asserts exactly one line differs and that it is the link.
- **With no runtime, the try-link 503 is logged as "unreadable stored
  state".** The API's error event for a 5xx names `NoRuntimeError`
  that way; it is pre-existing behavior of every runtime route's 503
  and is only visible in the CLI suite's runner, which builds the API
  without a server. Not changed here; a follow-up candidate.
- **M1's review-round rebase:** both conflicts were additive (M1's
  `TRY_IDENTITY_UNAVAILABLE` beside M2's redeem names); the redeem
  routes go through `spellings()` and pass the inventory's new count
  and both-spellings checks.

### Tests first, and the mutations

Each test file was written before the code it pins and run to a
failure first (an `ImportError` or `AttributeError` on the missing
name, logs `m2-*-first-fail.log`), except `test_try_link_issue.py`,
which was written before the route but first run after it; its
falsification is the mutation set below, the first of which removes
the route (12 of its tests fail). One run each unless stated; every line is in the
worktree's `.logs/mutations-m2.log`.

| Guard | Mutation | Killed by |
| --- | --- | --- |
| Single use | `get` instead of `pop` | `test_an_issued_token_is_claimed_exactly_once`, `test_a_spent_token_is_gone_from_the_store`, `test_a_claim_frees_capacity` |
| Expiry | prune removed from the claim; `<` for `<=` | `test_a_token_expires_after_ten_minutes` and two more; five tests |
| Removal, not refusal (D6a) | prune removed from the issue | `test_expired_records_are_removed_by_the_next_issue`, `test_expiry_frees_capacity` |
| Capacity | the bound removed | `test_a_mint_past_the_capacity_is_refused_and_holds_nothing_more` |
| Honest seams | `os.urandom`, `time.time`, 16 bytes | the two default pins; three token-size tests |
| Not a string | the guard removed | the unhashable cases |
| D5b one transaction | bind then rename; merge an existing MAC; no default check; wrong refusal type | `test_a_name_that_cannot_be_given_leaves_no_device_behind` and three more; one each |
| D5a | the default-agent refusal removed; its reason token dropped | `test_with_no_default_agent_nothing_is_issued_and_the_state_is_named`, `test_the_default_agent_is_read_as_it_stands_now` |
| D6b, snapshot, no runtime, `no-store` | each removed | one test each |
| D5c server half | any scheme accepted; the listen address guessed | the secure-context cases; `test_a_link_is_issued_into_the_page_s_fragment` |
| D5d atomic claim | check, `await asyncio.sleep(0)`, then claim | `test_of_redemptions_started_together_exactly_one_binds` 10 of 10; `test_of_concurrent_redemptions_exactly_one_binds` 5 of 10 (see Discoveries) |
| Same origin | removed; checked after the claim; an absent `Sec-Fetch-Site` admitted; the `Origin` fallback restored | eight origin cases; four of them and both `test_an_origin_header_without_fetch_metadata_is_not_enough` cases; the latter two |
| Body | the 1 KiB bound removed; any object accepted | `test_a_long_body_is_not_read_to_its_end`; two body cases |
| Redemption | no claim; a collision gives up; draws unbounded; a non-collision redrawn; `no-store` dropped; wrong onboarding path | fifteen tests; `test_a_minted_mac_that_is_taken_is_drawn_again`; `test_the_draws_are_bounded`; `test_a_refusal_that_is_not_a_collision_is_not_drawn_again`; one each |
| D5c CLI half | no completion; any target local; CLI overrides the server; the address guessed; link on stderr | one to seven tests each |
| In place | refusal ends `info`; any failure declined | the three in-place cases and 23 existing `info` cases; `test_a_try_link_request_that_never_got_an_answer_still_ends_info` |
| D7a | a debug line; an echo in the refusal; the unparsed body logged; an echo on success | the no-leak cases, one to three each |

Survivors, both reported and resolved: the expiry comparison (unreachable,
removed; see Discoveries) and `except ConfigError: continue` in
`redeem`, which survived because a default agent cleared since issuance
refuses every draw alike, so redrawing three times ends in the same
`None` with nothing written. The driver did reach the condition; the
outcome only differed in work done, so
`test_a_refusal_that_is_not_a_collision_is_not_drawn_again` now counts
the draws, and it kills the mutation. Seven `cli-*` entries in the log
are marked void: zsh passed the two test paths as one argument and no
test ran; the `-2` reruns are the real ones.

### Verification

Run on agentpi (four cores), each line quoted from the log written in
the worktree's `.logs/`:

- `uv run ruff check .`: `All checks passed!`
- `uv run pytest tests/unit -q -n auto --dist loadfile`:
  `2 failed, 8328 passed, 19 skipped in 961.39s (0:16:01)`. The two
  are `test_logs.py`'s uvicorn cases, the interaction with
  `test_drain.py` M1's review round recorded: alone `27 passed`, after
  `test_drain.py` in one process `2 failed, 50 passed`
  (`m2-test-logs-alone.log`, `m2-test-logs-after-drain.log`). Not this
  milestone's; it also happens on `main`.
- `uv run pytest tests/integration -q -n auto --dist loadfile`:
  `354 passed in 217.50s (0:03:37)`
- The eight generated-document checks the server workflow runs, each
  regenerated to a scratch directory and compared: all current
  (`m2-drift.log`). `api-openapi.json` and `cli.md` were regenerated
  in their commits.
- The wheel built with `uv build --wheel` carries both new description
  files, `try_links.py`, `page.js` and `index.html`
  (`m2-wheel-contents.log`).
- `page.js` parses as an ES module under Node 22 (`m2-page-js-check.log`).
- **A real browser, once, by hand** (`m2-manual-browser-check.log`):
  a server booted from the checkout on a scratch store with a default
  agent, `vinga info` against it (exit 0, empty stderr, one link
  naming `http://localhost:18093`), and the link opened in Chromium
  from the cached `mcr.microsoft.com/playwright/python:v1.63.0-noble`
  image. After load the address was `http://localhost:18093/try/` with
  the token gone, the page said it was bound and stored `mac`,
  `client_id` and `onboarding_path`; going back in history reached
  `about:blank`, not the token; a second browser page opening the same
  link got the fixed refusal; the store held `Browser <mac>` bound to
  `assistant`; the server's log did not contain the token.
- `python3 scripts/check_doc_links.py .`: `checked 333 files, 0 failures`
- `uv run pytest tests/census -q`, last, after this section:
  `66 passed in 28.96s`.
  Both manifests were regenerated by their generators: the spellings
  gain `vinga default-agent set` (the remedy's spelling, quoted in the
  guides), and the reach-ins gain one `_call` site in
  `test_config_cli_try_link.py`, the transport-failure injection the
  `info` suite already makes the same way.

Not verified here: the image and the smoke lane (CI's), and the page
in any engine but Chromium. The lane that loads the page from the
installed wheel is M3's.
