#!/usr/bin/env python3
"""Tests for the appsec-scan skill documentation and GitLab runners."""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path


SKILL_DIR = Path(__file__).resolve().parents[1]
REPO_ROOT = SKILL_DIR.parents[3]
SKILL_MD = SKILL_DIR / "SKILL.md"
SAST_RUNNER = SKILL_DIR / "scanners" / "fortify-sast.sh"
DS_RUNNER = SKILL_DIR / "scanners" / "gitlab-dependency-scanning.sh"
CS_RUNNER = SKILL_DIR / "scanners" / "gitlab-container-scanning.sh"
RUN_SCAN = SKILL_DIR / "scripts" / "run-scan.sh"
NORMALIZE = SKILL_DIR / "scripts" / "normalize.py"
SECRET_TEMPLATE = (
    SKILL_DIR
    / "reference"
    / "catalog"
    / "lobster-thermidor"
    / "devops"
    / "ci-catalogue"
    / "secret-detection"
    / "secret-detection"
    / "1.0.0"
    / "template.yml"
)
SECRET_TEMPLATE_TEXT = SECRET_TEMPLATE.read_text(encoding="utf-8")
PUBLIC_IMAGE_MATCH = re.search(r'image:\s*"([^"]+)"', SECRET_TEMPLATE_TEXT)
if PUBLIC_IMAGE_MATCH is None:  # pragma: no cover - static shipped fixture
    raise AssertionError(f"could not derive public secret-detection image from {SECRET_TEMPLATE}")
PUBLIC_IMAGE = PUBLIC_IMAGE_MATCH.group(1)
SKILL_TEXT = SKILL_MD.read_text(encoding="utf-8")
RUN_SCAN_TEXT = RUN_SCAN.read_text(encoding="utf-8")


def run(cmd: list[str], cwd: Path, check: bool = True) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        cmd,
        cwd=str(cwd),
        check=check,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
    )


class SkillDocumentationContractTest(unittest.TestCase):
    def test_skill_contains_required_guardrails_and_contract_strings(self) -> None:
        required_strings = [
            "catalog.sh",
            "scanner-preferences.yaml",
            "TRIAGE.md",
            "Ask for approval once before making changes",
            "create a new branch",
            "run the app's relevant tests",
            "Secret Detection findings (redacted)",
            "appsec/fix-",
            "FORTIFY_SAST_IMAGE",
            "RUN_FORTIFY_SAST",
            "RUN_GITLAB_DS",
            "RUN_SECRET_DETECTION",
            "RUN_GITLAB_CS",
            "lobster-thermidor/devops/ci-catalogue/fortify-sast/fortify-sast",
        ]

        for expected in required_strings:
          with self.subTest(expected=expected):
            self.assertIn(expected, SKILL_TEXT)

        self.assertRegex(SKILL_TEXT, re.compile(r"5 iterations", re.IGNORECASE))
        self.assertRegex(
            SKILL_TEXT,
            re.compile(r"(?is)(ask(?:ing)?[\s\S]{0,250}push|push[\s\S]{0,250}ask(?:ing)?)"),
        )
        self.assertNotRegex(SKILL_TEXT, re.compile(r"glpat-[A-Za-z0-9]"))

    def test_scan_scope_routing_is_complete_and_fail_closed(self) -> None:
        """Step 0 must route every category, ask when unsure, and never let a
        scoped run read as an all-clear."""
        self.assertIn("SCAN_SCOPE", SKILL_TEXT)
        self.assertIn("AskUserQuestion", SKILL_TEXT)

        # Every category run-scan.sh accepts must be routable from Step 0,
        # otherwise a keyword request silently falls through to a full scan.
        run_scan = RUN_SCAN.read_text(encoding="utf-8")
        for category in (
            "sast",
            "dependency_scanning",
            "secret_detection",
            "container_scanning",
        ):
            with self.subTest(category=category):
                self.assertIn(category, SKILL_TEXT)
                self.assertIn(category, run_scan)

        # Asking beats guessing which scanners the user meant.
        self.assertRegex(
            SKILL_TEXT, re.compile(r"(?i)when unsure, ask|ask\b[^.]{0,40}never guess")
        )
        # A scoped scan must never be reported as clearance to push.
        self.assertRegex(
            SKILL_TEXT,
            re.compile(r"(?is)scoped[\s\S]{0,400}(not cover|did not run|full scan)"),
        )
        # --only narrows execution, not expected coverage (anti false all-clear).
        self.assertIn("never what is EXPECTED", SKILL_TEXT)

    def test_skill_documents_airgap_and_runtime_abstraction(self) -> None:
        required_strings = [
            "APPSEC_AIRGAP",
            "detect-runtime.sh",
            "resolve-jq.sh",
            "container-target.sh",
            "read_api",
            "HAS_MISSING_REPORT",
            "NOT an all-clear",
            "load-prefs.sh",
            "ENABLED_COMPONENTS",
        ]

        for expected in required_strings:
          with self.subTest(expected=expected):
            self.assertIn(expected, SKILL_TEXT)

        self.assertNotIn("IMAGE_PREFIX", SKILL_TEXT)
        self.assertNotIn("docker run --rm", SKILL_TEXT)
        self.assertNotIn("if docker pull", SKILL_TEXT)

        for expected in (
            '"$RUNTIME" run',
            # Every image pull goes through pull_image, which is the only place
            # that tells a refused credential apart from an unreachable registry.
            # Assert both halves: that the abstraction still runs the detected
            # runtime, and that secret detection still routes through it.
            'run_cmd "$RUNTIME" pull "$pull_ref"',
            'pull_image secret_detection "Secret Detection" "${SECRET_DETECTION_IMAGE}"',
            "GITLAB_FEATURES",
        ):
            with self.subTest(expected=expected):
                self.assertIn(expected, RUN_SCAN_TEXT)

    def test_normalizer_preserves_redacted_secret_summary_contract(self) -> None:
        normalizer = NORMALIZE.read_text(encoding="utf-8")

        self.assertIn("Secret Detection findings (redacted)", SKILL_TEXT)
        self.assertIn("Secret Detection findings (redacted)", normalizer)


