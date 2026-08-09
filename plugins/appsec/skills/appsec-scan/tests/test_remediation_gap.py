"""Registry-gap remediation: only block when the mirror actually said 'absent'.

The failure this guards against is subtle. If an unreachable registry were treated
as 'absent', every dependency finding would become a mirroring request the moment
the network hiccuped -- sending developers to chase packages that are already
there, and quietly removing findings from the fix loop's reach.
"""

from __future__ import annotations

import importlib.util
import json
import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

SKILL_DIR = Path(__file__).resolve().parents[1]
SCRIPTS = SKILL_DIR / "scripts"
RESOLVE_PACKAGE = SCRIPTS / "resolve-package.sh"

_spec = importlib.util.spec_from_file_location("normalize", SCRIPTS / "normalize.py")
normalize = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(normalize)

_spec2 = importlib.util.spec_from_file_location(
    "check_remediation", SCRIPTS / "check-remediation.py"
)
check_remediation = importlib.util.module_from_spec(_spec2)
_spec2.loader.exec_module(check_remediation)


def dep_finding(package="lodash", fixed="4.17.21", manifest="package-lock.json", severity="HIGH"):
    return {
        "category": "dependency_scanning",
        "severity": severity,
        "location": {"package": package},
        "evidence": {
            "package": package,
            "installed_version": "4.17.11",
            "fixed_version": fixed,
            "manifest": manifest,
        },
        "rule_id": "CVE-2020-8203",
    }


class EcosystemInferenceTest(unittest.TestCase):
    def test_infers_from_evidence_manifest_not_location(self) -> None:
        """Dependency findings carry {'package': name} as location, never the file."""
        self.assertEqual(check_remediation.infer_ecosystem(dep_finding()), "npm")
        self.assertEqual(
            check_remediation.infer_ecosystem(dep_finding(manifest="pom.xml")), "maven"
        )
        self.assertEqual(
            check_remediation.infer_ecosystem(dep_finding(manifest="requirements.txt")),
            "pypi",
        )
        self.assertEqual(
            check_remediation.infer_ecosystem(dep_finding(manifest="go.mod")), "go"
        )

    def test_nested_manifest_path_still_resolves(self) -> None:
        self.assertEqual(
            check_remediation.infer_ecosystem(dep_finding(manifest="services/api/pom.xml")),
            "maven",
        )

    def test_unknown_manifest_yields_none(self) -> None:
        self.assertIsNone(check_remediation.infer_ecosystem(dep_finding(manifest="Makefile")))

    def test_container_findings_are_never_targeted(self) -> None:
        """OS packages are fixed by rebasing the image, not from a language registry."""
        container = dep_finding()
        container["category"] = "container_scanning"
        self.assertEqual(check_remediation.collect_targets([container]), {})


class TriageRegistryGapTest(unittest.TestCase):
    def _triage(self, finding, availability):
        return normalize.triage_findings([json.loads(json.dumps(finding))], availability)[0]

    def test_absent_becomes_blocked_registry_gap(self) -> None:
        result = self._triage(dep_finding(), {"npm|lodash|4.17.21": "absent"})
        self.assertEqual(result["remediation_status"], "blocked_registry_gap")
        self.assertEqual(result["verification_status"], "not_fixable_locally")
        self.assertIn("4.17.21", result["triage_reason"])

    def test_unknown_is_not_treated_as_a_gap(self) -> None:
        """An unreachable registry is not evidence the package is missing."""
        result = self._triage(dep_finding(), {"npm|lodash|4.17.21": "unknown"})
        self.assertNotEqual(result["remediation_status"], "blocked_registry_gap")

    def test_available_stays_fixable(self) -> None:
        result = self._triage(dep_finding(), {"npm|lodash|4.17.21": "available"})
        self.assertEqual(result["remediation_status"], "fixable_candidate")

    def test_no_availability_data_changes_nothing(self) -> None:
        result = self._triage(dep_finding(), {})
        self.assertEqual(result["remediation_status"], "fixable_candidate")

    def test_gap_finding_still_counts_toward_the_gate(self) -> None:
        """A vulnerability you cannot fix is still a vulnerability."""
        result = self._triage(dep_finding(), {"npm|lodash|4.17.21": "absent"})
        self.assertTrue(normalize.gate_failed([result], "high"))

    def test_missing_fixed_version_keeps_external_dependency_status(self) -> None:
        finding = dep_finding()
        del finding["evidence"]["fixed_version"]
        result = self._triage(finding, {"npm|lodash|4.17.21": "absent"})
        self.assertEqual(result["remediation_status"], "blocked_external_dependency")


