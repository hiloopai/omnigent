"""Admin route for the server-wide session-sharing policy.

``GET /v1/sharing-mode`` reports the current mode, whether it is editable on
this server, and the available tiers. ``PUT /v1/sharing-mode`` sets it (admin
only), persisting an override to ``<data_dir>/sharing_mode`` that the grant
gate and ``GET /v1/info`` read per request.

Editing is only possible when the server resolves its mode from that file (the
OSS default, ``create_app(sharing_mode=None)``). A deployment that injects its
own resolver — a static value or a callable such as a Databricks SAFE flag —
reports ``editable: false`` and rejects writes, since its policy is
authoritative elsewhere.
"""

from __future__ import annotations

import asyncio
from typing import Any

from fastapi import APIRouter, Request
from pydantic import BaseModel

from omnigent.errors import ErrorCode, OmnigentError
from omnigent.server.auth import AuthProvider, SharingMode
from omnigent.server.routes._auth_helpers import get_user_id
from omnigent.server.sharing_settings import write_sharing_mode_override
from omnigent.stores.permission_store import PermissionStore

# The tiers offered to admins, most-permissive first (matches the UI order).
_TIERS: tuple[SharingMode, ...] = (
    SharingMode.ON,
    SharingMode.READ_ONLY,
    SharingMode.RESTRICTED_READ_ONLY,
    SharingMode.OFF,
)


class SetSharingModeRequest(BaseModel):
    """Body for ``PUT /v1/sharing-mode``."""

    sharing_mode: str


def _state_response(mode: SharingMode, editable: bool) -> dict[str, Any]:
    """Shape the ``sharing_mode`` state payload shared by GET and PUT."""
    return {
        "object": "sharing_mode",
        "sharing_mode": mode.value,
        "editable": editable,
        "options": [tier.value for tier in _TIERS],
    }


async def _require_admin(
    request: Request,
    auth_provider: AuthProvider | None,
    permission_store: PermissionStore | None,
) -> None:
    """Verify the caller is an admin, mirroring the default-policies gate.

    Single-user mode (no permission store) skips the check. Multi-user mode
    raises 401 if unauthenticated or 403 if the user is not an admin.
    """
    if permission_store is None:
        return
    user_id = get_user_id(request, auth_provider)
    if user_id is None:
        raise OmnigentError("Authentication required", code=ErrorCode.UNAUTHORIZED)
    is_admin = await asyncio.to_thread(permission_store.is_admin, user_id)
    if not is_admin:
        raise OmnigentError(
            "Admin privileges required to manage the sharing mode",
            code=ErrorCode.FORBIDDEN,
        )


def create_sharing_mode_router(
    auth_provider: AuthProvider | None = None,
    permission_store: PermissionStore | None = None,
) -> APIRouter:
    """Build the admin sharing-mode router (mounted under ``/v1``)."""
    router = APIRouter()

    @router.get("/sharing-mode")
    async def get_sharing_mode(request: Request) -> dict[str, Any]:
        """Report the current mode, whether it is editable here, and the tiers."""
        await _require_admin(request, auth_provider, permission_store)
        mode: SharingMode = request.app.state.sharing_mode()
        editable = bool(getattr(request.app.state, "sharing_mode_writable", False))
        return _state_response(mode, editable)

    @router.put("/sharing-mode")
    async def set_sharing_mode(request: Request, body: SetSharingModeRequest) -> dict[str, Any]:
        """Set the server-wide sharing mode (admin only).

        Rejects an unknown value with 400 (no fail-open coercion — an admin
        setting a value should learn about a typo). Rejects the write with 403
        when the deployment's mode is not file-backed (``editable: false``).
        """
        await _require_admin(request, auth_provider, permission_store)
        if not getattr(request.app.state, "sharing_mode_writable", False):
            raise OmnigentError(
                "Sharing mode is managed by this deployment and cannot be changed here.",
                code=ErrorCode.FORBIDDEN,
            )
        try:
            mode = SharingMode(body.sharing_mode.strip().lower())
        except ValueError as exc:
            raise OmnigentError(
                f"Unknown sharing mode {body.sharing_mode!r}. Expected one of: "
                + ", ".join(tier.value for tier in _TIERS)
                + ".",
                code=ErrorCode.INVALID_INPUT,
            ) from exc
        await asyncio.to_thread(write_sharing_mode_override, mode)
        return _state_response(mode, editable=True)

    return router
