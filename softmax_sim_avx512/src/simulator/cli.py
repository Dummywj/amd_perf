#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from src.frontends.common import write_json
from src.frontends.x86 import build_dynamic_trace
from src.simulator.engine import SimulatorError, simulate
from src.simulator.export import (
    write_dot,
    write_events_jsonl,
    write_perfetto,
    write_result,
    write_timeline,
)
from src.simulator.profile import ProfileError, load_profile


def main() -> int:
    parser = argparse.ArgumentParser(description="Generic-uop softmax cycle simulator")
    parser.add_argument("--isa", choices=("x86",), default="x86")
    parser.add_argument("--assembly", type=Path, required=True)
    parser.add_argument("--function", default="softmax_avx512_f32")
    parser.add_argument("--recipe", type=Path, required=True)
    parser.add_argument("--uop-kinds", type=Path)
    parser.add_argument("--profile", type=Path, required=True)
    parser.add_argument("--schema", type=Path, required=True)
    parser.add_argument("--count", type=int, required=True)
    parser.add_argument(
        "--execution-model",
        choices=("out_of_order", "in_order"),
        default="out_of_order",
    )
    parser.add_argument(
        "--cache-mode", choices=("hot-l1", "hot-capacity", "cold"), default="hot-l1"
    )
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--visual-start", type=int, default=0)
    parser.add_argument("--visual-limit", type=int, default=200)
    args = parser.parse_args()
    try:
        dynamic = build_dynamic_trace(
            args.assembly,
            args.function,
            args.recipe,
            args.count,
            args.uop_kinds,
        )
        profile = load_profile(args.profile, args.schema)
        result = simulate(
            profile.bind(dynamic), profile, args.execution_model, args.cache_mode
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
    except (OSError, ValueError, KeyError, ProfileError, SimulatorError) as error:
        print(f"simulator: error: {error}", file=sys.stderr)
        return 2
    print(json.dumps({"cycles": result.cycles, **result.summary}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
