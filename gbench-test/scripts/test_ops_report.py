#!/usr/bin/env python3

import unittest
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from ops_report import (
    DENSE_SIZES,
    expected_dense_curves,
    render_markdown,
    render_svg,
    validate_dense_cases,
)


def make_case(operation, variant, implementation, n, unstable=False):
    if operation == "fma_bf16":
        working, logical, pattern_id = 8 * n, 8 * n, 0 if variant == "reuse" else 1
    elif operation == "fma":
        working, logical, pattern_id = ((4 * n, 8 * n, 0) if variant == "reuse" else (16 * n, 16 * n, 1))
    elif operation == "reduce":
        working, logical, pattern_id = 4 * n, 4 * n + 4, -1
    elif operation == "softmax":
        working, logical, pattern_id = 8 * n, 20 * n, -1
    elif variant == "contiguous":
        working, logical, pattern_id = 8 * n, 8 * n, 4
    else:
        working, logical = 12 * n, 12 * n
        pattern_id = ("sequential", "stride17", "block_random_4k", "uniform_random").index(variant)
    implementation_id = 0 if implementation == "scalar" else (2 if implementation == "avx512_load_store" else 1)
    median = 2.0 if implementation == "scalar" else (8.0 if implementation == "avx512_load_store" else 4.0)
    if operation in ("fma", "fma_bf16"):
        median = 32.0 if variant == "reuse" else 2.0
    stats = {"median": median, "min": median, "mean": median, "stddev": 0.6 if unstable else 0.0, "cv": 0.15 if unstable else 0.0}
    return {
        "run_name": f"{operation}/{variant}/{implementation}/{n}/{n}",
        "operation": operation,
        "variant": variant,
        "implementation": implementation,
        "elements": n,
        "working_set": working,
        "inner_passes": max(1, (32768 + n - 1) // n),
        "logical_bytes": logical,
        "implementation_id": implementation_id,
        "pattern_id": pattern_id,
        "repetitions": 7,
        "elem_cycle": stats,
        "flop_cycle": {**stats, "median": median * 2.0},
        "dpbf16_cycle": {**stats, "median": median / 32.0 if operation == "fma_bf16" else 0.0},
        "ns_element": {**stats, "median": 1.0},
        "logical_gbs": {**stats, "median": 10.0},
        "fma_rounds": 64 if operation in ("fma", "fma_bf16") and variant == "reuse" else (1 if operation in ("fma", "fma_bf16") else 0),
    }


def make_operation(operation):
    return [
        make_case(operation, variant, implementation, n)
        for variant, implementation in sorted(expected_dense_curves(operation))
        for n in DENSE_SIZES
    ]


class DenseReportTest(unittest.TestCase):
    def test_integer_size_table(self):
        self.assertEqual(len(DENSE_SIZES), 113)
        self.assertEqual(DENSE_SIZES[0], 1 << 10)
        self.assertEqual(DENSE_SIZES[-1], 1 << 26)
        self.assertEqual(len(set(DENSE_SIZES)), 113)
        self.assertTrue(all(left < right for left, right in zip(DENSE_SIZES, DENSE_SIZES[1:])))
        self.assertTrue(all(n % 16 == 0 and n % 17 != 0 for n in DENSE_SIZES))

    def test_gather_complete_and_rendered(self):
        cases = make_operation("gather")
        self.assertEqual(validate_dense_cases(cases), (9, 1017, 7119))
        markdown = render_markdown({}, cases, exploratory=True, dense=True)
        self.assertIn("contiguous/indexed-SIMD throughput ratio", markdown)
        self.assertIn("2.000x (indexed CV 0.00%; contiguous CV 0.00%; stable)", markdown)
        svg = render_svg({"host_name": "test-host"}, cases, exploratory=True, dense=True)
        self.assertEqual(svg.count("<polyline "), 9)
        self.assertEqual(svg.count('data-points="113"'), 9)
        self.assertEqual(svg.count("<circle "), 0)
        self.assertNotIn('class="anchor"', svg)
        self.assertNotIn('class="unstable"', svg)
        self.assertIn(
            '>Gather FP32</text>',
            svg,
        )

    def test_fma_complete_and_rendered(self):
        cases = make_operation("fma")
        self.assertEqual(validate_dense_cases(cases), (2, 226, 1582))
        markdown = render_markdown({}, cases, exploratory=True, dense=True)
        self.assertIn("FMA rounds", markdown)
        self.assertIn("flop/core_cycle median", markdown)
        svg = render_svg({}, cases, exploratory=True, dense=True)
        self.assertEqual(svg.count("<polyline "), 2)
        self.assertEqual(svg.count('data-points="113"'), 2)
        self.assertIn(">FMA FP32</text>", svg)
        self.assertIn("flop/core_cycle median", svg)
        self.assertNotIn("EXPLORATORY / NON-FORMAL", svg)
        self.assertNotIn("Java/ZGC", svg)
        self.assertNotIn("test-host", svg)
        self.assertIn(
            'class="legend" data-position="upper-right-inside" transform="translate(814 86)"',
            svg,
        )

    def test_bf16_fma_complete_and_rendered(self):
        cases = make_operation("fma_bf16")
        self.assertEqual(validate_dense_cases(cases), (2, 226, 1582))
        markdown = render_markdown({}, cases, dense=True)
        self.assertIn("dpbf16_instr/core_cycle median", markdown)
        svg = render_svg({}, cases, dense=True)
        self.assertEqual(svg.count("<polyline "), 2)
        self.assertEqual(svg.count('data-points="113"'), 2)
        self.assertIn(">FMA BF16</text>", svg)

    def test_missing_dense_case_fails(self):
        cases = make_operation("scatter")
        with self.assertRaises(ValueError):
            validate_dense_cases(cases[:-1])

    def test_only_unstable_points_have_markers(self):
        cases = make_operation("reduce")
        cases[0]["elem_cycle"]["cv"] = 0.15
        svg = render_svg({}, cases, exploratory=True, dense=True)
        self.assertEqual(svg.count("<circle "), 1)
        self.assertEqual(svg.count('class="unstable"'), 1)
        self.assertIn('fill="#ffffff"', svg)
        self.assertNotIn('class="anchor"', svg)


if __name__ == "__main__":
    unittest.main()
