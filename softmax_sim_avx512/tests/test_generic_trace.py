from __future__ import annotations

import copy
import unittest
from pathlib import Path

from src.simulator.engine import simulate
from src.simulator.model import BoundTrace, ExecutionUop, MacroOp
from src.simulator.profile import load_profile
from src.simulator.trace import TraceValidationError


ROOT = Path(__file__).resolve().parents[1]


class GenericTraceTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.profile = load_profile(ROOT / "profiles/amd_zen4.yaml")

    def _trace(self, interval: float = 0.5) -> BoundTrace:
        tpc = self.profile.ticks_per_cycle
        uops = [
            ExecutionUop(
                id=f"u{index}",
                sequence=index,
                parent_id=f"m{index}",
                parent_sequence=index,
                mnemonic="display-only",
                assembly="display-only",
                semantic_kinds=("scalar_alu",),
                kind="scalar_alu",
                scheduling_class="generic-test",
                part_index=None,
                latency_ticks=(5 if index == 0 else 1) * tpc,
                issue_interval_ticks=self.profile.ticks(interval),
                occupancy_ticks=tpc,
                resource_choices=("scalar-alu-fit",),
                issue_domains=(),
                dependencies={"u0"} if index == 1 else set(),
            )
            for index in range(3)
        ]
        macros = [
            MacroOp(
                id=f"m{index}",
                sequence=index,
                mnemonic="display-only",
                assembly="display-only",
                uop_ids=(f"u{index}",),
                decoded_macro_ops=1,
                retire_macro_ops=1,
                uses_vector_scheduler=False,
                uses_load_queue=False,
                uses_store_queue=False,
            )
            for index in range(3)
        ]
        resources = self.profile._resources()
        return BoundTrace(
            trace_version=2,
            profile_id=self.profile.id,
            profile_sha256=self.profile.digest,
            ticks_per_cycle=tpc,
            macros=macros,
            uops=uops,
            resources=resources,
            workload={"name": "generic-test"},
            source_trace={"instructions": []},
        )

    def test_out_of_order_bypasses_blocked_generic_uop(self) -> None:
        out_of_order = simulate(copy.deepcopy(self._trace()), self.profile)
        in_order = simulate(
            copy.deepcopy(self._trace()), self.profile, execution_model="in_order"
        )
        self.assertLess(
            out_of_order.trace.uops[2].issue_tick,
            in_order.trace.uops[2].issue_tick,
        )
        self.assertEqual(
            {uop.id for uop in out_of_order.trace.uops},
            {uop.id for uop in in_order.trace.uops},
        )

    def test_half_cycle_issue_interval_uses_integer_ticks(self) -> None:
        result = simulate(self._trace(), self.profile)
        self.assertEqual(
            result.trace.uops[2].issue_tick - result.trace.uops[0].issue_tick,
            result.ticks_per_cycle // 2,
        )

    def test_dependency_cycle_is_rejected_before_simulation(self) -> None:
        trace = self._trace()
        trace.uops[0].dependencies.add("u1")
        with self.assertRaisesRegex(TraceValidationError, "contains a cycle"):
            simulate(trace, self.profile)


if __name__ == "__main__":
    unittest.main()
