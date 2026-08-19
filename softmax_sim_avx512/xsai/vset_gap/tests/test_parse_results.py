import importlib.util
import tempfile
import unittest
from pathlib import Path


SCRIPT = Path(__file__).parents[1] / "scripts" / "parse_results.py"
SPEC = importlib.util.spec_from_file_location("vset_gap_parse_results", SCRIPT)
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(MODULE)


def complete_log(samples_per_case=2):
    lines = [
        "XSAI_VSET_META format=1 isa=rv64gcv_zvl128b vlen_bits=128 "
        f"samples={samples_per_case} cases={len(MODULE.CASE_SPECS)} "
        "iterations=64 elements_per_iteration=4 l1d_bytes=65536 "
        "cute_instructions=0 hpm_audit=1"
    ]
    for name, (form, consumer) in MODULE.CASE_SPECS.items():
        for sample in range(samples_per_case):
            lines.append(
                f"XSAI_VSET_RESULT name={name} form={form} consumer={consumer} "
                f"sample={sample} iterations=64 raw_cycles=650 empty_cycles=10 "
                "cycles=640 checksum=0x1 status=PASS"
            )
            lines.append(
                f"XSAI_HPM scope={name} n=64 sample={sample} "
                "cute_active_cycles=0 cute_retired=0 cute_memory_requests=0 "
                "l1d_load_misses=0 dtlb_load_misses=0 cute_status=PASS "
                "cache_status=CLEAN"
            )
    lines.append(
        f"XSAI_VSET_DONE status=PASS cases={len(MODULE.CASE_SPECS)} "
        f"samples={len(MODULE.CASE_SPECS) * samples_per_case}"
    )
    return "\n".join(lines)


class ParseResultsTest(unittest.TestCase):
    def test_complete_matrix_is_validated_and_written(self):
        metadata, samples, hpm, done = MODULE.parse_log(complete_log())
        MODULE.validate(metadata, samples, hpm, done)
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory)
            MODULE.write_results(metadata, samples, hpm, done, "rtl", output)
            summary = (output / "summary.csv").read_text(encoding="utf-8")
            self.assertIn("regular_lfs", summary)
            self.assertIn("10.000000", summary)
            self.assertTrue((output / "samples.csv").is_file())

    def test_missing_case_is_rejected(self):
        metadata, samples, hpm, done = MODULE.parse_log(complete_log())
        with self.assertRaisesRegex(ValueError, "incomplete vset-gap matrix"):
            MODULE.validate(metadata, samples[:-1], hpm, done)

    def test_wrong_form_is_rejected(self):
        text = complete_log().replace(
            "name=regular_lfs form=rd_rs1", "name=regular_lfs form=x0_x0", 1
        )
        metadata, samples, hpm, done = MODULE.parse_log(text)
        with self.assertRaisesRegex(ValueError, "invalid vset-gap case contract"):
            MODULE.validate(metadata, samples, hpm, done)

    def test_cute_activity_is_rejected(self):
        text = complete_log().replace("cute_active_cycles=0", "cute_active_cycles=1", 1)
        metadata, samples, hpm, done = MODULE.parse_log(text)
        with self.assertRaisesRegex(ValueError, "functional/HPM failures"):
            MODULE.validate(metadata, samples, hpm, done)

    def test_legacy_seven_case_matrix_remains_accepted(self):
        lines = complete_log().splitlines()
        legacy = MODULE.LEGACY_CASE_SPECS
        lines[0] = lines[0].replace(
            f"cases={len(MODULE.CASE_SPECS)}", f"cases={len(legacy)}"
        )
        lines[-1] = lines[-1].replace(
            f"cases={len(MODULE.CASE_SPECS)}", f"cases={len(legacy)}"
        ).replace(
            f"samples={len(MODULE.CASE_SPECS) * 2}", f"samples={len(legacy) * 2}"
        )
        lines = [
            line for line in lines
            if not any(
                f"name={name} " in line or f"scope={name} " in line
                for name in {
                    "outside_load",
                    "load_stream_1",
                    "load_stream_2",
                    "load_stream_4",
                    "aligned_load_stream_2",
                    "aligned_load_stream_4",
                }
            )
        ]
        metadata, samples, hpm, done = MODULE.parse_log("\n".join(lines))
        MODULE.validate(metadata, samples, hpm, done)

    def test_previous_eleven_case_matrix_remains_accepted(self):
        lines = complete_log().splitlines()
        previous = MODULE.PREVIOUS_CASE_SPECS
        lines[0] = lines[0].replace(
            f"cases={len(MODULE.CASE_SPECS)}", f"cases={len(previous)}"
        )
        lines[-1] = lines[-1].replace(
            f"cases={len(MODULE.CASE_SPECS)}", f"cases={len(previous)}"
        ).replace(
            f"samples={len(MODULE.CASE_SPECS) * 2}", f"samples={len(previous) * 2}"
        )
        lines = [
            line for line in lines
            if not any(
                f"name={name} " in line or f"scope={name} " in line
                for name in {"aligned_load_stream_2", "aligned_load_stream_4"}
            )
        ]
        metadata, samples, hpm, done = MODULE.parse_log("\n".join(lines))
        MODULE.validate(metadata, samples, hpm, done)


if __name__ == "__main__":
    unittest.main()
