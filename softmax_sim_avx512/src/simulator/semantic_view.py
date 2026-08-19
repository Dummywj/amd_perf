from __future__ import annotations

import re
from collections import defaultdict
from typing import Any

from .engine import SimulationResult
from .model import ExecutionUop
from .semantic import SEMANTIC_RESOURCES, semantic_id


class SemanticViewError(ValueError):
    pass


def build_semantic_view_model(
    result: SimulationResult,
    instruction_start: int = 0,
    instruction_limit: int | None = None,
) -> dict[str, Any]:
    end = (
        instruction_start + instruction_limit
        if instruction_limit is not None
        else len(result.trace.macros)
    )
    macros = [
        macro
        for macro in result.trace.macros
        if instruction_start <= macro.sequence < end
    ]
    selected_instruction_ids = {macro.id for macro in macros}
    source_instructions = {
        str(instruction["id"]): instruction
        for instruction in result.trace.source_trace.get("instructions", [])
    }
    missing_sources = [macro.id for macro in macros if macro.id not in source_instructions]
    if missing_sources:
        raise SemanticViewError(
            "source trace is missing dynamic instructions: " + ", ".join(missing_sources)
        )

    execution_uops = [
        uop for uop in result.trace.uops if uop.parent_id in selected_instruction_ids
    ]
    execution_by_id = {uop.id: uop for uop in result.trace.uops}
    selected_execution_ids = {uop.id for uop in execution_uops}
    execution_by_semantic: dict[str, list[ExecutionUop]] = defaultdict(list)
    for uop in execution_uops:
        if len(uop.semantic_ids) != 1:
            raise SemanticViewError(
                f"{uop.id}: expected exactly one semantic parent, got {uop.semantic_ids}"
            )
        execution_by_semantic[uop.semantic_ids[0]].append(uop)

    instruction_nodes: list[dict[str, Any]] = []
    semantic_nodes: list[dict[str, Any]] = []
    semantic_definition_by_id: dict[str, dict[str, Any]] = {}
    for macro in macros:
        source = source_instructions[macro.id]
        semantic_definitions = source.get("semantic_uops", [])
        semantic_ids = [
            semantic_id(macro.id, str(definition["local_id"]))
            for definition in semantic_definitions
        ]
        for current_id, definition in zip(semantic_ids, semantic_definitions):
            semantic_definition_by_id[current_id] = definition
        operands = _semantic_operands(source, semantic_definitions)
        macro_uops = [execution_by_id[uop_id] for uop_id in macro.uop_ids]
        first_issue = _minimum_tick(uop.issue_tick for uop in macro_uops)
        instruction_nodes.append(
            {
                "id": macro.id,
                "node_type": "instruction",
                "sequence": macro.sequence,
                "mnemonic": macro.mnemonic,
                "assembly": macro.assembly,
                "semantic_ids": semantic_ids,
                "execution_uop_count": len(macro_uops),
                "dispatch_domains": list(macro.dispatch_domains),
                "dispatch_domain_demands": dict(
                    sorted(macro.dispatch_domain_demands.items())
                ),
                "rename_allocations": dict(
                    sorted(macro.rename_allocations.items())
                ),
                "dispatch_blocker": macro.dispatch_blocker,
                "dispatch_blocker_domain": macro.dispatch_blocker_domain,
                "dispatch_blocker_count": macro.dispatch_blocker_count,
                "timing": _timing(
                    macro.dispatch_tick,
                    first_issue,
                    macro.complete_tick,
                    macro.retire_tick,
                ),
                "source_line": source.get("source_line"),
                "static_index": source.get("static_index"),
                "depends_on_instruction_ids": source.get(
                    "depends_on_instructions", []
                ),
            }
        )
        for current_id, definition, operand_pair in zip(
            semantic_ids, semantic_definitions, operands
        ):
            children = sorted(
                execution_by_semantic.get(current_id, []), key=lambda uop: uop.sequence
            )
            if not children:
                raise SemanticViewError(
                    f"{current_id}: semantic uop has no execution implementation"
                )
            semantic_nodes.append(
                {
                    "id": current_id,
                    "node_type": "semantic",
                    "parent_id": macro.id,
                    "sequence": len(semantic_nodes),
                    "kind": str(definition["kind"]),
                    "abstract_resource": SEMANTIC_RESOURCES.get(
                        str(definition["kind"]), "unknown"
                    ),
                    "execution_uop_ids": [uop.id for uop in children],
                    "source_operands": operand_pair[0],
                    "destination_operands": operand_pair[1],
                    "effects": _effects(str(definition["kind"])),
                    "timing": _timing(
                        macro.dispatch_tick,
                        _minimum_tick(uop.issue_tick for uop in children),
                        _maximum_tick(uop.complete_tick for uop in children),
                        macro.retire_tick,
                    ),
                    "provenance": {
                        "isa": result.trace.source_trace.get("isa", "unknown"),
                        "mnemonic": macro.mnemonic,
                        "assembly": macro.assembly,
                        "source_line": source.get("source_line"),
                    },
                }
            )

    execution_nodes = [
        _execution_node(uop, result)
        for uop in execution_uops
    ]
    macro_by_id = {macro.id: macro for macro in macros}
    for node, uop in zip(execution_nodes, execution_uops):
        node["timing"]["retire_tick"] = macro_by_id[uop.parent_id].retire_tick

    semantic_edges: dict[tuple[str, str, str], dict[str, str]] = {}
    execution_edges: dict[tuple[str, str, str], dict[str, str]] = {}
    for uop in execution_uops:
        for producer_id in sorted(uop.dependencies):
            if producer_id not in selected_execution_ids:
                continue
            producer = execution_by_id[producer_id]
            kind = _dependency_kind(
                producer.parent_id, uop.parent_id, source_instructions[uop.parent_id]
            )
            edge = {"source": producer_id, "target": uop.id, "kind": kind}
            execution_edges[(producer_id, uop.id, kind)] = edge
            for producer_semantic in producer.semantic_ids:
                for consumer_semantic in uop.semantic_ids:
                    if producer_semantic == consumer_semantic:
                        continue
                    semantic_edge = {
                        "source": producer_semantic,
                        "target": consumer_semantic,
                        "kind": kind,
                    }
                    semantic_edges[
                        (producer_semantic, consumer_semantic, kind)
                    ] = semantic_edge
        if uop.issue_after_uop and uop.issue_after_uop in selected_execution_ids:
            edge = {
                "source": uop.issue_after_uop,
                "target": uop.id,
                "kind": "part_order",
            }
            execution_edges[(edge["source"], edge["target"], edge["kind"])] = edge

    for current_id, definition in semantic_definition_by_id.items():
        instruction_id = current_id.split(".", 1)[0]
        for local_dependency in definition.get("depends_on_local", []):
            producer_id = semantic_id(instruction_id, str(local_dependency))
            if producer_id == current_id:
                continue
            edge = {"source": producer_id, "target": current_id, "kind": "internal"}
            semantic_edges[(producer_id, current_id, "internal")] = edge

    semantic_dependencies: dict[str, set[str]] = defaultdict(set)
    for edge in semantic_edges.values():
        semantic_dependencies[edge["target"]].add(edge["source"])
    for node in semantic_nodes:
        node["dependency_ids"] = sorted(semantic_dependencies[node["id"]])

    return {
        "view_model_version": 1,
        "metadata": {
            "title": "Semantic uop schedule",
            "profile_id": result.trace.profile_id,
            "profile_sha256": result.trace.profile_sha256,
            "execution_model": result.execution_model,
            "cache_mode": result.cache_mode,
            "ticks_per_cycle": result.ticks_per_cycle,
            "total_ticks": result.total_ticks,
            "cycles": result.cycles,
            "workload": result.trace.workload,
            "dispatch_domains": result.summary.get("dispatch_domain_stats", {}),
            "instruction_start": instruction_start,
            "instruction_count": len(instruction_nodes),
        },
        "instructions": instruction_nodes,
        "semantic_uops": semantic_nodes,
        "execution_uops": execution_nodes,
        "dependencies": {
            "semantic": sorted(
                semantic_edges.values(),
                key=lambda edge: (edge["target"], edge["source"], edge["kind"]),
            ),
            "execution": sorted(
                execution_edges.values(),
                key=lambda edge: (edge["target"], edge["source"], edge["kind"]),
            ),
        },
    }


