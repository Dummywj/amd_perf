from __future__ import annotations

import unittest
import tempfile
from pathlib import Path

from src.frontends.x86 import (
    StaticInstruction,
    branch_taken,
    build_dynamic_trace,
    load_recipe,
    register_roles,
    update_scalar_state,
)


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

    def test_generic_scalar_loop_is_expanded(self) -> None:
        assembly_text = """\
generic_copy_avx512_f32:
\tendbr64
\tcmpq\t$16, %rdx
\tjbe\t.Lshort
\tmovq\t%rdx, %r8
\tjmp\t.Lready
.Lshort:
\tmovq\t$16, %r8
.Lready:
\tshrq\t$4, %r8
\tsalq\t$4, %r8
\txorl\t%eax, %eax
.Lloop:
\tvmovups\t(%rdi,%rax,4), %zmm0
\tvmovups\t%zmm0, (%rsi,%rax,4)
\taddq\t$16, %rax
\tcmpq\t%r8, %rax
\tjb\t.Lloop
\tret
\t.size\tgeneric_copy_avx512_f32, .-generic_copy_avx512_f32
"""
        recipe_text = """\
version: 1
isa: x86
instructions:
  - {mnemonic: movq, form: any, uops: [scalar_move]}
  - {mnemonic: cmpq, form: any, uops: [scalar_alu]}
  - {mnemonic: jbe, form: any, uops: [branch]}
  - {mnemonic: jmp, form: any, uops: [branch]}
  - {mnemonic: shrq, form: any, uops: [scalar_alu]}
  - {mnemonic: salq, form: any, uops: [scalar_alu]}
  - {mnemonic: xorl, form: any, uops: [scalar_alu]}
  - {mnemonic: vmovups, form: memory_load, uops: [address_generation, vector_load]}
  - {mnemonic: vmovups, form: memory_store, uops: [address_generation, vector_store]}
  - {mnemonic: addq, form: any, uops: [scalar_alu]}
  - {mnemonic: jb, form: any, uops: [branch]}
  - {mnemonic: ret, form: any, uops: [return]}
"""
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            assembly = directory / "kernel.s"
            recipe = directory / "recipe.yaml"
            assembly.write_text(assembly_text, encoding="utf-8")
            recipe.write_text(recipe_text, encoding="utf-8")
            for count in (16, 32):
                with self.subTest(count=count):
                    trace = build_dynamic_trace(
                        assembly,
                        "generic_copy_avx512_f32",
                        recipe,
                        count,
                        ROOT / "uops/uop_kinds.yaml",
                    )
                    loads = [
                        instruction["memory"]
                        for instruction in trace["instructions"]
                        if instruction["memory"]
                        and instruction["memory"]["access"] == "load"
                    ]
                    stores = [
                        instruction["memory"]
                        for instruction in trace["instructions"]
                        if instruction["memory"]
                        and instruction["memory"]["access"] == "store"
                    ]
                    expected_input = [
                        0x100000 + offset for offset in range(0, count * 4, 64)
                    ]
                    expected_output = [
                        0x200000 + offset for offset in range(0, count * 4, 64)
                    ]
                    self.assertEqual(
                        [entry["address"] for entry in loads], expected_input
                    )
                    self.assertEqual(
                        [entry["address"] for entry in stores], expected_output
                    )
                    self.assertEqual(
                        trace["statistics"]["input_output_total_bytes"], count * 8
                    )

    def test_scalar_state_supports_register_arithmetic_and_branch_aliases(self) -> None:
        registers = {"rax": 0, "rcx": 3, "rdx": 256, "r8": 32}
        flags: dict[str, int | bool] = {
            "zf": False,
            "cf": False,
            "sf": False,
            "of": False,
        }

        def execute(mnemonic: str, *operands: str) -> None:
            update_scalar_state(
                StaticInstruction(0, 1, mnemonic, operands, ""),
                registers,
                flags,
                {},
            )

        execute("movq", "%rdx", "%r9")
        execute("shrq", "$4", "%r9")
        execute("salq", "$4", "%r9")
        execute("addq", "%r8", "%rax")
        execute("subq", "$-128", "%rax")
        execute("cmpq", "%rax", "%rdx")
        self.assertEqual(registers["r9"], 256)
        self.assertEqual(registers["rax"], 160)
        self.assertTrue(branch_taken("jnb", flags))
        self.assertFalse(branch_taken("jbe", flags))

        execute("cmpq", "$256", "%rdx")
        self.assertTrue(branch_taken("jbe", flags))
        self.assertTrue(branch_taken("jnb", flags))
        self.assertTrue(branch_taken("jmp", flags))

    def test_scalar_dependency_roles_cover_compiler_loop_operations(self) -> None:
        move = StaticInstruction(0, 1, "movq", ("%rdx", "%r8"), "")
        add = StaticInstruction(1, 2, "addq", ("%r8", "%rcx"), "")
        shift = StaticInstruction(2, 3, "shrq", ("$4", "%rcx"), "")
        branch = StaticInstruction(3, 4, "jbe", (".Ldone",), "")
        jump = StaticInstruction(4, 5, "jmp", (".Lloop",), "")

        self.assertEqual(register_roles(move), (["rdx"], ["r8"], False, False))
        self.assertEqual(register_roles(add), (["r8", "rcx"], ["rcx"], False, True))
        self.assertEqual(register_roles(shift), (["rcx"], ["rcx"], False, True))
        self.assertEqual(register_roles(branch), ([], [], True, False))
        self.assertEqual(register_roles(jump), ([], [], False, False))

    def test_scalar_read_before_write_is_rejected(self) -> None:
        with self.assertRaisesRegex(ValueError, "read before write"):
            update_scalar_state(
                StaticInstruction(0, 1, "addq", ("%r8", "%rax"), ""),
                {"rax": 0},
                {"zf": False, "cf": False, "sf": False, "of": False},
                {},
            )


if __name__ == "__main__":
    unittest.main()
