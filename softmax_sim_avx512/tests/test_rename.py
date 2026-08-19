from __future__ import annotations

import copy
import unittest
from pathlib import Path

from src.simulator.engine import Engine
from src.simulator.profile import load_profile


ROOT = Path(__file__).resolve().parents[1]


def _trace(count: int) -> dict[str, object]:
    instructions = []
    for index in range(count):
        instructions.append(
            {
                "id": f"i{index}",
                "sequence": index,
                "mnemonic": "vfadd.vv",
                "profile_recipe": "vfadd.vv:any",
                "assembly": f"vfadd.vv v{index % 8}, v1, v2",
                "operands": [f"v{index % 8}", "v1", "v2"],
                "register_reads": ["v1", "v2"],
                "register_writes": [f"v{index % 8}"],
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
                "semantic_uops": [{"local_id": "u0", "kind": "vector_fp_add"}],
            }
        )
    return {"trace_version": 2, "workload": {"name": "rename-test"}, "instructions": instructions}


class RenamePolicyTest(unittest.TestCase):
    def _profile(self, free_entries: int, *, allocation_width: int = 6):
        base = load_profile(ROOT / "profiles/xsai.yaml", ROOT / "schemas/profile.schema.json")
        data = copy.deepcopy(base.data)
        rename = data["backend"]["rename"]
        rename["free_lists"]["vector"]["free_entries"] = free_entries
        rename["free_lists"]["vector_state"]["free_entries"] = 31
        rename["guard_entries"] = 0
        rename["allocation_width"] = allocation_width
        return type(base)(base.path, data, f"rename-test-{free_entries}-{allocation_width}")

    def test_free_list_blocks_until_retirement_release(self) -> None:
        profile = self._profile(2)
        bound = profile.bind(_trace(4))
        result = Engine(bound, profile, "out_of_order", "hot-l1").run()
        self.assertGreater(result.summary["rename"]["blockers"].get("rename_free_list:vector", 0), 0)
        self.assertEqual(result.summary["rename"]["remaining_free"]["vector"], 0)
        self.assertGreater(result.summary["rename"]["release_tokens"], 0)

    def test_allocation_width_is_checked_per_dispatch_cycle(self) -> None:
        profile = self._profile(20, allocation_width=1)
        profile.data["recipes"]["vfadd.vv:any"].pop("dispatch_domains")
        bound = profile.bind(_trace(3))
        result = Engine(bound, profile, "out_of_order", "hot-l1").run()
        self.assertGreater(
            result.summary["rename"]["blockers"].get("rename_allocation_width", 0), 0
        )

    def test_zen4_keeps_legacy_rename_disabled(self) -> None:
        profile = load_profile(ROOT / "profiles/amd_zen4.yaml", ROOT / "schemas/profile.schema.json")
        self.assertFalse(profile.rename_policy["enabled"])


if __name__ == "__main__":
    unittest.main()