def _execution_node(uop: ExecutionUop, result: SimulationResult) -> dict[str, Any]:
    return {
        "id": uop.id,
        "node_type": "execution",
        "parent_id": uop.semantic_ids[0],
        "instruction_id": uop.parent_id,
        "sequence": uop.sequence,
        "kind": uop.kind,
        "scheduling_class": uop.scheduling_class,
        "part_index": uop.part_index,
        "resource": uop.resource,
        "resource_lane": uop.resource_lane,
        "resource_choices": list(uop.resource_choices),
        "issue_domains": list(uop.issue_domains),
        "issue_domain_demands": dict(sorted(uop.issue_domain_demands.items())),
        "latency_ticks": uop.latency_ticks,
        "issue_interval_ticks": uop.issue_interval_ticks,
        "occupancy_ticks": uop.occupancy_ticks,
        "latency_cycles": uop.latency_ticks / result.ticks_per_cycle,
        "issue_interval_cycles": uop.issue_interval_ticks / result.ticks_per_cycle,
        "occupancy_cycles": uop.occupancy_ticks / result.ticks_per_cycle,
        "memory_level": uop.memory_level,
        "stall_reason": uop.stall_reason,
        "stall_reasons": dict(sorted(uop.stall_reasons.items())),
        "dependency_ids": sorted(uop.dependencies),
        "vector_state_dependencies": sorted(uop.vector_state_dependencies),
        "old_destination_dependencies": sorted(
            uop.old_destination_dependencies
        ),
        "requires_vector_state": uop.requires_vector_state,
        "reads_old_destination": uop.reads_old_destination,
        "issue_after_uop": uop.issue_after_uop,
        "timing": _timing(
            uop.dispatch_tick, uop.issue_tick, uop.complete_tick, None
        )
        | {"ready_tick": uop.ready_tick},
    }


