import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest import mock
import zipfile


SCRIPT_DIR = Path(__file__).resolve().parents[1] / "scripts"
sys.path.insert(0, str(SCRIPT_DIR))

import normalize  # noqa: E402


class NormalizeTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.results = Path(self.temporary.name)

    def tearDown(self):
        self.temporary.cleanup()

    def write_json(self, name, value):
        path = self.results / name
        path.write_text(json.dumps(value), encoding="utf-8")
        return path

    def assert_finding_shape(self, finding):
        required = {
            "category",
            "severity",
            "verification_status",
            "remediation_status",
            "triage_reason",
            "location",
            "evidence",
            "fingerprint",
            "scanner",
            "rule_id",
        }
        self.assertTrue(required.issubset(finding))
        self.assertIn(finding["severity"], normalize.SEVERITIES)

    def test_gitlab_schema_json_parsing(self):
        path = self.write_json(
            "gl-secret-detection-report.json",
            {
                "scan": {"scanner": {"id": "gitleaks"}},
                "vulnerabilities": [
                    {
                        "id": "secret-1",
                        "name": "Leaked API token",
                        "description": "sensitive token value",
                        "severity": "Critical",
                        "identifiers": [{"value": "GL-SECRET-001"}],
                        "location": {"file": "src/settings.py", "start_line": 9},
                    }
                ],
            },
        )

        findings = normalize.parse_generic_json(
            path, normalize.read_json_loose(path), "secret_detection"
        )

        self.assertEqual(len(findings), 1)
        finding = findings[0]
        self.assertEqual(finding["category"], "secret_detection")
        self.assertEqual(finding["scanner"], "gitleaks")
        self.assertEqual(finding["severity"], "CRITICAL")
        self.assertEqual(finding["rule_id"], "GL-SECRET-001")
        self.assertEqual(finding["location"], {"file": "src/settings.py", "line": 9})
        self.assert_finding_shape(finding)

    def test_trivy_schema_json_parsing(self):
        path = self.write_json(
            "container-scan-archive.json",
            {
                "Results": [
                    {
                        "Target": "registry.example/app:sha",
                        "Vulnerabilities": [
                            {
                                "VulnerabilityID": "CVE-2026-1000",
                                "Title": "Library issue",
                                "Severity": "HIGH",
                                "PkgName": "libssl",
                                "InstalledVersion": "1.0",
                                "FixedVersion": "1.1",
                            }
                        ],
                    }
                ]
            },
        )

        findings = normalize.parse_generic_json(path, normalize.read_json_loose(path))

        self.assertEqual(len(findings), 1)
        finding = findings[0]
        self.assertEqual(finding["category"], "container_scanning")
        self.assertEqual(finding["location"], {"image": "registry.example/app:sha"})
        self.assertEqual(finding["evidence"]["package"], "libssl")
        self.assertEqual(finding["evidence"]["fixed_version"], "1.1")

    def test_fpr_zip_float_severity_mapping(self):
        fvdl = """<?xml version="1.0"?>
<FVDL xmlns="xmlns://www.fortifysoftware.com/schema/fvdl">
  <Vulnerabilities>
    <Vulnerability><ClassInfo><ClassID>1</ClassID><Type>A</Type><DefaultSeverity>4.5</DefaultSeverity></ClassInfo><InstanceInfo><FileName>src/a.py</FileName><LineStart>1</LineStart></InstanceInfo></Vulnerability>
    <Vulnerability><ClassInfo><ClassID>2</ClassID><Type>B</Type><DefaultSeverity>3.5</DefaultSeverity></ClassInfo><InstanceInfo><FileName>src/b.py</FileName><LineStart>2</LineStart></InstanceInfo></Vulnerability>
    <Vulnerability><ClassInfo><ClassID>3</ClassID><Type>C</Type><DefaultSeverity>2.5</DefaultSeverity></ClassInfo><InstanceInfo><FileName>src/c.py</FileName><LineStart>3</LineStart></InstanceInfo></Vulnerability>
    <Vulnerability><ClassInfo><ClassID>4</ClassID><Type>D</Type><DefaultSeverity>1.0</DefaultSeverity></ClassInfo><InstanceInfo><FileName>src/d.py</FileName><LineStart>4</LineStart></InstanceInfo></Vulnerability>
  </Vulnerabilities>
</FVDL>"""
        fpr = self.results / "fortify-sast.fpr"
        with zipfile.ZipFile(fpr, "w") as archive:
            archive.writestr("audit.fvdl", fvdl)

        findings = normalize.parse_fpr(fpr)

        self.assertEqual(
            [finding["severity"] for finding in findings],
            ["CRITICAL", "HIGH", "MEDIUM", "LOW"],
        )
        self.assertTrue(all(finding["scanner"] == "fortify" for finding in findings))

    def test_fvdl_string_severity_and_generic_xml(self):
        path = self.results / "scanner.xml"
        path.write_text(
            "<report><issue severity='High' file='src/app.py' line='7'>"
            "<Name>Unsafe call</Name><RuleID>RULE-7</RuleID></issue></report>",
            encoding="utf-8",
        )

        findings = normalize.parse_generic_xml(path)

        self.assertEqual(findings[0]["severity"], "HIGH")
        self.assertEqual(findings[0]["rule_id"], "RULE-7")

    def test_test_path_is_likely_false_positive(self):
        finding = normalize.new_finding(
            "fortify",
            "Test-only issue",
            "HIGH",
            {"file": "test/fixture.py", "line": 4},
            {},
            category="sast",
            rule_id="RULE-1",
        )

        triaged = normalize.triage_findings([finding])

        self.assertEqual(triaged[0]["verification_status"], "likely_false_positive")

    def test_likely_false_positive_still_fails_gate(self):
        finding = normalize.new_finding(
            "fortify",
            "Test-only issue",
            "CRITICAL",
            {"file": "test/fixture.py", "line": 4},
            {},
            category="sast",
            rule_id="RULE-1",
        )
        normalize.triage_findings([finding])

        self.assertEqual(finding["verification_status"], "likely_false_positive")
        self.assertTrue(normalize.gate_failed([finding], "high"))

    def test_parse_failure_becomes_high_finding_without_raising(self):
        (self.results / "broken.json").write_text("{", encoding="utf-8")

        findings = normalize.normalize_reports(self.results)

        self.assertEqual(len(findings), 1)
        self.assertEqual(findings[0]["severity"], "HIGH")
        self.assertEqual(findings[0]["rule_id"], "APPSEC-REPORT-PARSE-FAILED")
        self.assertEqual(findings[0]["scanner"], "normalizer")

    def test_ran_category_without_report_creates_coverage_finding(self):
        output = io.StringIO()
        with mock.patch("sys.stdout", output):
            exit_code = normalize.main(
                [str(self.results), "--ran", "sast", "--gate", "high"]
            )

        findings = json.loads(
            (self.results / "findings.normalized.json").read_text(encoding="utf-8")
        )
        coverage = json.loads(
            (self.results / "scan-coverage.json").read_text(encoding="utf-8")
        )
        self.assertEqual(exit_code, 1)
        self.assertEqual(findings[0]["rule_id"], "APPSEC-REPORT-MISSING")
        self.assertEqual(coverage["missing_report"], ["sast"])
        self.assertIn("NOT an all-clear", output.getvalue())

    def test_ran_category_with_empty_report_fails_coverage(self):
        (self.results / "gl-secret-detection-report.json").write_bytes(b"")

        exit_code = normalize.main(
            [str(self.results), "--ran", "secret_detection", "--gate", "high"]
        )

        findings = json.loads(
            (self.results / "findings.normalized.json").read_text(encoding="utf-8")
        )
        self.assertEqual(exit_code, 1)
        self.assertEqual(
            [item["rule_id"] for item in findings], ["APPSEC-REPORT-MISSING"]
        )
        self.assertEqual(findings[0]["severity"], "HIGH")

    def test_ran_category_with_malformed_report_fails_as_unparseable(self):
        (self.results / "gl-secret-detection-report.json").write_text(
            '{"vulnerabilities": [', encoding="utf-8"
        )

        exit_code = normalize.main(
            [str(self.results), "--ran", "secret_detection", "--gate", "high"]
        )

        findings = json.loads(
            (self.results / "findings.normalized.json").read_text(encoding="utf-8")
        )
        self.assertEqual(exit_code, 1)
        self.assertEqual(
            [item["rule_id"] for item in findings],
            ["APPSEC-REPORT-UNPARSEABLE"],
        )
        self.assertEqual(findings[0]["severity"], "HIGH")

    def test_ran_category_with_valid_empty_findings_report_is_clean(self):
        self.write_json(
            "gl-secret-detection-report.json", {"vulnerabilities": []}
        )

        exit_code = normalize.main(
            [str(self.results), "--ran", "secret_detection", "--gate", "high"]
        )

        findings = json.loads(
            (self.results / "findings.normalized.json").read_text(encoding="utf-8")
        )
        self.assertEqual(exit_code, 0)
        self.assertEqual(findings, [])

    def test_recorded_skip_creates_a_gap_even_when_a_report_exists(self):
        # A skip is authoritative. gl-sbom-*.cdx.json is a valid dependency
        # report, so an SBOM that was never matched against an advisory DB used
        # to normalize to zero findings and print "Gate verdict: PASSED" with
        # coverage_complete: true — a category whose dependencies were never
        # checked against anything, reported as scanned and clean.
        self.write_json(
            "gl-sbom-python.cdx.json",
            {
                "bomFormat": "CycloneDX",
                "specVersion": "1.5",
                "components": [{"name": "flask", "version": "1.0"}],
            },
        )
        skips = self.results / "scan-skips"
        skips.write_text(
            "dependency_scanning\tSBOM vulnerability match did not run (no "
            "container-scanning image), so dependencies were NOT matched "
            "against any advisory DB.\n",
            encoding="utf-8",
        )

        output = io.StringIO()
        with mock.patch("sys.stdout", output):
            exit_code = normalize.main(
                [
                    str(self.results),
                    "--gate",
                    "high",
                    "--ran",
                    "dependency_scanning",
                    "--skips",
                    str(skips),
                ]
            )

        coverage = json.loads(
            (self.results / "scan-coverage.json").read_text(encoding="utf-8")
        )
        findings = json.loads(
            (self.results / "findings.triaged.json").read_text(encoding="utf-8")
        )
        self.assertEqual(exit_code, 1)
        self.assertIn("Gate verdict: FAILED", output.getvalue())
        self.assertIn("NOT an all-clear", output.getvalue())
        self.assertFalse(coverage["coverage_complete"])
        self.assertEqual(coverage["missing_report"], ["dependency_scanning"])
        # INCOMPLETE, not MISSING: the report is there, the work is not.
        self.assertEqual(
            [item["rule_id"] for item in findings], ["APPSEC-REPORT-INCOMPLETE"]
        )
        self.assertEqual(findings[0]["severity"], "HIGH")
        # The reason is what makes the gap fixable, so it must reach the user.
        self.assertIn("advisory DB", findings[0]["evidence"]["why"])

    def test_empty_skips_file_leaves_a_complete_scan_clean(self):
        # run-scan.sh truncates the skips file at startup, so the usual case is
        # an existing but empty file. It must not manufacture gaps.
        for name in (
            "gl-secret-detection-report.json",
            "gl-container-scanning-report.json",
        ):
            self.write_json(name, {"vulnerabilities": []})
        self.write_json(
            "gl-sbom-python.cdx.json", {"bomFormat": "CycloneDX", "components": []}
        )
        with zipfile.ZipFile(self.results / "fortify-sast.fpr", "w") as archive:
            archive.writestr("audit.fvdl", "<FVDL/>")
        skips = self.results / "scan-skips"
        skips.write_text("", encoding="utf-8")

        exit_code = normalize.main(
            [
                str(self.results),
                "--gate",
                "high",
                "--ran",
                "sast,dependency_scanning,secret_detection,container_scanning",
                "--skips",
                str(skips),
            ]
        )

        coverage = json.loads(
            (self.results / "scan-coverage.json").read_text(encoding="utf-8")
        )
        self.assertEqual(exit_code, 0)
        self.assertTrue(coverage["coverage_complete"])
        self.assertEqual(coverage["missing_report"], [])

    def test_clean_sbom_vulnerability_report_passes_the_gate(self):
        # sbom-vuln-scan.sh writes one dependency-sbom-scan-<sbom>.json per SBOM.
        # While that name was registered nowhere, Trivy finding nothing — the
        # GOOD outcome — produced two phantom HIGHs: unsupported_report from the
        # unguarded generic .json branch, and APPSEC-REPORT-MISSING because the
        # report satisfied no category. A clean dependency scan could not pass.
        self.write_json(
            "dependency-sbom-scan-npm-npm.json",
            {
                "SchemaVersion": 2,
                "ArtifactName": "gl-sbom-npm-npm.cdx.json",
                "ArtifactType": "cyclonedx",
                "Results": [
                    {"Target": "Node.js", "Class": "lang-pkgs", "Type": "node-pkg"}
                ],
            },
        )
        skips = self.results / "scan-skips"
        skips.write_text("", encoding="utf-8")

        output = io.StringIO()
        with mock.patch("sys.stdout", output):
            exit_code = normalize.main(
                [
                    str(self.results),
                    "--gate",
                    "high",
                    "--ran",
                    "dependency_scanning",
                    "--skips",
                    str(skips),
                ]
            )

        findings = json.loads(
            (self.results / "findings.triaged.json").read_text(encoding="utf-8")
        )
        coverage = json.loads(
            (self.results / "scan-coverage.json").read_text(encoding="utf-8")
        )
        self.assertEqual(exit_code, 0)
        self.assertEqual(findings, [])
        self.assertIn("Gate verdict: PASSED", output.getvalue())
        self.assertTrue(coverage["coverage_complete"])
        self.assertEqual(coverage["missing_report"], [])

    def test_sbom_vulnerability_report_keeps_upgrade_evidence(self):
        # The other half of registering the name: it must still be parsed.
        # fixed_version and ecosystem are what check-remediation.py probes and
        # what the fix loop upgrades to.
        self.write_json(
            "dependency-sbom-scan-npm-npm.json",
            {
                "Results": [
                    {
                        "Target": "Node.js",
                        "Type": "node-pkg",
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
            },
        )

        findings = normalize.normalize_reports(self.results)

        self.assertEqual(len(findings), 1)
        self.assertEqual(findings[0]["category"], "dependency_scanning")
        self.assertEqual(findings[0]["location"], {"package": "lodash"})
        self.assertEqual(findings[0]["evidence"]["fixed_version"], "4.17.12")
        self.assertEqual(findings[0]["evidence"]["ecosystem"], "npm")

    def test_skip_without_a_reason_still_records_the_gap(self):
        # Whether a category counts as covered must not depend on whether the
        # reason text made it into the file: an empty, whitespace-only or
        # tab-less line used to discard the skip itself, all-clearing a category
        # that never ran.
        for line in (
            "dependency_scanning\n",
            "dependency_scanning\t\n",
            "dependency_scanning\t   \n",
        ):
            with self.subTest(line=line):
                self.write_json(
                    "gl-sbom-python.cdx.json",
                    {"bomFormat": "CycloneDX", "components": []},
                )
                skips = self.results / "scan-skips"
                skips.write_text(line, encoding="utf-8")

                exit_code = normalize.main(
                    [
                        str(self.results),
                        "--gate",
                        "high",
                        "--ran",
                        "dependency_scanning",
                        "--skips",
                        str(skips),
                    ]
                )

                coverage = json.loads(
                    (self.results / "scan-coverage.json").read_text(encoding="utf-8")
                )
                findings = json.loads(
                    (self.results / "findings.triaged.json").read_text(encoding="utf-8")
                )
                self.assertEqual(exit_code, 1)
                self.assertFalse(coverage["coverage_complete"])
                self.assertEqual(coverage["missing_report"], ["dependency_scanning"])
                self.assertEqual(
                    [item["rule_id"] for item in findings],
                    ["APPSEC-REPORT-INCOMPLETE"],
                )
                self.assertTrue(findings[0]["evidence"]["why"].strip())

    def test_unreadable_skips_file_fails_loudly(self):
        # A skips file we were told to read but could not is not evidence that
        # nothing was skipped; swallowing the OSError erased every recorded gap
        # and reported full coverage. A directory is the portable "exists but
        # cannot be read as a file" case — chmod 000 is a no-op for root.
        self.write_json("gl-secret-detection-report.json", {"vulnerabilities": []})
        unreadable = self.results / "scan-skips"
        unreadable.mkdir()

        errors = io.StringIO()
        with mock.patch("sys.stderr", errors):
            exit_code = normalize.main(
                [
                    str(self.results),
                    "--gate",
                    "high",
                    "--ran",
                    "secret_detection",
                    "--skips",
                    str(unreadable),
                ]
            )

        self.assertEqual(exit_code, 2)
        self.assertIn("ERROR", errors.getvalue())
        self.assertFalse((self.results / "scan-coverage.json").exists())

    def test_absent_skips_file_is_not_a_gap(self):
        # run-scan.sh truncates the skips file before any scanner starts, so a
        # path that does not exist means nothing was ever recorded.
        self.write_json("gl-secret-detection-report.json", {"vulnerabilities": []})

        exit_code = normalize.main(
            [
                str(self.results),
                "--gate",
                "high",
                "--ran",
                "secret_detection",
                "--skips",
                str(self.results / "never-written"),
            ]
        )

        coverage = json.loads(
            (self.results / "scan-coverage.json").read_text(encoding="utf-8")
        )
        self.assertEqual(exit_code, 0)
        self.assertTrue(coverage["coverage_complete"])

    def test_sbom_is_supported_with_zero_findings(self):
        self.write_json(
            "gl-sbom-python.cdx.json",
            {"bomFormat": "CycloneDX", "specVersion": "1.5", "components": []},
        )

        findings = normalize.normalize_reports(self.results)

        self.assertEqual(findings, [])

    def test_unrecognized_json_schema_is_unsupported(self):
        # A schema we cannot read is still a HIGH: it may be a report whose
        # findings we are silently dropping.
        self.write_json("unknown.json", {"unexpected": "schema"})

        findings = normalize.normalize_reports(self.results)

        self.assertEqual(len(findings), 1)
        self.assertEqual(findings[0]["severity"], "HIGH")
        self.assertEqual(findings[0]["rule_id"], "unsupported_report")

    def test_clean_json_report_is_not_a_phantom_high(self):
        # The generic .json branch was the one place without the clean-schema
        # guard, so a report that ran and found nothing — the GOOD outcome —
        # became a HIGH that failed the gate. It cost an all-clear twice:
        # registry-availability.json, then the Trivy SBOM report. An empty
        # object is the same case: no findings, and no coverage credit either,
        # so it cannot manufacture a false all-clear.
        for payload in ({"Results": []}, {"vulnerabilities": []}, {}):
            with self.subTest(payload=payload):
                self.write_json("some-scanner-output.json", payload)

                self.assertEqual(normalize.normalize_reports(self.results), [])

    def test_cached_bin_and_catalog_reports_are_ignored(self):
        bin_dir = self.results / "bin"
        catalog_dir = self.results / "catalog"
        bin_dir.mkdir()
        catalog_dir.mkdir()
        (bin_dir / "fortify-sast.fpr").write_bytes(b"cached")
        (catalog_dir / "gl-secret-detection-report.json").write_text(
            '{"vulnerabilities": []}', encoding="utf-8"
        )

        findings = normalize.normalize_reports(self.results)
        coverage, missing = normalize.coverage_findings(
            self.results, ["sast", "secret_detection"]
        )

        self.assertEqual(findings, [])
        self.assertEqual(missing, ["sast", "secret_detection"])
        self.assertEqual(
            [finding["rule_id"] for finding in coverage],
            ["APPSEC-REPORT-MISSING", "APPSEC-REPORT-MISSING"],
        )

    def test_registry_availability_output_is_ignored(self):
        self.write_json(
            "registry-availability.json",
            {"npm|lodash|4.17.21": "absent"},
        )

        findings = normalize.normalize_reports(self.results)

        self.assertEqual(findings, [])

    def test_environment_medium_gate_fails_on_medium_finding(self):
        self.write_json(
            "gl-secret-detection-report.json",
            {
                "vulnerabilities": [
                    {
                        "name": "Medium secret",
                        "severity": "MEDIUM",
                        "identifiers": [{"value": "SECRET-1"}],
                        "location": {"file": "src/app.py", "line": 2},
                    }
                ]
            },
        )

        with mock.patch.dict(os.environ, {"CI_GATE_FAIL_ON": "medium"}):
            exit_code = normalize.main([str(self.results), "--ran", ""])

        self.assertEqual(exit_code, 1)

    def test_unrecognized_severity_requires_review_and_fails_gate(self):
        errors = io.StringIO()
        with mock.patch("sys.stderr", errors):
            finding = normalize.new_finding(
                "fortify",
                "Invalid scanner severity",
                "garbage",
                {"file": "src/app.py", "line": 4},
                {},
                category="sast",
                rule_id="RULE-GARBAGE",
            )
        normalize.triage_findings([finding])

        self.assertEqual(finding["severity"], "UNKNOWN")
        self.assertEqual(finding["verification_status"], "needs_human_review")
        self.assertTrue(normalize.gate_failed([finding], "high"))
        self.assertIn("RULE-GARBAGE", errors.getvalue())

    def test_missing_severity_with_real_location_is_conservative(self):
        errors = io.StringIO()
        with mock.patch("sys.stderr", errors):
            finding = normalize.new_finding(
                "fortify",
                "Missing scanner severity",
                None,
                {"file": "src/app.py", "line": 5},
                {},
                category="sast",
                rule_id="RULE-MISSING-SEVERITY",
            )
        normalize.triage_findings([finding])

        self.assertEqual(finding["severity"], "UNKNOWN")
        self.assertEqual(finding["verification_status"], "needs_human_review")
        self.assertTrue(normalize.gate_failed([finding], "high"))
        self.assertIn("RULE-MISSING-SEVERITY", errors.getvalue())

    def test_gate_none_always_exits_zero(self):
        self.write_json(
            "gl-container-scanning-report.json",
            {
                "vulnerabilities": [
                    {
                        "name": "Critical package",
                        "severity": "CRITICAL",
                        "identifiers": [{"value": "CVE-1"}],
                        "location": {"dependency": {"package": {"name": "openssl"}}},
                    }
                ]
            },
        )

        exit_code = normalize.main([str(self.results), "--gate", "none"])

        self.assertEqual(exit_code, 0)

    def test_only_merge_preserves_other_categories_and_scopes_exit(self):
        preserved = normalize.new_finding(
            "gitleaks",
            "Previously redacted",
            "CRITICAL",
            {"file": "src/secret.py", "line": 1},
            {"description": "Prev..."},
            category="secret_detection",
            rule_id="SECRET-OLD",
        )
        old_sast = normalize.new_finding(
            "fortify",
            "Old SAST",
            "CRITICAL",
            {"file": "src/old.py", "line": 1},
            {},
            category="sast",
            rule_id="OLD",
        )
        for name in ("findings.normalized.json", "findings.triaged.json"):
            (self.results / name).write_text(
                json.dumps([preserved, old_sast]), encoding="utf-8"
            )
        fvdl = """<FVDL><Vulnerability><ClassInfo><ClassID>NEW</ClassID><Type>New SAST</Type><DefaultSeverity>1.0</DefaultSeverity></ClassInfo><InstanceInfo><FileName>src/new.py</FileName><LineStart>3</LineStart></InstanceInfo></Vulnerability></FVDL>"""
        with zipfile.ZipFile(self.results / "fortify-sast.fpr", "w") as archive:
            archive.writestr("audit.fvdl", fvdl)
        # A real rescan runs against a results dir where the earlier full scan's
        # report artifacts still exist. Without this, secret_detection looks like
        # a coverage gap — which coverage checking now correctly reports, since
        # it is no longer narrowed to the --only category.
        (self.results / "gl-secret-detection-report.json").write_text(
            json.dumps({"vulnerabilities": []}), encoding="utf-8"
        )

        exit_code = normalize.main(
            [
                str(self.results),
                "--only",
                "sast",
                "--ran",
                "sast,secret_detection",
                "--gate",
                "high",
            ]
        )

        merged = json.loads(
            (self.results / "findings.normalized.json").read_text(encoding="utf-8")
        )
        self.assertEqual(exit_code, 0)
        self.assertEqual(
            [item for item in merged if item["category"] == "secret_detection"],
            [preserved],
        )
        sast = [item for item in merged if item["category"] == "sast"]
        self.assertEqual(len(sast), 1)
        self.assertEqual(sast[0]["rule_id"], "NEW")

    def test_secret_text_is_redacted_before_json_write(self):
        self.write_json(
            "gl-secret-detection-report.json",
            {
                "scan": {"scanner": {"id": "gitleaks"}},
                "vulnerabilities": [
                    {
                        "name": "Exposed production credential",
                        "description": "super-secret-value",
                        "solution": "rotate immediately",
                        "severity": "HIGH",
                        "identifiers": [{"value": "SECRET-42"}],
                        "location": {"file": "src/config.py", "line": 5},
                    }
                ],
            },
        )

        output = io.StringIO()
        with mock.patch("sys.stdout", output):
            exit_code = normalize.main([str(self.results), "--gate", "none"])

        findings = json.loads(
            (self.results / "findings.normalized.json").read_text(encoding="utf-8")
        )
        finding = findings[0]
        self.assertEqual(exit_code, 0)
        self.assertEqual(finding["name"], "Expo...")
        self.assertEqual(finding["evidence"]["description"], "supe...")
        self.assertEqual(finding["evidence"]["solution"], "rota...")
        self.assertNotIn("super-secret-value", json.dumps(findings))
        self.assertIn("Secret Detection findings (redacted)", output.getvalue())
        self.assertNotIn("Exposed production credential", output.getvalue())

    def test_sast_secret_pattern_is_redacted_in_all_written_outputs(self):
        token = "glpat-abc123xyz789"
        self.write_json(
            "sast-report.json",
            {
                "vulnerabilities": [
                    {
                        "name": "Token embedded in source",
                        "description": "Observed " + token + " in a request",
                        "severity": "HIGH",
                        "identifiers": [{"value": "SAST-TOKEN-1"}],
                        "location": {"file": "src/client.py", "line": 12},
                    }
                ]
            },
        )

        exit_code = normalize.main([str(self.results), "--gate", "none"])

        self.assertEqual(exit_code, 0)
        for name in ("findings.normalized.json", "findings.triaged.json"):
            output = (self.results / name).read_text(encoding="utf-8")
            self.assertNotIn(token, output)
            self.assertIn("Observed *** in a request", output)

    def test_redaction_preserves_manifest_and_package_metadata(self):
        token = "glpat-abc123xyz789"
        manifest = "services/api/src/main/requirements.txt"
        package = "internal_dependency_package_identifier"
        self.write_json(
            "dependency-report.json",
            {
                "vulnerabilities": [
                    {
                        "name": "Credential in dependency finding",
                        "description": "Observed " + token + " while scanning",
                        "severity": "HIGH",
                        "identifiers": [{"value": "DEPENDENCY-SECRET-1"}],
                        "location": {
                            "file": manifest,
                            "dependency": {"package": {"name": package}},
                        },
                        "fixed_version": "2.0",
                    }
                ]
            },
        )

        exit_code = normalize.main([str(self.results), "--gate", "none"])

        self.assertEqual(exit_code, 0)
        for name in ("findings.normalized.json", "findings.triaged.json"):
            finding = json.loads(
                (self.results / name).read_text(encoding="utf-8")
            )[0]
            self.assertEqual(finding["evidence"]["manifest"], manifest)
            self.assertEqual(finding["evidence"]["package"], package)
            self.assertNotIn(token, json.dumps(finding))

    def test_secret_pattern_in_rule_id_is_redacted_in_all_written_outputs(self):
        for rule_id in ("glpat-ruleid123", "AKIA1234567890ABCDEF"):
            with self.subTest(rule_id=rule_id):
                self.write_json(
                    "sast-report.json",
                    {
                        "vulnerabilities": [
                            {
                                "name": "Credential-shaped rule identifier",
                                "severity": "HIGH",
                                "identifiers": [{"value": rule_id}],
                                "location": {"file": "src/client.py", "line": 12},
                            }
                        ]
                    },
                )

                exit_code = normalize.main([str(self.results), "--gate", "none"])

                self.assertEqual(exit_code, 0)
                for name in ("findings.normalized.json", "findings.triaged.json"):
                    findings = json.loads(
                        (self.results / name).read_text(encoding="utf-8")
                    )
                    self.assertEqual(findings[0]["rule_id"], "***")
                    self.assertNotIn(rule_id, json.dumps(findings))

    def test_fingerprint_is_stable(self):
        first = normalize.new_finding(
            "fortify",
            "SQL injection",
            "4.5",
            {"file": "src/db.py", "line": 12},
            {"context": "query"},
            category="sast",
            rule_id="SQL-1",
        )
        second = normalize.new_finding(
            "fortify",
            "SQL injection",
            "4.5",
            {"file": "src/db.py", "line": 12},
            {"context": "query"},
            category="sast",
            rule_id="SQL-1",
        )

        self.assertEqual(first["fingerprint"], second["fingerprint"])

    def test_summary_reports_total_and_actionable_critical_high_counts(self):
        findings = [
            {
                "scanner": "fortify",
                "severity": "CRITICAL",
                "remediation_status": "fixable_candidate",
            },
            {
                "scanner": "gemnasium",
                "severity": "HIGH",
                "remediation_status": "blocked_external_dependency",
            },
            {
                "scanner": "gemnasium",
                "severity": "HIGH",
                "remediation_status": "blocked_registry_gap",
            },
        ]
        output = io.StringIO()

        with mock.patch("sys.stdout", output):
            normalize.print_summary(findings, "high", True)

        self.assertIn("TOTAL C+H: 3", output.getvalue())
        self.assertIn("ACTIONABLE C+H: 1", output.getvalue())

    def test_cli_subprocess_contract_writes_three_files(self):
        env = dict(os.environ)
        env["PYTHONDONTWRITEBYTECODE"] = "1"
        process = subprocess.run(
            [
                sys.executable,
                str(SCRIPT_DIR / "normalize.py"),
                str(self.results),
                "--ran",
                "",
            ],
            text=True,
            capture_output=True,
            env=env,
            check=False,
        )

        self.assertEqual(process.returncode, 0, process.stderr)
        self.assertIn("Scanner", process.stdout)
        self.assertIn("TOTAL C+H", process.stdout)
        self.assertIn("Gate verdict: PASSED", process.stdout)
        for name in (
            "findings.normalized.json",
            "findings.triaged.json",
            "scan-coverage.json",
        ):
            self.assertTrue((self.results / name).exists())


if __name__ == "__main__":
    unittest.main()


class ScopedRescanCoverageTest(unittest.TestCase):
    """A --only rescan must never launder the coverage record clean."""

    def _coverage(self, tmp):
        return json.loads((Path(tmp) / "scan-coverage.json").read_text())

    def test_scoped_rescan_preserves_earlier_missing_reports(self) -> None:
        # SKILL.md Step 5 runs `run-scan.sh --only <category>` every iteration.
        # It used to overwrite scan-coverage.json with just that category, so
        # {"missing_report": ["sast"]} became {"missing_report": [], "gate_passed": true}
        # while sast had still never run.
        with tempfile.TemporaryDirectory() as tmp:
            results = Path(tmp)
            (results / "gl-secret-detection-report.json").write_text('{"vulnerabilities": []}')

            normalize.main([str(results), "--gate", "high", "--ran", "sast,secret_detection"])
            first = self._coverage(tmp)
            self.assertIn("sast", first["missing_report"])
            self.assertFalse(first["gate_passed"])

            normalize.main([str(results), "--gate", "high", "--ran", "secret_detection",
                  "--only", "secret_detection"])
            second = self._coverage(tmp)

        self.assertIn("sast", second["missing_report"], "scoped rescan erased the gap")
        self.assertIn("sast", second["scanners_run"], "scoped rescan forgot sast ran")
        self.assertFalse(second["gate_passed"], "incomplete coverage reported as a pass")

    def test_scoped_rescan_recovers_a_gap_from_a_lost_findings_file(self) -> None:
        # `missing` was rebuilt purely from findings.triaged.json, never unioned
        # with the previous run's missing_report. Losing, truncating or
        # rewriting that file turned a recorded gap into coverage_complete:
        # true, gate_passed: true, exit 0 — while sast had still never run.
        with tempfile.TemporaryDirectory() as tmp:
            results = Path(tmp)
            (results / "gl-secret-detection-report.json").write_text(
                '{"vulnerabilities": []}'
            )

            normalize.main(
                [str(results), "--gate", "high", "--ran", "sast,secret_detection"]
            )
            self.assertIn("sast", self._coverage(tmp)["missing_report"])

            for name in ("findings.triaged.json", "findings.normalized.json"):
                (results / name).write_text("[]")

            rc = normalize.main(
                [
                    str(results),
                    "--gate",
                    "high",
                    "--ran",
                    "secret_detection",
                    "--only",
                    "secret_detection",
                ]
            )
            coverage = self._coverage(tmp)

        self.assertIn("sast", coverage["missing_report"], "lost findings erased the gap")
        self.assertFalse(coverage["coverage_complete"])
        self.assertEqual(rc, 1)

    def test_scoped_rescan_keeps_a_gap_when_only_normalized_survives(self) -> None:
        # An interrupted run can leave the three records out of step. Coverage
        # gaps were deduped against findings.normalized.json but re-derived from
        # findings.triaged.json + scan-coverage.json, so when the latter two were
        # lost and the former survived, the surviving copy suppressed the gap
        # here AND had nothing left to re-derive it from: PASSED, exit 0,
        # coverage_complete: true, for a category that never ran.
        with tempfile.TemporaryDirectory() as tmp:
            results = Path(tmp)
            (results / "gl-secret-detection-report.json").write_text(
                '{"vulnerabilities": []}'
            )

            normalize.main(
                [str(results), "--gate", "high", "--ran", "sast,secret_detection"]
            )
            self.assertIn("sast", self._coverage(tmp)["missing_report"])

            # Only findings.normalized.json is left holding the record.
            (results / "findings.triaged.json").unlink()
            (results / "scan-coverage.json").unlink()

            rc = normalize.main(
                [
                    str(results),
                    "--gate",
                    "high",
                    "--ran",
                    "secret_detection",
                    "--only",
                    "secret_detection",
                ]
            )
            coverage = self._coverage(tmp)

        self.assertIn(
            "sast", coverage["missing_report"], "surviving record did not hold the gap"
        )
        self.assertFalse(coverage["coverage_complete"])
        self.assertEqual(rc, 1)

    def test_scoped_rescan_clears_a_gap_the_category_actually_filled(self) -> None:
        # The other direction: a gap the rescan genuinely closed must not be
        # carried forever, or a clean scan can never pass again.
        with tempfile.TemporaryDirectory() as tmp:
            results = Path(tmp)
            (results / "gl-secret-detection-report.json").write_text(
                '{"vulnerabilities": []}'
            )

            normalize.main(
                [str(results), "--gate", "high", "--ran", "sast,secret_detection"]
            )
            self.assertIn("sast", self._coverage(tmp)["missing_report"])

            with zipfile.ZipFile(results / "fortify-sast.fpr", "w") as archive:
                archive.writestr("audit.fvdl", "<FVDL/>")
            rc = normalize.main(
                [
                    str(results),
                    "--gate",
                    "high",
                    "--ran",
                    "sast,secret_detection",
                    "--only",
                    "sast",
                ]
            )
            coverage = self._coverage(tmp)

        self.assertEqual(coverage["missing_report"], [])
        self.assertTrue(coverage["coverage_complete"])
        self.assertEqual(rc, 0)

    def test_scoped_rescan_does_not_clear_another_categorys_gap(self) -> None:
        # `cleared` was `set(scanners_run) - set(missing)`, and run-scan.sh
        # deliberately passes the FULL admin-enabled list as --ran even under
        # --only. So a `--only sast` rescan cleared the recorded gap of every
        # category whose stale report file was still on disk: dependency
        # scanning was never matched against any advisory DB, and the rescan
        # printed PASSED / exit 0 / coverage_complete: true.
        all_four = "sast,dependency_scanning,secret_detection,container_scanning"
        with tempfile.TemporaryDirectory() as tmp:
            results = Path(tmp)
            (results / "gl-secret-detection-report.json").write_text(
                '{"vulnerabilities": []}'
            )
            (results / "gl-container-scanning-report.json").write_text(
                '{"vulnerabilities": []}'
            )
            (results / "gl-sbom-npm.cdx.json").write_text(
                '{"bomFormat": "CycloneDX", "components": []}'
            )
            with zipfile.ZipFile(results / "fortify-sast.fpr", "w") as archive:
                archive.writestr("audit.fvdl", "<FVDL/>")
            skips = results / "scan-skips"
            skips.write_text(
                "dependency_scanning\tThe SBOM was never matched against any "
                "advisory DB.\n"
            )

            first = normalize.main(
                [str(results), "--gate", "high", "--ran", all_four,
                 "--skips", str(skips)]
            )
            self.assertEqual(first, 1)
            self.assertEqual(
                self._coverage(tmp)["missing_report"], ["dependency_scanning"]
            )

            # run-scan.sh truncates the skips file at startup, and the fix loop
            # rewrites findings.triaged.json — so neither can hold the invariant.
            skips.write_text("")
            for name in ("findings.triaged.json", "findings.normalized.json"):
                (results / name).write_text("[]")

            output = io.StringIO()
            with mock.patch("sys.stdout", output):
                rc = normalize.main(
                    [str(results), "--gate", "high", "--only", "sast",
                     "--ran", all_four, "--skips", str(skips)]
                )
            coverage = self._coverage(tmp)

        self.assertIn(
            "dependency_scanning",
            coverage["missing_report"],
            "a sast rescan cleared dependency scanning's gap",
        )
        self.assertFalse(coverage["coverage_complete"])
        self.assertEqual(rc, 1)
        self.assertIn("Gate verdict: FAILED", output.getvalue())

    def test_scoped_rescan_clears_its_own_gap_when_the_report_arrives(self) -> None:
        # The other direction of the same fix: a gate that can never pass again
        # after one gap trains the team to ignore it.
        both = "dependency_scanning,secret_detection"
        with tempfile.TemporaryDirectory() as tmp:
            results = Path(tmp)
            (results / "gl-secret-detection-report.json").write_text(
                '{"vulnerabilities": []}'
            )
            skips = results / "scan-skips"
            skips.write_text(
                "dependency_scanning\tThe SBOM was never matched against any "
                "advisory DB.\n"
            )
            self.assertEqual(
                normalize.main(
                    [str(results), "--gate", "high", "--ran", both,
                     "--skips", str(skips)]
                ),
                1,
            )
            self.assertEqual(
                self._coverage(tmp)["missing_report"], ["dependency_scanning"]
            )

            skips.write_text("")
            (results / "dependency-sbom-scan-npm.json").write_text(
                '{"SchemaVersion": 2, "ArtifactName": "gl-sbom-npm.cdx.json",'
                ' "Results": []}'
            )
            rc = normalize.main(
                [str(results), "--gate", "high", "--only", "dependency_scanning",
                 "--ran", both, "--skips", str(skips)]
            )
            coverage = self._coverage(tmp)

        self.assertEqual(coverage["missing_report"], [])
        self.assertTrue(coverage["coverage_complete"])
        self.assertEqual(rc, 0)

    def test_scoped_rescan_of_a_category_it_did_not_run_keeps_the_gap(self) -> None:
        # `--only sast` cleared sast's recorded gap on the strength of the flag
        # alone, even when --ran says sast was not among the categories this
        # invocation examined: nothing re-checked it, so nothing may clear it.
        with tempfile.TemporaryDirectory() as tmp:
            results = Path(tmp)
            (results / "gl-secret-detection-report.json").write_text(
                '{"vulnerabilities": []}'
            )
            normalize.main(
                [str(results), "--gate", "high", "--ran", "sast,secret_detection"]
            )
            self.assertIn("sast", self._coverage(tmp)["missing_report"])

            rc = normalize.main(
                [str(results), "--gate", "high", "--only", "sast",
                 "--ran", "secret_detection"]
            )
            coverage = self._coverage(tmp)

        self.assertIn(
            "sast",
            coverage["missing_report"],
            "a rescan that never ran sast cleared sast's gap",
        )
        self.assertFalse(coverage["coverage_complete"])
        self.assertEqual(rc, 1)

    def test_repeated_scoped_rescans_do_not_duplicate_a_coverage_finding(self) -> None:
        # The fix loop reruns `--only sast` up to five times. The dedupe only
        # looked at this run's parsed findings, never at the merged file the
        # other categories are carried over from, so container_scanning's one
        # gap was appended again on every iteration.
        with tempfile.TemporaryDirectory() as tmp:
            results = Path(tmp)
            skips = results / "scan-skips"
            skips.write_text("container_scanning\tNo Dockerfile was found.\n")
            with zipfile.ZipFile(results / "fortify-sast.fpr", "w") as archive:
                archive.writestr("audit.fvdl", "<FVDL/>")

            for _ in range(3):
                rc = normalize.main(
                    [str(results), "--gate", "high", "--only", "sast",
                     "--ran", "sast,container_scanning", "--skips", str(skips)]
                )
            findings = json.loads(
                (results / "findings.normalized.json").read_text()
            )
            coverage = self._coverage(tmp)

        gaps = [
            item for item in findings
            if item["category"] == "container_scanning"
            and item["rule_id"].startswith("APPSEC-REPORT-")
        ]
        self.assertEqual(len(gaps), 1, findings)
        self.assertEqual(coverage["missing_report"], ["container_scanning"])
        self.assertEqual(rc, 1)

    def test_incomplete_coverage_fails_even_a_critical_only_gate(self) -> None:
        # A HIGH coverage finding does not trip a critical-only gate on severity
        # alone, so the rule is stated explicitly instead.
        with tempfile.TemporaryDirectory() as tmp:
            results = Path(tmp)
            rc = normalize.main([str(results), "--gate", "critical", "--ran", "sast"])
            coverage = self._coverage(tmp)

        self.assertEqual(rc, 1)
        self.assertFalse(coverage["gate_passed"])

    def test_report_only_gate_none_records_coverage_without_failing(self) -> None:
        # `none` is documented as "always exit 0, report-only", and something
        # unattended may branch on that, so incomplete coverage does NOT change
        # the exit code here. It must still be RECORDED: coverage_complete is
        # false, so SKILL.md Step 3 can refuse to call the scan done. The exit
        # code alone is not a sufficient all-clear signal at this threshold.
        with tempfile.TemporaryDirectory() as tmp:
            results = Path(tmp)
            (results / "gl-secret-detection-report.json").write_text(
                json.dumps(
                    {
                        "vulnerabilities": [
                            {
                                "name": "Critical secret",
                                "severity": "CRITICAL",
                                "identifiers": [{"value": "SECRET-1"}],
                                "location": {"file": "src/app.py", "line": 2},
                            }
                        ]
                    }
                )
            )
            clean = normalize.main(
                [str(results), "--gate", "none", "--ran", "secret_detection"]
            )
            uncovered = normalize.main(
                [str(results), "--gate", "none", "--ran", "sast,secret_detection"]
            )
            coverage = self._coverage(tmp)

        self.assertEqual(clean, 0)
        self.assertEqual(uncovered, 0, "gate none must stay exit 0 (documented contract)")
        self.assertFalse(
            coverage["coverage_complete"], "the gap must still be recorded"
        )

    def test_remediation_text_survives_redaction(self) -> None:
        # `why` is tool-authored guidance; redacting it mangled the image path
        # the user needs ("Could not pull registry.gitlab.***").
        with tempfile.TemporaryDirectory() as tmp:
            results = Path(tmp)
            skips = results / "scan-skips"
            reason = "Could not pull registry.gitlab.com/ns/proj/img:1.2.3, so SAST did NOT run."
            skips.write_text("sast\t" + reason + "\n")
            normalize.main([str(results), "--gate", "high", "--ran", "sast", "--skips", str(skips)])
            findings = json.loads((results / "findings.triaged.json").read_text())

        whys = [(f.get("evidence") or {}).get("why") for f in findings]
        self.assertIn(reason, whys)


class CleanReportAndDurabilityTests(unittest.TestCase):
    """A genuinely clean scan must pass; a truncated one must not read as clean."""

    def test_clean_trivy_report_passes_with_results_absent_or_null(self) -> None:
        # Trivy tags Results `json:",omitempty"`, so a clean scan that detected
        # no packages omits the key or writes null. Both shapes became a phantom
        # HIGH unsupported_report and failed the gate: a dependency-free
        # dependency-sbom-scan-*.json, and container-scan-archive.json for a
        # distroless/scratch image with no OS packages.
        shapes = (
            {"Results": [{"Target": "Node.js", "Class": "lang-pkgs",
                          "Type": "node-pkg"}]},
            {"Results": []},
            {},
            {"Results": None},
        )
        names = {
            "dependency-sbom-scan-npm-npm.json": "dependency_scanning",
            "container-scan-archive.json": "container_scanning",
        }
        for name, category in names.items():
            for shape in shapes:
                with self.subTest(name=name, shape=shape):
                    with tempfile.TemporaryDirectory() as tmp:
                        results = Path(tmp)
                        payload = {
                            "SchemaVersion": 2,
                            "ArtifactName": "package-lock.json",
                            "ArtifactType": "filesystem",
                        }
                        payload.update(shape)
                        (results / name).write_text(json.dumps(payload))

                        output = io.StringIO()
                        with mock.patch("sys.stdout", output):
                            rc = normalize.main(
                                [str(results), "--gate", "high", "--ran", category]
                            )
                        coverage = json.loads(
                            (results / "scan-coverage.json").read_text()
                        )
                        findings = json.loads(
                            (results / "findings.triaged.json").read_text()
                        )

                    self.assertEqual(findings, [])
                    self.assertEqual(rc, 0)
                    self.assertIn("Gate verdict: PASSED", output.getvalue())
                    self.assertTrue(coverage["coverage_complete"])

    def test_document_that_is_trivy_shaped_in_no_way_is_still_unsupported(self) -> None:
        # The guard above must not widen into "anything unparseable is clean":
        # a report we cannot read may be hiding findings.
        with tempfile.TemporaryDirectory() as tmp:
            results = Path(tmp)
            (results / "container-scan-archive.json").write_text(
                '{"unexpected": "schema"}'
            )
            findings = normalize.normalize_reports(results)

        self.assertEqual([item["rule_id"] for item in findings], ["unsupported_report"])
        self.assertEqual(findings[0]["severity"], "HIGH")

    def test_truncated_recognized_report_is_not_scanned_and_clean(self) -> None:
        # `{}` parses, so a truncated gl-secret-detection-report.json satisfied
        # secret_detection's coverage and the category read as scanned and
        # clean. Gated at `critical` so the verdict cannot come from the HIGH's
        # severity — the coverage record itself must carry it.
        for payload in ("{}", "[]", "null"):
            with self.subTest(payload=payload):
                with tempfile.TemporaryDirectory() as tmp:
                    results = Path(tmp)
                    (results / "gl-secret-detection-report.json").write_text(payload)
                    rc = normalize.main(
                        [str(results), "--gate", "critical",
                         "--ran", "secret_detection"]
                    )
                    coverage = json.loads(
                        (results / "scan-coverage.json").read_text()
                    )
                    findings = json.loads(
                        (results / "findings.triaged.json").read_text()
                    )

                self.assertEqual(rc, 1)
                self.assertFalse(coverage["coverage_complete"])
                self.assertEqual(coverage["missing_report"], ["secret_detection"])
                self.assertEqual(
                    [item["rule_id"] for item in findings],
                    ["APPSEC-REPORT-UNPARSEABLE"],
                )

    def test_unreadable_report_is_incomplete_coverage_at_every_gate(self) -> None:
        # A report we cannot read is a COVERAGE fact, not a finding severity.
        # The parse failure is only a HIGH, so `--gate critical` and `--gate
        # none` reported PASSED, exit 0 and coverage_complete: true over a
        # scanner whose output was truncated. Neither .fpr nor .xml ever reached
        # the JSON validity check, and one valid JSON hid a truncated sibling.
        def truncated_fpr(results):
            (results / "fortify-sast.fpr").write_bytes(b"PK\x03\x04truncated")
            return "sast"

        def truncated_json(results):
            (results / "gl-container-scanning-report.json").write_text(
                '{"vulnerabilities": []}'
            )
            (results / "container-scan-archive.json").write_text(
                '{"SchemaVersion": 2, "Results": [{"Targ'
            )
            return "container_scanning"

        def truncated_xml(results):
            with zipfile.ZipFile(results / "fortify-sast.fpr", "w") as archive:
                archive.writestr("audit.fvdl", "<FVDL/>")
            (results / "fortify-sast.xml").write_text("<FVDL><Vulnerabil")
            return "sast"

        for shape in (truncated_fpr, truncated_json, truncated_xml):
            for gate in ("high", "critical", "none"):
                with self.subTest(shape=shape.__name__, gate=gate):
                    with tempfile.TemporaryDirectory() as tmp:
                        results = Path(tmp)
                        category = shape(results)
                        output = io.StringIO()
                        with mock.patch("sys.stdout", output):
                            rc = normalize.main(
                                [str(results), "--gate", gate, "--ran", category]
                            )
                        coverage = json.loads(
                            (results / "scan-coverage.json").read_text()
                        )
                        findings = json.loads(
                            (results / "findings.triaged.json").read_text()
                        )

                    printed = output.getvalue()
                    # The COVERAGE fact is recorded identically at every gate.
                    # The exit code is not: `none` is documented as always
                    # exit 0, so there the record and the verdict line carry it
                    # (SKILL.md Step 3 reads coverage_complete, not just $?).
                    self.assertFalse(coverage["coverage_complete"], printed)
                    self.assertEqual(coverage["missing_report"], [category])
                    self.assertNotIn("Gate verdict: PASSED", printed)
                    self.assertIn("NOT an all-clear", printed)
                    if gate == "none":
                        self.assertEqual(rc, 0, printed)
                    else:
                        self.assertNotEqual(rc, 0, printed)
                        self.assertFalse(coverage["gate_passed"], printed)
                    self.assertTrue(
                        [
                            item
                            for item in findings
                            if item["rule_id"] in normalize.PARSE_FAILURE_RULES
                        ],
                        findings,
                    )

    def test_registered_report_with_a_schema_we_cannot_read_is_not_coverage(self) -> None:
        # Same class as a truncated file: a report whose schema we do not
        # recognise (a future GitLab version, say) may be hiding every finding
        # it holds. It was a HIGH, so `--gate critical` exited 0 and recorded
        # coverage_complete: true over a scanner nothing had read.
        with tempfile.TemporaryDirectory() as tmp:
            results = Path(tmp)
            (results / "gl-container-scanning-report.json").write_text(
                '{"unexpected": "schema"}'
            )
            rc = normalize.main(
                [str(results), "--gate", "critical", "--ran", "container_scanning"]
            )
            coverage = json.loads((results / "scan-coverage.json").read_text())

        self.assertEqual(rc, 1)
        self.assertFalse(coverage["coverage_complete"])
        self.assertEqual(coverage["missing_report"], ["container_scanning"])

    def test_a_stray_unrecognized_file_does_not_invent_a_coverage_gap(self) -> None:
        # The boundary of the test above, and the no-false-alarm half of it:
        # _fallback_category guesses "sast" for any file it cannot place, so
        # routing every unsupported schema through coverage would let a stray
        # notes.json report SAST as unscanned. Only registered report names,
        # whose category is a fact rather than a guess, may do that.
        with tempfile.TemporaryDirectory() as tmp:
            results = Path(tmp)
            with zipfile.ZipFile(results / "fortify-sast.fpr", "w") as archive:
                archive.writestr("audit.fvdl", "<FVDL/>")
            (results / "notes.json").write_text('{"unexpected": "schema"}')
            rc = normalize.main(
                [str(results), "--gate", "critical", "--ran", "sast"]
            )
            coverage = json.loads((results / "scan-coverage.json").read_text())

        self.assertEqual(rc, 0)
        self.assertTrue(coverage["coverage_complete"])

    def test_clean_dependency_scanning_report_is_evidence_the_scanner_ran(self) -> None:
        # gl-dependency-scanning-report.json was in no category's report list,
        # so a valid clean one sitting on disk reported dependency_scanning as
        # APPSEC-REPORT-MISSING — "expected a report and did not [produce one]"
        # — and failed the gate on a genuinely clean scan.
        with tempfile.TemporaryDirectory() as tmp:
            results = Path(tmp)
            (results / "gl-dependency-scanning-report.json").write_text(
                '{"version":"15.0.4","vulnerabilities":[],"dependency_files":[]}'
            )
            output = io.StringIO()
            with mock.patch("sys.stdout", output):
                rc = normalize.main(
                    [str(results), "--gate", "high", "--ran", "dependency_scanning"]
                )
            coverage = json.loads((results / "scan-coverage.json").read_text())
            findings = json.loads((results / "findings.triaged.json").read_text())

        self.assertEqual(findings, [])
        self.assertEqual(rc, 0)
        self.assertIn("Gate verdict: PASSED", output.getvalue())
        self.assertTrue(coverage["coverage_complete"])

    def test_dependency_coverage_for_every_sbom_and_ds_report_combination(self) -> None:
        # A run may produce the SBOM, the DS report, both, or neither: only the
        # last is a gap. Registering the DS report must not make the SBOM path
        # (or the pair) read as incomplete.
        sbom = (
            "gl-sbom-python.cdx.json",
            '{"bomFormat":"CycloneDX","specVersion":"1.5","components":[]}',
        )
        report = (
            "gl-dependency-scanning-report.json",
            '{"version":"15.0.4","vulnerabilities":[],"dependency_files":[]}',
        )
        for present in ((), (sbom,), (report,), (sbom, report)):
            with self.subTest(present=[name for name, _ in present]):
                with tempfile.TemporaryDirectory() as tmp:
                    results = Path(tmp)
                    for name, payload in present:
                        (results / name).write_text(payload)
                    rc = normalize.main(
                        [str(results), "--gate", "high", "--ran", "dependency_scanning"]
                    )
                    coverage = json.loads(
                        (results / "scan-coverage.json").read_text()
                    )

                self.assertEqual(coverage["coverage_complete"], bool(present))
                self.assertEqual(rc, 0 if present else 1)

    def test_gate_none_verdict_is_not_a_bare_pass_when_coverage_is_incomplete(self) -> None:
        # `gate: none` keeps exit 0 (documented contract), so the VERDICT LINE is
        # what has to carry the truth. A bare `PASSED` over a category that never
        # ran reads as a clean scan to the human and to the model summarising it.
        with tempfile.TemporaryDirectory() as tmp:
            results = Path(tmp)
            output = io.StringIO()
            with mock.patch("sys.stdout", output):
                rc = normalize.main(
                    [str(results), "--gate", "none", "--ran", "sast"]
                )
            coverage = json.loads((results / "scan-coverage.json").read_text())

        printed = output.getvalue()
        self.assertNotIn("Gate verdict: PASSED", printed)
        self.assertIn("Gate verdict: INCOMPLETE COVERAGE", printed)
        self.assertIn("NOT an all-clear", printed)
        self.assertFalse(coverage["coverage_complete"])
        self.assertEqual(rc, 0, "gate none must stay exit 0 (documented contract)")

    def test_unrecognized_skip_category_warns_instead_of_vanishing(self) -> None:
        # A typo in a record_skip call dropped the line in silence, erasing a
        # coverage gap with no diagnostic anywhere.
        with tempfile.TemporaryDirectory() as tmp:
            results = Path(tmp)
            (results / "gl-secret-detection-report.json").write_text(
                '{"vulnerabilities": []}'
            )
            skips = results / "scan-skips"
            skips.write_text("dependancy_scanning\ttypo in a record_skip call\n")

            errors = io.StringIO()
            with mock.patch("sys.stderr", errors):
                rc = normalize.main(
                    [str(results), "--gate", "high", "--ran", "secret_detection",
                     "--skips", str(skips)]
                )

        self.assertIn("dependancy_scanning", errors.getvalue())
        self.assertEqual(rc, 0)

    def test_write_json_keeps_the_previous_file_on_an_interrupted_write(self) -> None:
        # findings.triaged.json is what the --only coverage union reads back, so
        # an in-place truncate turned an interrupted run into a lost gap.
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "findings.triaged.json"
            path.write_text('[{"category": "sast"}]')

            with mock.patch.object(
                normalize.json, "dump", side_effect=KeyboardInterrupt
            ):
                with self.assertRaises(KeyboardInterrupt):
                    normalize.write_json(path, ["replacement"])

            self.assertEqual(json.loads(path.read_text()), [{"category": "sast"}])
            # The abandoned temp file must not be read as a scanner report.
            self.assertEqual(normalize.normalize_reports(Path(tmp)), [])
