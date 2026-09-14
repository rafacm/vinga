# Two configuration refusals that mislead the operator: implementation

Companion to [`2026-09-14-two-misleading-refusals.md`](2026-09-14-two-misleading-refusals.md),
one section per milestone, appended in the same change that ticks the
milestone checklist. It records deviations from the plan, resolutions
of the plan's open questions, and discoveries.

## M1: a header may compose a reference

`$NAME` now resolves wherever it stands inside an MCP server's `env` or
`headers` value, so `Authorization: Bearer $WEATHER_TOKEN` is one value
with a credential in it and the word `Bearer` lives in the
configuration rather than inside the secret.

### What landed

| Piece | Where |
| --- | --- |
| The scanner | `config/models.py`: `_ENV_REFERENCE_RE` loses its anchors, and the whole-value question is the same pattern asked with `fullmatch` in `_env_reference`, which keeps its `value.strip()` and therefore its behavior |
| The one rule both paths read | `config/models.py`: `references_environment(value)`, asked by the secret-bearing check and by the display path, so the mirror that used to sit in `secrets.py` cannot drift |
| The substitution, and the atoms | `config/models.py`: `resolve_env_values` answers with `ResolvedValues(values, secrets, substituted)`, the last two split by whether the key that referenced them is secret-bearing; a value that is nothing but a reference resolves as it always did, any other value is scanned and every reference in it is substituted where it stands |
| The widened write rule | `config/models.py`: `_secret_problems` asks whether a value contains a reference, and the refusal names what is now allowed with the composed form as its example, quoting neither the key nor the value |
| The field descriptions | `config/models.py`: `env` and `headers` say a reference may be the whole value or sit inside a larger one, and that there is no escape for a literal `$` |
| The display rule | `config/secrets.py`: `_DOLLAR_REFERENCE_RE` is gone and `mask` reads `references_environment`, so a composed value displays, exports and imports and a paste with no reference in it still masks |
| The atoms crossing the seam | `config/secrets.py`: `resolve_mcp_values` answers with `ResolvedValues`, a stored secret joining the set as its own atom; `tools/mcp/transport.py`'s `_resolve` passes both halves on and `_connect` answers with the pair it actually sent |
| The redactor | `tools/mcp/manager.py`'s `_capture` is handed what the connect sent and gives `tools/mcp/prompts.py`'s `_redactor` two buckets: the materialized values and the substitutions nothing has classified, where the length floor applies, and the substitutions a secret-bearing key made, where it never does; the longest-first rule is unchanged |
| The example | `examples/mcp-server-streamable-http.yaml`: the composed header, the doubled-prefix 401 named, and the encrypted slot stated as holding the FINISHED header value with the precedence pinned at the wire |
| The other three documents that stated the old rule | `examples/mcp-server-stdio.yaml`, `examples/README.md`, `vinga-server/README.md` |
| The regenerated references | `docs/reference/domain-config.md` and `docs/reference/api-openapi.json`, through their generators; the other five committed references and the CLI page did not move |
| The changelog fragment | `changelog.d/504-compose-an-env-reference.md`, `### Changed`, with the upgrade note |

Tests, by claim:

| Claim | Where |
| --- | --- |
| A composed value resolves where the reference stands, and the atoms come with it | `tests/unit/test_config_tools.py` |
| Several references in one value each resolve; a value with none passes through byte for byte | `tests/unit/test_config_tools.py` |
| A whole reference keeps its trimming, padding and terminal newline included | `tests/unit/test_config_tools.py` |
| A secret-bearing key may compose, in both groups; one that references nothing is refused and the sentence says what is allowed | `tests/unit/test_config_tools.py` |
| The resolution's two halves, for a substituted secret and for a stored one | `tests/unit/test_config_secrets.py` |
| A padded and a composed reference display and resubmit as themselves; a paste still masks | `tests/unit/test_config_round_trip.py` |
| The composed header reaches the far side with the secret in it, read off a real HTTP server | `tests/unit/test_mcp_composed_reference.py` |
| An unset variable inside a composed value refuses, naming the location and the variable and quoting neither the value, the partially substituted string, nor the credential, on any surface a boot reaches | `tests/unit/test_mcp_composed_reference.py` |
| A pasted credential under a secret-bearing key is still refused, and the refusal quotes nothing, at the CLI | `tests/unit/test_mcp_composed_reference.py` |
| A composed value carrying a newline never reaches the wire, and reaches no surface either | `tests/unit/test_mcp_composed_reference.py` |
| The acceptance case: written, exported, imported into an empty database, and the second deployment sends the byte-identical header | `tests/unit/test_mcp_composed_reference.py` |
| A server reflecting the BARE token out of a composed value reaches no operator surface | `tests/unit/test_mcp_status_reflection.py`, with `tests/support/mcp_reflecting_server.py` stripping the composed prefix before it reflects |
| A reflected token shorter than the redaction floor is taken out all the same | `tests/unit/test_mcp_composed_reference.py` |
| A short reference under a key that is not secret-bearing keeps the floor and is left where it is | `tests/unit/test_mcp_composed_reference.py` |
| What was substituted is split by what its key says | `tests/unit/test_config_tools.py` |
| The capture redacts what the connection sent, not what the environment says by the time it runs | `tests/unit/test_mcp_composed_reference.py` |

