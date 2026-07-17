"""Native Hiloop sandbox launcher contracts."""

from __future__ import annotations

import json
import ssl
from pathlib import Path
from typing import Any

import httpx
import pytest
from cryptography import x509
from cryptography.hazmat.primitives.serialization import Encoding

from omnigent.inner.egress.ca import ensure_ca
from omnigent.onboarding.sandboxes.hiloop import (
    HiloopSandboxLauncher,
    _api_ssl_context,
    _HiloopError,
    _RestApi,
)

_IMAGE = (
    "registry.example.com/omnigent-host@"
    "sha256:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"
)
_WORKSPACE = (
    "branchfs:v1:11111111111111111111111111111111:"
    "2222222222222222222222222222222222222222222222222222222222222222"
)
_MODEL_GATEWAY_URL = "http://model-gateway.control.svc:8080/v1"
_MODEL = "gpt-5.6-terra"


class _FakeApi:
    def __init__(self) -> None:
        self.create_payload: dict[str, Any] | None = None
        self.deleted: list[str] = []
        self.resumed: list[str] = []

    def create_sandbox(self, payload: dict[str, Any]) -> str:
        self.create_payload = payload
        return "sandbox-native-1"

    def delete_sandbox(self, sandbox_id: str) -> None:
        self.deleted.append(sandbox_id)

    def resume_sandbox(self, sandbox_id: str) -> None:
        self.resumed.append(sandbox_id)

    def is_running(self, sandbox_id: str) -> bool:
        return sandbox_id == "sandbox-native-1"


class _FakeBootstrap:
    def __init__(self) -> None:
        self.calls: list[tuple[str, dict[str, str]]] = []

    def launch(self, sandbox_id: str, payload: dict[str, str]) -> None:
        self.calls.append((sandbox_id, payload))


def _launcher(api: _FakeApi, bootstrap: _FakeBootstrap) -> HiloopSandboxLauncher:
    return HiloopSandboxLauncher(
        api_url="https://api.hiloop.test",
        project_id="aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa",
        image=_IMAGE,
        workspace_revision=_WORKSPACE,
        model_gateway_url=_MODEL_GATEWAY_URL,
        model=_MODEL,
        api_key="hiloop-test-key",
        api=api,
        bootstrap=bootstrap,
    )


def test_provision_requests_only_new_cell_and_branchfs_contracts() -> None:
    api = _FakeApi()
    launcher = _launcher(api, _FakeBootstrap())

    assert launcher.provision("managed-native") == "sandbox-native-1"

    assert api.create_payload == {
        "project_id": "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa",
        "name": "managed-native",
        "image": {
            "oci": {
                "reference": "registry.example.com/omnigent-host",
                "digest": (
                    "sha256:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"
                ),
            }
        },
        "resources": {
            "cpus": 2,
            "memory_mb": "4096",
            "disk_mb": "20480",
            "architecture": "ARCHITECTURE_X86_64",
        },
        "requested_capabilities": [
            {
                "key": "core_lifecycle",
                "minimum_support": "native",
                "minimum_maturity": "experimental",
            },
            {
                "key": "exec_non_interactive",
                "minimum_support": "native",
                "minimum_maturity": "experimental",
            },
            {
                "key": "session_tcp",
                "minimum_support": "native",
                "minimum_maturity": "experimental",
            },
        ],
        "labels": {"managed-by": "omnigent"},
        "capture": {"policy": "CAPTURE_POLICY_DISABLED"},
        "egress": {"mode": "EGRESS_MODE_ALLOW", "domains": [], "cidrs": []},
        "lifecycle": {"lease_secs": "86400", "idle_timeout_secs": "86400"},
        "network_mode": "NETWORK_MODE_SANDBOX",
        "workspace": {"revision_ref": _WORKSPACE, "target_path": "/workspace"},
    }


