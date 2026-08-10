"""Base-image mirroring gap: probe it, triage it, and never let a suggestion decide.

Two failures this guards against:

1. "Rebuild on a newer base image" is useless advice on an airgapped host when
   that image is not in the internal registry. The probe has to happen and the
   verdict has to reach the finding -- which it did not, because container
   findings carry no fixed_version and were swallowed by the
   blocked_external_dependency branch before the gap branch was ever reached.
2. A hardened image is a DIFFERENT image, not a newer tag. Its availability is a
   suggestion for a human, so it must never move a finding's remediation_status
   in either direction.
"""

from __future__ import annotations

import importlib.util
import json
import os
import subprocess
import tempfile
import unittest
from pathlib import Path

SKILL_DIR = Path(__file__).resolve().parents[1]
SCRIPTS = SKILL_DIR / "scripts"

_spec = importlib.util.spec_from_file_location("normalize", SCRIPTS / "normalize.py")
normalize = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(normalize)

_spec2 = importlib.util.spec_from_file_location(
    "check_remediation", SCRIPTS / "check-remediation.py"
)
check_remediation = importlib.util.module_from_spec(_spec2)
_spec2.loader.exec_module(check_remediation)

# A container runtime that answers from the ref alone: anything from the hardened
# repo exists, everything else is missing. No registry, no network.
STUB_RUNTIME = """#!/bin/sh
printf '%s\\n' "$*" >> "$STUB_LOG"
for arg in "$@"; do
  case "$arg" in
    *hardened*) exit 0 ;;
  esac
done
echo "manifest unknown" >&2
exit 1
"""


def container_finding(severity="HIGH", fixed=None):
    evidence = {"package": "openssl", "installed_version": "3.0.8-r0"}
    if fixed:
        evidence["fixed_version"] = fixed
    return {
        "category": "container_scanning",
        "severity": severity,
        "location": {"image": "myapp:latest", "package": "openssl"},
        "evidence": evidence,
        "rule_id": "CVE-2024-0001",
    }


def dep_finding(fixed="4.17.21"):
    return {
        "category": "dependency_scanning",
        "severity": "HIGH",
        "location": {"package": "lodash"},
        "evidence": {
            "package": "lodash",
            "installed_version": "4.17.11",
            "fixed_version": fixed,
            "manifest": "package-lock.json",
        },
        "rule_id": "CVE-2020-8203",
    }


def triage(finding, availability):
    return normalize.triage_findings([json.loads(json.dumps(finding))], availability)[0]


class BaseImageTriageTest(unittest.TestCase):
    def test_absent_base_image_blocks_a_container_finding(self) -> None:
        result = triage(container_finding(), {"image|alpine|3.18": "absent"})
        self.assertEqual(result["remediation_status"], "blocked_registry_gap")
        self.assertEqual(result["verification_status"], "not_fixable_locally")
        # The reason has to name what to mirror or it is not actionable.
        self.assertIn("alpine:3.18", result["triage_reason"])

    def test_absent_wins_over_the_missing_fixed_version_branch(self) -> None:
        """The ordering bug: no fixed_version used to mask every base-image gap."""
        finding = container_finding()
        self.assertNotIn("fixed_version", finding["evidence"])
        result = triage(finding, {"image|alpine|3.18": "absent"})
        self.assertEqual(result["remediation_status"], "blocked_registry_gap")

    def test_unknown_base_image_changes_nothing(self) -> None:
        """Unreachable is not evidence of absence."""
        result = triage(container_finding(), {"image|alpine|3.18": "unknown"})
        self.assertEqual(result["remediation_status"], "blocked_external_dependency")

    def test_available_base_image_changes_nothing(self) -> None:
        result = triage(container_finding(), {"image|alpine|3.18": "available"})
        self.assertEqual(result["remediation_status"], "blocked_external_dependency")

    def test_gap_finding_still_counts_toward_the_gate(self) -> None:
        """A vulnerability you cannot fix here is still a vulnerability."""
        result = triage(container_finding(), {"image|alpine|3.18": "absent"})
        self.assertTrue(normalize.gate_failed([result], "high"))

    def test_dependency_findings_are_untouched_by_a_base_image_gap(self) -> None:
        """Ordering for dependency findings must be exactly as it was."""
        missing_fix = dep_finding()
        del missing_fix["evidence"]["fixed_version"]
        self.assertEqual(
            triage(missing_fix, {"image|alpine|3.18": "absent"})["remediation_status"],
            "blocked_external_dependency",
        )
        self.assertEqual(
            triage(dep_finding(), {"image|alpine|3.18": "absent"})["remediation_status"],
            "fixable_candidate",
        )

    def test_sast_findings_are_untouched_by_a_base_image_gap(self) -> None:
        sast = {
            "category": "sast",
            "severity": "HIGH",
            "location": {"file": "src/db.py", "line": 42},
            "evidence": {},
            "rule_id": "SQLI",
        }
        self.assertEqual(
            triage(sast, {"image|alpine|3.18": "absent"})["remediation_status"],
            "fixable_candidate",
        )

    def test_report_coverage_findings_still_win(self) -> None:
        """A scanner that did not run must never be re-labelled as a mirror gap."""
        missing = {
            "category": "container_scanning",
            "severity": "HIGH",
            "location": {},
            "evidence": {"why": "image not built"},
            "rule_id": "APPSEC-REPORT-MISSING",
        }
        self.assertEqual(
            triage(missing, {"image|alpine|3.18": "absent"})["remediation_status"],
            "parser_or_report_fix_required",
        )


