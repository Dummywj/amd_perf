#!/usr/bin/env python3
"""Check that each active kernel working set fits the XSAI 64 KiB L1D."""

from __future__ import annotations

import argparse
import json
import subprocess
from pathlib import Path


LINE_BYTES = 64
SETS = 256
WAYS = 4
CAPACITY_BYTES = LINE_BYTES * SETS * WAYS
ALIGNMENT_BUDGET_BYTES = CAPACITY_BYTES // 2
COUNTS = (512, 1024, 2048)
WORKLOADS = {
    "fma_throughput": (1, None),
    "fma_latency": (1, None),
    "axpy": (2, None),
    "vector_copy": (1, None),
    "vector_triad": (2, None),
    "pointer_agu": (3, None),
    "dot_product": (2, 1),
    "vector_reduction": (1, 2),
    "conversion": (1, None),
    "vector_integer": (1, None),
    "mixed_compute": (1, None),
    "softmax": (1, None),
}


def parse_symbols(output: str) -> dict[str, tuple[int, int]]:
    symbols: dict[str, tuple[int, int]] = {}
    for line in output.splitlines():
        fields = line.split()
        if len(fields) < 4:
            continue
        try:
            address = int(fields[0], 16)
            size = int(fields[1], 16)
        except ValueError:
            continue
        symbols[fields[-1]] = (address, size)
    return symbols


def line_addresses(address: int, size: int) -> set[int]:
    if size <= 0:
        return set()
    first = address // LINE_BYTES
    last = (address + size - 1) // LINE_BYTES
    return set(range(first, last + 1))


def assess_case(
    input_address: int,
    output_address: int,
    count: int,
    input_vectors: int,
    scalar_outputs: int | None,
) -> dict[str, int | str]:
    input_bytes = count * input_vectors * 4
    output_bytes = count * 4 if scalar_outputs is None else scalar_outputs * 4
    lines = line_addresses(input_address, input_bytes)
    lines |= line_addresses(output_address, output_bytes)
    occupancy = [0] * SETS
    for line in lines:
        occupancy[line % SETS] += 1
    working_set_bytes = input_bytes + max(output_bytes, LINE_BYTES)
    status = (
        "PASS"
        if working_set_bytes <= ALIGNMENT_BUDGET_BYTES and max(occupancy) <= WAYS - 1
        else "FAIL"
    )
    return {
        "status": status,
        "input_bytes": input_bytes,
        "output_bytes": max(output_bytes, LINE_BYTES),
        "working_set_bytes": working_set_bytes,
        "cache_lines": len(lines),
        "max_lines_per_set": max(occupancy),
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--elf", required=True, type=Path)
    parser.add_argument("--nm", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()

    nm_output = subprocess.run(
        [str(args.nm), "--defined-only", "--print-size", str(args.elf)],
        check=True,
        text=True,
        stdout=subprocess.PIPE,
    ).stdout
    symbols = parse_symbols(nm_output)
    missing = [
        name
        for name in ("xsai_input_arena", "xsai_output_arena")
        if name not in symbols
    ]
    if missing:
        raise SystemExit(f"missing ELF symbols: {', '.join(missing)}")

    input_address, input_size = symbols["xsai_input_arena"]
    output_address, output_size = symbols["xsai_output_arena"]
    if input_address % LINE_BYTES or output_address % LINE_BYTES:
        raise SystemExit("input/output arenas are not 64-byte aligned")
    if input_size < 3 * 2048 * 4 or output_size < 2048 * 4:
        raise SystemExit("ELF arena is smaller than the declared maximum workload")

    cases: dict[str, dict[str, int | str]] = {}
    for name, (input_vectors, scalar_outputs) in WORKLOADS.items():
        for count in COUNTS:
            cases[f"{name}:n={count}"] = assess_case(
                input_address,
                output_address,
                count,
                input_vectors,
                scalar_outputs,
            )

    failed = [name for name, case in cases.items() if case["status"] != "PASS"]
    result = {
        "status": "PASS" if not failed else "FAIL",
        "l1d": {
            "capacity_bytes": CAPACITY_BYTES,
            "line_bytes": LINE_BYTES,
            "sets": SETS,
            "ways": WAYS,
            "working_set_budget_bytes": ALIGNMENT_BUDGET_BYTES,
        },
        "arenas": {
            "input_address": hex(input_address),
            "input_size": input_size,
            "output_address": hex(output_address),
            "output_size": output_size,
        },
        "cases": cases,
        "failed_cases": failed,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    if failed:
        raise SystemExit(f"L1D layout audit failed: {', '.join(failed)}")
    worst = max(case["working_set_bytes"] for case in cases.values())
    max_set = max(case["max_lines_per_set"] for case in cases.values())
    print(
        f"L1D layout passed: worst working set={worst} bytes, "
        f"max set occupancy={max_set}/{WAYS}."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
