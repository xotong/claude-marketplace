#!/usr/bin/env python3
"""Hermetic tests for run-scan.sh's engine: glci / remote-match wiring.

glci-run.sh and remote-match.sh are already tested standalone (test_glci_run.py,
test_remote_match.py). These tests are about the ORCHESTRATOR: does run-scan.sh
call them with the right arguments, handle their exit codes the way the task
brief pins (0/3/4), and never leak the resolved token. Both scripts are
replaced with small stubs so no docker/network is needed — SCRIPTS_DIR points
at a directory that symlinks every real script except the ones under test
(catalog.sh still needs the real vendored reference/catalog/ snapshots to
resolve a component tag offline, so a sibling `reference` symlink is set up
alongside it).
"""

from __future__ import annotations

import json
import os
import subprocess
import tempfile
import unittest
from pathlib import Path

from test_run_scan import RunScanDryRunTest, SKILL_DIR, SCRIPTS_DIR, RUN_SCAN, BASH


CATALOG_ENGINE_BLOCK = (
    "  catalog:\n"
    "    gitlab_instance: https://gitlab.com\n"
)


class GlciEngineIntegrationTest(RunScanDryRunTest):
    def stub_scripts_dir(self, root: Path, **stub_bodies: str) -> Path:
        """A SCRIPTS_DIR mirror: every real script symlinked in, except the
        names in stub_bodies, which become executable stub scripts instead.
        A sibling `reference` symlink keeps catalog.sh's offline snapshot
        fallback (reference/catalog/...) working unmodified.
        """
        mirror = root / "scripts-stub"
        mirror.mkdir()
        for entry in SCRIPTS_DIR.iterdir():
            if entry.name in stub_bodies:
                continue
            (mirror / entry.name).symlink_to(entry)
        for name, body in stub_bodies.items():
            script = mirror / name
            script.write_text(body, encoding="utf-8")
            script.chmod(0o755)
        (root / "reference").symlink_to(SKILL_DIR / "reference")
        return mirror

    def glci_engine_skill(self, root: Path, *, remote_match_project: str = "") -> Path:
        """catalog profile with engine: glci (+ optional remote_match_project)."""
        extra = "    engine: glci\n"
        if remote_match_project:
            extra += f"    remote_match_project: {remote_match_project}\n"
        return self.make_skill_with_config(
            root,
            (CATALOG_ENGINE_BLOCK, CATALOG_ENGINE_BLOCK + extra),
        )

    def sd_only_env(self, root: Path, scripts_dir: Path, **overrides: str) -> dict[str, str]:
        env = self.self_loading_env(
            SCRIPTS_DIR=str(scripts_dir),
            SKILL_DIR=str(self.glci_engine_skill(root)),
            **overrides,
        )
        return env

    def run_scan_real(self, repo: Path, *args: str, env: dict[str, str]) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [BASH, str(RUN_SCAN), *args],
            cwd=repo,
            env=env,
            capture_output=True,
            text=True,
        )

    # -------------------------------------------------------------------
    # Secret detection, engine: glci
    # -------------------------------------------------------------------

    def test_sd_glci_success_calls_glci_run_with_component_ref_and_hides_token(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "repo").mkdir()
            repo = self.make_repo(str(root / "repo"), pom=False)
            argv_log = root / "argv.log"
            env_log = root / "env.log"
            stub = (
                "#!/bin/sh\n"
                f"printf '%s\\n' \"$@\" > {argv_log}\n"
                f'printf \'GITLAB_TOKEN=%s APPSEC_RESOLVED_TOKEN=%s\\n\' "$GITLAB_TOKEN" "$APPSEC_RESOLVED_TOKEN" > {env_log}\n'
                "results=\"\"\n"
                "prev=\"\"\n"
                "for a in \"$@\"; do\n"
                "  if [ \"$prev\" = --results ]; then results=\"$a\"; fi\n"
                "  prev=\"$a\"\n"
                "done\n"
                "mkdir -p \"$results\"\n"
                "printf '{\"version\":\"15.0.0\",\"vulnerabilities\":[]}' > \"$results/gl-secret-detection-report.json\"\n"
                "printf 'GLCI-RESULT: category=secret_detection status=ok jobs=secret-detection:passed reports=gl-secret-detection-report.json glci_commit=deadbeef\\n'\n"
                "exit 0\n"
            )
            scripts = self.stub_scripts_dir(root, **{"glci-run.sh": stub})
            fake_docker = root / "fake-docker"
            fake_docker.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
            fake_docker.chmod(0o755)
            env = self.sd_only_env(
                root,
                scripts,
                RUNTIME=str(fake_docker),
                GITLAB_READ_TOKEN="s3cr3t-token-value",
            )
            result = self.run_scan_real(repo, "--only", "secret_detection", env=env)
            argv_text = argv_log.read_text(encoding="utf-8")
            env_text = env_log.read_text(encoding="utf-8")
            coverage = json.loads(
                (repo / ".appsec-results" / "scan-coverage.json").read_text(encoding="utf-8")
            )

        output = result.stdout + result.stderr
        self.assertIn("--category", argv_text, output)
        self.assertIn("secret_detection", argv_text, output)
        self.assertIn(
            "--component gitlab.com/lobster-thermidor/devops/ci-catalogue/secret-detection/secret-detection@1.0.0",
            " ".join(argv_text.split()),
            output,
        )
        # The token reaches glci-run.sh only through its OWN environment
        # (which it is entitled to — it re-exports it to the real glci
        # binary), never via argv, and never printed anywhere on stdout/stderr.
        self.assertNotIn("s3cr3t-token-value", argv_text)
        self.assertNotIn("s3cr3t-token-value", output)
        self.assertIn("APPSEC_RESOLVED_TOKEN=s3cr3t-token-value", env_text)
        self.assertEqual(coverage["engine"]["secret_detection"], "glci")
        self.assertEqual(coverage["glci_commit"]["secret_detection"], "deadbeef")
        self.assertNotIn("secret_detection", coverage["missing_report"])

    def test_sd_glci_unavailable_falls_back_to_docker_with_advisory(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "repo").mkdir()
            repo = self.make_repo(str(root / "repo"), pom=False)
            stub = (
                "#!/bin/sh\n"
                "printf 'GLCI-RESULT: category=secret_detection status=unavailable jobs= reports= glci_commit=\\n'\n"
                "printf 'GLCI-REASON: glci not found\\n'\n"
                "exit 3\n"
            )
            scripts = self.stub_scripts_dir(root, **{"glci-run.sh": stub})
            fake_docker = root / "fake-docker"
            fake_docker.write_text(
                "#!/bin/sh\n"
                "case \"$*\" in\n"
                "  *secret-detection.sh*)\n"
                "    printf '{\"version\":\"15.0.0\",\"vulnerabilities\":[]}' > .appsec-results/gl-secret-detection-report.json ;;\n"
                "esac\n"
                "exit 0\n",
                encoding="utf-8",
            )
            fake_docker.chmod(0o755)
            env = self.sd_only_env(
                root,
                scripts,
                RUNTIME=str(fake_docker),
            )
            result = self.run_scan_real(repo, "--only", "secret_detection", env=env)
            coverage = json.loads(
                (repo / ".appsec-results" / "scan-coverage.json").read_text(encoding="utf-8")
            )

        output = result.stdout + result.stderr
        self.assertIn("ADVISORY: glci unavailable — secret_detection ran with the docker engine", output)
        self.assertEqual(coverage["engine"]["secret_detection"], "docker-fallback")
        self.assertNotIn("secret_detection", coverage["missing_report"], output)

    def test_sd_glci_job_failed_is_a_missing_report_not_clean(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "repo").mkdir()
            repo = self.make_repo(str(root / "repo"), pom=False)
            stub = (
                "#!/bin/sh\n"
                "printf 'GLCI-RESULT: category=secret_detection status=job_failed jobs=secret-detection:failed reports= glci_commit=abc123\\n'\n"
                "printf 'GLCI-REASON: job secret-detection failed\\n'\n"
                "exit 4\n"
            )
            scripts = self.stub_scripts_dir(root, **{"glci-run.sh": stub})
            fake_docker = root / "fake-docker"
            fake_docker.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
            fake_docker.chmod(0o755)
            env = self.sd_only_env(
                root,
                scripts,
                RUNTIME=str(fake_docker),
            )
            result = self.run_scan_real(repo, "--only", "secret_detection", env=env)
            coverage = json.loads(
                (repo / ".appsec-results" / "scan-coverage.json").read_text(encoding="utf-8")
            )
            skips = (repo / ".appsec-results" / "scan-skips").read_text(encoding="utf-8")

        output = result.stdout + result.stderr
        self.assertIn("secret_detection", coverage["missing_report"], output)
        self.assertFalse(coverage["coverage_complete"], output)
        self.assertIn("job secret-detection failed", skips)
        self.assertNotEqual(result.returncode, 0, output)

    # -------------------------------------------------------------------
    # Container scanning, engine: glci
    # -------------------------------------------------------------------

    def test_cs_glci_success_does_not_docker_save_the_image_archive(self) -> None:
        # glci pushes the host-built image into its own embedded registry
        # (see glci-run.sh), so a `docker save` archive is never read on a
        # successful glci run -- only the docker engine and the glci->docker
        # fallback path need it.
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "repo").mkdir()
            repo = self.make_repo(str(root / "repo"), pom=False)
            (repo / "Dockerfile").write_text("FROM alpine:3\n", encoding="utf-8")
            stub = (
                "#!/bin/sh\n"
                "results=\"\"\n"
                "prev=\"\"\n"
                "for a in \"$@\"; do\n"
                "  if [ \"$prev\" = --results ]; then results=\"$a\"; fi\n"
                "  prev=\"$a\"\n"
                "done\n"
                "mkdir -p \"$results\"\n"
                "printf '{\"version\":\"15.0.0\",\"vulnerabilities\":[]}' > \"$results/gl-container-scanning-report.json\"\n"
                "printf 'GLCI-RESULT: category=container_scanning status=ok "
                "jobs=container-scanning:passed "
                "reports=gl-container-scanning-report.json glci_commit=deadbeef\\n'\n"
                "exit 0\n"
            )
            scripts = self.stub_scripts_dir(root, **{"glci-run.sh": stub})
            fake_docker = root / "fake-docker"
            fake_docker.write_text(
                "#!/bin/sh\n"
                "case \"$1\" in\n"
                "  save)\n"
                "    out=\"\"\n"
                "    prev=\"\"\n"
                "    for a in \"$@\"; do\n"
                "      if [ \"$prev\" = -o ]; then out=\"$a\"; fi\n"
                "      prev=\"$a\"\n"
                "    done\n"
                "    : > \"$out\"\n"
                "    exit 0 ;;\n"
                "esac\n"
                "exit 0\n",
                encoding="utf-8",
            )
            fake_docker.chmod(0o755)
            components = {
                "sast": "fortify-sast/fortify-sast",
                "dependency_scanning": "dependency-scanning/dependency-scanning",
                "secret_detection": "secret-detection/secret-detection",
            }
            block = (
                "component: lobster-thermidor/devops/ci-catalogue/{path}\n"
                "        version: ~latest\n"
                "        enabled: {flag}"
            )
            replacements = [
                (block.format(path=path, flag="true"), block.format(path=path, flag="false"))
                for path in components.values()
            ]
            replacements.append(
                (CATALOG_ENGINE_BLOCK, CATALOG_ENGINE_BLOCK + "    engine: glci\n")
            )
            skill = self.make_skill_with_config(root, *replacements)
            # Every RUN_* stays unset so run-scan.sh self-loads the config
            # above (only that path reads engine: glci and resolves
            # GITLAB_CS_IMAGE via the component catalog; presetting RUN_* -
            # the way non-glci container-scanning tests do - skips that load
            # entirely).
            env = self.self_loading_env(
                SCRIPTS_DIR=str(scripts),
                SKILL_DIR=str(skill),
                RUNTIME=str(fake_docker),
            )
            env.pop("CS_IMAGE", None)
            result = self.run_scan_real(repo, "--only", "container_scanning", env=env)
            coverage = json.loads(
                (repo / ".appsec-results" / "scan-coverage.json").read_text(encoding="utf-8")
            )
            archive_exists = (repo / ".appsec-results" / "container-image.tar").exists()

        output = result.stdout + result.stderr
        self.assertEqual(result.returncode, 0, output)
        self.assertEqual(coverage["engine"]["container_scanning"], "glci")
        self.assertFalse(archive_exists, output)


