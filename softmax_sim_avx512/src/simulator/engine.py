from __future__ import annotations

import copy
import heapq
import math
from collections import Counter, deque
from dataclasses import dataclass
from typing import Any, Literal

from .model import BoundTrace, ExecutionUop, MacroOp, VECTOR_RESOURCE_KINDS
from .memory import CacheMode, MemoryHierarchy
from .profile import Profile
from .semantic import semantic_id
from .trace import validate_bound_trace


ExecutionModel = Literal["out_of_order", "in_order"]


@dataclass
class SimulationResult:
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


class SimulatorError(ValueError):
    pass


class Engine:
    def __init__(
        self,
        trace: BoundTrace,
        profile: Profile,
        execution_model: ExecutionModel,
        cache_mode: CacheMode,
        memory_compute_overlap_limit: bool | None = None,
    ):
        if execution_model not in {"out_of_order", "in_order"}:
            raise SimulatorError(f"unknown execution model: {execution_model}")
        validate_bound_trace(trace)
        # Timing and resource assignments are simulation state, not part of the
        # reusable bound trace.  Keep each run isolated so callers can compare
        # execution models without manually cloning the trace between runs.
        self.trace = copy.deepcopy(trace)
        self.profile = profile
        self.execution_model = execution_model
        self.cache_mode = cache_mode
        self.memory = MemoryHierarchy(profile, self.trace, cache_mode)
        self.tpc = self.trace.ticks_per_cycle
        self.uops = {uop.id: uop for uop in self.trace.uops}
        self.macros = {macro.id: macro for macro in self.trace.macros}
        self.rob: deque[str] = deque()
        self.unissued_dispatched: set[str] = set()
        self.completion_heap: list[tuple[int, int, str]] = []
        self.resource_free = {
            resource_id: [0] * resource.capacity
            for resource_id, resource in self.trace.resources.items()
        }
        self.last_class_issue: dict[str, int] = {}
        backend = profile.backend
        self.scheduler_partitions = {
            str(entry["id"]): entry
            for entry in backend.get("scheduler_partitions", [])
        }
        self.scheduler_partition_occupancy = {
            partition_id: 0 for partition_id in self.scheduler_partitions
        }
        self.execution_units = backend.get("execution_units", {})
        self.execution_unit_free = {
            unit_id: 0 for unit_id in self.execution_units
        }
        self.vector_read_domain_capacity: dict[str, int] = {}
        self.completion_domain_capacity: dict[str, int] = {}
        for register_file in backend.get("register_files", {}).values():
            for domain_id, domain in register_file.get("read_domains", {}).items():
                if domain_id in self.vector_read_domain_capacity:
                    raise SimulatorError(
                        f"duplicate vector read domain in backend: {domain_id}"
                    )
                self.vector_read_domain_capacity[domain_id] = int(
                    domain["arbitration_capacity"]
                )
            for domain_id, domain in register_file.get(
                "writeback_domains", {}
            ).items():
                if domain_id in self.completion_domain_capacity:
                    raise SimulatorError(
                        f"duplicate completion domain in backend: {domain_id}"
                    )
                self.completion_domain_capacity[domain_id] = int(
                    domain["arbitration_capacity"]
                )
        self.vector_read_domain_reservations: dict[str, Counter[int]] = {
            domain_id: Counter() for domain_id in self.vector_read_domain_capacity
        }
        self.completion_domain_reservations: dict[str, Counter[int]] = {
            domain_id: Counter() for domain_id in self.completion_domain_capacity
        }
        self._validate_topology_choices()
        self.dispatch_domain_capacity = {
            str(domain_id): profile._parameter_int(
                domain["capacity"],
                f"backend.dispatch_domains.{domain_id}.capacity",
            )
            for domain_id, domain in backend.get("dispatch_domains", {}).items()
        }
        self.dispatch_domain_tokens: Counter[str] = Counter()
        self.dispatch_domain_blockers: Counter[str] = Counter()
        rename = profile.rename_policy
        self.rename_enabled = bool(rename["enabled"])
        self.rename_free = dict(rename["free_lists"])
        self.rename_initial_free = dict(self.rename_free)
        self.rename_allocation_width = int(rename["allocation_width"])
        self.rename_release_width = int(rename["release_width"])
        self.rename_release_delay_ticks = int(rename["release_delay_ticks"])
        self.rename_availability_delay_ticks = int(
            rename["availability_delay_ticks"]
        )
        self.rename_guard_entries = int(rename["guard_entries"])
        self.rename_policy_name = str(rename["policy"])
        self.rename_pending_releases: list[tuple[int, int, dict[str, int]]] = []
        self.rename_allocation_tokens = 0
        self.rename_release_tokens = 0
        self.rename_blockers: Counter[str] = Counter()
        self.issue_domain_free = {
            domain_id: [0] * int(entry["capacity"])
            for domain_id, entry in profile.data["issue_domains"].items()
        }
        unknown_issue_domains = sorted(
            {
                domain_id
                for uop in self.trace.uops
                for domain_id in uop.issue_domains
                if domain_id not in self.issue_domain_free
            }
        )
        if unknown_issue_domains:
            raise SimulatorError(
                "bound trace references unknown issue domains: "
                + ", ".join(unknown_issue_domains)
            )
        overlap = profile.memory_compute_overlap_limit
        self.memory_compute_overlap_limit_enabled = (
            bool(overlap["enabled"])
            if memory_compute_overlap_limit is None
            else memory_compute_overlap_limit
        )
        self.max_pending_memory_compute_groups = int(overlap["max_pending_groups"])
        self.memory_compute_semantic_kinds = frozenset(
            str(value) for value in overlap["compute_semantic_kinds"]
        )
        self.semantic_kind_by_id = {
            semantic_id(str(instruction["id"]), str(semantic["local_id"])): str(
                semantic["kind"]
            )
            for instruction in self.trace.source_trace.get("instructions", [])
            for semantic in instruction.get("semantic_uops", [])
        }
        self.vector_memory_policy = profile.vector_memory_policy
        self.vector_memory_inflight: dict[str, set[str]] = {
            "load": set(),
            "store": set(),
        }
        self.vector_memory_service_heap: list[tuple[int, int, str]] = []
        self.vector_memory_split_issue_free = {
            "load": [0] * self.vector_memory_policy.get("split_lanes", {}).get(
                "load", 1
            ),
            "store": [0] * self.vector_memory_policy.get("split_lanes", {}).get(
                "store", 1
            ),
        }
        self.vector_memory_flow_counts: Counter[int] = Counter()
        self.memory_compute_groups = self._discover_memory_compute_groups()
        self.pending_memory_compute_groups: set[str] = set()
        self.next_dispatch = 0
        # Dispatch bandwidth can drain one macro-op over multiple architectural
        # cycles when its execution uops exceed the frontend or IQ enqueue
        # width.  Keep progress separate from the architectural ROB entry.
        self.dispatch_unit_progress: Counter[str] = Counter()
        self.in_order_issue_index = 0
        self.rob_occupancy = 0
        self.vector_scheduler_occupancy = 0
        self.load_queue_occupancy = 0
        self.store_queue_occupancy = 0
        self.peaks = Counter()
        self.stalls = Counter()
        self.events: list[dict[str, Any]] = []

    def _validate_topology_choices(self) -> None:
        known_partitions = set(self.scheduler_partitions)
        known_units = set(self.execution_units)
        for uop in self.trace.uops:
            unknown_partitions = set(uop.scheduler_partition_choices) - known_partitions
            if unknown_partitions:
                raise SimulatorError(
                    f"uop {uop.id} references unknown scheduler partitions: "
                    + ", ".join(sorted(unknown_partitions))
                )
            unknown_units = set(uop.execution_unit_choices) - known_units
            if unknown_units:
                raise SimulatorError(
                    f"uop {uop.id} references unknown execution units: "
                    + ", ".join(sorted(unknown_units))
                )
            derived_partitions = {
                self.execution_units[unit_id]["scheduler_partition"]
                for unit_id in uop.execution_unit_choices
            }
            if set(uop.scheduler_partition_choices) != derived_partitions:
                raise SimulatorError(
                    f"uop {uop.id} scheduler choices do not match its execution units"
                )
            for unit_id in uop.execution_unit_choices:
                unit = self.execution_units[unit_id]
                if not set(uop.resource_choices).intersection(unit["functional_units"]):
                    raise SimulatorError(
                        f"uop {uop.id} has no functional resource on unit {unit_id}"
                    )
                if uop.requires_completion_token:
                    domain_id = unit.get("vector_writeback_domain")
                    if domain_id not in self.completion_domain_capacity:
                        raise SimulatorError(
                            f"uop {uop.id} requires missing completion domain on "
                            f"unit {unit_id}"
                        )
                if uop.requires_vector_read_token:
                    domain_id = unit.get("vector_read_domain")
                    if domain_id not in self.vector_read_domain_capacity:
                        raise SimulatorError(
                            f"uop {uop.id} requires missing vector read domain on "
                            f"unit {unit_id}"
                        )

    def run(self) -> SimulationResult:
        now = 0
        iteration_guard = 0
        while self.next_dispatch < len(self.trace.macros) or self.rob:
            iteration_guard += 1
            if iteration_guard > max(10000, len(self.trace.uops) * 100):
                raise SimulatorError("event loop did not converge")
            self._complete(now)
            self._release_vector_memory_flows(now)
            self._release_rename(now)
            if now % self.tpc == 0:
                self._dispatch(now)
            self._issue_fixed_point(now)
            self._complete(now)
            if now % self.tpc == 0:
                self._retire(now)
            self._record_peaks()
            if self.next_dispatch >= len(self.trace.macros) and not self.rob:
                break
            next_tick = self._next_event_tick(now)
            if next_tick <= now:
                raise SimulatorError(f"no forward progress at tick {now}")
            now = next_tick

        summary = {
            "dynamic_macro_ops": len(self.trace.macros),
            "execution_uops": len(self.trace.uops),
            "dispatch_units": sum(
                macro.dispatch_width_units for macro in self.trace.macros
            ),
            "rob_entries_allocated": sum(
                macro.rob_entry_count for macro in self.trace.macros
            ),
            "retired_macro_ops": sum(macro.retire_macro_ops for macro in self.trace.macros),
            "peak_rob": self.peaks["rob"],
            "peak_vector_scheduler": self.peaks["vector_scheduler"],
            "peak_scheduler_partitions": {
                partition_id: self.peaks[f"scheduler_partition:{partition_id}"]
                for partition_id in self.scheduler_partitions
            },
            "peak_load_queue": self.peaks["load_queue"],
            "peak_store_queue": self.peaks["store_queue"],
            "dependency_critical_path_cycles": self._dependency_critical_path_cycles(),
            "dispatch_stalls": dict(sorted(self.stalls.items())),
            "dispatch_domain_capacities": dict(
                sorted(self.dispatch_domain_capacity.items())
            ),
            "dispatch_domain_usage": dict(
                sorted(self.dispatch_domain_tokens.items())
            ),
            "dispatch_domain_blockers": dict(
                sorted(self.dispatch_domain_blockers.items())
            ),
            "dispatch_domain_stats": {
                domain_id: {
                    "capacity": self.dispatch_domain_capacity[domain_id],
                    "tokens": self.dispatch_domain_tokens.get(domain_id, 0),
                    "blocked": self.dispatch_domain_blockers.get(domain_id, 0),
                }
                for domain_id in sorted(self.dispatch_domain_capacity)
            },
            "rename": {
                "enabled": self.rename_enabled,
                "initial_free": dict(sorted(self.rename_initial_free.items())),
                "remaining_free": dict(sorted(self.rename_free.items())),
                "peak_allocated": {
                    name: self.rename_initial_free[name] - self.rename_free[name]
                    for name in sorted(self.rename_initial_free)
                },
                "allocation_tokens": self.rename_allocation_tokens,
                "release_tokens": self.rename_release_tokens,
                "blockers": dict(sorted(self.rename_blockers.items())),
            },
            "issue_blocker_observations": dict(
                sorted(
                    sum(
                        (Counter(uop.stall_reasons) for uop in self.trace.uops),
                        Counter(),
                    ).items()
                )
            ),
            "resource_issues": dict(
                sorted(
                    Counter(uop.resource for uop in self.trace.uops if uop.resource).items()
                )
            ),
            "execution_unit_issues": dict(
                sorted(
                    Counter(
                        uop.execution_unit
                        for uop in self.trace.uops
                        if uop.execution_unit
                    ).items()
                )
            ),
            "vector_read_domain_reads": dict(
                sorted(
                    Counter(
                        uop.vector_read_domain
                        for uop in self.trace.uops
                        if uop.vector_read_domain
                    ).items()
                )
            ),
            "completion_domain_writes": dict(
                sorted(
                    Counter(
                        uop.completion_domain
                        for uop in self.trace.uops
                        if uop.completion_domain
                    ).items()
                )
            ),
            "cache_line_accesses": dict(self.memory.hits),
            "memory_compute_overlap_limit": {
                "enabled": self.memory_compute_overlap_limit_enabled,
                "max_pending_groups": self.max_pending_memory_compute_groups,
                "compute_semantic_kinds": sorted(
                    self.memory_compute_semantic_kinds
                ),
                "eligible_groups": len(self.memory_compute_groups),
                "peak_pending_groups": self.peaks["memory_compute_pending_groups"],
            },
            "vector_memory": {
                "issue_order": self.vector_memory_policy["issue_order"],
                "service_capacity": self.vector_memory_policy.get(
                    "service_capacity", {}
                ),
                "service_ticks": self.vector_memory_policy.get(
                    "service_ticks", {}
                ),
                "store_completion_ticks": self.vector_memory_policy[
                    "store_completion_ticks"
                ],
                "split_lanes": self.vector_memory_policy["split_lanes"],
                "peak_inflight_accesses": {
                    kind: self.peaks[f"vector_memory_inflight_{kind}"]
                    for kind in ("load", "store")
                },
                "flow_split": self.vector_memory_policy.get("flow_split"),
                "flow_count_accesses": {
                    str(flow_count): count
                    for flow_count, count in sorted(
                        self.vector_memory_flow_counts.items()
                    )
                },
            },
        }
        return SimulationResult(
            execution_model=self.execution_model,
            cache_mode=self.cache_mode,
            ticks_per_cycle=self.tpc,
            total_ticks=now,
            cycles=now / self.tpc,
            events=self.events,
            summary=summary,
            trace=self.trace,
        )

    def _dependency_critical_path_cycles(self) -> float:
        indegree = {uop.id: len(uop.dependencies) for uop in self.trace.uops}
        consumers: dict[str, list[str]] = {uop.id: [] for uop in self.trace.uops}
        for uop in self.trace.uops:
            for dependency in uop.dependencies:
                consumers[dependency].append(uop.id)
        ready = [
            (self.uops[uop_id].sequence, uop_id)
            for uop_id, degree in indegree.items()
            if degree == 0
        ]
        heapq.heapify(ready)
        finish: dict[str, int] = {}
        while ready:
            _, uop_id = heapq.heappop(ready)
            uop = self.uops[uop_id]
            dependency_finish = max(
                (finish[dependency] for dependency in uop.dependencies), default=0
            )
            finish[uop.id] = dependency_finish + uop.latency_ticks
            for consumer in consumers[uop.id]:
                indegree[consumer] -= 1
                if indegree[consumer] == 0:
                    heapq.heappush(
                        ready, (self.uops[consumer].sequence, consumer)
                    )
        return max(finish.values(), default=0) / self.tpc

    def _complete(self, now: int) -> bool:
        changed = False
        while self.completion_heap and self.completion_heap[0][0] <= now:
            complete_tick, _, uop_id = heapq.heappop(self.completion_heap)
            uop = self.uops[uop_id]
            if uop.complete_tick is not None:
                continue
            uop.complete_tick = complete_tick
            # Legacy profiles bind flow occupancy to completion. Profiles with
            # service_cycles release the flow token independently below.
            if self._vector_memory_service_ticks(uop) is None:
                access_kind = self._vector_memory_access_kind(uop)
                self.vector_memory_inflight[access_kind].discard(uop.id)
            self.events.append(self._event("complete", complete_tick, uop))
            parent = self.macros[uop.parent_id]
            if all(
                self.uops[value].complete_tick is not None
                for value in parent.uop_ids
            ):
                parent.complete_tick = max(
                    self.uops[value].complete_tick or 0 for value in parent.uop_ids
                )
            changed = True
        return changed

    def _release_vector_memory_flows(self, now: int) -> bool:
        changed = False
        while (
            self.vector_memory_service_heap
            and self.vector_memory_service_heap[0][0] <= now
        ):
            _, _, uop_id = heapq.heappop(self.vector_memory_service_heap)
            uop = self.uops[uop_id]
            access_kind = self._vector_memory_access_kind(uop)
            if uop_id in self.vector_memory_inflight[access_kind]:
                self.vector_memory_inflight[access_kind].remove(uop_id)
                changed = True
        return changed

    def _vector_memory_service_ticks(self, uop: ExecutionUop) -> int | None:
        if "service_ticks" not in self.vector_memory_policy:
            return None
        return self.vector_memory_policy["service_ticks"].get(
            "load" if uop.kind == "load_data" else "store"
        )

    @staticmethod
    def _vector_memory_access_kind(uop: ExecutionUop) -> str:
        return "load" if uop.kind == "load_data" else "store"

    def _vector_memory_flow_count(self, uop: ExecutionUop) -> int:
        split = self.vector_memory_policy.get("flow_split")
        memory = uop.memory
        if split is None or not memory:
            return 1
        address = memory.get("address")
        byte_count = memory.get("bytes")
        if (
            isinstance(address, bool)
            or not isinstance(address, int)
            or isinstance(byte_count, bool)
            or not isinstance(byte_count, int)
            or byte_count <= 0
        ):
            return 1
        boundary = split["boundary_bytes"]
        covered = (address % boundary) + byte_count
        flow_count = (covered + boundary - 1) // boundary
        return min(flow_count, split["max_flows_per_access"])

    def _reserve_vector_memory_split_issue(
        self, uop: ExecutionUop, now: int
    ) -> None:
        split = self.vector_memory_policy.get("flow_split")
        if split is None:
            return
        flow_count = self._vector_memory_flow_count(uop)
        self.vector_memory_flow_counts[flow_count] += 1
        access_kind = self._vector_memory_access_kind(uop)
        lanes = self.vector_memory_split_issue_free[access_kind]
        lane = min(range(len(lanes)), key=lambda index: (lanes[index], index))
        lanes[lane] = (
            now + flow_count * split["issue_ticks_per_flow"]
        )

    def _dispatch(self, now: int) -> None:
        width = int(self.profile.pipeline["dispatch_macro_ops_per_cycle"])
        dispatched = 0
        partition_enqueues: Counter[str] = Counter()
        dispatch_domain_usage: Counter[str] = Counter()
        rename_usage: Counter[str] = Counter()
        while self.next_dispatch < len(self.trace.macros) and dispatched < width:
            macro = self.trace.macros[self.next_dispatch]
            pending_uop_ids = tuple(
                uop_id
                for uop_id in macro.uop_ids
                if self.uops[uop_id].dispatch_tick is None
            )
            if not pending_uop_ids:
                self.next_dispatch += 1
                continue

            admitted = macro.dispatch_tick is not None
            progress = self.dispatch_unit_progress[macro.id]
            remaining_width = width - dispatched
            partition_assignment: dict[str, str] | None = None
            chunk_uop_ids: tuple[str, ...] = ()
            dispatch_delta = 0

            # A macro-op that fits one architectural dispatch cycle remains
            # atomic when only the tail of the cycle is left by an earlier
            # macro.  This preserves the existing frontend behavior for Zen4
            # and small macro-ops; partial draining is reserved for a macro
            # that intrinsically exceeds one cycle or its IQ enqueue width.
            if (
                not admitted
                and progress == 0
                and macro.dispatch_width_units <= width
                and macro.dispatch_width_units > remaining_width
            ):
                break

            # Keep the existing atomic path for a macro that fits the frontend
            # budget and can be admitted to all of its scheduler partitions.
            if (
                not admitted
                and progress == 0
                and macro.dispatch_width_units <= remaining_width
            ):
                atomic_assignment = self._plan_partition_assignment(
                    macro,
                    partition_enqueues,
                    uop_ids=pending_uop_ids,
                )
                if atomic_assignment is not None:
                    partition_assignment = atomic_assignment
                    chunk_uop_ids = pending_uop_ids
                    dispatch_delta = macro.dispatch_width_units

            if partition_assignment is None:
                (
                    chunk_uop_ids,
                    partition_assignment,
                    dispatch_delta,
                    budget_limited,
                ) = self._select_dispatch_chunk(
                    macro,
                    pending_uop_ids,
                    partition_enqueues,
                    remaining_width,
                    progress,
                )
                if partition_assignment is None:
                    if budget_limited:
                        # A single frontend uop can account for more dispatch
                        # units than fit in one cycle.  Consume the partial
                        # decoder work without exposing the execution uop yet.
                        reason = self._dispatch_blocker(
                            macro,
                            {},
                            dispatch_domain_usage,
                            rename_usage,
                            admitted=admitted,
                            check_partition=False,
                        )
                        if reason:
                            self._record_dispatch_blocker(macro, now, reason)
                            break
                        if not admitted:
                            self._admit_macro(
                                macro, now, dispatch_domain_usage, rename_usage
                            )
                        self.dispatch_unit_progress[macro.id] += dispatch_delta
                        dispatched += dispatch_delta
                        break
                    reason = self._dispatch_blocker(
                        macro,
                        None,
                        dispatch_domain_usage,
                        rename_usage,
                        admitted=admitted,
                        pending_uop_ids=pending_uop_ids,
                    )
                    if reason:
                        self._record_dispatch_blocker(macro, now, reason)
                    break

            reason = self._dispatch_blocker(
                macro,
                partition_assignment,
                dispatch_domain_usage,
                rename_usage,
                admitted=admitted,
            )
            if reason:
                self._record_dispatch_blocker(macro, now, reason)
                break
            if not admitted:
                self._admit_macro(macro, now, dispatch_domain_usage, rename_usage)

            self.dispatch_unit_progress[macro.id] += dispatch_delta
            dispatched += dispatch_delta
            for uop_id in chunk_uop_ids:
                uop = self.uops[uop_id]
                uop.dispatch_tick = now
                uop.scheduler_partition = partition_assignment.get(uop_id)
                if uop.scheduler_partition is not None:
                    partition_enqueues[uop.scheduler_partition] += 1
                    self.scheduler_partition_occupancy[uop.scheduler_partition] += 1
                    peak_key = f"scheduler_partition:{uop.scheduler_partition}"
                    self.peaks[peak_key] = max(
                        self.peaks[peak_key],
                        self.scheduler_partition_occupancy[uop.scheduler_partition],
                    )
                self.unissued_dispatched.add(uop_id)
                self.events.append(self._event("dispatch", now, uop))

            if all(
                self.uops[uop_id].dispatch_tick is not None for uop_id in macro.uop_ids
            ):
                if self.dispatch_unit_progress[macro.id] != macro.dispatch_width_units:
                    raise SimulatorError(
                        f"dispatch accounting did not converge for {macro.id}"
                    )
                self.next_dispatch += 1
            else:
                # The frontend drains one macro-op in order.  No later macro
                # can consume the remaining dispatch width in this cycle.
                break

    def _record_dispatch_blocker(
        self, macro: MacroOp, now: int, reason: str
    ) -> None:
        self.stalls[reason] += 1
        macro.dispatch_blocker = reason
        macro.dispatch_blocker_count += 1
        if reason == "dispatch_domain_full":
            if macro.dispatch_blocker_domain is None:
                raise SimulatorError(
                    "dispatch-domain blocker is missing its domain"
                )
            self.dispatch_domain_blockers[macro.dispatch_blocker_domain] += 1
        else:
            macro.dispatch_blocker_domain = None
        self.events.append(
            {
                "type": "dispatch_blocked",
                "tick": now,
                "instruction_id": macro.id,
                "sequence": macro.sequence,
                "mnemonic": macro.mnemonic,
                "assembly": macro.assembly,
                "reason": reason,
                "domain": (
                    macro.dispatch_blocker_domain
                    if reason == "dispatch_domain_full"
                    else None
                ),
            }
        )

    def _admit_macro(
        self,
        macro: MacroOp,
        now: int,
        dispatch_domain_usage: Counter[str],
        rename_usage: Counter[str],
    ) -> None:
        macro.dispatch_tick = now
        self.rob.append(macro.id)
        self.rob_occupancy += macro.rob_entry_count
        if self._uses_legacy_vector_scheduler(macro):
            self.vector_scheduler_occupancy += 1
        self.load_queue_occupancy += int(macro.uses_load_queue)
        self.store_queue_occupancy += int(macro.uses_store_queue)
        for domain_id in macro.dispatch_domains:
            demand = macro.dispatch_domain_demands.get(domain_id, 1)
            dispatch_domain_usage[domain_id] += demand
            self.dispatch_domain_tokens[domain_id] += demand
        if self.rename_enabled:
            for name, demand in macro.rename_allocations.items():
                self.rename_free[name] -= demand
                rename_usage[name] += demand
                self.rename_allocation_tokens += demand

    def _dispatch_unit_costs(self, macro: MacroOp) -> tuple[int, ...]:
        count = len(macro.uop_ids)
        width = macro.dispatch_width_units
        return tuple(
            ((index + 1) * width) // count - (index * width) // count
            for index in range(count)
        )

    def _select_dispatch_chunk(
        self,
        macro: MacroOp,
        pending_uop_ids: tuple[str, ...],
        partition_enqueues: Counter[str],
        dispatch_budget: int,
        progress: int,
    ) -> tuple[tuple[str, ...], dict[str, str] | None, int, bool]:
        costs = self._dispatch_unit_costs(macro)
        first_index = next(
            index
            for index, uop_id in enumerate(macro.uop_ids)
            if uop_id == pending_uop_ids[0]
        )
        already_accounted = sum(costs[:first_index])
        partial_cost = progress - already_accounted
        cumulative = 0
        for count in range(len(pending_uop_ids), 0, -1):
            cumulative = sum(costs[first_index : first_index + count])
            delta = cumulative - partial_cost
            if delta < 0 or delta > dispatch_budget:
                continue
            candidate_ids = pending_uop_ids[:count]
            assignment = self._plan_partition_assignment(
                macro,
                partition_enqueues,
                uop_ids=candidate_ids,
            )
            if assignment is not None:
                return candidate_ids, assignment, delta, False

        first_cost = costs[first_index] - partial_cost
        if first_cost > dispatch_budget and dispatch_budget > 0:
            return (), None, dispatch_budget, True
        return (), None, 0, False

    def _dispatch_blocker(
        self,
        macro: MacroOp,
        partition_assignment: dict[str, str] | None,
        dispatch_domain_usage: Counter[str] | None = None,
        rename_usage: Counter[str] | None = None,
        *,
        admitted: bool = False,
        check_partition: bool = True,
        pending_uop_ids: tuple[str, ...] | None = None,
    ) -> str | None:
        pipeline = self.profile.pipeline
        if not admitted:
            if self.rob_occupancy + macro.rob_entry_count > int(
                pipeline["rob_entries"]
            ):
                return "rob_full"
            usage = (
                dispatch_domain_usage
                if dispatch_domain_usage is not None
                else Counter()
            )
            for domain_id in macro.dispatch_domains:
                demand = macro.dispatch_domain_demands.get(domain_id, 1)
                capacity = self.dispatch_domain_capacity.get(domain_id)
                if capacity is None:
                    raise SimulatorError(
                        f"macro {macro.id} references unknown dispatch domain: {domain_id}"
                    )
                if usage[domain_id] + demand > capacity:
                    macro.dispatch_blocker_domain = domain_id
                    return "dispatch_domain_full"
            rename_reason = self._rename_blocker(macro, rename_usage or Counter())
            if rename_reason is not None:
                return rename_reason
            if (
                self._uses_legacy_vector_scheduler(macro)
                and self.vector_scheduler_occupancy
                + int(macro.uses_vector_scheduler)
                > int(pipeline["vector_scheduler_entries"])
            ):
                return "vector_scheduler_full"
            if macro.uses_load_queue and self.load_queue_occupancy >= int(
                pipeline["load_queue_entries"]
            ):
                return "load_queue_full"
            if macro.uses_store_queue and self.store_queue_occupancy >= int(
                pipeline["store_queue_entries"]
            ):
                return "store_queue_full"
        if not check_partition:
            return None
        if partition_assignment is None:
            if self._plan_partition_assignment(
                macro,
                enforce_enqueue_width=False,
                uop_ids=pending_uop_ids,
            ) is None:
                return "scheduler_partition_full"
            return "scheduler_partition_enqueue_width"
        return None

    def _rename_blocker(
        self, macro: MacroOp, cycle_usage: Counter[str]
    ) -> str | None:
        if not self.rename_enabled or not macro.rename_allocations:
            return None
        allocations = macro.rename_allocations
        unknown = set(allocations) - set(self.rename_free)
        if unknown:
            raise SimulatorError(
                f"macro {macro.id} references unknown rename free list: "
                + ", ".join(sorted(unknown))
            )
        total = sum(allocations.values())
        if sum(cycle_usage.values()) + total > self.rename_allocation_width:
            self.rename_blockers["rename_allocation_width"] += 1
            return "rename_allocation_width"
        for name, demand in allocations.items():
            if self.rename_free[name] - demand < self.rename_guard_entries:
                self.rename_blockers[f"rename_free_list:{name}"] += 1
                return f"rename_free_list:{name}"
        if self.rename_policy_name == "all_files_must_be_ready":
            # The per-list guard checks above are intentionally performed for
            # every listed allocation, so one unavailable file blocks the
            # architectural instruction as a whole.
            return None
        return None

    def _release_rename(self, now: int) -> None:
        if not self.rename_enabled or not self.rename_pending_releases:
            return
        released = 0
        while self.rename_pending_releases:
            ready_tick, _, allocations = self.rename_pending_releases[0]
            if ready_tick > now:
                break
            amount = sum(allocations.values())
            remaining_width = self.rename_release_width - released
            if remaining_width <= 0:
                break
            heapq.heappop(self.rename_pending_releases)
            leftover: dict[str, int] = {}
            for name, count in allocations.items():
                returned = min(count, remaining_width)
                self.rename_free[name] += returned
                remaining_width -= returned
                released += returned
                self.rename_release_tokens += returned
                if count > returned:
                    leftover[name] = count - returned
            if leftover:
                heapq.heappush(
                    self.rename_pending_releases,
                    (ready_tick, _, leftover),
                )
                break

    def _uses_legacy_vector_scheduler(self, macro: MacroOp) -> bool:
        return macro.uses_vector_scheduler and any(
            not self.uops[uop_id].scheduler_partition_choices
            for uop_id in macro.uop_ids
            if self.uops[uop_id].kind in VECTOR_RESOURCE_KINDS
        )

    def _plan_partition_assignment(
        self,
        macro: MacroOp,
        cycle_enqueues: Counter[str] | None = None,
        *,
        enforce_enqueue_width: bool = True,
        uop_ids: tuple[str, ...] | None = None,
    ) -> dict[str, str] | None:
        occupancy = dict(self.scheduler_partition_occupancy)
        enqueues = Counter(cycle_enqueues or {})
        result: dict[str, str] = {}
        selected_uop_ids = macro.uop_ids if uop_ids is None else uop_ids
        pending = sorted(
            (
                self.uops[uop_id]
                for uop_id in selected_uop_ids
                if self.uops[uop_id].scheduler_partition_choices
            ),
            key=lambda uop: (len(uop.scheduler_partition_choices), uop.sequence),
        )

        def assign(index: int) -> bool:
            if index == len(pending):
                return True
            uop = pending[index]
            choices = sorted(
                (
                    partition_id
                    for partition_id in uop.scheduler_partition_choices
                    if occupancy[partition_id]
                    < int(self.scheduler_partitions[partition_id]["entries"])
                    and (
                        not enforce_enqueue_width
                        or enqueues[partition_id]
                        < int(
                            self.scheduler_partitions[partition_id]["enqueue_width"]
                        )
                    )
                ),
                key=lambda value: (
                    occupancy[value]
                    / int(self.scheduler_partitions[value]["entries"]),
                    occupancy[value],
                    value,
                ),
            )
            for partition_id in choices:
                result[uop.id] = partition_id
                occupancy[partition_id] += 1
                enqueues[partition_id] += 1
                if assign(index + 1):
                    return True
                occupancy[partition_id] -= 1
                enqueues[partition_id] -= 1
                del result[uop.id]
            return False

        return result if assign(0) else None

    def _issue_fixed_point(self, now: int) -> None:
        while True:
            changed = self._complete(now)
            issued = self._issue_once(now)
            if not changed and not issued:
                break

    def _issue_once(self, now: int) -> bool:
        candidates = self._issue_candidates()
        issued = False
        for uop in candidates:
            reason, earliest = self._issue_blocker(uop, now)
            if reason:
                uop.stall_reason = reason
                uop.stall_reasons[reason] = uop.stall_reasons.get(reason, 0) + 1
                if self.execution_model == "in_order":
                    break
                continue
            (
                resource_id,
                lane,
                execution_unit,
                vector_read_domain,
                completion_domain,
            ) = (
                self._select_execution(uop, now)
            )
            uop.ready_tick = self._dependency_ready_tick(uop)
            uop.issue_tick = now
            self.unissued_dispatched.remove(uop.id)
            uop.resource = resource_id
            uop.resource_lane = lane
            uop.execution_unit = execution_unit
            uop.vector_read_domain = vector_read_domain
            uop.completion_domain = completion_domain
            if uop.kind in {"load_data", "store_data"}:
                access = self.memory.access(uop, now)
                uop.memory_level = access.level
                # Recipe latency represents execution-side service before a
                # memory result is architecturally visible; hierarchy latency
                # represents the selected cache/memory level.  Completion may
                # not precede either constraint.  This also gives stores a
                # completion point that retirement and a trailing fence can
                # observe instead of treating them as zero-latency fire-and-
                # forget operations.
                uop.latency_ticks = max(uop.latency_ticks, access.latency_ticks)
                if self._is_vector_memory_uop(uop):
                    if uop.kind == "store_data":
                        uop.latency_ticks = max(
                            uop.latency_ticks,
                            self.vector_memory_policy["store_completion_ticks"],
                        )
                    service_ticks = self._vector_memory_service_ticks(uop)
                    access_kind = self._vector_memory_access_kind(uop)
                    self.vector_memory_inflight[access_kind].add(uop.id)
                    self._reserve_vector_memory_split_issue(uop, now)
                    if service_ticks is not None:
                        if service_ticks == 0:
                            self.vector_memory_inflight[access_kind].discard(uop.id)
                        else:
                            heapq.heappush(
                                self.vector_memory_service_heap,
                                (now + service_ticks, uop.sequence, uop.id),
                            )
            self.resource_free[resource_id][lane] = now + uop.occupancy_ticks
            if execution_unit is not None:
                self.execution_unit_free[execution_unit] = (
                    now + uop.occupancy_ticks
                )
            if uop.scheduler_partition is not None:
                partition_id = uop.scheduler_partition
                self.scheduler_partition_occupancy[partition_id] -= 1
                if self.scheduler_partition_occupancy[partition_id] < 0:
                    raise SimulatorError(
                        f"negative scheduler occupancy for {partition_id}"
                    )
            self.last_class_issue[uop.scheduling_class] = now
            self._reserve_issue_domains(uop, now)
            if vector_read_domain is not None:
                self._reserve_vector_read_domain(vector_read_domain, now)
            self._update_memory_compute_groups_after_issue(uop)
            if (
                uop.kind in VECTOR_RESOURCE_KINDS
                and self._uses_legacy_vector_scheduler(self.macros[uop.parent_id])
            ):
                parent = self.macros[uop.parent_id]
                if not any(
                    self.uops[value].issue_tick is not None
                    for value in parent.uop_ids
                    if value != uop.id and self.uops[value].kind in VECTOR_RESOURCE_KINDS
                ):
                    self.vector_scheduler_occupancy -= 1
            completion_tick = now + uop.latency_ticks
            if completion_domain is not None:
                reserved_tick = self._reserve_completion_domain(
                    completion_domain, completion_tick
                )
                if reserved_tick != completion_tick:
                    # A variable-latency memory access can discover a different
                    # completion tick after issue. Model writeback arbitration
                    # as delayed visibility rather than losing the result.
                    completion_tick = reserved_tick
                    uop.latency_ticks = completion_tick - now
            heapq.heappush(
                self.completion_heap, (completion_tick, uop.sequence, uop.id)
            )
            self.events.append(self._event("ready", uop.ready_tick, uop))
            self.events.append(self._event("issue", now, uop))
            issued = True
            if self.execution_model == "in_order":
                self.in_order_issue_index += 1
        return issued

    def _issue_candidates(self) -> list[ExecutionUop]:
        if self.execution_model == "in_order":
            if self.in_order_issue_index >= len(self.trace.uops):
                return []
            uop = self.trace.uops[self.in_order_issue_index]
            return [uop] if uop.id in self.unissued_dispatched else []
        return sorted(
            (self.uops[uop_id] for uop_id in self.unissued_dispatched),
            key=lambda uop: uop.sequence,
        )

    def _dependency_ready_tick(self, uop: ExecutionUop) -> int:
        return max(
            [uop.dispatch_tick or 0]
            + [self.uops[value].complete_tick or 0 for value in uop.dependencies]
        )

    def _issue_blocker(self, uop: ExecutionUop, now: int) -> tuple[str | None, int]:
        incomplete = [
            self.uops[value]
            for value in uop.dependencies
            if self.uops[value].complete_tick is None
        ]
        if incomplete:
            if any(
                value.id in uop.vector_state_dependencies for value in incomplete
            ):
                reason = "vector_state_dependency"
            elif any(
                value.id in uop.old_destination_dependencies for value in incomplete
            ):
                reason = "old_destination_dependency"
            else:
                reason = "dependency"
            known = [
                value.issue_tick + value.latency_ticks
                for value in incomplete
                if value.issue_tick is not None
            ]
            return reason, min(known) if known else math.inf
        dependency_ready = self._dependency_ready_tick(uop)
        if dependency_ready > now:
            return "dependency", dependency_ready
        if uop.issue_after_uop:
            previous = self.uops[uop.issue_after_uop]
            if previous.issue_tick is None:
                return "part_order", math.inf
            earliest = previous.issue_tick + uop.issue_gap_ticks
            if earliest > now:
                return "part_gap", earliest
        if self._memory_compute_overlap_blocked(uop):
            return "memory_compute_overlap_limit", math.inf
        last_issue = self.last_class_issue.get(uop.scheduling_class)
        if last_issue is not None:
            earliest = last_issue + uop.issue_interval_ticks
            if earliest > now:
                return "issue_interval", earliest
        if not any(min(self.resource_free[value]) <= now for value in uop.resource_choices):
            earliest = min(
                min(self.resource_free[value]) for value in uop.resource_choices
            )
            return "resource_busy", earliest
        if uop.execution_unit_choices:
            units = self._eligible_execution_units(uop)
            if not units:
                raise SimulatorError(
                    f"uop {uop.id} has no execution unit in scheduler partition "
                    f"{uop.scheduler_partition}"
                )
            if not any(self.execution_unit_free[unit_id] <= now for unit_id in units):
                return "execution_unit_busy", min(
                    self.execution_unit_free[unit_id] for unit_id in units
                )
        if uop.kind in {"load_data", "store_data"}:
            vector_memory_reason, vector_memory_earliest = self._vector_memory_blocker(
                uop, now
            )
            if vector_memory_reason:
                return vector_memory_reason, vector_memory_earliest
            reason, earliest = self.memory.blocker(uop, now)
            if reason:
                return reason, earliest
        domain_ready_ticks = [
            self._issue_domain_ready_tick(uop, domain_id)
            for domain_id in uop.issue_domains
        ]
        if any(ready_tick > now for ready_tick in domain_ready_ticks):
            earliest = max(domain_ready_ticks)
            return "issue_domain_busy", earliest
        read_eligible = self._execution_candidates(
            uop, now, check_completion=False, check_vector_read=True
        )
        if not read_eligible:
            without_vector_read = self._execution_candidates(
                uop, now, check_completion=False, check_vector_read=False
            )
            if without_vector_read:
                return (
                    "vector_read_domain_busy",
                    self._next_architectural_cycle_tick(now),
                )
        candidates = self._execution_candidates(
            uop, now, check_completion=True, check_vector_read=True
        )
        if not candidates:
            without_completion = self._execution_candidates(
                uop, now, check_completion=False, check_vector_read=True
            )
            if without_completion:
                return "completion_domain_busy", self._next_completion_issue_tick(
                    now
                )
            return "execution_unit_busy", self._next_execution_ready_tick(uop, now)
        return None, now

    def _is_vector_memory_uop(self, uop: ExecutionUop) -> bool:
        if uop.kind not in {"load_data", "store_data"}:
            return False
        # Bound traces normally carry semantic ids, but hand-built and older
        # traces may only retain the semantic-kind tuple. Keep the policy
        # generic and avoid silently disabling it for those traces.
        return any(
            self.semantic_kind_by_id.get(semantic) in {"vector_load", "vector_store"}
            for semantic in uop.semantic_ids
        ) or any(
            kind in {"vector_load", "vector_store"}
            for kind in uop.semantic_kinds
        )

    def _vector_memory_blocker(
        self, uop: ExecutionUop, now: int
    ) -> tuple[str | None, int]:
        if not self._is_vector_memory_uop(uop):
            return None, now
        split = self.vector_memory_policy.get("flow_split")
        if split is not None:
            access_kind = self._vector_memory_access_kind(uop)
            split_issue_free = min(
                self.vector_memory_split_issue_free[access_kind]
            )
            if split_issue_free > now:
                return "vector_memory_split_issue_busy", split_issue_free
        access_kind = self._vector_memory_access_kind(uop)
        inflight = self.vector_memory_inflight[access_kind]
        capacity = self.vector_memory_policy.get("service_capacity", {}).get(
            access_kind
        )
        if capacity is not None and len(inflight) >= capacity:
            release_ticks = [
                release_tick
                for release_tick, _, uop_id in self.vector_memory_service_heap
                if uop_id in inflight
            ]
            release_ticks.extend(
                self.uops[uop_id].complete_tick
                if self.uops[uop_id].complete_tick is not None
                else (
                    (
                        self.uops[uop_id].issue_tick
                        if self.uops[uop_id].issue_tick is not None
                        else now
                    )
                    + self.uops[uop_id].latency_ticks
                )
                for uop_id in inflight
                if self._vector_memory_service_ticks(self.uops[uop_id]) is None
            )
            earliest = min(release_ticks)
            if earliest <= now:
                earliest = self._next_architectural_cycle_tick(now)
            return f"vector_memory_{access_kind}_service_busy", earliest
        issue_order = self.vector_memory_policy["issue_order"]
        if issue_order in {"oldest", "oldest_same_kind"}:
            earlier = [
                candidate
                for candidate in self.uops.values()
                if candidate.sequence < uop.sequence
                and candidate.id in self.unissued_dispatched
                and self._is_vector_memory_uop(candidate)
                and (issue_order == "oldest" or candidate.kind == uop.kind)
                and all(
                    self.uops[dependency].complete_tick is not None
                    for dependency in candidate.dependencies
                )
            ]
            if earlier:
                return f"vector_memory_{issue_order}", math.inf
        return None, now

    def _eligible_execution_units(self, uop: ExecutionUop) -> tuple[str, ...]:
        if not uop.execution_unit_choices:
            return ()
        if uop.scheduler_partition is None:
            return uop.execution_unit_choices
        return tuple(
            unit_id
            for unit_id in uop.execution_unit_choices
            if self.execution_units[unit_id]["scheduler_partition"]
            == uop.scheduler_partition
        )

    def _completion_domain_for(
        self, uop: ExecutionUop, execution_unit: str | None
    ) -> str | None:
        if not uop.requires_completion_token or execution_unit is None:
            return None
        return self.execution_units[execution_unit].get("vector_writeback_domain")

    def _vector_read_domain_for(
        self, uop: ExecutionUop, execution_unit: str | None
    ) -> str | None:
        if not uop.requires_vector_read_token or execution_unit is None:
            return None
        return self.execution_units[execution_unit].get("vector_read_domain")

    def _vector_read_token_available(self, domain_id: str, tick: int) -> bool:
        cycle = tick // self.tpc
        return (
            self.vector_read_domain_reservations[domain_id][cycle]
            < self.vector_read_domain_capacity[domain_id]
        )

    def _reserve_vector_read_domain(self, domain_id: str, tick: int) -> None:
        if not self._vector_read_token_available(domain_id, tick):
            raise SimulatorError(
                f"reserved unavailable vector read-domain token: {domain_id}"
            )
        self.vector_read_domain_reservations[domain_id][tick // self.tpc] += 1

    def _completion_token_available(self, domain_id: str, tick: int) -> bool:
        cycle = tick // self.tpc
        return (
            self.completion_domain_reservations[domain_id][cycle]
            < self.completion_domain_capacity[domain_id]
        )

    def _next_architectural_cycle_tick(self, tick: int) -> int:
        return ((tick // self.tpc) + 1) * self.tpc

    def _execution_candidates(
        self,
        uop: ExecutionUop,
        now: int,
        *,
        check_completion: bool,
        check_vector_read: bool = True,
    ) -> list[
        tuple[int, str, int, str | None, str | None, str | None]
    ]:
        result: list[
            tuple[int, str, int, str | None, str | None, str | None]
        ] = []
        units: tuple[str | None, ...] = (
            self._eligible_execution_units(uop)
            if uop.execution_unit_choices
            else (None,)
        )
        for resource_id in uop.resource_choices:
            for lane, free_tick in enumerate(self.resource_free[resource_id]):
                if free_tick > now:
                    continue
                for unit_id in units:
                    if unit_id is not None:
                        unit = self.execution_units[unit_id]
                        if resource_id not in unit["functional_units"]:
                            continue
                        if self.execution_unit_free[unit_id] > now:
                            continue
                    read_domain_id = self._vector_read_domain_for(uop, unit_id)
                    if (
                        check_vector_read
                        and read_domain_id is not None
                        and not self._vector_read_token_available(
                            read_domain_id, now
                        )
                    ):
                        continue
                    completion_domain_id = self._completion_domain_for(uop, unit_id)
                    if (
                        check_completion
                        and completion_domain_id is not None
                        and not self._completion_token_available(
                            completion_domain_id, now + uop.latency_ticks
                        )
                    ):
                        continue
                    result.append(
                        (
                            free_tick,
                            resource_id,
                            lane,
                            unit_id,
                            read_domain_id,
                            completion_domain_id,
                        )
                    )
        return result

    def _next_execution_ready_tick(self, uop: ExecutionUop, now: int) -> int:
        choices: list[int] = []
        units: tuple[str | None, ...] = (
            self._eligible_execution_units(uop)
            if uop.execution_unit_choices
            else (None,)
        )
        for resource_id in uop.resource_choices:
            resource_tick = min(self.resource_free[resource_id])
            for unit_id in units:
                if unit_id is None:
                    choices.append(resource_tick)
                elif resource_id in self.execution_units[unit_id]["functional_units"]:
                    choices.append(
                        max(resource_tick, self.execution_unit_free[unit_id])
                    )
        later = [tick for tick in choices if tick > now]
        return min(later) if later else now + 1

    def _next_completion_issue_tick(self, now: int) -> int:
        return self._next_architectural_cycle_tick(now)

    @staticmethod
    def _issue_domain_demand(uop: ExecutionUop, domain_id: str) -> int:
        return uop.issue_domain_demands.get(domain_id, 1)

    def _issue_domain_ready_tick(
        self, uop: ExecutionUop, domain_id: str
    ) -> int:
        free_ticks = self.issue_domain_free[domain_id]
        demand = self._issue_domain_demand(uop, domain_id)
        if demand > len(free_ticks):
            raise SimulatorError(
                f"uop {uop.id} demand {demand} exceeds issue domain "
                f"{domain_id} capacity {len(free_ticks)}"
            )
        return sorted(free_ticks)[demand - 1]

    def _reserve_issue_domains(self, uop: ExecutionUop, now: int) -> None:
        for domain_id in uop.issue_domains:
            free_ticks = self.issue_domain_free[domain_id]
            demand = self._issue_domain_demand(uop, domain_id)
            lanes = sorted(
                range(len(free_ticks)),
                key=lambda lane: (free_ticks[lane], lane),
            )[:demand]
            if any(free_ticks[lane] > now for lane in lanes):
                raise SimulatorError(
                    f"reserved unavailable issue-domain token for uop {uop.id}"
                )
            for lane in lanes:
                free_ticks[lane] = now + uop.occupancy_ticks

    def _discover_memory_compute_groups(self) -> dict[str, frozenset[str]]:
        groups: dict[str, frozenset[str]] = {}
        for macro in self.trace.macros:
            macro_uops = {uop_id: self.uops[uop_id] for uop_id in macro.uop_ids}
            load_ids = {
                uop_id for uop_id, uop in macro_uops.items() if uop.kind == "load_data"
            }
            if not load_ids:
                continue
            dependent_compute_ids = {
                uop_id
                for uop_id, uop in macro_uops.items()
                if any(
                    self.semantic_kind_by_id.get(semantic)
                    in self.memory_compute_semantic_kinds
                    for semantic in uop.semantic_ids
                )
                and self._depends_transitively_on_any(uop, load_ids, macro_uops)
            }
            if dependent_compute_ids:
                groups[macro.id] = frozenset(dependent_compute_ids)
        return groups

    @staticmethod
    def _depends_transitively_on_any(
        uop: ExecutionUop,
        targets: set[str],
        macro_uops: dict[str, ExecutionUop],
    ) -> bool:
        pending = list(uop.dependencies)
        visited: set[str] = set()
        while pending:
            dependency = pending.pop()
            if dependency in targets:
                return True
            if dependency in visited or dependency not in macro_uops:
                continue
            visited.add(dependency)
            pending.extend(macro_uops[dependency].dependencies)
        return False

    def _memory_compute_overlap_blocked(self, uop: ExecutionUop) -> bool:
        return (
            self.memory_compute_overlap_limit_enabled
            and uop.kind == "load_data"
            and uop.parent_id in self.memory_compute_groups
            and uop.parent_id not in self.pending_memory_compute_groups
            and len(self.pending_memory_compute_groups)
            >= self.max_pending_memory_compute_groups
        )

    def _update_memory_compute_groups_after_issue(self, uop: ExecutionUop) -> None:
        if not self.memory_compute_overlap_limit_enabled:
            return
        compute_ids = self.memory_compute_groups.get(uop.parent_id)
        if compute_ids is None:
            return
        if uop.kind == "load_data":
            self.pending_memory_compute_groups.add(uop.parent_id)
        if uop.id in compute_ids and all(
            self.uops[uop_id].issue_tick is not None for uop_id in compute_ids
        ):
            self.pending_memory_compute_groups.discard(uop.parent_id)

    def _select_execution(
        self, uop: ExecutionUop, now: int
    ) -> tuple[str, int, str | None, str | None, str | None]:
        choices = self._execution_candidates(uop, now, check_completion=True)
        if not choices:
            raise SimulatorError(f"selected unavailable execution path for {uop.id}")
        (
            _,
            resource_id,
            lane,
            execution_unit,
            vector_read_domain,
            completion_domain,
        ) = min(choices)
        return (
            resource_id,
            lane,
            execution_unit,
            vector_read_domain,
            completion_domain,
        )

    def _reserve_completion_domain(self, domain_id: str, tick: int) -> int:
        while not self._completion_token_available(domain_id, tick):
            tick = self._next_architectural_cycle_tick(tick)
        self.completion_domain_reservations[domain_id][tick // self.tpc] += 1
        return tick

    def _retire(self, now: int) -> None:
        width = int(self.profile.pipeline["retire_macro_ops_per_cycle"])
        retired = 0
        while self.rob and retired < width:
            macro = self.macros[self.rob[0]]
            if macro.complete_tick is None or macro.complete_tick > now:
                break
            if retired + macro.retire_macro_ops > width:
                break
            self.rob.popleft()
            macro.retire_tick = now
            self.rob_occupancy -= macro.rob_entry_count
            self.load_queue_occupancy -= int(macro.uses_load_queue)
            self.store_queue_occupancy -= int(macro.uses_store_queue)
            retired += macro.retire_macro_ops
            if self.rename_enabled and macro.rename_allocations:
                ready_tick = (
                    now
                    + self.rename_release_delay_ticks
                    + self.rename_availability_delay_ticks
                )
                heapq.heappush(
                    self.rename_pending_releases,
                    (ready_tick, macro.sequence, dict(macro.rename_allocations)),
                )
            self.events.append(
                {
                    "type": "retire",
                    "tick": now,
                    "instruction_id": macro.id,
                    "sequence": macro.sequence,
                    "mnemonic": macro.mnemonic,
                    "assembly": macro.assembly,
                }
            )

    def _next_event_tick(self, now: int) -> int:
        candidates: list[int] = []
        if self.completion_heap:
            candidates.append(self.completion_heap[0][0])
        if self.vector_memory_service_heap:
            candidates.append(self.vector_memory_service_heap[0][0])
        if self.rename_pending_releases:
            ready_tick = self.rename_pending_releases[0][0]
            if ready_tick > now:
                candidates.append(ready_tick)
            else:
                # Release width may leave a ready batch pending; retry on the
                # next architectural cycle rather than spinning at one tick.
                candidates.append(self._next_architectural_cycle_tick(now))
        next_cycle = ((now // self.tpc) + 1) * self.tpc
        if self.next_dispatch < len(self.trace.macros) or self.rob:
            candidates.append(next_cycle)
        for uop in self._issue_candidates():
            _, earliest = self._issue_blocker(uop, now)
            if earliest != math.inf and earliest > now:
                candidates.append(int(earliest))
            for resource_id in uop.resource_choices:
                resource_tick = min(self.resource_free[resource_id])
                if resource_tick > now:
                    candidates.append(resource_tick)
            last_issue = self.last_class_issue.get(uop.scheduling_class)
            if last_issue is not None:
                interval_tick = last_issue + uop.issue_interval_ticks
                if interval_tick > now:
                    candidates.append(interval_tick)
            for domain_id in uop.issue_domains:
                domain_tick = self._issue_domain_ready_tick(uop, domain_id)
                if domain_tick > now:
                    candidates.append(domain_tick)
        if not candidates:
            blocked = [
                uop.id
                for uop in self.trace.uops
                if uop.id in self.unissued_dispatched
            ]
            raise SimulatorError(f"deadlock; blocked uops: {blocked[:8]}")
        return min(candidates)

    def _record_peaks(self) -> None:
        self.peaks["rob"] = max(self.peaks["rob"], self.rob_occupancy)
        self.peaks["vector_scheduler"] = max(
            self.peaks["vector_scheduler"],
            self.vector_scheduler_occupancy
            + sum(
                occupancy
                for partition_id, occupancy in self.scheduler_partition_occupancy.items()
                if self.scheduler_partitions[partition_id]["kind"] == "vector_compute"
            ),
        )
        self.peaks["load_queue"] = max(
            self.peaks["load_queue"], self.load_queue_occupancy
        )
        self.peaks["store_queue"] = max(
            self.peaks["store_queue"], self.store_queue_occupancy
        )
        self.peaks["memory_compute_pending_groups"] = max(
            self.peaks["memory_compute_pending_groups"],
            len(self.pending_memory_compute_groups),
        )
        for access_kind, inflight in self.vector_memory_inflight.items():
            key = f"vector_memory_inflight_{access_kind}"
            self.peaks[key] = max(self.peaks[key], len(inflight))

    @staticmethod
    def _event(kind: str, tick: int, uop: ExecutionUop) -> dict[str, Any]:
        return {
            "type": kind,
            "tick": tick,
            "uop_id": uop.id,
            "instruction_id": uop.parent_id,
            "sequence": uop.sequence,
            "kind": uop.kind,
            "resource": uop.resource,
            "scheduler_partition": uop.scheduler_partition,
            "execution_unit": uop.execution_unit,
            "vector_read_domain": uop.vector_read_domain,
            "completion_domain": uop.completion_domain,
            "part_index": uop.part_index,
            "part_count": uop.part_count,
            "memory_level": uop.memory_level,
            "mnemonic": uop.mnemonic,
            "assembly": uop.assembly,
        }


def simulate(
    trace: BoundTrace,
    profile: Profile,
    execution_model: ExecutionModel = "out_of_order",
    cache_mode: CacheMode = "hot-l1",
    memory_compute_overlap_limit: bool | None = None,
) -> SimulationResult:
    return Engine(
        trace,
        profile,
        execution_model,
        cache_mode,
        memory_compute_overlap_limit,
    ).run()
