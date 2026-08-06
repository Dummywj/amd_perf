from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from src.frontends.x86 import build_dynamic_trace
from src.simulator.engine import simulate
from src.simulator.export import write_dot, write_events_jsonl, write_perfetto, write_timeline
from src.simulator.profile import load_profile


ROOT = Path(__file__).resolve().parents[1]


class ExportTest(unittest.TestCase):
    def test_all_schedule_views_share_ids(self) -> None:
        profile = load_profile(ROOT / "profiles/amd_zen4.yaml")
        dynamic = build_dynamic_trace(
            ROOT / "kernel/softmax/artifacts/x86/softmax_avx512.s",
            "softmax_avx512_f32",
            ROOT / "recipes/x86.yaml",
            16,
        )
        result = simulate(profile.bind(dynamic), profile, "out_of_order")
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            write_events_jsonl(directory / "events.jsonl", result)
            write_perfetto(directory / "perfetto.json", result, 0, 20)
            write_dot(directory / "dependencies.dot", result, 0, 20)
            write_timeline(directory / "timeline.txt", result, 0, 20)

            perfetto = json.loads((directory / "perfetto.json").read_text())
            self.assertTrue(perfetto["traceEvents"])
            self.assertEqual(
                perfetto["otherData"]["execution_model"], "out_of_order"
            )
            events = [
                json.loads(line)
                for line in (directory / "events.jsonl").read_text().splitlines()
            ]
            self.assertEqual(events[0]["type"], "metadata")
            self.assertIn("i0.e0", (directory / "dependencies.dot").read_text())
            self.assertIn("testq", (directory / "timeline.txt").read_text())


if __name__ == "__main__":
    unittest.main()
