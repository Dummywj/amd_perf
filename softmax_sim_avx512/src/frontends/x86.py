#!/usr/bin/env python3
"""Expand the current AVX-512 softmax assembly into a dynamic semantic-uop DAG."""

from __future__ import annotations

import argparse
import hashlib
import re
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

from .common import write_json


INSTRUCTION_RE = re.compile(r"^\s*([A-Za-z][A-Za-z0-9.]*)\s*(.*?)\s*$")
LABEL_RE = re.compile(r"^\s*([.A-Za-z_][A-Za-z0-9_.]*):\s*$")
MEMORY_RE = re.compile(
    r"^(?P<disp>[^()]*)\((?P<base>%[A-Za-z0-9]+)?(?:,(?P<index>%[A-Za-z0-9]+)?(?:,(?P<scale>[1248]))?)?\)$"
)
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
        kinds = list(entry["uops"])
        unknown = sorted(set(kinds) - known_kinds)
        if unknown:
            raise ValueError(
                f"recipe {entry['mnemonic']}/{entry['form']} references unknown "
                f"semantic uop kinds: {', '.join(unknown)}"
            )
        result[(entry["mnemonic"].lower(), entry["form"].lower())] = kinds
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
        if mnemonic == "retq":
            mnemonic = "ret"
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


def operand_form(operands: tuple[str, ...]) -> str:
    memory = ["(" in operand or "[" in operand for operand in operands]
    if any(memory):
        return "memory_store" if memory[-1] else "memory_load"
    return "register"


REGISTER_ALIASES = {
    "eax": "rax",
    "ax": "rax",
    "al": "rax",
    "ecx": "rcx",
    "cx": "rcx",
    "cl": "rcx",
    "edx": "rdx",
    "dx": "rdx",
    "dl": "rdx",
    "esi": "rsi",
    "edi": "rdi",
}


def canonical_register(operand: str) -> str | None:
    token = operand.strip()
    if not token.startswith("%"):
        return None
    name = token[1:].lower()
    if name in REGISTER_ALIASES:
        return REGISTER_ALIASES[name]
    if re.fullmatch(r"(?:xmm|ymm|zmm)\d+", name):
        return "zmm" + re.search(r"\d+", name).group(0)
    return name


def registers_in_memory(operand: str) -> list[str]:
    match = MEMORY_RE.match(operand)
    if not match:
        return []
    return [
        register
        for raw in (match.group("base"), match.group("index"))
        if raw and (register := canonical_register(raw))
    ]


def register_roles(instruction: StaticInstruction) -> tuple[list[str], list[str], bool, bool]:
    mnemonic = instruction.mnemonic
    operands = instruction.operands
    reads: list[str] = []
    writes: list[str] = []
    reads_flags = mnemonic in {"je", "jne", "jb"}
    writes_flags = mnemonic in {"testq", "cmpq", "addq", "andq", "xorl"}

    for operand in operands:
        reads.extend(registers_in_memory(operand))

    registers = [canonical_register(operand) for operand in operands]
    if mnemonic in {"je", "jne", "jb", "ret", "vzeroupper"}:
        pass
    elif mnemonic in {"testq", "cmpq"}:
        reads.extend(register for register in registers if register)
    elif mnemonic in {"xorl", "vxorps"} and len(set(r for r in registers if r)) == 1:
        if registers and registers[-1]:
            writes.append(registers[-1])
    elif mnemonic in {"movl", "vmovaps", "vmovss", "vmovups"}:
        if operands and ("(" in operands[-1] or "[" in operands[-1]):
            reads.extend(register for register in registers[:-1] if register)
        else:
            reads.extend(register for register in registers[:-1] if register)
            if registers and registers[-1]:
                writes.append(registers[-1])
    elif mnemonic in {"addq", "andq"}:
        if registers and registers[-1]:
            reads.append(registers[-1])
            writes.append(registers[-1])
        reads.extend(register for register in registers[:-1] if register)
    elif mnemonic == "leaq":
        if registers and registers[-1]:
            writes.append(registers[-1])
    else:
        reads.extend(register for register in registers[:-1] if register)
        if registers and registers[-1]:
            if mnemonic.startswith("vfmadd") or mnemonic.startswith("vfnmadd"):
                reads.append(registers[-1])
            writes.append(registers[-1])
    return sorted(set(reads)), sorted(set(writes)), reads_flags, writes_flags


def parse_integer(token: str) -> int:
    return int(token.strip().removeprefix("$"), 0)


