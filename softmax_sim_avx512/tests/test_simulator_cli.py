from __future__ import annotations

import contextlib
import io
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

from src.simulator import cli


class FakeProfile:
    def __init__(self, data: dict) -> None:
        self.data = data
        self.bound_trace = None

    def bind(self, trace: dict) -> str:
        self.bound_trace = trace
        return "bound-trace"


class SimulatorCliTest(unittest.TestCase):
    def arguments(self, output_dir: Path, *extra: str) -> list[str]:
        return [
            "simulator",
            *extra,
            "--assembly",
            "kernel.s",
            "--recipe",
            "recipe.yaml",
            "--profile",
            "profile.yaml",
            "--schema",
            "schema.json",
            "--count",
            "16",
            "--output-dir",
            str(output_dir),
        ]

    def run_main(
        self,
        arguments: list[str],
        profile: FakeProfile,
        *,
        events: list[str] | None = None,
    ) -> tuple[int, str, str, mock.Mock, mock.Mock]:
        order = events if events is not None else []

        def load_profile(*_args: object) -> FakeProfile:
            order.append("profile")
            return profile

        x86_builder = mock.Mock(
            side_effect=lambda *_args, **_kwargs: (
                order.append("x86-trace") or {"isa": "x86"}
            )
        )
        rvv_builder = mock.Mock(
            side_effect=lambda *_args, **_kwargs: (
                order.append("rvv-trace") or {"isa": "rvv"}
            )
        )
        result = SimpleNamespace(cycles=12, summary={"retired_macro_ops": 3})
        standard_output = io.StringIO()
        standard_error = io.StringIO()
        with contextlib.ExitStack() as stack:
            stack.enter_context(mock.patch.object(cli.sys, "argv", arguments))
            stack.enter_context(
                mock.patch.object(cli, "load_profile", side_effect=load_profile)
            )
            stack.enter_context(
                mock.patch.object(cli, "build_x86_dynamic_trace", x86_builder)
            )
            stack.enter_context(
                mock.patch.object(cli, "build_rvv_dynamic_trace", rvv_builder)
            )
            simulate = stack.enter_context(
                mock.patch.object(cli, "simulate", return_value=result)
            )
            for name in (
                "write_json",
                "write_result",
                "write_events_jsonl",
                "write_perfetto",
                "write_dot",
                "write_timeline",
                "write_semantic_html",
            ):
                stack.enter_context(mock.patch.object(cli, name))
            with contextlib.redirect_stdout(standard_output), contextlib.redirect_stderr(
                standard_error
            ):
                status = cli.main()

        if status == 0:
            simulate.assert_called_once_with(
                "bound-trace", profile, "out_of_order", "hot-l1", None
            )
        return (
            status,
            standard_output.getvalue(),
            standard_error.getvalue(),
            x86_builder,
            rvv_builder,
        )

    def test_x86_keeps_softmax_function_default_and_loads_profile_first(self) -> None:
        profile = FakeProfile({"isa": {"max_vector_bits": 512}})
        events: list[str] = []
        with tempfile.TemporaryDirectory() as temporary:
            status, output, error, x86_builder, rvv_builder = self.run_main(
                self.arguments(Path(temporary)), profile, events=events
            )

        self.assertEqual(status, 0)
        self.assertEqual(error, "")
        self.assertIn('"cycles": 12', output)
        self.assertEqual(events[:2], ["profile", "x86-trace"])
        x86_builder.assert_called_once_with(
            Path("kernel.s"),
            "softmax_avx512_f32",
            Path("recipe.yaml"),
            16,
            None,
        )
        rvv_builder.assert_not_called()
        self.assertEqual(profile.bound_trace, {"isa": "x86"})

    def test_rvv_uses_profile_vlen(self) -> None:
        profile = FakeProfile(
            {
                "isa": {
                    "vector_length_bits": 128,
                    "max_vector_bits": 128,
                    "max_element_bits": 64,
                }
            }
        )
        with tempfile.TemporaryDirectory() as temporary:
            status, _, error, x86_builder, rvv_builder = self.run_main(
                self.arguments(
                    Path(temporary),
                    "--isa",
                    "rvv",
                    "--function",
                    "vector_copy_rvv_f32",
                ),
                profile,
            )

        self.assertEqual(status, 0)
        self.assertEqual(error, "")
        x86_builder.assert_not_called()
        rvv_builder.assert_called_once_with(
            Path("kernel.s"),
            "vector_copy_rvv_f32",
            Path("recipe.yaml"),
            16,
            None,
            vlen_bits=128,
        )
        self.assertEqual(profile.bound_trace, {"isa": "rvv"})

    def test_rvv_accepts_bounded_explicit_vlen_override(self) -> None:
        profile = FakeProfile(
            {
                "isa": {
                    "vector_length_bits": 128,
                    "max_vector_bits": 512,
                    "max_element_bits": 64,
                }
            }
        )
        with tempfile.TemporaryDirectory() as temporary:
            status, _, error, _, rvv_builder = self.run_main(
                self.arguments(
                    Path(temporary),
                    "--isa",
                    "rvv",
                    "--function",
                    "vector_copy_rvv_f32",
                    "--vlen-bits",
                    "256",
                ),
                profile,
            )

        self.assertEqual(status, 0)
        self.assertEqual(error, "")
        self.assertEqual(rvv_builder.call_args.kwargs, {"vlen_bits": 256})

    def test_rvv_requires_function_without_using_x86_default(self) -> None:
        profile = FakeProfile(
            {"isa": {"vector_length_bits": 128, "max_vector_bits": 128}}
        )
        with tempfile.TemporaryDirectory() as temporary:
            status, _, error, _, rvv_builder = self.run_main(
                self.arguments(Path(temporary), "--isa", "rvv"), profile
            )

        self.assertEqual(status, 2)
        self.assertIn("--function is required when --isa=rvv", error)
        rvv_builder.assert_not_called()

    def test_rvv_reports_missing_or_out_of_range_vlen(self) -> None:
        cases = (
            (
                {"isa": {"max_vector_bits": 128}},
                (),
                "RVV VLEN is unavailable",
            ),
            (
                {
                    "isa": {
                        "vector_length_bits": 128,
                        "max_vector_bits": 128,
                    }
                },
                ("--vlen-bits", "256"),
                "exceeds profile isa.max_vector_bits",
            ),
        )
        for data, vlen_arguments, message in cases:
            with self.subTest(message=message), tempfile.TemporaryDirectory() as temporary:
                status, _, error, _, rvv_builder = self.run_main(
                    self.arguments(
                        Path(temporary),
                        "--isa",
                        "rvv",
                        "--function",
                        "vector_copy_rvv_f32",
                        *vlen_arguments,
                    ),
                    FakeProfile(data),
                )
                self.assertEqual(status, 2)
                self.assertIn(message, error)
                rvv_builder.assert_not_called()

    def test_x86_rejects_rvv_vlen_option(self) -> None:
        profile = FakeProfile({"isa": {"max_vector_bits": 512}})
        with tempfile.TemporaryDirectory() as temporary:
            status, _, error, x86_builder, _ = self.run_main(
                self.arguments(Path(temporary), "--vlen-bits", "128"), profile
            )

        self.assertEqual(status, 2)
        self.assertIn("--vlen-bits is only valid when --isa=rvv", error)
        x86_builder.assert_not_called()


if __name__ == "__main__":
    unittest.main()
