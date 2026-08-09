#!/usr/bin/env python3
"""Gate appsec-scan runners against the vendored CI component snapshots.

Runs fully offline. `catalog.sh check-drift` is pointed at a cache directory that
does not exist, which forces it down its vendored-snapshot fallback path, so this
never touches the network and is safe on any runner.

Two signal classes come back, and they are deliberately NOT treated the same:

  CONTRACT-DRIFT  The component's declared spec inputs or artifact reports no
                  longer match the runner's checked-in .contract file. The runner
                  mirrors a component whose shape has changed underneath it.
                  This BLOCKS — it is the case that shipped the `go` language
                  option into fortify-sast with no runner support.

  DRIFT           Image pin differs from the template default, or a runner's
                  "Last synced" header is over 90 days old. Both are advisory by
                  design: config/scanner-preferences.yaml states admins pin
                  images independently of the component version and bump them on
                  their own schedule. These are REPORTED, never blocking.

Usage:  python3 ci/check-appsec-drift.py
"""

from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

import yaml

IMAGE_DRIFT_RE = re.compile(
    r"^DRIFT: image drift: configured (?P<configured>\S+) "
    r"vs component template (?P<template>\S+)$"
)

REPO_ROOT = Path(__file__).resolve().parent.parent
SKILL_DIR = REPO_ROOT / "plugins" / "appsec" / "skills" / "appsec-scan"
PREFS = SKILL_DIR / "config" / "scanner-preferences.yaml"
CATALOG_SH = SKILL_DIR / "scripts" / "catalog.sh"

# Deliberately absent so catalog.sh falls back to reference/catalog/ and stays offline.
OFFLINE_CACHE = "/nonexistent-appsec-drift-cache"

# Keep aligned with default_runner_for() in scripts/load-prefs.sh. The regression
# test parses that Bash function and compares the complete mapping.
DEFAULT_RUNNERS = {
    "sast": "fortify-sast.sh",
    "dependency_scanning": "gitlab-dependency-scanning.sh",
    "secret_detection": "secret-detection.sh",
    "container_scanning": "gitlab-container-scanning.sh",
}


def load_targets() -> list[dict]:
    """Flatten every enabled category across every profile into check targets."""
    with PREFS.open() as fh:
        prefs = yaml.safe_load(fh)

    targets: list[dict] = []
    for profile_name, profile in (prefs.get("profiles") or {}).items():
        for category, cfg in (profile.get("categories") or {}).items():
            if not cfg.get("enabled", False):
                continue
            component = cfg.get("component")
            runner = cfg.get("runner") or DEFAULT_RUNNERS.get(category)
            if not component or not runner:
                continue
            targets.append(
                {
                    "profile": profile_name,
                    "category": category,
                    "component": component,
                    "runner": runner,
                    "image": cfg.get("image", ""),
                }
            )
    return targets


def image_tail(ref: str) -> str:
    """Trailing `name:tag` of an image ref, with the registry/path prefix dropped.

    An internal mirror only rewrites that prefix — jfrog.internal/security/secrets:7
    and registry.gitlab.com/security-products/secrets:7 are the same image. Comparing
    tails separates "we mirror this registry" (expected, every run, forever) from
    "the pinned version no longer matches the component" (worth a human's attention).
    """
    return ref.rsplit("/", 1)[-1]


def classify_advisory(line: str) -> tuple[str, str]:
    """Return (kind, line) where kind is 'mirror', 'version', or 'other'."""
    match = IMAGE_DRIFT_RE.match(line)
    if not match:
        return "other", line

    configured = match.group("configured")
    template = match.group("template")
    if image_tail(configured) == image_tail(template):
        return "mirror", f"{image_tail(configured)} — mirrored from {template.rsplit('/', 1)[0]}"
    return (
        "version",
        f"{image_tail(configured)} pinned, but component template declares "
        f"{image_tail(template)}",
    )


def run_check(target: dict) -> tuple[list[str], list[str]]:
    """Return (contract_drift_lines, advisory_drift_lines) for one target."""
    runner_path = SKILL_DIR / "scanners" / target["runner"]
    if not runner_path.is_file():
        return (
            [f"{target['category']}: runner {target['runner']} named in "
             f"scanner-preferences.yaml does not exist"],
            [],
        )

    proc = subprocess.run(
        [
            "bash",
            str(CATALOG_SH),
            "check-drift",
            target["component"],
            OFFLINE_CACHE,
            str(runner_path),
            target["image"],
        ],
        cwd=str(SKILL_DIR),
        capture_output=True,
        text=True,
    )

    contract: list[str] = []
    advisory: list[str] = []
    for line in proc.stdout.splitlines():
        line = line.strip()
        if line.startswith("CONTRACT-DRIFT:"):
            contract.append(line)
        elif line.startswith("DRIFT:"):
            advisory.append(line)
    return contract, advisory


def main() -> int:
    if not PREFS.is_file():
        print(f"ERROR: {PREFS} not found", file=sys.stderr)
        return 1
    if not CATALOG_SH.is_file():
        print(f"ERROR: {CATALOG_SH} not found", file=sys.stderr)
        return 1

    targets = load_targets()
    if not targets:
        print("No enabled scanner categories found — nothing to check.")
        return 0

    # Contract shape depends only on (component, runner); the image is what varies
    # per profile. Check each contract once, but every profile's image pin.
    seen_contracts: set[tuple[str, str]] = set()
    all_contract: list[str] = []
    mirrored: list[str] = []
    version_drift: list[str] = []
    other_advisory: list[str] = []

    for target in targets:
        key = (target["component"], target["runner"])
        contract, advisory = run_check(target)

        if key not in seen_contracts:
            seen_contracts.add(key)
            all_contract.extend(contract)

        for line in advisory:
            kind, rendered = classify_advisory(line)
            tagged = f"[{target['profile']}] {rendered}"
            bucket = {
                "mirror": mirrored,
                "version": version_drift,
            }.get(kind, other_advisory)
            if tagged not in bucket:
                bucket.append(tagged)

    print("=" * 72)
    print("  appsec-scan component drift check (offline, vendored snapshots)")
    print("=" * 72)
    print(f"Checked {len(seen_contracts)} component contract(s) "
          f"across {len(targets)} profile/category target(s).")
    print()

    if mirrored:
        print(f"Registry mirroring ({len(mirrored)}) — expected, same image:")
        for line in mirrored:
            print(f"  {line}")
        print()

    if version_drift:
        print(f"Version drift ({len(version_drift)}) — review, not blocking:")
        for line in version_drift:
            print(f"  {line}")
        print()

    if other_advisory:
        print(f"Advisory ({len(other_advisory)}) — reported, not blocking:")
        for line in other_advisory:
            print(f"  {line}")
        print()

    if all_contract:
        print(f"BLOCKING — contract drift ({len(all_contract)}):")
        for line in all_contract:
            print(f"  {line}")
        print()
        print("A component's declared inputs or reports changed underneath its runner.")
        print("Re-vendor the snapshot and reconcile the runner:")
        print("  plugins/appsec/skills/appsec-scan/UPDATE-GUIDE.md")
        return 1

    print("No contract drift. Runners match their vendored component snapshots.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
