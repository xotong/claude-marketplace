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

A registry that answers 401/403 also leaves the status alone -- being refused is
no more evidence of absence than a timeout. But it is reported as a CONFIG-ERROR:
rather than folded silently into `unknown`, because the two failures need
opposite handling: a timeout may fix itself, a rejected credential never will.
Against a non-anonymous mirror with no `auth_token_env` set, EVERY probe returns
unknown, the whole registry-gap feature quietly does nothing, and the run still
reads like a result. One line per ecosystem, not per package -- a misconfigured
registry produces hundreds of probes.

Container-scanning findings are deliberately NOT probed against a PACKAGE
registry. Their packages are OS packages (apk/deb/rpm) inside a base image; the
remediation is rebuilding on a newer base image, not fetching a library from a
language registry. Probing npm for `openssl` would produce a confidently wrong
`absent`.

Base images get their own probe instead, beside the package one and never
widening it: container-target.sh already parsed the Dockerfile's FROM lines into
base-images.json, so this asks the container registry whether each of those is
obtainable at all. Telling an airgapped developer to rebuild on an image their
registry does not carry is the same dead end the package probe exists to prevent.
Verdicts land in the same map under `image|<image>|<tag>` keys, which cannot
collide with `<ecosystem>|<package>|<version>`.

`hardened_repo` results are recorded under `hardened|...` and are SUGGESTION
ONLY: a hardened image is a different image, not a newer tag, so nothing reads
those keys when deciding a finding's status.

Usage:
    check-remediation.py <results_dir> [--registries <json>] [--token-env <name>]
                         [--base-repo <template>] [--hardened-repo <template>]
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path

SCRIPTS_DIR = Path(__file__).resolve().parent
RESOLVE_PACKAGE = SCRIPTS_DIR / "resolve-package.sh"
RESOLVE_BASE_IMAGE = SCRIPTS_DIR / "resolve-base-image.sh"

# resolve-package.sh's full contract. resolve-base-image.sh has no `unauthorized`
# -- it deliberately collapses auth into `unknown` so it can never manufacture a
# false `absent` -- so base-image probes keep the narrower set.
PACKAGE_VERDICTS = frozenset({"available", "absent", "unauthorized", "unknown"})
IMAGE_VERDICTS = frozenset({"available", "absent", "unknown"})

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


def write_availability(path: Path, value: dict) -> None:
    """Temp file + os.replace, so readers see the whole map or the old one.

    Same pattern as normalize.py's write_json, kept local rather than imported:
    this probe must still run when normalize.py cannot be imported. A plain
    write_text truncates first, so an interruption (Ctrl-C between the two
    normalize passes, a killed run) left registry-availability.json empty --
    and normalize.py then reads no verdict for any package, silently degrading
    every remediation_status to unknown. The `.tmp` name is deliberate: it does
    not end in .json, so a leftover temp file is never parsed as a report.
    """
    temporary = path.with_name(path.name + ".tmp")
    temporary.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    os.replace(temporary, path)


def infer_ecosystem(finding: dict) -> str | None:
    evidence = finding.get("evidence") or {}
    ecosystem = str(evidence.get("ecosystem") or "").strip().lower()
    if ecosystem:
        return ecosystem
    # evidence.manifest is the fallback for GitLab reports: _gitlab_location
    # collapses dependency findings to {"package": name}, so location.file is
    # usually absent there.
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
    return verdict if verdict in PACKAGE_VERDICTS else "unknown"


def read_base_images(results_dir: Path) -> list:
    """Unique (image, tag) pairs container-target.sh parsed out of the Dockerfile.

    A missing file means container-target.sh never ran (container scanning off);
    `[]` means it looked and found none. Both mean nothing to probe.
    """
    try:
        data = json.loads((results_dir / "base-images.json").read_text(encoding="utf-8"))
    except (OSError, ValueError, json.JSONDecodeError):
        return []
    if not isinstance(data, list):
        return []
    pairs = []
    for entry in data:
        if not isinstance(entry, dict):
            continue
        image = str(entry.get("image") or "").strip()
        tag = str(entry.get("tag") or "").strip()
        # Multi-stage Dockerfiles repeat the same base; probe each one once.
        if image and tag and (image, tag) not in pairs:
            pairs.append((image, tag))
    return pairs


def probe_base_image(image: str, tag: str, template: str) -> str:
    """One registry question per base image; every failure mode is 'unknown'.

    The runtime is left to resolve-base-image.sh, which reads CONTAINER_RUNTIME
    from the environment load-prefs.sh already exported.
    """
    if not RESOLVE_BASE_IMAGE.is_file():
        return "unknown"
    try:
        proc = subprocess.run(
            ["bash", str(RESOLVE_BASE_IMAGE), image, tag, template],
            capture_output=True,
            text=True,
            # Generous: the helper falls back to a real pull when the runtime has
            # no `manifest inspect`. A timeout kill still yields 'unknown'.
            timeout=300,
        )
    except (OSError, subprocess.SubprocessError):
        return "unknown"
    verdict = (proc.stdout or "").strip()
    return verdict if verdict in IMAGE_VERDICTS else "unknown"


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


