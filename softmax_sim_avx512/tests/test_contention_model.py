from __future__ import annotations

import unittest
from pathlib import Path

from src.simulator.engine import simulate
from src.simulator.profile import load_profile


ROOT = Path(__file__).resolve().parents[1]


STREAMS = {
    "conversion": (
        "vcvttps2dq",
        ["%zmm16", "%zmm0"],
        "vector_convert",
    ),
    "fma": (
        "vfmadd231ps",
        ["%zmm16", "%zmm17", "%zmm0"],
        "vector_fp_fma",
    ),
    "integer": (
        "vpaddd",
        ["%zmm16", "%zmm17", "%zmm0"],
        "vector_integer",
    ),
}


class ContentionModelTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.profile = load_profile(
            ROOT / "profiles/amd_zen4.yaml", ROOT / "schemas/profile.schema.json"
        )

    def _modeled_ipc(self, pattern: tuple[str, ...]) -> float:
        instructions = []
        for sequence, stream in enumerate(pattern * 256):
            mnemonic, operands, semantic_kind = STREAMS[stream]
            instructions.append(
                {
                    "id": f"i{sequence}",
                    "sequence": sequence,
                    "mnemonic": mnemonic,
                    "assembly": f"{mnemonic} " + ", ".join(operands),
                    "operands": operands,
                    "register_dependencies": {},
                    "memory_dependencies": [],
                    "flags_dependency": None,
                    "semantic_uops": [
                        {"local_id": "u0", "kind": semantic_kind}
                    ],
                }
            )
        dynamic = {
            "trace_version": 2,
            "workload": {"name": "contention-model-test"},
            "instructions": instructions,
        }
        result = simulate(self.profile.bind(dynamic), self.profile)
        by_id = {uop.id: uop for uop in result.trace.uops}
        issue_ticks = sorted(
            max(by_id[uop_id].issue_tick or 0 for uop_id in macro.uop_ids)
            for macro in result.trace.macros
        )
        trim = max(8, len(issue_ticks) // 10)
        steady = issue_ticks[trim:-trim]
        return (
            (len(steady) - 1)
            * result.ticks_per_cycle
            / (steady[-1] - steady[0])
        )

    def test_standalone_zmm_throughput_matches_microbenchmarks(self) -> None:
        expected = {"conversion": 1.0, "fma": 1.0, "integer": 2.0}
        for stream, expected_ipc in expected.items():
            with self.subTest(stream=stream):
                self.assertAlmostEqual(
                    self._modeled_ipc((stream,)), expected_ipc, delta=0.03
                )

    def test_mixed_zmm_throughput_matches_microbenchmarks(self) -> None:
        expected = {
            ("conversion", "integer"): 1.99245,
            ("fma", "integer"): 1.51607,
            ("conversion", "fma", "integer", "integer"): 1.99277,
        }
        for pattern, expected_ipc in expected.items():
            with self.subTest(pattern=pattern):
                self.assertAlmostEqual(
                    self._modeled_ipc(pattern), expected_ipc, delta=0.08
                )


if __name__ == "__main__":
    unittest.main()
