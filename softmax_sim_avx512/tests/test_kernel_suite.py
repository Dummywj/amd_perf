from __future__ import annotations

import unittest
from pathlib import Path

import yaml

from src.frontends.x86 import build_dynamic_trace
from src.simulator.engine import simulate
from src.simulator.profile import load_profile


ROOT = Path(__file__).resolve().parents[1]
KERNELS = (
    "fma_throughput",
    "fma_latency",
    "axpy",
    "dot_product",
    "vector_copy",
    "vector_triad",
    "vector_reduction",
    "conversion",
    "vector_integer",
    "mixed_compute",
    "pointer_agu",
)


class KernelSuiteTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.profile = load_profile(
            ROOT / "profiles/amd_zen4.yaml", ROOT / "schemas/profile.schema.json"
        )

    def test_workloads_bind_and_run_in_both_execution_models(self) -> None:
        for kernel in KERNELS:
            with self.subTest(kernel=kernel):
                workload = yaml.safe_load(
                    (ROOT / f"kernel/{kernel}/workloads/{kernel}.yaml").read_text(
                        encoding="utf-8"
                    )
                )
                self.assertEqual(workload["function"], f"{kernel}_avx512_f32")
                self.assertEqual(
                    [point["count"] for point in workload["points"]],
                    [256, 1024, 4096],
                )
                dynamic = build_dynamic_trace(
                    ROOT / f"kernel/{kernel}/artifacts/x86/{kernel}_avx512.s",
                    f"{kernel}_avx512_f32",
                    ROOT / "recipes/x86.yaml",
                    256,
                    ROOT / "uops/uop_kinds.yaml",
                )
                bound = self.profile.bind(dynamic)
                out_of_order = simulate(bound, self.profile, "out_of_order", "hot-l1")
                in_order = simulate(bound, self.profile, "in_order", "hot-l1")
                self.assertGreater(out_of_order.cycles, 0)
                self.assertGreaterEqual(in_order.cycles, out_of_order.cycles)
                self.assertTrue(
                    all(macro.retire_tick is not None for macro in out_of_order.trace.macros)
                )


if __name__ == "__main__":
    unittest.main()
