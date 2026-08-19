#!/usr/bin/env python3
"""Verify XSAI HPM IDs against the pinned source and elaborated RTL."""

import argparse
import json
import re
import subprocess
from pathlib import Path


EXPECTED_XSAI_COMMIT = "04909692a1cdc6b9165b95c7ea83b94bdc01ab39"
MACHINE_ONLY_INHIBIT = sum(1 << bit for bit in (58, 59, 60, 61))
ADD = 4

EVENTS = {
    "cute_active_cycles": {
        "counter": 11,
        "domain": "backend",
        "ids": [105],
    },
    "cute_retired": {
        "counter": 12,
        "domain": "backend",
        "ids": [106],
    },
    "l1d_load_misses": {
        "counter": 19,
        "domain": "memblock",
        "ids": [7, 16, 25],
    },
    "dtlb_load_misses": {
        "counter": 20,
        "domain": "memblock",
        "ids": [5, 14, 23],
    },
    "cute_memory_requests": {
        "counter": 21,
        "domain": "memblock",
        "ids": [153, 154],
    },
}

BACKEND_CONNECTIONS = {
    105: "io_perf_perfEventsMatrixBackend_0_value",
    106: "io_perf_perfEventsMatrixBackend_1_value",
}

MEMBLOCK_CONNECTIONS = {
    5: "_inner_LoadUnit_0_io_perf_4_value",
    7: "_inner_LoadUnit_0_io_perf_6_value",
    14: "_inner_LoadUnit_1_io_perf_4_value",
    16: "_inner_LoadUnit_1_io_perf_6_value",
    23: "_inner_LoadUnit_2_io_perf_4_value",
    25: "_inner_LoadUnit_2_io_perf_6_value",
    153: "io_outer_matrixPerfEvents_8_value",
    154: "io_outer_matrixPerfEvents_9_value",
}


class MappingError(RuntimeError):
    pass


def encode_events(ids):
    padded = list(ids) + [0] * (4 - len(ids))
    value = MACHINE_ONLY_INHIBIT
    for index, event_id in enumerate(padded[:4]):
        value |= event_id << (10 * index)
    if len(ids) > 1:
        value |= ADD << 40
        value |= ADD << 45
        value |= ADD << 50
    return value


def _require_connection(text, event_id, signal, file_name):
    pattern = re.compile(
        rf"\.io_events_sets_{event_id}_value\s*\(\s*"
        rf"{re.escape(signal)}\s*\)"
    )
    if not pattern.search(text):
        raise MappingError(
            f"{file_name}: event {event_id} no longer maps to {signal}"
        )


def verify_rtl(backend_text, memblock_text):
    for event_id, signal in BACKEND_CONNECTIONS.items():
        _require_connection(backend_text, event_id, signal, "Backend.sv")
    for event_id, signal in MEMBLOCK_CONNECTIONS.items():
        _require_connection(memblock_text, event_id, signal, "MemBlock.sv")


def verify_source(xsai_root):
    backend = (
        xsai_root / "src/main/scala/xiangshan/backend/Backend.scala"
    ).read_text()
    memblock = (
        xsai_root / "src/main/scala/xiangshan/mem/MemBlock.scala"
    ).read_text()
    load_unit = (
        xsai_root / "src/main/scala/xiangshan/mem/pipeline/LoadUnit.scala"
    ).read_text()
    hardware_hpm = (
        xsai_root / "utility/src/main/scala/utility/HardwarePerfMonitor.scala"
    ).read_text()

    required = {
        "Backend.scala": ["amu_active_cycle", "amu_retire"],
        "MemBlock.scala": ["amu_mem_rd_req", "amu_mem_wr_req"],
        "LoadUnit.scala": ["load_s1_tlb_miss", "load_s2_dcache_miss"],
        "HardwarePerfMonitor.scala": [
            "io.hpm_event( 9,  0)",
            "io.hpm_event(19, 10)",
            "io.hpm_event(29, 20)",
            "io.hpm_event(39, 30)",
        ],
    }
    texts = {
        "Backend.scala": backend,
        "MemBlock.scala": memblock,
        "LoadUnit.scala": load_unit,
        "HardwarePerfMonitor.scala": hardware_hpm,
    }
    for name, needles in required.items():
        for needle in needles:
            if needle not in texts[name]:
                raise MappingError(f"{name}: missing source evidence {needle!r}")


def verify(xsai_root, rtl_dir):
    commit = subprocess.run(
        ["git", "-C", str(xsai_root), "rev-parse", "HEAD"],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    if commit != EXPECTED_XSAI_COMMIT:
        raise MappingError(
            f"XSAI commit drift: expected {EXPECTED_XSAI_COMMIT}, got {commit}"
        )

    verify_source(xsai_root)
    backend_path = rtl_dir / "Backend.sv"
    memblock_path = rtl_dir / "MemBlock.sv"
    verify_rtl(backend_path.read_text(), memblock_path.read_text())

    return {
        "status": "PASS",
        "xsai_commit": commit,
        "config": "DefaultMatrixConfig",
        "rtl": {
            "backend": str(backend_path),
            "memblock": str(memblock_path),
        },
        "events": {
            name: {**event, "selector": f"0x{encode_events(event['ids']):016x}"}
            for name, event in EVENTS.items()
        },
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--xsai-root", type=Path, required=True)
    parser.add_argument("--rtl-dir", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    try:
        result = verify(args.xsai_root.resolve(), args.rtl_dir.resolve())
    except (MappingError, OSError, subprocess.CalledProcessError) as error:
        raise SystemExit(f"HPM event-map audit failed: {error}") from error
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2) + "\n")
    print(f"HPM event-map audit passed: {args.output}")


if __name__ == "__main__":
    main()
