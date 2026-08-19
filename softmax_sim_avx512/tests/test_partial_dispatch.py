from __future__ import annotations

from collections import Counter
import unittest
from pathlib import Path

from src.simulator.engine import simulate
from src.simulator.profile import load_profile


ROOT = Path(__file__).resolve().parents[1]


class PartialDispatchTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.profile = load_profile(
            ROOT / "profiles/xsai.yaml", ROOT / "schemas/profile.schema.json"
        )

    @staticmethod
    def _m4_vector_load_trace() -> dict:
        return {
            "trace_version": 2,
            "workload": {"name": "xsai-m4-vector-load"},
            "instructions": [
                {
                    "id": "i0",
                    "sequence": 0,
                    "mnemonic": "vle32.v",
                    "profile_recipe": "vle32.v:any",
                    "assembly": "vle32.v v8, 0(a6)",
                    "operands": ["v8", "0(a6)"],
                    "register_reads": ["a6", "vconfig"],
                    "register_writes": ["v8", "v9", "v10", "v11"],
                    "register_dependencies": {},
                    "memory_dependencies": [],
                    "flags_dependency": None,
                    "memory": {
                        "address": 0x100000,
                        "region": "input",
                        "offset": 0,
                        "bytes": 64,
                        "cache_lines": [0x100000 // 64],
                        "access": "load",
                        "address_registers": ["a6"],
                    },
                    "semantic_uops": [
                        {"local_id": "u0", "kind": "address_generation"},
                        {
                            "local_id": "u1",
                            "kind": "vector_load",
                            "depends_on_local": ["u0"],
                        },
                    ],
                    "vector_state": {
                        "vlen_bits": 128,
                        "sew_bits": 32,
                        "lmul": "m4",
                        "vlmax": 16,
                        "vl": 16,
                        "tail_policy": "ta",
                        "mask_policy": "ma",
                    },
                    "active_vector_bits": 512,
                }
            ],
        }

    def test_xsai_m4_vector_load_drains_across_dispatch_cycles(self) -> None:
        bound = self.profile.bind(self._m4_vector_load_trace())
        # XSAI's unit-stride memory path includes an i2v preparation uop in
        # addition to the four AGU/load flow pairs.
        self.assertEqual(len(bound.uops), 9)
        self.assertEqual(bound.macros[0].dispatch_width_units, 9)

        result = simulate(bound, self.profile)
        macro = result.trace.macros[0]
        self.assertEqual(macro.dispatch_tick, 0)
        self.assertEqual(macro.rob_entry_count, 1)
        self.assertEqual(result.summary["rob_entries_allocated"], 1)
        self.assertEqual(result.summary["peak_rob"], 1)
        self.assertEqual(result.summary["dispatch_units"], 9)

        ticks = [uop.dispatch_tick for uop in result.trace.uops]
        self.assertEqual(
            Counter(ticks), Counter({0: 5, result.ticks_per_cycle: 4})
        )
        for tick in (0, result.ticks_per_cycle):
            self.assertEqual(
                Counter(
                    uop.scheduler_partition
                    for uop in result.trace.uops
                    if uop.dispatch_tick == tick
                ),
                Counter(
                    {"int-iq-2": 1, "vlsu-iq-0": 2, "vlsu-iq-1": 2}
                )
                if tick == 0
                else Counter({"vlsu-iq-0": 2, "vlsu-iq-1": 2}),
            )
        self.assertTrue(
            all(
                uop.issue_tick is not None and uop.complete_tick is not None
                for uop in result.trace.uops
            )
        )
        self.assertEqual(macro.retire_tick, result.ticks_per_cycle * 4)


if __name__ == "__main__":
    unittest.main()
