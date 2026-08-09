#!/usr/bin/env python3
"""Tests for resolve-base-image.sh's conservative three-verdict contract."""

from __future__ import annotations

import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path


SKILL_DIR = Path(__file__).resolve().parents[1]
SCRIPT = SKILL_DIR / "scripts" / "resolve-base-image.sh"
BASH = shutil.which("bash") or "/bin/bash"
TEMPLATE = "dock.artifactory.internal/docker-virtual/{image}:{tag}"
REF = "dock.artifactory.internal/docker-virtual/alpine:3.20"


class ResolveBaseImageTest(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory(prefix="resolve-base-image-")
        self.addCleanup(self.tmp.cleanup)
        self.bin_dir = Path(self.tmp.name) / "bin"
        self.bin_dir.mkdir()
        self.log = Path(self.tmp.name) / "runtime.log"

    def write_runtime(self, name: str = "fake-runtime") -> str:
        """Create a PATH-resolved runtime with outcomes controlled by env."""
        path = self.bin_dir / name
        path.write_text(
            "#!/bin/sh\n"
            "printf '%s\\n' \"$*\" >>\"$FAKE_RUNTIME_LOG\"\n"
            "if [ \"$1\" = manifest ] && [ \"${2:-}\" = inspect ]; then\n"
            "  [ -z \"${FAKE_MANIFEST_ERROR:-}\" ] || "
            "printf '%s\\n' \"$FAKE_MANIFEST_ERROR\" >&2\n"
            "  exit \"${FAKE_MANIFEST_STATUS:-0}\"\n"
            "fi\n"
            "if [ \"$1\" = pull ]; then\n"
            "  [ -z \"${FAKE_PULL_ERROR:-}\" ] || "
            "printf '%s\\n' \"$FAKE_PULL_ERROR\" >&2\n"
            "  exit \"${FAKE_PULL_STATUS:-0}\"\n"
            "fi\n"
            "exit 97\n",
            encoding="utf-8",
        )
        path.chmod(0o755)
        return name

    def run_resolver(
        self,
        *,
        image: str = "alpine",
        tag: str = "3.20",
        template: str = TEMPLATE,
        runtime: str | None = "fake-runtime",
        manifest_status: int = 0,
        manifest_error: str = "",
        pull_status: int = 0,
        pull_error: str = "",
        path: str | None = None,
    ) -> subprocess.CompletedProcess[str]:
        env = os.environ.copy()
        env.pop("RUNTIME", None)
        env.pop("CONTAINER_RUNTIME", None)
        env.update(
            {
                "PATH": path
                if path is not None
                else f"{self.bin_dir}{os.pathsep}{env.get('PATH', '')}",
                "FAKE_RUNTIME_LOG": str(self.log),
                "FAKE_MANIFEST_STATUS": str(manifest_status),
                "FAKE_MANIFEST_ERROR": manifest_error,
                "FAKE_PULL_STATUS": str(pull_status),
                "FAKE_PULL_ERROR": pull_error,
            }
        )
        argv = [BASH, str(SCRIPT), image, tag, template]
        if runtime is not None:
            argv.append(runtime)
        return subprocess.run(
            argv,
            env=env,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )

    def assert_verdict(
        self, result: subprocess.CompletedProcess[str], expected: str
    ) -> None:
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout, f"{expected}\n")

    def runtime_calls(self) -> list[str]:
        if not self.log.exists():
            return []
        return self.log.read_text(encoding="utf-8").splitlines()

    def test_empty_inputs_are_unknown_without_probing(self) -> None:
        self.write_runtime()
        for field in ("image", "tag", "template"):
            with self.subTest(field=field):
                kwargs = {field: ""}
                result = self.run_resolver(**kwargs)
                self.assert_verdict(result, "unknown")
        self.assertEqual(self.runtime_calls(), [])

    def test_missing_runtime_is_unknown(self) -> None:
        result = self.run_resolver(runtime="not-installed-runtime", path=str(self.bin_dir))
        self.assert_verdict(result, "unknown")
        self.assertEqual(self.runtime_calls(), [])

    def test_optional_runtime_with_no_docker_or_podman_is_unknown(self) -> None:
        result = self.run_resolver(runtime=None, path=str(self.bin_dir))
        self.assert_verdict(result, "unknown")
        self.assertEqual(self.runtime_calls(), [])

    def test_manifest_success_is_available_and_expands_template(self) -> None:
        self.write_runtime()
        result = self.run_resolver()
        self.assert_verdict(result, "available")
        self.assertEqual(self.runtime_calls(), [f"manifest inspect {REF}"])

    def test_optional_runtime_auto_detects_docker(self) -> None:
        self.write_runtime("docker")
        result = self.run_resolver(runtime=None)
        self.assert_verdict(result, "available")
        self.assertEqual(self.runtime_calls(), [f"manifest inspect {REF}"])

    def test_missing_manifest_errors_are_absent_without_pull(self) -> None:
        self.write_runtime()
        errors = (
            "manifest unknown",
            "repository.example/alpine:3.20 not found",
            "manifest unknown: manifest tagged by 3.20 is not found",
        )
        for error in errors:
            with self.subTest(error=error):
                self.log.unlink(missing_ok=True)
                result = self.run_resolver(manifest_status=1, manifest_error=error)
                self.assert_verdict(result, "absent")
                self.assertEqual(self.runtime_calls(), [f"manifest inspect {REF}"])

    def test_auth_errors_are_unknown_even_when_they_say_not_found(self) -> None:
        self.write_runtime()
        errors = (
            "unauthorized: authentication required",
            "denied: requested access to the resource is denied",
            "pull access denied",
            "no basic auth credentials",
            "authentication required: manifest not found",
        )
        for error in errors:
            with self.subTest(error=error):
                self.log.unlink(missing_ok=True)
                result = self.run_resolver(manifest_status=1, manifest_error=error)
                self.assert_verdict(result, "unknown")
                self.assertEqual(self.runtime_calls(), [f"manifest inspect {REF}"])

    def test_network_and_unrecognised_errors_are_unknown_without_pull(self) -> None:
        self.write_runtime()
        errors = (
            "dial tcp: lookup registry: no such host",
            "connection refused",
            "request timed out",
            "the registry emitted something surprising",
        )
        for error in errors:
            with self.subTest(error=error):
                self.log.unlink(missing_ok=True)
                result = self.run_resolver(manifest_status=1, manifest_error=error)
                self.assert_verdict(result, "unknown")
                self.assertEqual(self.runtime_calls(), [f"manifest inspect {REF}"])

    def test_unsupported_manifest_inspect_falls_back_to_quiet_pull(self) -> None:
        self.write_runtime()
        result = self.run_resolver(
            manifest_status=1,
            manifest_error="docker manifest inspect is only supported on a Docker CLI "
            "with experimental CLI features enabled",
        )
        self.assert_verdict(result, "available")
        self.assertEqual(
            self.runtime_calls(),
            [f"manifest inspect {REF}", f"pull -q {REF}"],
        )

    def test_pull_fallback_preserves_absent_auth_and_unknown_split(self) -> None:
        self.write_runtime()
        cases = (
            ("manifest unknown", "absent"),
            ("unauthorized: authentication required", "unknown"),
            ("dial tcp: connection refused", "unknown"),
        )
        for pull_error, expected in cases:
            with self.subTest(pull_error=pull_error):
                self.log.unlink(missing_ok=True)
                result = self.run_resolver(
                    manifest_status=1,
                    manifest_error="unknown command 'manifest'",
                    pull_status=1,
                    pull_error=pull_error,
                )
                self.assert_verdict(result, expected)
                self.assertEqual(
                    self.runtime_calls(),
                    [f"manifest inspect {REF}", f"pull -q {REF}"],
                )


if __name__ == "__main__":
    unittest.main()
