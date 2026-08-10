#!/usr/bin/env python3
"""Hermetic tests for the host AppSec scan orchestrator."""

from __future__ import annotations

import importlib.util
import json
import os
import re
import shutil
import subprocess
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock


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

    def make_skill_with_config(self, root: Path, *replacements: tuple[str, str]) -> Path:
        """A SKILL_DIR whose only content is an edited scanner-preferences.yaml.

        run-scan.sh reads the config through SKILL_DIR; catalog.sh finds its
        vendored snapshots relative to SCRIPTS_DIR, so the real ones still apply.
        """
        temp_skill = root / "skill"
        (temp_skill / "config").mkdir(parents=True)
        preferences = (SKILL_DIR / "config" / "scanner-preferences.yaml").read_text(
            encoding="utf-8"
        )
        for old, new in replacements:
            self.assertIn(old, preferences, old)
            preferences = preferences.replace(old, new)
        (temp_skill / "config" / "scanner-preferences.yaml").write_text(
            preferences, encoding="utf-8"
        )
        return temp_skill

    def self_loading_env(self, **overrides: str) -> dict[str, str]:
        """base_env minus everything that suppresses the config self-load."""
        env = self.base_env(**overrides)
        for name in (
            "RUN_FORTIFY_SAST",
            "RUN_GITLAB_DS",
            "RUN_SECRET_DETECTION",
            "RUN_GITLAB_CS",
            "FORTIFY_SAST_IMAGE",
            "GITLAB_DS_IMAGE",
            "SECRET_DETECTION_IMAGE",
            "GITLAB_CS_IMAGE",
            "MAVEN_SETTINGS",
        ):
            if name not in overrides:
                env.pop(name, None)
        return env

    def dry_run_line(self, result, marker: str) -> str:
        output = result.stdout + result.stderr
        lines = [
            line
            for line in output.splitlines()
            if line.startswith("DRY-RUN:") and marker in line
        ]
        self.assertEqual(len(lines), 1, f"expected one {marker} command in:\n{output}")
        return lines[0]

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
        for image_repo in (
            "example/fortify:",
            "example/ds:",
            "example/secrets:",
            "example/cs:",
        ):
            with self.subTest(image_repo=image_repo):
                self.assertIn(image_repo, output)
        self.assertGreaterEqual(output.count("fake-runtime run --rm"), 4)
        self.assertIn("GITLAB_FEATURES=dependency_scanning", output)
        self.assertIn("CS_SCAN_MODE=registry", output)

    def test_only_secret_detection_filters_other_scanners(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo = self.make_repo(tmp)
            result = self.run_scan(repo, "--only", "secret_detection", "--dry-run")

        output = result.stdout + result.stderr
        self.assertEqual(result.returncode, 0, output)
        self.assertIn("example/secrets:", output)
        self.assertNotIn("example/fortify:", output)
        self.assertNotIn("example/ds:", output)
        self.assertNotIn("example/cs:", output)

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

    def test_dry_run_derives_images_when_image_env_is_absent(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo = self.make_repo(tmp)
            env = self.base_env()
            for name in (
                "FORTIFY_SAST_IMAGE",
                "GITLAB_DS_IMAGE",
                "SECRET_DETECTION_IMAGE",
                "GITLAB_CS_IMAGE",
                "RUN_FORTIFY_SAST",
                "RUN_GITLAB_DS",
                "RUN_SECRET_DETECTION",
                "RUN_GITLAB_CS",
            ):
                env.pop(name)
            result = self.run_scan(repo, "--dry-run", env=env)

        output = result.stdout + result.stderr
        self.assertEqual(result.returncode, 0, output)
        self.assertIn("RUN_* vars absent, self-loading preferences", output)
        self.assertGreaterEqual(output.count("DRY-RUN: fake-runtime run --rm"), 4)
        for marker in (
            "fortify-sast.sh:/runner.sh:ro",
            "GITLAB_FEATURES=dependency_scanning",
            "secret-detection.sh:/runner.sh:ro",
            "CS_SCAN_MODE=registry",
        ):
            with self.subTest(marker=marker):
                self.assertIn(marker, output)
        self.assertNotIn("Enabled but", output)
        self.assertNotIn("missing image", output.lower())

    def test_enabled_scanner_with_empty_image_exits_nonzero(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo = self.make_repo(tmp)
            empty_cache = repo / "catalog"
            (
                empty_cache
                / "lobster-thermidor/devops/ci-catalogue/fortify-sast/fortify-sast"
            ).mkdir(parents=True)
            env = self.base_env(
                RUN_GITLAB_DS="false",
                RUN_SECRET_DETECTION="false",
                RUN_GITLAB_CS="false",
                FORTIFY_SAST_IMAGE="",
                CATALOG_CACHE=str(empty_cache),
            )
            result = self.run_scan(repo, "--dry-run", env=env)
            # read inside the context — the temp dir is removed on exit
            skips = (repo / ".appsec-results" / "scan-skips").read_text()

        self.assertIn(
            "WARNING: [Fortify SCA] Enabled but FORTIFY_SAST_IMAGE is empty",
            result.stderr,
        )
        # sast is enabled, so it is EXPECTED up front and its absence is a
        # coverage gap with an actionable reason — not a bare "no scanners ran".
        # Letting an enabled-but-unrun category vanish is how the false all-clear
        # happened (gate PASSED with 2 of 4 scanners never executed).
        self.assertIn("sast\t", skips)
        self.assertIn("re-run this skill", skips)
        self.assertNotEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_only_disabled_category_exits_nonzero(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo = self.make_repo(tmp)
            env = self.base_env(RUN_FORTIFY_SAST="false")
            result = self.run_scan(repo, "--only", "sast", "--dry-run", env=env)

        self.assertEqual(result.returncode, 2, result.stdout + result.stderr)
        self.assertIn("WARNING: no scanners ran", result.stderr)
        self.assertIn("filtered by --only sast", result.stderr)

    def test_bogus_run_flag_is_not_executed_and_scanner_is_skipped(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo = self.make_repo(tmp)
            env = self.base_env(
                RUN_FORTIFY_SAST="echo pwned",
                RUN_GITLAB_DS="false",
                RUN_SECRET_DETECTION="false",
                RUN_GITLAB_CS="false",
            )
            result = self.run_scan(repo, "--dry-run", env=env)

        output = result.stdout + result.stderr
        self.assertEqual(result.returncode, 2, output)
        self.assertNotIn("pwned", output)
        self.assertNotIn("example/fortify:test", output)
        self.assertIn("WARNING: no scanners ran", output)

    def test_missing_required_environment_exits_two(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            env = self.base_env()
            env.pop("RUNTIME")
            env.pop("APPSEC_PROFILE")
            result = self.run_scan(Path(tmp), "--dry-run", env=env)

        # RUNTIME is now self-detected when absent, so it is no longer reported
        # missing — only genuinely unrecoverable vars are. Asserting on
        # APPSEC_PROFILE alone also keeps this test independent of whether a
        # container runtime happens to be installed on the host.
        self.assertEqual(result.returncode, 2)
        self.assertIn("required environment variables are unset", result.stderr)
        self.assertIn("APPSEC_PROFILE", result.stderr)

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

    def test_unset_run_flags_self_load_preferences(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo = self.make_repo(tmp)
            env = self.base_env()
            for name in (
                "RUN_FORTIFY_SAST",
                "RUN_GITLAB_DS",
                "RUN_SECRET_DETECTION",
                "RUN_GITLAB_CS",
            ):
                env.pop(name, None)
            result = self.run_scan(repo, "--dry-run", env=env)

        output = result.stdout + result.stderr
        self.assertEqual(result.returncode, 0, output)
        self.assertIn("RUN_* vars absent, self-loading preferences", result.stderr)
        self.assertIn("fake-runtime run --rm", output)
        self.assertNotEqual(output.strip(), "Gate verdict: PASSED")

    def test_all_disabled_preferences_exit_two(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "repo").mkdir()
            repo = self.make_repo(str(root / "repo"))
            temp_skill = root / "skill"
            config_dir = temp_skill / "config"
            config_dir.mkdir(parents=True)
            preferences = (
                SKILL_DIR / "config" / "scanner-preferences.yaml"
            ).read_text(encoding="utf-8")
            (config_dir / "scanner-preferences.yaml").write_text(
                preferences.replace("enabled: true", "enabled: false"),
                encoding="utf-8",
            )
            env = self.base_env(SKILL_DIR=str(temp_skill))
            for name in (
                "RUN_FORTIFY_SAST",
                "RUN_GITLAB_DS",
                "RUN_SECRET_DETECTION",
                "RUN_GITLAB_CS",
            ):
                env.pop(name, None)
            result = self.run_scan(repo, "--dry-run", env=env)

        self.assertEqual(result.returncode, 2, result.stdout + result.stderr)
        self.assertIn("WARNING: no scanners enabled", result.stderr)

    def test_fast_scanner_reaps_watchdog_without_pipe_hang(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "repo").mkdir()
            repo = self.make_repo(str(root / "repo"))
            bin_dir = root / "bin"
            bin_dir.mkdir()
            fake_runtime = bin_dir / "fake-docker"
            fake_runtime.write_text(
                '#!/bin/sh\nif [ "${1:-}" = run ]; then\n'
                "  attempts=0\n"
                '  while [ ! -s "$SLEEP_PID_LOG" ] && [ "$attempts" -lt 100 ]; do\n'
                "    /bin/sleep 0.01\n"
                "    attempts=$((attempts + 1))\n"
                "  done\n"
                "fi\nexit 0\n",
                encoding="utf-8",
            )
            fake_runtime.chmod(0o755)
            sleep_pid_log = root / "sleep-pids"
            fake_sleep = bin_dir / "sleep"
            fake_sleep.write_text(
                '#!/bin/sh\nprintf \'%s\\n\' "$$" >>"$SLEEP_PID_LOG"\n'
                'exec /bin/sleep "$@"\n',
                encoding="utf-8",
            )
            fake_sleep.chmod(0o755)
            env = self.base_env(
                PATH=f"{bin_dir}{os.pathsep}{os.environ.get('PATH', '')}",
                RUNTIME=str(fake_runtime),
                APPSEC_SCAN_TIMEOUT="8",
                SLEEP_PID_LOG=str(sleep_pid_log),
                RUN_GITLAB_DS="false",
                RUN_SECRET_DETECTION="false",
                RUN_GITLAB_CS="false",
            )
            started = time.monotonic()
            result = subprocess.run(
                [BASH, str(RUN_SCAN)],
                cwd=repo,
                env=env,
                capture_output=True,
                text=True,
                timeout=8,
            )
            elapsed = time.monotonic() - started
            sleep_pids = [
                int(pid)
                for pid in sleep_pid_log.read_text(encoding="utf-8").splitlines()
            ]

        output = result.stdout + result.stderr
        # The pipe-hang bug blocked for the full APPSEC_SCAN_TIMEOUT (8s here, 3600s
        # default). A completion well under that timeout proves the watchdog no longer
        # holds stdout; the reaping asserts below carry the real correctness proof, so
        # keep this bound loose enough to survive a loaded CI host.
        self.assertLess(elapsed, 6, output)
        self.assertTrue(sleep_pids, output)
        self.assertNotIn("Terminated", output)
        for pid in sleep_pids:
            with self.subTest(pid=pid):
                with self.assertRaises(ProcessLookupError):
                    os.kill(pid, 0)

    def test_parallel_watchdog_kills_term_ignoring_scanner(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "repo").mkdir()
            repo = self.make_repo(str(root / "repo"))
            fake_runtime = root / "fake-docker"
            fake_runtime.write_text(
                '#!/bin/sh\nif [ "${1:-}" = run ]; then\n'
                "  trap '' TERM\n"
                "  while :; do /bin/sleep 0.1; done\n"
                "fi\nexit 0\n",
                encoding="utf-8",
            )
            fake_runtime.chmod(0o755)
            env = self.base_env(
                RUNTIME=str(fake_runtime),
                APPSEC_SCAN_TIMEOUT="1",
                RUN_GITLAB_DS="false",
                RUN_SECRET_DETECTION="false",
                RUN_GITLAB_CS="false",
            )
            started = time.monotonic()
            result = subprocess.run(
                [BASH, str(RUN_SCAN)],
                cwd=repo,
                env=env,
                capture_output=True,
                text=True,
                timeout=7,
            )
            elapsed = time.monotonic() - started

        output = result.stdout + result.stderr
        self.assertLess(elapsed, 6, output)
        self.assertNotEqual(result.returncode, 0, output)
        self.assertIn("[FORTIFY_SAST] Failed", output)

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
            repo = self.make_repo(tmp)
            bin_dir = repo / "bin"
            bin_dir.mkdir()
            for name in ("bash", "basename", "git", "grep", "mkdir"):
                target = shutil.which(name)
                self.assertIsNotNone(target, name)
                (bin_dir / name).symlink_to(target)
            env = self.base_env(
                PATH=str(bin_dir),
                RUN_FORTIFY_SAST="true",
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

    def test_repointed_component_is_not_resolved_from_the_shipped_path(self) -> None:
        # component: is admin-owned and PREFERENCES.md tells admins to change it.
        # run-scan.sh used to carry its own literal table of component paths, so a
        # repointed category was still resolved from the SHIPPED component — and
        # silently: catalog.sh falls back to the vendored snapshot of that path,
        # which yields registry.gitlab.com/security-products/container-scanning,
        # i.e. the public analyzer instead of the configured mirror. A test over
        # the shipped config alone cannot see this.
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "repo").mkdir()
            repo = self.make_repo(str(root / "repo"))
            temp_skill = self.make_skill_with_config(
                root,
                (
                    "component: lobster-thermidor/devops/ci-catalogue"
                    "/container-scanning/container-scanning",
                    "component: lobster-thermidor/devops/ci-catalogue"
                    "/secret-detection/secret-detection",
                ),
            )
            env = self.self_loading_env(
                SKILL_DIR=str(temp_skill), CS_IMAGE="example/app:test"
            )
            result = self.run_scan(repo, "--dry-run", env=env)

        output = result.stdout + result.stderr
        self.assertEqual(result.returncode, 0, output)
        self.assertNotIn("security-products/container-scanning", output)
        cs_line = self.dry_run_line(result, "gitlab-container-scanning.sh:/runner.sh:ro")
        self.assertIn("security-products/secrets:", cs_line)

    def test_dry_run_plans_the_sbom_match_in_the_container_scanning_image(self) -> None:
        # Dependency Scanning alone leaves only an SBOM, which normalizes to zero
        # findings. The match runs in the GTCS image because that is the one with
        # trivy and an advisory DB baked in — the DS image has neither.
        with tempfile.TemporaryDirectory() as tmp:
            repo = self.make_repo(tmp)
            result = self.run_scan(repo, "--dry-run")

        line = self.dry_run_line(result, "sbom-vuln-scan.sh:/runner.sh:ro")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("example/cs:", line)
        self.assertNotIn("example/ds:", line)
        self.assertIn("CI_PROJECT_DIR=/workspace", line)

    def test_only_dependency_scanning_still_resolves_the_match_image(self) -> None:
        # `--only dependency_scanning` is exactly the rescan SKILL.md's fix loop
        # runs after fixing a dependency. The image loop skipped any category the
        # scope did not select, so GITLAB_CS_IMAGE went unresolved and the match
        # degraded every time — the rescan then reported the dependency findings
        # GONE rather than fixed, because an SBOM alone normalizes to zero
        # findings. The container-scanning image is the tool here, not a scanner.
        # self_loading_env, NOT base_env: base_env pins all four *_IMAGE vars, so
        # the resolution loop is never reached and this bug is invisible — the
        # same harness gap that let the --dry-run regression ship.
        with tempfile.TemporaryDirectory() as tmp:
            repo = self.make_repo(tmp)
            result = self.run_scan(
                repo,
                "--only",
                "dependency_scanning",
                "--dry-run",
                env=self.self_loading_env(),
            )

        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        line = self.dry_run_line(result, "sbom-vuln-scan.sh:/runner.sh:ro")
        self.assertIn(
            "container-scanning:", line, "the SBOM match lost its advisory image"
        )
        self.assertNotIn(
            "no container-scanning image was resolved",
            result.stdout + result.stderr,
            "the match degraded instead of running",
        )

    def test_sbom_match_without_a_scanner_image_is_not_a_silent_pass(self) -> None:
        # No container-scanning image => no bundled trivy => nothing is matched.
        # The SBOM is still a valid dependency report, so the old version of this
        # test — a warning string plus a line in the skips file — passed while
        # normalize.py printed "Gate verdict: PASSED" and coverage_complete:true
        # for dependencies that had never been compared to any advisory DB.
        # Assert the invariant itself, not the side channels that announce it.
        with tempfile.TemporaryDirectory() as tmp:
            repo = self.make_repo(tmp)
            env = self.base_env(
                RUN_FORTIFY_SAST="false",
                RUN_SECRET_DETECTION="false",
                RUN_GITLAB_CS="false",
                GITLAB_CS_IMAGE="",
            )
            result = self.run_scan(repo, "--dry-run", env=env)
            results_dir = repo / ".appsec-results"
            skips = (results_dir / "scan-skips").read_text(encoding="utf-8")

            # Run the normalize command the dry run planned, against the SBOM the
            # dependency analyzer would have left behind. Nothing else is faked.
            (results_dir / "gl-sbom-python.cdx.json").write_text(
                json.dumps(
                    {
                        "bomFormat": "CycloneDX",
                        "specVersion": "1.5",
                        "components": [{"name": "flask", "version": "1.0"}],
                    }
                ),
                encoding="utf-8",
            )
            command = self.dry_run_line(result, "normalize.py").split(":", 1)[1]
            normalized = subprocess.run(
                [BASH, "-c", command],
                cwd=repo,
                env=env,
                capture_output=True,
                text=True,
            )
            coverage = json.loads(
                (results_dir / "scan-coverage.json").read_text(encoding="utf-8")
            )
            findings = json.loads(
                (results_dir / "findings.triaged.json").read_text(encoding="utf-8")
            )

        output = result.stdout + result.stderr
        self.assertEqual(result.returncode, 0, output)
        self.assertNotIn("sbom-vuln-scan.sh", output)
        self.assertIn("NOT an all-clear for dependencies", output)
        self.assertIn("dependency_scanning\t", skips)
        self.assertIn("re-run this skill", skips)

        report = normalized.stdout + normalized.stderr
        self.assertEqual(normalized.returncode, 1, report)
        self.assertIn("Gate verdict: FAILED", report)
        self.assertFalse(coverage["coverage_complete"], report)
        self.assertIn("dependency_scanning", coverage["missing_report"], report)
        self.assertIn(
            "APPSEC-REPORT-INCOMPLETE",
            [
                item["rule_id"]
                for item in findings
                if item["category"] == "dependency_scanning"
            ],
            report,
        )

    def test_registry_mode_passes_the_discovered_dockerfile_to_gtcs(self) -> None:
        # GTCS only generates base-image remediation when CS_DOCKERFILE_PATH
        # names the Dockerfile; it was never passed, so that never ran locally.
        with tempfile.TemporaryDirectory() as tmp:
            repo = self.make_repo(tmp)
            (repo / "docker").mkdir()
            (repo / "docker" / "app.Dockerfile").write_text(
                "FROM python:3.12-slim\n", encoding="utf-8"
            )
            result = self.run_scan(repo, "--dry-run")

        line = self.dry_run_line(result, "CS_SCAN_MODE=registry")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("CS_DOCKERFILE_PATH=./docker/app.Dockerfile", line)

    def test_airgap_settings_are_mounted_into_the_scanner_containers(self) -> None:
        # ca_bundle / maven_settings are HOST paths: forwarding them unmounted
        # points the scanner at a file that is not in the container, and the
        # failure looks like a TLS or mirror outage instead of a missing mount.
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "repo").mkdir()
            repo = self.make_repo(str(root / "repo"))
            ca_bundle = root / "internal-ca.pem"
            ca_bundle.write_text("-----BEGIN CERTIFICATE-----\n", encoding="utf-8")
            maven_settings = root / "settings-internal.xml"
            maven_settings.write_text("<settings/>\n", encoding="utf-8")
            temp_skill = self.make_skill_with_config(
                root,
                ('ca_bundle: ""', f'ca_bundle: "{ca_bundle}"'),
                ('pip_index_url: ""', 'pip_index_url: "https://jfrog.invalid/simple/"'),
                ('maven_settings: ""', f'maven_settings: "{maven_settings}"'),
            )
            env = self.self_loading_env(
                SKILL_DIR=str(temp_skill), CS_IMAGE="example/app:test"
            )
            result = self.run_scan(repo, "--dry-run", env=env)

        output = result.stdout + result.stderr
        self.assertEqual(result.returncode, 0, output)
        for marker in (
            "fortify-sast.sh:/runner.sh:ro",
            "gitlab-dependency-scanning.sh:/runner.sh:ro",
            "secret-detection.sh:/runner.sh:ro",
            "gitlab-container-scanning.sh:/runner.sh:ro",
            "sbom-vuln-scan.sh:/runner.sh:ro",
        ):
            with self.subTest(marker=marker):
                line = self.dry_run_line(result, marker)
                self.assertIn(f"{ca_bundle}:/appsec/ca-bundle.pem:ro", line)
                self.assertIn(
                    "ADDITIONAL_CA_CERT_BUNDLE=/appsec/ca-bundle.pem", line
                )

        ds_line = self.dry_run_line(result, "gitlab-dependency-scanning.sh:/runner.sh:ro")
        self.assertIn("PIP_INDEX_URL=https://jfrog.invalid/simple/", ds_line)
        self.assertIn(f"{maven_settings}:/appsec/maven-settings.xml:ro", ds_line)
        self.assertIn("MAVEN_ARGS=-s\\ /appsec/maven-settings.xml", ds_line)
        # Fortify's own maven build reads MAVEN_SETTINGS, and it too must get the
        # in-container path rather than the host one.
        sast_line = self.dry_run_line(result, "fortify-sast.sh:/runner.sh:ro")
        self.assertIn("MAVEN_SETTINGS=/appsec/maven-settings.xml", sast_line)


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


class FixBranchInputValidationTest(FixBranchTest):
    """The loop guard must reject garbage rather than silently pass it."""

    def test_non_integer_totals_are_rejected_without_touching_state(self) -> None:
        # <prev> <curr> are finding COUNTS. Passing the findings FILES is the
        # natural misreading right after "rescan", and it used to fall through:
        # `[ "$3" -ge "$2" ]` errors on a non-integer, but as an `if` condition
        # set -e does not fire, so the script persisted invalid JSON into
        # loop-state, advanced the iteration, and exited 0 as if progress
        # had been made.
        with tempfile.TemporaryDirectory() as tmp:
            repo = self.make_committed_repo(tmp)
            result = self.run_fix(
                repo, "--check-progress",
                "findings.normalized.json", "findings.triaged.json",
            )
            state = repo / ".appsec-results" / "loop-state"
            state_written = state.exists()

        self.assertEqual(result.returncode, 2, result.stdout + result.stderr)
        self.assertIn("integer finding COUNTS", result.stderr)
        self.assertFalse(state_written, "garbage input corrupted the loop state")


class CoverageExpectationTest(RunScanDryRunTest):
    """What the admin enabled is expected, whatever this invocation does."""

    def _expected(self, result):
        # --dry-run prints the normalize.py command; its --ran value IS the
        # expected-coverage set.
        match = re.search(r"--ran (\S+)", result.stdout + result.stderr)
        self.assertIsNotNone(match, result.stdout + result.stderr)
        return set(match.group(1).replace("\\", "").split(","))

    def test_partial_run_env_cannot_shrink_expected_coverage(self) -> None:
        # One leftover `export RUN_SECRET_DETECTION=true` suppressed run-scan's
        # self-load; the other three flags defaulted to false and vanished from
        # scan-coverage.json entirely — PASSED, exit 0, no warning at all.
        with tempfile.TemporaryDirectory() as tmp:
            repo = self.make_repo(tmp)
            env = {k: v for k, v in self.base_env().items() if not k.startswith("RUN_")}
            env["RUN_SECRET_DETECTION"] = "true"
            result = self.run_scan(repo, "--dry-run", env=env)

        expected = self._expected(result)
        self.assertIn("sast", expected)
        self.assertGreater(len(expected), 1, "expected coverage shrank to the exported flag")

    def test_only_as_first_scan_does_not_shrink_expected_coverage(self) -> None:
        # --only narrows what EXECUTES, never what is EXPECTED. As a first scan
        # it used to yield gate_passed true with three enabled categories absent
        # from both scanners_run and missing_report.
        with tempfile.TemporaryDirectory() as tmp:
            repo = self.make_repo(tmp)
            result = self.run_scan(repo, "--only", "secret_detection", "--dry-run")

        expected = self._expected(result)
        for category in ("sast", "dependency_scanning", "container_scanning"):
            self.assertIn(category, expected, f"{category} vanished from expected coverage")


class FailOpenPathsTest(RunScanDryRunTest):
    """Real-scan paths that used to end in a clean result they had not earned."""

    CLEAN_GITLAB_REPORT = '{"version":"15.0.0","vulnerabilities":[]}\n'

    def stub(self, root: Path, name: str, body: str) -> Path:
        """An executable stub, so PATH lookups and the runtime can be steered."""
        directory = root / (name + "-bin")
        directory.mkdir()
        script = directory / name
        script.write_text("#!/bin/sh\n" + body, encoding="utf-8")
        script.chmod(0o755)
        return script

    def real_scan_env(self, runtime: Path, **overrides: str) -> dict[str, str]:
        return self.base_env(RUNTIME=str(runtime), **overrides)

    def skill_enabling_only(self, root: Path, keep: str) -> Path:
        """A SKILL_DIR whose config enables `keep` and nothing else.

        Expected coverage is read from the admin config, so narrowing it there
        keeps the assertions about the one category under test instead of the
        three that were never meant to run.
        """
        components = {
            "sast": "fortify-sast/fortify-sast",
            "dependency_scanning": "dependency-scanning/dependency-scanning",
            "secret_detection": "secret-detection/secret-detection",
            "container_scanning": "container-scanning/container-scanning",
        }
        block = (
            "component: lobster-thermidor/devops/ci-catalogue/{path}\n"
            "        version: ~latest\n"
            "        enabled: {flag}"
        )
        return self.make_skill_with_config(
            root,
            *[
                (
                    block.format(path=path, flag="true"),
                    block.format(path=path, flag="false"),
                )
                for category, path in components.items()
                if category != keep
            ],
        )

    def results_of(self, repo: Path) -> Path:
        directory = repo / ".appsec-results"
        directory.mkdir(exist_ok=True)
        return directory

    def test_failed_scanner_cannot_inherit_the_previous_runs_clean_report(self) -> None:
        # Run 1 succeeded and left a clean gl-secret-detection-report.json behind.
        # Run 2's container never starts (bad image, no daemon, OOM). Nothing
        # cleared the results directory and the failure only warned, so run 1's
        # report was read as run 2's evidence: coverage_complete true, gate
        # PASSED, exit 0 — for a scan that did not happen.
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "repo").mkdir()
            repo = self.make_repo(str(root / "repo"))
            results = self.results_of(repo)
            stale = results / "gl-secret-detection-report.json"
            stale.write_text(self.CLEAN_GITLAB_REPORT, encoding="utf-8")
            runtime = self.stub(
                root,
                "fake-runtime",
                'case "$*" in *secret-detection.sh*) exit 137 ;; esac\nexit 0\n',
            )
            env = self.real_scan_env(
                runtime,
                SKILL_DIR=str(self.skill_enabling_only(root, "secret_detection")),
                RUN_FORTIFY_SAST="false",
                RUN_GITLAB_DS="false",
                RUN_GITLAB_CS="false",
            )
            result = self.run_scan(repo, env=env)
            stale_survived = stale.exists()
            skips = (results / "scan-skips").read_text(encoding="utf-8")
            coverage = json.loads(
                (results / "scan-coverage.json").read_text(encoding="utf-8")
            )

        output = result.stdout + result.stderr
        self.assertFalse(stale_survived, "the previous run's report stood in\n" + output)
        self.assertIn("secret_detection", skips, output)
        self.assertIn("secret_detection", coverage["missing_report"], coverage)
        self.assertFalse(coverage["coverage_complete"], coverage)
        self.assertFalse(coverage["gate_passed"], coverage)
        self.assertNotEqual(result.returncode, 0, output)

    def test_scoped_rescan_clears_only_its_own_category(self) -> None:
        # The other half of the staleness fix: a `--only` rescan RELIES on the
        # other categories' reports persisting from the previous full run. A
        # blanket wipe of .appsec-results would open three fresh coverage gaps on
        # every fix-loop iteration — a false alarm on an otherwise clean branch.
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "repo").mkdir()
            repo = self.make_repo(str(root / "repo"))
            results = self.results_of(repo)
            secret_report = results / "gl-secret-detection-report.json"
            secret_report.write_text(self.CLEAN_GITLAB_REPORT, encoding="utf-8")
            container_report = results / "gl-container-scanning-report.json"
            container_report.write_text(self.CLEAN_GITLAB_REPORT, encoding="utf-8")
            sbom = results / "gl-sbom-python.cdx.json"
            sbom.write_text(
                '{"bomFormat":"CycloneDX","specVersion":"1.5","components":[]}\n',
                encoding="utf-8",
            )
            runtime = self.stub(
                root,
                "fake-runtime",
                'case "$*" in *secret-detection.sh*) exit 1 ;; esac\nexit 0\n',
            )
            result = self.run_scan(
                repo,
                "--only",
                "secret_detection",
                env=self.real_scan_env(runtime),
            )
            secret_survived = secret_report.exists()
            others_survived = container_report.exists() and sbom.exists()
            coverage = json.loads(
                (results / "scan-coverage.json").read_text(encoding="utf-8")
            )

        output = result.stdout + result.stderr
        self.assertFalse(secret_survived, "the rescanned category kept run N-1's report\n" + output)
        self.assertIn("secret_detection", coverage["missing_report"], coverage)
        self.assertTrue(others_survived, "a scoped rescan deleted another category's report\n" + output)
        self.assertNotIn("container_scanning", coverage["missing_report"], coverage)
        self.assertNotIn("dependency_scanning", coverage["missing_report"], coverage)

    def test_container_scan_failure_is_recorded_as_a_coverage_gap(self) -> None:
        # The container-scanning failure paths warned and recorded nothing, so the
        # category still counted as covered — clean, if any older report was on
        # disk. Same hole as the parallel-scanner failure, different branch.
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "repo").mkdir()
            repo = self.make_repo(str(root / "repo"))
            results = self.results_of(repo)
            stale = results / "gl-container-scanning-report.json"
            stale.write_text(self.CLEAN_GITLAB_REPORT, encoding="utf-8")
            runtime = self.stub(
                root,
                "fake-runtime",
                'case "$*" in *gitlab-container-scanning.sh*) exit 1 ;; esac\nexit 0\n',
            )
            env = self.real_scan_env(
                runtime,
                SKILL_DIR=str(self.skill_enabling_only(root, "container_scanning")),
                RUN_FORTIFY_SAST="false",
                RUN_GITLAB_DS="false",
                RUN_SECRET_DETECTION="false",
            )
            result = self.run_scan(repo, env=env)
            stale_survived = stale.exists()
            skips = (results / "scan-skips").read_text(encoding="utf-8")
            coverage = json.loads(
                (results / "scan-coverage.json").read_text(encoding="utf-8")
            )

        output = result.stdout + result.stderr
        self.assertFalse(stale_survived, "the previous run's report stood in\n" + output)
        self.assertIn("container_scanning", skips, output)
        self.assertIn("container_scanning", coverage["missing_report"], coverage)
        self.assertFalse(coverage["coverage_complete"], coverage)
        self.assertNotEqual(result.returncode, 0, output)

    def test_broken_ls_does_not_silently_skip_the_sbom_match(self) -> None:
        # The trigger for the SBOM vulnerability match ran `ls` to ask whether an
        # SBOM exists. On the stripped PATH these airgapped hosts have, an `ls`
        # that cannot be resolved answered "no SBOM" — so the match was skipped,
        # nothing recorded that it was, and dependency findings stayed SBOM-only
        # (zero findings, no advisory ever consulted) while the run looked clean.
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "repo").mkdir()
            repo = self.make_repo(str(root / "repo"))
            runtime = self.stub(
                root,
                "fake-runtime",
                'case "$*" in\n'
                "  *gitlab-dependency-scanning.sh*)\n"
                "    printf '{\"bomFormat\":\"CycloneDX\",\"specVersion\":\"1.5\","
                '"components":[]}\' > .appsec-results/gl-sbom-python.cdx.json ;;\n'
                "  *sbom-vuln-scan.sh*) : > .appsec-results/sbom-match-ran ;;\n"
                "esac\n"
                "exit 0\n",
            )
            broken_ls = self.stub(root, "ls", 'echo "ls: not found" >&2\nexit 127\n')
            env = self.real_scan_env(runtime)
            env["PATH"] = f"{broken_ls.parent}{os.pathsep}{env['PATH']}"
            result = self.run_scan(repo, "--only", "dependency_scanning", env=env)
            results_dir = repo / ".appsec-results"
            matched = (results_dir / "sbom-match-ran").exists()
            skips = (results_dir / "scan-skips").read_text(encoding="utf-8")

        output = result.stdout + result.stderr
        self.assertTrue(matched, "the SBOM match was skipped with nothing recorded\n" + output)
        # The same broken `ls` also invented a lock-file gap for an SBOM that is
        # right there on disk — a false alarm on the happy path.
        self.assertNotIn("produced no SBOM", skips)

    def test_no_lockfile_does_not_gain_a_spurious_dependency_gap(self) -> None:
        # The other direction: with no SBOM at all there is nothing to match, and
        # the lock-file skip already names the real cause. A second "the match did
        # not run" gap here would fail every clean lockfile-less repo.
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "repo").mkdir()
            repo = self.make_repo(str(root / "repo"))
            runtime = self.stub(
                root,
                "fake-runtime",
                "case \"$*\" in *sbom-vuln-scan.sh*) : > .appsec-results/sbom-match-ran ;; esac\n"
                "exit 0\n",
            )
            result = self.run_scan(
                repo, "--only", "dependency_scanning", env=self.real_scan_env(runtime)
            )
            results_dir = repo / ".appsec-results"
            matched = (results_dir / "sbom-match-ran").exists()
            skips = (results_dir / "scan-skips").read_text(encoding="utf-8")

        output = result.stdout + result.stderr
        self.assertFalse(matched, "matched an SBOM that does not exist\n" + output)
        self.assertIn("produced no SBOM", skips)
        self.assertNotIn("local vulnerability match did not run", skips)

    def test_missing_python3_is_not_a_pass(self) -> None:
        # Without python3 nothing is normalized, triaged or gated. This path used
        # to print "this is NOT an all-clear" and then exit 0 writing no
        # scan-coverage.json at all — so a scripted caller read a clean pass with
        # no machine-readable record able to contradict it.
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "repo").mkdir()
            repo = self.make_repo(str(root / "repo"))
            runtime = self.stub(root, "fake-runtime", "exit 0\n")
            # resolve-python.sh verifies the interpreter it finds; one that cannot
            # `import sys` is exactly what an unusable/absent python3 looks like.
            no_python = self.stub(root, "python3", "exit 1\n")
            env = self.real_scan_env(runtime)
            env["PATH"] = f"{no_python.parent}{os.pathsep}{env['PATH']}"
            result = self.run_scan(repo, "--only", "secret_detection", env=env)
            coverage_path = repo / ".appsec-results" / "scan-coverage.json"
            coverage = (
                json.loads(coverage_path.read_text(encoding="utf-8"))
                if coverage_path.exists()
                else None
            )

        output = result.stdout + result.stderr
        self.assertNotEqual(result.returncode, 0, "unassessed run reported success\n" + output)
        self.assertIsNotNone(coverage, "no coverage record contradicts the exit code\n" + output)
        self.assertFalse(coverage["gate_passed"], coverage)
        self.assertFalse(coverage["coverage_complete"], coverage)
        self.assertIn("sast", coverage["missing_report"], coverage)
        self.assertEqual(coverage["scanners_run"], [], coverage)


