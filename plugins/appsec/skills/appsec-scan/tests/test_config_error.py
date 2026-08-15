#!/usr/bin/env python3
"""A misconfiguration must stop the work it blocks, not get routed around.

Tested in an airgapped estate, a JFrog repo that was not anonymous made the skill
hunt for alternative methods instead of stopping. Two distinct defects sat behind
that, and both are guarded here:

  1. Nothing distinguished "the registry refused us" from "we could not reach
     it". Every consumer collapsed a 401 into the same shrug a timeout produces,
     so the misconfiguration was invisible and the run still read like a result.
  2. Nothing said a configuration error is terminal. Retrying, or reaching for
     another image/registry/credential/endpoint, cannot authenticate a credential
     the admin has not set -- it only buries the cause.

The split these tests defend: HTTP 401/403 and registry auth phrases are CONFIG
(terminal, reported, never worked around); timeouts, connection failures, DNS and
5xx are ENVIRONMENT (may fall back -- the airgap guarantee is built on it).

The coverage invariant must survive all of it: a category blocked by config is
still `missing_report` with `coverage_complete: false`, never a quiet pass.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

SKILL_DIR = Path(__file__).resolve().parents[1]
SCRIPTS = SKILL_DIR / "scripts"
SCANNERS = SKILL_DIR / "scanners"
RESOLVE_PACKAGE = SCRIPTS / "resolve-package.sh"
CHECK_REMEDIATION = SCRIPTS / "check-remediation.py"
CLASSIFY_ERROR = SCRIPTS / "classify-error.sh"
PREFLIGHT = SCANNERS / "preflight.sh"
RUN_SCAN = SCRIPTS / "run-scan.sh"
BASH = shutil.which("bash") or "/bin/bash"

# A curl that honours -o and reports whatever status the test asked for. The real
# probe reads the code from -w, so a stub that only writes a body proves nothing.
FAKE_CURL = """#!/bin/sh
out=
prev=
for arg do
  if [ "$prev" = "-o" ]; then out=$arg; fi
  prev=$arg
done
if [ -n "$out" ]; then : > "$out"; fi
printf '%s' '{status}'
"""


def stub(directory: Path, name: str, body: str) -> Path:
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / name
    path.write_text(body if body.startswith("#!") else "#!/bin/sh\n" + body, encoding="utf-8")
    path.chmod(0o755)
    return path


class AuthErrorClassifierTest(unittest.TestCase):
    """classify-error.sh is the single definition of 'this is config, not luck'."""

    def _is_auth(self, text: str) -> bool:
        proc = subprocess.run(
            [BASH, "-c", f'. "{CLASSIFY_ERROR}"; if is_auth_error "$1"; then echo yes; else echo no; fi', "_", text],
            capture_output=True,
            text=True,
        )
        self.assertEqual(proc.returncode, 0, proc.stderr)
        return proc.stdout.strip() == "yes"

    def test_registry_refusals_are_config(self) -> None:
        for text in (
            "Error response from daemon: pull access denied for x/y",
            "unauthorized: authentication required",
            "denied: requested access to the resource is denied",
            "no basic auth credentials",
            "UNAUTHORIZED",  # registries differ on capitalisation
            "The server returned 401 Unauthorized",
        ):
            with self.subTest(text=text):
                self.assertTrue(self._is_auth(text), text)

    def test_unreachable_is_not_config(self) -> None:
        """The airgap guarantee depends on these still being allowed to fall back."""
        for text in (
            "dial tcp 10.0.0.1:443: connect: connection refused",
            "Client.Timeout exceeded while awaiting headers",
            "no such host",
            "manifest unknown",
            "500 Internal Server Error",
            "",
        ):
            with self.subTest(text=text):
                self.assertFalse(self._is_auth(text), text)

    def test_sourcing_does_not_change_the_callers_case_matching(self) -> None:
        """Set globally, nocasematch would silently alter every caller's `case`."""
        proc = subprocess.run(
            [
                BASH,
                "-c",
                f'. "{CLASSIFY_ERROR}"; is_auth_error "UNAUTHORIZED" || true; '
                'case "REGISTRY" in registry) echo leaked ;; *) echo intact ;; esac',
            ],
            capture_output=True,
            text=True,
        )
        self.assertEqual(proc.stdout.strip(), "intact", proc.stdout + proc.stderr)


