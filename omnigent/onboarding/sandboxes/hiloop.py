"""Managed Omnigent hosts on the Hiloop cell and BranchFS architecture."""

from __future__ import annotations

import os
import re
import time
import uuid
from collections.abc import Mapping
from contextlib import suppress
from math import isfinite
from pathlib import Path
from typing import Any, ClassVar, Protocol
from urllib.parse import quote, urlsplit

import click
import httpx

from omnigent.onboarding.sandboxes.base import (
    RemoteCommandResult,
    SandboxCapabilityError,
    SandboxLauncher,
)
from omnigent.onboarding.sandboxes.hiloop_bootstrap import BOOTSTRAP_SCHEMA, DEFAULT_PORT
from omnigent.onboarding.sandboxes.hiloop_session import _SessionBootstrap

API_URL_ENV_VAR = "HILOOP_API_URL"
API_KEY_ENV_VAR = "HILOOP_API_KEY"
GATEWAY_CA_ENV_VAR = "HILOOP_SESSION_GATEWAY_CA_CERT"

_IMAGE = re.compile(r"(?P<reference>[^@\s]+)@(?P<digest>sha256:[0-9a-f]{64})")
_BRANCHFS = re.compile(r"branchfs:v1:(?P<repository>[0-9a-f]{32}):(?P<change>[0-9a-f]{64})")
_WORKSPACE_PATH = "/workspace"
_LOOPBACK_HOSTS = frozenset({"localhost", "127.0.0.1", "::1"})
_TERMINAL_OPERATION_STATES = frozenset({"succeeded", "failed", "cancelled"})
_RETRYABLE_HTTP_STATUSES = frozenset({429, 500, 502, 503, 504})
_REQUEST_ATTEMPTS = 3


class _HiloopError(RuntimeError):
    def __init__(self, message: str, *, status_code: int | None = None) -> None:
        super().__init__(message)
        self.status_code = status_code


class _Api(Protocol):
    def create_sandbox(self, payload: dict[str, Any]) -> str: ...

    def delete_sandbox(self, sandbox_id: str) -> None: ...

    def resume_sandbox(self, sandbox_id: str) -> None: ...

    def is_running(self, sandbox_id: str) -> bool: ...


class _Bootstrap(Protocol):
    def launch(self, sandbox_id: str, payload: dict[str, str]) -> None: ...


