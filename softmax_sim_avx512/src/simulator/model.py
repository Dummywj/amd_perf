from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


VECTOR_RESOURCE_KINDS = {
    "vector_fp",
    "vector_integer",
    "conversion",
    "shuffle",
    "vector_control",
    "vector_divide",
}


@dataclass
class ExecutionUop:
    id: str
    sequence: int
    parent_id: str
    parent_sequence: int
    mnemonic: str
    assembly: str
    semantic_kinds: tuple[str, ...]
    kind: str
    scheduling_class: str
    part_index: int | None
    latency_ticks: int
    issue_interval_ticks: int
    occupancy_ticks: int
    resource_choices: tuple[str, ...]
    issue_domains: tuple[str, ...]
    issue_domain_demands: dict[str, int] = field(default_factory=dict)
    rename_allocations: dict[str, int] = field(default_factory=dict)
    scheduler_partition_choices: tuple[str, ...] = ()
    execution_unit_choices: tuple[str, ...] = ()
    requires_completion_token: bool = False
    requires_vector_read_token: bool = False
    part_count: int | None = None
    semantic_ids: tuple[str, ...] = ()
    dependencies: set[str] = field(default_factory=set)
    # Subsets of ``dependencies`` introduced by profile-driven vector
    # readiness policies.  Keeping the categories separate makes the generic
    # engine observable without making the scheduler ISA-specific.
    vector_state_dependencies: set[str] = field(default_factory=set)
    old_destination_dependencies: set[str] = field(default_factory=set)
    requires_vector_state: bool = False
    reads_old_destination: bool = False
    issue_after_uop: str | None = None
    issue_gap_ticks: int = 0
    memory: dict[str, Any] | None = None
    dispatch_tick: int | None = None
    ready_tick: int | None = None
    issue_tick: int | None = None
    complete_tick: int | None = None
    resource: str | None = None
    resource_lane: int | None = None
    scheduler_partition: str | None = None
    execution_unit: str | None = None
    vector_read_domain: str | None = None
    completion_domain: str | None = None
    memory_level: str | None = None
    stall_reason: str | None = None
    stall_reasons: dict[str, int] = field(default_factory=dict)


@dataclass
class MacroOp:
    id: str
    sequence: int
    mnemonic: str
    assembly: str
    uop_ids: tuple[str, ...]
    decoded_macro_ops: int
    retire_macro_ops: int
    uses_vector_scheduler: bool
    uses_load_queue: bool
    uses_store_queue: bool
    # Profile-driven admission domains are architectural macro-op tokens.  They
    # are deliberately separate from execution-uop issue domains: a frontend
    # domain can limit admission even when the backend has multiple eligible
    # execution units.
    dispatch_domains: tuple[str, ...] = ()
    dispatch_domain_demands: dict[str, int] = field(default_factory=dict)
    rename_allocations: dict[str, int] = field(default_factory=dict)
    dispatch_units: int | None = None
    rob_entries: int | None = None
    dispatch_tick: int | None = None
    complete_tick: int | None = None
    retire_tick: int | None = None
    dispatch_blocker: str | None = None
    dispatch_blocker_domain: str | None = None
    dispatch_blocker_count: int = 0

    @property
    def dispatch_width_units(self) -> int:
        return (
            self.decoded_macro_ops
            if self.dispatch_units is None
            else self.dispatch_units
        )

    @property
    def rob_entry_count(self) -> int:
        return self.decoded_macro_ops if self.rob_entries is None else self.rob_entries


@dataclass(frozen=True)
class Resource:
    id: str
    capacity: int
    bytes_per_cycle: int | None = None


@dataclass
class BoundTrace:
    trace_version: int
    profile_id: str
    profile_sha256: str
    ticks_per_cycle: int
    macros: list[MacroOp]
    uops: list[ExecutionUop]
    resources: dict[str, Resource]
    workload: dict[str, Any]
    source_trace: dict[str, Any]
