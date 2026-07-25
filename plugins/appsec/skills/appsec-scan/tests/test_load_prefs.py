#!/usr/bin/env python3
"""Tests for the deterministic scanner preference loader."""

from __future__ import annotations

import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path


SKILL_DIR = Path(__file__).resolve().parents[1]
PREFERENCES_PATH = SKILL_DIR / "config" / "scanner-preferences.yaml"
LOAD_PREFS = SKILL_DIR / "scripts" / "load-prefs.sh"
BASH = shutil.which("bash") or "/bin/bash"


class LoadPrefsTest(unittest.TestCase):
    maxDiff = None

    def run_loader(self, config_path: Path, **env_overrides: str) -> subprocess.CompletedProcess[str]:
        env = dict(os.environ)
        env.update(env_overrides)
        return subprocess.run(
            [BASH, str(LOAD_PREFS), str(config_path)],
            env=env,
            capture_output=True,
            text=True,
        )

    def eval_output(self, assignments: str, *names: str) -> dict[str, str]:
        command = "eval \"$1\"; " + " ".join(
            f"printf '%s=%s\\n' '{name}' \"${{{name}}}\";" for name in names
        )
        result = subprocess.run(
            [BASH, "-c", command, "bash", assignments],
            capture_output=True,
            text=True,
            check=True,
        )
        values: dict[str, str] = {}
        for line in result.stdout.splitlines():
            key, value = line.split("=", 1)
            values[key] = value
        return values

    def write_temp_config(self, content: str) -> Path:
        tmp = tempfile.NamedTemporaryFile("w", delete=False, suffix=".yaml")
        try:
            tmp.write(content)
            return Path(tmp.name)
        finally:
            tmp.close()

    def test_shipped_config_defaults(self) -> None:
        result = self.run_loader(PREFERENCES_PATH)
        self.assertEqual(result.returncode, 0, result.stderr)

        values = self.eval_output(
            result.stdout,
            "APPSEC_PROFILE",
            "RUN_FORTIFY_SAST",
            "RUN_GITLAB_DS",
            "RUN_SECRET_DETECTION",
            "RUN_GITLAB_CS",
            "FORTIFY_SAST_IMAGE",
            "GITLAB_INSTANCE",
            "ENABLED_COMPONENTS",
            "PYTHON_INSTALL_URL",
            "CI_GATE_FAIL_ON",
        )

        self.assertEqual(values["APPSEC_PROFILE"], "catalog")
        self.assertEqual(values["RUN_FORTIFY_SAST"], "true")
        self.assertEqual(values["RUN_GITLAB_DS"], "true")
        self.assertEqual(values["RUN_SECRET_DETECTION"], "true")
        self.assertEqual(values["RUN_GITLAB_CS"], "true")
        self.assertEqual(
            values["FORTIFY_SAST_IMAGE"],
            "registry.gitlab.com/lobster-thermidor/devops/ci-catalogue/docker-images/fortify-sca:25.2.0-jdk17-review",
        )
        self.assertEqual(values["GITLAB_INSTANCE"], "https://gitlab.com")
        self.assertEqual(values["PYTHON_INSTALL_URL"], "")
        self.assertEqual(values["CI_GATE_FAIL_ON"], "high")
        self.assertIn(
            "lobster-thermidor/devops/ci-catalogue/fortify-sast/fortify-sast|~latest|fortify-sast.sh",
            values["ENABLED_COMPONENTS"],
        )
        self.assertIn(
            "lobster-thermidor/devops/ci-catalogue/container-scanning/container-scanning|~latest|gitlab-container-scanning.sh",
            values["ENABLED_COMPONENTS"],
        )
        self.assertNotIn("RUN_GITLAB_SAST=", result.stdout)
        self.assertNotIn("RUN_FORTIFY=", result.stdout)
        self.assertNotIn("RUN_" + "PARA" + "SOFT=", result.stdout)
        self.assertNotIn("RUN_" + "PY" + "LINT=", result.stdout)
        self.assertNotIn("RUN_" + "ES" + "LINT=", result.stdout)
        self.assertNotIn("RUN_" + "SCAN" + "TIST=", result.stdout)
        self.assertNotIn("RUN_" + "TRI" + "VY=", result.stdout)
        self.assertNotIn("RUN_SCANNER=", result.stdout)
        self.assertNotIn("GITLAB_" + "SAST_IMAGE=", result.stdout)

    def test_env_override_wins(self) -> None:
        result = self.run_loader(PREFERENCES_PATH, FORTIFY_SAST_IMAGE="custom:1")
        self.assertEqual(result.returncode, 0, result.stderr)

        values = self.eval_output(result.stdout, "FORTIFY_SAST_IMAGE")
        self.assertEqual(values["FORTIFY_SAST_IMAGE"], "custom:1")

    def test_unknown_profile_fails_with_available_profiles(self) -> None:
        result = self.run_loader(PREFERENCES_PATH, APPSEC_PROFILE="nonexistent")
        self.assertEqual(result.returncode, 1)
        self.assertIn("company", result.stderr)
        self.assertIn("catalog", result.stderr)

    def test_airgap_refuses_catalog_profile_targeting_gitlab_com(self) -> None:
        original = PREFERENCES_PATH.read_text(encoding="utf-8")
        temp_path = self.write_temp_config(original.replace("airgap: false", "airgap: true", 1))
        self.addCleanup(lambda: temp_path.unlink(missing_ok=True))

        result = self.run_loader(temp_path, APPSEC_PROFILE="catalog")
        self.assertEqual(result.returncode, 1)
        self.assertIn("APPSEC_PROFILE='catalog'", result.stderr)
        self.assertIn("APPSEC_PROFILE=company", result.stderr)

    def test_disabled_sast_removes_flag_and_component_triple(self) -> None:
        original = PREFERENCES_PATH.read_text(encoding="utf-8")
        modified = original.replace("        enabled: true", "        enabled: false", 1)
        temp_path = self.write_temp_config(modified)
        self.addCleanup(lambda: temp_path.unlink(missing_ok=True))

        result = self.run_loader(temp_path)
        self.assertEqual(result.returncode, 0, result.stderr)

        values = self.eval_output(result.stdout, "RUN_FORTIFY_SAST", "ENABLED_COMPONENTS")
        self.assertEqual(values["RUN_FORTIFY_SAST"], "false")
        self.assertNotIn(
            "lobster-thermidor/devops/ci-catalogue/fortify-sast/fortify-sast|~latest|fortify-sast.sh",
            values["ENABLED_COMPONENTS"],
        )


if __name__ == "__main__":
    unittest.main()
