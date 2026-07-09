#!/usr/bin/env python3

import argparse
import html
import json
import math
from pathlib import Path


COLORS = [
    "#2563eb",
    "#dc2626",
    "#16a34a",
    "#9333ea",
    "#ea580c",
    "#0891b2",
]


def parse_args():
    parser = argparse.ArgumentParser(
        description="Plot Google Benchmark FP32 FMA length sweep results as SVG."
    )
    parser.add_argument("input_json", help="Google Benchmark JSON result file")
    parser.add_argument("output_svg", help="Output SVG path")
    parser.add_argument(
        "--x",
        default="working_set_bytes",
        help="JSON counter used as the log-scale x axis",
    )
    parser.add_argument(
        "--y",
        action="append",
        dest="y_keys",
        help="JSON counter used as a linear y-axis series; repeat for multiple series",
    )
    parser.add_argument(
        "--title",
        default="FP32 FMA Length Sweep",
        help="Chart title",
    )
    parser.add_argument("--width", type=int, default=1000, help="SVG width")
    parser.add_argument("--height", type=int, default=620, help="SVG height")
    parser.add_argument("--y-min", type=float, default=None, help="Override y min")
    parser.add_argument("--y-max", type=float, default=None, help="Override y max")
    return parser.parse_args()


def as_float(value):
    if isinstance(value, (int, float)):
        return float(value)
    return None


def benchmark_family(name):
    if not name:
        return "benchmark"
    return name.split("/", 1)[0]


def load_series(input_path, x_key, y_keys):
    with Path(input_path).open() as f:
        data = json.load(f)

    benchmarks = data.get("benchmarks", [])
    families = sorted({benchmark_family(row.get("name", "")) for row in benchmarks})
    include_family_in_label = len(families) > 1
    series = []
    for y_key in y_keys:
        grouped_points = {}
        for row in benchmarks:
            x = as_float(row.get(x_key))
            y = as_float(row.get(y_key))
            if x is None or y is None or x <= 0 or not math.isfinite(y):
                continue
            family = benchmark_family(row.get("name", ""))
            grouped_points.setdefault(family, []).append((x, y, row.get("name", "")))
        for family in families:
            points = grouped_points.get(family, [])
            points.sort(key=lambda item: item[0])
            if points:
                label = f"{family} {y_key}" if include_family_in_label else y_key
                series.append((label, points))

    if not series:
        raise SystemExit(
            f"no plottable benchmark rows found for x={x_key!r}, y={y_keys!r}"
        )

    return data.get("context", {}), series


def format_bytes(value):
    units = ["B", "KiB", "MiB", "GiB", "TiB"]
    scaled = float(value)
    unit_index = 0
    while scaled >= 1024.0 and unit_index + 1 < len(units):
        scaled /= 1024.0
        unit_index += 1
    if scaled >= 100 or scaled.is_integer():
        number = f"{scaled:.0f}"
    elif scaled >= 10:
        number = f"{scaled:.1f}"
    else:
        number = f"{scaled:.2f}"
    return f"{number} {units[unit_index]}"


def format_number(value):
    if abs(value) >= 100:
        return f"{value:.0f}"
    if abs(value) >= 10:
        return f"{value:.1f}"
    if abs(value) >= 1:
        return f"{value:.2f}"
    return f"{value:.3g}"


def nice_step(raw_step):
    if raw_step <= 0:
        return 1.0
    exponent = math.floor(math.log10(raw_step))
    base = 10 ** exponent
    fraction = raw_step / base
    if fraction <= 1:
        nice_fraction = 1
    elif fraction <= 2:
        nice_fraction = 2
    elif fraction <= 5:
        nice_fraction = 5
    else:
        nice_fraction = 10
    return nice_fraction * base


def linear_ticks(y_min, y_max, target_count=7):
    if y_max <= y_min:
        y_max = y_min + 1.0
    step = nice_step((y_max - y_min) / max(1, target_count - 1))
    start = math.floor(y_min / step) * step
    end = math.ceil(y_max / step) * step
    ticks = []
    value = start
    while value <= end + step * 0.5:
        ticks.append(value)
        value += step
    return ticks


def log2_ticks(x_min, x_max):
    start = math.ceil(math.log2(x_min))
    end = math.floor(math.log2(x_max))
    return [2**power for power in range(start, end + 1)]


def svg_text(x, y, text, size=13, anchor="middle", extra=""):
    return (
        f'<text x="{x:.2f}" y="{y:.2f}" text-anchor="{anchor}" '
        f'font-size="{size}" {extra}>{html.escape(text)}</text>'
    )


