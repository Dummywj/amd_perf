#!/usr/bin/env python3

import argparse
import hashlib
import json
import re
import statistics
import subprocess
from collections import defaultdict
from pathlib import Path

from ops_report import DENSE_SIZES, indexed_simd_name, load_cases, validate_dense_cases


EXPECTED = {
    "reduce": (4, 452, 3164),
    "gather": (9, 1017, 7119),
    "scatter": (9, 1017, 7119),
    "softmax": (2, 226, 1582),
}
ANCHORS = (1 << 10, 1 << 18, 1 << 26)


def parse_args():
    parser = argparse.ArgumentParser(description="Build and validate a dense exploratory report")
    parser.add_argument("output_dir")
    return parser.parse_args()


def sha256(path):
    digest = hashlib.sha256()
    with Path(path).open("rb") as source:
        for block in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def git_revision(path):
    result = subprocess.run(
        ["git", "-C", str(path), "rev-parse", "HEAD"],
        check=True,
        text=True,
        capture_output=True,
    )
    return result.stdout.strip()


def fmt_duration(seconds):
    seconds = int(round(seconds))
    hours, remainder = divmod(seconds, 3600)
    minutes, seconds = divmod(remainder, 60)
    return f"{hours:02d}:{minutes:02d}:{seconds:02d}"


def warning_lines(title):
    return [
        f"# EXPLORATORY / NON-FORMAL - {title}",
        "",
        "**Newly collected dense exploratory data; the environment may be affected by external Java/ZGC activity and CPU contention.**",
        "",
        "**Relative trends only. Do not use for absolute performance, cross-machine comparisons, performance regression, capacity planning, hardware limits, or formal acceptance.**",
        "",
    ]


def build_pairs(all_cases):
    paired = {}
    for operation, cases in all_cases.items():
        for case in cases:
            paired.setdefault(
                (operation, case["variant"], case["elements"]), {}
            )[case["implementation"]] = case
    return paired


def pair_status(left, right):
    return "UNSTABLE" if left["elem_cycle"]["cv"] > 0.05 or right["elem_cycle"]["cv"] > 0.05 else "stable"


def write_commands(output_dir, metadata):
    relative_output = f"results/{output_dir.name}"
    lines = [
        "EXPLORATORY / NON-FORMAL - DENSE FP32 COMMAND RECORD",
        "Newly collected dense exploratory data; external Java/ZGC activity and CPU contention may affect the environment.",
        "Relative trends only; no absolute, cross-machine, regression, capacity, hardware-limit, or formal-acceptance conclusions.",
        "",
        "# Build and semantic gates",
        "cmake --build build-ops-release --target ops_fp32_correctness reduce_fp32_bench gather_fp32_bench scatter_fp32_bench softmax_fp32_bench -j 16",
        "python3 -m unittest -v scripts/test_ops_report.py",
        "python3 scripts/validate_dense_benchmark_list.py build-ops-release",
        "python3 scripts/check_ops_disassembly.py build-ops-release /tmp/dense_disassembly.md --dense-exploratory",
        "numactl --physcpubind=8 --membind=0 build-ops-release/ops_fp32_correctness /tmp/dense_correctness.md --dense-exploratory",
        f"cp /tmp/dense_correctness.md {relative_output}/correctness.md",
        f"cp /tmp/dense_disassembly.md {relative_output}/disassembly.md",
        f"scripts/collect_ops_environment.sh {relative_output}/environment.md 8 200 dense-exploratory",
        "",
        "# Dense benchmark commands actually executed",
    ]
    for operation in EXPECTED:
        lines.append(" ".join(metadata[operation]["command"]))
    lines.extend(["", "# Offline report commands"])
    for operation in EXPECTED:
        lines.append(
            f"python3 scripts/ops_report.py {relative_output}/{operation}_fp32.json {relative_output}/{operation}_fp32.md {relative_output}/{operation}_fp32.svg --exploratory --dense"
        )
    lines.extend(
        [
            f"python3 scripts/dense_summary.py {relative_output}",
            "",
            "# Explicitly skipped",
            "formal runtime gate: skipped for the approved exploratory dense run",
            "perf stat: skipped in exploratory dense mode",
            "CV > 5%: marked UNSTABLE without rerun",
            "No external process was modified or stopped.",
            "",
        ]
    )
    (output_dir / "commands.log").write_text("\n".join(lines), encoding="utf-8")


