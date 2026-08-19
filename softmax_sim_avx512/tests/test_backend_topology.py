from __future__ import annotations

import copy
import unittest
from pathlib import Path
from typing import Any

from src.simulator.engine import simulate
from src.simulator.model import BoundTrace, ExecutionUop, MacroOp
from src.simulator.profile import Profile, ProfileError, load_profile


ROOT = Path(__file__).resolve().parents[1]


class BackendTopologyTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        base = load_profile(ROOT / "profiles/amd_zen4.yaml")
        data = copy.deepcopy(base.data)
        data["resources"]["integer-to-vector"] = {
            "kind": "vector_integer",
            "capacity": 1,
            "width_bits": 128,
        }
        data["resources"]["fp-to-vector"] = {
            "kind": "vector_fp",
            "capacity": 1,
            "width_bits": 128,
        }
        data["pipeline"]["vector_scheduler_entries"] = 8
        data["backend"] = {
            "execution_model": "generic-token",
            "scheduler_partitions": [
                {
                    "id": "compute-iq",
                    "kind": "vector_compute",
                    "entries": 8,
                    "enqueue_width": 8,
                    "execution_units": ["slot-fp", "slot-convert"],
                },
                {
                    "id": "memory-iq",
                    "kind": "vector_memory",
                    "entries": 8,
                    "enqueue_width": 8,
                    "execution_units": ["slot-memory"],
                },
                {
                    "id": "scalar-prep-iq",
                    "kind": "scalar",
                    "entries": 4,
                    "enqueue_width": 2,
                    "execution_units": ["slot-i2v", "slot-f2v"],
                },
            ],
            "execution_units": {
                "slot-fp": {
                    "scheduler_partition": "compute-iq",
                    "functional_units": ["vector-fp"],
                    "vector_read_domain": "shared-rd",
                    "vector_writeback_domain": "shared-wb",
                },
                "slot-convert": {
                    "scheduler_partition": "compute-iq",
                    "functional_units": ["conversion"],
                    "vector_read_domain": "shared-rd",
                    "vector_writeback_domain": "shared-wb",
                },
                "slot-memory": {
                    "scheduler_partition": "memory-iq",
                    "functional_units": [
                        "address-generation",
                        "load-data",
                        "store-data",
                    ],
                    "vector_read_domain": "memory-rd",
                    "vector_writeback_domain": "memory-wb",
                },
                "slot-i2v": {
                    "scheduler_partition": "scalar-prep-iq",
                    "functional_units": ["integer-to-vector"],
                    "vector_writeback_domain": "prep-wb",
                },
                "slot-f2v": {
                    "scheduler_partition": "scalar-prep-iq",
                    "functional_units": ["fp-to-vector"],
                    "vector_writeback_domain": "prep-wb",
                },
            },
            "register_files": {
                "vector": {
                    "logical_registers": 32,
                    "physical_registers": 64,
                    "width_bits": 128,
                    "read_ports": 4,
                    "writeback_ports": 3,
                    "read_domains": {
                        "shared-rd": {
                            "port_count": 8,
                            "arbitration_capacity": 8,
                            "execution_units": ["slot-fp", "slot-convert"],
                        },
                        "memory-rd": {
                            "port_count": 8,
                            "arbitration_capacity": 8,
                            "execution_units": ["slot-memory"],
                        },
                    },
                    "writeback_domains": {
                        "shared-wb": {
                            "port_count": 1,
                            "arbitration_capacity": 1,
                            "execution_units": ["slot-fp", "slot-convert"],
                        },
                        "memory-wb": {
                            "port_count": 1,
                            "arbitration_capacity": 1,
                            "execution_units": ["slot-memory"],
                        },
                        "prep-wb": {
                            "port_count": 1,
                            "arbitration_capacity": 1,
                            "execution_units": ["slot-i2v", "slot-f2v"],
                        },
                    },
                }
            },
            "vector_memory": {
                "load_pipelines": 1,
                "store_pipelines": 1,
                "source_input_width": 1,
                "instruction_writeback_width": 1,
                "max_unit_stride_flows": 1,
                "load_merge_buffer_entries": 4,
                "store_merge_buffer_entries": 4,
            },
            "vector_decomposition": {
                "register_width_bits": 128,
                "rules": {
                    "vector-vector": "lmul",
                    "vector-scalar": {
                        "parts": "lmul",
                        "prep_uops": {
                            "register": {
                                "id": "integer-to-vector-prep",
                                "kind": "vector_integer",
                                "latency_cycles": 1,
                                "issue_interval_cycles": 1,
                                "resource_choices": ["integer-to-vector"],
                                "resource_occupancy_cycles": 1,
                            },
                            "immediate": {
                                "id": "immediate-to-vector-prep",
                                "kind": "vector_integer",
                                "latency_cycles": 1,
                                "issue_interval_cycles": 1,
                                "resource_choices": ["integer-to-vector"],
                                "resource_occupancy_cycles": 1,
                            },
                            "fp_register": {
                                "id": "fp-to-vector-prep",
                                "kind": "vector_fp",
                                "latency_cycles": 1,
                                "issue_interval_cycles": 1,
                                "resource_choices": ["fp-to-vector"],
                                "resource_occupancy_cycles": 1,
                            },
                        },
                    },
                    "vector-config": 1,
                    "vector-reduction": 1,
                    "vector-memory": "dynamic",
                },
            },
        }
        data["recipes"]["synthetic-vector:any"] = {
            "required_features": ["avx512f"],
            "decoded_macro_ops": 1,
            "retire_macro_ops": 1,
            "uops": [
                {
                    "id": "execute",
                    "kind": "vector_fp",
                    "latency_cycles": 2,
                    "issue_interval_cycles": 1,
                    "resource_choices": ["vector-fp"],
                    "resource_occupancy_cycles": 1,
                }
            ],
        }
        data["recipes"]["synthetic-memory:any"] = {
            "required_features": ["avx512f"],
            "decoded_macro_ops": 1,
            "retire_macro_ops": 1,
            "uops": [
                {
                    "id": "address",
                    "kind": "address_generation",
                    "latency_cycles": 0,
                    "issue_interval_cycles": 1,
                    "resource_choices": ["address-generation"],
                    "resource_occupancy_cycles": 1,
                },
                {
                    "id": "load",
                    "kind": "load_data",
                    "latency_cycles": 4,
                    "issue_interval_cycles": 1,
                    "resource_choices": ["load-data"],
                    "resource_occupancy_cycles": 1,
                    "depends_on": ["address"],
                },
            ],
        }
        data["recipes"]["synthetic-store:any"] = {
            "required_features": ["avx512f"],
            "decoded_macro_ops": 1,
            "retire_macro_ops": 1,
            "uops": [
                {
                    "id": "address",
                    "kind": "address_generation",
                    "latency_cycles": 0,
                    "issue_interval_cycles": 1,
                    "resource_choices": ["address-generation"],
                    "resource_occupancy_cycles": 1,
                },
                {
                    "id": "store",
                    "kind": "store_data",
                    "latency_cycles": 0,
                    "issue_interval_cycles": 1,
                    "resource_choices": ["store-data"],
                    "resource_occupancy_cycles": 1,
                    "depends_on": ["address"],
                },
            ],
        }
        cls.profile = Profile(base.path, data, "synthetic-topology")

    def _bound(self, specifications: list[dict[str, Any]]) -> BoundTrace:
        tpc = self.profile.ticks_per_cycle
        uops: list[ExecutionUop] = []
        macros: list[MacroOp] = []
        for index, specification in enumerate(specifications):
            unit = specification["unit"]
            partition = self.profile.backend["execution_units"][unit][
                "scheduler_partition"
            ]
            uop = ExecutionUop(
                id=f"u{index}",
                sequence=index,
                parent_id=f"m{index}",
                parent_sequence=index,
                mnemonic="display-only",
                assembly="display-only",
                semantic_kinds=("vector_fp_add",),
                kind=specification.get("kind", "vector_fp"),
                scheduling_class=f"class-{index}",
                part_index=None,
                latency_ticks=specification.get(
                    "latency_ticks", specification.get("latency", 1) * tpc
                ),
                issue_interval_ticks=tpc,
                occupancy_ticks=specification.get("occupancy_ticks", tpc),
                resource_choices=(specification.get("resource", "vector-fp"),),
                issue_domains=(),
                scheduler_partition_choices=(partition,),
                execution_unit_choices=(unit,),
                requires_completion_token=specification.get("writeback", False),
                requires_vector_read_token=specification.get(
                    "vector_read", False
                ),
                dependencies=set(specification.get("dependencies", ())),
                memory=specification.get("memory"),
            )
            uops.append(uop)
            macros.append(
                MacroOp(
                    id=f"m{index}",
                    sequence=index,
                    mnemonic="display-only",
                    assembly="display-only",
                    uop_ids=(uop.id,),
                    decoded_macro_ops=1,
                    retire_macro_ops=1,
                    uses_vector_scheduler=True,
                    uses_load_queue=uop.kind == "load_data",
                    uses_store_queue=uop.kind == "store_data",
                )
            )
        return BoundTrace(
            trace_version=2,
            profile_id=self.profile.id,
            profile_sha256=self.profile.digest,
            ticks_per_cycle=tpc,
            macros=macros,
            uops=uops,
            resources=self.profile._resources(),
            workload={"name": "backend-topology-test"},
            source_trace={"instructions": []},
        )

    def test_partition_capacity_is_held_from_dispatch_until_issue(self) -> None:
        profile = copy.deepcopy(self.profile)
        profile.data["backend"]["scheduler_partitions"][0]["entries"] = 1
        profile.data["pipeline"]["vector_scheduler_entries"] = 1
        trace = self._bound(
            [
                {"unit": "slot-fp"},
                {"unit": "slot-fp"},
            ]
        )

        result = simulate(trace, profile)

        self.assertEqual(result.summary["peak_scheduler_partitions"]["compute-iq"], 1)
        self.assertEqual(
            result.trace.macros[1].dispatch_tick,
            result.trace.macros[0].dispatch_tick + result.ticks_per_cycle,
        )
        self.assertGreater(
            result.summary["dispatch_stalls"].get("scheduler_partition_full", 0), 0
        )

    def test_partition_enqueue_width_limits_same_cycle_dispatch(self) -> None:
        profile = copy.deepcopy(self.profile)
        profile.data["backend"]["scheduler_partitions"][0]["enqueue_width"] = 1
        trace = self._bound(
            [
                {"unit": "slot-fp"},
                {"unit": "slot-fp"},
            ]
        )

        result = simulate(trace, profile)

        first, second = result.trace.macros
        self.assertEqual(first.dispatch_tick, 0)
        self.assertEqual(second.dispatch_tick, result.ticks_per_cycle)
        self.assertGreater(
            result.summary["dispatch_stalls"].get(
                "scheduler_partition_enqueue_width", 0
            ),
            0,
        )
        self.assertEqual(
            result.summary["dispatch_stalls"].get("scheduler_partition_full", 0),
            0,
        )

    def test_multi_eligible_uops_can_split_across_partition_enqueue_widths(
        self,
    ) -> None:
        data = copy.deepcopy(self.profile.data)
        compute = data["backend"]["scheduler_partitions"][0]
        compute["entries"] = 4
        compute["enqueue_width"] = 1
        compute["execution_units"] = ["slot-fp"]
        data["backend"]["scheduler_partitions"].insert(
            1,
            {
                "id": "compute-iq-alt",
                "kind": "vector_compute",
                "entries": 4,
                "enqueue_width": 1,
                "execution_units": ["slot-convert"],
            },
        )
        convert = data["backend"]["execution_units"]["slot-convert"]
        convert["scheduler_partition"] = "compute-iq-alt"
        convert["functional_units"].append("vector-fp")
        profile = Profile(self.profile.path, data, "split-enqueue-width")
        instruction = self._vector_instruction("i0", "multi-eligible")
        instruction["vector_state"]["lmul"] = "m2"
        instruction["vector_state"]["vl"] = 8
        instruction["active_vector_bits"] = 256
        bound = profile.bind(
            {
                "trace_version": 2,
                "workload": {"name": "partition-enqueue-split"},
                "instructions": [instruction],
            }
        )

        result = simulate(bound, profile)

        self.assertEqual(result.trace.macros[0].dispatch_tick, 0)
        self.assertEqual(
            {uop.scheduler_partition for uop in result.trace.uops},
            {"compute-iq", "compute-iq-alt"},
        )
        self.assertEqual(
            result.summary["dispatch_stalls"].get(
                "scheduler_partition_enqueue_width", 0
            ),
            0,
        )

    def test_execution_slot_eligibility_blocks_cross_kind_substitution(self) -> None:
        trace = self._bound(
            [
                {"unit": "slot-fp", "occupancy_ticks": 4},
                {"unit": "slot-fp"},
                {
                    "unit": "slot-convert",
                    "kind": "conversion",
                    "resource": "conversion",
                },
            ]
        )

        result = simulate(trace, self.profile)

        self.assertEqual(result.trace.uops[0].execution_unit, "slot-fp")
        self.assertEqual(result.trace.uops[2].execution_unit, "slot-convert")
        self.assertEqual(result.trace.uops[2].issue_tick, 0)
        self.assertEqual(result.trace.uops[1].issue_tick, 4)
        self.assertGreater(
            result.trace.uops[1].stall_reasons.get("execution_unit_busy", 0), 0
        )

    def test_shared_vector_read_domain_blocks_other_subticks_in_cycle(self) -> None:
        profile = copy.deepcopy(self.profile)
        read_domain = profile.data["backend"]["register_files"]["vector"][
            "read_domains"
        ]["shared-rd"]
        read_domain["arbitration_capacity"] = 1
        trace = self._bound(
            [
                {"unit": "slot-fp", "vector_read": True},
                {
                    "unit": "slot-i2v",
                    "kind": "vector_integer",
                    "resource": "integer-to-vector",
                    "latency_ticks": 1,
                    "occupancy_ticks": 1,
                },
                {
                    "unit": "slot-convert",
                    "kind": "conversion",
                    "resource": "conversion",
                    "vector_read": True,
                    "dependencies": ["u1"],
                },
            ]
        )

        result = simulate(trace, profile)

        first, prep, second = result.trace.uops
        self.assertGreater(result.ticks_per_cycle, 1)
        self.assertEqual(first.issue_tick, 0)
        self.assertEqual(prep.complete_tick, 1)
        self.assertEqual(second.issue_tick, result.ticks_per_cycle)
        self.assertNotEqual(
            (first.issue_tick or 0) // result.ticks_per_cycle,
            (second.issue_tick or 0) // result.ticks_per_cycle,
        )
        self.assertEqual(first.vector_read_domain, "shared-rd")
        self.assertEqual(second.vector_read_domain, "shared-rd")
        self.assertGreater(
            second.stall_reasons.get("vector_read_domain_busy", 0), 0
        )
        self.assertEqual(
            result.summary["vector_read_domain_reads"], {"shared-rd": 2}
        )
        exported = {entry["id"]: entry for entry in result.to_dict()["uops"]}
        self.assertEqual(exported[second.id]["vector_read_domain"], "shared-rd")
        self.assertGreater(
            exported[second.id]["stall_reasons"].get(
                "vector_read_domain_busy", 0
            ),
            0,
        )

    def test_distinct_vector_read_domains_issue_in_parallel(self) -> None:
        data = copy.deepcopy(self.profile.data)
        read_domains = data["backend"]["register_files"]["vector"][
            "read_domains"
        ]
        read_domains["shared-rd"]["arbitration_capacity"] = 1
        read_domains["shared-rd"]["execution_units"] = ["slot-fp"]
        read_domains["convert-rd"] = {
            "port_count": 1,
            "arbitration_capacity": 1,
            "execution_units": ["slot-convert"],
        }
        data["backend"]["execution_units"]["slot-convert"][
            "vector_read_domain"
        ] = "convert-rd"
        profile = Profile(self.profile.path, data, "distinct-read-domains")
        trace = self._bound(
            [
                {"unit": "slot-fp", "vector_read": True},
                {
                    "unit": "slot-convert",
                    "kind": "conversion",
                    "resource": "conversion",
                    "vector_read": True,
                },
            ]
        )

        result = simulate(trace, profile)

        self.assertEqual({uop.issue_tick for uop in result.trace.uops}, {0})
        self.assertEqual(
            {uop.vector_read_domain for uop in result.trace.uops},
            {"shared-rd", "convert-rd"},
        )

    def test_load_does_not_consume_vector_read_domain_token(self) -> None:
        data = copy.deepcopy(self.profile.data)
        read_domains = data["backend"]["register_files"]["vector"][
            "read_domains"
        ]
        read_domains["shared-rd"]["arbitration_capacity"] = 1
        read_domains["shared-rd"]["execution_units"].append("slot-memory")
        del read_domains["memory-rd"]
        data["backend"]["execution_units"]["slot-memory"][
            "vector_read_domain"
        ] = "shared-rd"
        profile = Profile(self.profile.path, data, "load-read-domain-exemption")
        trace = self._bound(
            [
                {"unit": "slot-fp", "vector_read": True},
                {
                    "unit": "slot-memory",
                    "kind": "load_data",
                    "resource": "load-data",
                    "memory": {
                        "address": 0x100000,
                        "offset": 0,
                        "region": "input",
                        "bytes": 16,
                        "cache_lines": [0x100000 // 64],
                        "access": "load",
                    },
                },
            ]
        )

        result = simulate(trace, profile)

        compute, load = result.trace.uops
        self.assertEqual(compute.issue_tick, 0)
        self.assertEqual(load.issue_tick, 0)
        self.assertEqual(compute.vector_read_domain, "shared-rd")
        self.assertIsNone(load.vector_read_domain)
        self.assertNotIn("vector_read_domain_busy", load.stall_reasons)
        self.assertEqual(
            result.summary["vector_read_domain_reads"], {"shared-rd": 1}
        )

    def test_shared_writeback_domain_blocks_other_subticks_in_cycle(self) -> None:
        trace = self._bound(
            [
                {
                    "unit": "slot-fp",
                    "latency": 2,
                    "occupancy_ticks": 1,
                    "writeback": True,
                },
                {
                    "unit": "slot-i2v",
                    "kind": "vector_integer",
                    "resource": "integer-to-vector",
                    "latency_ticks": 1,
                    "occupancy_ticks": 1,
                },
                {
                    "unit": "slot-convert",
                    "kind": "conversion",
                    "resource": "conversion",
                    "latency": 2,
                    "occupancy_ticks": 1,
                    "writeback": True,
                    "dependencies": ["u1"],
                },
            ]
        )

        result = simulate(trace, self.profile)

        first, prep, second = result.trace.uops
        self.assertGreater(result.ticks_per_cycle, 1)
        self.assertEqual(first.issue_tick, 0)
        self.assertEqual(prep.complete_tick, 1)
        self.assertEqual(second.issue_tick, result.ticks_per_cycle)
        self.assertNotEqual(
            (first.complete_tick or 0) // result.ticks_per_cycle,
            (second.complete_tick or 0) // result.ticks_per_cycle,
        )
        self.assertNotEqual(first.complete_tick, second.complete_tick)
        self.assertEqual(first.completion_domain, "shared-wb")
        self.assertEqual(second.completion_domain, "shared-wb")
        self.assertGreater(
            second.stall_reasons.get("completion_domain_busy", 0), 0
        )

    @staticmethod
    def _vector_instruction(
        instruction_id: str,
        mnemonic: str,
        *,
        dependency: str | None = None,
        scalar_source: bool = False,
    ) -> dict[str, Any]:
        return {
            "id": instruction_id,
            "sequence": int(instruction_id[1:]),
            "mnemonic": mnemonic,
            "profile_recipe": "synthetic-vector:any",
            "assembly": f"{mnemonic} display-only",
            "operands": ["v0", "v4", "a0" if scalar_source else "v8"],
            "register_reads": ["v4", "a0" if scalar_source else "v8"],
            "register_writes": ["v0"],
            "register_dependencies": {"v4": dependency} if dependency else {},
            "memory_dependencies": [],
            "flags_dependency": None,
            "memory": None,
            "vector_state": {
                "vlen_bits": 128,
                "sew_bits": 32,
                "lmul": "m4",
                "vl": 16,
            },
            "active_vector_bits": 512,
            "semantic_uops": [{"local_id": "u0", "kind": "vector_fp_add"}],
        }

    def test_lmul_decomposition_preserves_matching_part_dependencies(self) -> None:
        dynamic = {
            "trace_version": 2,
            "workload": {"name": "lmul-test"},
            "instructions": [
                self._vector_instruction("i0", "name-a"),
                self._vector_instruction("i1", "name-b", dependency="i0"),
            ],
        }

        bound = self.profile.bind(dynamic)

        first = bound.uops[:4]
        second = bound.uops[4:]
        self.assertEqual([uop.part_index for uop in first], [0, 1, 2, 3])
        self.assertEqual([uop.part_count for uop in first], [4, 4, 4, 4])
        for part_index, uop in enumerate(second):
            self.assertEqual(uop.dependencies, {first[part_index].id})

    def test_macro_op_accounting_separates_dispatch_width_from_rob_entries(
        self,
    ) -> None:
        data = copy.deepcopy(self.profile.data)
        data["backend"]["macro_op_accounting"] = {
            "dispatch_units": "max_decoded_or_execution_uops",
            "rob_entries": "architectural_instructions",
        }
        data["recipes"]["synthetic-vector:any"]["decoded_macro_ops"] = 3
        data["pipeline"]["dispatch_macro_ops_per_cycle"] = 6
        data["pipeline"]["rob_entries"] = 2
        profile = Profile(self.profile.path, data, "split-accounting")
        dynamic = {
            "trace_version": 2,
            "workload": {"name": "split-accounting"},
            "instructions": [
                self._vector_instruction(f"i{index}", f"opaque-{index}")
                for index in range(3)
            ],
        }

        bound = profile.bind(dynamic)

        self.assertEqual([macro.dispatch_units for macro in bound.macros], [4, 4, 4])
        self.assertEqual([macro.rob_entries for macro in bound.macros], [1, 1, 1])
        m1_instruction = self._vector_instruction("i0", "opaque-m1")
        m1_instruction["vector_state"]["lmul"] = "m1"
        m1_instruction["vector_state"]["vl"] = 4
        m1_instruction["active_vector_bits"] = 128
        m1_bound = profile.bind(
            {
                "trace_version": 2,
                "workload": {"name": "decoded-dominates-accounting"},
                "instructions": [m1_instruction],
            }
        )
        self.assertEqual(len(m1_bound.uops), 1)
        self.assertEqual(m1_bound.macros[0].dispatch_units, 3)
        self.assertEqual(m1_bound.macros[0].rob_entries, 1)
        result = simulate(bound, profile)
        first, second, _ = result.trace.macros
        self.assertEqual(first.dispatch_tick, 0)
        self.assertEqual(second.dispatch_tick, result.ticks_per_cycle)
        self.assertEqual(result.summary["dispatch_units"], 12)
        self.assertEqual(result.summary["rob_entries_allocated"], 3)
        self.assertEqual(result.summary["peak_rob"], 2)
        self.assertGreater(
            result.summary["dispatch_stalls"].get("rob_full", 0), 0
        )

    def test_absent_macro_op_accounting_preserves_legacy_counts(self) -> None:
        dynamic = {
            "trace_version": 2,
            "workload": {"name": "legacy-accounting"},
            "instructions": [
                self._vector_instruction("i0", "opaque-a"),
                self._vector_instruction("i1", "opaque-b"),
            ],
        }

        bound = self.profile.bind(dynamic)

        self.assertEqual(
            [macro.dispatch_width_units for macro in bound.macros], [1, 1]
        )
        self.assertEqual([macro.rob_entry_count for macro in bound.macros], [1, 1])
        result = simulate(bound, self.profile)
        self.assertEqual(
            result.trace.macros[0].dispatch_tick,
            result.trace.macros[1].dispatch_tick,
        )

    def test_invalid_macro_op_accounting_basis_is_rejected(self) -> None:
        data = copy.deepcopy(self.profile.data)
        data["backend"]["macro_op_accounting"] = {
            "dispatch_units": "mnemonic-dependent",
            "rob_entries": "architectural_instructions",
        }

        with self.assertRaisesRegex(ProfileError, "unsupported basis"):
            Profile(self.profile.path, data, "invalid-accounting")

    def test_vector_scalar_prep_uop_is_profile_policy(self) -> None:
        dynamic = {
            "trace_version": 2,
            "workload": {"name": "vector-scalar-policy"},
            "instructions": [
                self._vector_instruction(
                    "i0", "opaque-name", scalar_source=True
                )
            ],
        }

        bound = self.profile.bind(dynamic)

        self.assertEqual(len(bound.uops), 5)
        prep = bound.uops[0]
        compute = bound.uops[1:]
        self.assertEqual(prep.resource_choices, ("integer-to-vector",))
        self.assertEqual(prep.execution_unit_choices, ("slot-i2v",))
        self.assertIsNone(prep.part_index)
        self.assertFalse(prep.requires_vector_read_token)
        self.assertEqual([uop.part_index for uop in compute], [0, 1, 2, 3])
        self.assertTrue(all(uop.kind == "vector_fp" for uop in compute))
        self.assertTrue(
            all(uop.requires_vector_read_token for uop in compute)
        )
        self.assertTrue(all(prep.id in uop.dependencies for uop in compute))

        result = simulate(bound, self.profile)
        issued_prep = result.trace.uops[0]
        issued_compute = result.trace.uops[1:]
        self.assertEqual(issued_prep.execution_unit, "slot-i2v")
        self.assertTrue(
            all(
                (uop.issue_tick or 0) >= (issued_prep.complete_tick or 0)
                for uop in issued_compute
            )
        )

    def test_prep_waits_only_for_scalar_source_while_compute_waits_for_vectors(
        self,
    ) -> None:
        scalar_producer = {
            "id": "i0",
            "sequence": 0,
            "mnemonic": "opaque-scalar-producer",
            "assembly": "opaque-scalar-producer display-only",
            "operands": ["a0", "a1"],
            "register_reads": [],
            "register_writes": ["a0"],
            "register_dependencies": {},
            "memory_dependencies": [],
            "flags_dependency": None,
            "memory": None,
            "semantic_uops": [{"local_id": "u0", "kind": "scalar_alu"}],
        }
        vector_producer = self._vector_instruction("i1", "opaque-vector-producer")
        consumer = self._vector_instruction(
            "i2", "opaque-vector-scalar-consumer", scalar_source=True
        )
        consumer["register_reads"] = ["v0", "v4", "a0"]
        consumer["register_dependencies"] = {
            "v0": "i1",
            "v4": "i1",
            "a0": "i0",
        }
        dynamic = {
            "trace_version": 2,
            "workload": {"name": "prep-dependency-filter"},
            "instructions": [scalar_producer, vector_producer, consumer],
        }

        bound = self.profile.bind(dynamic)
        by_parent = {
            parent_id: [uop for uop in bound.uops if uop.parent_id == parent_id]
            for parent_id in ("i0", "i1", "i2")
        }
        scalar_uop = by_parent["i0"][0]
        producer_parts = by_parent["i1"]
        prep = next(uop for uop in by_parent["i2"] if uop.part_index is None)
        compute_parts = [
            uop for uop in by_parent["i2"] if uop.part_index is not None
        ]

        self.assertEqual(prep.dependencies, {scalar_uop.id})
        for part_index, compute in enumerate(compute_parts):
            self.assertIn(prep.id, compute.dependencies)
            self.assertIn(producer_parts[part_index].id, compute.dependencies)

        result = simulate(bound, self.profile)
        result_uops = {uop.id: uop for uop in result.trace.uops}
        issued_scalar = result_uops[scalar_uop.id]
        issued_prep = result_uops[prep.id]
        issued_producers = [result_uops[uop.id] for uop in producer_parts]
        issued_compute = [result_uops[uop.id] for uop in compute_parts]

        self.assertGreaterEqual(
            issued_prep.issue_tick or 0, issued_scalar.complete_tick or 0
        )
        self.assertLess(
            issued_prep.issue_tick or 0,
            max(uop.complete_tick or 0 for uop in issued_producers),
        )
        for part_index, compute in enumerate(issued_compute):
            self.assertGreaterEqual(
                compute.issue_tick or 0,
                max(
                    issued_prep.complete_tick or 0,
                    issued_producers[part_index].complete_tick or 0,
                ),
            )

    def test_vector_scalar_prep_variant_uses_source_operand_class(self) -> None:
        instruction = self._vector_instruction(
            "i0", "another-opaque-name", scalar_source=True
        )
        instruction["operands"][-1] = "fa0"
        instruction["register_reads"][-1] = "fa0"
        dynamic = {
            "trace_version": 2,
            "workload": {"name": "fp-vector-scalar-policy"},
            "instructions": [instruction],
        }

        bound = self.profile.bind(dynamic)

        self.assertEqual(bound.uops[0].resource_choices, ("fp-to-vector",))
        self.assertEqual(bound.uops[0].execution_unit_choices, ("slot-f2v",))

    def test_immediate_prep_has_no_external_register_dependency(self) -> None:
        producer = self._vector_instruction("i0", "opaque-vector-producer")
        consumer = self._vector_instruction(
            "i1", "opaque-immediate-consumer", scalar_source=True
        )
        consumer["operands"][-1] = "7"
        consumer["register_reads"] = ["v0", "v4"]
        consumer["register_dependencies"] = {"v0": "i0", "v4": "i0"}
        bound = self.profile.bind(
            {
                "trace_version": 2,
                "workload": {"name": "immediate-prep-dependency"},
                "instructions": [producer, consumer],
            }
        )
        consumer_uops = [uop for uop in bound.uops if uop.parent_id == "i1"]
        prep = next(uop for uop in consumer_uops if uop.part_index is None)
        compute = [uop for uop in consumer_uops if uop.part_index is not None]

        self.assertEqual(prep.resource_choices, ("integer-to-vector",))
        self.assertFalse(prep.dependencies)
        self.assertTrue(all(prep.id in uop.dependencies for uop in compute))

    def test_lmul_plus_one_cannot_clone_the_compute_uop(self) -> None:
        data = copy.deepcopy(self.profile.data)
        data["backend"]["vector_decomposition"]["rules"][
            "vector-scalar"
        ] = "lmul-plus-one"
        invalid = Profile(self.profile.path, data, "invalid-clone-policy")
        dynamic = {
            "trace_version": 2,
            "workload": {"name": "invalid-vector-scalar-policy"},
            "instructions": [
                self._vector_instruction("i0", "opaque-name", scalar_source=True)
            ],
        }

        with self.assertRaisesRegex(ProfileError, "cannot clone the compute uop"):
            invalid.bind(dynamic)

    def test_active_width_memory_flows_do_not_duplicate_bytes(self) -> None:
        instruction = {
            "id": "i0",
            "sequence": 0,
            "mnemonic": "opaque-memory-name",
            "profile_recipe": "synthetic-memory:any",
            "assembly": "opaque-memory-name display-only",
            "operands": ["v0", "0(a0)"],
            "register_reads": ["a0"],
            "register_writes": ["v0"],
            "register_dependencies": {},
            "memory_dependencies": [],
            "flags_dependency": None,
            "memory": {
                "address": 0x100000,
                "offset": 0,
                "region": "input",
                "bytes": 40,
                "cache_lines": [0x100000 // 64],
                "access": "load",
                "address_registers": ["a0"],
            },
            "vector_state": {
                "vlen_bits": 128,
                "sew_bits": 32,
                "lmul": "m4",
                "vl": 10,
            },
            "active_vector_bits": 320,
            "semantic_uops": [
                {"local_id": "u0", "kind": "address_generation"},
                {"local_id": "u1", "kind": "vector_load"},
            ],
        }
        dynamic = {
            "trace_version": 2,
            "workload": {"name": "memory-flow-test"},
            "instructions": [instruction],
        }

        bound = self.profile.bind(dynamic)
        loads = [uop for uop in bound.uops if uop.kind == "load_data"]
        addresses = [uop.memory["address"] for uop in loads if uop.memory]
        sizes = [uop.memory["bytes"] for uop in loads if uop.memory]

        self.assertEqual(addresses, [0x100000, 0x100010, 0x100020])
        self.assertEqual(sizes, [16, 16, 8])
        self.assertEqual(sum(sizes), 40)
        self.assertTrue(
            all(
                not uop.requires_vector_read_token
                for uop in bound.uops
                if uop.kind in {"address_generation", "load_data"}
            )
        )
        for load in loads:
            address = next(
                uop
                for uop in bound.uops
                if uop.kind == "address_generation"
                and uop.part_index == load.part_index
            )
            self.assertEqual(load.dependencies, {address.id})

    def test_vector_store_data_requires_read_token_but_address_does_not(
        self,
    ) -> None:
        instruction = {
            "id": "i0",
            "sequence": 0,
            "mnemonic": "opaque-store-name",
            "profile_recipe": "synthetic-store:any",
            "assembly": "opaque-store-name display-only",
            "operands": ["v0", "0(a0)"],
            "register_reads": ["v0", "a0"],
            "register_writes": [],
            "register_dependencies": {},
            "memory_dependencies": [],
            "flags_dependency": None,
            "memory": {
                "address": 0x100000,
                "offset": 0,
                "region": "output",
                "bytes": 16,
                "cache_lines": [0x100000 // 64],
                "access": "store",
                "address_registers": ["a0"],
            },
            "vector_state": {
                "vlen_bits": 128,
                "sew_bits": 32,
                "lmul": "m1",
                "vl": 4,
            },
            "active_vector_bits": 128,
            "semantic_uops": [
                {"local_id": "u0", "kind": "address_generation"},
                {"local_id": "u1", "kind": "vector_store"},
            ],
        }

        bound = self.profile.bind(
            {
                "trace_version": 2,
                "workload": {"name": "store-read-domain-test"},
                "instructions": [instruction],
            }
        )

        address = next(
            uop for uop in bound.uops if uop.kind == "address_generation"
        )
        store = next(uop for uop in bound.uops if uop.kind == "store_data")
        self.assertFalse(address.requires_vector_read_token)
        self.assertTrue(store.requires_vector_read_token)

    def test_decomposition_and_timing_are_mnemonic_independent(self) -> None:
        traces = []
        for mnemonic in ("first-spelling", "unrelated-spelling"):
            traces.append(
                self.profile.bind(
                    {
                        "trace_version": 2,
                        "workload": {"name": "mnemonic-independence"},
                        "instructions": [
                            self._vector_instruction("i0", mnemonic)
                        ],
                    }
                )
            )

        first = simulate(traces[0], self.profile)
        second = simulate(traces[1], self.profile)

        self.assertEqual(len(first.trace.uops), 4)
        self.assertEqual(first.cycles, second.cycles)
        self.assertEqual(
            [uop.execution_unit for uop in first.trace.uops],
            [uop.execution_unit for uop in second.trace.uops],
        )


if __name__ == "__main__":
    unittest.main()
