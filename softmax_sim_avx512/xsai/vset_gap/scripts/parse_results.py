#!/usr/bin/env python3
"""Parse the standalone XSAI vset/VL/VLSU gap microbenchmark log."""

from __future__ import annotations

import argparse
import csv
import json
import statistics
from collections import defaultdict
from pathlib import Path


CASE_SPECS = {
    "regular_lfs": ("rd_rs1", "load_fma_store"),
    "keep_vl_lfs": ("x0_x0", "load_fma_store"),
    "vlmax_lfs": ("rd_x0", "load_fma_store"),
    "outside_lfs": ("outside", "load_fma_store"),
    "regular_load": ("rd_rs1", "load_only"),
    "outside_load": ("outside", "load_only"),
    "load_stream_1": ("rd_rs1", "load_stream"),
    "load_stream_2": ("rd_rs1", "load_stream"),
    "load_stream_4": ("rd_rs1", "load_stream"),
    "aligned_load_stream_2": ("rd_rs1", "load_stream"),
    "aligned_load_stream_4": ("rd_rs1", "load_stream"),
    "regular_compute": ("rd_rs1", "compute_only"),
    "regular_store": ("rd_rs1", "store_only"),
}

PREVIOUS_CASE_SPECS = {
    name: spec for name, spec in CASE_SPECS.items()
    if name not in {"aligned_load_stream_2", "aligned_load_stream_4"}
}
LEGACY_CASE_SPECS = {
    name: spec for name, spec in PREVIOUS_CASE_SPECS.items()
    if name not in {"outside_load", "load_stream_1", "load_stream_2", "load_stream_4"}
}
STREAM_COUNTS = {
    "load_stream_1": 1,
    "load_stream_2": 2,
    "load_stream_4": 4,
    "aligned_load_stream_2": 2,
    "aligned_load_stream_4": 4,
}


def parse_fields(record: str) -> dict[str, str]:
    return dict(field.split("=", 1) for field in record.split()[1:] if "=" in field)


def parse_log(
    text: str,
) -> tuple[
    dict[str, str], list[dict[str, str]], list[dict[str, str]], dict[str, str]
]:
    metadata: dict[str, str] = {}
    samples: list[dict[str, str]] = []
    hpm_samples: list[dict[str, str]] = []
    done: dict[str, str] = {}
    for line in text.splitlines():
        marker = line.find("XSAI_")
        if marker < 0:
            continue
        record = line[marker:].strip()
        if record.startswith("XSAI_VSET_META "):
            metadata = parse_fields(record)
        elif record.startswith("XSAI_VSET_RESULT "):
            samples.append(parse_fields(record))
        elif record.startswith("XSAI_HPM "):
            hpm_samples.append(parse_fields(record))
        elif record.startswith("XSAI_VSET_DONE "):
            done = parse_fields(record)
    return metadata, samples, hpm_samples, done


def validate(
    metadata: dict[str, str],
    samples: list[dict[str, str]],
    hpm_samples: list[dict[str, str]],
    done: dict[str, str],
) -> None:
    if metadata.get("format") != "1":
        raise ValueError("missing or unsupported XSAI_VSET_META format")
    if metadata.get("hpm_audit") != "1":
        raise ValueError("missing HPM audit metadata")
    declared_cases = int(metadata.get("cases", "0"))
    if declared_cases == len(CASE_SPECS):
        case_specs = CASE_SPECS
    elif declared_cases == len(PREVIOUS_CASE_SPECS):
        case_specs = PREVIOUS_CASE_SPECS
    elif declared_cases == len(LEGACY_CASE_SPECS):
        case_specs = LEGACY_CASE_SPECS
    else:
        raise ValueError("case count disagrees with vset-gap parser contract")
    if done.get("status") != "PASS":
        raise ValueError("missing successful XSAI_VSET_DONE marker")

    sample_count = int(metadata["samples"])
    iterations = int(metadata["iterations"])
    expected = {
        (name, sample) for name in case_specs for sample in range(sample_count)
    }
    actual = {(sample["name"], int(sample["sample"])) for sample in samples}
    if actual != expected or len(samples) != len(expected):
        raise ValueError(
            f"incomplete vset-gap matrix: missing={sorted(expected - actual)}, "
            f"extra={sorted(actual - expected)}"
        )
    hpm_actual = {
        (sample["scope"], int(sample["sample"])) for sample in hpm_samples
    }
    if hpm_actual != expected or len(hpm_samples) != len(expected):
        raise ValueError("incomplete vset-gap HPM matrix")

    malformed = []
    failed = []
    for sample in samples:
        if sample["name"] not in case_specs:
            malformed.append(sample["name"])
            continue
        form, consumer = case_specs[sample["name"]]
        if (
            sample.get("form") != form
            or sample.get("consumer") != consumer
            or int(sample["iterations"]) != iterations
        ):
            malformed.append(sample["name"])
        if sample.get("status") != "PASS":
            failed.append(sample["name"])
    if malformed:
        raise ValueError("invalid vset-gap case contract: " + ", ".join(malformed))

    for sample in hpm_samples:
        if (
            int(sample.get("n", "-1")) != iterations
            or sample.get("cute_status") != "PASS"
            or int(sample["cute_active_cycles"]) != 0
            or int(sample["cute_retired"]) != 0
            or int(sample["cute_memory_requests"]) != 0
        ):
            failed.append(sample["scope"])
    if failed:
        raise ValueError("vset-gap functional/HPM failures: " + ", ".join(failed))


