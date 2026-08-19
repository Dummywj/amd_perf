from __future__ import annotations

import copy
import unittest
from pathlib import Path

from src.frontends.rvv import build_dynamic_trace as build_rvv_dynamic_trace
from src.frontends.x86 import build_dynamic_trace
from src.simulator.engine import simulate
from src.simulator.memory import MemoryModelError
from src.simulator.profile import load_profile


ROOT = Path(__file__).resolve().parents[1]


class MemoryTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.profile = load_profile(
            ROOT / "profiles/amd_zen4.yaml", ROOT / "schemas/profile.schema.json"
        )

    def _trace(self, count: int):
        dynamic = build_dynamic_trace(
            ROOT / "kernel/softmax/artifacts/x86/softmax_avx512.s",
            "softmax_avx512_f32",
            ROOT / "recipes/x86.yaml",
            count,
        )
        return self.profile.bind(dynamic)

    def test_cold_loads_reach_dram_and_cost_more_than_hot_l1(self) -> None:
        hot = simulate(self._trace(16), self.profile, cache_mode="hot-l1")
        cold = simulate(self._trace(16), self.profile, cache_mode="cold")
        self.assertGreater(cold.cycles, hot.cycles)
        self.assertGreater(cold.summary["cache_line_accesses"]["dram"], 0)
        self.assertTrue(
            any(uop.memory_level == "dram" for uop in cold.trace.uops)
        )

    def test_hot_l1_rejects_capacity_boundary_working_set(self) -> None:
        with self.assertRaises(MemoryModelError):
            simulate(self._trace(4096), self.profile, cache_mode="hot-l1")

    def test_hot_capacity_places_boundary_working_set_in_l2(self) -> None:
        result = simulate(self._trace(4096), self.profile, cache_mode="hot-capacity")
        self.assertGreater(result.summary["cache_line_accesses"]["l2"], 0)
        self.assertEqual(result.summary["cache_line_accesses"]["dram"], 0)

    def test_memory_completion_keeps_recipe_side_latency(self) -> None:
        base = load_profile(
            ROOT / "profiles/xsai.yaml", ROOT / "schemas/profile.schema.json"
        )
        data = copy.deepcopy(base.data)
        for entry in data["recipes"]["vle32.v:any"]["uops"]:
            if entry["kind"] == "load_data":
                entry["latency_cycles"] = 7
        for entry in data["recipes"]["vse32.v:any"]["uops"]:
            if entry["kind"] == "store_data":
                entry["latency_cycles"] = 5
        data["memory"]["levels"]["l1d"]["latency_cycles"] = 3
        profile = type(base)(base.path, data, "memory-recipe-latency")
        dynamic = build_rvv_dynamic_trace(
            ROOT / "kernel/vector_copy/artifacts/rvv/vector_copy_rvv.s",
            "vector_copy_rvv_f32",
            ROOT / "recipes/rvv.yaml",
            4,
            ROOT / "uops/uop_kinds.yaml",
            vlen_bits=128,
        )

        result = simulate(profile.bind(dynamic), profile, cache_mode="hot-l1")
        load = next(uop for uop in result.trace.uops if uop.kind == "load_data")
        store = next(uop for uop in result.trace.uops if uop.kind == "store_data")

        self.assertEqual(load.latency_ticks, profile.ticks(7))
        self.assertEqual(store.latency_ticks, profile.ticks(5))
        self.assertEqual(load.complete_tick - load.issue_tick, profile.ticks(7))
        self.assertEqual(store.complete_tick - store.issue_tick, profile.ticks(5))


if __name__ == "__main__":
    unittest.main()
