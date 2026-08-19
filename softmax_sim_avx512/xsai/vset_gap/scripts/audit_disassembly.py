#!/usr/bin/env python3
"""Audit the standalone vset-gap image and its intended instruction forms."""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path


SYMBOLS = (
    "xsai_vg_regular_lfs",
    "xsai_vg_keep_vl_lfs",
    "xsai_vg_vlmax_lfs",
    "xsai_vg_outside_lfs",
    "xsai_vg_regular_load",
    "xsai_vg_outside_load",
    "xsai_vg_load_stream_1",
    "xsai_vg_load_stream_2",
    "xsai_vg_load_stream_4",
    "xsai_vg_aligned_load_stream_2",
    "xsai_vg_aligned_load_stream_4",
    "xsai_vg_regular_compute",
    "xsai_vg_regular_store",
)

EXPECTED_VSET_FORMS = {
    "xsai_vg_regular_lfs": (("t0", "zero"), ("t0", "a4")),
    "xsai_vg_keep_vl_lfs": (("t0", "zero"), ("zero", "zero")),
    "xsai_vg_vlmax_lfs": (("t0", "zero"), ("t0", "zero")),
    "xsai_vg_outside_lfs": (("t0", "zero"),),
    "xsai_vg_regular_load": (("t0", "zero"), ("t0", "a4")),
    "xsai_vg_outside_load": (("t0", "zero"),),
    "xsai_vg_load_stream_1": (("t0", "zero"), ("t0", "a4")),
    "xsai_vg_load_stream_2": (("t0", "zero"), ("t0", "a5")),
    "xsai_vg_load_stream_4": (("t0", "zero"), ("t0", "t2")),
    "xsai_vg_aligned_load_stream_2": (("t0", "zero"), ("t0", "a5")),
    "xsai_vg_aligned_load_stream_4": (("t0", "zero"), ("t0", "t2")),
    "xsai_vg_regular_compute": (("t0", "zero"), ("t0", "a4")),
    "xsai_vg_regular_store": (("t0", "zero"), ("t0", "a4")),
}

EXPECTED_VECTOR_COUNTS = {
    "xsai_vg_regular_lfs": (3, 1, 1),
    "xsai_vg_keep_vl_lfs": (3, 1, 1),
    "xsai_vg_vlmax_lfs": (3, 1, 1),
    "xsai_vg_outside_lfs": (3, 1, 1),
    "xsai_vg_regular_load": (1, 0, 1),
    "xsai_vg_outside_load": (1, 0, 1),
    "xsai_vg_load_stream_1": (1, 0, 1),
    "xsai_vg_load_stream_2": (2, 0, 2),
    "xsai_vg_load_stream_4": (4, 0, 4),
    "xsai_vg_aligned_load_stream_2": (2, 0, 2),
    "xsai_vg_aligned_load_stream_4": (4, 0, 4),
    "xsai_vg_regular_compute": (3, 1, 1),
    "xsai_vg_regular_store": (1, 0, 1),
}

EXPECTED_LOAD_DESTS = {
    "xsai_vg_load_stream_1": {"v8"},
    "xsai_vg_load_stream_2": {"v8", "v9"},
    "xsai_vg_load_stream_4": {"v8", "v9", "v10", "v11"},
    "xsai_vg_aligned_load_stream_2": {"v8", "v9"},
    "xsai_vg_aligned_load_stream_4": {"v8", "v9", "v10", "v11"},
}

EXPECTED_LOAD_BASES = {
    "xsai_vg_aligned_load_stream_2": {"a0", "a3"},
    "xsai_vg_aligned_load_stream_4": {"a0", "a3", "a4", "a5"},
}


def has_aligned_stream_setup(body: str, streams: int) -> bool:
    patterns = [
        r"\bslli\s+t1\s*,\s*a2\s*,\s*(?:0x)?4\b",
        r"\badd\s+a3\s*,\s*a0\s*,\s*t1\b",
    ]
    if streams == 4:
        patterns.extend(
            (
                r"\badd\s+a4\s*,\s*a3\s*,\s*t1\b",
                r"\badd\s+a5\s*,\s*a4\s*,\s*t1\b",
            )
        )
    return all(re.search(pattern, body, re.IGNORECASE) for pattern in patterns)

