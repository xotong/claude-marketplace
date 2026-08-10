#!/usr/bin/env python3
"""Tests for the appsec-scan scanner preference configuration (v2 schema)."""

from __future__ import annotations

import os
import shutil
import subprocess
import tempfile
import time
import unittest
from pathlib import Path

try:
    import yaml
except ImportError as exc:  # pragma: no cover - environment dependent
    raise unittest.SkipTest("pyyaml not installed - pip install pyyaml") from exc


SKILL_DIR = Path(__file__).resolve().parents[1]
PREFERENCES_PATH = SKILL_DIR / "config" / "scanner-preferences.yaml"
SCANNERS_DIR = SKILL_DIR / "scanners"
SCRIPTS_DIR = SKILL_DIR / "scripts"
EXPECTED_CATEGORIES = {
    "sast",
    "dependency_scanning",
    "secret_detection",
    "container_scanning",
}

with PREFERENCES_PATH.open("r", encoding="utf-8") as fh:
    PREFERENCES = yaml.safe_load(fh)


class SettingsBlockTest(unittest.TestCase):
    def setUp(self) -> None:
        self.settings = PREFERENCES.get("settings", {})

    def test_settings_block_present(self) -> None:
        self.assertIsInstance(self.settings, dict)

    def test_airgap_is_boolean(self) -> None:
        self.assertIn("airgap", self.settings)
        self.assertIsInstance(self.settings["airgap"], bool)

    def test_container_runtime_valid(self) -> None:
        self.assertIn(self.settings.get("container_runtime"), {"auto", "docker", "podman"})


    def test_tooling_gate_and_container_registry_keys(self) -> None:
        self.assertIn("install_url", self.settings.get("jq", {}))
        self.assertIn("install_url", self.settings.get("python", {}))
        self.assertIn(
            self.settings.get("ci_gate", {}).get("fail_on"),
            {"critical", "high", "medium", "none"},
        )
        cr = self.settings.get("container_registry", {})
        self.assertIn("user_env", cr)
        self.assertIn("password_env", cr)

    def test_airgap_knobs_exist_and_ship_disabled(self) -> None:
        """ca_bundle / pip_index_url / maven_settings must be declarable, and must
        default to off — nothing may be mounted or rewritten unless an admin says so."""
        for key in ("ca_bundle", "pip_index_url", "maven_settings"):
            with self.subTest(key=key):
                self.assertIn(key, self.settings, "airgap estates have no other way in")
                self.assertIsInstance(self.settings[key], str)
                self.assertEqual(self.settings[key], "", "shipped default must disable it")

    def test_global_base_image_templates_exist_and_ship_empty(self) -> None:
        """They live inside container_registry, which already holds this
        registry's credential env-var names — not in a new top-level block."""
        cr = self.settings.get("container_registry", {})
        for key in ("base_repo", "hardened_repo"):
            with self.subTest(key=key):
                self.assertIn(key, cr)
                self.assertIsInstance(cr[key], str)
                self.assertEqual(cr[key], "", "no probing by default")

    def test_the_two_base_image_templates_state_their_differing_contracts(self) -> None:
        """A hardened image is a DIFFERENT image, not a newer tag. Without this
        warning in the file the next maintainer wires hardened_repo into the
        triage branch and the fix loop starts 'fixing' builds by breaking them."""
        text = PREFERENCES_PATH.read_text(encoding="utf-8")
        self.assertIn("ONLY one of the two that may change a finding's status", text)
        self.assertIn("SUGGESTION-ONLY", text)
        self.assertIn("fix loop must NEVER apply it", text)


