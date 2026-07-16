"""Loopback bootstrap protocol for native Hiloop sandbox hosts."""

from __future__ import annotations

import json
import socket
import stat
import threading
from pathlib import Path

import pytest

from omnigent.onboarding.sandboxes.hiloop_bootstrap import (
    BOOTSTRAP_SCHEMA,
    BootstrapRequest,
    _write_provider_config,
    exchange,
    read_frame,
    validate_request,
    write_frame,
)


def _payload() -> dict[str, str]:
    return {
        "schema": BOOTSTRAP_SCHEMA,
        "token": "a-secure-one-time-managed-host-token",
        "host_id": "host-1",
        "host_name": "managed-native",
        "server_url": "https://agents.hiloop.test",
        "workspace": "/workspace/repo",
        "model_gateway_url": "http://model-gateway.control.svc:8080/v1",
        "model": "gpt-5.6-terra",
    }


def test_framed_exchange_never_needs_process_environment_delivery() -> None:
    client, server = socket.socketpair()
    observed: list[dict[str, str]] = []

    def serve() -> None:
        with server:
            observed.append(read_frame(server))
            write_frame(server, {"schema": BOOTSTRAP_SCHEMA, "status": "accepted"})

    thread = threading.Thread(target=serve)
    thread.start()
    with client:
        exchange(client, _payload())
    thread.join(timeout=1)

    assert observed == [_payload()]


def test_validate_request_returns_typed_boot_contract() -> None:
    assert validate_request(_payload()) == BootstrapRequest(
        token="a-secure-one-time-managed-host-token",
        host_id="host-1",
        host_name="managed-native",
        server_url="https://agents.hiloop.test",
        workspace="/workspace/repo",
        model_gateway_url="http://model-gateway.control.svc:8080/v1",
        model="gpt-5.6-terra",
    )


def test_provider_config_uses_only_projected_workload_identity(tmp_path: Path) -> None:
    request = validate_request(_payload())
    config_home = tmp_path / "omnigent"

    _write_provider_config(request, config_home)

    config_path = config_home / "config.yaml"
    config = json.loads(config_path.read_text())
    family = config["providers"]["hiloop"]["openai"]
    assert family == {
        "auth_command": "cat /var/run/secrets/hiloop/model-gateway/token",
        "base_url": "http://model-gateway.control.svc:8080/v1",
        "models": {"default": "gpt-5.6-terra"},
        "wire_api": "responses",
    }
    assert "api_key" not in config_path.read_text().casefold()
    assert stat.S_IMODE(config_home.stat().st_mode) == 0o700
    assert stat.S_IMODE(config_path.stat().st_mode) == 0o600


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("server_url", "http://agents.hiloop.test"),
        ("workspace", "/tmp/not-branchfs"),
        ("workspace", "/workspace/../etc"),
        ("token", "short"),
        ("host_id", "bad host"),
        ("model_gateway_url", "http://attacker.example/v1"),
        ("model_gateway_url", "https://gateway.example/not-responses"),
        ("model", "bad model"),
    ],
)
def test_validate_request_fails_closed(field: str, value: str) -> None:
    payload = _payload()
    payload[field] = value

    with pytest.raises(ValueError):
        validate_request(payload)