class CheckRemediationAtomicWriteTest(unittest.TestCase):
    """registry-availability.json must survive an interrupted write.

    It lives beside the orchestrator tests because run-scan.sh is what invokes
    check-remediation.py — between its two normalize passes, which is the window
    an interrupt lands in.
    """

    def load_module(self):
        spec = importlib.util.spec_from_file_location(
            "check_remediation_atomic", SCRIPTS_DIR / "check-remediation.py"
        )
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module

    def test_interrupted_write_keeps_the_previous_map(self) -> None:
        # A plain write_text truncates first, so Ctrl-C (or a killed run) partway
        # through left an empty or half-written availability map — and every
        # remediation verdict then silently degrades to unknown.
        module = self.load_module()
        previous = {"npm|lodash|4.17.21": "available"}
        real_write_text = Path.write_text

        def interrupted_write(self, data, *args, **kwargs):
            real_write_text(self, data[: len(data) // 2], *args, **kwargs)
            raise KeyboardInterrupt

        with tempfile.TemporaryDirectory() as tmp:
            out_path = Path(tmp) / "registry-availability.json"
            out_path.write_text(json.dumps(previous), encoding="utf-8")
            with mock.patch.object(Path, "write_text", interrupted_write):
                with self.assertRaises(KeyboardInterrupt):
                    module.write_availability(out_path, {"npm|left-pad|1.3.0": "absent"})
            survived = json.loads(out_path.read_text(encoding="utf-8"))
            leftovers = sorted(path.name for path in Path(tmp).iterdir())

        self.assertEqual(survived, previous)
        # normalize.py parses every *.json in the results directory, so a leftover
        # temp file must not end in .json or it becomes a phantom HIGH finding.
        self.assertEqual(
            [name for name in leftovers if name.endswith(".json")],
            ["registry-availability.json"],
            leftovers,
        )
