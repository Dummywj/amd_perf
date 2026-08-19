#!/usr/bin/env python3
"""Expand RVV compiler assembly into a dynamic semantic-uop DAG."""

from __future__ import annotations

import argparse
import hashlib
import re
import sys
from dataclasses import dataclass
from fractions import Fraction
from pathlib import Path
from typing import Any

import yaml

from .common import write_json


INPUT_BASE = 0x100000
OUTPUT_BASE = 0x200000
STACK_BASE = 0x300000
CONSTANT_BASE = 0x400000

INSTRUCTION_RE = re.compile(r"^\s*([A-Za-z][A-Za-z0-9.]*)\s*(.*?)\s*$")
LABEL_RE = re.compile(r"^\s*([.A-Za-z_][A-Za-z0-9_.]*):\s*$")
MEMORY_RE = re.compile(r"^(?P<disp>.*?)\((?P<base>[A-Za-z][A-Za-z0-9]*)\)$")
VECTOR_REGISTER_RE = re.compile(r"^v(?P<index>\d+)$")

BRANCHES = {"beq", "bgeu", "bgtu", "bltu", "j"}
RETURNS = {"ret", "jr"}
LOADS = {"ld", "flw", "vle32.v"}
STORES = {"sd", "fsw", "vse32.v"}
VECTOR_FMA = {"vfmacc.vf", "vfmacc.vv"}


@dataclass(frozen=True)
class StaticInstruction:
    index: int
    source_line: int
    mnemonic: str
    operands: tuple[str, ...]
    text: str


def split_operands(text: str) -> list[str]:
    result: list[str] = []
    start = 0
    depth = 0
    for index, character in enumerate(text):
        if character in "([":
            depth += 1
        elif character in ")]":
            depth -= 1
        elif character == "," and depth == 0:
            result.append(text[start:index].strip())
            start = index + 1
    tail = text[start:].strip()
    if tail:
        result.append(tail)
    return result


def load_recipe(
    path: Path, uop_kinds_path: Path | None = None
) -> dict[tuple[str, str], list[str]]:
    document = yaml.safe_load(path.read_text(encoding="utf-8"))
    if uop_kinds_path is None:
        uop_kinds_path = path.parent.parent / "uops/uop_kinds.yaml"
    catalog = yaml.safe_load(uop_kinds_path.read_text(encoding="utf-8"))
    known_kinds = {entry["id"] for entry in catalog["uop_kinds"]}
    result: dict[tuple[str, str], list[str]] = {}
    for entry in document["instructions"]:
        kinds = [str(value) for value in entry["uops"]]
        unknown = sorted(set(kinds) - known_kinds)
        if unknown:
            raise ValueError(
                f"recipe {entry['mnemonic']}/{entry['form']} references unknown "
                f"semantic uop kinds: {', '.join(unknown)}"
            )
        key = (str(entry["mnemonic"]).lower(), str(entry["form"]).lower())
        if key in result:
            raise ValueError(f"duplicate semantic recipe: {key[0]}/{key[1]}")
        result[key] = kinds
    return result


def parse_function(path: Path, function: str) -> tuple[list[StaticInstruction], dict[str, int]]:
    lines = path.read_text(encoding="utf-8").splitlines()
    in_target = False
    instructions: list[StaticInstruction] = []
    labels: dict[str, int] = {}
    for line_number, original in enumerate(lines, start=1):
        stripped = original.split("#", 1)[0].strip()
        if not in_target:
            if stripped == f"{function}:":
                in_target = True
                labels[function] = 0
            continue
        if stripped.startswith(f".size\t{function},") or stripped.startswith(
            f".size {function},"
        ):
            break
        label = LABEL_RE.match(stripped)
        if label:
            labels[label.group(1)] = len(instructions)
            continue
        if not stripped or stripped.startswith("."):
            continue
        match = INSTRUCTION_RE.match(stripped)
        if not match:
            raise ValueError(f"line {line_number}: cannot parse {original!r}")
        mnemonic = match.group(1).lower()
        operands = tuple(split_operands(match.group(2)))
        instructions.append(
            StaticInstruction(
                index=len(instructions),
                source_line=line_number,
                mnemonic=mnemonic,
                operands=operands,
                text=f"{mnemonic} {', '.join(operands)}".strip(),
            )
        )
    if not instructions:
        raise ValueError(f"function not found or empty: {function}")
    return instructions, labels


