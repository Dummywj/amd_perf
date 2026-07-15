#!/usr/bin/env python3

import argparse
import datetime
import json
import subprocess
import time
from pathlib import Path

from ops_report import validate_dense_cases, load_cases


def parse_args():
    parser = argparse.ArgumentParser(description="Run one approved dense exploratory operation")
    parser.add_argument("operation", choices=("reduce", "gather", "scatter", "softmax", "fma"))
    parser.add_argument("binary")
    parser.add_argument("output_json")
    parser.add_argument("metadata_json")
    parser.add_argument("--cpu", type=int, default=8)
    parser.add_argument("--numa-node", type=int, default=0)
    return parser.parse_args()


def now():
    return datetime.datetime.now().astimezone().isoformat(timespec="seconds")


def main():
    args = parse_args()
    binary = str(Path(args.binary).resolve())
    output_json = Path(args.output_json).resolve()
    metadata_json = Path(args.metadata_json).resolve()
    if output_json.exists() or metadata_json.exists():
        raise SystemExit("refusing to overwrite dense output or metadata")
    command = [
        "numactl",
        f"--physcpubind={args.cpu}",
        f"--membind={args.numa_node}",
        binary,
        "--benchmark_min_time=0.25s",
        "--benchmark_repetitions=7",
        "--benchmark_enable_random_interleaving=true",
        f"--benchmark_out={output_json}",
        "--benchmark_out_format=json",
    ]
    metadata = {
        "designation": "EXPLORATORY / NON-FORMAL",
        "operation": args.operation,
        "cpu": args.cpu,
        "numa_node": args.numa_node,
        "command": command,
        "started": now(),
    }
    start = time.monotonic()
    result = subprocess.run(command, check=False)
    metadata["ended"] = now()
    metadata["elapsed_seconds"] = time.monotonic() - start
    metadata["returncode"] = result.returncode
    metadata["output_json"] = str(output_json)
    if result.returncode == 0 and output_json.exists():
        _, cases = load_cases(output_json)
        curves, count, rows = validate_dense_cases(cases)
        metadata.update(
            {
                "validation": "PASS",
                "curves": curves,
                "cases": count,
                "raw_repetition_rows": rows,
            }
        )
    else:
        metadata["validation"] = "FAIL"
    metadata_json.write_text(json.dumps(metadata, indent=2) + "\n", encoding="utf-8")
    if result.returncode != 0:
        raise SystemExit(result.returncode)
    if metadata["validation"] != "PASS":
        raise SystemExit("dense output validation failed")


if __name__ == "__main__":
    main()
