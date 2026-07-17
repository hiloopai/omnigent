"""Proof-bound Hiloop session_tcp client contracts."""

from __future__ import annotations

import hashlib
import ssl
import uuid
from collections.abc import Iterator
from pathlib import Path

import pytest
from cryptography import x509
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
from cryptography.hazmat.primitives.serialization import Encoding

import omnigent.onboarding.sandboxes.hiloop_session as hiloop_session
from omnigent.api.hiloop.v1 import sandbox_session_pb2 as wire
from omnigent.inner.egress.ca import ensure_ca
from omnigent.onboarding.sandboxes.hiloop_bootstrap import decode_frame, encode_frame
from omnigent.onboarding.sandboxes.hiloop_session import (
    _channel,
    _combined_root_certificates,
    _HiloopSessionError,
    _read_api_ca,
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
        self.connection_id: bytes | None = None
        self.signed_ticket: bytes | None = None
        self.client_proof_public_key: bytes | None = None

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
        self.connection_id = bytes(opened.open.connection_id)
        self.signed_ticket = bytes(opened.open.signed_ticket)
        self.client_proof_public_key = bytes(opened.open.client_proof_public_key)

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

        response = encode_frame({"schema": "omnigent.hiloop-bootstrap/v3", "status": "accepted"})
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


class _RejectedOpenCall(Iterator[wire.OpenResponse]):
    def __init__(
        self,
        requests: Iterator[wire.OpenRequest],
        code: int,
    ) -> None:
        self._requests = requests
        self._code = code
        self._responses = self._serve()
        self.cancelled = False
        self.connection_id: bytes | None = None
        self.signed_ticket: bytes | None = None
        self.client_proof_public_key: bytes | None = None

    def __iter__(self) -> _RejectedOpenCall:
        return self

    def __next__(self) -> wire.OpenResponse:
        return next(self._responses)

    def cancel(self) -> bool:
        self.cancelled = True
        return True

    def _serve(self) -> Iterator[wire.OpenResponse]:
        opened = next(self._requests)
        assert opened.WhichOneof("frame") == "open"
        self.connection_id = bytes(opened.open.connection_id)
        self.signed_ticket = bytes(opened.open.signed_ticket)
        self.client_proof_public_key = bytes(opened.open.client_proof_public_key)
        challenge = b"r" * 32
        yield wire.OpenResponse(challenge=wire.SandboxSessionClientChallenge(nonce=challenge))
        proof = next(self._requests)
        assert proof.WhichOneof("frame") == "proof"
        signed = (
            _PROOF_DOMAIN
            + hashlib.sha256(opened.open.signed_ticket).digest()
            + opened.open.connection_id
            + challenge
        )
        Ed25519PublicKey.from_public_bytes(opened.open.client_proof_public_key).verify(
            proof.proof.signature,
            signed,
        )
        yield wire.OpenResponse(
            open_result=wire.SandboxSessionOpenResult(
                error=wire.SandboxSessionError(code=self._code, message="internal detail")
            )
        )


class _AcceptedResetCall(Iterator[wire.OpenResponse]):
    def __init__(self, requests: Iterator[wire.OpenRequest]) -> None:
        self._requests = requests
        self._responses = self._serve()
        self.cancelled = False

    def __iter__(self) -> _AcceptedResetCall:
        return self

    def __next__(self) -> wire.OpenResponse:
        return next(self._responses)

    def cancel(self) -> bool:
        self.cancelled = True
        return True

    def _serve(self) -> Iterator[wire.OpenResponse]:
        opened = next(self._requests)
        assert opened.WhichOneof("frame") == "open"
        yield wire.OpenResponse(challenge=wire.SandboxSessionClientChallenge(nonce=b"a" * 32))
        proof = next(self._requests)
        assert proof.WhichOneof("frame") == "proof"
        yield wire.OpenResponse(
            open_result=wire.SandboxSessionOpenResult(
                accepted=wire.SandboxSessionOpenAccepted(
                    initial_send_credit=256 * 1024,
                    initial_receive_credit=256 * 1024,
                )
            )
        )
        data = next(self._requests)
        assert data.WhichOneof("frame") == "data"
        yield wire.OpenResponse(
            reset=wire.SandboxSessionReset(
                error=wire.SandboxSessionError(code=wire.SANDBOX_SESSION_ERROR_CODE_CARRIER_LOST)
            )
        )


class _ScriptedGateway:
    def __init__(self, outcomes: list[int | str]) -> None:
        self._outcomes = outcomes
        self.calls: list[_RejectedOpenCall | _FakeOpenCall | _AcceptedResetCall] = []
        self.timeouts: list[float] = []

    def Open(
        self,
        requests: Iterator[wire.OpenRequest],
        *,
        timeout: float,
    ) -> _RejectedOpenCall | _FakeOpenCall | _AcceptedResetCall:
        self.timeouts.append(timeout)
        outcome = self._outcomes[len(self.calls)]
        if outcome == "success":
            call: _RejectedOpenCall | _FakeOpenCall | _AcceptedResetCall = _FakeOpenCall(requests)
        elif outcome == "accepted-reset":
            call = _AcceptedResetCall(requests)
        else:
            assert isinstance(outcome, int)
            call = _RejectedOpenCall(requests, outcome)
        self.calls.append(call)
        return call


def _payload() -> dict[str, str]:
    return {
        "schema": "omnigent.hiloop-bootstrap/v3",
        "token": "a-secure-one-time-managed-host-token",
        "host_id": "host-1",
        "host_name": "managed-native",
        "server_url": "https://agents.hiloop.test",
        "workspace": "/workspace",
        "model_gateway_url": "http://model-gateway.control.svc:8080/v1",
        "model": "gpt-5.6-terra",
        "server_ca_pem": "",
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


def test_bootstrap_retries_only_pre_accept_target_unavailable_with_one_grant() -> None:
    authority = _FakeAuthority()
    gateway = _ScriptedGateway(
        [
            wire.SANDBOX_SESSION_ERROR_CODE_TARGET_UNAVAILABLE,
            wire.SANDBOX_SESSION_ERROR_CODE_TARGET_UNAVAILABLE,
            "success",
        ]
    )
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

    assert len(authority.calls) == 1
    assert len(gateway.calls) == 3
    rejected = [call for call in gateway.calls[:2] if isinstance(call, _RejectedOpenCall)]
    assert len(rejected) == 2
    assert all(call.cancelled for call in rejected)
    success = gateway.calls[2]
    assert isinstance(success, _FakeOpenCall)
    connection_ids = [call.connection_id for call in rejected] + [success.connection_id]
    assert all(connection_ids)
    assert len(set(connection_ids)) == 3
    authority_request = authority.calls[0][0]
    assert all(call.signed_ticket == _TICKET for call in [*rejected, success])
    assert all(
        call.client_proof_public_key == authority_request.client_proof_public_key
        for call in [*rejected, success]
    )
    assert success.bootstrap_payload == _payload()


def test_bootstrap_does_not_retry_other_pre_accept_errors() -> None:
    authority = _FakeAuthority()
    gateway = _ScriptedGateway([wire.SANDBOX_SESSION_ERROR_CODE_TARGET_TIMEOUT])
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

    with pytest.raises(_HiloopSessionError, match="target_timeout"):
        bootstrap.launch("sandbox-native-1", _payload())

    assert len(authority.calls) == 1
    assert len(gateway.calls) == 1


def test_bootstrap_never_retries_after_open_was_accepted() -> None:
    gateway = _ScriptedGateway(["accepted-reset"])
    bootstrap = _SessionBootstrap(
        api_url="https://api.hiloop.test",
        api_key="secret-key",
        remote_port=17_891,
        gateway_ca=None,
        expected_gateway_authority="sessions.hiloop.test:443",
        timeout_s=20,
        authority=_FakeAuthority(),
        gateway=gateway,
    )

    with pytest.raises(_HiloopSessionError, match="carrier_lost"):
        bootstrap.launch("sandbox-native-1", _payload())

    assert len(gateway.calls) == 1


def test_target_unavailable_retry_is_attempt_bounded(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(hiloop_session, "_TARGET_READY_MAX_ATTEMPTS", 2)
    monkeypatch.setattr(hiloop_session.time, "sleep", lambda _delay: None)
    gateway = _ScriptedGateway(
        [
            wire.SANDBOX_SESSION_ERROR_CODE_TARGET_UNAVAILABLE,
            wire.SANDBOX_SESSION_ERROR_CODE_TARGET_UNAVAILABLE,
        ]
    )
    bootstrap = _SessionBootstrap(
        api_url="https://api.hiloop.test",
        api_key="secret-key",
        remote_port=17_891,
        gateway_ca=None,
        expected_gateway_authority="sessions.hiloop.test:443",
        timeout_s=20,
        authority=_FakeAuthority(),
        gateway=gateway,
    )

    with pytest.raises(_HiloopSessionError, match="retry budget"):
        bootstrap.launch("sandbox-native-1", _payload())

    assert len(gateway.calls) == 2


@pytest.mark.parametrize(("timeout_s", "expected_budget"), [(20.0, 10.0), (0.2, 0.2)])
def test_target_unavailable_retry_uses_one_decreasing_wall_deadline(
    monkeypatch: pytest.MonkeyPatch,
    timeout_s: float,
    expected_budget: float,
) -> None:
    class _Clock:
        def __init__(self) -> None:
            self.now = 100.0
            self.sleeps: list[float] = []

        def monotonic(self) -> float:
            return self.now

        def sleep(self, delay: float) -> None:
            self.sleeps.append(delay)
            self.now += delay

    clock = _Clock()
    monkeypatch.setattr(hiloop_session.time, "monotonic", clock.monotonic)
    monkeypatch.setattr(hiloop_session.time, "sleep", clock.sleep)
    gateway = _ScriptedGateway([wire.SANDBOX_SESSION_ERROR_CODE_TARGET_UNAVAILABLE] * 32)
    bootstrap = _SessionBootstrap(
        api_url="https://api.hiloop.test",
        api_key="secret-key",
        remote_port=17_891,
        gateway_ca=None,
        expected_gateway_authority="sessions.hiloop.test:443",
        timeout_s=timeout_s,
        authority=_FakeAuthority(),
        gateway=gateway,
    )

    with pytest.raises(_HiloopSessionError, match="retry budget"):
        bootstrap.launch("sandbox-native-1", _payload())

    assert clock.now == pytest.approx(100.0 + expected_budget)
    assert gateway.timeouts[0] == pytest.approx(expected_budget)
    assert all(
        later < earlier
        for earlier, later in zip(gateway.timeouts[:-1], gateway.timeouts[1:], strict=True)
    )


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


def test_api_authority_channel_adds_private_ca_to_system_roots(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, bytes | None] = {}
    monkeypatch.setattr(
        hiloop_session,
        "_combined_root_certificates",
        lambda additional: b"system-roots\n" + additional,
    )

    def credentials(*, root_certificates: bytes | None = None) -> object:
        captured["roots"] = root_certificates
        return object()

    monkeypatch.setattr(hiloop_session.grpc, "ssl_channel_credentials", credentials)
    monkeypatch.setattr(
        hiloop_session.grpc,
        "secure_channel",
        lambda target, credentials, options=None: (target, credentials, options),
    )

    _channel(
        "https://api.hiloop.test",
        additional_ca=b"private-api-ca",
        include_system_roots=True,
    )

    assert captured["roots"] == b"system-roots\nprivate-api-ca"


def test_api_authority_combined_roots_retain_system_and_private_ca(tmp_path: Path) -> None:
    api_ca, _ = ensure_ca(cache_dir=tmp_path)
    system_roots = set(ssl.create_default_context().get_ca_certs(binary_form=True))

    combined = _combined_root_certificates(api_ca.read_bytes())

    end_marker = b"-----END CERTIFICATE-----"
    parsed_roots = {
        ssl.PEM_cert_to_DER_cert((block + end_marker).strip().decode("ascii"))
        for block in combined.split(end_marker)
        if block.strip()
    }
    custom_der = x509.load_pem_x509_certificate(api_ca.read_bytes()).public_bytes(Encoding.DER)
    assert system_roots <= parsed_roots
    assert custom_der in parsed_roots


def test_api_ca_read_rejects_missing_empty_and_oversized_inputs(tmp_path: Path) -> None:
    missing = tmp_path / "missing-api-ca.pem"
    with pytest.raises(_HiloopSessionError, match="could not be read"):
        _read_api_ca(str(missing))

    empty = tmp_path / "empty-api-ca.pem"
    empty.write_bytes(b"")
    with pytest.raises(_HiloopSessionError, match="1 byte through 1 MiB"):
        _read_api_ca(str(empty))

    oversized = tmp_path / "oversized-api-ca.pem"
    oversized.write_bytes(b"x" * ((1 << 20) + 1))
    with pytest.raises(_HiloopSessionError, match="1 byte through 1 MiB"):
        _read_api_ca(str(oversized))


def test_api_ca_combination_rejects_invalid_pem(tmp_path: Path) -> None:
    invalid = tmp_path / "invalid-api-ca.pem"
    invalid.write_bytes(b"not a certificate")

    value = _read_api_ca(str(invalid))
    assert value is not None
    with pytest.raises(_HiloopSessionError, match="must be a PEM trust bundle"):
        _combined_root_certificates(value)
