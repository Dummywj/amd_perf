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
                    "resource": uop.resource,
                    "resource_lane": uop.resource_lane,
                    "memory_level": uop.memory_level,
                    "dependencies": sorted(uop.dependencies),
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
        self.memory_compute_groups = self._discover_memory_compute_groups()
        self.pending_memory_compute_groups: set[str] = set()
        self.next_dispatch = 0
        self.in_order_issue_index = 0
        self.rob_occupancy = 0
        self.vector_scheduler_occupancy = 0
        self.load_queue_occupancy = 0
        self.store_queue_occupancy = 0
        self.peaks = Counter()
        self.stalls = Counter()
        self.events: list[dict[str, Any]] = []

    def run(self) -> SimulationResult:
        now = 0
        iteration_guard = 0
        while self.next_dispatch < len(self.trace.macros) or self.rob:
            iteration_guard += 1
            if iteration_guard > max(10000, len(self.trace.uops) * 100):
                raise SimulatorError("event loop did not converge")
            self._complete(now)
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
            "retired_macro_ops": sum(macro.retire_macro_ops for macro in self.trace.macros),
            "peak_rob": self.peaks["rob"],
            "peak_vector_scheduler": self.peaks["vector_scheduler"],
            "peak_load_queue": self.peaks["load_queue"],
            "peak_store_queue": self.peaks["store_queue"],
            "dependency_critical_path_cycles": self._dependency_critical_path_cycles(),
            "dispatch_stalls": dict(sorted(self.stalls.items())),
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
            self.events.append(self._event("complete", complete_tick, uop))
            parent = self.macros[uop.parent_id]
            if all(self.uops[value].complete_tick is not None for value in parent.uop_ids):
                parent.complete_tick = max(
                    self.uops[value].complete_tick or 0 for value in parent.uop_ids
                )
            changed = True
        return changed

    def _dispatch(self, now: int) -> None:
        width = int(self.profile.pipeline["dispatch_macro_ops_per_cycle"])
        dispatched = 0
        while self.next_dispatch < len(self.trace.macros) and dispatched < width:
            macro = self.trace.macros[self.next_dispatch]
            if dispatched + macro.decoded_macro_ops > width:
                break
            reason = self._dispatch_blocker(macro)
            if reason:
                self.stalls[reason] += 1
                break
            macro.dispatch_tick = now
            self.rob.append(macro.id)
            self.rob_occupancy += macro.decoded_macro_ops
            self.vector_scheduler_occupancy += int(macro.uses_vector_scheduler)
            self.load_queue_occupancy += int(macro.uses_load_queue)
            self.store_queue_occupancy += int(macro.uses_store_queue)
            for uop_id in macro.uop_ids:
                uop = self.uops[uop_id]
                uop.dispatch_tick = now
                self.unissued_dispatched.add(uop_id)
                self.events.append(self._event("dispatch", now, uop))
            self.next_dispatch += 1
            dispatched += macro.decoded_macro_ops

    def _dispatch_blocker(self, macro: MacroOp) -> str | None:
        pipeline = self.profile.pipeline
        if self.rob_occupancy + macro.decoded_macro_ops > int(pipeline["rob_entries"]):
            return "rob_full"
        if (
            self.vector_scheduler_occupancy + int(macro.uses_vector_scheduler)
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
        return None

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
            resource_id, lane = self._select_resource(uop, now)
            uop.ready_tick = self._dependency_ready_tick(uop)
            uop.issue_tick = now
            self.unissued_dispatched.remove(uop.id)
            uop.resource = resource_id
            uop.resource_lane = lane
            if uop.kind in {"load_data", "store_data"}:
                access = self.memory.access(uop, now)
                uop.memory_level = access.level
                if uop.kind == "load_data":
                    uop.latency_ticks = access.latency_ticks
            self.resource_free[resource_id][lane] = now + uop.occupancy_ticks
            self.last_class_issue[uop.scheduling_class] = now
            self._reserve_issue_domains(uop, now)
            self._update_memory_compute_groups_after_issue(uop)
            if uop.kind in VECTOR_RESOURCE_KINDS:
                parent = self.macros[uop.parent_id]
                if not any(
                    self.uops[value].issue_tick is not None
                    for value in parent.uop_ids
                    if value != uop.id and self.uops[value].kind in VECTOR_RESOURCE_KINDS
                ):
                    self.vector_scheduler_occupancy -= 1
            completion_tick = now + uop.latency_ticks
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
            known = [
                value.issue_tick + value.latency_ticks
                for value in incomplete
                if value.issue_tick is not None
            ]
            return "dependency", min(known) if known else math.inf
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
        if uop.kind in {"load_data", "store_data"}:
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
        return None, now

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

    def _select_resource(self, uop: ExecutionUop, now: int) -> tuple[str, int]:
        choices: list[tuple[int, str, int]] = []
        for resource_id in uop.resource_choices:
            lane = min(
                range(len(self.resource_free[resource_id])),
                key=self.resource_free[resource_id].__getitem__,
            )
            choices.append((self.resource_free[resource_id][lane], resource_id, lane))
        free_tick, resource_id, lane = min(choices)
        if free_tick > now:
            raise SimulatorError("selected unavailable resource")
        return resource_id, lane

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
            self.rob_occupancy -= macro.decoded_macro_ops
            self.load_queue_occupancy -= int(macro.uses_load_queue)
            self.store_queue_occupancy -= int(macro.uses_store_queue)
            retired += macro.retire_macro_ops
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
            self.peaks["vector_scheduler"], self.vector_scheduler_occupancy
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
