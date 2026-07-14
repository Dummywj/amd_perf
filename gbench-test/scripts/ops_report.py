#!/usr/bin/env python3

import argparse
import html
import json
import math
import statistics
from collections import defaultdict
from pathlib import Path


COLORS = ["#166534", "#b91c1c", "#1d4ed8", "#a16207", "#6b21a8", "#0e7490"]
DENSE_BASES = (1024, 1136, 1248, 1376, 1520, 1680, 1856)
DENSE_SIZES = tuple(base << octave for octave in range(16) for base in DENSE_BASES) + (
    1 << 26,
)
PATTERN_COLORS = {
    "sum": "#166534",
    "max": "#b91c1c",
    "softmax": "#1d4ed8",
    "sequential": "#166534",
    "stride17": "#b91c1c",
    "block_random_4k": "#1d4ed8",
    "uniform_random": "#a16207",
    "contiguous": "#6b21a8",
}
LINE_STYLES = {
    "scalar": "8,5",
    "avx512": "",
    "avx512_vgather": "",
    "avx512_vscatter": "",
    "avx512_load_store": "3,3,10,3",
}


def parse_args():
    parser = argparse.ArgumentParser(description="Summarize and plot FP32 ops results")
    parser.add_argument("input_json")
    parser.add_argument("output_md")
    parser.add_argument("output_svg")
    parser.add_argument(
        "--unstable-out", help="write newline-separated run names with elem/core_cycle CV > 5%"
    )
    parser.add_argument(
        "--exploratory",
        action="store_true",
        help="add the approved EXPLORATORY / NON-FORMAL warnings",
    )
    parser.add_argument(
        "--dense",
        action="store_true",
        help="require the approved 113-size dense matrix and dense rendering",
    )
    return parser.parse_args()


def parse_name(run_name):
    parts = run_name.split("/")
    operation = parts[0]
    if operation == "reduce":
        variant, implementation = parts[1], parts[2]
    elif operation in ("gather", "scatter"):
        variant, implementation = parts[1], parts[2]
    elif operation == "softmax":
        variant, implementation = "softmax", parts[1]
    else:
        raise ValueError(f"unknown operation in {run_name!r}")
    return operation, variant, implementation


def sample_stats(values):
    mean = statistics.fmean(values)
    stddev = statistics.stdev(values) if len(values) > 1 else 0.0
    return {
        "median": statistics.median(values),
        "min": min(values),
        "mean": mean,
        "stddev": stddev,
        "cv": stddev / mean if mean else math.inf,
    }


def load_cases(path):
    with Path(path).open() as source:
        data = json.load(source)
    groups = defaultdict(list)
    for row in data.get("benchmarks", []):
        if row.get("run_type") != "iteration" or "repetition_index" not in row:
            continue
        groups[row["run_name"]].append(row)

    cases = []
    for run_name, rows in groups.items():
        rows.sort(key=lambda row: row["repetition_index"])
        operation, variant, implementation = parse_name(run_name)
        elements = int(round(rows[0]["elements"]))
        working_set = int(round(rows[0]["working_set_bytes"]))
        inner_passes = int(round(rows[0]["inner_passes"]))
        elem_cycle = [float(row["elem/core_cycle"]) for row in rows]
        ns_element = [
            float(row["real_time"]) / (elements * inner_passes) for row in rows
        ]
        logical_gbs = [float(row["bytes_per_second"]) / 1e9 for row in rows]
        implementation_id = int(round(rows[0]["implementation_id"]))
        pattern_id = int(round(rows[0]["pattern_id"]))
        logical_bytes = int(round(rows[0]["logical_bytes"]))
        cases.append(
            {
                "run_name": run_name,
                "operation": operation,
                "variant": variant,
                "implementation": implementation,
                "elements": elements,
                "working_set": working_set,
                "inner_passes": inner_passes,
                "logical_bytes": logical_bytes,
                "implementation_id": implementation_id,
                "pattern_id": pattern_id,
                "repetitions": len(rows),
                "elem_cycle": sample_stats(elem_cycle),
                "ns_element": sample_stats(ns_element),
                "logical_gbs": sample_stats(logical_gbs),
            }
        )
    cases.sort(
        key=lambda case: (
            case["variant"],
            case["implementation"],
            case["elements"],
        )
    )
    return data.get("context", {}), cases


