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
    # Our own bookkeeping, not scanner reports. Anything left off this list is
    # parsed as a report and, if its schema is neither parseable nor recognisably
    # clean, becomes a phantom HIGH "unsupported report schema" finding that
    # fails the gate on its own.
    "base-images.json",
    "registry-availability.json",
    "scan-coverage.json",
}
REPORT_CATEGORIES = {
    "fortify-sast.fpr": "sast",
    # Older analyzers emit this instead of (or beside) the SBOM, and run-scan.sh
    # moves it into the results dir and clears it on a scoped rescan, so it is a
    # real supported input. While it was unregistered it counted as evidence for
    # no category at all: a valid clean report sitting on disk reported
    # dependency_scanning as APPSEC-REPORT-MISSING and failed the gate.
    "gl-dependency-scanning-report.json": "dependency_scanning",
    "gl-secret-detection-report.json": "secret_detection",
    "gl-container-scanning-report.json": "container_scanning",
    "container-scan-archive.json": "container_scanning",
}
TRIVY_ECOSYSTEMS = {
    "node-pkg": "npm",
    "python-pkg": "pypi",
    "gobinary": "go",
    "gomod": "go",
    "jar": "maven",
    "pom": "maven",
    "gradle": "maven",
    "gemspec": "rubygems",
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
    """Write via a sibling temp file + os.replace, so readers see all or nothing.

    Truncating in place meant an interrupted run could leave
    findings.triaged.json empty or half-written -- and that is the file the
    --only coverage union reads back to recover an earlier run's gaps, so a
    partial write became a false all-clear.
    """
    path = Path(path)
    # ponytail: same-directory fixed suffix, which is all os.replace atomicity
    # needs. Two normalize runs against one results dir would race; per-pid
    # names if that ever becomes a real invocation pattern.
    temporary = path.with_name(path.name + ".tmp")
    with temporary.open("w", encoding="utf-8") as stream:
        json.dump(value, stream, indent=2, sort_keys=True)
        stream.write("\n")
    os.replace(temporary, path)

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
    """Category a file counts as evidence for, or None if it is not a report.

    Two producers write one report per input, so their names are variable and
    cannot be REPORT_CATEGORIES keys: GitLab DS writes gl-sbom-<name>.cdx.json,
    and sbom-vuln-scan.sh writes dependency-sbom-scan-<name>.json beside it.
    While the latter was unregistered a clean Trivy SBOM report satisfied no
    category, so the GOOD outcome (no vulnerabilities) reported
    dependency_scanning as APPSEC-REPORT-MISSING and failed the gate.
    """
    name = Path(path).name.lower()
    if name.startswith("gl-sbom-") and name.endswith(".cdx.json"):
        return "dependency_scanning"
    if name.startswith("dependency-sbom-scan") and name.endswith(".json"):
        return "dependency_scanning"
    # Fortify fans out one report per (source-path, language) unit, so its names
    # are variable for the same reason the two above are.
    if name.startswith("fortify-sast") and name.endswith(".fpr"):
        return "sast"
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
    # A CycloneDX SBOM is an inventory, not a findings report: its optional
    # `vulnerabilities` array uses a different schema (ratings/bom-ref, no
    # `severity`), which this branch would turn into UNKNOWN-severity findings
    # that fail the gate on an otherwise clean scan.
    if (
        isinstance(data, dict)
        and isinstance(data.get("vulnerabilities"), list)
        and data.get("bomFormat") != "CycloneDX"
    ):
        category = category or _report_category(path) or _fallback_category(path)
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
            # The dependency manifest is the ecosystem signal (package-lock.json ->
            # npm, pom.xml -> maven). It has to be kept here because _gitlab_location
            # collapses dependency findings to {"package": name} and drops the file.
            manifest = raw_location.get("file") or raw_location.get("path")
            if manifest:
                evidence["manifest"] = manifest
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
        trivy_category = category or _report_category(path) or _fallback_category(path)
        for result in data["Results"]:
            if not isinstance(result, dict):
                continue
            target = result.get("Target") or str(path)
            ecosystem = TRIVY_ECOSYSTEMS.get(str(result.get("Type") or "").lower())
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
                if ecosystem:
                    evidence["ecosystem"] = ecosystem
                findings.append(
                    new_finding(
                        "trivy",
                        vulnerability.get("Title")
                        or vulnerability.get("VulnerabilityID")
                        or "Container vulnerability",
                        vulnerability.get("Severity"),
                        (
                            {"package": package}
                            if trivy_category == "dependency_scanning"
                            else {"image": target}
                        ),
                        evidence,
                        category=trivy_category,
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
        # Trivy tags Results `json:",omitempty"`, so a scan that detected no
        # packages omits the key entirely or writes null -- a dependency-free
        # dependency-sbom-scan-*.json, or container-scan-archive.json for a
        # distroless/scratch image. Both are the GOOD outcome and both became a
        # phantom HIGH unsupported_report that failed the gate on a clean scan.
        # Keyed on SchemaVersion so this stays narrow: a document that is Trivy-
        # shaped in no way at all is still unsupported, because a report we
        # cannot parse may be hiding findings.
        or ("SchemaVersion" in data and data.get("Results") is None)
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

def _fvdl_recommendations(root):
    """Map Fortify classID -> remediation text.

    FVDL keeps guidance in top-level <Description classID="..."> blocks, not on the
    <Vulnerability> elements, so it has to be collected separately and joined on
    ClassID. Without this every SAST finding reached the developer with no
    remediation at all, which is the one category where they most need it.
    """
    guidance = {}
    for node in root.iter():
        if strip_ns(node.tag).lower() != "description":
            continue
        class_id = node.get("classID") or node.get("classid")
        if not class_id:
            continue
        text = first_text(node, ["Recommendations", "Abstract", "Explanation"])
        if not text:
            continue
        collapsed = " ".join(str(text).split())
        if collapsed:
            guidance[class_id] = collapsed[:1200]
    return guidance

def _unit_prefix(path):
    """Repo-relative source path of the unit that produced this FPR, or "".

    Fortify records file names relative to the tree it was pointed at, so a
    finding from `services/workshop` comes back as `crapi/shop/views.py`. Two
    units can then report the same-looking path for different files, and every
    link into the repo is broken. CI hit the identical problem and solved it the
    identical way, with --prepend-path. run-scan.sh writes the mapping beside the
    reports; a missing or unreadable file means the single-unit layout, where
    paths are already repo-relative and the prefix is correctly empty.
    """
    path = Path(path)
    units = path.parent / "sast-units"
    try:
        lines = units.read_text(encoding="utf-8").splitlines()
    except OSError:
        return ""
    entries = [line.split("|", 1)[0].strip() for line in lines if "|" in line]
    entries = [entry for entry in entries if entry]
    if len(entries) <= 1:
        return ""
    for source_path in entries:
        slug = re.sub(r"[^A-Za-z0-9._-]", "-", source_path) if source_path != "." else "root"
        if path.name == "fortify-sast-" + slug + ".fpr":
            return "" if source_path == "." else source_path.rstrip("/")
    return ""


def parse_fvdl_root(root, path, prefix=""):
    path = Path(path)
    findings = []
    recommendations = _fvdl_recommendations(root)
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
        if prefix and file_name:
            file_name = prefix + "/" + file_name.lstrip("/")
        evidence = {"raw_report": str(path)}
        guidance = recommendations.get(rule_id) if rule_id else None
        if guidance:
            evidence["solution"] = guidance
        findings.append(
            new_finding(
                "fortify",
                name or "Fortify vulnerability",
                severity or "HIGH",
                {"file": file_name or str(path), "line": line},
                evidence,
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
    prefix = _unit_prefix(path)
    with zipfile.ZipFile(path) as archive:
        members = [name for name in archive.namelist() if name.lower().endswith(".fvdl")]
        members.sort(key=lambda name: Path(name).name.lower() != "audit.fvdl")
        for member in members:
            root = ET.fromstring(archive.read(member))
            findings.extend(parse_fvdl_root(root, path, prefix))
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

# Every rule_id parse_failure_finding can emit. Kept as one name because these
# also drive coverage: see unreadable_categories.
PARSE_FAILURE_RULES = frozenset(
    {"APPSEC-REPORT-PARSE-FAILED", "APPSEC-REPORT-UNPARSEABLE"}
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
            if name.startswith("fortify-sast") and name.endswith(".fpr"):
                findings.extend(parse_fpr(path))
            elif name.endswith(".json"):
                data = read_json_loose(path)
                parsed = parse_generic_json(path, data, _report_category(path))
                findings.extend(parsed)
                # ONE guarded path for every JSON file, so no future report name
                # can land on a branch that forgot the guard. Zero findings is
                # the GOOD outcome, not an unsupported schema: this branch used
                # to be the unguarded one, and it turned a clean Trivy SBOM
                # report -- and before that our own registry-availability.json --
                # into a phantom HIGH that failed the gate on a clean scan.
                if not parsed and not is_supported_clean_json(data, path):
                    findings.append(unsupported_report_finding(path))
            elif name.endswith(".xml") or name.endswith(".fvdl"):
                parsed = parse_generic_xml(path)
                findings.extend(parsed)
                if not parsed:
                    findings.append(unsupported_report_finding(path))
        except Exception as error:  # Deliberate ceiling: vendor parse failures become findings.
            findings.append(parse_failure_finding(path, error))
    return findings

def unreadable_categories(findings):
    """Categories whose report normalize_reports could not read at all.

    A scanner whose output we cannot parse did not successfully scan, so this is
    a COVERAGE fact and must not be filtered through the gate threshold. As a
    finding it is only a HIGH, so a truncated fortify-sast.fpr used to report
    Gate verdict: PASSED, exit 0 and coverage_complete: true on a critical-only
    gate -- the exact false all-clear this tool exists to prevent.

    Unreadable covers an unsupported schema too, but only for a REGISTERED
    report name -- a report whose schema we do not recognise may be hiding every
    finding it holds. Stray files are excluded on purpose: _fallback_category
    guesses "sast" for anything it cannot place, so a notes.json someone dropped
    in the results dir would report SAST as unscanned.
    """
    unreadable = set()
    for item in findings or []:
        category = item.get("category")
        rule_id = item.get("rule_id")
        registered = _report_category((item.get("location") or {}).get("file") or "")
        if category and (
            rule_id in PARSE_FAILURE_RULES
            or (rule_id == "unsupported_report" and registered)
        ):
            unreadable.add(category)
    return unreadable

# Mirrors check-remediation.py's inference. Kept here too so normalize.py stays a
# pure function of its inputs — it reads the availability map, never the network.
_MANIFEST_ECOSYSTEMS = {
    "package-lock.json": "npm",
    "package.json": "npm",
    "yarn.lock": "npm",
    "npm-shrinkwrap.json": "npm",
    "pnpm-lock.yaml": "npm",
    "pom.xml": "maven",
    "build.gradle": "maven",
    "build.gradle.kts": "maven",
    "gradle.lockfile": "maven",
    "requirements.txt": "pypi",
    "pyproject.toml": "pypi",
    "Pipfile.lock": "pypi",
    "poetry.lock": "pypi",
    "go.mod": "go",
    "go.sum": "go",
    "Gemfile.lock": "rubygems",
}

def _registry_gap(finding, availability):
    """True only when the mirror explicitly answered 'absent'.

    'unknown' must never route here: a registry we could not reach is not proof
    the package is missing, and mislabelling it would send the developer chasing
    a mirroring request for something that is already available.
    """
    if not availability:
        return False
    if finding.get("category") != "dependency_scanning":
        return False
    evidence = finding.get("evidence") or {}
    package = evidence.get("package")
    fixed = evidence.get("fixed_version")
    if not package or not fixed:
        return False
    ecosystem = str(evidence.get("ecosystem") or "").strip().lower() or None
    if not ecosystem:
        manifest = evidence.get("manifest") or (finding.get("location") or {}).get(
            "file"
        )
        path = str(manifest or "").replace("\\", "/")
        ecosystem = (
            _MANIFEST_ECOSYSTEMS.get(path.rsplit("/", 1)[-1]) if path else None
        )
    if not ecosystem:
        return False
    return availability.get(f"{ecosystem}|{package}|{fixed}") == "absent"

def _absent_base_image(availability):
    """Name the first base image the container registry said it does not carry.

    Only `image|` keys are read. check-remediation.py files hardened-image
    verdicts under `hardened|` precisely so they can never reach this decision:
    a hardened image is a different image, not a newer tag, and swapping to one
    is a human call about libc, shell and UID -- not an availability fact.

    'unknown' is ignored here for the same reason it is in _registry_gap: a
    registry we could not reach is not proof the image is missing.

    ponytail: the base images belong to the whole build, not to one finding, so
    this reports the first gap rather than mapping each finding to its layer.
    Layer-to-image attribution would need the scanner's layer digests; add it
    when a report actually carries them.
    """
    for key in sorted(availability or {}):
        parts = key.split("|")
        if len(parts) == 3 and parts[0] == "image" and availability[key] == "absent":
            return "{}:{}".format(parts[1], parts[2])
    return None

def load_availability(path):
    """Read the registry-availability map; any problem degrades to 'no data'."""
    if not path:
        return {}
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError, json.JSONDecodeError):
        return {}
    return data if isinstance(data, dict) else {}

def triage_findings(findings, availability=None):
    availability = availability or {}
    base_gap = _absent_base_image(availability)
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
            "APPSEC-REPORT-INCOMPLETE",
            "APPSEC-REPORT-PARSE-FAILED",
            "APPSEC-REPORT-UNPARSEABLE",
            "unsupported_report",
        }:
            finding["verification_status"] = "needs_human_review"
            finding["remediation_status"] = "parser_or_report_fix_required"
            finding["triage_reason"] = (
                "Scanner coverage is incomplete until the report is supplied or supported."
            )
        elif category == "container_scanning" and base_gap:
            # Deliberately ABOVE the blocked_external_dependency branch. Container
            # findings routinely arrive with no fixed_version, so that branch used
            # to swallow every one of them and this gap was unreachable. The mirror
            # gap is the more specific answer and the only actionable one: there IS
            # something to ask the platform team for.
            finding["verification_status"] = "not_fixable_locally"
            finding["remediation_status"] = "blocked_registry_gap"
            finding["triage_reason"] = (
                "The fix is a rebuild on a newer base image, but {} is not in the "
                "configured container registry; ask for it to be mirrored before "
                "this can be fixed here.".format(base_gap)
            )
        elif category in {"dependency_scanning", "container_scanning"} and not evidence.get(
            "fixed_version"
        ):
            finding["verification_status"] = "not_fixable_locally"
            finding["remediation_status"] = "blocked_external_dependency"
            finding["triage_reason"] = "The scanner did not report a fixed version."
        elif _registry_gap(finding, availability):
            # The scanner named a fixed version, but the internal mirror does not
            # carry it. Distinct from blocked_external_dependency: there IS a known
            # fix, it just cannot be fetched here yet. The fix loop must not spend
            # an iteration on it, and TRIAGE.md turns it into a mirroring request.
            finding["verification_status"] = "not_fixable_locally"
            finding["remediation_status"] = "blocked_registry_gap"
            finding["triage_reason"] = (
                "Upgrade to {} is available upstream but not in the configured "
                "registry mirror; request it before this can be fixed here.".format(
                    evidence.get("fixed_version")
                )
            )
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
        # this tool's own remediation text and structural registry metadata.
        # Mangling a long manifest path removes the ecosystem signal the mirror
        # probe needs, so an unavailable upgrade is never marked as blocked.
        _evidence = finding.get("evidence")
        _protected_evidence = (
            {
                key: _evidence[key]
                for key in ("why", "manifest", "package")
                if key in _evidence
            }
            if isinstance(_evidence, dict)
            else {}
        )
        for key, value in list(finding.items()):
            finding[key] = _redact_structure(value, True)
        finding_matched_only = (
            matched_only or finding.get("category") != "secret_detection"
        )
        for key in ("name", "title", "description"):
            if key in finding:
                finding[key] = redact_value(finding.get(key), finding_matched_only)
        # These values are derived by this tool, never scanner-captured secret
        # material. `why` supplies remediation guidance; `manifest` and `package`
        # identify which registry to probe. Everything else stays redacted.
        finding["evidence"] = _redact_structure(
            finding.get("evidence") or {}, finding_matched_only
        )
        if isinstance(finding.get("evidence"), dict):
            finding["evidence"].update(_protected_evidence)
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
        text = Path(path).read_text(encoding="utf-8", errors="replace")
    except FileNotFoundError:
        # Absent is genuinely "no skips": run-scan.sh truncates this file before
        # any scanner starts, so the file exists for the whole of a real run.
        # Every other OSError propagates and main() turns it into exit 2. A skips
        # file we were told to read but could not is not evidence that nothing
        # was skipped -- swallowing it erased every recorded gap and reported
        # full coverage.
        return reasons
    for line in text.splitlines():
        if not line.strip():
            continue
        category, _, reason = line.partition("\t")
        category = category.strip()
        if category not in CATEGORIES:
            # The line is dropped, so say so. A typo in a future record_skip
            # call would otherwise erase a coverage gap in complete silence.
            print(
                "WARNING: ignoring recorded skip for unrecognized category: "
                + category,
                file=sys.stderr,
            )
            continue
        # Register the skip on the category alone. Whether a category counts as
        # covered must never depend on whether the reason text survived: an
        # empty, whitespace-only or tab-less line used to discard the skip
        # itself, turning a recorded gap into an all-clear.
        reasons[category] = reason.strip() or (
            "The scanner did not complete and recorded no reason; treat this "
            "category as unscanned."
        )
    return reasons

def coverage_findings(
    results_dir,
    scanners_run,
    existing_findings=None,
    skip_reasons=None,
    unreadable=None,
):
    unreadable = set(unreadable or ())
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
        if category in unreadable:
            # Checked for EVERY report shape, before the JSON scan below: that
            # scan never sees a .fpr or an .xml, and it accepts one valid JSON
            # while a truncated sibling is ignored. Either way a scanner whose
            # output we cannot read scored as covered.
            states[category] = "unparseable"
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
                    if json.loads(text) in (None, [], {}):
                        # An empty document is not evidence a scanner ran. A
                        # truncated gl-secret-detection-report.json parses fine
                        # and satisfied secret_detection's coverage, so the
                        # category read as scanned-and-clean with no finding at
                        # all. Every real report carries at least one key
                        # (vulnerabilities / Results / SchemaVersion /
                        # bomFormat), so this cannot reject a genuine clean one.
                        continue
                    valid = True
                    break
                except (OSError, ValueError, json.JSONDecodeError):
                    pass
            if not valid:
                states[category] = "unparseable"
    existing_findings = existing_findings or []
    skip_reasons = skip_reasons or {}
    # A recorded skip is authoritative. run-scan.sh writes one only when a
    # scanner did not run at all, or ran only partway, so a report file that
    # happens to exist must never outvote it. gl-sbom-*.cdx.json parses fine, so
    # an SBOM that was never matched against any advisory DB used to report
    # dependency_scanning as scanned and clean with a PASSED gate. setdefault:
    # "missing"/"unparseable" are the more precise verdicts, keep them.
    for category in skip_reasons:
        states.setdefault(category, "incomplete")
    missing = [category for category in CATEGORIES if category in states]
    findings = []
    for category, state in states.items():
        rule_id = {
            "missing": "APPSEC-REPORT-MISSING",
            "unparseable": "APPSEC-REPORT-UNPARSEABLE",
            "incomplete": "APPSEC-REPORT-INCOMPLETE",
        }[state]
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

def print_summary(findings, gate, failed, coverage_incomplete=False):
    widths = (28, 8, 8, 8, 8)
    header = ("Scanner", "Critical", "High", "Medium", "Low")
    non_actionable_statuses = {
        "blocked_registry_gap",
        "blocked_external_dependency",
    }
    actionable_critical_high = 0
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
                    if (
                        severity in {"CRITICAL", "HIGH"}
                        and finding.get("remediation_status")
                        not in non_actionable_statuses
                    ):
                        actionable_critical_high += 1
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
    print(f"ACTIONABLE C+H: {actionable_critical_high}")
    # `gate: none` is report-only for FINDINGS and stays exactly that: the exit
    # code and the findings verdict are unchanged. But whether a category ran at
    # all is not a finding-severity question, and the verdict line is what a
    # human skims -- a bare PASSED over a category that never ran is the false
    # all-clear this tool exists to prevent. Only the wording changes.
    if failed and coverage_incomplete:
        # Both facts, because either alone misleads: a bare FAILED reads as
        # "findings to fix" when a scanner never ran, and a bare INCOMPLETE
        # COVERAGE hides that findings are failing the gate too.
        verdict = "FAILED (INCOMPLETE COVERAGE)"
    elif failed:
        verdict = "FAILED"
    elif coverage_incomplete:
        verdict = "INCOMPLETE COVERAGE"
    else:
        verdict = "PASSED"
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
    parser.add_argument("--availability", default=None)
    return parser

def _previous_coverage(results_dir, key):
    """What an earlier run already recorded, so a scoped rescan cannot forget it."""
    try:
        value = read_json_loose(Path(results_dir) / "scan-coverage.json")
    except (OSError, ValueError, json.JSONDecodeError):
        return []
    if isinstance(value, dict):
        previous = value.get(key)
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
        normalized_path = results_dir / "findings.normalized.json"
        triaged_path = results_dir / "findings.triaged.json"
        # Taken BEFORE --only narrows the list: whether a scanner's report could
        # be read is a fact about the run, not about the scoped category, and
        # dropping it here let a scoped rescan report full coverage for a
        # category whose report on disk was truncated.
        unreadable = unreadable_categories(parsed)
        if args.only:
            parsed = [item for item in parsed if item.get("category") == args.only]
        skip_reasons = load_skip_reasons(args.skips)
        # Dedupe coverage findings against what the OUTPUT will hold, not just
        # this run's parsed findings: under --only the other categories are kept
        # from the previous file, so every rescan appended one more copy of the
        # same gap for a category it never touched.
        #
        # Read BOTH output files, because `missing` below is derived from both.
        # Deduping against findings.normalized.json alone split the two apart: an
        # interrupted run that left normalized.json on disk while losing
        # triaged.json and scan-coverage.json suppressed the gap here AND had
        # nothing left to re-derive it from — PASSED, exit 0,
        # coverage_complete: true, for categories that never ran. Suppressing a
        # gap is only safe when whatever suppressed it is also read back below.
        already_reported = parsed + [
            item
            for item in (
                _load_existing(normalized_path) + _load_existing(triaged_path)
                if args.only
                else []
            )
            if item.get("category") != args.only
        ]
        coverage, missing = coverage_findings(
            results_dir, scanners_run, already_reported, skip_reasons, unreadable
        )
        normalized_new = parsed + coverage
        availability = load_availability(args.availability)
        triaged_new = triage_findings(
            json.loads(json.dumps(normalized_new)), availability
        )
        redact_secret_findings(normalized_new)
        redact_secret_findings(triaged_new)

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
            # Only a category re-examined THIS run and found good may clear a
            # previously recorded gap. `missing` still names the bad ones here.
            # ONLY the category re-examined this run. `scanners_run` is
            # deliberately the full admin-enabled list even under --only, so
            # subtracting it cleared a recorded gap for every category whose
            # stale report file happened to still be on disk: `--only sast`
            # all-cleared a dependency_scanning gap nothing had re-examined.
            # Intersected with scanners_run, which still names the categories
            # this invocation actually examined: `--only sast --ran
            # secret_detection` examined no SAST at all, yet it cleared SAST's
            # recorded gap on the strength of the flag alone.
            cleared = ({args.only} & set(scanners_run)) - set(missing)
            scanners_run = sorted(
                set(scanners_run)
                | set(_previous_coverage(results_dir, "scanners_run"))
            )
            # Union of every surviving record, not merely rebuilt from one file:
            # if findings.triaged.json is lost, truncated or rewritten, deriving
            # the gaps from it alone reported coverage_complete: true for
            # categories that had never run. normalized is read too because an
            # interrupted run can leave the two out of step, and a gap recorded
            # in either is still a gap.
            def _gap_categories(items):
                return {
                    item.get("category")
                    for item in items
                    if str(item.get("rule_id") or "").startswith("APPSEC-REPORT-")
                    and item.get("category")
                }

            missing = sorted(
                (_gap_categories(triaged) | _gap_categories(normalized))
                | (set(_previous_coverage(results_dir, "missing_report")) - cleared)
            )
        write_json(normalized_path, normalized)
        write_json(triaged_path, triaged)
        # Incomplete coverage is not a pass at any threshold that gates at all. A
        # HIGH coverage finding already fails a `high` gate, but not a
        # `critical`-only one — so state the rule explicitly instead of relying
        # on severity arithmetic.
        #
        # `none` is exempt because it is documented as "always exit 0,
        # report-only" (config/PREFERENCES.md), and something unattended may be
        # branching on that. Incomplete coverage is NOT silent there: the verdict
        # line reads INCOMPLETE COVERAGE, the WARNING prints, and
        # scan-coverage.json carries coverage_complete: false. SKILL.md Step 3
        # requires reading that field rather than the exit code alone, so the
        # skill can never report "done" over a scanner that never ran.
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
        print_summary(triaged, gate, failed, bool(missing))
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