class ScannerPreferencesTest(unittest.TestCase):
    def test_default_profile_is_catalog(self) -> None:
        self.assertEqual(PREFERENCES.get("default_profile"), "catalog")
        self.assertIn("catalog", PREFERENCES.get("profiles", {}))

    def test_every_profile_has_expected_categories(self) -> None:
        for profile_name, profile in PREFERENCES["profiles"].items():
            with self.subTest(profile=profile_name):
                self.assertEqual(set(profile.get("categories", {})), EXPECTED_CATEGORIES)

    def test_category_requires_component_version_enabled(self) -> None:
        """image: and runner: are optional overrides; the other three are not."""
        required = {"component", "version", "enabled"}
        optional = {"image", "runner"}
        for profile_name, profile in PREFERENCES["profiles"].items():
            for category_name, category in profile["categories"].items():
                with self.subTest(profile=profile_name, category=category_name):
                    keys = set(category)
                    self.assertTrue(required <= keys, f"missing {required - keys}")
                    self.assertFalse(keys - required - optional, "unknown keys present")
                    self.assertIsInstance(category["component"], str)
                    self.assertGreaterEqual(category["component"].count("/"), 2)
                    self.assertIsInstance(category["version"], str)
                    self.assertTrue(category["version"])
                    self.assertIsInstance(category["enabled"], bool)

    def test_declared_runner_must_exist(self) -> None:
        """An omitted runner defaults to the shipped one; a declared one must be real."""
        for profile_name, profile in PREFERENCES["profiles"].items():
            for category_name, category in profile["categories"].items():
                runner = category.get("runner")
                if not runner or runner == "none":
                    continue
                with self.subTest(profile=profile_name, category=category_name, runner=runner):
                    self.assertTrue((SCANNERS_DIR / runner).is_file())

    def test_every_category_resolves_a_runner(self) -> None:
        """Omitting runner: must not leave a category unable to run."""
        defaults = {
            "sast": "fortify-sast.sh",
            "dependency_scanning": "gitlab-dependency-scanning.sh",
            "secret_detection": "secret-detection.sh",
            "container_scanning": "gitlab-container-scanning.sh",
        }
        for profile_name, profile in PREFERENCES["profiles"].items():
            for category_name, category in profile["categories"].items():
                resolved = category.get("runner") or defaults.get(category_name)
                with self.subTest(profile=profile_name, category=category_name):
                    self.assertIsNotNone(resolved, "no runner and no default")
                    self.assertTrue((SCANNERS_DIR / resolved).is_file())

    def test_omitted_image_is_derivable_from_the_component(self) -> None:
        """A category may omit image: only if the template supplies one."""
        import subprocess

        for profile_name, profile in PREFERENCES["profiles"].items():
            for category_name, category in profile["categories"].items():
                if category.get("image") or not category["enabled"]:
                    continue
                with self.subTest(profile=profile_name, category=category_name):
                    proc = subprocess.run(
                        [
                            "bash",
                            str(SCANNERS_DIR.parent / "scripts" / "catalog.sh"),
                            "template-image",
                            category["component"],
                            "/nonexistent-cache-dir",
                        ],
                        capture_output=True,
                        text=True,
                        cwd=str(SCANNERS_DIR.parent),
                        check=True,
                    )
                    self.assertTrue(
                        proc.stdout.strip(),
                        f"{category_name} omits image: but its template declares none",
                    )

    def test_catalog_profile_targets_gitlab_com(self) -> None:
        self.assertEqual(
            PREFERENCES["profiles"]["catalog"]["gitlab_instance"], "https://gitlab.com"
        )

    def test_catalog_and_company_profiles_exist(self) -> None:
        self.assertIn("catalog", PREFERENCES["profiles"])
        self.assertIn("company", PREFERENCES["profiles"])

    def test_catalog_profile_ships_public_base_image_templates(self) -> None:
        """Real public values, so an internet-connected run exercises the same
        probe code path an airgapped estate uses instead of leaving it dead."""
        catalog = PREFERENCES["profiles"]["catalog"]
        self.assertEqual(catalog["base_repo"], "docker.io/library/{image}:{tag}")
        self.assertEqual(catalog["hardened_repo"], "cgr.dev/chainguard/{image}:{tag}")

    def test_company_profile_declares_no_base_image_templates(self) -> None:
        """The internal registry layout is the admin's to paste in; guessing it
        would probe the wrong path and report 'absent' for images that exist."""
        company = PREFERENCES["profiles"]["company"]
        self.assertNotIn("base_repo", company)
        self.assertNotIn("hardened_repo", company)

    def test_every_declared_base_image_template_is_a_ref_template(self) -> None:
        """These are refs with {image} and {tag}, not base URLs — a pasted base
        URL would silently probe one wrong path for every image."""
        declared = [
            ("settings", key, PREFERENCES["settings"]["container_registry"][key])
            for key in ("base_repo", "hardened_repo")
        ] + [
            (name, key, profile[key])
            for name, profile in PREFERENCES["profiles"].items()
            for key in ("base_repo", "hardened_repo")
            if key in profile
        ]
        for where, key, value in declared:
            if not value:
                continue
            with self.subTest(where=where, key=key):
                self.assertIn("{image}", value)
                self.assertIn("{tag}", value)

    def test_no_hummingbird_registry_is_invented(self) -> None:
        """Its registry/namespace is unconfirmed. A guessed URL probes as
        'absent' and manufactures mirroring work for the platform team, which is
        strictly worse than leaving the shape for the admin to paste."""
        text = PREFERENCES_PATH.read_text(encoding="utf-8")
        self.assertIn("Hummingbird", text, "the gap should be named, not silently omitted")
        self.assertIn("unconfirmed", text)
        for invented in ("hummingbird.io", "hummingbird.dev", "hmb.dev", "ghcr.io/hummingbird"):
            with self.subTest(invented=invented):
                self.assertNotIn(invented, text)


