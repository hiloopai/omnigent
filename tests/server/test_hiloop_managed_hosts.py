"""Server configuration for native Hiloop managed hosts."""

from __future__ import annotations

import pytest

from omnigent.onboarding.sandboxes.hiloop import HiloopSandboxLauncher
from omnigent.server.managed_hosts import parse_sandbox_config


def _config() -> dict[str, object]:
    return {
        "provider": "hiloop",
        "server_url": "https://agents.hiloop.test",
        "hiloop": {
            "api_url": "https://api.hiloop.test",
            "project_id": "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa",
            "image": (
                "registry.example.com/omnigent-host@"
                "sha256:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"
            ),
            "workspace_revision": (
                "branchfs:v1:11111111111111111111111111111111:"
                "2222222222222222222222222222222222222222222222222222222222222222"
            ),
            "resources": {"cpus": 4, "memory_mb": 8192, "disk_mb": 32768},
            "bootstrap_port": 17891,
        },
    }


def test_parse_native_hiloop_config() -> None:
    config = parse_sandbox_config(_config())

    assert config is not None
    assert config.provider == "hiloop"
    assert config.managed_launch_supported is True
    launcher = config.launcher_factory()
    assert isinstance(launcher, HiloopSandboxLauncher)
    assert launcher._cpus == 4
    assert launcher._workspace_path == "/workspace"


@pytest.mark.parametrize(
    "obsolete",
    ["capture", "secrets", "runtime_profile", "cli_path", "workspace_path"],
)
def test_old_hiloop_provider_contract_is_rejected(obsolete: str) -> None:
    raw = _config()
    hiloop = raw["hiloop"]
    assert isinstance(hiloop, dict)
    hiloop[obsolete] = True

    with pytest.raises(ValueError, match=obsolete):
        parse_sandbox_config(raw)


@pytest.mark.parametrize(
    ("key", "value", "message"),
    [
        ("project_id", "not-a-uuid", "project_id"),
        ("api_url", "https://api.hiloop.test/prefix", "must not contain a path"),
        (
            "workspace_revision",
            "branchfs:v1:00000000000000000000000000000000:"
            "2222222222222222222222222222222222222222222222222222222222222222",
            "BranchFS",
        ),
        ("lease_secs", 59, "lifecycle"),
        ("bootstrap_port", 65_536, "bootstrap port"),
    ],
)
def test_invalid_hiloop_contract_is_rejected_during_config_parse(
    key: str, value: object, message: str
) -> None:
    raw = _config()
    hiloop = raw["hiloop"]
    assert isinstance(hiloop, dict)
    hiloop[key] = value

    with pytest.raises(ValueError, match=message):
        parse_sandbox_config(raw)
