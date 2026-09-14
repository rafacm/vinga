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

### #504: one pattern, asked two ways

`_ENV_REFERENCE_RE` stops being anchored and becomes the scanner.
"Is this value exactly a reference" is then the same pattern asked with
`fullmatch`, so the two questions cannot drift apart.

`fullmatch` deliberately, never `match` with a `$` appended: `re.match(p + "$")`
accepts a terminal newline where `fullmatch` does not, which broke a
same-syntax contract in #500 M4 and was a live bug in `PCM_FORMAT_PATTERN`
beside it. A header value ending in a newline is exactly the shape a
copy-paste produces.

### #504: the display path stays anchored, and a composed value shows as the mask

`config/secrets.py` has its own `_DOLLAR_REFERENCE_RE`, and its comment
says it mirrors the model's pattern. After this change it deliberately
does not, and the comment must say so rather than be left as a claim
that has quietly become false.

It stays anchored because it answers a different question. `mask`
decides what a stored secret slot may DISPLAY, and it fails closed: a
value that is exactly `$TOKEN` is a variable name and not a secret, so
it shows; anything else may be a pasted credential, so it becomes the
mask. Widening it to "contains a reference" would display
`sk-live-abc $UNUSED` in full, and the write-time check can no longer
rule that value out, because after this change it contains a reference
and passes. So the two moves are not symmetric, and only one of them is
safe.

The consequence, stated because an operator will meet it: a composed
header stored in a secret slot reads back as the mask rather than as
`Bearer $TOKEN`. That is the display path answering "I cannot prove
this is safe to print", which is the answer it exists to give.

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

### #507: the recovery belongs at the boot, not in the refusal

The refusal itself is raised by `_body` through `_from_row`, and every
kind and every reader shares it, the running server's API included.
There, the advice the issue wants would be wrong: with the server up,
an unreadable row IS reachable, `vinga mcp-server delete` does remove
it by identity, and telling an operator to rebuild from an export would
be advice to do something drastic instead of something that works.

What makes the boot different is the door being shut, and the boot is
the one place that knows it. `serving.py` already catches
`ConfigError` where it loads the configuration and prints one sentence;
`StorageError` is a subclass, and catching it a line earlier is the
whole seam. The stored-row refusal then prints with a second line
saying what the running-server case does not need.

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
