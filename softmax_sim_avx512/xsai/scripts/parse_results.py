#!/usr/bin/env python3
"""Convert XSAI bare-metal result markers into stable CSV/JSON artifacts."""

from __future__ import annotations

import argparse
import csv
import json
import statistics
from collections import defaultdict
from pathlib import Path


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
EXPECTED_PARAMETER_SPECS = {
    "loop16_baseline": ("baseline", "nop", 16),
    "scalar_alu_dependency": ("dependency", "instruction", 16),
    "scalar_alu_throughput": ("throughput", "instruction", 16),
    "scalar_fp_add_dependency": ("dependency", "instruction", 16),
    "scalar_fp_add_throughput": ("throughput", "instruction", 16),
    "scalar_fp_div_dependency": ("dependency", "instruction", 8),
    "vset_throughput": ("throughput", "instruction", 16),
    "fma_dependency": ("dependency", "instruction", 16),
    "fma_throughput": ("throughput", "instruction", 16),
    "fp_add_dependency": ("dependency", "instruction", 16),
    "fp_add_throughput": ("throughput", "instruction", 16),
    "fp_add_same_vd": ("same_vd", "instruction", 16),
    "integer_dependency": ("dependency", "instruction", 16),
    "integer_throughput": ("throughput", "instruction", 16),
    "integer_same_vd": ("same_vd", "instruction", 16),
    "conversion_dependency": ("dependency", "instruction", 16),
    "conversion_throughput": ("throughput", "instruction", 16),
    "conversion_same_vd": ("same_vd", "instruction", 16),
    "conversion_integer": ("contention", "instruction", 16),
    "fma_integer": ("contention", "instruction", 16),
    "conversion_fma_integer": ("contention", "instruction", 16),
    "reduction_sum_dependency": ("dependency", "instruction", 16),
    "reduction_sum_throughput": ("throughput", "instruction", 16),
    "reduction_max_dependency": ("dependency", "instruction", 16),
    "reduction_max_throughput": ("throughput", "instruction", 16),
    "fma_scalar_dependency": ("dependency", "instruction", 16),
    "fma_scalar_throughput": ("throughput", "instruction", 16),
    "fp_broadcast_throughput": ("throughput", "instruction", 16),
    "integer_scalar_throughput": ("throughput", "instruction", 16),
    "immediate_broadcast_throughput": ("throughput", "instruction", 16),
    "load_throughput": ("memory", "load", 16),
    "load_stream_throughput": ("memory_stream", "load", 16),
    "load_same_vd": ("memory_dependency", "load", 16),
    "load_use": ("memory", "load_use_pair", 8),
    "load_alu_dependency": ("memory_dependency", "load_alu_pair", 8),
    "load_fma_dependency": ("memory_dependency", "load_fma_pair", 8),
    "store_throughput": ("memory", "store", 16),
    "store_stream_throughput": ("memory_stream", "store", 16),
    "load_fma_iteration": ("iteration", "iteration", 1),
    "load_fma_store_iteration": ("iteration", "iteration", 1),
    "vset_rd_dependency": ("dependency", "instruction", 16),
}
EXPECTED_PARAMETERS = tuple(EXPECTED_PARAMETER_SPECS)


def parse_fields(line: str) -> dict[str, str]:
    return dict(field.split("=", 1) for field in line.split()[1:] if "=" in field)


def parse_log(text: str) -> tuple[dict[str, str], list[dict[str, str]], dict[str, str]]:
    metadata: dict[str, str] = {}
    samples: list[dict[str, str]] = []
    done: dict[str, str] = {}
    for line in text.splitlines():
        marker = line.find("XSAI_")
        if marker < 0:
            continue
        record = line[marker:].strip()
        if record.startswith("XSAI_META "):
            metadata = parse_fields(record)
        elif record.startswith("XSAI_RESULT "):
            samples.append(parse_fields(record))
        elif record.startswith("XSAI_DONE "):
            done = parse_fields(record)
    return metadata, samples, done


