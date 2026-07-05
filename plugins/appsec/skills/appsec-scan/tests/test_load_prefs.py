#!/usr/bin/env python3
"""Tests for the deterministic scanner preference loader."""

from __future__ import annotations

import os
import shutil
import subprocess
import tempfile
import textwrap
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
            "RUN_GITLAB_SAST",
            "RUN_GITLAB_DS",
            "RUN_SECRET_DETECTION",
            "RUN_GITLAB_CS",
            "RUN_FORTIFY",
            "RUN_PARASOFT",
            "RUN_PYLINT",
            "RUN_ESLINT",
            "RUN_SCANTIST",
            "RUN_TRIVY",
            "GITLAB_SAST_IMAGE",
            "GITLAB_INSTANCE",
            "ENABLED_COMPONENTS",
        )

        self.assertEqual(values["APPSEC_PROFILE"], "company")
        self.assertEqual(values["RUN_GITLAB_SAST"], "true")
        self.assertEqual(values["RUN_GITLAB_DS"], "true")
        self.assertEqual(values["RUN_SECRET_DETECTION"], "true")
        self.assertEqual(values["RUN_GITLAB_CS"], "true")
        self.assertEqual(values["RUN_FORTIFY"], "true")
        self.assertEqual(values["RUN_PARASOFT"], "true")
        self.assertEqual(values["RUN_PYLINT"], "true")
        self.assertEqual(values["RUN_ESLINT"], "true")
        self.assertEqual(values["RUN_SCANTIST"], "true")
        self.assertEqual(values["RUN_TRIVY"], "true")
        self.assertEqual(values["GITLAB_SAST_IMAGE"], "jfrog.internal/security/semgrep:6")
        self.assertEqual(values["GITLAB_INSTANCE"], "https://gitlab.internal.example")
        self.assertIn("components/sast/sast|gitlab-sast.sh", values["ENABLED_COMPONENTS"])
        self.assertNotIn("components/dast/dast|", values["ENABLED_COMPONENTS"])

    def test_env_override_wins(self) -> None:
        result = self.run_loader(PREFERENCES_PATH, GITLAB_SAST_IMAGE="custom:1")
        self.assertEqual(result.returncode, 0, result.stderr)

        values = self.eval_output(result.stdout, "GITLAB_SAST_IMAGE")
        self.assertEqual(values["GITLAB_SAST_IMAGE"], "custom:1")

    def test_unknown_profile_fails_with_available_profiles(self) -> None:
        result = self.run_loader(PREFERENCES_PATH, APPSEC_PROFILE="nonexistent")
        self.assertEqual(result.returncode, 1)
        self.assertIn("company", result.stderr)
        self.assertIn("public-test", result.stderr)

    def test_public_test_refused_under_airgap(self) -> None:
        result = self.run_loader(PREFERENCES_PATH, APPSEC_PROFILE="public-test")
        self.assertEqual(result.returncode, 1)
        self.assertIn("airgap", result.stderr.lower())

    def test_public_test_default_allowed_when_airgap_false(self) -> None:
        temp_path = self.write_temp_config(
            textwrap.dedent(
                """
                settings:
                  airgap: false
                  container_runtime: auto
                  jq:
                    prefer: host
                    install_url: ""
                  catalog:
                    mode: online
                    auth_token_env: ""
                  container_registry:
                    user_env: CS_REGISTRY_USER
                    password_env: CS_REGISTRY_PASSWORD
                default_profile: public-test
                profiles:
                  public-test:
                    gitlab_instance: https://gitlab.com
                    categories:
                      sast:
                        component: components/sast/sast
                        image: registry.gitlab.com/security-products/semgrep:6
                        runner: gitlab-sast.sh
                        enabled: true
                      dependency_scanning:
                        component: components/dependency-scanning/main
                        image: registry.gitlab.com/security-products/dependency-scanning:2
                        runner: gitlab-dependency-scanning.sh
                        enabled: false
                      secret_detection:
                        component: components/secret-detection/secret-detection
                        image: registry.gitlab.com/security-products/secrets:7
                        runner: secret-detection.sh
                        enabled: false
                      container_scanning:
                        component: components/container-scanning/container-scanning
                        image: registry.gitlab.com/security-products/container-scanning:8
                        runner: gitlab-container-scanning.sh
                        enabled: false
                      dast_web:
                        component: components/dast/dast
                        image: ""
                        runner: none
                        enabled: false
                      dast_api:
                        component: components/dast/dast
                        image: ""
                        runner: none
                        enabled: false
                    additional_scanners: {}
                """
            ).lstrip()
        )
        self.addCleanup(lambda: temp_path.unlink(missing_ok=True))

        result = self.run_loader(temp_path)
        self.assertEqual(result.returncode, 0, result.stderr)

        values = self.eval_output(
            result.stdout,
            "APPSEC_PROFILE",
            "RUN_GITLAB_SAST",
            "RUN_GITLAB_DS",
            "RUN_SECRET_DETECTION",
            "RUN_GITLAB_CS",
            "RUN_FORTIFY",
            "RUN_PARASOFT",
            "RUN_PYLINT",
            "RUN_ESLINT",
            "RUN_SCANTIST",
            "RUN_TRIVY",
        )

        self.assertEqual(values["APPSEC_PROFILE"], "public-test")
        self.assertEqual(values["RUN_GITLAB_SAST"], "true")
        self.assertEqual(values["RUN_GITLAB_DS"], "false")
        self.assertEqual(values["RUN_SECRET_DETECTION"], "false")
        self.assertEqual(values["RUN_GITLAB_CS"], "false")
        self.assertEqual(values["RUN_FORTIFY"], "false")
        self.assertEqual(values["RUN_PARASOFT"], "false")
        self.assertEqual(values["RUN_PYLINT"], "false")
        self.assertEqual(values["RUN_ESLINT"], "false")
        self.assertEqual(values["RUN_SCANTIST"], "false")
        self.assertEqual(values["RUN_TRIVY"], "false")

    def test_disabled_sast_removes_flag_and_component_pair(self) -> None:
        original = PREFERENCES_PATH.read_text(encoding="utf-8")
        modified = original.replace("enabled: true", "enabled: false", 1)
        temp_path = self.write_temp_config(modified)
        self.addCleanup(lambda: temp_path.unlink(missing_ok=True))

        result = self.run_loader(temp_path)
        self.assertEqual(result.returncode, 0, result.stderr)

        values = self.eval_output(result.stdout, "RUN_GITLAB_SAST", "ENABLED_COMPONENTS")
        self.assertEqual(values["RUN_GITLAB_SAST"], "false")
        self.assertNotIn("components/sast/sast|gitlab-sast.sh", values["ENABLED_COMPONENTS"])


if __name__ == "__main__":
    unittest.main()
