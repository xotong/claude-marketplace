#!/usr/bin/env python3
"""Tests for the appsec-scan catalog resolver script."""

from __future__ import annotations

import os
import subprocess
import tempfile
import re
import unittest
from pathlib import Path


SKILL_DIR = Path(__file__).resolve().parents[1]
REPO_ROOT = SKILL_DIR.parents[3]
CATALOG_SCRIPT = SKILL_DIR / "scripts" / "catalog.sh"
SCANNERS_DIR = SKILL_DIR / "scanners"
SCRIPTS_DIR = SKILL_DIR / "scripts"
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
        self.assertIn("check-drift runner-staleness DRIFT ok", result.stdout)
        self.assertIn("image drift literal mismatch ok", result.stdout)
        self.assertIn("image drift literal match silent ok", result.stdout)
        self.assertIn("image drift inputs-interpolation ok", result.stdout)
        self.assertIn("image drift underivable reported ok", result.stdout)


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

    def test_resolve_offline_mode_never_calls_curl(self) -> None:
        script = """#!/bin/sh
set -eu
: > "$CURL_CALLED_FILE"
exit 99
"""
        tmp, env = self.make_env_with_fake_curl(script)
        self.addCleanup(tmp.cleanup)
        called_file = Path(tmp.name) / "curl-called"
        env["CATALOG_MODE"] = "offline"
        env["CURL_CALLED_FILE"] = str(called_file)

        result = run(
            [
                "bash",
                str(CATALOG_SCRIPT),
                "resolve",
                "https://example.invalid",
                SECRET_COMPONENT,
                "~latest",
                str(Path(tmp.name) / "cache"),
            ],
            cwd=REPO_ROOT,
            env=env,
        )

        self.assertFalse(called_file.exists(), result.stdout)
        self.assertTrue(
            result.stdout.strip().endswith("[offline-fallback]"),
            result.stdout,
        )

    def test_date_to_epoch_accepts_today_on_this_host(self) -> None:
        source = CATALOG_SCRIPT.read_text(encoding="utf-8")
        start = source.index("date_to_epoch() {")
        end = source.index("\n}\n", start) + 3
        result = run(
            ["bash", "-c", source[start:end] + '\ndate_to_epoch "$(date +%F)"'],
            cwd=REPO_ROOT,
        )

        self.assertGreater(int(result.stdout.strip()), 1_700_000_000)

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


