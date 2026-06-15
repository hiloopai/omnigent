#!/usr/bin/env bash
# Mechanically restrict the agent's working-tree changes to $ALLOW_PREFIX, then
# stage exactly those. Anything the agent touched outside the prefix is reverted
# (tracked) or removed (untracked). Never trust the prompt to stay in its lane.
#
# How it works:
#   1. stage every change (add/modify/delete) under the prefix, incl. new files;
#   2. `git checkout -- .` reverts all *unstaged* tracked modifications -- i.e.
#      everything outside the prefix (prefix changes are staged, so untouched);
#   3. `git clean -fdq` removes leftover untracked files -- staged new files under
#      the prefix are in the index, so clean leaves them.
#
# Env in: ALLOW_PREFIX (default tests/e2e_ui/)
# Out:    staged tree contains only ALLOW_PREFIX changes; prints them.
set -euo pipefail

ALLOW_PREFIX="${ALLOW_PREFIX:-tests/e2e_ui/}"

git add -A -- "$ALLOW_PREFIX"
git checkout -- .
git clean -fdq

echo "Allowlist enforced (prefix: $ALLOW_PREFIX). Staged changes:"
git diff --cached --name-only || true