def parse_parameter_samples(text: str) -> list[dict[str, str]]:
    samples: list[dict[str, str]] = []
    for line in text.splitlines():
        marker = line.find("XSAI_PARAM ")
        if marker >= 0:
            samples.append(parse_fields(line[marker:].strip()))
    return samples


def parse_hpm_samples(text: str) -> list[dict[str, str]]:
    samples: list[dict[str, str]] = []
    for line in text.splitlines():
        marker = line.find("XSAI_HPM ")
        if marker >= 0:
            samples.append(parse_fields(line[marker:].strip()))
    return samples


def validate_hpm_samples(
    metadata: dict[str, str], samples: list[dict[str, str]]
) -> None:
    if metadata.get("hpm_audit") != "1":
        raise ValueError("missing HPM audit metadata")
    samples_per_case = int(metadata["samples"])
    parameter_iterations = int(metadata["param_iterations"])
    expected = {
        (kernel, count, sample)
        for kernel in EXPECTED_KERNELS
        for count in EXPECTED_COUNTS
        for sample in range(samples_per_case)
    }
    expected.update(
        (name, parameter_iterations, sample)
        for name in EXPECTED_PARAMETERS
        for sample in range(samples_per_case)
    )
    actual = {
        (sample["scope"], int(sample["n"]), int(sample["sample"]))
        for sample in samples
    }
    if actual != expected or len(samples) != len(expected):
        missing = sorted(expected - actual)
        extra = sorted(actual - expected)
        raise ValueError(f"incomplete HPM matrix: missing={missing}, extra={extra}")
    active = [
        f"{sample['scope']}:n={sample['n']}:sample={sample['sample']}"
        for sample in samples
        if sample.get("cute_status") != "PASS"
        or int(sample["cute_active_cycles"]) != 0
        or int(sample["cute_retired"]) != 0
        or int(sample["cute_memory_requests"]) != 0
    ]
    if active:
        raise ValueError("CUTE activity in timed region: " + ", ".join(active))


def hpm_index(samples: list[dict[str, str]]) -> dict[tuple[str, int, int], dict[str, str]]:
    return {
        (sample["scope"], int(sample["n"]), int(sample["sample"])): sample
        for sample in samples
    }


def validate_parameter_samples(
    metadata: dict[str, str], samples: list[dict[str, str]]
) -> None:
    if "param_cases" not in metadata:
        if samples:
            raise ValueError("XSAI_PARAM records require param_cases metadata")
        return
    if int(metadata["param_cases"]) != len(EXPECTED_PARAMETERS):
        raise ValueError("profile microbenchmark count disagrees with parser contract")
    samples_per_case = int(metadata["samples"])
    expected = {
        (name, sample)
        for name in EXPECTED_PARAMETERS
        for sample in range(samples_per_case)
    }
    actual = {(sample["name"], int(sample["sample"])) for sample in samples}
    if actual != expected or len(samples) != len(expected):
        missing = sorted(expected - actual)
        extra = sorted(actual - expected)
        raise ValueError(
            f"incomplete profile microbenchmark matrix: missing={missing}, extra={extra}"
        )
    failed = [sample["name"] for sample in samples if sample.get("status") != "PASS"]
    if failed:
        raise ValueError("profile microbenchmark failures: " + ", ".join(failed))
    malformed = []
    iterations = int(metadata["param_iterations"])
    for sample in samples:
        category, unit, operations_per_iteration = EXPECTED_PARAMETER_SPECS[
            sample["name"]
        ]
        expected_operations = iterations * operations_per_iteration
        if (
            sample.get("category") != category
            or sample.get("unit") != unit
            or int(sample["iterations"]) != iterations
            or int(sample["operations"]) != expected_operations
        ):
            malformed.append(sample["name"])
    if malformed:
        raise ValueError(
            "invalid profile microbenchmark normalization: "
            + ", ".join(sorted(set(malformed)))
        )