class SkillDocTokenBudgetTest(unittest.TestCase):
    def test_skill_stays_within_host_orchestrator_token_budget(self) -> None:
        # Raised from 260/13000 in 2026-07 to fit the escalation-prefix table
        # (ADVISORY / DRIFT / CONTRACT-DRIFT / NEEDS-MAPPING). The budget exists
        # to keep this readable by a small orchestrator model; a decision table
        # that removes ambiguity earns its lines back.
        #
        # Raised again from 275/13800 in 2026-08 for Step 0 (scan-scope routing)
        # and its keyword triggers. Same rationale: the alternative is guessing
        # which scanners the user meant, and guessing wrong on a security scan
        # either wastes several minutes of container time or silently skips the
        # category they actually cared about. Routing that removes that ambiguity
        # earns its lines.
        #
        # Raised again from 310/16200 in 2026-08 for the registry-gap path: the
        # fix loop must be told to skip blocked_registry_gap findings, and
        # TRIAGE.md needs the batched mirroring table. Both are load-bearing --
        # without the skip the loop spends its 5-iteration budget on upgrades the
        # mirror cannot serve.
        #
        # Raised again from 320/17000 in 2026-08 for §3b's base-image table and
        # the hardened-image suggestion block. The warning about what a hardened
        # image actually is (different libc, no shell, non-root UID) is the whole
        # point of that block -- without it a reader treats a suggestion as an
        # upgrade and swaps a base image that cannot run the build.
        #
        # Raised from 17400 in 2026-08 for the Step 3 branching rule. `fail_on:
        # none` is documented as always exit 0, so at that threshold the exit
        # code carries NO coverage information: branching on it alone let the
        # skill report "done" over a scanner that never ran. Reading
        # coverage_complete is the only thing standing between that config and a
        # false all-clear, so the rule has to be in the file the model reads.
        # Paid for by deduplicating three restatements of "not an all-clear"
        # down to one; the remaining budget is deliberately tight.
        #
        # Raised from 330/17600 in 2026-08 for the CONFIG-ERROR: prefix and the
        # rule that a configuration error is never worked around. Tested in an
        # airgapped estate, a non-anonymous JFrog made the skill hunt for
        # alternative methods instead of stopping: this file states fourteen
        # hard-stop conditions but drew the misconfiguration-vs-environment
        # distinction zero times, while the scripts implement fifteen fallback
        # chains the docs celebrate. Faced with a 401 the model generalised from
        # those fifteen and improvised a sixteenth. The rule only works if it is
        # in the file the model actually reads. Paid for partly by cutting the
        # stale `"$RUNTIME" pull "${SECRET_DETECTION_IMAGE}"` literal (the pull
        # moved into pull_image) and tightening Step 0's rationale.
        lines = SKILL_TEXT.splitlines()

        self.assertLessEqual(len(lines), 334)
        self.assertLessEqual(len(SKILL_TEXT), 18100)


