"""Security floor checks for the MCP runtime dependency."""

from importlib.metadata import version

from packaging.version import Version


def test_installed_mcp_has_websocket_origin_validation_fix() -> None:
    """CVE-2026-59950 is fixed in mcp 1.28.1 and later."""
    assert Version(version("mcp")) >= Version("1.28.1")
