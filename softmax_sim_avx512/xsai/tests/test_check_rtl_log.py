import importlib.util
import unittest
from pathlib import Path


SCRIPT = Path(__file__).parents[1] / "scripts" / "check_rtl_log.py"
SPEC = importlib.util.spec_from_file_location("check_rtl_log", SCRIPT)
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(MODULE)


class CheckRtlLogTest(unittest.TestCase):
    def assertAccepted(self, text):
        self.assertEqual(MODULE.check_log(text), [])

    def assertRejected(self, text, reason):
        self.assertIn(reason, MODULE.check_log(text))

    def test_success_ignores_performance_counter_mismatch(self):
        self.assertAccepted("ras_top_mismatch=0\nHIT GOOD TRAP\n")

    def test_success_accepts_colored_emulator_marker(self):
        self.assertAccepted(
            "[PERF] SimTopCore 0: \x1b[32mHIT GOOD TRAP at pc = 0x80000000\n"
        )

    def test_missing_good_trap_is_rejected(self):
        self.assertRejected("HIT something else\n", "missing HIT GOOD TRAP")

    def test_bad_trap_is_rejected(self):
        self.assertRejected("HIT GOOD TRAP\nHIT BAD TRAP\n", "HIT BAD TRAP")

    def test_explicit_difftest_mismatch_or_fail_is_rejected(self):
        for marker in ("difftest mismatch", "difftest fail", "DIFFTEST FAILED"):
            with self.subTest(marker=marker):
                self.assertRejected(
                    f"HIT GOOD TRAP\n{marker}\n", "explicit difftest mismatch/fail"
                )

    def test_abort_is_rejected(self):
        self.assertRejected("HIT GOOD TRAP\nABORT\n", "ABORT")


if __name__ == "__main__":
    unittest.main()
