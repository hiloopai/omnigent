"""One-use loopback bootstrap for an Omnigent host in a Hiloop sandbox."""

from __future__ import annotations

import argparse
import json
import os
import re
import socket
import ssl
import struct
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any, NoReturn
from urllib.parse import urlsplit

from omnigent.host.identity import HOST_ID_ENV_VAR, HOST_NAME_ENV_VAR, HOST_TOKEN_ENV_VAR

BOOTSTRAP_SCHEMA = "omnigent.hiloop-bootstrap/v3"
DEFAULT_PORT = 17891
_MAX_FRAME_BYTES = 128 * 1024
MAX_SERVER_CA_BYTES = 64 * 1024
_IDENTIFIER = re.compile(r"[A-Za-z0-9._:-]{1,128}")
_CERTIFICATE_BODY = re.compile(r"[A-Za-z0-9+/=\r\n]+")
_CERTIFICATE_BEGIN = "-----BEGIN CERTIFICATE-----"
_CERTIFICATE_END = "-----END CERTIFICATE-----"
_PEM_WHITESPACE = " \t\r\n"
_LOOPBACK_HOSTS = frozenset({"localhost", "127.0.0.1", "::1"})
_MODEL_GATEWAY_TOKEN = "/var/run/secrets/hiloop/model-gateway/token"
_CONFIG_HOME = Path("/tmp/.omnigent")
_SERVER_CA_PATH = _CONFIG_HOME / "coordinator-server-ca.pem"
_SERVER_TRUST_BUNDLE_PATH = _CONFIG_HOME / "coordinator-server-trust.pem"


@dataclass(frozen=True, repr=False)
class BootstrapRequest:
    """Validated inputs needed to replace the bootstrap listener with a host."""

    token: str
    host_id: str
    host_name: str
    server_url: str
    workspace: str
    model_gateway_url: str
    model: str
    server_ca_pem: str


def write_frame(connection: socket.socket, payload: dict[str, str]) -> None:
    """Write one bounded length-prefixed JSON object."""
    connection.sendall(encode_frame(payload))


def encode_frame(payload: dict[str, str]) -> bytes:
    """Encode one complete bounded bootstrap frame."""
    encoded = json.dumps(payload, separators=(",", ":"), sort_keys=True).encode()
    if not encoded or len(encoded) > _MAX_FRAME_BYTES:
        raise ValueError("bootstrap frame is outside its byte limit")
    return struct.pack("!I", len(encoded)) + encoded


def read_frame(connection: socket.socket) -> dict[str, str]:
    """Read one bounded length-prefixed JSON object."""
    size = struct.unpack("!I", _read_exact(connection, 4))[0]
    if size == 0 or size > _MAX_FRAME_BYTES:
        raise ValueError("bootstrap frame is outside its byte limit")
    return _decode_payload(_read_exact(connection, size))


def decode_frame(frame: bytes) -> dict[str, str]:
    """Decode one complete bounded bootstrap frame with no trailing bytes."""
    if len(frame) < 4:
        raise ValueError("bootstrap frame is incomplete")
    size = struct.unpack("!I", frame[:4])[0]
    if size == 0 or size > _MAX_FRAME_BYTES:
        raise ValueError("bootstrap frame is outside its byte limit")
    if len(frame) != size + 4:
        raise ValueError("bootstrap frame is incomplete or has trailing bytes")
    return _decode_payload(frame[4:])


def _decode_payload(encoded: bytes) -> dict[str, str]:
    try:
        decoded: Any = json.loads(encoded)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError("bootstrap frame is not valid JSON") from exc
    if not isinstance(decoded, dict) or not all(
        isinstance(key, str) and isinstance(value, str) for key, value in decoded.items()
    ):
        raise ValueError("bootstrap frame must be a string-to-string object")
    return decoded


def exchange(connection: socket.socket, payload: dict[str, str]) -> None:
    """Deliver one launch request and require an accepted response."""
    write_frame(connection, payload)
    response = read_frame(connection)
    if response != {"schema": BOOTSTRAP_SCHEMA, "status": "accepted"}:
        raise RuntimeError("sandbox rejected the Omnigent bootstrap request")


def validate_request(payload: dict[str, str]) -> BootstrapRequest:
    """Validate a launch request without retaining unknown fields."""
    required = {
        "schema",
        "token",
        "host_id",
        "host_name",
        "server_url",
        "workspace",
        "model_gateway_url",
        "model",
        "server_ca_pem",
    }
    if set(payload) != required or payload.get("schema") != BOOTSTRAP_SCHEMA:
        raise ValueError("bootstrap request has an invalid schema")

    token = payload["token"]
    if not 16 <= len(token) <= 4096 or any(character.isspace() for character in token):
        raise ValueError("bootstrap token is invalid")
    for field in ("host_id", "host_name"):
        if _IDENTIFIER.fullmatch(payload[field]) is None:
            raise ValueError(f"bootstrap {field} is invalid")

    server_url = _server_url(payload["server_url"])
    workspace = _workspace(payload["workspace"])
    model_gateway_url = validate_model_gateway_url(payload["model_gateway_url"])
    model = validate_model(payload["model"])
    server_ca_pem = validate_server_ca_pem(payload["server_ca_pem"])
    return BootstrapRequest(
        token=token,
        host_id=payload["host_id"],
        host_name=payload["host_name"],
        server_url=server_url,
        workspace=workspace,
        model_gateway_url=model_gateway_url,
        model=model,
        server_ca_pem=server_ca_pem,
    )