def write_perf_status(output_dir):
    lines = warning_lines("Dense PMU status")
    lines.extend(
        [
            "`perf stat: skipped in exploratory dense mode`.",
            "",
            "No PMU values were measured, estimated, copied from another batch, or filled with zero.",
            "",
        ]
    )
    perf_dir = output_dir / "perf-stat"
    perf_dir.mkdir(exist_ok=True)
    (perf_dir / "README.md").write_text("\n".join(lines), encoding="utf-8")


def selected_rows(paired):
    rows = []
    for n in ANCHORS:
        for operation, variants in (
            ("reduce", ("sum", "max")),
            ("softmax", ("softmax",)),
            ("gather", ("sequential", "stride17", "block_random_4k", "uniform_random")),
            ("scatter", ("sequential", "stride17", "block_random_4k", "uniform_random")),
        ):
            for variant in variants:
                implementations = paired[(operation, variant, n)]
                scalar = implementations["scalar"]
                simd_name = indexed_simd_name(operation, set(implementations))
                simd = implementations[simd_name]
                ratio = simd["elem_cycle"]["median"] / scalar["elem_cycle"]["median"]
                rows.append(
                    (
                        operation,
                        variant,
                        n,
                        f"scalar -> {simd_name}",
                        scalar,
                        simd,
                        ratio,
                        pair_status(scalar, simd),
                    )
                )
        for operation in ("gather", "scatter"):
            indexed_impls = paired[(operation, "sequential", n)]
            simd_name = indexed_simd_name(operation, set(indexed_impls))
            indexed = indexed_impls[simd_name]
            contiguous = paired[(operation, "contiguous", n)]["avx512_load_store"]
            ratio = contiguous["elem_cycle"]["median"] / indexed["elem_cycle"]["median"]
            rows.append(
                (
                    operation,
                    "contiguous",
                    n,
                    f"sequential {simd_name} -> load_store",
                    indexed,
                    contiguous,
                    ratio,
                    pair_status(indexed, contiguous),
                )
            )
    return rows


def ratio_ranges(paired):
    standard = defaultdict(list)
    contiguous = defaultdict(list)
    for (operation, variant, n), implementations in paired.items():
        if "scalar" in implementations:
            simd_name = indexed_simd_name(operation, set(implementations))
            simd = implementations[simd_name]
            scalar = implementations["scalar"]
            if pair_status(scalar, simd) == "stable":
                standard[operation].append(
                    simd["elem_cycle"]["median"] / scalar["elem_cycle"]["median"]
                )
        if variant == "contiguous":
            indexed_impls = paired[(operation, "sequential", n)]
            simd_name = indexed_simd_name(operation, set(indexed_impls))
            indexed = indexed_impls[simd_name]
            load_store = implementations["avx512_load_store"]
            if pair_status(indexed, load_store) == "stable":
                contiguous[operation].append(
                    load_store["elem_cycle"]["median"] / indexed["elem_cycle"]["median"]
                )
    return standard, contiguous