class ResolvePackageUnauthorizedTest(unittest.TestCase):
    """401/403 gets its own word; everything unreachable stays `unknown`."""

    def _verdict(self, status: str) -> str:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            stub(root / "bin", "curl", FAKE_CURL.format(status=status))
            env = dict(os.environ, PATH=f"{root / 'bin'}{os.pathsep}{os.environ['PATH']}")
            proc = subprocess.run(
                [
                    BASH,
                    str(RESOLVE_PACKAGE),
                    "npm",
                    "lodash",
                    "4.17.21",
                    "https://registry.example/{package}/{version}",
                ],
                capture_output=True,
                text=True,
                env=env,
            )
        self.assertEqual(proc.returncode, 0, proc.stderr)
        return proc.stdout.strip()

    def test_refusal_is_unauthorized(self) -> None:
        self.assertEqual(self._verdict("401"), "unauthorized")
        self.assertEqual(self._verdict("403"), "unauthorized")

    def test_server_error_and_no_answer_stay_unknown(self) -> None:
        # The whole point of the split: these may fix themselves, a credential
        # never will. Collapsing them together is the bug being fixed.
        self.assertEqual(self._verdict("500"), "unknown")
        self.assertEqual(self._verdict("000"), "unknown")

    def test_settled_answers_are_unchanged(self) -> None:
        self.assertEqual(self._verdict("200"), "available")
        self.assertEqual(self._verdict("404"), "absent")


class CheckRemediationRefusalTest(unittest.TestCase):
    """A refused mirror reports itself — but must not move a single status."""

    def _run(self, status: str):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            results = root / ".appsec-results"
            results.mkdir()
            findings = [
                {
                    "category": "dependency_scanning",
                    "severity": "HIGH",
                    "location": {"package": name},
                    "evidence": {
                        "package": name,
                        "fixed_version": "9.9.9",
                        "manifest": "package-lock.json",
                    },
                    "rule_id": "CVE-0000-0000",
                }
                for name in ("lodash", "minimist", "axios")
            ]
            (results / "findings.triaged.json").write_text(json.dumps(findings), encoding="utf-8")
            stub(root / "bin", "curl", FAKE_CURL.format(status=status))
            env = dict(os.environ, PATH=f"{root / 'bin'}{os.pathsep}{os.environ['PATH']}")
            proc = subprocess.run(
                [
                    "python3",
                    str(CHECK_REMEDIATION),
                    str(results),
                    "--registries",
                    '{"npm":"https://registry.example/{package}/{version}"}',
                ],
                capture_output=True,
                text=True,
                env=env,
            )
            availability = json.loads(
                (results / "registry-availability.json").read_text(encoding="utf-8")
            )
        return proc, availability

    def test_refusal_never_becomes_absent_or_moves_a_status(self) -> None:
        """`absent` invents mirroring work; being refused is not evidence of it."""
        refused, refused_map = self._run("401")
        unreachable, unreachable_map = self._run("000")

        self.assertEqual(refused.returncode, 0, refused.stderr)
        self.assertNotIn("unauthorized", json.dumps(refused_map))
        self.assertNotIn("absent", json.dumps(refused_map))
        # Byte-identical to the unreachable case: normalize.py can never tell.
        self.assertEqual(refused_map, unreachable_map)

    def test_reports_once_per_ecosystem_not_once_per_package(self) -> None:
        refused, _ = self._run("401")
        lines = [
            line for line in refused.stderr.splitlines() if line.startswith("CONFIG-ERROR:")
        ]
        self.assertEqual(len(lines), 1, refused.stderr)
        self.assertIn("npm", lines[0])
        self.assertIn("auth_token_env", lines[0])

    def test_unreachable_registry_reports_no_config_error(self) -> None:
        unreachable, _ = self._run("000")
        self.assertNotIn("CONFIG-ERROR:", unreachable.stderr)


