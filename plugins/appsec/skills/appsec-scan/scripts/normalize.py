#!/usr/bin/env python3
"""Normalize AppSec scanner reports into a small, stable finding schema."""

import argparse
import hashlib
import json
import math
import os
from pathlib import Path
import re
import sys
from xml.etree import ElementTree as ET
import zipfile

CATEGORIES = (
    "sast",
    "dependency_scanning",
    "secret_detection",
    "container_scanning",
)
SEVERITIES = ("CRITICAL", "HIGH", "MEDIUM", "LOW")
GATE_LEVELS = {
    "critical": {"CRITICAL"},
    "high": {"CRITICAL", "HIGH"},
    "medium": {"CRITICAL", "HIGH", "MEDIUM"},
    "none": set(),
}
OUTPUT_FILES = {
    "findings.normalized.json",
    "findings.triaged.json",
    "scan-coverage.json",
}
REPORT_CATEGORIES = {
    "fortify-sast.fpr": "sast",
    "gl-secret-detection-report.json": "secret_detection",
    "gl-container-scanning-report.json": "container_scanning",
    "container-scan-archive.json": "container_scanning",
}
TEST_PATH_RE = re.compile(
    r"(?:^|/)(?:test|tests|vendor|node_modules|dist|build)(?:/|$)", re.IGNORECASE
)
SECRET_VALUE_RE = re.compile(
    r"(?:glpat-[A-Za-z0-9_-]+|(?:AKIA|ASIA)[A-Z0-9]{16}|"
    r"(?<![A-Za-z0-9+/_-])[A-Za-z0-9+/_-]{32,}={0,2}"
    r"(?![A-Za-z0-9+/=_-]))"
)

def _json_text(path):
    text = Path(path).read_text(encoding="utf-8", errors="replace")
    return "\n".join(
        line for line in text.splitlines() if not line.startswith("##tool")
    )

def read_json_loose(path):
    text = _json_text(path)
    return json.loads(text or "null")

def write_json(path, value):
    with Path(path).open("w", encoding="utf-8") as stream:
        json.dump(value, stream, indent=2, sort_keys=True)
        stream.write("\n")

def fingerprint(parts):
    raw = "|".join(str(part or "") for part in parts)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16]

def normalize_severity(value, rule_id=None):
    if value is None:
        text = ""
    else:
        text = str(value).strip().upper()
    aliases = {
        "BLOCKER": "CRITICAL",
        "FATAL": "CRITICAL",
        "ERROR": "HIGH",
        "IMPORTANT": "HIGH",
        "WARN": "MEDIUM",
        "WARNING": "MEDIUM",
        "MODERATE": "MEDIUM",
        "INFO": "LOW",
        "INFORMATIONAL": "LOW",
    }
    if text in SEVERITIES:
        return text
    if text == "UNKNOWN":
        return text
    if text in aliases:
        return aliases[text]
    try:
        numeric = float(text)
    except (TypeError, ValueError):
        numeric = None
    if numeric is None or not math.isfinite(numeric):
        print(
            "WARNING: unrecognized severity for rule "
            + str(rule_id or "unknown_rule"),
            file=sys.stderr,
        )
        return "UNKNOWN"
    if numeric >= 4.0:
        return "CRITICAL"
    if numeric >= 3.0:
        return "HIGH"
    if numeric >= 2.0:
        return "MEDIUM"
    return "LOW"

def _category_for_scanner(scanner):
    scanner = str(scanner or "").lower()
    if any(word in scanner for word in ("secret", "gitleaks")):
        return "secret_detection"
    if any(word in scanner for word in ("trivy", "container")):
        return "container_scanning"
    if any(word in scanner for word in ("dependency", "gemnasium", "sca")):
        return "dependency_scanning"
    return "sast"

def _clean_location(location, fallback_file=None):
    location = location if isinstance(location, dict) else {}
    if location.get("file"):
        return {"file": location.get("file"), "line": location.get("line")}
    if location.get("image"):
        return {"image": location.get("image")}
    if location.get("package"):
        return {"package": location.get("package")}
    return {"file": str(fallback_file or "unknown"), "line": None}

