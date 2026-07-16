from google.protobuf.internal import enum_type_wrapper as _enum_type_wrapper
from google.protobuf import descriptor as _descriptor
from google.protobuf import message as _message
from collections.abc import Mapping as _Mapping
from typing import ClassVar as _ClassVar, Optional as _Optional, Union as _Union

DESCRIPTOR: _descriptor.FileDescriptor

class SandboxSessionKind(int, metaclass=_enum_type_wrapper.EnumTypeWrapper):
    __slots__ = ()
    SANDBOX_SESSION_KIND_UNSPECIFIED: _ClassVar[SandboxSessionKind]
    SANDBOX_SESSION_KIND_TCP: _ClassVar[SandboxSessionKind]
    SANDBOX_SESSION_KIND_SSH: _ClassVar[SandboxSessionKind]

class SandboxSessionState(int, metaclass=_enum_type_wrapper.EnumTypeWrapper):
    __slots__ = ()
    SANDBOX_SESSION_STATE_UNSPECIFIED: _ClassVar[SandboxSessionState]
    SANDBOX_SESSION_STATE_ISSUED: _ClassVar[SandboxSessionState]
    SANDBOX_SESSION_STATE_CONNECTED: _ClassVar[SandboxSessionState]
    SANDBOX_SESSION_STATE_CLOSED: _ClassVar[SandboxSessionState]
    SANDBOX_SESSION_STATE_EXPIRED: _ClassVar[SandboxSessionState]
    SANDBOX_SESSION_STATE_REVOKED: _ClassVar[SandboxSessionState]

class SandboxSessionErrorCode(int, metaclass=_enum_type_wrapper.EnumTypeWrapper):
    __slots__ = ()
    SANDBOX_SESSION_ERROR_CODE_UNSPECIFIED: _ClassVar[SandboxSessionErrorCode]
    SANDBOX_SESSION_ERROR_CODE_UNAUTHENTICATED: _ClassVar[SandboxSessionErrorCode]
    SANDBOX_SESSION_ERROR_CODE_PERMISSION_DENIED: _ClassVar[SandboxSessionErrorCode]
    SANDBOX_SESSION_ERROR_CODE_TICKET_EXPIRED: _ClassVar[SandboxSessionErrorCode]
    SANDBOX_SESSION_ERROR_CODE_TICKET_INVALID: _ClassVar[SandboxSessionErrorCode]
    SANDBOX_SESSION_ERROR_CODE_INCARNATION_CHANGED: _ClassVar[SandboxSessionErrorCode]
    SANDBOX_SESSION_ERROR_CODE_ROUTE_UNAVAILABLE: _ClassVar[SandboxSessionErrorCode]
    SANDBOX_SESSION_ERROR_CODE_ROUTE_FENCED: _ClassVar[SandboxSessionErrorCode]
    SANDBOX_SESSION_ERROR_CODE_SANDBOX_NOT_RUNNING: _ClassVar[SandboxSessionErrorCode]
    SANDBOX_SESSION_ERROR_CODE_UNSUPPORTED_CAPABILITY: _ClassVar[SandboxSessionErrorCode]
    SANDBOX_SESSION_ERROR_CODE_TARGET_UNAVAILABLE: _ClassVar[SandboxSessionErrorCode]
    SANDBOX_SESSION_ERROR_CODE_TARGET_TIMEOUT: _ClassVar[SandboxSessionErrorCode]
    SANDBOX_SESSION_ERROR_CODE_RESOURCE_EXHAUSTED: _ClassVar[SandboxSessionErrorCode]
    SANDBOX_SESSION_ERROR_CODE_IDLE_TIMEOUT: _ClassVar[SandboxSessionErrorCode]
    SANDBOX_SESSION_ERROR_CODE_SESSION_EXPIRED: _ClassVar[SandboxSessionErrorCode]
    SANDBOX_SESSION_ERROR_CODE_PROTOCOL_ERROR: _ClassVar[SandboxSessionErrorCode]
    SANDBOX_SESSION_ERROR_CODE_CARRIER_LOST: _ClassVar[SandboxSessionErrorCode]
    SANDBOX_SESSION_ERROR_CODE_INCARNATION_DRAIN: _ClassVar[SandboxSessionErrorCode]
    SANDBOX_SESSION_ERROR_CODE_INTERNAL: _ClassVar[SandboxSessionErrorCode]
