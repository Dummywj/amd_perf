from __future__ import annotations

import hashlib
import json
import math
from fractions import Fraction
from pathlib import Path
from typing import Any

import yaml

from .model import BoundTrace, ExecutionUop, MacroOp, Resource, VECTOR_RESOURCE_KINDS


class ProfileError(ValueError):
    pass


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


def recipe_key(instruction: dict[str, Any]) -> str:
    operands = instruction.get("operands", [])
    return f"{instruction['mnemonic']}:{','.join(operand_class(value) for value in operands)}"


class Profile:
    def __init__(self, path: Path, data: dict[str, Any], digest: str):
        self.path = path
        self.data = data
        self.digest = digest
        self.id = str(data["profile_id"])
        self.ticks_per_cycle = self._ticks_per_cycle()

    def _ticks_per_cycle(self) -> int:
        denominators = [1]

        def visit(value: Any) -> None:
            if isinstance(value, dict):
                for nested in value.values():
                    visit(nested)
            elif isinstance(value, list):
                for nested in value:
                    visit(nested)
            elif isinstance(value, (int, float)) and not isinstance(value, bool):
                denominators.append(Fraction(str(value)).denominator)

        visit(self.data)
        bandwidth_entries = list(self.data["resources"].values())
        bandwidth_entries.extend(self.data["memory"]["levels"].values())
        bandwidth_entries.append(self.data["memory"]["dram"])
        for resource in bandwidth_entries:
            for key in ("bytes_per_cycle", "read_bytes_per_cycle", "write_bytes_per_cycle"):
                bytes_per_cycle = resource.get(key)
                if isinstance(bytes_per_cycle, (int, float)):
                    for width in (4, 16, 32, 64):
                        denominators.append(
                            (Fraction(width, 1) / Fraction(str(bytes_per_cycle))).denominator
                        )
        result = 1
        for denominator in denominators:
            if isinstance(denominator, Fraction):
                denominator = denominator.denominator
            result = math.lcm(result, int(denominator))
        return result

    def ticks(self, cycles: int | float) -> int:
        value = Fraction(str(cycles)) * self.ticks_per_cycle
        if value.denominator != 1:
            raise ProfileError(f"{cycles} cycles cannot be represented in integer ticks")
        return value.numerator

    @property
    def pipeline(self) -> dict[str, int | float]:
        return self.data["pipeline"]

    @property
    def l1_latency_ticks(self) -> int:
        return self.ticks(self.data["memory"]["levels"]["l1d"]["latency_cycles"])

    def bind(self, trace: dict[str, Any]) -> BoundTrace:
        if trace.get("trace_version") != 2:
            raise ProfileError("simulator requires dynamic trace_version 2")
        resources = self._resources()
        macros: list[MacroOp] = []
        uops: list[ExecutionUop] = []
        result_uops: dict[str, tuple[ExecutionUop, ...]] = {}

        for instruction in trace["instructions"]:
            key = recipe_key(instruction)
            recipe = self.data["recipes"].get(key)
            semantic_kinds = tuple(
                semantic["kind"] for semantic in instruction["semantic_uops"]
            )
            if recipe is None:
                recipe = self._fallback_recipe(semantic_kinds, key)
            local_ids: dict[str, str] = {}
            execution: list[ExecutionUop] = []
            for local_index, entry in enumerate(recipe["uops"]):
                uop_id = f"{instruction['id']}.e{local_index}"
                local_ids[entry["id"]] = uop_id
                memory = (
                    instruction.get("memory")
                    if entry["kind"] in {"load_data", "store_data", "address_generation"}
                    else None
                )
                occupancy = self.ticks(entry["resource_occupancy_cycles"])
                latency = self.ticks(entry["latency_cycles"])
                if entry["kind"] == "load_data":
                    latency = self.l1_latency_ticks
                execution.append(
                    ExecutionUop(
                        id=uop_id,
                        sequence=len(uops) + len(execution),
                        parent_id=instruction["id"],
                        parent_sequence=instruction["sequence"],
                        mnemonic=instruction["mnemonic"],
                        assembly=instruction["assembly"],
                        semantic_kinds=semantic_kinds,
                        kind=entry["kind"],
                        scheduling_class=(
                            f"{key}:{entry['id']}:part-{entry['part_index']}"
                            if "part_index" in entry
                            else f"{key}:{entry['id']}"
                        ),
                        part_index=entry.get("part_index"),
                        latency_ticks=latency,
                        issue_interval_ticks=self.ticks(entry["issue_interval_cycles"])
                        * (
                            int(recipe["vector_decomposition"]["parts"])
                            if "part_index" in entry and recipe.get("vector_decomposition")
                            else 1
                        ),
                        occupancy_ticks=occupancy,
                        resource_choices=tuple(entry["resource_choices"]),
                        issue_domains=tuple(entry.get("issue_domains", [])),
                        memory=memory,
                    )
                )

            for local_index, (entry, uop) in enumerate(zip(recipe["uops"], execution)):
                uop.dependencies.update(local_ids[value] for value in entry.get("depends_on", []))
                part_index = entry.get("part_index")
                if part_index and recipe.get("vector_decomposition"):
                    previous = next(
                        (
                            candidate
                            for candidate, candidate_entry in zip(execution, recipe["uops"])
                            if candidate_entry.get("part_index") == part_index - 1
                        ),
                        None,
                    )
                    if previous:
                        uop.issue_after_uop = previous.id
                        uop.issue_gap_ticks = self.ticks(
                            recipe["vector_decomposition"]["part_issue_gap_cycles"]
                        )
                self._add_external_dependencies(
                    uop, instruction, result_uops, local_index == 0
                )

            uops.extend(execution)
            depended_locals = {
                dependency
                for entry in recipe["uops"]
                for dependency in entry.get("depends_on", [])
            }
            result_uops[instruction["id"]] = tuple(
                uop
                for entry, uop in zip(recipe["uops"], execution)
                if entry["id"] not in depended_locals
            )
            kinds = {uop.kind for uop in execution}
            macros.append(
                MacroOp(
                    id=instruction["id"],
                    sequence=instruction["sequence"],
                    mnemonic=instruction["mnemonic"],
                    assembly=instruction["assembly"],
                    uop_ids=tuple(uop.id for uop in execution),
                    decoded_macro_ops=int(recipe["decoded_macro_ops"]),
                    retire_macro_ops=int(recipe["retire_macro_ops"]),
                    uses_vector_scheduler=bool(kinds & VECTOR_RESOURCE_KINDS),
                    uses_load_queue="load_data" in kinds,
                    uses_store_queue="store_data" in kinds,
                )
            )
        return BoundTrace(
            trace_version=2,
            profile_id=self.id,
            profile_sha256=self.digest,
            ticks_per_cycle=self.ticks_per_cycle,
            macros=macros,
            uops=uops,
            resources=resources,
            workload=trace["workload"],
            source_trace=trace,
        )

    def _add_external_dependencies(
        self,
        uop: ExecutionUop,
        instruction: dict[str, Any],
        result_uops: dict[str, tuple[ExecutionUop, ...]],
        first_local: bool,
    ) -> None:
        register_dependencies = instruction.get("register_dependencies", {})
        address_registers = set((instruction.get("memory") or {}).get("address_registers", []))
        producer_ids: set[str] = set()
        if uop.kind == "address_generation":
            producer_ids.update(
                producer
                for register, producer in register_dependencies.items()
                if register in address_registers
            )
        elif uop.kind == "load_data":
            producer_ids.update(instruction.get("memory_dependencies", []))
            if first_local:
                producer_ids.update(register_dependencies.values())
        elif uop.kind == "store_data":
            producer_ids.update(register_dependencies.values())
            producer_ids.update(instruction.get("memory_dependencies", []))
        else:
            producer_ids.update(register_dependencies.values())
            producer_ids.update(instruction.get("memory_dependencies", []))
            if instruction.get("flags_dependency"):
                producer_ids.add(instruction["flags_dependency"])
        for producer in producer_ids:
            if producer not in result_uops:
                raise ProfileError(f"unknown producer instruction: {producer}")
            candidates = result_uops[producer]
            matching = tuple(
                candidate
                for candidate in candidates
                if uop.part_index is not None
                and candidate.part_index == uop.part_index
            )
            uop.dependencies.update(
                candidate.id for candidate in (matching if matching else candidates)
            )

    def _fallback_recipe(self, semantic_kinds: tuple[str, ...], key: str) -> dict[str, Any]:
        fit = self.data["scalar_control_fit"]
        if not fit["enabled"] or len(semantic_kinds) != 1:
            raise ProfileError(f"missing instruction recipe: {key}")
        semantic = semantic_kinds[0]
        timing = fit["uops"].get(semantic)
        if timing is None:
            raise ProfileError(f"missing instruction recipe and fallback: {key} ({semantic})")
        return {
            "decoded_macro_ops": 1,
            "retire_macro_ops": 1,
            "uops": [{"id": "fit", "kind": semantic, **timing}],
        }

    def _resources(self) -> dict[str, Resource]:
        result: dict[str, Resource] = {}
        for resource_id, entry in self.data["resources"].items():
            result[resource_id] = Resource(
                id=resource_id,
                capacity=int(entry["capacity"]),
                bytes_per_cycle=(
                    int(entry["bytes_per_cycle"])
                    if "bytes_per_cycle" in entry
                    else None
                ),
            )
        for resource_id, entry in self.data["scalar_control_fit"]["resources"].items():
            result[resource_id] = Resource(resource_id, int(entry["capacity"]))
        for recipe in self.data["recipes"].values():
            for uop in recipe["uops"]:
                for resource_id in uop["resource_choices"]:
                    if resource_id not in result:
                        raise ProfileError(f"recipe references missing resource: {resource_id}")
        for uop in self.data["scalar_control_fit"]["uops"].values():
            for resource_id in uop["resource_choices"]:
                if resource_id not in result:
                    raise ProfileError(f"fit references missing resource: {resource_id}")
        for recipe in self.data["recipes"].values():
            for uop in recipe["uops"]:
                for domain_id in uop.get("issue_domains", []):
                    if domain_id not in self.data["issue_domains"]:
                        raise ProfileError(f"recipe references missing issue domain: {domain_id}")
        return result


def load_profile(path: Path, schema_path: Path | None = None) -> Profile:
    raw = path.read_bytes()
    data = yaml.safe_load(raw)
    if not isinstance(data, dict):
        raise ProfileError("profile top level must be a mapping")
    if schema_path is not None:
        try:
            from jsonschema import Draft202012Validator
        except ModuleNotFoundError as error:
            raise ProfileError("jsonschema is required for profile validation") from error
        schema = json.loads(schema_path.read_text(encoding="utf-8"))
        errors = sorted(
            Draft202012Validator(schema).iter_errors(data), key=lambda error: list(error.path)
        )
        if errors:
            first = errors[0]
            location = "/".join(str(value) for value in first.path)
            raise ProfileError(f"profile schema violation at {location}: {first.message}")
    return Profile(path, data, hashlib.sha256(raw).hexdigest())
