#!/usr/bin/env python3
"""Check the small set of acceptance markers emitted by an RTL run."""

from __future__ import annotations

import argparse
import re
from pathlib import Path


_GOOD_TRAP = re.compile(r"\bHIT\s+GOOD\s+TRAP\b", re.IGNORECASE)
_BAD_TRAP = re.compile(r"\bHIT\s+BAD\s+TRAP\b", re.IGNORECASE)
_ABORT = re.compile(r"\bABORT\b", re.IGNORECASE)
_ANSI_ESCAPE = re.compile(r"\x1b\[[0-?]*[ -/]*[@-~]")
# Keep this line-oriented: an unrelated counter named ras_top_mismatch must
# not be mistaken for a difftest failure.
_DIFFTEST_FAILURE = re.compile(
    r"\bdifftest\b[^\r\n]*(?:\bmismatch\b|\bfail(?:ed|ure|ures)?\b)",
    re.IGNORECASE,
)


def check_log(text: str) -> list[str]:
    """Return acceptance-rule violations, or an empty list for a valid log."""
    text = _ANSI_ESCAPE.sub("", text)
    errors: list[str] = []
    if not _GOOD_TRAP.search(text):
        errors.append("missing HIT GOOD TRAP")
    if _BAD_TRAP.search(text):
        errors.append("HIT BAD TRAP")
    if _ABORT.search(text):
        errors.append("ABORT")
    if _DIFFTEST_FAILURE.search(text):
        errors.append("explicit difftest mismatch/fail")
    return errors


def validate_log(text: str) -> None:
    """Raise ``ValueError`` when *text* does not satisfy RTL acceptance."""
    errors = check_log(text)
    if errors:
        raise ValueError("RTL log acceptance failed: " + ", ".join(errors))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--log", type=Path, required=True, help="RTL log to check")
    args = parser.parse_args(argv)
    try:
        validate_log(args.log.read_text())
    except (OSError, ValueError) as error:
        parser.error(str(error))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
