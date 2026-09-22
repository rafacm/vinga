#!/bin/sh
# Plan review: runs the review backend against a committed plan from
# inside the plan's worktree and writes the round, header and findings,
# to a file the session records into the plan. Nothing is posted: a
# plan round lives in the plan's own "Plan review round" section, and
# what this script fixes is the header, which used to be typed by hand
# and so recorded whatever the hand remembered.
#
# Usage:
#   run-plan-review.sh <worktree> <plan-path> <issue-number> <reading-list-file>
#
# <plan-path> is relative to the worktree. <reading-list-file> holds the
# markdown list that fills the prompt's "Then the substrate it builds
# on" slot: every file the reviewer should read, since it has no
# network and sees only the worktree. The issue body is fetched here,
# where there is a network, and pasted into the prompt.
#
# The reviewer, its model and its reasoning effort come from
# REVIEW_BACKEND, REVIEW_MODEL and REVIEW_EFFORT, read by
# review-backend.sh beside this script. The round header is the
# review-round form of the implement-issue skill's "Attribution":
# reviewer as `<provider>/<model>, thinking <level>`, tool and
# enforcement, runtime, the reviewed commit and the plan's blob hash,
# which is what still resolves after the rebase merge rewrites the
# commit.
#
# Working files (prompt, output, the round) go to $TMPDIR (or /tmp).
set -eu
WORKTREE="$1"; PLAN="$2"; ISSUE="$3"; READING="$4"
SKILL_DIR="$(cd "$(dirname "$0")" && pwd)"
. "$SKILL_DIR/review-backend.sh"
review_select
READING="$(cd "$(dirname "$READING")" && pwd)/$(basename "$READING")"
WORK="${TMPDIR:-/tmp}/external-review-plan-$ISSUE"
mkdir -p "$WORK"
PROMPT="$WORK/prompt.md"
OUT="$WORK/out.txt"
ERR="$WORK/err.txt"
BODY="$WORK/issue-body.md"

cd "$WORKTREE"
# The reviewer reads the plan live from the worktree, so a plan HEAD
# does not hold, or holds in another form, would be reviewed as
# something the recorded hashes do not name. Both checks run before
# anything else does, because the reviewer is the expensive step and
# a refusal after it has already cost the run (2026-09-22, once).
if ! git cat-file -e "HEAD:$PLAN" 2>/dev/null; then
  echo "$PLAN is not in HEAD of $WORKTREE; commit the plan first" >&2; exit 2
fi
if [ -n "$(git status --porcelain -- "$PLAN")" ]; then
  echo "$PLAN has uncommitted changes; commit the plan first" >&2; exit 2
fi
HEAD_SHA="$(git rev-parse --short HEAD)"
BLOB_SHA="$(git rev-parse --short "HEAD:$PLAN")"
BRANCH="$(git branch --show-current)"
gh issue view "$ISSUE" --repo rafacm/vinga --json body --jq .body > "$BODY"

python3 - "$SKILL_DIR/plan-review-prompt.md" "$PROMPT" \
  "$BRANCH" "$PLAN" "$ISSUE" "$READING" "$BODY" <<'PY'
import sys
template, out, branch, plan, issue, reading, body = sys.argv[1:8]
text = open(template).read()
for key, value in [("__BRANCH__", branch), ("__PLAN_PATH__", plan),
                   ("__ISSUE__", issue),
                   ("__READING_LIST__", open(reading).read().rstrip()),
                   ("__ISSUE_BODY__", open(body).read().rstrip())]:
    text = text.replace(key, value)
open(out, "w").write(text)
PY

review_run "$PROMPT" "$OUT" "$ERR"
{
  printf '## Plan review round\n\n'
  printf 'Reviewed %s by %s via %s, runtime %s, at commit %s, plan blob %s.\n\n' \
    "$(date -u +%Y-%m-%d)" "$ATTRIBUTION" "$CLI_STAMP" "$DURATION" "$HEAD_SHA" "$BLOB_SHA"
  printf -- '---\n\n'
  cat "$OUT"
} > "$WORK/round.md"
echo "$WORK/round.md"
