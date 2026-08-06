#!/usr/bin/env python3
from __future__ import annotations

import argparse
import copy
import json
import sys
from pathlib import Path
from typing import Any

import yaml


def resolve(base: Path, value: str) -> Path:
    return (base / value).resolve()


def compare(workload_path: Path) -> dict[str, Any]:
    workload = yaml.safe_load(workload_path.read_text(encoding="utf-8"))
    if workload.get("format_version") != 1:
        raise ValueError("unsupported workload format_version")
    if workload.get("isa") != "x86":
        raise ValueError("this comparison driver currently supports x86 traces")

    workload_dir = workload_path.parent
    project_root = workload_dir.parents[2]
    sys.path.insert(0, str(project_root))
    from src.frontends.x86 import build_dynamic_trace
    from src.simulator.engine import simulate
    from src.simulator.profile import load_profile

    assembly = resolve(workload_dir, workload["assembly"])
    recipe = resolve(workload_dir, workload["recipe"])
    uop_kinds = resolve(workload_dir, workload["uop_kinds"])
    profile_path = resolve(workload_dir, workload["profile"])
    schema = resolve(workload_dir, workload["schema"])
    measurements_path = resolve(workload_dir, workload["measurement_summary"])
    measurements = json.loads(measurements_path.read_text(encoding="utf-8"))
    profile = load_profile(profile_path, schema)
    rows: list[dict[str, Any]] = []

    for point in workload["points"]:
        count = int(point["count"])
        measured = measurements["counts"][str(count)]
        dynamic = build_dynamic_trace(
            assembly, workload["function"], recipe, count, uop_kinds
        )
        results = {}
        for execution_model in workload["execution_models"]:
            result = simulate(
                profile.bind(copy.deepcopy(dynamic)),
                profile,
                execution_model,
                point["cache_mode"],
            )
            results[execution_model] = {
                "cycles": result.cycles,
                "summary": result.summary,
            }
        simulated = results["out_of_order"]["cycles"]
        measured_cycles = measured["serialized_body_median_cycles"]
        error = simulated - measured_cycles
        rows.append(
            {
                "count": count,
                "cache_mode": point["cache_mode"],
                "validation_class": point["validation_class"],
                "measured_serialized_body_cycles": measured_cycles,
                "measured_mad_cycles": measured["serialized_body_mad_cycles"],
                "measured_p10_cycles": measured["serialized_body_p10_cycles"],
                "measured_p90_cycles": measured["serialized_body_p90_cycles"],
                "simulated_out_of_order_cycles": simulated,
                "simulated_in_order_cycles": results["in_order"]["cycles"],
                "absolute_error_cycles": error,
                "relative_error_percent": 100.0 * error / measured_cycles,
                "inside_measured_p10_p90": (
                    measured["serialized_body_p10_cycles"]
                    <= simulated
                    <= measured["serialized_body_p90_cycles"]
                ),
                "out_of_order_summary": results["out_of_order"]["summary"],
            }
        )

    steady = [row for row in rows if row["validation_class"] == "steady-l1"]
    return {
        "format_version": 1,
        "workload_id": workload["workload_id"],
        "profile_id": profile.id,
        "profile_sha256": profile.digest,
        "measurement_summary": workload["measurement_summary"],
        "primary_metric": "serialized_body_median_cycles",
        "rows": rows,
        "acceptance": {
            "steady_l1_limit_percent": 10.0,
            "steady_l1_all_within_limit": all(
                abs(row["relative_error_percent"]) <= 10.0 for row in steady
            ),
            "steady_l1_max_absolute_error_percent": max(
                abs(row["relative_error_percent"]) for row in steady
            ),
        },
    }


def write_markdown(path: Path, report: dict[str, Any]) -> None:
    lines = [
        "# Softmax simulator comparison",
        "",
        "Primary measurement: serialized, baseline-subtracted core cycles per call.",
        "",
        "| N | cache | class | measured | OOO sim | error | in-order sim | p10-p90 |",
        "|---:|:---|:---|---:|---:|---:|---:|:---:|",
    ]
    for row in report["rows"]:
        lines.append(
            f"| {row['count']} | {row['cache_mode']} | {row['validation_class']} | "
            f"{row['measured_serialized_body_cycles']:.2f} | "
            f"{row['simulated_out_of_order_cycles']:.2f} | "
            f"{row['relative_error_percent']:+.2f}% | "
            f"{row['simulated_in_order_cycles']:.2f} | "
            f"{'yes' if row['inside_measured_p10_p90'] else 'no'} |"
        )
    acceptance = report["acceptance"]
    lines.extend(
        [
            "",
            "## Acceptance",
            "",
            f"- Steady hot-L1 points within 10%: "
            f"{'yes' if acceptance['steady_l1_all_within_limit'] else 'no'}",
            f"- Maximum steady hot-L1 absolute error: "
            f"{acceptance['steady_l1_max_absolute_error_percent']:.2f}%",
            "- N=16/32/64 are diagnostic only; N=4096 is the L1 capacity boundary.",
        ]
    )
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("workload", type=Path)
    parser.add_argument("output_dir", type=Path)
    args = parser.parse_args()
    report = compare(args.workload.resolve())
    args.output_dir.mkdir(parents=True, exist_ok=True)
    (args.output_dir / "comparison.json").write_text(
        json.dumps(report, indent=2) + "\n", encoding="utf-8"
    )
    write_markdown(args.output_dir / "comparison.md", report)
    print(json.dumps(report["acceptance"], sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
