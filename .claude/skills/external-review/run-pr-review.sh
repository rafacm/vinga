#!/bin/sh
# Self-posting PR review: runs the review backend against a PR's diff
# from inside the PR's worktree, then posts the result as a comment with
# a provenance header, so the review lands even if the driving session
# dies between the review finishing and the comment being posted.
#
# Usage:
#   run-pr-review.sh <worktree> <base-ref> <pr-number> "<pr-title>" "<context sentence>"
#
# The reviewer, its model and its reasoning effort come from
# REVIEW_BACKEND, REVIEW_MODEL and REVIEW_EFFORT, read by
# review-backend.sh beside this script; the tiering rule (sol for
# plans and behavior-changing milestone PRs, terra for low-stakes
# rounds) lives in SKILL.md. The provenance header records the run as
# `<provider>/<model>, thinking <level>`, the attribution string the
# implement-issue skill defines.
#
# Writes its working files (diff, prompt, output, posted comment) next
# to nothing in the repository: they go to $TMPDIR (or /tmp).
set -eu
WORKTREE="$1"; BASE="$2"; PR="$3"; TITLE="$4"; CONTEXT="$5"
SKILL_DIR="$(cd "$(dirname "$0")" && pwd)"
. "$SKILL_DIR/review-backend.sh"
review_select
WORK="${TMPDIR:-/tmp}/external-review-pr-$PR"
mkdir -p "$WORK"
DIFF="$WORK/diff.txt"
PROMPT="$WORK/prompt.md"
OUT="$WORK/out.txt"
ERR="$WORK/err.txt"

cd "$WORKTREE"
git diff "$BASE"...HEAD > "$DIFF"

# Placeholder substitution via python: the title and context are prose
# and sed's replacement syntax would mangle the characters prose uses.
python3 - "$SKILL_DIR/pr-review-prompt.md" "$PROMPT" \
  "$PR" "$TITLE" "$CONTEXT" "$DIFF" "$BASE" <<'PY'
import sys
template, out, pr, title, context, diff, base = sys.argv[1:8]
text = open(template).read()
for key, value in [("__PR_NUMBER__", pr), ("__PR_TITLE__", title),
                   ("__CONTEXT__", context), ("__DIFF_FILE__", diff),
                   ("__BASE__", base)]:
    text = text.replace(key, value)
open(out, "w").write(text)
PY

review_run "$PROMPT" "$OUT" "$ERR"
HEAD_SHA="$(git rev-parse --short HEAD)"
{
  printf '## External review round\n\n'
  printf 'Automated external review of this PR'"'"'s diff (%s...%s). Reviewed %s by %s via %s, runtime %s, at commit %s. Posted verbatim by the review run itself; resolutions follow as replies.\n\n' \
    "$BASE" "$HEAD_SHA" "$(date -u +%Y-%m-%d)" "$ATTRIBUTION" "$CLI_STAMP" "$DURATION" "$HEAD_SHA"
  printf -- '---\n\n'
  cat "$OUT"
} > "$WORK/comment.md"

gh pr comment "$PR" --repo rafacm/vinga --body-file "$WORK/comment.md"
echo "posted review to PR #$PR (working files in $WORK)"