def evaluate_memory(
    operand: str, registers: dict[str, int], constants: dict[str, int]
) -> tuple[int, str]:
    match = MEMORY_RE.match(operand)
    if not match:
        raise ValueError(f"unsupported memory operand: {operand}")
    displacement = match.group("disp").strip()
    label = None
    if displacement.startswith(".L"):
        label = displacement
        if label not in constants:
            constants[label] = 0x400000 + len(constants) * 4
        offset = constants[label]
    else:
        offset = int(displacement, 0) if displacement else 0
    base = canonical_register(match.group("base") or "")
    index = canonical_register(match.group("index") or "")
    scale = int(match.group("scale") or "1")
    address = offset
    if base and base != "rip":
        address += registers[base]
    if index:
        address += registers[index] * scale
    region = "constant" if label else ("input" if address < 0x200000 else "output")
    return address, region


def access_bytes(instruction: StaticInstruction) -> int:
    if instruction.mnemonic in {"vmovss", "vbroadcastss"}:
        return 4
    width = 32
    for operand in instruction.operands:
        match = re.search(r"%(zmm|ymm|xmm)\d+", operand)
        if match:
            width = {"zmm": 512, "ymm": 256, "xmm": 128}[match.group(1)]
            break
    return width // 8


def update_scalar_state(
    instruction: StaticInstruction,
    registers: dict[str, int],
    state: dict[str, int | bool],
    labels: dict[str, int],
) -> None:
    mnemonic = instruction.mnemonic
    operands = instruction.operands
    if mnemonic in {"xorl", "movl"}:
        destination = canonical_register(operands[-1])
        if destination:
            registers[destination] = 0 if mnemonic == "xorl" else parse_integer(operands[0])
    elif mnemonic == "addq":
        destination = canonical_register(operands[-1])
        registers[destination] += parse_integer(operands[0])
    elif mnemonic == "andq":
        destination = canonical_register(operands[-1])
        registers[destination] &= parse_integer(operands[0]) & ((1 << 64) - 1)
    elif mnemonic == "leaq":
        destination = canonical_register(operands[-1])
        address, _ = evaluate_memory(operands[0], registers, labels)
        registers[destination] = address
    elif mnemonic in {"testq", "cmpq"}:
        if mnemonic == "testq":
            left = registers[canonical_register(operands[-1])]
            right = registers[canonical_register(operands[0])]
            result = left & right
            state["zf"] = result == 0
            state["cf"] = False
        else:
            left_operand, right_operand = operands[0], operands[-1]
            left = (
                parse_integer(left_operand)
                if left_operand.startswith("$")
                else registers[canonical_register(left_operand)]
            )
            right = registers[canonical_register(right_operand)]
            state["zf"] = right == left
            state["cf"] = right < left


def branch_taken(mnemonic: str, state: dict[str, int | bool]) -> bool:
    if mnemonic == "je":
        return bool(state["zf"])
    if mnemonic == "jne":
        return not bool(state["zf"])
    if mnemonic == "jb":
        return bool(state["cf"])
    raise ValueError(f"unsupported branch: {mnemonic}")


def semantic_uop_dependencies(
    kinds: list[str], instruction_dependencies: list[str]
) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    previous: str | None = None
    for index, kind in enumerate(kinds):
        local_id = f"u{index}"
        dependencies = list(instruction_dependencies)
        if previous:
            dependencies.append(previous)
        result.append({"local_id": local_id, "kind": kind, "depends_on_local": dependencies})
        previous = local_id
    return result


