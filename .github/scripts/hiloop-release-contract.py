#!/usr/bin/env python3
"""Contracts for the fork-owned Hiloop OCI release."""

from __future__ import annotations

import json
import os
import re
import shlex
import shutil
import subprocess
import sys
import tempfile
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

MOCK_RELEASE_TOOLS = r"""#!/usr/bin/env python3
import json
import os
import sys
from pathlib import Path

tool = Path(sys.argv[0]).name
args = sys.argv[1:]
if tool == "trivy":
    if "--output" in args:
        Path(args[args.index("--output") + 1]).write_text(
            '{"bomFormat":"CycloneDX","components":[]}'
        )
elif tool == "cosign":
    assert args[0] in ("verify", "verify-attestation"), args
elif tool == "gh":
    assert args[:2] == ["attestation", "verify"], args
    assert args[2].startswith("oci://registry.invalid/hiloop/omnigent-"), args
    assert args[2].endswith("@sha256:" + "b" * 64), args
    assert "--bundle-from-oci" in args, args
    assert args[args.index("--predicate-type") + 1] == "https://slsa.dev/provenance/v1"
    repo = args[args.index("--repo") + 1]
    assert repo in ("hiloopai/omnigent", "autoresearchinc/omnigent"), args
    with Path(os.environ["MOCK_GH_LOG"]).open("a") as log:
        log.write(json.dumps(args) + "\n")
    case = json.loads(Path(os.environ["MOCK_RELEASE_CASE"]).read_text())
    if repo not in case["results"]:
        sys.exit(1)
    if "--format" in args:
        assert args[args.index("--format") + 1] == "json"
        print(json.dumps(case["results"][repo]))
    else:
        assert args[args.index("--source-digest") + 1] == os.environ["GITHUB_SHA"]
        assert args[args.index("--source-ref") + 1] == "refs/heads/main"
        if case.get("reject_strict"):
            sys.exit(1)
else:
    raise AssertionError(tool)
"""


def _workflow_run(marker: str) -> str:
    workflow = WORKFLOW.read_text(encoding="utf-8")
    start = workflow.index("        run: |\n", workflow.index(marker))
    lines = []
    for line in workflow[start + len("        run: |\n") :].splitlines():
        if line.startswith("          "):
            lines.append(line[10:])
        elif not line.strip():
            lines.append("")
        else:
            break
    return "\n".join(lines)


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
        for package in ("mcp", "openai", "openai-agents", "pydantic"):
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

    def test_workflow_publish_namespace_is_exact(self) -> None:
        guard = re.search(r"(?m)^  publish:\n    if: ([^\n]+)$", self.workflow)
        self.assertIsNotNone(guard)
        expected = (
            "github.repository_id == '1303106334' && "
            "github.repository_owner_id == '291932505' && "
            "(github.repository == 'hiloopai/omnigent' || "
            "github.repository == 'autoresearchinc/omnigent') && "
            "github.ref == 'refs/heads/main'"
        )
        self.assertEqual(guard.group(1), expected)
        self.assertIn(f'grep -Fq "{expected}" "$workflow"', self.workflow)
        gate = self.workflow.index("- name: Enforce exact release source")
        self.assertLess(
            gate, self.workflow.index("- uses: aws-actions/configure-aws-credentials@")
        )
        for check in (
            "[[ \"$RELEASE_REPOSITORY_ID\" == '1303106334' ]]",
            "[[ \"$RELEASE_OWNER_ID\" == '291932505' ]]",
            "[[ \"$RELEASE_REPOSITORY\" == 'hiloopai/omnigent' || "
            "\"$RELEASE_REPOSITORY\" == 'autoresearchinc/omnigent' ]]",
            "[[ \"$RELEASE_REF\" == 'refs/heads/main' ]]",
        ):
            self.assertIn(check, self.workflow)

    def test_workflow_release_identity_accepts_only_approved_names(self) -> None:
        identity = re.search(r"(?m)^\s+identity_re='([^']+)'$", self.workflow)
        self.assertIsNotNone(identity)
        self.assertTrue(identity.group(1).startswith("^"))
        self.assertTrue(identity.group(1).endswith("$"))
        pattern = re.compile(identity.group(1))
        path = "/omnigent/.github/workflows/hiloop-release-images.yml@refs/heads/main"
        for owner in ("hiloopai", "autoresearchinc"):
            with self.subTest(owner=owner):
                self.assertIsNotNone(pattern.search(f"https://github.com/{owner}{path}"))
        valid = f"https://github.com/autoresearchinc{path}"
        rejected = (
            valid.replace("autoresearchinc", "untrusted"),
            valid.replace("autoresearchinc", "autoresearchinc-extra"),
            valid.replace("autoresearchinc", "hiloopai-extra"),
            valid.replace("/omnigent/", "/omnigent-fork/"),
            valid.replace("/.github/", "/xgithub/"),
            valid.replace("hiloop-release-images.yml", "other.yml"),
            valid.replace("images.yml", "imagesXyml"),
            valid.replace("refs/heads/main", "refs/heads/dev"),
            valid.replace("refs/heads/main", "refs/tags/main"),
            valid.replace("refs/heads/main", "refs/pull/1/merge"),
            valid.replace("github.com", "githubXcom"),
            valid.replace("https://", "http://"),
            "prefix" + valid,
            valid + "/extra",
        )
        for untrusted in rejected:
            with self.subTest(identity=untrusted):
                self.assertIsNone(pattern.search(untrusted))

    def test_workflow_checks_provenance_across_both_approved_names(self) -> None:
        self.assertIn(
            "for provenance_repo in hiloopai/omnigent autoresearchinc/omnigent; do",
            self.workflow,
        )
        self.assertNotIn('--repo "$GITHUB_REPOSITORY"', self.workflow)
        self.assertEqual(self.workflow.count('--repo "$provenance_repo"'), 2)
        self.assertIn("'$existing + $verified'", self.workflow)
        self.assertIn('for provenance_repo in "${provenance_repos[@]}"; do', self.workflow)

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


class HiloopReleaseWorkflowExecutionTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.source_gate = _workflow_run("- name: Enforce exact release source")
        cls.secure = _workflow_run("      - id: secure\n")
        cls.bash = shutil.which("bash")
        cls.jq = shutil.which("jq")
        if cls.bash is None or cls.jq is None:
            raise AssertionError("release contract tests require bash and jq")

    def test_publisher_gate_accepts_only_exact_repository_owner_and_main(self) -> None:
        approved = {
            "RELEASE_REPOSITORY": "hiloopai/omnigent",
            "RELEASE_REPOSITORY_ID": "1303106334",
            "RELEASE_OWNER_ID": "291932505",
            "RELEASE_REF": "refs/heads/main",
        }
        cases = [(approved, True)]
        cases.append(({**approved, "RELEASE_REPOSITORY": "autoresearchinc/omnigent"}, True))
        for field, invalid in (
            ("RELEASE_REPOSITORY", "outsider/omnigent"),
            ("RELEASE_REPOSITORY", "autoresearchinc/omnigent-fork"),
            ("RELEASE_REPOSITORY", "hiloopai-extra/omnigent"),
            ("RELEASE_REPOSITORY_ID", "1303106335"),
            ("RELEASE_OWNER_ID", "291932506"),
            ("RELEASE_REF", "refs/heads/main-extra"),
            ("RELEASE_REF", "refs/tags/main"),
            ("RELEASE_REF", "refs/pull/1/merge"),
        ):
            cases.append(({**approved, field: invalid}, False))
        for env, accepted in cases:
            with self.subTest(source=env):
                result = subprocess.run(
                    [self.bash, "-c", self.source_gate],
                    env=env,
                    capture_output=True,
                    text=True,
                    check=False,
                )
                self.assertEqual(result.returncode == 0, accepted, result.stdout)

    @staticmethod
    def _provenance(**overrides: str) -> list[dict[str, object]]:
        certificate = {
            "sourceRepositoryIdentifier": "1303106334",
            "sourceRepositoryOwnerIdentifier": "291932505",
            "sourceRepositoryDigest": "a" * 40,
            "sourceRepositoryRef": "refs/heads/main",
            **overrides,
        }
        return [{"verificationResult": {"signature": {"certificate": certificate}}}]

    def _run_secure(
        self, results: dict[str, object], *, reject_strict: bool = False
    ) -> tuple[subprocess.CompletedProcess[str], str, list[list[str]]]:
        with tempfile.TemporaryDirectory() as scratch:
            path = Path(scratch)
            bin_path = path / "bin"
            bin_path.mkdir()
            for name in ("trivy", "cosign", "gh"):
                mock = bin_path / name
                mock.write_text(MOCK_RELEASE_TOOLS, encoding="utf-8")
                mock.chmod(0o755)
            (bin_path / "python3").symlink_to(sys.executable)
            (bin_path / "jq").symlink_to(self.jq)
            case = path / "case.json"
            case.write_text(
                json.dumps({"results": results, "reject_strict": reject_strict}),
                encoding="utf-8",
            )
            output = path / "output"
            log = path / "gh.jsonl"
            result = subprocess.run(
                [self.bash, "-c", self.secure],
                cwd=path,
                env={
                    "PATH": f"{bin_path}{os.pathsep}{os.defpath}",
                    "MOCK_RELEASE_CASE": str(case),
                    "MOCK_GH_LOG": str(log),
                    "GITHUB_OUTPUT": str(output),
                    "GITHUB_SHA": "a" * 40,
                    "REGISTRY": "registry.invalid",
                    "SERVER_DIGEST": "sha256:" + "b" * 64,
                    "HOST_DIGEST": "sha256:" + "b" * 64,
                },
                capture_output=True,
                text=True,
                check=False,
            )
            return (
                result,
                output.read_text() if output.exists() else "",
                [json.loads(line) for line in log.read_text().splitlines()],
            )

    def test_same_commit_provenance_is_reused_under_either_or_both_names(self) -> None:
        legacy, renamed = "hiloopai/omnigent", "autoresearchinc/omnigent"
        for repositories in ((legacy,), (renamed,), (legacy, renamed)):
            with self.subTest(repositories=repositories):
                result, output, calls = self._run_secure(
                    dict.fromkeys(repositories, self._provenance())
                )
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertEqual(output, "server-provenance=true\nhost-provenance=true\n")
                strict = [args for args in calls if "--source-digest" in args]
                self.assertEqual(len(strict), 2 * len(repositories))
                self.assertEqual(
                    {args[args.index("--repo") + 1] for args in strict},
                    set(repositories),
                )

    def test_provenance_from_another_commit_ref_or_repository_is_rejected(self) -> None:
        for field, invalid in (
            ("sourceRepositoryDigest", "c" * 40),
            ("sourceRepositoryRef", "refs/heads/dev"),
            ("sourceRepositoryIdentifier", "1303106335"),
            ("sourceRepositoryOwnerIdentifier", "291932506"),
        ):
            with self.subTest(field=field):
                result, output, _calls = self._run_secure(
                    {"hiloopai/omnigent": self._provenance(**{field: invalid})}
                )
                self.assertNotEqual(result.returncode, 0)
                self.assertEqual(output, "")

    def test_mixed_sources_cannot_be_hidden_by_an_approved_attestation(self) -> None:
        for invalid in (
            {"sourceRepositoryDigest": "c" * 40},
            {"sourceRepositoryRef": "refs/heads/dev"},
            {"sourceRepositoryIdentifier": "1303106335"},
            {"sourceRepositoryOwnerIdentifier": "291932506"},
        ):
            with self.subTest(invalid=invalid):
                result, output, _calls = self._run_secure(
                    {
                        "hiloopai/omnigent": self._provenance(),
                        "autoresearchinc/omnigent": self._provenance(**invalid),
                    }
                )
                self.assertNotEqual(result.returncode, 0)
                self.assertEqual(output, "")

    def test_missing_identity_fields_or_empty_results_fail_closed(self) -> None:
        for invalid in ([], {}, [{}], self._provenance(sourceRepositoryIdentifier="")):
            with self.subTest(result=invalid):
                result, output, _calls = self._run_secure({"hiloopai/omnigent": invalid})
                self.assertNotEqual(result.returncode, 0)
                self.assertEqual(output, "")

    def test_strict_cli_verification_failure_is_not_reused(self) -> None:
        result, output, _calls = self._run_secure(
            {"hiloopai/omnigent": self._provenance()}, reject_strict=True
        )
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(output, "")

    def test_missing_provenance_is_reported_for_creation(self) -> None:
        result, output, calls = self._run_secure({})
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(output, "server-provenance=false\nhost-provenance=false\n")
        self.assertFalse(any("--source-digest" in args for args in calls))


if __name__ == "__main__":
    unittest.main()