def write_summary(output_dir, contexts, all_cases, metadata, manifest):
    paired = build_pairs(all_cases)
    unstable = {
        operation: [case for case in cases if case["elem_cycle"]["cv"] > 0.05]
        for operation, cases in all_cases.items()
    }
    standard_ranges, contiguous_ranges = ratio_ranges(paired)
    lines = warning_lines("Dense FP32 operation summary")
    lines.extend(
        [
            "## Scope And Approval",
            "",
            "- Fourth supplemental approval date: 2026-07-14.",
            "- This is a newly collected dense exploratory batch; no case was reused, merged, selected, or copied from the three earlier diagnostic/sparse batches.",
            "- Binding: CPU 8 on NUMA node 0; SMT sibling CPU 200 was documented but no formal isolation/runtime gate was applied.",
            "- Seven randomized repetitions and 0.25-second minimum time were used for every case.",
            "- External Java/ZGC activity, swap, CPU contention, and CV did not stop this approved exploratory run.",
            "- `perf stat: skipped in exploratory dense mode`.",
            "",
            "## Completeness And Duration",
            "",
            "| Operation | Curves | Cases | Raw repetition rows | CV > 5% | Wall time |",
            "| --- | ---: | ---: | ---: | ---: | ---: |",
        ]
    )
    total_seconds = 0.0
    total_unstable = 0
    for operation in EXPECTED:
        curves, cases, rows = EXPECTED[operation]
        elapsed = metadata[operation]["elapsed_seconds"]
        total_seconds += elapsed
        total_unstable += len(unstable[operation])
        lines.append(
            f"| {operation} | {curves} | {cases} | {rows} | {len(unstable[operation])} | {fmt_duration(elapsed)} |"
        )
    lines.extend(
        [
            f"| **Total** | **24** | **2712** | **18984** | **{total_unstable}** | **{fmt_duration(total_seconds)}** |",
            "",
            "Every curve contains exactly the approved 113 unique N values. JSON SHA-256 hashes, run timestamps, command metadata, IDs, and logical-byte validation are recorded in `provenance.json` and `validation.md`.",
            "",
            "### Process Start Context",
            "",
            "| Operation | Start time | Load average (1/5/15 min) | CPU scaling |",
            "| --- | --- | --- | --- |",
        ]
    )
    for operation in EXPECTED:
        load = contexts[operation].get("load_avg", [])
        load_text = " / ".join(f"{value:.3f}" for value in load)
        lines.append(
            f"| {operation} | `{contexts[operation].get('date', '')}` | {load_text} | {'enabled' if contexts[operation].get('cpu_scaling_enabled') else 'disabled'} |"
        )
    lines.extend(
        [
            "",
            "## Size Formula And IDs",
            "",
            "`base={1024,1136,1248,1376,1520,1680,1856}`; generate `base[j] << octave` for octave 0..15 and j 0..6, then append `1 << 26`.",
            "",
            "The resulting 113 values are strictly increasing, unique, multiples of 16, coprime with 17, and contain every power-of-two anchor from 1K through 64M.",
            "",
            "- `implementation_id`: scalar=0, indexed AVX-512=1, contiguous AVX-512 load/store=2.",
            "- `pattern_id`: sequential/stride17/block_random_4k/uniform_random=0/1/2/3, contiguous=4; Reduce/Softmax use -1.",
            "",
            "## Workload Semantics",
            "",
            "- Reduce computes FP32 sum or max. Softmax uses stable max, SLEEF u10 exp+sum, and normalization phases.",
            "- Indexed Gather/Scatter always allocate and read a permutation index. Even sequential indexed SIMD is forced through `vgatherdps`/`vscatterdps` and uses a 12N logical-byte model.",
            "- Contiguous Gather/Scatter allocate no index and use explicit cached ZMM load/store with an 8N logical-byte model. It is a cached-copy control, not an equivalent third Gather/Scatter implementation.",
            "- Indexed patterns are identity, stride17 `(17*i) mod N`, deterministic 4K-block Fisher-Yates, and deterministic full-array Fisher-Yates.",
            "- Logical GB/s is derived from the frozen logical-byte model, not measured DRAM traffic. Indexed/contiguous ratios include both removal of the index stream and instruction-semantic changes.",
            "",
            "## Semantic Gates",
            "",
            "- Correctness: PASS for dense size structure, the five tail sizes plus nine original numerical anchors, and contiguous Gather/Scatter bitwise checks.",
            "- Disassembly: PASS. Indexed kernels contain `vgatherdps`/`vscatterdps`; contiguous kernels contain ordinary ZMM `vmovups` with masked tails and no gather/scatter or copy call; scalar timed math has no packed arithmetic body.",
            "",
            "## Selected Same-Batch Ratios",
            "",
            "Each row includes both endpoint CV values. `UNSTABLE` means at least one endpoint has CV > 5%; no case was rerun.",
            "",
            "| Operation | Variant | N | Comparison | Left elem/cycle (CV) | Right elem/cycle (CV) | Throughput ratio | Status |",
            "| --- | --- | ---: | --- | ---: | ---: | ---: | --- |",
        ]
    )
    for operation, variant, n, comparison, left, right, ratio, status in selected_rows(paired):
        lines.append(
            f"| {operation} | {variant} | {n} | {comparison} | "
            f"{left['elem_cycle']['median']:.6g} ({left['elem_cycle']['cv']:.2%}) | "
            f"{right['elem_cycle']['median']:.6g} ({right['elem_cycle']['cv']:.2%}) | "
            f"{ratio:.3f}x | {status} |"
        )
    lines.extend(["", "## Stable Ratio Ranges", ""])
    lines.append("Only pairs with both endpoint CV values <= 5% are included:")
    lines.append("")
    for operation in EXPECTED:
        values = standard_ranges.get(operation, [])
        if values:
            ratio_label = (
                "scalar/AVX-512"
                if operation in ("reduce", "softmax")
                else "scalar/indexed-SIMD"
            )
            lines.append(
                f"- {operation} {ratio_label}: median {statistics.median(values):.3f}x, range {min(values):.3f}x to {max(values):.3f}x across {len(values)} stable pairs."
            )
    for operation in ("gather", "scatter"):
        values = contiguous_ranges.get(operation, [])
        if values:
            lines.append(
                f"- {operation} contiguous/indexed-SIMD throughput ratio: median {statistics.median(values):.3f}x, range {min(values):.3f}x to {max(values):.3f}x across {len(values)} stable pairs."
            )
    def comparison(operation, variant, n):
        implementations = paired[(operation, variant, n)]
        scalar = implementations["scalar"]
        simd_name = indexed_simd_name(operation, set(implementations))
        simd = implementations[simd_name]
        ratio = simd["elem_cycle"]["median"] / scalar["elem_cycle"]["median"]
        return scalar, simd, ratio

    def ratio_text(operation, variant, n):
        scalar, simd, ratio = comparison(operation, variant, n)
        return (
            f"{ratio:.3f}x (scalar CV {scalar['elem_cycle']['cv']:.2%}; "
            f"SIMD CV {simd['elem_cycle']['cv']:.2%}; {pair_status(scalar, simd)})"
        )

    gather_indexed = paired[("gather", "sequential", 1 << 26)]["avx512_vgather"]
    gather_contiguous = paired[("gather", "contiguous", 1 << 26)]["avx512_load_store"]
    scatter_indexed = paired[("scatter", "sequential", 1 << 26)]["avx512_vscatter"]
    scatter_contiguous = paired[("scatter", "contiguous", 1 << 26)]["avx512_load_store"]
    lines.extend(
        [
            "",
            "## Conservative Same-Batch Observations",
            "",
            "All ratios below are descriptive medians from this exploratory batch and include both endpoint CV values:",
            "",
            f"- Reduce sum AVX-512/scalar changes from {ratio_text('reduce', 'sum', 1 << 10)} at 1K to {ratio_text('reduce', 'sum', 1 << 26)} at 64M; max changes from {ratio_text('reduce', 'max', 1 << 10)} to {ratio_text('reduce', 'max', 1 << 26)}.",
            f"- Softmax AVX-512/scalar changes from {ratio_text('softmax', 'softmax', 1 << 10)} at 1K to {ratio_text('softmax', 'softmax', 1 << 26)} at 64M.",
            f"- At 64M, Gather AVX-512/scalar is sequential {ratio_text('gather', 'sequential', 1 << 26)}, stride17 {ratio_text('gather', 'stride17', 1 << 26)}, block-random {ratio_text('gather', 'block_random_4k', 1 << 26)}, and uniform-random {ratio_text('gather', 'uniform_random', 1 << 26)}.",
            f"- At 64M, Scatter AVX-512/scalar is sequential {ratio_text('scatter', 'sequential', 1 << 26)}, stride17 {ratio_text('scatter', 'stride17', 1 << 26)}, block-random {ratio_text('scatter', 'block_random_4k', 1 << 26)}, and uniform-random {ratio_text('scatter', 'uniform_random', 1 << 26)}.",
            f"- At 64M, Gather contiguous/indexed-SIMD throughput ratio is {gather_contiguous['elem_cycle']['median'] / gather_indexed['elem_cycle']['median']:.3f}x (indexed CV {gather_indexed['elem_cycle']['cv']:.2%}; contiguous CV {gather_contiguous['elem_cycle']['cv']:.2%}; {pair_status(gather_indexed, gather_contiguous)}); Scatter is {scatter_contiguous['elem_cycle']['median'] / scatter_indexed['elem_cycle']['median']:.3f}x (indexed CV {scatter_indexed['elem_cycle']['cv']:.2%}; contiguous CV {scatter_contiguous['elem_cycle']['cv']:.2%}; {pair_status(scatter_indexed, scatter_contiguous)}). These ratios also remove the index stream and compare 8N versus 12N logical bytes.",
            f"- {total_unstable} of 2712 implementation cases exceed 5% CV. This is concentrated in Scatter ({len(unstable['scatter'])}) and Gather ({len(unstable['gather'])}), so unstable regions cannot support determined cache-transition or speedup claims.",
        ]
    )
    lines.extend(
        [
            "",
            "These are same-batch descriptive ranges, not causal cache claims. Use the per-case tables and dense N-axis plots to inspect transitions together with CV.",
            "",
            "## Unstable Cases",
            "",
        ]
    )
    if total_unstable == 0:
        lines.append("No case exceeded 5% CV.")
    else:
        for operation in EXPECTED:
            for case in unstable[operation]:
                lines.append(
                    f"- `UNSTABLE` `{case['run_name']}`: elem/core_cycle CV {case['elem_cycle']['cv']:.2%}; no dense exploratory rerun."
                )
    lines.extend(
        [
            "",
            "## Environment And Limitations",
            "",
            f"- Host: `{contexts['reduce'].get('host_name', '')}`; detailed topology, frequency policy, toolchain, memory/swap snapshot, git state, and resident CPU 8/200 tasks are in `environment.md`.",
            "- No formal runtime gate was applied. The report cannot establish CPU isolation, absence of external Java/ZGC interference, swap attribution, PSI compliance, or formal repeatability.",
            "- `ns/element` uses wall time and is sensitive to descheduling; `elem/core_cycle` uses in-process user core cycles.",
            "- `perf stat: skipped in exploratory dense mode`; no PMU or measured-DRAM conclusions are available.",
            "- These results cannot support absolute performance, cross-machine comparison, performance regression, capacity planning, hardware limits, or formal acceptance.",
            "",
        ]
    )
    (output_dir / "summary.md").write_text("\n".join(lines), encoding="utf-8")


