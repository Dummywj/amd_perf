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
    "xsai_vg_regular_compute",
    "xsai_vg_regular_store",
)

EXPECTED_VSET_FORMS = {
    "xsai_vg_regular_lfs": (("t0", "zero"), ("t0", "a4")),
    "xsai_vg_keep_vl_lfs": (("t0", "zero"), ("zero", "zero")),
    "xsai_vg_vlmax_lfs": (("t0", "zero"), ("t0", "zero")),
    "xsai_vg_outside_lfs": (("t0", "zero"),),
    "xsai_vg_regular_load": (("t0", "zero"), ("t0", "a4")),
    "xsai_vg_regular_compute": (("t0", "zero"), ("t0", "a4")),
    "xsai_vg_regular_store": (("t0", "zero"), ("t0", "a4")),
}

EXPECTED_VECTOR_COUNTS = {
    "xsai_vg_regular_lfs": (3, 1, 1),
    "xsai_vg_keep_vl_lfs": (3, 1, 1),
    "xsai_vg_vlmax_lfs": (3, 1, 1),
    "xsai_vg_outside_lfs": (3, 1, 1),
    "xsai_vg_regular_load": (1, 0, 1),
    "xsai_vg_regular_compute": (3, 1, 1),
    "xsai_vg_regular_store": (1, 0, 1),
}

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
        scalar_vl_consumers = len(
            re.findall(r"\b(?:slli\s+t1\s*,\s*t0|sub\s+a4\s*,\s*a4\s*,\s*t0)", body)
        )
        passed = (
            forms == EXPECTED_VSET_FORMS[symbol]
            and vector_counts == EXPECTED_VECTOR_COUNTS[symbol]
            and not uses_v0
            and scalar_vl_consumers >= 1
        )
        cases[symbol] = {
            "status": "PASS" if passed else "FAIL",
            "vset_forms": forms,
            "vector_counts": vector_counts,
            "uses_v0": uses_v0,
            "scalar_vl_consumers": scalar_vl_consumers,
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
    print("vset-gap disassembly audit passed: 7 cases, ordinary vector registers, no CUTE.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