def new_finding(
    scanner,
    name,
    severity,
    location=None,
    evidence=None,
    category=None,
    rule_id=None,
):
    evidence = dict(evidence or {})
    rule_id = rule_id or evidence.pop("rule_id", None) or "unknown_rule"
    category = category or _category_for_scanner(scanner)
    has_context = bool(evidence) or bool(
        isinstance(location, dict)
        and any(location.get(key) for key in ("file", "image", "package"))
    )
    location = _clean_location(location)
    normalized = (
        "LOW"
        if severity is None and not has_context
        else normalize_severity(severity, rule_id)
    )
    stable = fingerprint(
        [
            category,
            scanner,
            rule_id,
            name,
            normalized,
            json.dumps(location, sort_keys=True, separators=(",", ":")),
            evidence.get("package"),
        ]
    )
    return {
        "category": category,
        "severity": normalized,
        "verification_status": (
            "needs_human_review" if normalized == "UNKNOWN" else "unverified"
        ),
        "remediation_status": "unassessed",
        "triage_reason": "Not triaged.",
        "location": location,
        "evidence": evidence,
        "fingerprint": stable,
        "scanner": str(scanner or "unknown"),
        "rule_id": str(rule_id),
        "name": str(name or "Security finding"),
    }

def _report_category(path):
    name = Path(path).name.lower()
    if name.startswith("gl-sbom-") and name.endswith(".cdx.json"):
        return "dependency_scanning"
    return REPORT_CATEGORIES.get(name)

def _fallback_category(path):
    name = Path(path).name.lower()
    if "secret" in name:
        return "secret_detection"
    if "container" in name or "trivy" in name or "image" in name:
        return "container_scanning"
    if "dependency" in name or "sbom" in name or "sca" in name:
        return "dependency_scanning"
    return "sast"

def _gitlab_location(vulnerability, category, path):
    raw = vulnerability.get("location") or {}
    dependency = raw.get("dependency") or {}
    package = dependency.get("package") or {}
    package_name = package.get("name") or raw.get("package")
    image = raw.get("image")
    if isinstance(image, dict):
        image = image.get("name") or image.get("path")
    file_name = raw.get("file") or raw.get("path")
    line = raw.get("start_line") or raw.get("line")
    if category == "container_scanning" and image:
        return {"image": image}
    if category in {"dependency_scanning", "container_scanning"} and package_name:
        return {"package": package_name}
    if file_name:
        return {"file": file_name, "line": line}
    return {"file": str(path), "line": None}

def parse_generic_json(path, data, category=None):
    path = Path(path)
    findings = []
    if isinstance(data, dict) and isinstance(data.get("vulnerabilities"), list):
        category = category or _fallback_category(path)
        scanner_data = ((data.get("scan") or {}).get("scanner") or {})
        scanner = scanner_data.get("id") or scanner_data.get("name") or path.stem
        for vulnerability in data["vulnerabilities"]:
            if not isinstance(vulnerability, dict):
                continue
            identifiers = vulnerability.get("identifiers") or []
            first_identifier = identifiers[0] if identifiers else {}
            rule_id = (
                first_identifier.get("value")
                if isinstance(first_identifier, dict)
                else None
            ) or vulnerability.get("id") or vulnerability.get("cve")
            raw_location = vulnerability.get("location") or {}
            dependency = raw_location.get("dependency") or {}
            package = dependency.get("package") or {}
            evidence = {
                "description": vulnerability.get("description"),
                "solution": vulnerability.get("solution"),
                "raw_report": str(path),
            }
            package_name = package.get("name") or raw_location.get("package")
            if package_name:
                evidence["package"] = package_name
            if dependency.get("version"):
                evidence["installed_version"] = dependency.get("version")
            fixed = vulnerability.get("fixed_version")
            if fixed is not None:
                evidence["fixed_version"] = fixed
            findings.append(
                new_finding(
                    scanner,
                    vulnerability.get("name")
                    or vulnerability.get("message")
                    or "Security finding",
                    vulnerability.get("severity"),
                    _gitlab_location(vulnerability, category, path),
                    evidence,
                    category=category,
                    rule_id=rule_id,
                )
            )

    if isinstance(data, dict) and isinstance(data.get("Results"), list):
        for result in data["Results"]:
            if not isinstance(result, dict):
                continue
            target = result.get("Target") or str(path)
            for vulnerability in result.get("Vulnerabilities") or []:
                if not isinstance(vulnerability, dict):
                    continue
                package = vulnerability.get("PkgName")
                evidence = {
                    "package": package,
                    "installed_version": vulnerability.get("InstalledVersion"),
                    "fixed_version": vulnerability.get("FixedVersion"),
                    "description": vulnerability.get("Description"),
                    "raw_report": str(path),
                }
                findings.append(
                    new_finding(
                        "trivy",
                        vulnerability.get("Title")
                        or vulnerability.get("VulnerabilityID")
                        or "Container vulnerability",
                        vulnerability.get("Severity"),
                        {"image": target} if target else {"package": package},
                        evidence,
                        category="container_scanning",
                        rule_id=vulnerability.get("VulnerabilityID"),
                    )
                )
    return findings

