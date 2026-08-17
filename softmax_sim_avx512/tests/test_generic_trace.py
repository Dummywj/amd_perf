from __future__ import annotations

import copy
import unittest
from pathlib import Path

from src.simulator.engine import SimulatorError, simulate
from src.simulator.model import BoundTrace, ExecutionUop, MacroOp
from src.simulator.profile import Profile, load_profile
from src.simulator.trace import TraceValidationError


ROOT = Path(__file__).resolve().parents[1]


class GenericTraceTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.profile = load_profile(ROOT / "profiles/amd_zen4.yaml")

    def _trace(
        self,
        interval: float = 0.5,
        issue_domains: tuple[str, ...] = (),
        issue_domain_demands: dict[str, int] | None = None,
    ) -> BoundTrace:
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
                issue_domains=issue_domains,
                issue_domain_demands=dict(issue_domain_demands or {}),
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

    def _profile_with_issue_domains(
        self, capacities: dict[str, int]
    ) -> Profile:
        data = copy.deepcopy(self.profile.data)
        data["issue_domains"].update(
            {
                domain_id: {
                    "capacity": capacity,
                    "evidence": ["local-profile-benchmark"],
                }
                for domain_id, capacity in capacities.items()
            }
        )
        return Profile(self.profile.path, data, self.profile.digest)

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

    def test_unlisted_issue_domain_demand_is_rejected_before_simulation(self) -> None:
        trace = self._trace(issue_domain_demands={"not-listed": 1})
        with self.assertRaisesRegex(
            TraceValidationError, "demands for unlisted issue domains: not-listed"
        ):
            simulate(trace, self.profile)

    def test_unknown_issue_domain_is_rejected_with_clear_error(self) -> None:
        trace = self._trace(issue_domains=("not-in-profile",))
        with self.assertRaisesRegex(
            SimulatorError,
            "bound trace references unknown issue domains: not-in-profile",
        ):
            simulate(trace, self.profile)

    def test_weighted_issue_domain_reserves_multiple_tokens(self) -> None:
        profile = self._profile_with_issue_domains({"test-weighted": 3})
        trace = self._trace(
            issue_domains=("test-weighted",),
            issue_domain_demands={"test-weighted": 2},
        )

        result = simulate(trace, profile)

        self.assertEqual(
            [uop.issue_tick for uop in result.trace.uops],
            [0, 5 * result.ticks_per_cycle, result.ticks_per_cycle],
        )
        self.assertGreater(
            result.trace.uops[1].stall_reasons.get("dependency", 0), 0
        )
        self.assertGreater(
            result.trace.uops[2].stall_reasons.get("issue_domain_busy", 0), 0
        )

    def test_all_issue_domains_must_have_their_demand_available(self) -> None:
        profile = self._profile_with_issue_domains(
            {"test-wide": 4, "test-narrow": 1}
        )
        trace = self._trace(
            issue_domains=("test-wide", "test-narrow"),
            issue_domain_demands={"test-wide": 2},
        )

        result = simulate(trace, profile)

        # test-narrow omits an override and therefore consumes one token.
        self.assertEqual(result.trace.uops[2].issue_tick, result.ticks_per_cycle)
        self.assertEqual(
            result.trace.uops[2].issue_domain_demands, {"test-wide": 2}
        )


if __name__ == "__main__":
    unittest.main()
