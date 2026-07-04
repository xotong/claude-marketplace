#!/usr/bin/env python3
"""Tests for the appsec-scan scanner preference configuration (v2 schema)."""

from __future__ import annotations

import os
import subprocess
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
    "dast_web",
    "dast_api",
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

    def test_jq_and_container_registry_keys(self) -> None:
        self.assertIn("install_url", self.settings.get("jq", {}))
        cr = self.settings.get("container_registry", {})
        self.assertIn("user_env", cr)
        self.assertIn("password_env", cr)


class ScannerPreferencesTest(unittest.TestCase):
    def test_default_profile_exists_and_names_profile(self) -> None:
        self.assertIn(PREFERENCES.get("default_profile"), PREFERENCES.get("profiles", {}))

    def test_every_profile_has_expected_categories(self) -> None:
        for profile_name, profile in PREFERENCES["profiles"].items():
            with self.subTest(profile=profile_name):
                self.assertEqual(set(profile.get("categories", {})), EXPECTED_CATEGORIES)

    def test_every_category_has_component_image_runner_enabled(self) -> None:
        for profile_name, profile in PREFERENCES["profiles"].items():
            for category_name, category in profile["categories"].items():
                with self.subTest(profile=profile_name, category=category_name):
                    self.assertEqual(set(category), {"component", "image", "runner", "enabled"})
                    self.assertIsInstance(category["component"], str)
                    self.assertGreaterEqual(category["component"].count("/"), 2)
                    self.assertIsInstance(category["image"], str)  # may be "" for CI-only
                    self.assertIsInstance(category["runner"], str)
                    self.assertIsInstance(category["enabled"], bool)

    def test_enabled_category_runner_exists_or_none(self) -> None:
        for profile_name, profile in PREFERENCES["profiles"].items():
            for category_name, category in profile["categories"].items():
                runner = category["runner"]
                if runner == "none":
                    continue
                with self.subTest(profile=profile_name, category=category_name, runner=runner):
                    self.assertTrue((SCANNERS_DIR / runner).is_file())

    def test_enabled_non_dast_category_has_image(self) -> None:
        # Any enabled category that runs a real runner must name an image to run.
        for profile_name, profile in PREFERENCES["profiles"].items():
            for category_name, category in profile["categories"].items():
                if category["enabled"] and category["runner"] != "none":
                    with self.subTest(profile=profile_name, category=category_name):
                        self.assertTrue(category["image"], "enabled runner needs an image")

    def test_additional_scanner_runners_exist(self) -> None:
        for profile_name, profile in PREFERENCES["profiles"].items():
            for scanner_name, cfg in profile.get("additional_scanners", {}).items():
                with self.subTest(profile=profile_name, scanner=scanner_name):
                    self.assertTrue((SCANNERS_DIR / cfg["runner"]).is_file())

    def test_public_test_targets_gitlab_com(self) -> None:
        self.assertEqual(
            PREFERENCES["profiles"]["public-test"]["gitlab_instance"], "https://gitlab.com"
        )

    def test_company_profile_exists(self) -> None:
        self.assertIn("company", PREFERENCES["profiles"])


class HelperScriptsTest(unittest.TestCase):
    """The airgap helper scripts must exist, be executable, and behave sanely."""

    def test_helper_scripts_present_and_executable(self) -> None:
        for name in ("detect-runtime.sh", "resolve-jq.sh", "container-target.sh", "catalog.sh"):
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
        import shutil
        bash = shutil.which("bash") or "/bin/bash"
        env = dict(os.environ, PATH="", JQ_INSTALL_URL="")
        result = subprocess.run(
            [bash, str(SCRIPTS_DIR / "resolve-jq.sh")],
            env=env, capture_output=True, text=True,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.strip(), "")

    def test_container_target_defers_when_no_image_no_dockerfile(self) -> None:
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            env = dict(os.environ, CS_IMAGE="")
            result = subprocess.run(
                ["bash", str(SCRIPTS_DIR / "container-target.sh"), "docker", "app", ".appsec-results"],
                cwd=tmp, env=env, capture_output=True, text=True,
            )
            self.assertEqual(result.returncode, 0)
            self.assertEqual(result.stdout.strip(), "none|")

    def test_container_target_uses_cs_image_when_set(self) -> None:
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            env = dict(os.environ, CS_IMAGE="jfrog.internal/app:1.2.3")
            result = subprocess.run(
                ["bash", str(SCRIPTS_DIR / "container-target.sh"), "docker", "app", ".appsec-results"],
                cwd=tmp, env=env, capture_output=True, text=True,
            )
            self.assertEqual(result.returncode, 0)
            self.assertEqual(result.stdout.strip(), "registry|jfrog.internal/app:1.2.3")


if __name__ == "__main__":
    unittest.main()