SANDBOX_SESSION_KIND_UNSPECIFIED: SandboxSessionKind
SANDBOX_SESSION_KIND_TCP: SandboxSessionKind
SANDBOX_SESSION_KIND_SSH: SandboxSessionKind
SANDBOX_SESSION_STATE_UNSPECIFIED: SandboxSessionState
SANDBOX_SESSION_STATE_ISSUED: SandboxSessionState
SANDBOX_SESSION_STATE_CONNECTED: SandboxSessionState
SANDBOX_SESSION_STATE_CLOSED: SandboxSessionState
SANDBOX_SESSION_STATE_EXPIRED: SandboxSessionState
SANDBOX_SESSION_STATE_REVOKED: SandboxSessionState
SANDBOX_SESSION_ERROR_CODE_UNSPECIFIED: SandboxSessionErrorCode
SANDBOX_SESSION_ERROR_CODE_UNAUTHENTICATED: SandboxSessionErrorCode
SANDBOX_SESSION_ERROR_CODE_PERMISSION_DENIED: SandboxSessionErrorCode
SANDBOX_SESSION_ERROR_CODE_TICKET_EXPIRED: SandboxSessionErrorCode
SANDBOX_SESSION_ERROR_CODE_TICKET_INVALID: SandboxSessionErrorCode
SANDBOX_SESSION_ERROR_CODE_INCARNATION_CHANGED: SandboxSessionErrorCode
SANDBOX_SESSION_ERROR_CODE_ROUTE_UNAVAILABLE: SandboxSessionErrorCode
SANDBOX_SESSION_ERROR_CODE_ROUTE_FENCED: SandboxSessionErrorCode
SANDBOX_SESSION_ERROR_CODE_SANDBOX_NOT_RUNNING: SandboxSessionErrorCode
SANDBOX_SESSION_ERROR_CODE_UNSUPPORTED_CAPABILITY: SandboxSessionErrorCode
SANDBOX_SESSION_ERROR_CODE_TARGET_UNAVAILABLE: SandboxSessionErrorCode
SANDBOX_SESSION_ERROR_CODE_TARGET_TIMEOUT: SandboxSessionErrorCode
SANDBOX_SESSION_ERROR_CODE_RESOURCE_EXHAUSTED: SandboxSessionErrorCode
SANDBOX_SESSION_ERROR_CODE_IDLE_TIMEOUT: SandboxSessionErrorCode
SANDBOX_SESSION_ERROR_CODE_SESSION_EXPIRED: SandboxSessionErrorCode
SANDBOX_SESSION_ERROR_CODE_PROTOCOL_ERROR: SandboxSessionErrorCode
SANDBOX_SESSION_ERROR_CODE_CARRIER_LOST: SandboxSessionErrorCode
SANDBOX_SESSION_ERROR_CODE_INCARNATION_DRAIN: SandboxSessionErrorCode
SANDBOX_SESSION_ERROR_CODE_INTERNAL: SandboxSessionErrorCode

class SandboxLoopbackTarget(_message.Message):
    __slots__ = ("port",)
    PORT_FIELD_NUMBER: _ClassVar[int]
    port: int
    def __init__(self, port: _Optional[int] = ...) -> None: ...

class SandboxSshTarget(_message.Message):
    __slots__ = ("unix_user", "client_public_key", "permit_local_forwarding")
    UNIX_USER_FIELD_NUMBER: _ClassVar[int]
    CLIENT_PUBLIC_KEY_FIELD_NUMBER: _ClassVar[int]
    PERMIT_LOCAL_FORWARDING_FIELD_NUMBER: _ClassVar[int]
    unix_user: str
    client_public_key: bytes
    permit_local_forwarding: bool
    def __init__(self, unix_user: _Optional[str] = ..., client_public_key: _Optional[bytes] = ..., permit_local_forwarding: _Optional[bool] = ...) -> None: ...

class SandboxSessionConnectionLimits(_message.Message):
    __slots__ = ("max_concurrent_connections", "opens_per_second", "max_total_connections", "max_bytes_up_per_connection", "max_bytes_down_per_connection", "idle_timeout_seconds")
    MAX_CONCURRENT_CONNECTIONS_FIELD_NUMBER: _ClassVar[int]
    OPENS_PER_SECOND_FIELD_NUMBER: _ClassVar[int]
    MAX_TOTAL_CONNECTIONS_FIELD_NUMBER: _ClassVar[int]
    MAX_BYTES_UP_PER_CONNECTION_FIELD_NUMBER: _ClassVar[int]
    MAX_BYTES_DOWN_PER_CONNECTION_FIELD_NUMBER: _ClassVar[int]
    IDLE_TIMEOUT_SECONDS_FIELD_NUMBER: _ClassVar[int]
    max_concurrent_connections: int
    opens_per_second: int
    max_total_connections: int
    max_bytes_up_per_connection: int
    max_bytes_down_per_connection: int
    idle_timeout_seconds: int
    def __init__(self, max_concurrent_connections: _Optional[int] = ..., opens_per_second: _Optional[int] = ..., max_total_connections: _Optional[int] = ..., max_bytes_up_per_connection: _Optional[int] = ..., max_bytes_down_per_connection: _Optional[int] = ..., idle_timeout_seconds: _Optional[int] = ...) -> None: ...

