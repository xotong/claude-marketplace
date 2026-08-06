#!/usr/bin/env python3
"""Decide, before the fix loop runs, which suggested upgrades are actually gettable.

Dependency findings arrive with a `fixed_version` -- "upgrade lodash to 4.17.21".
In an airgapped estate that is only actionable if the internal mirror carries that
version. Attempting it blind spends the fix loop's 5-iteration budget on work that
cannot succeed, and the developer sees a confusing failure rather than a clear ask.

So the mirror is asked first. Output is a small map that normalize.py folds into
each finding's remediation_status:

    available -> fixable_candidate      the loop may attempt it
    absent    -> blocked_registry_gap   route to TRIAGE.md as a mirroring request
    unknown   -> left alone             a registry we could not reach is not evidence

Container-scanning findings are deliberately NOT probed. Their packages are OS
packages (apk/deb/rpm) inside a base image; the remediation is rebuilding on a
newer base image, not fetching a library from a language registry. Probing npm for
`openssl` would produce a confidently wrong answer.

Usage:
    check-remediation.py <results_dir> [--registries <json>] [--token-env <name>]
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

SCRIPTS_DIR = Path(__file__).resolve().parent
RESOLVE_PACKAGE = SCRIPTS_DIR / "resolve-package.sh"

# Dependency manifests are the most reliable ecosystem signal available: the
# scanner reports the file the dependency was declared in.
MANIFEST_ECOSYSTEMS = {
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


def infer_ecosystem(finding: dict) -> str | None:
    # evidence.manifest is authoritative: _gitlab_location collapses dependency
    # findings to {"package": name}, so location.file is usually absent here.
    evidence = finding.get("evidence") or {}
    location = finding.get("location") or {}
    manifest = evidence.get("manifest") or location.get("file")
    path = str(manifest or "").replace("\\", "/")
    if not path:
        return None
    return MANIFEST_ECOSYSTEMS.get(path.rsplit("/", 1)[-1])


def probe(ecosystem: str, package: str, version: str, template: str, token_env: str) -> str:
    if not RESOLVE_PACKAGE.is_file():
        return "unknown"
    try:
        proc = subprocess.run(
            [
                "bash",
                str(RESOLVE_PACKAGE),
                ecosystem,
                package,
                version,
                template,
                token_env,
            ],
            capture_output=True,
            text=True,
            timeout=60,
        )
    except (OSError, subprocess.SubprocessError):
        return "unknown"
    verdict = (proc.stdout or "").strip()
    return verdict if verdict in {"available", "absent", "unknown"} else "unknown"


def collect_targets(findings: list) -> dict:
    """Unique (ecosystem, package, version) triples worth asking about."""
    targets: dict = {}
    for finding in findings:
        # Only dependency findings map onto a language registry; see module docstring.
        if finding.get("category") != "dependency_scanning":
            continue
        evidence = finding.get("evidence") or {}
        package = evidence.get("package")
        fixed = evidence.get("fixed_version")
        if not package or not fixed:
            continue
        ecosystem = infer_ecosystem(finding)
        if not ecosystem:
            continue
        targets[f"{ecosystem}|{package}|{fixed}"] = (ecosystem, str(package), str(fixed))
    return targets


def main(argv=None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("results_dir")
    parser.add_argument("--registries", default="", help="JSON: {ecosystem: url_template}")
    parser.add_argument("--token-env", default="", help="env var NAME holding a registry token")
    args = parser.parse_args(argv)

    results_dir = Path(args.results_dir)
    triaged_path = results_dir / "findings.triaged.json"
    out_path = results_dir / "registry-availability.json"

    try:
        registries = json.loads(args.registries) if args.registries.strip() else {}
    except json.JSONDecodeError:
        print("[remediation] registries config is not valid JSON; skipping probe", file=sys.stderr)
        registries = {}

    if not isinstance(registries, dict) or not any(str(v).strip() for v in registries.values()):
        # No mirrors declared: stay silent and leave every status untouched.
        out_path.write_text(json.dumps({}, indent=2) + "\n", encoding="utf-8")
        return 0

    try:
        findings = json.loads(triaged_path.read_text(encoding="utf-8"))
    except (OSError, ValueError, json.JSONDecodeError):
        out_path.write_text(json.dumps({}, indent=2) + "\n", encoding="utf-8")
        return 0
    if not isinstance(findings, list):
        out_path.write_text(json.dumps({}, indent=2) + "\n", encoding="utf-8")
        return 0

    targets = collect_targets(findings)
    if not targets:
        out_path.write_text(json.dumps({}, indent=2) + "\n", encoding="utf-8")
        return 0

    availability: dict = {}
    counts = {"available": 0, "absent": 0, "unknown": 0}
    for key, (ecosystem, package, version) in sorted(targets.items()):
        template = str(registries.get(ecosystem) or "").strip()
        if not template:
            # Ecosystem present in the project but no mirror declared for it.
            availability[key] = "unknown"
            counts["unknown"] += 1
            continue
        verdict = probe(ecosystem, package, version, template, args.token_env)
        availability[key] = verdict
        counts[verdict] += 1

    out_path.write_text(json.dumps(availability, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    print(
        f"[remediation] checked {len(targets)} upgrade(s) against the mirror: "
        f"{counts['available']} available, {counts['absent']} missing, "
        f"{counts['unknown']} undetermined",
        file=sys.stderr,
    )
    if counts["absent"]:
        print(
            "[remediation] missing upgrades will be reported as blocked_registry_gap "
            "and listed in TRIAGE.md for mirroring — the fix loop will not attempt them.",
            file=sys.stderr,
        )
    return 0


if __name__ == "__main__":
    sys.exit(main())
