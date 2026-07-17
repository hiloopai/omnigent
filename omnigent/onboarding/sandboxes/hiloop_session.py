"""Direct proof-bound client for Hiloop ``session_tcp`` bootstrap traffic."""

from __future__ import annotations

import hashlib
import queue
import ssl
import time
import uuid
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol, cast
from urllib.parse import SplitResult, urlsplit

import grpc
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from omnigent.api.hiloop.v1 import sandbox_session_pb2 as wire
from omnigent.api.hiloop.v1 import sandbox_session_pb2_grpc as wire_grpc
from omnigent.onboarding.sandboxes.hiloop_bootstrap import (
    BOOTSTRAP_SCHEMA,
    decode_frame,
    encode_frame,
)

_PROOF_DOMAIN = b"hiloop.session-proof.v1\0"
_MAX_CARRIER_FRAME_BYTES = 32 * 1024
_MAX_GATEWAY_MESSAGE_BYTES = _MAX_CARRIER_FRAME_BYTES + 8 * 1024
_MAX_CREDIT_BYTES = 256 * 1024
_MAX_TICKET_BYTES = 4 * 1024
_MAX_CONCURRENT_CONNECTIONS = 4_096
_MAX_OPENS_PER_SECOND = 16_384
_MAX_TOTAL_CONNECTIONS = 1_000_000
_MAX_BYTES_PER_CONNECTION = 1 << 40
_MAX_IDLE_SECONDS = 86_400
_MAX_GATEWAY_CA_BYTES = 1 << 20
_DEFAULT_GRANT_SECONDS = 3_600
_AUTHORITY_TIMEOUT_SECONDS = 30.0
_REQUEST_QUEUE_DEPTH = 8
_TARGET_READY_RETRY_BUDGET_SECONDS = 10.0
_TARGET_READY_RETRY_INITIAL_SECONDS = 0.05
_TARGET_READY_RETRY_MAX_SECONDS = 0.5
_TARGET_READY_MAX_ATTEMPTS = 32
_LOOPBACK_HOSTS = frozenset({"localhost", "127.0.0.1", "::1"})


class _HiloopSessionError(RuntimeError):
    """A sanitized authority, gateway, or carrier contract failure."""


class _TargetUnavailable(_HiloopSessionError):
    """The proof succeeded but the loopback listener is not ready yet."""


class _Authority(Protocol):
    def CreateSandboxSession(
        self,
        request: wire.CreateSandboxSessionRequest,
        *,
        timeout: float,
        metadata: tuple[tuple[str, str], ...],
    ) -> wire.CreateSandboxSessionResponse: ...


class _OpenCall(Iterator[wire.OpenResponse], Protocol):
    def cancel(self) -> bool: ...


class _Gateway(Protocol):
    def Open(
        self,
        requests: Iterator[wire.OpenRequest],
        *,
        timeout: float,
    ) -> _OpenCall: ...


@dataclass(frozen=True)
class _Limits:
    max_bytes_up: int
    max_bytes_down: int


@dataclass(frozen=True, repr=False)
class _Grant:
    gateway_authority: str
    ticket: bytes
    limits: _Limits

    def __repr__(self) -> str:
        return "_Grant([redacted])"


class _ProofIdentity:
    def __init__(self, private_key: Ed25519PrivateKey) -> None:
        self._private_key = private_key
        self.public_key = private_key.public_key().public_bytes(
            encoding=serialization.Encoding.Raw,
            format=serialization.PublicFormat.Raw,
        )

    @classmethod
    def generate(cls) -> _ProofIdentity:
        return cls(Ed25519PrivateKey.generate())

    def sign(self, ticket: bytes, connection_id: bytes, challenge: bytes) -> bytes:
        message = _PROOF_DOMAIN + hashlib.sha256(ticket).digest() + connection_id + challenge
        return self._private_key.sign(message)

    def __repr__(self) -> str:
        return "_ProofIdentity([redacted])"