def _timing(
    dispatch_tick: int | None,
    issue_tick: int | None,
    complete_tick: int | None,
    retire_tick: int | None,
) -> dict[str, int | None]:
    return {
        "dispatch_tick": dispatch_tick,
        "issue_tick": issue_tick,
        "complete_tick": complete_tick,
        "retire_tick": retire_tick,
    }


def _minimum_tick(values: Any) -> int | None:
    present = [value for value in values if value is not None]
    return min(present) if present else None


def _maximum_tick(values: Any) -> int | None:
    present = [value for value in values if value is not None]
    return max(present) if present else None


def _dependency_kind(
    producer_instruction_id: str,
    consumer_instruction_id: str,
    consumer: dict[str, Any],
) -> str:
    if producer_instruction_id == consumer_instruction_id:
        return "internal"
    if producer_instruction_id in consumer.get("memory_dependencies", []):
        return "memory"
    if producer_instruction_id == consumer.get("flags_dependency"):
        return "flags"
    return "register"


def _semantic_operands(
    instruction: dict[str, Any], semantic_definitions: list[dict[str, Any]]
) -> list[tuple[list[dict[str, Any]], list[dict[str, Any]]]]:
    instruction_id = str(instruction["id"])
    memory = instruction.get("memory")
    address_registers = set((memory or {}).get("address_registers", []))
    register_dependencies = instruction.get("register_dependencies", {})
    register_reads = [
        _register_operand(
            register,
            register_dependencies.get(register, "entry"),
            instruction,
            False,
        )
        for register in instruction.get("register_reads", [])
    ]
    data_register_reads = [
        operand
        for register, operand in zip(instruction.get("register_reads", []), register_reads)
        if register not in address_registers
    ]
    register_writes = [
        _register_operand(register, instruction_id, instruction, True)
        for register in instruction.get("register_writes", [])
    ]
    immediates = [
        _immediate_operand(value)
        for value in instruction.get("operands", [])
        if str(value).strip().startswith("$")
    ]
    local_outputs: dict[str, list[dict[str, Any]]] = {}
    result: list[tuple[list[dict[str, Any]], list[dict[str, Any]]]] = []
    last_index = len(semantic_definitions) - 1
    for index, definition in enumerate(semantic_definitions):
        local_id = str(definition["local_id"])
        current_id = semantic_id(instruction_id, local_id)
        kind = str(definition["kind"])
        dependency_outputs = [
            operand
            for dependency in definition.get("depends_on_local", [])
            for operand in local_outputs.get(str(dependency), [])
        ]
        sources: list[dict[str, Any]]
        destinations: list[dict[str, Any]]
        if kind == "address_generation":
            sources = [
                operand
                for register, operand in zip(
                    instruction.get("register_reads", []), register_reads
                )
                if register in address_registers
            ] + immediates
            destinations = [_address_operand(current_id, memory)]
        elif kind in {"vector_load", "scalar_load"}:
            sources = dependency_outputs + ([_memory_operand(memory)] if memory else [])
            destinations = (
                register_writes
                if index == last_index and register_writes
                else [_temporary_operand(current_id, kind, instruction, memory)]
            )
        elif kind in {"vector_store", "scalar_store"}:
            sources = dependency_outputs + data_register_reads + immediates
            destinations = [_memory_operand(memory)] if memory else []
        elif kind in {"branch", "return"}:
            sources = data_register_reads + immediates
            flags_dependency = instruction.get("flags_dependency")
            if flags_dependency:
                sources.append(
                    {
                        "id": f"flags@{flags_dependency}",
                        "kind": "flags",
                        "data_type": "flags",
                        "element_bits": None,
                        "lane_count": 1,
                        "width_bits": None,
                        "location": "flags",
                    }
                )
            destinations = [
                {
                    "id": f"control@{instruction_id}",
                    "kind": "control",
                    "data_type": "control",
                    "element_bits": None,
                    "lane_count": 1,
                    "width_bits": None,
                    "location": (
                        instruction.get("operands", [])[-1]
                        if instruction.get("operands")
                        else "exit"
                    ),
                }
            ]
        elif kind == "vector_config":
            sources = data_register_reads + immediates
            destinations = [
                {
                    "id": f"vector_state@{instruction_id}",
                    "kind": "vector_state",
                    "data_type": "vector_state",
                    "element_bits": None,
                    "lane_count": "runtime",
                    "width_bits": None,
                    "location": "vector state",
                }
            ]
        else:
            sources = data_register_reads + dependency_outputs + immediates
            destinations = (
                register_writes
                if index == last_index and register_writes
                else [_temporary_operand(current_id, kind, instruction, memory)]
            )
        sources = _unique_operands(sources)
        destinations = _unique_operands(destinations)
        local_outputs[local_id] = destinations
        result.append((sources, destinations))
    return result


