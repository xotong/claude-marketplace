"""resolve-image.sh decides which scanner image actually runs.

The rule it must never break: follow the component's TAG, keep the admin's
REGISTRY. Getting that backwards sends an airgapped scan to a public registry;
dropping the availability check turns a mirror gap into a mid-scan crash.
"""

from __future__ import annotations

import os
import stat
import subprocess
import tempfile
import unittest
from pathlib import Path

SKILL_DIR = Path(__file__).resolve().parents[1]
RESOLVE_IMAGE = SKILL_DIR / "scripts" / "resolve-image.sh"
CATALOG = SKILL_DIR / "scripts" / "catalog.sh"

CS_COMPONENT = "lobster-thermidor/devops/ci-catalogue/container-scanning/container-scanning"
DS_COMPONENT = "lobster-thermidor/devops/ci-catalogue/dependency-scanning/dependency-scanning"


class ResolveImageTest(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.bin = Path(self.tmp.name)

    def _runtime(self, name: str, pull_succeeds: bool) -> str:
        """A stub container runtime whose `pull` outcome we control."""
        path = self.bin / name
        path.write_text(
            "#!/bin/sh\n"
            f'[ "$1" = pull ] && exit {0 if pull_succeeds else 1}\n'
            "exit 0\n"
        )
        path.chmod(path.stat().st_mode | stat.S_IEXEC)
        return str(path)

    def _resolve(self, configured: str, template: str, runtime: str, policy: str = "") -> str:
        argv = ["bash", str(RESOLVE_IMAGE), configured, template, runtime]
        if policy:
            argv.append(policy)
        proc = subprocess.run(argv, capture_output=True, text=True, check=True)
        return proc.stdout.strip()

    def test_adopts_template_tag_but_keeps_configured_registry(self) -> None:
        """The whole point: new tag, our mirror. Never the template's registry."""
        result = self._resolve(
            "jfrog.internal/security/container-scanning:8",
            "registry.gitlab.com/security-products/container-scanning:8.6.31",
            self._runtime("docker-ok", True),
        )
        self.assertEqual(result, "jfrog.internal/security/container-scanning:8.6.31")
        self.assertNotIn("registry.gitlab.com", result)

    def test_falls_back_when_mirror_lacks_the_tag(self) -> None:
        """A mirror gap must degrade to the configured image, not fail the scan."""
        configured = "jfrog.internal/security/container-scanning:8"
        result = self._resolve(
            configured,
            "registry.gitlab.com/security-products/container-scanning:8.6.31",
            self._runtime("docker-fail", False),
        )
        self.assertEqual(result, configured)

    def test_fallback_names_the_image_to_mirror(self) -> None:
        """The warning has to be actionable, not just 'something went wrong'."""
        proc = subprocess.run(
            [
                "bash",
                str(RESOLVE_IMAGE),
                "jfrog.internal/security/container-scanning:8",
                "registry.gitlab.com/security-products/container-scanning:8.6.31",
                self._runtime("docker-fail2", False),
            ],
            capture_output=True,
            text=True,
            check=True,
        )
        self.assertIn("jfrog.internal/security/container-scanning:8.6.31", proc.stderr)
        self.assertIn("mirror", proc.stderr.lower())

    def test_pinned_policy_never_adopts_or_pulls(self) -> None:
        configured = "jfrog.internal/security/container-scanning:8"
        result = self._resolve(
            configured,
            "registry.gitlab.com/security-products/container-scanning:8.6.31",
            self._runtime("docker-ok2", True),
            policy="pinned",
        )
        self.assertEqual(result, configured)

    def test_underivable_template_image_keeps_configured(self) -> None:
        """dependency-scanning builds its image from $DS_ANALYZER_IMAGE."""
        configured = "jfrog.internal/security/dependency-scanning:2"
        self.assertEqual(
            self._resolve(configured, "", self._runtime("docker-ok3", True)),
            configured,
        )

    def test_registry_port_is_not_mistaken_for_a_tag(self) -> None:
        """registry:5000/foo has a colon that is a port, not a tag."""
        result = self._resolve(
            "registry:5000/security/secrets:7",
            "registry.gitlab.com/security-products/secrets:9",
            self._runtime("docker-ok4", True),
        )
        self.assertEqual(result, "registry:5000/security/secrets:9")

    def test_matching_tags_are_a_no_op(self) -> None:
        configured = "jfrog.internal/security/secrets:7"
        self.assertEqual(
            self._resolve(
                configured,
                "registry.gitlab.com/security-products/secrets:7",
                self._runtime("docker-ok5", True),
            ),
            configured,
        )

    def test_empty_configured_image_yields_nothing(self) -> None:
        self.assertEqual(self._resolve("", "anything:1", self._runtime("d6", True)), "")


class CatalogTemplateImageTest(unittest.TestCase):
    """template-image must read the vendored snapshot and stay offline."""

    def _template_image(self, component: str) -> str:
        proc = subprocess.run(
            ["bash", str(CATALOG), "template-image", component, "/nonexistent-cache-dir"],
            capture_output=True,
            text=True,
            cwd=str(SKILL_DIR),
            check=True,
            env={**os.environ, "PATH": os.environ.get("PATH", "")},
        )
        return proc.stdout.strip()

    def test_resolves_literal_template_image_offline(self) -> None:
        self.assertEqual(
            self._template_image(CS_COMPONENT),
            "registry.gitlab.com/security-products/container-scanning:8.6.31",
        )

    def test_prints_nothing_when_image_is_underivable(self) -> None:
        """Silence beats guessing: DS builds its ref from an undeclared variable."""
        self.assertEqual(self._template_image(DS_COMPONENT), "")


if __name__ == "__main__":
    unittest.main()
