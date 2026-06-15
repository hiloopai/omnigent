#!/usr/bin/env bash
# Run claude-code headless on a coding task in the current working tree.
#
# The prompt is read from $PROMPT_FILE (never passed through argv/interpolation)
# so untrusted diff / test-output text can't be shell-expanded. The agent may run
# shell + edit files (bypassPermissions) to write and run tests; it is *told* to
# touch only tests/e2e_ui/**, and the caller enforces that mechanically afterward
# with enforce-allowlist.sh. The run is bounded by a wall-clock timeout and
# claude's own --max-turns.
#
# SECURITY: invoke this step with gateway creds only and NO GitHub write token in
# its environment -- committing/PR-opening happens in a separate step. The agent
# operates on already-merged, human-reviewed code (post-merge tier).
#
# Env in: PROMPT_FILE, MODEL (default databricks-claude-sonnet-4-6),
#         MAX_TURNS (default 40), AGENT_TIMEOUT_S (default 1500)
# Exit:   always 0 -- agent success is judged by the caller's independent
#         verification (re-running the test), never by the agent's own exit code.
set -uo pipefail

MODEL="${MODEL:-databricks-claude-sonnet-4-6}"
MAX_TURNS="${MAX_TURNS:-40}"
AGENT_TIMEOUT_S="${AGENT_TIMEOUT_S:-1500}"

if [[ ! -s "${PROMPT_FILE:-}" ]]; then
  echo "::error::PROMPT_FILE is unset or empty"; exit 0
fi

echo "Running claude (model=$MODEL, max-turns=$MAX_TURNS, timeout=${AGENT_TIMEOUT_S}s)"
timeout "$AGENT_TIMEOUT_S" claude -p "$(cat "$PROMPT_FILE")" \
  --model "$MODEL" \
  --max-turns "$MAX_TURNS" \
  --permission-mode bypassPermissions \
  --output-format text
rc=$?
if [[ $rc -eq 124 ]]; then
  echo "::warning::agent hit the ${AGENT_TIMEOUT_S}s wall-clock timeout"
elif [[ $rc -ne 0 ]]; then
  echo "::warning::claude exited $rc; verification step will decide the outcome"
fi
exit 0
