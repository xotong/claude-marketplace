#!/usr/bin/env python3
"""Tests for the appsec-scan skill documentation and GitLab runners."""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path


SKILL_DIR = Path(__file__).resolve().parents[1]
REPO_ROOT = SKILL_DIR.parents[3]
SKILL_MD = SKILL_DIR / "SKILL.md"
SAST_RUNNER = SKILL_DIR / "scanners" / "fortify-sast.sh"
DS_RUNNER = SKILL_DIR / "scanners" / "gitlab-dependency-scanning.sh"
CS_RUNNER = SKILL_DIR / "scanners" / "gitlab-container-scanning.sh"
RUN_SCAN = SKILL_DIR / "scripts" / "run-scan.sh"
NORMALIZE = SKILL_DIR / "scripts" / "normalize.py"
SECRET_TEMPLATE = (
    SKILL_DIR
    / "reference"
    / "catalog"
    / "lobster-thermidor"
    / "devops"
    / "ci-catalogue"
    / "secret-detection"
    / "secret-detection"
    / "1.0.0"
    / "template.yml"
)
SECRET_TEMPLATE_TEXT = SECRET_TEMPLATE.read_text(encoding="utf-8")
PUBLIC_IMAGE_MATCH = re.search(r'image:\s*"([^"]+)"', SECRET_TEMPLATE_TEXT)
if PUBLIC_IMAGE_MATCH is None:  # pragma: no cover - static shipped fixture
    raise AssertionError(f"could not derive public secret-detection image from {SECRET_TEMPLATE}")
PUBLIC_IMAGE = PUBLIC_IMAGE_MATCH.group(1)
SKILL_TEXT = SKILL_MD.read_text(encoding="utf-8")
RUN_SCAN_TEXT = RUN_SCAN.read_text(encoding="utf-8")


def run(cmd: list[str], cwd: Path, check: bool = True) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        cmd,
        cwd=str(cwd),
        check=check,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
    )


class SkillDocumentationContractTest(unittest.TestCase):
    def test_skill_contains_required_guardrails_and_contract_strings(self) -> None:
        required_strings = [
            "catalog.sh",
            "scanner-preferences.yaml",
            "TRIAGE.md",
            "Ask for approval once before making changes",
            "create a new branch",
            "run the app's relevant tests",
            "Secret Detection findings (redacted)",
            "appsec/fix-",
            "FORTIFY_SAST_IMAGE",
            "RUN_FORTIFY_SAST",
            "RUN_GITLAB_DS",
            "RUN_SECRET_DETECTION",
            "RUN_GITLAB_CS",
            "lobster-thermidor/devops/ci-catalogue/fortify-sast/fortify-sast",
        ]

        for expected in required_strings:
          with self.subTest(expected=expected):
            self.assertIn(expected, SKILL_TEXT)

        self.assertRegex(SKILL_TEXT, re.compile(r"5 iterations", re.IGNORECASE))
        self.assertRegex(
            SKILL_TEXT,
            re.compile(r"(?is)(ask(?:ing)?[\s\S]{0,250}push|push[\s\S]{0,250}ask(?:ing)?)"),
        )
        self.assertNotRegex(SKILL_TEXT, re.compile(r"glpat-[A-Za-z0-9]"))

    def test_skill_documents_airgap_and_runtime_abstraction(self) -> None:
        required_strings = [
            "APPSEC_AIRGAP",
            "detect-runtime.sh",
            "resolve-jq.sh",
            "container-target.sh",
            "read_api",
            "CATALOG_MODE",
            "HAS_MISSING_REPORT",
            "NOT an all-clear",
            "load-prefs.sh",
            "ENABLED_COMPONENTS",
        ]

        for expected in required_strings:
          with self.subTest(expected=expected):
            self.assertIn(expected, SKILL_TEXT)

        self.assertNotIn("IMAGE_PREFIX", SKILL_TEXT)
        self.assertNotIn("docker run --rm", SKILL_TEXT)
        self.assertNotIn("if docker pull", SKILL_TEXT)

        for expected in (
            '"$RUNTIME" run',
            '"$RUNTIME" pull "${SECRET_DETECTION_IMAGE}"',
            "GITLAB_FEATURES",
        ):
            with self.subTest(expected=expected):
                self.assertIn(expected, RUN_SCAN_TEXT)

    def test_normalizer_preserves_redacted_secret_summary_contract(self) -> None:
        normalizer = NORMALIZE.read_text(encoding="utf-8")

        self.assertIn("Secret Detection findings (redacted)", SKILL_TEXT)
        self.assertIn("Secret Detection findings (redacted)", normalizer)


