from __future__ import annotations

import json
from collections import defaultdict
from pathlib import Path
from typing import Any

from .engine import SimulationResult
from .semantic_view import build_semantic_view_model


def write_result(path: Path, result: SimulationResult) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(result.to_dict(), indent=2) + "\n", encoding="utf-8")


def write_events_jsonl(path: Path, result: SimulationResult) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    metadata = {
        "type": "metadata",
        "profile_id": result.trace.profile_id,
        "profile_sha256": result.trace.profile_sha256,
        "backend": result.backend,
        "execution_model": result.execution_model,
        "cache_mode": result.cache_mode,
        "ticks_per_cycle": result.ticks_per_cycle,
        "cycles": result.cycles,
        "workload": result.trace.workload,
        "dispatch_domain_stats": result.summary.get("dispatch_domain_stats", {}),
    }
    with path.open("w", encoding="utf-8") as stream:
        stream.write(json.dumps(metadata, sort_keys=True) + "\n")
        for event in sorted(result.events, key=lambda value: (value["tick"], value["type"])):
            stream.write(json.dumps(event, sort_keys=True) + "\n")


def write_perfetto(
    path: Path,
    result: SimulationResult,
    instruction_start: int = 0,
    instruction_limit: int = 200,
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    end = instruction_start + instruction_limit
    macros = [
        macro
        for macro in result.trace.macros
        if instruction_start <= macro.sequence < end
    ]
    macro_ids = {macro.id for macro in macros}
    uops = [uop for uop in result.trace.uops if uop.parent_id in macro_ids]
    events: list[dict[str, Any]] = []
    pid_instructions = 1
    pid_resources = 2
    pid_counters = 3

    events.append(_process_name(pid_instructions, "instructions"))
    events.append(_process_name(pid_resources, "execution resources"))
    events.append(_process_name(pid_counters, "queue occupancy"))

    for macro in macros:
        tid = macro.sequence + 1
        events.append(_thread_name(pid_instructions, tid, f"{macro.id} {macro.assembly}"))
        dispatch = macro.dispatch_tick or 0
        issue_ticks = [
            uop.issue_tick for uop in uops if uop.parent_id == macro.id and uop.issue_tick is not None
        ]
        complete = macro.complete_tick if macro.complete_tick is not None else dispatch
        retire = macro.retire_tick if macro.retire_tick is not None else complete
        first_issue = min(issue_ticks) if issue_ticks else dispatch
        _slice(events, pid_instructions, tid, "waiting", dispatch, first_issue, macro)
        _slice(events, pid_instructions, tid, "executing", first_issue, complete, macro)
        _slice(events, pid_instructions, tid, "retire wait", complete, retire, macro)

    resource_tids: dict[tuple[str, int], int] = {}
    for uop in uops:
        if uop.issue_tick is None or uop.complete_tick is None or uop.resource is None:
            continue
        lane = uop.resource_lane or 0
        resource_key = (uop.resource, lane)
        if resource_key not in resource_tids:
            tid = len(resource_tids) + 1
            resource_tids[resource_key] = tid
            events.append(
                _thread_name(pid_resources, tid, f"{uop.resource}[{lane}]")
            )
        duration = max(uop.occupancy_ticks, 1)
        events.append(
            {
                "ph": "X",
                "pid": pid_resources,
                "tid": resource_tids[resource_key],
                "ts": uop.issue_tick,
                "dur": duration,
                "cat": "uop",
                "name": f"{uop.id} {uop.kind}",
                "args": _uop_args(uop, result.ticks_per_cycle),
            }
        )

    edge_id = 1
    selected_uop_ids = {uop.id for uop in uops}
    for consumer in uops:
        if consumer.issue_tick is None:
            continue
        for producer_id in sorted(consumer.dependencies):
            if producer_id not in selected_uop_ids:
                continue
            producer = next(uop for uop in uops if uop.id == producer_id)
            if producer.complete_tick is None or producer.resource is None:
                continue
            producer_tid = resource_tids[(producer.resource, producer.resource_lane or 0)]
            consumer_tid = resource_tids[(consumer.resource, consumer.resource_lane or 0)]
            events.extend(
                [
                    {
                        "ph": "s",
                        "pid": pid_resources,
                        "tid": producer_tid,
                        "ts": producer.complete_tick,
                        "cat": "dependency",
                        "name": "RAW dependency",
                        "id": edge_id,
                    },
                    {
                        "ph": "f",
                        "bp": "e",
                        "pid": pid_resources,
                        "tid": consumer_tid,
                        "ts": consumer.issue_tick,
                        "cat": "dependency",
                        "name": "RAW dependency",
                        "id": edge_id,
                    },
                ]
            )
            edge_id += 1

    occupancy = _occupancy_samples(result)
    counter_names = ("rob", "vector_scheduler", "load_queue", "store_queue")
    for counter_index, name in enumerate(counter_names, start=1):
        events.append(_thread_name(pid_counters, counter_index, name))
        for tick, values in occupancy:
            events.append(
                {
                    "ph": "C",
                    "pid": pid_counters,
                    "tid": counter_index,
                    "ts": tick,
                    "name": name,
                    "args": {"entries": values[name]},
                }
            )

    document = {
        "displayTimeUnit": "ns",
        "otherData": {
            "time_unit": "simulator_tick",
            "ticks_per_cycle": result.ticks_per_cycle,
            "backend": result.backend,
            "execution_model": result.execution_model,
            "cache_mode": result.cache_mode,
            "profile_id": result.trace.profile_id,
            "profile_sha256": result.trace.profile_sha256,
        },
        "traceEvents": events,
    }
    path.write_text(json.dumps(document, separators=(",", ":")) + "\n", encoding="utf-8")


def write_dot(
    path: Path,
    result: SimulationResult,
    instruction_start: int = 0,
    instruction_limit: int = 200,
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    end = instruction_start + instruction_limit
    uops = [
        uop
        for uop in result.trace.uops
        if instruction_start <= uop.parent_sequence < end
    ]
    selected = {uop.id for uop in uops}
    lines = [
        "digraph schedule {",
        '  graph [rankdir="LR"];',
        '  node [shape="box", fontname="monospace", fontsize="9"];',
    ]
    for uop in uops:
        label = (
            f"{uop.id}\\n{uop.kind}\\n"
            f"issue={_cycle(uop.issue_tick, result.ticks_per_cycle)} "
            f"done={_cycle(uop.complete_tick, result.ticks_per_cycle)}"
        )
        lines.append(f'  "{uop.id}" [label="{label}"];')
    for uop in uops:
        for dependency in sorted(uop.dependencies):
            if dependency in selected:
                lines.append(f'  "{dependency}" -> "{uop.id}";')
    lines.append("}")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def write_timeline(
    path: Path,
    result: SimulationResult,
    instruction_start: int = 0,
    instruction_limit: int = 80,
    max_cycles: int = 200,
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    end = instruction_start + instruction_limit
    lines = [
        f"backend={result.backend} execution_model={result.execution_model} "
        f"cycles={result.cycles:g} "
        f"ticks_per_cycle={result.ticks_per_cycle}",
        "D=dispatch  I=first issue  E=complete  R=retire",
    ]
    for macro in result.trace.macros:
        if not instruction_start <= macro.sequence < end:
            continue
        first_issue = min(
            self_issue
            for uop_id in macro.uop_ids
            if (self_issue := next(u for u in result.trace.uops if u.id == uop_id).issue_tick)
            is not None
        )
        marks = [" "] * (max_cycles + 1)
        for symbol, tick in (
            ("D", macro.dispatch_tick),
            ("I", first_issue),
            ("E", macro.complete_tick),
            ("R", macro.retire_tick),
        ):
            if tick is not None:
                cycle = tick // result.ticks_per_cycle
                if cycle <= max_cycles:
                    marks[cycle] = symbol if marks[cycle] == " " else "*"
        lines.append(
            f"{macro.sequence:5d} {''.join(marks).rstrip():<{max_cycles + 1}} {macro.assembly}"
        )
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def write_semantic_html(path: Path, result: SimulationResult) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    full_view_model = build_semantic_view_model(result)
    view_model = {
        "view_model_version": full_view_model["view_model_version"],
        "metadata": {
            **full_view_model["metadata"],
            "semantic_uop_count": len(full_view_model["semantic_uops"]),
        },
        "semantic_uops": full_view_model["semantic_uops"],
        "dependencies": full_view_model["dependencies"]["semantic"],
    }
    template_path = Path(__file__).resolve().parents[1] / "viewer/semantic_schedule.html"
    template = template_path.read_text(encoding="utf-8")
    marker = "__SEMANTIC_TRACE_DATA__"
    if template.count(marker) != 1:
        raise ValueError(f"semantic viewer template must contain one {marker} marker")
    encoded = json.dumps(view_model, ensure_ascii=False, separators=(",", ":"))
    encoded = (
        encoded.replace("&", "\\u0026")
        .replace("<", "\\u003c")
        .replace(">", "\\u003e")
    )
    path.write_text(template.replace(marker, encoded), encoding="utf-8")


def _occupancy_samples(result: SimulationResult) -> list[tuple[int, dict[str, int]]]:
    deltas: dict[int, dict[str, int]] = defaultdict(lambda: defaultdict(int))
    for macro in result.trace.macros:
        if macro.dispatch_tick is None or macro.retire_tick is None:
            continue
        deltas[macro.dispatch_tick]["rob"] += macro.rob_entry_count
        deltas[macro.retire_tick]["rob"] -= macro.rob_entry_count
        if macro.uses_load_queue:
            deltas[macro.dispatch_tick]["load_queue"] += 1
            deltas[macro.retire_tick]["load_queue"] -= 1
        if macro.uses_store_queue:
            deltas[macro.dispatch_tick]["store_queue"] += 1
            deltas[macro.retire_tick]["store_queue"] -= 1
    by_id = {uop.id: uop for uop in result.trace.uops}
    for macro in result.trace.macros:
        if not macro.uses_vector_scheduler or macro.dispatch_tick is None:
            continue
        vector_issue_ticks = [
            by_id[uop_id].issue_tick
            for uop_id in macro.uop_ids
            if by_id[uop_id].kind
            in {"vector_fp", "vector_integer", "conversion", "shuffle"}
            and by_id[uop_id].issue_tick is not None
        ]
        deltas[macro.dispatch_tick]["vector_scheduler"] += 1
        if vector_issue_ticks:
            deltas[min(vector_issue_ticks)]["vector_scheduler"] -= 1
    current = {"rob": 0, "vector_scheduler": 0, "load_queue": 0, "store_queue": 0}
    samples = []
    for tick in sorted(deltas):
        for name, value in deltas[tick].items():
            current[name] += value
        samples.append((tick, dict(current)))
    return samples


def _slice(
    events: list[dict[str, Any]],
    pid: int,
    tid: int,
    name: str,
    start: int,
    end: int,
    macro: Any,
) -> None:
    if end <= start:
        return
    events.append(
        {
            "ph": "X",
            "pid": pid,
            "tid": tid,
            "ts": start,
            "dur": end - start,
            "cat": "instruction",
            "name": name,
            "args": {
                "instruction_id": macro.id,
                "sequence": macro.sequence,
                "mnemonic": macro.mnemonic,
                "assembly": macro.assembly,
            },
        }
    )


def _process_name(pid: int, name: str) -> dict[str, Any]:
    return {"ph": "M", "pid": pid, "tid": 0, "name": "process_name", "args": {"name": name}}


def _thread_name(pid: int, tid: int, name: str) -> dict[str, Any]:
    return {"ph": "M", "pid": pid, "tid": tid, "name": "thread_name", "args": {"name": name}}


def _uop_args(uop: Any, ticks_per_cycle: int) -> dict[str, Any]:
    return {
        "uop_id": uop.id,
        "instruction_id": uop.parent_id,
        "kind": uop.kind,
        "mnemonic": uop.mnemonic,
        "assembly": uop.assembly,
        "memory_level": uop.memory_level,
        "vector_read_domain": uop.vector_read_domain,
        "stall_reason": uop.stall_reason,
        "stall_reasons": dict(sorted(uop.stall_reasons.items())),
        "issue_cycle": _cycle(uop.issue_tick, ticks_per_cycle),
        "complete_cycle": _cycle(uop.complete_tick, ticks_per_cycle),
    }


def _cycle(tick: int | None, ticks_per_cycle: int) -> float | None:
    return None if tick is None else tick / ticks_per_cycle
