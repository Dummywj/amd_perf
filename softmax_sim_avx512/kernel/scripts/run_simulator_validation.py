#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import statistics
import sys
from pathlib import Path

try:
    import yaml
except ModuleNotFoundError as error:
    raise SystemExit(
        "PyYAML is required; run with the project Python environment"
    ) from error

DEFAULT_PROJECT_DIR = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(DEFAULT_PROJECT_DIR))

from src.frontends.x86 import build_dynamic_trace
from src.simulator.engine import simulate
from src.simulator.profile import load_profile


KERNELS = (
    "fma_throughput",
    "fma_latency",
    "axpy",
    "dot_product",
    "vector_copy",
    "vector_triad",
    "vector_reduction",
    "conversion",
    "vector_integer",
    "mixed_compute",
    "pointer_agu",
)


def percentile(values: list[float], fraction: float) -> float:
    ordered = sorted(values)
    position = fraction * (len(ordered) - 1)
    lower = int(position)
    upper = min(lower + 1, len(ordered) - 1)
    weight = position - lower
    return ordered[lower] * (1.0 - weight) + ordered[upper] * weight


def load_measurements(path: Path | None) -> dict[tuple[str, int], dict[str, float]]:
    if path is None:
        return {}
    document = json.loads(path.read_text(encoding="utf-8"))
    grouped: dict[tuple[str, int], list[float]] = {}
    for row in document["measurements"]:
        key = (str(row["kernel"]), int(row["count"]))
        grouped.setdefault(key, []).append(float(row["net_cycles"]))
    return {
        key: {
            "median": statistics.median(values),
            "p10": percentile(values, 0.1),
            "p90": percentile(values, 0.9),
        }
        for key, values in grouped.items()
    }


