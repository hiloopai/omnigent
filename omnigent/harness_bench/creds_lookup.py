"""Databricks workspace-host lookup for bench transports.

A thin ``~/.databrickscfg`` reader the full-server and native-tui drivers use to
skip-gate on a hostless profile. Kept package-local so the bench ships without a
test-tree dependency.
"""

from __future__ import annotations

import configparser
from pathlib import Path

_DATABRICKSCFG_PATH = Path.home() / ".databrickscfg"


def lookup_databricks_host(profile: str) -> str | None:
    """Return the workspace ``host`` for *profile* from ``~/.databrickscfg``.

    :param profile: The Databricks profile name to look up.
    :returns: The workspace host with any trailing ``/`` stripped, or ``None``
        when the profile is absent or the section has no ``host`` key.
    """
    cfg = configparser.ConfigParser()
    if _DATABRICKSCFG_PATH.exists():
        cfg.read(_DATABRICKSCFG_PATH)
    host = cfg[profile].get("host") if profile in cfg else None
    return host.rstrip("/") if host else None


__all__ = ["lookup_databricks_host"]
