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
    printf '%s\\n' '[{"name":"1.0.0"},{"name":"2.3.0"},{"name":"2.2.9"},{"name":"v0.9.0"},{"name":"2.4.0-rc1"},{"name":"3.0"}]'
    ;;
  */repository/files/templates%2Fsecret-detection.yml/raw?ref=3.0)
    exit 22
    ;;
  */repository/files/templates%2Fsecret-detection%2Ftemplate.yml/raw?ref=3.0)
    printf '%s\\n' 'spec:' '  inputs:' '    image_tag:' '      default: "3.0"'
    ;;
  */repository/files/README.md/raw?ref=3.0)
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
        component = "components/secret-detection/secret-detection"
        result = run(
            ["bash", str(CATALOG_SCRIPT), "resolve", "https://example.invalid", component, str(cache_dir)],
            cwd=REPO_ROOT,
            env=env,
        )

        self.assertEqual(
            result.stdout.strip().splitlines()[-1],
            f"{component}@3.0 [online]",
        )
        self.assertTrue((cache_dir / component / "3.0" / "template.yml").is_file())
        self.assertTrue((cache_dir / component / "3.0" / "README.md").is_file())

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
                "components/secret-detection/secret-detection",
                str(cache_dir),
            ],
            cwd=REPO_ROOT,
            env=env,
        )

        self.assertIn("[offline-fallback]", result.stdout)
        component_dir = REFERENCE_CATALOG / "components" / "secret-detection" / "secret-detection"
        tag_dirs = sorted(
            (path for path in component_dir.iterdir() if path.is_dir()),
            key=lambda path: tuple(int(part) for part in path.name.split(".")),
        )
        self.assertTrue(tag_dirs, f"missing vendored snapshot tags under {component_dir}")
        template_path = tag_dirs[-1] / "template.yml"
        template_text = template_path.read_text(encoding="utf-8")
        self.assertTrue(template_text.strip(), f"{template_path} is empty")
        self.assertIn("spec:", template_text)
        self.assertIn("inputs:", template_text)

    def test_resolve_supports_nested_template_path_when_flat_path_404s(self) -> None:
        script = """#!/bin/sh
set -eu
for last do :; done
url=$last
case "$url" in
  */repository/tags?per_page=100)
    printf '%s\\n' '[{"name":"2.1.0"}]'
    ;;
  */repository/files/templates%2Fmain.yml/raw?ref=2.1.0)
    exit 22
    ;;
  */repository/files/templates%2Fmain%2Ftemplate.yml/raw?ref=2.1.0)
    printf '%s\\n' 'spec:' '  inputs:' '    image_tag:' '      default: "2.1.0"'
    ;;
  */repository/files/README.md/raw?ref=2.1.0)
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
        component = "components/dependency-scanning/main"
        result = run(
            ["bash", str(CATALOG_SCRIPT), "resolve", "https://example.invalid", component, str(cache_dir)],
            cwd=REPO_ROOT,
            env=env,
        )

        self.assertEqual(
            result.stdout.strip().splitlines()[-1],
            f"{component}@2.1.0 [online]",
        )
        self.assertTrue((cache_dir / component / "2.1.0" / "template.yml").is_file())


class VendoredSnapshots(unittest.TestCase):
    def test_expected_components_have_snapshot_with_template_and_readme(self) -> None:
        components = [
            "components/sast/sast",
            "components/secret-detection/secret-detection",
            "components/dependency-scanning/main",
            "components/container-scanning/container-scanning",
        ]

        for component in components:
            with self.subTest(component=component):
                component_dir = REFERENCE_CATALOG / component
                self.assertTrue(component_dir.is_dir(), f"missing snapshot root for {component}")
                tag_dirs = [path for path in component_dir.iterdir() if path.is_dir()]
                self.assertTrue(tag_dirs, f"missing tag directories for {component}")
                self.assertTrue(
                    any(
                        (tag_dir / "template.yml").is_file() and (tag_dir / "README.md").is_file()
                        for tag_dir in tag_dirs
                    ),
                    f"expected template.yml and README.md under at least one tag for {component}",
                )


if __name__ == "__main__":
    unittest.main()
