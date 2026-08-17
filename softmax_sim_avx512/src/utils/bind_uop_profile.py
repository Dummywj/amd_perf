#!/usr/bin/env python3
"""Attach profile resource metadata to a generic assembly uop trace.

This is intentionally a resource-only binding pass. Opcode-specific timing is
attached only when the profile has an explicit recipe; missing timing remains
visible instead of being filled with a default.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path
from typing import Any

try:
    import yaml
except ModuleNotFoundError as error:  # pragma: no cover - environment guard
    raise SystemExit("PyYAML is required for profile binding") from error


CLASS_TO_RESOURCE = {
    "vector_fp": "vector-fp",
    "vector_integer": "vector-integer",
    "conversion": "conversion",
    "shuffle": "shuffle",
    "address_generation": "address-generation",
    "load_data": "load-data",
    "store_data": "store-data",
}


def operand_class(operand: str) -> str:
    token = operand.lower()
    for register_class in ("zmm", "ymm", "xmm"):
        if f"%{register_class}" in token:
            return register_class
    if "(" in token or "[" in token:
        return "memory"
    if token.startswith("$"):
        return "immediate"
    if "%" in token:
        return "register"
    return "other"


def instruction_recipe_key(
    instruction: dict[str, Any], recipes: dict[str, Any]
) -> str | None:
    mnemonic = str(instruction.get("mnemonic", "")).lower()
    operands = instruction.get("operands", [])
    if not isinstance(operands, list):
        return None
    key = f"{mnemonic}:{','.join(operand_class(str(operand)) for operand in operands)}"
    if key in recipes:
        return key
    return None


def load_yaml(path: Path) -> dict[str, Any]:
    with path.open(encoding="utf-8") as stream:
        value = yaml.safe_load(stream)
    if not isinstance(value, dict):
        raise ValueError(f"{path}: expected a mapping")
    return value


def bind_trace(trace: dict[str, Any], profile: dict[str, Any]) -> dict[str, Any]:
    resources = profile.get("resources", {})
    if not isinstance(resources, dict):
        raise ValueError("profile.resources must be a mapping")
    profile_recipes = profile.get("recipes", {})
    if not isinstance(profile_recipes, dict):
        raise ValueError("profile.recipes must be a mapping")
    instructions = trace.get("instructions", [])
    if not isinstance(instructions, list):
        raise ValueError("trace.instructions must be a list")
    timed_lines: dict[int, str] = {}
    bound_instructions: list[dict[str, Any]] = []
    for instruction in instructions:
        if not isinstance(instruction, dict):
            raise ValueError("trace.instructions must contain mappings")
        key = instruction_recipe_key(instruction, profile_recipes)
        if key is not None:
            timed_lines[int(instruction["source_line"])] = key
        bound_instruction = dict(instruction)
        if key is not None:
            bound_instruction["profile_opcode_recipe"] = {
                "key": key,
                "recipe": profile_recipes[key],
            }
        bound_instructions.append(bound_instruction)
    unbound_classes: set[str] = set()
    missing_timing: set[str] = set()
    timed_uops = 0
    bound_uops: list[dict[str, Any]] = []
    for uop in trace.get("uops", []):
        bound = dict(uop)
        execution_class = str(uop["execution_class"])
        resource_id = CLASS_TO_RESOURCE.get(execution_class)
        if resource_id is None or resource_id not in resources:
            bound["resource_binding"] = None
            bound["timing_status"] = "unmodeled_profile_class"
            unbound_classes.add(execution_class)
        else:
            resource = resources[resource_id]
            bound["resource_binding"] = {
                "id": resource_id,
                "kind": resource.get("kind"),
                "capacity": resource.get("capacity"),
                "width_bits": resource.get("width_bits"),
                "bytes_per_cycle": resource.get("bytes_per_cycle"),
            }
            recipe_key = timed_lines.get(int(uop["source_line"]))
            if recipe_key is None:
                bound["timing_status"] = "resource_only"
                missing_timing.add(uop["kind"])
            else:
                bound["timing_status"] = "profile_recipe_present"
                bound["opcode_recipe"] = recipe_key
                timed_uops += 1
        bound_uops.append(bound)

    result = dict(trace)
    result["profile_id"] = profile.get("profile_id")
    result["profile_status"] = profile.get("profile_status")
    result["instructions"] = bound_instructions
    result["uops"] = bound_uops
    result["binding"] = {
        "resource_classes_unbound": sorted(unbound_classes),
        "uop_kinds_without_opcode_timing": sorted(missing_timing),
        "uops_with_profile_opcode_timing": timed_uops,
        "instructions_with_profile_opcode_timing": len(timed_lines),
        "note": "No timing default is synthesized by this pass.",
    }
    return result


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--trace", type=Path, required=True)
    parser.add_argument("--profile", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    try:
        trace = json.loads(args.trace.read_text(encoding="utf-8"))
        profile = load_yaml(args.profile)
        result = bind_trace(trace, profile)
        result["profile_sha256"] = hashlib.sha256(
            args.profile.read_bytes()
        ).hexdigest()
    except (OSError, ValueError, KeyError, json.JSONDecodeError) as error:
        print(f"bind_uop_profile: error: {error}", file=sys.stderr)
        return 2
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    print(f"bound {len(result.get('uops', []))} uops -> {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
