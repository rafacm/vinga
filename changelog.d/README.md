# Changelog fragments

A branch never edits `CHANGELOG.md`. It writes one file here, and a
workflow on `main` folds the file into the dated section after the
merge. Two branches adding two files cannot conflict, which is the
whole reason this directory exists: the dated section used to conflict
on almost every rebase, and one such merge silently dropped a finished
milestone's entry from `main` for five merges.

## The contract

- **One file per change**, named `<issue>-<slug>.md`: the issue number
  the change belongs to (the pull request number where no issue
  exists), a dash, and a short lowercase-and-dashes slug.
  `467-changelog-fragments.md` is the shape.
- **Headings are `### <Class>`**, from the closed Keep a Changelog six:
  `Added`, `Changed`, `Deprecated`, `Removed`, `Fixed`, `Security`. One
  file may carry several, and each must be followed by entry text.
- **No date header and no `##` heading.** The date is not the fragment's
  to state: the fold derives it from the commit that brought the
  fragment onto `main`, so a session running past midnight no longer
  has to move its entries into a new section by hand.
- **The entry text is final.** Whatever is written under a heading is
  moved into `CHANGELOG.md` byte for byte: the same list items, the
  same bolding, the same wrapping. What is reviewed on the pull request
  is what the changelog will read.
- **This README is not a fragment.** It is excluded by name, so it can
  sit here without ever being folded.

## What enforces it

- A pull request that changes `CHANGELOG.md` is refused by the `docs`
  workflow. The escape hatch for a genuine correction of history is the
  literal phrase `Corrects CHANGELOG history` in the pull request body,
  where a reviewer sees it.
- A malformed fragment is refused on the pull request too, by the same
  workflow, so a bad filename or an unknown heading fails before it can
  reach `main`.
- `.github/workflows/changelog-fold.yml` runs the fold on every push to
  `main` that touches this directory, and its failure is a red run on
  `main`. An unfolded fragment is a tracked file either way, so unlike
  a dropped entry it is visible in the tree.

## Folding by hand

The workflow runs one command, and so can a person:

```bash
python3 scripts/fold_changelog.py fold .
```

from the checkout root. It moves each fragment's entries into its dated
section, deletes the fragments, and refuses without writing anything
when its own post-conditions do not hold. Running it with no fragments
present is a no-op. `check` validates the fragments without writing.