### Deviations from the plan

Five, four of them small and one of them a contradiction inside the
plan that the review round had already settled.

- **`resolve_env_references` was deleted rather than kept.** The plan
  says it "keeps its signature for every caller that wants only the
  mapping". After this milestone there is no such caller: its only
  production caller was `resolve_mcp_values`, which now needs the
  atoms, and the manager's `_resolve` serves both the connection and
  the capture. A public function whose only callers are its own tests
  is what the plan's own rule for `_env_reference` says to delete
  rather than keep and test privately, so the same rule was applied
  one name over. `ResolvedValues` and `resolve_env_values` take its
  place in `config/__init__`'s exports. `_env_reference` itself was
  kept, because it does have a production caller: it is the
  whole-value question `resolve_env_values` asks first.
- **The plan's Tests list still asks for `mask` to return the mask for
  a composed value.** That bullet is the decision the review round's
  finding 1 reversed, and the resolutions are binding, so what is
  pinned is the reversal: `mask` returns a composed value as written,
  and a paste with no reference in it still masks. Both are in
  `test_config_round_trip.py`, beside the padded reference that
  changes with them.
- **`secrets.py` lost its pattern instead of widening it.** The plan
  says `_DOLLAR_REFERENCE_RE` "widens with the model's pattern, so the
  mirror its comment claims stays true". A mirror that has to be kept
  true is two structures that must agree, so the constant is gone and
  both paths call `references_environment`. This is the plan's intent
  with one fewer thing to keep in step; the bare uppercase spelling
  stays a pattern of its own, because it is a different question.
- **Three documents beyond the plan's footprint were corrected.** The
  plan names the streamable_http example and the README's MCP section
  "if it states the old rule; checked, not assumed". It did, and so did
  `examples/mcp-server-stdio.yaml` and `examples/README.md`, each in one
  sentence. A document that states the whole-value rule as the rule is
  wrong after this change, so all four moved. The full treatment (the
  composed header, the doubled-prefix 401, the encrypted slot's
  finished-value rule) is only in the streamable_http example, as the
  plan says.
- **The "still refused" case is asserted at the CLI rather than at the
  model.** pydantic's `ValidationError` string echoes the input it was
  handed whatever the message says, so a model-level assertion that the
  value is absent from `str(exc)` cannot hold. This is not something
  this milestone introduced and it is not a leak: `config/loader.py`
  renders a refusal from the error locations and messages only, never
  from `str(exc)`, with a comment saying why. The operator surfaces are
  therefore where the claim belongs, and the CLI case asserts it over
  both streams, both log formats and every emission.

### Resolutions the plan left to this milestone

- **What a newline inside a composed value does.** Measured, below. The
  answer is that the transport refuses it, so no refusal of our own was
  added.
- **Which of the two resolution functions is the primitive.** The one
  that answers with both halves, for the reason the deletion test gives:
  the other had nothing left to serve.

### The newline measurement

The plan asked for this to be observed rather than asserted, and it was
observed twice: first directly against httpx, then through the server
as a test case.

Measured 2026-09-14 against httpx 0.28.1 and the h11 engine under it,
on `Authorization` values `Bearer sk-1\n`, `Bearer sk-1\r\nX-Evil: yes`
and `Bearer sk-1\nX-Evil: yes`:

- The client accepts all three. `httpx.Client(headers=...)` builds and
  the header is on the client's own header set, so nothing refuses at
  construction time.
- The request is refused at send time, before any byte leaves:
  `h11._util.LocalProtocolError: Illegal header value b'Bearer sk-1\n'`.
  A listening socket recorded on the other end received nothing at all
  in every case.

So header injection is not reachable through this transport, and the
milestone adds no refusal, which is the branch the plan named for that
outcome. What the case in `test_mcp_composed_reference.py` pins is the
consequence rather than the message: the connection does not come up,
the far side is never asked, and the credential reaches no surface.
That last part is worth the case on its own, because this is the one
path where a credential is closest to a log: h11's exception message
quotes the whole header value, and `transport._reason` renders a
failure by type name only, so the sentinel is absent from the status,
from every record in both formats, and from every emission.