class ContainerScanningGlciDockerfileTest(RunScanDryRunTest):
    """Multi-Dockerfile naming + partial coverage, and single-Dockerfile
    backward compatibility — both engines share this code path, so plain
    docker (no glci needed) already exercises the interesting part."""

    def stub_runtime(self, root: Path, body: str) -> Path:
        script = root / "fake-runtime"
        script.write_text("#!/bin/sh\n" + body, encoding="utf-8")
        script.chmod(0o755)
        return script

    def skill_enabling_only_cs(self, root: Path) -> Path:
        """A SKILL_DIR whose config enables only container_scanning.

        run-scan.sh's "expected coverage" bookkeeping re-reads
        scanner-preferences.yaml directly (never the RUN_* env), so a
        RUN_FORTIFY_SAST=false override alone still leaves sast/dependency_
        scanning/secret_detection "expected" per the shipped catalog
        profile (all enabled: true) — and each then reads as a coverage gap.
        Disabling them in the config itself is what test_run_scan.py's own
        FailOpenPathsTest.skill_enabling_only does for the same reason.
        """
        components = {
            "sast": "fortify-sast/fortify-sast",
            "dependency_scanning": "dependency-scanning/dependency-scanning",
            "secret_detection": "secret-detection/secret-detection",
        }
        block = (
            "component: lobster-thermidor/devops/ci-catalogue/{path}\n"
            "        version: ~latest\n"
            "        enabled: {flag}"
        )
        return self.make_skill_with_config(
            root,
            *[
                (block.format(path=path, flag="true"), block.format(path=path, flag="false"))
                for path in components.values()
            ],
        )

    def cs_only_env(self, root: Path, runtime: Path, **overrides: str) -> dict[str, str]:
        return self.base_env(
            RUNTIME=str(runtime),
            SKILL_DIR=str(self.skill_enabling_only_cs(root)),
            RUN_FORTIFY_SAST="false",
            RUN_GITLAB_DS="false",
            RUN_SECRET_DETECTION="false",
            RUN_GITLAB_CS="true",
            **overrides,
        )

    def test_single_dockerfile_keeps_canonical_report_name(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "repo").mkdir()
            repo = self.make_repo(str(root / "repo"), pom=False)
            (repo / "Dockerfile").write_text("FROM alpine:3\n", encoding="utf-8")
            runtime = self.stub_runtime(
                root,
                "case \"$1 $*\" in\n"
                "  *gitlab-container-scanning.sh*)\n"
                "    printf '{\"version\":\"15.0.0\",\"vulnerabilities\":[]}' > .appsec-results/gl-container-scanning-report.json ;;\n"
                "esac\n"
                "exit 0\n",
            )
            env = self.cs_only_env(root, runtime)
            env.pop("CS_IMAGE", None)
            result = subprocess.run(
                [BASH, str(RUN_SCAN), "--only", "container_scanning"],
                cwd=repo,
                env=env,
                capture_output=True,
                text=True,
            )
            report_exists = (repo / ".appsec-results" / "gl-container-scanning-report.json").exists()
            slug_report_exists = (
                repo / ".appsec-results" / "gl-container-scanning-report-dockerfile.json"
            ).exists()

        output = result.stdout + result.stderr
        self.assertEqual(result.returncode, 0, output)
        self.assertTrue(report_exists, output)
        self.assertFalse(slug_report_exists, output)

    def test_multi_dockerfile_gets_per_image_reports_and_partial_failure_is_a_gap(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "repo").mkdir()
            repo = self.make_repo(str(root / "repo"), pom=False)
            (repo / "a").mkdir()
            (repo / "b").mkdir()
            (repo / "a" / "Dockerfile").write_text("FROM alpine:3\n", encoding="utf-8")
            (repo / "b" / "Dockerfile").write_text("FROM alpine:3\n", encoding="utf-8")
            subprocess.run(["git", "add", "-A"], cwd=repo, check=True)
            # b/Dockerfile's build fails; a/Dockerfile's build+scan succeeds.
            runtime = self.stub_runtime(
                root,
                "case \"$1\" in\n"
                "  build)\n"
                "    case \"$*\" in\n"
                "      *b/Dockerfile*) echo 'boom' >&2; exit 1 ;;\n"
                "    esac\n"
                "    ;;\n"
                "esac\n"
                "case \"$*\" in\n"
                "  *gitlab-container-scanning.sh*)\n"
                "    printf '{\"version\":\"15.0.0\",\"vulnerabilities\":[]}' > .appsec-results/gl-container-scanning-report.json ;;\n"
                "esac\n"
                "exit 0\n",
            )
            env = self.cs_only_env(root, runtime, APPSEC_DOCKERFILES="a/Dockerfile,b/Dockerfile")
            env.pop("CS_IMAGE", None)
            result = subprocess.run(
                [BASH, str(RUN_SCAN), "--only", "container_scanning"],
                cwd=repo,
                env=env,
                capture_output=True,
                text=True,
            )
            results_dir = repo / ".appsec-results"
            a_report_exists = (results_dir / "gl-container-scanning-report-a-dockerfile.json").exists()
            b_report_exists = (results_dir / "gl-container-scanning-report-b-dockerfile.json").exists()
            coverage = json.loads((results_dir / "scan-coverage.json").read_text(encoding="utf-8"))
            skips = (results_dir / "scan-skips").read_text(encoding="utf-8")

        output = result.stdout + result.stderr
        self.assertTrue(a_report_exists, output)
        self.assertFalse(b_report_exists, output)
        self.assertIn("container_scanning", coverage["missing_report"], output)
        self.assertFalse(coverage["coverage_complete"], output)
        self.assertIn("b/Dockerfile", skips)
        self.assertIn("1 of 2", skips)
        self.assertNotEqual(result.returncode, 0, output)