class _SessionBootstrap:
    """Issue one target-bound grant and carry one bootstrap exchange over it."""

    def __init__(
        self,
        *,
        api_url: str,
        api_key: str,
        remote_port: int,
        gateway_ca: str | None,
        expected_gateway_authority: str | None,
        timeout_s: float,
        api_ca: str | None = None,
        authority: _Authority | None = None,
        gateway: _Gateway | None = None,
    ) -> None:
        self._api_url = api_url
        self._api_key = api_key
        self._remote_port = remote_port
        self._gateway_ca = gateway_ca
        self._expected_gateway_authority = expected_gateway_authority
        self._timeout_s = timeout_s
        self._api_ca = api_ca
        self._authority_override = authority
        self._gateway_override = gateway

    def launch(self, sandbox_id: str, payload: dict[str, str]) -> None:
        gateway_ca = _read_gateway_ca(self._gateway_ca) if self._gateway_override is None else None
        api_ca = _read_api_ca(self._api_ca) if self._authority_override is None else None
        identity = _ProofIdentity.generate()
        authority_channel: grpc.Channel | None = None
        gateway_channel: grpc.Channel | None = None
        try:
            authority = self._authority_override
            if authority is None:
                authority_channel = _channel(
                    self._api_url,
                    additional_ca=api_ca,
                    include_system_roots=True,
                )
                authority = cast(
                    _Authority,
                    wire_grpc.SandboxSessionServiceStub(authority_channel),  # type: ignore[no-untyped-call]
                )
            grant = self._issue_grant(authority, sandbox_id, identity)
            if (
                self._expected_gateway_authority is not None
                and grant.gateway_authority != self._expected_gateway_authority
            ):
                raise _HiloopSessionError(
                    "Hiloop session grant named an unexpected gateway authority"
                )

            gateway = self._gateway_override
            if gateway is None:
                gateway_channel = _channel(
                    _gateway_url(grant.gateway_authority),
                    additional_ca=gateway_ca,
                    allow_plaintext=False,
                    max_message_bytes=_MAX_GATEWAY_MESSAGE_BYTES,
                )
                gateway = cast(
                    _Gateway,
                    wire_grpc.SandboxSessionConnectServiceStub(gateway_channel),  # type: ignore[no-untyped-call]
                )
            try:
                encoded_payload = encode_frame(payload)
            except ValueError as exc:
                raise _HiloopSessionError("Omnigent bootstrap request is invalid") from exc
            response = self._open_when_ready(gateway, grant, identity, encoded_payload)
        except grpc.RpcError as exc:
            raise _HiloopSessionError(
                f"Hiloop sandbox session failed ({_grpc_code(exc)})"
            ) from exc
        finally:
            if gateway_channel is not None:
                gateway_channel.close()
            if authority_channel is not None:
                authority_channel.close()
        if response != {"schema": BOOTSTRAP_SCHEMA, "status": "accepted"}:
            raise _HiloopSessionError("sandbox rejected the Omnigent bootstrap request")

    def _open_when_ready(
        self,
        gateway: _Gateway,
        grant: _Grant,
        identity: _ProofIdentity,
        payload: bytes,
    ) -> dict[str, str]:
        deadline = time.monotonic() + min(
            self._timeout_s,
            _TARGET_READY_RETRY_BUDGET_SECONDS,
        )
        delay = _TARGET_READY_RETRY_INITIAL_SECONDS
        for _attempt in range(_TARGET_READY_MAX_ATTEMPTS):
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                break
            try:
                return self._open(
                    gateway,
                    grant,
                    identity,
                    payload,
                    timeout_s=remaining,
                )
            except _TargetUnavailable:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    break
                time.sleep(min(delay, remaining))
                delay = min(delay * 2, _TARGET_READY_RETRY_MAX_SECONDS)
        raise _HiloopSessionError(
            "Hiloop sandbox bootstrap target did not become ready within its retry budget"
        )

    def _issue_grant(
        self,
        authority: _Authority,
        sandbox_id: str,
        identity: _ProofIdentity,
    ) -> _Grant:
        request = wire.CreateSandboxSessionRequest(
            sandbox_id=sandbox_id,
            kind=wire.SANDBOX_SESSION_KIND_TCP,
            tcp=wire.SandboxLoopbackTarget(port=self._remote_port),
            max_duration_seconds=_DEFAULT_GRANT_SECONDS,
            client_proof_public_key=identity.public_key,
            connection_limits=wire.SandboxSessionConnectionLimits(),
        )
        try:
            response = authority.CreateSandboxSession(
                request,
                timeout=min(self._timeout_s, _AUTHORITY_TIMEOUT_SECONDS),
                metadata=(
                    ("authorization", f"Bearer {self._api_key}"),
                    ("idempotency-key", str(uuid.uuid4())),
                ),
            )
        except (TypeError, ValueError) as exc:
            raise _HiloopSessionError("Hiloop session request metadata is invalid") from exc
        return _validate_grant(response.session, sandbox_id, self._remote_port)

    def _open(
        self,
        gateway: _Gateway,
        grant: _Grant,
        identity: _ProofIdentity,
        payload: bytes,
        *,
        timeout_s: float,
    ) -> dict[str, str]:
        requests: queue.Queue[wire.OpenRequest | None] = queue.Queue(maxsize=_REQUEST_QUEUE_DEPTH)
        connection_id = uuid.uuid4().bytes
        requests.put(
            wire.OpenRequest(
                open=wire.SandboxSessionClientOpen(
                    signed_ticket=grant.ticket,
                    client_proof_public_key=identity.public_key,
                    connection_id=connection_id,
                )
            )
        )
        call = gateway.Open(_request_iterator(requests), timeout=timeout_s)
        try:
            challenge_frame = _next_response(call)
            if (
                challenge_frame.WhichOneof("frame") != "challenge"
                or len(challenge_frame.challenge.nonce) != 32
            ):
                raise _HiloopSessionError("Hiloop session gateway sent an invalid challenge")
            requests.put(
                wire.OpenRequest(
                    proof=wire.SandboxSessionClientProof(
                        signature=identity.sign(
                            grant.ticket,
                            connection_id,
                            challenge_frame.challenge.nonce,
                        )
                    )
                )
            )
            result_frame = _next_response(call)
            if result_frame.WhichOneof("frame") != "open_result":
                raise _HiloopSessionError("Hiloop session gateway omitted its open result")
            outcome = result_frame.open_result.WhichOneof("outcome")
            if outcome == "error":
                if (
                    result_frame.open_result.error.code
                    == wire.SANDBOX_SESSION_ERROR_CODE_TARGET_UNAVAILABLE
                ):
                    raise _TargetUnavailable("Hiloop sandbox bootstrap target is not ready")
                raise _HiloopSessionError(
                    "Hiloop session gateway rejected the connection "
                    f"({_error_token(result_frame.open_result.error.code)})"
                )
            if outcome != "accepted":
                raise _HiloopSessionError("Hiloop session gateway sent an invalid open result")
            accepted = result_frame.open_result.accepted
            _validate_credit(accepted.initial_send_credit, grant.limits.max_bytes_up)
            _validate_credit(accepted.initial_receive_credit, grant.limits.max_bytes_down)
            return _bridge_bootstrap(
                call,
                requests,
                payload,
                accepted.initial_send_credit,
                accepted.initial_receive_credit,
                grant.limits,
            )
        finally:
            call.cancel()
            _stop_request_iterator(requests)


