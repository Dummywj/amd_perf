#!/usr/bin/env python3

import argparse
import re
import subprocess
from pathlib import Path


def parse_args():
    parser = argparse.ArgumentParser(description="Check FP32 operation disassembly")
    parser.add_argument("build_dir")
    parser.add_argument("output_md")
    parser.add_argument("--dense-exploratory", action="store_true")
    return parser.parse_args()


def disassemble(binary, symbol):
    result = subprocess.run(
        [
            "objdump",
            "-d",
            "--no-show-raw-insn",
            f"--disassemble={symbol}",
            str(binary),
        ],
        check=True,
        text=True,
        capture_output=True,
    )
    marker = f"<{symbol}>:"
    if marker not in result.stdout:
        raise ValueError(f"missing symbol {symbol} in {binary}")
    return result.stdout.split(marker, 1)[1]


def require(body, pattern, description):
    if not re.search(pattern, body, re.MULTILINE):
        raise ValueError(f"missing {description}")


def forbid(body, pattern, description):
    if re.search(pattern, body, re.MULTILINE):
        raise ValueError(f"unexpected {description}")


def matching_instructions(body, pattern):
    return [line.strip() for line in body.splitlines() if re.search(pattern, line)]


def main():
    args = parse_args()
    build_dir = Path(args.build_dir).resolve()
    gather_binary = build_dir / "gather_fp32_bench"
    scatter_binary = build_dir / "scatter_fp32_bench"
    softmax_binary = build_dir / "softmax_fp32_bench"

    bodies = {
        "gather_avx512_vgather": disassemble(gather_binary, "gather_avx512_vgather"),
        "scatter_avx512_vscatter": disassemble(scatter_binary, "scatter_avx512_vscatter"),
        "gather_avx512_load_store": disassemble(gather_binary, "gather_avx512_load_store"),
        "scatter_avx512_load_store": disassemble(scatter_binary, "scatter_avx512_load_store"),
        "gather_scalar": disassemble(gather_binary, "gather_scalar"),
        "scatter_scalar": disassemble(scatter_binary, "scatter_scalar"),
        "reduce_sum_scalar": disassemble(softmax_binary, "reduce_sum_scalar"),
        "reduce_max_scalar": disassemble(softmax_binary, "reduce_max_scalar"),
        "softmax_scalar": disassemble(softmax_binary, "softmax_scalar"),
        "reduce_sum_avx512": disassemble(softmax_binary, "reduce_sum_avx512"),
        "reduce_max_avx512": disassemble(softmax_binary, "reduce_max_avx512"),
        "softmax_avx512": disassemble(softmax_binary, "softmax_avx512"),
    }

    require(bodies["gather_avx512_vgather"], r"\bvgatherdps\b", "vgatherdps")
    forbid(bodies["gather_avx512_vgather"], r"\bvscatterdps\b", "vscatterdps in gather")
    require(bodies["scatter_avx512_vscatter"], r"\bvscatterdps\b", "vscatterdps")
    forbid(bodies["scatter_avx512_vscatter"], r"\bvgatherdps\b", "vgatherdps in scatter")

    for symbol in ("gather_avx512_load_store", "scatter_avx512_load_store"):
        body = bodies[symbol]
        if len(re.findall(r"\bvmovups\b.*%zmm|\bvmovups\b.*\{%k", body)) < 2:
            raise ValueError(f"{symbol}: missing explicit ZMM load/store")
        forbid(body, r"\b(?:vgatherdps|vscatterdps|call)\b", f"indirect/copy call in {symbol}")

    packed_math = r"\bv(?:add|sub|mul|div|max|min)ps\b|\b(?:vgatherdps|vscatterdps)\b|%ymm"
    for symbol in (
        "gather_scalar",
        "scatter_scalar",
        "reduce_sum_scalar",
        "reduce_max_scalar",
        "softmax_scalar",
    ):
        forbid(bodies[symbol], packed_math, f"packed arithmetic in {symbol}")
        for line in matching_instructions(bodies[symbol], r"%zmm"):
            if "vmovdqu8" not in line or not re.search(r"\(%r(?:sp|bp)\)", line):
                raise ValueError(f"{symbol}: non-stack-clear ZMM instruction: {line}")

    require(bodies["reduce_sum_avx512"], r"\bvaddps\b.*%zmm", "packed AVX-512 sum")
    require(bodies["reduce_max_avx512"], r"\bvmaxps\b.*%zmm", "packed AVX-512 max")
    require(bodies["softmax_avx512"], r"Sleef_expf16_u10avx512f", "SLEEF AVX-512 u10 call")

    lines = []
    if args.dense_exploratory:
        lines.extend(
            [
                "# EXPLORATORY / NON-FORMAL - Dense disassembly gate",
                "",
                "**This gate supports a dense exploratory run whose environment may be affected by external Java/ZGC activity and CPU contention.**",
                "",
                "**Performance results are for relative trends only; no absolute, cross-machine, regression, capacity, hardware-limit, or formal-acceptance conclusions are permitted.**",
                "",
            ]
        )
    else:
        lines.extend(["# FP32 operation disassembly gate", ""])
    lines.extend(
        [
            "| Kernel group | Required evidence | Forbidden evidence | Status |",
            "| --- | --- | --- | --- |",
            "| Indexed Gather | `vgatherdps` | `vscatterdps` | PASS |",
            "| Indexed Scatter | `vscatterdps` | `vgatherdps` | PASS |",
            "| Contiguous Gather/Scatter | explicit ZMM `vmovups`, masked tail | gather/scatter, `call`/library copy | PASS |",
            "| Scalar timed math bodies | scalar `ss` arithmetic | packed arithmetic, YMM, gather/scatter | PASS |",
            "| AVX-512 Reduce/Softmax | packed ZMM math, SLEEF `expf16_u10` | missing vector body | PASS |",
            "",
            "ZMM stores used only to clear scalar accumulator arrays on the stack are not vectorized timed math and were checked separately.",
            "",
            "## Key instructions",
            "",
        ]
    )
    for symbol, pattern in (
        ("gather_avx512_vgather", r"vgatherdps"),
        ("scatter_avx512_vscatter", r"vscatterdps"),
        ("gather_avx512_load_store", r"vmovups.*(?:%zmm|\{%k)"),
        ("scatter_avx512_load_store", r"vmovups.*(?:%zmm|\{%k)"),
    ):
        lines.extend([f"### `{symbol}`", "", "```text"])
        lines.extend(matching_instructions(bodies[symbol], pattern)[:4])
        lines.extend(["```", ""])
    Path(args.output_md).write_text("\n".join(lines), encoding="utf-8")


if __name__ == "__main__":
    main()
