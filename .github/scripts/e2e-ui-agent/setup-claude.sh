#!/usr/bin/env bash
# Configure claude-code (`claude -p`) to authenticate to the Databricks gateway's
# Anthropic-compatible endpoint, mirroring omnigent's claude-sdk executor
# (omnigent/inner/claude_sdk_executor.py:736 -- <host>/ai-gateway/anthropic, with
# the bearer = LLM_API_KEY). Writes the env to $GITHUB_ENV so later steps inherit
# it. Verified end-to-end by the Part 2 spike.
#
# Shared by e2e-ui-autofix.yml and e2e-ui-backfill.yml.
#
# Env in: GATEWAY_BASE_URL, LLM_API_KEY
set -euo pipefail

host="${GATEWAY_BASE_URL%/serving-endpoints}"
{
  echo "ANTHROPIC_BASE_URL=$host/ai-gateway/anthropic"
  echo "ANTHROPIC_AUTH_TOKEN=$LLM_API_KEY"
  # Matches the executor's gateway settings; avoids beta headers the gateway
  # may not accept.
  echo "CLAUDE_CODE_DISABLE_EXPERIMENTAL_BETAS=1"
} >> "$GITHUB_ENV"
echo "Configured claude -> $host/ai-gateway/anthropic"
