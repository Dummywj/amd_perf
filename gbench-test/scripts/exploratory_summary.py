#!/usr/bin/env python3

import argparse
import hashlib
import json
import statistics
from pathlib import Path

from ops_report import load_cases


EXPECTED = {"reduce": 36, "gather": 72, "scatter": 72, "softmax": 18}
SIZES = (1024, 262144, 67108864)


def parse_args():
    parser = argparse.ArgumentParser(description="Build the approved exploratory summary")
    parser.add_argument("output_dir")
    parser.add_argument("canonical_dir")
    return parser.parse_args()


def sha256(path):
    digest = hashlib.sha256()
    with Path(path).open("rb") as source:
        for block in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def fmt_ratio(value):
    return f"{value:.3f}x"


def main():
    args = parse_args()
    output_dir = Path(args.output_dir).resolve()
    canonical_dir = Path(args.canonical_dir).resolve()

    all_cases = {}
    manifest = {
        "exploratory_canonical": str(canonical_dir),
        "excluded_batches": [
            "ops_fp32_20260714-155323",
            "ops_fp32_20260714-161522",
        ],
        "files": {},
    }
    validation = []
    for operation, expected in EXPECTED.items():
        copied = output_dir / f"{operation}_fp32.json"
        source = canonical_dir / f"{operation}_fp32.json"
        _, cases = load_cases(copied)
        all_cases[operation] = cases
        raw_rows = sum(case["repetitions"] for case in cases)
        source_hash = sha256(source)
        copy_hash = sha256(copied)
        manifest["files"][copied.name] = {
            "source": str(source),
            "source_sha256": source_hash,
            "copy_sha256": copy_hash,
            "byte_identical": source_hash == copy_hash,
            "case_count": len(cases),
            "raw_repetition_rows": raw_rows,
        }
        validation.append(
            (operation, len(cases), expected, raw_rows, source_hash == copy_hash)
        )
        if len(cases) != expected or raw_rows != expected * 7 or source_hash != copy_hash:
            raise SystemExit(f"canonical validation failed for {operation}")

    manifest["total_case_count"] = sum(len(cases) for cases in all_cases.values())
    if manifest["total_case_count"] != 198:
        raise SystemExit("expected exactly 198 cases")
    (output_dir / "provenance.json").write_text(
        json.dumps(manifest, indent=2) + "\n", encoding="utf-8"
    )

    unstable = []
    for operation, cases in all_cases.items():
        for case in cases:
            if case["elem_cycle"]["cv"] > 0.05:
                unstable.append((operation, case))

    paired = {}
    for operation, cases in all_cases.items():
        for case in cases:
            key = (operation, case["variant"], case["elements"])
            paired.setdefault(key, {})[case["implementation"]] = case

    pair_speedups = []
    stable_speedups = []
    for key, implementations in paired.items():
        scalar = implementations["scalar"]
        avx512 = implementations["avx512"]
        speedup = avx512["elem_cycle"]["median"] / scalar["elem_cycle"]["median"]
        pair_speedups.append(speedup)
        if scalar["elem_cycle"]["cv"] <= 0.05 and avx512["elem_cycle"]["cv"] <= 0.05:
            stable_speedups.append(speedup)

    lines = [
        "# EXPLORATORY / NON-FORMAL",
        "",
        "**Data comes only from formally invalid batch `ops_fp32_20260714-152755`; external Java/ZGC activity and CPU contention affected the environment.**",
        "",
        "**Relative trends only. Do not use for absolute performance, cross-machine comparisons, performance regression, capacity planning, hardware limits, or formal acceptance.**",
        "",
        "## Provenance",
        "",
        "- Third supplemental approval date: 2026-07-14.",
        "- Sole exploratory canonical: `gbench-test/results/ops_fp32_20260714-152755`.",
        "- Batch 2 `ops_fp32_20260714-155323`: incomplete diagnostic only; not used.",
        "- Batch 3 `ops_fp32_20260714-161522`: runtime-gate diagnostic only; not used.",
        "- No cross-batch merge, selection, replacement, exclusion, or CV rerun was performed.",
        "- `perf stat: skipped in exploratory mode`.",
        "",
        "| Operation | Cases | Expected | Raw repetition rows | Copy matches canonical |",
        "| --- | ---: | ---: | ---: | --- |",
    ]
    for operation, count, expected, raw_rows, matched in validation:
        lines.append(
            f"| {operation} | {count} | {expected} | {raw_rows} | {'yes' if matched else 'no'} |"
        )
    lines.extend(
        [
            f"| **Total** | **{manifest['total_case_count']}** | **198** | **{sum(row[3] for row in validation)}** | **yes** |",
            "",
            "Machine-readable source paths, SHA-256 hashes, counts, and exclusions are in `provenance.json`.",
            "",
            "## Correctness",
            "",
            "The canonical correctness record reports PASS for all executed Reduce, Softmax, Gather, and Scatter checks. The approved `(stride17, N=17/1003)` Gather and Scatter combinations are explicitly N/A and were not executed.",
            "",
            "## Workload Semantics",
            "",
            "- Main lengths are `2^10, 2^12, ..., 2^26` (1K through 64M). Small lengths repeat the kernel `ceil(32768/N)` times inside each timed iteration; lengths at or above 32768 use one pass.",
            "- Reduce computes either FP32 sum or max over one input array. Scalar code has vectorization disabled; AVX-512 uses explicit 512-bit accumulators and masked tails. Working set is `4*N` bytes and logical traffic is `4*N + 4` bytes.",
            "- Gather computes `out[i] = table[index[i]]`; Scatter computes `dst[index[i]] = src[i]`. Their scalar loops have vectorization disabled and their AVX-512 loops use explicit i32 gather/scatter instructions with masked tails. Both use a `12*N` byte working-set and logical-traffic model.",
            "- Gather/Scatter indices are deterministic permutations: sequential identity; `stride17` as `(17*i) mod N`; independent shuffle within each 4096-element block for `block_random_4k`; and a full-array deterministic shuffle for `uniform_random`.",
            "- Softmax is numerically stable: subtract maximum, apply SLEEF u10 exponential, accumulate the sum in 4096-element blocks, then normalize. Scalar uses `Sleef_expf_u10`; AVX-512 uses `Sleef_expf16_u10avx512f`. Working set is `8*N` bytes and logical traffic is `20*N` bytes.",
            "- Inputs and permutations use fixed global seed `20260714`; Reduce/Gather/Scatter values are in `[-1,1)`, while Softmax inputs are in `[-10,10)`.",
            "",
            "## Statistical Scope",
            "",
            "Statistics use the seven raw repetitions from the canonical JSON only. Median/min/mean/sample standard deviation/CV are computed for `elem/core_cycle`; `ns/element` and logical GB/s are derived per repetition and reported by median. AVX-512 speedup is AVX-512 median `elem/core_cycle` divided by the paired scalar median.",
            "",
            f"- Unstable implementation cases (`CV > 5%`): **{len(unstable)} / 198**.",
            f"- Stable paired speedup range: **{min(stable_speedups):.3f}x to {max(stable_speedups):.3f}x** across {len(stable_speedups)} semantic pairs.",
            f"- All-pair exploratory speedup range, including unstable pairs: **{min(pair_speedups):.3f}x to {max(pair_speedups):.3f}x**.",
            "",
            "The per-case Markdown tables contain median, min, mean, standard deviation, CV, ns/element, logical GB/s, speedup, and an explicit `UNSTABLE` marker. Hollow large SVG points denote unstable cases.",
            "",
            "## Selected Same-Batch Observations",
            "",
            "| Operation | Variant/pattern | N | Scalar elem/cycle (CV) | AVX-512 elem/cycle (CV) | Speedup | Status |",
            "| --- | --- | ---: | ---: | ---: | ---: | --- |",
        ]
    )
    for key in sorted(paired):
        operation, variant, elements = key
        if elements not in SIZES:
            continue
        scalar = paired[key]["scalar"]
        avx512 = paired[key]["avx512"]
        speedup = avx512["elem_cycle"]["median"] / scalar["elem_cycle"]["median"]
        is_unstable = scalar["elem_cycle"]["cv"] > 0.05 or avx512["elem_cycle"]["cv"] > 0.05
        lines.append(
            f"| {operation} | {variant} | {elements} | "
            f"{scalar['elem_cycle']['median']:.6g} ({scalar['elem_cycle']['cv']:.2%}) | "
            f"{avx512['elem_cycle']['median']:.6g} ({avx512['elem_cycle']['cv']:.2%}) | "
            f"{speedup:.3f}x | {'UNSTABLE' if is_unstable else 'stable'} |"
        )

    def pair(operation, variant, elements):
        return paired[(operation, variant, elements)]

    gather_seq = pair("gather", "sequential", 67108864)["avx512"]["elem_cycle"]["median"]
    gather_random = pair("gather", "uniform_random", 67108864)["avx512"]["elem_cycle"]["median"]
    scatter_seq = pair("scatter", "sequential", 67108864)["avx512"]["elem_cycle"]["median"]
    scatter_random = pair("scatter", "uniform_random", 67108864)["avx512"]["elem_cycle"]["median"]
    lines.extend(
        [
            "",
            "These are observations within the same invalid batch, not causal cache or hardware-limit claims:",
            "",
            f"- At 64M, AVX-512 uniform-random Gather is {gather_random / gather_seq:.3f}x the sequential Gather throughput.",
            f"- At 64M, the observed AVX-512 uniform-random Scatter median is {scatter_random / scatter_seq:.3f}x the sequential median, but both cases are `UNSTABLE`; this is not a determined trend.",
            "- Throughput changes with working-set size in all four operators; the plots expose those transitions, but this batch cannot establish their cause because CPU contention was not controlled.",
            "- Scalar/AVX-512 differences are implementation-package differences. Softmax includes different fixed SLEEF u10 scalar/vector entry points plus reduction and normalization code.",
            "",
            "## Unstable Cases",
            "",
        ]
    )
    if unstable:
        for operation, case in unstable:
            lines.append(
                f"- `UNSTABLE` `{case['run_name']}`: elem/core_cycle CV {case['elem_cycle']['cv']:.2%}; no exploratory rerun."
            )
    else:
        lines.append("No case exceeded 5% CV.")

    lines.extend(
        [
            "",
            "## Environment Interference",
            "",
            "The batch began under low reported load but Softmax JSON records load average 149.336 at process start. Later diagnostics identified another user's GraalVM Bloop server with ZGC (`ZCollectionInterval=5`) and unrestricted CPU affinity `0-383`; periodic runnable-thread bursts reached roughly 67-101 tasks. The exploratory canonical predates the later complete runtime-gate instrumentation, so it cannot prove process major-fault, PSI, context-switch, or CPU-isolation compliance.",
            "",
            "## Limitations",
            "",
            "- Logical GB/s follows the frozen logical byte model and is not measured DRAM traffic.",
            "- No PMU conclusions are available: `perf stat: skipped in exploratory mode`.",
            "- No absolute performance, cross-machine comparison, regression threshold, capacity estimate, hardware ceiling, or acceptance claim is valid from this package.",
            "- Future formal results require a new complete 198-case batch satisfying all runtime gates; this exploratory authorization does not relax them.",
            "",
        ]
    )
    (output_dir / "summary.md").write_text("\n".join(lines), encoding="utf-8")


if __name__ == "__main__":
    main()