class ContractCoverageTest(unittest.TestCase):
    """The checked-in contracts are only useful if the runners honour them."""

    CONTRACTS = {
        "fortify-sast": "fortify-sast",
        "gitlab-dependency-scanning": "dependency-scanning",
        "secret-detection": "secret-detection",
        "gitlab-container-scanning": "container-scanning",
    }

    def test_every_contract_has_a_runner(self) -> None:
        for runner in self.CONTRACTS:
            contract = SCANNERS_DIR / f"{runner}.contract"
            self.assertTrue(contract.is_file(), f"{contract.name} missing")
            self.assertTrue((SCANNERS_DIR / f"{runner}.sh").is_file())

    def test_contracts_match_vendored_templates(self) -> None:
        # Guards against someone hand-editing a contract instead of regenerating
        # it, which would silently suppress real drift.
        for runner, component in self.CONTRACTS.items():
            path = f"lobster-thermidor/devops/ci-catalogue/{component}/{component}"
            result = run(
                ["bash", str(CATALOG_SCRIPT), "contract", path, "/nonexistent"],
                cwd=REPO_ROOT, check=False,
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            # the run() helper folds stderr in; keep only contract lines
            derived = sorted(
                l for l in result.stdout.splitlines()
                if l.startswith(("input.", "report."))
            )
            text = (SCANNERS_DIR / f"{runner}.contract").read_text()
            # Only inputs a contract explicitly names as `# ignore-input:` may be left out.
            ignored = tuple(
                f"input.{l.split(':', 1)[1].strip()}."
                for l in text.splitlines() if l.startswith("# ignore-input:")
            )
            derived = [l for l in derived if not (ignored and l.startswith(ignored))]
            checked_in = sorted(
                l for l in text.splitlines()
                if l.strip() and not l.startswith("#")
            )
            self.assertEqual(derived, checked_in, f"{runner}.contract is stale — regenerate it")

    def test_fortify_runner_acknowledges_every_declared_language(self) -> None:
        # A language the component offers but the runner silently ignores is the
        # exact false-clean this whole mechanism exists to prevent. Each one must
        # either run or fail with NEEDS-MAPPING.
        contract = (SCANNERS_DIR / "fortify-sast.contract").read_text().splitlines()
        languages = [
            line.split("=", 1)[1] for line in contract
            if line.startswith("input.language.option=")
        ]
        self.assertIn("go", languages, "expected the component to declare go")
        runner = (SCANNERS_DIR / "fortify-sast.sh").read_text()
        for language in languages:
            self.assertTrue(
                re.search(rf"^\s*{re.escape(language)}\)", runner, re.MULTILINE),
                f"fortify-sast.sh has no case arm for declared language {language!r}",
            )


class RevendorSafetyTest(unittest.TestCase):
    """Re-vendoring must never confirm a stale snapshot against itself."""

    def test_refuses_to_vendor_from_offline_fallback(self) -> None:
        # An unreachable instance makes every component resolve
        # [offline-fallback]. Copying that back over reference/catalog/ would
        # restamp the existing snapshot as freshly fetched — a stale component
        # would then look verified. Nothing may be written.
        before = {
            path: path.read_bytes()
            for path in (SKILL_DIR / "reference" / "catalog").rglob("*")
            if path.is_file()
        }
        result = run(
            ["bash", str(SCRIPTS_DIR / "revendor.sh"), "https://gitlab.invalid.example"],
            cwd=REPO_ROOT, check=False,
        )
        after = {
            path: path.read_bytes()
            for path in (SKILL_DIR / "reference" / "catalog").rglob("*")
            if path.is_file()
        }

        # run() folds stderr into stdout
        self.assertIn("REFUSED", result.stdout)
        self.assertIn("0 vendored", result.stdout)
        self.assertEqual(before, after, "refused run still modified vendored snapshots")


class CatalogAuthDiagnosticsTest(unittest.TestCase):
    """catalog.sh: Bearer header, glab fallback, and the new CONFIG-ERROR classes."""

    COMPONENT = "platform-engineering/ci-catalogue/secret-detection/secret-detection"

    def make_env(self, curl_body: str, *, glab_body: str | None = None,
                 extra_env: dict[str, str] | None = None) -> tuple[tempfile.TemporaryDirectory[str], dict[str, str], Path]:
        tmp = tempfile.TemporaryDirectory(prefix="appsec-catalog-auth-")
        bin_dir = Path(tmp.name) / "bin"
        bin_dir.mkdir()
        curl_path = bin_dir / "curl"
        curl_path.write_text(curl_body, encoding="utf-8")
        curl_path.chmod(0o755)
        if glab_body is not None:
            glab_path = bin_dir / "glab"
            glab_path.write_text(glab_body, encoding="utf-8")
            glab_path.chmod(0o755)

        env = os.environ.copy()
        env["PATH"] = f"{bin_dir}{os.pathsep}{env.get('PATH', '')}"
        # Isolate from whatever the real environment happens to export.
        for name in ("APPSEC_GITLAB_TOKEN", "GITLAB_READ_TOKEN"):
            env.pop(name, None)
        if extra_env:
            env.update(extra_env)
        return tmp, env, bin_dir

    def resolve(self, env: dict[str, str], token_env: str = "", *, cache: Path | None = None) -> subprocess.CompletedProcess[str]:
        return run(
            [
                "bash", str(CATALOG_SCRIPT), "resolve",
                "https://gitlab.example.com", self.COMPONENT, "~latest",
                str(cache or (Path(tempfile.mkdtemp()) / "cache")),
                token_env,
            ],
            cwd=REPO_ROOT, env=env, check=False,
        )

    # -- Bearer header, not PRIVATE-TOKEN -----------------------------------

    def test_bearer_header_written_to_curl_config_not_private_token(self) -> None:
        capture = Path(tempfile.mkdtemp()) / "captured-config"
        curl = f"""#!/bin/sh
for arg do
  if [ "$prev" = "--config" ]; then cp "$arg" "{capture}"; fi
  prev=$arg
done
exit 22
"""
        tmp, env, _ = self.make_env(curl)
        self.addCleanup(tmp.cleanup)
        env["APPSEC_TEST_TOKEN"] = "glpat-deadbeef00112233"

        self.resolve(env, "APPSEC_TEST_TOKEN")

        self.assertTrue(capture.is_file(), "curl --config was never written")
        config_text = capture.read_text(encoding="utf-8")
        self.assertIn("Authorization: Bearer glpat-deadbeef00112233", config_text)
        self.assertNotIn("PRIVATE-TOKEN", config_text)

    def test_curl_config_temp_file_is_chmod_600(self) -> None:
        # The token lives in this file (see the Bearer-header test above).
        # mktemp already defaults to 0600 on this box, so asserting the
        # file's final mode can't tell "explicitly chmod'd" apart from
        # "mktemp's default happened to be 600" -- assert the chmod call
        # itself instead (a stub that logs argv then chains to the real
        # /bin/chmod). curl_get AND curl_status_probe (the diagnostics probe
        # curl_get's failure path calls) each write their own --config file
        # -- exit 22 below drives both in one resolve call, so this catches
        # either one regressing.
        capture = Path(tempfile.mkdtemp()) / "chmod.log"
        chmod_stub = f"""#!/bin/sh
printf '%s\\n' "$*" >> "{capture}"
exec /bin/chmod "$@"
"""
        curl = "#!/bin/sh\nexit 22\n"
        tmp, env, bin_dir = self.make_env(curl)
        self.addCleanup(tmp.cleanup)
        chmod_path = bin_dir / "chmod"
        chmod_path.write_text(chmod_stub, encoding="utf-8")
        chmod_path.chmod(0o755)
        env["APPSEC_TEST_TOKEN"] = "glpat-deadbeef00112233"

        self.resolve(env, "APPSEC_TEST_TOKEN")

        self.assertTrue(capture.is_file(), "chmod was never called on a curl --config file")
        calls = [line for line in capture.read_text(encoding="utf-8").splitlines() if line]
        # curl_get is retried across releases/tags, and each failure re-probes
        # via curl_status_probe, so this is "at least the two call sites",
        # not an exact count.
        self.assertGreaterEqual(len(calls), 2, calls)
        for call in calls:
            self.assertTrue(call.startswith("600 "), call)

    # -- glab fallback --------------------------------------------------------

    def test_glab_fallback_supplies_token_and_never_leaks_it(self) -> None:
        capture = Path(tempfile.mkdtemp()) / "captured-config"
        curl = f"""#!/bin/sh
for arg do
  if [ "$prev" = "--config" ]; then cp "$arg" "{capture}"; fi
  prev=$arg
done
exit 22
"""
        glab = """#!/bin/sh
case "$*" in
  "config get token --host gitlab.example.com") printf '%s' "glab-secret-token-xyz" ;;
  *) exit 1 ;;
esac
"""
        tmp, env, _ = self.make_env(curl, glab_body=glab)
        self.addCleanup(tmp.cleanup)
        env["CATALOG_GLAB_FALLBACK"] = "true"
        # APPSEC_TEST_TOKEN is deliberately absent/empty: env source must miss
        # before glab is even tried.
        env["APPSEC_TEST_TOKEN"] = ""

        result = self.resolve(env, "APPSEC_TEST_TOKEN")

        self.assertTrue(capture.is_file(), "curl --config was never written")
        config_text = capture.read_text(encoding="utf-8")
        self.assertIn("Authorization: Bearer glab-secret-token-xyz", config_text)
        # The token must never appear anywhere in this process's own captured
        # output — only inside the curl --config temp file above.
        # run()'s stderr=STDOUT means result.stderr is None here; the
        # combined output already landed in result.stdout.
        self.assertIsNone(result.stderr)
        self.assertNotIn("glab-secret-token-xyz", result.stdout)

    def test_glab_fallback_off_by_default_does_not_shell_out(self) -> None:
        curl = "#!/bin/sh\nexit 22\n"
        glab = '#!/bin/sh\ntouch "$GLAB_CALLED_MARKER"\nexit 1\n'
        tmp, env, _ = self.make_env(curl, glab_body=glab)
        self.addCleanup(tmp.cleanup)
        marker = Path(tmp.name) / "glab-called"
        env["GLAB_CALLED_MARKER"] = str(marker)
        env["CATALOG_GLAB_FALLBACK"] = "false"
        env["APPSEC_TEST_TOKEN"] = ""

        self.resolve(env, "APPSEC_TEST_TOKEN")

        self.assertFalse(marker.exists(), "glab must not run when glab_fallback is false")

    # -- HTTP 404 classification ---------------------------------------------

    def test_404_with_no_token_names_the_setup_steps(self) -> None:
        curl = """#!/bin/sh
case "${1:-}" in --version) echo "curl 8.0.0"; exit 0 ;; esac
has_w=0
for arg do [ "$arg" = "-w" ] && has_w=1; done
if [ "$has_w" = 1 ]; then printf '404'; exit 0; fi
exit 22
"""
        tmp, env, _ = self.make_env(curl)
        self.addCleanup(tmp.cleanup)
        env["CATALOG_GLAB_FALLBACK"] = "false"

        result = self.resolve(env, "")

        self.assertIn("CONFIG-ERROR", result.stdout)
        self.assertIn("no credential attached", result.stdout)
        self.assertIn("glab auth login", result.stdout)
        self.assertIn("offline-fallback: config-error]", result.stdout)

    def test_404_with_token_names_path_or_visibility(self) -> None:
        curl = """#!/bin/sh
case "${1:-}" in --version) echo "curl 8.0.0"; exit 0 ;; esac
has_w=0
for arg do [ "$arg" = "-w" ] && has_w=1; done
if [ "$has_w" = 1 ]; then printf '404'; exit 0; fi
exit 22
"""
        tmp, env, _ = self.make_env(curl)
        self.addCleanup(tmp.cleanup)
        env["APPSEC_TEST_TOKEN"] = "glpat-hastoken0000000"

        result = self.resolve(env, "APPSEC_TEST_TOKEN")

        self.assertIn("CONFIG-ERROR", result.stdout)
        self.assertIn("even with a token attached", result.stdout)
        self.assertIn("offline-fallback: config-error]", result.stdout)

    # -- TLS verification failure --------------------------------------------

    def test_tls_verify_failure_names_ca_bundle(self) -> None:
        curl = "#!/bin/sh\nexit 60\n"
        tmp, env, _ = self.make_env(curl)
        self.addCleanup(tmp.cleanup)

        result = self.resolve(env, "")

        self.assertIn("CONFIG-ERROR", result.stdout)
        self.assertIn("TLS", result.stdout)
        self.assertIn("ca_bundle", result.stdout)
        self.assertIn("offline-fallback: config-error]", result.stdout)

    # -- Zero releases and zero tags -----------------------------------------

    def test_zero_releases_and_zero_tags_is_a_config_error(self) -> None:
        curl = """#!/bin/sh
for last do :; done
url=$last
case "$url" in
  */releases?per_page=100) printf '[]' ;;
  */repository/tags?per_page=100) printf '[]' ;;
  *) exit 22 ;;
esac
"""
        tmp, env, _ = self.make_env(curl)
        self.addCleanup(tmp.cleanup)

        result = self.resolve(env, "")

        self.assertIn("CONFIG-ERROR", result.stdout)
        self.assertIn("has no releases or tags", result.stdout)
        self.assertIn("~latest cannot resolve", result.stdout)
        self.assertIn("offline-fallback: config-error]", result.stdout)

    # -- 401/403 stays on its existing label (regression only) --------------

    def test_401_keeps_unauthorized_label(self) -> None:
        curl = """#!/bin/sh
case "${1:-}" in --version) echo "curl 8.0.0"; exit 0 ;; esac
has_w=0
for arg do [ "$arg" = "-w" ] && has_w=1; done
if [ "$has_w" = 1 ]; then printf '401'; exit 0; fi
exit 22
"""
        tmp, env, _ = self.make_env(curl)
        self.addCleanup(tmp.cleanup)

        result = self.resolve(env, "")

        self.assertIn("offline-fallback: unauthorized]", result.stdout)
