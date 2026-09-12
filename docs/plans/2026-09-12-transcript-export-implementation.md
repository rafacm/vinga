# Transcript export as the third optional telemetry layer: implementation

Companion to [`2026-09-12-transcript-export.md`](2026-09-12-transcript-export.md),
one section per milestone, appended in the same change that ticks the
milestone checklist. It records deviations from the plan, resolutions of
the plan's open questions, and discoveries.

## M1: rename attach_captures to export_audio

The mechanical sweep the plan sequenced first, so the new flag's prose,
refusal ordering and tests in M2 are written against the final
vocabulary once instead of twice. Semantics are untouched: same default
of off, same builder ordering, same three refusals, same no-op with
capture off. No alias machinery was added and none was found to remove;
a file still spelling `attach_captures` is refused at boot by the
telemetry section's existing `extra="forbid"`.

### What moved

| Site | What changed |
| --- | --- |
| `config/models.py` | the `TelemetryConfig` field and its description prose, the section docstring's sentence contrasting it with `enabled`, and the `BOOT_REFUSALS` registry comment's closing clause |
| `capture_upload.py` | `ATTACH_KEY`'s value, the builder docstring's step 3, the `attaching` read, and both refusal sentences (`ATTACHMENT_NEEDS_TELEMETRY` and `ATTACHMENT_NEEDS_AN_EXPORTER`, the latter through `ATTACH_KEY`) |
| `telemetry.py` | the vocabulary-exception note's sentence about when a media reference is written at all |
| `config.example.yaml`, `config.deploy.example.yaml` | the commented-out key in the telemetry block |
| `tests/unit/test_capture_upload.py` | 16 sites, including the pin that `ATTACH_KEY` ends in the key's own spelling |
| `tests/integration/test_capture_upload.py` | one `TelemetryConfig(...)` construction |
| `tests/integration/test_tier_closure.py` | the environment-variable spelling, `VINGA_SERVER__TELEMETRY__ATTACH_CAPTURES` |
| `docs/reference/server-config.md` | regenerated through its generator, never hand-edited |
| `docs/architecture/observability-surfaces.md` | the exported-capture-media row's switching clause |
| `docs/adr/2026-08-15-content-and-telemetry-are-separate-surfaces.md` | the 2026-09-12 amendment's key, plus one clause naming the rename |
| `.github/workflows/vinga-server.yml`, `vinga-server/pyproject.toml` | the two build comments that name the flag to explain why both image variants carry the observability extras |

`ATTACH_KEY` keeps its constant name. It names the role the constant
plays (the one spelling every refusal below it quotes), not the spelling
of the key it holds, so renaming it would have been churn with no reader
served.

Historical records kept their spelling, per the plan's documentation
rule: the two `2026-09-12-langfuse-backend*.md` files and the folded
`CHANGELOG.md` entry describe the repository on their own date.

### Deviations from the plan

One, and it is an addition to the census rather than a departure from a
decision.

- **A seventeenth site the plan's census did not name:**
  `tests/integration/test_tier_closure.py` sets the flag through the
  environment rather than through a file, as
  `VINGA_SERVER__TELEMETRY__ATTACH_CAPTURES`. The loader derives that
  variable's name from the field, so the rename moves it too and a
  missed one would have left that lane setting a key the model no longer
  has. Renamed with the rest; the lane passes.

Nothing else deviated. The plan's census was otherwise exact, and
`config/loader.py` holds no alias machinery to remove, as the plan said.

### Discoveries

- **The command-spellings census was already stale at the branch head,
  and not from the rename.** The unit lane's
  `test_the_manifest_is_the_census` failed on one missing row, and the
  spelling behind it is a sentence in this plan's own Goal paragraph:
  the sweep reads every tracked file and matches an invocation-shaped
  run of words after a program word, and ordinary prose naming the
  program and a noun looks exactly like one. So the census has been
  stale since the plan was committed, several commits before this
  milestone started. `docs/plans/` is a historical path, so the row is
  classified `historical` and nothing is asked to respell.
  Regenerated rather than hand-edited, which is what the row's
  presence then records.
- **And a census row must not be quoted back into a tracked page.**
  The first draft of the paragraph above reproduced the row and the
  sentence behind it verbatim. The next sweep matched the quotations
  too, and the line break inside one of them produced a SECOND,
  shorter row, so the manifest grew a spelling that existed only
  because this page described the first one. The paragraph now names
  the row without reproducing it. Worth knowing before writing about
  the census anywhere: quoting it edits it.
