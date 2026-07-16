"""Loopback bootstrap protocol for native Hiloop sandbox hosts."""

from __future__ import annotations

import socket
import threading

import pytest

from omnigent.onboarding.sandboxes.hiloop_bootstrap import (
    BOOTSTRAP_SCHEMA,
    BootstrapRequest,
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
    )


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("server_url", "http://agents.hiloop.test"),
        ("workspace", "/tmp/not-branchfs"),
        ("workspace", "/workspace/../etc"),
        ("token", "short"),
        ("host_id", "bad host"),
    ],
)
def test_validate_request_fails_closed(field: str, value: str) -> None:
    payload = _payload()
    payload[field] = value

    with pytest.raises(ValueError):
        validate_request(payload)