class ResolvePackageVerdictTest(unittest.TestCase):
    """resolve-package.sh must never invent a verdict it cannot support."""

    def _run(self, *args):
        proc = subprocess.run(
            ["bash", str(RESOLVE_PACKAGE), *args],
            capture_output=True,
            text=True,
            check=True,
        )
        return proc.stdout.strip()

    def test_no_template_is_unknown(self) -> None:
        self.assertEqual(self._run("npm", "lodash", "4.17.21", ""), "unknown")

    def test_no_package_is_unknown(self) -> None:
        self.assertEqual(self._run("npm", "", "4.17.21", "https://x/{package}"), "unknown")

    def test_unreachable_host_is_unknown_not_absent(self) -> None:
        verdict = self._run(
            "npm",
            "lodash",
            "4.17.21",
            "http://127.0.0.1:9/{package}/{version}",
        )
        self.assertEqual(verdict, "unknown")

    def test_no_token_curl_failure_is_unknown_with_zero_exit(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            fake_curl = Path(tmp) / "curl"
            fake_curl.write_text("#!/bin/sh\nexit 7\n", encoding="utf-8")
            fake_curl.chmod(0o755)
            env = os.environ.copy()
            env["PATH"] = f"{tmp}{os.pathsep}{env['PATH']}"

            proc = subprocess.run(
                [
                    "bash",
                    str(RESOLVE_PACKAGE),
                    "npm",
                    "lodash",
                    "4.17.21",
                    "https://registry.example/{package}/{version}",
                ],
                capture_output=True,
                text=True,
                env=env,
            )

        self.assertEqual(proc.returncode, 0)
        self.assertEqual(proc.stdout.strip(), "unknown")

    def test_go_module_path_uses_goproxy_case_encoding(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            fake_curl = Path(tmp) / "curl"
            url_log = Path(tmp) / "url.log"
            fake_curl.write_text(
                "#!/bin/sh\n"
                "last=\n"
                "for arg do\n"
                "  last=$arg\n"
                "done\n"
                "printf '%s\\n' \"$last\" > \"$CURL_URL_LOG\"\n"
                "printf '200'\n",
                encoding="utf-8",
            )
            fake_curl.chmod(0o755)
            env = os.environ.copy()
            env["PATH"] = f"{tmp}{os.pathsep}{env['PATH']}"
            env["CURL_URL_LOG"] = str(url_log)

            proc = subprocess.run(
                [
                    "bash",
                    str(RESOLVE_PACKAGE),
                    "go",
                    "github.com/Sirupsen/logrus",
                    "1.9.3",
                    "https://proxy.example/{module}/@v/{version}.info",
                ],
                capture_output=True,
                text=True,
                env=env,
                check=True,
            )

            self.assertEqual(proc.stdout.strip(), "available")
            self.assertEqual(
                url_log.read_text(encoding="utf-8").strip(),
                "https://proxy.example/github.com/!sirupsen/logrus/@v/1.9.3.info",
            )

    def test_maven_without_coordinates_is_unknown(self) -> None:
        """group:artifact is required to lay out a maven path; do not guess."""
        self.assertEqual(
            self._run("maven", "nogroup", "1.0", "https://x/{group_path}/{artifact}/"),
            "unknown",
        )


class ResolvePackageStrippedPathTest(unittest.TestCase):
    """The probe must hold its contract on a host that carries curl and little else.

    An airgapped dev box is not guaranteed coreutils. Every case below used to
    abort with 127 and print no verdict at all -- except the listing case, which
    answered `absent` on the strength of a `grep` that never ran, manufacturing a
    mirroring request for a package the registry had actually served.
    """

    # Only builtins: this stub also runs under the stripped PATH.
    CURL_STUB = (
        "#!/bin/sh\n"
        "out=\n"
        "url=\n"
        "while [ $# -gt 0 ]; do\n"
        "  case $1 in -o) out=$2; shift ;; esac\n"
        "  url=$1\n"
        "  shift\n"
        "done\n"
        '[ -n "$out" ] && printf \'%s\\n\' "${CURL_BODY:-}" > "$out"\n'
        '[ -n "${CURL_URL_LOG:-}" ] && printf \'%s\\n\' "$url" > "$CURL_URL_LOG"\n'
        "printf '200'\n"
    )

    def _run(self, args, tmp, body=""):
        bin_dir = Path(tmp) / "bin"
        bin_dir.mkdir()
        curl = bin_dir / "curl"
        curl.write_text(self.CURL_STUB, encoding="utf-8")
        curl.chmod(0o755)
        # mktemp is the one tool the script cannot do without: curl needs a real
        # file to write the response body into. Nothing else may be required.
        (bin_dir / "mktemp").symlink_to(shutil.which("mktemp"))
        url_log = Path(tmp) / "url.log"

        proc = subprocess.run(
            [shutil.which("bash") or "/bin/bash", str(RESOLVE_PACKAGE), *args],
            capture_output=True,
            text=True,
            env={
                "PATH": str(bin_dir),
                "CURL_URL_LOG": str(url_log),
                "CURL_BODY": body,
            },
        )
        logged = url_log.read_text(encoding="utf-8").strip() if url_log.exists() else ""
        return proc, logged

    def test_maven_group_path_needs_no_tr(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            proc, url = self._run(
                ["maven", "com.foo.bar:baz", "1.0", "http://x/{group_path}/{artifact}/{version}/"],
                tmp,
            )
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertEqual(proc.stdout.strip(), "available")
        self.assertEqual(url, "http://x/com/foo/bar/baz/1.0/")

    def test_go_case_encoding_needs_no_sed_or_tr(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            proc, url = self._run(
                ["go", "github.com/Sirupsen/logrus", "1.9.3", "http://p/{module}/@v/{version}.info"],
                tmp,
            )
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertEqual(url, "http://p/github.com/!sirupsen/logrus/@v/1.9.3.info")

    def test_listing_body_match_needs_no_grep(self) -> None:
        # No {version} in the template, so the verdict rests on the body.
        with tempfile.TemporaryDirectory() as tmp:
            hit, _ = self._run(
                ["npm", "lodash", "4.17.21", "http://x/simple/{package}/"],
                tmp,
                body="lodash-4.17.21.tgz",
            )
        with tempfile.TemporaryDirectory() as tmp:
            miss, _ = self._run(
                ["npm", "lodash", "9.9.9", "http://x/simple/{package}/"],
                tmp,
                body="lodash-4.17.21.tgz",
            )
        self.assertEqual((hit.returncode, hit.stdout.strip()), (0, "available"), hit.stderr)
        self.assertEqual((miss.returncode, miss.stdout.strip()), (0, "absent"), miss.stderr)

    def test_no_curl_at_all_is_unknown_with_zero_exit(self) -> None:
        proc = subprocess.run(
            [
                shutil.which("bash") or "/bin/bash",
                str(RESOLVE_PACKAGE),
                "npm",
                "lodash",
                "4.17.21",
                "http://x/{package}/{version}",
            ],
            capture_output=True,
            text=True,
            env={"PATH": "/nonexistent"},
        )
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertEqual(proc.stdout.strip(), "unknown")


class CheckRemediationOutputTest(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.results = Path(self.tmp.name)

    def _write(self, findings):
        (self.results / "findings.triaged.json").write_text(
            json.dumps(findings), encoding="utf-8"
        )

    def test_no_registries_writes_empty_map(self) -> None:
        self._write([dep_finding()])
        rc = check_remediation.main([str(self.results)])
        self.assertEqual(rc, 0)
        out = json.loads((self.results / "registry-availability.json").read_text())
        self.assertEqual(out, {})

    def test_ecosystem_without_declared_mirror_is_unknown(self) -> None:
        self._write([dep_finding(manifest="pom.xml")])
        rc = check_remediation.main(
            [str(self.results), "--registries", json.dumps({"npm": "https://x/{package}"})]
        )
        self.assertEqual(rc, 0)
        out = json.loads((self.results / "registry-availability.json").read_text())
        self.assertEqual(out, {"maven|lodash|4.17.21": "unknown"})

    def test_malformed_registries_json_degrades_quietly(self) -> None:
        self._write([dep_finding()])
        self.assertEqual(check_remediation.main([str(self.results), "--registries", "{oops"]), 0)
        self.assertEqual(
            json.loads((self.results / "registry-availability.json").read_text()), {}
        )


class FortifyRemediationTest(unittest.TestCase):
    """Fortify keeps guidance in <Description classID>, away from <Vulnerability>."""

    FVDL = """<?xml version="1.0"?>
    <FVDL>
      <Vulnerabilities>
        <Vulnerability>
          <ClassInfo>
            <ClassID>ABC-123</ClassID>
            <Type>SQL Injection</Type>
            <DefaultSeverity>4.0</DefaultSeverity>
          </ClassInfo>
          <InstanceInfo><FileName>src/db.py</FileName><LineStart>42</LineStart></InstanceInfo>
        </Vulnerability>
      </Vulnerabilities>
      <Description classID="ABC-123">
        <Abstract>Untrusted input reaches a SQL query.</Abstract>
        <Recommendations>Use parameterised queries;
        never concatenate user input into SQL.</Recommendations>
      </Description>
    </FVDL>"""

    def _parse(self, xml):
        from xml.etree import ElementTree as ET

        return normalize.parse_fvdl_root(ET.fromstring(xml), "fortify-sast.fpr")

    def test_recommendations_are_attached_to_the_finding(self) -> None:
        finding = self._parse(self.FVDL)[0]
        self.assertIn("parameterised queries", finding["evidence"]["solution"])
        self.assertEqual(finding["category"], "sast")

    def test_whitespace_is_collapsed(self) -> None:
        solution = self._parse(self.FVDL)[0]["evidence"]["solution"]
        self.assertNotIn("\n", solution)
        self.assertNotIn("  ", solution)

    def test_missing_description_is_not_an_error(self) -> None:
        xml = self.FVDL.replace('classID="ABC-123"', 'classID="OTHER"')
        finding = self._parse(xml)[0]
        self.assertNotIn("solution", finding["evidence"])

    def test_sast_findings_never_become_registry_gaps(self) -> None:
        """SAST is fixed by editing code; no registry is involved."""
        finding = self._parse(self.FVDL)[0]
        triaged = normalize.triage_findings(
            [json.loads(json.dumps(finding))], {"npm|x|1": "absent"}
        )[0]
        self.assertNotEqual(triaged["remediation_status"], "blocked_registry_gap")


if __name__ == "__main__":
    unittest.main()