def write_validation(output_dir, all_cases, manifest):
    lines = warning_lines("Dense package validation")
    lines.extend(
        [
            "All checks below were performed offline after the four benchmark commands completed. No formal runtime gate or `perf stat` was run.",
            "",
            "| Operation | Curves | Cases / MD rows | Raw repetitions | SVG dense curves | CV > 5% | JSON SHA-256 |",
            "| --- | ---: | ---: | ---: | ---: | ---: | --- |",
        ]
    )
    for operation, cases in all_cases.items():
        expected_curves, expected_cases, expected_rows = EXPECTED[operation]
        markdown = (output_dir / f"{operation}_fp32.md").read_text(encoding="utf-8")
        svg = (output_dir / f"{operation}_fp32.svg").read_text(encoding="utf-8")
        md_rows = len(re.findall(r"^\| .*\| (?:stable|UNSTABLE) \|$", markdown, re.MULTILINE))
        svg_curves = len(re.findall(r'<polyline data-curve="[^"]+" data-points="113"', svg))
        unstable = [case for case in cases if case["elem_cycle"]["cv"] > 0.05]
        unstable_nonanchors = [case for case in unstable if case["elements"] & (case["elements"] - 1)]
        expected_markers = expected_curves * 17 + len(unstable_nonanchors)
        if md_rows != expected_cases or svg_curves != expected_curves:
            raise ValueError(f"{operation}: report row/curve mismatch")
        if svg.count("<circle ") != expected_markers or svg.count('class="unstable"') != len(unstable):
            raise ValueError(f"{operation}: dense SVG marker mismatch")
        lines.append(
            f"| {operation} | {expected_curves} | {expected_cases} / {md_rows} | {expected_rows} | {svg_curves} | {len(unstable)} | `{manifest['files'][f'{operation}_fp32.json']['sha256']}` |"
        )
    lines.extend(
        [
            "| **Total** | **24** | **2712 / 2712** | **18984** | **24** | **{}** | |".format(
                sum(
                    case["elem_cycle"]["cv"] > 0.05
                    for cases in all_cases.values()
                    for case in cases
                )
            ),
            "",
            "Additional checks:",
            "",
            "- Every curve has exactly the same 113 approved unique N values in strict order.",
            "- Every case has seven raw repetitions and the approved implementation/pattern IDs, working set, and logical-byte counters.",
            "- Correctness and disassembly gates are PASS.",
            "- Dense SVG uses N on the log2 x-axis; pattern controls color, implementation controls line style, ordinary non-anchor stable points have no marker, all power-of-two anchors are marked, and every unstable point is hollow.",
            "- All human-readable package files begin with or visibly contain `EXPLORATORY / NON-FORMAL` and usage restrictions.",
            "- Earlier sparse/diagnostic batches were not read or merged by this generator.",
            "- `perf stat: skipped in exploratory dense mode`.",
            "",
        ]
    )
    (output_dir / "validation.md").write_text("\n".join(lines), encoding="utf-8")


