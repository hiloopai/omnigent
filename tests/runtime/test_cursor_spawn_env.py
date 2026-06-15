"""
Tests for ``_build_cursor_spawn_env`` in ``omnigent/runtime/workflow.py``.

The spawn-env builder maps ``spec`` fields to the ``HARNESS_CURSOR_*`` env
vars the cursor harness wrap reads at first-turn time. Unlike the
gateway-backed builders, cursor has NO Databricks-gateway path: only an
explicit ``api_key`` auth maps to ``HARNESS_CURSOR_API_KEY``, and a
``DatabricksAuth`` profile is deliberately ignored (cursor-agent talks only
to Cursor's own backend). Mirrors ``test_openai_agents_sdk_spawn_env.py``.

This is a unit test — no subprocess spawn. End-to-end verification of the
spawn-env → wrap → executor path lives in the harness e2e tests.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from omnigent.runtime.workflow import _build_cursor_spawn_env
from omnigent.spec.types import (
    AgentSpec,
    ApiKeyAuth,
    DatabricksAuth,
    ExecutorSpec,
    LLMConfig,
)


@pytest.fixture(autouse=True)
def _isolate_global_config(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """Point OMNIGENT_CONFIG_HOME at an empty temp dir so the developer's real
    ``~/.omnigent/config.yaml`` can't leak into these tests."""
    monkeypatch.setenv("OMNIGENT_CONFIG_HOME", str(tmp_path))


def _make_spec(
    *,
    model: str | None = "gpt-5",
    name: str = "test-cursor",
    auth: ApiKeyAuth | DatabricksAuth | None = None,
) -> AgentSpec:
    """Build a minimal cursor :class:`AgentSpec` for the spawn-env tests."""
    config: dict[str, object] = {"harness": "cursor"}
    if model is not None:
        config["model"] = model
    return AgentSpec(
        spec_version=1,
        name=name,
        instructions="You are a test agent.",
        executor=ExecutorSpec(type="omnigent", config=config, model=model, auth=auth),
        llm=LLMConfig(model=model) if model is not None else None,
    )


def test_model_threads_into_env_var() -> None:
    """``executor.model`` is encoded into ``HARNESS_CURSOR_MODEL``."""
    env = _build_cursor_spawn_env(_make_spec(model="gpt-5"))
    assert env["HARNESS_CURSOR_MODEL"] == "gpt-5"


def test_no_model_produces_no_model_env_var() -> None:
    """A spec with no model omits ``HARNESS_CURSOR_MODEL`` (cursor's default applies)."""
    env = _build_cursor_spawn_env(_make_spec(model=None))
    assert "HARNESS_CURSOR_MODEL" not in env


def test_api_key_auth_sets_api_key_env_var() -> None:
    """``executor.auth: {type: api_key, ...}`` sets ``HARNESS_CURSOR_API_KEY``."""
    env = _build_cursor_spawn_env(_make_spec(auth=ApiKeyAuth(api_key="cur_test_123")))
    assert env["HARNESS_CURSOR_API_KEY"] == "cur_test_123"


def test_databricks_auth_does_not_set_api_key() -> None:
    """A ``DatabricksAuth`` profile has no cursor equivalent and is ignored.

    Failure means a Databricks profile is mis-forwarded as a Cursor API key —
    cursor-agent has no gateway path, so the only correct behaviour is to leave
    auth to an inherited ``CURSOR_API_KEY`` / ``cursor-agent login``.
    """
    env = _build_cursor_spawn_env(_make_spec(auth=DatabricksAuth(profile="oss")))
    assert "HARNESS_CURSOR_API_KEY" not in env


def test_no_auth_omits_api_key_env_var() -> None:
    """With no spec auth, no ``HARNESS_CURSOR_API_KEY`` is written."""
    env = _build_cursor_spawn_env(_make_spec(auth=None))
    assert "HARNESS_CURSOR_API_KEY" not in env


def test_skills_filter_always_set() -> None:
    """``HARNESS_CURSOR_SKILLS_FILTER`` is always written so the wrap never
    falls back to ``"all"`` and overrides an explicit ``skills: none``."""
    env = _build_cursor_spawn_env(_make_spec())
    assert "HARNESS_CURSOR_SKILLS_FILTER" in env


def test_name_threads_into_agent_name_env_var() -> None:
    """``spec.name`` is forwarded as ``HARNESS_CURSOR_AGENT_NAME``."""
    env = _build_cursor_spawn_env(_make_spec(name="polly"))
    assert env["HARNESS_CURSOR_AGENT_NAME"] == "polly"


def test_workdir_threads_into_bundle_dir_env_var(tmp_path: Path) -> None:
    """A bundle ``workdir`` is forwarded as ``HARNESS_CURSOR_BUNDLE_DIR``."""
    env = _build_cursor_spawn_env(_make_spec(), workdir=tmp_path)
    assert env["HARNESS_CURSOR_BUNDLE_DIR"] == str(tmp_path)


def test_no_workdir_omits_bundle_dir_env_var() -> None:
    """No ``workdir`` omits ``HARNESS_CURSOR_BUNDLE_DIR``."""
    env = _build_cursor_spawn_env(_make_spec())
    assert "HARNESS_CURSOR_BUNDLE_DIR" not in env
