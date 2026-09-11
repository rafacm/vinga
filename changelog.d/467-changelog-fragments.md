### Added

- **A changelog entry is a fragment now** (#467, M2). A branch no
  longer edits `CHANGELOG.md`. It writes one
  `changelog.d/<issue>-<slug>.md` carrying `### <Class>` headings from
  the Keep a Changelog six and the entry text exactly as it should
  read in the changelog, and a workflow on `main` folds the fragments
  into the dated section after the merge. Two branches adding two
  files cannot conflict, which is the point: the dated section
  conflicted on almost every rebase, and one such merge dropped a
  finished milestone's entry from `main` for five merges without a
  single run going red. The fragment states no date; the fold derives
  the day from the committer date of the commit that brought the
  fragment onto `main`, in that commit's own recorded offset, so a
  session running past midnight no longer has to move its entries into
  a new section by hand. `changelog.d/README.md` states the contract
  where the fragments live.

- **`scripts/fold_changelog.py`**, the stdlib script both the workflow
  and a person run. It orders fragments by their introduction commit's
  place in first-parent history with the filename as the tie-breaker,
  moves entry text verbatim, and refuses without writing a byte unless
  its own post-conditions hold: every entry present exactly once, no
  conflict marker anywhere, the file outside the touched sections
  byte-identical, created sections canonical and appended-into
  sections keeping their standing shape. Settled history is not
  canonical and is never normalized or rewritten. A fragment whose
  introduction commit is not in the available history is refused
  rather than dated from today. Its diagnostics reproduce nothing they
  read: no fragment text, no filename, no git output, because they
  land in a public CI log.

- **A pull request that edits `CHANGELOG.md` is refused**, by a check
  in the docs workflow that reads the changed files from the
  pull-request files API and names the remedy in its refusal. A
  genuine correction of history says `Corrects CHANGELOG history` in
  the pull request body, where a reviewer sees it. The same job holds
  every fragment to its shape, so a bad filename or a heading outside
  the six fails where somebody can still fix it.