def write_results(
    metadata: dict[str, str],
    samples: list[dict[str, str]],
    hpm_samples: list[dict[str, str]],
    done: dict[str, str],
    source: str,
    output_dir: Path,
) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    hpm = {
        (sample["scope"], int(sample["sample"])): sample
        for sample in hpm_samples
    }
    rows = []
    for sample in samples:
        audit = hpm[(sample["name"], int(sample["sample"]))]
        cycles = int(sample["cycles"])
        iterations = int(sample["iterations"])
        rows.append(
            {
                "source": source,
                "name": sample["name"],
                "form": sample["form"],
                "consumer": sample["consumer"],
                "streams": int(sample.get("streams", STREAM_COUNTS.get(sample["name"], 1))),
                "sample": int(sample["sample"]),
                "iterations": iterations,
                "raw_cycles": int(sample["raw_cycles"]),
                "empty_cycles": int(sample["empty_cycles"]),
                "cycles": cycles,
                "cycles_per_iteration": f"{cycles / iterations:.6f}",
                "checksum": sample["checksum"],
                "cute_active_cycles": int(audit["cute_active_cycles"]),
                "cute_retired": int(audit["cute_retired"]),
                "cute_memory_requests": int(audit["cute_memory_requests"]),
                "l1d_load_misses": int(audit["l1d_load_misses"]),
                "dtlb_load_misses": int(audit["dtlb_load_misses"]),
                "cache_status": audit["cache_status"],
                "status": sample["status"],
            }
        )
    rows.sort(key=lambda row: (str(row["name"]), int(row["sample"])))
    with (output_dir / "samples.csv").open("w", newline="", encoding="utf-8") as file:
        writer = csv.DictWriter(file, fieldnames=rows[0].keys())
        writer.writeheader()
        writer.writerows(rows)

    grouped: dict[str, list[dict[str, object]]] = defaultdict(list)
    for row in rows:
        grouped[str(row["name"])].append(row)
    summary = []
    for name, case_rows in sorted(grouped.items()):
        clean_cycles = [
            int(row["cycles"])
            for row in case_rows
            if row["cache_status"] == "CLEAN"
        ]
        all_cycles = [int(row["cycles"]) for row in case_rows]
        selected = clean_cycles or all_cycles
        median_cycles = statistics.median(selected)
        iterations = int(case_rows[0]["iterations"])
        summary.append(
            {
                "source": source,
                "name": name,
                "form": case_rows[0]["form"],
                "consumer": case_rows[0]["consumer"],
                "streams": case_rows[0]["streams"],
                "samples": len(case_rows),
                "clean_samples": len(clean_cycles),
                "excluded_samples": len(case_rows) - len(clean_cycles),
                "iterations": iterations,
                "median_cycles": int(median_cycles),
                "min_cycles": min(selected),
                "max_cycles": max(selected),
                "cycles_per_iteration": f"{median_cycles / iterations:.6f}",
                "cache_status": "CLEAN" if clean_cycles else "CONTAMINATED",
                "fit_status": "VALID" if clean_cycles else "CACHE_CONTAMINATED",
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


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--log", required=True, type=Path)
    parser.add_argument("--source", required=True, choices=("nemu", "rtl"))
    parser.add_argument("--output-dir", required=True, type=Path)
    args = parser.parse_args()

    metadata, samples, hpm_samples, done = parse_log(
        args.log.read_text(encoding="utf-8")
    )
    validate(metadata, samples, hpm_samples, done)
    write_results(
        metadata, samples, hpm_samples, done, args.source, args.output_dir
    )
    print(f"Parsed {len(samples)} standalone vset-gap {args.source} samples.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
