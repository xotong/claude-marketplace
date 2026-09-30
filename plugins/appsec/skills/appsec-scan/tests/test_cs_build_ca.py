#!/usr/bin/env python3
"""Local image builds behind a TLS-inspecting proxy.

Behind Zscaler (or any proxy that re-signs certificates) every crAPI Dockerfile
failed locally at its first downloading RUN step — apk, pip, npm, go, gradle —
while CI built the same files fine, so container scanning covered 0 of 7
images. The fix builds from a rewritten copy of each Dockerfile whose RUN steps
bind-mount settings.ca_bundle. The image being scanned must not change: no
COPY, no ENV, and every non-RUN line byte-identical.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

SKILL_DIR = Path(__file__).resolve().parents[1]
SCRIPTS = SKILL_DIR / "scripts"
SCANNERS = SKILL_DIR / "scanners"
OVERLAY = SCRIPTS / "ca-overlay.awk"
TARGET = SCRIPTS / "container-target.sh"
BUILD_CA = SCRIPTS / "build-ca-context.sh"
RUN_SCAN = SCRIPTS / "run-scan.sh"
BASH = shutil.which("bash") or "/bin/bash"
MOUNT = "--mount=type=bind,from=appsec-ca,target=/tmp/appsec-ca"

DOCKERFILE = """\
# syntax=docker/dockerfile:1
FROM python:3.11-alpine AS build
ARG PIP_INDEX
ENV PYTHONUNBUFFERED=1
RUN apk add --no-cache curl
run pip install -r requirements.txt
RUN --network=default go mod download
RUN ["/bin/sh", "-c", "echo exec-form"]
RUN <<EOF
echo heredoc
EOF
RUN \\
    npm install
