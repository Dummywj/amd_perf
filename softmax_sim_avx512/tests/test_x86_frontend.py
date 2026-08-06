from __future__ import annotations

import unittest
import tempfile
from pathlib import Path

from src.frontends.x86 import build_dynamic_trace, load_recipe


ROOT = Path(__file__).resolve().parents[1]
ASSEMBLY = ROOT / "kernel/softmax/artifacts/x86/softmax_avx512.s"
RECIPE = ROOT / "recipes/x86.yaml"


class X86FrontendTest(unittest.TestCase):
    def test_softmax_loops_and_memory_formula(self) -> None:
        for count in (16, 32, 256):
            with self.subTest(count=count):
                trace = build_dynamic_trace(
                    ASSEMBLY, "softmax_avx512_f32", RECIPE, count
                )
                statistics = trace["statistics"]
                self.assertEqual(statistics["input_output_load_bytes"], 12 * count)
                self.assertEqual(statistics["input_output_store_bytes"], 8 * count)
                self.assertEqual(statistics["input_output_total_bytes"], 20 * count)

                iterations = count // 16
                per_static = {}
                for instruction in trace["instructions"]:
                    index = instruction["static_index"]
                    per_static[index] = per_static.get(index, 0) + 1
                for index in range(4, 8):
                    self.assertEqual(per_static[index], iterations)
                for index in range(32, 56):
                    self.assertEqual(per_static[index], iterations)
                for index in range(71, 76):
                    self.assertEqual(per_static[index], iterations)

    def test_register_aliases_create_loop_carried_raw_dependencies(self) -> None:
        trace = build_dynamic_trace(ASSEMBLY, "softmax_avx512_f32", RECIPE, 32)
        max_instructions = [
            instruction
            for instruction in trace["instructions"]
            if instruction["static_index"] == 4
        ]
        self.assertEqual(len(max_instructions), 2)
        self.assertIn(
            max_instructions[0]["id"], max_instructions[1]["depends_on_instructions"]
        )

    def test_invalid_count_is_rejected(self) -> None:
        for count in (0, 1, 17):
            with self.subTest(count=count), self.assertRaises(ValueError):
                build_dynamic_trace(ASSEMBLY, "softmax_avx512_f32", RECIPE, count)

    def test_unknown_semantic_uop_kind_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            recipe = Path(temporary) / "recipe.yaml"
            recipe.write_text(
                "version: 1\nisa: x86\ninstructions:\n"
                "  - mnemonic: testq\n"
                "    form: any\n"
                "    uops: [unknown_kind]\n",
                encoding="utf-8",
            )
            with self.assertRaisesRegex(ValueError, "unknown semantic uop"):
                load_recipe(recipe, ROOT / "uops/uop_kinds.yaml")


if __name__ == "__main__":
    unittest.main()
