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
    if operation == "reduce":
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
        "ns_element": {**stats, "median": 1.0},
        "logical_gbs": {**stats, "median": 10.0},
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
        svg = render_svg({}, cases, exploratory=True, dense=True)
        self.assertEqual(svg.count("<polyline "), 9)
        self.assertEqual(svg.count('data-points="113"'), 9)
        self.assertEqual(svg.count('class="anchor"'), 9 * 17)
        self.assertNotIn('class="unstable"', svg)

    def test_missing_dense_case_fails(self):
        cases = make_operation("scatter")
        with self.assertRaises(ValueError):
            validate_dense_cases(cases[:-1])


if __name__ == "__main__":
    unittest.main()
