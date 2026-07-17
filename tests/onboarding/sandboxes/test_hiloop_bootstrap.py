"""Loopback bootstrap protocol for native Hiloop sandbox hosts."""

from __future__ import annotations

import json
import os
import socket
import ssl
import stat
import threading
from pathlib import Path

import pytest

from omnigent.onboarding.sandboxes.hiloop_bootstrap import (
    BOOTSTRAP_SCHEMA,
    BootstrapRequest,
    _write_provider_config,
    _write_server_trust,
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
        "server_ca_pem": "",
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
        server_ca_pem="",
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


def test_private_coordinator_ca_augments_system_roots_and_sets_runner_trust(
    tmp_path: Path,
) -> None:
    from cryptography import x509
    from cryptography.hazmat.primitives.serialization import Encoding

    from omnigent.inner.egress.ca import ensure_ca

    server_ca, _ = ensure_ca(cache_dir=tmp_path / "ca")
    payload = _payload()
    payload["server_ca_pem"] = server_ca.read_text()
    request = validate_request(payload)
    config_home = tmp_path / "omnigent"
    config_home.mkdir(mode=0o700)

    _write_server_trust(request, config_home)

    combined_path = config_home / "coordinator-server-trust.pem"
    custom_path = config_home / "coordinator-server-ca.pem"
    context = ssl.create_default_context(cafile=str(combined_path))
    combined_roots = set(context.get_ca_certs(binary_form=True))
    system_roots = set(ssl.create_default_context().get_ca_certs(binary_form=True))
    custom_der = x509.load_pem_x509_certificate(server_ca.read_bytes()).public_bytes(Encoding.DER)
    assert system_roots <= combined_roots
    assert custom_der in combined_roots
    assert custom_path.read_bytes() == server_ca.read_bytes()
    assert stat.S_IMODE(combined_path.stat().st_mode) == 0o600
    assert stat.S_IMODE(custom_path.stat().st_mode) == 0o600


def test_exec_host_exports_coordinator_trust_to_host_and_spawned_tools(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from omnigent.onboarding.sandboxes import hiloop_bootstrap

    payload = _payload()
    payload["server_ca_pem"] = "-----BEGIN CERTIFICATE-----\nproof-ca\n-----END CERTIFICATE-----\n"
    request = BootstrapRequest(
        token=payload["token"],
        host_id=payload["host_id"],
        host_name=payload["host_name"],
        server_url=payload["server_url"],
        workspace=payload["workspace"],
        model_gateway_url=payload["model_gateway_url"],
        model=payload["model"],
        server_ca_pem=payload["server_ca_pem"],
    )
    captured: dict[str, str] = {}
    monkeypatch.setattr(os, "chdir", lambda path: None)

    def execvpe(executable: str, argv: list[str], environment: dict[str, str]) -> None:
        del executable, argv
        captured.update(environment)
        raise RuntimeError("stop before exec")

    monkeypatch.setattr(os, "execvpe", execvpe)
    with pytest.raises(RuntimeError, match="stop before exec"):
        hiloop_bootstrap._exec_host(request)

    combined = "/tmp/.omnigent/coordinator-server-trust.pem"
    assert captured["SSL_CERT_FILE"] == combined
    assert captured["REQUESTS_CA_BUNDLE"] == combined
    assert captured["CURL_CA_BUNDLE"] == combined
    assert captured["GIT_SSL_CAINFO"] == combined
    assert captured["GRPC_DEFAULT_SSL_ROOTS_FILE_PATH"] == combined
    assert captured["NODE_EXTRA_CA_CERTS"] == "/tmp/.omnigent/coordinator-server-ca.pem"


@pytest.mark.parametrize(
    "value",
    [
        "not a certificate",
        "x" * ((64 * 1024) + 1),
        "\N{SNOWMAN}",
    ],
    ids=["garbage", "oversized", "non-ascii"],
)
def test_validate_request_rejects_invalid_coordinator_ca(value: str) -> None:
    payload = _payload()
    payload["server_ca_pem"] = value

    with pytest.raises(ValueError, match="coordinator server CA"):
        validate_request(payload)


def test_validate_request_rejects_certificate_bundle_with_private_key(
    tmp_path: Path,
) -> None:
    from omnigent.inner.egress.ca import ensure_ca

    server_ca, server_key = ensure_ca(cache_dir=tmp_path)
    payload = _payload()
    payload["server_ca_pem"] = server_ca.read_text() + server_key.read_text()

    with pytest.raises(ValueError, match="certificates only"):
        validate_request(payload)


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