def is_supported_clean_json(data, path=None):
    if data in (None, [], {}):
        return True
    if not isinstance(data, dict):
        return False
    name = Path(path).name.lower() if path else ""
    if name.startswith("gl-sbom-") and name.endswith(".cdx.json"):
        return data.get("bomFormat") == "CycloneDX" or isinstance(
            data.get("components"), list
        )
    if data.get("bomFormat") == "CycloneDX":
        return True
    return (
        isinstance(data.get("vulnerabilities"), list)
        or isinstance(data.get("Results"), list)
        or isinstance(data.get("results"), list)
    )

def strip_ns(tag):
    return str(tag).rsplit("}", 1)[-1]

def child_by_name(element, name):
    if element is None:
        return None
    wanted = name.lower()
    for child in element:
        if strip_ns(child.tag).lower() == wanted:
            return child
    return None

def _node_at_local_path(element, path):
    node = element
    for part in path.split("/"):
        node = child_by_name(node, part)
        if node is None:
            return None
    return node

def first_text(element, names):
    if element is None:
        return None
    for name in names:
        node = _node_at_local_path(element, name)
        if node is None:
            wanted = name.rsplit("/", 1)[-1].lower()
            for candidate in element.iter():
                if strip_ns(candidate.tag).lower() == wanted:
                    node = candidate
                    break
        if node is not None and node.text and node.text.strip():
            return node.text.strip()
    return None

def parse_fvdl_root(root, path):
    path = Path(path)
    findings = []
    for vulnerability in root.iter():
        if strip_ns(vulnerability.tag).lower() != "vulnerability":
            continue
        class_info = child_by_name(vulnerability, "ClassInfo")
        instance_info = child_by_name(vulnerability, "InstanceInfo")
        name = first_text(class_info, ["Type", "Subtype", "Kingdom"])
        severity = first_text(
            class_info, ["DefaultSeverity", "Friority", "Priority", "Severity"]
        )
        file_name = first_text(
            instance_info,
            ["FileName", "FunctionDeclarationSourceLocation/Path", "Path"],
        )
        line = first_text(
            instance_info,
            ["LineStart", "FunctionDeclarationSourceLocation/Line", "Line"],
        )
        rule_id = first_text(class_info, ["ClassID", "RuleID"])
        findings.append(
            new_finding(
                "fortify",
                name or "Fortify vulnerability",
                severity or "HIGH",
                {"file": file_name or str(path), "line": line},
                {"raw_report": str(path)},
                category="sast",
                rule_id=rule_id,
            )
        )
    return findings

def parse_generic_xml(path):
    path = Path(path)
    root = ET.parse(path).getroot()
    if strip_ns(root.tag).lower() == "fvdl":
        return parse_fvdl_root(root, path)
    findings = []
    for element in root.iter():
        element_tag = strip_ns(element.tag).lower()
        if element_tag not in {"violation", "rule", "issue", "vulnerability"}:
            continue
        name = first_text(
            element, ["Name", "Message", "Category", "RuleID", "Rule"]
        ) or element.get("name") or element_tag
        severity = first_text(
            element, ["Severity", "Priority"]
        ) or element.get("severity")
        file_name = first_text(
            element, ["File", "FileName", "Path"]
        ) or element.get("file") or str(path)
        line = first_text(element, ["Line", "LineStart"]) or element.get("line")
        rule_id = first_text(element, ["RuleID", "Rule"]) or element.get("rule")
        findings.append(
            new_finding(
                path.stem,
                name,
                severity,
                {"file": file_name, "line": line},
                {"raw_report": str(path)},
                category=_fallback_category(path),
                rule_id=rule_id,
            )
        )
    return findings

def parse_fpr(path):
    path = Path(path)
    findings = []
    with zipfile.ZipFile(path) as archive:
        members = [name for name in archive.namelist() if name.lower().endswith(".fvdl")]
        members.sort(key=lambda name: Path(name).name.lower() != "audit.fvdl")
        for member in members:
            root = ET.fromstring(archive.read(member))
            findings.extend(parse_fvdl_root(root, path))
    return findings