def indexed_simd_name(operation, implementations):
    explicit = {
        "gather": "avx512_vgather",
        "scatter": "avx512_vscatter",
        "reduce": "avx512",
        "softmax": "avx512",
    }[operation]
    if explicit in implementations:
        return explicit
    if "avx512" in implementations:
        return "avx512"
    return explicit


def expected_dense_curves(operation):
    if operation == "reduce":
        return {(variant, impl) for variant in ("sum", "max") for impl in ("scalar", "avx512")}
    if operation == "softmax":
        return {("softmax", impl) for impl in ("scalar", "avx512")}
    simd = "avx512_vgather" if operation == "gather" else "avx512_vscatter"
    indexed = {
        (variant, impl)
        for variant in ("sequential", "stride17", "block_random_4k", "uniform_random")
        for impl in ("scalar", simd)
    }
    return indexed | {("contiguous", "avx512_load_store")}


def validate_dense_cases(cases):
    operation = cases[0]["operation"]
    expected_curves = expected_dense_curves(operation)
    grouped = defaultdict(list)
    for case in cases:
        grouped[(case["variant"], case["implementation"])].append(case)
    if set(grouped) != expected_curves:
        missing = sorted(expected_curves - set(grouped))
        extra = sorted(set(grouped) - expected_curves)
        raise ValueError(f"{operation}: dense curves mismatch; missing={missing}, extra={extra}")

    pattern_ids = {
        "sequential": 0,
        "stride17": 1,
        "block_random_4k": 2,
        "uniform_random": 3,
        "contiguous": 4,
    }
    for (variant, implementation), curve in grouped.items():
        curve.sort(key=lambda case: case["elements"])
        sizes = tuple(case["elements"] for case in curve)
        if sizes != DENSE_SIZES:
            raise ValueError(f"{operation}/{variant}/{implementation}: not exactly 113 approved sizes")
        for case in curve:
            n = case["elements"]
            if case["repetitions"] != 7:
                raise ValueError(f"{case['run_name']}: expected 7 raw repetitions")
            expected_impl_id = 0 if implementation == "scalar" else (2 if implementation == "avx512_load_store" else 1)
            expected_pattern_id = pattern_ids.get(variant, -1)
            if case["implementation_id"] != expected_impl_id or case["pattern_id"] != expected_pattern_id:
                raise ValueError(f"{case['run_name']}: counter ID mismatch")
            if operation == "reduce":
                working, logical = 4 * n, 4 * n + 4
            elif operation == "softmax":
                working, logical = 8 * n, 20 * n
            elif variant == "contiguous":
                working = logical = 8 * n
            else:
                working = logical = 12 * n
            if case["working_set"] != working or case["logical_bytes"] != logical:
                raise ValueError(f"{case['run_name']}: working-set/logical-byte mismatch")
    return len(grouped), len(cases), sum(case["repetitions"] for case in cases)


def fmt_size(value):
    units = ["B", "KiB", "MiB", "GiB"]
    scaled = float(value)
    unit = 0
    while scaled >= 1024 and unit + 1 < len(units):
        scaled /= 1024
        unit += 1
    return f"{scaled:.0f} {units[unit]}" if scaled >= 10 else f"{scaled:.2f} {units[unit]}"


