#!/usr/bin/env python3

import argparse
import shlex
import subprocess
import sys
from pathlib import Path


OPERATIONS = ("reduce", "gather", "scatter", "softmax", "fma")


def parse_args():
    parser = argparse.ArgumentParser(
        description="Run the complete exploratory dense FP32 operation suite"
    )
    parser.add_argument("--build-dir", default="build-ops-release")
    parser.add_argument("--output-dir", required=True)
    parser.add_argument("--cpu", type=int, default=8)
    parser.add_argument("--numa-node", type=int, default=0)
    parser.add_argument("--smt-sibling", type=int, default=200)
    parser.add_argument("--config", default="Release")
    parser.add_argument("--jobs", type=int, default=16)
    return parser.parse_args()


def run(command, cwd):
    print(f"+ {shlex.join(str(part) for part in command)}", flush=True)
    subprocess.run([str(part) for part in command], cwd=cwd, check=True)


def main():
    args = parse_args()
    if min(args.cpu, args.numa_node, args.smt_sibling) < 0:
        raise SystemExit("CPU, NUMA node, and SMT sibling must be non-negative")
    if args.jobs < 1:
        raise SystemExit("jobs must be at least 1")

    project_dir = Path(__file__).resolve().parents[1]
    build_dir = Path(args.build_dir)
    if not build_dir.is_absolute():
        build_dir = project_dir / build_dir
    output_dir = Path(args.output_dir)
    if not output_dir.is_absolute():
        output_dir = project_dir / output_dir
    if output_dir.exists():
        raise SystemExit(f"refusing to overwrite existing output directory: {output_dir}")

    binaries = {
        operation: build_dir / f"{operation}_fp32_bench"
        for operation in OPERATIONS
    }
    required = [build_dir / "ops_fp32_correctness", *binaries.values()]
    missing = [str(path) for path in required if not path.is_file()]
    if missing:
        raise SystemExit("missing built executable(s): " + ", ".join(missing))

    output_dir.mkdir(parents=True)
    python = sys.executable
    scripts = project_dir / "scripts"

    run([python, "-m", "unittest", "-v", "scripts/test_ops_report.py"], project_dir)
    run(
        [python, scripts / "validate_dense_benchmark_list.py", build_dir],
        project_dir,
    )
    run(
        [
            python,
            scripts / "check_ops_disassembly.py",
            build_dir,
            output_dir / "disassembly.md",
            "--dense-exploratory",
        ],
        project_dir,
    )
    run(
        [
            "numactl",
            f"--physcpubind={args.cpu}",
            f"--membind={args.numa_node}",
            build_dir / "ops_fp32_correctness",
            output_dir / "correctness.md",
            "--dense-exploratory",
        ],
        project_dir,
    )
    run(
        [
            scripts / "collect_ops_environment.sh",
            output_dir / "environment.md",
            args.cpu,
            args.smt_sibling,
            "dense-exploratory",
        ],
        project_dir,
    )

    for operation in OPERATIONS:
        json_path = output_dir / f"{operation}_fp32.json"
        run(
            [
                python,
                scripts / "run_dense_op.py",
                operation,
                binaries[operation],
                json_path,
                output_dir / f"{operation}_run.json",
                "--cpu",
                args.cpu,
                "--numa-node",
                args.numa_node,
            ],
            project_dir,
        )
        run(
            [
                python,
                scripts / "ops_report.py",
                json_path,
                output_dir / f"{operation}_fp32.md",
                output_dir / f"{operation}_fp32.svg",
                "--exploratory",
                "--dense",
            ],
            project_dir,
        )

    run(
        [
            python,
            scripts / "dense_summary.py",
            output_dir,
            "--build-dir",
            args.build_dir,
            "--cpu",
            args.cpu,
            "--numa-node",
            args.numa_node,
            "--smt-sibling",
            args.smt_sibling,
            "--config",
            args.config,
            "--jobs",
            args.jobs,
        ],
        project_dir,
    )
    print(f"Dense suite complete: {output_dir}", flush=True)


if __name__ == "__main__":
    main()