class HardenedIsSuggestionOnlyTest(unittest.TestCase):
    """The single most important guarantee here: hardened verdicts decide nothing."""

    def test_hardened_absent_does_not_block(self) -> None:
        result = triage(container_finding(), {"hardened|alpine|3.18": "absent"})
        self.assertEqual(result["remediation_status"], "blocked_external_dependency")

    def test_hardened_available_does_not_unblock(self) -> None:
        result = triage(
            container_finding(),
            {"image|alpine|3.18": "absent", "hardened|alpine|3.18": "available"},
        )
        self.assertEqual(result["remediation_status"], "blocked_registry_gap")
        self.assertIn("alpine:3.18", result["triage_reason"])

    def test_hardened_only_map_is_identical_to_no_map(self) -> None:
        baseline = triage(container_finding(fixed="3.0.12-r1"), {})
        hardened = triage(
            container_finding(fixed="3.0.12-r1"),
            {"hardened|alpine|3.18": "absent", "hardened|node|20": "available"},
        )
        self.assertEqual(
            baseline["remediation_status"], hardened["remediation_status"]
        )
        self.assertEqual(baseline["triage_reason"], hardened["triage_reason"])


class ReadBaseImagesTest(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.results = Path(self.tmp.name)

    def _write(self, data) -> None:
        (self.results / "base-images.json").write_text(
            json.dumps(data), encoding="utf-8"
        )

    def test_missing_file_is_no_targets(self) -> None:
        self.assertEqual(check_remediation.read_base_images(self.results), [])

    def test_empty_list_is_no_targets(self) -> None:
        self._write([])
        self.assertEqual(check_remediation.read_base_images(self.results), [])

    def test_repeated_stage_bases_are_probed_once(self) -> None:
        self._write(
            [
                {"raw": "node:20", "image": "node", "tag": "20", "line": 1, "alias": "b"},
                {"raw": "node:20", "image": "node", "tag": "20", "line": 9, "alias": ""},
                {"raw": "alpine:3.18", "image": "alpine", "tag": "3.18", "line": 12, "alias": ""},
            ]
        )
        self.assertEqual(
            check_remediation.read_base_images(self.results),
            [("node", "20"), ("alpine", "3.18")],
        )

    def test_junk_entries_are_skipped_not_fatal(self) -> None:
        self._write(["nope", {"image": "", "tag": "3.18"}, {"image": "alpine"}])
        self.assertEqual(check_remediation.read_base_images(self.results), [])


class BaseImageProbeTest(unittest.TestCase):
    """End-to-end through resolve-base-image.sh against a stubbed runtime."""

    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.results = Path(self.tmp.name)
        self.log = self.results / "stub.log"
        runtime = self.results / "fake-runtime"
        runtime.write_text(STUB_RUNTIME, encoding="utf-8")
        runtime.chmod(0o755)

        previous = {
            key: os.environ.get(key) for key in ("CONTAINER_RUNTIME", "STUB_LOG")
        }

        def restore() -> None:
            for key, value in previous.items():
                if value is None:
                    os.environ.pop(key, None)
                else:
                    os.environ[key] = value

        self.addCleanup(restore)
        os.environ["CONTAINER_RUNTIME"] = str(runtime)
        os.environ["STUB_LOG"] = str(self.log)

        (self.results / "base-images.json").write_text(
            json.dumps(
                [{"raw": "alpine:3.18", "image": "alpine", "tag": "3.18", "line": 1, "alias": ""}]
            ),
            encoding="utf-8",
        )
        (self.results / "findings.triaged.json").write_text(
            json.dumps([container_finding()]), encoding="utf-8"
        )

    def _availability(self) -> dict:
        return json.loads(
            (self.results / "registry-availability.json").read_text(encoding="utf-8")
        )

    def test_base_repo_probe_runs_without_any_package_mirror(self) -> None:
        """Container-only projects declare no package registries; still probe."""
        rc = check_remediation.main(
            [str(self.results), "--base-repo", "reg.internal/base/{image}:{tag}"]
        )
        self.assertEqual(rc, 0)
        self.assertEqual(self._availability(), {"image|alpine|3.18": "absent"})
        self.assertIn("reg.internal/base/alpine:3.18", self.log.read_text())

    def test_hardened_verdicts_use_a_separate_key_prefix(self) -> None:
        rc = check_remediation.main(
            [
                str(self.results),
                "--base-repo",
                "reg.internal/base/{image}:{tag}",
                "--hardened-repo",
                "reg.internal/hardened/{image}:{tag}",
            ]
        )
        self.assertEqual(rc, 0)
        self.assertEqual(
            self._availability(),
            {"image|alpine|3.18": "absent", "hardened|alpine|3.18": "available"},
        )

    def test_probe_output_feeds_triage_end_to_end(self) -> None:
        check_remediation.main(
            [
                str(self.results),
                "--base-repo",
                "reg.internal/base/{image}:{tag}",
                "--hardened-repo",
                "reg.internal/hardened/{image}:{tag}",
            ]
        )
        result = triage(container_finding(), self._availability())
        self.assertEqual(result["remediation_status"], "blocked_registry_gap")
        self.assertIn("alpine:3.18", result["triage_reason"])

    def test_repo_templates_default_from_the_exported_environment(self) -> None:
        """run-scan.sh eval's load-prefs.sh, so the templates arrive as env vars."""
        os.environ["BASE_IMAGE_REPO"] = "reg.internal/base/{image}:{tag}"
        self.addCleanup(os.environ.pop, "BASE_IMAGE_REPO", None)
        self.assertEqual(check_remediation.main([str(self.results)]), 0)
        self.assertEqual(self._availability(), {"image|alpine|3.18": "absent"})

    def test_no_repos_configured_writes_an_empty_map(self) -> None:
        self.assertEqual(check_remediation.main([str(self.results)]), 0)
        self.assertEqual(self._availability(), {})
        self.assertFalse(self.log.exists())

    def test_container_findings_are_still_kept_out_of_the_package_probe(self) -> None:
        """An OS package name means nothing to npm; probing it there lies."""
        rc = check_remediation.main(
            [
                str(self.results),
                "--registries",
                json.dumps({"npm": "https://npm.internal/{package}/{version}"}),
                "--base-repo",
                "reg.internal/base/{image}:{tag}",
            ]
        )
        self.assertEqual(rc, 0)
        self.assertEqual(list(self._availability()), ["image|alpine|3.18"])


class BaseImagesJsonIsNotAScannerReportTest(unittest.TestCase):
    """base-images.json lives in .appsec-results; it must not become a finding."""

    def test_normalize_ignores_base_images_json(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            results = Path(tmp) / ".appsec-results"
            results.mkdir()
            (results / "base-images.json").write_text(
                json.dumps(
                    [{"raw": "alpine:3.18", "image": "alpine", "tag": "3.18", "line": 1, "alias": ""}]
                ),
                encoding="utf-8",
            )
            proc = subprocess.run(
                [
                    "python3",
                    str(SCRIPTS / "normalize.py"),
                    str(results),
                    "--gate",
                    "high",
                    "--ran",
                    "",
                ],
                capture_output=True,
                text=True,
            )
            findings = json.loads(
                (results / "findings.triaged.json").read_text(encoding="utf-8")
            )

        self.assertEqual(findings, [], proc.stdout)
        self.assertEqual(proc.returncode, 0, proc.stdout)


if __name__ == "__main__":
    unittest.main()
