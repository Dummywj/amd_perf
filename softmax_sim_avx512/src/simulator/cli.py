#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

import yaml

from src.frontends.common import write_json
from src.frontends.rvv import build_dynamic_trace as build_rvv_dynamic_trace
from src.frontends.x86 import build_dynamic_trace as build_x86_dynamic_trace
from src.simulator.engine import SimulatorError, simulate
from src.simulator.export import (
    write_dot,
    write_events_jsonl,
    write_perfetto,
    write_result,
    write_semantic_html,
    write_timeline,
)
from src.simulator.profile import ProfileError, load_profile


def _resolve_function(isa: str, function: str | None) -> str:
    if function:
        return function
    if isa == "x86":
        return "softmax_avx512_f32"
    raise ValueError("--function is required when --isa=rvv")


def _resolve_rvv_vlen(profile_data: dict[str, Any], override: int | None) -> int:
    isa = profile_data.get("isa", {})
    value = override if override is not None else isa.get("vector_length_bits")
    source = "--vlen-bits" if override is not None else "profile isa.vector_length_bits"
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError(
            "RVV VLEN is unavailable: set integer profile isa.vector_length_bits "
            "or pass --vlen-bits"
        )
    if value <= 0 or value % 8:
        raise ValueError(f"{source} must be a positive multiple of 8 bits")

    max_vector_bits = isa.get("max_vector_bits")
    if isinstance(max_vector_bits, int) and value > max_vector_bits:
        raise ValueError(
            f"{source} ({value}) exceeds profile isa.max_vector_bits "
            f"({max_vector_bits})"
        )
    max_element_bits = isa.get("max_element_bits")
    if isinstance(max_element_bits, int) and value < max_element_bits:
        raise ValueError(
            f"{source} ({value}) is smaller than profile isa.max_element_bits "
            f"({max_element_bits})"
        )
    return value


def _build_dynamic_trace(
    args: argparse.Namespace, profile_data: dict[str, Any]
) -> dict[str, Any]:
    function = _resolve_function(args.isa, args.function)
    if args.isa == "x86":
        if args.vlen_bits is not None:
            raise ValueError("--vlen-bits is only valid when --isa=rvv")
        return build_x86_dynamic_trace(
            args.assembly,
            function,
            args.recipe,
            args.count,
            args.uop_kinds,
        )

    vlen_bits = _resolve_rvv_vlen(profile_data, args.vlen_bits)
    return build_rvv_dynamic_trace(
        args.assembly,
        function,
        args.recipe,
        args.count,
        args.uop_kinds,
        vlen_bits=vlen_bits,
    )


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Semantic-uop x86/RVV kernel cycle simulator"
    )
    parser.add_argument("--isa", choices=("x86", "rvv"), default="x86")
    parser.add_argument("--assembly", type=Path, required=True)
    parser.add_argument(
        "--function",
        help="assembly function (defaults to softmax_avx512_f32 for x86)",
    )
    parser.add_argument("--recipe", type=Path, required=True)
    parser.add_argument("--uop-kinds", type=Path)
    parser.add_argument("--profile", type=Path, required=True)
    parser.add_argument("--schema", type=Path, required=True)
    parser.add_argument("--count", type=int, required=True)
    parser.add_argument(
        "--vlen-bits",
        type=int,
        help="RVV VLEN override (defaults to profile isa.vector_length_bits)",
    )
    parser.add_argument(
        "--execution-model",
        choices=("out_of_order", "in_order"),
        default="out_of_order",
    )
    parser.add_argument(
        "--cache-mode", choices=("hot-l1", "hot-capacity", "cold"), default="hot-l1"
    )
    overlap = parser.add_mutually_exclusive_group()
    overlap.add_argument(
        "--memory-compute-overlap-limit",
        dest="memory_compute_overlap_limit",
        action="store_true",
        help="enable the profile's pending load-to-compute group limit",
    )
    overlap.add_argument(
        "--no-memory-compute-overlap-limit",
        dest="memory_compute_overlap_limit",
        action="store_false",
        help="disable the profile's pending load-to-compute group limit",
    )
    parser.set_defaults(memory_compute_overlap_limit=None)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--visual-start", type=int, default=0)
    parser.add_argument("--visual-limit", type=int, default=200)
    args = parser.parse_args()
    try:
        profile = load_profile(args.profile, args.schema)
        dynamic = _build_dynamic_trace(args, profile.data)
        result = simulate(
            profile.bind(dynamic),
            profile,
            args.execution_model,
            args.cache_mode,
            args.memory_compute_overlap_limit,
        )
        args.output_dir.mkdir(parents=True, exist_ok=True)
        write_json(args.output_dir / "dynamic_trace.json", dynamic)
        write_result(args.output_dir / "result.json", result)
        write_events_jsonl(args.output_dir / "schedule_events.jsonl", result)
        write_perfetto(
            args.output_dir / "schedule_perfetto.json",
            result,
            args.visual_start,
            args.visual_limit,
        )
        write_dot(
            args.output_dir / "dependencies.dot",
            result,
            args.visual_start,
            args.visual_limit,
        )
        write_timeline(
            args.output_dir / "timeline.txt",
            result,
            args.visual_start,
            min(args.visual_limit, 80),
        )
        write_semantic_html(args.output_dir / "semantic_schedule.html", result)
    except (
        OSError,
        ValueError,
        KeyError,
        yaml.YAMLError,
        ProfileError,
        SimulatorError,
    ) as error:
        print(f"simulator: error: {error}", file=sys.stderr)
        return 2
    print(json.dumps({"cycles": result.cycles, **result.summary}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
