"""scanners/fortify-sast.sh must run the command the CI component runs.

The gradle arm is the one that can silently disagree. The component invokes
`$[[ inputs.source-path ]]/gradlew` (template.yml:130); this runner used to invoke
`./gradlew`. Whenever source-path is not ".", those are different files — so the
local scan and the CI job could execute different builds, and a repository with the
wrapper in only one of the two places passed in one and failed in the other with a
message that looked like a broken build rather than a path mismatch.

Executed with a stub `sourceanalyzer` on PATH, so these assert the actual command
line rather than the shape of the source file.
"""

from __future__ import annotations

import os
import stat
import subprocess
import tempfile
import unittest
from pathlib import Path

SKILL_DIR = Path(__file__).resolve().parents[1]
RUNNER = SKILL_DIR / "scanners" / "fortify-sast.sh"


class FortifyRunnerTest(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.bin = self.root / "stub-bin"
        self.bin.mkdir()
        stub = self.bin / "sourceanalyzer"
        stub.write_text("#!/bin/sh\necho \"sourceanalyzer $*\"\n")
        stub.chmod(stub.stat().st_mode | stat.S_IEXEC)

    def _repo(self, name: str, *wrappers: str) -> Path:
        repo = self.root / name
        (repo / "src").mkdir(parents=True)
        for rel in wrappers:
            path = repo / rel
            path.write_text("#!/bin/sh\n")
            path.chmod(path.stat().st_mode | stat.S_IEXEC)
        return repo

    def _run(self, repo: Path, language: str = "gradle",
             source_path: str = "src") -> subprocess.CompletedProcess[str]:
        env = dict(
            os.environ,
            PATH=f"{self.bin}{os.pathsep}{os.environ['PATH']}",
            CI_PROJECT_DIR=str(repo),
            SOURCE_PATH=source_path,
            FORTIFY_LANGUAGE=language,
            APP_NAME="demo",
        )
        return subprocess.run(
            ["sh", str(RUNNER)], cwd=repo, env=env, capture_output=True, text=True
        )

    def test_uses_the_wrapper_ci_uses(self) -> None:
        result = self._run(self._repo("a", "src/gradlew"))
        self.assertIn("sourceanalyzer -b demo src/gradlew -p src clean assemble",
                      result.stdout)
        self.assertNotIn("./gradlew -p", result.stdout)
        self.assertNotIn("WARNING", result.stderr)

    def test_root_wrapper_still_scans_but_predicts_the_ci_failure(self) -> None:
        """The whole value of a pre-push scan: say what CI will do, before CI does."""
        result = self._run(self._repo("b", "gradlew"))
        self.assertIn("sourceanalyzer -b demo ./gradlew -p src clean assemble",
                      result.stdout)
        self.assertIn("CI runs src/gradlew, which does not exist here", result.stderr)
        self.assertIn("the CI job", result.stderr)

    def test_no_wrapper_anywhere_fails_loudly(self) -> None:
        result = self._run(self._repo("c"))
        self.assertEqual(result.returncode, 2)
        self.assertIn("no gradle wrapper", result.stderr)

    def test_source_path_dot_uses_the_root_wrapper_without_warning(self) -> None:
        """source-path: . is the layout the component's own README assumes."""
        result = self._run(self._repo("d", "gradlew"), source_path=".")
        self.assertIn("sourceanalyzer -b demo ./gradlew -p . clean assemble",
                      result.stdout)
        self.assertNotIn("WARNING", result.stderr)

    def test_diagnostic_flags_match_the_component(self) -> None:
        """-debug-verbose changes only log output, but a translation that fails
        without it is markedly harder to diagnose than the CI job it mirrors."""
        maven = self._run(self._repo("m"), language="maven")
        self.assertIn("sourceanalyzer -debug -verbose -b demo mvn clean install",
                      maven.stdout)

        python = self._run(self._repo("p"), language="python")
        self.assertIn("-debug-verbose", python.stdout)
        self.assertIn("-python-version 3", python.stdout)

        javascript = self._run(self._repo("j"), language="javascript")
        self.assertIn("-debug-verbose", javascript.stdout)
        self.assertIn("-Dcom.fortify.sca.follow.imports=false", javascript.stdout)

    def test_python_arm_does_not_pass_python_path(self) -> None:
        """Deliberate: the component's `.venv` cannot exist in that job, and
        -python-path alone does not add the library to the build anyway. See
        github issue #12 — do not "restore" this without the translation target."""
        result = self._run(self._repo("q"), language="python")
        self.assertNotIn("-python-path", result.stdout)


if __name__ == "__main__":
    unittest.main()
