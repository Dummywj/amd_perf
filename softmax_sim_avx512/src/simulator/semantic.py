from __future__ import annotations

from typing import Any


class SemanticBindingError(ValueError):
    pass


# The semantic vocabulary is ISA-neutral. This table only bridges semantic
# classes to the equivalent execution classes used by a profile recipe.
SEMANTIC_EXECUTION_KINDS: dict[str, frozenset[str]] = {
    "scalar_alu": frozenset({"scalar_alu"}),
    "scalar_load": frozenset({"load_data"}),
    "scalar_store": frozenset({"store_data"}),
    "scalar_fp_add": frozenset({"scalar_fp_add", "scalar_fp"}),
    "scalar_fp_div": frozenset({"scalar_fp_div", "scalar_fp"}),
    "scalar_move": frozenset({"scalar_move", "scalar_alu"}),
    "branch": frozenset({"branch"}),
    "return": frozenset({"return", "branch"}),
    "vector_config": frozenset({"vector_config", "vector_integer"}),
    "address_generation": frozenset({"address_generation"}),
    "vector_load": frozenset({"load_data"}),
    "vector_store": frozenset({"store_data"}),
    "vector_broadcast": frozenset({"vector_fp", "vector_integer"}),
    "vector_move": frozenset({"vector_fp", "vector_integer"}),
    "vector_fp_add": frozenset({"vector_fp"}),
    "vector_fp_sub": frozenset({"vector_fp"}),
    "vector_fp_mul": frozenset({"vector_fp"}),
    "vector_fp_fma": frozenset({"vector_fp"}),
    "vector_fp_max": frozenset({"vector_fp"}),
    "vector_reduce_add": frozenset({"vector_fp"}),
    "vector_reduce_max": frozenset({"vector_fp"}),
    "vector_convert": frozenset({"conversion"}),
    "vector_integer": frozenset({"vector_integer"}),
    "vector_shift": frozenset({"vector_integer"}),
    "vector_shuffle": frozenset({"shuffle"}),
}


SEMANTIC_RESOURCES: dict[str, str] = {
    "scalar_alu": "scalar integer ALU",
    "scalar_load": "load data path",
    "scalar_store": "store data path",
    "scalar_fp_add": "scalar FP add/sub",
    "scalar_fp_div": "scalar FP divide",
    "scalar_move": "scalar integer ALU",
    "branch": "branch unit",
    "return": "branch unit",
    "vector_config": "vector control",
    "address_generation": "address generation unit",
    "vector_load": "load data path",
    "vector_store": "store data path",
    "vector_broadcast": "vector move/broadcast",
    "vector_move": "vector move",
    "vector_fp_add": "vector FP add/sub",
    "vector_fp_sub": "vector FP add/sub",
    "vector_fp_mul": "vector FP multiply",
    "vector_fp_fma": "vector FP FMA",
    "vector_fp_max": "vector FP compare/max",
    "vector_reduce_add": "vector FP reduction",
    "vector_reduce_max": "vector FP reduction",
    "vector_convert": "vector conversion",
    "vector_integer": "vector integer ALU",
    "vector_shift": "vector integer shift",
    "vector_shuffle": "vector shuffle",
}


def semantic_id(instruction_id: str, local_id: str) -> str:
    suffix = f"s{local_id[1:]}" if local_id.startswith("u") else local_id
    return f"{instruction_id}.{suffix}"


def bind_execution_semantics(
    instruction: dict[str, Any], execution_entries: list[dict[str, Any]]
) -> list[tuple[str, ...]]:
    instruction_id = str(instruction["id"])
    semantic_uops = instruction.get("semantic_uops", [])
    semantics = [
        (
            semantic_id(instruction_id, str(entry["local_id"])),
            str(entry["kind"]),
        )
        for entry in semantic_uops
    ]
    if not semantics:
        raise SemanticBindingError(f"{instruction_id}: instruction has no semantic uops")

    result: list[tuple[str, ...]] = []
    covered: set[str] = set()
    for execution in execution_entries:
        execution_kind = str(execution["kind"])
        candidates = [
            current_id
            for current_id, semantic_kind in semantics
            if execution_kind in SEMANTIC_EXECUTION_KINDS.get(semantic_kind, frozenset())
        ]
        if len(candidates) != 1:
            detail = ", ".join(
                f"{current_id}:{semantic_kind}" for current_id, semantic_kind in semantics
            )
            reason = "no compatible" if not candidates else "ambiguous"
            raise SemanticBindingError(
                f"{instruction_id}: {reason} semantic mapping for execution uop "
                f"{execution.get('id', '?')}:{execution_kind}; semantics=[{detail}]"
            )
        result.append((candidates[0],))
        covered.add(candidates[0])

    missing = [current_id for current_id, _ in semantics if current_id not in covered]
    if missing:
        raise SemanticBindingError(
            f"{instruction_id}: semantic uops have no execution implementation: "
            f"{', '.join(missing)}"
        )
    return result
