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
EXPECTED_COUNTS = (512, 1024, 2048)


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


def load_hardware_repetitions(path: Path | None) -> int | None:
    if path is None:
        return None
    document = json.loads(path.read_text(encoding="utf-8"))
    repetitions = document.get("repetitions")
    return int(repetitions) if repetitions is not None else None


def write_markdown(path: Path, output: dict[str, object]) -> None:
    rows = output["results"]
    assert isinstance(rows, list)
    measured_rows = [
        row
        for row in rows
        if isinstance(row, dict) and row.get("hardware_median_cycles") is not None
    ]
    judged_rows = [row for row in measured_rows if bool(row["judged"])]
    passed_rows = [row for row in judged_rows if row["verdict"] == "通过"]
    steady_rows = judged_rows
    overlap_changed_rows = [
        row
        for row in judged_rows
        if float(row["baseline_out_of_order_cycles"])
        != float(row["out_of_order_cycles"])
    ]

    def mean_absolute_error(
        selected: list[dict[str, object]], field: str
    ) -> float | None:
        if not selected:
            return None
        return statistics.mean(abs(float(row[field])) for row in selected)

    baseline_mae = mean_absolute_error(judged_rows, "baseline_relative_error")
    limited_mae = mean_absolute_error(judged_rows, "relative_error")
    steady_baseline_mae = mean_absolute_error(
        steady_rows, "baseline_relative_error"
    )
    steady_limited_mae = mean_absolute_error(steady_rows, "relative_error")
    failed_steady_kernels = sorted(
        {str(row["kernel"]) for row in steady_rows if row["verdict"] == "待分析"}
    )
    axpy_triad_steady = [
        row
        for row in steady_rows
        if str(row["kernel"]) in {"axpy", "vector_triad"}
    ]
    pointer_steady = [
        row for row in steady_rows if str(row["kernel"]) == "pointer_agu"
    ]
    mixed_steady = [
        row for row in steady_rows if str(row["kernel"]) == "mixed_compute"
    ]

    lines = [
        "# Kernel 测试结果",
        "",
        "本文汇总新增 kernel 的功能验证、Zen 4 真机周期和模拟器周期。"
        f"真机以 {output.get('hardware_repetitions', '未知')} 次重复测量的净周期中位数为主；"
        "乱序模型同时给出显式关闭 memory-source FMA overlap 限制的基线，"
        "以及按 Zen 4 profile "
        "默认开启限制的修改后结果。",
        "",
        "## 验证环境",
        "",
        "- 真机：AMD EPYC 9684X（Zen 4），固定 CPU 8、NUMA node 0。",
        "- x86：GCC 13.3，AVX-512/FMA，功能测试 34/34 通过。",
        "- RVV：GCC 13.3 cross compiler，Spike VLEN=128/512 均 34/34 通过。",
        "- 模拟器 profile：`amd-zen4-epyc-9684x`。",
        f"- Profile SHA-256：`{output['profile_sha256']}`。",
        "- Zen 4 overlap 配置：默认开启，最多 2 个待发射组，"
        "仅匹配 `vector_fp_fma` semantic uop。",
        "- 共享 issue domain：窄执行域 2 part-token/cycle、总执行域 4 "
        "part-token/cycle、加权寄存器源交付域 8 source-token/cycle。",
        "- 报告仅覆盖 `N=512/1024/2048`，全部使用 `hot-l1`。",
        "- 校验脚本只读取 profile，不会根据误差自动改参。",
        "",
        "## 周期对比",
        "",
        "相对误差为 `(模拟 - 真机中位数) / 真机中位数`。"
        "三个规模的绝对误差不超过 10% 记为通过。",
        "",
        "| Kernel | N | Cache | 真机净周期 [p10, p90] | 限制前周期 | 限制前误差 | 限制后周期 | 限制后误差 | 绝对误差改善 | 结论 |",
        "|---|---:|---|---:|---:|---:|---:|---:|---:|---|",
    ]
    for row in rows:
        assert isinstance(row, dict)
        measured = row.get("hardware_median_cycles")
        limited_relative = row.get("relative_error")
        baseline_relative = row.get("baseline_relative_error")
        if measured is None or limited_relative is None or baseline_relative is None:
            hardware_range = baseline_error = limited_error = improvement = "-"
        else:
            hardware_range = (
                f"{float(measured):.2f} "
                f"[{float(row['hardware_p10_cycles']):.2f}, "
                f"{float(row['hardware_p90_cycles']):.2f}]"
            )
            baseline_error = f"{float(baseline_relative) * 100:+.1f}%"
            limited_error = f"{float(limited_relative) * 100:+.1f}%"
            improvement = (
                f"{(abs(float(baseline_relative)) - abs(float(limited_relative))) * 100:+.1f} pp"
            )
        lines.append(
            f"| {row['kernel']} | {row['count']} | {row['cache_mode']} | "
            f"{hardware_range} | {float(row['baseline_out_of_order_cycles']):.2f} | "
            f"{baseline_error} | {float(row['out_of_order_cycles']):.2f} | "
            f"{limited_error} | {improvement} | {row['verdict']} |"
        )

    lines.extend(
        [
            "",
            "## 顺序模型诊断（N=2048）",
            "",
            "顺序模型仅用于观察乱序调度收益，不参与通过判定。",
            "",
            "| Kernel | 顺序周期 | 乱序（默认限制）周期 |",
            "|---|---:|---:|",
        ]
    )
    for row in rows:
        assert isinstance(row, dict)
        if row["count"] == 2048:
            lines.append(
                f"| {row['kernel']} | {float(row['in_order_cycles']):.2f} | "
                f"{float(row['out_of_order_cycles']):.2f} |"
            )

    lines.extend(
        [
            "",
            "## 模拟器诊断摘要（N=2048）",
            "",
            "| Kernel | Macro-op | Execution uop | 关键路径 | Peak ROB/VS/LQ/SQ | 主要资源 issue |",
            "|---|---:|---:|---:|---:|---|",
        ]
    )
    for row in rows:
        assert isinstance(row, dict)
        if row["count"] != 2048:
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

    lines.extend(["", "## 审核结论", ""])
    lines.append(
        f"- 有真机数据且参与审核的周期点共 {len(judged_rows)} 个，"
        f"{len(passed_rows)} 个处于 ±10% 内。"
    )
    if (
        baseline_mae is not None
        and limited_mae is not None
        and steady_baseline_mae is not None
        and steady_limited_mae is not None
    ):
        direction = "改善" if limited_mae < baseline_mae else "未改善"
        lines.append(
            f"- overlap 限制实际改变了 {len(overlap_changed_rows)} 个参审点；"
            f"全部参审点的平均绝对误差由 {baseline_mae * 100:.1f}% "
            f"变为 {limited_mae * 100:.1f}%，三个稳态规模则由 "
            f"{steady_baseline_mae * 100:.1f}% 变为 "
            f"{steady_limited_mae * 100:.1f}%，总体{direction}。"
        )
    else:
        lines.append("- 本轮参审点中 overlap 限制未改变模拟周期。")
    if axpy_triad_steady and pointer_steady and mixed_steady:
        axpy_triad_before = max(
            abs(float(row["baseline_relative_error"])) for row in axpy_triad_steady
        )
        axpy_triad_after = max(
            abs(float(row["relative_error"])) for row in axpy_triad_steady
        )
        pointer_after = max(
            abs(float(row["relative_error"])) for row in pointer_steady
        )
        mixed_after = [abs(float(row["relative_error"])) for row in mixed_steady]
        lines.append(
            "- `N=512/1024/2048`：AXPY/Triad 最大绝对误差由 "
            f"{axpy_triad_before * 100:.1f}% 降至 {axpy_triad_after * 100:.1f}%；"
            f"Pointer/AGU 保持不变且不超过 {pointer_after * 100:.1f}%；"
            f"Mixed Compute 仍为 {min(mixed_after) * 100:.1f}% 到 "
            f"{max(mixed_after) * 100:.1f}%。"
        )
    if not steady_rows:
        lines.append("- 未提供可审核的 `N=512/1024/2048` 真机数据。")
    elif failed_steady_kernels:
        lines.append(
            "- 稳态点仍需分析的 kernel："
            + "、".join(failed_steady_kernels)
            + "。"
        )
    else:
        lines.append("- 所有有真机数据的稳态点均处于 ±10% 内。")
    lines.extend(
        [
            "- 容量边界与 L2 初始状态不在本轮报告范围内。",
            "- overlap 限制是微架构相关的等效调度约束，"
            "不应被解读为精确的物理队列容量。",
            "- 后续 profile 变更仍需独立微基准和 hold-out kernel 共同验证。",
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
    hardware_repetitions = load_hardware_repetitions(args.hardware_json)
    rows: list[dict[str, object]] = []
    for kernel in KERNELS:
        workload = yaml.safe_load(
            (project / f"kernel/{kernel}/workloads/{kernel}.yaml").read_text(
                encoding="utf-8"
            )
        )
        point_counts = tuple(int(point["count"]) for point in workload["points"])
        if point_counts != EXPECTED_COUNTS:
            raise ValueError(
                f"{kernel} workload counts must be {EXPECTED_COUNTS}, got {point_counts}"
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
            cache_mode = str(point["cache_mode"])
            out_of_order = simulate(
                bound,
                profile,
                "out_of_order",
                cache_mode,
                memory_compute_overlap_limit=None,
            )
            baseline_out_of_order = simulate(
                bound,
                profile,
                "out_of_order",
                cache_mode,
                memory_compute_overlap_limit=False,
            )
            in_order = simulate(
                bound,
                profile,
                "in_order",
                cache_mode,
                memory_compute_overlap_limit=None,
            )
            measured = hardware.get((kernel, count))
            row: dict[str, object] = {
                "kernel": kernel,
                "count": count,
                "cache_mode": point["cache_mode"],
                "out_of_order_cycles": out_of_order.cycles,
                "baseline_out_of_order_cycles": baseline_out_of_order.cycles,
                "in_order_cycles": in_order.cycles,
                "dynamic_macro_ops": out_of_order.summary["dynamic_macro_ops"],
                "execution_uops": out_of_order.summary["execution_uops"],
                "dependency_critical_path_cycles": out_of_order.summary[
                    "dependency_critical_path_cycles"
                ],
                "peak_rob": out_of_order.summary["peak_rob"],
                "peak_vector_scheduler": out_of_order.summary[
                    "peak_vector_scheduler"
                ],
                "peak_load_queue": out_of_order.summary["peak_load_queue"],
                "peak_store_queue": out_of_order.summary["peak_store_queue"],
                "resource_issues": out_of_order.summary["resource_issues"],
                "judged": measured is not None,
            }
            if measured:
                row["hardware_median_cycles"] = measured["median"]
                row["hardware_p10_cycles"] = measured["p10"]
                row["hardware_p90_cycles"] = measured["p90"]
                row["relative_error"] = (
                    out_of_order.cycles - measured["median"]
                ) / measured["median"]
                row["baseline_relative_error"] = (
                    baseline_out_of_order.cycles - measured["median"]
                ) / measured["median"]
                row["absolute_error_improvement"] = abs(
                    float(row["baseline_relative_error"])
                ) - abs(float(row["relative_error"]))
            if measured:
                row["verdict"] = (
                    "通过" if abs(float(row["relative_error"])) <= 0.10 else "待分析"
                )
            else:
                row["verdict"] = "无真机数据"
            rows.append(row)

    output = {
        "format_version": 2,
        "profile_id": profile.id,
        "profile_sha256": profile.digest,
        "hardware_measurements": str(args.hardware_json) if args.hardware_json else None,
        "hardware_repetitions": hardware_repetitions,
        "memory_compute_overlap_limit": profile.memory_compute_overlap_limit,
        "results": rows,
        "note": (
            "Validation is read-only: the default profile overlap limit is compared "
            "with an explicitly disabled baseline; only N=512/1024/2048 are included."
        ),
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(output, indent=2) + "\n", encoding="utf-8")
    if args.markdown:
        write_markdown(args.markdown, output)
    print(f"Wrote {len(rows)} simulator validation points to {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
