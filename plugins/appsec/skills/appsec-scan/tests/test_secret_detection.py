#!/usr/bin/env python3
"""Tests for the appsec-scan GitLab Secret Detection integration.

The Docker smoke test is opt-in because it pulls GitLab's public analyzer image.
Run it with:

    RUN_SECRET_DETECTION_SMOKE=1 python3 plugins/appsec/skills/appsec-scan/tests/test_secret_detection.py
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path


SKILL_DIR = Path(__file__).resolve().parents[1]
REPO_ROOT = SKILL_DIR.parents[3]
RUNNER = SKILL_DIR / "scanners" / "secret-detection.sh"
SKILL_MD = SKILL_DIR / "SKILL.md"
PUBLIC_IMAGE = "registry.gitlab.com/security-products/secrets:7"


def run(cmd: list[str], cwd: Path, check: bool = True) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        cmd,
        cwd=str(cwd),
        check=check,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
    )


def fake_gitlab_token() -> str:
    # Keep the detector fixture out of this repository's static text while still
    # writing a realistic-looking value into the temporary smoke-test repo.
    return "glpat-" + "1234567890" + "abcdef" + "1234"


class SecretDetectionDocumentationTest(unittest.TestCase):
    def test_skill_documents_scanner_and_approval_loop(self) -> None:
        skill = SKILL_MD.read_text(encoding="utf-8")

        self.assertIn("GitLab Secret Detection", skill)
        self.assertIn("docker pull", skill)
        self.assertIn("gl-secret-detection-report.json", skill)
        self.assertIn("Secret Detection findings (redacted)", skill)
        self.assertIn("Ask for approval once before making changes", skill)
        self.assertIn("create a new branch", skill)
        self.assertIn("Rerun only GitLab Secret Detection first", skill)
        self.assertIn("run the app's relevant tests", skill)

    def test_runner_mirrors_catalog_script(self) -> None:
        runner = RUNNER.read_text(encoding="utf-8")

        self.assertIn("gitlab.com/components/secret-detection", runner)
        self.assertIn("/analyzer run", runner)
        self.assertIn("gl-secret-detection-report.json", runner)


@unittest.skipUnless(
    os.environ.get("RUN_SECRET_DETECTION_SMOKE") == "1",
    "set RUN_SECRET_DETECTION_SMOKE=1 to pull and run the public GitLab analyzer image",
)
class SecretDetectionDockerSmokeTest(unittest.TestCase):
    image = os.environ.get("SECRET_DETECTION_SMOKE_IMAGE", PUBLIC_IMAGE)

    @classmethod
    def setUpClass(cls) -> None:
        if shutil.which("docker") is None:
            raise unittest.SkipTest("docker is not installed")
        run(["docker", "pull", cls.image], cwd=REPO_ROOT)

    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory(prefix="appsec-secret-detection-")
        self.repo = Path(self.tmp.name)
        run(["git", "init", "-b", "main"], cwd=self.repo)
        run(["git", "config", "user.email", "appsec-test@example.invalid"], cwd=self.repo)
        run(["git", "config", "user.name", "AppSec Smoke Test"], cwd=self.repo)
        (self.repo / "README.md").write_text("# smoke\n", encoding="utf-8")
        run(["git", "add", "README.md"], cwd=self.repo)
        run(["git", "commit", "-m", "initial clean commit"], cwd=self.repo)

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def run_secret_detection(self) -> list[dict[str, object]]:
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
                f"{RUNNER}:/runner.sh:ro",
                "-w",
                "/workspace",
                "-e",
                "CI_PROJECT_DIR=/workspace",
                "-e",
                "GIT_DEPTH=50",
                "-e",
                "SECRET_DETECTION_EXCLUDED_PATHS=",
                self.image,
                "sh",
                "/runner.sh",
            ],
            cwd=REPO_ROOT,
        )
        report_path = self.repo / ".appsec-results" / "gl-secret-detection-report.json"
        self.assertTrue(report_path.exists(), "expected gl-secret-detection-report.json")
        report = json.loads(report_path.read_text(encoding="utf-8"))
        return list(report.get("vulnerabilities", []))

    def test_scanner_detects_then_clears_secret_fixture(self) -> None:
        (self.repo / "config.env").write_text(
            "GITLAB_TOKEN=" + fake_gitlab_token() + "\n",
            encoding="utf-8",
        )

        findings = self.run_secret_detection()
        self.assertGreater(len(findings), 0, "expected fake token to be detected")

        (self.repo / "config.env").write_text(
            "GITLAB_TOKEN=${GITLAB_TOKEN}\n",
            encoding="utf-8",
        )

        findings = self.run_secret_detection()
        self.assertEqual(findings, [], "expected findings to clear after remediation")


if __name__ == "__main__":
    unittest.main()
