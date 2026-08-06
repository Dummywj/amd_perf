from __future__ import annotations

import copy
import unittest
from pathlib import Path

from src.frontends.x86 import build_dynamic_trace
from src.simulator.engine import simulate
from src.simulator.profile import load_profile


ROOT = Path(__file__).resolve().parents[1]


class EngineTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.profile = load_profile(
            ROOT / "profiles/amd_zen4.yaml", ROOT / "schemas/profile.schema.json"
        )
        cls.dynamic = build_dynamic_trace(
            ROOT / "kernel/softmax/artifacts/x86/softmax_avx512.s",
            "softmax_avx512_f32",
            ROOT / "recipes/x86.yaml",
            32,
        )

    def test_out_of_order_is_faster_than_in_order(self) -> None:
        out_of_order = simulate(
            self.profile.bind(copy.deepcopy(self.dynamic)),
            self.profile,
            "out_of_order",
        )
        in_order = simulate(
            self.profile.bind(copy.deepcopy(self.dynamic)), self.profile, "in_order"
        )
        self.assertLess(out_of_order.cycles, in_order.cycles)
        self.assertEqual(
            out_of_order.summary["execution_uops"], in_order.summary["execution_uops"]
        )

    def test_result_is_deterministic_and_all_uops_complete(self) -> None:
        first = simulate(
            self.profile.bind(copy.deepcopy(self.dynamic)), self.profile, "out_of_order"
        )
        second = simulate(
            self.profile.bind(copy.deepcopy(self.dynamic)), self.profile, "out_of_order"
        )
        self.assertEqual(first.cycles, second.cycles)
        self.assertEqual(first.events, second.events)
        self.assertTrue(
            all(
                uop.dispatch_tick is not None
                and uop.issue_tick is not None
                and uop.complete_tick is not None
                for uop in first.trace.uops
            )
        )
        self.assertTrue(
            all(macro.retire_tick is not None for macro in first.trace.macros)
        )
        self.assertLessEqual(first.summary["peak_rob"], 320)
        self.assertLessEqual(first.summary["peak_vector_scheduler"], 64)
        self.assertLessEqual(
            first.summary["dependency_critical_path_cycles"], first.cycles
        )

    def test_zmm_parts_keep_one_cycle_gap_without_cross_part_raw(self) -> None:
        result = simulate(
            self.profile.bind(copy.deepcopy(self.dynamic)), self.profile, "out_of_order"
        )
        zmm_add = next(
            macro
            for macro in result.trace.macros
            if macro.mnemonic == "vaddps" and "%zmm" in macro.assembly
        )
        by_id = {uop.id: uop for uop in result.trace.uops}
        parts = [by_id[value] for value in zmm_add.uop_ids]
        self.assertEqual(len(parts), 2)
        self.assertEqual(
            parts[1].issue_tick - parts[0].issue_tick, result.ticks_per_cycle
        )


if __name__ == "__main__":
    unittest.main()