def unsupported_report_finding(path):
    return new_finding(
        "normalizer",
        "Unsupported scanner report schema",
        "HIGH",
        {"file": str(path), "line": None},
        {"raw_report": str(path)},
        category=_fallback_category(path),
        rule_id="unsupported_report",
    )

def parse_failure_finding(path, error):
    rule_id = "APPSEC-REPORT-PARSE-FAILED"
    if _report_category(path) and Path(path).suffix.lower() == ".json":
        rule_id = "APPSEC-REPORT-UNPARSEABLE"
    return new_finding(
        "normalizer",
        "Failed to parse " + Path(path).name,
        "HIGH",
        {"file": str(path), "line": None},
        {"error": str(error), "raw_report": str(path)},
        category=_report_category(path) or _fallback_category(path),
        rule_id=rule_id,
    )

def normalize_reports(results_dir):
    """Normalize every supported report; one bad file can never stop the run."""
    findings = []
    for path in sorted(Path(results_dir).rglob("*")):
        if any(part in path.parts for part in ("bin", "catalog")):
            continue
        if not path.is_file() or path.name in OUTPUT_FILES:
            continue
        name = path.name.lower()
        try:
            if name == "fortify-sast.fpr":
                findings.extend(parse_fpr(path))
            elif name in {
                "gl-secret-detection-report.json",
                "gl-container-scanning-report.json",
            }:
                data = read_json_loose(path)
                parsed = parse_generic_json(path, data, REPORT_CATEGORIES[name])
                findings.extend(parsed)
                if not parsed and not is_supported_clean_json(data, path):
                    findings.append(unsupported_report_finding(path))
            elif name == "container-scan-archive.json":
                data = read_json_loose(path)
                parsed = parse_generic_json(path, data, "container_scanning")
                findings.extend(parsed)
                if not parsed and not is_supported_clean_json(data, path):
                    findings.append(unsupported_report_finding(path))
            elif name.startswith("gl-sbom-") and name.endswith(".cdx.json"):
                data = read_json_loose(path)
                if not is_supported_clean_json(data, path):
                    findings.append(unsupported_report_finding(path))
            elif name.endswith(".json"):
                data = read_json_loose(path)
                parsed = parse_generic_json(path, data, _fallback_category(path))
                findings.extend(parsed)
                if not parsed:
                    findings.append(unsupported_report_finding(path))
            elif name.endswith(".xml") or name.endswith(".fvdl"):
                parsed = parse_generic_xml(path)
                findings.extend(parsed)
                if not parsed:
                    findings.append(unsupported_report_finding(path))
        except Exception as error:  # Deliberate ceiling: vendor parse failures become findings.
            findings.append(parse_failure_finding(path, error))
    return findings

def triage_findings(findings):
    for finding in findings:
        location = finding.get("location") or {}
        evidence = finding.get("evidence") or {}
        rule_id = finding.get("rule_id")
        category = finding.get("category")
        path = str(location.get("file") or "").replace("\\", "/")
        concrete = any(location.get(key) for key in ("file", "image", "package"))
        if finding.get("severity") == "UNKNOWN":
            finding["verification_status"] = "needs_human_review"
            finding["remediation_status"] = "needs_user_decision"
            finding["triage_reason"] = "Scanner severity requires human review."
        elif rule_id in {
            "APPSEC-REPORT-MISSING",
            "APPSEC-REPORT-PARSE-FAILED",
            "APPSEC-REPORT-UNPARSEABLE",
            "unsupported_report",
        }:
            finding["verification_status"] = "needs_human_review"
            finding["remediation_status"] = "parser_or_report_fix_required"
            finding["triage_reason"] = (
                "Scanner coverage is incomplete until the report is supplied or supported."
            )
        elif category in {"dependency_scanning", "container_scanning"} and not evidence.get(
            "fixed_version"
        ):
            finding["verification_status"] = "not_fixable_locally"
            finding["remediation_status"] = "blocked_external_dependency"
            finding["triage_reason"] = "The scanner did not report a fixed version."
        elif TEST_PATH_RE.search(path):
            finding["verification_status"] = "likely_false_positive"
            finding["remediation_status"] = "needs_user_decision"
            finding["triage_reason"] = (
                "The location is test, vendored, dependency, distribution, or build output."
            )
        elif normalize_severity(finding.get("severity")) in {"CRITICAL", "HIGH"} and concrete:
            finding["verification_status"] = "confirmed_true_positive"
            finding["remediation_status"] = "fixable_candidate"
            finding["triage_reason"] = "High-impact finding includes a concrete location."
        else:
            finding["verification_status"] = "needs_human_review"
            finding["remediation_status"] = "unassessed"
            finding["triage_reason"] = "Evidence is insufficient for automatic classification."
    return findings

