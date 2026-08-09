"""Regression coverage for offline Trivy scans of GitLab dependency SBOMs."""

from __future__ import annotations

import importlib.util
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest import mock


SKILL_DIR = Path(__file__).resolve().parents[1]
RUNNER = SKILL_DIR / "scanners" / "sbom-vuln-scan.sh"
SCRIPTS = SKILL_DIR / "scripts"


def load_script_module(name: str, filename: str):
    spec = importlib.util.spec_from_file_location(name, SCRIPTS / filename)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


normalize = load_script_module("normalize_sbom_tests", "normalize.py")
check_remediation = load_script_module(
    "check_remediation_sbom_tests", "check-remediation.py"
)


def trivy_report(result_type="node-pkg"):
    return {
        "Results": [
            {
                "Target": "Node.js",
                "Type": result_type,
                "Vulnerabilities": [
                    {
                        "VulnerabilityID": "CVE-2019-10744",
                        "Title": "Prototype pollution",
                        "Severity": "CRITICAL",
                        "PkgName": "lodash",
                        "InstalledVersion": "4.17.11",
                        "FixedVersion": "4.17.12",
                    }
                ],
            }
        ]
    }


class NormalizeSbomTrivyTest(unittest.TestCase):
    def test_dependency_report_uses_package_location_and_ecosystem(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "dependency-sbom-scan-npm-npm.json"
            path.write_text(json.dumps(trivy_report()), encoding="utf-8")

            findings = normalize.normalize_reports(tmp)

        self.assertEqual(len(findings), 1)
        finding = findings[0]
        self.assertEqual(finding["category"], "dependency_scanning")
        self.assertEqual(finding["scanner"], "trivy")
        self.assertEqual(finding["location"], {"package": "lodash"})
        self.assertEqual(finding["evidence"]["package"], "lodash")
        self.assertEqual(finding["evidence"]["fixed_version"], "4.17.12")
        self.assertEqual(finding["evidence"]["ecosystem"], "npm")

    def test_container_archive_remains_container_scanning(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "container-scan-archive.json"
            path.write_text(json.dumps(trivy_report()), encoding="utf-8")

            findings = normalize.normalize_reports(tmp)

        self.assertEqual(findings[0]["category"], "container_scanning")
        self.assertEqual(findings[0]["location"], {"image": "Node.js"})

    def test_all_trivy_result_types_map_to_registry_ecosystems(self):
        expected = {
            "node-pkg": "npm",
            "python-pkg": "pypi",
            "gobinary": "go",
            "gomod": "go",
            "jar": "maven",
            "pom": "maven",
            "gradle": "maven",
            "gemspec": "rubygems",
        }
        for result_type, ecosystem in expected.items():
            with self.subTest(result_type=result_type):
                findings = normalize.parse_generic_json(
                    "dependency-sbom-scan.json", trivy_report(result_type)
                )
                self.assertEqual(findings[0]["evidence"]["ecosystem"], ecosystem)


class RemediationSbomTrivyTest(unittest.TestCase):
    @staticmethod
    def finding(fixed="1.2.6, 0.2.4"):
        return {
            "category": "dependency_scanning",
            "location": {"package": "example-package"},
            "evidence": {
                "package": "example-package",
                "fixed_version": fixed,
                "ecosystem": "npm",
            },
        }

    def test_evidence_ecosystem_precedes_manifest_fallback(self):
        finding = self.finding()
        finding["evidence"]["manifest"] = "requirements.txt"
        self.assertEqual(check_remediation.infer_ecosystem(finding), "npm")

    def test_sbom_finding_without_manifest_is_collected(self):
        self.assertEqual(
            check_remediation.collect_targets([self.finding()]),
            {
                "npm|example-package|1.2.6, 0.2.4": (
                    "npm",
                    "example-package",
                    "1.2.6, 0.2.4",
                )
            },
        )

    def test_comma_separated_versions_are_aggregated(self):
        cases = (
            (["absent", "available"], "available"),
            (["absent", "absent"], "absent"),
            (["absent", "unknown"], "unknown"),
        )
        for probe_results, expected in cases:
            with self.subTest(probe_results=probe_results):
                with tempfile.TemporaryDirectory() as tmp:
                    results = Path(tmp)
                    (results / "findings.triaged.json").write_text(
                        json.dumps([self.finding()]), encoding="utf-8"
                    )
                    with mock.patch.object(
                        check_remediation, "probe", side_effect=probe_results
                    ) as probe:
                        rc = check_remediation.main(
                            [
                                str(results),
                                "--registries",
                                json.dumps({"npm": "https://mirror/{package}/{version}"}),
                            ]
                        )

                    availability = json.loads(
                        (results / "registry-availability.json").read_text(
                            encoding="utf-8"
                        )
                    )

                self.assertEqual(rc, 0)
                self.assertEqual(
                    availability,
                    {"npm|example-package|1.2.6, 0.2.4": expected},
                )
                self.assertEqual(
                    [call.args[2] for call in probe.call_args_list],
                    ["1.2.6", "0.2.4"],
                )

    def test_sbom_registry_gap_is_applied_by_normalizer(self):
        finding = normalize.new_finding(
            "trivy",
            "Prototype pollution",
            "HIGH",
            {"package": "lodash"},
            {
                "package": "lodash",
                "fixed_version": "4.17.12",
                "ecosystem": "npm",
            },
            category="dependency_scanning",
            rule_id="CVE-2019-10744",
        )
        normalize.triage_findings(
            [finding], {"npm|lodash|4.17.12": "absent"}
        )
        self.assertEqual(finding["remediation_status"], "blocked_registry_gap")


class SbomRunnerTest(unittest.TestCase):
    def run_runner(self, project: Path, **extra_env):
        env = {
            **os.environ,
            "CI_PROJECT_DIR": str(project),
            **extra_env,
        }
        return subprocess.run(
            ["/bin/sh", str(RUNNER)],
            capture_output=True,
            text=True,
            env=env,
        )

    def test_no_sbom_succeeds_without_trivy_or_output(self):
        with tempfile.TemporaryDirectory() as tmp:
            results = Path(tmp) / ".appsec-results"
            results.mkdir()
            (results / "dependency-sbom-scan-stale.json").write_text(
                "{}", encoding="utf-8"
            )

            proc = self.run_runner(Path(tmp))

            self.assertEqual(proc.returncode, 0, proc.stderr)
            self.assertEqual(list(results.glob("dependency-sbom-scan*.json")), [])

    def test_each_sbom_gets_a_distinct_offline_report(self):
        with tempfile.TemporaryDirectory() as tmp:
            project = Path(tmp)
            results = project / ".appsec-results"
            results.mkdir()
            for name in ("gl-sbom-npm-npm.cdx.json", "gl-sbom-pypi-pip.cdx.json"):
                (results / name).write_text("{}", encoding="utf-8")

            fake_trivy = project / "fake-trivy"
            call_log = project / "trivy-calls.log"
            fake_trivy.write_text(
                "#!/bin/sh\n"
                "output=\n"
                "for arg do\n"
                "  if [ \"${previous:-}\" = -o ]; then output=$arg; fi\n"
                "  printf '%s\\n' \"$arg\" >> \"$TRIVY_CALL_LOG\"\n"
                "  previous=$arg\n"
                "done\n"
                "printf '{\\\"Results\\\": []}\\n' > \"$output\"\n",
                encoding="utf-8",
            )
            fake_trivy.chmod(0o755)

            proc = self.run_runner(
                project,
                SBOM_TRIVY_BIN=str(fake_trivy),
                SBOM_TRIVY_CACHE_DIR="/custom/cache",
                TRIVY_CALL_LOG=str(call_log),
            )

            self.assertEqual(proc.returncode, 0, proc.stderr)
            self.assertEqual(
                sorted(path.name for path in results.glob("dependency-sbom-scan*.json")),
                [
                    "dependency-sbom-scan-npm-npm.json",
                    "dependency-sbom-scan-pypi-pip.json",
                ],
            )
            calls = call_log.read_text(encoding="utf-8").splitlines()
            self.assertEqual(calls.count("sbom"), 2)
            self.assertEqual(calls.count("--skip-db-update"), 2)
            self.assertEqual(calls.count("--scanners"), 2)
            self.assertEqual(calls.count("vuln"), 2)
            self.assertEqual(calls.count("/custom/cache"), 2)

    # The two tests below guard invariant 1 (no false all-clear). An SBOM exists,
    # so the dependency scanner DID run and this step owes an answer. Exiting 0
    # here would hand run-scan.sh an empty results dir that looks exactly like
    # "no vulnerabilities" — the silent skip this skill exists to prevent.
    def test_missing_trivy_with_an_sbom_present_fails_loudly(self):
        with tempfile.TemporaryDirectory() as tmp:
            project = Path(tmp)
            results = project / ".appsec-results"
            results.mkdir()
            (results / "gl-sbom-npm-npm.cdx.json").write_text("{}", encoding="utf-8")

            proc = self.run_runner(
                project, SBOM_TRIVY_BIN=str(project / "definitely-not-here")
            )

            self.assertNotEqual(proc.returncode, 0)
            self.assertIn("not found", proc.stderr)
            self.assertEqual(list(results.glob("dependency-sbom-scan*.json")), [])

    def test_failed_scan_leaves_no_partial_report_behind(self):
        with tempfile.TemporaryDirectory() as tmp:
            project = Path(tmp)
            results = project / ".appsec-results"
            results.mkdir()
            (results / "gl-sbom-npm-npm.cdx.json").write_text("{}", encoding="utf-8")

            # Writes a truncated report, then dies — a half-written file that
            # normalize.py would otherwise read as a real, nearly clean scan.
            fake_trivy = project / "fake-trivy"
            fake_trivy.write_text(
                "#!/bin/sh\n"
                "output=\n"
                "for arg do\n"
                "  if [ \"${previous:-}\" = -o ]; then output=$arg; fi\n"
                "  previous=$arg\n"
                "done\n"
                "printf '{\"Resu' > \"$output\"\n"
                "exit 1\n",
                encoding="utf-8",
            )
            fake_trivy.chmod(0o755)

            proc = self.run_runner(project, SBOM_TRIVY_BIN=str(fake_trivy))

            self.assertNotEqual(proc.returncode, 0)
            self.assertEqual(list(results.glob("dependency-sbom-scan*.json")), [])


if __name__ == "__main__":
    unittest.main()
