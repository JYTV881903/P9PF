"""Compile and exercise Java controller + reflection contracts using host-only stubs."""

import pathlib
import shutil
import subprocess
import tempfile
import unittest


ROOT = pathlib.Path(__file__).resolve().parents[1]
CASES = (
    "status", "noop", "enable", "asynchronous", "unsupported",
    "switchedBeforeWrite", "changedBeforeWrite", "restore", "restoreBinding",
    "restoreChangedTarget", "malformedBackup", "appliedThenThrow",
    "queuedThenThrow", "denied", "boundedTimeout", "reflectionContract",
    "switchedAfterApply", "shutdownRequest",
)


class SaPolicyTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.java = shutil.which("java")
        if cls.java is None:
            raise unittest.SkipTest("Java runtime/compiler unavailable")
        cls.tmp = tempfile.TemporaryDirectory(prefix="p9pf-sa-tests-")
        cls.addClassCleanup(cls.tmp.cleanup)
        cls.root = pathlib.Path(cls.tmp.name)
        cls.classes = cls.root / "classes"
        sources = [ROOT / "android/NrSaPolicy.java", *sorted((ROOT / "tests/java").rglob("*.java"))]
        compiled = subprocess.run(
            [cls.java, "com.sun.tools.javac.Main", "-source", "8", "-target", "8",
             "-Xlint:-options", "-d", str(cls.classes), *map(str, sources)],
            capture_output=True, text=True, timeout=30,
        )
        if compiled.returncode:
            raise AssertionError(compiled.stdout + compiled.stderr)


def make_test(case):
    def test(self):
        state = self.root / ("state-" + case)
        completed = subprocess.run(
            [self.java, "-cp", str(self.classes), "dev.p9pf.nrdc.NrSaPolicyTest", case, str(state)],
            capture_output=True, text=True, timeout=10,
        )
        self.assertEqual(completed.returncode, 0, completed.stdout + completed.stderr)
        self.assertIn("PASS " + case, completed.stdout)
    test.__name__ = "test_" + case
    return test


for _case in CASES:
    setattr(SaPolicyTests, "test_" + _case, make_test(_case))


if __name__ == "__main__":
    unittest.main()
