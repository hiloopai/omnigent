"""Unit tests for the omni hermes CLI-side helpers + harness wiring (no server)."""

from __future__ import annotations

import click
import pytest

from omnigent import hermes_native as hn


def test_resolve_hermes_executable_found() -> None:
    resolved = hn.resolve_hermes_executable(
        env={}, which=lambda cmd: f"/usr/local/bin/{cmd}" if cmd == "hermes" else None
    )
    assert resolved == "/usr/local/bin/hermes"


def test_resolve_hermes_executable_honors_path_override() -> None:
    resolved = hn.resolve_hermes_executable(
        env={"OMNIGENT_HERMES_PATH": "/opt/hermes"},
        which=lambda cmd: cmd if cmd == "/opt/hermes" else None,
    )
    assert resolved == "/opt/hermes"


def test_resolve_hermes_executable_missing_raises_with_hint() -> None:
    with pytest.raises(click.ClickException) as exc:
        hn.resolve_hermes_executable(env={}, which=lambda _cmd: None)
    assert "hermes-agent.nousresearch.com" in str(exc.value)


def test_build_hermes_launch_argv() -> None:
    launch = hn.build_hermes_launch(
        ["--resume", "x"],
        env={},
        which=lambda cmd: f"/bin/{cmd}",
    )
    assert launch.executable == "/bin/hermes"
    assert launch.argv == ["/bin/hermes", "--resume", "x"]


def test_terminal_resource_id_stable() -> None:
    assert hn.hermes_terminal_resource_id() == hn.hermes_terminal_resource_id()


def test_harness_registry_has_hermes_native() -> None:
    from omnigent.runtime.harnesses import _HARNESS_MODULES

    assert _HARNESS_MODULES["hermes-native"] == "omnigent.inner.hermes_native_harness"


def test_alias_and_native_membership() -> None:
    from omnigent.harness_aliases import (
        NATIVE_HARNESSES,
        canonicalize_harness,
        is_native_harness,
    )

    assert canonicalize_harness("native-hermes") == "hermes-native"
    assert "hermes-native" in NATIVE_HARNESSES
    assert "native-hermes" in NATIVE_HARNESSES
    assert is_native_harness("hermes-native") is True
    assert is_native_harness("native-hermes") is True
    # The headless ``hermes`` harness is NOT a native CLI harness.
    assert is_native_harness("hermes") is False


def test_native_coding_agent_resolves() -> None:
    from omnigent._wrapper_labels import (
        HERMES_NATIVE_WRAPPER_VALUE,
        UI_MODE_LABEL_KEY,
        UI_MODE_TERMINAL_VALUE,
        WRAPPER_LABEL_KEY,
    )
    from omnigent.native_coding_agents import (
        HERMES_NATIVE_CODING_AGENT,
        native_coding_agent_for_harness,
    )

    agent = native_coding_agent_for_harness("native-hermes")
    assert agent is HERMES_NATIVE_CODING_AGENT
    assert agent is native_coding_agent_for_harness("hermes-native")
    assert agent.agent_name == "hermes-native-ui"
    assert agent.terminal_name == "hermes"
    assert agent.presentation_labels == {
        UI_MODE_LABEL_KEY: UI_MODE_TERMINAL_VALUE,
        WRAPPER_LABEL_KEY: HERMES_NATIVE_WRAPPER_VALUE,
    }


def test_create_app_builds() -> None:
    from omnigent.inner.hermes_native_harness import create_app

    assert create_app() is not None


def test_setup_hermes_native_home_preserves_config_and_layers_hook(tmp_path, monkeypatch) -> None:
    """The per-session HERMES_HOME copies full user config + layers the policy hook."""
    import json

    from omnigent import hermes_native_bridge as b

    # Fake ~/.hermes with a full config + a transcript store that must NOT be copied.
    fake_home = tmp_path / "user_home"
    hermes_dir = fake_home / ".hermes"
    hermes_dir.mkdir(parents=True)
    (hermes_dir / "config.yaml").write_text(
        "model: openrouter/some-model\ntools:\n  - shell\n  - file\n", encoding="utf-8"
    )
    (hermes_dir / "auth.json").write_text('{"k": "v"}', encoding="utf-8")
    (hermes_dir / "state.db").write_text("OLD TRANSCRIPT", encoding="utf-8")
    monkeypatch.setenv("HOME", str(fake_home))

    bridge_dir = tmp_path / "bridge"
    bridge_dir.mkdir()
    home = b.setup_hermes_native_home(
        bridge_dir,
        session_id="conv_x",
        server_url="http://127.0.0.1:6767",
        hook_script_path="/h.py",
    )

    assert home == b.hermes_native_home(bridge_dir)
    cfg = json.loads((home / "config.yaml").read_text())
    # Full user config preserved...
    assert cfg["model"] == "openrouter/some-model"
    assert cfg["tools"] == ["shell", "file"]
    # ...with the Omnigent policy hook layered on.
    assert cfg["hooks_auto_accept"] is True
    assert cfg["hooks"]["pre_tool_call"][0]["command"].endswith("omnigent-policy-hook.sh")
    assert cfg["hooks"]["pre_tool_call"][0]["timeout"] == 86400
    # auth.json carried over; the transcript store did NOT (fresh store per session).
    assert (home / "auth.json").is_file()
    assert not (home / "state.db").exists()
    # Wrapper exports server/session and execs the hook; allowlist pre-approves it.
    wrapper = (home / "omnigent-policy-hook.sh").read_text()
    assert "http://127.0.0.1:6767" in wrapper and "conv_x" in wrapper and "/h.py" in wrapper
    allow = json.loads((home / "shell-hooks-allowlist.json").read_text())
    assert allow["approvals"][0]["event"] == "pre_tool_call"
