import importlib.util
import unittest
from pathlib import Path


SCRIPT = Path(__file__).parents[1] / "scripts" / "check_l1_layout.py"
SPEC = importlib.util.spec_from_file_location("check_l1_layout", SCRIPT)
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(MODULE)


class L1LayoutTest(unittest.TestCase):
    def test_pointer_agu_n2048_uses_half_l1(self):
        case = MODULE.assess_case(0x80010000, 0x80016000, 2048, 3, None)
        self.assertEqual(case["status"], "PASS")
        self.assertEqual(case["working_set_bytes"], 32768)
        self.assertLessEqual(case["max_lines_per_set"], 3)

    def test_rejects_working_set_larger_than_budget(self):
        case = MODULE.assess_case(0x80010000, 0x80020000, 4096, 3, None)
        self.assertEqual(case["status"], "FAIL")

    def test_parses_llvm_nm_symbols(self):
        symbols = MODULE.parse_symbols(
            "0000000080010000 0000000000006000 B xsai_input_arena\n"
            "0000000080016000 0000000000002000 B xsai_output_arena\n"
        )
        self.assertEqual(symbols["xsai_input_arena"], (0x80010000, 0x6000))


if __name__ == "__main__":
    unittest.main()
