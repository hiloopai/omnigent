"""Cheap "is this CLI runnable?" probe for harness skip-gating.

A harness whose vendor CLI is missing or broken should SKIP cleanly rather than
fail deep inside an executor. Both the bench drivers and the e2e parametrize
gate (:func:`tests.e2e._harness_probes.skip_if_harness_cli_missing`) call
:func:`cli_unavailable_reason` for that decision, so it lives here in the shipped
package and the test tree re-imports it.
"""

from __future__ import annotations

import shutil
import subprocess
from functools import cache


def _cli_probe_args(binary: str) -> list[str]:
    """Return a cheap command that proves *binary* is runnable."""
    if binary == "pi":
        # ``shutil.which("pi")`` alone is not enough: pi's npm package
        # may be installed under an older Node version than the package
        # supports. ``pi --help`` exercises module loading without making
        # model/network calls, so it catches broken installs early and lets
        # rows skip instead of failing deep inside ``PiExecutor``.
        return [binary, "--help"]
    return [binary, "--version"]


@cache
def cli_unavailable_reason(binary: str) -> str | None:
    """
    Return ``None`` when *binary* exists and starts, else a skip reason.

    The result is cached because callers gate many rows off it and CLI
    startup can be non-trivial.
    """
    path = shutil.which(binary)
    if path is None:
        return f"{binary!r} CLI is not on PATH"

    try:
        proc = subprocess.run(
            _cli_probe_args(binary),
            capture_output=True,
            text=True,
            timeout=15,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        return f"{binary!r} CLI at {path!r} is not runnable: {exc}"

    if proc.returncode != 0:
        detail = (proc.stderr or proc.stdout).strip().splitlines()
        suffix = f": {detail[0]}" if detail else ""
        return f"{binary!r} CLI at {path!r} exits {proc.returncode}{suffix}"
    return None


__all__ = ["cli_unavailable_reason"]
