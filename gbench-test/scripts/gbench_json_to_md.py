#!/usr/bin/env python3

import json
import sys
from pathlib import Path


def fmt_number(value):
    if value is None:
        return ""
    if isinstance(value, int):
        return f"{value:,}"
    if abs(value) >= 1_000_000_000:
        return f"{value / 1_000_000_000:.3f}G"
    if abs(value) >= 1_000_000:
        return f"{value / 1_000_000:.3f}M"
    if abs(value) >= 1_000:
        return f"{value / 1_000:.3f}K"
    return f"{value:.6g}"


def main():
    if len(sys.argv) != 3:
        print("usage: gbench_json_to_md.py <input.json> <output.md>", file=sys.stderr)
        return 2

    input_path = Path(sys.argv[1])
    output_path = Path(sys.argv[2])

    with input_path.open() as f:
        data = json.load(f)

    context = data.get("context", {})
    rows = data.get("benchmarks", [])

    lines = [
        "# Google Benchmark 结果",
        "",
        f"- 日期：{context.get('date', '')}",
        f"- 主机：{context.get('host_name', '')}",
        f"- 可执行文件：`{context.get('executable', '')}`",
        f"- CPU 数量：{context.get('num_cpus', '')}",
        f"- Google Benchmark 版本：{context.get('library_version', '')}",
        "",
        "| Benchmark | Iterations | Core Cycles | elem/core_cycle | items/s |",
        "| --- | ---: | ---: | ---: | ---: |",
    ]

    for row in rows:
        lines.append(
            "| {name} | {iterations} | {core_cycles} | {elem_cycle} | {items_s} |".format(
                name=row.get("name", ""),
                iterations=fmt_number(row.get("iterations")),
                core_cycles=fmt_number(row.get("core_cycles")),
                elem_cycle=fmt_number(row.get("elem/core_cycle")),
                items_s=fmt_number(row.get("items_per_second")),
            )
        )

    lines.append("")
    output_path.write_text("\n".join(lines), encoding="utf-8")


if __name__ == "__main__":
    raise SystemExit(main())

