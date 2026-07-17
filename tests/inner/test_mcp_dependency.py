"""Supported patched SDK range checks for the MCP runtime dependency."""

import ast
from importlib.metadata import version
from pathlib import Path

from packaging.specifiers import SpecifierSet
from packaging.version import Version

_ROOT = Path(__file__).resolve().parents[2]
_PRODUCTION_SOURCE_ROOTS = (
    _ROOT / "omnigent",
    _ROOT / "sdks/python-client/omnigent_client",
    _ROOT / "sdks/ui/omnigent_ui_sdk",
)
_SUPPORTED_PATCHED_MCP_RANGE = SpecifierSet(">=1.28.1,<2")
_DEPRECATED_SERVER_TRANSPORT = "mcp.server.websocket"


def _imports_deprecated_server_transport(tree: ast.AST) -> list[int]:
    lines: list[int] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import) and any(
            alias.name == _DEPRECATED_SERVER_TRANSPORT
            or alias.name.startswith(f"{_DEPRECATED_SERVER_TRANSPORT}.")
            for alias in node.names
        ):
            lines.append(node.lineno)
        elif isinstance(node, ast.ImportFrom):
            module = node.module or ""
            imports_module = module == _DEPRECATED_SERVER_TRANSPORT or module.startswith(
                f"{_DEPRECATED_SERVER_TRANSPORT}."
            )
            imports_from_parent = module == "mcp.server" and any(
                alias.name == "websocket" for alias in node.names
            )
            if imports_module or imports_from_parent:
                lines.append(node.lineno)
    return lines


def test_installed_mcp_is_in_supported_patched_sdk_range() -> None:
    assert Version(version("mcp")) in _SUPPORTED_PATCHED_MCP_RANGE


def test_production_avoids_deprecated_mcp_websocket_server_transport() -> None:
    """MCP 2 removes this non-standard transport; use streamable HTTP instead."""
    offenders: list[str] = []
    for source_root in _PRODUCTION_SOURCE_ROOTS:
        for path in source_root.rglob("*.py"):
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
            offenders.extend(
                f"{path.relative_to(_ROOT)}:{line}"
                for line in _imports_deprecated_server_transport(tree)
            )

    assert offenders == []