def test_prepare_does_not_require_a_hiloop_cli_binary(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("PATH", "")
    launcher = HiloopSandboxLauncher(
        api_url="https://api.hiloop.test",
        project_id="aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa",
        image=_IMAGE,
        workspace_revision=_WORKSPACE,
        model_gateway_url=_MODEL_GATEWAY_URL,
        model=_MODEL,
        api_key="hiloop-test-key",
        api=_FakeApi(),
    )

    launcher.prepare()


def test_api_ca_augments_instead_of_replacing_system_trust(tmp_path: Path) -> None:
    api_ca, _ = ensure_ca(cache_dir=tmp_path)
    system_roots = set(ssl.create_default_context().get_ca_certs(binary_form=True))

    context = _api_ssl_context(str(api_ca))

    assert isinstance(context, ssl.SSLContext)
    combined_roots = set(context.get_ca_certs(binary_form=True))
    custom_der = x509.load_pem_x509_certificate(api_ca.read_bytes()).public_bytes(Encoding.DER)
    assert system_roots <= combined_roots
    assert custom_der in combined_roots


def test_api_ca_rejects_an_invalid_trust_bundle(tmp_path: Path) -> None:
    invalid = tmp_path / "invalid-api-ca.pem"
    invalid.write_text("not a certificate")

    with pytest.raises(_HiloopError, match="readable PEM trust bundle"):
        _api_ssl_context(str(invalid))


def test_api_ca_can_be_supplied_by_dedicated_environment_path(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    api_ca, _ = ensure_ca(cache_dir=tmp_path)
    monkeypatch.setenv("HILOOP_API_CA_CERT", str(api_ca))
    launcher = _launcher(_FakeApi(), _FakeBootstrap())

    launcher.prepare()

    assert launcher._resolved_api_ca() == str(api_ca)


def test_start_host_uses_proof_bound_session_bootstrap() -> None:
    bootstrap = _FakeBootstrap()
    launcher = _launcher(_FakeApi(), bootstrap)

    workspace = launcher.start_host(
        "sandbox-native-1",
        token="short-lived-host-token",
        host_id="host-1",
        host_name="managed-native",
        server_url="https://agents.hiloop.test",
    )

    assert workspace == "/workspace"
    assert bootstrap.calls == [
        (
            "sandbox-native-1",
            {
                "schema": "omnigent.hiloop-bootstrap/v3",
                "token": "short-lived-host-token",
                "host_id": "host-1",
                "host_name": "managed-native",
                "server_url": "https://agents.hiloop.test",
                "workspace": "/workspace",
                "model_gateway_url": _MODEL_GATEWAY_URL,
                "model": _MODEL,
                "server_ca_pem": "",
            },
        )
    ]


def test_start_host_delivers_bounded_coordinator_ca_over_proof_channel(
    tmp_path: Path,
) -> None:
    server_ca, _ = ensure_ca(cache_dir=tmp_path)
    bootstrap = _FakeBootstrap()
    launcher = HiloopSandboxLauncher(
        api_url="https://api.hiloop.test",
        project_id="aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa",
        image=_IMAGE,
        workspace_revision=_WORKSPACE,
        model_gateway_url=_MODEL_GATEWAY_URL,
        model=_MODEL,
        api_key="hiloop-test-key",
        server_ca=str(server_ca),
        api=_FakeApi(),
        bootstrap=bootstrap,
    )

    launcher.start_host(
        "sandbox-native-1",
        token="short-lived-host-token",
        host_id="host-1",
        host_name="managed-native",
        server_url="https://agents.hiloop.test",
    )

    assert bootstrap.calls[0][1]["server_ca_pem"] == server_ca.read_text()


@pytest.mark.parametrize("size", [0, (64 * 1024) + 1])
def test_coordinator_ca_file_is_strictly_bounded(tmp_path: Path, size: int) -> None:
    server_ca = tmp_path / "server-ca.pem"
    server_ca.write_bytes(b"x" * size)
    launcher = HiloopSandboxLauncher(
        api_url="https://api.hiloop.test",
        project_id="aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa",
        image=_IMAGE,
        workspace_revision=_WORKSPACE,
        model_gateway_url=_MODEL_GATEWAY_URL,
        model=_MODEL,
        api_key="hiloop-test-key",
        server_ca=str(server_ca),
        api=_FakeApi(),
        bootstrap=_FakeBootstrap(),
    )

    with pytest.raises(Exception, match="1 byte through 64 KiB"):
        launcher.prepare()


def test_start_host_rejects_clone_instead_of_bypassing_branchfs() -> None:
    launcher = _launcher(_FakeApi(), _FakeBootstrap())

    with pytest.raises(Exception, match="BranchFS seed"):
        launcher.start_host(
            "sandbox-native-1",
            token="token",
            host_id="host-1",
            host_name="managed-native",
            server_url="https://agents.hiloop.test",
            repo_url="https://github.com/acme/repo.git",
            repo_name="repo",
        )


@pytest.mark.parametrize(
    ("image", "workspace", "message"),
    [
        ("registry.example.com/host:latest", _WORKSPACE, "sha256"),
        (_IMAGE, "branchfs:v1:latest", "BranchFS"),
    ],
)
def test_immutable_image_and_workspace_are_mandatory(
    image: str, workspace: str, message: str
) -> None:
    launcher = HiloopSandboxLauncher(
        api_url="https://api.hiloop.test",
        project_id="aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa",
        image=image,
        workspace_revision=workspace,
        model_gateway_url=_MODEL_GATEWAY_URL,
        model=_MODEL,
        api_key="hiloop-test-key",
        api=_FakeApi(),
        bootstrap=_FakeBootstrap(),
    )

    with pytest.raises(Exception, match=message):
        launcher.prepare()


def test_terminate_deletes_the_logical_sandbox() -> None:
    api = _FakeApi()
    launcher = _launcher(api, _FakeBootstrap())

    launcher.terminate("sandbox-native-1")

    assert api.deleted == ["sandbox-native-1"]


def test_rest_create_uses_native_contract_and_polls_operation() -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if request.method == "POST":
            return httpx.Response(
                202,
                json={
                    "sandbox": {"id": "sandbox-native-1"},
                    "operation": {"id": "operation-create-1"},
                },
            )
        return httpx.Response(
            200,
            json={"operation": {"id": "operation-create-1", "state": "succeeded"}},
        )

    api = _RestApi(
        base_url="https://api.hiloop.test",
        api_key="secret-key",
        timeout_s=1,
        transport=httpx.MockTransport(handler),
    )
    try:
        assert api.create_sandbox({"project_id": "project-1"}) == "sandbox-native-1"
    finally:
        api.close()

    assert [(request.method, request.url.path) for request in requests] == [
        ("POST", "/v1/sandboxes"),
        ("GET", "/v1/operations/operation-create-1"),
    ]
    assert json.loads(requests[0].content) == {"project_id": "project-1"}
    assert requests[0].headers["authorization"] == "Bearer secret-key"
    assert requests[0].headers["idempotency-key"].startswith("omnigent-create-")


def test_rest_create_retries_an_ambiguous_transport_failure_with_the_same_key() -> None:
    create_keys: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "POST":
            create_keys.append(request.headers["idempotency-key"])
            if len(create_keys) == 1:
                raise httpx.ReadError("connection dropped", request=request)
            return httpx.Response(
                202,
                json={
                    "sandbox": {"id": "sandbox-native-1"},
                    "operation": {"id": "operation-create-1"},
                },
            )
        return httpx.Response(
            200,
            json={"operation": {"id": "operation-create-1", "state": "succeeded"}},
        )

    api = _RestApi(
        base_url="https://api.hiloop.test",
        api_key="secret-key",
        timeout_s=1,
        transport=httpx.MockTransport(handler),
    )
    try:
        assert api.create_sandbox({}) == "sandbox-native-1"
    finally:
        api.close()

    assert len(create_keys) == 2
    assert create_keys[0] == create_keys[1]


def test_rest_create_cleans_up_a_sandbox_with_a_malformed_operation() -> None:
    requests: list[tuple[str, str]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append((request.method, request.url.path))
        if request.method == "POST":
            return httpx.Response(
                202,
                json={"sandbox": {"id": "sandbox-orphan"}, "operation": {}},
            )
        if request.method == "DELETE":
            return httpx.Response(202, json={"operation": {"id": "operation-delete-1"}})
        return httpx.Response(
            200,
            json={"operation": {"id": "operation-delete-1", "state": "succeeded"}},
        )

    api = _RestApi(
        base_url="https://api.hiloop.test",
        api_key="secret-key",
        timeout_s=1,
        transport=httpx.MockTransport(handler),
    )
    try:
        with pytest.raises(_HiloopError, match="create operation id"):
            api.create_sandbox({})
    finally:
        api.close()

    assert requests == [
        ("POST", "/v1/sandboxes"),
        ("DELETE", "/v1/sandboxes/sandbox-orphan"),
        ("GET", "/v1/operations/operation-delete-1"),
    ]


def test_rest_create_preserves_the_original_failure_when_cleanup_fails() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "POST":
            return httpx.Response(
                202,
                json={
                    "sandbox": {"id": "sandbox-orphan"},
                    "operation": {"id": "operation-create-1"},
                },
            )
        if request.method == "GET":
            return httpx.Response(
                200,
                json={
                    "operation": {
                        "id": "operation-create-1",
                        "state": "failed",
                        "error": {"message": "capacity unavailable"},
                    }
                },
            )
        return httpx.Response(503, json={"error": "cleanup unavailable"})

    api = _RestApi(
        base_url="https://api.hiloop.test",
        api_key="secret-key",
        timeout_s=1,
        transport=httpx.MockTransport(handler),
    )
    try:
        with pytest.raises(_HiloopError, match="capacity unavailable"):
            api.create_sandbox({})
    finally:
        api.close()


def test_rest_resume_preserves_the_branchfs_workspace() -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if request.method == "POST":
            return httpx.Response(202, json={"operation": {"id": "operation-resume-1"}})
        return httpx.Response(
            200,
            json={"operation": {"id": "operation-resume-1", "state": "succeeded"}},
        )

    api = _RestApi(
        base_url="https://api.hiloop.test",
        api_key="secret-key",
        timeout_s=1,
        transport=httpx.MockTransport(handler),
    )
    try:
        api.resume_sandbox("sandbox-native-1")
    finally:
        api.close()

    assert [(request.method, request.url.path) for request in requests] == [
        ("POST", "/v1/sandboxes/sandbox-native-1:resume"),
        ("GET", "/v1/operations/operation-resume-1"),
    ]
    assert json.loads(requests[0].content) == {
        "id": "sandbox-native-1",
        "fresh_workspace": False,
    }
    assert requests[0].headers["idempotency-key"].startswith("omnigent-resume-")


def test_rest_ready_state_is_running_and_missing_sandbox_is_not() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("sandbox-ready"):
            return httpx.Response(
                200,
                json={"sandbox": {"id": "sandbox-ready", "observed_state": "ready"}},
            )
        return httpx.Response(404, json={"error": "not found"})

    api = _RestApi(
        base_url="https://api.hiloop.test",
        api_key="secret-key",
        timeout_s=1,
        transport=httpx.MockTransport(handler),
    )
    try:
        assert api.is_running("sandbox-ready") is True
        assert api.is_running("sandbox-gone") is False
    finally:
        api.close()
