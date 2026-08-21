from __future__ import annotations

import copy
import json
import unittest
from pathlib import Path

from jsonschema import Draft202012Validator

from src.simulator.engine import simulate
from src.simulator.model import BoundTrace, ExecutionUop, MacroOp, Resource
from src.simulator.profile import Profile, ProfileError, load_profile
from src.simulator.semantic import semantic_id


ROOT = Path(__file__).resolve().parents[1]


class VlsuPolicyTest(unittest.TestCase):
    def test_zen4_keeps_legacy_vector_memory_defaults(self) -> None:
        profile = load_profile(ROOT / "profiles/amd_zen4.yaml")
        self.assertEqual(
            profile.vector_memory_policy,
            {
                "issue_order": "any",
                "store_completion_ticks": 0,
                "split_lanes": {"load": 1, "store": 1},
            },
        )

    def test_xsai_enables_evidence_backed_policy(self) -> None:
        profile = load_profile(ROOT / "profiles/xsai.yaml")
        self.assertEqual(
            profile.vector_memory_policy["issue_order"], "any"
        )
        self.assertEqual(
            profile.vector_memory_policy["service_capacity"], {"load": 1}
        )
        self.assertEqual(
            profile.vector_memory_policy["service_ticks"],
            {"load": profile.ticks(3.5)},
        )
        self.assertEqual(
            profile.vector_memory_policy["flow_split"],
            {
                "boundary_bytes": 16,
                "max_flows_per_access": 2,
                "issue_ticks_per_flow": profile.ticks(1),
            },
        )

    def test_xsai_vector_epoch_policy_is_backend_local(self) -> None:
        xsai = load_profile(ROOT / "profiles/xsai.yaml")
        zen4 = load_profile(ROOT / "profiles/amd_zen4.yaml")

        self.assertEqual(zen4.xsai_vector_epoch_policy, {"enabled": False})
        self.assertEqual(
            xsai.xsai_vector_epoch_policy,
            {
                "enabled": True,
                "load_only_visibility_ticks": xsai.ticks(3),
                "multi_load_drain_ticks": xsai.ticks(5),
                "chained_compute_drain_ticks": xsai.ticks(9),
                "parallel_reduction_overlap_ticks": xsai.ticks(3),
                "mixed_store_reduction_capacity": 2,
            },
        )

    def test_issue_order_policy_values_parse_and_invalid_value_is_rejected(
        self,
    ) -> None:
        base = load_profile(ROOT / "profiles/xsai.yaml")
        for issue_order in ("any", "oldest", "oldest_same_kind"):
            with self.subTest(issue_order=issue_order):
                data = copy.deepcopy(base.data)
                data["backend"]["vector_memory"]["issue_order"] = issue_order
                profile = Profile(base.path, data, f"policy-{issue_order}")
                self.assertEqual(
                    profile.vector_memory_policy["issue_order"], issue_order
                )

        invalid = copy.deepcopy(base.data)
        invalid["backend"]["vector_memory"]["issue_order"] = "same_kind"
        with self.assertRaisesRegex(ProfileError, "oldest_same_kind"):
            Profile(base.path, invalid, "invalid-policy")

    def test_schema_accepts_optional_policy_fields(self) -> None:
        schema = json.loads((ROOT / "schemas/profile.schema.json").read_text())
        definition = schema["$defs"]["vector_memory_backend"]
        instance = {
            "load_pipelines": 1,
            "store_pipelines": 1,
            "source_input_width": 1,
            "instruction_writeback_width": 1,
            "max_unit_stride_flows": 1,
            "load_merge_buffer_entries": 1,
            "store_merge_buffer_entries": 1,
            "issue_order": "oldest_same_kind",
            "service_capacity": {"load": 2, "store": 1},
            "store_completion_cycles": 1,
            "evidence": ["local"],
        }
        # The fragment's refs resolve against the complete profile schema.
        validator = Draft202012Validator(schema)
        errors = list(
            validator.descend(
                instance,
                definition,
                path="backend.vector_memory",
            )
        )
        self.assertEqual(errors, [])
        properties = definition["properties"]
        self.assertEqual(
            properties["issue_order"]["enum"],
            ["any", "oldest", "oldest_same_kind"],
        )
        self.assertEqual(
            properties["service_capacity"]["properties"]["load"]["$ref"],
            "#/$defs/positive_integer_or_measure",
        )
        self.assertEqual(
            properties["store_completion_cycles"]["$ref"],
            "#/$defs/number_or_measure",
        )
        self.assertEqual(instance["evidence"], ["local"])

    def test_schema_accepts_load_store_service_cycles(self) -> None:
        schema = json.loads((ROOT / "schemas/profile.schema.json").read_text())
        definition = schema["$defs"]["vector_memory_backend"]
        instance = {
            "load_pipelines": 1,
            "store_pipelines": 1,
            "source_input_width": 1,
            "instruction_writeback_width": 1,
            "max_unit_stride_flows": 1,
            "load_merge_buffer_entries": 1,
            "store_merge_buffer_entries": 1,
            "service_cycles": {"load": 2, "store": 0},
        }
        errors = list(
            Draft202012Validator(schema).descend(
                instance, definition, path="backend.vector_memory"
            )
        )
        self.assertEqual(errors, [])

    def test_schema_accepts_complete_flow_split_policy(self) -> None:
        schema = json.loads((ROOT / "schemas/profile.schema.json").read_text())
        definition = schema["$defs"]["vector_memory_backend"]
        instance = {
            "load_pipelines": 1,
            "store_pipelines": 1,
            "source_input_width": 1,
            "instruction_writeback_width": 1,
            "max_unit_stride_flows": 2,
            "load_merge_buffer_entries": 1,
            "store_merge_buffer_entries": 1,
            "boundary_bytes": 16,
            "issue_cycles_per_flow": 1,
        }
        validator = Draft202012Validator(schema)
        errors = list(
            validator.descend(instance, definition, path="backend.vector_memory")
        )
        self.assertEqual(errors, [])
        del instance["issue_cycles_per_flow"]
        errors = list(
            validator.descend(instance, definition, path="backend.vector_memory")
        )
        self.assertTrue(errors)

    def test_incomplete_flow_split_policy_is_rejected(self) -> None:
        base = load_profile(ROOT / "profiles/amd_zen4.yaml")
        data = copy.deepcopy(base.data)
        data["backend"] = copy.deepcopy(base.backend)
        data["backend"]["vector_memory"] = {
            "boundary_bytes": 16,
        }
        with self.assertRaisesRegex(ProfileError, "requires all of"):
            Profile(base.path, data, "incomplete-flow-split")

    def test_address_crossing_boundary_occupies_split_issue_lane(self) -> None:
        profile = load_profile(ROOT / "profiles/amd_zen4.yaml")
        profile.data["backend"] = copy.deepcopy(profile.backend)
        profile.data["backend"]["execution_model"] = "generic-token"
        profile.data["backend"]["vector_memory"] = {
            "boundary_bytes": 16,
            "max_unit_stride_flows": 2,
            "issue_cycles_per_flow": 1,
            "service_cycles": {"load": 0, "store": 0},
        }
        trace = self._interleaved_vector_memory_trace(profile)
        trace.uops = [trace.uops[2], trace.uops[3]]
        trace.macros = [trace.macros[2], trace.macros[3]]
        for index, (uop, macro) in enumerate(zip(trace.uops, trace.macros)):
            uop.sequence = index
            uop.parent_sequence = index
            macro.sequence = index
            uop.scheduling_class = f"flow-split-{index}"
            uop.resource_choices = (f"flow-split-{index}",)
            trace.resources[f"flow-split-{index}"] = Resource(
                id=f"flow-split-{index}", capacity=1, bytes_per_cycle=16
            )
        trace.uops[0].memory["address"] = 0x100008
        trace.uops[0].memory["bytes"] = 16
        trace.uops[1].memory["address"] = 0x100020
        trace.uops[1].memory["bytes"] = 16

        result = simulate(trace, profile)
        by_id = {uop.id: uop for uop in result.trace.uops}

        self.assertEqual(by_id["u2"].issue_tick, 0)
        self.assertEqual(by_id["u3"].issue_tick, profile.ticks(2))
        self.assertGreater(
            by_id["u3"].stall_reasons.get(
                "vector_memory_split_issue_busy", 0
            ),
            0,
        )
        self.assertEqual(
            result.summary["vector_memory"]["flow_count_accesses"],
            {"1": 1, "2": 1},
        )

    def test_flow_count_is_capped_and_load_store_lanes_are_independent(self) -> None:
        profile = load_profile(ROOT / "profiles/amd_zen4.yaml")
        profile.data["backend"] = copy.deepcopy(profile.backend)
        profile.data["backend"]["execution_model"] = "generic-token"
        profile.data["backend"]["vector_memory"] = {
            "boundary_bytes": 16,
            "max_unit_stride_flows": 2,
            "issue_cycles_per_flow": 1,
            "service_cycles": {"load": 0, "store": 0},
        }
        trace = self._interleaved_vector_memory_trace(profile)
        trace.uops = [trace.uops[2], trace.uops[0], trace.uops[3]]
        trace.macros = [trace.macros[2], trace.macros[0], trace.macros[3]]
        for index, (uop, macro) in enumerate(zip(trace.uops, trace.macros)):
            uop.sequence = index
            uop.parent_sequence = index
            macro.sequence = index
            uop.scheduling_class = f"split-lane-{index}"
            uop.resource_choices = (f"split-lane-{index}",)
            trace.resources[f"split-lane-{index}"] = Resource(
                id=f"split-lane-{index}", capacity=1, bytes_per_cycle=16
            )
        trace.uops[0].memory["address"] = 0x100008
        trace.uops[0].memory["bytes"] = 64

        result = simulate(trace, profile)
        by_id = {uop.id: uop for uop in result.trace.uops}

        self.assertEqual(by_id["u2"].issue_tick, 0)
        self.assertEqual(by_id["u0"].issue_tick, 0)
        self.assertEqual(by_id["u3"].issue_tick, profile.ticks(2))
        self.assertEqual(
            result.summary["vector_memory"]["flow_count_accesses"],
            {"1": 2, "2": 1},
        )

    def test_service_token_outlives_uop_completion(self) -> None:
        profile = load_profile(ROOT / "profiles/amd_zen4.yaml")
        profile.data["backend"] = copy.deepcopy(profile.backend)
        profile.data["backend"]["execution_model"] = "generic-token"
        profile.data["backend"]["vector_memory"] = {
            "service_capacity": {"store": 1},
            "service_cycles": {"store": 6},
        }
        trace = self._interleaved_vector_memory_trace(profile)
        # Isolate two independent stores and avoid resource occupancy hiding
        # the service-token lifetime under test.
        trace.uops = [trace.uops[0], trace.uops[1]]
        trace.macros = [trace.macros[0], trace.macros[1]]
        trace.resources["store-serial"] = Resource(
            id="store-serial", capacity=1, bytes_per_cycle=16
        )
        for index, uop in enumerate(trace.uops):
            uop.sequence = index
            uop.parent_sequence = index
            uop.latency_ticks = profile.ticks(1)
            uop.occupancy_ticks = profile.ticks(1)
        result = simulate(trace, profile)
        by_id = {uop.id: uop for uop in result.trace.uops}
        self.assertEqual(by_id["u0"].complete_tick, profile.l1_latency_ticks)
        self.assertGreaterEqual(by_id["u1"].issue_tick, profile.ticks(6))
        self.assertGreater(
            by_id["u1"].stall_reasons.get(
                "vector_memory_store_service_busy", 0
            ),
            0,
        )

    def test_zero_service_cycles_release_token_at_issue(self) -> None:
        profile = load_profile(ROOT / "profiles/amd_zen4.yaml")
        profile.data["backend"] = copy.deepcopy(profile.backend)
        profile.data["backend"]["execution_model"] = "generic-token"
        profile.data["backend"]["vector_memory"] = {
            "service_capacity": {"store": 1},
            "service_cycles": {"store": 0},
        }
        trace = self._interleaved_vector_memory_trace(profile)
        trace.uops = [trace.uops[0], trace.uops[1]]
        trace.macros = [trace.macros[0], trace.macros[1]]
        for index, uop in enumerate(trace.uops):
            uop.sequence = index
            uop.parent_sequence = index
            uop.latency_ticks = profile.ticks(2)
            uop.occupancy_ticks = profile.ticks(1)
        result = simulate(trace, profile)
        by_id = {uop.id: uop for uop in result.trace.uops}
        self.assertEqual(by_id["u0"].issue_tick, 0)
        self.assertEqual(by_id["u1"].issue_tick, profile.ticks(1))
        self.assertNotIn(
            "vector_memory_store_service_busy", by_id["u1"].stall_reasons
        )

    def test_load_and_store_service_capacity_are_independent(self) -> None:
        profile = load_profile(ROOT / "profiles/amd_zen4.yaml")
        profile.data["backend"] = copy.deepcopy(profile.backend)
        profile.data["backend"]["execution_model"] = "generic-token"
        profile.data["backend"]["vector_memory"] = {
            "service_capacity": {"load": 1, "store": 1},
            "service_cycles": {"load": 6, "store": 6},
        }
        trace = self._interleaved_vector_memory_trace(profile)
        trace.uops = trace.uops[:4]
        trace.macros = trace.macros[:4]
        for index, uop in enumerate(trace.uops):
            resource = f"independent-service-{index}"
            uop.resource_choices = (resource,)
            uop.scheduling_class = resource
            trace.resources[resource] = Resource(
                id=resource, capacity=1, bytes_per_cycle=16
            )

        result = simulate(trace, profile)
        by_id = {uop.id: uop for uop in result.trace.uops}

        self.assertEqual(by_id["u0"].issue_tick, 0)
        self.assertEqual(by_id["u2"].issue_tick, 0)
        self.assertGreaterEqual(by_id["u1"].issue_tick, profile.ticks(6))
        self.assertGreaterEqual(by_id["u3"].issue_tick, profile.ticks(6))
        self.assertGreater(
            by_id["u1"].stall_reasons.get(
                "vector_memory_store_service_busy", 0
            ),
            0,
        )
        self.assertGreater(
            by_id["u3"].stall_reasons.get(
                "vector_memory_load_service_busy", 0
            ),
            0,
        )

    def test_oldest_same_kind_isolates_interleaved_load_and_store_queues(
        self,
    ) -> None:
        base = load_profile(ROOT / "profiles/xsai.yaml")
        profile = copy.deepcopy(base)
        policy = profile.data["backend"]["vector_memory"]
        policy["issue_order"] = "oldest_same_kind"
        policy.pop("service_capacity", None)
        trace = self._interleaved_vector_memory_trace(profile)

        result = simulate(trace, profile)
        by_id = {uop.id: uop for uop in result.trace.uops}

        self.assertEqual(by_id["u0"].issue_tick, 0)
        self.assertEqual(by_id["u2"].issue_tick, 0)
        self.assertNotIn("vector_memory_oldest_same_kind", by_id["u2"].stall_reasons)
        self.assertGreater(
            by_id["u4"].stall_reasons.get("vector_memory_oldest_same_kind", 0), 0
        )
        self.assertGreater(
            by_id["u5"].stall_reasons.get("vector_memory_oldest_same_kind", 0), 0
        )
        self.assertGreaterEqual(by_id["u4"].issue_tick, by_id["u1"].issue_tick)
        self.assertGreaterEqual(by_id["u5"].issue_tick, by_id["u3"].issue_tick)

    def test_max_inflight_flow_is_held_until_completion(self) -> None:
        profile = load_profile(ROOT / "profiles/xsai.yaml")
        profile.data["backend"]["vector_memory"].update(
            {"issue_order": "any", "service_capacity": {"store": 1}}
        )
        for field in (
            "boundary_bytes",
            "issue_cycles_per_flow",
        ):
            profile.data["backend"]["vector_memory"].pop(field, None)
        trace = self._interleaved_vector_memory_trace(profile)
        trace.uops[1].resource_choices = ("store-second",)
        trace.resources["store-second"] = Resource(
            id="store-second", capacity=1, bytes_per_cycle=16
        )
        # Remove source semantic ids to exercise the compact trace form. The
        # policy must still classify vector memory from semantic_kinds.
        for instruction in trace.source_trace["instructions"]:
            instruction["semantic_uops"] = []
        for uop in trace.uops:
            uop.semantic_ids = ()
        result = simulate(trace, profile)
        by_id = {uop.id: uop for uop in result.trace.uops}

        self.assertEqual(
            result.summary["vector_memory"]["service_capacity"], {"store": 1}
        )
        self.assertEqual(
            result.summary["vector_memory"]["peak_inflight_accesses"]["store"],
            1,
        )
        self.assertGreater(by_id["u1"].issue_tick, by_id["u0"].issue_tick)
        self.assertGreater(
            by_id["u1"].issue_tick,
            by_id["u0"].issue_tick + by_id["u0"].latency_ticks - 1,
        )
        self.assertGreater(
            by_id["u1"].stall_reasons.get(
                "vector_memory_store_service_busy", 0
            ),
            0,
        )

    @staticmethod
    def _interleaved_vector_memory_trace(profile: Profile) -> BoundTrace:
        tpc = profile.ticks_per_cycle
        specifications = (
            ("store_data", "store-serial", "vector_store"),
            ("store_data", "store-serial", "vector_store"),
            ("load_data", "load-serial", "vector_load"),
            ("load_data", "load-serial", "vector_load"),
            ("store_data", "store-free", "vector_store"),
            ("load_data", "load-free", "vector_load"),
        )
        uops = []
        macros = []
        instructions = []
        for index, (kind, resource, semantic_kind) in enumerate(specifications):
            instruction_id = f"m{index}"
            semantic = semantic_id(instruction_id, "u0")
            access = "load" if kind == "load_data" else "store"
            memory = {
                "address": 0x100000 + index * 64,
                "offset": index * 64,
                "region": access,
                "bytes": 16,
                "cache_lines": [(0x100000 + index * 64) // 64],
                "access": access,
            }
            uops.append(
                ExecutionUop(
                    id=f"u{index}",
                    sequence=index,
                    parent_id=instruction_id,
                    parent_sequence=index,
                    mnemonic="synthetic-vector-memory",
                    assembly="synthetic-vector-memory",
                    semantic_kinds=(semantic_kind,),
                    semantic_ids=(semantic,),
                    kind=kind,
                    scheduling_class=f"vlsu-{index}",
                    part_index=None,
                    latency_ticks=tpc,
                    issue_interval_ticks=tpc,
                    occupancy_ticks=5 * tpc if index in {0, 2} else tpc,
                    resource_choices=(resource,),
                    issue_domains=(),
                    memory=memory,
                )
            )
            macros.append(
                MacroOp(
                    id=instruction_id,
                    sequence=index,
                    mnemonic="synthetic-vector-memory",
                    assembly="synthetic-vector-memory",
                    uop_ids=(f"u{index}",),
                    decoded_macro_ops=1,
                    retire_macro_ops=1,
                    uses_vector_scheduler=False,
                    uses_load_queue=kind == "load_data",
                    uses_store_queue=kind == "store_data",
                )
            )
            instructions.append(
                {
                    "id": instruction_id,
                    "memory": memory,
                    "semantic_uops": [
                        {"local_id": "u0", "kind": semantic_kind}
                    ],
                }
            )
        resources = {
            resource: Resource(id=resource, capacity=1, bytes_per_cycle=16)
            for _, resource, _ in specifications
        }
        return BoundTrace(
            trace_version=2,
            profile_id=profile.id,
            profile_sha256=profile.digest,
            ticks_per_cycle=tpc,
            macros=macros,
            uops=uops,
            resources=resources,
            workload={"name": "interleaved-vector-memory"},
            source_trace={"instructions": instructions},
        )
