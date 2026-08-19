#!/usr/bin/env python3
"""Refresh hashes in an XSAI run metadata file."""

from __future__ import annotations

import argparse
import hashlib
import os
import tempfile
from pathlib import Path


RESULT_ARTIFACTS = {
    "rtl_log_sha256": "rtl.log",
    "summary_csv_sha256": "summary.csv",
    "profile_summary_csv_sha256": "profile_summary.csv",
    "result_metadata_sha256": "result_metadata.json",
}
BUILD_ARTIFACTS = {
    "binary_sha256": "xsai-kernel-bench-riscv64-xs.bin",
    "elf_sha256": "xsai-kernel-bench-riscv64-xs.elf",
    "disassembly_sha256": "xsai-kernel-bench-riscv64-xs.txt",
}


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as file:
        for block in iter(lambda: file.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def refreshed_metadata(
    existing: str, result_dir: Path, build_dir: Path
) -> str:
    artifacts = {
        **{key: result_dir / name for key, name in RESULT_ARTIFACTS.items()},
        **{key: build_dir / name for key, name in BUILD_ARTIFACTS.items()},
    }
    missing_required = [
        str(path)
        for key, path in artifacts.items()
        if key in RESULT_ARTIFACTS and not path.is_file()
    ]
    if missing_required:
        raise FileNotFoundError(
            "missing required result artifacts: " + ", ".join(missing_required)
        )

    hash_keys = set(artifacts)
    lines = [
        line
        for line in existing.splitlines()
        if line.partition("=")[0] not in hash_keys
    ]
    lines.extend(
        f"{key}={file_sha256(path)}"
        for key, path in artifacts.items()
        if path.is_file()
    )
    return "\n".join(lines) + "\n"


def refresh_file(metadata: Path, result_dir: Path, build_dir: Path) -> None:
    existing = metadata.read_text(encoding="utf-8")
    content = refreshed_metadata(existing, result_dir, build_dir)
    metadata.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{metadata.name}.", dir=metadata.parent, text=True
    )
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as file:
            file.write(content)
        os.replace(temporary_name, metadata)
    except BaseException:
        Path(temporary_name).unlink(missing_ok=True)
        raise


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--metadata", required=True, type=Path)
    parser.add_argument("--result-dir", required=True, type=Path)
    parser.add_argument("--build-dir", required=True, type=Path)
    args = parser.parse_args()
    refresh_file(args.metadata, args.result_dir, args.build_dir)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
