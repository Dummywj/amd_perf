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
        for name, count in (
            ("decoded_macro_ops", macro.decoded_macro_ops),
            ("dispatch_units", macro.dispatch_width_units),
            ("rob_entries", macro.rob_entry_count),
            ("retire_macro_ops", macro.retire_macro_ops),
        ):
            if isinstance(count, bool) or not isinstance(count, int) or count < 1:
                raise TraceValidationError(
                    f"macro-op {macro.id} has invalid {name}: {count!r}"
                )
        if len(set(macro.dispatch_domains)) != len(macro.dispatch_domains):
            raise TraceValidationError(
                f"macro-op {macro.id} has duplicate dispatch domains"
            )
        unlisted_dispatch_demands = set(macro.dispatch_domain_demands) - set(
            macro.dispatch_domains
        )
        if unlisted_dispatch_demands:
            raise TraceValidationError(
                f"macro-op {macro.id} has demands for unlisted dispatch domains: "
                + ", ".join(sorted(unlisted_dispatch_demands))
            )
        for domain_id, demand in macro.dispatch_domain_demands.items():
            if isinstance(demand, bool) or not isinstance(demand, int) or demand < 1:
                raise TraceValidationError(
                    f"macro-op {macro.id} has invalid demand for dispatch domain "
                    f"{domain_id}: {demand!r}"
                )
        for name, demand in macro.rename_allocations.items():
            if isinstance(demand, bool) or not isinstance(demand, int) or demand < 1:
                raise TraceValidationError(
                    f"macro-op {macro.id} has invalid rename allocation for "
                    f"{name}: {demand!r}"
                )
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
        if not isinstance(uop.requires_vector_read_token, bool):
            raise TraceValidationError(
                f"uop {uop.id} has invalid vector read-token requirement: "
                f"{uop.requires_vector_read_token!r}"
            )
        if not isinstance(uop.requires_vector_state, bool):
            raise TraceValidationError(
                f"uop {uop.id} has invalid vector-state requirement: "
                f"{uop.requires_vector_state!r}"
            )
        if not isinstance(uop.reads_old_destination, bool):
            raise TraceValidationError(
                f"uop {uop.id} has invalid old-destination metadata: "
                f"{uop.reads_old_destination!r}"
            )
        if not uop.vector_state_dependencies.issubset(uop.dependencies):
            raise TraceValidationError(
                f"uop {uop.id} has vector-state dependencies outside its dependency set"
            )
        if not uop.old_destination_dependencies.issubset(uop.dependencies):
            raise TraceValidationError(
                f"uop {uop.id} has old-destination dependencies outside its dependency set"
            )
        unlisted_demands = set(uop.issue_domain_demands) - set(uop.issue_domains)
        if unlisted_demands:
            raise TraceValidationError(
                f"uop {uop.id} has demands for unlisted issue domains: "
                + ", ".join(sorted(unlisted_demands))
            )
        if len(set(uop.scheduler_partition_choices)) != len(
            uop.scheduler_partition_choices
        ):
            raise TraceValidationError(
                f"uop {uop.id} has duplicate scheduler partition choices"
            )
        if len(set(uop.execution_unit_choices)) != len(uop.execution_unit_choices):
            raise TraceValidationError(
                f"uop {uop.id} has duplicate execution unit choices"
            )
        if uop.part_count is not None and uop.part_index is None:
            raise TraceValidationError(
                f"uop {uop.id} sets part_count without part_index"
            )
        if uop.part_index is not None and uop.part_count is not None and not (
            0 <= uop.part_index < uop.part_count
        ):
            raise TraceValidationError(
                f"uop {uop.id} has invalid part index/count: "
                f"{uop.part_index}/{uop.part_count}"
            )
        for domain_id, demand in uop.issue_domain_demands.items():
            if isinstance(demand, bool) or not isinstance(demand, int) or demand < 1:
                raise TraceValidationError(
                    f"uop {uop.id} has invalid demand for issue domain "
                    f"{domain_id}: {demand!r}"
                )
        for name, demand in uop.rename_allocations.items():
            if isinstance(demand, bool) or not isinstance(demand, int) or demand < 1:
                raise TraceValidationError(
                    f"uop {uop.id} has invalid rename allocation for {name}: "
                    f"{demand!r}"
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
