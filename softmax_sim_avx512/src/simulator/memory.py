from __future__ import annotations

import math
from collections import OrderedDict
from dataclasses import dataclass
from fractions import Fraction
from typing import Any, Literal

from .model import BoundTrace, ExecutionUop
from .profile import Profile


CacheMode = Literal["hot-l1", "hot-capacity", "cold"]


class MemoryModelError(ValueError):
    pass


@dataclass(frozen=True)
class MemoryAccess:
    level: str
    latency_ticks: int
    bandwidth_ticks: int
    completion_tick: int


class SetAssociativeCache:
    def __init__(self, size_bytes: int, ways: int, line_bytes: int):
        if size_bytes % (ways * line_bytes):
            raise MemoryModelError("cache size must be divisible by ways * line size")
        self.ways = ways
        self.set_count = size_bytes // (ways * line_bytes)
        self.sets = [OrderedDict() for _ in range(self.set_count)]

    def contains(self, line: int) -> bool:
        cache_set = self.sets[line % self.set_count]
        return line in cache_set

    def remove(self, line: int) -> None:
        self.sets[line % self.set_count].pop(line, None)

    def touch(self, line: int) -> int | None:
        cache_set = self.sets[line % self.set_count]
        if line in cache_set:
            cache_set.move_to_end(line)
            return None
        cache_set[line] = None
        if len(cache_set) > self.ways:
            evicted, _ = cache_set.popitem(last=False)
            return evicted
        return None

    def can_hold(self, lines: set[int]) -> bool:
        occupancy: dict[int, int] = {}
        for line in lines:
            index = line % self.set_count
            occupancy[index] = occupancy.get(index, 0) + 1
            if occupancy[index] > self.ways:
                return False
        return True


