#!/usr/bin/env python3
"""Tests for the appsec-scan scanner preference configuration (v2 schema)."""

from __future__ import annotations

import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

try:
    import yaml
except ImportError as exc:  # pragma: no cover - environment dependent
    raise unittest.SkipTest("pyyaml not installed - pip install pyyaml") from exc


SKILL_DIR = Path(__file__).resolve().parents[1]
PREFERENCES_PATH = SKILL_DIR / "config" / "scanner-preferences.yaml"
SCANNERS_DIR = SKILL_DIR / "scanners"
SCRIPTS_DIR = SKILL_DIR / "scripts"
EXPECTED_CATEGORIES = {
    "sast",
    "dependency_scanning",
    "secret_detection",
    "container_scanning",
}

with PREFERENCES_PATH.open("r", encoding="utf-8") as fh:
    PREFERENCES = yaml.safe_load(fh)


class SettingsBlockTest(unittest.TestCase):
    def setUp(self) -> None:
        self.settings = PREFERENCES.get("settings", {})

    def test_settings_block_present(self) -> None:
        self.assertIsInstance(self.settings, dict)

    def test_airgap_is_boolean(self) -> None:
        self.assertIn("airgap", self.settings)
        self.assertIsInstance(self.settings["airgap"], bool)

    def test_container_runtime_valid(self) -> None:
        self.assertIn(self.settings.get("container_runtime"), {"auto", "docker", "podman"})

    def test_catalog_mode_valid(self) -> None:
        self.assertIn(self.settings.get("catalog", {}).get("mode"), {"online", "offline"})

    def test_tooling_gate_and_container_registry_keys(self) -> None:
        self.assertIn("install_url", self.settings.get("jq", {}))
        self.assertIn("install_url", self.settings.get("python", {}))
        self.assertIn(
            self.settings.get("ci_gate", {}).get("fail_on"),
            {"critical", "high", "medium", "none"},
        )
        cr = self.settings.get("container_registry", {})
        self.assertIn("user_env", cr)
        self.assertIn("password_env", cr)


class ScannerPreferencesTest(unittest.TestCase):
    def test_default_profile_is_catalog(self) -> None:
        self.assertEqual(PREFERENCES.get("default_profile"), "catalog")
        self.assertIn("catalog", PREFERENCES.get("profiles", {}))

    def test_every_profile_has_expected_categories(self) -> None:
        for profile_name, profile in PREFERENCES["profiles"].items():
            with self.subTest(profile=profile_name):
                self.assertEqual(set(profile.get("categories", {})), EXPECTED_CATEGORIES)

    def test_every_category_has_component_image_runner_enabled(self) -> None:
        for profile_name, profile in PREFERENCES["profiles"].items():
            for category_name, category in profile["categories"].items():
                with self.subTest(profile=profile_name, category=category_name):
                    self.assertEqual(set(category), {"component", "version", "image", "runner", "enabled"})
                    self.assertIsInstance(category["component"], str)
                    self.assertGreaterEqual(category["component"].count("/"), 2)
                    self.assertIsInstance(category["version"], str)
                    self.assertTrue(category["version"])
                    self.assertIsInstance(category["image"], str)
                    self.assertIsInstance(category["runner"], str)
                    self.assertIsInstance(category["enabled"], bool)

    def test_enabled_category_runner_exists_or_none(self) -> None:
        for profile_name, profile in PREFERENCES["profiles"].items():
            for category_name, category in profile["categories"].items():
                runner = category["runner"]
                with self.subTest(profile=profile_name, category=category_name, runner=runner):
                    self.assertTrue((SCANNERS_DIR / runner).is_file())

    def test_enabled_runner_category_has_image(self) -> None:
        for profile_name, profile in PREFERENCES["profiles"].items():
            for category_name, category in profile["categories"].items():
                if category["enabled"]:
                    with self.subTest(profile=profile_name, category=category_name):
                        self.assertTrue(category["image"], "enabled runner needs an image")

    def test_catalog_profile_targets_gitlab_com(self) -> None:
        self.assertEqual(
            PREFERENCES["profiles"]["catalog"]["gitlab_instance"], "https://gitlab.com"
        )

    def test_catalog_and_company_profiles_exist(self) -> None:
        self.assertIn("catalog", PREFERENCES["profiles"])
        self.assertIn("company", PREFERENCES["profiles"])


