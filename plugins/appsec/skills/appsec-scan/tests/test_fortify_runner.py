"""scanners/fortify-sast.sh must run the command the CI component runs.

The gradle arm is the one that can silently disagree. The component invokes
`$[[ inputs.source-path ]]/gradlew` (template.yml:130); this runner used to invoke
`./gradlew`. Whenever source-path is not ".", those are different files — so the
local scan and the CI job could execute different builds, and a repository with the
wrapper in only one of the two places passed in one and failed in the other with a
message that looked like a broken build rather than a path mismatch.

Executed with a stub `sourceanalyzer` on PATH, so these assert the actual command
line rather than the shape of the source file.
"""

from __future__ import annotations

import os
import stat
import subprocess
import tempfile
import unittest
from pathlib import Path

SKILL_DIR = Path(__file__).resolve().parents[1]
RUNNER = SKILL_DIR / "scanners" / "fortify-sast.sh"


class FortifyRunnerTest(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.bin = self.root / "stub-bin"
        self.bin.mkdir()
        stub = self.bin / "sourceanalyzer"
        stub.write_text("#!/bin/sh\necho \"sourceanalyzer $*\"\n")
        stub.chmod(stub.stat().st_mode | stat.S_IEXEC)

    def _repo(self, name: str, *wrappers: str) -> Path:
        repo = self.root / name
        (repo / "src").mkdir(parents=True)
        for rel in wrappers:
            path = repo / rel
            path.write_text("#!/bin/sh\n")
            path.chmod(path.stat().st_mode | stat.S_IEXEC)
        return repo

    def _run(self, repo: Path, language: str = "gradle",
             source_path: str = "src", **extra: str) -> subprocess.CompletedProcess[str]:
        env = dict(
            os.environ,
            PATH=f"{self.bin}{os.pathsep}{os.environ['PATH']}",
            CI_PROJECT_DIR=str(repo),
            SOURCE_PATH=source_path,
            FORTIFY_LANGUAGE=language,
            APP_NAME="demo",
        )
        env.update(extra)
        return subprocess.run(
            ["sh", str(RUNNER)], cwd=repo, env=env, capture_output=True, text=True
        )

    def test_uses_the_wrapper_ci_uses(self) -> None:
        result = self._run(self._repo("a", "src/gradlew"))
        self.assertIn("sourceanalyzer -b demo src/gradlew -p src clean assemble",
                      result.stdout)
        self.assertNotIn("./gradlew -p", result.stdout)
        self.assertNotIn("WARNING", result.stderr)

    def test_root_wrapper_still_scans_but_predicts_the_ci_failure(self) -> None:
        """The whole value of a pre-push scan: say what CI will do, before CI does."""
        result = self._run(self._repo("b", "gradlew"))
        self.assertIn("sourceanalyzer -b demo ./gradlew -p src clean assemble",
                      result.stdout)
        self.assertIn("CI runs src/gradlew, which does not exist here", result.stderr)
        self.assertIn("the CI job", result.stderr)

    def test_no_wrapper_anywhere_fails_loudly(self) -> None:
        result = self._run(self._repo("c"))
        self.assertEqual(result.returncode, 2)
        self.assertIn("no gradle wrapper", result.stderr)

    def test_source_path_dot_uses_the_root_wrapper_without_warning(self) -> None:
        """source-path: . is the layout the component's own README assumes."""
        result = self._run(self._repo("d", "gradlew"), source_path=".")
        self.assertIn("sourceanalyzer -b demo ./gradlew -p . clean assemble",
                      result.stdout)
        self.assertNotIn("WARNING", result.stderr)

    def test_diagnostic_flags_match_the_component(self) -> None:
        """-debug-verbose changes only log output, but a translation that fails
        without it is markedly harder to diagnose than the CI job it mirrors."""
        maven = self._run(self._repo("m"), language="maven")
        self.assertIn("sourceanalyzer -debug -verbose -b demo mvn clean install",
                      maven.stdout)

        python = self._run(self._repo("p"), language="python")
        self.assertIn("-debug-verbose", python.stdout)
        self.assertIn("-python-version 3", python.stdout)

        javascript = self._run(self._repo("j"), language="javascript")
        self.assertIn("-debug-verbose", javascript.stdout)
        self.assertIn("-Dcom.fortify.sca.follow.imports=false", javascript.stdout)

    def test_python_arm_passes_python_path_but_not_a_translation_target(self) -> None:
        """Mirrors the component exactly — both halves matter.

        The original omission was deliberate: issue #12 established that the old
        component's `.venv` could not exist in that job (no pip, no uv, no
        virtualenv in the image, `dependencies: []`), so its `-python-path`
        pointed at nothing. That premise CHANGED when fortify-sast!2 taught the
        job to build the venv with uv, so the flag now resolves something real
        and this arm passes it.

        What has NOT changed is issue #12's other half, which its measured table
        is explicit about: `-python-path` resolves imports for the front end but
        does NOT add the library to the build, so a taint path routing THROUGH a
        dependency is still missed. Recovering it needs site-packages as a
        translation target as well — and adding that here alone would make the
        local scan find things CI does not, which breaks the mirror in the other
        direction. It stays an upstream fix; issue #12 stays open.
        """
        result = self._run(self._repo("q"), language="python")
        self.assertIn("-python-path", result.stdout)
        # The scan target is the source path, never site-packages.
        self.assertNotIn("site-packages -python-version", result.stdout)
        self.assertTrue(
            result.stdout.rstrip().endswith("src")
            or " src\n" in result.stdout,
            result.stdout,
        )


    def test_normal_mode_is_not_reported_as_degraded(self) -> None:
        """translation-mode=normal is the component's DEFAULT, not a shortfall.

        The component added the input precisely because full mode "CAN TAKE
        HOURS" — on a 230-package service it exceeded 3h and produced no report.
        Calling the default degraded would cry wolf on every run and train people
        to ignore the one message that matters."""
        result = self._run(self._repo("d"), language="python")
        output = result.stdout + result.stderr
        self.assertNotIn("APPSEC-PY-DEGRADED", output)
        self.assertIn("translation-mode=normal", output)
        # Still names the stdlib: upstream measured that as both more accurate
        # AND faster (349s -> 259s), and normal mode wants it too.
        self.assertIn("-python-path", result.stdout)

    def test_full_mode_that_cannot_be_honoured_is_degraded(self) -> None:
        """This is the real degraded case: a thinner result than the mode asked
        for, which now disagrees with a CI pipeline running full."""
        result = self._run(self._repo("f"), language="python",
                           FORTIFY_TRANSLATION_MODE="full")
        output = result.stdout + result.stderr
        self.assertIn("APPSEC-PY-DEGRADED:", output)
        self.assertIn("python_runtime", output)

    def test_normal_mode_never_installs_uv_even_when_configured(self) -> None:
        """Normal mode needs no venv, so it must not spend time or network on one
        just because the full-mode settings happen to be present."""
        result = self._run(self._repo("n2"), language="python",
                           FORTIFY_TRANSLATION_MODE="normal",
                           UV_VERSION="0.0.0",
                           UV_INSTALLER_BASE="https://mirror.invalid/uv")
        output = result.stdout + result.stderr
        self.assertNotIn("installing uv", output)
        self.assertNotIn("uv-installer.sh", output)

    def test_python_never_reaches_the_public_internet_to_close_the_gap(self) -> None:
        """An unconfigured airgapped host must degrade, not silently fetch uv
        from astral.sh — the component's own default points there."""
        result = self._run(self._repo("n"), language="python",
                           FORTIFY_TRANSLATION_MODE="full")
        output = result.stdout + result.stderr
        self.assertNotIn("astral.sh", output)
        self.assertNotIn("uv-installer.sh", output)

    def test_template_dirs_are_all_or_nothing(self) -> None:
        """-disable-template-autodiscover REPLACES discovery, so naming one
        directory in a repo with two loses the second. Unset must stay unset."""
        off = self._run(self._repo("t1"), language="python")
        self.assertNotIn("-disable-template-autodiscover", off.stdout)
        self.assertNotIn("-django-template-dirs", off.stdout)

        on = self._run(self._repo("t2"), language="python",
                       FORTIFY_PYTHON_TEMPLATE_DIRS="app/templates:web/tpl")
        self.assertIn("-django-template-dirs app/templates:web/tpl", on.stdout)
        self.assertIn("-jinja-template-dirs app/templates:web/tpl", on.stdout)
        self.assertIn("-disable-template-autodiscover", on.stdout)


class UvTlsLadderTest(unittest.TestCase):
    """Downloading a script and piping it to sh is remote code execution if
    anything can sit in the middle, so the order of these rungs is the whole
    point: verify, then trust the configured internal CA, and only then -- if an
    admin has explicitly allowed it -- give up on verification, loudly.

    Verified against the real fortify-sca 25.2.0 image: the container runs as
    uid 1000 with a non-writable anchors dir, so `update-ca-trust` cannot be the
    mechanism; exporting SSL_CERT_FILE/CURL_CA_BUNDLE/REQUESTS_CA_BUNDLE is, and
    unlike `curl --cacert` it also covers uv's own downloads.
    """

    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.bin = self.root / "bin"
        self.bin.mkdir()
        for name in ("sourceanalyzer",):
            stub = self.bin / name
            stub.write_text("#!/bin/sh\nexit 0\n")
            stub.chmod(stub.stat().st_mode | stat.S_IEXEC)
        self.calls = self.root / "curl-calls.log"

    def _curl(self, *, plain_works: bool, ca_works: bool = False) -> None:
        """A curl that verifies only under the conditions the test declares."""
        stub = self.bin / "curl"
        stub.write_text(
            "#!/bin/sh\n"
            f'echo "$@" >> {self.calls}\n'
            'case " $* " in *" -k "*) exit 0 ;; esac\n'
            + ("exit 0\n" if plain_works else
               ('if [ -n "$SSL_CERT_FILE" ] && grep -q MAGIC-CA "$SSL_CERT_FILE" 2>/dev/null; then\n'
                f'  {"exit 0" if ca_works else "exit 60"}\n'
                'fi\n'
                'exit 60\n'))
        )
        stub.chmod(stub.stat().st_mode | stat.S_IEXEC)

    def _run(self, **extra: str):
        repo = self.root / "repo"
        (repo / "src").mkdir(parents=True, exist_ok=True)
        env = dict(
            os.environ,
            PATH=f"{self.bin}{os.pathsep}{os.environ['PATH']}",
            CI_PROJECT_DIR=str(repo),
            SOURCE_PATH="src",
            FORTIFY_LANGUAGE="python",
            APP_NAME="demo",
            UV_VERSION="0.0.0",
            UV_INSTALLER_BASE="https://mirror.invalid/uv",
            FORTIFY_TRANSLATION_MODE="full",
        )
        env.update(extra)
        return subprocess.run(["sh", str(RUNNER)], cwd=repo, env=env,
                              capture_output=True, text=True)

    def _used_insecure(self) -> bool:
        if not self.calls.exists():
            return False
        return any(" -k " in f" {line} " for line in self.calls.read_text().splitlines())

    def test_rung1_verified_needs_no_ca_and_no_k(self) -> None:
        self._curl(plain_works=True)
        result = self._run()
        self.assertNotIn("APPSEC-INSECURE-TLS", result.stderr)
        self.assertNotIn("settings.ca_bundle", result.stderr)
        self.assertFalse(self._used_insecure(), self.calls.read_text())

    def test_rung2_configured_ca_rescues_the_handshake(self) -> None:
        ca = self.root / "ca.pem"
        ca.write_text("MAGIC-CA\n")
        self._curl(plain_works=False, ca_works=True)
        result = self._run(ADDITIONAL_CA_CERT_BUNDLE=str(ca))
        self.assertIn("verified via settings.ca_bundle", result.stderr)
        self.assertNotIn("APPSEC-INSECURE-TLS", result.stderr)
        self.assertFalse(self._used_insecure(), "fell back to -k with a working CA")

    def test_rung4_refuses_when_insecure_is_not_permitted(self) -> None:
        """The default. No CA, no verification, no download."""
        self._curl(plain_works=False)
        result = self._run(ALLOW_INSECURE_UV_DOWNLOAD="false")
        self.assertIn("could not be verified", result.stderr)
        self.assertIn("APPSEC-PY-DEGRADED", result.stderr)
        self.assertFalse(self._used_insecure(), "used -k without being allowed to")

    def test_a_404_is_not_diagnosed_as_a_tls_failure(self) -> None:
        """Caught against the real image. The probe used `curl -sSf`, so an HTTP
        404 exits 22 exactly like a certificate failure — a trusted mirror that
        simply does not carry this uv version was reported as "TLS could not be
        verified", and on an estate with allow_insecure_uv_download set that
        would disable verification to solve a missing file."""
        stub = self.bin / "curl"
        # Transport fine, HTTP 404: fails only when -f is passed.
        stub.write_text(
            "#!/bin/sh\n"
            f'echo "$@" >> {self.calls}\n'
            'case " $* " in *" -f "*|*"-LsSf"*|*"-sSf"*) exit 22 ;; esac\n'
            "exit 0\n"
        )
        stub.chmod(stub.stat().st_mode | stat.S_IEXEC)
        result = self._run(ALLOW_INSECURE_UV_DOWNLOAD="true")
        self.assertNotIn("could not be verified", result.stderr)
        self.assertNotIn("APPSEC-INSECURE-TLS", result.stderr)
        self.assertFalse(self._used_insecure(), "disabled TLS over an HTTP 404")

    def test_rung3_insecure_only_when_explicitly_allowed_and_says_so(self) -> None:
        self._curl(plain_works=False)
        result = self._run(ALLOW_INSECURE_UV_DOWNLOAD="true")
        self.assertIn("APPSEC-INSECURE-TLS", result.stderr)
        self.assertIn("arbitrary code", result.stderr)
        self.assertTrue(self._used_insecure(), "claimed insecure but never used -k")


class JvmTrustStoreTest(unittest.TestCase):
    """settings.ca_bundle reaches curl/python via appsec_trust_ca (see
    UvTlsLadderTest above) but never the JVM on its own, so a Maven/Gradle
    build behind TLS-inspection fails to resolve dependencies with a trust
    error that reads like a broken mirror. Exercised with a stub `keytool` on
    PATH and a fake $JAVA_HOME/lib/security/cacerts, so this never touches a
    real JDK."""

    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.bin = self.root / "bin"
        self.bin.mkdir()
        stub = self.bin / "sourceanalyzer"
        stub.write_text("#!/bin/sh\nexit 0\n")
        stub.chmod(stub.stat().st_mode | stat.S_IEXEC)
        self.keytool_log = self.root / "keytool-calls.log"
        self.java_home = self.root / "javahome"
        (self.java_home / "lib" / "security").mkdir(parents=True)
        (self.java_home / "lib" / "security" / "cacerts").write_text("fake-cacerts\n")
        self.bundle = self.root / "ca-bundle.pem"

    def _keytool(self, *, fail_alias: str | None = None) -> None:
        stub = self.bin / "keytool"
        fail_case = (
            f'case " $* " in *" -alias {fail_alias} "*) exit 1 ;; esac\n'
            if fail_alias else ""
        )
        stub.write_text(
            "#!/bin/sh\n"
            f'echo "$@" >> {self.keytool_log}\n'
            f"{fail_case}"
            "exit 0\n"
        )
        stub.chmod(stub.stat().st_mode | stat.S_IEXEC)

    def _run(self, path: str | None = None, **extra: str):
        repo = self.root / "repo"
        (repo / "src").mkdir(parents=True, exist_ok=True)
        env = dict(
            os.environ,
            PATH=path or f"{self.bin}{os.pathsep}{os.environ['PATH']}",
            CI_PROJECT_DIR=str(repo),
            SOURCE_PATH="src",
            FORTIFY_LANGUAGE="javascript",
            APP_NAME="demo",
            JAVA_HOME=str(self.java_home),
        )
        env.update(extra)
        return subprocess.run(["sh", str(RUNNER)], cwd=repo, env=env,
                              capture_output=True, text=True)

    def test_imports_every_certificate_and_exports_java_tool_options(self) -> None:
        self._keytool()
        self.bundle.write_text(
            "-----BEGIN CERTIFICATE-----\nFAKECERTONE\n-----END CERTIFICATE-----\n"
            "-----BEGIN CERTIFICATE-----\nFAKECERTTWO\n-----END CERTIFICATE-----\n"
        )
        result = self._run(ADDITIONAL_CA_CERT_BUNDLE=str(self.bundle))
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("imported 2 certificate(s)", result.stderr)
        self.assertIn("JAVA_TOOL_OPTIONS: -Djavax.net.ssl.trustStore=", result.stderr)
        self.assertIn("-Djavax.net.ssl.trustStorePassword=changeit", result.stderr)
        calls = self.keytool_log.read_text().splitlines()
        self.assertEqual(len(calls), 2, calls)
        self.assertTrue(
            all("-importcert" in c and "-noprompt" in c for c in calls), calls
        )

    def test_a_certificate_that_fails_to_import_is_skipped_not_fatal(self) -> None:
        self._keytool(fail_alias="appsec-ca-1")
        self.bundle.write_text(
            "-----BEGIN CERTIFICATE-----\nBADCERT\n-----END CERTIFICATE-----\n"
            "-----BEGIN CERTIFICATE-----\nGOODCERT\n-----END CERTIFICATE-----\n"
        )
        result = self._run(ADDITIONAL_CA_CERT_BUNDLE=str(self.bundle))
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("could not import certificate #1", result.stderr)
        self.assertIn("imported 1 certificate(s)", result.stderr)

    def test_no_bundle_configured_leaves_the_jvm_untouched(self) -> None:
        """Shipped default (no ca_bundle): every other estate is unchanged."""
        self._keytool()
        result = self._run()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertNotIn("JAVA_TOOL_OPTIONS", result.stderr)
        self.assertNotIn("imported", result.stderr)
        self.assertFalse(self.keytool_log.exists(), "keytool ran with no bundle configured")

    def test_no_keytool_on_path_leaves_the_jvm_untouched(self) -> None:
        self.bundle.write_text(
            "-----BEGIN CERTIFICATE-----\nX\n-----END CERTIFICATE-----\n"
        )
        result = self._run(
            path=f"{self.bin}{os.pathsep}/bin",
            ADDITIONAL_CA_CERT_BUNDLE=str(self.bundle),
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertNotIn("JAVA_TOOL_OPTIONS", result.stderr)


class GoTrustTest(unittest.TestCase):
    """go reads SSL_CERT_FILE, not the JVM truststore, so behind TLS
    inspection `go mod download` failed every fetch with "x509: certificate
    signed by unknown authority" and the unit produced no report — even with
    settings.ca_bundle configured."""

    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.bin = self.root / "bin"
        self.bin.mkdir()
        for name, body in (
            ("sourceanalyzer", "exit 0\n"),
            # Succeeds only if the bundle it is told to trust carries our CA.
            ("go", 'grep -q MAGIC-CA "${SSL_CERT_FILE:-/nonexistent}" 2>/dev/null'
                   ' || { echo "x509: certificate signed by unknown authority" >&2; exit 1; }\n'),
        ):
            stub = self.bin / name
            stub.write_text("#!/bin/sh\n" + body)
            stub.chmod(stub.stat().st_mode | stat.S_IEXEC)

    def _run(self, **extra: str):
        repo = self.root / "repo"
        (repo / "src").mkdir(parents=True, exist_ok=True)
        env = dict(
            os.environ,
            PATH=f"{self.bin}{os.pathsep}/usr/bin{os.pathsep}/bin",
            CI_PROJECT_DIR=str(repo),
            SOURCE_PATH="src",
            FORTIFY_LANGUAGE="go",
            APP_NAME="demo",
        )
        env.pop("SSL_CERT_FILE", None)
        env.update(extra)
        return subprocess.run(["sh", str(RUNNER)], cwd=repo, env=env,
                              capture_output=True, text=True)

    def test_go_module_fetch_trusts_the_configured_ca(self) -> None:
        bundle = self.root / "ca-bundle.pem"
        bundle.write_text("-----BEGIN CERTIFICATE-----\nMAGIC-CA\n-----END CERTIFICATE-----\n")
        result = self._run(ADDITIONAL_CA_CERT_BUNDLE=str(bundle))
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_no_bundle_leaves_go_on_the_system_trust(self) -> None:
        result = self._run()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("x509", result.stderr)


class PythonVenvLocationTest(unittest.TestCase):
    """translation_mode: full builds a venv. /workspace is the user's
    repository and is shared by every unit run-scan.sh runs in parallel, so the
    venv must live in the container's own temp space, never in the repo."""

    def test_full_mode_venv_is_not_created_in_the_repository(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            bin_dir = root / "bin"
            bin_dir.mkdir()
            home = root / "home"
            (home / ".local" / "bin").mkdir(parents=True)
            (home / ".local" / "bin" / "env").write_text("")
            for name, body in (
                ("sourceanalyzer", 'echo "sourceanalyzer $*"\n'),
                # The installer fetch: write a no-op installer wherever -o says.
                ("curl", 'while [ $# -gt 0 ]; do [ "$1" = -o ] && { printf "exit 0\\n" > "$2"; shift; }; shift; done\n'),
                ("uv", 'if [ "$1" = venv ]; then mkdir -p "$2/bin" "$2/lib/python3.12/site-packages";'
                       ' : > "$2/bin/activate"; fi\nexit 0\n'),
            ):
                stub = bin_dir / name
                stub.write_text("#!/bin/sh\n" + body)
                stub.chmod(stub.stat().st_mode | stat.S_IEXEC)
            repo = root / "repo"
            (repo / "src").mkdir(parents=True)
            (repo / "src" / "requirements.txt").write_text("requests\n")
            env = dict(
                os.environ,
                PATH=f"{bin_dir}{os.pathsep}{os.environ['PATH']}",
                HOME=str(home),
                CI_PROJECT_DIR=str(repo),
                SOURCE_PATH="src",
                FORTIFY_LANGUAGE="python",
                APP_NAME="demo",
                UV_VERSION="0.0.0",
                UV_INSTALLER_BASE="https://mirror.invalid/uv",
                FORTIFY_TRANSLATION_MODE="full",
            )
            result = subprocess.run(["sh", str(RUNNER)], cwd=repo, env=env,
                                    capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertFalse((repo / ".venv").exists(), "venv written into the repository")
            translate = next(line for line in result.stdout.splitlines()
                             if "-python-path" in line)
            self.assertIn("/venv/lib/python3.12/site-packages", translate)
            self.assertNotIn(str(repo) + "/", translate.split("-python-version")[0])
            self.assertNotIn("APPSEC-PY-DEGRADED", result.stderr)


if __name__ == "__main__":
    unittest.main()
