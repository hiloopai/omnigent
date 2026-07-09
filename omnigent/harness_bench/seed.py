"""Plain-data seed for the official SDK-wrap harnesses the bench ships with.

Each :class:`SdkSeed` names a harness plus the four concrete fields the
capability model does NOT carry: the default ``model`` id, the ``env_prefix`` its
wrap reads, the ``marker`` string a basic-turn probe echoes, and the ``cli_binary``
to skip-gate on. Descriptive/declared columns still come from
``harness_capabilities()`` (see :mod:`omnigent.harness_bench.manifest`).

This is the single source of truth for the SDK-wrap set. The e2e parametrize
matrix (``tests.e2e._harness_probes``) rebuilds its ``HARNESS_PROBES`` from these
seeds, wrapping ``model`` through its env-tunable test pools, so the bench and
e2e matrices cannot diverge. The ``model`` ids here are the deterministic
defaults (the same base ids the e2e pools are seeded with).
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class SdkSeed:
    """One SDK-wrap harness's bench-local concrete fields.

    :param harness: Registry harness id, e.g. ``"claude-sdk"``.
    :param model: Default gateway model id for a live probe.
    :param env_prefix: The env-var prefix the wrap reads, e.g.
        ``"HARNESS_CLAUDE_SDK_"``.
    :param marker: The literal string a basic-turn probe asks the model to echo.
    :param cli_binary: The CLI binary to skip-gate on, or ``None`` (pure-Python).
    """

    harness: str
    model: str
    env_prefix: str
    marker: str
    cli_binary: str | None = None


# The P0 SDK harnesses the sdk-inproc / full-server drivers cover. Add a new SDK
# wrap here and it flows into both the bench and the e2e parametrize matrix.
SDK_SEEDS: tuple[SdkSeed, ...] = (
    SdkSeed(
        harness="claude-sdk",
        model="databricks-claude-opus-4-6",
        env_prefix="HARNESS_CLAUDE_SDK_",
        marker="CLAUDE_E2E_OK",
        cli_binary="claude",
    ),
    SdkSeed(
        harness="codex",
        # OpenAI-style model exposed via the Databricks gateway; Codex's executor
        # speaks the OpenAI Responses API, lit up via HARNESS_CODEX_GATEWAY.
        model="databricks-gpt-5-4-mini",
        env_prefix="HARNESS_CODEX_",
        marker="CODEX_E2E_OK",
        cli_binary="codex",
    ),
    SdkSeed(
        harness="pi",
        # Pi speaks the OpenAI Responses API; the gateway exposes Claude through
        # that endpoint too.
        model="databricks-claude-sonnet-4-6",
        env_prefix="HARNESS_PI_",
        marker="PI_E2E_OK",
        cli_binary="pi",
    ),
    SdkSeed(
        harness="openai-agents",
        # Registry key is ``openai-agents`` (not ``-sdk``) to match the Omnigent
        # YAML ``executor.harness`` spelling. Pure-Python package; no CLI binary.
        model="databricks-gpt-5-4-mini",
        env_prefix="HARNESS_OPENAI_AGENTS_",
        marker="OPENAI_AGENTS_E2E_OK",
        cli_binary=None,
    ),
)


__all__ = ["SDK_SEEDS", "SdkSeed"]