class _RestApi:
    def __init__(
        self,
        *,
        base_url: str,
        api_key: str,
        timeout_s: float,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self._api_key = api_key
        self._operation_timeout_s = timeout_s
        self._client = httpx.Client(timeout=min(timeout_s, 30.0), transport=transport)

    def close(self) -> None:
        self._client.close()

    def create_sandbox(self, payload: dict[str, Any]) -> str:
        response = self._json(
            "POST",
            "/v1/sandboxes",
            json=payload,
            headers={"idempotency-key": f"omnigent-create-{uuid.uuid4()}"},
        )
        sandbox = _mapping(response.get("sandbox"), "create response sandbox")
        sandbox_id = _string(sandbox.get("id"), "created sandbox id")
        try:
            operation = _mapping(response.get("operation"), "create response operation")
            self._wait_operation(_string(operation.get("id"), "create operation id"))
        except _HiloopError:
            with suppress(_HiloopError):
                self.delete_sandbox(sandbox_id)
            raise
        return sandbox_id

    def delete_sandbox(self, sandbox_id: str) -> None:
        try:
            response = self._json("DELETE", f"/v1/sandboxes/{_component(sandbox_id)}")
        except _HiloopError as exc:
            if exc.status_code == 404:
                return
            raise
        operation = _mapping(response.get("operation"), "delete response operation")
        self._wait_operation(_string(operation.get("id"), "delete operation id"))

    def resume_sandbox(self, sandbox_id: str) -> None:
        response = self._json(
            "POST",
            f"/v1/sandboxes/{_component(sandbox_id)}:resume",
            json={"id": sandbox_id, "fresh_workspace": False},
            headers={"idempotency-key": f"omnigent-resume-{uuid.uuid4()}"},
        )
        operation = _mapping(response.get("operation"), "resume response operation")
        self._wait_operation(_string(operation.get("id"), "resume operation id"))

    def is_running(self, sandbox_id: str) -> bool:
        try:
            response = self._json("GET", f"/v1/sandboxes/{_component(sandbox_id)}")
        except _HiloopError as exc:
            if exc.status_code == 404:
                return False
            raise
        sandbox = _mapping(response.get("sandbox"), "sandbox response")
        state = _string(sandbox.get("observed_state"), "sandbox observed state")
        return state.casefold() in {"ready", "running"}

    def _wait_operation(self, operation_id: str) -> Mapping[str, Any]:
        deadline = time.monotonic() + self._operation_timeout_s
        while True:
            response = self._json("GET", f"/v1/operations/{_component(operation_id)}")
            operation = _mapping(response.get("operation"), "operation response")
            state = _string(operation.get("state"), "operation state").casefold()
            if state in _TERMINAL_OPERATION_STATES:
                if state == "succeeded":
                    return operation
                error = operation.get("error")
                detail = "operation failed"
                if isinstance(error, Mapping):
                    detail = str(error.get("message") or error.get("code") or detail)
                raise _HiloopError(f"Hiloop operation {operation_id} did not succeed: {detail}")
            if time.monotonic() >= deadline:
                raise _HiloopError(f"Hiloop operation {operation_id} timed out")
            time.sleep(0.5)

    def _json(self, method: str, endpoint: str, **kwargs: Any) -> dict[str, Any]:
        headers = {"Authorization": f"Bearer {self._api_key}"}
        headers.update(kwargs.pop("headers", {}) or {})
        retryable = method.upper() in {"GET", "DELETE"} or any(
            key.casefold() == "idempotency-key" for key in headers
        )
        for attempt in range(_REQUEST_ATTEMPTS):
            try:
                response = self._client.request(
                    method,
                    self._base_url + endpoint,
                    headers=headers,
                    follow_redirects=False,
                    **kwargs,
                )
            except httpx.TransportError as exc:
                if not retryable or attempt == _REQUEST_ATTEMPTS - 1:
                    raise _HiloopError(f"Hiloop {method} {endpoint} failed") from exc
                time.sleep(0.1 * 2**attempt)
                continue
            if (
                response.status_code in _RETRYABLE_HTTP_STATUSES
                and retryable
                and attempt < _REQUEST_ATTEMPTS - 1
            ):
                response.close()
                time.sleep(0.1 * 2**attempt)
                continue
            break
        else:  # pragma: no cover - the bounded loop always returns or raises
            raise AssertionError("unreachable Hiloop request retry state")
        if response.is_redirect:
            raise _HiloopError(f"Hiloop {method} {endpoint} refused a redirect")
        if response.status_code >= 400:
            raise _HiloopError(
                f"Hiloop {method} {endpoint} failed with HTTP {response.status_code}",
                status_code=response.status_code,
            )
        try:
            decoded = response.json()
        except ValueError as exc:
            raise _HiloopError(f"Hiloop {method} {endpoint} returned invalid JSON") from exc
        if not isinstance(decoded, dict):
            raise _HiloopError(f"Hiloop {method} {endpoint} returned a non-object")
        return decoded


class HiloopSandboxLauncher(SandboxLauncher):
    """Create one Omnigent host per fenced Hiloop cell sandbox."""

    provider: ClassVar[str] = "hiloop"
    supports_cli_bootstrap: ClassVar[bool] = False
    can_resume: ClassVar[bool] = True

    def __init__(
        self,
        *,
        api_url: str | None = None,
        project_id: str | None = None,
        image: str | None = None,
        workspace_revision: str | None = None,
        cpus: int = 2,
        memory_mb: int = 4096,
        disk_mb: int = 20_480,
        lease_secs: int = 86_400,
        idle_timeout_secs: int = 86_400,
        api_key: str | None = None,
        bootstrap_port: int = DEFAULT_PORT,
        gateway_ca: str | None = None,
        expected_gateway_authority: str | None = None,
        operation_timeout_s: float = 900.0,
        api: _Api | None = None,
        bootstrap: _Bootstrap | None = None,
    ) -> None:
        self._api_url = api_url
        self._project_id = project_id
        self._image = image
        self._workspace_revision = workspace_revision
        self._workspace_path = _WORKSPACE_PATH
        self._cpus = cpus
        self._memory_mb = memory_mb
        self._disk_mb = disk_mb
        self._lease_secs = lease_secs
        self._idle_timeout_secs = idle_timeout_secs
        self._api_key = api_key
        self._bootstrap_port = bootstrap_port
        self._gateway_ca = gateway_ca
        self._expected_gateway_authority = expected_gateway_authority
        self._operation_timeout_s = operation_timeout_s
        self._api_override = api
        self._bootstrap_override = bootstrap
        self._resolved_api: _RestApi | None = None
        self._resolved_bootstrap: _Bootstrap | None = None

    def prepare(self) -> None:
        self._validated()
        self._resolved_api_url()
        self._resolved_project_id()
        self._resolved_key()
        if self._bootstrap_override is None:
            gateway_ca = self._resolved_gateway_ca()
            if gateway_ca and not Path(gateway_ca).is_file():
                raise click.ClickException("Hiloop session gateway CA file does not exist")

    def validate_configuration(self) -> None:
        """Validate static launcher settings without touching credentials or tooling."""
        self._validated()
        self._resolved_project_id()
        if self._api_url is not None:
            self._resolved_api_url()

    def provision(self, name: str) -> str:
        image_reference, image_digest = self._validated()
        payload: dict[str, Any] = {
            "project_id": self._resolved_project_id(),
            "name": name,
            "image": {"oci": {"reference": image_reference, "digest": image_digest}},
            "resources": {
                "cpus": self._cpus,
                "memory_mb": str(self._memory_mb),
                "disk_mb": str(self._disk_mb),
                "architecture": "ARCHITECTURE_X86_64",
            },
            "requested_capabilities": [
                _capability("core_lifecycle"),
                _capability("exec_non_interactive"),
                _capability("session_tcp"),
            ],
            "labels": {"managed-by": "omnigent"},
            "capture": {"policy": "CAPTURE_POLICY_DISABLED"},
            "egress": {"mode": "EGRESS_MODE_ALLOW", "domains": [], "cidrs": []},
            "lifecycle": {
                "lease_secs": str(self._lease_secs),
                "idle_timeout_secs": str(self._idle_timeout_secs),
            },
            "network_mode": "NETWORK_MODE_SANDBOX",
            "workspace": {
                "revision_ref": self._workspace_revision,
                "target_path": self._workspace_path,
            },
        }
        try:
            return self._api().create_sandbox(payload)
        except _HiloopError as exc:
            raise click.ClickException(f"Hiloop sandbox creation failed: {exc}") from exc
        finally:
            self._close_api()

    def start_host(
        self,
        sandbox_id: str,
        *,
        token: str,
        host_id: str,
        host_name: str,
        server_url: str,
        repo_url: str | None = None,
        repo_branch: str | None = None,
        repo_name: str | None = None,
        on_stage: Any = None,
    ) -> str:
        del repo_branch, repo_name
        if repo_url is not None:
            raise click.ClickException(
                "Hiloop managed sessions require a BranchFS seed; cloning inside the sandbox "
                "would bypass the versioned workspace contract"
            )
        _secure_url(server_url, "Omnigent server URL")
        if on_stage is not None:
            on_stage("starting")
        payload = {
            "schema": BOOTSTRAP_SCHEMA,
            "token": token,
            "host_id": host_id,
            "host_name": host_name,
            "server_url": server_url.rstrip("/"),
            "workspace": self._workspace_path,
        }
        try:
            self._bootstrap().launch(sandbox_id, payload)
        except (OSError, RuntimeError, _HiloopError) as exc:
            raise click.ClickException(
                f"Hiloop session bootstrap failed for sandbox '{sandbox_id}'"
            ) from exc
        return self._workspace_path

    def run(self, sandbox_id: str, command: str, *, check: bool = True) -> RemoteCommandResult:
        del sandbox_id, command, check
        raise SandboxCapabilityError(
            "The native Hiloop managed launcher does not expose arbitrary exec; "
            "host startup uses a proof-bound session_tcp grant."
        )

    def terminate(self, sandbox_id: str) -> None:
        try:
            self._api().delete_sandbox(sandbox_id)
        except _HiloopError as exc:
            raise click.ClickException(f"Hiloop sandbox deletion failed: {exc}") from exc
        finally:
            self._close_api()

    def resume(self, sandbox_id: str) -> None:
        try:
            self._api().resume_sandbox(sandbox_id)
        except _HiloopError as exc:
            raise click.ClickException(f"Hiloop sandbox resume failed: {exc}") from exc
        finally:
            self._close_api()

    def is_running(self, sandbox_id: str) -> bool | None:
        try:
            return self._api().is_running(sandbox_id)
        except (_HiloopError, click.ClickException):
            return None
        finally:
            self._close_api()

    def _validated(self) -> tuple[str, str]:
        image = self._image or ""
        match = _IMAGE.fullmatch(image)
        if match is None:
            raise click.ClickException("Hiloop host image must be pinned by sha256 digest")
        workspace = self._workspace_revision or ""
        workspace_match = _BRANCHFS.fullmatch(workspace)
        if workspace_match is None or any(
            set(workspace_match.group(group)) == {"0"} for group in ("repository", "change")
        ):
            raise click.ClickException("Hiloop requires an exact immutable BranchFS revision")
        for name, value in (
            ("cpus", self._cpus),
            ("memory_mb", self._memory_mb),
            ("disk_mb", self._disk_mb),
            ("lease_secs", self._lease_secs),
            ("idle_timeout_secs", self._idle_timeout_secs),
            ("bootstrap_port", self._bootstrap_port),
        ):
            if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
                raise click.ClickException(f"Hiloop {name} must be a positive integer")
        if not 60 <= self._lease_secs <= 86_400 or not 60 <= self._idle_timeout_secs <= 86_400:
            raise click.ClickException("Hiloop lifecycle timeouts must be between 60 and 86400")
        if not 1 <= self._bootstrap_port <= 65_535:
            raise click.ClickException("Hiloop bootstrap port is invalid")
        if not isfinite(self._operation_timeout_s) or self._operation_timeout_s <= 0:
            raise click.ClickException("Hiloop operation timeout must be positive and finite")
        return match.group("reference"), match.group("digest")

    def _resolved_api_url(self) -> str:
        value = (self._api_url or os.environ.get(API_URL_ENV_VAR, "")).strip()
        return _secure_url(value, "Hiloop API URL", origin_only=True)

    def _resolved_project_id(self) -> str:
        value = (self._project_id or "").strip()
        try:
            uuid.UUID(value)
        except ValueError as exc:
            raise click.ClickException("Hiloop project_id must be a UUID") from exc
        return value

    def _resolved_key(self) -> str:
        value = (self._api_key or os.environ.get(API_KEY_ENV_VAR, "")).strip()
        if not value:
            raise click.ClickException(f"Set {API_KEY_ENV_VAR} for the Hiloop launcher")
        return value

    def _resolved_gateway_ca(self) -> str | None:
        value = (self._gateway_ca or os.environ.get(GATEWAY_CA_ENV_VAR, "")).strip()
        return value or None

    def _api(self) -> _Api:
        if self._api_override is not None:
            return self._api_override
        if self._resolved_api is None:
            self._resolved_api = _RestApi(
                base_url=self._resolved_api_url(),
                api_key=self._resolved_key(),
                timeout_s=self._operation_timeout_s,
            )
        return self._resolved_api

    def _close_api(self) -> None:
        api = self._resolved_api
        self._resolved_api = None
        if api is not None:
            api.close()

    def _bootstrap(self) -> _Bootstrap:
        if self._bootstrap_override is not None:
            return self._bootstrap_override
        if self._resolved_bootstrap is None:
            self._resolved_bootstrap = _SessionBootstrap(
                api_url=self._resolved_api_url(),
                api_key=self._resolved_key(),
                remote_port=self._bootstrap_port,
                gateway_ca=self._resolved_gateway_ca(),
                expected_gateway_authority=self._expected_gateway_authority,
                timeout_s=min(self._operation_timeout_s, 120.0),
            )
        return self._resolved_bootstrap


def _secure_url(value: str, label: str, *, origin_only: bool = False) -> str:
    try:
        parsed = urlsplit(value)
        _ = parsed.port
    except ValueError as exc:
        raise click.ClickException(f"{label} must be an absolute URL") from exc
    if not parsed.hostname or parsed.scheme not in {"http", "https"}:
        raise click.ClickException(f"{label} must be an absolute URL")
    if parsed.scheme == "http" and parsed.hostname not in _LOOPBACK_HOSTS:
        raise click.ClickException(f"{label} must use HTTPS")
    if origin_only and parsed.path not in {"", "/"}:
        raise click.ClickException(f"{label} must not contain a path")
    if (
        parsed.username is not None
        or parsed.password is not None
        or parsed.query
        or parsed.fragment
    ):
        raise click.ClickException(f"{label} must not contain credentials, query, or fragment")
    return value.rstrip("/")


def _capability(key: str) -> dict[str, str]:
    return {
        "key": key,
        "minimum_support": "native",
        "minimum_maturity": "experimental",
    }


def _mapping(value: Any, label: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise _HiloopError(f"Hiloop {label} is missing")
    return value


def _string(value: Any, label: str) -> str:
    if not isinstance(value, str) or not value:
        raise _HiloopError(f"Hiloop {label} is missing")
    return value


def _component(value: str) -> str:
    return quote(value, safe="")