def _gate_severities(gate):
    if isinstance(gate, dict):
        values = (gate.get("ci_gate") or {}).get("severities", ["CRITICAL", "HIGH"])
        return {normalize_severity(value) for value in values}
    if isinstance(gate, (set, list, tuple)):
        return {normalize_severity(value) for value in gate}
    return GATE_LEVELS.get(str(gate or "high").lower(), GATE_LEVELS["high"])

def gate_failed(findings, gate="high"):
    failing = _gate_severities(gate)
    if not failing:
        return False
    for item in findings:
        severity = normalize_severity(item.get("severity"))
        if severity in failing or severity == "UNKNOWN":
            return True
    return False

def redact_value(value, matched_only=False):
    """Keep only a four-character hint for secret finding text."""
    if value is None:
        return None
    text = str(value)
    if matched_only:
        return SECRET_VALUE_RE.sub("***", text)
    if text.endswith("...") and len(text) <= 7:
        return text
    return text[:4] + "..."

def _redact_structure(value, matched_only=False):
    if isinstance(value, dict):
        return {
            key: _redact_structure(item, matched_only)
            for key, item in value.items()
        }
    if isinstance(value, list):
        return [_redact_structure(item, matched_only) for item in value]
    if isinstance(value, str):
        return redact_value(value, matched_only)
    return value

def redact_secret_findings(findings, matched_only=False):
    for finding in findings:
        # Capture before the blanket pass below, which would otherwise redact
        # this tool's own remediation text out from under us.
        _evidence = finding.get("evidence")
        _why = _evidence.get("why") if isinstance(_evidence, dict) else None
        for key, value in list(finding.items()):
            finding[key] = _redact_structure(value, True)
        finding_matched_only = (
            matched_only or finding.get("category") != "secret_detection"
        )
        for key in ("name", "title", "description"):
            if key in finding:
                finding[key] = redact_value(finding.get(key), finding_matched_only)
        # `why` is remediation text this tool wrote itself, never scanner data.
        # Redacting it mangled the very image path the user needs to act on
        # ("Could not pull registry.gitlab.***"), defeating the guidance.
        finding["evidence"] = _redact_structure(
            finding.get("evidence") or {}, finding_matched_only
        )
        if _why is not None and isinstance(finding.get("evidence"), dict):
            finding["evidence"]["why"] = _why
        finding["location"] = _redact_structure(
            finding.get("location") or {}, True
        )
    return findings

def load_skip_reasons(path):
    """category -> actionable reason, written by run-scan.sh when a scanner bails.

    A coverage finding that just says "report missing" leaves the user with no
    idea what to do. The reason names the fix (write a Dockerfile, set
    FORTIFY_LANGUAGE) so the gap is actionable rather than merely visible.
    """
    reasons = {}
    if not path:
        return reasons
    try:
        for line in Path(path).read_text(encoding="utf-8", errors="replace").splitlines():
            category, _, reason = line.partition("\t")
            if category in CATEGORIES and reason.strip():
                reasons[category] = reason.strip()
    except OSError:
        pass
    return reasons