def probe_fixed_versions(
    ecosystem: str, package: str, versions: str, template: str, token_env: str
) -> str:
    """Probe every scanner-supplied fix and conservatively combine the verdicts."""
    candidates = [candidate.strip() for candidate in str(versions).split(",")]
    candidates = [candidate for candidate in candidates if candidate]
    if not candidates:
        return "unknown"
    verdicts = [
        probe(ecosystem, package, candidate, template, token_env)
        for candidate in candidates
    ]
    if "available" in verdicts:
        return "available"
    if all(verdict == "absent" for verdict in verdicts):
        return "absent"
    # Ranked below both settled answers on purpose: a registry that answered for
    # one candidate and refused another has still told us something real, and the
    # refusal is only worth surfacing when nothing settled it.
    if "unauthorized" in verdicts:
        return "unauthorized"
    return "unknown"


def main(argv=None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("results_dir")
    parser.add_argument("--registries", default="", help="JSON: {ecosystem: url_template}")
    parser.add_argument("--token-env", default="", help="env var NAME holding a registry token")
    # Defaulted from the environment load-prefs.sh already exports, so the probe
    # is correct whether or not the caller spells the flags out.
    parser.add_argument("--base-repo", default=os.environ.get("BASE_IMAGE_REPO", ""))
    parser.add_argument("--hardened-repo", default=os.environ.get("HARDENED_IMAGE_REPO", ""))
    args = parser.parse_args(argv)

    results_dir = Path(args.results_dir)
    triaged_path = results_dir / "findings.triaged.json"
    out_path = results_dir / "registry-availability.json"
    base_repo = args.base_repo.strip()
    hardened_repo = args.hardened_repo.strip()

    try:
        registries = json.loads(args.registries) if args.registries.strip() else {}
    except json.JSONDecodeError:
        print("[remediation] registries config is not valid JSON; skipping probe", file=sys.stderr)
        registries = {}

    package_mirrors = isinstance(registries, dict) and any(
        str(value).strip() for value in registries.values()
    )
    if not package_mirrors and not base_repo and not hardened_repo:
        # Nothing declared anywhere: stay silent and leave every status untouched.
        write_availability(out_path, {})
        return 0

    try:
        findings = json.loads(triaged_path.read_text(encoding="utf-8"))
    except (OSError, ValueError, json.JSONDecodeError):
        findings = []
    if not isinstance(findings, list):
        findings = []

    availability: dict = {}
    counts = {"available": 0, "absent": 0, "unknown": 0}
    refused: list = []
    targets = collect_targets(findings) if package_mirrors else {}
    for key, (ecosystem, package, version) in sorted(targets.items()):
        template = str(registries.get(ecosystem) or "").strip()
        if not template:
            # Ecosystem present in the project but no mirror declared for it.
            availability[key] = "unknown"
            counts["unknown"] += 1
            continue
        verdict = probe_fixed_versions(
            ecosystem, package, version, template, args.token_env
        )
        if verdict == "unauthorized":
            # Downgraded to `unknown` before anything records it, so no finding's
            # status can move: the map normalize.py reads never learns the
            # difference. Only the human-facing report does.
            if ecosystem not in refused:
                refused.append(ecosystem)
            verdict = "unknown"
        availability[key] = verdict
        counts[verdict] += 1

    base_images = read_base_images(results_dir) if (base_repo or hardened_repo) else []
    base_counts = {"available": 0, "absent": 0, "unknown": 0}
    for image, tag in base_images:
        if base_repo:
            verdict = probe_base_image(image, tag, base_repo)
            availability[f"image|{image}|{tag}"] = verdict
            base_counts[verdict] += 1
        if hardened_repo:
            # Separate key prefix on purpose: normalize.py reads only `image|`
            # when deciding a status, so a hardened hit can never silently
            # re-classify a finding into or out of a mirroring request.
            availability[f"hardened|{image}|{tag}"] = probe_base_image(
                image, tag, hardened_repo
            )

    write_availability(out_path, availability)

    if targets:
        print(
            f"[remediation] checked {len(targets)} upgrade(s) against the mirror: "
            f"{counts['available']} available, {counts['absent']} missing, "
            f"{counts['unknown']} undetermined",
            file=sys.stderr,
        )
    if base_repo and base_images:
        print(
            f"[remediation] checked {len(base_images)} base image(s) against the "
            f"container registry: {base_counts['available']} available, "
            f"{base_counts['absent']} missing, {base_counts['unknown']} undetermined",
            file=sys.stderr,
        )
    if counts["absent"] or base_counts["absent"]:
        print(
            "[remediation] missing upgrades and base images will be reported as "
            "blocked_registry_gap and listed in TRIAGE.md for mirroring — the fix "
            "loop will not attempt them.",
            file=sys.stderr,
        )
    for ecosystem in refused:
        # run-scan.sh greps this prefix; keep the wording on one line.
        print(
            f"CONFIG-ERROR: the {ecosystem} package registry refused the request "
            "(HTTP 401/403), so no upgrade could be checked against it — set "
            "settings.package_registries.auth_token_env to the name of an env var "
            "holding a token for it, or make the repository readable anonymously",
            file=sys.stderr,
        )
    return 0


if __name__ == "__main__":
    sys.exit(main())