def _validate_grant(
    session: wire.SandboxSession,
    sandbox_id: str,
    remote_port: int,
) -> _Grant:
    try:
        uuid.UUID(session.id)
    except ValueError as exc:
        raise _HiloopSessionError("Hiloop session authority returned an invalid grant") from exc
    valid_state = session.state in {
        wire.SANDBOX_SESSION_STATE_ISSUED,
        wire.SANDBOX_SESSION_STATE_CONNECTED,
    }
    if (
        session.sandbox_id != sandbox_id
        or session.kind != wire.SANDBOX_SESSION_KIND_TCP
        or not valid_state
        or session.WhichOneof("target") != "tcp"
        or session.tcp.port != remote_port
        or session.HasField("ssh")
        or session.ticket_generation == 0
        or not session.connect_ticket
        or len(session.connect_ticket) > _MAX_TICKET_BYTES
        or not session.gateway_authority
    ):
        raise _HiloopSessionError("Hiloop session authority returned an invalid grant")
    limits = session.connection_limits
    if (
        limits.max_concurrent_connections == 0
        or limits.max_concurrent_connections > _MAX_CONCURRENT_CONNECTIONS
        or limits.opens_per_second == 0
        or limits.opens_per_second > _MAX_OPENS_PER_SECOND
        or limits.max_total_connections > _MAX_TOTAL_CONNECTIONS
        or (
            limits.max_total_connections != 0
            and limits.max_total_connections < limits.max_concurrent_connections
        )
        or limits.max_bytes_up_per_connection == 0
        or limits.max_bytes_up_per_connection > _MAX_BYTES_PER_CONNECTION
        or limits.max_bytes_down_per_connection == 0
        or limits.max_bytes_down_per_connection > _MAX_BYTES_PER_CONNECTION
        or limits.idle_timeout_seconds == 0
        or limits.idle_timeout_seconds > _MAX_IDLE_SECONDS
    ):
        raise _HiloopSessionError("Hiloop session authority returned invalid limits")
    return _Grant(
        gateway_authority=session.gateway_authority,
        ticket=bytes(session.connect_ticket),
        limits=_Limits(
            max_bytes_up=limits.max_bytes_up_per_connection,
            max_bytes_down=limits.max_bytes_down_per_connection,
        ),
    )