def canonical_register(token: str) -> str | None:
    value = token.strip().lower()
    if re.fullmatch(
        r"(?:zero|ra|sp|gp|tp|t[0-6]|s(?:[0-9]|1[01])|a[0-7]|"
        r"f(?:t(?:[0-9]|1[01])|s(?:[0-9]|1[01])|a[0-7])|v(?:[0-9]|[12][0-9]|3[01]))",
        value,
    ):
        return value
    return None


def lmul_value(token: str) -> Fraction:
    values = {
        "mf8": Fraction(1, 8),
        "mf4": Fraction(1, 4),
        "mf2": Fraction(1, 2),
        "m1": Fraction(1, 1),
        "m2": Fraction(2, 1),
        "m4": Fraction(4, 1),
        "m8": Fraction(8, 1),
    }
    if token not in values:
        raise ValueError(f"unsupported LMUL: {token}")
    return values[token]


def vector_group(register: str, state: dict[str, Any]) -> list[str]:
    match = VECTOR_REGISTER_RE.match(register)
    if not match:
        return [register]
    lmul = lmul_value(str(state.get("lmul") or "m1"))
    group_size = max(1, int(lmul))
    start = int(match.group("index"))
    if start + group_size > 32:
        raise ValueError(f"vector register group exceeds v31: {register}/{state['lmul']}")
    return [f"v{index}" for index in range(start, start + group_size)]


def registers_in_memory(operand: str) -> list[str]:
    match = MEMORY_RE.match(operand)
    if not match:
        return []
    register = canonical_register(match.group("base"))
    return [] if register in {None, "zero"} else [register]


def add_operand_registers(
    result: list[str], operand: str, vector_state: dict[str, Any]
) -> None:
    register = canonical_register(operand)
    if register is None or register == "zero":
        return
    result.extend(vector_group(register, vector_state))


def register_roles(
    instruction: StaticInstruction, vector_state: dict[str, Any]
) -> tuple[list[str], list[str]]:
    mnemonic = instruction.mnemonic
    operands = instruction.operands
    reads: list[str] = []
    writes: list[str] = []

    for operand in operands:
        reads.extend(registers_in_memory(operand))

    if mnemonic in RETURNS:
        if mnemonic == "ret":
            reads.append("ra")
        elif operands:
            add_operand_registers(reads, operands[0], vector_state)
    elif mnemonic in BRANCHES:
        if mnemonic != "j":
            for operand in operands[:-1]:
                add_operand_registers(reads, operand, vector_state)
    elif mnemonic in STORES:
        if operands:
            add_operand_registers(reads, operands[0], vector_state)
        if mnemonic.startswith("v"):
            reads.append("vconfig")
    elif mnemonic in LOADS:
        if operands:
            add_operand_registers(writes, operands[0], vector_state)
        if mnemonic.startswith("v"):
            reads.append("vconfig")
    elif mnemonic == "vsetvli":
        if len(operands) >= 2:
            add_operand_registers(reads, operands[1], vector_state)
        if operands and canonical_register(operands[0]) != "zero":
            add_operand_registers(writes, operands[0], vector_state)
        writes.append("vconfig")
    elif mnemonic in {"li", "lui"}:
        if operands:
            add_operand_registers(writes, operands[0], vector_state)
    elif mnemonic in {"add", "addi", "sub", "slli"}:
        if operands:
            add_operand_registers(writes, operands[0], vector_state)
        for operand in operands[1:]:
            add_operand_registers(reads, operand, vector_state)
    elif mnemonic.startswith("v"):
        reads.append("vconfig")
        if operands:
            add_operand_registers(writes, operands[0], vector_state)
            if mnemonic in VECTOR_FMA:
                add_operand_registers(reads, operands[0], vector_state)
        for operand in operands[1:]:
            add_operand_registers(reads, operand, vector_state)
    else:
        if operands:
            add_operand_registers(writes, operands[0], vector_state)
        for operand in operands[1:]:
            add_operand_registers(reads, operand, vector_state)

    return list(dict.fromkeys(reads)), list(dict.fromkeys(writes))