def coverage_findings(results_dir, scanners_run, existing_findings=None, skip_reasons=None):
    reports = {category: [] for category in CATEGORIES}
    for path in Path(results_dir).rglob("*"):
        # ponytail: cached tools and catalog payloads are not scanner evidence.
        if any(part in path.parts for part in ("bin", "catalog")):
            continue
        if path.is_file():
            category = _report_category(path)
            if category:
                reports[category].append(path)
    states = {}
    for category in scanners_run:
        paths = reports[category]
        if not paths or all(path.stat().st_size == 0 for path in paths):
            states[category] = "missing"
            continue
        json_paths = [path for path in paths if path.suffix.lower() == ".json"]
        if json_paths:
            valid = False
            for path in json_paths:
                if path.stat().st_size == 0:
                    continue
                try:
                    text = _json_text(path)
                    if not text.strip():
                        continue
                    json.loads(text)
                    valid = True
                    break
                except (OSError, ValueError, json.JSONDecodeError):
                    pass
            if not valid:
                states[category] = "unparseable"
    missing = [category for category in scanners_run if category in states]
    findings = []
    existing_findings = existing_findings or []
    skip_reasons = skip_reasons or {}
    for category, state in states.items():
        rule_id = (
            "APPSEC-REPORT-MISSING"
            if state == "missing"
            else "APPSEC-REPORT-UNPARSEABLE"
        )
        if any(
            item.get("category") == category and item.get("rule_id") == rule_id
            for item in existing_findings
        ):
            continue
        findings.append(
            new_finding(
                "normalizer",
                "Scanner report " + state + ": " + category,
                "HIGH",
                {"file": "scan results", "line": None},
                {
                    "category_attempted": category,
                    "why": skip_reasons.get(
                        category,
                        "The scanner was expected to produce a report and did not.",
                    ),
                },
                category=category,
                rule_id=rule_id,
            )
        )
    return findings, missing

def _load_existing(path):
    if not Path(path).exists():
        return []
    value = read_json_loose(path)
    if not isinstance(value, list):
        raise ValueError(str(path) + " must contain a JSON array")
    return value

def _merge_category(path, new_findings, category):
    existing = _load_existing(path)
    return [item for item in existing if item.get("category") != category] + new_findings

def print_summary(findings, gate, failed):
    widths = (28, 8, 8, 8, 8)
    header = ("Scanner", "Critical", "High", "Medium", "Low")
    print(
        f"{header[0]:<{widths[0]}}|{header[1]:>{widths[1]}}|"
        f"{header[2]:>{widths[2]}}|{header[3]:>{widths[3]}}|{header[4]:>{widths[4]}}"
    )
    print("-" * (sum(widths) + 4))
    scanners = sorted({str(item.get("scanner") or "unknown") for item in findings})
    totals = {severity: 0 for severity in SEVERITIES}
    for scanner in scanners:
        counts = {severity: 0 for severity in SEVERITIES}
        unknown = 0
        for finding in findings:
            if str(finding.get("scanner") or "unknown") == scanner:
                severity = normalize_severity(finding.get("severity"))
                if severity == "UNKNOWN":
                    unknown += 1
                else:
                    counts[severity] += 1
        for severity in SEVERITIES:
            totals[severity] += counts[severity]
        label = scanner[: widths[0]]
        print(
            f"{label:<{widths[0]}}|{counts['CRITICAL']:>{widths[1]}}|"
            f"{counts['HIGH']:>{widths[2]}}|{counts['MEDIUM']:>{widths[3]}}|"
            f"{counts['LOW']:>{widths[4]}}"
        )
        if unknown:
            print(f"  UNKNOWN severity requiring review: {unknown}")
    print(f"TOTAL C+H: {totals['CRITICAL'] + totals['HIGH']}")
    verdict = "FAILED" if failed else "PASSED"
    print(f"Gate verdict: {verdict} (threshold: {gate})")

    secrets = [item for item in findings if item.get("category") == "secret_detection"]
    if secrets:
        print("Secret Detection findings (redacted)")
        for finding in secrets:
            location = finding.get("location") or {}
            file_name = location.get("file") or "unknown"
            line = location.get("line")
            suffix = f":{line}" if line not in (None, "") else ""
            print(
                f"  {finding.get('severity')} {finding.get('rule_id')} "
                f"{file_name}{suffix}"
            )

def _parse_ran(value, parser):
    if value is None or value.strip() == "":
        return []
    categories = []
    for item in value.split(","):
        category = item.strip()
        if category not in CATEGORIES:
            parser.error("unknown category in --ran: " + category)
        if category not in categories:
            categories.append(category)
    return categories

def build_parser():
    parser = argparse.ArgumentParser(description="Normalize AppSec scanner reports")
    parser.add_argument("results_dir")
    parser.add_argument("--gate", choices=tuple(GATE_LEVELS), default=None)
    parser.add_argument("--only", choices=CATEGORIES)
    parser.add_argument("--ran", default=None)
    parser.add_argument("--skips", default=None)
    return parser

