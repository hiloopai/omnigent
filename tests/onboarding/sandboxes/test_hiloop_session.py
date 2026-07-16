"""Proof-bound Hiloop session_tcp client contracts."""

from __future__ import annotations

import hashlib
import uuid
from collections.abc import Iterator
from pathlib import Path

import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey

from omnigent.api.hiloop.v1 import sandbox_session_pb2 as wire
from omnigent.onboarding.sandboxes.hiloop_bootstrap import decode_frame, encode_frame
from omnigent.onboarding.sandboxes.hiloop_session import (
    _channel,
    _HiloopSessionError,
    _read_gateway_ca,
    _SessionBootstrap,
    _validate_grant,
)

_PROOF_DOMAIN = b"hiloop.session-proof.v1\0"
_TICKET = b"signed-incarnation-fenced-ticket"


def _session(**overrides: object) -> wire.SandboxSession:
    values: dict[str, object] = {
        "id": str(uuid.uuid4()),
        "sandbox_id": "sandbox-native-1",
        "kind": wire.SANDBOX_SESSION_KIND_TCP,
        "state": wire.SANDBOX_SESSION_STATE_ISSUED,
        "gateway_authority": "sessions.hiloop.test:443",
        "connect_ticket": _TICKET,
        "ticket_generation": 1,
        "tcp": wire.SandboxLoopbackTarget(port=17_891),
        "connection_limits": wire.SandboxSessionConnectionLimits(
            max_concurrent_connections=4,
            opens_per_second=16,
            max_total_connections=100,
            max_bytes_up_per_connection=1 << 20,
            max_bytes_down_per_connection=1 << 20,
            idle_timeout_seconds=60,
        ),
    }
    values.update(overrides)
    return wire.SandboxSession(**values)


class _FakeAuthority:
    def __init__(self, session: wire.SandboxSession | None = None) -> None:
        self._session = session or _session()
        self.calls: list[
            tuple[
                wire.CreateSandboxSessionRequest,
                float,
                tuple[tuple[str, str], ...],
            ]
        ] = []

    def CreateSandboxSession(
        self,
        request: wire.CreateSandboxSessionRequest,
        *,
        timeout: float,
        metadata: tuple[tuple[str, str], ...],
    ) -> wire.CreateSandboxSessionResponse:
        self.calls.append((request, timeout, metadata))
        return wire.CreateSandboxSessionResponse(session=self._session)


class _FakeOpenCall(Iterator[wire.OpenResponse]):
    def __init__(self, requests: Iterator[wire.OpenRequest]) -> None:
        self._requests = requests
        self._responses = self._serve()
        self.cancelled = False
        self.bootstrap_payload: dict[str, str] | None = None

    def __iter__(self) -> _FakeOpenCall:
        return self

    def __next__(self) -> wire.OpenResponse:
        return next(self._responses)

    def cancel(self) -> bool:
        self.cancelled = True
        return True

    def _serve(self) -> Iterator[wire.OpenResponse]:
        opened = next(self._requests)
        assert opened.WhichOneof("frame") == "open"
        assert opened.open.signed_ticket == _TICKET
        assert len(opened.open.client_proof_public_key) == 32
        assert len(opened.open.connection_id) == 16

        challenge = b"c" * 32
        yield wire.OpenResponse(challenge=wire.SandboxSessionClientChallenge(nonce=challenge))

        proof = next(self._requests)
        assert proof.WhichOneof("frame") == "proof"
        signed = (
            _PROOF_DOMAIN
            + hashlib.sha256(_TICKET).digest()
            + opened.open.connection_id
            + challenge
        )
        Ed25519PublicKey.from_public_bytes(opened.open.client_proof_public_key).verify(
            proof.proof.signature,
            signed,
        )
        yield wire.OpenResponse(
            open_result=wire.SandboxSessionOpenResult(
                accepted=wire.SandboxSessionOpenAccepted(
                    initial_send_credit=5,
                    initial_receive_credit=64,
                )
            )
        )

        request_bytes = bytearray()
        first_data = next(self._requests)
        assert first_data.WhichOneof("frame") == "data"
        assert first_data.data.offset == 0
        request_bytes.extend(first_data.data.payload)
        yield wire.OpenResponse(
            credit=wire.SandboxSessionCredit(
                consumed_through_offset=len(request_bytes),
                grant_bytes=256 * 1024,
            )
        )

        while True:
            request = next(self._requests)
            if request.WhichOneof("frame") == "half_close":
                break
            assert request.WhichOneof("frame") == "data"
            assert request.data.offset == len(request_bytes)
            request_bytes.extend(request.data.payload)
        self.bootstrap_payload = decode_frame(bytes(request_bytes))

        response = encode_frame({"schema": "omnigent.hiloop-bootstrap/v2", "status": "accepted"})
        split = len(response) // 2
        yield wire.OpenResponse(data=wire.SandboxSessionData(offset=0, payload=response[:split]))
        credit = next(self._requests)
        assert credit.WhichOneof("frame") == "credit"
        assert credit.credit.consumed_through_offset == split
        yield wire.OpenResponse(
            data=wire.SandboxSessionData(offset=split, payload=response[split:])
        )
        credit = next(self._requests)
        assert credit.WhichOneof("frame") == "credit"
        assert credit.credit.consumed_through_offset == len(response)
        yield wire.OpenResponse(half_close=wire.SandboxSessionHalfClose())