def render_svg(context, series, args):
    all_x = [x for _, points in series for x, _, _ in points]
    all_y = [y for _, points in series for _, y, _ in points]
    x_min = min(all_x)
    x_max = max(all_x)
    y_min = args.y_min if args.y_min is not None else min(0.0, min(all_y))
    y_max = args.y_max if args.y_max is not None else max(all_y) * 1.08

    if x_max <= x_min:
        x_max = x_min * 2.0
    if y_max <= y_min:
        y_max = y_min + 1.0

    width = args.width
    height = args.height
    left = 92
    right = 34
    top = 76
    bottom = 92
    plot_w = width - left - right
    plot_h = height - top - bottom
    log_x_min = math.log2(x_min)
    log_x_max = math.log2(x_max)

    def x_pos(value):
        return left + (math.log2(value) - log_x_min) / (log_x_max - log_x_min) * plot_w

    def y_pos(value):
        return top + (y_max - value) / (y_max - y_min) * plot_h

    elements = [
        '<?xml version="1.0" encoding="UTF-8"?>',
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" viewBox="0 0 {width} {height}">',
        "<style>",
        "text { font-family: Arial, Helvetica, sans-serif; fill: #111827; }",
        ".grid { stroke: #e5e7eb; stroke-width: 1; }",
        ".axis { stroke: #111827; stroke-width: 1.4; }",
        ".tick { stroke: #111827; stroke-width: 1; }",
        ".label { fill: #374151; }",
        "</style>",
        '<rect width="100%" height="100%" fill="white"/>',
        svg_text(width / 2, 32, args.title, size=22),
    ]

    subtitle_parts = []
    if context.get("host_name"):
        subtitle_parts.append(str(context["host_name"]))
    if context.get("date"):
        subtitle_parts.append(str(context["date"]))
    if subtitle_parts:
        elements.append(svg_text(width / 2, 54, " | ".join(subtitle_parts), size=12))

    for tick in linear_ticks(y_min, y_max):
        if tick < y_min - 1e-9 or tick > y_max + 1e-9:
            continue
        y = y_pos(tick)
        elements.append(f'<line class="grid" x1="{left}" y1="{y:.2f}" x2="{width - right}" y2="{y:.2f}"/>')
        elements.append(f'<line class="tick" x1="{left - 5}" y1="{y:.2f}" x2="{left}" y2="{y:.2f}"/>')
        elements.append(svg_text(left - 10, y + 4, format_number(tick), size=12, anchor="end"))

    last_label_x = -1e9
    for tick in log2_ticks(x_min, x_max):
        x = x_pos(tick)
        elements.append(f'<line class="grid" x1="{x:.2f}" y1="{top}" x2="{x:.2f}" y2="{height - bottom}"/>')
        elements.append(f'<line class="tick" x1="{x:.2f}" y1="{height - bottom}" x2="{x:.2f}" y2="{height - bottom + 5}"/>')
        if x - last_label_x >= 62:
            elements.append(svg_text(x, height - bottom + 22, format_bytes(tick), size=11))
            last_label_x = x

    elements.append(f'<line class="axis" x1="{left}" y1="{top}" x2="{left}" y2="{height - bottom}"/>')
    elements.append(f'<line class="axis" x1="{left}" y1="{height - bottom}" x2="{width - right}" y2="{height - bottom}"/>')
    elements.append(svg_text(width / 2, height - 26, f"{args.x} (log2 scale)", size=14, extra='class="label"'))
    elements.append(
        f'<text x="22" y="{top + plot_h / 2:.2f}" text-anchor="middle" font-size="14" '
        f'transform="rotate(-90 22 {top + plot_h / 2:.2f})" class="label">'
        f'{html.escape(", ".join(name for name, _ in series))}</text>'
    )

    legend_x = left + 12
    legend_y = top + 18
    for index, (name, points) in enumerate(series):
        color = COLORS[index % len(COLORS)]
        polyline_points = " ".join(f"{x_pos(x):.2f},{y_pos(y):.2f}" for x, y, _ in points)
        elements.append(
            f'<polyline points="{polyline_points}" fill="none" stroke="{color}" stroke-width="2.5" '
            'stroke-linejoin="round" stroke-linecap="round"/>'
        )
        for x, y, _ in points:
            elements.append(f'<circle cx="{x_pos(x):.2f}" cy="{y_pos(y):.2f}" r="3" fill="{color}"/>')
        elements.append(f'<line x1="{legend_x}" y1="{legend_y + index * 20}" x2="{legend_x + 24}" y2="{legend_y + index * 20}" stroke="{color}" stroke-width="2.5"/>')
        elements.append(svg_text(legend_x + 32, legend_y + 4 + index * 20, name, size=12, anchor="start"))

    elements.append("</svg>")
    return "\n".join(elements) + "\n"


def main():
    args = parse_args()
    y_keys = args.y_keys if args.y_keys else ["flop/core_cycle"]
    context, series = load_series(args.input_json, args.x, y_keys)
    svg = render_svg(context, series, args)
    output_path = Path(args.output_svg)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(svg, encoding="utf-8")


if __name__ == "__main__":
    raise SystemExit(main())
