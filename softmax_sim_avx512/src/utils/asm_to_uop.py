#!/usr/bin/env python3
"""Convert one compiler-generated assembly function into a uop trace.

The input is assembly only. The parser deliberately fails on an instruction
that has no exact recipe entry; silently assigning a default uop would hide
compiler changes from the simulator calibration workflow.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from collections import Counter
from pathlib import Path
from typing import Any

try:
    import yaml
except ModuleNotFoundError as error:  # pragma: no cover - environment guard
    raise SystemExit(
        "PyYAML is required; use the project toolchain environment or install it"
    ) from error


INSTRUCTION_RE = re.compile(r"^\s*([A-Za-z][A-Za-z0-9.]*)\s*(.*?)\s*$")
LABEL_RE = re.compile(r"^\s*(?:[.]L[A-Za-z0-9_.]+|[A-Za-z_][A-Za-z0-9_.]*):\s*$")


def load_yaml(path: Path) -> dict[str, Any]:
    with path.open(encoding="utf-8") as stream:
        value = yaml.safe_load(stream)
    if not isinstance(value, dict):
        raise ValueError(f"{path}: top-level YAML value must be a mapping")
    return value


def split_operands(operand_text: str) -> list[str]:
    operands: list[str] = []
    start = 0
    depth = 0
    for index, character in enumerate(operand_text):
        if character in "([":
            depth += 1
        elif character in ")]":
            depth = max(0, depth - 1)
        elif character == "," and depth == 0:
            part = operand_text[start:index].strip()
            if part:
                operands.append(part)
            start = index + 1
    part = operand_text[start:].strip()
    if part:
        operands.append(part)
    return operands


def x86_form(mnemonic: str, operands: list[str]) -> str:
    del mnemonic
    memory = ["(" in operand or "[" in operand for operand in operands]
    if any(memory):
        if memory and memory[-1]:
            return "memory_store"
        return "memory_load"
    return "register"


def recipe_index(recipe: dict[str, Any]) -> dict[tuple[str, str], list[str]]:
    entries = recipe.get("instructions")
    if not isinstance(entries, list):
        raise ValueError("recipe.instructions must be a list")
    index: dict[tuple[str, str], list[str]] = {}
    for entry in entries:
        if not isinstance(entry, dict):
            raise ValueError("each recipe instruction must be a mapping")
        mnemonic = str(entry.get("mnemonic", "")).lower()
        form = str(entry.get("form", "")).lower()
        uops = entry.get("uops")
        if not mnemonic or not form or not isinstance(uops, list) or not uops:
            raise ValueError(f"invalid recipe entry: {entry!r}")
        key = (mnemonic, form)
        if key in index:
            raise ValueError(f"duplicate recipe entry: {mnemonic}/{form}")
        index[key] = [str(uop) for uop in uops]
    return index


def catalog_index(catalog: dict[str, Any]) -> dict[str, dict[str, Any]]:
    entries = catalog.get("uop_kinds")
    if not isinstance(entries, list):
        raise ValueError("uop_kinds must be a list")
    result: dict[str, dict[str, Any]] = {}
    for entry in entries:
        if not isinstance(entry, dict):
            raise ValueError("each uop kind must be a mapping")
        kind = str(entry.get("id", ""))
        if not kind or kind in result:
            raise ValueError(f"invalid or duplicate uop kind: {kind!r}")
        result[kind] = entry
    return result


def in_function(lines: list[str], function: str) -> list[tuple[int, str]]:
    start = None
    end = None
    function_re = re.compile(rf"^\s*{re.escape(function)}:\s*$")
    size_re = re.compile(rf"^\s*\.size\s+{re.escape(function)}\s*,")
    for number, line in enumerate(lines, start=1):
        if start is None and function_re.match(line):
            start = number
            continue
        if start is not None and size_re.match(line):
            end = number
            break
    if start is None:
        raise ValueError(f"function label not found: {function}")
    if end is None:
        raise ValueError(f".size terminator not found: {function}")
    return list(enumerate(lines[start:end - 1], start=start + 1))


def parse_function(
    lines: list[str], function: str, isa: str, recipes: dict[tuple[str, str], list[str]],
    catalog: dict[str, dict[str, Any]],
) -> list[dict[str, Any]]:
    parsed: list[dict[str, Any]] = []
    rvv_state: dict[str, Any] = {
        "sew_bits": None,
        "lmul": None,
        "vl": "runtime",
        "vl_operand": None,
        "tail_policy": None,
        "mask_policy": None,
    }
    for line_number, original in in_function(lines, function):
        line = original.split("#", 1)[0].strip()
        if not line or line.startswith(".") or LABEL_RE.match(line):
            continue
        match = INSTRUCTION_RE.match(original)
        if not match:
            raise ValueError(f"line {line_number}: cannot parse {original.rstrip()!r}")
        mnemonic = match.group(1).lower()
        operands = split_operands(match.group(2))
        form = x86_form(mnemonic, operands) if isa == "x86" else "any"
        uop_ids = recipes.get((mnemonic, form)) or recipes.get((mnemonic, "any"))
        if uop_ids is None:
            raise ValueError(
                f"line {line_number}: no recipe for {isa} {mnemonic}/{form}: "
                f"{original.rstrip()}"
            )
        uop_entries = []
        for uop_id in uop_ids:
            if uop_id not in catalog:
                raise ValueError(f"recipe references unknown uop kind: {uop_id}")
            kind = catalog[uop_id]
            uop_entries.append(
                {
                    "kind": uop_id,
                    "category": kind["category"],
                    "execution_class": kind["execution_class"],
                    "source_line": line_number,
                }
            )
        width = "runtime" if isa == "rvv" else vector_width(operands)
        instruction: dict[str, Any] = {
            "index": len(parsed),
            "source_line": line_number,
            "mnemonic": mnemonic,
            "form": form,
            "operands": operands,
            "width_bits": width,
            "uops": uop_entries,
        }
        if isa == "rvv":
            if mnemonic == "vsetvli":
                rvv_state = update_rvv_state(rvv_state, operands)
            if mnemonic.startswith("v"):
                instruction["vector_state"] = dict(rvv_state)
        parsed.append(instruction)
    if not parsed:
        raise ValueError(f"function contains no instructions: {function}")
    return parsed


def update_rvv_state(state: dict[str, Any], operands: list[str]) -> dict[str, Any]:
    updated = dict(state)
    if len(operands) >= 2:
        # vsetvli rd, rs1, ...: the resulting VL depends on runtime AVL/VLEN.
        updated["vl_operand"] = operands[1]
    for operand in operands[2:]:
        token = operand.lower()
        # The policy tokens also start with ``m``; classify them before LMUL.
        if token in {"ta", "tu"}:
            updated["tail_policy"] = token
        elif token in {"ma", "mu"}:
            updated["mask_policy"] = token
        elif token.startswith("e") and token[1:].isdigit():
            updated["sew_bits"] = int(token[1:])
        elif token.startswith("m"):
            updated["lmul"] = token
    return updated


def vector_width(operands: list[str]) -> int:
    joined = " ".join(operands).lower()
    if "%zmm" in joined:
        return 512
    if "%ymm" in joined:
        return 256
    if "%xmm" in joined:
        return 128
    return 32


def build_trace(
    assembly: Path, isa: str, function: str, recipe_path: Path, catalog_path: Path
) -> dict[str, Any]:
    recipe = load_yaml(recipe_path)
    catalog = catalog_index(load_yaml(catalog_path))
    if str(recipe.get("isa", "")).lower() != isa:
        raise ValueError(f"recipe ISA does not match --isa={isa}")
    lines = assembly.read_text(encoding="utf-8").splitlines()
    instructions = parse_function(
        lines, function, isa, recipe_index(recipe), catalog
    )
    flat_uops = [uop for instruction in instructions for uop in instruction["uops"]]
    return {
        "trace_version": 1,
        "isa": isa,
        "assembly": str(assembly),
        "function": function,
        "input_mode": "assembly_only",
        "provenance": {
            "assembly_sha256": hashlib.sha256(assembly.read_bytes()).hexdigest(),
            "recipe_sha256": hashlib.sha256(recipe_path.read_bytes()).hexdigest(),
            "uop_catalog_sha256": hashlib.sha256(
                catalog_path.read_bytes()
            ).hexdigest(),
        },
        "instructions": instructions,
        "uops": flat_uops,
        "vector_state_final": (
            next(
                (
                    instruction["vector_state"]
                    for instruction in reversed(instructions)
                    if "vector_state" in instruction
                ),
                None,
            )
            if isa == "rvv"
            else None
        ),
        "statistics": {
            "instruction_count": len(instructions),
            "uop_count": len(flat_uops),
            "instructions_by_mnemonic": dict(
                sorted(Counter(i["mnemonic"] for i in instructions).items())
            ),
            "uops_by_kind": dict(
                sorted(Counter(u["kind"] for u in flat_uops).items())
            ),
        },
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--isa", choices=("x86", "rvv"), required=True)
    parser.add_argument("--assembly", type=Path, required=True)
    parser.add_argument("--function", required=True)
    parser.add_argument("--recipe", type=Path, required=True)
    parser.add_argument("--catalog", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    try:
        trace = build_trace(
            args.assembly, args.isa, args.function, args.recipe, args.catalog
        )
    except (OSError, ValueError, KeyError) as error:
        print(f"asm_to_uop: error: {error}", file=sys.stderr)
        return 2
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(trace, indent=2) + "\n", encoding="utf-8")
    print(
        f"{args.isa}: {trace['statistics']['instruction_count']} instructions, "
        f"{trace['statistics']['uop_count']} uops -> {args.output}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
