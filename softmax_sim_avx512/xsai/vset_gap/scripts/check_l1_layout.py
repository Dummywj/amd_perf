#!/usr/bin/env python3
"""Check that the vset-gap timed working set is resident within XSAI L1D."""

from __future__ import annotations

import argparse
import json
import subprocess
from pathlib import Path


LINE_BYTES = 64
SETS = 256
WAYS = 4
CAPACITY_BYTES = LINE_BYTES * SETS * WAYS
ITERATIONS = 64
ELEMENTS_PER_ITERATION = 4
# aligned_load_stream_4 uses four disjoint, 16-byte-aligned regions.
INPUT_ELEMENTS = 8 + 4 * ITERATIONS * ELEMENTS_PER_ITERATION
OUTPUT_ELEMENTS = ITERATIONS * ELEMENTS_PER_ITERATION


def parse_symbols(output: str) -> dict[str, tuple[int, int]]:
    symbols = {}
    for line in output.splitlines():
        fields = line.split()
        if len(fields) < 4:
            continue
        try:
            symbols[fields[-1]] = (int(fields[0], 16), int(fields[1], 16))
        except ValueError:
            pass
    return symbols


def cache_lines(address: int, size: int) -> set[int]:
    first = address // LINE_BYTES
    last = (address + size - 1) // LINE_BYTES
    return set(range(first, last + 1))


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
    required = ("xsai_vset_gap_input", "xsai_vset_gap_output")
    missing = [name for name in required if name not in symbols]
    if missing:
        raise SystemExit("missing ELF symbols: " + ", ".join(missing))
    input_address, input_size = symbols[required[0]]
    output_address, output_size = symbols[required[1]]
    input_bytes = INPUT_ELEMENTS * 4
    output_bytes = OUTPUT_ELEMENTS * 4
    if input_address % LINE_BYTES or output_address % LINE_BYTES:
        raise SystemExit("vset-gap arenas are not 64-byte aligned")
    if input_size < input_bytes or output_size < output_bytes:
        raise SystemExit("vset-gap arena is smaller than the timed working set")
    lines = cache_lines(input_address, input_bytes) | cache_lines(
        output_address, output_bytes
    )
    occupancy = [0] * SETS
    for line in lines:
        occupancy[line % SETS] += 1
    working_set_bytes = input_bytes + output_bytes
    passed = working_set_bytes <= CAPACITY_BYTES // 2 and max(occupancy) <= WAYS - 1
    result = {
        "status": "PASS" if passed else "FAIL",
        "iterations": ITERATIONS,
        "elements_per_iteration": ELEMENTS_PER_ITERATION,
        "working_set_bytes": working_set_bytes,
        "l1d_capacity_bytes": CAPACITY_BYTES,
        "max_lines_per_set": max(occupancy),
        "arenas": {
            "input_address": hex(input_address),
            "input_size": input_size,
            "output_address": hex(output_address),
            "output_size": output_size,
        },
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    if not passed:
        raise SystemExit("vset-gap L1D layout audit failed")
    print(
        f"vset-gap L1D layout passed: working set={working_set_bytes} bytes, "
        f"max set occupancy={max(occupancy)}/{WAYS}."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