class PreflightProbeTest(unittest.TestCase):
    """Catch it in seconds, before any scanner container starts."""

    def _preflight(self, root: Path, curl_status: str | None, **env_extra):
        bin_dir = root / "bin"
        # preflight only accepts auto|docker|podman, and probes the daemon.
        stub(bin_dir, "docker", "exit 0\n")
        if curl_status is not None:
            stub(bin_dir, "curl", FAKE_CURL.format(status=curl_status))
        env = dict(
            os.environ,
            PATH=f"{bin_dir}{os.pathsep}{os.environ['PATH']}",
            CATALOG_AUTH_ENV="",
            APPSEC_AIRGAP="false",
            APPSEC_PROFILE="catalog",
            CONTAINER_RUNTIME="docker",
            # Set so preflight does not self-load the shipped config.
            PACKAGE_REGISTRIES="{}",
            PACKAGE_REGISTRY_AUTH_ENV="",
            CA_BUNDLE="",
            MAVEN_SETTINGS="",
        )
        env.update(env_extra)
        return subprocess.run(
            [BASH, str(PREFLIGHT)], capture_output=True, text=True, env=env
        )

    def test_refused_registry_fails_preflight_and_names_the_setting(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            proc = self._preflight(
                Path(tmp),
                "401",
                PACKAGE_REGISTRIES='{"npm":"","pypi":"https://jfrog.example/simple/{package}/","maven":"","go":""}',
            )
        self.assertEqual(proc.returncode, 1, proc.stdout + proc.stderr)
        output = proc.stdout + proc.stderr
        self.assertIn("pypi", output)
        self.assertIn("auth_token_env", output)

    def test_reachable_registry_passes(self) -> None:
        """404 for a package nobody published is the healthy answer, not an error."""
        with tempfile.TemporaryDirectory() as tmp:
            proc = self._preflight(
                Path(tmp),
                "404",
                PACKAGE_REGISTRIES='{"npm":"","pypi":"https://jfrog.example/simple/{package}/","maven":"","go":""}',
            )
        self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)

    def test_nothing_configured_probes_nothing(self) -> None:
        """No configured registries must mean no new network calls, and no new
        way for a previously-fine environment to start failing."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            marker = root / "curl-was-called"
            stub(root / "bin", "curl", f"touch '{marker}'\nprintf '000'\n")
            proc = self._preflight(root, None)
            self.assertFalse(marker.exists(), "probed with nothing configured")
        self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)

    def test_unreadable_ca_bundle_fails_before_scanning(self) -> None:
        """It otherwise fails every request from inside the container in a way
        that reads like a network outage rather than a trust problem."""
        with tempfile.TemporaryDirectory() as tmp:
            proc = self._preflight(Path(tmp), None, CA_BUNDLE="/nonexistent/internal-ca.pem")
        self.assertEqual(proc.returncode, 1, proc.stdout + proc.stderr)
        self.assertIn("ca_bundle", proc.stdout + proc.stderr)


class RunScanConfigErrorTest(unittest.TestCase):
    """The reported bug, end to end: stop the category, fail the run, say why."""

    AUTH_RUNTIME = (
        "#!/bin/sh\n"
        "case \"$1\" in\n"
        "  pull) echo 'Error response from daemon: pull access denied for x, "
        "repository does not exist or may require authorization' >&2; exit 1 ;;\n"
        "esac\n"
        "exit 0\n"
    )
    UNREACHABLE_RUNTIME = (
        "#!/bin/sh\n"
        "case \"$1\" in\n"
        "  pull) echo 'dial tcp 10.0.0.1:443: connect: connection refused' >&2; exit 1 ;;\n"
        "esac\n"
        "exit 0\n"
    )

    def _scan(self, root: Path, runtime_body: str, *args: str, **env_extra):
        repo = root / "repo"
        repo.mkdir()
        subprocess.run(["git", "init", "-q"], cwd=repo, check=True)
        runtime = stub(root / "bin", "fake-runtime", runtime_body)
        env = dict(
            os.environ,
            RUNTIME=str(runtime),
            SKILL_DIR=str(SKILL_DIR),
            SCANNERS_DIR=str(SCANNERS),
            SCRIPTS_DIR=str(SCRIPTS),
            APPSEC_PROFILE="catalog",
            RUN_FORTIFY_SAST="false",
            RUN_GITLAB_DS="false",
            RUN_SECRET_DETECTION="true",
            RUN_GITLAB_CS="false",
            FORTIFY_SAST_IMAGE="example/fortify:test",
            GITLAB_DS_IMAGE="example/ds:test",
            SECRET_DETECTION_IMAGE="example/secrets:test",
            GITLAB_CS_IMAGE="example/cs:test",
            CS_USER_ENV="TEST_CS_USER",
            CS_PASS_ENV="TEST_CS_PASS",
            PYTHON_INSTALL_URL="",
            JQ_INSTALL_URL="",
            CI_GATE_FAIL_ON="high",
        )
        env.update(env_extra)
        proc = subprocess.run(
            [BASH, str(RUN_SCAN), *args], cwd=repo, env=env, capture_output=True, text=True
        )
        coverage_path = repo / ".appsec-results" / "scan-coverage.json"
        coverage = (
            json.loads(coverage_path.read_text(encoding="utf-8"))
            if coverage_path.exists()
            else None
        )
        triaged_path = repo / ".appsec-results" / "findings.triaged.json"
        triaged = (
            json.loads(triaged_path.read_text(encoding="utf-8"))
            if triaged_path.exists()
            else []
        )
        return proc, coverage, triaged

    def test_refused_pull_is_a_config_error_and_fails_the_run(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            proc, coverage, triaged = self._scan(
                Path(tmp), self.AUTH_RUNTIME, "--only", "secret_detection"
            )
        output = proc.stdout + proc.stderr
        self.assertIn("CONFIG-ERROR:", output)
        self.assertIn("CONFIGURATION ERRORS", output)
        self.assertIn("No workaround was attempted", output)
        self.assertEqual(proc.returncode, 2, output)

        # The coverage invariant is untouched by the new path.
        self.assertIsNotNone(coverage, output)
        self.assertFalse(coverage["coverage_complete"], coverage)
        self.assertIn("secret_detection", coverage["missing_report"], coverage)
        reasons = [
            f.get("evidence", {}).get("why", "")
            for f in triaged
            if str(f.get("rule_id", "")).startswith("APPSEC-REPORT-")
        ]
        self.assertTrue(reasons, triaged)
        self.assertTrue(
            any("CONFIG-ERROR" in why for why in reasons),
            "the cause did not reach the finding: " + repr(reasons),
        )

    def test_unreachable_registry_keeps_the_old_graceful_skip(self) -> None:
        """Environment failures must NOT become terminal — the airgap path."""
        with tempfile.TemporaryDirectory() as tmp:
            proc, coverage, _ = self._scan(
                Path(tmp), self.UNREACHABLE_RUNTIME, "--only", "secret_detection"
            )
        output = proc.stdout + proc.stderr
        self.assertNotIn("CONFIG-ERROR:", output)
        self.assertIn("Failed to pull", output)
        # Still not a pass: the coverage gap alone accounts for it.
        self.assertFalse(coverage["coverage_complete"], coverage)

    def test_config_error_exits_two_even_when_the_gate_never_fails(self) -> None:
        """`fail_on: none` always exits 0 on findings. Without this override the
        whole 'stop and report' contract would be one warning in the scrollback."""
        with tempfile.TemporaryDirectory() as tmp:
            proc, _, _ = self._scan(
                Path(tmp),
                self.AUTH_RUNTIME,
                "--only",
                "secret_detection",
                CI_GATE_FAIL_ON="none",
            )
        self.assertEqual(proc.returncode, 2, proc.stdout + proc.stderr)

    def test_base_image_pull_failure_keeps_container_targets_own_remedy(self) -> None:
        """container-target.sh already diagnosed this and printed the fix; the
        orchestrator used to discard it and tell the user to raise a ticket."""
        build_fails_auth = (
            "#!/bin/sh\n"
            "case \"$1\" in\n"
            "  build) echo 'unauthorized: authentication required' >&2; exit 1 ;;\n"
            "esac\n"
            "exit 0\n"
        )
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            repo = root / "repo"
            repo.mkdir()
            (repo / "Dockerfile").write_text("FROM jfrog.example/base:1\n", encoding="utf-8")
            subprocess.run(["git", "init", "-q"], cwd=repo, check=True)
            runtime = stub(root / "bin", "fake-runtime", build_fails_auth)
            env = dict(
                os.environ,
                RUNTIME=str(runtime),
                SKILL_DIR=str(SKILL_DIR),
                SCANNERS_DIR=str(SCANNERS),
                SCRIPTS_DIR=str(SCRIPTS),
                APPSEC_PROFILE="catalog",
                RUN_FORTIFY_SAST="false",
                RUN_GITLAB_DS="false",
                RUN_SECRET_DETECTION="false",
                RUN_GITLAB_CS="true",
                FORTIFY_SAST_IMAGE="example/fortify:test",
                GITLAB_DS_IMAGE="example/ds:test",
                SECRET_DETECTION_IMAGE="example/secrets:test",
                GITLAB_CS_IMAGE="example/cs:test",
                CS_USER_ENV="TEST_CS_USER",
                CS_PASS_ENV="TEST_CS_PASS",
                PYTHON_INSTALL_URL="",
                JQ_INSTALL_URL="",
                CI_GATE_FAIL_ON="high",
            )
            env.pop("CS_IMAGE", None)
            proc = subprocess.run(
                [BASH, str(RUN_SCAN), "--only", "container_scanning"],
                cwd=repo,
                env=env,
                capture_output=True,
                text=True,
            )
        output = proc.stdout + proc.stderr
        self.assertIn("CONFIG-ERROR:", output)
        self.assertIn("base image", output)
        self.assertNotIn("Submit a Jira ticket", output)
        self.assertEqual(proc.returncode, 2, output)


if __name__ == "__main__":
    unittest.main()
