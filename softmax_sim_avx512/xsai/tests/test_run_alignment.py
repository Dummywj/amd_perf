from __future__ import annotations

import csv
import importlib.util
import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock


SCRIPT = Path(__file__).parents[1] / "scripts" / "run_alignment.py"
SPEC = importlib.util.spec_from_file_location("run_alignment", SCRIPT)
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(MODULE)


def write_complete_summary(path: Path) -> None:
    fields = [
        "source",
        "kernel",
        "n",
        "samples",
        "median_cycles",
        "min_cycles",
        "max_cycles",
        "cycles_per_element",
        "l1d_refill_max",
        "dtlb_miss_max",
        "cache_contaminated_samples",
    ]
    with path.open("w", newline="", encoding="utf-8") as target:
        writer = csv.DictWriter(target, fieldnames=fields)
        writer.writeheader()
        for kernel in MODULE.EXPECTED_KERNELS:
            for count in MODULE.EXPECTED_COUNTS:
                row = {
                    "source": "rtl",
                    "kernel": kernel,
                    "n": count,
                    "samples": 5,
                    "median_cycles": count + 100,
                    "min_cycles": count + 95,
                    "max_cycles": count + 105,
                    "cycles_per_element": (count + 100) / count,
                    "l1d_refill_max": 0,
                    "dtlb_miss_max": 0,
                    "cache_contaminated_samples": 0,
                }
                if kernel == "axpy" and count == 1024:
                    row["l1d_refill_max"] = 1
                    row["cache_contaminated_samples"] = 1
                writer.writerow(row)


def write_dummy_assemblies(root: Path) -> None:
    for kernel in MODULE.EXPECTED_KERNELS:
        assembly = root / kernel / "artifacts" / "rvv" / f"{kernel}_rvv.s"
        assembly.parent.mkdir(parents=True)
        assembly.write_text(f"{kernel}_rvv_f32:\n\tret\n", encoding="utf-8")


def write_profile_summary(path: Path) -> None:
    fields = [
        "source",
        "name",
        "category",
        "unit",
        "samples",
        "operations",
        "median_cycles",
        "cycles_per_operation",
        "cache_status",
        "fit_status",
    ]
    with path.open("w", newline="", encoding="utf-8") as target:
        writer = csv.DictWriter(target, fieldnames=fields)
        writer.writeheader()
        for index, name in enumerate(MODULE.DIAGNOSTIC_MICROBENCHES):
            writer.writerow(
                {
                    "source": "rtl",
                    "name": name,
                    "category": "diagnostic",
                    "unit": "instruction",
                    "samples": 5,
                    "operations": 1024,
                    "median_cycles": 1024 + index,
                    "cycles_per_operation": 1.0 + index / 1024,
                    "cache_status": "CLEAN",
                    "fit_status": "VALID",
                }
            )


