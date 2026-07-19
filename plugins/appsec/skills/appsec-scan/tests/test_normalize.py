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

    def test_sbom_is_supported_with_zero_findings(self):
        self.write_json(
            "gl-sbom-python.cdx.json",
            {"bomFormat": "CycloneDX", "specVersion": "1.5", "components": []},
        )

        findings = normalize.normalize_reports(self.results)

        self.assertEqual(findings, [])

    def test_unrecognized_empty_json_is_unsupported(self):
        self.write_json("unknown.json", {})

        findings = normalize.normalize_reports(self.results)

        self.assertEqual(len(findings), 1)
        self.assertEqual(findings[0]["severity"], "HIGH")
        self.assertEqual(findings[0]["rule_id"], "unsupported_report")

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
        for name in normalize.OUTPUT_FILES:
            self.assertTrue((self.results / name).exists())


if __name__ == "__main__":
    unittest.main()
