"""
Shared parametrize probes for e2e tests that should run against
every wrapped harness.

Each :class:`HarnessProbe` describes one harness + model + marker
tuple. e2e tests import :data:`HARNESS_PROBES` and use it as the
``parametrize`` argvalues so a single test ID per harness shows
up (``[claude-sdk]``, ``[codex]``, etc.) and a per-harness failure
is visible without re-reading the parametrize tuple.

Add a new entry here when a new harness wrap lands in
:data:`omnigent.runtime.harnesses._HARNESS_MODULES`. Every
parametrized e2e test then picks up the new harness without
per-file edits.
"""

from __future__ import annotations

from dataclasses import dataclass

import pytest

from omnigent.harness_bench.cli_probe import cli_unavailable_reason
from omnigent.harness_bench.seed import SDK_SEEDS
from tests._model_pools import resolve_model

__all__ = [
    "HARNESS_HARNESS_MODELS",
    "HARNESS_IDS",
    "HARNESS_PROBES",
    "HarnessProbe",
    "cli_unavailable_reason",
    "skip_if_harness_cli_missing",
]


@dataclass(frozen=True)
class HarnessProbe:
    """One row of the harness parametrize matrix.

    :param harness: The harness name as registered in
        ``_HARNESS_MODULES`` and used by
        :meth:`HarnessProcessManager.get_client`, e.g.
        ``"claude-sdk"``.
    :param model: The model identifier the inner executor
        receives via the harness's ``HARNESS_<HARNESS>_MODEL``
        env var (or, for AP-level tests, the model field in
        the agent spec). Must be a real model the Databricks
        gateway exposes for the user's profile.
    :param env_prefix: The env-var prefix the wrap reads
        (e.g. ``HARNESS_CLAUDE_SDK_``). The model-routing env
        vars are derived as ``{prefix}MODEL``,
        ``{prefix}GATEWAY``, ``{prefix}DATABRICKS_PROFILE``.
        Used by the harness-wrap smoke test that talks
        directly to ``HarnessProcessManager``.
    :param marker: The exact literal string the LLM is asked
        to echo back in marker-based tests. Per-harness
        markers keep concurrent runs of different harnesses
        from cross-matching against each other in the
        assertion path.
    :param cli_binary: Name of the CLI binary the inner
        executor requires on PATH (e.g. ``"claude"``,
        ``"codex"``, ``"pi"``). ``None`` when no binary check
        is meaningful (the inner executor's failure path
        surfaces a clear error of its own). Tests can call
        :func:`skip_if_harness_cli_missing` to skip the
        harness's parametrize row when its CLI isn't
        installed locally.
    """

    harness: str
    model: str
    env_prefix: str
    marker: str
    cli_binary: str | None = None


# Probes for every wrapped harness. Add a new entry when
# ``_HARNESS_MODULES`` gains a new key (currently 4b: claude-sdk,
# 4c: codex, 4d: pi; 4e is pending).
#
# Probe models resolve at import time with a stable per-harness key,
# so the OMNIGENT_TEST_MODEL_* env vars can rebalance a harness's
# rows without code edits; pools stay within the API style each
# harness supports.
# Built from :data:`omnigent.harness_bench.seed.SDK_SEEDS` (the single source of
# truth the bench also uses) so the e2e and bench matrices never diverge. The
# only e2e-specific layer is routing each seed's default ``model`` through
# ``resolve_model`` (the env-tunable test pools), which lets ``OMNIGENT_TEST_MODEL_*``
# rebalance a harness's rows without editing the seed table.
HARNESS_PROBES: list[HarnessProbe] = [
    HarnessProbe(
        harness=seed.harness,
        model=resolve_model(seed.model, key=f"probe:{seed.harness}"),
        env_prefix=seed.env_prefix,
        marker=seed.marker,
        cli_binary=seed.cli_binary,
    )
    for seed in SDK_SEEDS
]


# Convenience: list of just (harness, model) tuples for tests
# that don't need the env-var prefix or marker. Pass to
# ``pytest.mark.parametrize("harness,model", HARNESS_HARNESS_MODELS)``.
HARNESS_HARNESS_MODELS: list[tuple[str, str]] = [(p.harness, p.model) for p in HARNESS_PROBES]


# IDs for parametrize calls — keeps test names like
# ``test_foo[claude-sdk]`` / ``test_foo[codex]`` / ``test_foo[pi]``.
HARNESS_IDS: list[str] = [p.harness for p in HARNESS_PROBES]


# ── CLI availability gate ───────────────────────────────────


# Look up table from harness name to its required CLI binary.
# Built once at import time from ``HARNESS_PROBES`` so the
# helper below doesn't reconstruct it on every call.
_CLI_BINARY_BY_HARNESS: dict[str, str | None] = {p.harness: p.cli_binary for p in HARNESS_PROBES}

# ``cli_unavailable_reason`` now lives in the shipped package
# (:mod:`omnigent.harness_bench.cli_probe`) and is imported at the top; the e2e
# gate below reuses it so there is one copy.


def skip_if_harness_cli_missing(harness: str) -> None:
    """
    Skip the current pytest test when the harness's CLI binary
    isn't installed and runnable.

    Call from the top of a parametrized test body when the test
    drives a real harness subprocess and the CLI is required for
    the inner executor to start. Local dev environments often
    have only some of the harnesses installed; this helper keeps
    missing or broken binaries from surfacing as confusing
    executor errors in the middle of a test.

    No-op for harnesses with ``cli_binary=None`` and for unknown
    harnesses (so an old test that drops in a new harness name
    without updating this table doesn't break unexpectedly).

    :param harness: The harness name from the parametrize row,
        e.g. ``"pi"``. Looked up in :data:`_CLI_BINARY_BY_HARNESS`.
    """
    binary = _CLI_BINARY_BY_HARNESS.get(harness)
    if binary is None:
        return
    reason = cli_unavailable_reason(binary)
    if reason is not None:
        pytest.skip(
            f"{harness!r} harness requires a runnable {binary!r} CLI; "
            f"{reason}. Install/fix it to run this row. Other harness rows continue."
        )
