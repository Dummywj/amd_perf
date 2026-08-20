from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal

from ..simulator.memory import CacheMode
from ..simulator.model import BoundTrace


ExecutionModel = Literal["out_of_order", "in_order"]


class SimulatorError(ValueError):
    pass


@dataclass
class SimulationResult:
    backend: str
    execution_model: ExecutionModel
    cache_mode: CacheMode
    ticks_per_cycle: int
    total_ticks: int
    cycles: float
    events: list[dict[str, Any]]
    summary: dict[str, Any]
    trace: BoundTrace

    def to_dict(self) -> dict[str, Any]:
        return {
            "result_version": 1,
            "profile_id": self.trace.profile_id,
            "profile_sha256": self.trace.profile_sha256,
            "backend": self.backend,
            "execution_model": self.execution_model,
            "cache_mode": self.cache_mode,
            "ticks_per_cycle": self.ticks_per_cycle,
            "total_ticks": self.total_ticks,
            "cycles": self.cycles,
            "workload": self.trace.workload,
            "summary": self.summary,
            "instructions": [
                {
                    "id": macro.id,
                    "sequence": macro.sequence,
                    "mnemonic": macro.mnemonic,
                    "assembly": macro.assembly,
                    "decoded_macro_ops": macro.decoded_macro_ops,
                    "dispatch_units": macro.dispatch_width_units,
                    "rob_entries": macro.rob_entry_count,
                    "retire_macro_ops": macro.retire_macro_ops,
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
                    "dispatch_tick": macro.dispatch_tick,
                    "complete_tick": macro.complete_tick,
                    "retire_tick": macro.retire_tick,
                    "uop_ids": list(macro.uop_ids),
                }
                for macro in self.trace.macros
            ],
            "uops": [
                {
                    "id": uop.id,
                    "sequence": uop.sequence,
                    "parent_id": uop.parent_id,
                    "semantic_ids": list(uop.semantic_ids),
                    "kind": uop.kind,
                    "scheduling_class": uop.scheduling_class,
                    "issue_domains": list(uop.issue_domains),
                    "issue_domain_demands": dict(
                        sorted(uop.issue_domain_demands.items())
                    ),
                    "rename_allocations": dict(
                        sorted(uop.rename_allocations.items())
                    ),
                    "scheduler_partition_choices": list(
                        uop.scheduler_partition_choices
                    ),
                    "execution_unit_choices": list(uop.execution_unit_choices),
                    "scheduler_partition": uop.scheduler_partition,
                    "execution_unit": uop.execution_unit,
                    "requires_vector_read_token": uop.requires_vector_read_token,
                    "requires_vector_state": uop.requires_vector_state,
                    "reads_old_destination": uop.reads_old_destination,
                    "vector_read_domain": uop.vector_read_domain,
                    "completion_domain": uop.completion_domain,
                    "part_index": uop.part_index,
                    "part_count": uop.part_count,
                    "resource": uop.resource,
                    "resource_lane": uop.resource_lane,
                    "memory_level": uop.memory_level,
                    "dependencies": sorted(uop.dependencies),
                    "vector_state_dependencies": sorted(
                        uop.vector_state_dependencies
                    ),
                    "old_destination_dependencies": sorted(
                        uop.old_destination_dependencies
                    ),
                    "dispatch_tick": uop.dispatch_tick,
                    "ready_tick": uop.ready_tick,
                    "issue_tick": uop.issue_tick,
                    "complete_tick": uop.complete_tick,
                    "stall_reason": uop.stall_reason,
                    "stall_reasons": dict(sorted(uop.stall_reasons.items())),
                }
                for uop in self.trace.uops
            ],
        }
