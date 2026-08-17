from __future__ import annotations

import json
import re
import tempfile
import unittest
from pathlib import Path

from src.frontends.x86 import build_dynamic_trace
from src.simulator.engine import simulate
from src.simulator.export import (
    write_dot,
    write_events_jsonl,
    write_perfetto,
    write_semantic_html,
    write_timeline,
)
from src.simulator.profile import load_profile
from src.simulator.semantic_view import build_semantic_view_model


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
            write_semantic_html(directory / "semantic_schedule.html", result)

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

            html = (directory / "semantic_schedule.html").read_text()
            self.assertIn("<!doctype html>", html)
            self.assertNotIn("__SEMANTIC_TRACE_DATA__", html)
            self.assertNotRegex(html, r"<script[^>]+src=")
            self.assertNotRegex(html, r"<link[^>]+href=")
            encoded = re.search(
                r'<script id="trace-data" type="application/json">(.*?)</script>',
                html,
                re.DOTALL,
            )
            self.assertIsNotNone(encoded)
            view_model = json.loads(encoded.group(1))
            self.assertEqual(
                view_model["metadata"]["ticks_per_cycle"], result.ticks_per_cycle
            )
            self.assertNotIn("instructions", view_model)
            self.assertNotIn("execution_uops", view_model)
            self.assertEqual(
                view_model["metadata"]["semantic_uop_count"],
                len(view_model["semantic_uops"]),
            )
            self.assertIn("Continuous", html)
            self.assertIn("Discrete", html)
            self.assertIn("drawDiscreteTiming", html)

    def test_semantic_view_aggregates_execution_parts(self) -> None:
        profile = load_profile(ROOT / "profiles/amd_zen4.yaml")
        dynamic = build_dynamic_trace(
            ROOT / "kernel/softmax/artifacts/x86/softmax_avx512.s",
            "softmax_avx512_f32",
            ROOT / "recipes/x86.yaml",
            16,
        )
        result = simulate(profile.bind(dynamic), profile, "out_of_order")
        view_model = build_semantic_view_model(result)
        semantic = next(
            node
            for node in view_model["semantic_uops"]
            if node["kind"] == "vector_fp_max" and len(node["execution_uop_ids"]) == 2
        )
        execution = {
            node["id"]: node for node in view_model["execution_uops"]
        }
        children = [execution[uop_id] for uop_id in semantic["execution_uop_ids"]]
        self.assertEqual(
            semantic["timing"]["issue_tick"],
            min(child["timing"]["issue_tick"] for child in children),
        )
        self.assertEqual(
            semantic["timing"]["complete_tick"],
            max(child["timing"]["complete_tick"] for child in children),
        )
        self.assertTrue(
            any(
                operand["width_bits"] == 512
                for operand in semantic["source_operands"]
            )
        )
        self.assertTrue(
            any(
                edge["target"] == semantic["id"] and edge["kind"] == "internal"
                for edge in view_model["dependencies"]["semantic"]
            )
        )
        weighted = next(
            node
            for node in view_model["execution_uops"]
            if any(demand > 1 for demand in node["issue_domain_demands"].values())
        )
        self.assertTrue(
            set(weighted["issue_domain_demands"]).issubset(weighted["issue_domains"])
        )
        serialized = {uop["id"]: uop for uop in result.to_dict()["uops"]}
        self.assertEqual(
            serialized[weighted["id"]]["issue_domain_demands"],
            weighted["issue_domain_demands"],
        )


if __name__ == "__main__":
    unittest.main()
