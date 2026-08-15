"""detect-java-release.sh picks the Fortify JDK variant without asking anyone.

The rule it must never break: report the HIGHEST release declared anywhere in the
repository. A JDK compiles its own release and every earlier one, never a later
one, so the highest declaration is what decides the lowest usable JDK. Reporting
a lower one sends a Java 21 project to a JDK 17 analyzer, which is the silent
failure this script exists to prevent.

Guessing is worse than not knowing: an unreadable or templated version must come
back empty so the caller keeps its existing behaviour.
"""

from __future__ import annotations

import subprocess
import tempfile
import unittest
from pathlib import Path

SKILL_DIR = Path(__file__).resolve().parents[1]
DETECT = SKILL_DIR / "scripts" / "detect-java-release.sh"


class DetectJavaReleaseTest(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)

    def _write(self, relative: str, body: str) -> None:
        path = self.root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(body)

    def _detect(self) -> str:
        proc = subprocess.run(
            ["sh", str(DETECT), str(self.root)], capture_output=True, text=True
        )
        return proc.stdout.strip()

    # ---- Maven -----------------------------------------------------------

    def test_maven_compiler_release(self) -> None:
        self._write("pom.xml", "<project><properties>"
                    "<maven.compiler.release>21</maven.compiler.release>"
                    "</properties></project>")
        self.assertEqual(self._detect(), "21")

    def test_spring_boot_java_version_property(self) -> None:
        self._write("pom.xml", "<project><properties>"
                    "<java.version>17</java.version></properties></project>")
        self.assertEqual(self._detect(), "17")

    def test_legacy_source_target_normalises_1_8(self) -> None:
        self._write("pom.xml", "<project><build><plugins><plugin><configuration>"
                    "<source>1.8</source><target>1.8</target>"
                    "</configuration></plugin></plugins></build></project>")
        self.assertEqual(self._detect(), "8")

    def test_unresolved_property_is_unknown_not_a_guess(self) -> None:
        self._write("pom.xml", "<project><properties>"
                    "<java.version>${jdk.ver}</java.version></properties></project>")
        self.assertEqual(self._detect(), "")

    # ---- Gradle ----------------------------------------------------------

    def test_gradle_toolchain(self) -> None:
        self._write("build.gradle",
                    "java { toolchain { languageVersion = JavaLanguageVersion.of(21) } }")
        self.assertEqual(self._detect(), "21")

    def test_kotlin_dsl_jvm_toolchain(self) -> None:
        self._write("build.gradle.kts", "kotlin { jvmToolchain(17) }")
        self.assertEqual(self._detect(), "17")

    def test_source_compatibility_java_version_constant(self) -> None:
        self._write("build.gradle", "sourceCompatibility = JavaVersion.VERSION_21")
        self.assertEqual(self._detect(), "21")

    def test_source_compatibility_quoted_string(self) -> None:
        """The quote broke the first implementation of this."""
        self._write("build.gradle", "sourceCompatibility = '11'")
        self.assertEqual(self._detect(), "11")

    def test_source_compatibility_bare_number(self) -> None:
        self._write("build.gradle", "targetCompatibility = 17")
        self.assertEqual(self._detect(), "17")

    def test_old_groovy_style_without_equals(self) -> None:
        self._write("build.gradle", "sourceCompatibility JavaVersion.VERSION_1_8")
        self.assertEqual(self._detect(), "8")

    def test_buildsrc_convention_plugin(self) -> None:
        """Multi-module Gradle sets the toolchain once, in a convention plugin.

        Matching only build.gradle[.kts] missed every project built this way.
        """
        self._write("build.gradle.kts", 'plugins { id("java-conventions") }')
        self._write("buildSrc/src/main/kotlin/java-conventions.gradle.kts",
                    "java { toolchain { languageVersion = JavaLanguageVersion.of(21) } }")
        self.assertEqual(self._detect(), "21")

    def test_toolchain_version_held_in_gradle_properties(self) -> None:
        self._write("build.gradle",
                    "java { toolchain { languageVersion = JavaLanguageVersion.of(javaVersion) } }")
        self._write("gradle.properties", "javaVersion=21\n")
        self.assertEqual(self._detect(), "21")

    def test_compatibility_version_held_in_gradle_properties(self) -> None:
        self._write("build.gradle", "sourceCompatibility = jdkVersion")
        self._write("gradle.properties", "jdkVersion=17\n")
        self.assertEqual(self._detect(), "17")

    def test_unresolvable_property_name_is_unknown_not_a_guess(self) -> None:
        self._write("build.gradle",
                    "java { toolchain { languageVersion = JavaLanguageVersion.of(mystery) } }")
        self.assertEqual(self._detect(), "")

    # ---- Whole-repository behaviour --------------------------------------

    def test_multi_module_takes_the_highest(self) -> None:
        """A JDK 17 image cannot build the module that declares 21."""
        self._write("a/pom.xml", "<project><properties>"
                    "<maven.compiler.release>17</maven.compiler.release>"
                    "</properties></project>")
        self._write("b/pom.xml", "<project><properties>"
                    "<maven.compiler.release>21</maven.compiler.release>"
                    "</properties></project>")
        self.assertEqual(self._detect(), "21")

    def test_generated_build_output_never_outvotes_the_source(self) -> None:
        """A stale copy under target/ must not decide the analyzer image."""
        self._write("pom.xml", "<project><properties>"
                    "<maven.compiler.release>17</maven.compiler.release>"
                    "</properties></project>")
        self._write("target/classes/pom.xml", "<project><properties>"
                    "<maven.compiler.release>21</maven.compiler.release>"
                    "</properties></project>")
        self.assertEqual(self._detect(), "17")

    def test_mixed_maven_and_gradle_takes_the_highest(self) -> None:
        self._write("svc/pom.xml", "<project><properties>"
                    "<java.version>17</java.version></properties></project>")
        self._write("app/build.gradle", "sourceCompatibility = JavaVersion.VERSION_21")
        self.assertEqual(self._detect(), "21")

    def test_non_java_project_says_nothing(self) -> None:
        self._write("package.json", "{}")
        self._write("requirements.txt", "flask\n")
        self.assertEqual(self._detect(), "")

    def test_empty_directory_says_nothing(self) -> None:
        self.assertEqual(self._detect(), "")

    def test_implausible_numbers_are_rejected(self) -> None:
        """A plugin version is not a Java release."""
        self._write("pom.xml", "<project><build><plugins><plugin>"
                    "<configuration><source>3</source><target>999</target>"
                    "</configuration></plugin></plugins></build></project>")
        self.assertEqual(self._detect(), "")

    def test_exit_status_reports_whether_anything_was_found(self) -> None:
        self._write("pom.xml", "<project><properties>"
                    "<java.version>21</java.version></properties></project>")
        found = subprocess.run(["sh", str(DETECT), str(self.root)], capture_output=True)
        self.assertEqual(found.returncode, 0)

        empty = tempfile.TemporaryDirectory()
        self.addCleanup(empty.cleanup)
        missing = subprocess.run(["sh", str(DETECT), empty.name], capture_output=True)
        self.assertEqual(missing.returncode, 1)


if __name__ == "__main__":
    unittest.main()
