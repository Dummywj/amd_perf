from __future__ import annotations

import copy
import unittest
from pathlib import Path

from src.simulator.engine import simulate
from src.simulator.model import BoundTrace, ExecutionUop, MacroOp
from src.simulator.profile import ProfileError, load_profile


ROOT = Path(__file__).resolve().parents[1]


class DispatchDomainTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.profile = load_profile(
            ROOT / "profiles/xsai.yaml", ROOT / "schemas/profile.schema.json"
        )

    def _trace(self, count: int) -> BoundTrace:
        tpc = self.profile.ticks_per_cycle
        macros: list[MacroOp] = []
        uops: list[ExecutionUop] = []
        for index in range(count):
            uop_id = f"i{index}.e0"
            uops.append(
                ExecutionUop(
                    id=uop_id,
                    sequence=index,
                    parent_id=f"i{index}",
                    parent_sequence=index,
                    mnemonic="vfadd.vv",
                    assembly="vfadd.vv v1, v2, v3",
                    semantic_kinds=("vector_fp_add",),
                    kind="vector_fp",
                    scheduling_class=f"dispatch-domain-{index}",
                    part_index=None,
                    latency_ticks=tpc,
                    issue_interval_ticks=tpc,
                    occupancy_ticks=tpc,
                    resource_choices=("vfalu",),
                    issue_domains=(),
                )
            )
            macros.append(
                MacroOp(
                    id=f"i{index}",
                    sequence=index,
                    mnemonic="vfadd.vv",
                    assembly="vfadd.vv v1, v2, v3",
                    uop_ids=(uop_id,),
                    decoded_macro_ops=1,
                    retire_macro_ops=1,
                    uses_vector_scheduler=True,
                    uses_load_queue=False,
                    uses_store_queue=False,
                    dispatch_domains=("vector-complex-decode",),
                    dispatch_domain_demands={"vector-complex-decode": 1},
                )
            )
        return BoundTrace(
            trace_version=2,
            profile_id=self.profile.id,
            profile_sha256=self.profile.digest,
            ticks_per_cycle=tpc,
            macros=macros,
            uops=uops,
            resources=self.profile._resources({"vfalu"}),
            workload={"name": "dispatch-domain-test"},
            source_trace={"instructions": []},
        )

    def test_capacity_is_limited_per_architectural_dispatch_cycle(self) -> None:
        result = simulate(self._trace(2), self.profile, "out_of_order")

        self.assertEqual(
            [macro.dispatch_tick for macro in result.trace.macros],
            [0, result.ticks_per_cycle],
        )
        second = result.trace.macros[1]
        self.assertEqual(second.dispatch_blocker, "dispatch_domain_full")
        self.assertEqual(second.dispatch_blocker_domain, "vector-complex-decode")
        self.assertGreaterEqual(second.dispatch_blocker_count, 1)
        self.assertGreater(
            result.summary["dispatch_stalls"]["dispatch_domain_full"], 0
        )
        self.assertGreater(
            result.summary["dispatch_domain_blockers"]["vector-complex-decode"],
            0,
        )
        self.assertEqual(
            result.summary["dispatch_domain_stats"]["vector-complex-decode"][
                "capacity"
            ],
            1,
        )
        encoded = result.to_dict()
        self.assertEqual(
            encoded["instructions"][0]["dispatch_domains"],
            ["vector-complex-decode"],
        )
        self.assertTrue(
            any(event["type"] == "dispatch_blocked" for event in result.events)
        )

    def test_capacity_two_allows_two_macros_in_one_cycle(self) -> None:
        data = copy.deepcopy(self.profile.data)
        data["backend"]["dispatch_domains"]["vector-complex-decode"][
            "capacity"
        ] = 2
        profile = type(self.profile)(self.profile.path, data, "dispatch-capacity-two")

        result = simulate(self._trace(2), profile, "out_of_order")

        self.assertEqual(
            [macro.dispatch_tick for macro in result.trace.macros], [0, 0]
        )
        self.assertEqual(
            result.summary["dispatch_domain_blockers"], {}
        )

    def test_undomained_scalar_macro_uses_remaining_dispatch_width(self) -> None:
        trace = self._trace(2)
        scalar_macro = trace.macros[1]
        scalar_macro.uses_vector_scheduler = False
        scalar_macro.dispatch_domains = ()
        scalar_macro.dispatch_domain_demands = {}
        trace.uops[1].kind = "scalar_alu"
        trace.uops[1].semantic_kinds = ("scalar_alu",)

        result = simulate(trace, self.profile, "out_of_order")

        self.assertEqual(
            [macro.dispatch_tick for macro in result.trace.macros], [0, 0]
        )
        self.assertEqual(
            result.summary["dispatch_domain_usage"], {"vector-complex-decode": 1}
        )
        self.assertEqual(result.summary["dispatch_domain_blockers"], {})

    def test_recipe_must_reference_a_backend_dispatch_domain(self) -> None:
        data = copy.deepcopy(self.profile.data)
        data["recipes"]["vfadd.vv:any"]["dispatch_domains"] = ["missing"]

        with self.assertRaisesRegex(
            ProfileError, "recipe references missing dispatch domain: missing"
        ):
            type(self.profile)(self.profile.path, data, "missing-dispatch-domain")

    def test_profile_binding_carries_recipe_domains_to_macro_op(self) -> None:
        data = copy.deepcopy(self.profile.data)
        timing = data["recipes"]["vfadd.vv:any"]["uops"][0]
        timing["latency_cycles"] = 1
        timing["issue_interval_cycles"] = 1
        timing["resource_occupancy_cycles"] = 1
        profile = type(self.profile)(self.profile.path, data, "bound-dispatch-domain")
        trace = {
            "trace_version": 2,
            "workload": {"name": "bound-dispatch-domain"},
            "instructions": [
                {
                    "id": "i0",
                    "sequence": 0,
                    "mnemonic": "vfadd.vv",
                    "form": "any",
                    "assembly": "vfadd.vv v0, v1, v2",
                    "operands": ["v0", "v1", "v2"],
                    "register_reads": ["v1", "v2"],
                    "register_writes": ["v0"],
                    "register_dependencies": {},
                    "memory_dependencies": [],
                    "flags_dependency": None,
                    "memory": None,
                    "vector_state": {
                        "vlen_bits": 128,
                        "sew_bits": 32,
                        "lmul": "m1",
                        "vl": 4,
                    },
                    "active_vector_bits": 128,
                    "semantic_uops": [
                        {"local_id": "u0", "kind": "vector_fp_add"}
                    ],
                }
            ],
        }

        bound = profile.bind(trace)

        self.assertEqual(
            bound.macros[0].dispatch_domains, ("vector-complex-decode",)
        )
        self.assertEqual(
            bound.macros[0].dispatch_domain_demands,
            {"vector-complex-decode": 1},
        )

    def test_xsai_vector_recipes_carry_the_complex_decode_domain(self) -> None:
        recipes = self.profile.data["recipes"]
        self.assertEqual(self.profile.data["issue_domains"], {})
        self.assertTrue(
            all(
                recipe.get("dispatch_domains") == ["vector-complex-decode"]
                for recipe_id, recipe in recipes.items()
                if recipe_id.startswith("v")
            )
        )
        self.assertTrue(
            all(
                not recipe.get("dispatch_domains")
                for recipe_id, recipe in recipes.items()
                if not recipe_id.startswith("v")
            )
        )
        self.assertTrue(
            all(
                not uop.get("issue_domains")
                for recipe_id, recipe in recipes.items()
                if recipe_id.startswith("v")
                for uop in recipe["uops"]
            )
        )


if __name__ == "__main__":
    unittest.main()