class GitlabRunnerDocTest(unittest.TestCase):
    def test_container_runner_supports_registry_and_archive_modes(self) -> None:
        text = CS_RUNNER.read_text(encoding="utf-8")
        self.assertIn("CS_SCAN_MODE", text)
        self.assertIn("gtcs", text)
        self.assertIn("--input", text)
        self.assertIn("--offline-scan", text)

    def test_runner_headers_and_component_paths_are_documented(self) -> None:
        expected_components = {
            SAST_RUNNER: "lobster-thermidor/devops/ci-catalogue/fortify-sast/fortify-sast",
            DS_RUNNER: "lobster-thermidor/devops/ci-catalogue/dependency-scanning/dependency-scanning",
            CS_RUNNER: "lobster-thermidor/devops/ci-catalogue/container-scanning/container-scanning",
        }

        for runner_path, component in expected_components.items():
            with self.subTest(runner=runner_path.name):
                text = runner_path.read_text(encoding="utf-8")
                self.assertTrue(text.startswith("#!/usr/bin/env sh"))
                self.assertIn(component, text)

        self.assertIn("FORTIFY_LANGUAGE", SAST_RUNNER.read_text(encoding="utf-8"))
        self.assertIn("/analyzer run", DS_RUNNER.read_text(encoding="utf-8"))
        self.assertIn("gtcs scan", CS_RUNNER.read_text(encoding="utf-8"))

    def test_dependency_scanning_runner_documents_exit_2_and_features_flag(self) -> None:
        text = DS_RUNNER.read_text(encoding="utf-8")

        self.assertIn("exit 2", text)
        self.assertIn("GITLAB_FEATURES", text)


@unittest.skipUnless(
    os.environ.get("RUN_GITLAB_SAST_SMOKE") == "1",
    "set RUN_GITLAB_SAST_SMOKE=1 to pull and run the public analyzer image",
)
class GitlabSastSmokeTest(unittest.TestCase):
    image = os.environ.get("GITLAB_SAST_SMOKE_IMAGE", PUBLIC_IMAGE)

    @classmethod
    def setUpClass(cls) -> None:
        if shutil.which("docker") is None:
            raise unittest.SkipTest("docker is not installed")
        run(["docker", "pull", cls.image], cwd=REPO_ROOT)

    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory(prefix="appsec-fortify-sast-")
        self.repo = Path(self.tmp.name)
        run(["git", "init", "-b", "main"], cwd=self.repo)
        run(["git", "config", "user.email", "appsec-test@example.invalid"], cwd=self.repo)
        run(["git", "config", "user.name", "AppSec Smoke Test"], cwd=self.repo)
        (self.repo / "app.py").write_text(
            'import os\n\n'
            'eval(os.environ.get("X", ""))\n',
            encoding="utf-8",
        )
        run(["git", "add", "app.py"], cwd=self.repo)
        run(["git", "commit", "-m", "add eval fixture"], cwd=self.repo)

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def test_scanner_produces_output_file(self) -> None:
        run(
            [
                "docker",
                "run",
                "--rm",
                "--entrypoint",
                "",
                "-v",
                f"{self.repo}:/workspace",
                "-v",
                f"{SAST_RUNNER}:/runner.sh:ro",
                "-w",
                "/workspace",
                "-e",
                "CI_PROJECT_DIR=/workspace",
                "-e",
                "FORTIFY_LANGUAGE=python",
                self.image,
                "sh",
                "/runner.sh",
            ],
            cwd=REPO_ROOT,
        )

        report_path = self.repo / ".appsec-results" / "fortify-sast.fpr"
        self.assertTrue(report_path.exists(), "expected fortify-sast.fpr")
        self.assertGreater(report_path.stat().st_size, 0)


if __name__ == "__main__":
    unittest.main()


class ShellContractTest(unittest.TestCase):
    """SKILL.md snippets run on hosts whose default shell is zsh."""

    def test_no_unquoted_word_split_loops(self) -> None:
        # `for x in $VAR` word-splits in bash but NOT in zsh (macOS default).
        # The old Step 2.5 loop silently resolved 1 of 4 components and fed the
        # remainder into check-drift as an image arg, producing a bogus DRIFT
        # line. Iteration over emitted lists belongs in a bash script.
        offenders = [
            line.strip() for line in SKILL_TEXT.splitlines()
            if re.search(r"^\s*for\s+\w+\s+in\s+\$[A-Za-z_]", line)
        ]
        self.assertEqual(offenders, [], f"unquoted word-split loop in SKILL.md: {offenders}")

    def test_does_not_derive_skill_dir_from_bash_source(self) -> None:
        # BASH_SOURCE/$0 resolve to the agent's shell, not to SKILL.md, and
        # produced SKILL_DIR=/bin. Prose may warn about it; runnable code may not
        # use it.
        in_fence, offenders = False, []
        for line in SKILL_TEXT.splitlines():
            if line.startswith("```"):
                in_fence = not in_fence
                continue
            if in_fence and "BASH_SOURCE" in line:
                offenders.append(line.strip())
        self.assertEqual(offenders, [], f"BASH_SOURCE used in a SKILL.md snippet: {offenders}")

    def test_states_the_shell_contract(self) -> None:
        self.assertIn("Shell contract", SKILL_TEXT)
        self.assertIn("zsh", SKILL_TEXT)