One consequence is worth stating plainly for an operator: a composed
value with a newline in it is a connection that never comes up, logged
as a transport failure. It is not refused at write time and not at
boot.

### What the verification proved, and how each claim was falsified

Every new claim was watched failing before it was believed, by mutation
rather than by a full revert, so that each group of cases fails against
the one thing it is about.

**Mutation 1, the pattern re-anchored** (`_ENV_REFERENCE_RE` back to
`^\$([A-Za-z_][A-Za-z0-9_]*)$`, everything else untouched). Eleven
cases failed and 86 passed:

- the four composed cases in `test_mcp_composed_reference.py` (the
  header reaching the far side, the partial refusal, the newline, and
  the export into an empty database), each because the write rule
  refuses a composed value again or the resolver hands back the
  literal;
- the two composed parameters of
  `test_a_secret_bearing_value_may_compose_a_reference`, and both
  substitution cases in `test_config_tools.py`;
- all three display cases in `test_config_round_trip.py`, including
  `mask('Bearer $HOME_ASSISTANT_TOKEN') == '********'`, which is the
  reversal the review round asked for failing as it should.

The two cases in the new suite that survived are the two that are not
about composition: a value with no reference passing through byte for
byte, and a pasted credential still being refused. That they survived
is the evidence that the suite is not one claim written six times.

**Mutation 2, the atoms withheld** (`_capture` passing only the
materialized values to `_redactor`, with the composition left in
place). The new reflection case failed with the bare token in the
assembled prompt:

```
assert 'Call the forecast tool with [redacted].' in
  '...Call the forecast tool with sk-test-6e3a91d4-never-a-real-credential.'
```

and the five existing reflection cases stayed green, which is exactly
the plan's claim about why the defect needed a case of its own: the
existing coverage uses a whole-value reference, where the materialized
value IS the credential.

The display rule needed no mutation of its own: it reads the same
predicate as the write rule, so mutation 1 took it with it, which is
the "one rule read by both paths" property demonstrated rather than
asserted.

### Discoveries

- **The acceptance case needed a second database to be a second
  deployment.** The first draft read the rebuilt configuration through
  `load_boot_config()` after pointing `VINGA_DB_NAME` at the spare
  database, which would have been indistinguishable from the first
  deployment answering twice if the pointer had not moved. The case now
  asserts the spare database is empty before the import, so the
  byte-identical header is a claim about two stores.
- **A composed value is the first thing that makes the redactor's
  longest-first rule load-bearing.** It was written for one value
  containing another, and a token inside its own header is exactly that
  shape, so the ordering needed no change: the header is replaced whole
  and the bare token catches whatever the header did not.
- **The reflecting test server can carry the hostile case without a
  second server.** It strips the composed prefix before it reflects, so
  an entry written with the whole value as the reference is unaffected
  (a value with no prefix comes out unchanged) and an entry that
  composes one is answered with the bare token.

### PR review round, PR #519

External review: codex CLI 0.154.0, model gpt-5.6-sol, read-only
sandbox, 2026-09-14, runtime 8m43s, reviewing main...b232cdc0. Verdict
as received: **mergeable after the listed fixes**. Five findings, four
adopted and one rejected; each adopted one is fixed in a commit of its
own.

Both P1s are about the same half of the change, and neither is about
the composition itself: they are about what the redactor is given. The
milestone made the atoms cross the seam and then let two things undo
it, a floor that swallowed the short ones and a capture that went back
to the environment for them anyway.

1. **P1: short substituted secrets bypass redaction.**
   `resolve_env_values` classifies every substituted value as a secret,
   but `_redactor` discards every string shorter than eight characters,
   so `TOKEN=abc123` with `Authorization: Bearer $TOKEN` redacts
   `Bearer abc123` and lets a hostile server's bare `abc123` reach
   stored guidance, the prompt preview, the API and the CLI. Fix:
   distinguish generic materialized values from known substituted
   atoms, keep the floor only for the generic ones, redact every
   non-empty atom whatever its length, and add an end-to-end case below
   the floor.

   *Resolution.* Adopted, with one correction the integration lane
   forced. `_redactor` now takes the two separately rather than as
   varargs over one set, and the docstring says why they differ: the
   floor is about not knowing, and a credential is not a guess.

   The correction is which substitutions count as credentials. Taken
   literally, "every substituted atom" was too wide, because
   `resolve_env_values` called every substituted value a secret,
   secret-bearing key or not. Exempting them all redacted a
   three-character marker a test server ships back, which
   `tests/integration/test_agent_guidance.py` pins by name and whose
   comment states the floor's contract in so many words. The classifier
   this configuration already has is the key: a secret-bearing key's
   reference is a credential whatever it looks like, and every other
   key's is a value out of the environment nothing has classified, so
   it keeps the floor. `ResolvedValues` carries the two apart as
   `secrets` and `substituted`, the manager hands the second to the
   redactor beside the materialized values, and stored credentials join
   the first because a slot written with `secret set` is a credential
   by the same declaration. That also makes the finding's own
   justification true, which it was not while every substitution was
   called a secret.

   `test_a_reflected_token_below_the_redaction_floor_is_taken_out`
   drives a six-character credential through a composed header under
   `Authorization` and a server that hands the bare token back, and was
   watched failing with the floor left on the atoms: `'Call the
   forecast tool with [redacted].' in 'Call the forecast tool with
   q7v3zx.'` Its opposite,
   `test_a_short_value_under_an_ordinary_key_is_left_where_it_is`,
   fails the other way when every substitution is called a credential
   (`'Deployed in q7v3zx.' in 'Deployed in [redacted].'`), and the
   hostile reflection case fails when `substituted` is withheld from
   the redactor, its entry key not being secret-bearing and its bare
   token reachable no other way. Both halves of the split are
   load-bearing and each is pinned by a case that dies without it.

