# Decompose the CLI along its existing seams: implementation

Companion to [`2026-09-22-cli-decomposition.md`](2026-09-22-cli-decomposition.md),
one section per milestone, appended in the same change that ticks the
milestone checklist. It records deviations from the plan, resolutions
of the plan's open questions, and discoveries.

## M4: refusal reasons

**Attribution:** anthropic/claude-opus-5, thinking high; Claude Code 2.1.278; 2026-09-22.

The five refusals that named a command of the CLI's grammar now state
what they refused in and carry a closed token for it, and the CLI says
what to type. The server stops speaking a grammar it neither ships nor
versions, which is the coupling #386 measured: an image built before a
rename told an operator to type a command the client beside it no
longer had.

### What landed

| Piece | Where |
| --- | --- |
| The vocabulary | `config/responses.py`: `RefusalReason(StrEnum)`, six kebab-case members, with the comment above it saying why it is an extension member and not the RFC's `type` |
| The member | `config/responses.py`: `Problem.reason: RefusalReason \| None = None`, described as the state and not the remedy; `Problem`'s docstring gains the paragraph about the extension mechanism |
| The revised contract | `config/responses.py`: `Problem.detail`'s description stops claiming to be the sentence the CLI prints and says it is the state the server refused in, which a client holding the token may extend |
| The fact on the exception | `config/loader.py`: `ConfigError.__init__` gains keyword-only `reason`, stored as `self.reason`; the import edge is `responses.py`, which imports pydantic and nothing of this server |
| The token on the wire | `config/api.py`: `problem_response` takes `reason` and excludes the member from the dump when it is None; `_refusal`'s handler reads `exc.reason` |
| The three API sentences | `config/api.py`: `_UNKNOWN_CODE`, `_CLAIM_REFUSED` and `_UNLOADED_AGENT` lose their command halves; their raise sites (1774, 2554, 2595 before the change) pass `agent-not-serving`, `code-not-pending` and `agents-unknown` |
| The two store sentences | `config/store.py`: `ALREADY_BOUND` loses its command half and its raise site passes `device-already-bound`; `_write_secrets`'s refusal becomes `_missing(holder)` alone with `provider-missing` or `mcp-server-missing` from `_MISSING_HOLDER[location.kind]` |
| The constant's comment | `config/models.py`: `SERVER_PROGRAM` now names the one composer left, `loader.served`, instead of claiming three |
| The reading rule | `config/cli.py`: `_nameable` replaces a `reason` that is a string this build cannot name with None before `Problem.model_validate`; everything else stays as strict as it was |
| The remedies | `config/cli.py`: `REMEDIES: dict[RefusalReason, str]` beside `_refusal`, its one consumer, spelled with `PROGRAM` the way `SPOKEN` is; `_refusal` returns `detail`, a space and the remedy where the token is known, `detail` alone where it is not |
| The published document | `docs/reference/api-openapi.json`, through `uv run vinga-server config openapi`: the `RefusalReason` component, `Problem.reason` as `anyOf[$ref, null]`, and the revised `detail` description |
| The changelog fragment | `changelog.d/488-refusal-reasons.md`, `### Changed`, two entries: the five refusals, and the upgrade order |

`docs/reference/cli.md` did not move. Verified with the workflow's own
drift check over the generated region rather than assumed, and it
reports no difference: no help page changed.

The six remedy sentences are the plan's, verbatim, with `PROGRAM`
standing for `vinga`, checked against the plan's text by comparing the
rendered table string by string.

### The tests, by path

One named home per raise path, each asserting the sentence, the exact
token the site attaches, that neither spelling of this grammar's
program word is in `detail`, and keeping the no-secret and no-address
checks already beside it.

| Path | Where |
| --- | --- |
| `code-not-pending`, unknown and expired and already-claimed | `tests/unit/test_config_api_pending.py`: `test_an_unknown_code_points_at_the_screen`, `test_an_expired_code_is_answered_the_same_way`, `test_a_claim_retires_the_code` |
| `agents-unknown` | `tests/unit/test_config_api_pending.py`: `test_a_refused_claim_does_not_quote_the_names_it_refused`, and end to end in `tests/integration/test_cli_live.py` |
| `agent-not-serving` | `tests/unit/test_config_api_runtime.py`: `test_an_agent_this_server_is_not_serving_is_a_404_carrying_the_state` |
| `device-already-bound` | `tests/unit/test_config_api_pending.py`: `test_a_claim_will_not_replace_a_binding_made_underneath_it`, and through the client in `tests/unit/test_simulator_board.py` |
| `provider-missing`, `mcp-server-missing` | `tests/unit/test_config_store.py`: `test_a_holder_that_is_not_there_at_the_write_says_which_kind_it_was`; over HTTP in `tests/unit/test_config_api_writes.py`: `test_a_secret_for_a_holder_that_is_not_there_says_which_kind_it_was` |

