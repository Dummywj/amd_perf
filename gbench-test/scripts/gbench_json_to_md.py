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

    candidate_columns = [
        ("Benchmark", "name"),
        ("Iterations", "iterations"),
        ("Elements", "elements"),
        ("Working Set Bytes", "working_set_bytes"),
        ("FMA Rounds", "fma_rounds"),
        ("Inner Passes", "inner_passes"),
        ("Core Cycles", "core_cycles"),
        ("elem/core_cycle", "elem/core_cycle"),
        ("fma_instr/core_cycle", "fma_instr/core_cycle"),
        ("flop/core_cycle", "flop/core_cycle"),
        ("bytes/core_cycle", "bytes/core_cycle"),
        ("flop/byte", "flop/byte"),
        ("items/s", "items_per_second"),
    ]
    columns = [
        (name, key)
        for name, key in candidate_columns
        if key == "name" or any(key in row for row in rows)
    ]

    lines = [
        "# Google Benchmark 结果",
        "",
        f"- 日期：{context.get('date', '')}",
        f"- 主机：{context.get('host_name', '')}",
        f"- 可执行文件：`{context.get('executable', '')}`",
        f"- CPU 数量：{context.get('num_cpus', '')}",
        f"- Google Benchmark 版本：{context.get('library_version', '')}",
        "",
        "| " + " | ".join(name for name, _ in columns) + " |",
        "| " + " | ".join("---" if key == "name" else "---:" for _, key in columns) + " |",
    ]

    for row in rows:
        cells = []
        for _, key in columns:
            if key == "name":
                cells.append(row.get(key, ""))
            else:
                cells.append(fmt_number(row.get(key)))
        lines.append("| " + " | ".join(cells) + " |")

    lines.append("")
    output_path.write_text("\n".join(lines), encoding="utf-8")


if __name__ == "__main__":
    raise SystemExit(main())