def validate(
    metadata: dict[str, str], samples: list[dict[str, str]], done: dict[str, str]
) -> None:
    if metadata.get("format") != "2":
        raise ValueError("missing or unsupported XSAI_META format")
    if done.get("status") != "PASS":
        raise ValueError("missing successful XSAI_DONE marker")
    samples_per_case = int(metadata["samples"])
    expected_keys = {
        (kernel, count, sample)
        for kernel in EXPECTED_KERNELS
        for count in EXPECTED_COUNTS
        for sample in range(samples_per_case)
    }
    actual_keys = {
        (sample["kernel"], int(sample["n"]), int(sample["sample"]))
        for sample in samples
    }
    if actual_keys != expected_keys or len(samples) != len(expected_keys):
        missing = sorted(expected_keys - actual_keys)
        extra = sorted(actual_keys - expected_keys)
        raise ValueError(f"incomplete result matrix: missing={missing}, extra={extra}")
    failed = [
        f"{sample['kernel']}:n={sample['n']}:sample={sample['sample']}"
        for sample in samples
        if sample.get("status") != "PASS"
    ]
    if failed:
        raise ValueError(f"functional failures: {', '.join(failed)}")


def write_results(
    metadata: dict[str, str],
    samples: list[dict[str, str]],
    done: dict[str, str],
    hpm_samples: list[dict[str, str]],
    source: str,
    output_dir: Path,
) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    hpm = hpm_index(hpm_samples)
    normalized = []
    for sample in samples:
        audit = hpm[(sample["kernel"], int(sample["n"]), int(sample["sample"]))]
        normalized.append(
            {
                "source": source,
                "kernel": sample["kernel"],
                "n": int(sample["n"]),
                "sample": int(sample["sample"]),
                "raw_cycles": int(sample["raw_cycles"]),
                "empty_cycles": int(sample["empty_cycles"]),
                "cycles": int(sample["cycles"]),
                "checksum": sample["checksum"],
                "max_error_ppb": int(sample["max_error_ppb"]),
                "cute_active_cycles": int(audit["cute_active_cycles"]),
                "cute_retired": int(audit["cute_retired"]),
                "cute_memory_requests": int(audit["cute_memory_requests"]),
                "l1d_load_misses": int(audit["l1d_load_misses"]),
                "dtlb_load_misses": int(audit["dtlb_load_misses"]),
                "cache_status": audit["cache_status"],
                "status": sample["status"],
            }
        )
    normalized.sort(key=lambda row: (row["kernel"], row["n"], row["sample"]))
    with (output_dir / "samples.csv").open("w", newline="", encoding="utf-8") as file:
        writer = csv.DictWriter(file, fieldnames=normalized[0].keys())
        writer.writeheader()
        writer.writerows(normalized)

    grouped: dict[tuple[str, int], list[dict[str, object]]] = defaultdict(list)
    for row in normalized:
        grouped[(str(row["kernel"]), int(row["n"]))].append(row)
    summary = []
    for (kernel, count), rows in sorted(grouped.items()):
        all_cycles = [int(row["cycles"]) for row in rows]
        cycles = [
            int(row["cycles"])
            for row in rows
            if row["cache_status"] == "CLEAN"
        ]
        selected_cycles = cycles or all_cycles
        median_cycles = int(statistics.median(selected_cycles))
        summary.append(
            {
                "source": source,
                "kernel": kernel,
                "n": count,
                "samples": len(rows),
                "clean_samples": len(cycles),
                "excluded_samples": len(rows) - len(cycles),
                "median_cycles": median_cycles,
                "min_cycles": min(selected_cycles),
                "max_cycles": max(selected_cycles),
                "cycles_per_element": f"{median_cycles / count:.6f}",
                "cache_status": "CLEAN" if cycles else "CONTAMINATED",
                "fit_status": "VALID" if cycles else "CACHE_CONTAMINATED",
            }
        )
    with (output_dir / "summary.csv").open("w", newline="", encoding="utf-8") as file:
        writer = csv.DictWriter(file, fieldnames=summary[0].keys())
        writer.writeheader()
        writer.writerows(summary)

    (output_dir / "result_metadata.json").write_text(
        json.dumps(
            {"source": source, "metadata": metadata, "done": done}, indent=2
        )
        + "\n",
        encoding="utf-8",
    )