def constant_address(label: str, constants: dict[str, int]) -> int:
    if label not in constants:
        constants[label] = CONSTANT_BASE + len(constants) * 64
    return constants[label]


def scalar_value(operand: str, registers: dict[str, int]) -> int:
    register = canonical_register(operand)
    if register:
        return 0 if register == "zero" else registers.get(register, 0)
    return int(operand, 0)


def evaluate_memory(
    operand: str, registers: dict[str, int], constants: dict[str, int]
) -> tuple[int, str]:
    match = MEMORY_RE.match(operand)
    if not match:
        raise ValueError(f"unsupported memory operand: {operand}")
    displacement = match.group("disp") or "0"
    relocation = re.fullmatch(r"%lo\(([^)]+)\)", displacement)
    if relocation:
        address = constant_address(relocation.group(1), constants)
        return address, "constant"
    base = canonical_register(match.group("base"))
    address = (0 if base in {None, "zero"} else registers.get(base, 0)) + int(
        displacement, 0
    )
    if INPUT_BASE <= address < OUTPUT_BASE:
        region = "input"
    elif OUTPUT_BASE <= address < STACK_BASE:
        region = "output"
    elif STACK_BASE - 0x10000 <= address < CONSTANT_BASE:
        region = "stack"
    elif address >= CONSTANT_BASE:
        region = "constant"
    else:
        region = "other"
    return address, region


def vector_state_from_operands(
    operands: tuple[str, ...],
    registers: dict[str, int],
    vlen_bits: int,
    previous_state: dict[str, Any] | None = None,
) -> dict[str, Any]:
    if len(operands) < 3:
        raise ValueError(f"invalid vsetvli operands: {operands!r}")
    sew_bits: int | None = None
    lmul: str | None = None
    tail_policy: str | None = None
    mask_policy: str | None = None
    for operand in operands[2:]:
        token = operand.lower()
        if token.startswith("e") and token[1:].isdigit():
            sew_bits = int(token[1:])
        elif token in {"mf8", "mf4", "mf2", "m1", "m2", "m4", "m8"}:
            lmul = token
        elif token in {"ta", "tu"}:
            tail_policy = token
        elif token in {"ma", "mu"}:
            mask_policy = token
    if sew_bits is None or lmul is None:
        raise ValueError(f"vsetvli is missing SEW/LMUL: {operands!r}")
    vlmax = int(Fraction(vlen_bits, sew_bits) * lmul_value(lmul))
    destination = canonical_register(operands[0])
    source = canonical_register(operands[1])
    if source == "zero" and destination != "zero":
        vl = vlmax
    elif source == "zero" and destination == "zero":
        previous_vl = None if previous_state is None else previous_state.get("vl")
        if previous_vl is None:
            raise ValueError("vsetvli zero, zero requires an established VL")
        vl = int(previous_vl)
    else:
        vl = min(scalar_value(operands[1], registers), vlmax)
    return {
        "vlen_bits": vlen_bits,
        "sew_bits": sew_bits,
        "lmul": lmul,
        "vlmax": vlmax,
        "vl": vl,
        "tail_policy": tail_policy,
        "mask_policy": mask_policy,
    }