def render_markdown(context, cases, exploratory=False, dense=False):
    operation = cases[0]["operation"] if cases else "unknown"
    paired = {}
    for case in cases:
        key = (case["variant"], case["elements"])
        paired.setdefault(key, {})[case["implementation"]] = case

    lines = []
    if exploratory:
        source_warning = (
            "**Newly collected dense exploratory data; the environment may be affected by external Java/ZGC activity and CPU contention.**"
            if dense
            else "**Data comes only from formally invalid batch `ops_fp32_20260714-152755`; external Java/ZGC activity and CPU contention affected the environment.**"
        )
        lines.extend(
            [
                f"# EXPLORATORY / NON-FORMAL - {'Dense ' if dense else ''}{operation.capitalize()} FP32",
                "",
                source_warning,
                "",
                "**Relative trends only. Do not use for absolute performance, cross-machine comparisons, performance regression, capacity planning, hardware limits, or formal acceptance.**",
                "",
            ]
        )
    else:
        lines.extend([f"# {operation.capitalize()} FP32 results", ""])
    lines.extend([
        f"- Host: `{context.get('host_name', '')}`",
        f"- Date: `{context.get('date', '')}`",
        f"- Executable: `{context.get('executable', '')}`",
        f"- Raw repetition rows: `{sum(case['repetitions'] for case in cases)}`",
        f"- Curves / cases: `{len(set((case['variant'], case['implementation']) for case in cases))}` / `{len(cases)}`",
        "- Primary stability statistic: sample standard deviation / mean of `elem/core_cycle`.",
        "- `logical GB/s` is derived from frozen logical bytes; it is not measured DRAM traffic.",
        "- Dense indexed/contiguous comparisons use the same N; indexed logical bytes are 12N and contiguous logical bytes are 8N." if dense and operation in ("gather", "scatter") else "",
        "",
        "| Variant | N | Impl | Reps | Working set | elem/core_cycle median | min | mean | stddev | CV | ns/element median | logical GB/s median | Scalar/AVX speedup | contiguous/indexed-SIMD throughput ratio | Status |",
        "| --- | ---: | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | --- | --- | --- |",
    ])
    for case in cases:
        pair = paired[(case["variant"], case["elements"])]
        speedup = ""
        implementations = set(pair)
        simd = indexed_simd_name(operation, implementations)
        if case["implementation"] == simd and "scalar" in pair:
            scalar = pair["scalar"]
            unstable_pair = case["elem_cycle"]["cv"] > 0.05 or scalar["elem_cycle"]["cv"] > 0.05
            speedup = (
                f"{case['elem_cycle']['median'] / scalar['elem_cycle']['median']:.3f}x "
                f"(scalar CV {scalar['elem_cycle']['cv']:.2%}; SIMD CV {case['elem_cycle']['cv']:.2%}"
                f"; {'UNSTABLE' if unstable_pair else 'stable'})"
            )
        contiguous_ratio = ""
        if case["implementation"] == "avx512_load_store":
            indexed = paired[("sequential", case["elements"])]
            indexed_name = indexed_simd_name(operation, set(indexed))
            indexed_case = indexed[indexed_name]
            unstable_pair = case["elem_cycle"]["cv"] > 0.05 or indexed_case["elem_cycle"]["cv"] > 0.05
            contiguous_ratio = (
                f"{case['elem_cycle']['median'] / indexed_case['elem_cycle']['median']:.3f}x "
                f"(indexed CV {indexed_case['elem_cycle']['cv']:.2%}; contiguous CV {case['elem_cycle']['cv']:.2%}"
                f"; {'UNSTABLE' if unstable_pair else 'stable'})"
            )
        ec = case["elem_cycle"]
        status = "UNSTABLE" if ec["cv"] > 0.05 else "stable"
        lines.append(
            "| {variant} | {elements} | {implementation} | {repetitions} | {working} | "
            "{median:.6g} | {minimum:.6g} | {mean:.6g} | {stddev:.3g} | {cv:.2%} | "
            "{ns:.6g} | {gbs:.6g} | {speedup} | {contiguous_ratio} | {status} |".format(
                variant=case["variant"],
                elements=case["elements"],
                implementation=case["implementation"],
                repetitions=case["repetitions"],
                working=fmt_size(case["working_set"]),
                median=ec["median"],
                minimum=ec["min"],
                mean=ec["mean"],
                stddev=ec["stddev"],
                cv=ec["cv"],
                ns=case["ns_element"]["median"],
                gbs=case["logical_gbs"]["median"],
                speedup=speedup,
                contiguous_ratio=contiguous_ratio,
                status=status,
            )
        )
    unstable = [case for case in cases if case["elem_cycle"]["cv"] > 0.05]
    lines.extend(["", "## Stability", ""])
    if dense:
        lines.extend(
            [
                f"Dense completeness: {len(set((case['variant'], case['implementation']) for case in cases))} curves, 113 unique N per curve, {len(cases)} cases, and {sum(case['repetitions'] for case in cases)} raw repetition rows.",
                "",
            ]
        )
    if unstable:
        lines.append("Cases above the frozen 5% CV threshold:")
        lines.append("")
        for case in unstable:
            lines.append(
                f"- `{case['run_name']}`: CV {case['elem_cycle']['cv']:.2%}"
            )
    else:
        lines.append("All cases are at or below the frozen 5% CV threshold.")
    lines.append("")
    return "\n".join(lines)