def build_dynamic_trace(
    assembly: Path,
    function: str,
    recipe_path: Path,
    count: int,
    uop_kinds_path: Path | None = None,
) -> dict[str, Any]:
    if count <= 0 or count % 16:
        raise ValueError("x86 softmax requires count > 0 and divisible by 16")
    static, labels = parse_function(assembly, function)
    if uop_kinds_path is None:
        uop_kinds_path = recipe_path.parent.parent / "uops/uop_kinds.yaml"
    recipes = load_recipe(recipe_path, uop_kinds_path)
    registers = {"rdi": 0x100000, "rsi": 0x200000, "rdx": count, "rax": 0, "rcx": 0}
    flags: dict[str, int | bool] = {"zf": False, "cf": False}
    constants: dict[str, int] = {}
    last_register_writer: dict[str, str] = {}
    last_flags_writer: str | None = None
    last_store_by_line: dict[int, str] = {}
    instructions: list[dict[str, Any]] = []
    pc = 0
    steps = 0
    max_steps = 1000 + count * 16
    while pc < len(static):
        steps += 1
        if steps > max_steps:
            raise ValueError("dynamic expansion exceeded safety bound")
        item = static[pc]
        reads, writes, reads_flags, writes_flags = register_roles(item)
        instruction_id = f"i{len(instructions)}"
        dependencies = {
            last_register_writer[register]
            for register in reads
            if register in last_register_writer
        }
        if reads_flags and last_flags_writer:
            dependencies.add(last_flags_writer)
        register_dependencies = {
            register: last_register_writer[register]
            for register in reads
            if register in last_register_writer
        }
        flags_dependency = last_flags_writer if reads_flags else None
        memory_dependencies: set[str] = set()
        memory: dict[str, Any] | None = None
        memory_operands = (
            []
            if item.mnemonic == "leaq"
            else [operand for operand in item.operands if "(" in operand]
        )
        if memory_operands:
            address, region = evaluate_memory(memory_operands[0], registers, constants)
            size = access_bytes(item)
            is_store = item.operands[-1] == memory_operands[0]
            line = address // 64
            memory = {
                "address": address,
                "region": region,
                "offset": address - {"input": 0x100000, "output": 0x200000}.get(region, address),
                "bytes": size,
                "cache_lines": list(range(line, (address + size - 1) // 64 + 1)),
                "access": "store" if is_store else "load",
                "address_registers": registers_in_memory(memory_operands[0]),
            }
            if not is_store:
                for cache_line in memory["cache_lines"]:
                    if cache_line in last_store_by_line:
                        dependencies.add(last_store_by_line[cache_line])
                        memory_dependencies.add(last_store_by_line[cache_line])
            else:
                for cache_line in memory["cache_lines"]:
                    if cache_line in last_store_by_line:
                        dependencies.add(last_store_by_line[cache_line])
                        memory_dependencies.add(last_store_by_line[cache_line])

        form = operand_form(item.operands)
        kinds = recipes.get((item.mnemonic, form)) or recipes.get((item.mnemonic, "any"))
        if not kinds:
            raise ValueError(f"no semantic recipe for {item.mnemonic}/{form}")
        dynamic = {
            "id": instruction_id,
            "sequence": len(instructions),
            "static_index": item.index,
            "source_line": item.source_line,
            "mnemonic": item.mnemonic,
            "form": form,
            "operands": list(item.operands),
            "assembly": item.text,
            "register_reads": reads,
            "register_writes": writes,
            "depends_on_instructions": sorted(dependencies, key=lambda value: int(value[1:])),
            "register_dependencies": register_dependencies,
            "flags_dependency": flags_dependency,
            "memory_dependencies": sorted(
                memory_dependencies, key=lambda value: int(value[1:])
            ),
            "memory": memory,
            "semantic_uops": semantic_uop_dependencies(kinds, []),
        }
        instructions.append(dynamic)
        for register in writes:
            last_register_writer[register] = instruction_id
        if writes_flags:
            last_flags_writer = instruction_id
        if memory and memory["access"] == "store":
            for cache_line in memory["cache_lines"]:
                last_store_by_line[cache_line] = instruction_id

        update_scalar_state(item, registers, flags, constants)
        if item.mnemonic == "ret":
            break
        if item.mnemonic in {"je", "jne", "jb"} and branch_taken(item.mnemonic, flags):
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
            uop_counts[uop["kind"]] = uop_counts.get(uop["kind"], 0) + 1
        memory = instruction["memory"]
        if memory:
            if memory["region"] in {"input", "output"}:
                if memory["access"] == "load":
                    load_bytes += memory["bytes"]
                else:
                    store_bytes += memory["bytes"]
    return {
        "trace_version": 2,
        "isa": "x86",
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
            "buffers": {"input": 0x100000, "output": 0x200000},
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
    parser = argparse.ArgumentParser()
    parser.add_argument("--assembly", type=Path, required=True)
    parser.add_argument("--function", default="softmax_avx512_f32")
    parser.add_argument("--recipe", type=Path, required=True)
    parser.add_argument("--uop-kinds", type=Path)
    parser.add_argument("--count", type=int, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    try:
        trace = build_dynamic_trace(
            args.assembly,
            args.function,
            args.recipe,
            args.count,
            args.uop_kinds,
        )
        write_json(args.output, trace)
    except (OSError, ValueError, KeyError, yaml.YAMLError) as error:
        print(f"x86 frontend: error: {error}", file=sys.stderr)
        return 2
    print(
        f"x86 dynamic trace: {trace['statistics']['dynamic_instruction_count']} instructions, "
        f"{trace['statistics']['semantic_uop_count']} semantic uops -> {args.output}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