def serve_once(*, port: int = DEFAULT_PORT, timeout_s: float = 120.0) -> NoReturn:
    """Accept one loopback launch request, acknowledge it, then exec the host."""
    if not 1 <= port <= 65535 or timeout_s <= 0:
        raise ValueError("bootstrap listener options are invalid")
    listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    with listener:
        listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        listener.bind(("127.0.0.1", port))
        listener.listen(1)
        listener.settimeout(timeout_s)
        connection, _ = listener.accept()
        with connection:
            connection.settimeout(timeout_s)
            request = validate_request(read_frame(connection))
            _prepare_provider_config(request)
            write_frame(connection, {"schema": BOOTSTRAP_SCHEMA, "status": "accepted"})
    _exec_host(request)


def _read_exact(connection: socket.socket, size: int) -> bytes:
    chunks = bytearray()
    while len(chunks) < size:
        chunk = connection.recv(size - len(chunks))
        if not chunk:
            raise ValueError("bootstrap connection closed before a complete frame")
        chunks.extend(chunk)
    return bytes(chunks)


def _server_url(value: str) -> str:
    try:
        parsed = urlsplit(value)
        _ = parsed.port
    except ValueError as exc:
        raise ValueError("bootstrap server URL is invalid") from exc
    if not parsed.hostname or parsed.scheme not in {"http", "https"}:
        raise ValueError("bootstrap server URL is invalid")
    if parsed.scheme == "http" and parsed.hostname not in _LOOPBACK_HOSTS:
        raise ValueError("bootstrap server URL must use TLS")
    if (
        parsed.username is not None
        or parsed.password is not None
        or parsed.query
        or parsed.fragment
    ):
        raise ValueError("bootstrap server URL is invalid")
    return value.rstrip("/")


def _workspace(value: str) -> str:
    path = PurePosixPath(value)
    if not path.is_absolute() or ".." in path.parts:
        raise ValueError("bootstrap workspace is invalid")
    root = PurePosixPath("/workspace")
    if path != root and root not in path.parents:
        raise ValueError("bootstrap workspace must be inside /workspace")
    return str(path)


def validate_model_gateway_url(value: str) -> str:
    """Require a credential-free Responses API base URL."""
    try:
        parsed = urlsplit(value)
        _ = parsed.port
    except ValueError as exc:
        raise ValueError("bootstrap model gateway URL is invalid") from exc
    host = parsed.hostname or ""
    in_cluster = host.endswith((".svc", ".svc.cluster.local"))
    if not host or parsed.scheme not in {"http", "https"}:
        raise ValueError("bootstrap model gateway URL is invalid")
    if parsed.scheme == "http" and host not in _LOOPBACK_HOSTS and not in_cluster:
        raise ValueError("bootstrap model gateway URL must use TLS or cluster-local DNS")
    if parsed.path not in {"/v1", "/v1/"}:
        raise ValueError("bootstrap model gateway URL must end at /v1")
    if (
        parsed.username is not None
        or parsed.password is not None
        or parsed.query
        or parsed.fragment
    ):
        raise ValueError("bootstrap model gateway URL is invalid")
    return value.rstrip("/")


def validate_model(value: str) -> str:
    """Require one bounded provider model identifier."""
    if _IDENTIFIER.fullmatch(value) is None:
        raise ValueError("bootstrap model is invalid")
    return value


def validate_server_ca_pem(value: str) -> str:
    """Validate one optional, bounded coordinator-server CA bundle."""
    if not value:
        return ""
    try:
        encoded = value.encode("ascii")
    except UnicodeEncodeError as exc:
        raise ValueError("bootstrap coordinator server CA must be ASCII PEM") from exc
    if len(encoded) > MAX_SERVER_CA_BYTES:
        raise ValueError("bootstrap coordinator server CA exceeds 64 KiB")
    blocks = _certificate_blocks(value)
    context = ssl.create_default_context()
    for block in blocks:
        try:
            context.load_verify_locations(cadata=block)
        except (OSError, ssl.SSLError) as exc:
            raise ValueError("bootstrap coordinator server CA must be a PEM trust bundle") from exc
    return value


