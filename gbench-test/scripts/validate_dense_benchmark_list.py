#!/usr/bin/env python3

import argparse
import subprocess
from collections import defaultdict
from pathlib import Path

from ops_report import DENSE_SIZES, expected_dense_curves


EXPECTED_CASES = {
    "reduce": 452,
    "gather": 1017,
    "scatter": 1017,
    "softmax": 226,
    "fma": 226,
}


def parse_args():
    parser = argparse.ArgumentParser(description="Validate dense benchmark registration")
    parser.add_argument("build_dir")
    return parser.parse_args()


def validate_binary(build_dir, operation):
    binary = build_dir / f"{operation}_fp32_bench"
    result = subprocess.run(
        [str(binary), "--benchmark_list_tests=true"],
        check=True,
        text=True,
        capture_output=True,
    )
    names = [line.strip() for line in result.stdout.splitlines() if line.strip()]
    grouped = defaultdict(list)
    for name in names:
        parts = name.split("/")
        if parts[0] != operation:
            raise ValueError(f"unexpected operation in {name}")
        if operation == "softmax":
            curve = ("softmax", parts[1])
        else:
            curve = (parts[1], parts[2])
        grouped[curve].append(int(parts[-1]))

    expected_curves = expected_dense_curves(operation)
    if set(grouped) != expected_curves:
        raise ValueError(f"{operation}: curve set mismatch")
    for curve, sizes in grouped.items():
        if tuple(sizes) != DENSE_SIZES:
            raise ValueError(f"{operation}/{curve[0]}/{curve[1]}: size table mismatch")
    if len(names) != EXPECTED_CASES[operation]:
        raise ValueError(
            f"{operation}: expected {EXPECTED_CASES[operation]} cases, got {len(names)}"
        )
    return len(grouped), len(names)


def main():
    args = parse_args()
    build_dir = Path(args.build_dir).resolve()
    total_curves = 0
    total_cases = 0
    for operation in EXPECTED_CASES:
        curves, cases = validate_binary(build_dir, operation)
        total_curves += curves
        total_cases += cases
        print(f"{operation}: {curves} curves x 113 sizes = {cases} cases")
    if total_curves != 26 or total_cases != 2938:
        raise SystemExit(f"total mismatch: {total_curves} curves, {total_cases} cases")
    print(f"total: {total_curves} curves, {total_cases} cases")


if __name__ == "__main__":
    main()