class CreateSandboxSessionRequest(_message.Message):
    __slots__ = ("sandbox_id", "kind", "tcp", "ssh", "max_duration_seconds", "client_proof_public_key", "connection_limits")
    SANDBOX_ID_FIELD_NUMBER: _ClassVar[int]
    KIND_FIELD_NUMBER: _ClassVar[int]
    TCP_FIELD_NUMBER: _ClassVar[int]
    SSH_FIELD_NUMBER: _ClassVar[int]
    MAX_DURATION_SECONDS_FIELD_NUMBER: _ClassVar[int]
    CLIENT_PROOF_PUBLIC_KEY_FIELD_NUMBER: _ClassVar[int]
    CONNECTION_LIMITS_FIELD_NUMBER: _ClassVar[int]
    sandbox_id: str
    kind: SandboxSessionKind
    tcp: SandboxLoopbackTarget
    ssh: SandboxSshTarget
    max_duration_seconds: int
    client_proof_public_key: bytes
    connection_limits: SandboxSessionConnectionLimits
    def __init__(self, sandbox_id: _Optional[str] = ..., kind: _Optional[_Union[SandboxSessionKind, str]] = ..., tcp: _Optional[_Union[SandboxLoopbackTarget, _Mapping]] = ..., ssh: _Optional[_Union[SandboxSshTarget, _Mapping]] = ..., max_duration_seconds: _Optional[int] = ..., client_proof_public_key: _Optional[bytes] = ..., connection_limits: _Optional[_Union[SandboxSessionConnectionLimits, _Mapping]] = ...) -> None: ...

class SandboxSshSessionMaterial(_message.Message):
    __slots__ = ("logical_hostname", "username", "user_certificate", "host_ca_public_key")
    LOGICAL_HOSTNAME_FIELD_NUMBER: _ClassVar[int]
    USERNAME_FIELD_NUMBER: _ClassVar[int]
    USER_CERTIFICATE_FIELD_NUMBER: _ClassVar[int]
    HOST_CA_PUBLIC_KEY_FIELD_NUMBER: _ClassVar[int]
    logical_hostname: str
    username: str
    user_certificate: bytes
    host_ca_public_key: bytes
    def __init__(self, logical_hostname: _Optional[str] = ..., username: _Optional[str] = ..., user_certificate: _Optional[bytes] = ..., host_ca_public_key: _Optional[bytes] = ...) -> None: ...

class SandboxSession(_message.Message):
    __slots__ = ("id", "sandbox_id", "kind", "state", "gateway_authority", "connect_ticket", "connect_deadline", "expires_at", "ssh", "created_at", "connection_limits", "ticket_generation", "tcp", "ssh_target")
    ID_FIELD_NUMBER: _ClassVar[int]
    SANDBOX_ID_FIELD_NUMBER: _ClassVar[int]
    KIND_FIELD_NUMBER: _ClassVar[int]
    STATE_FIELD_NUMBER: _ClassVar[int]
    GATEWAY_AUTHORITY_FIELD_NUMBER: _ClassVar[int]
    CONNECT_TICKET_FIELD_NUMBER: _ClassVar[int]
    CONNECT_DEADLINE_FIELD_NUMBER: _ClassVar[int]
    EXPIRES_AT_FIELD_NUMBER: _ClassVar[int]
    SSH_FIELD_NUMBER: _ClassVar[int]
    CREATED_AT_FIELD_NUMBER: _ClassVar[int]
    CONNECTION_LIMITS_FIELD_NUMBER: _ClassVar[int]
    TICKET_GENERATION_FIELD_NUMBER: _ClassVar[int]
    TCP_FIELD_NUMBER: _ClassVar[int]
    SSH_TARGET_FIELD_NUMBER: _ClassVar[int]
    id: str
    sandbox_id: str
    kind: SandboxSessionKind
    state: SandboxSessionState
    gateway_authority: str
    connect_ticket: bytes
    connect_deadline: str
    expires_at: str
    ssh: SandboxSshSessionMaterial
    created_at: str
    connection_limits: SandboxSessionConnectionLimits
    ticket_generation: int
    tcp: SandboxLoopbackTarget
    ssh_target: SandboxSshTarget
    def __init__(self, id: _Optional[str] = ..., sandbox_id: _Optional[str] = ..., kind: _Optional[_Union[SandboxSessionKind, str]] = ..., state: _Optional[_Union[SandboxSessionState, str]] = ..., gateway_authority: _Optional[str] = ..., connect_ticket: _Optional[bytes] = ..., connect_deadline: _Optional[str] = ..., expires_at: _Optional[str] = ..., ssh: _Optional[_Union[SandboxSshSessionMaterial, _Mapping]] = ..., created_at: _Optional[str] = ..., connection_limits: _Optional[_Union[SandboxSessionConnectionLimits, _Mapping]] = ..., ticket_generation: _Optional[int] = ..., tcp: _Optional[_Union[SandboxLoopbackTarget, _Mapping]] = ..., ssh_target: _Optional[_Union[SandboxSshTarget, _Mapping]] = ...) -> None: ...

