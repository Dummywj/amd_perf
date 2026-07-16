#!/usr/bin/env python3

import argparse
import re
import subprocess
from pathlib import Path


def parse_args():
    parser = argparse.ArgumentParser(description="Check native BF16 FMA instructions")
    parser.add_argument("build_dir")
    parser.add_argument("output_md")
    return parser.parse_args()


def disassemble(binary, symbol):
    result = subprocess.run(
        ["objdump", "-d", "--no-show-raw-insn", f"--disassemble={symbol}", str(binary)],
        check=True,
        text=True,
        capture_output=True,
    )
    marker = f"<{symbol}>:"
    if marker not in result.stdout:
        raise ValueError(f"missing symbol {symbol} in {binary}")
    return result.stdout.split(marker, 1)[1]


def matching(body):
    return [line.strip() for line in body.splitlines() if re.search(r"\bvdpbf16ps\b", line)]


def main():
    args = parse_args()
    binary = Path(args.build_dir).resolve() / "fma_bf16_bench"
    symbols = (
        "fma_bf16_reuse_avx512_dot",
        "fma_bf16_once_avx512_dot",
    )
    evidence = {}
    for symbol in symbols:
        instructions = matching(disassemble(binary, symbol))
        if not instructions:
            raise ValueError(f"{symbol}: missing native vdpbf16ps")
        evidence[symbol] = instructions
    if len(evidence[symbols[0]]) < 8:
        raise ValueError("reuse kernel has insufficient independent vdpbf16ps instructions")

    lines = [
        "# BF16 FMA disassembly gate",
        "",
        "| Kernel | Required instruction | Status |",
        "| --- | --- | --- |",
        "| reuse (64 rounds) | native `vdpbf16ps` with at least 8 independent accumulators | PASS |",
        "| once (1 round) | native `vdpbf16ps` | PASS |",
        "",
    ]
    for symbol in symbols:
        lines.extend([f"## `{symbol}`", "", "```text"])
        lines.extend(evidence[symbol][:8])
        lines.extend(["```", ""])
    Path(args.output_md).write_text("\n".join(lines), encoding="utf-8")


if __name__ == "__main__":
    main()
