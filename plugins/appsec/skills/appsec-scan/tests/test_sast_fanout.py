#!/usr/bin/env python3
"""Fortify fans out per build tree, and every unit is expected coverage.

CI includes the fortify-sast component once per service, each with its own
source-path, and gets one scan each. Locally there are no includes to read, so
run-scan.sh detected ONE language from the repo root and scanned ONE path. On a
repository with a root manifest plus services beneath it, that scanned the root,
silently ignored the rest, and still reported sast as covered with
`coverage_complete: true`.

That is the `--only` bug one axis over: narrowing what RUNS must never narrow
what is EXPECTED. The invariant was keyed on category, so it could not see
narrowing *within* a category.

Dependency scanning is deliberately untouched — its analyzer walks the whole
worktree in one pass, which is why only SAST fans out.
"""

from __future__ import annotations

import importlib.util
import json
import os
import shutil
import subprocess
import tempfile
import unittest
import zipfile
from pathlib import Path

SKILL_DIR = Path(__file__).resolve().parents[1]
SCRIPTS = SKILL_DIR / "scripts"
SCANNERS = SKILL_DIR / "scanners"
DETECT_UNITS = SCRIPTS / "detect-sast-units.sh"
RUN_SCAN = SCRIPTS / "run-scan.sh"
BASH = shutil.which("bash") or "/bin/bash"

_spec = importlib.util.spec_from_file_location("normalize_fanout", SCRIPTS / "normalize.py")
normalize = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(normalize)

FVDL = """<?xml version="1.0"?>
<FVDL xmlns="xmlns://www.fortifysoftware.com/schema/fvdl">
  <Vulnerabilities>
    <Vulnerability><ClassInfo><ClassID>1</ClassID><Type>XSS</Type><DefaultSeverity>4.0</DefaultSeverity></ClassInfo><InstanceInfo><FileName>crapi/shop/views.py</FileName><LineStart>7</LineStart></InstanceInfo></Vulnerability>
  </Vulnerabilities>
</FVDL>"""


def touch(root: Path, *relative: str) -> None:
    for item in relative:
        path = root / item
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("", encoding="utf-8")


