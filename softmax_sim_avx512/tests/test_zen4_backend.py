from __future__ import annotations

import unittest
from pathlib import Path

from src.backend.zen4 import Engine as Zen4Engine
from src.frontends.x86 import build_dynamic_trace
from src.simulator.engine import Engine, backend_name, simulate
from src.simulator.profile import load_profile


ROOT = Path(__file__).resolve().parents[1]


class Zen4BackendFreezeTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.profile = load_profile(
            ROOT / "profiles/amd_zen4.yaml",
            ROOT / "schemas/profile.schema.json",
        )

    def test_profile_selects_frozen_zen4_backend(self) -> None:
        self.assertEqual(backend_name(self.profile), "zen4")
        dynamic = build_dynamic_trace(
            ROOT / "kernel/vector_copy/artifacts/x86/vector_copy_avx512.s",
            "vector_copy_avx512_f32",
            ROOT / "recipes/x86.yaml",
            512,
        )
        selected = Engine(self.profile.bind(dynamic), self.profile)
        self.assertIsInstance(selected, Zen4Engine)

    def test_representative_cycles_match_frozen_validation(self) -> None:
        expected = {
            ("fma_throughput", 512): 541.0,
            ("fma_latency", 512): 2152.0,
            ("axpy", 1024): 173.0,
            ("vector_copy", 512): 68.0,
            ("mixed_compute", 2048): 429.0,
            ("pointer_agu", 2048): 409.0,
        }
        for (kernel, count), cycles in expected.items():
            with self.subTest(kernel=kernel, count=count):
                dynamic = build_dynamic_trace(
                    ROOT / f"kernel/{kernel}/artifacts/x86/{kernel}_avx512.s",
                    f"{kernel}_avx512_f32",
                    ROOT / "recipes/x86.yaml",
                    count,
                )
                result = simulate(self.profile.bind(dynamic), self.profile)
                self.assertEqual(result.backend, "zen4")
                self.assertEqual(result.cycles, cycles)


if __name__ == "__main__":
    unittest.main()
