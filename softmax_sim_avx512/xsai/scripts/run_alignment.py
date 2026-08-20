#!/usr/bin/env python3
"""Compare XSAI RTL kernel cycles with the generic semantic-uop simulator."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import sys
from pathlib import Path
from typing import Any, Callable


SCRIPT = Path(__file__).resolve()
PROJECT_ROOT = SCRIPT.parents[2]

EXPECTED_KERNELS = (
    "fma_throughput",
    "fma_latency",
    "axpy",
    "vector_copy",
    "vector_triad",
    "pointer_agu",
    "dot_product",
    "vector_reduction",
    "conversion",
    "vector_integer",
    "mixed_compute",
    "softmax",
)
EXPECTED_COUNTS = (512, 1024, 2048)

DIAGNOSTIC_MICROBENCHES = (
    "vset_throughput",
    "vset_rd_dependency",
    "load_same_vd",
    "load_alu_dependency",
    "load_fma_dependency",
    "load_fma_iteration",
    "load_fma_store_iteration",
)

RTL_BASE_FIELDS = {
    "source",
    "kernel",
    "n",
    "samples",
    "median_cycles",
    "min_cycles",
    "max_cycles",
    "cycles_per_element",
}


class AlignmentError(ValueError):
    pass


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for block in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _integer(row: dict[str, str], field: str) -> int:
    try:
        value = int(row[field])
    except (KeyError, TypeError, ValueError) as error:
        raise AlignmentError(
            f"invalid integer field {field!r}: {row.get(field)!r}"
        ) from error
    return value


def _number(value: str | None) -> float | None:
    if value is None or not value.strip():
        return None
    try:
        result = float(value)
    except ValueError:
        return None
    return result if math.isfinite(result) else None


def _boolean(value: str | None) -> bool | None:
    if value is None:
        return None
    normalized = value.strip().lower()
    if normalized in {"1", "true", "yes", "y", "pass", "eligible", "clean"}:
        return True
    if normalized in {
        "0",
        "false",
        "no",
        "n",
        "fail",
        "ineligible",
        "excluded",
        "contaminated",
    }:
        return False
    return None


def classify_cache(row: dict[str, str]) -> tuple[str, bool, str]:
    """Interpret explicit flags or HPM miss/refill columns without fixing a format."""

    normalized = {
        key.strip().lower().replace("-", "_"): value
        for key, value in row.items()
    }
    status_value = next(
        (
            normalized[key].strip().lower()
            for key in ("cache_status", "cache_state", "l1_status")
            if normalized.get(key, "").strip()
        ),
        None,
    )
    fit_status = normalized.get("fit_status", "").strip().lower()
    if fit_status in {"cache_contaminated", "cache-contaminated"}:
        return (
            "contaminated",
            False,
            "RTL summary has no cache-clean samples",
        )
    if fit_status == "valid":
        clean_evidence = True
    else:
        clean_evidence = False
    if status_value in {
        "contaminated",
        "cache_contaminated",
        "cache-contaminated",
        "dirty",
    }:
        return (
            "contaminated",
            False,
            "RTL summary marks the sample group cache-contaminated",
        )

    contaminated = False
    clean_evidence = clean_evidence or status_value in {
        "clean",
        "hot_l1",
        "hot-l1",
        "l1_clean",
        "pass",
    }
    reasons: list[str] = []

    explicit_contamination = None
    for key in (
        "cache_contaminated",
        "hpm_cache_contaminated",
        "l1_cache_contaminated",
    ):
        if key in normalized and normalized[key].strip():
            explicit_contamination = _boolean(normalized[key])
            if explicit_contamination is None:
                raise AlignmentError(
                    f"invalid cache contamination flag {key}={normalized[key]!r}"
                )
            if explicit_contamination:
                contaminated = True
                reasons.append(key)
            else:
                clean_evidence = True

    samples = _number(normalized.get("samples"))
    for key, value in normalized.items():
        if not value.strip():
            continue
        numeric = _number(value)
        if numeric is None:
            continue
        if "contaminated" in key and ("sample" in key or "count" in key):
            if numeric > 0:
                contaminated = True
                reasons.append(key)
            else:
                clean_evidence = True
        if key in {"clean_samples", "cache_clean_samples", "fit_eligible_samples"}:
            if numeric > 0:
                clean_evidence = True
            elif samples is not None:
                contaminated = True
                reasons.append(key)
        is_cache_counter = (
            any(token in key for token in ("l1", "dcache", "d_cache", "dtlb", "tlb"))
            and any(token in key for token in ("miss", "refill"))
        )
        if is_cache_counter:
            if numeric > 0:
                contaminated = True
                reasons.append(key)
            else:
                clean_evidence = True

    explicit_eligibility = _boolean(normalized.get("fit_eligible"))
    if explicit_eligibility is True:
        clean_evidence = True
    if contaminated:
        return (
            "contaminated",
            False,
            "nonzero cache/TLB contamination evidence: "
            + ", ".join(sorted(set(reasons))),
        )
    if explicit_eligibility is False:
        return (
            "unknown",
            False,
            "RTL summary explicitly excludes this group from fitting",
        )
    functional_status = normalized.get("status", "PASS").strip().upper()
    if functional_status and functional_status != "PASS":
        return (
            "clean" if clean_evidence else "unknown",
            False,
            f"functional status is {functional_status}",
        )
    if clean_evidence:
        return "clean", True, ""
    return "unknown", False, "cache/TLB HPM evidence is unavailable"


def read_rtl_summary(path: Path) -> list[dict[str, Any]]:
    if not path.is_file():
        raise AlignmentError(f"RTL summary does not exist: {path}")
    with path.open(newline="", encoding="utf-8") as source:
        reader = csv.DictReader(source)
        if reader.fieldnames is None:
            raise AlignmentError(f"RTL summary has no CSV header: {path}")
        missing = {
            "kernel",
            "n",
            "samples",
            "median_cycles",
            "min_cycles",
            "max_cycles",
        } - set(reader.fieldnames)
        if missing:
            raise AlignmentError(
                "RTL summary is missing fields: " + ", ".join(sorted(missing))
            )
        raw_rows = list(reader)

    indexed: dict[tuple[str, int], dict[str, Any]] = {}
    for unnormalized in raw_rows:
        raw = {key: value or "" for key, value in unnormalized.items()}
        if raw.get("source") and raw["source"].strip().lower() != "rtl":
            raise AlignmentError(f"summary row is not RTL data: source={raw['source']!r}")
        kernel = raw.get("kernel", "").strip()
        count = _integer(raw, "n")
        key = (kernel, count)
        if key in indexed:
            raise AlignmentError(f"duplicate RTL summary row: {kernel}/N={count}")
        samples = _integer(raw, "samples")
        median_cycles = _integer(raw, "median_cycles")
        minimum = _integer(raw, "min_cycles")
        maximum = _integer(raw, "max_cycles")
        if samples <= 0 or median_cycles <= 0 or minimum <= 0 or maximum <= 0:
            raise AlignmentError(f"non-positive RTL measurement in {kernel}/N={count}")
        if not minimum <= median_cycles <= maximum:
            raise AlignmentError(
                f"RTL min/median/max are inconsistent in {kernel}/N={count}"
            )
        cache_status, fit_eligible, exclusion_reason = classify_cache(raw)
        indexed[key] = {
            "kernel": kernel,
            "n": count,
            "samples": samples,
            "median_cycles": median_cycles,
            "min_cycles": minimum,
            "max_cycles": maximum,
            "cycles_per_element": median_cycles / count,
            "cache_status": cache_status,
            "fit_eligible": fit_eligible,
            "exclusion_reason": exclusion_reason,
            "rtl_fields": {
                key: value
                for key, value in raw.items()
                if key not in RTL_BASE_FIELDS and value != ""
            },
        }

    expected = {
        (kernel, count)
        for kernel in EXPECTED_KERNELS
        for count in EXPECTED_COUNTS
    }
    actual = set(indexed)
    if actual != expected:
        missing = sorted(expected - actual)
        extra = sorted(actual - expected)
        raise AlignmentError(
            f"incomplete RTL summary matrix: missing={missing}, extra={extra}"
        )
    return [
        indexed[(kernel, count)]
        for kernel in EXPECTED_KERNELS
        for count in EXPECTED_COUNTS
    ]


def read_profile_summary(path: Path | None) -> dict[str, dict[str, Any]]:
    """Read only the directed microbenchmarks used by the gap diagnosis."""

    if path is None or not path.is_file():
        return {}
    with path.open(newline="", encoding="utf-8") as source:
        reader = csv.DictReader(source)
        required = {
            "source",
            "name",
            "category",
            "unit",
            "samples",
            "operations",
            "median_cycles",
            "cycles_per_operation",
            "cache_status",
            "fit_status",
        }
        if reader.fieldnames is None:
            raise AlignmentError(f"profile summary has no CSV header: {path}")
        missing = required - set(reader.fieldnames)
        if missing:
            raise AlignmentError(
                "profile summary is missing fields: " + ", ".join(sorted(missing))
            )
        rows = list(reader)

    selected: dict[str, dict[str, Any]] = {}
    for raw in rows:
        name = (raw.get("name") or "").strip()
        if name not in DIAGNOSTIC_MICROBENCHES:
            continue
        if name in selected:
            raise AlignmentError(f"duplicate profile summary row: {name}")
        if (raw.get("source") or "").strip().lower() != "rtl":
            raise AlignmentError(f"profile summary row is not RTL data: {name}")
        samples = _integer(raw, "samples")
        operations = _integer(raw, "operations")
        median_cycles = _integer(raw, "median_cycles")
        cycles_per_operation = _number(raw.get("cycles_per_operation"))
        if (
            samples <= 0
            or operations <= 0
            or median_cycles <= 0
            or cycles_per_operation is None
            or cycles_per_operation <= 0
        ):
            raise AlignmentError(f"invalid profile measurement in {name}")
        selected[name] = {
            "category": (raw.get("category") or "").strip(),
            "unit": (raw.get("unit") or "").strip(),
            "samples": samples,
            "operations": operations,
            "median_cycles": median_cycles,
            "cycles_per_operation": cycles_per_operation,
            "cache_status": (raw.get("cache_status") or "").strip().lower(),
            "fit_status": (raw.get("fit_status") or "").strip().lower(),
        }
    return selected


def kernel_specs(kernel_root: Path) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    missing: list[Path] = []
    for kernel in EXPECTED_KERNELS:
        assembly = (
            kernel_root / kernel / "artifacts" / "rvv" / f"{kernel}_rvv.s"
        )
        if not assembly.is_file():
            missing.append(assembly)
        result.append(
            {
                "kernel": kernel,
                "assembly": assembly,
                "function": f"{kernel}_rvv_f32",
            }
        )
    if missing:
        raise AlignmentError(
            "missing RVV kernel assembly: "
            + ", ".join(str(path) for path in missing)
        )
    return result


def require_ready_profile(profile: Any) -> None:
    if profile.simulation_ready:
        return
    backend = profile.backend.get("execution_model", "missing")
    # A future binder may validate only parameters reached by the selected
    # trace.  Do not reject such a profile merely because unrelated L2/DRAM
    # parameters remain unresolved.
    if backend == "generic-token":
        return
    unresolved = list(profile.unresolved_parameters)
    preview = ", ".join(unresolved[:8])
    suffix = " ..." if len(unresolved) > 8 else ""
    detail = (
        f"; unresolved 'measure' parameters ({len(unresolved)}): {preview}{suffix}"
        if unresolved
        else ""
    )
    raise AlignmentError(
        f"XSAI profile is not simulation-ready (backend={backend}){detail}. "
        "Calibrate the profile first, or use --parse-only to validate RTL "
        "inputs without simulation."
    )


def simulate_matrix(
    records: list[dict[str, Any]],
    specs: list[dict[str, Any]],
    profile_path: Path,
    schema_path: Path,
    recipe_path: Path,
    uop_kinds_path: Path,
    simulator_case: Callable[[dict[str, Any], int, Any], dict[str, Any]]
    | None = None,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    if str(PROJECT_ROOT) not in sys.path:
        sys.path.insert(0, str(PROJECT_ROOT))
    from src.simulator.profile import load_profile

    profile = load_profile(profile_path, schema_path)
    require_ready_profile(profile)
    by_kernel = {spec["kernel"]: spec for spec in specs}

    if simulator_case is None:
        from src.frontends.rvv import build_dynamic_trace
        from src.simulator.engine import simulate

        def simulator_case(
            spec: dict[str, Any], count: int, loaded_profile: Any
        ) -> dict[str, Any]:
            vlen_bits = loaded_profile.data["isa"].get("vector_length_bits")
            if isinstance(vlen_bits, bool) or not isinstance(vlen_bits, int):
                raise AlignmentError(
                    "XSAI profile requires an integer isa.vector_length_bits"
                )
            dynamic = build_dynamic_trace(
                spec["assembly"],
                spec["function"],
                recipe_path,
                count,
                uop_kinds_path,
                vlen_bits=vlen_bits,
            )
            result = simulate(
                loaded_profile.bind(dynamic),
                loaded_profile,
                "out_of_order",
                "hot-l1",
                None,
            )
            return {
                "cycles": float(result.cycles),
                "backend": result.backend,
                "dynamic_instruction_count": dynamic["statistics"][
                    "dynamic_instruction_count"
                ],
                "semantic_uop_count": dynamic["statistics"]["semantic_uop_count"],
                "assembly_sha256": dynamic["provenance"]["assembly_sha256"],
            }

    aligned: list[dict[str, Any]] = []
    for record in records:
        try:
            simulation = simulator_case(
                by_kernel[record["kernel"]], record["n"], profile
            )
        except (KeyError, ValueError) as error:
            hint = (
                " Calibrate the parameters used by this trace, or use --parse-only."
                if "measure" in str(error).lower()
                else ""
            )
            raise AlignmentError(
                f"cannot simulate {record['kernel']}/N={record['n']}: {error}.{hint}"
            ) from error
        cycles = float(simulation["cycles"])
        if not math.isfinite(cycles) or cycles <= 0:
            raise AlignmentError(
                f"invalid simulator cycles for {record['kernel']}/N={record['n']}: {cycles}"
            )
        rtl_cycles = int(record["median_cycles"])
        relative_error = (cycles - rtl_cycles) / rtl_cycles * 100.0
        aligned.append(
            {
                **record,
                "simulator_cycles": cycles,
                "simulator_cycles_per_element": cycles / int(record["n"]),
                "signed_error_cycles": cycles - rtl_cycles,
                "relative_error_percent": relative_error,
                "absolute_relative_error_percent": abs(relative_error),
                "dynamic_instruction_count": int(
                    simulation["dynamic_instruction_count"]
                ),
                "semantic_uop_count": int(simulation["semantic_uop_count"]),
                "assembly_sha256": str(simulation["assembly_sha256"]),
            }
        )
    return aligned, {
        "profile_id": profile.id,
        "profile_sha256": profile.digest,
        "profile_path": str(profile_path),
        "schema_path": str(schema_path),
        "backend": str(profile.backend["execution_model"]),
        "execution_model": "out_of_order",
        "cache_mode": "hot-l1",
    }


def aggregate(records: list[dict[str, Any]]) -> dict[str, Any]:
    compared = [row for row in records if "simulator_cycles" in row]
    eligible = [row for row in compared if row["fit_eligible"]]

    def metrics(rows: list[dict[str, Any]]) -> dict[str, Any] | None:
        if not rows:
            return None
        absolute = [float(row["absolute_relative_error_percent"]) for row in rows]
        return {
            "points": len(rows),
            "mean_absolute_relative_error_percent": sum(absolute) / len(absolute),
            "max_absolute_relative_error_percent": max(absolute),
        }

    cache_counts = {
        state: sum(1 for row in records if row["cache_status"] == state)
        for state in ("clean", "contaminated", "unknown")
    }
    return {
        "rtl_points": len(records),
        "simulated_points": len(compared),
        "fit_eligible_points": len(eligible),
        "cache_status_counts": cache_counts,
        "diagnostic_all_points": metrics(compared),
        "fit_eligible_points_only": metrics(eligible),
    }


def _csv_value(value: Any) -> Any:
    if isinstance(value, float):
        return f"{value:.6f}"
    return value


def write_outputs(
    records: list[dict[str, Any]],
    output_dir: Path,
    rtl_summary: Path,
    profile_summary: Path | None,
    microbenchmark_evidence: dict[str, dict[str, Any]],
    mode: str,
    simulation_metadata: dict[str, Any] | None,
) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    fields = [
        "kernel",
        "n",
        "samples",
        "median_cycles",
        "min_cycles",
        "max_cycles",
        "cycles_per_element",
        "cache_status",
        "fit_eligible",
        "exclusion_reason",
        "simulator_cycles",
        "simulator_cycles_per_element",
        "signed_error_cycles",
        "relative_error_percent",
        "absolute_relative_error_percent",
        "dynamic_instruction_count",
        "semantic_uop_count",
        "assembly_sha256",
        "rtl_evidence_json",
    ]
    with (output_dir / "alignment.csv").open(
        "w", newline="", encoding="utf-8"
    ) as target:
        writer = csv.DictWriter(target, fieldnames=fields)
        writer.writeheader()
        for record in records:
            row = {field: _csv_value(record.get(field, "")) for field in fields}
            row["rtl_evidence_json"] = json.dumps(
                record.get("rtl_fields", {}), sort_keys=True, separators=(",", ":")
            )
            writer.writerow(row)

    document = {
        "format_version": 1,
        "status": "rtl-parsed" if mode == "parse-only" else "simulated",
        "mode": mode,
        "rtl_summary": {
            "path": str(rtl_summary),
            "sha256": file_sha256(rtl_summary),
        },
        "profile_summary": (
            {
                "path": str(profile_summary),
                "sha256": file_sha256(profile_summary),
            }
            if profile_summary is not None and profile_summary.is_file()
            else None
        ),
        "microbenchmark_evidence": microbenchmark_evidence,
        "simulation": simulation_metadata,
        "aggregate": aggregate(records),
        "records": records,
    }
    (output_dir / "alignment.json").write_text(
        json.dumps(document, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )


def _format_cycles(value: Any) -> str:
    if value in (None, ""):
        return "-"
    number = float(value)
    return f"{number:.2f}" if not number.is_integer() else str(int(number))


def write_report(
    path: Path,
    records: list[dict[str, Any]],
    rtl_summary: Path,
    microbenchmark_evidence: dict[str, dict[str, Any]],
    mode: str,
    simulation_metadata: dict[str, Any] | None,
) -> None:
    stats = aggregate(records)
    lines = [
        "# XSAI 模拟器对齐结果",
        "",
        "> 本文件由 `xsai/scripts/run_alignment.py` 生成。工具只比较结果，不自动修改 profile。",
        "",
        "## 状态",
        "",
        f"- 模式：`{mode}`",
        f"- RTL 汇总：`{rtl_summary}`",
        f"- RTL 点数：{stats['rtl_points']}，"
        f"模拟点数：{stats['simulated_points']}，"
        f"拟合有效点数：{stats['fit_eligible_points']}",
    ]
    if simulation_metadata:
        lines.extend(
            [
                f"- Profile：`{simulation_metadata['profile_id']}`"
                f"（`{simulation_metadata['profile_sha256']}`）",
                f"- 执行后端：`{simulation_metadata['backend']}`",
                "- 执行模型：乱序、Hot-L1",
            ]
        )
    else:
        lines.append("- 模拟尚未运行；profile 完成校准后去掉 `--parse-only` 重新执行。")
    cache = stats["cache_status_counts"]
    lines.extend(
        [
            f"- 缓存证据：clean={cache['clean']}，"
            f"contaminated={cache['contaminated']}，unknown={cache['unknown']}。"
            "后两类不进入拟合统计。",
            "",
            "## 汇总",
            "",
        ]
    )
    eligible_metrics = stats["fit_eligible_points_only"]
    if eligible_metrics:
        lines.append(
            "拟合有效点 MAPE 为 "
            f"{eligible_metrics['mean_absolute_relative_error_percent']:.2f}%，"
            "最大绝对相对误差为 "
            f"{eligible_metrics['max_absolute_relative_error_percent']:.2f}%。"
        )
    else:
        lines.append("当前没有同时具备模拟结果与 clean HPM 证据的拟合有效点。")
    lines.extend(
        [
            "",
            "| Kernel | N | RTL cycles | Simulator cycles | Error | Cache | Fit |",
            "|---|---:|---:|---:|---:|---|---|",
        ]
    )
    for row in records:
        error = (
            f"{float(row['relative_error_percent']):+.2f}%"
            if "relative_error_percent" in row
            else "-"
        )
        lines.append(
            f"| {row['kernel']} | {row['n']} | {row['median_cycles']} | "
            f"{_format_cycles(row.get('simulator_cycles'))} | {error} | "
            f"{row['cache_status']} | {'yes' if row['fit_eligible'] else 'no'} |"
        )
    lines.extend(["", "## 差距诊断", ""])
    if microbenchmark_evidence:
        lines.extend(
            [
                "| RTL 微基准 | cycles/operation | 说明 |",
                "|---|---:|---|",
            ]
        )
        descriptions = {
            "vset_throughput": "`x0,x0` keep-VL 形式的独立吞吐",
            "vset_rd_dependency": "标量 `rd` 到下一条 vset 的 RAW 链",
            "load_same_vd": "普通向量寄存器 `v8` 的重复 load",
            "load_alu_dependency": "普通 `v8` load -> vector ALU",
            "load_fma_dependency": "普通 `v8` load -> FMA",
            "load_fma_iteration": "vset 在循环外的 load/FMA 迭代",
            "load_fma_store_iteration": "vset 在循环外的 load/FMA/store 迭代",
        }
        for name in DIAGNOSTIC_MICROBENCHES:
            evidence = microbenchmark_evidence.get(name)
            if evidence is None:
                continue
            lines.append(
                f"| `{name}` | {evidence['cycles_per_operation']:.3f} | "
                f"{descriptions[name]} |"
            )
        lines.extend(
            [
                "",
                "普通 `v8` 的 load 与 load-use 结果不支持把所有向量 load "
                "统一设为 16 cycle；该假设已排除。现有两组 vset 测试分别覆盖特殊 "
                "keep-VL 形式和标量 `rd` RAW，但都没有覆盖真实 kernel 每轮 "
                "`vsetvli a5,a5` 后由向量/VLSU 消费 VL 的路径。",
                "",
                "FMA kernel 的误差约为 0%--3%，而多数组合 kernel 仍明显偏乐观。"
                "当前最小未决缺口是 profile-driven 的 VL 写回可见性，以及 VLSU "
                "oldest/order、split/merge/replay 和完成路径；在定向 RTL 微基准完成前，"
                "报告不会用 kernel 误差反推一个统一延迟或串行屏障。",
            ]
        )
    else:
        lines.append(
            "未提供 RTL profile summary；本报告不对资源级误差原因作参数判断。"
        )
    lines.extend(
        [
            "",
            "## 判定规则",
            "",
            "`cache-contaminated` 点保留在表格和机器可读文件中，但不参与"
            "拟合统计。缺少 L1/TLB HPM 证据的 `unknown` 点同样不参与拟合，"
            "避免把缓存影响误归因于执行后端。",
            "",
        ]
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines), encoding="utf-8")


def parse_arguments(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Align XSAI RTL kernel cycles with the selected simulator backend"
    )
    parser.add_argument(
        "--rtl-summary",
        type=Path,
        default=PROJECT_ROOT / "artifacts/xsai/rtl/summary.csv",
    )
    parser.add_argument(
        "--profile-summary",
        type=Path,
        default=PROJECT_ROOT / "artifacts/xsai/rtl/profile_summary.csv",
        help="optional directed RTL microbenchmark summary used for diagnosis",
    )
    parser.add_argument("--kernel-root", type=Path, default=PROJECT_ROOT / "kernel")
    parser.add_argument(
        "--profile", type=Path, default=PROJECT_ROOT / "profiles/xsai.yaml"
    )
    parser.add_argument(
        "--schema",
        type=Path,
        default=PROJECT_ROOT / "schemas/profile.schema.json",
    )
    parser.add_argument(
        "--recipe", type=Path, default=PROJECT_ROOT / "recipes/rvv.yaml"
    )
    parser.add_argument(
        "--uop-kinds",
        type=Path,
        default=PROJECT_ROOT / "uops/uop_kinds.yaml",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=PROJECT_ROOT / "artifacts/xsai/alignment",
    )
    parser.add_argument(
        "--report", type=Path, default=PROJECT_ROOT / "docs/xsai_result.md"
    )
    parser.add_argument(
        "--parse-only",
        action="store_true",
        help="validate/normalize RTL and cache evidence without loading or running the profile",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_arguments(argv)
    try:
        records = read_rtl_summary(args.rtl_summary)
        microbenchmark_evidence = read_profile_summary(args.profile_summary)
        specs = kernel_specs(args.kernel_root)
        simulation_metadata = None
        mode = "parse-only" if args.parse_only else "simulate"
        if not args.parse_only:
            records, simulation_metadata = simulate_matrix(
                records,
                specs,
                args.profile,
                args.schema,
                args.recipe,
                args.uop_kinds,
            )
        write_outputs(
            records,
            args.output_dir,
            args.rtl_summary,
            args.profile_summary,
            microbenchmark_evidence,
            mode,
            simulation_metadata,
        )
        write_report(
            args.report,
            records,
            args.rtl_summary,
            microbenchmark_evidence,
            mode,
            simulation_metadata,
        )
    except (AlignmentError, OSError, KeyError, ValueError) as error:
        print(f"alignment: error: {error}", file=sys.stderr)
        return 2
    print(
        json.dumps(
            {
                "mode": mode,
                "points": len(records),
                "fit_eligible_points": aggregate(records)["fit_eligible_points"],
                "output_dir": str(args.output_dir),
                "report": str(args.report),
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