class HelperScriptsTest(unittest.TestCase):
    """The airgap helper scripts must exist, be executable, and behave sanely."""

    def make_stub_dir(self, tmp: str, scripts: dict[str, str]) -> Path:
        bin_dir = Path(tmp) / "bin"
        bin_dir.mkdir()
        for name, body in scripts.items():
            path = bin_dir / name
            path.write_text(body, encoding="utf-8")
            path.chmod(0o755)
        return bin_dir

    def add_passthrough_tools(self, bin_dir: Path, tool_names: list[str]) -> None:
        for tool_name in tool_names:
            tool_path = shutil.which(tool_name)
            if tool_path is None:
                self.fail(f"required tool {tool_name} not found on host PATH")
            link_path = bin_dir / tool_name
            if not link_path.exists():
                link_path.symlink_to(tool_path)

    def run_script(
        self,
        script_name: str,
        *,
        env: dict[str, str] | None = None,
        cwd: str | None = None,
        args: list[str] | None = None,
    ) -> subprocess.CompletedProcess[str]:
        bash = shutil.which("bash") or "/bin/bash"
        return subprocess.run(
            [bash, str(SCRIPTS_DIR / script_name), *(args or [])],
            env=env,
            cwd=cwd,
            capture_output=True,
            text=True,
        )

    def test_helper_scripts_present_and_executable(self) -> None:
        for name in (
            "detect-runtime.sh",
            "resolve-jq.sh",
            "container-target.sh",
            "catalog.sh",
            "run-scan.sh",
            "resolve-python.sh",
            "fix-branch.sh",
        ):
            path = SCRIPTS_DIR / name
            with self.subTest(script=name):
                self.assertTrue(path.is_file(), f"{name} missing")
                self.assertTrue(os.access(path, os.X_OK), f"{name} not executable")

    def test_detect_runtime_errors_when_forced_missing(self) -> None:
        # Forcing a bogus runtime must fail cleanly (non-zero), not crash.
        env = dict(os.environ, CONTAINER_RUNTIME="podman")
        # If podman is genuinely installed this returns it; either way exit code is defined.
        result = subprocess.run(
            ["bash", str(SCRIPTS_DIR / "detect-runtime.sh")],
            env=env, capture_output=True, text=True,
        )
        self.assertIn(result.returncode, (0, 1))
        if result.returncode == 0:
            self.assertEqual(result.stdout.strip(), "podman")

    def test_resolve_jq_degrades_without_url(self) -> None:
        # jq absent (empty PATH) and no install_url → exit 0, print nothing.
        # Launch bash by absolute path so an empty PATH only hides jq, not bash.
        env = dict(os.environ, PATH="", JQ_INSTALL_URL="")
        result = self.run_script("resolve-jq.sh", env=env)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.strip(), "")

    def test_detect_runtime_errors_when_auto_finds_no_runtime(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            env = dict(os.environ, PATH=tmp, CONTAINER_RUNTIME="auto")
            result = self.run_script("detect-runtime.sh", env=env)

        self.assertEqual(result.returncode, 1)
        self.assertEqual(result.stdout.strip(), "")
        self.assertIn("no container runtime found", result.stderr)

    def test_detect_runtime_rejects_invalid_forced_value(self) -> None:
        # Contract: invalid values do not fall back to auto-detection; they hard-fail.
        env = dict(os.environ, CONTAINER_RUNTIME="bogus")
        result = self.run_script("detect-runtime.sh", env=env)

        self.assertEqual(result.returncode, 1)
        self.assertEqual(result.stdout.strip(), "")
        self.assertIn("unsupported CONTAINER_RUNTIME 'bogus'", result.stderr)

    def test_resolve_jq_returns_existing_jq_path(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            bin_dir = self.make_stub_dir(
                tmp,
                {
                    "jq": "#!/bin/sh\nexit 0\n",
                },
            )
            env = dict(os.environ, PATH=str(bin_dir))
            result = self.run_script("resolve-jq.sh", env=env)

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertTrue(result.stdout.strip().endswith("/jq"))
        self.assertEqual(result.stdout.strip(), str(bin_dir / "jq"))

    def test_resolve_jq_warns_and_degrades_when_download_fails(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            bin_dir = self.make_stub_dir(
                tmp,
                {
                    "curl": "#!/bin/sh\nexit 7\n",
                    "uname": "#!/bin/sh\nexec /usr/bin/uname \"$@\"\n",
                    "tr": "#!/bin/sh\nexec /usr/bin/tr \"$@\"\n",
                    "mkdir": "#!/bin/sh\nexec /bin/mkdir \"$@\"\n",
                    "chmod": "#!/bin/sh\nexec /bin/chmod \"$@\"\n",
                },
            )
            env = dict(
                os.environ,
                PATH=str(bin_dir),
                APPSEC_RESULTS_DIR=str(Path(tmp) / "results"),
                JQ_INSTALL_URL="https://example.invalid/{os}/{arch}/jq",
            )
            result = self.run_script("resolve-jq.sh", env=env)

        self.assertEqual(result.returncode, 0)
        self.assertEqual(result.stdout.strip(), "")
        self.assertIn("WARNING: failed to download jq", result.stderr)

    def test_container_target_defers_when_no_image_no_dockerfile(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            env = dict(os.environ, CS_IMAGE="")
            result = self.run_script(
                "container-target.sh",
                cwd=tmp,
                env=env,
                args=["docker", "app", ".appsec-results"],
            )
            self.assertEqual(result.returncode, 0)
            self.assertEqual(result.stdout.strip(), "none|")

    def test_container_target_uses_cs_image_when_set(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            env = dict(os.environ, CS_IMAGE="jfrog.internal/app:1.2.3")
            result = self.run_script(
                "container-target.sh",
                cwd=tmp,
                env=env,
                args=["docker", "app", ".appsec-results"],
            )
            self.assertEqual(result.returncode, 0)
            self.assertEqual(result.stdout.strip(), "registry|jfrog.internal/app:1.2.3")

    def test_container_target_reports_build_failure_for_top_level_dockerfile(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            project_dir = Path(tmp)
            (project_dir / "Dockerfile").write_text("FROM scratch\n", encoding="utf-8")
            runtime_log = project_dir / "runtime.log"
            bin_dir = self.make_stub_dir(
                tmp,
                {
                    "fake-runtime": (
                        "#!/bin/sh\n"
                        "printf '%s\\n' \"$*\" >> \"$RUNTIME_LOG\"\n"
                        "if [ \"$1\" = \"build\" ]; then\n"
                        "  echo 'build failed' >&2\n"
                        "  exit 1\n"
                        "fi\n"
                        "exit 0\n"
                    ),
                },
            )
            self.add_passthrough_tools(bin_dir, ["mkdir", "dirname", "grep", "cat"])
            env = dict(os.environ, PATH=str(bin_dir), RUNTIME_LOG=str(runtime_log))
            result = self.run_script(
                "container-target.sh",
                cwd=tmp,
                env=env,
                args=["fake-runtime", "sample-app", str(project_dir / ".appsec-results")],
            )

            build_log = project_dir / ".appsec-results" / "container-build.log"
            self.assertEqual(result.returncode, 3)
            self.assertEqual(result.stdout.strip(), "error|build")
            self.assertIn("Container image build failed", result.stderr)
            self.assertIn(f"see {build_log}", result.stderr)
            self.assertTrue(build_log.is_file())
            self.assertIn("build -t appsec-local/sample-app:appsec-scan -f ./Dockerfile .", runtime_log.read_text(encoding="utf-8"))

    def test_container_target_discovers_nested_dockerfile_and_reports_build_failure(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            project_dir = Path(tmp)
            nested_dir = project_dir / "service"
            nested_dir.mkdir()
            (nested_dir / "Dockerfile").write_text("FROM scratch\n", encoding="utf-8")
            runtime_log = project_dir / "runtime.log"
            bin_dir = self.make_stub_dir(
                tmp,
                {
                    "fake-runtime": (
                        "#!/bin/sh\n"
                        "printf '%s\\n' \"$*\" >> \"$RUNTIME_LOG\"\n"
                        "if [ \"$1\" = \"build\" ]; then\n"
                        "  exit 1\n"
                        "fi\n"
                        "exit 0\n"
                    ),
                },
            )
            self.add_passthrough_tools(bin_dir, ["mkdir", "find", "dirname", "grep", "cat"])
            env = dict(os.environ, PATH=str(bin_dir), RUNTIME_LOG=str(runtime_log))
            result = self.run_script(
                "container-target.sh",
                cwd=tmp,
                env=env,
                args=["fake-runtime", "sample-app", str(project_dir / ".appsec-results")],
            )

            self.assertEqual(result.returncode, 3)
            self.assertEqual(result.stdout.strip(), "error|build")
            self.assertIn(
                "build -t appsec-local/sample-app:appsec-scan -f ./service/Dockerfile ./service",
                runtime_log.read_text(encoding="utf-8"),
            )


if __name__ == "__main__":
    unittest.main()