class RunAlignmentTest(unittest.TestCase):
    def test_cache_classification_accepts_future_hpm_columns(self) -> None:
        self.assertEqual(
            MODULE.classify_cache(
                {"samples": "5", "l1d_refills": "0", "dtlb_misses": "0"}
            )[:2],
            ("clean", True),
        )
        status, eligible, reason = MODULE.classify_cache(
            {"samples": "5", "l1d_refills": "2", "dtlb_misses": "0"}
        )
        self.assertEqual(status, "contaminated")
        self.assertFalse(eligible)
        self.assertIn("l1d_refills", reason)
        self.assertEqual(
            MODULE.classify_cache({"samples": "5"})[:2], ("unknown", False)
        )

    def test_complete_matrix_is_normalized_and_contamination_is_excluded(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            summary = Path(directory) / "summary.csv"
            write_complete_summary(summary)
            records = MODULE.read_rtl_summary(summary)

        self.assertEqual(len(records), 36)
        contaminated = [row for row in records if row["cache_status"] == "contaminated"]
        self.assertEqual(
            [(row["kernel"], row["n"]) for row in contaminated], [("axpy", 1024)]
        )
        self.assertFalse(contaminated[0]["fit_eligible"])
        self.assertEqual(sum(row["fit_eligible"] for row in records), 35)

    def test_incomplete_matrix_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            summary = Path(directory) / "summary.csv"
            write_complete_summary(summary)
            rows = summary.read_text(encoding="utf-8").splitlines()
            summary.write_text("\n".join(rows[:-1]) + "\n", encoding="utf-8")
            with self.assertRaisesRegex(MODULE.AlignmentError, "incomplete RTL summary"):
                MODULE.read_rtl_summary(summary)

    def test_parse_only_cli_writes_csv_json_and_report_without_profile(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            summary = root / "summary.csv"
            kernel_root = root / "kernel"
            output = root / "alignment"
            report = root / "xsai_result.md"
            profile_summary = root / "profile_summary.csv"
            write_complete_summary(summary)
            write_profile_summary(profile_summary)
            write_dummy_assemblies(kernel_root)

            status = MODULE.main(
                [
                    "--parse-only",
                    "--rtl-summary",
                    str(summary),
                    "--profile-summary",
                    str(profile_summary),
                    "--kernel-root",
                    str(kernel_root),
                    "--profile",
                    str(root / "does-not-exist.yaml"),
                    "--output-dir",
                    str(output),
                    "--report",
                    str(report),
                ]
            )

            self.assertEqual(status, 0)
            self.assertTrue((output / "alignment.csv").is_file())
            document = json.loads((output / "alignment.json").read_text())
            self.assertEqual(document["status"], "rtl-parsed")
            self.assertEqual(document["aggregate"]["rtl_points"], 36)
            self.assertEqual(
                set(document["microbenchmark_evidence"]),
                set(MODULE.DIAGNOSTIC_MICROBENCHES),
            )
            report_text = report.read_text(encoding="utf-8")
            self.assertIn("模拟尚未运行", report_text)
            self.assertIn("## 差距诊断", report_text)
            self.assertIn("load_same_vd", report_text)

    def test_profile_summary_rejects_duplicate_diagnostic_case(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            profile_summary = Path(directory) / "profile_summary.csv"
            write_profile_summary(profile_summary)
            lines = profile_summary.read_text(encoding="utf-8").splitlines()
            profile_summary.write_text(
                "\n".join([*lines, lines[1]]) + "\n", encoding="utf-8"
            )
            with self.assertRaisesRegex(MODULE.AlignmentError, "duplicate"):
                MODULE.read_profile_summary(profile_summary)

    def test_simulator_rows_compute_signed_error_but_fit_uses_clean_only(self) -> None:
        records = [
            {
                "kernel": "axpy",
                "n": 512,
                "samples": 5,
                "median_cycles": 100,
                "min_cycles": 98,
                "max_cycles": 102,
                "cycles_per_element": 100 / 512,
                "cache_status": "clean",
                "fit_eligible": True,
                "exclusion_reason": "",
                "rtl_fields": {},
            },
            {
                "kernel": "axpy",
                "n": 1024,
                "samples": 5,
                "median_cycles": 200,
                "min_cycles": 198,
                "max_cycles": 202,
                "cycles_per_element": 200 / 1024,
                "cache_status": "contaminated",
                "fit_eligible": False,
                "exclusion_reason": "miss",
                "rtl_fields": {},
            },
        ]
        specs = [
            {"kernel": "axpy", "assembly": Path("axpy.s"), "function": "axpy_rvv_f32"}
        ]
        profile = SimpleNamespace(
            simulation_ready=True,
            backend={"execution_model": "generic-token"},
            unresolved_parameters=(),
            id="fixture",
            digest="abc",
        )

        def simulator_case(_spec, count, _profile):
            return {
                "cycles": 110 if count == 512 else 180,
                "dynamic_instruction_count": 10,
                "semantic_uop_count": 12,
                "assembly_sha256": "def",
            }

        with mock.patch("src.simulator.profile.load_profile", return_value=profile):
            aligned, _ = MODULE.simulate_matrix(
                records,
                specs,
                Path("profile.yaml"),
                Path("schema.json"),
                Path("recipe.yaml"),
                Path("uops.yaml"),
                simulator_case,
            )

        self.assertEqual(aligned[0]["relative_error_percent"], 10.0)
        self.assertEqual(aligned[1]["relative_error_percent"], -10.0)
        stats = MODULE.aggregate(aligned)
        self.assertEqual(stats["diagnostic_all_points"]["points"], 2)
        self.assertEqual(stats["fit_eligible_points_only"]["points"], 1)

    def test_unresolved_profile_error_points_to_parse_only(self) -> None:
        profile = SimpleNamespace(
            simulation_ready=False,
            backend={"execution_model": "xsai-capability-gap-pending"},
            unresolved_parameters=("resources.vfdiv.source_latency_cycles",),
        )
        with self.assertRaisesRegex(MODULE.AlignmentError, "--parse-only"):
            MODULE.require_ready_profile(profile)

    def test_generic_backend_can_defer_readiness_to_trace_binding(self) -> None:
        profile = SimpleNamespace(
            simulation_ready=False,
            backend={"execution_model": "generic-token"},
            unresolved_parameters=("memory.levels.l2.latency_cycles",),
        )
        MODULE.require_ready_profile(profile)


if __name__ == "__main__":
    unittest.main()
