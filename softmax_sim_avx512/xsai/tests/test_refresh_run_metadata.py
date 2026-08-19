import hashlib
import importlib.util
import tempfile
import unittest
from pathlib import Path


SCRIPT = Path(__file__).parents[1] / "scripts" / "refresh_run_metadata.py"
SPEC = importlib.util.spec_from_file_location("refresh_run_metadata", SCRIPT)
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(MODULE)


class RefreshRunMetadataTests(unittest.TestCase):
    def test_refreshes_results_and_existing_build_artifacts(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            result_dir = root / "rtl"
            build_dir = root / "build"
            result_dir.mkdir()
            build_dir.mkdir()
            contents = {
                result_dir / "rtl.log": b"rtl log\n",
                result_dir / "summary.csv": b"summary\n",
                result_dir / "profile_summary.csv": b"profile\n",
                result_dir / "result_metadata.json": b"{}\n",
                build_dir / "xsai-kernel-bench-riscv64-xs.bin": b"binary",
                build_dir / "xsai-kernel-bench-riscv64-xs.elf": b"elf",
                build_dir / "xsai-kernel-bench-riscv64-xs.txt": b"disassembly",
            }
            for path, content in contents.items():
                path.write_bytes(content)

            existing = (
                "workspace_commit=abc\n"
                "summary_csv_sha256=stale\n"
                "binary_sha256=stale\n"
            )
            metadata = result_dir / "run_metadata.txt"
            metadata.write_text(existing, encoding="utf-8")
            MODULE.refresh_file(metadata, result_dir, build_dir)
            refreshed = metadata.read_text(encoding="utf-8")
            pairs = [line.split("=", 1) for line in refreshed.splitlines()]
            fields = dict(pairs)

            self.assertEqual(fields["workspace_commit"], "abc")
            for key, path in {
                **{
                    key: result_dir / name
                    for key, name in MODULE.RESULT_ARTIFACTS.items()
                },
                **{
                    key: build_dir / name
                    for key, name in MODULE.BUILD_ARTIFACTS.items()
                },
            }.items():
                expected = hashlib.sha256(path.read_bytes()).hexdigest()
                self.assertEqual(fields[key], expected)
                self.assertEqual(sum(field == key for field, _ in pairs), 1)

    def test_omits_missing_optional_build_artifacts(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            result_dir = root / "rtl"
            build_dir = root / "build"
            result_dir.mkdir()
            build_dir.mkdir()
            for name in MODULE.RESULT_ARTIFACTS.values():
                (result_dir / name).write_text(name, encoding="utf-8")

            refreshed = MODULE.refreshed_metadata(
                "elf_sha256=stale\nkeep=value\n", result_dir, build_dir
            )

            self.assertIn("keep=value\n", refreshed)
            for key in MODULE.BUILD_ARTIFACTS:
                self.assertNotIn(f"{key}=", refreshed)

    def test_rejects_missing_required_result_artifact(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            result_dir = root / "rtl"
            build_dir = root / "build"
            result_dir.mkdir()
            build_dir.mkdir()

            with self.assertRaisesRegex(FileNotFoundError, "summary.csv"):
                MODULE.refreshed_metadata("keep=value\n", result_dir, build_dir)


if __name__ == "__main__":
    unittest.main()
