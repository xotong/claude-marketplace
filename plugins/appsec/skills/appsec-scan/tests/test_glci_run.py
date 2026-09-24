#!/usr/bin/env python3
"""Hermetic tests for scripts/glci-run.sh.

glci-run.sh runs one security category's REAL CI/CD catalog component job
locally with GitLab's `glci` tool and leaves the report(s) at the same
canonical paths the docker engine (run-scan.sh) produces. These tests stub
both `glci` and `docker` on a temp PATH so nothing here touches a real
container runtime or a real GitLab instance — see the module docstring on
STUB_GLCI / STUB_DOCKER for exactly what each stub emits.

Real (non-hermetic) verification against the actual glci binary, Docker, and
a live GitLab instance was done separately and is not part of this suite.
"""

from __future__ import annotations

import json
import os
import re
import stat
import subprocess
import tempfile
import unittest
from pathlib import Path

SKILL_DIR = Path(__file__).resolve().parents[1]
SCRIPT = SKILL_DIR / "scripts" / "glci-run.sh"
BASH = "bash"

# -----------------------------------------------------------------------------
# Stub `glci`: dispatches on the first non-"-f <file>" argument, matching the
# handful of subcommands glci-run.sh actually calls (doctor, daemon, version,
# run, log, artifacts). Every invocation's argv is appended to STUB_LOG (JSON
# list per line) so tests can assert on exact flags without parsing prose.
# Behaviour for `doctor`/`run`/`log`/`artifacts` is controlled by env vars so
# each test can pick a scenario without a different stub file.
# -----------------------------------------------------------------------------
STUB_GLCI = r'''#!/usr/bin/env python3
import json, os, sys, zipfile

def log(argv):
    p = os.environ.get("STUB_LOG")
    if p:
        with open(p, "a", encoding="utf-8") as f:
            f.write(json.dumps(argv) + "\n")

def find_subcommand(argv):
    i = 0
    while i < len(argv):
        if argv[i] == "-f":
            i += 2
            continue
        return argv[i], i
    return None, -1

def main():
    argv = sys.argv[1:]
    log(argv)
    cmd, idx = find_subcommand(argv)
    rest = argv[idx + 1:] if idx >= 0 else []

    if cmd == "doctor":
        mode = os.environ.get("GLCI_STUB_DOCTOR", "healthy")
        docker_status = "fail" if mode == "unhealthy" else "pass"
        daemon_status = "warn" if mode == "cold_daemon" else "pass"
        checks = [
            {"name": "Docker", "status": docker_status, "detail": "stub docker check"},
            {"name": "glci images", "status": "pass", "detail": "stub"},
            {"name": "Daemon", "status": daemon_status,
             "detail": "not running (starts automatically on first use)" if daemon_status == "warn" else "stub"},
            {"name": "CI config", "status": "fail", "detail": "ignored by caller"},
            {"name": "Git repository", "status": "pass", "detail": "stub"},
        ]
        ok = all(c["status"] != "fail" for c in checks if c["name"] not in ("CI config", "Git repository"))
        print(json.dumps({"ok": ok, "checks": checks}))
        sys.exit(0 if ok else 1)

    if cmd == "daemon":
        sys.exit(0)

    if cmd == "version":
        sys.stderr.write("glci  commit deadbeefcafe1234567890\n")
        sys.stderr.write("daemon commit deadbeefcafe1234567890 (pid 1, up 1s)\n")
        sys.exit(0)

    if cmd == "run":
        job = os.environ.get("GLCI_STUB_JOB", "test_job")
        status = os.environ.get("GLCI_STUB_JOB_STATUS", "passed")
        events = [
            {"schema": 1, "type": "pipeline_start", "pipeline_id": 1, "stages": ["test"],
             "jobs": [{"name": job, "stage": "test"}]},
            {"schema": 1, "type": "job_status", "pipeline_id": 1, "job_name": job, "status": "running"},
            {"schema": 1, "type": "job_status", "pipeline_id": 1, "job_name": job, "status": status,
             "allow_failure": True},
            {"schema": 1, "type": "pipeline_done", "pipeline_id": 1,
             "outcome": "passed", "results": [{"name": job, "status": status}]},
        ]
        for e in events:
            print(json.dumps(e))
        sys.exit(0)

    if cmd == "log":
        text = os.environ.get(
            "GLCI_STUB_LOG_TEXT",
            "[INFO] running\nUploading artifacts...\nWARNING: no matching files\nERROR: No files to upload\n",
        )
        sys.stdout.write(text)
        sys.exit(0)

    if cmd == "artifacts":
        out_path = rest[rest.index("-o") + 1]
        files_spec = os.environ.get("GLCI_STUB_ARTIFACT_FILES", "")
        with zipfile.ZipFile(out_path, "w") as zf:
            for entry in [e for e in files_spec.split(",") if e]:
                zf.writestr(entry, "{}")
        sys.exit(0)

    sys.exit(0)

main()
'''