class CreateSandboxSessionResponse(_message.Message):
    __slots__ = ("session",)
    SESSION_FIELD_NUMBER: _ClassVar[int]
    session: SandboxSession
    def __init__(self, session: _Optional[_Union[SandboxSession, _Mapping]] = ...) -> None: ...

class GetSandboxSessionRequest(_message.Message):
    __slots__ = ("id",)
    ID_FIELD_NUMBER: _ClassVar[int]
    id: str
    def __init__(self, id: _Optional[str] = ...) -> None: ...

class GetSandboxSessionResponse(_message.Message):
    __slots__ = ("session",)
    SESSION_FIELD_NUMBER: _ClassVar[int]
    session: SandboxSession
    def __init__(self, session: _Optional[_Union[SandboxSession, _Mapping]] = ...) -> None: ...

class RevokeSandboxSessionRequest(_message.Message):
    __slots__ = ("id",)
    ID_FIELD_NUMBER: _ClassVar[int]
    id: str
    def __init__(self, id: _Optional[str] = ...) -> None: ...

class RevokeSandboxSessionResponse(_message.Message):
    __slots__ = ("session",)
    SESSION_FIELD_NUMBER: _ClassVar[int]
    session: SandboxSession
    def __init__(self, session: _Optional[_Union[SandboxSession, _Mapping]] = ...) -> None: ...

class SandboxSessionError(_message.Message):
    __slots__ = ("code", "message")
    CODE_FIELD_NUMBER: _ClassVar[int]
    MESSAGE_FIELD_NUMBER: _ClassVar[int]
    code: SandboxSessionErrorCode
    message: str
    def __init__(self, code: _Optional[_Union[SandboxSessionErrorCode, str]] = ..., message: _Optional[str] = ...) -> None: ...

class SandboxSessionClientOpen(_message.Message):
    __slots__ = ("signed_ticket", "client_proof_public_key", "connection_id")
    SIGNED_TICKET_FIELD_NUMBER: _ClassVar[int]
    CLIENT_PROOF_PUBLIC_KEY_FIELD_NUMBER: _ClassVar[int]
    CONNECTION_ID_FIELD_NUMBER: _ClassVar[int]
    signed_ticket: bytes
    client_proof_public_key: bytes
    connection_id: bytes
    def __init__(self, signed_ticket: _Optional[bytes] = ..., client_proof_public_key: _Optional[bytes] = ..., connection_id: _Optional[bytes] = ...) -> None: ...

class SandboxSessionClientChallenge(_message.Message):
    __slots__ = ("nonce",)
    NONCE_FIELD_NUMBER: _ClassVar[int]
    nonce: bytes
    def __init__(self, nonce: _Optional[bytes] = ...) -> None: ...

class SandboxSessionClientProof(_message.Message):
    __slots__ = ("signature",)
    SIGNATURE_FIELD_NUMBER: _ClassVar[int]
    signature: bytes
    def __init__(self, signature: _Optional[bytes] = ...) -> None: ...

class SandboxSessionOpenAccepted(_message.Message):
    __slots__ = ("initial_send_credit", "initial_receive_credit")
    INITIAL_SEND_CREDIT_FIELD_NUMBER: _ClassVar[int]
    INITIAL_RECEIVE_CREDIT_FIELD_NUMBER: _ClassVar[int]
    initial_send_credit: int
    initial_receive_credit: int
    def __init__(self, initial_send_credit: _Optional[int] = ..., initial_receive_credit: _Optional[int] = ...) -> None: ...