class HelperScriptsTest(unittest.TestCase):
    """The airgap helper scripts must exist, be executable, and behave sanely."""

    def make_stub_dir(self, tmp: str, scripts: dict[str, str]) -> Path:
        bin_dir = Path(tmp) / "bin"
        bin_dir.mkdir()
        for name, body in scripts.items():
            path = bin_dir / name
            path.write_text(body, encoding="utf-8")
            path.chmod(0o755)
        return bin_dir

    def add_passthrough_tools(self, bin_dir: Path, tool_names: list[str]) -> None:
        for tool_name in tool_names:
            tool_path = shutil.which(tool_name)
            if tool_path is None:
                self.fail(f"required tool {tool_name} not found on host PATH")
            link_path = bin_dir / tool_name
            if not link_path.exists():
                link_path.symlink_to(tool_path)

    def run_script(
        self,
        script_name: str,
        *,
        env: dict[str, str] | None = None,
        cwd: str | None = None,
        args: list[str] | None = None,
    ) -> subprocess.CompletedProcess[str]:
        bash = shutil.which("bash") or "/bin/bash"
        return subprocess.run(
            [bash, str(SCRIPTS_DIR / script_name), *(args or [])],
            env=env,
            cwd=cwd,
            capture_output=True,
            text=True,
        )

    def test_helper_scripts_present_and_executable(self) -> None:
        for name in (
            "detect-runtime.sh",
            "resolve-jq.sh",
            "container-target.sh",
            "catalog.sh",
            "run-scan.sh",
            "resolve-python.sh",
            "fix-branch.sh",
        ):
            path = SCRIPTS_DIR / name
            with self.subTest(script=name):
                self.assertTrue(path.is_file(), f"{name} missing")
                self.assertTrue(os.access(path, os.X_OK), f"{name} not executable")

    def test_detect_runtime_errors_when_forced_missing(self) -> None:
        # Forcing a bogus runtime must fail cleanly (non-zero), not crash.
        env = dict(os.environ, CONTAINER_RUNTIME="podman")
        # If podman is genuinely installed this returns it; either way exit code is defined.
        result = subprocess.run(
            ["bash", str(SCRIPTS_DIR / "detect-runtime.sh")],
            env=env, capture_output=True, text=True,
        )
        self.assertIn(result.returncode, (0, 1))
        if result.returncode == 0:
            self.assertEqual(result.stdout.strip(), "podman")

    def test_resolve_jq_degrades_without_url(self) -> None:
        # jq absent (empty PATH) and no install_url → exit 0, print nothing.
        # Launch bash by absolute path so an empty PATH only hides jq, not bash.
        env = dict(os.environ, PATH="", JQ_INSTALL_URL="")
        result = self.run_script("resolve-jq.sh", env=env)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.strip(), "")

    def test_detect_runtime_errors_when_auto_finds_no_runtime(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            env = dict(os.environ, PATH=tmp, CONTAINER_RUNTIME="auto")
            result = self.run_script("detect-runtime.sh", env=env)

        self.assertEqual(result.returncode, 1)
        self.assertEqual(result.stdout.strip(), "")
        self.assertIn("no container runtime found", result.stderr)

    def test_detect_runtime_rejects_invalid_forced_value(self) -> None:
        # Contract: invalid values do not fall back to auto-detection; they hard-fail.
        env = dict(os.environ, CONTAINER_RUNTIME="bogus")
        result = self.run_script("detect-runtime.sh", env=env)

        self.assertEqual(result.returncode, 1)
        self.assertEqual(result.stdout.strip(), "")
        self.assertIn("unsupported CONTAINER_RUNTIME 'bogus'", result.stderr)

    def test_preflight_allows_unset_gitlab_instance_under_set_u(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            bin_dir = self.make_stub_dir(
                tmp,
                {"docker": "#!/bin/sh\nexit 0\n"},
            )
            env = dict(
                os.environ,
                APPSEC_AIRGAP="true",
                CONTAINER_RUNTIME="auto",
                PATH=f"{bin_dir}{os.pathsep}{os.environ.get('PATH', '')}",
            )
            env.pop("GITLAB_INSTANCE", None)
            result = subprocess.run(
                ["bash", str(SCANNERS_DIR / "preflight.sh")],
                env=env,
                capture_output=True,
                text=True,
            )

        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertNotIn("unbound variable", result.stderr)

    def test_preflight_catalog_auth_required_whenever_named(self) -> None:
        # catalog.mode was removed; resolution is always attempted online, so a
        # named-but-unset token var is always a hard failure. Profiles on
        # anonymous instances set auth_token_env: "" instead.
        with tempfile.TemporaryDirectory() as tmp:
            bin_dir = self.make_stub_dir(tmp, {"docker": "#!/bin/sh\nexit 0\n"})
            env = dict(
                os.environ,
                CATALOG_AUTH_ENV="APPSEC_TEST_PAT",
                CONTAINER_RUNTIME="auto",
                PATH=f"{bin_dir}{os.pathsep}{os.environ.get('PATH', '')}",
            )
            env.pop("APPSEC_TEST_PAT", None)
            named_unset = subprocess.run(
                ["bash", str(SCANNERS_DIR / "preflight.sh")],
                env=env, capture_output=True, text=True,
            )
            env["CATALOG_AUTH_ENV"] = ""
            anonymous = subprocess.run(
                ["bash", str(SCANNERS_DIR / "preflight.sh")],
                env=env, capture_output=True, text=True,
            )

        self.assertEqual(named_unset.returncode, 1)
        self.assertIn("APPSEC_TEST_PAT", named_unset.stdout)
        self.assertEqual(
            anonymous.returncode, 0,
            anonymous.stdout + anonymous.stderr,
        )

    def test_resolve_jq_returns_existing_jq_path(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            bin_dir = self.make_stub_dir(
                tmp,
                {
                    "jq": "#!/bin/sh\nexit 0\n",
                },
            )
            env = dict(os.environ, PATH=str(bin_dir))
            result = self.run_script("resolve-jq.sh", env=env)

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertTrue(result.stdout.strip().endswith("/jq"))
        self.assertEqual(result.stdout.strip(), str(bin_dir / "jq"))

    def test_resolve_jq_warns_and_degrades_when_download_fails(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            bin_dir = self.make_stub_dir(
                tmp,
                {
                    "curl": "#!/bin/sh\nexit 7\n",
                    "uname": "#!/bin/sh\nexec /usr/bin/uname \"$@\"\n",
                    "tr": "#!/bin/sh\nexec /usr/bin/tr \"$@\"\n",
                    "mkdir": "#!/bin/sh\nexec /bin/mkdir \"$@\"\n",
                    "chmod": "#!/bin/sh\nexec /bin/chmod \"$@\"\n",
                },
            )
            env = dict(
                os.environ,
                PATH=str(bin_dir),
                APPSEC_RESULTS_DIR=str(Path(tmp) / "results"),
                JQ_INSTALL_URL="https://example.invalid/{os}/{arch}/jq",
            )
            result = self.run_script("resolve-jq.sh", env=env)

        self.assertEqual(result.returncode, 0)
        self.assertEqual(result.stdout.strip(), "")
        self.assertIn("WARNING: failed to download jq", result.stderr)

    def test_container_target_defers_when_no_image_no_dockerfile(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            env = dict(os.environ, CS_IMAGE="")
            result = self.run_script(
                "container-target.sh",
                cwd=tmp,
                env=env,
                args=["docker", "app", ".appsec-results"],
            )
            self.assertEqual(result.returncode, 0)
            self.assertEqual(result.stdout.strip(), "none|")

    def test_container_target_uses_cs_image_when_set(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            env = dict(os.environ, CS_IMAGE="jfrog.internal/app:1.2.3")
            result = self.run_script(
                "container-target.sh",
                cwd=tmp,
                env=env,
                args=["docker", "app", ".appsec-results"],
            )
            self.assertEqual(result.returncode, 0)
            self.assertEqual(result.stdout.strip(), "registry|jfrog.internal/app:1.2.3")

    def test_container_target_reports_build_failure_for_top_level_dockerfile(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            project_dir = Path(tmp)
            (project_dir / "Dockerfile").write_text("FROM scratch\n", encoding="utf-8")
            runtime_log = project_dir / "runtime.log"
            bin_dir = self.make_stub_dir(
                tmp,
                {
                    "fake-runtime": (
                        "#!/bin/sh\n"
                        "printf '%s\\n' \"$*\" >> \"$RUNTIME_LOG\"\n"
                        "if [ \"$1\" = \"build\" ]; then\n"
                        "  echo 'build failed' >&2\n"
                        "  exit 1\n"
                        "fi\n"
                        "exit 0\n"
                    ),
                },
            )
            self.add_passthrough_tools(bin_dir, ["mkdir", "dirname", "grep", "cat"])
            env = dict(os.environ, PATH=str(bin_dir), RUNTIME_LOG=str(runtime_log))
            result = self.run_script(
                "container-target.sh",
                cwd=tmp,
                env=env,
                args=["fake-runtime", "sample-app", str(project_dir / ".appsec-results")],
            )

            build_log = project_dir / ".appsec-results" / "container-build.log"
            self.assertEqual(result.returncode, 3)
            self.assertEqual(result.stdout.strip(), "error|build")
            self.assertIn("Container image build failed", result.stderr)
            self.assertIn(f"see {build_log}", result.stderr)
            self.assertTrue(build_log.is_file())
            self.assertIn("build -t appsec-local/sample-app:appsec-scan -f ./Dockerfile .", runtime_log.read_text(encoding="utf-8"))

    def test_container_target_discovers_nested_dockerfile_and_reports_build_failure(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            project_dir = Path(tmp)
            nested_dir = project_dir / "service"
            nested_dir.mkdir()
            (nested_dir / "Dockerfile").write_text("FROM scratch\n", encoding="utf-8")
            runtime_log = project_dir / "runtime.log"
            bin_dir = self.make_stub_dir(
                tmp,
                {
                    "fake-runtime": (
                        "#!/bin/sh\n"
                        "printf '%s\\n' \"$*\" >> \"$RUNTIME_LOG\"\n"
                        "if [ \"$1\" = \"build\" ]; then\n"
                        "  exit 1\n"
                        "fi\n"
                        "exit 0\n"
                    ),
                },
            )
            self.add_passthrough_tools(bin_dir, ["mkdir", "find", "dirname", "grep", "cat"])
            env = dict(os.environ, PATH=str(bin_dir), RUNTIME_LOG=str(runtime_log))
            result = self.run_script(
                "container-target.sh",
                cwd=tmp,
                env=env,
                args=["fake-runtime", "sample-app", str(project_dir / ".appsec-results")],
            )

            self.assertEqual(result.returncode, 3)
            self.assertEqual(result.stdout.strip(), "error|build")
            self.assertIn(
                "build -t appsec-local/sample-app:appsec-scan -f ./service/Dockerfile ./service",
                runtime_log.read_text(encoding="utf-8"),
            )

    # The sandbox above used to stop at container-target.sh. That gap is exactly
    # how resolve-image.sh shipped calling `cut` unguarded: on a host without
    # coreutils it exited 127, and run-scan.sh reads a non-zero exit from it as
    # fatal and refuses to scan at all. The probe helpers get the same treatment.

    def test_resolve_image_resolves_without_coreutils(self) -> None:
        cases = [
            # Adopt the component's tag, keep the configured registry.
            (
                ("jfrog.internal/security/cs:8", "registry.gitlab.com/sp/cs:8.6.31"),
                "jfrog.internal/security/cs:8.6.31",
            ),
            # A port in the registry host is not a tag.
            (
                ("registry:5000/security/cs", "registry.gitlab.com/sp/cs:8.6.31"),
                "registry:5000/security/cs:8.6.31",
            ),
            # Untagged template: nothing to follow.
            (
                ("registry:5000/security/cs:8", "registry.gitlab.com/sp/cs"),
                "registry:5000/security/cs:8",
            ),
        ]
        with tempfile.TemporaryDirectory() as tmp:
            bin_dir = self.make_stub_dir(tmp, {"fake-runtime": "#!/bin/sh\nexit 0\n"})
            env = dict(os.environ, PATH=str(bin_dir))
            for (configured, template), expected in cases:
                with self.subTest(configured=configured):
                    result = self.run_script(
                        "resolve-image.sh",
                        env=env,
                        args=[configured, template, "fake-runtime", "follow-component", "no-pull"],
                    )
                    self.assertEqual(result.returncode, 0, result.stderr)
                    self.assertEqual(result.stdout.strip(), expected)

    def test_resolve_base_image_verdicts_without_coreutils(self) -> None:
        # `absent` must come from the registry's own wording, never from a helper
        # that failed to launch.
        with tempfile.TemporaryDirectory() as tmp:
            bin_dir = self.make_stub_dir(
                tmp,
                {"fake-runtime": "#!/bin/sh\necho 'manifest unknown' >&2\nexit 1\n"},
            )
            env = dict(os.environ, PATH=str(bin_dir))
            absent = self.run_script(
                "resolve-base-image.sh",
                env=env,
                args=["alpine", "3.19", "jfrog.internal/{image}:{tag}", "fake-runtime"],
            )

        with tempfile.TemporaryDirectory() as tmp:
            empty_bin = self.make_stub_dir(tmp, {})
            env = dict(os.environ, PATH=str(empty_bin))
            no_runtime = self.run_script(
                "resolve-base-image.sh",
                env=env,
                args=["alpine", "3.19", "jfrog.internal/{image}:{tag}", "auto"],
            )

        self.assertEqual((absent.returncode, absent.stdout.strip()), (0, "absent"), absent.stderr)
        self.assertEqual(
            (no_runtime.returncode, no_runtime.stdout.strip()), (0, "unknown"), no_runtime.stderr
        )

    def test_sbom_vuln_scan_without_sboms_is_not_an_error(self) -> None:
        # No lockfile means no SBOM, which is not a failure — and must not become
        # one just because the userland is thin either.
        with tempfile.TemporaryDirectory() as tmp:
            bin_dir = self.make_stub_dir(tmp, {})
            self.add_passthrough_tools(bin_dir, ["mkdir", "rm"])
            env = dict(os.environ, PATH=str(bin_dir), CI_PROJECT_DIR=tmp)
            result = subprocess.run(
                [shutil.which("bash") or "/bin/bash", str(SCANNERS_DIR / "sbom-vuln-scan.sh")],
                env=env, capture_output=True, text=True,
            )
            produced = list((Path(tmp) / ".appsec-results").glob("dependency-sbom-scan*.json"))

        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(produced, [])


if __name__ == "__main__":
    unittest.main()


class RuntimeDaemonProbeTest(HelperScriptsTest):
    """Binary presence is not a usable environment."""

    def test_require_daemon_fails_fast_on_wedged_runtime(self) -> None:
        # A wedged Docker Desktop makes `docker info` hang forever, and macOS
        # has no timeout(1) — the probe must bound itself.
        with tempfile.TemporaryDirectory() as tmp:
            bin_dir = self.make_stub_dir(tmp, {"docker": "#!/bin/sh\nsleep 300\n"})
            env = dict(
                os.environ,
                PATH=f"{bin_dir}{os.pathsep}{os.environ.get('PATH', '')}",
                CONTAINER_RUNTIME="docker",
                APPSEC_RUNTIME_PROBE_TIMEOUT="2",
            )
            start = time.monotonic()
            result = subprocess.run(
                ["bash", str(SCRIPTS_DIR / "detect-runtime.sh"), "--require-daemon"],
                env=env, capture_output=True, text=True,
            )
            elapsed = time.monotonic() - start

        self.assertEqual(result.returncode, 1)
        self.assertIn("daemon is not responding", result.stderr)
        self.assertLess(elapsed, 30, "probe did not bound itself")

    def test_without_flag_binary_presence_is_enough(self) -> None:
        # --dry-run must keep working with no daemon.
        with tempfile.TemporaryDirectory() as tmp:
            bin_dir = self.make_stub_dir(tmp, {"docker": "#!/bin/sh\nsleep 300\n"})
            env = dict(
                os.environ,
                PATH=f"{bin_dir}{os.pathsep}{os.environ.get('PATH', '')}",
                CONTAINER_RUNTIME="docker",
            )
            result = subprocess.run(
                ["bash", str(SCRIPTS_DIR / "detect-runtime.sh")],
                env=env, capture_output=True, text=True,
            )

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.strip(), "docker")