def update_scalar_state(
    instruction: StaticInstruction,
    registers: dict[str, int],
    stack: dict[int, int],
    constants: dict[str, int],
    vector_state: dict[str, Any],
    vlen_bits: int,
) -> dict[str, Any]:
    mask = (1 << 64) - 1
    mnemonic = instruction.mnemonic
    operands = instruction.operands

    def write(destination: str, value: int) -> None:
        register = canonical_register(destination)
        if register and register != "zero":
            registers[register] = value & mask

    if mnemonic == "li":
        write(operands[0], scalar_value(operands[1], registers))
    elif mnemonic == "lui":
        relocation = re.fullmatch(r"%hi\(([^)]+)\)", operands[1])
        value = (
            (constant_address(relocation.group(1), constants) + 0x800) & ~0xFFF
            if relocation
            else scalar_value(operands[1], registers) << 12
        )
        write(operands[0], value)
    elif mnemonic in {"add", "addi", "sub", "slli"}:
        left = scalar_value(operands[1], registers)
        right = scalar_value(operands[2], registers)
        if mnemonic in {"add", "addi"}:
            value = left + right
        elif mnemonic == "sub":
            value = left - right
        else:
            value = left << right
        write(operands[0], value)
    elif mnemonic == "sd":
        address, _ = evaluate_memory(operands[1], registers, constants)
        stack[address] = scalar_value(operands[0], registers)
    elif mnemonic == "ld":
        address, _ = evaluate_memory(operands[1], registers, constants)
        write(operands[0], stack.get(address, 0))
    elif mnemonic == "vsetvli":
        vector_state = vector_state_from_operands(
            operands, registers, vlen_bits, vector_state
        )
        write(operands[0], int(vector_state["vl"]))
    return vector_state


def branch_taken(
    instruction: StaticInstruction, registers: dict[str, int]
) -> bool:
    mnemonic = instruction.mnemonic
    if mnemonic == "j":
        return True
    left = scalar_value(instruction.operands[0], registers) & ((1 << 64) - 1)
    right = scalar_value(instruction.operands[1], registers) & ((1 << 64) - 1)
    if mnemonic == "beq":
        return left == right
    if mnemonic == "bgeu":
        return left >= right
    if mnemonic == "bgtu":
        return left > right
    if mnemonic == "bltu":
        return left < right
    raise ValueError(f"unsupported branch: {mnemonic}")


def access_bytes(instruction: StaticInstruction, vector_state: dict[str, Any]) -> int:
    if instruction.mnemonic in {"ld", "sd"}:
        return 8
    if instruction.mnemonic in {"flw", "fsw"}:
        return 4
    if instruction.mnemonic in {"vle32.v", "vse32.v"}:
        if vector_state.get("vl") is None:
            raise ValueError(f"{instruction.mnemonic} executed before vsetvli")
        return int(vector_state["vl"]) * 4
    raise ValueError(f"unsupported memory instruction: {instruction.mnemonic}")


def semantic_uops(
    kinds: list[str], old_destination_registers: list[str] | None = None
) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    previous: str | None = None
    old_destination_registers = old_destination_registers or []
    for index, kind in enumerate(kinds):
        local_id = f"u{index}"
        entry: dict[str, Any] = {
            "local_id": local_id,
            "kind": kind,
            "depends_on_local": [previous] if previous else [],
        }
        if old_destination_registers and kind not in {
            "address_generation",
            "vector_config",
        }:
            entry["reads_old_destination"] = True
            entry["old_destination_registers"] = list(old_destination_registers)
        result.append(entry)
        previous = local_id
    return result


