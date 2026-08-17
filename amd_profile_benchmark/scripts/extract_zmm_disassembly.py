#!/usr/bin/env python3

import re
import sys
from pathlib import Path


TARGETS = (
    "RunZmmFmaThroughput",
    "RunZmmIntegerThroughput",
    "RunZmmTruncateConvertThroughput",
    "RunZmmConvertIntegerMix",
    "RunZmmFmaIntegerMix",
    "RunZmmConvertFmaIntegerMix",
)
HEADER = re.compile(r"^[0-9a-fA-F]+ <(.+)>:$")


def main() -> int:
    source = Path(sys.argv[1])
    output = Path(sys.argv[2])
    blocks = {target: [] for target in TARGETS}
    active = None
    for line in source.read_text(encoding="utf-8").splitlines():
        match = HEADER.match(line)
        if match:
            active = next(
                (target for target in TARGETS if target in match.group(1)), None
            )
        if active is not None:
            blocks[active].append(line)

    missing = [target for target, lines in blocks.items() if not lines]
    if missing:
        raise SystemExit("missing disassembly targets: " + ", ".join(missing))

    lines = [
        "# Focused ZMM benchmark disassembly",
        "# Generated from the full objdump by extract_zmm_disassembly.py.",
        "",
    ]
    for target in TARGETS:
        block = blocks[target]
        while block and not block[-1].strip():
            block.pop()
        lines.extend(block)
        if target != TARGETS[-1]:
            lines.append("")
    output.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
