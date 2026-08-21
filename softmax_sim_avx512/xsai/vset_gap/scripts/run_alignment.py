#!/usr/bin/env python3
"""Compare XSAI vset-gap RTL cases with the selected simulator backend."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import sys
from pathlib import Path
from typing import Any


SCRIPT = Path(__file__).resolve()
PROJECT_ROOT = SCRIPT.parents[3]

CASE_SPECS = (
    ("regular_lfs", "xsai_vg_regular_lfs", 65, (3, 1, 1), 2080),
    ("keep_vl_lfs", "xsai_vg_keep_vl_lfs", 65, (3, 1, 1), 2080),
    ("vlmax_lfs", "xsai_vg_vlmax_lfs", 65, (3, 1, 1), 2080),
    ("outside_lfs", "xsai_vg_outside_lfs", 1, (3, 1, 1), 2080),
    ("regular_load", "xsai_vg_regular_load", 65, (1, 0, 1), 1040),
    ("outside_load", "xsai_vg_outside_load", 1, (1, 0, 1), 1040),
    ("load_stream_1", "xsai_vg_load_stream_1", 65, (1, 0, 1), 1040),
    ("load_stream_2", "xsai_vg_load_stream_2", 65, (2, 0, 2), 2080),
    ("load_stream_4", "xsai_vg_load_stream_4", 65, (4, 0, 4), 4160),
    ("aligned_load_stream_2", "xsai_vg_aligned_load_stream_2", 65, (2, 0, 2), 2080),
    ("aligned_load_stream_4", "xsai_vg_aligned_load_stream_4", 65, (4, 0, 4), 4160),
    ("regular_compute", "xsai_vg_regular_compute", 65, (3, 1, 1), 64),
    ("regular_store", "xsai_vg_regular_store", 65, (1, 0, 1), 1040),
)

EXPECTED_FORMS = {
    "regular_lfs": (("t0", "zero"), ("t0", "a4")),
    "keep_vl_lfs": (("t0", "zero"), ("zero", "zero")),
    "vlmax_lfs": (("t0", "zero"), ("t0", "zero")),
    "outside_lfs": (("t0", "zero"),),
    "regular_load": (("t0", "zero"), ("t0", "a4")),
    "outside_load": (("t0", "zero"),),
    "load_stream_1": (("t0", "zero"), ("t0", "a4")),
    "load_stream_2": (("t0", "zero"), ("t0", "a5")),
    "load_stream_4": (("t0", "zero"), ("t0", "t2")),
    "aligned_load_stream_2": (("t0", "zero"), ("t0", "a5")),
    "aligned_load_stream_4": (("t0", "zero"), ("t0", "t2")),
    "regular_compute": (("t0", "zero"), ("t0", "a4")),
    "regular_store": (("t0", "zero"), ("t0", "a4")),
}


class AlignmentError(ValueError):
    pass


def file_sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def read_rtl_summary(path: Path) -> dict[str, dict[str, str]]:
    if not path.is_file():
        raise AlignmentError(f"RTL summary does not exist: {path}")
    with path.open(newline="", encoding="utf-8") as source:
        reader = csv.DictReader(source)
        required = {
            "source",
            "name",
            "iterations",
            "median_cycles",
            "cycles_per_iteration",
            "cache_status",
            "fit_status",
        }
        if reader.fieldnames is None or not required.issubset(reader.fieldnames):
            missing = required - set(reader.fieldnames or ())
            raise AlignmentError(
                "RTL summary is missing fields: " + ", ".join(sorted(missing))
            )
        rows = list(reader)

    indexed: dict[str, dict[str, str]] = {}
    for row in rows:
        name = row["name"].strip()
        if name in indexed:
            raise AlignmentError(f"duplicate RTL case: {name}")
        if row["source"].strip().lower() != "rtl":
            raise AlignmentError(f"non-RTL summary row: {name}")
        if int(row["iterations"]) != 64:
            raise AlignmentError(f"{name} does not use 64 iterations")
        if row["cache_status"].strip().upper() != "CLEAN":
            raise AlignmentError(f"{name} is not cache-clean")
        if row["fit_status"].strip().upper() != "VALID":
            raise AlignmentError(f"{name} is not fit-eligible")
        indexed[name] = row
    expected = {spec[0] for spec in CASE_SPECS}
    if set(indexed) != expected:
        raise AlignmentError(
            f"RTL cases disagree: missing={sorted(expected - set(indexed))}, "
            f"extra={sorted(set(indexed) - expected)}"
        )
    return indexed


def audit_fixture(path: Path) -> None:
    if str(PROJECT_ROOT) not in sys.path:
        sys.path.insert(0, str(PROJECT_ROOT))
    from src.frontends.rvv import parse_function

    for name, function, _, vector_counts, _ in CASE_SPECS:
        instructions, _ = parse_function(path, function)
        forms = tuple(
            (instruction.operands[0], instruction.operands[1])
            for instruction in instructions
            if instruction.mnemonic == "vsetvli"
        )
        actual_vector_counts = (
            sum(item.mnemonic == "vle32.v" for item in instructions),
            sum(item.mnemonic == "vfmacc.vv" for item in instructions),
            sum(item.mnemonic == "vse32.v" for item in instructions),
        )
        if forms != EXPECTED_FORMS[name]:
            raise AlignmentError(f"fixture vset forms disagree for {name}: {forms}")
        if actual_vector_counts != vector_counts:
            raise AlignmentError(
                f"fixture vector instruction counts disagree for {name}: "
                f"{actual_vector_counts}"
            )


def simulate_cases(
    rtl: dict[str, dict[str, str]],
    fixture: Path,
    profile_path: Path,
    schema_path: Path,
    recipe_path: Path,
    uop_kinds_path: Path,
) -> list[dict[str, Any]]:
    if str(PROJECT_ROOT) not in sys.path:
        sys.path.insert(0, str(PROJECT_ROOT))
    from src.frontends.rvv import build_dynamic_trace
    from src.simulator.engine import simulate
    from src.simulator.profile import load_profile

    audit_fixture(fixture)
    profile = load_profile(profile_path, schema_path)
    vlen_bits = profile.data["isa"].get("vector_length_bits")
    if vlen_bits != 128:
        raise AlignmentError(f"vset-gap requires profile VLEN=128, got {vlen_bits!r}")

    rows: list[dict[str, Any]] = []
    for name, function, expected_vsets, _, expected_bytes in CASE_SPECS:
        trace = build_dynamic_trace(
            fixture,
            function,
            recipe_path,
            64,
            uop_kinds_path,
            vlen_bits=vlen_bits,
        )
        vector_states = [
            instruction["vector_state"]
            for instruction in trace["instructions"]
            if instruction["mnemonic"].startswith("v")
        ]
        vsets = sum(
            instruction["mnemonic"] == "vsetvli"
            for instruction in trace["instructions"]
        )
        if vsets != expected_vsets or any(state["vl"] != 4 for state in vector_states):
            raise AlignmentError(f"dynamic VL/vset expansion disagrees for {name}")
        if trace["statistics"]["input_output_total_bytes"] != expected_bytes:
            raise AlignmentError(f"dynamic memory volume disagrees for {name}")

        result = simulate(profile.bind(trace), profile, "out_of_order", "hot-l1", None)
        rtl_cycles = int(rtl[name]["median_cycles"])
        simulator_cycles = int(result.cycles)
        relative_error = (simulator_cycles - rtl_cycles) / rtl_cycles * 100.0
        rows.append(
            {
                "name": name,
                "iterations": 64,
                "rtl_cycles": rtl_cycles,
                "rtl_cycles_per_iteration": float(
                    rtl[name]["cycles_per_iteration"]
                ),
                "simulator_cycles": simulator_cycles,
                "simulator_cycles_per_iteration": simulator_cycles / 64.0,
                "signed_error_cycles": simulator_cycles - rtl_cycles,
                "relative_error_percent": relative_error,
                "absolute_relative_error_percent": abs(relative_error),
                "dynamic_instruction_count": trace["statistics"][
                    "dynamic_instruction_count"
                ],
                "semantic_uop_count": trace["statistics"]["semantic_uop_count"],
                "input_output_total_bytes": trace["statistics"][
                    "input_output_total_bytes"
                ],
            }
        )
    return rows


def write_outputs(
    rows: list[dict[str, Any]],
    output_dir: Path,
    fixture: Path,
    profile: Path,
    rtl_summary: Path,
) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    with (output_dir / "alignment.csv").open("w", newline="", encoding="utf-8") as target:
        writer = csv.DictWriter(target, fieldnames=rows[0].keys())
        writer.writeheader()
        writer.writerows(rows)

    mape = sum(row["absolute_relative_error_percent"] for row in rows) / len(rows)
    payload = {
        "format_version": 1,
        "execution": {
            "model": "out_of_order",
            "cache_mode": "hot-l1",
            "iterations": 64,
            "vlen_bits": 128,
        },
        "inputs": {
            "fixture": str(fixture),
            "fixture_sha256": file_sha256(fixture),
            "profile": str(profile),
            "profile_sha256": file_sha256(profile),
            "rtl_summary": str(rtl_summary),
            "rtl_summary_sha256": file_sha256(rtl_summary),
        },
        "summary": {
            "cases": len(rows),
            "mape_percent": mape,
            "max_absolute_relative_error_percent": max(
                row["absolute_relative_error_percent"] for row in rows
            ),
        },
        "cases": rows,
    }
    (output_dir / "alignment.json").write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--rtl-summary",
        type=Path,
        default=PROJECT_ROOT / "artifacts/xsai/vset_gap/rtl/summary.csv",
    )
    parser.add_argument(
        "--fixture",
        type=Path,
        default=PROJECT_ROOT / "xsai/vset_gap/fixtures/vset_gap_expanded.s",
    )
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
        default=PROJECT_ROOT / "artifacts/xsai/vset_gap/alignment",
    )
    args = parser.parse_args(argv)
    try:
        rtl = read_rtl_summary(args.rtl_summary)
        rows = simulate_cases(
            rtl,
            args.fixture,
            args.profile,
            args.schema,
            args.recipe,
            args.uop_kinds,
        )
        write_outputs(rows, args.output_dir, args.fixture, args.profile, args.rtl_summary)
    except (OSError, KeyError, ValueError) as error:
        print(f"vset-gap alignment: error: {error}", file=sys.stderr)
        return 2
    mape = sum(row["absolute_relative_error_percent"] for row in rows) / len(rows)
    if not math.isfinite(mape):
        print("vset-gap alignment: error: non-finite MAPE", file=sys.stderr)
        return 2
    print(f"Aligned {len(rows)} vset-gap cases; MAPE={mape:.2f}% -> {args.output_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
