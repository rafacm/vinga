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
| The substitution, and the atoms | `config/models.py`: `resolve_env_values` answers with `ResolvedValues(values, secrets)`; a value that is nothing but a reference resolves as it always did, any other value is scanned and every reference in it is substituted where it stands |
| The widened write rule | `config/models.py`: `_secret_problems` asks whether a value contains a reference, and the refusal names what is now allowed with the composed form as its example, quoting neither the key nor the value |
| The field descriptions | `config/models.py`: `env` and `headers` say a reference may be the whole value or sit inside a larger one, and that there is no escape for a literal `$` |
| The display rule | `config/secrets.py`: `_DOLLAR_REFERENCE_RE` is gone and `mask` reads `references_environment`, so a composed value displays, exports and imports and a paste with no reference in it still masks |
| The atoms crossing the seam | `config/secrets.py`: `resolve_mcp_values` answers with `ResolvedValues`, a stored secret joining the set as its own atom; `tools/mcp/transport.py`'s `_resolve` passes both halves on |
| The redactor | `tools/mcp/manager.py`'s `_capture` gives `_redactor` the substituted secrets beside the materialized values, and `tools/mcp/prompts.py`'s `_redactor` takes iterables of values, its longest-first rule unchanged |
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
