#!/usr/bin/env python3
"""Hermetic tests for the host AppSec scan orchestrator."""

from __future__ import annotations

import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path


SKILL_DIR = Path(__file__).resolve().parents[1]
SCRIPTS_DIR = SKILL_DIR / "scripts"
RUN_SCAN = SCRIPTS_DIR / "run-scan.sh"
FIX_BRANCH = SCRIPTS_DIR / "fix-branch.sh"
RESOLVE_PYTHON = SCRIPTS_DIR / "resolve-python.sh"
BASH = shutil.which("bash") or "/bin/bash"


class RunScanDryRunTest(unittest.TestCase):
    def make_repo(self, tmp: str, *, pom: bool = True) -> Path:
        repo = Path(tmp)
        subprocess.run(["git", "init", "-q"], cwd=repo, check=True)
        if pom:
            (repo / "pom.xml").write_text("<project/>\n", encoding="utf-8")
        return repo

    def base_env(self, **overrides: str) -> dict[str, str]:
        env = dict(
            os.environ,
            RUNTIME="fake-runtime",
            SKILL_DIR=str(SKILL_DIR),
            SCANNERS_DIR=str(SKILL_DIR / "scanners"),
            SCRIPTS_DIR=str(SCRIPTS_DIR),
            APPSEC_PROFILE="catalog",
            RUN_FORTIFY_SAST="true",
            RUN_GITLAB_DS="true",
            RUN_SECRET_DETECTION="true",
            RUN_GITLAB_CS="true",
            FORTIFY_SAST_IMAGE="example/fortify:test",
            GITLAB_DS_IMAGE="example/ds:test",
            SECRET_DETECTION_IMAGE="example/secrets:test",
            GITLAB_CS_IMAGE="example/cs:test",
            CS_USER_ENV="TEST_CS_USER",
            CS_PASS_ENV="TEST_CS_PASS",
            CS_IMAGE="example/app:test",
            PYTHON_INSTALL_URL="",
            JQ_INSTALL_URL="",
            CI_GATE_FAIL_ON="high",
        )
        env.update(overrides)
        return env

    def run_scan(
        self,
        cwd: Path,
        *args: str,
        env: dict[str, str] | None = None,
    ) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [BASH, str(RUN_SCAN), *args],
            cwd=cwd,
            env=env or self.base_env(),
            capture_output=True,
            text=True,
        )

    def test_detects_maven_without_gradle(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo = self.make_repo(tmp)
            result = self.run_scan(repo, "--dry-run")

        output = result.stdout + result.stderr
        self.assertEqual(result.returncode, 0, output)
        self.assertIn("Maven=true", output)
        self.assertIn("Gradle=false", output)
        self.assertIn("HAS_POM_NO_GRADLE=true", output)
        self.assertIn("FORTIFY_LANGUAGE=maven", output)

    def test_enabled_scanners_emit_runtime_run_shapes(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo = self.make_repo(tmp)
            result = self.run_scan(repo, "--dry-run")

        output = result.stdout + result.stderr
        self.assertEqual(result.returncode, 0, output)
        for image in (
            "example/fortify:test",
            "example/ds:test",
            "example/secrets:test",
            "example/cs:test",
        ):
            with self.subTest(image=image):
                self.assertIn(image, output)
        self.assertGreaterEqual(output.count("fake-runtime run --rm"), 4)
        self.assertIn("GITLAB_FEATURES=dependency_scanning", output)
        self.assertIn("CS_SCAN_MODE=registry", output)

    def test_only_secret_detection_filters_other_scanners(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo = self.make_repo(tmp)
            result = self.run_scan(repo, "--only", "secret_detection", "--dry-run")

        output = result.stdout + result.stderr
        self.assertEqual(result.returncode, 0, output)
        self.assertIn("example/secrets:test", output)
        self.assertNotIn("example/fortify:test", output)
        self.assertNotIn("example/ds:test", output)
        self.assertNotIn("example/cs:test", output)

    def test_unknown_only_category_exits_two(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            result = self.run_scan(Path(tmp), "--only", "bogus", "--dry-run")

        self.assertEqual(result.returncode, 2)
        self.assertIn("ERROR: unknown category: bogus", result.stderr)

    def test_dry_run_exits_zero(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo = self.make_repo(tmp)
            result = self.run_scan(repo, "--dry-run")

        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_dry_run_redacts_registry_password(self) -> None:
        sentinel = "SUPERSECRET123"
        with tempfile.TemporaryDirectory() as tmp:
            repo = self.make_repo(tmp)
            env = self.base_env(TEST_CS_PASS=sentinel)
            result = self.run_scan(repo, "--dry-run", env=env)

        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertNotIn(sentinel, result.stdout)
        self.assertIn("CS_REGISTRY_PASSWORD=***", result.stdout)

    def test_self_locates_skill_paths_when_environment_paths_are_unset(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo = self.make_repo(tmp)
            env = self.base_env()
            for name in ("SKILL_DIR", "SCANNERS_DIR", "SCRIPTS_DIR"):
                env.pop(name, None)
            result = self.run_scan(repo, "--dry-run", env=env)

        output = result.stdout + result.stderr
        self.assertEqual(result.returncode, 0, output)
        self.assertNotIn("unbound variable", output)
        self.assertIn(str(SKILL_DIR / "scanners" / "fortify-sast.sh"), output)

    def test_container_timeout_cleanup_policy_is_valid_bash(self) -> None:
        result = subprocess.run(
            [BASH, "-n", str(RUN_SCAN)], capture_output=True, text=True
        )
        script = RUN_SCAN.read_text(encoding="utf-8")

        self.assertEqual(result.returncode, 0, result.stderr)
        # A hermetic timeout test would require portable fake docker process-tree
        # semantics; macOS lacks setsid, so verify the explicit cleanup policy.
        self.assertIn("APPSEC_SCAN_TIMEOUT", script)
        self.assertIn("command -v setsid", script)
        self.assertIn('kill -TERM -- "-$container_pid"', script)
        self.assertIn("macOS/Bash 3.2", script)

    def test_pythonless_tier_warns_and_never_claims_all_clear(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo = self.make_repo(tmp, pom=False)
            bin_dir = repo / "bin"
            bin_dir.mkdir()
            for name in ("bash", "basename", "git", "grep", "mkdir"):
                target = shutil.which(name)
                self.assertIsNotNone(target, name)
                (bin_dir / name).symlink_to(target)
            env = self.base_env(
                PATH=str(bin_dir),
                RUN_FORTIFY_SAST="false",
                RUN_GITLAB_DS="false",
                RUN_SECRET_DETECTION="false",
                RUN_GITLAB_CS="false",
                PYTHON_INSTALL_URL="",
            )
            result = self.run_scan(repo, "--dry-run", env=env)

        output = result.stdout + result.stderr
        self.assertEqual(result.returncode, 0, output)
        self.assertIn("install python3 or set settings.python.install_url", output)
        self.assertIn("UNKNOWN status", output)
        self.assertIn("NOT an all-clear", output)
        self.assertNotIn("All clear", output)


class ResolvePythonTest(unittest.TestCase):
    def test_returns_verified_host_python_path(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            bin_dir = Path(tmp) / "bin"
            bin_dir.mkdir()
            python = bin_dir / "python3"
            python.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
            python.chmod(0o755)
            result = subprocess.run(
                [BASH, str(RESOLVE_PYTHON)],
                env=dict(os.environ, PATH=str(bin_dir), PYTHON_INSTALL_URL=""),
                capture_output=True,
                text=True,
            )

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.strip(), str(python))

    def test_empty_url_degrades_without_output(self) -> None:
        result = subprocess.run(
            [BASH, str(RESOLVE_PYTHON)],
            env=dict(os.environ, PATH="", PYTHON_INSTALL_URL=""),
            capture_output=True,
            text=True,
        )

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.strip(), "")


class FixBranchTest(unittest.TestCase):
    def make_committed_repo(self, tmp: str) -> Path:
        repo = Path(tmp)
        subprocess.run(["git", "init", "-q"], cwd=repo, check=True)
        subprocess.run(
            ["git", "config", "user.email", "appsec-test@example.invalid"],
            cwd=repo,
            check=True,
        )
        subprocess.run(
            ["git", "config", "user.name", "AppSec Test"], cwd=repo, check=True
        )
        (repo / "tracked.txt").write_text("baseline\n", encoding="utf-8")
        subprocess.run(["git", "add", "tracked.txt"], cwd=repo, check=True)
        subprocess.run(["git", "commit", "-qm", "baseline"], cwd=repo, check=True)
        return repo

    def run_fix(self, repo: Path, *args: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [BASH, str(FIX_BRANCH), *args],
            cwd=repo,
            capture_output=True,
            text=True,
        )

    def test_init_creates_branch_and_loop_state(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo = self.make_committed_repo(tmp)
            result = self.run_fix(repo, "--init")
            state = (repo / ".appsec-results" / "loop-state").read_text(
                encoding="utf-8"
            )
            branch = subprocess.run(
                ["git", "branch", "--show-current"],
                cwd=repo,
                check=True,
                capture_output=True,
                text=True,
            ).stdout.strip()

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertTrue(branch.startswith("appsec/fix-"), branch)
        self.assertEqual(state, '{"iteration":0,"last_total":-1}\n')

    def test_init_counts_findings_in_triaged_array(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo = self.make_committed_repo(tmp)
            results = repo / ".appsec-results"
            results.mkdir()
            (results / "findings.triaged.json").write_text(
                '[{"fingerprint":"one"},{"fingerprint":"two"}]\n',
                encoding="utf-8",
            )
            result = self.run_fix(repo, "--init")
            state = (results / "loop-state").read_text(encoding="utf-8")

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(state, '{"iteration":0,"last_total":2}\n')

    def test_check_progress_increments_and_rejects_no_progress(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo = self.make_committed_repo(tmp)
            self.assertEqual(self.run_fix(repo, "--init").returncode, 0)
            result = self.run_fix(repo, "--check-progress", "10", "10")
            state = (repo / ".appsec-results" / "loop-state").read_text(
                encoding="utf-8"
            )

        self.assertEqual(result.returncode, 1)
        self.assertIn("ERROR: no progress", result.stderr)
        self.assertEqual(state, '{"iteration":1,"last_total":10}\n')

    def test_check_progress_allows_five_fix_cycles_then_aborts(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo = self.make_committed_repo(tmp)
            self.assertEqual(self.run_fix(repo, "--init").returncode, 0)
            for previous, current in ((10, 9), (9, 8), (8, 7), (7, 6), (6, 5)):
                result = self.run_fix(
                    repo, "--check-progress", str(previous), str(current)
                )
                self.assertEqual(result.returncode, 0, result.stderr)
            result = self.run_fix(repo, "--check-progress", "5", "4")

        self.assertEqual(result.returncode, 1)
        self.assertIn("ERROR: fix loop exceeded 5 iterations", result.stderr)


if __name__ == "__main__":
    unittest.main()
