AMD 向量处理单元测试
测试框架：Google Benchmark

| Benchmark 名称 | 测试说明 |
| --- | --- |
| `BM_Fp32FmaSmoke` | FP32 FMA 冒烟测试，执行 `out[i] = a[i] * b[i] + c[i]`，用于验证 Google Benchmark、AVX-512 编译和 perf cycle 计数链路是否正常。 |
| `BM_Fp32FmaRegisterPeak` | FP32 AVX-512 FMA 寄存器峰值测试，使用 16 个独立 ZMM accumulator，尽量减少内存访问影响，观察单核 FMA 吞吐上限。 |
| `BM_Fp32FmaLengthSweep` | 高计算密度 FP32 FMA 长度扫描测试，单数组 load/store，每个元素在寄存器中执行多轮 FMA，用于观察较高算术强度下工作集增大对吞吐的影响。 |
| `BM_Fp32FmaLengthSweepOnce` | 单次 FMA stream 长度扫描测试，四数组 `out[i] = a[i] * b[i] + c[i]`，每个元素只做一次 FMA，用于观察 L1/L2/L3/内存层级对低计算密度 FMA 的影响。 |

## FP32 operations

The approved single-core operation suite provides these payloads:

| Payload | Cases |
| --- | ---: |
| `reduce-fp32` | 452 |
| `gather-fp32` | 1,017 |
| `scatter-fp32` | 1,017 |
| `softmax-fp32` | 226 |
| **Total** | **2,712** |

Each curve uses 113 deterministic integer sizes:

```text
base = {1024, 1136, 1248, 1376, 1520, 1680, 1856}
sizes = {base[j] << octave | octave=0..15, j=0..6} U {1 << 26}
```

Indexed Gather/Scatter keep `scalar` plus explicitly named
`avx512_vgather` / `avx512_vscatter` implementations for all four index
patterns. The `contiguous/avx512_load_store` curve is a separate cached-copy
control with no index allocation or access and an `8N` logical-byte model.

Build all kernels and the correctness gate in an independent build directory:

```bash
make ops-build BUILD_DIR=build-ops-release CONFIG=Release
```

Run the full non-timed correctness matrix:

```bash
numactl --physcpubind=8 --membind=0 \
  build-ops-release/ops_fp32_correctness results/correctness.md
```

Run one approved performance payload by passing a new result directory:

```bash
make run PAYLOAD=reduce-fp32 BUILD_DIR=build-ops-release CPU=8 NUMA_NODE=0 \
  RESULTS_DIR=results/ops_fp32_<timestamp>
```

The ops Makefile path performs one NUMA-bound dense run with 7 randomized
repetitions and a 0.25-second minimum time. Use `scripts/ops_report.py --dense`
to validate all 113 points per curve and derive the Markdown stability table
and SVG from the raw JSON. The 2,712-case kernel-time lower bound is 79 minutes;
initialization and deterministic shuffles make 2-4 hours a realistic full-run
estimate. The frozen semantics, correctness thresholds, and execution rules are
in `docs/test-plan.md`.
