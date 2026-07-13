"""Async queue-based telemetry emitter.

Errors are silently swallowed — telemetry must never disrupt the
application.  All opt-out signals are checked in :func:`is_disabled`.

Wire format (matches the API Gateway / Kinesis ingestion schema):

    POST OMNIGENT_TELEMETRY_ENDPOINT
    {
        "records": [
            {
                "data": {
                    "event_name": "SessionCreatedEvent",
                    "session_id": "<telemetry-session-uuid>",
                    "omnigent_version": "0.4.2",
                    "schema_version": 1,
                    "python_version": "3.12.3",
                    "operating_system": "Linux",
                    "timestamp_ns": 1720000000000000000,
                    "status": "success",
                    "duration_ms": 0,
                    "installation_id": "<uuid>",
                    "environment": null,
                    "params": "{\"agent_id\": \"...\", ...}"
                },
                "partition-key": "<random-uuid>"
            }
        ]
    }

``session_id`` is a per-process UUID that groups all events from one
server run — it is NOT the Omnigent conversation id (which goes in
``params``).  ``params`` is a JSON-encoded string of event-specific
fields.  ``additionalProperties: false`` on the gateway means any field
not in the schema above will cause a 400, so event-specific data must
live in ``params``.
"""

from __future__ import annotations

import atexit
import json
import logging
import os
import platform
import queue
import sys
import threading
import time
import uuid
from dataclasses import asdict
from typing import Any

from omnigent.version import VERSION

_logger = logging.getLogger(__name__)

# CI / test environment variable names that indicate telemetry should be off.
_CI_ENV_VARS = frozenset(
    {
        "CI",
        "GITHUB_ACTIONS",
        "PYTEST_CURRENT_TEST",
        "CIRCLECI",
        "JENKINS_URL",
        "TRAVIS",
        "GITLAB_CI",
        "TF_BUILD",
        "BITBUCKET_BUILD_NUMBER",
        "CODEBUILD_BUILD_ARN",
        "BUILDKITE",
        "TEAMCITY_VERSION",
    }
)

_BATCH_SIZE = 50
_BATCH_INTERVAL_S = 30.0
_MAX_QUEUE_SIZE = 512
_SCHEMA_VERSION = 1

# Per-process telemetry session ID — groups all events from one server run.
_TELEMETRY_SESSION_ID: str = str(uuid.uuid4())


def is_disabled() -> bool:
    """Return ``True`` when telemetry should be completely suppressed.

    Checks (in order):
    1. ``OMNIGENT_TELEMETRY=0``
    2. ``OMNIGENT_DISABLE_TELEMETRY=true`` (any truthy spelling)
    3. ``DO_NOT_TRACK=1``
    4. Any CI environment variable from :data:`_CI_ENV_VARS`

    Always returns a ``bool``; never raises.
    """
    try:
        if os.environ.get("OMNIGENT_TELEMETRY", "").strip() == "0":
            return True
        dnt_val = os.environ.get("OMNIGENT_DISABLE_TELEMETRY", "").strip().lower()
        if dnt_val in ("1", "true", "yes"):
            return True
        if os.environ.get("DO_NOT_TRACK", "").strip() == "1":
            return True
        return any(var in os.environ for var in _CI_ENV_VARS)
    except Exception:
        return True


def _detect_environment() -> str | None:
    """Return a short environment tag or ``None`` for plain installs."""
    try:
        checks: list[tuple[str, str]] = [
            ("KAGGLE_KERNEL_RUN_TYPE", "kaggle"),
            ("COLAB_BACKEND_VERSION", "colab"),
            ("AZUREML_ARM_WORKSPACE_NAME", "azure_ml"),
            ("SM_CURRENT_HOST", "sagemaker_studio"),
        ]
        for env_var, tag in checks:
            if os.environ.get(env_var):
                return tag
        # Docker: /.dockerenv exists in containers
        if os.path.exists("/.dockerenv"):
            return "docker"
        return None
    except Exception:
        return None


def _build_record(event: object) -> dict[str, Any]:
    """Serialise *event* into the gateway ``data`` envelope.

    Event-specific fields (everything except ``installation_id``) are
    JSON-encoded into the ``params`` string so the gateway schema's
    ``additionalProperties: false`` constraint is satisfied.
    """
    fields: dict[str, Any] = asdict(event)  # type: ignore[arg-type]
    installation_id: str | None = fields.pop("installation_id", None)

    # All remaining event-specific fields go into params as a JSON string.
    params_str: str | None = None
    if fields:
        params_str = json.dumps(fields, default=str)
        if len(params_str) > 1000:
            params_str = params_str[:997] + "..."

    data: dict[str, Any] = {
        "event_name": type(event).__name__,
        "session_id": _TELEMETRY_SESSION_ID,
        "omnigent_version": VERSION,
        "schema_version": _SCHEMA_VERSION,
        "python_version": sys.version.split()[0],
        "operating_system": platform.system(),
        "timestamp_ns": time.time_ns(),
        "status": "success",
        "duration_ms": 0,
        "installation_id": installation_id,
        "environment": _detect_environment(),
        "params": params_str,
    }
    return {
        "data": data,
        "partition-key": str(uuid.uuid4()),
    }


