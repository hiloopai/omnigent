#!/usr/bin/env python3
"""Static contracts for the fork-owned Hiloop OCI release."""

from __future__ import annotations

import json
import re
import shlex
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
DOCKERFILE = ROOT / "deploy/docker/Dockerfile"
WORKFLOW = ROOT / ".github/workflows/hiloop-release-images.yml"

EXPECTED_ENV = {
    "HOME": "/tmp",
    "IS_SANDBOX": "1",
    "OMNIGENT_BOOTSTRAP_EXEC": "/opt/venv/bin/omnigent",
    "PYTHONDONTWRITEBYTECODE": "1",
    "PYTHONUNBUFFERED": "1",
    "XDG_CACHE_HOME": "/tmp/.cache",
    "XDG_CONFIG_HOME": "/tmp/.config",
    "XDG_DATA_HOME": "/tmp/.local/share",
}
EXPECTED_ENTRYPOINT = [
    "/opt/venv/bin/python",
    "-m",
    "omnigent.onboarding.sandboxes.hiloop_bootstrap",
]


def _stage(source: str, name: str) -> str:
    match = re.search(rf"(?m)^FROM [^\n]+ AS {re.escape(name)}\s*$", source)
    if match is None:
        raise AssertionError(f"missing Dockerfile stage {name!r}")
    next_stage = re.search(r"(?m)^FROM ", source[match.end() :])
    end = len(source) if next_stage is None else match.end() + next_stage.start()
    return source[match.start() : end]


def _json_instruction(stage: str, instruction: str) -> object:
    match = re.search(rf"(?m)^{instruction} (.+)$", stage)
    if match is None:
        raise AssertionError(f"missing {instruction} instruction")
    return json.loads(match.group(1))


def _environment(stage: str) -> dict[str, str]:
    match = re.search(r"(?ms)^ENV (.+?)(?=^[A-Z]+ )", stage)
    if match is None:
        raise AssertionError("missing ENV instruction")
    tokens = shlex.split(match.group(1).replace("\\\n", " "))
    return dict(token.split("=", 1) for token in tokens)


class HiloopImageContractTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.dockerfile = DOCKERFILE.read_text(encoding="utf-8")
        cls.workflow = WORKFLOW.read_text(encoding="utf-8")
        cls.builder = _stage(cls.dockerfile, "builder")
        cls.generic_host = _stage(cls.dockerfile, "host")
        cls.hiloop_host = _stage(cls.dockerfile, "hiloop-host")
        cls.runtime = _stage(cls.dockerfile, "runtime")

    def test_generic_host_stays_provider_neutral(self) -> None:
        self.assertIn("WORKDIR /root", self.generic_host)
        self.assertEqual(_json_instruction(self.generic_host, "CMD"), ["sleep", "infinity"])
        self.assertNotRegex(self.generic_host, r"(?m)^ENTRYPOINT ")
        self.assertNotRegex(self.generic_host, r"(?m)^USER ")

    def test_builder_installs_the_reviewed_lock_without_resolution(self) -> None:
        self.assertIn("COPY pyproject.toml setup.py uv.lock uv.toml ./", self.builder)
        self.assertIn("uv sync --locked --active --no-dev --no-cache", self.builder)
        self.assertNotIn(
            "uv pip install --no-cache-dir --index-url ${PYPI_INDEX_URL} -e .",
            self.builder,
        )
        for package in ("openai", "openai-agents", "pydantic"):
            self.assertIn(f'"{package}"', self.builder)

    def test_hiloop_host_has_exact_runtime_config(self) -> None:
        self.assertTrue(self.hiloop_host.startswith("FROM host AS hiloop-host\n"))
        self.assertIn("groupadd --gid 1000 omnigent", self.hiloop_host)
        self.assertIn("useradd --uid 1000 --gid 1000 --no-create-home", self.hiloop_host)
        self.assertIn("--home-dir /tmp", self.hiloop_host)
        self.assertEqual(_environment(self.hiloop_host), EXPECTED_ENV)
        self.assertRegex(self.hiloop_host, r"(?m)^WORKDIR /$")
        self.assertRegex(self.hiloop_host, r"(?m)^USER 1000:1000$")
        self.assertEqual(_json_instruction(self.hiloop_host, "ENTRYPOINT"), EXPECTED_ENTRYPOINT)
        self.assertEqual(_json_instruction(self.hiloop_host, "CMD"), [])
        self.assertEqual(len(re.findall(r"(?m)^RUN ", self.hiloop_host)), 1)
        self.assertNotRegex(self.hiloop_host, r"(?m)^(?:ADD|COPY) ")

    def test_released_targets_are_unique_to_the_source_commit(self) -> None:
        revision_label = 'LABEL org.opencontainers.image.revision="${SOURCE_REVISION}"'
        for stage in (self.runtime, self.hiloop_host):
            self.assertRegex(stage, r"(?m)^ARG SOURCE_REVISION$")
            self.assertIn(revision_label, stage)

    def test_workflow_publishes_and_checks_final_host(self) -> None:
        self.assertIn("target: hiloop-host", self.workflow)
        self.assertNotRegex(self.workflow, r"(?m)^\s+target: host\s*$")
        self.assertIn("host-tag=native-host-%s-%s", self.workflow)
        self.assertNotIn("host-tag=base-", self.workflow)
        self.assertEqual(self.workflow.count("SOURCE_REVISION=${{ github.sha }}"), 2)
        self.assertEqual(
            self.workflow.count('.Labels["org.opencontainers.image.revision"] == $revision'),
            2,
        )
        self.assertIn('docker image inspect "$host_ref"', self.workflow)
        self.assertIn('.User == "1000:1000"', self.workflow)
        self.assertIn("((.Cmd // []) | length == 0)", self.workflow)
        self.assertIn('pwd.getpwuid(1000).pw_dir == "/tmp"', self.workflow)
        self.assertEqual(self.workflow.count('tomllib.load(open("/build/uv.lock", "rb"))'), 2)
        self.assertEqual(self.workflow.count("Usage().input_tokens_details.cached_tokens == 0"), 2)
        self.assertIn("cosign attest --type cyclonedx", self.workflow)
        self.assertIn("actions/attest-build-provenance@", self.workflow)
        self.assertIn('--source-digest "$GITHUB_SHA"', self.workflow)
        self.assertIn("--source-ref refs/heads/main", self.workflow)
        self.assertIn("refusing to create a multi-source digest", self.workflow)


if __name__ == "__main__":
    unittest.main()
