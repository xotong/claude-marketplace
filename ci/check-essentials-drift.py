#!/usr/bin/env python3
"""
Check that skills bundled in plugins/essentials/ are identical to their
canonical source plugin directories.

Essentials bundles content from three sources:
  plugins/superpowers/skills/    → plugins/essentials/skills/
  plugins/anthropic-feature-dev/ → plugins/essentials/ (agents/ + commands/)
  plugins/anthropic-pr-review/   → plugins/essentials/ (agents/ + commands/)

When a source plugin is updated, essentials must be updated to match.
This script detects drift between the two and fails if any file differs.

Exit codes:
  0  All bundled files match their source.
  1  Drift detected — one or more files differ or are missing from essentials.
"""

import hashlib
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).parent.parent

SOURCES = [
    # (source_dir, essentials_dir, glob_pattern)
    (
        REPO_ROOT / "plugins/superpowers/skills",
        REPO_ROOT / "plugins/essentials/skills",
        "**/*",
    ),
    (
        REPO_ROOT / "plugins/anthropic-feature-dev/agents",
        REPO_ROOT / "plugins/essentials/agents",
        "**/*",
    ),
    (
        REPO_ROOT / "plugins/anthropic-feature-dev/commands",
        REPO_ROOT / "plugins/essentials/commands",
        "**/*",
    ),
    (
        REPO_ROOT / "plugins/anthropic-pr-review/agents",
        REPO_ROOT / "plugins/essentials/agents",
        "**/*",
    ),
    (
        REPO_ROOT / "plugins/anthropic-pr-review/commands",
        REPO_ROOT / "plugins/essentials/commands",
        "**/*",
    ),
]


def file_hash(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def check_source(source_dir: Path, essentials_dir: Path, pattern: str) -> list[str]:
    if not source_dir.is_dir():
        return [f"MISSING source dir: {source_dir}"]

    errors = []
    for src_file in sorted(source_dir.glob(pattern)):
        if not src_file.is_file():
            continue
        rel = src_file.relative_to(source_dir)
        bundled = essentials_dir / rel
        if not bundled.exists():
            errors.append(f"MISSING in essentials: {bundled.relative_to(REPO_ROOT)}")
        elif (src_file.stat().st_size != bundled.stat().st_size
              or file_hash(src_file) != file_hash(bundled)):
            errors.append(
                f"DRIFT: {bundled.relative_to(REPO_ROOT)}\n"
                f"  source : {src_file.relative_to(REPO_ROOT)}\n"
                f"  Fix: cp {src_file.relative_to(REPO_ROOT)} {bundled.relative_to(REPO_ROOT)}"
            )
    return errors


def main() -> None:
    all_errors: list[str] = []
    for source_dir, essentials_dir, pattern in SOURCES:
        all_errors.extend(check_source(source_dir, essentials_dir, pattern))

    if all_errors:
        print(f"essentials drift check FAILED — {len(all_errors)} issue(s):\n")
        for e in all_errors:
            print(f"  {e}")
        print(
            "\nUpdate plugins/essentials/ to match the source plugin dirs, "
            "then re-run this check."
        )
        sys.exit(1)
    else:
        print("essentials drift check PASSED — all bundled files match their sources.")


if __name__ == "__main__":
    main()
