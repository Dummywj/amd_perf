#!/usr/bin/env python3

import json
import math
import statistics
import sys
from collections import defaultdict
from pathlib import Path


ZMM_BASELINES = {
    "BM_Vcvttps2dqThroughputZmm": "conversion",
    "BM_VfmaddpsThroughputZmm": "fma",
    "BM_VpadddThroughputZmm": "integer",
}


def select_metric(row):
    for name in (
        "latency_cycles",
        "issue_interval_cycles",
        "mixed_instructions_per_cycle",
        "retired_ops_per_cycle",
        "probe_tsc_cycles",
        "bytes_per_cycle",
        "loads_per_cycle",
    ):
        if name in row:
            return name
    return "cpu_time"


def benchmark_name(run_name):
    return run_name.split("/", 1)[0]


def median_counter(rows, counter):
    return statistics.median(float(row[counter]) for row in rows)


def format_instruction_ratio(rows):
    counts = [
        round(median_counter(rows, f"{kind}_target_instructions"))
        for kind in ("conversion", "fma", "integer")
    ]
    divisor = 0
    for count in counts:
        divisor = math.gcd(divisor, count)
    return ":".join(str(count // divisor) for count in counts)


def append_zmm_contention_summary(lines, grouped):
    baselines = {}
    mixes = []
    for name, rows in grouped.items():
        base_name = benchmark_name(name)
        if base_name in ZMM_BASELINES:
            baselines[ZMM_BASELINES[base_name]] = median_counter(
                rows, "instructions_per_cycle"
            )
        if base_name.startswith("BM_ContentionZmm"):
            mixes.append((name, rows))

    if not mixes:
        return

    lines.extend(
        [
            "",
            "## ZMM contention comparison",
            "",
            "`C:F:I` is the static conversion:FMA:integer instruction ratio. "
            "Each class cell is `observed IPC / standalone IPC utilization`. "
            "Aggregate normalized demand is the sum of those utilizations; a value "
            "above 1 means the classes made simultaneous progress beyond one fully "
            "shared standalone bottleneck.",
            "",
            "| Benchmark | C:F:I | Total IPC | Conversion IPC / util | FMA IPC / util | Integer IPC / util | Aggregate normalized demand | Static source operands/cycle | Retired ZMM / target |",
            "|---|---:|---:|---:|---:|---:|---:|---:|---:|",
        ]
    )
    for name, rows in mixes:
        class_cells = []
        normalized_demand = 0.0
        for kind in ("conversion", "fma", "integer"):
            rate = median_counter(rows, f"{kind}_instructions_per_cycle")
            if rate == 0.0:
                class_cells.append("-")
                continue
            baseline = baselines.get(kind)
            if not baseline:
                class_cells.append(f"{rate:.6g} / n/a")
                continue
            utilization = rate / baseline
            normalized_demand += utilization
            class_cells.append(f"{rate:.6g} / {utilization:.2%}")

        total_ipc = median_counter(rows, "mixed_instructions_per_cycle")
        source_operands = median_counter(rows, "static_source_operands_per_cycle")
        retired_ratio = median_counter(rows, "retired_zmm_ops_per_target")
        lines.append(
            f"| `{name}` | `{format_instruction_ratio(rows)}` | {total_ipc:.6g} | "
            f"{class_cells[0]} | {class_cells[1]} | {class_cells[2]} | "
            f"{normalized_demand:.4f} | {source_operands:.6g} | "
            f"{retired_ratio:.6g} |"
        )

    missing = sorted(set(ZMM_BASELINES.values()) - set(baselines))
    if missing:
        lines.extend(
            [
                "",
                "Standalone baselines missing for: " + ", ".join(missing) + ".",
            ]
        )


def zmm_contention_gate_failures(grouped):
    base_names = {benchmark_name(name) for name in grouped}
    mixes = [
        (name, rows)
        for name, rows in grouped.items()
        if benchmark_name(name).startswith("BM_ContentionZmm")
    ]
    if not mixes:
        return []

    failures = []
    missing = sorted(set(ZMM_BASELINES) - base_names)
    if missing:
        failures.append("missing standalone baselines: " + ", ".join(missing))
    for name, rows in mixes:
        if any("retired_zmm_ops_per_target" not in row for row in rows):
            failures.append(f"`{name}` has no retired-ZMM audit counter")
            continue
        ratios = [float(row["retired_zmm_ops_per_target"]) for row in rows]
        if min(ratios) < 0.98 or max(ratios) > 1.02:
            failures.append(
                f"`{name}` retired-ZMM/target range "
                f"[{min(ratios):.4f}, {max(ratios):.4f}] is outside [0.98, 1.02]"
            )
    return failures


def main():
    input_path = Path(sys.argv[1])
    output_path = Path(sys.argv[2])
    payload = json.loads(input_path.read_text(encoding="utf-8"))
    raw_rows = [
        row
        for row in payload["benchmarks"]
        if row.get("run_type") == "iteration"
        and "repetition_index" in row
    ]
    grouped = defaultdict(list)
    for row in raw_rows:
        grouped[row["run_name"]].append(row)

    lines = [
        "# Raw benchmark summary",
        "",
        "All values are computed from raw repetition rows, not Google Benchmark aggregate rows.",
        "",
        "| Benchmark | Metric | Median | Min | Max | CV | PMU min running ratio |",
        "|---|---|---:|---:|---:|---:|---:|",
    ]
    for name, rows in grouped.items():
        metric = select_metric(rows[0])
        values = [float(row[metric]) for row in rows]
        mean = statistics.fmean(values)
        cv = statistics.pstdev(values) / mean if len(values) > 1 and mean else 0.0
        running = [float(row.get("pmu_running_ratio", 1.0)) for row in rows]
        lines.append(
            f"| `{name}` | `{metric}` | {statistics.median(values):.6g} | "
            f"{min(values):.6g} | {max(values):.6g} | {cv:.2%} | {min(running):.4f} |"
        )

    append_zmm_contention_summary(lines, grouped)

    unstable = []
    for name, rows in grouped.items():
        metric = select_metric(rows[0])
        values = [float(row[metric]) for row in rows]
        mean = statistics.fmean(values)
        cv = statistics.pstdev(values) / mean if len(values) > 1 and mean else 0.0
        if cv > 0.03 or min(float(row.get("pmu_running_ratio", 1.0)) for row in rows) < 0.95:
            unstable.append((name, metric, cv))
    zmm_gate_failures = zmm_contention_gate_failures(grouped)

    lines.extend(["", "## Stability gate", ""])
    if unstable or zmm_gate_failures:
        for name, metric, cv in unstable:
            lines.append(f"- UNSTABLE: `{name}` / `{metric}`, CV={cv:.2%}")
        for failure in zmm_gate_failures:
            lines.append(f"- INVALID: {failure}.")
    else:
        lines.append(
            "All primary metrics passed CV <= 3% and PMU running ratio >= 0.95; "
            "all ZMM mixes passed retired-ZMM/target in [0.98, 1.02] and have "
            "all standalone baselines."
        )

    output_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return 1 if unstable or zmm_gate_failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
