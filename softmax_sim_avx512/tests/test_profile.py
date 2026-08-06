from __future__ import annotations

import unittest
from pathlib import Path

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
