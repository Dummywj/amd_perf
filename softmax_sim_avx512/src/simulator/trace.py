from __future__ import annotations

from collections import Counter, deque

from .model import BoundTrace


class TraceValidationError(ValueError):
    pass


def validate_bound_trace(trace: BoundTrace) -> None:
    macro_ids = [macro.id for macro in trace.macros]
    uop_ids = [uop.id for uop in trace.uops]
    if any(count != 1 for count in Counter(macro_ids).values()):
        raise TraceValidationError("duplicate macro-op ID")
    if any(count != 1 for count in Counter(uop_ids).values()):
        raise TraceValidationError("duplicate execution-uop ID")

    macros = {macro.id: macro for macro in trace.macros}
    uops = {uop.id: uop for uop in trace.uops}
    referenced: set[str] = set()
    for macro in trace.macros:
        if not macro.uop_ids:
            raise TraceValidationError(f"macro-op has no execution uops: {macro.id}")
        for uop_id in macro.uop_ids:
            if uop_id not in uops:
                raise TraceValidationError(
                    f"macro-op {macro.id} references unknown uop: {uop_id}"
                )
            if uops[uop_id].parent_id != macro.id:
                raise TraceValidationError(f"uop parent mismatch: {uop_id}")
            referenced.add(uop_id)
    if referenced != set(uops):
        raise TraceValidationError("one or more execution uops have no macro-op parent")

    indegree = {uop_id: 0 for uop_id in uops}
    consumers: dict[str, list[str]] = {uop_id: [] for uop_id in uops}
    for uop in trace.uops:
        if uop.parent_id not in macros:
            raise TraceValidationError(f"unknown parent macro-op: {uop.parent_id}")
        unlisted_demands = set(uop.issue_domain_demands) - set(uop.issue_domains)
        if unlisted_demands:
            raise TraceValidationError(
                f"uop {uop.id} has demands for unlisted issue domains: "
                + ", ".join(sorted(unlisted_demands))
            )
        for domain_id, demand in uop.issue_domain_demands.items():
            if isinstance(demand, bool) or not isinstance(demand, int) or demand < 1:
                raise TraceValidationError(
                    f"uop {uop.id} has invalid demand for issue domain "
                    f"{domain_id}: {demand!r}"
                )
        for resource_id in uop.resource_choices:
            if resource_id not in trace.resources:
                raise TraceValidationError(
                    f"uop {uop.id} references unknown resource: {resource_id}"
                )
        for dependency in uop.dependencies:
            if dependency not in uops:
                raise TraceValidationError(
                    f"uop {uop.id} references unknown dependency: {dependency}"
                )
            indegree[uop.id] += 1
            consumers[dependency].append(uop.id)
        if uop.issue_after_uop and uop.issue_after_uop not in uops:
            raise TraceValidationError(
                f"uop {uop.id} references unknown issue predecessor: "
                f"{uop.issue_after_uop}"
            )

    ready = deque(sorted(value for value, degree in indegree.items() if degree == 0))
    visited = 0
    while ready:
        producer = ready.popleft()
        visited += 1
        for consumer in consumers[producer]:
            indegree[consumer] -= 1
            if indegree[consumer] == 0:
                ready.append(consumer)
    if visited != len(uops):
        raise TraceValidationError("execution-uop dependency graph contains a cycle")