def _bridge_bootstrap(
    call: _OpenCall,
    requests: queue.Queue[wire.OpenRequest | None],
    payload: bytes,
    initial_send_credit: int,
    initial_receive_credit: int,
    limits: _Limits,
) -> dict[str, str]:
    sent = 0
    send_consumed = 0
    send_limit = initial_send_credit
    receive_next = 0
    receive_limit = initial_receive_credit
    received = bytearray()
    half_closed = False

    def send_available() -> None:
        nonlocal half_closed, sent
        while sent < len(payload) and sent < send_limit:
            count = min(_MAX_CARRIER_FRAME_BYTES, send_limit - sent, len(payload) - sent)
            requests.put(
                wire.OpenRequest(
                    data=wire.SandboxSessionData(
                        offset=sent,
                        payload=payload[sent : sent + count],
                    )
                )
            )
            sent += count
        if sent == len(payload) and not half_closed:
            requests.put(wire.OpenRequest(half_close=wire.SandboxSessionHalfClose()))
            half_closed = True
        elif sent == limits.max_bytes_up and sent < len(payload):
            raise _HiloopSessionError("Hiloop session bootstrap exceeded its byte limit")

    send_available()
    while True:
        response = _next_response(call)
        frame = response.WhichOneof("frame")
        if frame == "data":
            data = response.data
            end = data.offset + len(data.payload)
            if (
                data.offset != receive_next
                or not data.payload
                or len(data.payload) > _MAX_CARRIER_FRAME_BYTES
                or end > receive_limit
                or end > limits.max_bytes_down
            ):
                raise _HiloopSessionError("Hiloop session gateway violated carrier ordering")
            received.extend(data.payload)
            if len(received) > 4 + 16 * 1024:
                raise _HiloopSessionError("Hiloop bootstrap response exceeded its byte limit")
            receive_next = end
            grant = min(_MAX_CREDIT_BYTES, limits.max_bytes_down - end)
            if grant:
                new_limit = end + grant
                if new_limit < receive_limit:
                    raise _HiloopSessionError("Hiloop session gateway regressed receive credit")
                requests.put(
                    wire.OpenRequest(
                        credit=wire.SandboxSessionCredit(
                            consumed_through_offset=end,
                            grant_bytes=grant,
                        )
                    )
                )
                receive_limit = new_limit
        elif frame == "credit":
            credit = response.credit
            if (
                credit.grant_bytes == 0
                or credit.grant_bytes > _MAX_CREDIT_BYTES
                or credit.consumed_through_offset < send_consumed
                or credit.consumed_through_offset > sent
            ):
                raise _HiloopSessionError("Hiloop session gateway sent invalid credit")
            new_limit = credit.consumed_through_offset + credit.grant_bytes
            if new_limit < send_limit or new_limit > limits.max_bytes_up:
                raise _HiloopSessionError("Hiloop session gateway sent invalid credit")
            send_consumed = credit.consumed_through_offset
            send_limit = new_limit
            send_available()
        elif frame == "half_close":
            try:
                return decode_frame(bytes(received))
            except ValueError as exc:
                raise _HiloopSessionError("Hiloop bootstrap response is invalid") from exc
        elif frame == "reset":
            raise _HiloopSessionError(
                "Hiloop session gateway reset the connection "
                f"({_error_token(response.reset.error.code)})"
            )
        else:
            raise _HiloopSessionError("Hiloop session gateway violated the carrier protocol")


def _validate_credit(value: int, ceiling: int) -> None:
    if value == 0 or value > _MAX_CREDIT_BYTES or value > ceiling:
        raise _HiloopSessionError("Hiloop session gateway sent invalid initial credit")


def _request_iterator(
    requests: queue.Queue[wire.OpenRequest | None],
) -> Iterator[wire.OpenRequest]:
    while True:
        request = requests.get()
        if request is None:
            return
        yield request