class MemoryHierarchy:
    """Deterministic inclusive LRU effective model with explicit initial state."""

    def __init__(self, profile: Profile, trace: BoundTrace, mode: CacheMode):
        if mode not in {"hot-l1", "hot-capacity", "cold"}:
            raise MemoryModelError(f"unknown cache mode: {mode}")
        self.profile = profile
        self.trace = trace
        self.mode = mode
        self.line_bytes = int(profile.data["memory"]["cache_line_bytes"])
        self.level_order = list(profile.data["memory"]["levels"])
        self.caches = {
            level: SetAssociativeCache(
                int(entry["size_bytes"]), int(entry["ways"]), self.line_bytes
            )
            for level, entry in profile.data["memory"]["levels"].items()
        }
        self.bandwidth_free = {
            (level, access): 0
            for level in self.level_order + ["dram"]
            for access in ("load", "store")
        }
        self.outstanding: dict[str, list[int]] = {
            level: [] for level in self.level_order + ["dram"]
        }
        self.pending_fills: dict[int, tuple[int, str]] = {}
        self.hits = {level: 0 for level in self.level_order + ["dram"]}
        self._initialize()

    def _initialize(self) -> None:
        lines = {
            line
            for instruction in self.trace.source_trace["instructions"]
            if instruction.get("memory")
            for line in instruction["memory"]["cache_lines"]
        }
        if self.mode == "cold":
            return
        if self.mode == "hot-l1":
            level = self.level_order[0]
            if not self.caches[level].can_hold(lines):
                raise MemoryModelError(
                    f"working set ({len(lines) * self.line_bytes} bytes) cannot be "
                    f"represented as {level} resident"
                )
        else:
            level = next(
                (
                    candidate
                    for candidate in self.level_order
                    if self.caches[candidate].can_hold(lines)
                ),
                None,
            )
            if level is None:
                raise MemoryModelError("working set exceeds modeled cache capacity")
        target_index = self.level_order.index(level)
        for line in sorted(lines):
            for candidate in self.level_order[target_index:]:
                self.caches[candidate].touch(line)
            if self.mode == "hot-l1":
                for candidate in self.level_order[:target_index]:
                    self.caches[candidate].touch(line)

    def peek_level(self, uop: ExecutionUop, now: int) -> str:
        self._complete_fills(now)
        memory = uop.memory
        if not memory:
            raise MemoryModelError("memory access requested for a non-memory uop")
        worst = -1
        for line in memory["cache_lines"]:
            pending = self.pending_fills.get(line)
            if pending is not None:
                pending_level = pending[1]
                index = (
                    len(self.level_order)
                    if pending_level == "dram"
                    else self.level_order.index(pending_level)
                )
            else:
                index = next(
                    (
                        offset
                        for offset, level in enumerate(self.level_order)
                        if self.caches[level].contains(line)
                    ),
                    len(self.level_order),
                )
            worst = max(worst, index)
        return "dram" if worst == len(self.level_order) else self.level_order[worst]

    def blocker(self, uop: ExecutionUop, now: int) -> tuple[str | None, int]:
        level = self.peek_level(uop, now)
        memory = uop.memory or {}
        if any(line in self.pending_fills for line in memory["cache_lines"]):
            return None, now
        access = (uop.memory or {})["access"]
        if self.bandwidth_free[(level, access)] > now:
            return "memory_bandwidth", self.bandwidth_free[(level, access)]
        for missed_level in self._miss_path(level):
            pending = [
                tick for tick in self.outstanding[missed_level] if tick > now
            ]
            self.outstanding[missed_level] = pending
            if len(pending) >= self._outstanding_limit(missed_level):
                return "memory_outstanding", min(pending)
        return None, now

    def access(self, uop: ExecutionUop, now: int) -> MemoryAccess:
        reason, _ = self.blocker(uop, now)
        if reason:
            raise MemoryModelError(f"access issued while blocked: {reason}")
        level = self.peek_level(uop, now)
        memory = uop.memory or {}
        pending = [
            self.pending_fills[line]
            for line in memory["cache_lines"]
            if line in self.pending_fills
        ]
        if pending:
            completion = max(value[0] for value in pending)
            self.hits[level] += len(memory["cache_lines"])
            return MemoryAccess(level, completion - now, 0, completion)
        entry = self._level_entry(level)
        latency_ticks = self.profile.ticks(entry["latency_cycles"])
        bytes_per_cycle = entry[
            "write_bytes_per_cycle" if memory.get("access") == "store" else "read_bytes_per_cycle"
        ]
        bandwidth_ticks = math.ceil(
            Fraction(int(memory["bytes"]), int(bytes_per_cycle))
            * self.profile.ticks_per_cycle
        )
        self.bandwidth_free[(level, memory["access"])] = now + bandwidth_ticks
        completion = now + latency_ticks
        for missed_level in self._miss_path(level):
            self.outstanding[missed_level].append(completion)
        self.hits[level] += len(memory["cache_lines"])
        for line in memory["cache_lines"]:
            if level == self.level_order[0]:
                self.caches[level].touch(line)
            else:
                self.pending_fills[line] = (completion, level)
        return MemoryAccess(level, latency_ticks, bandwidth_ticks, completion)

    def _complete_fills(self, now: int) -> None:
        completed = [
            (line, source_level)
            for line, (completion, source_level) in self.pending_fills.items()
            if completion <= now
        ]
        for line, source_level in sorted(completed):
            self._fill_inclusive(line, source_level)
            del self.pending_fills[line]

    def _fill_inclusive(self, line: int, source_level: str) -> None:
        source_index = (
            len(self.level_order)
            if source_level == "dram"
            else self.level_order.index(source_level)
        )
        for level_index, level in enumerate(self.level_order[: source_index + 1]):
            evicted = self.caches[level].touch(line)
            if evicted is not None:
                for upper_level in self.level_order[:level_index]:
                    self.caches[upper_level].remove(evicted)
        for level in self.level_order[source_index + 1 :]:
            evicted = self.caches[level].touch(line)
            if evicted is not None:
                level_index = self.level_order.index(level)
                for upper_level in self.level_order[:level_index]:
                    self.caches[upper_level].remove(evicted)

    def _level_entry(self, level: str) -> dict[str, Any]:
        if level == "dram":
            return self.profile.data["memory"]["dram"]
        return self.profile.data["memory"]["levels"][level]

    def _outstanding_limit(self, level: str) -> int:
        entry = self._level_entry(level)
        key = "max_outstanding_requests" if level == "dram" else "max_outstanding_misses"
        return int(entry[key])

    def _miss_path(self, hit_level: str) -> list[str]:
        if hit_level == "dram":
            return [*self.level_order, "dram"]
        return self.level_order[: self.level_order.index(hit_level)]
