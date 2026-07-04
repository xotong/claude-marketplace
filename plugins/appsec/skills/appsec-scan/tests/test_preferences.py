#!/usr/bin/env python3
"""Tests for the appsec-scan scanner preference configuration."""

from __future__ import annotations

import unittest
from pathlib import Path

try:
    import yaml
except ImportError as exc:  # pragma: no cover - environment dependent
    raise unittest.SkipTest("pyyaml not installed - pip install pyyaml") from exc


SKILL_DIR = Path(__file__).resolve().parents[1]
PREFERENCES_PATH = SKILL_DIR / "config" / "scanner-preferences.yaml"
SCANNERS_DIR = SKILL_DIR / "scanners"
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


class ScannerPreferencesTest(unittest.TestCase):
    def test_yaml_parses_to_dict(self) -> None:
        self.assertIsInstance(PREFERENCES, dict)

    def test_default_profile_exists_and_names_profile(self) -> None:
        default_profile = PREFERENCES.get("default_profile")
        profiles = PREFERENCES.get("profiles", {})

        self.assertIsInstance(profiles, dict)
        self.assertIn("default_profile", PREFERENCES)
        self.assertIn(default_profile, profiles)

    def test_every_profile_has_expected_categories(self) -> None:
        profiles = PREFERENCES["profiles"]

        for profile_name, profile in profiles.items():
            with self.subTest(profile=profile_name):
                categories = profile.get("categories")
                self.assertIsInstance(categories, dict)
                self.assertEqual(set(categories), EXPECTED_CATEGORIES)

    def test_every_category_has_components_runners_and_enabled(self) -> None:
        for profile_name, profile in PREFERENCES["profiles"].items():
            for category_name, category in profile["categories"].items():
                with self.subTest(profile=profile_name, category=category_name):
                    self.assertEqual(
                        set(category),
                        {"components", "runners", "enabled"},
                    )
                    self.assertIsInstance(category["components"], list)
                    self.assertTrue(category["components"])
                    self.assertIsInstance(category["runners"], list)
                    self.assertTrue(category["runners"])
                    self.assertIsInstance(category["enabled"], bool)

    def test_runner_entries_exist_under_scanners(self) -> None:
        for profile_name, profile in PREFERENCES["profiles"].items():
            for category_name, category in profile["categories"].items():
                for runner in category["runners"]:
                    if runner == "none":
                        continue
                    with self.subTest(
                        profile=profile_name,
                        category=category_name,
                        runner=runner,
                    ):
                        self.assertTrue((SCANNERS_DIR / runner).is_file())

    def test_additional_scanner_runners_exist_under_scanners(self) -> None:
        for profile_name, profile in PREFERENCES["profiles"].items():
            additional_scanners = profile.get("additional_scanners", {})
            self.assertIsInstance(additional_scanners, dict)
            for scanner_name, scanner_config in additional_scanners.items():
                with self.subTest(profile=profile_name, scanner=scanner_name):
                    runner = scanner_config.get("runner")
                    self.assertIsInstance(runner, str)
                    self.assertTrue((SCANNERS_DIR / runner).is_file())

    def test_public_test_profile_points_to_gitlab_dot_com(self) -> None:
        public_test = PREFERENCES["profiles"]["public-test"]
        self.assertEqual(public_test.get("gitlab_instance"), "https://gitlab.com")

    def test_company_profile_exists(self) -> None:
        self.assertIn("company", PREFERENCES["profiles"])

    def test_every_component_entry_looks_like_catalog_path(self) -> None:
        for profile_name, profile in PREFERENCES["profiles"].items():
            for category_name, category in profile["categories"].items():
                for component in category["components"]:
                    with self.subTest(
                        profile=profile_name,
                        category=category_name,
                        component=component,
                    ):
                        self.assertIsInstance(component, str)
                        self.assertGreaterEqual(component.count("/"), 2)


if __name__ == "__main__":
    unittest.main()
