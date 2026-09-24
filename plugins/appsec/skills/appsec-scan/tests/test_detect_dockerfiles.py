#!/usr/bin/env python3
"""Tests for detect-dockerfiles.sh: standalone Dockerfile discovery.

run-scan.sh's find_dockerfile() (scripts/run-scan.sh) only ever surfaces a
single Dockerfile — an explicit $DOCKERFILE, ./Dockerfile, or the first hit of
a shallow find. That is enough for a single-service repo, but a monorepo with
a Dockerfile per service needs every one of them enumerated so a later phase
can scan them all. This script is the standalone discovery half of that: it
prints every match, one per line, and does not choose a target or scan
anything. (Wiring it into run-scan.sh is a separate, later change.)
"""

from __future__ import annotations

import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

SKILL_DIR = Path(__file__).resolve().parents[1]
SCRIPT = SKILL_DIR / "scripts" / "detect-dockerfiles.sh"
BASH = shutil.which("bash") or "/bin/bash"


def touch(root: Path, *relative: str) -> None:
    for item in relative:
        path = root / item
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("", encoding="utf-8")


def git_init(repo: Path) -> None:
    subprocess.run(["git", "init", "-q", str(repo)], check=True)
    subprocess.run(["git", "-C", str(repo), "config", "user.email", "a@example.com"], check=True)
    subprocess.run(["git", "-C", str(repo), "config", "user.name", "a"], check=True)


def git_commit_all(repo: Path) -> None:
    subprocess.run(["git", "-C", str(repo), "add", "-A"], check=True)
    subprocess.run(["git", "-C", str(repo), "commit", "-q", "-m", "x"], check=True)


def run(root: Path, *args: str, bash: str = BASH) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [bash, str(SCRIPT), *args],
        cwd=str(root),
        capture_output=True,
        text=True,
    )


def parse(stdout: str) -> list[tuple[str, str, str]]:
    rows = []
    for line in stdout.splitlines():
        parts = line.split("\t")
        assert len(parts) == 3, f"expected 3 TAB-separated fields, got: {line!r}"
        rows.append(tuple(parts))
    return rows


