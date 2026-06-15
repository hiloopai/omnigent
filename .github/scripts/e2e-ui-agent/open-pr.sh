#!/usr/bin/env bash
# Commit the already-staged (allowlist-enforced) changes onto a fresh branch,
# push with the App token, and open a PR. The App token (not GITHUB_TOKEN) is
# used for BOTH push and `gh pr create` so the new PR's own checks actually run --
# GitHub suppresses workflow triggers for actions taken by GITHUB_TOKEN (the
# loop-guard), exactly as oss-regen-on-comment.yml documents.
#
# The bot is not in .github/MAINTAINER, so the opened PR still requires
# `Maintainer Approval` -- no merge bypass. It is opened as a draft unless the
# caller verified the result is green.
#
# Env in: REPO, BRANCH, BASE (default main), COMMIT_MSG, PR_TITLE, PR_BODY_FILE,
#         PUSH_TOKEN, REVIEWER (optional), DRAFT (true|false, default true),
#         LABELS (optional, comma-separated)
# Out:    pr_url=<url> on $GITHUB_OUTPUT (empty when nothing to commit)
set -euo pipefail

BASE="${BASE:-main}"
out="${GITHUB_OUTPUT:-/dev/null}"

git config user.name "github-actions[bot]"
git config user.email "41898282+github-actions[bot]@users.noreply.github.com"

if git diff --cached --quiet; then
  echo "No staged changes; nothing to open."
  echo "pr_url=" >> "$out"
  exit 0
fi

git checkout -b "$BRANCH"
git commit -q -m "$COMMIT_MSG"
git push "https://x-access-token:${PUSH_TOKEN}@github.com/${REPO}.git" "HEAD:$BRANCH"

# gh authenticates from GH_TOKEN; use the App token so the PR's checks fire.
export GH_TOKEN="$PUSH_TOKEN"
args=(--repo "$REPO" --base "$BASE" --head "$BRANCH" --title "$PR_TITLE" --body-file "$PR_BODY_FILE")
[[ "${DRAFT:-true}" == "true" ]] && args+=(--draft)
url=$(gh pr create "${args[@]}")
echo "Opened: $url"

if [[ -n "${REVIEWER:-}" ]]; then
  gh pr edit "$url" --repo "$REPO" --add-reviewer "$REVIEWER" \
    || echo "::warning::could not request review from @$REVIEWER (e.g. PR author can't review own PR / not a collaborator)"
fi
if [[ -n "${LABELS:-}" ]]; then
  gh pr edit "$url" --repo "$REPO" --add-label "$LABELS" \
    || echo "::warning::could not add labels: $LABELS"
fi
echo "pr_url=$url" >> "$out"