class _FakeGateway:
    def __init__(self) -> None:
        self.call: _FakeOpenCall | None = None
        self.timeout: float | None = None

    def Open(
        self,
        requests: Iterator[wire.OpenRequest],
        *,
        timeout: float,
    ) -> _FakeOpenCall:
        self.timeout = timeout
        self.call = _FakeOpenCall(requests)
        return self.call


def _payload() -> dict[str, str]:
    return {
        "schema": "omnigent.hiloop-bootstrap/v2",
        "token": "a-secure-one-time-managed-host-token",
        "host_id": "host-1",
        "host_name": "managed-native",
        "server_url": "https://agents.hiloop.test",
        "workspace": "/workspace",
        "model_gateway_url": "http://model-gateway.control.svc:8080/v1",
        "model": "gpt-5.6-terra",
    }


def test_direct_session_bootstrap_proves_key_and_carries_framed_request() -> None:
    authority = _FakeAuthority()
    gateway = _FakeGateway()
    bootstrap = _SessionBootstrap(
        api_url="https://api.hiloop.test",
        api_key="secret-key",
        remote_port=17_891,
        gateway_ca=None,
        expected_gateway_authority="sessions.hiloop.test:443",
        timeout_s=20,
        authority=authority,
        gateway=gateway,
    )

    bootstrap.launch("sandbox-native-1", _payload())

    request, timeout, metadata = authority.calls[0]
    assert request.sandbox_id == "sandbox-native-1"
    assert request.kind == wire.SANDBOX_SESSION_KIND_TCP
    assert request.tcp.port == 17_891
    assert request.max_duration_seconds == 3_600
    assert len(request.client_proof_public_key) == 32
    assert timeout == 20
    assert dict(metadata)["authorization"] == "Bearer secret-key"
    assert uuid.UUID(dict(metadata)["idempotency-key"])
    assert gateway.call is not None
    assert gateway.call.bootstrap_payload == _payload()
    assert gateway.call.cancelled is True


def test_direct_session_bootstrap_rejects_unexpected_gateway_authority() -> None:
    bootstrap = _SessionBootstrap(
        api_url="https://api.hiloop.test",
        api_key="secret-key",
        remote_port=17_891,
        gateway_ca=None,
        expected_gateway_authority="other.hiloop.test:443",
        timeout_s=20,
        authority=_FakeAuthority(),
        gateway=_FakeGateway(),
    )

    with pytest.raises(_HiloopSessionError, match="unexpected gateway authority"):
        bootstrap.launch("sandbox-native-1", _payload())


@pytest.mark.parametrize(
    "session",
    [
        _session(sandbox_id="another-sandbox"),
        _session(ticket_generation=0),
        _session(tcp=wire.SandboxLoopbackTarget(port=22)),
        _session(state=wire.SANDBOX_SESSION_STATE_REVOKED),
    ],
)
def test_grant_validation_fails_closed_on_identity_and_fence_mismatch(
    session: wire.SandboxSession,
) -> None:
    with pytest.raises(_HiloopSessionError, match="invalid grant"):
        _validate_grant(session, "sandbox-native-1", 17_891)


def test_gateway_transport_requires_tls_and_bounds_custom_ca(tmp_path: Path) -> None:
    with pytest.raises(_HiloopSessionError, match="must use TLS"):
        _channel(
            "http://sessions.hiloop.test:8080",
            additional_ca=None,
            allow_plaintext=False,
        )

    oversized = tmp_path / "oversized-ca.pem"
    oversized.write_bytes(b"x" * ((1 << 20) + 1))
    with pytest.raises(_HiloopSessionError, match="1 byte through 1 MiB"):
        _read_gateway_ca(str(oversized))