class SkillDocTokenBudgetTest(unittest.TestCase):
    def test_skill_stays_within_host_orchestrator_token_budget(self) -> None:
        # Raised from 260/13000 in 2026-07 to fit the escalation-prefix table
        # (ADVISORY / DRIFT / CONTRACT-DRIFT / NEEDS-MAPPING). The budget exists
        # to keep this readable by a small orchestrator model; a decision table
        # that removes ambiguity earns its lines back.
        lines = SKILL_TEXT.splitlines()

        self.assertLessEqual(len(lines), 275)
        self.assertLessEqual(len(SKILL_TEXT), 13800)


class GitlabRunnerDocTest(unittest.TestCase):
    def test_container_runner_supports_registry_and_archive_modes(self) -> None:
        text = CS_RUNNER.read_text(encoding="utf-8")
        self.assertIn("CS_SCAN_MODE", text)
        self.assertIn("gtcs", text)
        self.assertIn("--input", text)
        self.assertIn("--offline-scan", text)

    def test_runner_headers_and_component_paths_are_documented(self) -> None:
        expected_components = {
            SAST_RUNNER: "lobster-thermidor/devops/ci-catalogue/fortify-sast/fortify-sast",
            DS_RUNNER: "lobster-thermidor/devops/ci-catalogue/dependency-scanning/dependency-scanning",
            CS_RUNNER: "lobster-thermidor/devops/ci-catalogue/container-scanning/container-scanning",
        }

        for runner_path, component in expected_components.items():
            with self.subTest(runner=runner_path.name):
                text = runner_path.read_text(encoding="utf-8")
                self.assertTrue(text.startswith("#!/usr/bin/env sh"))
                self.assertIn(component, text)

        self.assertIn("FORTIFY_LANGUAGE", SAST_RUNNER.read_text(encoding="utf-8"))
        self.assertIn("/analyzer run", DS_RUNNER.read_text(encoding="utf-8"))
        self.assertIn("gtcs scan", CS_RUNNER.read_text(encoding="utf-8"))

    def test_dependency_scanning_runner_documents_exit_2_and_features_flag(self) -> None:
        text = DS_RUNNER.read_text(encoding="utf-8")

        self.assertIn("exit 2", text)
        self.assertIn("GITLAB_FEATURES", text)


@unittest.skipUnless(
    os.environ.get("RUN_GITLAB_SAST_SMOKE") == "1",
    "set RUN_GITLAB_SAST_SMOKE=1 to pull and run the public analyzer image",
)
class GitlabSastSmokeTest(unittest.TestCase):
    image = os.environ.get("GITLAB_SAST_SMOKE_IMAGE", PUBLIC_IMAGE)

    @classmethod
    def setUpClass(cls) -> None:
        if shutil.which("docker") is None:
            raise unittest.SkipTest("docker is not installed")
        run(["docker", "pull", cls.image], cwd=REPO_ROOT)

    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory(prefix="appsec-fortify-sast-")
        self.repo = Path(self.tmp.name)
        run(["git", "init", "-b", "main"], cwd=self.repo)
        run(["git", "config", "user.email", "appsec-test@example.invalid"], cwd=self.repo)
        run(["git", "config", "user.name", "AppSec Smoke Test"], cwd=self.repo)
        (self.repo / "app.py").write_text(
            'import os\n\n'
            'eval(os.environ.get("X", ""))\n',
            encoding="utf-8",
        )
        run(["git", "add", "app.py"], cwd=self.repo)
        run(["git", "commit", "-m", "add eval fixture"], cwd=self.repo)

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def test_scanner_produces_output_file(self) -> None:
        run(
            [
                "docker",
                "run",
                "--rm",
                "--entrypoint",
                "",
                "-v",
                f"{self.repo}:/workspace",
                "-v",
                f"{SAST_RUNNER}:/runner.sh:ro",
                "-w",
                "/workspace",
                "-e",
                "CI_PROJECT_DIR=/workspace",
                "-e",
                "FORTIFY_LANGUAGE=python",
                self.image,
                "sh",
                "/runner.sh",
            ],
            cwd=REPO_ROOT,
        )

        report_path = self.repo / ".appsec-results" / "fortify-sast.fpr"
        self.assertTrue(report_path.exists(), "expected fortify-sast.fpr")
        self.assertGreater(report_path.stat().st_size, 0)


if __name__ == "__main__":
    unittest.main()
