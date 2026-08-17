#!/usr/bin/env python3
"""Expand AVX-512 kernel assembly into a dynamic semantic-uop DAG."""

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
        if mnemonic == "endbr64":
            # CET landing pads do not participate in a direct-call kernel's timing.
            continue
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
    alias: canonical
    for canonical, aliases in {
        "rax": ("eax", "ax", "al", "ah"),
        "rbx": ("ebx", "bx", "bl", "bh"),
        "rcx": ("ecx", "cx", "cl", "ch"),
        "rdx": ("edx", "dx", "dl", "dh"),
        "rsi": ("esi", "si", "sil"),
        "rdi": ("edi", "di", "dil"),
        "rbp": ("ebp", "bp", "bpl"),
        "rsp": ("esp", "sp", "spl"),
        **{
            f"r{index}": (f"r{index}d", f"r{index}w", f"r{index}b")
            for index in range(8, 16)
        },
    }.items()
    for alias in aliases
}

UNCONDITIONAL_BRANCHES = {"jmp", "jmpq"}
CONDITIONAL_BRANCHES = {
    "ja",
    "jae",
    "jb",
    "jbe",
    "jc",
    "je",
    "jg",
    "jge",
    "jl",
    "jle",
    "jna",
    "jnae",
    "jnb",
    "jnbe",
    "jnc",
    "jne",
    "jng",
    "jnge",
    "jnl",
    "jnle",
    "jno",
    "jns",
    "jnz",
    "jo",
    "js",
    "jz",
}
BRANCHES = UNCONDITIONAL_BRANCHES | CONDITIONAL_BRANCHES
FLAG_WRITERS = {
    "addq",
    "andq",
    "cmpq",
    "decq",
    "incq",
    "negq",
    "orq",
    "salq",
    "sarq",
    "shlq",
    "shrq",
    "subq",
    "testq",
    "xorl",
    "xorq",
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
    reads_flags = mnemonic in CONDITIONAL_BRANCHES
    writes_flags = mnemonic in FLAG_WRITERS

    for operand in operands:
        reads.extend(registers_in_memory(operand))

    registers = [canonical_register(operand) for operand in operands]
    if mnemonic in BRANCHES | {"ret", "vzeroupper", "endbr64"}:
        pass
    elif mnemonic in {"testq", "cmpq"}:
        reads.extend(register for register in registers if register)
    elif mnemonic in {"xorl", "xorq", "vxorpd", "vxorps"} and len(
        set(register for register in registers if register)
    ) == 1:
        if registers and registers[-1]:
            writes.append(registers[-1])
    elif mnemonic in {
        "movl",
        "movq",
        "movslq",
        "movzbl",
        "vmovaps",
        "vmovdqu64",
        "vmovss",
        "vmovups",
    }:
        if operands and ("(" in operands[-1] or "[" in operands[-1]):
            reads.extend(register for register in registers[:-1] if register)
        else:
            reads.extend(register for register in registers[:-1] if register)
            if registers and registers[-1]:
                writes.append(registers[-1])
    elif mnemonic in {
        "addq",
        "andq",
        "orq",
        "salq",
        "sarq",
        "shlq",
        "shrq",
        "subq",
        "xorl",
        "xorq",
    }:
        if registers and registers[-1]:
            reads.append(registers[-1])
            writes.append(registers[-1])
        reads.extend(register for register in registers[:-1] if register)
    elif mnemonic in {"decq", "incq", "negq", "notq"}:
        if registers and registers[-1]:
            reads.append(registers[-1])
            writes.append(registers[-1])
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


def scalar_operand_value(token: str, registers: dict[str, int]) -> int:
    if token.startswith("$"):
        return parse_integer(token)
    register = canonical_register(token)
    if register is None:
        raise ValueError(f"unsupported scalar operand: {token}")
    if register not in registers:
        raise ValueError(f"scalar register read before write: %{register}")
    return registers[register]


def evaluate_memory(
    operand: str, registers: dict[str, int], constants: dict[str, int]
) -> tuple[int, str]:
    match = MEMORY_RE.match(operand)
    if not match:
        raise ValueError(f"unsupported memory operand: {operand}")
    displacement = match.group("disp").strip()
    label = None
    try:
        offset = int(displacement, 0) if displacement else 0
    except ValueError:
        label = displacement
        if label not in constants:
            constants[label] = 0x400000 + len(constants) * 4
        offset = constants[label]
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
    if instruction.mnemonic in {"movb"}:
        return 1
    if instruction.mnemonic in {"movw"}:
        return 2
    if instruction.mnemonic in {"movl", "vmovss", "vbroadcastss"}:
        return 4
    if instruction.mnemonic in {
        "movq",
        "vmovsd",
        "vmovlps",
        "vmovhps",
        "vbroadcastsd",
    }:
        return 8
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
    mask = (1 << 64) - 1

    def write_flags(result: int, *, cf: bool = False, of: bool = False) -> None:
        value = result & mask
        state["zf"] = value == 0
        state["cf"] = cf
        state["sf"] = bool(value & (1 << 63))
        state["of"] = of

    def write_register(destination_token: str, value: int) -> None:
        destination = canonical_register(destination_token)
        if destination:
            # Every 32-bit general-purpose write zero-extends to 64 bits.
            name = destination_token.lstrip("%").lower()
            width_mask = (
                (1 << 32) - 1
                if name.endswith("d") or name.startswith("e")
                else mask
            )
            registers[destination] = value & width_mask

    mnemonic = instruction.mnemonic
    operands = instruction.operands
    if mnemonic in {"movl", "movq"}:
        write_register(operands[-1], scalar_operand_value(operands[0], registers))
    elif mnemonic == "movslq":
        value = scalar_operand_value(operands[0], registers) & ((1 << 32) - 1)
        write_register(operands[-1], value - (1 << 32) if value & (1 << 31) else value)
    elif mnemonic == "movzbl":
        write_register(operands[-1], scalar_operand_value(operands[0], registers) & 0xFF)
    elif mnemonic in {"addq", "subq"}:
        destination = canonical_register(operands[-1])
        if destination:
            old = scalar_operand_value(operands[-1], registers)
            source = scalar_operand_value(operands[0], registers) & mask
            if mnemonic == "addq":
                full_result = old + source
                result = full_result & mask
                overflow = bool((~(old ^ source) & (old ^ result)) & (1 << 63))
                write_flags(result, cf=full_result > mask, of=overflow)
            else:
                result = (old - source) & mask
                overflow = bool(((old ^ source) & (old ^ result)) & (1 << 63))
                write_flags(result, cf=old < source, of=overflow)
            registers[destination] = result
    elif mnemonic in {"andq", "orq", "xorl", "xorq"}:
        destination = canonical_register(operands[-1])
        if destination:
            left = scalar_operand_value(operands[-1], registers)
            right = scalar_operand_value(operands[0], registers)
            if mnemonic == "andq":
                result = left & right
            elif mnemonic == "orq":
                result = left | right
            else:
                result = left ^ right
            write_register(operands[-1], result)
            write_flags(result)
    elif mnemonic in {"salq", "sarq", "shlq", "shrq"}:
        destination = canonical_register(operands[-1])
        if destination:
            count = scalar_operand_value(operands[0], registers) & 0x3F
            old = scalar_operand_value(operands[-1], registers) & mask
            if count:
                if mnemonic in {"salq", "shlq"}:
                    result = (old << count) & mask
                    carry = bool((old >> (64 - count)) & 1)
                elif mnemonic == "shrq":
                    result = old >> count
                    carry = bool((old >> (count - 1)) & 1)
                else:
                    signed = old - (1 << 64) if old & (1 << 63) else old
                    result = (signed >> count) & mask
                    carry = bool((old >> (count - 1)) & 1)
                registers[destination] = result
                write_flags(result, cf=carry)
    elif mnemonic in {"decq", "incq"}:
        destination = canonical_register(operands[-1])
        if destination:
            old_cf = bool(state["cf"])
            old = scalar_operand_value(operands[-1], registers) & mask
            delta = 1 if mnemonic == "incq" else -1
            result = (old + delta) & mask
            registers[destination] = result
            overflow = (
                old == (1 << 63) - 1
                if mnemonic == "incq"
                else old == (1 << 63)
            )
            write_flags(result, cf=old_cf, of=overflow)
    elif mnemonic in {"negq", "notq"}:
        destination = canonical_register(operands[-1])
        if destination:
            old = scalar_operand_value(operands[-1], registers) & mask
            result = (-old if mnemonic == "negq" else ~old) & mask
            registers[destination] = result
            if mnemonic == "negq":
                write_flags(result, cf=old != 0, of=old == (1 << 63))
    elif mnemonic == "leaq":
        destination = canonical_register(operands[-1])
        address, _ = evaluate_memory(operands[0], registers, labels)
        registers[destination] = address
    elif mnemonic in {"testq", "cmpq"}:
        if mnemonic == "testq":
            left = scalar_operand_value(operands[-1], registers)
            right = scalar_operand_value(operands[0], registers)
            result = left & right
            write_flags(result)
        else:
            source = scalar_operand_value(operands[0], registers) & mask
            destination = scalar_operand_value(operands[-1], registers) & mask
            result = (destination - source) & mask
            overflow = bool(((destination ^ source) & (destination ^ result)) & (1 << 63))
            write_flags(result, cf=destination < source, of=overflow)


def branch_taken(mnemonic: str, state: dict[str, int | bool]) -> bool:
    zf = bool(state["zf"])
    cf = bool(state["cf"])
    sf = bool(state.get("sf", False))
    of = bool(state.get("of", False))
    if mnemonic in UNCONDITIONAL_BRANCHES:
        return True
    if mnemonic in {"je", "jz"}:
        return zf
    if mnemonic in {"jne", "jnz"}:
        return not zf
    if mnemonic in {"jb", "jc", "jnae"}:
        return cf
    if mnemonic in {"jae", "jnb", "jnc"}:
        return not cf
    if mnemonic in {"jbe", "jna"}:
        return cf or zf
    if mnemonic in {"ja", "jnbe"}:
        return not cf and not zf
    if mnemonic in {"jl", "jnge"}:
        return sf != of
    if mnemonic in {"jge", "jnl"}:
        return sf == of
    if mnemonic in {"jle", "jng"}:
        return zf or sf != of
    if mnemonic in {"jg", "jnle"}:
        return not zf and sf == of
    if mnemonic == "jo":
        return of
    if mnemonic == "jno":
        return not of
    if mnemonic == "js":
        return sf
    if mnemonic == "jns":
        return not sf
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
        raise ValueError("x86 AVX-512 kernel requires count > 0 and divisible by 16")
    static, labels = parse_function(assembly, function)
    if uop_kinds_path is None:
        uop_kinds_path = recipe_path.parent.parent / "uops/uop_kinds.yaml"
    recipes = load_recipe(recipe_path, uop_kinds_path)
    registers = {"rdi": 0x100000, "rsi": 0x200000, "rdx": count, "rax": 0, "rcx": 0}
    flags: dict[str, int | bool] = {
        "zf": False,
        "cf": False,
        "sf": False,
        "of": False,
    }
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
        if item.mnemonic in BRANCHES and branch_taken(item.mnemonic, flags):
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
    parser = argparse.ArgumentParser(
        description="Expand an AVX-512 kernel into a dynamic semantic-uop trace"
    )
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