- **The unknown-key refusal names the section, not the key.** The
  milestone brief expected the refusal to name `attach_captures`. It
  does not, and deliberately: `config/models.py` renders pydantic's
  `extra_forbidden` in this repository's own words and relocates the
  error from the key to the parent it was written under, because an
  unknown key's spelling is operator input and this loader does not
  print input. So an operator who still writes the dead key is told
  `server.telemetry: an unrecognized key is not permitted`. The new test
  pins what the loader actually does rather than what the brief
  expected, and asserts in the same breath that the value the dead key
  carried never reaches the message and that nothing is chained behind
  it.

### The falsification

The new case, `test_the_old_attachment_key_is_refused_at_boot` in
`tests/unit/test_config.py`, was written before the rename and run
against the pre-rename tree, where it failed:

```
assert 'server.telemetry: an unrecognized key is not permitted' in
  'invalid config in the config file --config names:
   - server.telemetry.attach_captures: Input should be a valid boolean,
     unable to interpret input'
```

That is the discriminating failure and not an accident of the fixture:
the key's value is the credential-shaped `PARSER_SENTINEL`, so a
pre-rename tree raises `ConfigError` too, for a boolean type error. Only
the assertion on the unrecognized-key sentence separates the two, which
is why it is the one asserted.

After the rename it passes. It was then falsified a second time from the
other side: the test body pointed at `export_audio`, the live key, and
re-run. It failed with the same shape of message
(`server.telemetry.export_audio: Input should be a valid boolean`),
which proves it pins the old key's retirement rather than merely that
some `ConfigError` is raised. The body was restored to
`attach_captures`, the file touched to defeat any `.pyc` staleness, and
the whole file re-run green (150 passed).

### Verification

- [x] `uv run ruff check .`: all checks passed.
- [x] `uv run mypy` (the events package's strict check, the workflow's
      spelling): success, no issues found in 5 source files.
- [x] `uv run pytest tests/unit -q -n 4 --dist loadfile`: 6999 passed,
      19 skipped, 1 failed on the first run,
      `test_command_spellings.py::test_the_manifest_is_the_census`,
      on a row this branch's plan commits had already made stale (see
      the discovery above). Regenerated with
      `uv run python -m tests.unit.test_command_spellings` in the same
      commit as the last doc edit, per the repository's rule; that
      file's own suite is green afterwards.
- [x] `uv run pytest tests/integration -q`: 325 passed, against a
      Postgres 17 from the committed compose file on its own project and
      port.
- [x] `python3 scripts/check_doc_links.py .`: checked 234 files, 0
      failures.
- [x] `python3 scripts/fold_changelog.py check .`: checked 1 fragment, 0
      failures.
- [x] The committed server reference is current: regenerated with
      `uv run vinga-server config reference server > ../docs/reference/server-config.md`
      and held by `tests/unit/test_server_reference.py`, which the unit
      lane above ran.
- [x] Both example configs still parse and still cover every leaf:
      `tests/unit/test_config_examples.py`, in the lane above.
- [ ] The image lane's extras checks, which quote the flag in a comment
      only. Not run here: they build both image variants and the comment
      they carry is not executable. CI runs them on everything but a
      pull request.
- [ ] Anything on a board. This milestone changes no protocol, no
      firmware-visible behavior and no device path, so there is nothing
      a device checkpoint could falsify.

### PR review round, PR #497

External review: codex CLI 0.154.0, model gpt-5.6-sol, read-only
sandbox, 2026-09-12, runtime 3m31s, reviewing origin/main...a8de0b83.
Verdict as received: **mergeable after the listed fix**. One finding.

1. **P2: The old-key refusal test does not pin suppression of the
   rejected key.** The test's comment claims the refusal names only
   the section, but the assertions only exclude the sentinel value,
   so a refusal echoing `attach_captures` (itself rejected operator
   input) would pass. Fix: assert the old key's spelling absent from
   the refusal beside the value and chain assertions.

   *Resolution.* Adopted; `assert "attach_captures" not in refusal`
   joins the case. Falsified by running the assertion against a
   constructed key-carrying refusal sentence, which fails it; the
   suite file re-run green (150 passed).
