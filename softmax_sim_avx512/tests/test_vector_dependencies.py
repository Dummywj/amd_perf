from __future__ import annotations

import copy
import unittest
from pathlib import Path
from typing import Any

from src.simulator.engine import simulate
from src.simulator.profile import Profile, load_profile


ROOT = Path(__file__).resolve().parents[1]


class VectorDependencyPolicyTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.profile = load_profile(
            ROOT / "profiles/xsai.yaml", ROOT / "schemas/profile.schema.json"
        )

    @staticmethod
    def _vector_state() -> dict[str, Any]:
        return {
            "vlen_bits": 128,
            "sew_bits": 32,
            "lmul": "m4",
            "vl": 16,
        }

    @classmethod
    def _vector_load_trace(cls) -> dict[str, Any]:
        return {
            "trace_version": 2,
            "workload": {"name": "vector-state-load-policy"},
            "instructions": [
                {
                    "id": "i0",
                    "sequence": 0,
                    "mnemonic": "opaque-vset",
                    "profile_recipe": "vsetvli:any",
                    "assembly": "opaque-vset",
                    "operands": ["a1", "a2", "e32", "m4"],
                    "register_reads": ["a2"],
                    "register_writes": ["a1", "vconfig"],
                    "register_dependencies": {},
                    "memory_dependencies": [],
                    "flags_dependency": None,
                    "memory": None,
                    "vector_state": cls._vector_state(),
                    "active_vector_bits": 512,
                    "semantic_uops": [
                        {"local_id": "u0", "kind": "vector_config"}
                    ],
                },
                {
                    "id": "i1",
                    "sequence": 1,
                    "mnemonic": "opaque-vector-load",
                    "profile_recipe": "vle32.v:any",
                    "assembly": "opaque-vector-load v0, 0(a0)",
                    "operands": ["v0", "0(a0)"],
                    "register_reads": ["a0", "vconfig"],
                    "register_writes": ["v0", "v1", "v2", "v3"],
                    "register_dependencies": {"vconfig": "i0"},
                    "memory_dependencies": [],
                    "flags_dependency": None,
                    "memory": {
                        "address": 0x100000,
                        "region": "input",
                        "offset": 0,
                        "bytes": 64,
                        "cache_lines": [0x100000 // 64],
                        "access": "load",
                        "address_registers": ["a0"],
                    },
                    "vector_state": cls._vector_state(),
                    "active_vector_bits": 512,
                    "semantic_uops": [
                        {"local_id": "u0", "kind": "address_generation"},
                        {
                            "local_id": "u1",
                            "kind": "vector_load",
                            "depends_on_local": ["u0"],
                        },
                    ],
                },
            ],
        }

    @staticmethod
    def _old_destination_trace() -> dict[str, Any]:
        vector_state = {
            "vlen_bits": 128,
            "sew_bits": 32,
            "lmul": "m1",
            "vl": 4,
        }

        def instruction(
            instruction_id: str, sequence: int, *, reads_old_destination: bool
        ) -> dict[str, Any]:
            semantic: dict[str, Any] = {
                "local_id": "u0",
                "kind": "vector_fp_add",
            }
            if reads_old_destination:
                semantic.update(
                    {
                        "reads_old_destination": True,
                        "old_destination_registers": ["v0"],
                    }
                )
            return {
                "id": instruction_id,
                "sequence": sequence,
                "mnemonic": f"opaque-{instruction_id}",
                "profile_recipe": "vfadd.vv:any",
                "assembly": f"opaque-{instruction_id} v0, v1, v2",
                "operands": ["v0", "v1", "v2"],
                "register_reads": ["v1", "v2"],
                "register_writes": ["v0"],
                "register_dependencies": {},
                "old_destination_registers": ["v0"] if reads_old_destination else [],
                "old_destination_dependencies": (
                    {"v0": "i0"} if reads_old_destination else {}
                ),
                "memory_dependencies": [],
                "flags_dependency": None,
                "memory": None,
                "vector_state": vector_state,
                "active_vector_bits": 128,
                "semantic_uops": [semantic],
            }

        return {
            "trace_version": 2,
            "workload": {"name": "semantic-old-destination-policy"},
            "instructions": [
                instruction("i0", 0, reads_old_destination=False),
                instruction("i1", 1, reads_old_destination=True),
            ],
        }

    def _without_policy(self) -> Profile:
        data = copy.deepcopy(self.profile.data)
        del data["backend"]["vector_dependency"]
        return Profile(self.profile.path, data, "no-vector-dependency-policy")

    def test_xsai_all_load_data_flows_wait_for_vconfig(self) -> None:
        bound = self.profile.bind(self._vector_load_trace())
        configure = next(uop for uop in bound.uops if uop.parent_id == "i0")
        loads = [
            uop
            for uop in bound.uops
            if uop.parent_id == "i1" and uop.kind == "load_data"
        ]
        addresses = [
            uop
            for uop in bound.uops
            if uop.parent_id == "i1" and uop.kind == "address_generation"
        ]

        self.assertEqual(len(loads), 4)
        self.assertTrue(all(uop.requires_vector_state for uop in loads))
        self.assertTrue(
            all(uop.vector_state_dependencies == {configure.id} for uop in loads)
        )
        self.assertTrue(all(not uop.requires_vector_state for uop in addresses))

        result = simulate(bound, self.profile)
        issued_configure = next(
            uop for uop in result.trace.uops if uop.id == configure.id
        )
        issued_loads = [
            uop for uop in result.trace.uops if uop.parent_id == "i1" and uop.kind == "load_data"
        ]
        self.assertTrue(
            all(
                (uop.issue_tick or 0) >= (issued_configure.complete_tick or 0)
                for uop in issued_loads
            )
        )
        self.assertGreater(
            result.summary["issue_blocker_observations"].get(
                "vector_state_dependency", 0
            ),
            0,
        )

    def test_absent_policy_preserves_legacy_load_dependencies(self) -> None:
        profile = self._without_policy()
        bound = profile.bind(self._vector_load_trace())
        loads = [uop for uop in bound.uops if uop.kind == "load_data"]

        self.assertTrue(all(not uop.requires_vector_state for uop in loads))
        self.assertTrue(all(not uop.vector_state_dependencies for uop in loads))

    def test_semantic_old_destination_adds_profile_driven_raw_edge(self) -> None:
        bound = self.profile.bind(self._old_destination_trace())
        producer = next(uop for uop in bound.uops if uop.parent_id == "i0")
        consumer = next(uop for uop in bound.uops if uop.parent_id == "i1")

        self.assertTrue(consumer.reads_old_destination)
        self.assertEqual(consumer.old_destination_dependencies, {producer.id})
        self.assertIn(producer.id, consumer.dependencies)

        result = simulate(bound, self.profile)
        result_uops = {uop.id: uop for uop in result.trace.uops}
        self.assertGreaterEqual(
            result_uops[consumer.id].issue_tick or 0,
            result_uops[producer.id].complete_tick or 0,
        )
        self.assertGreater(
            result.summary["issue_blocker_observations"].get(
                "old_destination_dependency", 0
            ),
            0,
        )

    def test_profile_implicit_old_destination_adds_waw_as_raw_edge(self) -> None:
        trace = self._old_destination_trace()
        producer, consumer = trace["instructions"]
        consumer["semantic_uops"] = [
            {"local_id": "u0", "kind": "vector_fp_add"}
        ]
        consumer["old_destination_registers"] = []
        consumer["old_destination_dependencies"] = {}
        producer["vector_destination_registers"] = ["v0"]
        producer["vector_destination_dependencies"] = {}
        consumer["vector_destination_registers"] = ["v0"]
        consumer["vector_destination_dependencies"] = {"v0": "i0"}

        bound = self.profile.bind(trace)
        producer_uop = next(uop for uop in bound.uops if uop.parent_id == "i0")
        consumer_uop = next(uop for uop in bound.uops if uop.parent_id == "i1")

        self.assertTrue(consumer_uop.reads_old_destination)
        self.assertEqual(
            consumer_uop.old_destination_dependencies, {producer_uop.id}
        )
        self.assertIn(producer_uop.id, consumer_uop.dependencies)

    def test_integer_kind_does_not_gain_implicit_old_destination(self) -> None:
        trace = self._old_destination_trace()
        for index, instruction in enumerate(trace["instructions"]):
            instruction["profile_recipe"] = "vmv.v.v:any"
            instruction["mnemonic"] = "opaque-vector-move"
            instruction["semantic_uops"] = [
                {"local_id": "u0", "kind": "vector_move"}
            ]
            instruction["old_destination_registers"] = []
            instruction["old_destination_dependencies"] = {}
            instruction["vector_destination_registers"] = ["v0"]
            instruction["vector_destination_dependencies"] = (
                {"v0": "i0"} if index else {}
            )

        bound = self.profile.bind(trace)
        consumer = next(uop for uop in bound.uops if uop.parent_id == "i1")

        self.assertFalse(consumer.reads_old_destination)
        self.assertFalse(consumer.old_destination_dependencies)

    def test_semantic_old_destination_is_inert_without_policy(self) -> None:
        profile = self._without_policy()
        bound = profile.bind(self._old_destination_trace())
        consumer = next(uop for uop in bound.uops if uop.parent_id == "i1")

        self.assertFalse(consumer.reads_old_destination)
        self.assertFalse(consumer.old_destination_dependencies)
        self.assertFalse(consumer.dependencies)


if __name__ == "__main__":
    unittest.main()
