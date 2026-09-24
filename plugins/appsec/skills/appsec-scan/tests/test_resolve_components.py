#!/usr/bin/env python3
"""Tests for scripts/resolve-components.sh's config-error gate.

catalog.sh labels every CONFIG-ERROR fallback (401/403, 404 with or without a
token, TLS verification, zero releases/tags) `offline-fallback: config-error`
-- only the pre-existing 401/403 case additionally keeps the older
`offline-fallback: unauthorized` label. resolve-components.sh's own job is to
turn either label into a failing step so a refused/misconfigured catalogue
credential can never read as a live check that passed.
"""

from __future__ import annotations

import os
import subprocess
import tempfile
import unittest
from pathlib import Path


SKILL_DIR = Path(__file__).resolve().parents[1]
SCRIPTS_DIR = SKILL_DIR / "scripts"
RESOLVE_COMPONENTS = SCRIPTS_DIR / "resolve-components.sh"


class ResolveComponentsConfigErrorGateTest(unittest.TestCase):
    def run_with_fake_catalog(self, resolve_line: str, *, runner: str = "none") -> subprocess.CompletedProcess[str]:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            fake_scripts = root / "scripts"
            fake_scripts.mkdir()
            fake_catalog = fake_scripts / "catalog.sh"
            fake_catalog.write_text(
                "#!/bin/sh\n"
                "case \"$1\" in\n"
                f"  resolve) printf '%s\\n' '{resolve_line}' ;;\n"
                "  check-drift) printf 'DRIFT-IMAGE=%s\\n' \"$5\" ;;\n"
                "esac\n",
                encoding="utf-8",
            )
            fake_catalog.chmod(0o755)
            (root / ".appsec-results").mkdir()

            env = dict(
                os.environ,
                SCRIPTS_DIR=str(fake_scripts),
                SKILL_DIR=str(root),
                SCANNERS_DIR=str(root / "scanners"),
                ENABLED_COMPONENTS=f"example/component|1.0.0|{runner}|img|sast",
                GITLAB_INSTANCE="https://gitlab.example.com",
                CATALOG_AUTH_ENV="",
                CATALOG_CACHE=str(root / ".appsec-results" / "catalog"),
            )
            return subprocess.run(
                ["bash", str(RESOLVE_COMPONENTS)],
                cwd=root,
                env=env,
                capture_output=True,
                text=True,
            )

    def test_config_error_label_fails_the_step(self) -> None:
        result = self.run_with_fake_catalog(
            "example/component@1.0.0 [offline-fallback: config-error]"
        )
        self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
        self.assertIn("offline-fallback: config-error", result.stderr)

    def test_unauthorized_label_still_fails_the_step(self) -> None:
        result = self.run_with_fake_catalog(
            "example/component@1.0.0 [offline-fallback: unauthorized]"
        )
        self.assertEqual(result.returncode, 1, result.stdout + result.stderr)

    def test_online_label_passes(self) -> None:
        result = self.run_with_fake_catalog("example/component@1.0.0 [online]")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_plain_offline_fallback_label_passes(self) -> None:
        # Environment failures (unreachable host, timeout) stay non-fatal --
        # that is the airgap guarantee, distinct from a config problem.
        result = self.run_with_fake_catalog(
            "example/component@1.0.0 [offline-fallback]"
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_check_drift_gets_image_field_without_category(self) -> None:
        # Tuple is component|version|runner|image|category; the trailing
        # ${rest#*|} form handed check-drift "img|sast" and produced bogus
        # "configured |dependency_scanning" DRIFT lines.
        result = self.run_with_fake_catalog(
            "example/component@1.0.0 [online]", runner="fortify-sast.sh"
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("DRIFT-IMAGE=img\n", result.stdout)


if __name__ == "__main__":
    unittest.main()
