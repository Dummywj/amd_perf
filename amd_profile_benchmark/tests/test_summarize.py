from __future__ import annotations

import importlib.util
import json
import tempfile
import unittest
from pathlib import Path


SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "summarize.py"
SPEC = importlib.util.spec_from_file_location("benchmark_summarize", SCRIPT)
assert SPEC is not None and SPEC.loader is not None
summarize = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(summarize)


def valid_groups():
    groups = {
        f"{name}/4096/iterations:5": [{}]
        for name in summarize.ZMM_BASELINES
    }
    groups["BM_ContentionZmmConvertInteger1To1/4096/iterations:5"] = [
        {"retired_zmm_ops_per_target": 1.0}
    ]
    return groups


class ZmmContentionGateTest(unittest.TestCase):
    def test_accepts_complete_audited_group(self) -> None:
        self.assertEqual(summarize.zmm_contention_gate_failures(valid_groups()), [])

    def test_rejects_missing_standalone_baseline(self) -> None:
        groups = valid_groups()
        groups.pop("BM_VpadddThroughputZmm/4096/iterations:5")
        failures = summarize.zmm_contention_gate_failures(groups)
        self.assertTrue(any("missing standalone" in failure for failure in failures))

    def test_rejects_retired_instruction_mismatch(self) -> None:
        groups = valid_groups()
        mix = groups["BM_ContentionZmmConvertInteger1To1/4096/iterations:5"]
        mix[0]["retired_zmm_ops_per_target"] = 0.9
        failures = summarize.zmm_contention_gate_failures(groups)
        self.assertTrue(any("outside [0.98, 1.02]" in failure for failure in failures))

    def test_main_returns_nonzero_for_invalid_zmm_run(self) -> None:
        rows = []
        for run_name, group_rows in valid_groups().items():
            for row in group_rows:
                rows.append(
                    {
                        "run_name": run_name,
                        "run_type": "iteration",
                        "repetition_index": 0,
                        "issue_interval_cycles": 1.0,
                        "instructions_per_cycle": 1.0,
                        "pmu_running_ratio": 1.0,
                        "conversion_target_instructions": 32,
                        "fma_target_instructions": 0,
                        "integer_target_instructions": 32,
                        "conversion_instructions_per_cycle": 0.5,
                        "fma_instructions_per_cycle": 0.0,
                        "integer_instructions_per_cycle": 0.5,
                        "mixed_instructions_per_cycle": 1.0,
                        "static_source_operands_per_cycle": 1.5,
                        **row,
                    }
                )
        rows = [
            row
            for row in rows
            if not row["run_name"].startswith("BM_VpadddThroughputZmm/")
        ]
        with tempfile.TemporaryDirectory() as directory:
            input_path = Path(directory) / "raw.json"
            output_path = Path(directory) / "summary.md"
            input_path.write_text(json.dumps({"benchmarks": rows}), encoding="utf-8")
            old_argv = summarize.sys.argv
            summarize.sys.argv = ["summarize.py", str(input_path), str(output_path)]
            try:
                self.assertEqual(summarize.main(), 1)
            finally:
                summarize.sys.argv = old_argv
            self.assertIn("missing standalone baselines", output_path.read_text())


if __name__ == "__main__":
    unittest.main()