class SandboxSessionOpenResult(_message.Message):
    __slots__ = ("accepted", "error")
    ACCEPTED_FIELD_NUMBER: _ClassVar[int]
    ERROR_FIELD_NUMBER: _ClassVar[int]
    accepted: SandboxSessionOpenAccepted
    error: SandboxSessionError
    def __init__(self, accepted: _Optional[_Union[SandboxSessionOpenAccepted, _Mapping]] = ..., error: _Optional[_Union[SandboxSessionError, _Mapping]] = ...) -> None: ...

class SandboxSessionData(_message.Message):
    __slots__ = ("offset", "payload")
    OFFSET_FIELD_NUMBER: _ClassVar[int]
    PAYLOAD_FIELD_NUMBER: _ClassVar[int]
    offset: int
    payload: bytes
    def __init__(self, offset: _Optional[int] = ..., payload: _Optional[bytes] = ...) -> None: ...

class SandboxSessionCredit(_message.Message):
    __slots__ = ("consumed_through_offset", "grant_bytes")
    CONSUMED_THROUGH_OFFSET_FIELD_NUMBER: _ClassVar[int]
    GRANT_BYTES_FIELD_NUMBER: _ClassVar[int]
    consumed_through_offset: int
    grant_bytes: int
    def __init__(self, consumed_through_offset: _Optional[int] = ..., grant_bytes: _Optional[int] = ...) -> None: ...

class SandboxSessionHalfClose(_message.Message):
    __slots__ = ()
    def __init__(self) -> None: ...

class SandboxSessionReset(_message.Message):
    __slots__ = ("error",)
    ERROR_FIELD_NUMBER: _ClassVar[int]
    error: SandboxSessionError
    def __init__(self, error: _Optional[_Union[SandboxSessionError, _Mapping]] = ...) -> None: ...

class OpenRequest(_message.Message):
    __slots__ = ("open", "proof", "data", "credit", "half_close", "reset")
    OPEN_FIELD_NUMBER: _ClassVar[int]
    PROOF_FIELD_NUMBER: _ClassVar[int]
    DATA_FIELD_NUMBER: _ClassVar[int]
    CREDIT_FIELD_NUMBER: _ClassVar[int]
    HALF_CLOSE_FIELD_NUMBER: _ClassVar[int]
    RESET_FIELD_NUMBER: _ClassVar[int]
    open: SandboxSessionClientOpen
    proof: SandboxSessionClientProof
    data: SandboxSessionData
    credit: SandboxSessionCredit
    half_close: SandboxSessionHalfClose
    reset: SandboxSessionReset
    def __init__(self, open: _Optional[_Union[SandboxSessionClientOpen, _Mapping]] = ..., proof: _Optional[_Union[SandboxSessionClientProof, _Mapping]] = ..., data: _Optional[_Union[SandboxSessionData, _Mapping]] = ..., credit: _Optional[_Union[SandboxSessionCredit, _Mapping]] = ..., half_close: _Optional[_Union[SandboxSessionHalfClose, _Mapping]] = ..., reset: _Optional[_Union[SandboxSessionReset, _Mapping]] = ...) -> None: ...

class OpenResponse(_message.Message):
    __slots__ = ("challenge", "open_result", "data", "credit", "half_close", "reset")
    CHALLENGE_FIELD_NUMBER: _ClassVar[int]
    OPEN_RESULT_FIELD_NUMBER: _ClassVar[int]
    DATA_FIELD_NUMBER: _ClassVar[int]
    CREDIT_FIELD_NUMBER: _ClassVar[int]
    HALF_CLOSE_FIELD_NUMBER: _ClassVar[int]
    RESET_FIELD_NUMBER: _ClassVar[int]
    challenge: SandboxSessionClientChallenge
    open_result: SandboxSessionOpenResult
    data: SandboxSessionData
    credit: SandboxSessionCredit
    half_close: SandboxSessionHalfClose
    reset: SandboxSessionReset
    def __init__(self, challenge: _Optional[_Union[SandboxSessionClientChallenge, _Mapping]] = ..., open_result: _Optional[_Union[SandboxSessionOpenResult, _Mapping]] = ..., data: _Optional[_Union[SandboxSessionData, _Mapping]] = ..., credit: _Optional[_Union[SandboxSessionCredit, _Mapping]] = ..., half_close: _Optional[_Union[SandboxSessionHalfClose, _Mapping]] = ..., reset: _Optional[_Union[SandboxSessionReset, _Mapping]] = ...) -> None: ...
