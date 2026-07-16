"""Generate the checked-in Python bindings for Hiloop sandbox sessions.

The source schema mirrors Hiloop's public ``sandbox_session.proto`` contract.
Generated code is committed so runtime images need grpcio but never protoc or
the Hiloop CLI binary.
"""

from __future__ import annotations

import argparse
import filecmp
import subprocess
import sys
import tempfile
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent.parent
_PROTO = Path("omnigent/api/hiloop/v1/sandbox_session.proto")
_OUTPUTS = (
    Path("omnigent/api/hiloop/v1/sandbox_session_pb2.py"),
    Path("omnigent/api/hiloop/v1/sandbox_session_pb2.pyi"),
    Path("omnigent/api/hiloop/v1/sandbox_session_pb2_grpc.py"),
)


def _run_protoc(out_dir: Path) -> None:
    command = [
        sys.executable,
        "-m",
        "grpc_tools.protoc",
        f"--proto_path={_REPO_ROOT}",
        f"--python_out={out_dir}",
        f"--pyi_out={out_dir}",
        f"--grpc_python_out={out_dir}",
        str(_PROTO),
    ]
    try:
        subprocess.run(command, check=True, cwd=_REPO_ROOT)
    except FileNotFoundError:
        raise SystemExit(
            "grpc_tools.protoc not found. Install the dev dependencies first:\n"
            "  uv sync --extra dev"
        ) from None


def _generate() -> int:
    _run_protoc(_REPO_ROOT)
    print(f"Generated {', '.join(str(path) for path in _OUTPUTS)}")
    return 0


def _check() -> int:
    with tempfile.TemporaryDirectory() as temporary:
        generated_root = Path(temporary)
        _run_protoc(generated_root)
        stale = [
            path
            for path in _OUTPUTS
            if not (generated_root / path).exists()
            or not (_REPO_ROOT / path).exists()
            or not filecmp.cmp(
                generated_root / path,
                _REPO_ROOT / path,
                shallow=False,
            )
        ]
    if stale:
        names = ", ".join(str(path) for path in stale)
        print(
            f"Hiloop session protobuf bindings are out of date: {names}\n"
            "Regenerate and commit them:\n"
            "  python scripts/gen_hiloop_session_pb2.py",
            file=sys.stderr,
        )
        return 1
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--check",
        action="store_true",
        help="verify the committed bindings match the schema without writing",
    )
    arguments = parser.parse_args()
    return _check() if arguments.check else _generate()


if __name__ == "__main__":
    raise SystemExit(main())
