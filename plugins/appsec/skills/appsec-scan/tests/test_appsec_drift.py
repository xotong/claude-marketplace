#!/usr/bin/env python3
"""Regression tests for the repository appsec contract-drift gate."""

from __future__ import annotations

import importlib.util
import re
import unittest
from pathlib import Path


SKILL_DIR = Path(__file__).resolve().parents[1]
REPO_ROOT = SKILL_DIR.parents[3]
DRIFT_CHECK = REPO_ROOT / "ci" / "check-appsec-drift.py"
LOAD_PREFS = SKILL_DIR / "scripts" / "load-prefs.sh"

_spec = importlib.util.spec_from_file_location("check_appsec_drift", DRIFT_CHECK)
assert _spec is not None and _spec.loader is not None
check_appsec_drift = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(check_appsec_drift)


class AppsecDriftTargetsTest(unittest.TestCase):
    def test_shipped_config_loads_all_enabled_targets_with_runners(self) -> None:
        targets = check_appsec_drift.load_targets()

        self.assertEqual(len(targets), 8)
        for target in targets:
            with self.subTest(profile=target["profile"], category=target["category"]):
                self.assertTrue(target["runner"])

    def test_default_runner_mapping_agrees_with_bash_loader(self) -> None:
        source = LOAD_PREFS.read_text(encoding="utf-8")
        function = re.search(
            r"(?ms)^default_runner_for\(\) \{\n(?P<body>.*?)^\}\n",
            source,
        )
        self.assertIsNotNone(function, "default_runner_for() not found in load-prefs.sh")

        bash_defaults = dict(
            re.findall(
                r"^\s+([a-z_]+)\)\s+printf '([^']+)' ;;$",
                function.group("body"),
                flags=re.MULTILINE,
            )
        )
        self.assertEqual(bash_defaults, check_appsec_drift.DEFAULT_RUNNERS)


if __name__ == "__main__":
    unittest.main()