def write_parameter_results(
    samples: list[dict[str, str]],
    hpm_samples: list[dict[str, str]],
    source: str,
    output_dir: Path,
) -> None:
    if not samples:
        return
    hpm = hpm_index(hpm_samples)
    normalized = []
    for sample in samples:
        operations = int(sample["operations"])
        cycles = int(sample["cycles"])
        audit = hpm[
            (sample["name"], int(sample["iterations"]), int(sample["sample"]))
        ]
        normalized.append(
            {
                "source": source,
                "name": sample["name"],
                "category": sample["category"],
                "unit": sample["unit"],
                "sample": int(sample["sample"]),
                "iterations": int(sample["iterations"]),
                "operations": operations,
                "raw_cycles": int(sample["raw_cycles"]),
                "empty_cycles": int(sample["empty_cycles"]),
                "cycles": cycles,
                "cycles_per_operation": f"{cycles / operations:.6f}",
                "cute_active_cycles": int(audit["cute_active_cycles"]),
                "cute_retired": int(audit["cute_retired"]),
                "cute_memory_requests": int(audit["cute_memory_requests"]),
                "l1d_load_misses": int(audit["l1d_load_misses"]),
                "dtlb_load_misses": int(audit["dtlb_load_misses"]),
                "cache_status": audit["cache_status"],
                "status": sample["status"],
            }
        )
    normalized.sort(key=lambda row: (str(row["name"]), int(row["sample"])))
    with (output_dir / "profile_samples.csv").open(
        "w", newline="", encoding="utf-8"
    ) as file:
        writer = csv.DictWriter(file, fieldnames=normalized[0].keys())
        writer.writeheader()
        writer.writerows(normalized)

    grouped: dict[str, list[dict[str, object]]] = defaultdict(list)
    for row in normalized:
        grouped[str(row["name"])].append(row)
    summary = []
    for name, rows in sorted(grouped.items()):
        all_cycles = [int(row["cycles"]) for row in rows]
        cycles = [
            int(row["cycles"])
            for row in rows
            if row["cache_status"] == "CLEAN"
        ]
        operations = int(rows[0]["operations"])
        selected_cycles = cycles or all_cycles
        median_cycles = statistics.median(selected_cycles)
        summary.append(
            {
                "source": source,
                "name": name,
                "category": rows[0]["category"],
                "unit": rows[0]["unit"],
                "samples": len(rows),
                "clean_samples": len(cycles),
                "excluded_samples": len(rows) - len(cycles),
                "operations": operations,
                "median_cycles": int(median_cycles),
                "min_cycles": min(selected_cycles),
                "max_cycles": max(selected_cycles),
                "cycles_per_operation": f"{median_cycles / operations:.6f}",
                "operations_per_cycle": f"{operations / median_cycles:.6f}",
                "cache_status": "CLEAN" if cycles else "CONTAMINATED",
                "fit_status": "VALID" if cycles else "CACHE_CONTAMINATED",
            }
        )
    with (output_dir / "profile_summary.csv").open(
        "w", newline="", encoding="utf-8"
    ) as file:
        writer = csv.DictWriter(file, fieldnames=summary[0].keys())
        writer.writeheader()
        writer.writerows(summary)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--log", required=True, type=Path)
    parser.add_argument("--source", required=True, choices=("nemu", "rtl"))
    parser.add_argument("--output-dir", required=True, type=Path)
    args = parser.parse_args()

    text = args.log.read_text(encoding="utf-8")
    metadata, samples, done = parse_log(text)
    parameter_samples = parse_parameter_samples(text)
    hpm_samples = parse_hpm_samples(text)
    validate(metadata, samples, done)
    validate_parameter_samples(metadata, parameter_samples)
    validate_hpm_samples(metadata, hpm_samples)
    write_results(metadata, samples, done, hpm_samples, args.source, args.output_dir)
    write_parameter_results(
        parameter_samples, hpm_samples, args.source, args.output_dir
    )
    print(f"Parsed {len(samples)} {args.source} samples with a complete matrix.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
