from __future__ import annotations

import copy
import hashlib
import json
import math
import re
from fractions import Fraction
from pathlib import Path
from typing import Any

import yaml

from .model import BoundTrace, ExecutionUop, MacroOp, Resource, VECTOR_RESOURCE_KINDS
from .semantic import (
    SEMANTIC_EXECUTION_KINDS,
    SemanticBindingError,
    bind_execution_semantics,
    semantic_id,
)


class ProfileError(ValueError):
    pass


def operand_class(operand: str) -> str:
    token = operand.strip().lower()
    for register_class in ("zmm", "ymm", "xmm"):
        if f"%{register_class}" in token:
            return register_class
    if "(" in token or "[" in token:
        return "memory"
    if token.startswith("$") or re.fullmatch(r"[-+]?(?:0x[0-9a-f]+|\d+)", token):
        return "immediate"
    if re.fullmatch(r"v(?:[0-9]|[12][0-9]|3[01])", token):
        return "vector"
    if re.fullmatch(
        r"f(?:t(?:[0-9]|1[01])|s(?:[0-9]|1[01])|a[0-7])", token
    ):
        return "fp_register"
    if re.fullmatch(
        r"(?:zero|ra|sp|gp|tp|t[0-6]|s(?:[0-9]|1[01])|a[0-7])",
        token,
    ):
        return "register"
    if "%" in token:
        return "register"
    return "other"


def recipe_key(instruction: dict[str, Any]) -> str:
    operands = instruction.get("operands", [])
    return f"{instruction['mnemonic']}:{','.join(operand_class(value) for value in operands)}"


def recipe_keys(instruction: dict[str, Any]) -> tuple[str, ...]:
    """Return explicit, operand-derived and frontend-form recipe candidates."""
    candidates: list[str] = []
    explicit = instruction.get("profile_recipe")
    if explicit:
        candidates.append(str(explicit))
    candidates.append(recipe_key(instruction))
    form = instruction.get("form")
    if form:
        candidates.append(f"{instruction['mnemonic']}:{form}")
    return tuple(dict.fromkeys(candidates))