class RemoteMatchIntegrationTest(RunScanDryRunTest):
    def stub_scripts_dir(self, root: Path, **stub_bodies: str) -> Path:
        mirror = root / "scripts-stub"
        mirror.mkdir()
        for entry in SCRIPTS_DIR.iterdir():
            if entry.name in stub_bodies:
                continue
            (mirror / entry.name).symlink_to(entry)
        for name, body in stub_bodies.items():
            script = mirror / name
            script.write_text(body, encoding="utf-8")
            script.chmod(0o755)
        (root / "reference").symlink_to(SKILL_DIR / "reference")
        return mirror

    def ds_skill(self, root: Path, matcher_project: str = "acme/matcher") -> Path:
        extra = f"    remote_match_project: {matcher_project}\n"
        return self.make_skill_with_config(
            root,
            (CATALOG_ENGINE_BLOCK, CATALOG_ENGINE_BLOCK + extra),
        )

    def ds_env(self, root: Path, scripts_dir: Path, **overrides: str) -> dict[str, str]:
        # RUN_* deliberately left unset: the catalog profile enables every
        # category, and self-load is what actually resolves GITLAB_DS_IMAGE
        # (and friends) offline from the vendored catalog snapshots — the
        # same path --dry-run/a real scan takes. --only dependency_scanning
        # narrows EXECUTION; image resolution for the other categories is
        # harmless (no container ever runs for them under --only).
        return self.self_loading_env(
            SCRIPTS_DIR=str(scripts_dir),
            SKILL_DIR=str(self.ds_skill(root)),
            **overrides,
        )

    def run_scan_real(self, repo: Path, *args: str, env: dict[str, str]) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [BASH, str(RUN_SCAN), *args],
            cwd=repo,
            env=env,
            capture_output=True,
            text=True,
        )

    def test_remote_match_ok_skips_local_sbom_and_trivy_source_gitlab_native(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "repo").mkdir()
            repo = self.make_repo(str(root / "repo"), pom=False)
            docker_calls = root / "docker-calls.log"
            stub_rm = (
                "#!/bin/sh\n"
                "results=\"\"\n"
                "prev=\"\"\n"
                "for a in \"$@\"; do\n"
                "  if [ \"$prev\" = --results ]; then results=\"$a\"; fi\n"
                "  prev=\"$a\"\n"
                "done\n"
                "mkdir -p \"$results/remote-ds/javascript\"\n"
                "printf '{\"version\":\"15.0.0\",\"vulnerabilities\":[]}' > \"$results/remote-ds/javascript/gl-dependency-scanning-report.json\"\n"
                "printf '{\"language\":\"javascript\",\"status\":\"ok\"}' > \"$results/remote-ds/javascript/result.json\"\n"
                "printf 'REMOTE-MATCH: language=javascript status=ok findings=0 pipeline=https://gitlab.example/matcher/-/pipelines/42\\n'\n"
                "exit 0\n"
            )
            fake_docker = root / "fake-docker"
            fake_docker.write_text(
                f"#!/bin/sh\nprintf '%s\\n' \"$@\" >> {docker_calls}\nexit 0\n",
                encoding="utf-8",
            )
            fake_docker.chmod(0o755)
            scripts = self.stub_scripts_dir(root, **{"remote-match.sh": stub_rm})
            env = self.ds_env(root, scripts, RUNTIME=str(fake_docker))
            result = self.run_scan_real(repo, "--only", "dependency_scanning", env=env)
            coverage = json.loads(
                (repo / ".appsec-results" / "scan-coverage.json").read_text(encoding="utf-8")
            )

        output = result.stdout + result.stderr
        self.assertFalse(docker_calls.exists(), "local DS/Trivy docker path ran: " + output)
        self.assertEqual(coverage["engine"]["dependency_scanning"], "remote-matcher")
        self.assertEqual(coverage["dependency_scanning"]["source"], "gitlab-native")
        self.assertIn(
            "https://gitlab.example/matcher/-/pipelines/42",
            coverage["dependency_scanning"]["matcher_pipelines"],
        )
        self.assertIn("Dependency Scanning source: gitlab-native", output)

    def test_remote_match_unusable_falls_back_to_local_path(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "repo").mkdir()
            repo = self.make_repo(str(root / "repo"), pom=False)
            stub_rm = (
                "#!/bin/sh\n"
                "printf 'REMOTE-MATCH-REASON: language=javascript no token\\n'\n"
                "exit 3\n"
            )
            fake_docker = root / "fake-docker"
            fake_docker.write_text(
                "#!/bin/sh\n"
                "case \"$*\" in\n"
                "  *gitlab-dependency-scanning.sh*) : ;;\n"
                "esac\n"
                "exit 0\n",
                encoding="utf-8",
            )
            fake_docker.chmod(0o755)
            scripts = self.stub_scripts_dir(root, **{"remote-match.sh": stub_rm})
            env = self.ds_env(root, scripts, RUNTIME=str(fake_docker))
            result = self.run_scan_real(repo, "--only", "dependency_scanning", env=env)

        output = result.stdout + result.stderr
        self.assertIn("ADVISORY: remote matcher unusable", output)
        self.assertIn("falling back to the local SBOM + offline Trivy match", output)

    def test_remote_match_partial_failure_records_a_gap_and_names_the_off_switch(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "repo").mkdir()
            repo = self.make_repo(str(root / "repo"), pom=False)
            stub_rm = (
                "#!/bin/sh\n"
                "printf 'REMOTE-MATCH: language=javascript status=ok findings=0 pipeline=https://x/1\\n'\n"
                "printf 'REMOTE-MATCH: language=python status=failed findings=0 pipeline=https://x/2\\n'\n"
                "printf 'REMOTE-MATCH-REASON: language=python dependency-scanning job failed\\n'\n"
                "exit 4\n"
            )
            scripts = self.stub_scripts_dir(root, **{"remote-match.sh": stub_rm})
            fake_docker = root / "fake-docker"
            fake_docker.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
            fake_docker.chmod(0o755)
            env = self.ds_env(root, scripts, RUNTIME=str(fake_docker))
            result = self.run_scan_real(repo, "--only", "dependency_scanning", env=env)
            skips = (repo / ".appsec-results" / "scan-skips").read_text(encoding="utf-8")
            coverage = json.loads(
                (repo / ".appsec-results" / "scan-coverage.json").read_text(encoding="utf-8")
            )

        output = result.stdout + result.stderr
        self.assertIn("python", skips)
        self.assertIn("APPSEC_REMOTE_MATCH=off", skips)
        self.assertIn("dependency_scanning", coverage["missing_report"], output)
        self.assertNotEqual(result.returncode, 0, output)

    def test_appsec_remote_match_off_forces_local_path(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "repo").mkdir()
            repo = self.make_repo(str(root / "repo"), pom=False)
            called = root / "remote-match-called"
            stub_rm = f"#!/bin/sh\n: > {called}\nexit 0\n"
            fake_docker = root / "fake-docker"
            fake_docker.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
            fake_docker.chmod(0o755)
            scripts = self.stub_scripts_dir(root, **{"remote-match.sh": stub_rm})
            env = self.ds_env(root, scripts, RUNTIME=str(fake_docker), APPSEC_REMOTE_MATCH="off")
            self.run_scan_real(repo, "--only", "dependency_scanning", env=env)

        self.assertFalse(called.exists(), "remote-match.sh ran despite APPSEC_REMOTE_MATCH=off")

    def test_dry_run_prints_remote_match_command_with_redacted_token_and_uploads_nothing(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "repo").mkdir()
            repo = self.make_repo(str(root / "repo"), pom=False)
            called = root / "remote-match-called"
            stub_rm = f"#!/bin/sh\n: > {called}\nexit 0\n"
            scripts = self.stub_scripts_dir(root, **{"remote-match.sh": stub_rm})
            env = self.ds_env(root, scripts, GITLAB_READ_TOKEN="s3cr3t-token-value")
            result = self.run_scan_real(repo, "--only", "dependency_scanning", "--dry-run", env=env)

        output = result.stdout + result.stderr
        self.assertFalse(called.exists(), "remote-match.sh actually ran during --dry-run: " + output)
        self.assertIn("DRY-RUN:", output)
        self.assertIn("remote-match.sh", output)
        self.assertIn("APPSEC_RESOLVED_TOKEN=<redacted>", output)
        self.assertNotIn("s3cr3t-token-value", output)


if __name__ == "__main__":
    unittest.main()