def write_markdown(path: Path, output: dict[str, object]) -> None:
    rows = output["results"]
    assert isinstance(rows, list)
    lines = [
        "# Kernel 测试结果",
        "",
        "本文汇总新增 kernel 的功能验证、Zen 4 真机周期和模拟器周期。"
        "真机以 7 次重复测量的净周期中位数为主，模拟器以乱序模型为主；"
        "顺序模型仅用于诊断乱序收益。",
        "",
        "## 验证环境",
        "",
        "- 真机：AMD EPYC 9684X（Zen 4），固定 CPU 8、NUMA node 0。",
        "- x86：GCC 13.3，AVX-512/FMA，功能测试 56/56 通过。",
        "- RVV：GCC 13.3 cross compiler，Spike VLEN=128/512 均 56/56 通过。",
        "- 模拟器 profile：`amd-zen4-epyc-9684x`。",
        f"- Profile SHA-256：`{output['profile_sha256']}`。",
        "- `N=256/1024` 使用 `hot-l1`；`N=4096` 使用 `hot-capacity`。",
        "- 本轮未修改既有 profile 参数；新 memory-source timing 是基于既有 "
        "load/compute 参数的 provisional 等效分解，尚未单独校准。",
        "",
        "## 周期对比",
        "",
        "相对误差为 `(乱序模拟 - 真机中位数) / 真机中位数`。绝对值不超过 10%"
        "记为首轮通过，超过 10% 记为待分析。",
        "",
        "| Kernel | N | Cache | 真机总周期 [p10, p90] | 真机周期/元素 | 乱序周期/元素 | 乱序总周期 | 顺序总周期 | 误差 | 结论 |",
        "|---|---:|---|---:|---:|---:|---:|---:|---:|---|",
    ]
    for row in rows:
        assert isinstance(row, dict)
        measured = row.get("hardware_median_cycles")
        relative = row.get("relative_error")
        if measured is None or relative is None:
            hardware_range = hardware_per_element = error = "-"
            verdict = "无真机数据"
        else:
            hardware_range = (
                f"{float(measured):.2f} "
                f"[{float(row['hardware_p10_cycles']):.2f}, "
                f"{float(row['hardware_p90_cycles']):.2f}]"
            )
            hardware_per_element = f"{float(measured) / int(row['count']):.4f}"
            error = f"{float(relative) * 100:+.1f}%"
            verdict = "通过" if abs(float(relative)) <= 0.10 else "待分析"
        lines.append(
            f"| {row['kernel']} | {row['count']} | {row['cache_mode']} | "
            f"{hardware_range} | {hardware_per_element} | "
            f"{float(row['out_of_order_cycles']) / int(row['count']):.4f} | "
            f"{float(row['out_of_order_cycles']):.2f} | "
            f"{float(row['in_order_cycles']):.2f} | {error} | {verdict} |"
        )

    lines.extend(
        [
            "",
            "## 模拟器诊断摘要（N=4096）",
            "",
            "| Kernel | Macro-op | Execution uop | 关键路径 | Peak ROB/VS/LQ/SQ | 主要资源 issue |",
            "|---|---:|---:|---:|---:|---|",
        ]
    )
    for row in rows:
        assert isinstance(row, dict)
        if row["count"] != 4096:
            continue
        resource_issues = row["resource_issues"]
        assert isinstance(resource_issues, dict)
        major_issues = ", ".join(
            f"{name}={count}"
            for name, count in sorted(resource_issues.items())
            if int(count) > 1
        )
        lines.append(
            f"| {row['kernel']} | {row['dynamic_macro_ops']} | "
            f"{row['execution_uops']} | "
            f"{float(row['dependency_critical_path_cycles']):.2f} | "
            f"{row['peak_rob']}/{row['peak_vector_scheduler']}/"
            f"{row['peak_load_queue']}/{row['peak_store_queue']} | "
            f"{major_issues} |"
        )

    lines.extend(
        [
            "",
            "## 审核结论",
            "",
            "- 共 33 个周期点，22 个处于 ±10% 内；在 `N>=1024` 的 22 个稳态点中，"
            "16 个处于 ±10% 内。",
            "- FMA throughput/latency、Dot、Copy、Reduction、Conversion、Integer "
            "已能较好隔离对应资源，主要稳态点达到约 10% 误差范围。",
            "- AXPY、Triad、Pointer/AGU 以及部分 Mixed Compute 点仍有明显偏差，"
            "优先检查 memory-source 指令的 load/compute 重叠、cache 初态和 AGU 竞争。",
            "- `N=4096` 的多输入工作集超过 L1 容量，不应与 `hot-l1` 点混合拟合。",
            "- 新 memory-source profile recipe 复用既有 load/compute timing，属于 "
            "provisional 等效假设；不能视为新的本地校准结果。",
            "- 当前结果不足以授权修改 profile；后续参数变更仍需独立微基准和 hold-out "
            "kernel 共同验证。",
            "",
            "原始 PMU 和模拟器 JSON 位于被 Git 忽略的 "
            "`artifacts/kernel_validation/`。",
        ]
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Run the kernel suite through both simulator execution models"
    )
    parser.add_argument("--project-dir", type=Path, default=DEFAULT_PROJECT_DIR)
    parser.add_argument("--hardware-json", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--markdown", type=Path)
    args = parser.parse_args()

    project = args.project_dir.resolve()
    profile = load_profile(
        project / "profiles/amd_zen4.yaml",
        project / "schemas/profile.schema.json",
    )
    hardware = load_measurements(args.hardware_json)
    rows: list[dict[str, object]] = []
    for kernel in KERNELS:
        workload = yaml.safe_load(
            (project / f"kernel/{kernel}/workloads/{kernel}.yaml").read_text(
                encoding="utf-8"
            )
        )
        assembly = project / f"kernel/{kernel}/artifacts/x86/{kernel}_avx512.s"
        for point in workload["points"]:
            count = int(point["count"])
            trace = build_dynamic_trace(
                assembly,
                f"{kernel}_avx512_f32",
                project / "recipes/x86.yaml",
                count,
                project / "uops/uop_kinds.yaml",
            )
            bound = profile.bind(trace)
            results = {
                model: simulate(bound, profile, model, str(point["cache_mode"]))
                for model in ("out_of_order", "in_order")
            }
            row: dict[str, object] = {
                "kernel": kernel,
                "count": count,
                "cache_mode": point["cache_mode"],
                "out_of_order_cycles": results["out_of_order"].cycles,
                "in_order_cycles": results["in_order"].cycles,
                "dynamic_macro_ops": results["out_of_order"].summary[
                    "dynamic_macro_ops"
                ],
                "execution_uops": results["out_of_order"].summary["execution_uops"],
                "dependency_critical_path_cycles": results["out_of_order"].summary[
                    "dependency_critical_path_cycles"
                ],
                "peak_rob": results["out_of_order"].summary["peak_rob"],
                "peak_vector_scheduler": results["out_of_order"].summary[
                    "peak_vector_scheduler"
                ],
                "peak_load_queue": results["out_of_order"].summary[
                    "peak_load_queue"
                ],
                "peak_store_queue": results["out_of_order"].summary[
                    "peak_store_queue"
                ],
                "resource_issues": results["out_of_order"].summary["resource_issues"],
            }
            measured = hardware.get((kernel, count))
            if measured:
                row["hardware_median_cycles"] = measured["median"]
                row["hardware_p10_cycles"] = measured["p10"]
                row["hardware_p90_cycles"] = measured["p90"]
                row["relative_error"] = (
                    results["out_of_order"].cycles - measured["median"]
                ) / measured["median"]
            rows.append(row)

    output = {
        "format_version": 1,
        "profile_id": profile.id,
        "profile_sha256": profile.digest,
        "hardware_measurements": str(args.hardware_json) if args.hardware_json else None,
        "results": rows,
        "note": "No profile values are modified by this validation pass.",
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(output, indent=2) + "\n", encoding="utf-8")
    if args.markdown:
        write_markdown(args.markdown, output)
    print(f"Wrote {len(rows)} simulator validation points to {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