def _stop_request_iterator(requests: queue.Queue[wire.OpenRequest | None]) -> None:
    while True:
        try:
            requests.put_nowait(None)
            return
        except queue.Full:
            try:
                requests.get_nowait()
            except queue.Empty:  # pragma: no cover - another consumer won the race
                continue


def _next_response(call: Iterator[wire.OpenResponse]) -> wire.OpenResponse:
    try:
        return next(call)
    except StopIteration as exc:
        raise _HiloopSessionError("Hiloop session gateway closed the carrier early") from exc


def _read_gateway_ca(path: str | None) -> bytes | None:
    return _read_ca(path, "Hiloop session gateway CA")


def _read_api_ca(path: str | None) -> bytes | None:
    return _read_ca(path, "Hiloop API CA")


def _read_ca(path: str | None, label: str) -> bytes | None:
    if path is None:
        return None
    try:
        with Path(path).open("rb") as stream:
            value = stream.read(_MAX_GATEWAY_CA_BYTES + 1)
    except OSError as exc:
        raise _HiloopSessionError(f"{label} could not be read") from exc
    if not value or len(value) > _MAX_GATEWAY_CA_BYTES:
        raise _HiloopSessionError(f"{label} must be 1 byte through 1 MiB")
    return value


def _gateway_url(authority: str) -> str:
    return authority if "://" in authority else f"https://{authority}"


def _channel(
    endpoint: str,
    *,
    additional_ca: bytes | None,
    include_system_roots: bool = False,
    allow_plaintext: bool = True,
    max_message_bytes: int | None = None,
) -> grpc.Channel:
    parsed = _endpoint(endpoint)
    options = (
        (
            ("grpc.max_receive_message_length", max_message_bytes),
            ("grpc.max_send_message_length", max_message_bytes),
        )
        if max_message_bytes is not None
        else None
    )
    if parsed.scheme == "http":
        if not allow_plaintext or parsed.hostname not in _LOOPBACK_HOSTS:
            raise _HiloopSessionError("Hiloop session endpoint must use TLS")
        return grpc.insecure_channel(_grpc_target(parsed), options=options)
    if parsed.scheme != "https":
        raise _HiloopSessionError("Hiloop session endpoint must use TLS")
    roots = (
        _combined_root_certificates(additional_ca)
        if additional_ca is not None and include_system_roots
        else additional_ca
    )
    credentials = grpc.ssl_channel_credentials(root_certificates=roots)
    return grpc.secure_channel(_grpc_target(parsed), credentials, options=options)


def _combined_root_certificates(additional_ca: bytes) -> bytes:
    context = ssl.create_default_context()
    try:
        context.load_verify_locations(cadata=additional_ca.decode("ascii"))
    except (OSError, UnicodeDecodeError, ssl.SSLError) as exc:
        raise _HiloopSessionError("Hiloop API CA must be a PEM trust bundle") from exc
    system_and_additional = context.get_ca_certs(binary_form=True)
    if not system_and_additional:
        raise _HiloopSessionError("Hiloop API CA produced an empty trust bundle")
    return b"".join(
        ssl.DER_cert_to_PEM_cert(certificate).encode("ascii")
        for certificate in system_and_additional
    )


def _endpoint(value: str) -> SplitResult:
    try:
        parsed = urlsplit(value)
        _ = parsed.port
    except ValueError as exc:
        raise _HiloopSessionError("Hiloop session endpoint is invalid") from exc
    if (
        parsed.hostname is None
        or parsed.username is not None
        or parsed.password is not None
        or parsed.query
        or parsed.fragment
        or (parsed.path and parsed.path != "/")
    ):
        raise _HiloopSessionError("Hiloop session endpoint is invalid")
    return parsed


def _grpc_target(parsed: SplitResult) -> str:
    assert parsed.hostname is not None
    host = f"[{parsed.hostname}]" if ":" in parsed.hostname else parsed.hostname
    port = parsed.port or (443 if parsed.scheme == "https" else 80)
    return f"{host}:{port}"


def _grpc_code(exc: grpc.RpcError) -> str:
    code: Any = exc.code()
    name = getattr(code, "name", None)
    return name.casefold() if isinstance(name, str) else "unknown"


def _error_token(value: int) -> str:
    try:
        name = str(wire.SandboxSessionErrorCode.Name(value))
    except ValueError:
        return "protocol_error"
    return name.removeprefix("SANDBOX_SESSION_ERROR_CODE_").casefold()
