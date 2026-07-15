#!/usr/bin/env python3
"""Tests for the appsec-scan catalog resolver script."""

from __future__ import annotations

import os
import subprocess
import tempfile
import unittest
from pathlib import Path


SKILL_DIR = Path(__file__).resolve().parents[1]
REPO_ROOT = SKILL_DIR.parents[3]
CATALOG_SCRIPT = SKILL_DIR / "scripts" / "catalog.sh"
REFERENCE_CATALOG = SKILL_DIR / "reference" / "catalog"
SECRET_COMPONENT = "lobster-thermidor/devops/ci-catalogue/secret-detection/secret-detection"
DS_COMPONENT = "lobster-thermidor/devops/ci-catalogue/dependency-scanning/dependency-scanning"


def run(
    cmd: list[str],
    cwd: Path,
    env: dict[str, str] | None = None,
    check: bool = True,
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        cmd,
        cwd=str(cwd),
        env=env,
        check=check,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
    )


class CatalogSelfTest(unittest.TestCase):
    def test_catalog_self_test_passes(self) -> None:
        result = run(["bash", str(CATALOG_SCRIPT), "self-test"], cwd=REPO_ROOT, check=False)

        self.assertEqual(result.returncode, 0, result.stdout)
        self.assertIn("online path ok", result.stdout)
        self.assertIn("pinned path advisory ok", result.stdout)
        self.assertIn("offline-fallback path ok", result.stdout)
        self.assertIn("check-drift DRIFT line ok", result.stdout)


