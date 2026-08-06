#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import statistics
from collections import defaultdict
from pathlib import Path


def percentile(values: list[float], fraction: float) -> float:
    ordered = sorted(values)
    position = fraction * (len(ordered) - 1)
    lower = int(position)
    upper = min(lower + 1, len(ordered) - 1)
    weight = position - lower
    return ordered[lower] * (1.0 - weight) + ordered[upper] * weight


def summarize(raw: dict) -> dict:
    grouped: dict[tuple[int, str], list[dict]] = defaultdict(list)
    paired: dict[tuple[int, int], dict[str, dict]] = defaultdict(dict)
    for row in raw["measurements"]:
        grouped[(row["count"], row["kind"])].append(row)
        paired[(row["count"], row["repetition"])][row["kind"]] = row
    result = {"format_version": 1, "counts": {}}
    for count in sorted({key[0] for key in grouped}):
        kernel = [row["cycles_per_call"] for row in grouped[(count, "kernel")]]
        baseline = [row["cycles_per_call"] for row in grouped[(count, "baseline")]]
        body = [
            pair["kernel"]["cycles_per_call"] - pair["baseline"]["cycles_per_call"]
            for (pair_count, _), pair in paired.items()
            if pair_count == count
        ]
        serialized_kernel = [
            row["cycles_per_call"]
            for row in grouped[(count, "serialized_kernel")]
        ]
        serialized_baseline = [
            row["cycles_per_call"]
            for row in grouped[(count, "serialized_baseline")]
        ]
        serialized_body = [
            pair["serialized_kernel"]["cycles_per_call"]
            - pair["serialized_baseline"]["cycles_per_call"]
            for (pair_count, _), pair in paired.items()
            if pair_count == count
        ]
        median = statistics.median(body)
        serialized_median = statistics.median(serialized_body)
        result["counts"][str(count)] = {
            "kernel_median_cycles": statistics.median(kernel),
            "baseline_median_cycles": statistics.median(baseline),
            "body_median_cycles": median,
            "body_mad_cycles": statistics.median(abs(value - median) for value in body),
            "body_p10_cycles": percentile(body, 0.1),
            "body_p90_cycles": percentile(body, 0.9),
            "serialized_kernel_median_cycles": statistics.median(serialized_kernel),
            "serialized_baseline_median_cycles": statistics.median(serialized_baseline),
            "serialized_body_median_cycles": serialized_median,
            "serialized_body_mad_cycles": statistics.median(
                abs(value - serialized_median) for value in serialized_body
            ),
            "serialized_body_p10_cycles": percentile(serialized_body, 0.1),
            "serialized_body_p90_cycles": percentile(serialized_body, 0.9),
            "pmu_min_running_ratio": min(
                row["pmu_running_ratio"]
                for kind in ("kernel", "baseline", "serialized_kernel", "serialized_baseline")
                for row in grouped[(count, kind)]
            ),
        }
    return result


def write_markdown(path: Path, summary: dict) -> None:
    lines = [
        "# Softmax AVX-512 cycle measurement",
        "",
        "| N | throughput body | serialized body | serialized MAD | serialized p10 | serialized p90 | PMU min ratio |",
        "|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for count, row in summary["counts"].items():
        lines.append(
            f"| {count} | {row['body_median_cycles']:.2f} | "
            f"{row['serialized_body_median_cycles']:.2f} | "
            f"{row['serialized_body_mad_cycles']:.2f} | "
            f"{row['serialized_body_p10_cycles']:.2f} | "
            f"{row['serialized_body_p90_cycles']:.2f} | "
            f"{row['pmu_min_running_ratio']:.4f} |"
        )
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("raw", type=Path)
    parser.add_argument("summary_json", type=Path)
    parser.add_argument("summary_md", type=Path)
    args = parser.parse_args()
    raw = json.loads(args.raw.read_text(encoding="utf-8"))
    summary = summarize(raw)
    args.summary_json.write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
    write_markdown(args.summary_md, summary)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
