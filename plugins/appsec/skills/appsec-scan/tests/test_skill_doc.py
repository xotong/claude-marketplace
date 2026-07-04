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
SAST_RUNNER = SKILL_DIR / "scanners" / "gitlab-sast.sh"
DS_RUNNER = SKILL_DIR / "scanners" / "gitlab-dependency-scanning.sh"
CS_RUNNER = SKILL_DIR / "scanners" / "gitlab-container-scanning.sh"
PUBLIC_IMAGE = "registry.gitlab.com/security-products/semgrep:6"
SKILL_TEXT = SKILL_MD.read_text(encoding="utf-8")


def run(cmd: list[str], cwd: Path, check: bool = True) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        cmd,
        cwd=str(cwd),
        check=check,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
    )


class SkillDocumentationTest(unittest.TestCase):
    def test_skill_contains_required_guardrails_and_references(self) -> None:
        self.assertIn("catalog.sh", SKILL_TEXT)
        self.assertIn("Step 2.5", SKILL_TEXT)
        self.assertIn("scanner-preferences.yaml", SKILL_TEXT)
        self.assertIn("rewrite git history", SKILL_TEXT)
        self.assertIn("TRIAGE.md", SKILL_TEXT)
        self.assertIn("Ask for approval once before making changes", SKILL_TEXT)
        self.assertIn("create a new branch", SKILL_TEXT)
        self.assertIn("Rerun only GitLab Secret Detection first", SKILL_TEXT)
        self.assertIn("run the app's relevant tests", SKILL_TEXT)
        self.assertIn("Secret Detection findings (redacted)", SKILL_TEXT)
        self.assertIn("GITLAB_FEATURES", SKILL_TEXT)
        self.assertIn("appsec/fix-", SKILL_TEXT)
        self.assertRegex(SKILL_TEXT, re.compile(r"5 iterations", re.IGNORECASE))
        self.assertRegex(
            SKILL_TEXT,
            re.compile(r"(?is)(ask(?:ing)?[\s\S]{0,250}push|push[\s\S]{0,250}ask(?:ing)?)"),
        )

        for dismissal in (
            "false_positive",
            "acceptable_risk",
            "mitigating_control",
            "used_in_tests",
            "not_applicable",
        ):
            with self.subTest(dismissal=dismissal):
                self.assertIn(dismissal, SKILL_TEXT)

        self.assertNotRegex(SKILL_TEXT, re.compile(r"glpat-[A-Za-z0-9]"))


class GitlabRunnerDocTest(unittest.TestCase):
    def test_runner_headers_and_component_paths_are_documented(self) -> None:
        expected_components = {
            SAST_RUNNER: "components/sast/sast",
            DS_RUNNER: "components/dependency-scanning/main",
            CS_RUNNER: "components/container-scanning/container-scanning",
        }

        for runner_path, component in expected_components.items():
            with self.subTest(runner=runner_path.name):
                text = runner_path.read_text(encoding="utf-8")
                self.assertTrue(text.startswith("#!/usr/bin/env sh"))
                self.assertIn(component, text)
                self.assertIn("/analyzer run", text)

    def test_dependency_scanning_runner_documents_exit_2_and_features_flag(self) -> None:
        text = DS_RUNNER.read_text(encoding="utf-8")

        self.assertIn("exit 2", text)
        self.assertIn("GITLAB_FEATURES", text)


@unittest.skipUnless(
    os.environ.get("RUN_GITLAB_SAST_SMOKE") == "1",
    "set RUN_GITLAB_SAST_SMOKE=1 to pull and run the public GitLab analyzer image",
)
class GitlabSastSmokeTest(unittest.TestCase):
    image = os.environ.get("GITLAB_SAST_SMOKE_IMAGE", PUBLIC_IMAGE)

    @classmethod
    def setUpClass(cls) -> None:
        if shutil.which("docker") is None:
            raise unittest.SkipTest("docker is not installed")
        run(["docker", "pull", cls.image], cwd=REPO_ROOT)

    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory(prefix="appsec-gitlab-sast-")
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

    def test_scanner_produces_at_least_one_vulnerability(self) -> None:
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
                self.image,
                "sh",
                "/runner.sh",
            ],
            cwd=REPO_ROOT,
        )

        report_path = self.repo / ".appsec-results" / "gl-sast-report.json"
        if not report_path.exists():
            report_path = self.repo / "gl-sast-report.json"

        self.assertTrue(report_path.exists(), "expected gl-sast-report.json")
        report = json.loads(report_path.read_text(encoding="utf-8"))
        vulnerabilities = list(report.get("vulnerabilities", []))
        self.assertGreaterEqual(len(vulnerabilities), 1, "expected at least one SAST finding")


if __name__ == "__main__":
    unittest.main()