| Claim | Where |
| --- | --- |
| A refusal with no token carries exactly `title`, `status`, `detail`, `errors` | `tests/unit/test_config_api_problems.py`: `test_a_refusal_with_no_token_carries_exactly_the_four_members` |
| And a sibling of one of the five, `ALREADY_COVERED`, carries the same four | `tests/unit/test_config_api_pending.py`: `test_a_claim_will_not_bind_a_device_a_default_agent_now_covers` |
| A known token prints `detail` plus the remedy, the whole of stderr, once per member | `tests/unit/test_config_cli_rendering.py`: `test_a_state_this_client_knows_is_answered_with_its_own_remedy` |
| A token this build cannot name prints `detail` alone and is never echoed | `test_a_state_this_client_cannot_name_is_quoted_and_not_guessed_at` |
| No member at all prints `detail` alone | `test_a_refusal_from_a_server_older_than_the_vocabulary_is_unchanged` |
| A `reason` that is not a string is unrecognized, and nothing of it reaches a stream | `test_a_body_whose_state_is_not_a_token_is_not_this_apis_refusal`, three shapes |
| `set(REMEDIES) == set(RefusalReason)` | `test_the_remedies_cover_the_whole_vocabulary` |
| Every command quoted in a remedy names a row of `COMMANDS`, in the short spelling | `test_every_remedy_names_a_command_this_grammar_has` |
| Every secret holder has a token of its own | `tests/unit/test_config_api_writes.py`: `test_every_secret_holder_answers_in_a_token_of_its_own` |
| The whole client path against a real application: the server's sentence and this client's remedy | `tests/unit/test_config_cli_rendering.py`: `test_prompt_says_what_the_server_answered_for_an_unserved_agent` |
| Over a real connection: the pending row reads the table, and a claim naming an agent that is not there is refused whole | `tests/integration/test_cli_live.py`: the `("device", "pending")` row of `REFUSALS`, and `test_a_claim_naming_an_agent_that_is_not_there_is_refused_over_the_wire` |

`tests/support/problems.py` gained a keyword-only `reason=` mode on
`refused()`, which requires exactly the four members plus `reason`
holding that value. `PROBLEM_KEYS` was not broadened: the four-member
default is what pins every other refusal's body, and it is what the
old-client compatibility claim rests on.

### The falsification runs

Each was performed, watched and reverted.

| Mutation | What caught it |
| --- | --- |
| `problem_response` dumping the model plainly, so `reason` goes out as null | `test_a_refusal_with_no_token_carries_exactly_the_four_members`, on a malformed-request 422: `AssertionError ... Extra items in the left set: 'reason'` |
| `_write_secrets` raising without `reason=` | Both store-level holder cases: `assert None is <RefusalReason.PROVIDER_MISSING: 'provider-missing'>`, and both HTTP cases on the four-member body |
| The remedy lookup removed from `_refusal`, returning `problem.detail` | The six known-token cases, each on the whole of stderr being `detail` with nothing after it; the other six client cases stayed green, which is what says the mutation was local |
| The reading rule removed, validating the payload as it arrived | `test_a_state_this_client_cannot_name_is_quoted_and_not_guessed_at` alone: the unknown token turned a readable refusal into "a body this client does not recognize" |
| `provider set` spelled `provider add` in `REMEDIES` | `test_every_remedy_names_a_command_this_grammar_has`: `assert [('vinga', 'provider', 'add')] == []` |

No mutation survived a test.

The `PROGRAM`-absent and `SERVER_PROGRAM`-absent assertions need no
mutation: every one of the five sentences held one of those spellings
before this change, so each assertion is red against the pre-change
tree by construction. `PROGRAM` is `vinga`, which is a substring of
`vinga-server config`, so the first of the two would catch either
spelling on its own; both are asserted because the two constants are
two decisions and a sentence may come to hold either.

### Deviations from the plan

Five, all additive, none changing what the plan specifies.

- **A registry guard over `REMEDIES`, which the plan does not ask for.**
  The plan says the spelling is inside the command-spellings census's
  reach, quoting `SPOKEN`'s comment. It is not: that census reads the
  tree as text and these sentences are composed from `PROGRAM`, so a
  rename would leave a line naming a command nothing answers to with no
  text match to catch it. Measured rather than argued: both manifests
  were regenerated after the table landed and neither moved.
  `test_every_remedy_names_a_command_this_grammar_has` is the same
  guard over the composed table, holding every quoted invocation to a
  row of `COMMANDS` and to the short spelling, and the comment beside
  `REMEDIES` points at it rather than at the census.
- **The two holder cases pin the whole sentence**, against
  `entities.SECRET_HOLDERS[kind].missing`, rather than its `section:`
  prefix. What changed at that site is that the sentence is the kind's
  own ALONE, and the command that used to follow it would have passed a
  prefix check.
- **The `ALREADY_COVERED` sibling asserts the strict four members.** It
  is the refusal next door to `device-already-bound` and is not one of
  the five, so it is where "the skew is five bodies and not all of
  them" is cheapest to state twice.
