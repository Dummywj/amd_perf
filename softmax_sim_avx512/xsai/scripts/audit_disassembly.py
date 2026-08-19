#!/usr/bin/env python3
"""Reject CUTE/matrix instructions and confirm the RVV kernels are present."""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path


KERNEL_SYMBOLS = (
    "fma_throughput_rvv_f32",
    "fma_latency_rvv_f32",
    "axpy_rvv_f32",
    "vector_copy_rvv_f32",
    "vector_triad_rvv_f32",
    "pointer_agu_rvv_f32",
    "dot_product_rvv_f32",
    "vector_reduction_rvv_f32",
    "conversion_rvv_f32",
    "vector_integer_rvv_f32",
    "mixed_compute_rvv_f32",
    "softmax_rvv_f32",
)

MICROBENCH_SYMBOLS = (
    "xsai_mb_loop_baseline",
    "xsai_mb_scalar_alu_dependency",
    "xsai_mb_scalar_alu_throughput",
    "xsai_mb_scalar_fp_add_dependency",
    "xsai_mb_scalar_fp_add_throughput",
    "xsai_mb_scalar_fp_div_dependency",
    "xsai_mb_vset_throughput",
    "xsai_mb_fma_dependency",
    "xsai_mb_fma_throughput",
    "xsai_mb_fp_add_dependency",
    "xsai_mb_fp_add_throughput",
    "xsai_mb_fp_add_same_vd",
    "xsai_mb_integer_dependency",
    "xsai_mb_integer_throughput",
    "xsai_mb_integer_same_vd",
    "xsai_mb_conversion_dependency",
    "xsai_mb_conversion_throughput",
    "xsai_mb_conversion_same_vd",
    "xsai_mb_conversion_integer",
    "xsai_mb_fma_integer",
    "xsai_mb_conversion_fma_integer",
    "xsai_mb_reduction_sum_dependency",
    "xsai_mb_reduction_sum_throughput",
    "xsai_mb_reduction_max_dependency",
    "xsai_mb_reduction_max_throughput",
    "xsai_mb_fma_scalar_dependency",
    "xsai_mb_fma_scalar_throughput",
    "xsai_mb_fp_broadcast_throughput",
    "xsai_mb_integer_scalar_throughput",
    "xsai_mb_immediate_broadcast_throughput",
    "xsai_mb_load_throughput",
    "xsai_mb_load_stream_throughput",
    "xsai_mb_load_same_vd",
    "xsai_mb_load_use",
    "xsai_mb_load_alu_dependency",
    "xsai_mb_load_fma_dependency",
    "xsai_mb_store_throughput",
    "xsai_mb_store_stream_throughput",
    "xsai_mb_load_fma_iteration",
    "xsai_mb_load_fma_store_iteration",
    "xsai_mb_vset_rd_dependency",
)

MATRIX_MNEMONIC = re.compile(
    r"\b(?:msetcfg|msettile[mkni]*|m(?:la|lb|lc|sa|sb|sc)(?:e\d+|\.whole)?|"
    r"m(?:f)?macc(?:\.[a-z0-9.]+)?|msync(?:reg)?reset|macquire|mrelease)\b",
    re.IGNORECASE,
)
VECTOR_MNEMONIC = re.compile(r"\b(?:vsetvli|vle32\.v|vse32\.v|vfmacc\.)")

INDEPENDENT_FMA_CHAINS = {
    "xsai_mb_fma_throughput": ("vv", 16),
    "xsai_mb_fma_integer": ("vv", 8),
    "xsai_mb_fma_scalar_throughput": ("vf", 16),
}

SAME_VD_STREAMS = {
    "xsai_mb_fp_add_same_vd": (
        r"vfadd\.vv",
        r"\bvfadd\.vv\s+v0\s*,\s*v16\s*,\s*v17\b",
        16,
    ),
    "xsai_mb_integer_same_vd": (
        r"vadd\.vv",
        r"\bvadd\.vv\s+v0\s*,\s*v16\s*,\s*v17\b",
        16,
    ),
    "xsai_mb_conversion_same_vd": (
        r"vfcvt\.rtz\.x\.f\.v",
        r"\bvfcvt\.rtz\.x\.f\.v\s+v0\s*,\s*v16\b",
        16,
    ),
}