class Profile:
    def __init__(self, path: Path, data: dict[str, Any], digest: str):
        self.path = path
        self.data = data
        self.digest = digest
        self.id = str(data["profile_id"])
        self._validate_isa()
        self._validate_backend_topology()
        self._validate_vector_dependency_policy()
        self._validate_evidence_sources()
        overlap_kinds = set(
            self.memory_compute_overlap_limit["compute_semantic_kinds"]
        )
        unknown_overlap_kinds = overlap_kinds - SEMANTIC_EXECUTION_KINDS.keys()
        if unknown_overlap_kinds:
            raise ProfileError(
                "unknown memory-compute semantic kinds: "
                + ", ".join(sorted(unknown_overlap_kinds))
            )
        self._validate_issue_domains()
        self._validate_dispatch_domains()
        self.unresolved_parameters = tuple(self._find_unresolved_parameters())
        self.ticks_per_cycle = self._ticks_per_cycle()

    def _validate_evidence_sources(self) -> None:
        source_ids = [
            str(source["id"]) for source in self.data["metadata"]["sources"]
        ]
        if len(source_ids) != len(set(source_ids)):
            raise ProfileError("profile metadata source ids must be unique")
        known = set(source_ids)
        referenced: set[str] = set()
        for entry in self.data["evidence"]:
            referenced.update(str(value) for value in entry["sources"])
        for domain in self.data.get("issue_domains", {}).values():
            referenced.update(str(value) for value in domain["evidence"])
        for domain in self.backend.get("dispatch_domains", {}).values():
            referenced.update(str(value) for value in domain.get("evidence", []))
        rename = self.backend.get("rename")
        if rename:
            referenced.update(str(value) for value in rename.get("evidence", []))
        dependency_policy = self.backend.get("vector_dependency")
        if dependency_policy:
            referenced.update(
                str(value) for value in dependency_policy.get("evidence", [])
            )
        vector_memory = self.backend.get("vector_memory")
        if vector_memory:
            referenced.update(str(value) for value in vector_memory.get("evidence", []))
        # Existing v4 recipes may use local equivalence labels in addition to
        # centralized metadata source ids, so recipe evidence remains free-form.
        fit = self.data.get("scalar_control_fit")
        if fit:
            referenced.update(str(value) for value in fit["evidence"])
        unknown = referenced - known
        if unknown:
            raise ProfileError(
                "profile references missing evidence source: "
                + ", ".join(sorted(unknown))
            )

    def _validate_isa(self) -> None:
        isa = self.data["isa"]
        vector_length = isa.get("vector_length_bits")
        max_vector = isa["max_vector_bits"]
        if isinstance(vector_length, int) and vector_length > max_vector:
            raise ProfileError(
                "isa.vector_length_bits cannot exceed isa.max_vector_bits"
            )

    def _validate_backend_topology(self) -> None:
        backend = self.data.get("backend")
        if backend is None:
            return
        partitions = backend["scheduler_partitions"]
        partition_ids = [str(entry["id"]) for entry in partitions]
        if len(partition_ids) != len(set(partition_ids)):
            raise ProfileError("backend scheduler partition ids must be unique")
        known_partitions = set(partition_ids)
        units = backend["execution_units"]
        listed_units: set[str] = set()
        for partition in partitions:
            partition_id = str(partition["id"])
            for unit_id in partition["execution_units"]:
                if unit_id in listed_units:
                    raise ProfileError(
                        f"backend execution unit is listed by multiple partitions: {unit_id}"
                    )
                listed_units.add(unit_id)
                if unit_id not in units:
                    raise ProfileError(
                        f"backend scheduler partition references missing execution unit: {unit_id}"
                    )
                if units[unit_id]["scheduler_partition"] != partition_id:
                    raise ProfileError(
                        f"backend execution unit {unit_id} disagrees with scheduler "
                        f"partition {partition_id}"
                    )
        unlisted_units = set(units) - listed_units
        if unlisted_units:
            raise ProfileError(
                "backend execution units are not assigned to a scheduler partition: "
                + ", ".join(sorted(unlisted_units))
            )
        resources = self.data["resources"]
        for unit_id, unit in units.items():
            partition_id = unit["scheduler_partition"]
            if partition_id not in known_partitions:
                raise ProfileError(
                    f"backend execution unit {unit_id} references missing scheduler "
                    f"partition: {partition_id}"
                )
            missing = set(unit["functional_units"]) - set(resources)
            if missing:
                raise ProfileError(
                    f"backend execution unit {unit_id} references missing functional "
                    "resource: " + ", ".join(sorted(missing))
                )
        read_domains: set[str] = set()
        writeback_domains: set[str] = set()
        for register_file in backend["register_files"].values():
            for domain_kind, target in (
                ("read_domains", read_domains),
                ("writeback_domains", writeback_domains),
            ):
                for domain_id, domain in register_file.get(domain_kind, {}).items():
                    if domain_id in target:
                        raise ProfileError(
                            f"backend {domain_kind[:-1]} id is not unique: {domain_id}"
                        )
                    target.add(domain_id)
                    port_count = domain["port_count"]
                    arbitration_capacity = domain["arbitration_capacity"]
                    if (
                        isinstance(port_count, int)
                        and isinstance(arbitration_capacity, int)
                        and arbitration_capacity > port_count
                    ):
                        raise ProfileError(
                            f"backend register domain {domain_id} arbitration capacity "
                            "exceeds its port count"
                        )
                    missing_units = set(domain["execution_units"]) - set(units)
                    if missing_units:
                        raise ProfileError(
                            f"backend register domain {domain_id} references missing "
                            "execution unit: " + ", ".join(sorted(missing_units))
                        )
        for unit_id, unit in units.items():
            read_domain = unit.get("vector_read_domain")
            if read_domain and read_domain not in read_domains:
                raise ProfileError(
                    f"backend execution unit {unit_id} references missing vector "
                    f"read domain: {read_domain}"
                )
            writeback_domain = unit.get("vector_writeback_domain")
            if writeback_domain and writeback_domain not in writeback_domains:
                raise ProfileError(
                    f"backend execution unit {unit_id} references missing vector "
                    f"writeback domain: {writeback_domain}"
                )
        vector_entries = [
            entry["entries"]
            for entry in partitions
            if entry["kind"] == "vector_compute"
        ]
        configured = self.data["pipeline"]["vector_scheduler_entries"]
        if vector_entries and all(isinstance(value, int) for value in vector_entries):
            if isinstance(configured, int) and sum(vector_entries) != configured:
                raise ProfileError(
                    "pipeline.vector_scheduler_entries does not equal the sum of "
                    "vector_compute scheduler partitions"
                )
        decomposition = backend.get("vector_decomposition")
        if decomposition:
            width_bits = decomposition["register_width_bits"]
            if isinstance(width_bits, int) and width_bits % 8:
                raise ProfileError(
                    "backend.vector_decomposition.register_width_bits must be "
                    "byte-aligned"
                )
        accounting = backend.get("macro_op_accounting", {})
        valid_accounting_bases = {
            "decoded_macro_ops",
            "execution_uops",
            "max_decoded_or_execution_uops",
            "architectural_instructions",
        }
        for field in ("dispatch_units", "rob_entries"):
            basis = accounting.get(field, "decoded_macro_ops")
            if basis not in valid_accounting_bases:
                raise ProfileError(
                    f"backend.macro_op_accounting.{field} has unsupported basis: "
                    f"{basis!r}"
                )
        vector_memory = backend.get("vector_memory", {})
        if not isinstance(vector_memory, dict):
            raise ProfileError("backend.vector_memory must be a mapping")
        issue_order = vector_memory.get("issue_order", "any")
        valid_issue_orders = {"any", "oldest", "oldest_same_kind"}
        if issue_order not in valid_issue_orders:
            raise ProfileError(
                "backend.vector_memory.issue_order must be 'any', 'oldest', "
                "or 'oldest_same_kind'"
            )
        service_capacity = vector_memory.get("service_capacity")
        if service_capacity is not None:
            if not isinstance(service_capacity, dict) or not service_capacity:
                raise ProfileError(
                    "backend.vector_memory.service_capacity must be a non-empty mapping"
                )
            unknown_kinds = set(service_capacity) - {"load", "store"}
            if unknown_kinds:
                raise ProfileError(
                    "backend.vector_memory.service_capacity has unsupported kinds: "
                    + ", ".join(sorted(unknown_kinds))
                )
            for access_kind, capacity in service_capacity.items():
                if capacity != "measure" and (
                    isinstance(capacity, bool)
                    or not isinstance(capacity, int)
                    or capacity < 1
                ):
                    raise ProfileError(
                        "backend.vector_memory.service_capacity.%s must be "
                        "a positive integer, 'measure', or omitted" % access_kind
                    )
        store_completion = vector_memory.get("store_completion_cycles", 0)
        if store_completion != "measure" and (
            isinstance(store_completion, bool)
            or not isinstance(store_completion, (int, float))
            or store_completion < 0
        ):
            raise ProfileError(
                "backend.vector_memory.store_completion_cycles must be "
                "non-negative, 'measure', or omitted"
            )
        service_cycles = vector_memory.get("service_cycles")
        if service_cycles is not None:
            if not isinstance(service_cycles, dict) or not service_cycles:
                raise ProfileError(
                    "backend.vector_memory.service_cycles must be a non-empty mapping"
                )
            unknown_kinds = set(service_cycles) - {"load", "store"}
            if unknown_kinds:
                raise ProfileError(
                    "backend.vector_memory.service_cycles has unsupported kinds: "
                    + ", ".join(sorted(unknown_kinds))
                )
            for access_kind, cycles in service_cycles.items():
                if cycles != "measure" and (
                    isinstance(cycles, bool)
                    or not isinstance(cycles, (int, float))
                    or cycles < 0
                ):
                    raise ProfileError(
                        "backend.vector_memory.service_cycles.%s must be "
                        "non-negative, 'measure', or omitted" % access_kind
                    )
        split_fields = {
            "boundary_bytes",
            "issue_cycles_per_flow",
        }
        configured_split_fields = split_fields & set(vector_memory)
        if configured_split_fields and configured_split_fields != split_fields:
            missing = split_fields - configured_split_fields
            raise ProfileError(
                "backend.vector_memory flow-split policy requires all of: "
                + ", ".join(sorted(split_fields))
                + "; missing: "
                + ", ".join(sorted(missing))
            )
        for field in ("boundary_bytes",):
            value = vector_memory.get(field)
            if value is not None and (
                value != "measure"
                and (
                    isinstance(value, bool)
                    or not isinstance(value, int)
                    or value < 1
                )
            ):
                raise ProfileError(
                    f"backend.vector_memory.{field} must be a positive integer, "
                    "'measure', or omitted"
                )
        issue_cycles_per_flow = vector_memory.get("issue_cycles_per_flow")
        if issue_cycles_per_flow is not None and (
            issue_cycles_per_flow != "measure"
            and (
                isinstance(issue_cycles_per_flow, bool)
                or not isinstance(issue_cycles_per_flow, (int, float))
                or issue_cycles_per_flow < 0
            )
        ):
            raise ProfileError(
                "backend.vector_memory.issue_cycles_per_flow must be "
                "non-negative, 'measure', or omitted"
            )
        for domain_id, domain in backend.get("dispatch_domains", {}).items():
            capacity = domain.get("capacity")
            if capacity != "measure" and (
                isinstance(capacity, bool)
                or not isinstance(capacity, int)
                or capacity < 1
            ):
                raise ProfileError(
                    f"backend.dispatch_domains.{domain_id}.capacity must be a "
                    "positive integer or 'measure'"
                )
        rename = backend.get("rename")
        if rename is not None:
            if not isinstance(rename, dict):
                raise ProfileError("backend.rename must be a mapping")
            if rename.get("enabled"):
                free_lists = rename.get("free_lists", {})
                if not free_lists:
                    raise ProfileError("backend.rename.free_lists must be non-empty")
                policy = rename.get("policy")
                if policy not in {"all_files_must_be_ready", "any_file_may_be_ready"}:
                    raise ProfileError(
                        "backend.rename.policy has unsupported value: "
                        f"{policy!r}"
                    )
                for name, entry in free_lists.items():
                    value = entry.get("free_entries")
                    if value != "measure" and (
                        isinstance(value, bool)
                        or not isinstance(value, int)
                        or value < 1
                    ):
                        raise ProfileError(
                            f"backend.rename.free_lists.{name}.free_entries must be "
                            "a positive integer or 'measure'"
                        )
                for field in ("allocation_width", "release_width"):
                    value = rename.get(field)
                    if value != "measure" and (
                        isinstance(value, bool)
                        or not isinstance(value, int)
                        or value < 1
                    ):
                        raise ProfileError(
                            f"backend.rename.{field} must be a positive integer or 'measure'"
                        )
                for field in ("release_delay_cycles", "availability_delay_cycles"):
                    value = rename.get(field)
                    if value != "measure" and (
                        isinstance(value, bool)
                        or not isinstance(value, (int, float))
                        or value < 0
                    ):
                        raise ProfileError(
                            f"backend.rename.{field} must be a non-negative number or 'measure'"
                        )
                guard = rename.get("guard_entries")
                if guard != "measure" and (
                    isinstance(guard, bool)
                    or not isinstance(guard, int)
                    or guard < 0
                ):
                    raise ProfileError(
                        "backend.rename.guard_entries must be a non-negative integer or 'measure'"
                    )

    def _validate_vector_dependency_policy(self) -> None:
        """Validate optional vector state/old-destination dependency policy.

        This is deliberately profile data rather than an ISA/mnemonic switch.
        Profiles written before the policy existed simply get an empty policy
        and therefore retain the legacy dependency behavior.
        """
        policy = self.backend.get("vector_dependency")
        if policy is None:
            return
        if not isinstance(policy, dict):
            raise ProfileError("backend.vector_dependency must be a mapping")
        evidence = policy.get("evidence")
        if (
            not isinstance(evidence, list)
            or not evidence
            or len(evidence) != len(set(evidence))
        ):
            raise ProfileError(
                "backend.vector_dependency.evidence must be a non-empty unique list"
            )
        state = policy.get("vector_state")
        old_destination = policy.get("old_destination")
        if state is None and old_destination is None:
            raise ProfileError(
                "backend.vector_dependency requires vector_state or old_destination"
            )
        valid_kinds = {
            "vector_fp",
            "vector_integer",
            "conversion",
            "shuffle",
            "vector_control",
            "vector_divide",
            "address_generation",
            "load_data",
            "store_data",
        }
        if state is not None:
            if not isinstance(state, dict):
                raise ProfileError(
                    "backend.vector_dependency.vector_state must be a mapping"
                )
            registers = state.get("registers")
            wait_kinds = state.get("wait_execution_kinds")
            if (
                not isinstance(registers, list)
                or not registers
                or len(registers) != len(set(registers))
            ):
                raise ProfileError(
                    "backend.vector_dependency.vector_state.registers must be a non-empty unique list"
                )
            if (
                not isinstance(wait_kinds, list)
                or not wait_kinds
                or len(wait_kinds) != len(set(wait_kinds))
            ):
                raise ProfileError(
                    "backend.vector_dependency.vector_state.wait_execution_kinds must be a non-empty unique list"
                )
            unknown = set(wait_kinds) - valid_kinds
            if unknown:
                raise ProfileError(
                    "backend.vector_dependency.vector_state references unknown execution kind: "
                    + ", ".join(sorted(str(value) for value in unknown))
                )
        if old_destination is not None:
            if not isinstance(old_destination, dict):
                raise ProfileError(
                    "backend.vector_dependency.old_destination must be a mapping"
                )
            mode = old_destination.get("mode")
            if mode not in {"disabled", "semantic"}:
                raise ProfileError(
                    "backend.vector_dependency.old_destination.mode must be disabled or semantic"
                )
            old_wait_kinds = old_destination.get("wait_execution_kinds")
            if (
                not isinstance(old_wait_kinds, list)
                or not old_wait_kinds
                or len(old_wait_kinds) != len(set(old_wait_kinds))
            ):
                raise ProfileError(
                    "backend.vector_dependency.old_destination.wait_execution_kinds must be a non-empty unique list"
                )
            unknown = set(old_wait_kinds) - valid_kinds
            if unknown:
                raise ProfileError(
                    "backend.vector_dependency.old_destination references unknown execution kind: "
                    + ", ".join(sorted(str(value) for value in unknown))
                )
            implicit_kinds = old_destination.get("implicit_execution_kinds", [])
            if (
                not isinstance(implicit_kinds, list)
                or len(implicit_kinds) != len(set(implicit_kinds))
            ):
                raise ProfileError(
                    "backend.vector_dependency.old_destination."
                    "implicit_execution_kinds must be a unique list"
                )
            unknown = set(implicit_kinds) - valid_kinds
            if unknown:
                raise ProfileError(
                    "backend.vector_dependency.old_destination."
                    "implicit_execution_kinds references unknown execution kind: "
                    + ", ".join(sorted(str(value) for value in unknown))
                )
            outside_wait_set = set(implicit_kinds) - set(old_wait_kinds)
            if outside_wait_set:
                raise ProfileError(
                    "backend.vector_dependency.old_destination."
                    "implicit_execution_kinds must be a subset of "
                    "wait_execution_kinds: "
                    + ", ".join(sorted(str(value) for value in outside_wait_set))
                )

    def _find_unresolved_parameters(self) -> list[str]:
        result: list[str] = []

        def visit(value: Any, path: tuple[str, ...]) -> None:
            if value == "measure":
                result.append(".".join(path))
            elif isinstance(value, dict):
                for key, nested in value.items():
                    visit(nested, (*path, str(key)))
            elif isinstance(value, list):
                for index, nested in enumerate(value):
                    visit(nested, (*path, str(index)))

        visit(self.data, ())
        return result

    def _validate_issue_domains(self) -> None:
        domains = self.data.get("issue_domains", {})
        for recipe_id, recipe in self.data["recipes"].items():
            for uop in recipe["uops"]:
                issue_domains = tuple(uop.get("issue_domains", []))
                demands = uop.get("issue_domain_demands", {})
                if not isinstance(demands, dict):
                    raise ProfileError(
                        f"recipe {recipe_id} uop {uop['id']} issue-domain demands "
                        "must be a mapping"
                    )
                unlisted = set(demands) - set(issue_domains)
                if unlisted:
                    raise ProfileError(
                        f"recipe {recipe_id} uop {uop['id']} has demand for "
                        "unlisted issue domain: " + ", ".join(sorted(unlisted))
                    )
                for domain_id in issue_domains:
                    if domain_id not in domains:
                        raise ProfileError(
                            f"recipe references missing issue domain: {domain_id}"
                        )
                    demand = demands.get(domain_id, 1)
                    if (
                        isinstance(demand, bool)
                        or not isinstance(demand, int)
                        or demand < 1
                    ):
                        raise ProfileError(
                            f"recipe {recipe_id} uop {uop['id']} has invalid demand "
                            f"for issue domain {domain_id}: {demand!r}"
                        )
                    capacity = domains[domain_id]["capacity"]
                    if isinstance(capacity, int) and demand > capacity:
                        raise ProfileError(
                            f"recipe {recipe_id} uop {uop['id']} demand {demand} "
                            f"exceeds issue domain {domain_id} capacity {capacity}"
                        )

    def _validate_dispatch_domains(self) -> None:
        """Validate frontend macro admission domains, separate from uop issue domains."""
        domains = self.backend.get("dispatch_domains", {})
        for recipe_id, recipe in self.data["recipes"].items():
            configured_domains = recipe.get("dispatch_domains", [])
            if not isinstance(configured_domains, list):
                raise ProfileError(
                    f"recipe {recipe_id} dispatch domains must be a list"
                )
            dispatch_domains = tuple(configured_domains)
            if len(dispatch_domains) != len(set(dispatch_domains)):
                raise ProfileError(
                    f"recipe {recipe_id} has duplicate dispatch domains"
                )
            demands = recipe.get("dispatch_domain_demands", {})
            if not isinstance(demands, dict):
                raise ProfileError(
                    f"recipe {recipe_id} dispatch-domain demands must be a mapping"
                )
            unlisted = set(demands) - set(dispatch_domains)
            if unlisted:
                raise ProfileError(
                    f"recipe {recipe_id} has demand for unlisted dispatch domain: "
                    + ", ".join(sorted(unlisted))
                )
            for domain_id in dispatch_domains:
                if domain_id not in domains:
                    raise ProfileError(
                        f"recipe references missing dispatch domain: {domain_id}"
                    )
                demand = demands.get(domain_id, 1)
                if (
                    isinstance(demand, bool)
                    or not isinstance(demand, int)
                    or demand < 1
                ):
                    raise ProfileError(
                        f"recipe {recipe_id} has invalid demand for dispatch domain "
                        f"{domain_id}: {demand!r}"
                    )
                capacity = domains[domain_id]["capacity"]
                if isinstance(capacity, int) and demand > capacity:
                    raise ProfileError(
                        f"recipe {recipe_id} demand {demand} exceeds dispatch domain "
                        f"{domain_id} capacity {capacity}"
                    )

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
    def memory_compute_overlap_limit(self) -> dict[str, Any]:
        return self.data.get(
            "memory_compute_overlap_limit",
            {
                "enabled": False,
                "max_pending_groups": 1,
                "compute_semantic_kinds": [],
            },
        )

    @property
    def backend(self) -> dict[str, Any]:
        return self.data.get(
            "backend",
            {
                "execution_model": "zen4",
                "scheduler_partitions": [],
                "execution_units": {},
                "register_files": {},
                "vector_memory": {},
            },
        )

    @property
    def vector_memory_policy(self) -> dict[str, Any]:
        """Return optional VLSU flow/order policy; omitted fields are inert."""
        configured = self.backend.get("vector_memory", {})
        completion = configured.get("store_completion_cycles", 0)
        if completion == "measure":
            self._measurement_required(
                "backend.vector_memory.store_completion_cycles"
            )
        result = {
            "issue_order": str(configured.get("issue_order", "any")),
            "store_completion_ticks": self.ticks(completion),
            "split_lanes": {
                "load": self._parameter_int(
                    configured.get("load_pipelines", 1),
                    "backend.vector_memory.load_pipelines",
                ),
                "store": self._parameter_int(
                    configured.get("store_pipelines", 1),
                    "backend.vector_memory.store_pipelines",
                ),
            },
        }
        if "service_capacity" in configured:
            capacity = configured["service_capacity"]
            result["service_capacity"] = {
                str(kind): int(value)
                for kind, value in capacity.items()
                if value != "measure"
            }
            for kind, value in capacity.items():
                if value == "measure":
                    self._measurement_required(
                        f"backend.vector_memory.service_capacity.{kind}"
                    )
        # Omitted service_cycles retain the legacy completion-bound flow token.
        # An explicitly configured kind separates token service lifetime from
        # uop completion, including an intentional zero-cycle service.
        if "service_cycles" in configured:
            service = configured["service_cycles"]
            result["service_ticks"] = {
                str(kind): self.ticks(cycles)
                for kind, cycles in service.items()
                if cycles != "measure"
            }
            for kind, cycles in service.items():
                if cycles == "measure":
                    self._measurement_required(
                        f"backend.vector_memory.service_cycles.{kind}"
                    )
        split_fields = (
            "boundary_bytes",
            "issue_cycles_per_flow",
        )
        if any(field in configured for field in split_fields):
            for field in split_fields:
                if configured[field] == "measure":
                    self._measurement_required(f"backend.vector_memory.{field}")
            result["flow_split"] = {
                "boundary_bytes": int(configured["boundary_bytes"]),
                "max_flows_per_access": self._parameter_int(
                    configured.get("max_unit_stride_flows", 1),
                    "backend.vector_memory.max_unit_stride_flows",
                ),
                "issue_ticks_per_flow": self.ticks(
                    configured["issue_cycles_per_flow"]
                ),
            }
        return result

    @property
    def vector_dependency_policy(self) -> dict[str, Any]:
        """Return normalized vector dependency policy with legacy defaults."""
        configured = self.backend.get("vector_dependency", {})
        return {
            "vector_state": {
                "registers": tuple(
                    str(value)
                    for value in configured.get("vector_state", {}).get(
                        "registers", []
                    )
                ),
                "wait_execution_kinds": frozenset(
                    str(value)
                    for value in configured.get("vector_state", {}).get(
                        "wait_execution_kinds", []
                    )
                ),
            },
            "old_destination": {
                "mode": str(
                    configured.get("old_destination", {}).get(
                        "mode", "disabled"
                    )
                ),
                "wait_execution_kinds": frozenset(
                    str(value)
                    for value in configured.get("old_destination", {}).get(
                        "wait_execution_kinds", []
                    )
                ),
                "implicit_execution_kinds": frozenset(
                    str(value)
                    for value in configured.get("old_destination", {}).get(
                        "implicit_execution_kinds", []
                    )
                ),
            },
        }

    @property
    def rename_policy(self) -> dict[str, Any]:
        """Return normalized physical-register rename policy."""
        configured = self.backend.get("rename", {})
        enabled = bool(configured.get("enabled", False))
        if not enabled:
            return {
                "enabled": False,
                "free_lists": {},
                "allocation_width": 0,
                "release_width": 0,
                "release_delay_ticks": 0,
                "availability_delay_ticks": 0,
                "guard_entries": 0,
                "policy": "all_files_must_be_ready",
            }
        return {
            "enabled": True,
            "free_lists": {
                str(name): self._parameter_int(
                    value["free_entries"],
                    f"backend.rename.free_lists.{name}.free_entries",
                )
                for name, value in configured["free_lists"].items()
            },
            "allocation_width": self._parameter_int(
                configured["allocation_width"], "backend.rename.allocation_width"
            ),
            "release_width": self._parameter_int(
                configured["release_width"], "backend.rename.release_width"
            ),
            "release_delay_ticks": self._parameter_ticks(
                configured["release_delay_cycles"],
                "backend.rename.release_delay_cycles",
            ),
            "availability_delay_ticks": self._parameter_ticks(
                configured["availability_delay_cycles"],
                "backend.rename.availability_delay_cycles",
            ),
            "guard_entries": self._parameter_int(
                configured["guard_entries"], "backend.rename.guard_entries"
            ),
            "policy": configured["policy"],
        }

    @property
    def simulation_ready(self) -> bool:
        return self.backend["execution_model"] in {
            "zen4",
            "xsai-rvv",
            "generic-token",
        }

    def _require_simulation_ready(self) -> None:
        execution_model = self.backend["execution_model"]
        if execution_model not in {"zen4", "xsai-rvv", "generic-token"}:
            raise ProfileError(
                f"profile backend execution model is not implemented: {execution_model}"
            )

    @staticmethod
    def _measurement_required(path: str) -> None:
        raise ProfileError(
            f"profile parameter remains 'measure' for this trace: {path}"
        )

    def _parameter_int(self, value: Any, path: str) -> int:
        if value == "measure":
            self._measurement_required(path)
        try:
            return int(value)
        except (TypeError, ValueError) as error:
            raise ProfileError(f"profile parameter must be an integer: {path}") from error

    def _parameter_ticks(self, value: Any, path: str) -> int:
        if value == "measure":
            self._measurement_required(path)
        try:
            return self.ticks(value)
        except (TypeError, ValueError) as error:
            raise ProfileError(
                f"profile parameter must be a cycle count: {path}"
            ) from error

    @property
    def l1_latency_ticks(self) -> int:
        return self._parameter_ticks(
            self.data["memory"]["levels"]["l1d"]["latency_cycles"],
            "memory.levels.l1d.latency_cycles",
        )

    def _require_l1_access_parameters(self, access: str) -> None:
        level = self.data["memory"]["levels"]["l1d"]
        self.l1_latency_ticks
        bandwidth_key = (
            "write_bytes_per_cycle" if access == "store" else "read_bytes_per_cycle"
        )
        self._parameter_int(
            level[bandwidth_key], f"memory.levels.l1d.{bandwidth_key}"
        )

    def bind(self, trace: dict[str, Any]) -> BoundTrace:
        if trace.get("trace_version") != 2:
            raise ProfileError("simulator requires dynamic trace_version 2")
        self._require_simulation_ready()
        macros: list[MacroOp] = []
        uops: list[ExecutionUop] = []
        result_uops: dict[str, tuple[ExecutionUop, ...]] = {}
        required_resources: set[str] = set()
        dependency_policy = self.vector_dependency_policy

        for instruction in trace["instructions"]:
            candidates = recipe_keys(instruction)
            key = next(
                (value for value in candidates if value in self.data["recipes"]),
                candidates[0],
            )
            recipe = self.data["recipes"].get(key)
            recipe_path = f"recipes.{key}"
            semantic_kinds = tuple(
                semantic["kind"] for semantic in instruction["semantic_uops"]
            )
            if recipe is None:
                recipe = self._fallback_recipe(semantic_kinds, key)
                recipe_path = "scalar_control_fit"
            dispatch_domains = tuple(recipe.get("dispatch_domains", []))
            configured_dispatch_demands = recipe.get(
                "dispatch_domain_demands", {}
            )
            try:
                semantic_bindings = bind_execution_semantics(instruction, recipe["uops"])
            except SemanticBindingError as error:
                raise ProfileError(str(error)) from error
            semantic_kind_by_id = {
                semantic_id(str(instruction["id"]), str(semantic["local_id"])): str(
                    semantic["kind"]
                )
                for semantic in instruction["semantic_uops"]
            }
            semantic_definition_by_id = {
                semantic_id(str(instruction["id"]), str(semantic["local_id"])): semantic
                for semantic in instruction["semantic_uops"]
            }
            dynamic_decomposition = (
                None
                if recipe.get("vector_decomposition")
                else self._backend_vector_decomposition(instruction, semantic_kinds)
            )
            depended_locals = {
                dependency
                for entry in recipe["uops"]
                for dependency in entry.get("depends_on", [])
            }
            expanded: list[
                tuple[int, dict[str, Any], int | None, int | None, bool, str]
            ] = []
            if dynamic_decomposition is None:
                static_parts = recipe.get("vector_decomposition", {}).get("parts")
                for local_index, entry in enumerate(recipe["uops"]):
                    entry_path = entry.get(
                        "_profile_path", f"{recipe_path}.uops.{local_index}"
                    )
                    expanded.append(
                        (
                            local_index,
                            entry,
                            entry.get("part_index"),
                            (
                                self._parameter_int(
                                    static_parts,
                                    f"{recipe_path}.vector_decomposition.parts",
                                )
                                if static_parts is not None and "part_index" in entry
                                else None
                            ),
                            False,
                            entry_path,
                        )
                    )
            else:
                part_count = dynamic_decomposition["parts"]
                prep = dynamic_decomposition.get("prep_uop")
                if prep is not None:
                    expanded.append(
                        (
                            0,
                            prep,
                            None,
                            None,
                            True,
                            prep["_profile_path"],
                        )
                    )
                for part_index in range(part_count):
                    for local_index, entry in enumerate(recipe["uops"]):
                        compute_entry = entry
                        if prep is not None:
                            compute_entry = copy.deepcopy(entry)
                            compute_entry["depends_on"] = [
                                *compute_entry.get("depends_on", []),
                                prep["id"],
                            ]
                        expanded.append(
                            (
                                local_index,
                                compute_entry,
                                part_index,
                                part_count,
                                False,
                                entry.get(
                                    "_profile_path",
                                    f"{recipe_path}.uops.{local_index}",
                                ),
                            )
                        )
                depended_locals.update(
                    dependency
                    for _, entry, _, _, _, _ in expanded
                    for dependency in entry.get("depends_on", [])
                )

            execution: list[ExecutionUop] = []
            for expanded_index, (
                local_index,
                entry,
                part_index,
                part_count,
                generated_prep,
                entry_path,
            ) in enumerate(expanded):
                uop_id = f"{instruction['id']}.e{expanded_index}"
                issue_domains = tuple(entry.get("issue_domains", []))
                configured_demands = entry.get("issue_domain_demands", {})
                configured_rename_allocations = {
                    str(name): self._parameter_int(
                        value,
                        f"{entry_path}.rename_allocations.{name}",
                    )
                    for name, value in entry.get("rename_allocations", {}).items()
                }
                memory = (
                    copy.deepcopy(instruction.get("memory"))
                    if entry["kind"] in {"load_data", "store_data", "address_generation"}
                    else None
                )
                if memory is not None and dynamic_decomposition is not None:
                    memory = self._memory_part(
                        memory,
                        part_index or 0,
                        part_count or 1,
                        dynamic_decomposition["width_bits"],
                    )
                occupancy = self._parameter_ticks(
                    entry["resource_occupancy_cycles"],
                    f"{entry_path}.resource_occupancy_cycles",
                )
                latency = self._parameter_ticks(
                    entry["latency_cycles"], f"{entry_path}.latency_cycles"
                )
                if entry["kind"] == "load_data":
                    self._require_l1_access_parameters("load")
                elif entry["kind"] == "store_data":
                    self._require_l1_access_parameters("store")
                resource_choices = tuple(entry["resource_choices"])
                required_resources.update(resource_choices)
                execution_units = self._execution_unit_choices(resource_choices)
                scheduler_partitions = tuple(
                    dict.fromkeys(
                        str(self.backend["execution_units"][unit]["scheduler_partition"])
                        for unit in execution_units
                    )
                )
                terminal = entry["id"] not in depended_locals
                semantic_ids = semantic_bindings[local_index]
                waits_for_vector_state = (
                    not generated_prep
                    and str(entry["kind"])
                    in dependency_policy["vector_state"]["wait_execution_kinds"]
                    and any(
                        register in instruction.get("register_reads", [])
                        or register
                        in instruction.get("register_dependencies", {})
                        for register in dependency_policy["vector_state"]["registers"]
                    )
                )
                semantic_reads_old_destination = any(
                    bool(
                        semantic_definition_by_id.get(semantic_id, {}).get(
                            "reads_old_destination",
                            semantic_definition_by_id.get(semantic_id, {}).get(
                                "reads_old_dest", False
                            ),
                        )
                    )
                    for semantic_id in semantic_ids
                )
                implicit_old_destination = str(entry["kind"]) in dependency_policy[
                    "old_destination"
                ]["implicit_execution_kinds"]
                reads_old_destination = (
                    dependency_policy["old_destination"]["mode"] == "semantic"
                    and not generated_prep
                    and str(entry["kind"])
                    in dependency_policy["old_destination"]["wait_execution_kinds"]
                    and (semantic_reads_old_destination or implicit_old_destination)
                )
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
                            f"{key}:{entry['id']}:part-{part_index}"
                            if part_index is not None
                            else f"{key}:{entry['id']}"
                        ),
                        part_index=part_index,
                        part_count=part_count,
                        latency_ticks=latency,
                        issue_interval_ticks=self._parameter_ticks(
                            entry["issue_interval_cycles"],
                            f"{entry_path}.issue_interval_cycles",
                        )
                        * (
                            self._parameter_int(
                                recipe["vector_decomposition"]["parts"],
                                f"{recipe_path}.vector_decomposition.parts",
                            )
                            if (
                                "part_index" in entry
                                and recipe.get("vector_decomposition")
                                and recipe["vector_decomposition"].get(
                                    "scale_issue_interval_by_parts", True
                                )
                            )
                            else 1
                        ),
                        occupancy_ticks=occupancy,
                        resource_choices=resource_choices,
                        issue_domains=issue_domains,
                        issue_domain_demands={
                            domain_id: int(configured_demands.get(domain_id, 1))
                            for domain_id in issue_domains
                        },
                        rename_allocations=configured_rename_allocations,
                        scheduler_partition_choices=scheduler_partitions,
                        execution_unit_choices=execution_units,
                        requires_completion_token=(
                            generated_prep
                            or (terminal and self._writes_vector_result(instruction))
                        ),
                        requires_vector_read_token=self._requires_vector_read_token(
                            instruction,
                            str(entry["kind"]),
                            semantic_bindings[local_index],
                            semantic_kind_by_id,
                            generated_prep,
                        ),
                        semantic_ids=semantic_ids,
                        requires_vector_state=waits_for_vector_state,
                        reads_old_destination=reads_old_destination,
                        memory=memory,
                    )
                )

            local_uops: dict[str, list[ExecutionUop]] = {}
            for (_, entry, _, _, _, _), uop in zip(expanded, execution):
                local_uops.setdefault(str(entry["id"]), []).append(uop)
            for (local_index, entry, part_index, _, _, _), uop in zip(
                expanded, execution
            ):
                for dependency_id in entry.get("depends_on", []):
                    candidates = local_uops[dependency_id]
                    matching = [
                        candidate
                        for candidate in candidates
                        if part_index is not None
                        and candidate.part_index == part_index
                    ]
                    uop.dependencies.update(
                        candidate.id for candidate in (matching or candidates)
                    )
                if (
                    dynamic_decomposition is None
                    and part_index
                    and recipe.get("vector_decomposition")
                ):
                    previous = next(
                        (
                            candidate
                            for candidate in execution
                            if candidate.part_index == part_index - 1
                        ),
                        None,
                    )
                    if previous:
                        uop.issue_after_uop = previous.id
                        uop.issue_gap_ticks = self._parameter_ticks(
                            recipe["vector_decomposition"]["part_issue_gap_cycles"],
                            f"{recipe_path}.vector_decomposition.part_issue_gap_cycles",
                        )
                self._add_external_dependencies(
                    uop,
                    instruction,
                    result_uops,
                    local_index == 0,
                    entry.get("_external_dependency_registers"),
                )
                if uop.requires_vector_state:
                    state_dependencies = self._add_register_dependencies(
                        uop,
                        instruction,
                        result_uops,
                        dependency_policy["vector_state"]["registers"],
                    )
                    uop.vector_state_dependencies.update(state_dependencies)
                if uop.reads_old_destination:
                    old_destination_dependencies = self._add_old_destination_dependencies(
                        uop,
                        instruction,
                        result_uops,
                        semantic_bindings[local_index],
                        semantic_definition_by_id,
                        uop.kind
                        in dependency_policy["old_destination"][
                            "implicit_execution_kinds"
                        ],
                    )
                    uop.old_destination_dependencies.update(
                        old_destination_dependencies
                    )

            uops.extend(execution)
            result_uops[instruction["id"]] = tuple(
                uop
                for (_, entry, _, _, _, _), uop in zip(expanded, execution)
                if entry["id"] not in depended_locals
            )
            kinds = {uop.kind for uop in execution}
            decoded_macro_ops = self._parameter_int(
                recipe["decoded_macro_ops"],
                f"{recipe_path}.decoded_macro_ops",
            )
            macros.append(
                MacroOp(
                    id=instruction["id"],
                    sequence=instruction["sequence"],
                    mnemonic=instruction["mnemonic"],
                    assembly=instruction["assembly"],
                    uop_ids=tuple(uop.id for uop in execution),
                    decoded_macro_ops=decoded_macro_ops,
                    retire_macro_ops=self._parameter_int(
                        recipe["retire_macro_ops"],
                        f"{recipe_path}.retire_macro_ops",
                    ),
                    uses_vector_scheduler=bool(kinds & VECTOR_RESOURCE_KINDS),
                    uses_load_queue="load_data" in kinds,
                    uses_store_queue="store_data" in kinds,
                    dispatch_domains=dispatch_domains,
                    dispatch_domain_demands={
                        domain_id: int(
                            configured_dispatch_demands.get(domain_id, 1)
                        )
                        for domain_id in dispatch_domains
                    },
                    rename_allocations=(
                        {
                            str(name): self._parameter_int(
                                value,
                                f"{recipe_path}.rename_allocations.{name}",
                            )
                            for name, value in recipe.get(
                                "rename_allocations", {}
                            ).items()
                        }
                        if recipe.get("rename_allocations")
                        else {
                            name: sum(
                                uop.rename_allocations.get(name, 0)
                                for uop in execution
                            )
                            for name in {
                                name
                                for uop in execution
                                for name in uop.rename_allocations
                            }
                        }
                    ),
                    dispatch_units=self._macro_op_accounting_count(
                        "dispatch_units", decoded_macro_ops, len(execution)
                    ),
                    rob_entries=self._macro_op_accounting_count(
                        "rob_entries", decoded_macro_ops, len(execution)
                    ),
                )
            )
        resources = self._resources(required_resources)
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

    def _macro_op_accounting_count(
        self, field: str, decoded_macro_ops: int, execution_uops: int
    ) -> int:
        basis = self.backend.get("macro_op_accounting", {}).get(
            field, "decoded_macro_ops"
        )
        counts = {
            "decoded_macro_ops": decoded_macro_ops,
            "execution_uops": execution_uops,
            "max_decoded_or_execution_uops": max(
                decoded_macro_ops, execution_uops
            ),
            "architectural_instructions": 1,
        }
        try:
            return counts[str(basis)]
        except KeyError as error:
            raise ProfileError(
                f"backend.macro_op_accounting.{field} has unsupported basis: "
                f"{basis!r}"
            ) from error

    def _execution_unit_choices(
        self, resource_choices: tuple[str, ...]
    ) -> tuple[str, ...]:
        resources = set(resource_choices)
        return tuple(
            unit_id
            for unit_id, unit in self.backend.get("execution_units", {}).items()
            if resources.intersection(unit["functional_units"])
        )

    @staticmethod
    def _writes_vector_result(instruction: dict[str, Any]) -> bool:
        explicit = instruction.get("writes_vector_result")
        if explicit is not None:
            return bool(explicit)
        vector_classes = {"vector", "xmm", "ymm", "zmm"}
        return any(
            operand_class(str(register)) in vector_classes
            for register in instruction.get("register_writes", [])
        )

    @staticmethod
    def _requires_vector_read_token(
        instruction: dict[str, Any],
        execution_kind: str,
        semantic_ids: tuple[str, ...],
        semantic_kind_by_id: dict[str, str],
        generated_prep: bool,
    ) -> bool:
        if generated_prep or execution_kind not in {
            *VECTOR_RESOURCE_KINDS,
            "store_data",
        }:
            return False
        semantic_kinds = {
            semantic_kind_by_id[value]
            for value in semantic_ids
            if value in semantic_kind_by_id
        }
        if not any(
            kind.startswith("vector_")
            and kind not in {"vector_config", "vector_load"}
            for kind in semantic_kinds
        ):
            return False
        return any(
            Profile._is_vector_register(str(register))
            for register in instruction.get("register_reads", [])
        )

    @staticmethod
    def _is_vector_register(register: str) -> bool:
        token = register.strip().lower().lstrip("%")
        return bool(
            re.fullmatch(r"v(?:[0-9]|[12][0-9]|3[01])", token)
            or re.fullmatch(r"(?:xmm|ymm|zmm)\d+", token)
        )

    def _backend_vector_decomposition(
        self,
        instruction: dict[str, Any],
        semantic_kinds: tuple[str, ...],
    ) -> dict[str, Any] | None:
        configuration = self.backend.get("vector_decomposition")
        vector_state = instruction.get("vector_state")
        if not configuration or not vector_state:
            return None
        category = instruction.get("vector_decomposition_class")
        if category is None:
            category = self._vector_decomposition_class(instruction, semantic_kinds)
        if category is None:
            return None
        rules = configuration["rules"]
        if category not in rules:
            return None
        rule = rules[category]
        decomposition_path = "backend.vector_decomposition"
        rule_path = f"{decomposition_path}.rules.{category}"
        width_bits = self._parameter_int(
            configuration["register_width_bits"],
            f"{decomposition_path}.register_width_bits",
        )
        prep_uop: dict[str, Any] | None = None
        if isinstance(rule, dict):
            if "parts" not in rule or "prep_uops" not in rule:
                raise ProfileError(
                    f"structured vector decomposition rule for {category} must "
                    "provide parts and prep_uops"
                )
            parts_rule = rule["parts"]
            prep_uop = self._select_vector_prep_uop(
                instruction, rule["prep_uops"], f"{rule_path}.prep_uops"
            )
            parts_path = f"{rule_path}.parts"
        else:
            parts_rule = rule
            parts_path = rule_path
        parts = self._vector_part_count(
            parts_rule,
            instruction,
            vector_state,
            width_bits,
            category,
            parts_path,
        )
        return {
            "parts": max(1, parts),
            "width_bits": width_bits,
            "prep_uop": prep_uop,
        }

    def _vector_part_count(
        self,
        rule: Any,
        instruction: dict[str, Any],
        vector_state: dict[str, Any],
        width_bits: int,
        category: str,
        profile_path: str,
    ) -> int:
        if isinstance(rule, int):
            return rule
        if rule == "lmul":
            return self._lmul_parts(vector_state.get("lmul"))
        if rule == "lmul-plus-one":
            raise ProfileError(
                f"vector decomposition rule {category}=lmul-plus-one cannot clone "
                "the compute uop; configure a structured prep_uops rule"
            )
        if rule == "dynamic":
            memory = instruction.get("memory")
            active_bits = (
                int(memory["bytes"]) * 8
                if memory is not None
                else int(instruction.get("active_vector_bits", width_bits))
            )
            return max(1, math.ceil(active_bits / width_bits))
        if rule == "measure":
            self._measurement_required(profile_path)
        raise ProfileError(
            f"unsupported vector decomposition rule for {category}: {rule!r}"
        )

    def _select_vector_prep_uop(
        self,
        instruction: dict[str, Any],
        variants: dict[str, Any],
        profile_path: str,
    ) -> dict[str, Any]:
        explicit = instruction.get("vector_scalar_source_class")
        source_candidates: list[tuple[str, str | None]] = []
        if explicit is not None:
            explicit_class = str(explicit)
            explicit_operand = instruction.get("vector_scalar_source_operand")
            if explicit_operand is None:
                explicit_operand = next(
                    (
                        operand
                        for operand in instruction.get("operands", [])[1:]
                        if operand_class(str(operand)) == explicit_class
                    ),
                    None,
                )
            source_candidates.append(
                (
                    explicit_class,
                    str(explicit_operand) if explicit_operand is not None else None,
                )
            )
        else:
            for operand in instruction.get("operands", [])[1:]:
                current_class = operand_class(str(operand))
                if current_class in {"fp_register", "register", "immediate"}:
                    source_candidates.append((current_class, str(operand)))
        selected = next(
            (
                candidate
                for candidate in source_candidates
                if candidate[0] in variants
            ),
            None,
        )
        if selected is None and "default" in variants:
            selected = ("default", None)
        if selected is None:
            detail = ", ".join(value for value, _ in source_candidates) or "none"
            raise ProfileError(
                "vector-scalar decomposition has no prep uop for source class: "
                + detail
            )
        source_class, source_operand = selected
        result = copy.deepcopy(variants[source_class])
        result["_profile_path"] = f"{profile_path}.{source_class}"
        result["_external_dependency_registers"] = (
            [source_operand]
            if source_class in {"fp_register", "register"}
            and source_operand is not None
            else []
        )
        return result

    @staticmethod
    def _lmul_parts(value: Any) -> int:
        token = str(value or "m1")
        match = re.fullmatch(r"m(\d+)", token)
        if match:
            return max(1, int(match.group(1)))
        if re.fullmatch(r"mf\d+", token):
            return 1
        raise ProfileError(f"invalid RVV LMUL value in dynamic trace: {value!r}")

    @staticmethod
    def _vector_decomposition_class(
        instruction: dict[str, Any], semantic_kinds: tuple[str, ...]
    ) -> str | None:
        kinds = set(semantic_kinds)
        if instruction.get("memory") is not None and kinds.intersection(
            {"address_generation", "vector_load", "vector_store"}
        ):
            return "vector-memory"
        if "vector_config" in kinds:
            return "vector-config"
        if any(kind.startswith("vector_reduce_") for kind in kinds):
            return "vector-reduction"
        if not any(kind.startswith("vector_") for kind in kinds):
            return None
        source_classes = {
            operand_class(str(operand))
            for operand in instruction.get("operands", [])[1:]
        }
        if source_classes.intersection({"fp_register", "register", "immediate"}):
            return "vector-scalar"
        return "vector-vector"

    def _memory_part(
        self,
        memory: dict[str, Any],
        part_index: int,
        part_count: int,
        part_width_bits: int,
    ) -> dict[str, Any]:
        total_bytes = int(memory["bytes"])
        width_bytes = part_width_bits // 8
        if width_bytes < 1:
            raise ProfileError("vector decomposition width must be at least one byte")
        start = part_index * width_bytes
        if start >= total_bytes:
            raise ProfileError(
                f"vector memory decomposition creates empty part {part_index}/{part_count}"
            )
        size = min(width_bytes, total_bytes - start)
        result = copy.deepcopy(memory)
        result["address"] = int(memory["address"]) + start
        result["offset"] = int(memory.get("offset", 0)) + start
        result["bytes"] = size
        line_bytes = int(self.data["memory"]["cache_line_bytes"])
        result["cache_lines"] = list(
            range(
                result["address"] // line_bytes,
                (result["address"] + size - 1) // line_bytes + 1,
            )
        )
        result["flow_index"] = part_index
        result["flow_count"] = part_count
        return result

    def _add_external_dependencies(
        self,
        uop: ExecutionUop,
        instruction: dict[str, Any],
        result_uops: dict[str, tuple[ExecutionUop, ...]],
        first_local: bool,
        dependency_registers: list[str] | None = None,
    ) -> None:
        register_dependencies = instruction.get("register_dependencies", {})
        address_registers = set((instruction.get("memory") or {}).get("address_registers", []))
        producer_ids: set[str] = set()
        if dependency_registers is not None:
            producer_ids.update(
                register_dependencies[register]
                for register in dependency_registers
                if register in register_dependencies
            )
        elif uop.kind == "address_generation":
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
        self._add_producer_dependencies(uop, producer_ids, result_uops)

    @staticmethod
    def _add_producer_dependencies(
        uop: ExecutionUop,
        producer_ids: set[str],
        result_uops: dict[str, tuple[ExecutionUop, ...]],
    ) -> set[str]:
        """Add producer terminal-uop dependencies and return the added IDs."""
        added: set[str] = set()
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
            selected = {
                candidate.id for candidate in (matching if matching else candidates)
            }
            uop.dependencies.update(selected)
            added.update(selected)
        return added

    def _add_register_dependencies(
        self,
        uop: ExecutionUop,
        instruction: dict[str, Any],
        result_uops: dict[str, tuple[ExecutionUop, ...]],
        registers: tuple[str, ...],
        dependency_map_key: str = "register_dependencies",
    ) -> set[str]:
        mapping = instruction.get(dependency_map_key, {})
        if not isinstance(mapping, dict):
            return set()
        producer_ids: set[str] = set()
        for register in registers:
            producer = mapping.get(register)
            if isinstance(producer, str):
                producer_ids.add(producer)
            elif isinstance(producer, (list, tuple, set)):
                producer_ids.update(str(value) for value in producer)
        return self._add_producer_dependencies(uop, producer_ids, result_uops)

    @staticmethod
    def _semantic_old_destination_registers(
        instruction: dict[str, Any],
        semantic_ids: tuple[str, ...],
        semantic_definitions: dict[str, dict[str, Any]],
        include_profile_implicit: bool = False,
    ) -> tuple[str, ...]:
        registers: list[str] = []
        explicit = instruction.get("old_destination_registers", [])
        if isinstance(explicit, (list, tuple)):
            registers.extend(str(value) for value in explicit)
        for semantic_id_value in semantic_ids:
            definition = semantic_definitions.get(semantic_id_value, {})
            values = definition.get("old_destination_registers")
            if values is None:
                values = definition.get("old_dest_registers", [])
            if isinstance(values, (list, tuple)):
                registers.extend(str(value) for value in values)
        if include_profile_implicit:
            values = instruction.get("vector_destination_registers", [])
            if isinstance(values, (list, tuple)):
                registers.extend(str(value) for value in values)
        if not registers:
            # The common in-place RVV form lists vd in both read and write
            # sets.  This fallback keeps the trace compact while still being
            # explicit about which register is the old destination.
            reads = {
                str(value)
                for value in instruction.get("register_reads", [])
                if Profile._is_vector_register(str(value))
            }
            writes = {
                str(value)
                for value in instruction.get("register_writes", [])
                if Profile._is_vector_register(str(value))
            }
            registers.extend(sorted(reads & writes))
        return tuple(dict.fromkeys(registers))

    def _add_old_destination_dependencies(
        self,
        uop: ExecutionUop,
        instruction: dict[str, Any],
        result_uops: dict[str, tuple[ExecutionUop, ...]],
        semantic_ids: tuple[str, ...],
        semantic_definitions: dict[str, dict[str, Any]],
        include_profile_implicit: bool = False,
    ) -> set[str]:
        registers = self._semantic_old_destination_registers(
            instruction,
            semantic_ids,
            semantic_definitions,
            include_profile_implicit,
        )
        if not registers:
            return set()
        # A dedicated map lets a frontend describe an old-vd edge without
        # pretending that vd is an ordinary source operand.  Fall back to the
        # regular map for existing RVV traces that already expose vd there.
        if include_profile_implicit and isinstance(
            instruction.get("vector_destination_dependencies"), dict
        ):
            mapping_key = "vector_destination_dependencies"
        elif isinstance(instruction.get("old_destination_dependencies"), dict):
            mapping_key = "old_destination_dependencies"
        else:
            mapping_key = "register_dependencies"
        return self._add_register_dependencies(
            uop, instruction, result_uops, registers, mapping_key
        )

    def _fallback_recipe(self, semantic_kinds: tuple[str, ...], key: str) -> dict[str, Any]:
        fit = self.data.get("scalar_control_fit")
        if fit is None:
            raise ProfileError(f"missing instruction recipe: {key}")
        if not fit["enabled"] or len(semantic_kinds) != 1:
            raise ProfileError(f"missing instruction recipe: {key}")
        semantic = semantic_kinds[0]
        timing = fit["uops"].get(semantic)
        if timing is None:
            raise ProfileError(f"missing instruction recipe and fallback: {key} ({semantic})")
        return {
            "decoded_macro_ops": 1,
            "retire_macro_ops": 1,
            "uops": [
                {
                    "id": "fit",
                    "kind": semantic,
                    **timing,
                    "_profile_path": f"scalar_control_fit.uops.{semantic}",
                }
            ],
        }

    def _resources(
        self, required_resource_ids: set[str] | None = None
    ) -> dict[str, Resource]:
        self._require_simulation_ready()
        result: dict[str, Resource] = {}
        fit = self.data.get("scalar_control_fit", {"resources": {}, "uops": {}})
        sources = (
            ("resources", self.data["resources"]),
            ("scalar_control_fit.resources", fit["resources"]),
        )
        if required_resource_ids is None:
            resource_ids = {
                str(resource_id)
                for _, entries in sources
                for resource_id in entries
            }
        else:
            resource_ids = set(required_resource_ids)
        for resource_id in sorted(resource_ids):
            source = next(
                (
                    (prefix, entries[resource_id])
                    for prefix, entries in sources
                    if resource_id in entries
                ),
                None,
            )
            if source is None:
                raise ProfileError(
                    f"trace references missing resource: {resource_id}"
                )
            prefix, entry = source
            path = f"{prefix}.{resource_id}"
            consumed_values = [entry["capacity"]]
            if "bytes_per_cycle" in entry:
                consumed_values.append(entry["bytes_per_cycle"])
            if required_resource_ids is None and "measure" in consumed_values:
                continue
            result[resource_id] = Resource(
                id=resource_id,
                capacity=self._parameter_int(entry["capacity"], f"{path}.capacity"),
                bytes_per_cycle=(
                    self._parameter_int(
                        entry["bytes_per_cycle"], f"{path}.bytes_per_cycle"
                    )
                    if "bytes_per_cycle" in entry
                    else None
                ),
            )
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