def build_dynamic_trace(
    assembly: Path,
    function: str,
    recipe_path: Path,
    count: int,
    uop_kinds_path: Path | None = None,
    *,
    vlen_bits: int = 128,
) -> dict[str, Any]:
    if count <= 0:
        raise ValueError("RVV kernel requires count > 0")
    if vlen_bits <= 0 or vlen_bits % 8:
        raise ValueError("RVV VLEN must be a positive multiple of 8 bits")
    static, labels = parse_function(assembly, function)
    if uop_kinds_path is None:
        uop_kinds_path = recipe_path.parent.parent / "uops/uop_kinds.yaml"
    recipes = load_recipe(recipe_path, uop_kinds_path)
    registers = {
        "a0": INPUT_BASE,
        "a1": OUTPUT_BASE,
        "a2": count,
        "sp": STACK_BASE,
        "ra": 0,
    }
    stack: dict[int, int] = {}
    constants: dict[str, int] = {}
    vector_state: dict[str, Any] = {
        "vlen_bits": vlen_bits,
        "sew_bits": None,
        "lmul": None,
        "vlmax": None,
        "vl": None,
        "tail_policy": None,
        "mask_policy": None,
    }
    last_register_writer: dict[str, str] = {}
    last_store_by_line: dict[int, str] = {}
    instructions: list[dict[str, Any]] = []
    pc = 0
    steps = 0
    max_steps = 10000 + count * 256
    while pc < len(static):
        steps += 1
        if steps > max_steps:
            raise ValueError("RVV dynamic expansion exceeded safety bound")
        item = static[pc]
        reads, writes = register_roles(item, vector_state)
        instruction_id = f"i{len(instructions)}"
        register_dependencies = {
            register: last_register_writer[register]
            for register in reads
            if register in last_register_writer
        }
        old_destination_registers = sorted(
            {
                register
                for register in set(reads).intersection(writes)
                if VECTOR_REGISTER_RE.fullmatch(register)
            }
        )
        old_destination_dependencies = {
            register: register_dependencies[register]
            for register in old_destination_registers
            if register in register_dependencies
        }
        vector_destination_registers = sorted(
            register
            for register in writes
            if VECTOR_REGISTER_RE.fullmatch(register)
        )
        vector_destination_dependencies = {
            register: last_register_writer[register]
            for register in vector_destination_registers
            if register in last_register_writer
        }
        dependencies = set(register_dependencies.values())
        memory_dependencies: set[str] = set()
        memory: dict[str, Any] | None = None
        memory_operand = next(
            (operand for operand in item.operands if MEMORY_RE.match(operand)), None
        )
        if item.mnemonic in LOADS | STORES:
            if memory_operand is None:
                raise ValueError(f"missing memory operand: {item.text}")
            address, region = evaluate_memory(memory_operand, registers, constants)
            size = access_bytes(item, vector_state)
            cache_lines = list(range(address // 64, (address + size - 1) // 64 + 1))
            is_store = item.mnemonic in STORES
            memory = {
                "address": address,
                "region": region,
                "offset": address
                - {
                    "input": INPUT_BASE,
                    "output": OUTPUT_BASE,
                    "stack": STACK_BASE,
                    "constant": CONSTANT_BASE,
                }.get(region, address),
                "bytes": size,
                "cache_lines": cache_lines,
                "access": "store" if is_store else "load",
                "address_registers": registers_in_memory(memory_operand),
            }
            for cache_line in cache_lines:
                previous_store = last_store_by_line.get(cache_line)
                if previous_store:
                    dependencies.add(previous_store)
                    memory_dependencies.add(previous_store)

        kinds = recipes.get((item.mnemonic, "any"))
        if not kinds:
            raise ValueError(f"no semantic recipe for {item.mnemonic}/any")
        dynamic: dict[str, Any] = {
            "id": instruction_id,
            "sequence": len(instructions),
            "static_index": item.index,
            "source_line": item.source_line,
            "mnemonic": item.mnemonic,
            "form": "any",
            "operands": list(item.operands),
            "assembly": item.text,
            "register_reads": reads,
            "register_writes": writes,
            "depends_on_instructions": sorted(
                dependencies, key=lambda value: int(value[1:])
            ),
            "register_dependencies": register_dependencies,
            "flags_dependency": None,
            "memory_dependencies": sorted(
                memory_dependencies, key=lambda value: int(value[1:])
            ),
            "memory": memory,
            "semantic_uops": semantic_uops(kinds, old_destination_registers),
        }
        if old_destination_registers:
            dynamic["old_destination_registers"] = old_destination_registers
            dynamic["old_destination_dependencies"] = (
                old_destination_dependencies
            )
        if vector_destination_registers:
            dynamic["vector_destination_registers"] = (
                vector_destination_registers
            )
            dynamic["vector_destination_dependencies"] = (
                vector_destination_dependencies
            )
        if item.mnemonic.startswith("v"):
            recorded_vector_state = (
                vector_state_from_operands(
                    item.operands, registers, vlen_bits, vector_state
                )
                if item.mnemonic == "vsetvli"
                else vector_state
            )
            dynamic["vector_state"] = dict(recorded_vector_state)
            if recorded_vector_state.get("vl") is not None and recorded_vector_state.get(
                "sew_bits"
            ) is not None:
                dynamic["active_vector_bits"] = int(recorded_vector_state["vl"]) * int(
                    recorded_vector_state["sew_bits"]
                )
        instructions.append(dynamic)

        for register in writes:
            if register != "zero":
                last_register_writer[register] = instruction_id
        if memory and memory["access"] == "store":
            for cache_line in memory["cache_lines"]:
                last_store_by_line[cache_line] = instruction_id

        vector_state = update_scalar_state(
            item, registers, stack, constants, vector_state, vlen_bits
        )
        if item.mnemonic in RETURNS:
            break
        if item.mnemonic in BRANCHES and branch_taken(item, registers):
            target = item.operands[-1]
            if target not in labels:
                raise ValueError(f"unknown branch target: {target}")
            pc = labels[target]
        else:
            pc += 1

    uop_counts: dict[str, int] = {}
    load_bytes = 0
    store_bytes = 0
    for instruction in instructions:
        for uop in instruction["semantic_uops"]:
            kind = str(uop["kind"])
            uop_counts[kind] = uop_counts.get(kind, 0) + 1
        memory = instruction["memory"]
        if memory and memory["region"] in {"input", "output"}:
            if memory["access"] == "load":
                load_bytes += int(memory["bytes"])
            else:
                store_bytes += int(memory["bytes"])
    return {
        "trace_version": 2,
        "isa": "rvv",
        "function": function,
        "assembly": str(assembly),
        "provenance": {
            "assembly_sha256": hashlib.sha256(assembly.read_bytes()).hexdigest(),
            "recipe_sha256": hashlib.sha256(recipe_path.read_bytes()).hexdigest(),
            "uop_kinds_sha256": hashlib.sha256(
                uop_kinds_path.read_bytes()
            ).hexdigest(),
        },
        "workload": {
            "count": count,
            "vlen_bits": vlen_bits,
            "buffers": {"input": INPUT_BASE, "output": OUTPUT_BASE},
        },
        "instructions": instructions,
        "statistics": {
            "dynamic_instruction_count": len(instructions),
            "semantic_uop_count": sum(uop_counts.values()),
            "uops_by_kind": dict(sorted(uop_counts.items())),
            "input_output_load_bytes": load_bytes,
            "input_output_store_bytes": store_bytes,
            "input_output_total_bytes": load_bytes + store_bytes,
        },
    }


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Expand an RVV kernel into a dynamic semantic-uop trace"
    )
    parser.add_argument("--assembly", type=Path, required=True)
    parser.add_argument("--function", required=True)
    parser.add_argument("--recipe", type=Path, required=True)
    parser.add_argument("--uop-kinds", type=Path)
    parser.add_argument("--count", type=int, required=True)
    parser.add_argument("--vlen-bits", type=int, default=128)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    try:
        trace = build_dynamic_trace(
            args.assembly,
            args.function,
            args.recipe,
            args.count,
            args.uop_kinds,
            vlen_bits=args.vlen_bits,
        )
        write_json(args.output, trace)
    except (OSError, ValueError, KeyError, yaml.YAMLError) as error:
        print(f"RVV frontend: error: {error}", file=sys.stderr)
        return 2
    print(
        f"RVV dynamic trace: {trace['statistics']['dynamic_instruction_count']} "
        f"instructions, {trace['statistics']['semantic_uop_count']} semantic uops "
        f"-> {args.output}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
