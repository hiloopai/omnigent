"""File-backed session-sharing policy override for the OSS server.

The server-wide sharing mode (see :class:`SharingMode`) defaults from the
``OMNIGENT_SHARING_MODE`` env var at boot, but an admin can override it at
runtime from the Settings → Sharing panel. That override is persisted to a
plaintext ``<data_dir>/sharing_mode`` file (next to the ``admins`` roster) so
it survives restarts without a database migration and takes effect without a
redeploy.

File format: a single line holding the mode value — ``on`` / ``read_only`` /
``restricted_read_only`` / ``off``. A missing, empty, or unreadable file means
"no override recorded", so the caller falls back to the env-var default; an
unrecognized value is likewise ignored (falling back rather than silently
disabling sharing). The read is mtime-cached so the per-request hot path is
cheap, mirroring the ``admins`` roster loader.
"""

from __future__ import annotations

import contextlib
import logging
import os
import tempfile
from pathlib import Path

from omnigent.server.admin_list import resolve_data_dir
from omnigent.server.auth import SharingMode

logger = logging.getLogger(__name__)

_OVERRIDE_FILENAME = "sharing_mode"

# mtime cache keyed on (path, mtime) so a data-dir change (e.g. across tests)
# never reads through a stale entry. The third element is the parsed override,
# or ``None`` for "file present but no usable value".
_cache: tuple[str, float, SharingMode | None] | None = None


def resolve_sharing_mode_path() -> Path:
    """Path of the file holding the admin sharing-mode override."""
    return resolve_data_dir() / _OVERRIDE_FILENAME


def read_sharing_mode_override() -> SharingMode | None:
    """Return the admin-set sharing-mode override, or ``None`` when unset.

    mtime-cached. A missing/empty/unreadable file or an unrecognized value
    yields ``None`` — the caller then falls back to the env-var default rather
    than silently changing behavior.
    """
    global _cache
    path = resolve_sharing_mode_path()
    key = str(path)
    try:
        mtime = path.stat().st_mtime
    except OSError:
        return None
    if _cache is not None and _cache[0] == key and _cache[1] == mtime:
        return _cache[2]
    try:
        raw = path.read_text(encoding="utf-8").strip()
    except OSError:
        return None
    value: SharingMode | None
    try:
        value = SharingMode(raw.lower()) if raw else None
    except ValueError:
        logger.warning("Ignoring unrecognized sharing_mode override %r in %s", raw, path)
        value = None
    _cache = (key, mtime, value)
    return value


def write_sharing_mode_override(mode: SharingMode) -> None:
    """Persist the admin sharing-mode override atomically.

    Writes to a temp file in the data dir and ``os.replace``s it into place so
    a concurrent :func:`read_sharing_mode_override` never sees a half-written
    file. Invalidates the cache so the next read reflects the change.
    """
    global _cache
    path = resolve_sharing_mode_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=str(path.parent), prefix=".sharing_mode.")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(mode.value + "\n")
        os.replace(tmp, path)
    except OSError:
        with contextlib.suppress(OSError):
            os.unlink(tmp)
        raise
    _cache = None