def _register_operand(
    register: str,
    version: str,
    instruction: dict[str, Any],
    is_destination: bool,
) -> dict[str, Any]:
    bits, element_bits, lanes, data_type = _data_shape(instruction, None, register)
    explicit_bits = _register_bits(register, instruction, is_destination)
    if explicit_bits is not None:
        bits = explicit_bits
        element_bits = 32
        lanes = max(1, bits // element_bits)
    mnemonic = str(instruction.get("mnemonic", "")).lower()
    if mnemonic.endswith("ss"):
        bits, element_bits, lanes, data_type = 32, 32, 1, "fp32"
    elif mnemonic.startswith(("vcvttps2dq", "vcvtps2dq")):
        data_type = "i32" if is_destination else "fp32"
    elif mnemonic.startswith("vcvtdq2ps"):
        data_type = "fp32" if is_destination else "i32"
    kind = "vector" if register.startswith(("xmm", "ymm", "zmm", "v")) else "scalar"
    return {
        "id": f"{register}@{version}",
        "kind": kind,
        "data_type": data_type,
        "element_bits": element_bits,
        "lane_count": lanes,
        "width_bits": bits,
        "location": register,
        "version_role": "write" if is_destination else "read",
    }


def _register_bits(
    register: str, instruction: dict[str, Any], is_destination: bool
) -> int | None:
    match = re.search(r"(\d+)$", register)
    if not match or not register.startswith(("xmm", "ymm", "zmm")):
        return None
    aliases = re.findall(
        rf"%([xyz]mm){re.escape(match.group(1))}\b",
        str(instruction.get("assembly", "")).lower(),
    )
    if not aliases:
        return None
    widths = {"xmm": 128, "ymm": 256, "zmm": 512}
    candidates = [widths[alias] for alias in aliases]
    return min(candidates) if is_destination else max(candidates)


def _temporary_operand(
    current_id: str,
    semantic_kind: str,
    instruction: dict[str, Any],
    memory: dict[str, Any] | None,
) -> dict[str, Any]:
    bits, element_bits, lanes, data_type = _data_shape(
        instruction, semantic_kind, None, memory
    )
    vector = semantic_kind.startswith("vector_")
    return {
        "id": f"{current_id}.value",
        "kind": "temporary_vector" if vector else "temporary_scalar",
        "data_type": data_type,
        "element_bits": element_bits,
        "lane_count": lanes,
        "width_bits": bits,
        "location": "internal",
    }


def _address_operand(current_id: str, memory: dict[str, Any] | None) -> dict[str, Any]:
    location = "effective address"
    if memory:
        location = f"{memory.get('region', 'memory')}+{memory.get('offset', 0)}"
    return {
        "id": f"{current_id}.address",
        "kind": "address",
        "data_type": "pointer",
        "element_bits": None,
        "lane_count": 1,
        "width_bits": 64,
        "location": location,
    }


def _memory_operand(memory: dict[str, Any] | None) -> dict[str, Any]:
    if not memory:
        return {
            "id": "memory:unknown",
            "kind": "memory",
            "data_type": "unknown",
            "element_bits": None,
            "lane_count": None,
            "width_bits": None,
            "location": "unknown",
        }
    width = int(memory["bytes"]) * 8
    lanes = width // 32 if width >= 32 else 1
    location = f"{memory.get('region', 'memory')}+{memory.get('offset', 0)}"
    return {
        "id": f"memory:{location}",
        "kind": "memory",
        "data_type": "fp32",
        "element_bits": 32,
        "lane_count": lanes,
        "width_bits": width,
        "location": location,
    }


def _immediate_operand(value: str) -> dict[str, Any]:
    token = str(value).strip()
    return {
        "id": f"immediate:{token}",
        "kind": "immediate",
        "data_type": "integer",
        "element_bits": None,
        "lane_count": 1,
        "width_bits": None,
        "location": token,
    }


def _data_shape(
    instruction: dict[str, Any],
    semantic_kind: str | None,
    register: str | None,
    memory: dict[str, Any] | None = None,
) -> tuple[int | None, int | None, int | str | None, str]:
    mnemonic = str(instruction.get("mnemonic", "")).lower()
    assembly = str(instruction.get("assembly", "")).lower()
    if semantic_kind == "address_generation":
        return 64, None, 1, "pointer"
    if memory and semantic_kind in {
        "vector_load",
        "vector_store",
        "scalar_load",
        "scalar_store",
    }:
        bits = int(memory["bytes"]) * 8
    elif (register and register.startswith("zmm")) or re.search(r"%zmm\d+", assembly):
        bits = 512
    elif (register and register.startswith("ymm")) or re.search(r"%ymm\d+", assembly):
        bits = 256
    elif (register and register.startswith("xmm")) or re.search(r"%xmm\d+", assembly):
        bits = 32 if mnemonic.endswith("ss") else 128
    elif mnemonic.endswith("q") or (register and register.startswith("r")):
        bits = 64
    elif mnemonic.endswith("l") or (register and register.startswith("e")):
        bits = 32
    else:
        bits = 32
    vector = bool(semantic_kind and semantic_kind.startswith("vector_")) or bits >= 128
    integer = bool(
        semantic_kind in {"vector_integer", "vector_shift"}
        or mnemonic.startswith(("vp", "cmp", "test"))
    )
    data_type = "i32" if integer else "fp32" if "ss" in mnemonic or vector else "i64"
    element_bits = 32 if vector or data_type in {"i32", "fp32"} else bits
    lanes = bits // element_bits if bits is not None and element_bits else 1
    return bits, element_bits, lanes, data_type


def _unique_operands(values: list[dict[str, Any]]) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    seen: set[str] = set()
    for operand in values:
        if operand["id"] in seen:
            continue
        seen.add(operand["id"])
        result.append(operand)
    return result


def _effects(kind: str) -> dict[str, bool]:
    return {
        "reads_memory": kind in {"vector_load", "scalar_load"},
        "writes_memory": kind in {"vector_store", "scalar_store"},
        "reads_flags": kind in {"branch", "return"},
        "writes_flags": kind == "scalar_alu",
        "changes_control_flow": kind in {"branch", "return"},
    }
