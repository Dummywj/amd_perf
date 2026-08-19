from __future__ import annotations

import copy
import json
import unittest
from pathlib import Path

from jsonschema import Draft202012Validator

from src.frontends.x86 import build_dynamic_trace
from src.simulator.profile import ProfileError, load_profile, recipe_keys
from src.simulator.semantic import SemanticBindingError, bind_execution_semantics


ROOT = Path(__file__).resolve().parents[1]


class ProfileTest(unittest.TestCase):
    def test_zen4_profile_validates_and_covers_softmax(self) -> None:
        profile = load_profile(
            ROOT / "profiles/amd_zen4.yaml", ROOT / "schemas/profile.schema.json"
        )
        trace = build_dynamic_trace(
            ROOT / "kernel/softmax/artifacts/x86/softmax_avx512.s",
            "softmax_avx512_f32",
            ROOT / "recipes/x86.yaml",
            256,
        )
        bound = profile.bind(trace)
        self.assertEqual(len(bound.macros), trace["statistics"]["dynamic_instruction_count"])
        self.assertGreater(len(bound.uops), len(bound.macros))
        self.assertTrue(all(uop.resource_choices for uop in bound.uops))
        self.assertTrue(all(len(uop.semantic_ids) == 1 for uop in bound.uops))
        memory_macro = next(
            macro for macro in bound.macros if macro.mnemonic == "vmovups"
        )
        by_id = {uop.id: uop for uop in bound.uops}
        classes = {by_id[uop_id].scheduling_class for uop_id in memory_macro.uop_ids}
        self.assertEqual(len(classes), len(memory_macro.uop_ids))

    def test_unknown_vector_form_is_rejected(self) -> None:
        profile = load_profile(ROOT / "profiles/amd_zen4.yaml")
        trace = build_dynamic_trace(
            ROOT / "kernel/softmax/artifacts/x86/softmax_avx512.s",
            "softmax_avx512_f32",
            ROOT / "recipes/x86.yaml",
            16,
        )
        target = next(
            instruction
            for instruction in trace["instructions"]
            if instruction["mnemonic"] == "vsubps"
        )
        target["mnemonic"] = "unknown_vector_opcode"
        with self.assertRaisesRegex(ProfileError, "missing instruction recipe"):
            profile.bind(trace)

    def test_xsai_draft_validates_and_records_source_topology(self) -> None:
        profile = load_profile(
            ROOT / "profiles/xsai.yaml", ROOT / "schemas/profile.schema.json"
        )

        self.assertEqual(profile.data["profile_status"], "draft")
        self.assertEqual(profile.data["schema_version"], 5)
        self.assertEqual(profile.data["cpu"]["configuration"], "DefaultMatrixConfig")
        self.assertEqual(
            profile.data["cpu"]["source_revision"],
            "04909692a1cdc6b9165b95c7ea83b94bdc01ab39",
        )
        self.assertEqual(profile.data["isa"]["vector_length_bits"], 128)
        self.assertEqual(profile.data["isa"]["max_element_bits"], 64)
        self.assertEqual(profile.pipeline["rob_entries"], 160)
        self.assertEqual(profile.pipeline["vector_scheduler_entries"], 42)
        self.assertEqual(profile.data["memory"]["levels"]["l1d"]["size_bytes"], 65536)
        self.assertEqual(profile.data["memory"]["levels"]["l1d"]["banks"], 1)
        self.assertEqual(
            profile.data["memory"]["levels"]["l1d"]["data_banks"], 8
        )

        backend = profile.backend
        self.assertEqual(
            backend["macro_op_accounting"],
            {
                "dispatch_units": "max_decoded_or_execution_uops",
                "rob_entries": "architectural_instructions",
            },
        )
        dependency_policy = backend["vector_dependency"]
        self.assertEqual(
            dependency_policy["vector_state"]["registers"], ["vconfig"]
        )
        self.assertIn(
            "load_data",
            dependency_policy["vector_state"]["wait_execution_kinds"],
        )
        self.assertEqual(
            dependency_policy["old_destination"]["mode"], "semantic"
        )
        vector_partitions = [
            entry
            for entry in backend["scheduler_partitions"]
            if entry["kind"] == "vector_compute"
        ]
        self.assertEqual([entry["entries"] for entry in vector_partitions], [16, 16, 10])
        self.assertEqual(
            backend["execution_units"]["vfex0"]["functional_units"],
            ["vfma", "vialu", "vimac", "vppu"],
        )
        self.assertEqual(
            backend["execution_units"]["vfex1"]["vector_read_domain"],
            "vf-rd-0",
        )
        read_domains = backend["register_files"]["vector"]["read_domains"]
        self.assertEqual(read_domains["vf-rd-0"]["execution_units"], ["vfex0", "vfex1"])
        self.assertEqual(read_domains["vf-rd-0"]["arbitration_capacity"], 1)
        self.assertEqual(backend["vector_decomposition"]["rules"]["vector-config"], 1)
        self.assertFalse(backend["vector_memory"]["declared_vls_queue_connected"])

        resources = profile.data["resources"]
        self.assertEqual(resources["scalar-load-data"]["capacity"], 3)
        self.assertEqual(resources["scalar-store-address"]["capacity"], 2)
        self.assertEqual(resources["scalar-store-data"]["capacity"], 2)
        self.assertEqual(resources["load-data"]["capacity"], 2)
        self.assertEqual(profile.data["recipes"]["vadd.vx:any"]["decoded_macro_ops"], 2)
        self.assertEqual(profile.data["recipes"]["vfmv.f.s:any"]["decoded_macro_ops"], 1)
        self.assertEqual(
            profile.data["recipes"]["vfredmax.vs:any"]["decoded_macro_ops"], 3
        )
        self.assertEqual(
            profile.data["recipes"]["vfredusum.vs:any"]["decoded_macro_ops"], 3
        )

        units = backend["execution_units"]

        def units_for(resource_id: str) -> set[str]:
            return {
                unit_id
                for unit_id, unit in units.items()
                if resource_id in unit["functional_units"]
            }

        self.assertEqual(units_for("scalar-load-data"), {"ldu0", "ldu1", "ldu2"})
        self.assertEqual(units_for("scalar-store-address"), {"sta0", "sta1"})
        self.assertEqual(units_for("scalar-store-data"), {"std0", "std1"})
        self.assertEqual(units_for("load-data"), {"vlsu0", "vlsu1"})
        self.assertEqual(units_for("store-data"), {"vlsu0", "vlsu1"})
        self.assertTrue(
            units_for("scalar-load-data").isdisjoint(units_for("load-data"))
        )
        self.assertTrue(
            units_for("scalar-store-data").isdisjoint(units_for("store-data"))
        )

        partitions = {
            entry["id"]: entry for entry in backend["scheduler_partitions"]
        }
        for partition_id in (
            "sta-iq-0",
            "sta-iq-1",
            "ldu-iq-0",
            "ldu-iq-1",
            "ldu-iq-2",
            "std-iq-0",
            "std-iq-1",
        ):
            self.assertEqual(partitions[partition_id]["kind"], "scalar")
            self.assertEqual(partitions[partition_id]["entries"], 16)

        modeled_names = set(profile.data["resources"]) | set(backend["execution_units"])
        self.assertFalse(any("cute" in name or "matrix" in name for name in modeled_names))
        revisions = {
            source["id"]: source.get("revision")
            for source in profile.data["metadata"]["sources"]
        }
        self.assertEqual(
            revisions["xsai-cute-submodule"],
            "de31b2d23f042ff3e5bddc93b7f9ceb0e9263122",
        )

    @staticmethod
    def _xsai_compute_trace() -> dict[str, object]:
        return {
            "trace_version": 2,
            "workload": {"name": "xsai-trace-scoped-readiness"},
            "instructions": [
                {
                    "id": "i0",
                    "sequence": 0,
                    "mnemonic": "opaque-vector-compute",
                    "profile_recipe": "vfadd.vv:any",
                    "assembly": "opaque-vector-compute v0, v1, v2",
                    "operands": ["v0", "v1", "v2"],
                    "register_reads": ["v1", "v2"],
                    "register_writes": ["v0"],
                    "register_dependencies": {},
                    "memory_dependencies": [],
                    "flags_dependency": None,
                    "memory": None,
                    "vector_state": {
                        "vlen_bits": 128,
                        "sew_bits": 32,
                        "lmul": "m2",
                        "vl": 8,
                    },
                    "active_vector_bits": 256,
                    "semantic_uops": [
                        {"local_id": "u0", "kind": "vector_fp_add"}
                    ],
                }
            ],
        }

    @staticmethod
    def _xsai_scalar_memory_trace(access: str) -> dict[str, object]:
        if access == "load":
            mnemonic = "flw"
            semantic_kind = "scalar_load"
            operands = ["fa0", "0(a1)"]
            register_reads = ["a1"]
            register_writes = ["fa0"]
        elif access == "store":
            mnemonic = "fsw"
            semantic_kind = "scalar_store"
            operands = ["fa0", "0(a1)"]
            register_reads = ["fa0", "a1"]
            register_writes = []
        else:
            raise AssertionError(f"unsupported test access: {access}")
        return {
            "trace_version": 2,
            "workload": {"name": f"xsai-scalar-{access}-topology"},
            "instructions": [
                {
                    "id": "i0",
                    "sequence": 0,
                    "mnemonic": mnemonic,
                    "form": "any",
                    "assembly": f"{mnemonic} " + ", ".join(operands),
                    "operands": operands,
                    "register_reads": register_reads,
                    "register_writes": register_writes,
                    "register_dependencies": {},
                    "memory_dependencies": [],
                    "flags_dependency": None,
                    "memory": {
                        "address": 0x1000,
                        "region": "input" if access == "load" else "output",
                        "offset": 0,
                        "bytes": 4,
                        "cache_lines": [0x1000 // 64],
                        "access": access,
                        "address_registers": ["a1"],
                    },
                    "semantic_uops": [
                        {"local_id": "u0", "kind": semantic_kind}
                    ],
                }
            ],
        }

    def test_xsai_selected_recipe_measure_fails_with_profile_path(self) -> None:
        calibrated = load_profile(
            ROOT / "profiles/xsai.yaml", ROOT / "schemas/profile.schema.json"
        )
        data = copy.deepcopy(calibrated.data)
        data["recipes"]["vfadd.vv:any"]["uops"][0]["latency_cycles"] = "measure"
        profile = type(calibrated)(calibrated.path, data, "selected-measure-xsai")

        self.assertTrue(profile.simulation_ready)
        self.assertIn(
            "recipes.vfadd.vv:any.uops.0.latency_cycles",
            profile.unresolved_parameters,
        )
        with self.assertRaisesRegex(
            ProfileError,
            r"profile parameter remains 'measure' for this trace: "
            r"recipes\.vfadd\.vv:any\.uops\.0\.latency_cycles",
        ):
            profile.bind(self._xsai_compute_trace())

    def test_xsai_unused_measures_do_not_block_resolved_compute_trace(self) -> None:
        draft = load_profile(
            ROOT / "profiles/xsai.yaml", ROOT / "schemas/profile.schema.json"
        )
        bound = draft.bind(self._xsai_compute_trace())

        self.assertEqual(len(bound.uops), 2)
        self.assertEqual(bound.macros[0].dispatch_units, 2)
        self.assertEqual(bound.macros[0].rob_entries, 1)
        self.assertEqual(set(bound.resources), {"vfalu"})
        self.assertIn(
            "resources.vfdiv.source_latency_cycles",
            draft.unresolved_parameters,
        )
        self.assertIn(
            "memory.levels.l2.latency_cycles", draft.unresolved_parameters
        )
        self.assertIn("memory.dram.latency_cycles", draft.unresolved_parameters)

    def test_xsai_scalar_memory_uses_scalar_slots_and_ignores_vector_measures(
        self,
    ) -> None:
        draft = load_profile(
            ROOT / "profiles/xsai.yaml", ROOT / "schemas/profile.schema.json"
        )
        cases = (
            ("load", "flw:any", "scalar-load-data", {"ldu0", "ldu1", "ldu2"}),
            ("store", "fsw:any", "scalar-store-data", {"std0", "std1"}),
        )
        for access, recipe_id, resource_id, expected_units in cases:
            with self.subTest(access=access):
                data = copy.deepcopy(draft.data)
                data["resources"]["load-data"]["bytes_per_cycle"] = "measure"
                data["resources"]["store-data"]["bytes_per_cycle"] = "measure"
                selected = data["recipes"][recipe_id]["uops"][0]
                selected["latency_cycles"] = 1
                selected["issue_interval_cycles"] = 1
                selected["resource_occupancy_cycles"] = 1
                data["resources"][resource_id]["bytes_per_cycle"] = 8
                l1d = data["memory"]["levels"]["l1d"]
                l1d["latency_cycles"] = 3
                l1d[
                    "read_bytes_per_cycle"
                    if access == "load"
                    else "write_bytes_per_cycle"
                ] = 8
                profile = type(draft)(draft.path, data, f"scalar-{access}-topology")

                bound = profile.bind(self._xsai_scalar_memory_trace(access))

                self.assertEqual(set(bound.resources), {resource_id})
                self.assertEqual(len(bound.uops), 1)
                self.assertEqual(
                    set(bound.uops[0].execution_unit_choices), expected_units
                )
                self.assertTrue(
                    expected_units.isdisjoint({"vlsu0", "vlsu1"})
                )
                self.assertIn(
                    "resources.load-data.bytes_per_cycle",
                    profile.unresolved_parameters,
                )
                self.assertIn(
                    "resources.store-data.bytes_per_cycle",
                    profile.unresolved_parameters,
                )

    def test_backend_topology_rejects_unknown_register_domain(self) -> None:
        profile = load_profile(ROOT / "profiles/xsai.yaml")
        invalid = copy.deepcopy(profile.data)
        invalid["backend"]["execution_units"]["vfex0"][
            "vector_read_domain"
        ] = "missing-domain"

        with self.assertRaisesRegex(ProfileError, "missing vector read domain"):
            type(profile)(profile.path, invalid, profile.digest)

    def test_profile_recipe_candidates_support_frontend_form_and_override(self) -> None:
        instruction = {
            "mnemonic": "vfmacc.vv",
            "operands": ["v1", "v2", "v3"],
            "form": "any",
        }
        self.assertEqual(
            recipe_keys(instruction),
            ("vfmacc.vv:vector,vector,vector", "vfmacc.vv:any"),
        )
        instruction["profile_recipe"] = "rvv.explicit-recipe"
        self.assertEqual(recipe_keys(instruction)[0], "rvv.explicit-recipe")

    def test_profile_keeps_frozen_calibration_values(self) -> None:
        profile = load_profile(ROOT / "profiles/amd_zen4.yaml")
        self.assertTrue(profile.simulation_ready)
        self.assertEqual(profile.data["schema_version"], 4)
        self.assertEqual(profile.pipeline["rob_entries"], 320)
        self.assertEqual(profile.pipeline["vector_scheduler_entries"], 64)
        self.assertEqual(profile.data["resources"]["store-data"]["capacity"], 1)
        self.assertEqual(
            profile.data["resources"]["store-data"]["bytes_per_cycle"], 32
        )
        self.assertEqual(
            profile.data["recipes"]["vaddps:zmm,zmm,zmm"]["uops"][0][
                "issue_interval_cycles"
            ],
            0.5,
        )
        overlap = profile.memory_compute_overlap_limit
        self.assertTrue(overlap["enabled"])
        self.assertEqual(overlap["max_pending_groups"], 2)
        self.assertEqual(
            overlap["compute_semantic_kinds"], ["vector_fp_fma"]
        )
        domains = profile.data["issue_domains"]
        self.assertEqual(domains["fp-add-fma-convert"]["capacity"], 2)
        self.assertEqual(domains["fma-convert-integer-total"]["capacity"], 4)
        self.assertEqual(domains["zmm-register-source-delivery"]["capacity"], 8)
        self.assertFalse(
            profile.data["recipes"]["vpaddd:zmm,zmm,zmm"][
                "vector_decomposition"
            ]["scale_issue_interval_by_parts"]
        )
        expected_demands = {
            "vaddps:zmm,zmm,zmm": 2,
            "vaddps:memory,zmm,zmm": 1,
            "vfmadd132ps:zmm,zmm,zmm": 3,
            "vfmadd132ps:memory,zmm,zmm": 2,
            "vcvttps2dq:zmm,zmm": 1,
            "vpaddd:zmm,zmm,zmm": 2,
            "vpaddd:memory,zmm,zmm": 1,
            "vpslld:immediate,zmm,zmm": 1,
        }
        for recipe_id, expected in expected_demands.items():
            with self.subTest(recipe=recipe_id):
                compute = next(
                    uop
                    for uop in profile.data["recipes"][recipe_id]["uops"]
                    if uop["kind"] in {"vector_fp", "conversion", "vector_integer"}
                )
                self.assertEqual(
                    compute["issue_domain_demands"][
                        "zmm-register-source-delivery"
                    ],
                    expected,
                )
        memory_conversion = next(
            uop
            for uop in profile.data["recipes"]["vcvttps2dq:memory,zmm"]["uops"]
            if uop["kind"] == "conversion"
        )
        self.assertNotIn(
            "zmm-register-source-delivery", memory_conversion["issue_domains"]
        )

    def test_overlap_limit_schema_rejects_zero_capacity(self) -> None:
        profile = load_profile(ROOT / "profiles/amd_zen4.yaml")
        invalid = copy.deepcopy(profile.data)
        invalid["memory_compute_overlap_limit"]["max_pending_groups"] = 0
        schema = json.loads(
            (ROOT / "schemas/profile.schema.json").read_text(encoding="utf-8")
        )
        errors = list(Draft202012Validator(schema).iter_errors(invalid))
        self.assertTrue(
            any(list(error.path)[-1:] == ["max_pending_groups"] for error in errors)
        )

    def test_overlap_limit_rejects_unknown_semantic_kind(self) -> None:
        profile = load_profile(ROOT / "profiles/amd_zen4.yaml")
        invalid = copy.deepcopy(profile.data)
        invalid["memory_compute_overlap_limit"]["compute_semantic_kinds"] = [
            "unknown_compute"
        ]
        with self.assertRaisesRegex(
            ProfileError, "unknown memory-compute semantic kinds: unknown_compute"
        ):
            type(profile)(profile.path, invalid, profile.digest)

    def test_issue_domain_demand_must_reference_a_listed_domain(self) -> None:
        profile = load_profile(ROOT / "profiles/amd_zen4.yaml")
        invalid = copy.deepcopy(profile.data)
        recipe_id, uop = next(
            (recipe_id, uop)
            for recipe_id, recipe in invalid["recipes"].items()
            for uop in recipe["uops"]
            if uop.get("issue_domains")
        )
        uop["issue_domain_demands"] = {"not-listed": 1}

        with self.assertRaisesRegex(
            ProfileError, f"recipe {recipe_id}.*unlisted issue domain: not-listed"
        ):
            type(profile)(profile.path, invalid, profile.digest)

    def test_issue_domain_demand_cannot_exceed_capacity(self) -> None:
        profile = load_profile(ROOT / "profiles/amd_zen4.yaml")
        invalid = copy.deepcopy(profile.data)
        recipe_id, uop = next(
            (recipe_id, uop)
            for recipe_id, recipe in invalid["recipes"].items()
            for uop in recipe["uops"]
            if uop.get("issue_domains")
        )
        domain_id = uop["issue_domains"][0]
        capacity = invalid["issue_domains"][domain_id]["capacity"]
        uop["issue_domain_demands"] = {domain_id: capacity + 1}

        with self.assertRaisesRegex(
            ProfileError,
            f"demand {capacity + 1} exceeds issue domain {domain_id} capacity {capacity}",
        ):
            type(profile)(profile.path, invalid, profile.digest)

    def test_ambiguous_semantic_execution_mapping_is_rejected(self) -> None:
        instruction = {
            "id": "i0",
            "semantic_uops": [
                {"local_id": "u0", "kind": "vector_fp_add"},
                {"local_id": "u1", "kind": "vector_fp_mul"},
            ],
        }
        with self.assertRaisesRegex(SemanticBindingError, "ambiguous semantic mapping"):
            bind_execution_semantics(
                instruction, [{"id": "compute", "kind": "vector_fp"}]
            )


if __name__ == "__main__":
    unittest.main()
