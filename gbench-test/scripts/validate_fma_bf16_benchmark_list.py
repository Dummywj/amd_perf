#!/usr/bin/env python3

import argparse
import subprocess
from collections import defaultdict
from pathlib import Path

from ops_report import DENSE_SIZES, expected_dense_curves


def parse_args():
    parser = argparse.ArgumentParser(description="Validate BF16 FMA registration")
    parser.add_argument("build_dir")
    return parser.parse_args()


def main():
    args = parse_args()
    binary = Path(args.build_dir).resolve() / "fma_bf16_bench"
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
        if len(parts) < 4 or parts[0] != "fma_bf16":
            raise ValueError(f"unexpected benchmark name: {name}")
        grouped[(parts[1], parts[2])].append(int(parts[3]))

    expected_curves = expected_dense_curves("fma_bf16")
    if set(grouped) != expected_curves:
        raise ValueError(
            f"curve mismatch: expected={sorted(expected_curves)}, got={sorted(grouped)}"
        )
    for curve, sizes in grouped.items():
        if tuple(sizes) != DENSE_SIZES:
            raise ValueError(f"{curve[0]}/{curve[1]}: size table mismatch")
    if len(names) != 226:
        raise ValueError(f"expected 226 cases, got {len(names)}")
    print("fma_bf16: 2 curves x 113 sizes = 226 cases")


if __name__ == "__main__":
    main()