class CatalogTagSelection(unittest.TestCase):
    def make_env_with_fake_curl(self, script_body: str) -> tuple[tempfile.TemporaryDirectory[str], dict[str, str]]:
        tmp = tempfile.TemporaryDirectory(prefix="appsec-catalog-")
        bin_dir = Path(tmp.name) / "bin"
        bin_dir.mkdir()
        curl_path = bin_dir / "curl"
        curl_path.write_text(script_body, encoding="utf-8")
        curl_path.chmod(0o755)

        env = os.environ.copy()
        env["PATH"] = f"{bin_dir}{os.pathsep}{env.get('PATH', '')}"
        return tmp, env

    def test_resolve_picks_highest_stable_numeric_tag_and_caches_files(self) -> None:
        script = """#!/bin/sh
set -eu
for last do :; done
url=$last
case "$url" in
  */repository/tags?per_page=100)
    printf '%s\\n' '[{"name":"1.0.0"},{"name":"1.1.0"},{"name":"v0.9.0"},{"name":"1.2.0-rc1"}]'
    ;;
  */repository/files/templates%2Fsecret-detection.yml/raw?ref=1.1.0)
    printf '%s\\n' 'spec:' '  inputs:' '    image_tag:' '      default: "1.1.0"'
    ;;
  */repository/files/README.md/raw?ref=1.1.0)
    printf '%s\\n' '# README'
    ;;
  */repository/files/AGENTS.md/raw?ref=1.1.0)
    printf '%s\\n' '# AGENTS'
    ;;
  *)
    exit 22
    ;;
esac
"""
        tmp, env = self.make_env_with_fake_curl(script)
        self.addCleanup(tmp.cleanup)

        cache_dir = Path(tmp.name) / "cache"
        result = run(
            ["bash", str(CATALOG_SCRIPT), "resolve", "https://example.invalid", SECRET_COMPONENT, "~latest", str(cache_dir)],
            cwd=REPO_ROOT,
            env=env,
        )

        self.assertEqual(
            result.stdout.strip().splitlines()[-1],
            f"{SECRET_COMPONENT}@1.1.0 [online]",
        )
        self.assertTrue((cache_dir / SECRET_COMPONENT / "1.1.0" / "template.yml").is_file())
        self.assertTrue((cache_dir / SECRET_COMPONENT / "1.1.0" / "README.md").is_file())
        self.assertTrue((cache_dir / SECRET_COMPONENT / "1.1.0" / "AGENTS.md").is_file())

    def test_resolve_emits_advisory_for_exact_pin_when_newer_stable_exists(self) -> None:
        script = """#!/bin/sh
set -eu
for last do :; done
url=$last
case "$url" in
  */repository/tags?per_page=100)
    printf '%s\\n' '[{"name":"25.2.0"},{"name":"25.1.0"}]'
    ;;
  */repository/files/templates%2Ffortify-sast.yml/raw?ref=25.1.0)
    printf '%s\\n' 'spec:' '  inputs:' '    image-tag:' '      default: "25.1.0"'
    ;;
  */repository/files/README.md/raw?ref=25.1.0)
    printf '%s\\n' '# README'
    ;;
  */repository/files/AGENTS.md/raw?ref=25.1.0)
    printf '%s\\n' '# AGENTS'
    ;;
  *)
    exit 22
    ;;
esac
"""
        tmp, env = self.make_env_with_fake_curl(script)
        self.addCleanup(tmp.cleanup)

        cache_dir = Path(tmp.name) / "cache"
        component = "lobster-thermidor/devops/ci-catalogue/fortify-sast/fortify-sast"
        result = run(
            ["bash", str(CATALOG_SCRIPT), "resolve", "https://example.invalid", component, "25.1.0", str(cache_dir)],
            cwd=REPO_ROOT,
            env=env,
        )

        self.assertIn(f"{component}@25.1.0 [online]", result.stdout)
        self.assertIn(
            f"ADVISORY: {component} pinned 25.1.0, newer stable 25.2.0 available",
            result.stdout,
        )

    def test_resolve_falls_back_to_vendored_snapshot_when_offline(self) -> None:
        script = """#!/bin/sh
exit 7
"""
        tmp, env = self.make_env_with_fake_curl(script)
        self.addCleanup(tmp.cleanup)

        cache_dir = Path(tmp.name) / "cache"
        result = run(
            [
                "bash",
                str(CATALOG_SCRIPT),
                "resolve",
                "https://example.invalid",
                SECRET_COMPONENT,
                "~latest",
                str(cache_dir),
            ],
            cwd=REPO_ROOT,
            env=env,
        )

        self.assertIn("[offline-fallback]", result.stdout)
        component_dir = REFERENCE_CATALOG / SECRET_COMPONENT
        tag_dirs = sorted(
            (path for path in component_dir.iterdir() if path.is_dir()),
            key=lambda path: tuple(int(part) for part in path.name.split(".")),
        )
        self.assertTrue(tag_dirs, f"missing vendored snapshot tags under {component_dir}")
        self.assertTrue((tag_dirs[-1] / "template.yml").is_file())
        self.assertTrue((tag_dirs[-1] / "README.md").is_file())
        self.assertTrue((tag_dirs[-1] / "AGENTS.md").is_file())

    def test_resolve_supports_nested_template_path_when_flat_path_404s(self) -> None:
        script = """#!/bin/sh
set -eu
for last do :; done
url=$last
case "$url" in
  */repository/tags?per_page=100)
    printf '%s\\n' '[{"name":"1.0.0"}]'
    ;;
  */repository/files/templates%2Fdependency-scanning.yml/raw?ref=1.0.0)
    exit 22
    ;;
  */repository/files/templates%2Fdependency-scanning%2Ftemplate.yml/raw?ref=1.0.0)
    printf '%s\\n' 'spec:' '  inputs:' '    image_tag:' '      default: "1.0.0"'
    ;;
  */repository/files/README.md/raw?ref=1.0.0)
    printf '%s\\n' '# README'
    ;;
  *)
    exit 22
    ;;
esac
"""
        tmp, env = self.make_env_with_fake_curl(script)
        self.addCleanup(tmp.cleanup)

        cache_dir = Path(tmp.name) / "cache"
        result = run(
            ["bash", str(CATALOG_SCRIPT), "resolve", "https://example.invalid", DS_COMPONENT, "~latest", str(cache_dir)],
            cwd=REPO_ROOT,
            env=env,
        )

        self.assertEqual(
            result.stdout.strip().splitlines()[-1],
            f"{DS_COMPONENT}@1.0.0 [online]",
        )
        self.assertTrue((cache_dir / DS_COMPONENT / "1.0.0" / "template.yml").is_file())


class VendoredSnapshots(unittest.TestCase):
    def test_expected_components_have_snapshot_with_template_readme_and_agents(self) -> None:
        components = [
            "lobster-thermidor/devops/ci-catalogue/fortify-sast/fortify-sast",
            "lobster-thermidor/devops/ci-catalogue/dependency-scanning/dependency-scanning",
            "lobster-thermidor/devops/ci-catalogue/secret-detection/secret-detection",
            "lobster-thermidor/devops/ci-catalogue/container-scanning/container-scanning",
        ]

        for component in components:
            with self.subTest(component=component):
                component_dir = REFERENCE_CATALOG / component
                self.assertTrue(component_dir.is_dir(), f"missing snapshot root for {component}")
                tag_dirs = [path for path in component_dir.iterdir() if path.is_dir()]
                self.assertTrue(tag_dirs, f"missing tag directories for {component}")
                self.assertTrue(
                    any(
                        (tag_dir / "template.yml").is_file()
                        and (tag_dir / "README.md").is_file()
                        and (tag_dir / "AGENTS.md").is_file()
                        for tag_dir in tag_dirs
                    ),
                    f"expected template.yml, README.md, and AGENTS.md under at least one tag for {component}",
                )


if __name__ == "__main__":
    unittest.main()