def _previous_scanners_run(results_dir):
    """What an earlier run already recorded, so a scoped rescan cannot forget it."""
    try:
        value = read_json_loose(Path(results_dir) / "scan-coverage.json")
    except (OSError, ValueError, json.JSONDecodeError):
        return []
    if isinstance(value, dict):
        previous = value.get("scanners_run")
        if isinstance(previous, list):
            return [item for item in previous if item in CATEGORIES]
    return []

def main(argv=None):
    parser = build_parser()
    args = parser.parse_args(argv)
    gate = args.gate or os.environ.get("CI_GATE_FAIL_ON", "high").strip().lower()
    if gate not in GATE_LEVELS:
        parser.error("CI_GATE_FAIL_ON must be critical, high, medium, or none")
    scanners_run = _parse_ran(args.ran, parser)
    # NOT filtered by --only: coverage is about every category the admin
    # enabled, not just the one this invocation executed. Reports from earlier
    # runs persist in results_dir, so a genuine rescan still sees them present.

    results_dir = Path(args.results_dir)
    try:
        results_dir.mkdir(parents=True, exist_ok=True)
        parsed = normalize_reports(results_dir)
        if args.only:
            parsed = [item for item in parsed if item.get("category") == args.only]
        skip_reasons = load_skip_reasons(args.skips)
        coverage, missing = coverage_findings(
            results_dir, scanners_run, parsed, skip_reasons
        )
        normalized_new = parsed + coverage
        triaged_new = triage_findings(json.loads(json.dumps(normalized_new)))
        redact_secret_findings(normalized_new)
        redact_secret_findings(triaged_new)

        normalized_path = results_dir / "findings.normalized.json"
        triaged_path = results_dir / "findings.triaged.json"
        if args.only:
            normalized = _merge_category(normalized_path, normalized_new, args.only)
            triaged = _merge_category(triaged_path, triaged_new, args.only)
            gate_scope = triaged_new
        else:
            normalized = normalized_new
            triaged = triaged_new
            gate_scope = triaged

        redact_secret_findings(normalized, matched_only=True)
        redact_secret_findings(triaged, matched_only=True)
        failed = gate_failed(gate_scope, gate)

        # A scoped (--only) rescan must never launder the coverage record clean.
        # It used to overwrite scan-coverage.json with just its own category, so
        # the fix loop that SKILL.md tells you to run every iteration turned
        # {"missing_report": ["sast","container_scanning"]} into
        # {"missing_report": [], "gate_passed": true} while those two scanners
        # still had never run. Coverage is therefore derived from the MERGED
        # findings and unioned with what the previous run recorded.
        if args.only:
            scanners_run = sorted(
                set(scanners_run) | set(_previous_scanners_run(results_dir))
            )
            missing = sorted(
                {
                    item.get("category")
                    for item in triaged
                    if str(item.get("rule_id") or "").startswith("APPSEC-REPORT-")
                    and item.get("category")
                }
            )
        write_json(normalized_path, normalized)
        write_json(triaged_path, triaged)
        # Incomplete coverage is not a pass. A HIGH coverage finding already
        # fails a `high` gate, but not a `critical`-only one — so state the rule
        # explicitly instead of relying on severity arithmetic. `none` is
        # report-only by definition and is respected.
        if missing and gate != "none":
            failed = True

        write_json(
            results_dir / "scan-coverage.json",
            {
                "scanners_run": scanners_run,
                "missing_report": missing,
                "gate_threshold": gate,
                "gate_passed": not failed,
                # Separate fact from the gate verdict. `gate: none` is
                # report-only and always passes, so gate_passed alone could read
                # as "fully scanned and clean" while categories never ran.
                "coverage_complete": not missing,
            },
        )
        print_summary(triaged, gate, failed)
        if args.only:
            print("NOTE: this was a scoped rescan of " + args.only + " only.")
            outstanding = [
                item
                for item in triaged
                if item.get("category") != args.only
                and str(item.get("severity") or "").upper() in ("CRITICAL", "HIGH")
            ]
            if outstanding:
                print(
                    "WARNING: "
                    + str(len(outstanding))
                    + " critical/high finding(s) remain in other categories; "
                    "the branch is NOT clean. Re-run a full scan before pushing."
                )
        if missing:
            print("WARNING: scanner coverage is incomplete; this is NOT an all-clear")
        return 1 if failed else 0
    except (OSError, ValueError, json.JSONDecodeError) as error:
        print("ERROR: " + str(error), file=sys.stderr)
        return 2

if __name__ == "__main__":
    raise SystemExit(main())