class DetectDockerfilesTest(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory(prefix="detect-dockerfiles-")
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name) / "repo"
        self.root.mkdir()

    # -- basic discovery, git mode --------------------------------------

    def test_root_dockerfile(self) -> None:
        git_init(self.root)
        touch(self.root, "Dockerfile")
        git_commit_all(self.root)

        proc = run(self.root)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertEqual(parse(proc.stdout), [("Dockerfile", ".", "dockerfile")])

    def test_nested_services_dockerfiles(self) -> None:
        git_init(self.root)
        touch(self.root, "services/web/Dockerfile", "services/api/Dockerfile")
        git_commit_all(self.root)

        proc = run(self.root)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertEqual(
            parse(proc.stdout),
            [
                ("services/api/Dockerfile", "services/api", "services-api-dockerfile"),
                ("services/web/Dockerfile", "services/web", "services-web-dockerfile"),
            ],
        )

    def test_alternate_names_and_suffixes(self) -> None:
        git_init(self.root)
        touch(self.root, "Dockerfile.prod", "api.Dockerfile", "Containerfile")
        git_commit_all(self.root)

        proc = run(self.root)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        paths = [row[0] for row in parse(proc.stdout)]
        self.assertEqual(
            sorted(paths), sorted(["Dockerfile.prod", "api.Dockerfile", "Containerfile"])
        )

    def test_suffixed_containerfile_is_not_matched(self) -> None:
        """The spec pins Containerfile/Containerfile.* only — no *.Containerfile."""
        git_init(self.root)
        touch(self.root, "api.Containerfile")
        git_commit_all(self.root)

        proc = run(self.root)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertEqual(proc.stdout, "")

    def test_case_insensitive_basename(self) -> None:
        # A distinct directory from any other "Dockerfile" test: macOS's
        # default case-insensitive filesystem would alias "Dockerfile" and
        # "dockerfile" in the same directory into one file.
        git_init(self.root)
        touch(self.root, "case-variant/dockerfile")
        git_commit_all(self.root)

        proc = run(self.root)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertEqual(
            parse(proc.stdout),
            [("case-variant/dockerfile", "case-variant", "case-variant-dockerfile")],
        )

    # -- exclusions -------------------------------------------------------

    def test_node_modules_and_appsec_results_excluded(self) -> None:
        git_init(self.root)
        touch(
            self.root,
            "Dockerfile",
            "node_modules/dep/Dockerfile",
            ".appsec-results/Dockerfile",
        )
        git_commit_all(self.root)

        proc = run(self.root)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertEqual(parse(proc.stdout), [("Dockerfile", ".", "dockerfile")])

    def test_gitignored_excluded_untracked_not_ignored_included(self) -> None:
        git_init(self.root)
        (self.root / "ignored").mkdir()
        (self.root / "tracked").mkdir()
        (self.root / ".gitignore").write_text("ignored/\n", encoding="utf-8")
        touch(self.root, "ignored/Dockerfile", "tracked/Dockerfile")
        git_commit_all(self.root)

        # Untracked but NOT ignored: must still show up (git mode uses
        # --cached --others --exclude-standard, not just the index).
        touch(self.root, "untracked/Dockerfile")

        proc = run(self.root)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertEqual(
            parse(proc.stdout),
            [
                ("tracked/Dockerfile", "tracked", "tracked-dockerfile"),
                ("untracked/Dockerfile", "untracked", "untracked-dockerfile"),
            ],
        )

    # -- non-git fallback ---------------------------------------------------

    def test_non_git_fallback(self) -> None:
        # No `git init` here at all — self.root has no .git anywhere above it
        # (it lives under a fresh tempdir), so the script must use `find`.
        touch(self.root, "Dockerfile", "a/b/Containerfile", "node_modules/dep/Dockerfile")

        proc = run(self.root)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertEqual(
            parse(proc.stdout),
            [
                ("Dockerfile", ".", "dockerfile"),
                ("a/b/Containerfile", "a/b", "a-b-containerfile"),
            ],
        )

    # -- path handling ------------------------------------------------------

    def test_path_with_spaces_round_trips(self) -> None:
        git_init(self.root)
        touch(self.root, "my app/Dockerfile")
        git_commit_all(self.root)

        proc = run(self.root)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertEqual(
            parse(proc.stdout),
            [("my app/Dockerfile", "my app", "my-app-dockerfile")],
        )

    def test_tab_or_newline_in_path_is_skipped_with_warning(self) -> None:
        touch(self.root, "normal/Dockerfile")
        weird = self.root / "weird\tdir"
        weird.mkdir()
        (weird / "Dockerfile").write_text("", encoding="utf-8")

        proc = run(self.root)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertEqual(parse(proc.stdout), [("normal/Dockerfile", "normal", "normal-dockerfile")])
        self.assertIn("skipping path", proc.stderr)
        self.assertIn("weird", proc.stderr)

    # -- slugging -------------------------------------------------------

    def test_slug_collision_suffixing_in_sorted_order(self) -> None:
        git_init(self.root)
        # All three slugify to "a-b-dockerfile"; LC_ALL=C sorts '-' < '.' < '_'.
        touch(self.root, "a-b/Dockerfile", "a.b/Dockerfile", "a_b/Dockerfile")
        git_commit_all(self.root)

        proc = run(self.root)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertEqual(
            parse(proc.stdout),
            [
                ("a-b/Dockerfile", "a-b", "a-b-dockerfile"),
                ("a.b/Dockerfile", "a.b", "a-b-dockerfile-2"),
                ("a_b/Dockerfile", "a_b", "a-b-dockerfile-3"),
            ],
        )

    # -- ordering -------------------------------------------------------

    def test_output_is_sorted_by_path(self) -> None:
        git_init(self.root)
        touch(
            self.root,
            "zeta/Dockerfile",
            "Dockerfile",
            "alpha/Dockerfile",
            "beta/Dockerfile",
        )
        git_commit_all(self.root)

        proc = run(self.root)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        paths = [row[0] for row in parse(proc.stdout)]
        self.assertEqual(paths, sorted(paths))
        self.assertEqual(
            paths, ["Dockerfile", "alpha/Dockerfile", "beta/Dockerfile", "zeta/Dockerfile"]
        )

    # -- errors -----------------------------------------------------------

    def test_missing_root_exits_2(self) -> None:
        proc = run(self.root, str(self.root / "does-not-exist"))
        self.assertEqual(proc.returncode, 2)
        self.assertEqual(proc.stdout, "")

    def test_usage_error_exits_2(self) -> None:
        proc = run(self.root, "one", "two")
        self.assertEqual(proc.returncode, 2)

    def test_default_root_is_cwd(self) -> None:
        git_init(self.root)
        touch(self.root, "Dockerfile")
        git_commit_all(self.root)

        proc = run(self.root)  # no args
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertEqual(parse(proc.stdout), [("Dockerfile", ".", "dockerfile")])

    def test_no_dockerfiles_is_empty_output_exit_0(self) -> None:
        git_init(self.root)
        touch(self.root, "README.md")
        git_commit_all(self.root)

        proc = run(self.root)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertEqual(proc.stdout, "")

    # -- explicit /bin/bash invocation --------------------------------------

    def test_runs_under_bin_bash_explicitly(self) -> None:
        git_init(self.root)
        touch(self.root, "Dockerfile")
        git_commit_all(self.root)

        proc = run(self.root, bash="/bin/bash")
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertEqual(parse(proc.stdout), [("Dockerfile", ".", "dockerfile")])


if __name__ == "__main__":
    unittest.main()