class UnitDiscoveryTest(unittest.TestCase):
    def units(self, root: Path) -> list[str]:
        proc = subprocess.run(
            ["sh", str(DETECT_UNITS), "."], cwd=root, capture_output=True, text=True
        )
        self.assertEqual(proc.returncode, 0, proc.stderr)
        return [line for line in proc.stdout.splitlines() if line.strip()]

    def test_polyglot_monorepo_yields_one_unit_per_service(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            touch(
                root,
                "services/identity/build.gradle",
                "services/identity/pom.xml",       # part of the gradle build, not a unit
                "services/workshop/requirements.txt",
                "services/web/package.json",
                "services/community/go.mod",
                "node_modules/dep/package.json",   # dependency, never ours
            )
            self.assertEqual(
                self.units(root),
                [
                    "services/community|go",
                    "services/identity|gradle",
                    "services/web|javascript",
                    "services/workshop|python",
                ],
            )

    def test_gradle_multi_module_does_not_explode(self) -> None:
        """The root build owns its modules; one unit, not one per module."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            touch(root, "build.gradle", "settings.gradle", "a/build.gradle", "b/build.gradle")
            self.assertEqual(self.units(root), [".|gradle"])

    def test_single_root_project_is_one_unit(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            touch(root, "pom.xml", "src/main/Main.java")
            self.assertEqual(self.units(root), [".|maven"])

    def test_nothing_recognisable_yields_nothing(self) -> None:
        """Empty output must mean 'SAST did not run', never 'nothing to find'."""
        with tempfile.TemporaryDirectory() as tmp:
            self.assertEqual(self.units(Path(tmp)), [])

    def test_a_language_beside_another_is_not_pruned(self) -> None:
        """Ancestor pruning is per-language: a JS root must not hide a python service."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            touch(root, "package.json", "api/requirements.txt")
            self.assertEqual(self.units(root), [".|javascript", "api|python"])


class FanoutOrchestrationTest(unittest.TestCase):
    def scan(self, root: Path, *args: str, skip_fpr: str = "", **env_extra):
        repo = root / "repo"
        repo.mkdir(exist_ok=True)
        subprocess.run(["git", "init", "-q"], cwd=repo, check=True)
        bin_dir = root / "bin"
        bin_dir.mkdir(exist_ok=True)
        fixture = bin_dir / "fixture.fpr"
        with zipfile.ZipFile(fixture, "w") as archive:
            archive.writestr("audit.fvdl", FVDL)
        runtime = bin_dir / "fake-runtime"
        # Writes the report it was told to write, so "the unit ran" and "the unit
        # produced evidence" are separable — which is the whole thing under test.
        runtime.write_text(
            "#!/bin/sh\n"
            "name=\n"
            'for a in "$@"; do case "$a" in FPR_NAME=*) name=${a#FPR_NAME=} ;; esac; done\n'
            'if [ -n "$name" ] && [ "$name" != "$FAKE_SKIP_FPR" ]; then\n'
            '  mkdir -p .appsec-results\n'
            f'  cp "{fixture}" ".appsec-results/$name"\n'
            "fi\n"
            "exit 0\n",
            encoding="utf-8",
        )
        runtime.chmod(0o755)
        env_extra.setdefault("FAKE_SKIP_FPR", skip_fpr)
        env = {
            key: value
            for key, value in os.environ.items()
            if key not in ("SOURCE_PATH", "FORTIFY_LANGUAGE")
        }
        env.update(
            RUNTIME=str(runtime),
            SKILL_DIR=str(SKILL_DIR),
            SCANNERS_DIR=str(SCANNERS),
            SCRIPTS_DIR=str(SCRIPTS),
            APPSEC_PROFILE="catalog",
            RUN_FORTIFY_SAST="true",
            RUN_GITLAB_DS="false",
            RUN_SECRET_DETECTION="false",
            RUN_GITLAB_CS="false",
            FORTIFY_SAST_IMAGE="example/fortify:test",
            GITLAB_DS_IMAGE="example/ds:test",
            SECRET_DETECTION_IMAGE="example/secrets:test",
            GITLAB_CS_IMAGE="example/cs:test",
            CS_USER_ENV="U",
            CS_PASS_ENV="P",
            PYTHON_INSTALL_URL="",
            JQ_INSTALL_URL="",
            CI_GATE_FAIL_ON="high",
        )
        env.update(env_extra)
        return subprocess.run(
            [BASH, str(RUN_SCAN), "--only", "sast", *args],
            cwd=repo,
            env=env,
            capture_output=True,
            text=True,
        )

    def test_each_unit_gets_its_own_run_report_and_build_id(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "repo").mkdir()
            touch(
                root / "repo",
                "services/identity/build.gradle",
                "services/workshop/requirements.txt",
                "services/web/package.json",
            )
            proc = self.scan(root, "--dry-run")
        output = proc.stdout + proc.stderr
        self.assertIn("3 unit(s) to scan", output)
        for path, language in (
            ("services/identity", "gradle"),
            ("services/workshop", "python"),
            ("services/web", "javascript"),
        ):
            slug = path.replace("/", "-")
            with self.subTest(path=path):
                self.assertIn(f"-e SOURCE_PATH={path} ", output)
                self.assertIn(f"-e FORTIFY_LANGUAGE={language} ", output)
                # Distinct report AND distinct Fortify build id: sharing either
                # would let each unit's `-clean` wipe the previous one's build.
                self.assertIn(f"-e FPR_NAME=fortify-sast-{slug}.fpr ", output)
                self.assertIn(f"-e FORTIFY_BUILD_ID=repo-{slug} ", output)

    def test_single_unit_keeps_the_original_report_name(self) -> None:
        """A repo whose shape did not change must not see a new filename."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "repo").mkdir()
            touch(root / "repo", "pom.xml")
            proc = self.scan(root, "--dry-run")
        output = proc.stdout + proc.stderr
        self.assertIn("1 unit(s) to scan", output)
        self.assertIn("-e FPR_NAME=fortify-sast.fpr ", output)
        self.assertNotIn("fortify-sast-", output)

    def test_explicit_source_path_still_pins_one_unit(self) -> None:
        """The documented override must keep overriding discovery."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "repo").mkdir()
            touch(root / "repo", "services/a/pom.xml", "services/b/pom.xml")
            proc = self.scan(
                root, "--dry-run", SOURCE_PATH="services/a", FORTIFY_LANGUAGE="maven"
            )
        output = proc.stdout + proc.stderr
        self.assertIn("1 unit(s) to scan", output)
        self.assertIn("-e SOURCE_PATH=services/a ", output)
        self.assertNotIn("services/b", output)

    def _coverage(self, repo: Path):
        path = repo / ".appsec-results" / "scan-coverage.json"
        return json.loads(path.read_text(encoding="utf-8")) if path.exists() else None

    def test_root_manifest_no_longer_hides_subdirectory_services(self) -> None:
        """The false all-clear this whole change exists for.

        A root manifest used to satisfy detection on its own: one scan of the
        root produced one report, sast counted as covered, coverage_complete came
        back true — and the services beside it were never analysed, with nothing
        anywhere saying so."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            repo = root / "repo"
            repo.mkdir()
            touch(
                repo,
                "package.json",                      # the root manifest that used to win
                "services/api/pom.xml",
                "services/worker/requirements.txt",
            )
            proc = self.scan(root)
            coverage = self._coverage(repo)
            produced = sorted(
                p.name for p in (repo / ".appsec-results").glob("fortify-sast*.fpr")
            )
        output = proc.stdout + proc.stderr
        self.assertIn("3 unit(s) to scan", output)
        # Every unit analysed => a report each, and coverage genuinely complete.
        self.assertEqual(
            produced,
            [
                "fortify-sast-root.fpr",
                "fortify-sast-services-api.fpr",
                "fortify-sast-services-worker.fpr",
            ],
            output,
        )
        self.assertIsNotNone(coverage, output)
        # sast specifically is satisfied. coverage_complete stays false because
        # `--only sast` narrows what RUNS, never what is EXPECTED — the other
        # three categories are still owed.
        self.assertIn("sast", coverage["scanners_run"], coverage)
        self.assertNotIn("sast", coverage["missing_report"], coverage)

    def test_a_unit_with_no_report_breaks_coverage(self) -> None:
        """Two of three succeeding is not a scanned repository."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            repo = root / "repo"
            repo.mkdir()
            touch(
                repo,
                "package.json",
                "services/api/pom.xml",
                "services/worker/requirements.txt",
            )
            proc = self.scan(root, skip_fpr="fortify-sast-services-worker.fpr")
            coverage = self._coverage(repo)
        output = proc.stdout + proc.stderr
        self.assertIsNotNone(coverage, output)
        self.assertFalse(coverage["coverage_complete"], coverage)
        self.assertIn("sast", coverage["missing_report"], coverage)
        self.assertNotEqual(proc.returncode, 0, output)
        # And it must name WHICH source path went unscanned, not just "sast" —
        # the other two reports sitting on disk are what made this invisible.
        self.assertIn("services/worker", output)


class UnitPathPrefixTest(unittest.TestCase):
    """Fortify reports paths relative to the tree it scanned, so they must be
    re-rooted — the same defect CI fixed with --prepend-path, where every
    finding from four services was stamped with one service's path."""

    def write_fpr(self, results: Path, name: str) -> Path:
        path = results / name
        with zipfile.ZipFile(path, "w") as archive:
            archive.writestr("audit.fvdl", FVDL)
        return path

    def test_multi_unit_findings_are_rerooted_to_their_source_path(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            results = Path(tmp)
            (results / "sast-units").write_text(
                "services/workshop|python\nservices/web|javascript\n", encoding="utf-8"
            )
            fpr = self.write_fpr(results, "fortify-sast-services-workshop.fpr")
            findings = normalize.parse_fpr(fpr)
        self.assertEqual(
            [f["location"]["file"] for f in findings],
            ["services/workshop/crapi/shop/views.py"],
        )

    def test_single_unit_paths_are_left_alone(self) -> None:
        """One unit means paths are already repo-relative; prefixing would break them."""
        with tempfile.TemporaryDirectory() as tmp:
            results = Path(tmp)
            (results / "sast-units").write_text(".|python\n", encoding="utf-8")
            fpr = self.write_fpr(results, "fortify-sast.fpr")
            findings = normalize.parse_fpr(fpr)
        self.assertEqual(
            [f["location"]["file"] for f in findings], ["crapi/shop/views.py"]
        )

    def test_missing_units_file_is_not_an_error(self) -> None:
        """Reports predating the fan-out, or written by hand, still parse."""
        with tempfile.TemporaryDirectory() as tmp:
            fpr = self.write_fpr(Path(tmp), "fortify-sast.fpr")
            findings = normalize.parse_fpr(fpr)
        self.assertEqual(
            [f["location"]["file"] for f in findings], ["crapi/shop/views.py"]
        )

    def test_per_unit_report_still_counts_as_sast_evidence(self) -> None:
        """An unregistered report name satisfies no category, so a clean scan
        would report APPSEC-REPORT-MISSING and fail the gate on its own."""
        self.assertEqual(
            normalize._report_category(Path("fortify-sast-services-web.fpr")), "sast"
        )


if __name__ == "__main__":
    unittest.main()
