from __future__ import annotations

import unittest
from pathlib import Path

from src.frontends.rvv import build_dynamic_trace


ROOT = Path(__file__).resolve().parents[1]
RECIPE = ROOT / "recipes/rvv.yaml"


class RvvFrontendTest(unittest.TestCase):
    def build(self, kernel: str, count: int = 512) -> dict:
        return build_dynamic_trace(
            ROOT / f"kernel/{kernel}/artifacts/rvv/{kernel}_rvv.s",
            f"{kernel}_rvv_f32",
            RECIPE,
            count,
            vlen_bits=128,
        )

    def test_all_kernel_assemblies_expand_at_xsai_vlen(self) -> None:
        for kernel in (
            "fma_throughput",
            "fma_latency",
            "axpy",
            "vector_copy",
            "vector_triad",
            "pointer_agu",
            "dot_product",
            "vector_reduction",
            "conversion",
            "vector_integer",
            "mixed_compute",
            "softmax",
        ):
            with self.subTest(kernel=kernel):
                trace = self.build(kernel)
                self.assertEqual(trace["trace_version"], 2)
                self.assertEqual(trace["isa"], "rvv")
                self.assertGreater(trace["statistics"]["semantic_uop_count"], 0)
                self.assertTrue(all(i["id"] == f"i{n}" for n, i in enumerate(trace["instructions"])))

    def test_vector_copy_uses_four_fp32_elements_per_iteration(self) -> None:
        trace = self.build("vector_copy", 16)
        vector_loads = [
            instruction
            for instruction in trace["instructions"]
            if instruction["mnemonic"] == "vle32.v"
        ]
        vector_stores = [
            instruction
            for instruction in trace["instructions"]
            if instruction["mnemonic"] == "vse32.v"
        ]
        self.assertEqual(len(vector_loads), 4)
        self.assertEqual(len(vector_stores), 4)
        self.assertTrue(all(value["memory"]["bytes"] == 16 for value in vector_loads))
        vector_configs = [
            instruction
            for instruction in trace["instructions"]
            if instruction["mnemonic"] == "vsetvli"
        ]
        self.assertTrue(all(value["vector_state"]["vl"] == 4 for value in vector_configs))
        self.assertEqual(trace["statistics"]["input_output_load_bytes"], 64)
        self.assertEqual(trace["statistics"]["input_output_store_bytes"], 64)

    def test_fma_latency_m4_spans_sixteen_elements(self) -> None:
        trace = self.build("fma_latency", 32)
        vector_loads = [
            instruction
            for instruction in trace["instructions"]
            if instruction["mnemonic"] == "vle32.v"
        ]
        self.assertEqual(len(vector_loads), 2)
        self.assertTrue(all(value["vector_state"]["lmul"] == "m4" for value in vector_loads))
        self.assertTrue(all(value["memory"]["bytes"] == 64 for value in vector_loads))
        fmas = [
            instruction
            for instruction in trace["instructions"]
            if instruction["mnemonic"] == "vfmacc.vf"
        ]
        self.assertEqual(len(fmas), 32)
        self.assertIn("v28", fmas[0]["register_reads"])
        self.assertIn("v31", fmas[0]["register_reads"])
        old_destinations = sorted(
            set(fmas[0]["register_reads"]).intersection(
                fmas[0]["register_writes"]
            )
        )
        self.assertEqual(
            fmas[0]["old_destination_registers"], old_destinations
        )
        self.assertTrue(
            fmas[0]["semantic_uops"][0]["reads_old_destination"]
        )

    def test_softmax_accounts_for_three_load_passes_and_two_store_passes(self) -> None:
        count = 16
        trace = self.build("softmax", count)
        self.assertEqual(trace["statistics"]["input_output_load_bytes"], 3 * count * 4)
        self.assertEqual(trace["statistics"]["input_output_store_bytes"], 2 * count * 4)

    def test_vector_destination_history_is_recorded_without_adding_waw(self) -> None:
        trace = self.build("mixed_compute", 16)
        conversions = [
            instruction
            for instruction in trace["instructions"]
            if instruction["mnemonic"].startswith("vfcvt")
        ]
        self.assertGreaterEqual(len(conversions), 3)
        previous, current = conversions[1:3]
        self.assertEqual(current["vector_destination_registers"], ["v24"])
        self.assertEqual(
            current["vector_destination_dependencies"], {"v24": previous["id"]}
        )
        self.assertNotIn(previous["id"], current["depends_on_instructions"])

    def test_invalid_count_and_vlen_are_rejected(self) -> None:
        assembly = ROOT / "kernel/vector_copy/artifacts/rvv/vector_copy_rvv.s"
        with self.assertRaisesRegex(ValueError, "count"):
            build_dynamic_trace(
                assembly, "vector_copy_rvv_f32", RECIPE, 0, vlen_bits=128
            )
        with self.assertRaisesRegex(ValueError, "VLEN"):
            build_dynamic_trace(
                assembly, "vector_copy_rvv_f32", RECIPE, 16, vlen_bits=130
            )


if __name__ == "__main__":
    unittest.main()