# -----------------------------------------------------------------------------
# Stub `docker`: only the subset glci-run.sh's container_scanning image push
# uses (port / tag / push / image inspect). Logged the same way as glci.
# -----------------------------------------------------------------------------
STUB_DOCKER = r'''#!/usr/bin/env python3
import json, os, sys

def log(argv):
    p = os.environ.get("STUB_LOG")
    if p:
        with open(p, "a", encoding="utf-8") as f:
            f.write(json.dumps(["docker"] + argv) + "\n")

def main():
    argv = sys.argv[1:]
    log(argv)
    if not argv:
        sys.exit(0)
    if argv[0] == "port":
        port = os.environ.get("DOCKER_STUB_PORT", "39999")
        print(f"{port}/tcp -> 0.0.0.0:{port}")
        sys.exit(0)
    if argv[0] == "image":
        print(os.environ.get("DOCKER_STUB_PLATFORM", "linux/amd64"))
        sys.exit(0)
    sys.exit(0)

main()
'''


def _write_stub(path: Path, source: str) -> None:
    path.write_text(source, encoding="utf-8")
    path.chmod(path.stat().st_mode | stat.S_IEXEC | stat.S_IXGRP | stat.S_IXOTH)


class GlciRunTest(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory(prefix="glci-run-test-")
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)

        self.stub_bin = self.root / "stub-bin"
        self.stub_bin.mkdir()
        _write_stub(self.stub_bin / "glci", STUB_GLCI)
        _write_stub(self.stub_bin / "docker", STUB_DOCKER)

        self.stub_log = self.root / "stub.log"

        self.project_dir = self.root / "project"
        self.project_dir.mkdir()
        subprocess.run(["git", "init", "-q"], cwd=self.project_dir, check=True)
        subprocess.run(["git", "config", "user.email", "t@example.com"], cwd=self.project_dir, check=True)
        subprocess.run(["git", "config", "user.name", "t"], cwd=self.project_dir, check=True)
        (self.project_dir / "README.md").write_text("hi\n", encoding="utf-8")
        subprocess.run(["git", "add", "-A"], cwd=self.project_dir, check=True)
        subprocess.run(["git", "commit", "-q", "-m", "init"], cwd=self.project_dir, check=True)

        self.results_dir = self.root / "results"
        self.results_dir.mkdir()

    def base_env(self, **overrides: str) -> dict[str, str]:
        env = dict(
            os.environ,
            PATH=f"{self.stub_bin}{os.pathsep}{os.environ['PATH']}",
            STUB_LOG=str(self.stub_log),
            APPSEC_GITLAB_URL="https://gitlab.example.com",
            APPSEC_RESOLVED_TOKEN="sekrit-token-value",
        )
        env.update(overrides)
        return env

    def run_script(self, *args: str, env: dict[str, str] | None = None) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [BASH, str(SCRIPT), *args],
            env=env if env is not None else self.base_env(),
            capture_output=True,
            text=True,
        )

    def default_args(self, category: str = "secret_detection", **extra: str) -> list[str]:
        args = [
            "--category", category,
            "--component", "gitlab.example.com/group/ci-catalogue/x/x@1.0.0",
            "--results", str(self.results_dir),
            "--project-dir", str(self.project_dir),
        ]
        for k, v in extra.items():
            args += [f"--{k.replace('_', '-')}", v]
        return args

    def stub_log_lines(self) -> list[list[str]]:
        if not self.stub_log.exists():
            return []
        return [json.loads(line) for line in self.stub_log.read_text(encoding="utf-8").splitlines() if line]

    # -- usage errors ----------------------------------------------------

    def test_no_args_is_usage_error(self) -> None:
        result = self.run_script()
        self.assertEqual(result.returncode, 2, result.stderr)
        self.assertIn("usage", result.stderr.lower())

    def test_unknown_category_is_usage_error(self) -> None:
        result = self.run_script(*self.default_args(category="bogus"))
        self.assertEqual(result.returncode, 2, result.stderr)
        self.assertIn("unknown category", result.stderr)

    def test_missing_component_is_usage_error(self) -> None:
        result = self.run_script(
            "--category", "secret_detection",
            "--results", str(self.results_dir),
            "--project-dir", str(self.project_dir),
        )
        self.assertEqual(result.returncode, 2, result.stderr)

    def test_relative_results_dir_is_usage_error(self) -> None:
        args = self.default_args()
        args[args.index(str(self.results_dir))] = "relative/results"
        result = self.run_script(*args)
        self.assertEqual(result.returncode, 2, result.stderr)
        self.assertIn("absolute", result.stderr)

    def test_bad_input_format_is_usage_error(self) -> None:
        result = self.run_script(*self.default_args(), "--input", "no-equals-sign")
        self.assertEqual(result.returncode, 2, result.stderr)

    # -- glci availability -------------------------------------------------

    def test_glci_missing_exits_three(self) -> None:
        env = self.base_env(GLCI_BIN="/nonexistent/path/to/glci")
        result = self.run_script(*self.default_args(), env=env)
        self.assertEqual(result.returncode, 3, result.stdout + result.stderr)
        self.assertIn("status=unavailable", result.stdout)
        self.assertIn("GLCI-REASON:", result.stdout)

    def test_doctor_unhealthy_exits_three(self) -> None:
        env = self.base_env(GLCI_STUB_DOCTOR="unhealthy")
        result = self.run_script(*self.default_args(), env=env)
        self.assertEqual(result.returncode, 3, result.stdout + result.stderr)
        self.assertIn("status=unavailable", result.stdout)
        reason_lines = [l for l in result.stdout.splitlines() if l.startswith("GLCI-REASON:")]
        self.assertEqual(len(reason_lines), 1, result.stdout)
        self.assertIn("Docker", reason_lines[0])

    def test_doctor_cold_daemon_warn_is_not_treated_as_unhealthy(self) -> None:
        # Real glci reports {"status":"warn", ...} for "Daemon: not running
        # (starts automatically on first use)" on a cold environment — a
        # "warn" that must NOT be treated the same as a "fail", or every
        # first-ever invocation would wrongly fall back to the docker engine.
        env = self.base_env(
            GLCI_STUB_DOCTOR="cold_daemon",
            GLCI_STUB_JOB="secret_detection",
            GLCI_STUB_ARTIFACT_FILES="gl-secret-detection-report.json",
        )
        result = self.run_script(*self.default_args(category="secret_detection"), env=env)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("status=ok", result.stdout)

    # -- happy path ----------------------------------------------------------

    def test_job_passed_report_copied_and_exits_zero(self) -> None:
        env = self.base_env(
            GLCI_STUB_JOB="secret_detection",
            GLCI_STUB_JOB_STATUS="passed",
            GLCI_STUB_ARTIFACT_FILES="gl-secret-detection-report.json",
        )
        result = self.run_script(*self.default_args(category="secret_detection"), env=env)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("GLCI-RESULT: category=secret_detection status=ok", result.stdout)
        self.assertIn("jobs=secret_detection:passed", result.stdout)
        self.assertIn("reports=gl-secret-detection-report.json", result.stdout)
        self.assertIn("glci_commit=deadbeefcafe1234567890", result.stdout)

        copied = self.results_dir / "gl-secret-detection-report.json"
        self.assertTrue(copied.exists())
        # Raw glci material stays under results/glci/, not scattered at top level.
        self.assertTrue((self.results_dir / "glci" / "secret_detection.gitlab-ci.yml").exists())
        self.assertTrue((self.results_dir / "glci" / "secret_detection.events.jsonl").exists())

    # -- failure classification -----------------------------------------------

    def test_allow_failure_job_failed_exits_four_with_reason(self) -> None:
        log_text = (
            "[INFO] [analyzer] starting\n"
            "[FATA] [analyzer] something exploded: root cause here\n"
            "Uploading artifacts...\n"
            "WARNING: gl-report.json: no matching files\n"
            "ERROR: No files to upload\n"
        )
        env = self.base_env(
            GLCI_STUB_JOB="dependency-scanning",
            GLCI_STUB_JOB_STATUS="failed",
            GLCI_STUB_LOG_TEXT=log_text,
        )
        result = self.run_script(*self.default_args(category="dependency_scanning"), env=env)
        self.assertEqual(result.returncode, 4, result.stdout + result.stderr)
        self.assertIn("status=job_failed", result.stdout)
        self.assertIn("jobs=dependency-scanning:failed", result.stdout)

        reason_lines = [l for l in result.stdout.splitlines() if l.startswith("GLCI-REASON:")]
        self.assertEqual(len(reason_lines), 1, result.stdout)
        # The real cause is surfaced, not the trailing artifact-upload noise.
        self.assertIn("something exploded", reason_lines[0])
        self.assertNotIn("No files to upload", reason_lines[0])

    def test_report_missing_exits_four(self) -> None:
        env = self.base_env(
            GLCI_STUB_JOB="secret_detection",
            GLCI_STUB_JOB_STATUS="passed",
            GLCI_STUB_ARTIFACT_FILES="",  # job "passed" but produced nothing matching
        )
        result = self.run_script(*self.default_args(category="secret_detection"), env=env)
        self.assertEqual(result.returncode, 4, result.stdout + result.stderr)
        self.assertIn("status=no_report", result.stdout)
        self.assertIn("GLCI-REASON:", result.stdout)
        self.assertFalse((self.results_dir / "gl-secret-detection-report.json").exists())

    # -- generated pipeline shape ---------------------------------------------

    def test_generated_pipeline_forces_stage_test_and_keeps_extra_inputs(self) -> None:
        env = self.base_env(
            GLCI_STUB_JOB="secret_detection",
            GLCI_STUB_ARTIFACT_FILES="gl-secret-detection-report.json",
        )
        # --input stage=bogus must lose to the forced stage: test.
        result = self.run_script(
            *self.default_args(category="secret_detection"),
            "--input", "stage=bogus",
            "--input", "historic_scan=true",
            env=env,
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

        pipeline = (self.results_dir / "glci" / "secret_detection.gitlab-ci.yml").read_text(encoding="utf-8")
        self.assertIn("stages: [test]", pipeline)
        self.assertIn('stage: "test"', pipeline)
        self.assertNotIn("bogus", pipeline)
        self.assertIn('historic_scan: "true"', pipeline)

    # -- security / argv shape ------------------------------------------------

    def test_run_invocation_flags_and_no_token_on_argv(self) -> None:
        env = self.base_env(
            GLCI_STUB_JOB="secret_detection",
            GLCI_STUB_ARTIFACT_FILES="gl-secret-detection-report.json",
        )
        result = self.run_script(*self.default_args(category="secret_detection"), env=env)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

        run_calls = [c for c in self.stub_log_lines() if "run" in c]
        self.assertTrue(run_calls, self.stub_log_lines())
        run_argv = run_calls[0]
        self.assertIn("--no-token", run_argv)
        joined = " ".join(run_argv)
        self.assertIn("--secrets none", joined)
        self.assertRegex(joined, r"--context branch=\S+")

        raw_log = self.stub_log.read_text(encoding="utf-8")
        self.assertNotIn("sekrit-token-value", raw_log)
        pipeline = (self.results_dir / "glci" / "secret_detection.gitlab-ci.yml").read_text(encoding="utf-8")
        self.assertNotIn("sekrit-token-value", pipeline)
        events = (self.results_dir / "glci" / "secret_detection.events.jsonl").read_text(encoding="utf-8")
        self.assertNotIn("sekrit-token-value", events)
        self.assertNotIn("--unmask", joined)

    # -- container_scanning image push ----------------------------------------

    def test_container_scanning_pushes_image_and_sets_component_inputs(self) -> None:
        env = self.base_env(
            GLCI_STUB_JOB="container_scanning",
            GLCI_STUB_ARTIFACT_FILES="gl-container-scanning-report.json,gl-sbom-report.cdx.json",
            DOCKER_STUB_PORT="39741",
            DOCKER_STUB_PLATFORM="linux/arm64",
        )
        result = self.run_script(
            *self.default_args(category="container_scanning"),
            "--image", "myapp:latest",
            "--dockerfile", "Dockerfile",
            env=env,
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

        calls = self.stub_log_lines()
        push_calls = [c for c in calls if c[:2] == ["docker", "push"]]
        self.assertEqual(len(push_calls), 1, calls)
        self.assertTrue(push_calls[0][2].startswith("127.0.0.1:39741/appsec/"), push_calls[0])

        run_calls = [c for c in calls if "run" in c and c[0] != "docker"]
        self.assertEqual(len(run_calls), 1, calls)
        joined = " ".join(run_calls[0])
        self.assertIn("CS_REGISTRY_INSECURE=true", joined)
        self.assertIn("TRIVY_PLATFORM=linux/arm64", joined)

        pipeline = (self.results_dir / "glci" / "container_scanning.gitlab-ci.yml").read_text(encoding="utf-8")
        self.assertIn("glci-mock:39741/appsec/", pipeline)
        self.assertIn('cs_dockerfile_path: "Dockerfile"', pipeline)

    def test_container_scanning_never_copies_its_sbom_to_top_level(self) -> None:
        # normalize.py rglobs the whole results dir and treats ANY
        # gl-sbom-*.cdx.json as dependency_scanning evidence. GTCS's own
        # image SBOM must therefore never land outside results/glci/, or a
        # container_scanning-only run would be misread as dependency
        # evidence that was never actually produced.
        env = self.base_env(
            GLCI_STUB_JOB="container_scanning",
            GLCI_STUB_ARTIFACT_FILES="gl-container-scanning-report.json,gl-sbom-report.cdx.json",
            DOCKER_STUB_PORT="39741",
        )
        result = self.run_script(
            *self.default_args(category="container_scanning"),
            "--image", "myapp:latest",
            env=env,
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

        self.assertTrue((self.results_dir / "gl-container-scanning-report.json").exists())
        top_level_sboms = list(self.results_dir.glob("gl-sbom-*.cdx.json"))
        self.assertEqual(top_level_sboms, [], top_level_sboms)
        # It still exists, just scoped under glci/ where normalize.py's
        # future skip list keeps it out of the findings walk.
        nested_sboms = list((self.results_dir / "glci").rglob("gl-sbom-*.cdx.json"))
        self.assertEqual(len(nested_sboms), 1, nested_sboms)

    # -- dependency_scanning SBOM copy ----------------------------------------

    def test_dependency_scanning_copies_sbom_and_report(self) -> None:
        env = self.base_env(
            GLCI_STUB_JOB="dependency-scanning",
            GLCI_STUB_ARTIFACT_FILES="gl-sbom-npm.cdx.json,gl-dependency-scanning-report.json",
        )
        result = self.run_script(
            *self.default_args(category="dependency_scanning", input="language=javascript"),
            env=env,
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertTrue((self.results_dir / "gl-sbom-npm.cdx.json").exists())
        self.assertTrue((self.results_dir / "gl-dependency-scanning-report.json").exists())
        self.assertIn("reports=", result.stdout)
        reports = re.search(r"reports=(\S*)", result.stdout).group(1)
        self.assertIn("gl-sbom-npm.cdx.json", reports)
        self.assertIn("gl-dependency-scanning-report.json", reports)


if __name__ == "__main__":
    unittest.main()
