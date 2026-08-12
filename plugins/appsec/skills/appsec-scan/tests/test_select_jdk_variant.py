"""select-jdk-variant.sh maps a Java release onto a variant the component offers.

The offered set must come from scanners/fortify-sast.contract, never from a list
in the code. That is the failure this skill kept repeating: the contract recorded
input.variant.option=jdk21-review while the runner could only ever produce
jdk17-review, and no check noticed because nothing compares the two. Reading the
contract is what makes a future jdk25-review work with no code change at all.
"""

from __future__ import annotations

import subprocess
import tempfile
import unittest
from pathlib import Path

SKILL_DIR = Path(__file__).resolve().parents[1]
SELECT = SKILL_DIR / "scripts" / "select-jdk-variant.sh"
SHIPPED_CONTRACT = SKILL_DIR / "scanners" / "fortify-sast.contract"


class SelectJdkVariantTest(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)

    def _contract(self, *jdks: int) -> str:
        path = Path(self.tmp.name) / "fortify-sast.contract"
        lines = ["# header comment", "input.variant.default=jdk17-review"]
        lines += [f"input.variant.option=jdk{n}-review" for n in jdks]
        lines.append("input.language.option=maven")
        path.write_text("\n".join(lines) + "\n")
        return str(path)

    def _select(self, release: int, contract: str | None = None) -> str:
        argv = ["sh", str(SELECT), str(release)]
        if contract:
            argv.append(contract)
        proc = subprocess.run(argv, capture_output=True, text=True)
        return proc.stdout.strip()

    def test_smallest_sufficient_variant_wins(self) -> None:
        """Not the highest: picking needlessly high risks toolchain breakage."""
        contract = self._contract(17, 21, 25)
        self.assertEqual(self._select(8, contract), "jdk17-review")
        self.assertEqual(self._select(17, contract), "jdk17-review")
        self.assertEqual(self._select(18, contract), "jdk21-review")
        self.assertEqual(self._select(21, contract), "jdk21-review")
        self.assertEqual(self._select(22, contract), "jdk25-review")
        self.assertEqual(self._select(25, contract), "jdk25-review")

    def test_a_newly_published_variant_is_used_with_no_code_change(self) -> None:
        """The whole point. Same release, contract is the only thing that moved."""
        self.assertEqual(self._select(25, self._contract(17, 21)), "jdk21-review")
        self.assertEqual(self._select(25, self._contract(17, 21, 25)), "jdk25-review")

    def test_release_beyond_everything_offered_takes_the_highest(self) -> None:
        """Best available attempt; run-scan.sh warns that the JDK is behind."""
        self.assertEqual(self._select(30, self._contract(17, 21)), "jdk21-review")

    def test_single_variant_contract(self) -> None:
        self.assertEqual(self._select(21, self._contract(17)), "jdk17-review")

    def test_no_variant_options_leaves_the_image_alone(self) -> None:
        """Exit 1 and print nothing — never invent a tag that may not exist."""
        path = Path(self.tmp.name) / "bare.contract"
        path.write_text("input.language.option=maven\n")
        proc = subprocess.run(
            ["sh", str(SELECT), "21", str(path)], capture_output=True, text=True
        )
        self.assertEqual(proc.returncode, 1)
        self.assertEqual(proc.stdout.strip(), "")

    def test_missing_contract_leaves_the_image_alone(self) -> None:
        proc = subprocess.run(
            ["sh", str(SELECT), "21", str(Path(self.tmp.name) / "absent")],
            capture_output=True, text=True,
        )
        self.assertEqual(proc.returncode, 1)

    def test_non_numeric_release_is_rejected(self) -> None:
        proc = subprocess.run(
            ["sh", str(SELECT), "twenty-one"], capture_output=True, text=True
        )
        self.assertEqual(proc.returncode, 2)

    def test_defaults_to_the_shipped_contract(self) -> None:
        """No contract argument: find fortify-sast.contract next to the script."""
        self.assertEqual(self._select(21), "jdk21-review")
        self.assertEqual(self._select(11), "jdk17-review")

    def test_shipped_contract_still_offers_exactly_17_and_21(self) -> None:
        """A tripwire: if upstream publishes another variant and this contract is
        regenerated, this test fails and someone re-reads the mapping."""
        offered = sorted(
            line.split("=", 1)[1].strip()
            for line in SHIPPED_CONTRACT.read_text().splitlines()
            if line.startswith("input.variant.option=")
        )
        self.assertEqual(offered, ["jdk17-review", "jdk21-review"])


if __name__ == "__main__":
    unittest.main()