- **The client cases are driven through `main`** with a mock transport
  of their own rather than through `_refusal`, so they assert the whole
  of what reaches an operator and add no reach-in. The one
  problem-document case that already existed in that file,
  `test_prompt_says_what_the_server_answered_for_an_unserved_agent`,
  was updated in place: it pinned `"config apply"`, which is exactly
  the coupling this milestone removes.
- **The reading rule's function is `_nameable`, not `_reported`.**
  `cli.py` already has a `_reported`, the simulator's check-in
  rendering, and the first draft shadowed it, which the suite caught as
  a `TypeError` out of the refusal reader rather than as a name clash.

### Discoveries

- **The refusal M4 changes in `store.py` had nothing driving it.** The
  sentence that composed with `SERVER_PROGRAM` is `_write_secrets`'s,
  raised when its update affects no row, and every ordinary way of
  addressing a secret at a holder that is not there is answered by
  `_check_slot` before the write. The existing secret-write case near
  line 861 of `test_config_api_writes.py` meets the slot check, not
  this. So the sentence was being changed with no test on it, which is
  why the plan's Tests section now names a fixture for it.
- **No schedule can be raced into that window.** `set_secret` runs the
  check and the write in one transaction, and every transaction on this
  engine takes the chain's advisory lock in its begin listener
  (`db/__init__.py`), so a second connection deleting the holder waits
  on the one in flight and times out: what comes back is
  `DatabaseBusyError`, measured, not the state under test. The fixture
  is therefore a seam on the check, which answers as if the holder were
  present while the holder is never written.
- **An earlier draft widened the token to all three holder-missing
  sites**, `_check_slot`'s two included, on the reasoning that one state
  should have one home. It was narrowed back: the plan scopes the skew
  to five bodies, and tokenizing the slot check would have put the
  member on a refusal an ordinary request reaches. What is left is a
  real design question, recorded rather than resolved: after this
  change the two paths compose the same sentence and only one carries a
  token, so the reachable one gives a client nothing to phrase a remedy
  from. Extending the vocabulary to the slot check is a change to the
  published contract and belongs in its own issue.
- **The live lane's deployment is shared, and a case that mints a code
  needs a board of its own.** The end-to-end claim refusal first used
  the board the onboarding case is about, which that case binds, so by
  the time this one checked in it was answered as a configured device
  and no code was minted: `Unwelcome(...)` where `Activating` was
  expected, caught by the integration lane and not by anything
  smaller. Two of the lane's addresses already carried that reasoning
  in a comment; this is a third, and the reason it needs one is
  different enough to be written out, since what it needs is a board
  that stays unbound rather than one nothing else reads.
- **The published API document carries issue references already**
  (`#19`, `#88`, `#384`), so the reasoning that names `#386` was kept in
  comments above the declarations rather than in the docstrings the
  document renders, which is where this repository puts reasoning
  anyway.

### The reach-in, named

`vinga_server.config.store._check_slot` is replaced in two test files,
`tests/unit/test_config_store.py` and
`tests/unit/test_config_api_writes.py`. It is an underscore name and
therefore a review flag, answered explicitly: the refusal under test is
raised only when the holder's row is gone between two statements of one
transaction, and a race has no caller-facing seam to reach it by. The
design guide's two answers are "the module lacks an interface callers
need" and "the test pins a detail"; neither applies, because no caller
can ever ask for this state and nothing here pins how the check works,
only that it passed. That the slot-check refusal was not what answered
is proven by the body's `reason`, which only the write path attaches.

It arrives as no line in `tests/census/reach-ins.txt`, and that is a
fact about the census rather than about the reach: a site is a `.`
followed by an underscore name, and `monkeypatch.setattr(store,
"_check_slot", ...)` names it as a string. Recorded here so the flag is
raised where the manifest would have raised it.

### The upgrade order

An older CLI against a newer server refuses these five bodies, because
its `Problem` forbids the member it does not know, and the `vinga`
client installs separately from the image it administers. So the order
is stated where an operator meets upgrades: **upgrade every
administering CLI before the server.** Until that is done the five
refusals print the unreadable-body sentence instead of what was
refused, and every other refusal reads exactly as before, because none
of them carries the member. Nothing negotiates a version: the two
halves ship from one tree, the failure mode is a degraded sentence and
never a command that misbehaves, and the project is pre-release with no
third-party install to carry. The changelog fragment says the same
thing under `### Changed`, which is what the fold carries into
`CHANGELOG.md`.

### Verification

From `vinga-server/`: `uv run ruff check .` (clean),
`uv run pytest tests/unit -q` (7418 passed, 19 skipped, 28m37s),
`uv run pytest tests/integration -q` (347 passed, 9m01s) and
`uv run pytest tests/census -q` (66 passed), plus the two
generated-document drift checks run the way the workflow runs them:
the OpenAPI document matches the committed copy and the CLI
reference's generated region has no difference. The wheel-grade lane
is inside the integration lane and ran, since `uv` is on PATH and
nothing skipped. The image build and the smoke conversation were not
run here and are unverified in this section; the pull request records
what CI says about them.