def main():
    args = parse_args()
    output_dir = Path(args.output_dir).resolve()
    project_root = Path(__file__).resolve().parents[2]
    contexts = {}
    all_cases = {}
    metadata = {}
    manifest = {
        "designation": "EXPLORATORY / NON-FORMAL",
        "approval": "fourth supplemental approval, 2026-07-14",
        "batch_directory": str(output_dir),
        "size_formula": {
            "bases": [1024, 1136, 1248, 1376, 1520, 1680, 1856],
            "octaves": [0, 15],
            "appended_endpoint": 1 << 26,
            "size_count": len(DENSE_SIZES),
        },
        "collection_parameters": {
            "cpu": 8,
            "numa_node": 0,
            "benchmark_min_time": "0.25s",
            "benchmark_repetitions": 7,
            "benchmark_enable_random_interleaving": True,
            "formal_runtime_gate": "skipped",
            "perf_stat": "skipped in exploratory dense mode",
        },
        "prior_batches_used": [],
        "files": {},
        "revisions": {
            "project": git_revision(project_root),
            "google_benchmark": git_revision(project_root / "third_party/google-benchmark"),
            "sleef": git_revision(project_root / "third_party/sleef"),
            "tlfloat": git_revision(project_root / "third_party/sleef/submodules/tlfloat"),
        },
    }
    for operation, expected in EXPECTED.items():
        json_path = output_dir / f"{operation}_fp32.json"
        metadata_path = output_dir / f"{operation}_run.json"
        contexts[operation], cases = load_cases(json_path)
        observed = validate_dense_cases(cases)
        if observed != expected:
            raise SystemExit(f"{operation}: expected {expected}, observed {observed}")
        run = json.loads(metadata_path.read_text(encoding="utf-8"))
        if run.get("validation") != "PASS" or run.get("returncode") != 0:
            raise SystemExit(f"{operation}: run metadata is not PASS")
        all_cases[operation] = cases
        metadata[operation] = run
        manifest["files"][json_path.name] = {
            "sha256": sha256(json_path),
            "host": contexts[operation].get("host_name", ""),
            "date": contexts[operation].get("date", ""),
            "curves": observed[0],
            "cases": observed[1],
            "raw_repetition_rows": observed[2],
            "run_metadata": metadata_path.name,
        }
    manifest["totals"] = {"curves": 24, "cases": 2712, "raw_repetition_rows": 18984}
    (output_dir / "provenance.json").write_text(
        json.dumps(manifest, indent=2) + "\n", encoding="utf-8"
    )
    correctness = (output_dir / "correctness.md").read_text(encoding="utf-8")
    disassembly = (output_dir / "disassembly.md").read_text(encoding="utf-8")
    if "**PASS**" not in correctness or "| Count | 113 | PASS |" not in correctness:
        raise SystemExit("correctness gate evidence is not PASS")
    if "| PASS |" not in disassembly or "FAIL" in disassembly:
        raise SystemExit("disassembly gate evidence is not PASS")
    write_commands(output_dir, metadata)
    write_perf_status(output_dir)
    write_summary(output_dir, contexts, all_cases, metadata, manifest)
    write_validation(output_dir, all_cases, manifest)


if __name__ == "__main__":
    main()