2. **P1: the capture re-resolves instead of redacting with what was
   sent.** `_connect` resolves, sends, and discards its
   `ResolvedValues`, and `_capture` reads the environment again on the
   far side of a handshake and a tool listing. A variable that moves in
   that window leaves the server holding secret A while the redactor
   knows only B, so a reflected A leaks; it also contradicts the plan's
   own requirement that the atoms cross the seam rather than be
   reconstructed. Fix: return the active `ResolvedValues` from
   `_connect`, pass them into `_capture`, release them afterwards, and
   test with a variable that changes while discovery is blocked.

   *Resolution.* Adopted whole, and the finding is right that this was
   the rule half-followed. `_connect` answers with the values it used,
   one group rather than both because one is all a connection uses (a
   transport is given its own group and the model refuses an entry that
   names the other's), `_capture` takes them as an argument, and `_run`
   drops its reference in a `finally` before the wait that holds a
   connection open, so the "never held on the manager" promise now
   states its scope accurately. The fail-closed branch around the old
   resolution went with it: nothing in `_capture` can raise where it
   used to, because the values arrive already resolved by a connect
   that could not otherwise have succeeded.
   `test_the_capture_redacts_what_was_sent_and_not_what_is_set_now`
   holds the window open from the far side, an ASGI wrapper on the test
   server changing the variable when the handshake arrives, which is
   deterministic rather than a sleep: the change lands strictly after
   the values were resolved and sent and strictly before the listing
   and the capture. Watched failing with the capture resolving again:
   the credential that was actually sent stands unredacted in the
   guidance while the variable holds the other one.

3. **P2: the established resolver API was removed contrary to the
   plan.** The plan requires `resolve_env_references` to keep its
   mapping-returning signature; the PR removes the publicly exported
   name and replaces it with `resolve_env_values`, and the absence of
   an in-tree caller does not protect external importers of an
   `__all__` export.

   *Resolution.* **Rejected**, by the maintainer, who is answering it
   on the pull request; the name stays deleted. The project has a
   recorded pre-release compatibility stance: there are no third-party
   installs to support. So the importer the finding protects is
   hypothetical, and keeping a public name alive for a hypothetical
   reader is exactly what the deletion test refuses. The deviation note
   above stands as the record of the judgement.

4. **P2: the hostile redaction test omits required no-leak surfaces.**
   The composed-reflection case checks the response renderings and that
   suite's own `rendered`, which does not inspect typed `record.args`;
   it attaches no server tap and, unlike the whole-value case beside
   it, makes no exception-chain assertion, while the governing plan
   requires all-record rendering, event payloads and every exception
   chain.

   *Resolution.* Adopted. The case now reads every record through
   `every_format`, asserts the sentinel absent from every emission an
   attached tap was handed, and asserts no record carries an exception
   to render. The tap is checked non-empty first, so the absence is an
   absence from a transport that ran rather than from one nothing
   reached, which is the guard that makes an absence assertion worth
   reading at all.

5. **P2: the governing plan still states the pre-review masking
   behavior.** Its test section says a composed value remains masked
   and that the whole-value question rejects a terminal newline, and
   its risk section promises that a pasted credential beside a
   reference never renders. All three contradict the round's own
   resolution 1 and the implemented behavior.

   *Resolution.* Adopted. The two test bullets now say that composed
   and padded references display while a value with no reference still
   masks, and that the whole-value question keeps the strip it has, a
   terminal newline included, with `fullmatch` as the spelling that
   makes that true of the pattern as well. The risk bullet now names
   the display consequence as part of what was weighed rather than
   promising the opposite of it. The recorded plan-review findings and
   their resolutions were not touched: they are a record of what was
   said, and the contradiction was in the body that had not been
   carried forward with them.
