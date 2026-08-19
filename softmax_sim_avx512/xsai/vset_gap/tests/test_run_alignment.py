from __future__ import annotations

import csv
import importlib.util
import tempfile
import unittest
from pathlib import Path

from src.frontends.rvv import build_dynamic_trace


ROOT = Path(__file__).resolve().parents[3]
SCRIPT = ROOT / "xsai/vset_gap/scripts/run_alignment.py"
SPEC = importlib.util.spec_from_file_location("vset_gap_run_alignment", SCRIPT)
assert SPEC is not None and SPEC.loader is not None
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


class VsetGapAlignmentTest(unittest.TestCase):
    def test_fixture_matches_forms_and_expands_64_iterations_at_vl_four(self) -> None:
        fixture = ROOT / "xsai/vset_gap/fixtures/vset_gap_expanded.s"
        MODULE.audit_fixture(fixture)
        expected_instructions = {
            "regular_lfs": 649,
            "keep_vl_lfs": 649,
            "vlmax_lfs": 649,
            "outside_lfs": 585,
            "regular_load": 455,
            "outside_load": 390,
            "load_stream_1": 453,
            "load_stream_2": 584,
            "load_stream_4": 846,
            "aligned_load_stream_2": 585,
            "aligned_load_stream_4": 847,
            "regular_compute": 331,
            "regular_store": 456,
        }
        for name, function, expected_vsets, _, expected_bytes in MODULE.CASE_SPECS:
            with self.subTest(name=name):
                trace = build_dynamic_trace(
                    fixture,
                    function,
                    ROOT / "recipes/rvv.yaml",
                    64,
                    ROOT / "uops/uop_kinds.yaml",
                    vlen_bits=128,
                )
                self.assertEqual(
                    trace["statistics"]["dynamic_instruction_count"],
                    expected_instructions[name],
                )
                self.assertEqual(
                    sum(
                        item["mnemonic"] == "vsetvli"
                        for item in trace["instructions"]
                    ),
                    expected_vsets,
                )
                self.assertEqual(
                    trace["statistics"]["input_output_total_bytes"], expected_bytes
                )
                self.assertTrue(
                    all(
                        item["vector_state"]["vl"] == 4
                        for item in trace["instructions"]
                        if item["mnemonic"].startswith("v")
                    )
                )

    def test_rtl_summary_requires_exact_clean_64_iteration_matrix(self) -> None:
        fields = [
            "source",
            "name",
            "iterations",
            "median_cycles",
            "cycles_per_iteration",
            "cache_status",
            "fit_status",
        ]
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "summary.csv"
            with path.open("w", newline="", encoding="utf-8") as target:
                writer = csv.DictWriter(target, fieldnames=fields)
                writer.writeheader()
                for index, spec in enumerate(MODULE.CASE_SPECS):
                    writer.writerow(
                        {
                            "source": "rtl",
                            "name": spec[0],
                            "iterations": 64,
                            "median_cycles": 100 + index,
                            "cycles_per_iteration": "1.0",
                            "cache_status": "CLEAN",
                            "fit_status": "VALID",
                        }
                    )
            rows = MODULE.read_rtl_summary(path)
            self.assertEqual(set(rows), {spec[0] for spec in MODULE.CASE_SPECS})

            text = path.read_text(encoding="utf-8").replace(
                "regular_store,64", "regular_store,63"
            )
            path.write_text(text, encoding="utf-8")
            with self.assertRaisesRegex(MODULE.AlignmentError, "64 iterations"):
                MODULE.read_rtl_summary(path)


if __name__ == "__main__":
    unittest.main()