MEMORY_STREAMS = {
    "xsai_mb_load_stream_throughput": ("vle32.v", "a0", 16),
    "xsai_mb_store_stream_throughput": ("vse32.v", "a1", 1),
}

ORDINARY_VD_MEMORY_CHAINS = {
    "xsai_mb_load_same_vd": (
        (r"\bvle32\.v\s+v8\s*,\s*\(a0\)", 16),
        (r"\bvse32\.v\s+v8\s*,\s*\(a1\)", 1),
    ),
    "xsai_mb_load_alu_dependency": (
        (r"\bvle32\.v\s+v8\s*,\s*\(a0\)", 8),
        (r"\bvadd\.vv\s+v8\s*,\s*v8\s*,\s*v16\b", 8),
    ),
    "xsai_mb_load_fma_dependency": (
        (r"\bvle32\.v\s+v8\s*,\s*\(a0\)", 8),
        (r"\bvfmacc\.vv\s+v8\s*,\s*v16\s*,\s*v17\b", 8),
    ),
    "xsai_mb_load_fma_iteration": (
        (r"\bvle32\.v\s+v8\s*,\s*\(a0\)", 1),
        (r"\bvfmacc\.vv\s+v8\s*,\s*v16\s*,\s*v17\b", 1),
    ),
    "xsai_mb_load_fma_store_iteration": (
        (r"\bvle32\.v\s+v8\s*,\s*\(a0\)", 1),
        (r"\bvfmacc\.vv\s+v8\s*,\s*v16\s*,\s*v17\b", 1),
        (r"\bvse32\.v\s+v8\s*,\s*\(a1\)", 1),
    ),
}


def symbol_body(text: str, symbol: str) -> str:
    match = re.search(
        rf"^\s*[0-9a-f]+\s+<{re.escape(symbol)}>:\s*$"
        rf"(?P<body>.*?)(?=^\s*[0-9a-f]+\s+<[^>]+>:\s*$|\Z)",
        text,
        re.IGNORECASE | re.MULTILINE | re.DOTALL,
    )
    return match.group("body") if match else ""


def independent_fma_chain_counts(text: str) -> dict[str, int]:
    result: dict[str, int] = {}
    for symbol, (form, _) in INDEPENDENT_FMA_CHAINS.items():
        destinations = {
            int(match.group(1))
            for match in re.finditer(
                rf"\bvfmacc\.{form}\s+v([0-9]|[12][0-9]|3[01])\s*,",
                symbol_body(text, symbol),
                re.IGNORECASE,
            )
        }
        result[symbol] = len(destinations)
    return result


def same_vd_stream_counts(text: str) -> dict[str, dict[str, int]]:
    result = {}
    for symbol, (mnemonic, exact_pattern, required) in SAME_VD_STREAMS.items():
        body = symbol_body(text, symbol)
        result[symbol] = {
            "found": len(re.findall(rf"\b{mnemonic}\b", body, re.IGNORECASE)),
            "exact": len(re.findall(exact_pattern, body, re.IGNORECASE)),
            "required": required,
        }
    return result


def memory_stream_counts(text: str) -> dict[str, dict[str, int]]:
    result = {}
    for symbol, (
        mnemonic,
        base,
        required_unique_destinations,
    ) in MEMORY_STREAMS.items():
        body = symbol_body(text, symbol)
        mnemonic_pattern = re.escape(mnemonic)
        operands = re.findall(
            rf"\b{mnemonic_pattern}\s+v([0-9]|[12][0-9]|3[01])\s*,\s*\(t1\)",
            body,
            re.IGNORECASE,
        )
        result[symbol] = {
            "found": len(
                re.findall(rf"\b{mnemonic_pattern}\b", body, re.IGNORECASE)
            ),
            "exact": len(operands),
            "unique_vector_registers": len(set(operands)),
            "required_unique_vector_registers": required_unique_destinations,
            "base_setup": len(
                re.findall(
                    rf"\badd\s+t1\s*,\s*{base}\s*,\s*t0\b",
                    body,
                    re.IGNORECASE,
                )
            ),
            "pointer_steps": len(
                re.findall(
                    r"\baddi\s+t1\s*,\s*t1\s*,\s*16\b",
                    body,
                    re.IGNORECASE,
                )
            ),
            "offset_steps": len(
                re.findall(
                    r"\baddi\s+t0\s*,\s*t0\s*,\s*256\b",
                    body,
                    re.IGNORECASE,
                )
            ),
            "mask_initializers": len(
                re.findall(
                    r"\bli\s+t2\s*,\s*2047\b",
                    body,
                    re.IGNORECASE,
                )
            ),
            "wrap_masks": len(
                re.findall(
                    r"\band\s+t0\s*,\s*t0\s*,\s*t2\b",
                    body,
                    re.IGNORECASE,
                )
            ),
            "required": 16,
        }
    return result


