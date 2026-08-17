from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


VECTOR_RESOURCE_KINDS = {"vector_fp", "vector_integer", "conversion", "shuffle"}


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
    semantic_ids: tuple[str, ...] = ()
    dependencies: set[str] = field(default_factory=set)
    issue_after_uop: str | None = None
    issue_gap_ticks: int = 0
    memory: dict[str, Any] | None = None
    dispatch_tick: int | None = None
    ready_tick: int | None = None
    issue_tick: int | None = None
    complete_tick: int | None = None
    resource: str | None = None
    resource_lane: int | None = None
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
    dispatch_tick: int | None = None
    complete_tick: int | None = None
    retire_tick: int | None = None


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
