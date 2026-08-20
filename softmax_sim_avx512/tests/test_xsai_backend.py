from __future__ import annotations

import unittest
from pathlib import Path

from src.backend.xsai import XsaiRvvEngine, _XsaiUopExpander
from src.simulator.engine import backend_name, simulate
from src.simulator.profile import load_profile


ROOT = Path(__file__).resolve().parents[1]


def _instruction(
    mnemonic: str,
    recipe: str,
    operands: list[str],
    semantic_uops: list[dict],
    *,
    lmul: str = "m4",
    memory: dict | None = None,
) -> dict:
    return {
        "id": "i0",
        "sequence": 0,
        "mnemonic": mnemonic,
        "profile_recipe": recipe,
        "assembly": f"{mnemonic} " + ", ".join(operands),
        "operands": operands,
        "register_reads": [*operands[1:], "vconfig"],
        "register_writes": [operands[0]],
        "register_dependencies": {},
        "memory_dependencies": [],
        "flags_dependency": None,
        "memory": memory,
        "vector_state": {
            "vlen_bits": 128,
            "sew_bits": 32,
            "lmul": lmul,
            "vl": 16,
        },
        "active_vector_bits": 512,
        "semantic_uops": semantic_uops,
    }


def _trace(instruction: dict) -> dict:
    return {
        "trace_version": 2,
        "workload": {"name": "xsai-backend-uop-test"},
        "instructions": [instruction],
    }


class XsaiBackendTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.profile = load_profile(
            ROOT / "profiles/xsai.yaml", ROOT / "schemas/profile.schema.json"
        )

    def _engine(self, instruction: dict) -> _XsaiUopExpander:
        bound = self.profile.bind(_trace(instruction))
        return _XsaiUopExpander(bound, self.profile)

    def test_profile_selects_independent_xsai_backend(self) -> None:
        self.assertEqual(backend_name(self.profile), "xsai-rvv")

    def test_selected_backend_schedules_expanded_uops(self) -> None:
        instruction = _instruction(
            "vsetvli",
            "vsetvli:any",
            ["a0", "a1", "e32,m1,ta,ma"],
            [{"local_id": "u0", "kind": "vector_config"}],
            lmul="m1",
        )
        instruction["register_reads"] = ["a1"]
        instruction["register_writes"] = ["a0", "vconfig"]
        result = simulate(self.profile.bind(_trace(instruction)), self.profile)

        self.assertEqual(result.backend, "xsai-rvv")
        self.assertEqual(len(result.trace.uops), 2)
        self.assertEqual(result.summary["xsai_backend"]["scheduler_uops"], 2)
        self.assertTrue(all(uop.issue_tick is not None for uop in result.trace.uops))

    def test_vector_vector_expands_to_one_scheduler_uop_per_lmul_part(self) -> None:
        engine = self._engine(
            _instruction(
                "vfadd.vv",
                "vfadd.vv:any",
                ["v8", "v12", "v16"],
                [{"local_id": "u0", "kind": "vector_fp_add"}],
            )
        )
        uops = engine.backend_trace.uops_for_macro("i0")

        self.assertEqual(len(uops), 4)
        self.assertEqual({uop.role for uop in uops}, {"vector-lmul-part"})
        self.assertEqual([uop.part_index for uop in uops], [0, 1, 2, 3])
        self.assertTrue(all(len(uop.execution_uop_ids) == 1 for uop in uops))

    def test_vector_scalar_has_prep_plus_lmul_scheduler_uops(self) -> None:
        engine = self._engine(
            _instruction(
                "vfmax.vf",
                "vfmax.vf:any",
                ["v8", "v12", "fa0"],
                [{"local_id": "u0", "kind": "vector_fp_max"}],
            )
        )
        uops = engine.backend_trace.uops_for_macro("i0")

        self.assertEqual(len(uops), 5)
        self.assertEqual(uops[0].role, "vector-scalar-prep")
        self.assertEqual(
            [uop.role for uop in uops[1:]], ["vector-lmul-part"] * 4
        )
        self.assertTrue(all(uops[0].id in uop.dependencies for uop in uops[1:]))

    def test_vector_memory_has_prep_plus_one_scheduler_uop_per_flow(self) -> None:
        memory = {
            "address": 0x100000,
            "region": "input",
            "offset": 0,
            "bytes": 64,
            "cache_lines": [0x100000 // 64],
            "access": "load",
            "address_registers": ["a6"],
        }
        instruction = _instruction(
            "vle32.v",
            "vle32.v:any",
            ["v8", "0(a6)"],
            [
                {"local_id": "u0", "kind": "address_generation"},
                {
                    "local_id": "u1",
                    "kind": "vector_load",
                    "depends_on_local": ["u0"],
                },
            ],
            memory=memory,
        )
        instruction["register_reads"] = ["a6", "vconfig"]
        engine = self._engine(instruction)
        uops = engine.backend_trace.uops_for_macro("i0")

        self.assertEqual(len(engine.trace.uops), 9)
        self.assertEqual(len(uops), 5)
        self.assertEqual(uops[0].role, "vector-memory-prep")
        self.assertEqual([uop.role for uop in uops[1:]], ["vector-memory-flow"] * 4)
        self.assertTrue(all(len(uop.execution_uop_ids) == 2 for uop in uops[1:]))
        self.assertEqual(
            [uop.part_index for uop in uops[1:]], [0, 1, 2, 3]
        )

    def test_vector_config_decoded_count_is_real_scheduler_sequence(self) -> None:
        instruction = _instruction(
            "vsetvli",
            "vsetvli:any",
            ["a0", "a1", "e32,m1,ta,ma"],
            [{"local_id": "u0", "kind": "vector_config"}],
            lmul="m1",
        )
        instruction["register_reads"] = ["a1"]
        instruction["register_writes"] = ["a0", "vconfig"]
        engine = self._engine(instruction)
        uops = engine.backend_trace.uops_for_macro("i0")

        self.assertEqual(len(engine.trace.uops), 1)
        self.assertEqual(len(uops), 2)
        self.assertFalse(uops[0].owns_execution_timing)
        self.assertTrue(uops[1].owns_execution_timing)
        self.assertEqual(uops[1].dependencies, frozenset({uops[0].id}))
        self.assertEqual(uops[0].semantic_ids, uops[1].semantic_ids)

    def test_reduction_decoded_count_is_three_scheduler_uops(self) -> None:
        engine = self._engine(
            _instruction(
                "vfredmax.vs",
                "vfredmax.vs:any",
                ["v8", "v12", "v16"],
                [{"local_id": "u0", "kind": "vector_reduce_max"}],
                lmul="m1",
            )
        )
        uops = engine.backend_trace.uops_for_macro("i0")

        self.assertEqual(len(engine.trace.uops), 1)
        self.assertEqual(len(uops), 3)
        self.assertEqual([uop.role for uop in uops], [
            "vector-reduction-0",
            "vector-reduction-1",
            "vector-reduction-2",
        ])
        self.assertEqual(uops[1].dependencies, frozenset({uops[0].id}))
        self.assertEqual(uops[2].dependencies, frozenset({uops[1].id}))
        self.assertFalse(uops[0].owns_execution_timing)
        self.assertFalse(uops[1].owns_execution_timing)
        self.assertTrue(uops[2].owns_execution_timing)


if __name__ == "__main__":
    unittest.main()