MATRIX_MNEMONIC = re.compile(
    r"\b(?:msetcfg|msettile[mkni]*|m(?:la|lb|lc|sa|sb|sc)(?:e\d+|\.whole)?|"
    r"m(?:f)?macc(?:\.[a-z0-9.]+)?|msync(?:reg)?reset|macquire|mrelease)\b",
    re.IGNORECASE,
)


def symbol_body(text: str, symbol: str) -> str:
    match = re.search(
        rf"^\s*[0-9a-f]+\s+<{re.escape(symbol)}>:\s*$"
        rf"(?P<body>.*?)(?=^\s*[0-9a-f]+\s+<[^>]+>:\s*$|\Z)",
        text,
        re.IGNORECASE | re.MULTILINE | re.DOTALL,
    )
    return match.group("body") if match else ""


def vset_forms(body: str) -> tuple[tuple[str, str], ...]:
    return tuple(
        (match.group(1), match.group(2))
        for match in re.finditer(
            r"\bvsetvli\s+([^,\s]+)\s*,\s*([^,\s]+)", body, re.IGNORECASE
        )
    )


def audit(text: str) -> dict[str, object]:
    missing = [symbol for symbol in SYMBOLS if not symbol_body(text, symbol)]
    forbidden = sorted(set(MATRIX_MNEMONIC.findall(text)))
    cases: dict[str, dict[str, object]] = {}
    failed = []
    for symbol in SYMBOLS:
        body = symbol_body(text, symbol)
        vector_counts = (
            len(re.findall(r"\bvle32\.v\b", body, re.IGNORECASE)),
            len(re.findall(r"\bvfmacc\.vv\b", body, re.IGNORECASE)),
            len(re.findall(r"\bvse32\.v\b", body, re.IGNORECASE)),
        )
        forms = vset_forms(body)
        uses_v0 = bool(re.search(r"\bv0\b", body))
        load_dests = set(
            re.findall(r"\bvle32\.v\s+(v\d+)\b", body, re.IGNORECASE)
        )
        load_bases = set(
            re.findall(r"\bvle32\.v\s+v\d+\s*,?\s*\((\w+)\)", body, re.IGNORECASE)
        )
        expected_bases = EXPECTED_LOAD_BASES.get(symbol)
        aligned_setup = (
            expected_bases is None
            or has_aligned_stream_setup(body, len(expected_bases))
        )
        scalar_vl_consumers = len(
            re.findall(r"\b(?:slli\s+t1\s*,\s*t0|sub\s+a4\s*,\s*a4\s*,\s*t0)", body)
        )
        passed = (
            forms == EXPECTED_VSET_FORMS[symbol]
            and vector_counts == EXPECTED_VECTOR_COUNTS[symbol]
            and not uses_v0
            and scalar_vl_consumers >= 1
            and load_dests >= EXPECTED_LOAD_DESTS.get(symbol, set())
            and (expected_bases is None or load_bases == expected_bases)
            and aligned_setup
        )
        cases[symbol] = {
            "status": "PASS" if passed else "FAIL",
            "vset_forms": forms,
            "vector_counts": vector_counts,
            "uses_v0": uses_v0,
            "scalar_vl_consumers": scalar_vl_consumers,
            "load_bases": sorted(load_bases),
            "aligned_stream_setup": aligned_setup,
        }
        if not passed:
            failed.append(symbol)
    status = "PASS" if not missing and not forbidden and not failed else "FAIL"
    return {
        "status": status,
        "missing_symbols": missing,
        "forbidden_matrix_mnemonics": forbidden,
        "failed_cases": failed,
        "cases": cases,
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
        raise SystemExit("vset-gap disassembly audit failed")
    print("vset-gap disassembly audit passed: 13 cases, aligned streams verified, no CUTE.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