COPY . /app
FROM alpine:3
CMD ["/app/main"]
"""


def overlay(text: str, java: str = "0") -> str:
    with tempfile.NamedTemporaryFile("w", suffix=".Dockerfile", delete=False) as fh:
        fh.write(text)
    try:
        return subprocess.run(
            ["awk", "-v", f"java={java}", "-f", str(OVERLAY), fh.name],
            check=True, capture_output=True, text=True,
        ).stdout
    finally:
        os.unlink(fh.name)


class CaOverlayTest(unittest.TestCase):
    def setUp(self) -> None:
        self.out = overlay(DOCKERFILE).splitlines()
        self.src = DOCKERFILE.splitlines()

    def test_every_non_run_line_is_byte_identical(self) -> None:
        self.assertEqual(len(self.out), len(self.src))
        for before, after in zip(self.src, self.out):
            if not before.lstrip().upper().startswith("RUN "):
                self.assertEqual(after, before)

    def test_adds_no_copy_and_no_env(self) -> None:
        """Anything persistent would change the image under scan."""
        added = [a for a, b in zip(self.out, self.src) if a != b]
        for line in added:
            self.assertFalse(line.upper().startswith(("COPY", "ADD", "ENV")), line)

    def test_shell_form_run_mounts_the_bundle_and_exports_trust_vars(self) -> None:
        line = self.out[4]
        self.assertTrue(line.startswith(f"RUN {MOUNT} export SSL_CERT_FILE="), line)
        for var in ("SSL_CERT_FILE", "REQUESTS_CA_BUNDLE", "PIP_CERT",
                    "NODE_EXTRA_CA_CERTS", "CURL_CA_BUNDLE"):
            self.assertIn(f"{var}=/tmp/appsec-ca/ca.pem", line)
        # GNU wget ignores SSL_CERT_FILE (gateway-service's certgen download).
        self.assertIn("WGETRC=/tmp/appsec-ca/wgetrc", line)
        self.assertTrue(line.endswith("; apk add --no-cache curl"), line)

    def test_lowercase_run_is_rewritten_too(self) -> None:
        self.assertIn(MOUNT, self.out[5])

    def test_existing_flags_are_kept(self) -> None:
        self.assertIn(f"{MOUNT} --network=default export ", self.out[6])

    def test_exec_form_and_heredoc_are_left_alone(self) -> None:
        self.assertEqual(self.out[7], self.src[7])
        self.assertEqual(self.out[8], self.src[8])

    def test_continuation_line_keeps_its_continuation(self) -> None:
        self.assertTrue(self.out[11].endswith("; \\"), self.out[11])
        self.assertEqual(self.out[12], self.src[12])

    def test_jvm_truststore_only_when_asked(self) -> None:
        self.assertNotIn("JAVA_TOOL_OPTIONS", "\n".join(self.out))
        with_java = overlay(DOCKERFILE, java="1").splitlines()[4]
        self.assertIn("-Djavax.net.ssl.trustStore=/tmp/appsec-ca/truststore.p12", with_java)
        # An image's own JAVA_TOOL_OPTIONS is extended, not replaced.
        self.assertIn('JAVA_TOOL_OPTIONS="${JAVA_TOOL_OPTIONS:+$JAVA_TOOL_OPTIONS }', with_java)

    def test_rewritten_step_runs_in_a_posix_shell(self) -> None:
        """The prefix must be valid sh, or every RUN step fails outright."""
        line = overlay("RUN echo \"$SSL_CERT_FILE|$PIP_CERT\"\n", java="1")
        cmd = line.split(MOUNT, 1)[1].strip()
        proc = subprocess.run(["sh", "-c", cmd], capture_output=True, text=True)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertEqual(proc.stdout.strip(), "/tmp/appsec-ca/ca.pem|/tmp/appsec-ca/ca.pem")


class ContainerTargetBuildTest(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        root = Path(self.tmp.name)
        self.repo = root / "repo"
        self.repo.mkdir()
        (self.repo / "Dockerfile").write_text("FROM alpine:3\nRUN apk add curl\n")
        self.args_log = root / "build-args.log"
        self.runtime = root / "fake-runtime"
        self.runtime.write_text(
            "#!/bin/sh\n"
            f'[ "$1" = build ] && printf "%s\\n" "$@" > {self.args_log}\n'
            "exit 0\n"
        )
        self.runtime.chmod(0o755)
        self.ca_dir = root / "build-ca"
        self.ca_dir.mkdir()
        (self.ca_dir / "ca.pem").write_text("pem\n")

    def run_target(self, **env_extra: str) -> list[str]:
        env = {k: v for k, v in os.environ.items()
               if k not in ("CS_IMAGE", "DOCKERFILE", "APPSEC_BUILD_CA_DIR")}
        env.update(env_extra)
        proc = subprocess.run(
            ["bash", str(TARGET), str(self.runtime), "app", ".appsec-results"],
            cwd=self.repo, env=env, capture_output=True, text=True,
        )
        self.assertEqual(proc.returncode, 0, proc.stderr)
        return self.args_log.read_text().splitlines()

    def test_with_a_ca_dir_builds_the_overlay_with_the_named_context(self) -> None:
        args = self.run_target(APPSEC_BUILD_CA_DIR=str(self.ca_dir))
        self.assertIn(f"appsec-ca={self.ca_dir}", args)
        self.assertEqual(args[args.index("-f") + 1], ".appsec-results/Dockerfile.appsec-ca")
        built = (self.repo / ".appsec-results" / "Dockerfile.appsec-ca").read_text()
        self.assertIn(MOUNT, built)
        # The repository's own Dockerfile is never modified.
        self.assertEqual((self.repo / "Dockerfile").read_text(), "FROM alpine:3\nRUN apk add curl\n")

    def test_without_a_ca_dir_the_build_is_unchanged(self) -> None:
        args = self.run_target()
        self.assertNotIn("--build-context", args)
        self.assertEqual(args[args.index("-f") + 1], "./Dockerfile")


class BuildCaContextTest(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        root = Path(self.tmp.name)
        self.bin = root / "bin"
        self.bin.mkdir()
        self.calls = root / "keytool.log"
        keytool = self.bin / "keytool"
        # Records each import and creates the keystore, like the real one.
        keytool.write_text(
            "#!/bin/sh\n"
            f'echo import >> {self.calls}\n'
            'while [ $# -gt 0 ]; do [ "$1" = -keystore ] && echo store > "$2"; shift; done\n'
        )
        keytool.chmod(0o755)
        self.bundle = root / "bundle.pem"
        self.bundle.write_text(
            "-----BEGIN CERTIFICATE-----\nONE\n-----END CERTIFICATE-----\n"
            "-----BEGIN CERTIFICATE-----\nTWO\n-----END CERTIFICATE-----\n"
        )
        self.out = root / "build-ca"

    def build(self, path: str) -> str:
        proc = subprocess.run(
            [BASH, str(BUILD_CA), str(self.bundle), str(self.out), "false"],
            env=dict(os.environ, PATH=path), capture_output=True, text=True,
        )
        self.assertEqual(proc.returncode, 0, proc.stderr)
        return proc.stdout.strip()

    def test_imports_every_certificate_into_a_truststore(self) -> None:
        self.assertEqual(self.build(f"{self.bin}{os.pathsep}{os.environ['PATH']}"), "java=1")
        self.assertEqual(self.calls.read_text().split(), ["import", "import"])
        self.assertEqual((self.out / "ca.pem").read_text(), self.bundle.read_text())
        self.assertFalse((self.out / ".certs").exists())
        self.assertEqual((self.out / "wgetrc").read_text(),
                         "ca_certificate = /tmp/appsec-ca/ca.pem\n")

    def test_unchanged_bundle_reuses_the_truststore(self) -> None:
        path = f"{self.bin}{os.pathsep}{os.environ['PATH']}"
        self.build(path)
        self.calls.unlink()
        self.assertEqual(self.build(path), "java=1")
        self.assertFalse(self.calls.exists(), "rebuilt a truststore for an unchanged bundle")

    def test_no_keytool_anywhere_still_writes_the_pem(self) -> None:
        self.assertEqual(self.build("/usr/bin:/bin"), "java=0")
        self.assertTrue((self.out / "ca.pem").exists())
        self.assertFalse((self.out / "truststore.p12").exists())


class RunScanWiringTest(unittest.TestCase):
    def dry_run(self, app: str, **env_extra: str) -> str:
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp) / "repo"
            repo.mkdir()
            subprocess.run(["git", "init", "-q"], cwd=repo, check=True)
            (repo / "Dockerfile").write_text("FROM alpine:3\n")
            bundle = Path(tmp) / "ca.pem"
            bundle.write_text("pem\n")
            env = {k: v for k, v in os.environ.items()
                   if k not in ("CS_IMAGE", "DOCKERFILE", "APPSEC_CS_BUILD_CA")}
            env.update(
                RUNTIME="true", SKILL_DIR=str(SKILL_DIR), SCANNERS_DIR=str(SCANNERS),
                SCRIPTS_DIR=str(SCRIPTS), APPSEC_PROFILE="catalog", APP_NAME=app,
                CA_BUNDLE=str(bundle),
                RUN_FORTIFY_SAST="false", RUN_GITLAB_DS="false",
                RUN_SECRET_DETECTION="false", RUN_GITLAB_CS="true",
                FORTIFY_SAST_IMAGE="x", GITLAB_DS_IMAGE="x", SECRET_DETECTION_IMAGE="x",
                GITLAB_CS_IMAGE="example/cs:test", CS_USER_ENV="U", CS_PASS_ENV="P",
                PYTHON_INSTALL_URL="", JQ_INSTALL_URL="", CI_GATE_FAIL_ON="high",
            )
            env.update(env_extra)
            proc = subprocess.run(
                [BASH, str(RUN_SCAN), "--only", "container_scanning", "--dry-run"],
                cwd=repo, env=env, capture_output=True, text=True,
            )
        return proc.stdout + proc.stderr

    def test_image_name_is_lowercased(self) -> None:
        output = self.dry_run("crAPI")
        self.assertIn("crapi-dockerfile", output)
        self.assertNotIn("crAPI-dockerfile", output)

    def test_bundle_reaches_the_build(self) -> None:
        output = self.dry_run("app")
        self.assertIn("build-ca-context.sh", output)
        self.assertIn("APPSEC_BUILD_CA_DIR=", output)
        self.assertRegex(output, r"APPSEC_BUILD_CA_DIR=\S*\.appsec-results/build-ca ")

    def test_fortify_image_lends_keytool_to_a_container_only_scan(self) -> None:
        output = self.dry_run("app", RUN_FORTIFY_SAST="true",
                              FORTIFY_SAST_IMAGE="example/fortify:test")
        line = next(l for l in output.splitlines() if "build-ca-context.sh" in l)
        self.assertTrue(line.rstrip().endswith("example/fortify:test"), line)
        # Lending its JDK is all: SAST itself must not run.
        self.assertNotIn("Fortify unit", output)
        self.assertNotIn("/runner.sh:ro -w /workspace -e APP_NAME", output)

    def test_opt_out_builds_without_it(self) -> None:
        output = self.dry_run("app", APPSEC_CS_BUILD_CA="off")
        self.assertNotIn("build-ca-context.sh", output)
        self.assertRegex(output, r"APPSEC_BUILD_CA_DIR=(''|\"\"|) ")


class ContainerScanRunnerTrustTest(unittest.TestCase):
    """The runner is started with --entrypoint "", which skips the image's own
    ADDITIONAL_CA_CERT_BUNDLE install, so the vulnerability-DB download failed
    behind TLS inspection and every built image went unscanned."""

    def run_archive(self, **env_extra: str) -> subprocess.CompletedProcess[str]:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            bin_dir = root / "bin"
            bin_dir.mkdir()
            scanner = bin_dir / ("tri" + "vy")
            scanner.write_text(
                "#!/bin/sh\n"
                'grep -q MAGIC-CA "${SSL_CERT_FILE:-/nonexistent}" 2>/dev/null'
                ' || { echo "x509: certificate signed by unknown authority" >&2; exit 1; }\n'
                'while [ $# -gt 0 ]; do [ "$1" = -o ] && echo "{}" > "$2"; shift; done\n'
            )
            scanner.chmod(0o755)
            project = root / "project"
            (project / ".appsec-results").mkdir(parents=True)
            archive = project / ".appsec-results" / "container-image.tar"
            archive.write_text("tar")
            env = {k: v for k, v in os.environ.items()
                   if k not in ("SSL_CERT_FILE", "ADDITIONAL_CA_CERT_BUNDLE")}
            env.update(PATH=f"{bin_dir}{os.pathsep}/usr/bin{os.pathsep}/bin",
                       CI_PROJECT_DIR=str(project), CS_SCAN_MODE="archive",
                       CS_ARCHIVE=str(archive))
            if env_extra.pop("bundle", None):
                bundle = root / "ca.pem"
                bundle.write_text("-----BEGIN CERTIFICATE-----\nMAGIC-CA\n-----END CERTIFICATE-----\n")
                env["ADDITIONAL_CA_CERT_BUNDLE"] = str(bundle)
            env.update(env_extra)
            return subprocess.run(["sh", str(SCANNERS / "gitlab-container-scanning.sh")],
                                  env=env, capture_output=True, text=True)

    def test_db_download_trusts_the_configured_ca(self) -> None:
        proc = self.run_archive(bundle="yes")
        self.assertEqual(proc.returncode, 0, proc.stderr)

    def test_without_a_bundle_nothing_changes(self) -> None:
        proc = self.run_archive()
        self.assertNotEqual(proc.returncode, 0)
        self.assertIn("x509", proc.stderr)


if __name__ == "__main__":
    unittest.main()