def _certificate_blocks(value: str) -> tuple[str, ...]:
    """Consume a certificate-only PEM bundle in linear time."""
    blocks: list[str] = []
    cursor = 0
    while cursor < len(value):
        start = value.find(_CERTIFICATE_BEGIN, cursor)
        if start < 0:
            if value[cursor:].strip(_PEM_WHITESPACE):
                raise ValueError("bootstrap coordinator server CA must contain certificates only")
            break
        if value[cursor:start].strip(_PEM_WHITESPACE):
            raise ValueError("bootstrap coordinator server CA must contain certificates only")
        body_start = start + len(_CERTIFICATE_BEGIN)
        end = value.find(_CERTIFICATE_END, body_start)
        if end < 0 or _CERTIFICATE_BODY.fullmatch(value[body_start:end]) is None:
            raise ValueError("bootstrap coordinator server CA must contain certificates only")
        cursor = end + len(_CERTIFICATE_END)
        blocks.append(value[start:cursor])
    if not blocks:
        raise ValueError("bootstrap coordinator server CA must contain certificates only")
    return tuple(blocks)


def _write_provider_config(request: BootstrapRequest, config_home: Path = _CONFIG_HOME) -> None:
    """Write non-secret model routing whose auth helper reads the projected token."""
    config_home.mkdir(mode=0o700, parents=False, exist_ok=False)
    config = {
        "providers": {
            "hiloop": {
                "kind": "gateway",
                "default": True,
                "openai": {
                    "base_url": request.model_gateway_url,
                    "auth_command": f"cat {_MODEL_GATEWAY_TOKEN}",
                    "wire_api": "responses",
                    "models": {"default": request.model},
                },
            }
        }
    }
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
    for optional_flag in ("O_CLOEXEC", "O_NOFOLLOW"):
        flags |= getattr(os, optional_flag, 0)
    path = config_home / "config.yaml"
    descriptor = os.open(path, flags, 0o600)
    with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
        json.dump(config, stream, separators=(",", ":"), sort_keys=True)
        stream.write("\n")


def _write_server_trust(request: BootstrapRequest, config_home: Path = _CONFIG_HOME) -> None:
    """Augment system roots with the proof-delivered coordinator CA."""
    if not request.server_ca_pem:
        return
    context = ssl.create_default_context()
    try:
        context.load_verify_locations(cadata=request.server_ca_pem)
    except (OSError, ssl.SSLError) as exc:  # defensive: validation ran before filesystem writes
        raise RuntimeError("coordinator server CA trust preparation failed") from exc
    certificates = context.get_ca_certs(binary_form=True)
    if not certificates:
        raise RuntimeError("coordinator server CA produced an empty trust bundle")
    combined = b"".join(
        ssl.DER_cert_to_PEM_cert(certificate).encode("ascii") for certificate in certificates
    )
    _write_private_file(
        config_home / _SERVER_CA_PATH.name,
        request.server_ca_pem.encode("ascii"),
    )
    _write_private_file(config_home / _SERVER_TRUST_BUNDLE_PATH.name, combined)


def _write_private_file(path: Path, content: bytes) -> None:
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
    for optional_flag in ("O_CLOEXEC", "O_NOFOLLOW"):
        flags |= getattr(os, optional_flag, 0)
    descriptor = os.open(path, flags, 0o600)
    with os.fdopen(descriptor, "wb") as stream:
        stream.write(content)


def _prepare_provider_config(request: BootstrapRequest) -> None:
    token_path = Path(_MODEL_GATEWAY_TOKEN)
    if not token_path.is_file() or not os.access(token_path, os.R_OK):
        raise RuntimeError("projected model gateway identity is unavailable")
    _write_provider_config(request)
    _write_server_trust(request)


def _exec_host(request: BootstrapRequest) -> NoReturn:
    os.chdir(request.workspace)
    environment = os.environ.copy()
    environment.update(
        {
            HOST_TOKEN_ENV_VAR: request.token,
            HOST_ID_ENV_VAR: request.host_id,
            HOST_NAME_ENV_VAR: request.host_name,
            "HOME": "/tmp",
            "IS_SANDBOX": "1",
            "OMNIGENT_CONFIG_HOME": str(_CONFIG_HOME),
            "XDG_CACHE_HOME": "/tmp/.cache",
            "XDG_CONFIG_HOME": "/tmp/.config",
            "XDG_DATA_HOME": "/tmp/.local/share",
        }
    )
    if request.server_ca_pem:
        trust_bundle = str(_SERVER_TRUST_BUNDLE_PATH)
        environment.update(
            {
                "SSL_CERT_FILE": trust_bundle,
                "REQUESTS_CA_BUNDLE": trust_bundle,
                "CURL_CA_BUNDLE": trust_bundle,
                "GIT_SSL_CAINFO": trust_bundle,
                "GRPC_DEFAULT_SSL_ROOTS_FILE_PATH": trust_bundle,
                "NODE_EXTRA_CA_CERTS": str(_SERVER_CA_PATH),
            }
        )
    executable = os.environ.get("OMNIGENT_BOOTSTRAP_EXEC", "omnigent")
    os.execvpe(executable, [executable, "host", "--server", request.server_url], environment)


def main() -> NoReturn:
    parser = argparse.ArgumentParser(description="Bootstrap one Omnigent host over loopback")
    parser.add_argument("--port", type=int, default=DEFAULT_PORT)
    parser.add_argument("--timeout", type=float, default=120.0)
    args = parser.parse_args()
    serve_once(port=args.port, timeout_s=args.timeout)


if __name__ == "__main__":
    main()
