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

Design note: anthropic-feature-dev and anthropic-pr-review both contribute
to plugins/essentials/agents/ and plugins/essentials/commands/. The script
pre-checks that no two source plugins contribute a file with the same
relative path to the same destination — such a collision would create an
unsatisfiable constraint (essentials cannot match two different sources
simultaneously). If a collision is detected the script exits immediately
with a clear message so the conflict can be resolved before drift checking.

Exit codes:
  0  All bundled files match their source.
  1  Drift detected — one or more files differ or are missing from essentials.
  2  Source-conflict detected — two source plugins claim the same destination file.
"""

import hashlib
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).parent.parent

# (source_dir, essentials_dir, glob_pattern)
# anthropic-feature-dev and anthropic-pr-review share the same essentials
# agents/ and commands/ destinations — see design note above.
SOURCES = [
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


def detect_source_conflicts() -> list[str]:
    """Fail fast if two source dirs claim the same destination file with different content.

    Each (essentials_path) → [source_path, ...] mapping is checked; if two sources
    produce different hashes for the same destination the constraint is unsatisfiable.
    """
    dest_to_sources: dict[Path, list[Path]] = {}
    for source_dir, essentials_dir, pattern in SOURCES:
        if not source_dir.is_dir():
            continue
        for src_file in sorted(source_dir.glob(pattern)):
            if not src_file.is_file():
                continue
            rel = src_file.relative_to(source_dir)
            dest = essentials_dir / rel
            dest_to_sources.setdefault(dest, []).append(src_file)

    conflicts = []
    for dest, sources in dest_to_sources.items():
        if len(sources) < 2:
            continue
        hashes = {s: file_hash(s) for s in sources}
        unique_hashes = set(hashes.values())
        if len(unique_hashes) > 1:
            lines = [f"CONFLICT: two sources contribute different content for {dest.relative_to(REPO_ROOT)}"]
            for src, h in hashes.items():
                lines.append(f"  {src.relative_to(REPO_ROOT)}  ({h[:12]}…)")
            lines.append("  Resolve by making both source plugins identical for this file,")
            lines.append("  or remove one plugin's copy before it is merged into essentials.")
            conflicts.append("\n".join(lines))
    return conflicts


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
        elif file_hash(src_file) != file_hash(bundled):
            errors.append(
                f"DRIFT: {bundled.relative_to(REPO_ROOT)}\n"
                f"  source : {src_file.relative_to(REPO_ROOT)}\n"
                f"  Fix: cp {src_file.relative_to(REPO_ROOT)} {bundled.relative_to(REPO_ROOT)}"
            )
    return errors


def main() -> None:
    conflicts = detect_source_conflicts()
    if conflicts:
        print(f"essentials source-conflict check FAILED — {len(conflicts)} conflict(s):\n")
        for c in conflicts:
            print(f"  {c}\n")
        sys.exit(2)

    # De-duplicate: when two sources map to the same destination, only check
    # each (source_dir, essentials_dir) pair once per unique pair.
    seen: set[tuple[Path, Path]] = set()
    all_errors: list[str] = []
    for source_dir, essentials_dir, pattern in SOURCES:
        key = (source_dir, essentials_dir)
        if key in seen:
            continue
        seen.add(key)
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
