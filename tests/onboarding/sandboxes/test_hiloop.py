"""Native Hiloop sandbox launcher contracts."""

from __future__ import annotations

import json
from typing import Any

import httpx
import pytest

from omnigent.onboarding.sandboxes.hiloop import (
    HiloopSandboxLauncher,
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
        api_key="hiloop-test-key",
        api=_FakeApi(),
    )

    launcher.prepare()


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
                "schema": "omnigent.hiloop-bootstrap/v1",
                "token": "short-lived-host-token",
                "host_id": "host-1",
                "host_name": "managed-native",
                "server_url": "https://agents.hiloop.test",
                "workspace": "/workspace",
            },
        )
    ]


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