class TelemetryClient:
    """Fire-and-forget telemetry emitter backed by a background thread.

    Events are serialised into the gateway wire format and placed on an
    in-memory queue.  A single daemon thread consumes the queue and POSTs
    batches to ``OMNIGENT_TELEMETRY_ENDPOINT`` when that variable is set.
    If the variable is absent the queue is drained silently (useful for
    testing that instrumentation fires without a live endpoint).

    All errors in the background thread are suppressed.
    """

    def __init__(self) -> None:
        self._endpoint: str | None = os.environ.get("OMNIGENT_TELEMETRY_ENDPOINT")
        self._queue: queue.Queue[dict[str, Any] | None] = queue.Queue(maxsize=_MAX_QUEUE_SIZE)
        self._lock = threading.Lock()
        self._started = False
        self._stopped = False
        self._atexit_registered = False
        self._thread: threading.Thread | None = None

    # ── Public interface ─────────────────────────────────

    def emit(self, event: object) -> None:
        """Queue an event for async delivery.

        Accepts any dataclass; converts it to the gateway wire format.
        Silently no-ops when disabled or stopped.

        :param event: A dataclass instance, e.g. :class:`SessionCreatedEvent`.
        """
        if self._stopped:
            return
        # Defense-in-depth: re-check opt-out inside the client so
        # a late env-var change is respected even if the call site
        # skipped the module-level is_disabled() guard.
        if is_disabled():
            return
        try:
            record = _build_record(event)
            self._ensure_started()
            try:
                self._queue.put_nowait(record)
            except queue.Full:
                pass  # queue full — drop event; telemetry must never block
        except Exception:
            _logger.debug("Telemetry emit failed; dropping event", exc_info=True)

    def flush(self) -> None:
        """Block until the queue is empty (used in tests and at shutdown)."""
        try:
            self._queue.join()
        except Exception:
            pass  # best-effort flush; never raise from telemetry

    def shutdown(self) -> None:
        """Signal the background thread to stop and wait briefly."""
        if self._stopped:
            return
        self._stopped = True
        try:
            self._queue.put_nowait(None)  # poison pill
        except Exception:
            pass  # queue may be full/closed; best-effort shutdown
        if self._thread is not None:
            self._thread.join(timeout=2.0)

    # ── Internal helpers ─────────────────────────────────

    def _ensure_started(self) -> None:
        if self._started:
            return
        with self._lock:
            if self._started:
                return
            self._thread = threading.Thread(
                target=self._consumer,
                name="OmnigentTelemetryConsumer",
                daemon=True,
            )
            self._thread.start()
            self._started = True
            if not self._atexit_registered:
                atexit.register(self._atexit_callback)
                self._atexit_registered = True

    def _atexit_callback(self) -> None:
        try:
            self.shutdown()
        except Exception:
            pass  # best-effort shutdown at process exit; telemetry must never disrupt termination

    def _consumer(self) -> None:
        """Background thread: drain the queue in batches."""
        pending: list[dict[str, Any]] = []
        last_flush = time.monotonic()

        while not self._stopped:
            try:
                item = self._queue.get(timeout=1.0)
            except queue.Empty:
                if pending and time.monotonic() - last_flush >= _BATCH_INTERVAL_S:
                    self._send(pending)
                    pending = []
                    last_flush = time.monotonic()
                continue

            if item is None:
                # Poison pill — flush what we have, then exit.
                if pending:
                    self._send(pending)
                self._queue.task_done()
                break

            pending.append(item)
            self._queue.task_done()

            if len(pending) >= _BATCH_SIZE or time.monotonic() - last_flush >= _BATCH_INTERVAL_S:
                self._send(pending)
                pending = []
                last_flush = time.monotonic()

        # Drain remaining on stop.
        while not self._queue.empty():
            try:
                item = self._queue.get_nowait()
                if item is not None:
                    pending.append(item)
                self._queue.task_done()
            except queue.Empty:
                break
        if pending:
            self._send(pending)

    def _send(self, records: list[dict[str, Any]]) -> None:
        """POST a batch to the configured endpoint, or no-op if unset."""
        if not self._endpoint or not records:
            return
        try:
            import urllib.request

            body = json.dumps({"records": records}).encode("utf-8")
            req = urllib.request.Request(
                self._endpoint,
                data=body,
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            with urllib.request.urlopen(req, timeout=3) as resp:
                resp.read()
        except Exception:
            _logger.debug("Telemetry send failed; dropping batch", exc_info=True)


# ── Module-level singleton ───────────────────────────────

_CLIENT: TelemetryClient | None = None
_CLIENT_LOCK = threading.Lock()


def get_client() -> TelemetryClient | None:
    """Return the active singleton client, or ``None`` when disabled."""
    return _CLIENT


def init_client() -> None:
    """Initialise the module-level client if telemetry is enabled.

    Safe to call multiple times; idempotent after the first call.
    """
    global _CLIENT
    if is_disabled():
        return
    # Prime the installation-id cache on startup so later request
    # handlers do not perform synchronous file I/O on the event loop.
    try:
        from omnigent.telemetry.installation_id import get_installation_id

        get_installation_id()
    except Exception:
        _logger.debug("Telemetry installation-id prime failed", exc_info=True)
    with _CLIENT_LOCK:
        if _CLIENT is None:
            try:
                _CLIENT = TelemetryClient()
            except Exception:
                pass


def emit(event: object) -> None:
    """Emit an event through the module-level client.

    No-op when telemetry is disabled or the client is not initialised.
    Never raises.

    :param event: A dataclass instance.
    """
    try:
        if is_disabled():
            return
        client = _CLIENT
        if client is not None:
            client.emit(event)
    except Exception:
        _logger.debug(
            "Telemetry emit failed; swallowing to avoid disrupting application", exc_info=True
        )