def ordinary_vd_memory_chain_counts(
    text: str,
) -> dict[str, list[dict[str, int]]]:
    return {
        symbol: [
            {
                "found": len(re.findall(pattern, symbol_body(text, symbol), re.IGNORECASE)),
                "required": required,
            }
            for pattern, required in patterns
        ]
        for symbol, patterns in ORDINARY_VD_MEMORY_CHAINS.items()
    }


def audit(text: str) -> dict[str, object]:
    forbidden = sorted(set(match.group(0) for match in MATRIX_MNEMONIC.finditer(text)))
    missing_symbols = [
        symbol
        for symbol in (*KERNEL_SYMBOLS, *MICROBENCH_SYMBOLS)
        if f"<{symbol}>:" not in text
    ]
    vector_instruction_count = len(VECTOR_MNEMONIC.findall(text))
    chain_counts = independent_fma_chain_counts(text)
    insufficient_chains = {
        symbol: {"found": chain_counts[symbol], "required": required}
        for symbol, (_, required) in INDEPENDENT_FMA_CHAINS.items()
        if chain_counts[symbol] < required
    }
    same_vd_counts = same_vd_stream_counts(text)
    invalid_same_vd = {
        symbol: counts
        for symbol, counts in same_vd_counts.items()
        if counts["found"] != counts["required"]
        or counts["exact"] != counts["required"]
    }
    memory_counts = memory_stream_counts(text)
    invalid_memory_streams = {
        symbol: counts
        for symbol, counts in memory_counts.items()
        if counts["found"] != counts["required"]
        or counts["exact"] != counts["required"]
        or counts["unique_vector_registers"]
        != counts["required_unique_vector_registers"]
        or counts["base_setup"] != 1
        or counts["pointer_steps"] != 15
        or counts["offset_steps"] != 1
        or counts["mask_initializers"] != 1
        or counts["wrap_masks"] != 1
    }
    ordinary_vd_counts = ordinary_vd_memory_chain_counts(text)
    invalid_ordinary_vd = {
        symbol: counts
        for symbol, counts in ordinary_vd_counts.items()
        if any(entry["found"] != entry["required"] for entry in counts)
    }
    return {
        "status": "PASS"
        if (
            not forbidden
            and not missing_symbols
            and vector_instruction_count > 0
            and not insufficient_chains
            and not invalid_same_vd
            and not invalid_memory_streams
            and not invalid_ordinary_vd
        )
        else "FAIL",
        "matrix_mnemonics": forbidden,
        "missing_kernel_symbols": missing_symbols,
        "vector_instruction_count": vector_instruction_count,
        "independent_fma_chains": chain_counts,
        "insufficient_fma_chains": insufficient_chains,
        "same_vd_streams": same_vd_counts,
        "invalid_same_vd_streams": invalid_same_vd,
        "memory_streams": memory_counts,
        "invalid_memory_streams": invalid_memory_streams,
        "ordinary_vd_memory_chains": ordinary_vd_counts,
        "invalid_ordinary_vd_memory_chains": invalid_ordinary_vd,
        "target_isa": "rv64gcv_zvl128b",
        "cute_compiler_extension_enabled": False,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--disassembly", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()

    result = audit(args.disassembly.read_text(encoding="utf-8"))
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    if result["status"] != "PASS":
        raise SystemExit(f"instruction audit failed: {result}")
    print(
        "Instruction audit passed: "
        f"{result['vector_instruction_count']} RVV markers, no CUTE mnemonic."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
