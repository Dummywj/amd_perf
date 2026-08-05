#!/usr/bin/env python3

import json
import math
import statistics
import sys
from collections import defaultdict
from pathlib import Path


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

    unstable = []
    for name, rows in grouped.items():
        metric = select_metric(rows[0])
        values = [float(row[metric]) for row in rows]
        mean = statistics.fmean(values)
        cv = statistics.pstdev(values) / mean if len(values) > 1 and mean else 0.0
        if cv > 0.03 or min(float(row.get("pmu_running_ratio", 1.0)) for row in rows) < 0.95:
            unstable.append((name, metric, cv))

    lines.extend(["", "## Stability gate", ""])
    if unstable:
        for name, metric, cv in unstable:
            lines.append(f"- UNSTABLE: `{name}` / `{metric}`, CV={cv:.2%}")
    else:
        lines.append("All primary metrics passed CV <= 3% and PMU running ratio >= 0.95.")

    output_path.write_text("\n".join(lines) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
