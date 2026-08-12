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
        # image: is no longer declared in the shipped config — it is derived from
        # the component template at run time (run-scan.sh, resolve-image.sh), so
        # load-prefs emits it empty.
        self.assertEqual(values["FORTIFY_SAST_IMAGE"], "")
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
        # Deliberately does NOT name a profile: profile names are per-estate, and
        # advising one that does not exist there is worse than advising none.
        self.assertIn("gitlab_instance", result.stderr)
        self.assertNotIn("APPSEC_PROFILE=company", result.stderr)

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

    def test_inline_comment_on_category_key_is_accepted(self) -> None:
        original = PREFERENCES_PATH.read_text(encoding="utf-8")
        modified = original.replace(
            "      container_scanning:\n",
            "      container_scanning:  # paused\n",
            1,
        )
        temp_path = self.write_temp_config(modified)
        self.addCleanup(lambda: temp_path.unlink(missing_ok=True))

        result = self.run_loader(temp_path)
        self.assertEqual(result.returncode, 0, result.stderr)

        values = self.eval_output(result.stdout, "RUN_GITLAB_CS", "ENABLED_COMPONENTS")
        self.assertEqual(values["RUN_GITLAB_CS"], "true")
        self.assertIn(
            "lobster-thermidor/devops/ci-catalogue/container-scanning/container-scanning|~latest|gitlab-container-scanning.sh",
            values["ENABLED_COMPONENTS"],
        )

    def test_crlf_on_enabled_scalar_is_normalized(self) -> None:
        original = PREFERENCES_PATH.read_text(encoding="utf-8")
        modified = original.replace(
            "        enabled: true\n",
            "        enabled: true\r\n",
            1,
        )
        temp_path = self.write_temp_config(modified)
        self.addCleanup(lambda: temp_path.unlink(missing_ok=True))

        result = self.run_loader(temp_path)
        self.assertEqual(result.returncode, 0, result.stderr)

        values = self.eval_output(result.stdout, "RUN_FORTIFY_SAST", "ENABLED_COMPONENTS")
        self.assertEqual(values["RUN_FORTIFY_SAST"], "true")
        self.assertIn(
            "lobster-thermidor/devops/ci-catalogue/fortify-sast/fortify-sast|~latest|fortify-sast.sh",
            values["ENABLED_COMPONENTS"],
        )

    def test_crlf_on_version_scalar_is_normalized(self) -> None:
        original = PREFERENCES_PATH.read_text(encoding="utf-8")
        modified = original.replace(
            "        version: ~latest\n",
            "        version: ~latest\r\n",
            1,
        )
        temp_path = self.write_temp_config(modified)
        self.addCleanup(lambda: temp_path.unlink(missing_ok=True))

        result = self.run_loader(temp_path)
        self.assertEqual(result.returncode, 0, result.stderr)

        values = self.eval_output(result.stdout, "ENABLED_COMPONENTS")
        self.assertIn(
            "lobster-thermidor/devops/ci-catalogue/fortify-sast/fortify-sast|~latest|fortify-sast.sh",
            values["ENABLED_COMPONENTS"],
        )
        self.assertNotIn("\r", values["ENABLED_COMPONENTS"])

    def test_unknown_category_warns_without_overwriting_previous_category(self) -> None:
        original = PREFERENCES_PATH.read_text(encoding="utf-8")
        modified = original.replace(
            "      container_scanning:\n",
            "      container_scaning:\n",
            1,
        )
        temp_path = self.write_temp_config(modified)
        self.addCleanup(lambda: temp_path.unlink(missing_ok=True))

        result = self.run_loader(temp_path)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("WARNING: unknown category key 'container_scaning'", result.stderr)

        values = self.eval_output(
            result.stdout,
            "RUN_SECRET_DETECTION",
            "RUN_GITLAB_CS",
            "ENABLED_COMPONENTS",
        )
        self.assertEqual(values["RUN_SECRET_DETECTION"], "true")
        self.assertEqual(values["RUN_GITLAB_CS"], "false")
        self.assertIn(
            "lobster-thermidor/devops/ci-catalogue/secret-detection/secret-detection|~latest|secret-detection.sh",
            values["ENABLED_COMPONENTS"],
        )
        self.assertNotIn(
            "container-scanning/container-scanning|~latest|secret-detection.sh",
            values["ENABLED_COMPONENTS"],
        )

    def test_enabled_components_pair_each_component_with_its_own_runner(self) -> None:
        result = self.run_loader(PREFERENCES_PATH)
        self.assertEqual(result.returncode, 0, result.stderr)

        values = self.eval_output(result.stdout, "ENABLED_COMPONENTS")
        component_runners = {
            component: runner
            for component, _version, runner, _image, _category in (
                entry.split("|", 4) for entry in values["ENABLED_COMPONENTS"].split()
            )
        }
        self.assertEqual(
            component_runners,
            {
                "lobster-thermidor/devops/ci-catalogue/fortify-sast/fortify-sast": "fortify-sast.sh",
                "lobster-thermidor/devops/ci-catalogue/dependency-scanning/dependency-scanning": "gitlab-dependency-scanning.sh",
                "lobster-thermidor/devops/ci-catalogue/secret-detection/secret-detection": "secret-detection.sh",
                "lobster-thermidor/devops/ci-catalogue/container-scanning/container-scanning": "gitlab-container-scanning.sh",
            },
        )

    def test_enabled_components_carry_their_category_as_field_five(self) -> None:
        """run-scan.sh needs the category so it stops hardcoding component paths."""
        result = self.run_loader(PREFERENCES_PATH)
        self.assertEqual(result.returncode, 0, result.stderr)

        values = self.eval_output(result.stdout, "ENABLED_COMPONENTS")
        entries = values["ENABLED_COMPONENTS"].split()
        self.assertEqual(len(entries), 4)
        for entry in entries:
            with self.subTest(entry=entry):
                self.assertEqual(entry.count("|"), 4, "tuple is component|version|runner|image|category")

        categories = {entry.split("|")[0].rsplit("/", 1)[-1]: entry.split("|")[4] for entry in entries}
        self.assertEqual(
            categories,
            {
                "fortify-sast": "sast",
                "dependency-scanning": "dependency_scanning",
                "secret-detection": "secret_detection",
                "container-scanning": "container_scanning",
            },
        )

    def test_tuple_positions_one_to_three_survive_the_appended_category(self) -> None:
        """The category was appended, not inserted, so the fields the consumers
        already read keep their positions.

        These are the literal idioms in scripts/revendor.sh (component + runner)
        and scripts/resolve-components.sh (component + version + runner). If a
        future field lands anywhere but the end, both silently mis-parse and
        resolve-components.sh feeds garbage to catalog.sh check-drift — the exact
        bogus-DRIFT failure its file header was written about.
        """
        result = self.run_loader(PREFERENCES_PATH)
        self.assertEqual(result.returncode, 0, result.stderr)
        values = self.eval_output(result.stdout, "ENABLED_COMPONENTS")

        script = r"""
        for tuple in $ENABLED_COMPONENTS; do
          component="${tuple%%|*}"; rest="${tuple#*|}"
          version="${rest%%|*}"; rest="${rest#*|}"
          runner="${rest%%|*}"
          printf '%s %s %s\n' "$component" "$version" "$runner"
        done
        """
        parsed = subprocess.run(
            [BASH, "-c", script],
            env=dict(os.environ, ENABLED_COMPONENTS=values["ENABLED_COMPONENTS"]),
            capture_output=True,
            text=True,
            check=True,
        )
        rows = [line.split() for line in parsed.stdout.splitlines()]
        self.assertEqual(len(rows), 4)
        for component, version, runner in rows:
            with self.subTest(component=component):
                self.assertTrue(component.startswith("lobster-thermidor/devops/ci-catalogue/"))
                self.assertEqual(version, "~latest")
                self.assertTrue(runner.endswith(".sh"))
                self.assertTrue((SKILL_DIR / "scanners" / runner).is_file())

    # ------------------------------------------------------------------
    # Airgap configuration surface
    # ------------------------------------------------------------------

    AIRGAP_VARS = (
        "CA_BUNDLE",
        "APPSEC_PIP_INDEX_URL",
        "MAVEN_SETTINGS",
        "BASE_IMAGE_REPO",
        "HARDENED_IMAGE_REPO",
    )

    def test_shipped_config_leaves_airgap_plumbing_disabled(self) -> None:
        """Empty means disabled: nothing is mounted and nothing is overridden."""
        result = self.run_loader(PREFERENCES_PATH)
        self.assertEqual(result.returncode, 0, result.stderr)

        values = self.eval_output(result.stdout, *self.AIRGAP_VARS)
        self.assertEqual(values["CA_BUNDLE"], "")
        self.assertEqual(values["APPSEC_PIP_INDEX_URL"], "")
        self.assertEqual(values["MAVEN_SETTINGS"], "")
        # base/hardened are the exception: the catalog profile ships public
        # values so an internet-connected run exercises the same probe path.
        self.assertEqual(values["BASE_IMAGE_REPO"], "docker.io/library/{image}:{tag}")
        self.assertEqual(values["HARDENED_IMAGE_REPO"], "cgr.dev/chainguard/{image}:{tag}")

    def test_pip_index_url_is_not_exported_under_pips_own_variable_name(self) -> None:
        """A bare PIP_INDEX_URL='' would be inherited by the developer's own pip."""
        result = self.run_loader(PREFERENCES_PATH)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertNotIn("export PIP_INDEX_URL=", result.stdout)

    def test_company_profile_inherits_the_empty_global_registry_templates(self) -> None:
        result = self.run_loader(PREFERENCES_PATH, APPSEC_PROFILE="company")
        self.assertEqual(result.returncode, 0, result.stderr)

        values = self.eval_output(result.stdout, *self.AIRGAP_VARS)
        for name in self.AIRGAP_VARS:
            with self.subTest(var=name):
                self.assertEqual(values[name], "")

    def populated_config(self) -> Path:
        """Shipped config with every airgap knob filled in by an admin."""
        text = PREFERENCES_PATH.read_text(encoding="utf-8")
        replacements = (
            ('  ca_bundle: ""   #', "  ca_bundle: /etc/ssl/certs/internal-ca.pem   #"),
            ('  pip_index_url: ""   #', "  pip_index_url: https://jfrog.internal/simple/   #"),
            ('  maven_settings: ""  #', "  maven_settings: /home/dev/settings-internal.xml  #"),
            ('    base_repo: ""      #', "    base_repo: dock.internal/docker-virtual/{image}:{tag}      #"),
            ('    hardened_repo: ""  #', "    hardened_repo: dock.internal/hardened-virtual/{image}:{tag}  #"),
        )
        for needle, replacement in replacements:
            self.assertIn(needle, text, f"config no longer contains {needle!r}")
            text = text.replace(needle, replacement, 1)
        path = self.write_temp_config(text)
        self.addCleanup(lambda: path.unlink(missing_ok=True))
        return path

    def test_populated_airgap_settings_reach_the_exports(self) -> None:
        result = self.run_loader(self.populated_config(), APPSEC_PROFILE="company")
        self.assertEqual(result.returncode, 0, result.stderr)

        values = self.eval_output(result.stdout, *self.AIRGAP_VARS)
        self.assertEqual(values["CA_BUNDLE"], "/etc/ssl/certs/internal-ca.pem")
        self.assertEqual(values["APPSEC_PIP_INDEX_URL"], "https://jfrog.internal/simple/")
        self.assertEqual(values["MAVEN_SETTINGS"], "/home/dev/settings-internal.xml")
        self.assertEqual(values["BASE_IMAGE_REPO"], "dock.internal/docker-virtual/{image}:{tag}")
        self.assertEqual(values["HARDENED_IMAGE_REPO"], "dock.internal/hardened-virtual/{image}:{tag}")

    def test_profile_level_registry_templates_override_the_global(self) -> None:
        result = self.run_loader(self.populated_config(), APPSEC_PROFILE="catalog")
        self.assertEqual(result.returncode, 0, result.stderr)

        values = self.eval_output(result.stdout, "BASE_IMAGE_REPO", "HARDENED_IMAGE_REPO")
        self.assertEqual(values["BASE_IMAGE_REPO"], "docker.io/library/{image}:{tag}")
        self.assertEqual(values["HARDENED_IMAGE_REPO"], "cgr.dev/chainguard/{image}:{tag}")

    def test_explicit_empty_profile_override_disables_an_inherited_global(self) -> None:
        """Same contract as auth_token_env: an explicit "" turns the probe off."""
        text = self.populated_config().read_text(encoding="utf-8")
        text = text.replace(
            "    gitlab_instance: https://gitlab.internal.example\n",
            '    gitlab_instance: https://gitlab.internal.example\n    base_repo: ""\n',
            1,
        )
        path = self.write_temp_config(text)
        self.addCleanup(lambda: path.unlink(missing_ok=True))

        result = self.run_loader(path, APPSEC_PROFILE="company")
        self.assertEqual(result.returncode, 0, result.stderr)

        values = self.eval_output(result.stdout, "BASE_IMAGE_REPO", "HARDENED_IMAGE_REPO")
        self.assertEqual(values["BASE_IMAGE_REPO"], "")
        self.assertEqual(
            values["HARDENED_IMAGE_REPO"], "dock.internal/hardened-virtual/{image}:{tag}",
            "an override of one key must not clear the other",
        )

    def test_ambient_maven_settings_is_not_clobbered_by_the_empty_default(self) -> None:
        """MAVEN_SETTINGS predates this config key; fortify-sast.sh already reads it."""
        result = self.run_loader(PREFERENCES_PATH, MAVEN_SETTINGS="/ambient/settings.xml")
        self.assertEqual(result.returncode, 0, result.stderr)

        values = self.eval_output(result.stdout, "MAVEN_SETTINGS")
        self.assertEqual(values["MAVEN_SETTINGS"], "/ambient/settings.xml")

    def test_settings_scalars_do_not_leak_into_the_next_nested_block(self) -> None:
        """The new indent-2 scalars sit between nested blocks; a stale block name
        would file the following indent-4 key under the wrong parent."""
        result = self.run_loader(PREFERENCES_PATH)
        self.assertEqual(result.returncode, 0, result.stderr)

        values = self.eval_output(
            result.stdout,
            "CS_USER_ENV",
            "CS_PASS_ENV",
            "CATALOG_AUTH_ENV",
            "CI_GATE_FAIL_ON",
        )
        self.assertEqual(values["CS_USER_ENV"], "CS_REGISTRY_USER")
        self.assertEqual(values["CS_PASS_ENV"], "CS_REGISTRY_PASSWORD")
        self.assertEqual(values["CATALOG_AUTH_ENV"], "GITLAB_READ_TOKEN")
        self.assertEqual(values["CI_GATE_FAIL_ON"], "high")

    def test_artifactory_credential_names_default_to_the_components(self) -> None:
        """Env var NAMES, not values. Defaulting to what the CI component reads
        means an estate that already sets those needs no config entry at all."""
        result = self.run_loader(PREFERENCES_PATH)
        self.assertEqual(result.returncode, 0, result.stderr)
        values = self.eval_output(
            result.stdout, "ARTIFACTORY_USER_ENV", "ARTIFACTORY_PASSWORD_ENV"
        )
        self.assertEqual(values["ARTIFACTORY_USER_ENV"], "ARTIFACTORY_USER")
        self.assertEqual(values["ARTIFACTORY_PASSWORD_ENV"], "ARTIFACTORY_PASSWORD")

    def test_artifactory_credential_names_are_overridable(self) -> None:
        """An estate that names its credentials differently must not have to
        rename its CI variables to run this skill locally."""
        temp_path = self.write_temp_config(
            PREFERENCES_PATH.read_text(encoding="utf-8")
            .replace("artifactory_user_env: ARTIFACTORY_USER",
                     "artifactory_user_env: JF_USER")
            .replace("artifactory_password_env: ARTIFACTORY_PASSWORD",
                     "artifactory_password_env: JF_TOKEN")
        )
        self.addCleanup(lambda: temp_path.unlink(missing_ok=True))
        result = self.run_loader(temp_path)
        self.assertEqual(result.returncode, 0, result.stderr)
        values = self.eval_output(
            result.stdout, "ARTIFACTORY_USER_ENV", "ARTIFACTORY_PASSWORD_ENV"
        )
        self.assertEqual(values["ARTIFACTORY_USER_ENV"], "JF_USER")
        self.assertEqual(values["ARTIFACTORY_PASSWORD_ENV"], "JF_TOKEN")

if __name__ == "__main__":
    unittest.main()
