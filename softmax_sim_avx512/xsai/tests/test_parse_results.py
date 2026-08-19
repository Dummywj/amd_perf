import importlib.util
import tempfile
import unittest
from pathlib import Path


SCRIPT = Path(__file__).parents[1] / "scripts" / "parse_results.py"
SPEC = importlib.util.spec_from_file_location("parse_results", SCRIPT)
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(MODULE)


def complete_log(samples_per_case=2):
    lines = [
        "XSAI_META format=2 isa=rv64gcv_zvl128b vlen_bits=128 "
        f"samples={samples_per_case} l1d_bytes=65536 cute_instructions=0 "
        f"param_cases={len(MODULE.EXPECTED_PARAMETERS)} param_iterations=64 "
        "hpm_audit=1"
    ]
    total = 0
    for kernel in MODULE.EXPECTED_KERNELS:
        for count in MODULE.EXPECTED_COUNTS:
            for sample in range(samples_per_case):
                lines.append(
                    f"XSAI_RESULT kernel={kernel} n={count} sample={sample} "
                    "raw_cycles=110 empty_cycles=10 cycles=100 checksum=0x1 "
                    "max_error_ppb=0 status=PASS"
                )
                lines.append(
                    f"XSAI_HPM scope={kernel} n={count} sample={sample} "
                    "cute_active_cycles=0 cute_retired=0 cute_memory_requests=0 "
                    "l1d_load_misses=0 dtlb_load_misses=0 cute_status=PASS "
                    "cache_status=CLEAN"
                )
                total += 1
    for name in MODULE.EXPECTED_PARAMETERS:
        for sample in range(samples_per_case):
            lines.append(
                f"XSAI_HPM scope={name} n=64 sample={sample} "
                "cute_active_cycles=0 cute_retired=0 cute_memory_requests=0 "
                "l1d_load_misses=0 dtlb_load_misses=0 cute_status=PASS "
                "cache_status=CLEAN"
            )
    lines.append(f"XSAI_DONE status=PASS cases=36 samples={total}")
    return "\n".join(lines)


def complete_log_with_parameters(samples_per_case=2):
    lines = complete_log(samples_per_case).splitlines()
    records = []
    for name in MODULE.EXPECTED_PARAMETERS:
        category, unit, operations_per_iteration = MODULE.EXPECTED_PARAMETER_SPECS[
            name
        ]
        for sample in range(samples_per_case):
            records.append(
                f"XSAI_PARAM name={name} category={category} unit={unit} "
                f"sample={sample} iterations=64 "
                f"operations={64 * operations_per_iteration} raw_cycles=522 "
                "empty_cycles=10 cycles=512 status=PASS"
            )
    return "\n".join([lines[0], *records, *lines[1:]])


class ParseResultsTest(unittest.TestCase):
    def test_parameter_contract_has_41_cases(self):
        self.assertEqual(len(MODULE.EXPECTED_PARAMETERS), 41)

    def test_complete_matrix_is_accepted_and_written(self):
        metadata, samples, done = MODULE.parse_log(complete_log())
        hpm = MODULE.parse_hpm_samples(complete_log())
        MODULE.validate(metadata, samples, done)
        MODULE.validate_hpm_samples(metadata, hpm)
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory)
            MODULE.write_results(metadata, samples, done, hpm, "rtl", output)
            self.assertTrue((output / "samples.csv").is_file())
            self.assertTrue((output / "summary.csv").is_file())

    def test_missing_sample_is_rejected(self):
        metadata, samples, done = MODULE.parse_log(complete_log())
        with self.assertRaisesRegex(ValueError, "incomplete result matrix"):
            MODULE.validate(metadata, samples[:-1], done)

    def test_profile_microbenchmarks_are_validated_and_written(self):
        text = complete_log_with_parameters()
        metadata, samples, done = MODULE.parse_log(text)
        parameters = MODULE.parse_parameter_samples(text)
        hpm = MODULE.parse_hpm_samples(text)
        MODULE.validate(metadata, samples, done)
        MODULE.validate_parameter_samples(metadata, parameters)
        MODULE.validate_hpm_samples(metadata, hpm)
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory)
            MODULE.write_parameter_results(parameters, hpm, "rtl", output)
            self.assertTrue((output / "profile_samples.csv").is_file())
            summary = (output / "profile_summary.csv").read_text()
            self.assertIn("fma_dependency", summary)
            self.assertIn("fp_add_same_vd", summary)
            self.assertIn("conversion_same_vd", summary)
            self.assertIn("integer_same_vd", summary)
            self.assertIn("load_stream_throughput", summary)
            self.assertIn("store_stream_throughput", summary)
            self.assertIn("0.500000", summary)

    def test_profile_operation_normalization_is_validated(self):
        text = complete_log_with_parameters().replace(
            "name=load_fma_store_iteration category=iteration unit=iteration "
            "sample=0 iterations=64 operations=64",
            "name=load_fma_store_iteration category=iteration unit=iteration "
            "sample=0 iterations=64 operations=128",
            1,
        )
        metadata, _, _ = MODULE.parse_log(text)
        parameters = MODULE.parse_parameter_samples(text)
        with self.assertRaisesRegex(ValueError, "invalid .* normalization"):
            MODULE.validate_parameter_samples(metadata, parameters)

    def test_same_vd_category_is_validated(self):
        text = complete_log_with_parameters().replace(
            "name=fp_add_same_vd category=same_vd unit=instruction sample=0",
            "name=fp_add_same_vd category=throughput unit=instruction sample=0",
            1,
        )
        metadata, _, _ = MODULE.parse_log(text)
        parameters = MODULE.parse_parameter_samples(text)

        with self.assertRaisesRegex(ValueError, "invalid .* normalization"):
            MODULE.validate_parameter_samples(metadata, parameters)


if __name__ == "__main__":
    unittest.main()