def render_svg(context, cases, exploratory=False, dense=False):
    width, height = 1120, 680
    left, right, top, bottom = 92, 36, (126 if exploratory else 76), 96
    plot_w, plot_h = width - left - right, height - top - bottom
    grouped = defaultdict(list)
    for case in cases:
        grouped[(case["variant"], case["implementation"])].append(case)
    for points in grouped.values():
        points.sort(key=lambda case: case["elements"] if dense else case["working_set"])
    all_x = [case["elements"] if dense else case["working_set"] for case in cases]
    all_y = [case["elem_cycle"]["median"] for case in cases]
    log_min, log_max = math.log2(min(all_x)), math.log2(max(all_x))
    if log_max <= log_min:
        log_max = log_min + 1.0
    y_max = max(all_y) * 1.1

    def xp(value):
        return left + (math.log2(value) - log_min) / (log_max - log_min) * plot_w

    def yp(value):
        return top + (y_max - value) / y_max * plot_h

    operation = cases[0]["operation"].capitalize() if cases else "Ops"
    title = (
        f"EXPLORATORY / NON-FORMAL - {'Dense ' if dense else ''}{operation} FP32"
        if exploratory
        else f"{operation} FP32 median throughput"
    )
    output = [
        '<?xml version="1.0" encoding="UTF-8"?>',
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" viewBox="0 0 {width} {height}">',
        '<rect width="100%" height="100%" fill="white"/>',
        '<style>text{font-family:Arial,sans-serif;fill:#111827}.warning{fill:#991b1b}.grid{stroke:#e5e7eb}.axis{stroke:#111827;stroke-width:1.4}</style>',
        f'<text class="warning" x="{width / 2}" y="32" text-anchor="middle" font-size="22" font-weight="bold">{html.escape(title)}</text>',
    ]
    if exploratory:
        environment_warning = (
            "New dense exploratory run; external Java/ZGC and CPU contention may affect the environment."
            if dense
            else "Formally invalid source batch; external Java/ZGC and CPU contention affected the environment."
        )
        output.extend(
            [
                f'<text x="{width / 2}" y="57" text-anchor="middle" font-size="13" font-weight="bold">{html.escape(environment_warning)}</text>',
                f'<text x="{width / 2}" y="78" text-anchor="middle" font-size="12">Relative trends only; no absolute, cross-machine, regression, capacity, limit, or acceptance conclusions.</text>',
                f'<text x="{width / 2}" y="99" text-anchor="middle" font-size="11">{html.escape(str(context.get("host_name", "")))}</text>',
            ]
        )
    else:
        output.append(f'<text x="{width / 2}" y="54" text-anchor="middle" font-size="12">{html.escape(str(context.get("host_name", "")))}</text>')
    for tick_index in range(0, 7):
        value = y_max * tick_index / 6
        y = yp(value)
        output.append(f'<line class="grid" x1="{left}" y1="{y:.2f}" x2="{width-right}" y2="{y:.2f}"/>')
        output.append(f'<text x="{left-10}" y="{y+4:.2f}" text-anchor="end" font-size="11">{value:.3g}</text>')
    first_power, last_power = math.ceil(log_min), math.floor(log_max)
    last_label = -1000
    for power in range(first_power, last_power + 1):
        value = 2**power
        x = xp(value)
        output.append(f'<line class="grid" x1="{x:.2f}" y1="{top}" x2="{x:.2f}" y2="{height-bottom}"/>')
        if x - last_label >= 64:
            output.append(f'<text x="{x:.2f}" y="{height-bottom+23}" text-anchor="middle" font-size="11">{fmt_size(value)}</text>')
            last_label = x
    output.extend(
        [
            f'<line class="axis" x1="{left}" y1="{top}" x2="{left}" y2="{height-bottom}"/>',
            f'<line class="axis" x1="{left}" y1="{height-bottom}" x2="{width-right}" y2="{height-bottom}"/>',
            f'<text x="{width/2}" y="{height-28}" text-anchor="middle" font-size="14">{"N elements" if dense else "Working set bytes"} (log2)</text>',
            f'<text x="22" y="{top+plot_h/2}" text-anchor="middle" font-size="14" transform="rotate(-90 22 {top+plot_h/2})">elem/core_cycle median</text>',
        ]
    )
    legend_x, legend_y = left + 12, top + 18
    for index, ((variant, implementation), points) in enumerate(sorted(grouped.items())):
        color = PATTERN_COLORS.get(variant, COLORS[index % len(COLORS)]) if dense else COLORS[index % len(COLORS)]
        dash = LINE_STYLES.get(implementation, "") if dense else ""
        dash_attr = f' stroke-dasharray="{dash}"' if dash else ""
        polyline = " ".join(
            f"{xp(case['elements'] if dense else case['working_set']):.2f},{yp(case['elem_cycle']['median']):.2f}"
            for case in points
        )
        curve_name = f"{variant}/{implementation}"
        output.append(f'<polyline data-curve="{html.escape(curve_name)}" data-points="{len(points)}" points="{polyline}" fill="none" stroke="{color}" stroke-width="2.2"{dash_attr}/>')
        for case in points:
            unstable = case["elem_cycle"]["cv"] > 0.05
            anchor = case["elements"] > 0 and case["elements"] & (case["elements"] - 1) == 0
            if dense and not unstable and not anchor:
                continue
            radius = 5 if unstable else 3
            fill = "#ffffff" if unstable else color
            stroke_width = 2.5 if unstable else 1
            marker_class = "unstable" if unstable else "anchor"
            output.append(f'<circle class="{marker_class}" cx="{xp(case["elements"] if dense else case["working_set"]):.2f}" cy="{yp(case["elem_cycle"]["median"]):.2f}" r="{radius}" fill="{fill}" stroke="{color}" stroke-width="{stroke_width}"/>')
        label = f"{variant} {implementation}"
        output.append(f'<line x1="{legend_x}" y1="{legend_y+index*19}" x2="{legend_x+22}" y2="{legend_y+index*19}" stroke="{color}" stroke-width="2.2"{dash_attr}/>')
        output.append(f'<text x="{legend_x+29}" y="{legend_y+4+index*19}" font-size="11">{html.escape(label)}</text>')
    output.append("</svg>")
    return "\n".join(output) + "\n"


def main():
    args = parse_args()
    context, cases = load_cases(args.input_json)
    if not cases:
        raise SystemExit("no raw repetition rows found")
    if args.dense:
        try:
            validate_dense_cases(cases)
        except ValueError as error:
            raise SystemExit(str(error)) from error
    Path(args.output_md).write_text(
        render_markdown(context, cases, args.exploratory, args.dense), encoding="utf-8"
    )
    Path(args.output_svg).write_text(
        render_svg(context, cases, args.exploratory, args.dense), encoding="utf-8"
    )
    if args.unstable_out:
        unstable = [
            case["run_name"] for case in cases if case["elem_cycle"]["cv"] > 0.05
        ]
        Path(args.unstable_out).write_text("\n".join(unstable) + ("\n" if unstable else ""), encoding="utf-8")


if __name__ == "__main__":
    main()
