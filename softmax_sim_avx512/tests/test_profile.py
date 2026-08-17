from __future__ import annotations

import copy
import json
import unittest
from pathlib import Path

from jsonschema import Draft202012Validator

from src.frontends.x86 import build_dynamic_trace
from src.simulator.profile import ProfileError, load_profile
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

    def test_profile_keeps_frozen_calibration_values(self) -> None:
        profile = load_profile(ROOT / "profiles/amd_zen4.yaml")
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
