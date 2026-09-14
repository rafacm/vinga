# Two configuration refusals that mislead the operator

Plan for [#504](https://github.com/rafacm/vinga/issues/504) and
[#507](https://github.com/rafacm/vinga/issues/507). Its companion is
`docs/plans/2026-09-14-two-misleading-refusals-implementation.md`, one
section per milestone, appended in the same change that ticks the
milestone.

One plan for two issues, which the pipeline allows when the second's
plan would restate the first's reasoning rather than add to it. These
two are the same defect twice: a refusal in `vinga-server/src/vinga_server/config/`
that is correct about its rule and wrong about the operator's
situation, so the sentence sends them somewhere that does not help.
One is a write-time refusal that reads as though a secret was pasted
when a variable was referenced; the other is a boot-time refusal whose
obvious next step is a command that cannot run until the boot it is
blocking succeeds. They share a module, a vocabulary (a refusal names
the location, quotes no value, and says what to do) and a test lane,
and each gets its own milestone and its own pull request.

**Local baseline:** not applicable. Neither changes a conversational
capability. #504 widens what an MCP entry may hold, #507 changes what a
refused boot prints; a fully local deployment reaches neither.

## What is settled and not re-litigated

- **#504 takes the issue's option 2 with option 1 in the same change.**
  `$NAME` interpolates inside a larger value, the secret-bearing check
  asks whether a value CONTAINS a reference, and the example that an
  operator copies says so.
- **#507 takes option 2, reduced** (decided 2026-09-13): the boot keeps
  refusing, and the refusal says what to do about it. NOT quarantine,
  which cannot work as the issue imagined it (an agent referencing a
  dropped MCP entry is itself refused, so dropping the entry moves the
  refusal rather than scoping it), and NOT an offline repair verb,
  which would reopen the decision that the CLI is an API client and
  `--local` was a SQLite-era artifact to shrink rather than invest in.

## Open questions, resolved

### #504: one rule for `env` and for `headers`, not a rule per group

`resolve_env_references` serves both groups and `_secret_problems`
walks both. Widening one and not the other would be two rules on one
function, which is the "two structures that must agree" trap with the
bug already pending. So a `$NAME` anywhere inside a value is a
reference in both groups.

That is also the honest reading of what the reference is FOR. An `env`
value has the same problem the issue reports for a header the moment a
server wants `--token=$TOKEN`, and the rule that made `headers` the
reported case is the secret-bearing check, not the resolution.

### #504: one pattern, asked two ways, and the trimming stays

`_ENV_REFERENCE_RE` stops being anchored and becomes the scanner. "Is
this value exactly a reference" is then the same pattern asked with
`fullmatch`, so the two questions cannot drift apart.

**The trimming stays exactly where it is, and that is the whole of the
compatibility story here.** `_env_reference` matches against
`value.strip()` today, so `"$TOKEN "` and `"$TOKEN\n"` are accepted and
resolve to the secret with no padding, which a round-trip case already
pins. The resolver therefore keeps asking the whole-value question
first, against the stripped value, and answers it exactly as it does
now; only a value that is NOT a whole reference is scanned and
substituted as written. A padded reference keeps resolving to the bare
secret rather than quietly becoming a composed value with whitespace in
it, which is what dropping the strip would have done.

So `_env_reference` keeps a production caller and is not deleted. If
the implementation finds it has none, it is deleted rather than kept
and tested privately: a private helper with a test and no caller is a
test of nothing.

`fullmatch` deliberately, never `match` with a `$` appended:
`re.match(p + "$")` accepts a terminal newline where `fullmatch` does
not. Here the strip makes that moot for the whole-value question, which
is precisely why it is worth writing down rather than relying on: the
next reader of this pattern will not have the strip in view.

**What a newline inside a COMPOSED value does is a question this
milestone answers by measurement, not by assertion.** `Bearer $TOKEN\n`
is not a whole reference, so it is substituted as written and a value
with a newline in it reaches the HTTP client. The milestone writes the
case, observes what the client does with it, and records the answer: if
the client refuses it, that is the behavior and the case pins it; if it
passes it through, the milestone adds the refusal, because a header
value carrying CR or LF is header injection and not a configuration
style. Either way the plan does not claim an answer it has not seen.

### #504: what may be stored is what may be displayed

The plan said the display path would stay anchored and a composed
header would read back as the mask. The review showed what that costs
and it is not a display detail: `views._masked` masks every string
under a secret-shaped name and `store._keep` refuses a mask where
nothing is stored yet, which is every entry of an import into an empty
database. So a masked composed header exports as eight asterisks and
cannot be imported back, and the export-and-reapply promise is exactly
the recovery the other milestone tells an operator to perform. Worse,
the operator's way out would be the encrypted slot, which replaces the
whole value and therefore has to hold `Bearer <token>`: the workaround
this issue exists to remove.

So the display rule follows the write rule, and there is one rule
rather than two: **a value that references an environment variable
somewhere in it is a reference and displays; a value that references
none is a paste or a ciphertext and masks.** `config/secrets.py`'s
`_DOLLAR_REFERENCE_RE` widens with the model's pattern, and its comment
saying the two mirror each other becomes true again rather than
becoming a lie this plan has to explain.

What the mask still catches is what it was written for: ciphertext, a
malformed envelope, and a bare paste with no reference in it. Every
other stored secret slot holds a bare uppercase name or ciphertext, and
ciphertext contains no `$NAME`, so nothing else starts showing.

What it stops catching, stated plainly because it is the cost: a row
that was hand edited to hold a real credential BESIDE a reference, say
`sk-live-abc $UNUSED`, now displays in full. That value is one the
widened write check admits anyway, so the mask would have been hiding a
value this project had already agreed to store; and a display and a
write path that disagree about the same value is how a mask became a
keep marker over a value shown in full, which this repository has
already paid for once. One rule, read by both, is the remedy it settled
on then.

A side effect worth naming because it is a fix: a padded whole-value
reference (`"$TOKEN "`), which the secret rule accepts today and the
display rule masks, currently exports as a mask and cannot be imported
into an empty database either. It is the same defect in a rarer shape,
and it goes away with this.

**The acceptance case, which is the reviewer's and is required:** a
composed header is written, exported, imported into an EMPTY database,
and the server built from the second database sends the byte-identical
header the first one did. End to end, through the real export and
import, not through the display alone.

### #504: the redactor is given the atoms, not only the wire values

The review's second P1, and the plan had not followed the value this
far. An opted-in MCP entry's instructions reach a system prompt and a
gated read, and `_capture` takes this deployment's own credentials back
out of them by handing `_redactor` the materialized `env` and `headers`
values and replacing those complete strings. That works while a value
IS the secret. It stops working the moment a value CONTAINS one: with
`TOKEN=secret`, the materialized header is `Bearer secret`, and a
server that reads its own Authorization header can hand back `secret`
on its own, which is in no redaction set and reaches stored guidance,
the model's input, the prompt preview and the CLI.

So resolution answers with two things rather than one: the resolved
mapping, and the set of secret values it substituted. The atoms are
already in hand at the only place they exist, which is the resolver
reading the environment; recovering them anywhere else would mean
re-reading the environment or diffing strings, and both are a second
derivation of a fact one function already holds.

- `resolve_env_references` keeps its signature for every caller that
  wants only the mapping, and a sibling answers with both. Which of the
  two is the primitive and which is the thin one is the implementer's
  call under the deletion test; what the plan fixes is that the atoms
  cross the seam rather than being reconstructed.
- `config/secrets.py`'s MCP resolution passes them through, since it is
  what the manager calls.
- `tools/mcp/manager.py`'s `_capture` gives the redactor the atoms
  beside the materialized values, and `tools/mcp/prompts.py`'s
  `_redactor` keeps its longest-first rule, which already handles one
  value containing another and therefore handles an atom inside its own
  composed value.
- The stored credential path is unchanged: a slot holding ciphertext
  resolves to the whole value, which is its own atom.

**The case, and it is hostile by construction:** a server that reflects
the BARE token, without the `Bearer ` prefix, in its instructions. The
sentinel is asserted absent from stored guidance, the prompt preview,
the API read, the CLI output, both log formats, the event payloads and
every exception chain. The existing reflection coverage uses a
whole-value reference and would stay green through this defect, which
is why the new case is written to fail first.

### #504: an encrypted slot still holds the finished header

A stored secret replaces its slot's whole value: `secrets.py` removes
the key from reference resolution and puts the ciphertext's plaintext
in. So an encrypted `headers.Authorization` slot filled with the
vendor's raw token sends the raw token, not `Bearer <token>`, and an
example that offers the encrypted slot beside the composed reference
without saying so would walk an operator into a 401 that looks like a
bad key.

The example says it: the encrypted slot holds the FINISHED header
value, the composed reference is the other way of getting there, and
the two are not interchangeable halves of one recipe. Composing inside
an encrypted slot is not in this milestone, and the plan says that
rather than leaving it implied: it is a different design question, with
a template holding several references as its hard case.

The precedence is pinned at the wire rather than in the resolver: with
both a written reference and a stored secret for one key, what the
server is handed is the stored one, whole.

### #504: a value that contained a literal `$word` changes meaning

This is the upgrade trap and it is the reason the changelog entry
exists. Today `Authorization: Bearer $TOKEN` is a literal string sent
verbatim; after this change it is a reference and the boot resolves it.
A deployment that relied on sending a literal dollar sign inside a
header or an env value gets one of two outcomes, and neither is silent:
the variable is set, and the value changes; or it is not, and the boot
refuses naming the variable and the location.

No escape syntax is added. `$$` would be a second spelling to document,
to test and to explain, for a case this project has never seen, and the
absence is one line in the field description rather than a mechanism.
If a deployment ever needs a literal `$`, that is an issue with a real
report behind it.

### #504: what the refusal says when there is no reference at all

The rule the check enforces becomes "a secret-bearing key's value must
reference an environment variable somewhere in it". The sentence
changes with it, from "looks like an inline secret, which is not
allowed; reference an environment variable instead" to one that names
what is now allowed, with the composed form as its example, and it
still quotes neither the key nor the value.

### #507: the recovery belongs at the boot, and to one refusal class

The refusal itself is raised by `_body` through `_from_row`, and every
kind and every reader shares it, the running server's API included.
There, the advice the issue wants would be wrong: with the server up,
an unreadable row IS reachable, `vinga mcp-server delete` does remove
it by identity, and telling an operator to rebuild from an export would
be advice to do something drastic instead of something that works.

What makes the boot different is the door being shut, and the boot is
the one place that knows it. So the second line is printed where the
boot prints its refusal, in `serving.py`.

**But not for every `StorageError`, which is the review's third P1 and
a real misclassification.** That class covers an unreadable stored row
AND a database that cannot be reached at all, a migration that failed,
a superseded revision and a missing schema privilege; `db/__init__.py`
raises it for several of those. A database outage answered with "your
configuration is unreadable, rebuild from an export" would send an
operator to destroy a healthy configuration over a network problem.

So the milestone introduces the distinction the code is missing: a
subclass of `StorageError` meaning "a stored row cannot be read as
configuration", raised at the decision sites that already know it (the
per-row refusal in `_body`/`_from_row`, the assembly refusal in
`_read_domain`, and the sibling stored-state refusals beside them that
name an entry), and caught by name at the boot. No message parsing
anywhere: the classification is the type, decided where the code
actually classifies.

Every other reader keeps what it has. The subclass IS a `StorageError`,
so the API's 500, the reload path and the diff path go on catching what
they catch and answering what they answer.

That also settles where the sentence must NOT go: not into `_body`, not
into `_read_domain`, and not into the API's 500, each of which serves
readers for whom it is false.

### #507: what the second line says

Three facts and no parsing: that the row is in the domain database and
the location above addresses it, that the configuration API cannot
reach it until the server boots, and the procedure this project already
records (boot a server on an empty domain database, import a kept
`export`, re-enter the secrets an export deliberately omits, apply).

It does not try to name the table by taking the location apart. The
location is printed directly above it, and a sentence that re-derives
half of it is a second spelling of an identity.

### #507: the migration's docstring is corrected, not rewritten

`3004_reach_replaces_egress` argues, correctly, that aborting the
migration would lock the operator out of the one door to the row. That
argument stands. The sentence that does not is the one after it, which
claims the refusal is bounded to the entry and that
`vinga provider delete` and `vinga mcp-server delete` reach it. That is
true of a running server and false of a boot, which is the case the
migration is about. The docstring says which is which, and names what
the boot now prints.

An immutable record is not being edited here: a migration's docstring
is its reasoning, and a migration whose reasoning contains a false
claim about the release it shipped in is the thing to fix. The data
step itself does not move.

## Module layout

No new module in either milestone.

| Milestone | Module | Change |
| --- | --- | --- |
| M1 | `config/models.py` | `_ENV_REFERENCE_RE` becomes the scanner; `_env_reference` answers the whole-value question with `fullmatch`; a new `_env_references` substitutes every occurrence; `resolve_env_references` uses it; `_secret_problems` asks whether a value contains one; the `headers` and `env` field descriptions say what a value may hold |
| M1 | `config/secrets.py` | one comment, which currently claims a mirror that will no longer exist |
| M1 | `examples/mcp-server-streamable-http.yaml` | the composed header as the example beside `Authorization`, with the doubled-prefix 401 named |
| M2 | `serving.py` | `StorageError` caught ahead of `ConfigError` where the boot loads its configuration, printing the refusal and then what to do about it |
| M2 | `db/migrations/versions/3004_reach_replaces_egress.py` | the docstring paragraph that is true of a running server and false of a boot |

Design footprint, M1: one pattern asked two ways instead of two
patterns, and a substitution function beside the resolver that already
owned this vocabulary. Nothing new crosses a seam: `resolve_env_references`
keeps its signature, and no caller learns that a value may now be
composed.

Design footprint, M2: one refusal class separated from its parent at
the one site that can tell them apart. The depth claim is that no other
reader changes: the API, the reload path and the diff path keep the
sentence they have, because for them it is still the whole truth.

## Tests

**M1, the no-leak suite, which is the bulk of it.** The lens this
milestone is squarely inside: widening a secret-bearing check earns the
full sentinel treatment. The sentinel is planted as a VALUE, because
the value is what this change lets through and what a resolved header
carries; the KEY is what `_secret_problems` matches on and is an
ordinary declared word, never key material.

- A composed value resolves: `Bearer $TOKEN` with `TOKEN` set reaches
  the server as `Bearer <secret>`, asserted on what the transport is
  handed rather than on the model.
- Several references in one value each resolve, and a value with none
  passes through byte for byte.
- An unset variable refuses, naming the location and the variable and
  quoting neither the value nor anything around it.
- The sentinel: with a credential-shaped literal as part of a composed
  value, nothing of it appears in the refusal sentence, in `record.msg`
  or the typed `record.args` of either log format, in any config read,
  or in any `__cause__`/`__context__` chain reachable from the boot.
  The partially-resolved intermediate is included in that claim, which
  is what the issue's third verification box asks for.
- And the surface the plan first forgot: a server tap is ATTACHED while
  both paths run, the connection that succeeds and the one that
  refuses, and the sentinel is absent from every `Emission` payload and
  every typed argument on it. The events tap is its own retained
  transport in the observability contract and a claim about logs is not
  a claim about it. The suite reads every record through the existing
  all-record rendering helper rather than filtering by logger, so a
  foreign library's record cannot be silently excluded from the
  assertion.
- `Authorization: pasted-token-here`, with no reference anywhere in it,
  is still refused, and the refusal still quotes no key material.
- `mask` still returns the mask for a composed value, which is the
  decision above pinned rather than assumed.
- The whole-value question keeps rejecting a terminal newline, which is
  the `fullmatch` decision pinned as a boundary case, written FIRST.

**M2.** The boot printing is the behavior, so it is tested at the boot.

- A stored row that cannot be read as configuration refuses the boot,
  exits 1, and prints the refusal AND the recovery, with the entry's
  location intact and no value quoted.
- A configuration failure that is not a storage one (a file the loader
  refuses) prints the refusal and NOT the recovery, which is the case
  that proves the branch is the branch and not a sentence appended to
  everything.
- The same unreadable row, read through the running server's API,
  still answers 500 with the sentence it answers today and gains
  nothing: the milestone must not change what a reader with a working
  door is told.
- A reach value outside the three is the shape the issue reports, so
  that is the row the boot case uses, written through the store the way
  a hand edit would leave it rather than through a model that would
  refuse it.

**Falsify before claiming, both milestones.** Each new case is watched
failing before its claim is made: M1's against the anchored pattern,
M2's against the single `except ConfigError`. A mutation that survives
is reported as a finding about the test.

## Documentation footprint

- M1: the `headers` and `env` field descriptions in `config/models.py`,
  which regenerate `docs/reference/domain-config.md` and
  `api-openapi.json` (and `cli.md` if it renders either), through their
  generators only. `examples/mcp-server-streamable-http.yaml`, which is
  what an operator copies and where the issue asks for the constraint
  and the doubled-prefix 401 to be named. The MCP section of
  `vinga-server/README.md` if it states the whole-value rule; checked,
  not assumed.
- M2: the migration docstring. `docs/reference/cli.md` only if the
  recovery procedure's own wording moves, which this milestone does not
  intend: it points AT that procedure rather than restating it.
- Both: a `changelog.d/<issue>-<slug>.md` fragment each. M1's is
  `### Changed` and must carry the upgrade note about a literal `$`
  changing meaning. M2's is `### Changed` too, and tells an upgrader
  what the failure looks like and what to do, since the row that
  triggers it arrives from a restore or a hand edit rather than from
  this project.
- The command-spellings census is re-run after any documentation edit,
  and regenerated by its generator if it moved.

## Risks

- **M1 widens what a secret-bearing key accepts.** A value containing a
  reference and a pasted credential now passes the write-time check.
  Accepted, with the boundary held elsewhere: the display path stays
  closed, so such a value never renders, and the check was always a
  guard against the obvious mistake rather than a guarantee about what
  an operator can write. Named here so the review sees it was weighed.
- **M1 changes the meaning of an existing value.** Covered above; the
  failure is loud and the changelog says so.
- **M2 prints more on a failing boot.** The added line is fixed text
  with no value in it, and the case that proves it is absent from the
  non-storage branch is in the suite.

## Milestones

- [ ] **M1 (#504): a header may compose a reference**. `$NAME`
  interpolates anywhere inside an `env` or `headers` value, the
  secret-bearing check asks whether a value contains a reference, the
  refusal says what is now allowed, the display path stays closed with
  its comment corrected, and the example carries the composed header
  and the doubled-prefix 401. The sentinel suite above. Design
  footprint: one pattern asked two ways, one substitution beside the
  resolver, no new seam. Documentation footprint: two field
  descriptions with their regenerated references, the streamable_http
  example, and the README's MCP section if it states the old rule.
- [ ] **M2 (#507): a refused boot says what to do**. `serving.py`
  separates `StorageError` from its parent at the one site that can
  tell them apart and prints the recovery beside the refusal; `3004`'s
  docstring stops claiming a scoping that holds only while the server
  runs. Design footprint: one refusal class separated at one site, no
  other reader changed. Documentation footprint: the migration
  docstring, and nothing generated unless the recovery procedure's own
  wording moves, which it should not.

M1 first because #504 is the queue's order and because M2's diff is
smaller and touches a file M1 does not. M2 stacks on M1's branch and
starts when M1's pull request opens.

## Plan review round

External review: codex CLI 0.154.0, model gpt-5.6-sol, read-only
sandbox, 2026-09-14, runtime 10m30s, reviewing commit 9514ec46.
Verdict as received: **not ready** (three P1s; the masking and export
conflict and the reflected-secret leak need redesign before
implementation).

Every finding was checked against the code before being accepted, and
all seven hold. Two of the three P1s are about surfaces this plan never
looked at, which is the value of the round: the plan reasoned about the
write path and the display path and did not follow the value to the
places it is materialized.

Findings condensed but faithful; resolutions appended per amendment.

### 1 (P1): anchored masking makes a composed reference unexportable

The plan accepts that `Bearer $TOKEN` displays as the mask.
`views._masked` masks every string under a secret-shaped name, and
`store._keep` refuses a mask when the entity does not exist yet, which
is every entry of an import into an empty database. So a valid composed
reference exports as the mask and cannot be imported back, which
contradicts the export-and-reapply promise and is exactly the recovery
M2 tells an operator to perform. The plan should define a
representation that is both non-leaking and replayable and require an
end-to-end test: export `Bearer $TOKEN`, import into an empty database,
prove identical wire output.

*Resolution* (commit below): taken, and the decision reversed. The
display rule now follows the write rule: a value containing a reference
displays, a value containing none masks. It restores export and import
for composed values, fixes the same latent defect for a padded
reference, removes the mirror that was about to become false, and costs
the case where a hand-edited row holds a paste beside a reference,
which the widened write check admits anyway. The end-to-end export,
import into an empty database and identical wire output is now the
milestone's acceptance case.

### 2 (P1): interpolation defeats the MCP reflected-credential redactor

`_capture` hands `_redactor` only the fully materialized `env` and
`headers` values, and `_redactor` replaces those complete strings. With
`TOKEN=secret`, `Bearer $TOKEN` materializes as `Bearer secret`, and a
server that parses its own Authorization header can hand back `secret`
alone in its instructions. That substring is in no redaction set, so it
reaches stored guidance, the model's input, the prompt preview and the
CLI. The existing reflection coverage uses a whole-value reference and
stays green. The plan should make resolution expose every substituted
secret atom as well as the wire values, feed both to the redactor, name
the changes in `tools/mcp/manager.py` and `tools/mcp/prompts.py`, and
test it with a hostile server that reflects the bare token.

### 3 (P1): `StorageError` does not distinguish an unreadable row from a broken database

The plan catches every `StorageError` at boot, but that class covers an
unreachable database, a migration failure, a superseded revision and a
missing schema privilege as well as an unreadable row. An ordinary
database outage would be answered with destructive rebuild advice. The
plan should introduce a typed distinction raised at the row and
assembly decision sites, catch only that at boot, and test the negative
cases (database unreachable, schema privilege, generic storage
failure), with no message parsing anywhere.

*Resolution* (commit below): taken. The milestone now adds a subclass
of `StorageError` for an unreadable stored row, raised at the sites
that already classify it and caught by name at the boot, with the
negative cases (unreachable database, schema privilege, generic storage
failure) in the suite beside the positive one. No message parsing, and
every other reader keeps the behavior it has because the new class is
still a `StorageError`.

### 4 (P2): the documented encrypted alternative discards the composed prefix

A stored secret replaces the whole slot value, so an encrypted
`headers.Authorization` slot holding the vendor's raw token sends the
raw token and not `Bearer <token>`. The example must say the encrypted
slot holds the FINISHED header value, keep that separate from raw-token
interpolation, and pin the precedence at the wire.

*Resolution* (commit below): taken. The example states that an
encrypted slot holds the finished header value, keeps it apart from the
composed reference, and the precedence is pinned at the wire. Composing
inside an encrypted slot is named as out of scope with its reason.

### 5 (P2): the `fullmatch` and newline reasoning does not describe observable behavior

`_env_reference` matches against `value.strip()`, so a padded reference
is accepted today and is pinned by a round-trip case; `fullmatch` over
a stripped value still accepts a terminal newline, and the scanner
would substitute inside `Bearer $TOKEN\n` regardless. The plan should
decide what happens to the trimming, test the decision through
`resolve_env_references` and the real transport rather than through a
private helper, and say what it does about CR/LF in a header value. If
`_env_reference` has no production caller after the scanner lands, it
should be deleted rather than kept and tested privately.

### 6 (P2): the sentinel plan omits the attached event consumer

The suite checks sentences, `record.args`, both log formats, reads and
exception chains, but not the `Emission` handed to an attached tap,
which is its own retained transport in the observability contract. The
plan should attach a server tap across both the connecting and the
refusing path and assert the sentinel is absent from every payload and
typed argument, using the existing all-record rendering helper so a
foreign logger's records are not silently excluded.

*Resolution* (commit below): taken. The sentinel suite now attaches a
tap across the connecting and the refusing path, asserts absence from
every emission payload and typed argument, and reads records through
the all-record helper rather than by logger.

### 7 (P2): M2's recovery has no answer when no export exists

The line names only the rebuild from a kept export, and the procedure
requires an export taken while healthy. A restored or hand-edited
database may have none, which is the issue's own path. The output
should cover both: the rebuild where an export exists, and otherwise
correcting or deleting the addressed row through SQL as the server
role, which the CLI reference already names as the surgical
alternative.
