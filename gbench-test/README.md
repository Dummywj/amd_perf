AMD 向量处理单元测试
测试框架：Google Benchmark

| Benchmark 名称 | 测试说明 |
| --- | --- |
| `BM_Fp32FmaSmoke` | FP32 FMA 冒烟测试，执行 `out[i] = a[i] * b[i] + c[i]`，用于验证 Google Benchmark、AVX-512 编译和 perf cycle 计数链路是否正常。 |
| `BM_Fp32FmaRegisterPeak` | FP32 AVX-512 FMA 寄存器峰值测试，使用 16 个独立 ZMM accumulator，尽量减少内存访问影响，观察单核 FMA 吞吐上限。 |
| `BM_Fp32FmaLengthSweep` | 高计算密度 FP32 FMA 长度扫描测试，单数组 load/store，每个元素在寄存器中执行多轮 FMA，用于观察较高算术强度下工作集增大对吞吐的影响。 |
| `BM_Fp32FmaLengthSweepOnce` | 单次 FMA stream 长度扫描测试，四数组 `out[i] = a[i] * b[i] + c[i]`，每个元素只做一次 FMA，用于观察 L1/L2/L3/内存层级对低计算密度 FMA 的影响。 |

## FP32 算子测试

已批准的单核算子测试套件包含以下测试项：

| 测试项 | 用例数 |
| --- | ---: |
| `reduce-fp32` | 452 |
| `gather-fp32` | 1,017 |
| `scatter-fp32` | 1,017 |
| `softmax-fp32` | 226 |
| `fma-fp32` | 226 |
| **总计** | **2,938** |

每条曲线使用 113 个确定性的整数尺寸：

```text
base = {1024, 1136, 1248, 1376, 1520, 1680, 1856}
sizes = {base[j] << octave | octave=0..15, j=0..6} U {1 << 26}
```

四种索引模式下的 Gather/Scatter 均保留 `scalar` 实现，以及名称明确的
`avx512_vgather` / `avx512_vscatter` 实现。`contiguous/avx512_load_store`
是一条独立的缓存拷贝对照曲线，不分配或访问索引，采用 `8N` 逻辑字节模型。

FMA 包含两条 AVX-512 曲线：`reuse` 每次加载后对每个元素执行 64 轮 FMA，
用于提高算术强度并观察计算峰值；`once` 对每个元素只执行一次 `a*b+c`，
用于观察低算术强度下的流式访存表现。FMA 报告中的 `flop/core_cycle`
是主要计算吞吐指标。

### BF16 FMA

BF16 只增加原生 FMA 测试，不扩展 Reduce、Softmax、Gather 或 Scatter。
测试使用 AVX-512 BF16 的 `vdpbf16ps`：每条指令读取两组各 32 个 BF16
输入，将相邻两个 BF16 乘积相加，并累加到 16 个 FP32 结果中。

`fma-bf16` 与 FP32 FMA 使用相同的 113 个尺寸，也包含两条曲线：

- `reuse/avx512_bf16_dot`：A、B 和 FP32 accumulator 保持在寄存器中执行
  64 轮 dot-product FMA，使用 8 个独立 accumulator 挖掘计算吞吐。
- `once/avx512_bf16_dot`：每个 BF16 输入元素只参与一轮 dot-product FMA，
  用于观察单次使用时的访存表现。

这里的 `N` 是 A 和 B 各自的 BF16 元素数，输出包含 `N/2` 个 FP32 元素。
两条曲线的 working set 和 logical bytes 均为 `8N`。主指标是
`flop/core_cycle`；报告也给出 `dpbf16_instr/core_cycle`。运行服务器必须支持
`avx512_bf16`，否则正确性程序和 benchmark 会明确拒绝执行。

在独立构建目录中编译所有内核和正确性门禁程序：

```bash
make ops-build BUILD_DIR=build-ops-release CONFIG=Release
```

运行完整的非计时正确性矩阵：

```bash
numactl --physcpubind=8 --membind=0 \
  build-ops-release/ops_fp32_correctness results/correctness.md
```

### 单独运行一个算子

不需要每次都运行完整的五算子套件。可以通过 `PAYLOAD` 指定一个算子，
并为本次运行提供新的结果目录：

```bash
make run \
  PAYLOAD=<算子> \
  BUILD_DIR=build-ops-release \
  CPU=8 \
  NUMA_NODE=0 \
  RESULTS_DIR=results/<新的结果目录>
```

支持的单算子 `PAYLOAD` 及输出文件如下：

| 算子 | `PAYLOAD` | 输出文件 |
| --- | --- | --- |
| Reduce | `reduce-fp32` | `reduce_fp32.json`、`reduce_fp32.md`、`reduce_fp32.svg` |
| Gather | `gather-fp32` | `gather_fp32.json`、`gather_fp32.md`、`gather_fp32.svg` |
| Scatter | `scatter-fp32` | `scatter_fp32.json`、`scatter_fp32.md`、`scatter_fp32.svg` |
| Softmax | `softmax-fp32` | `softmax_fp32.json`、`softmax_fp32.md`、`softmax_fp32.svg` |
| FMA FP32 | `fma-fp32` | `fma_fp32.json`、`fma_fp32.md`、`fma_fp32.svg` |
| FMA BF16 | `fma-bf16` | `fma_bf16.json`、`fma_bf16.md`、`fma_bf16.svg` |

例如只运行 FMA：

```bash
make run \
  PAYLOAD=fma-fp32 \
  BUILD_DIR=build-ops-release \
  CPU=8 \
  NUMA_NODE=0 \
  RESULTS_DIR=results/fma_fp32_$(date +%Y%m%d-%H%M%S)
```

单算子模式仍会执行该算子的全部 113 个尺寸和 7 次随机交错重复，但不会生成
依赖全部五个算子的综合 `summary.md`、`validation.md` 和 `provenance.json`。
`make run` 不会像完整套件脚本一样拒绝覆盖已有目录，因此每次应指定新的
`RESULTS_DIR`。

BF16 FMA 的非计时门禁包含数值正确性、226 个完整用例的注册校验，以及
`vdpbf16ps` 反汇编校验：

```bash
make fma-bf16-gates BUILD_DIR=build-ops-release CONFIG=Release JOBS=16
```

门禁通过后，单独运行完整 BF16 FMA 密集测试并生成 JSON、Markdown 和 SVG：

```bash
make run \
  PAYLOAD=fma-bf16 \
  BUILD_DIR=build-ops-release \
  JOBS=16 \
  CPU=8 \
  NUMA_NODE=0 \
  RESULTS_DIR=results/fma_bf16_$(date +%Y%m%d-%H%M%S)
```

该命令执行 2 条曲线、每条 113 个尺寸、每个用例 7 次重复。BF16 FMA
保持为独立 payload，不会加入 `make ops-dense` 的五算子 FP32 批次。

运行完整的探索性密集测试，包括构建、语义门禁、五个算子、图表生成、
完整性校验和综合汇总：

```bash
make ops-dense
```

当前服务器的默认配置为构建目录 `build-ops-release`、CPU 8、NUMA 节点 0，
以及 SMT 兄弟线程 CPU 200。如果服务器拓扑不同，可以覆盖这些参数：

```bash
make ops-dense DENSE_CPU=<cpu> DENSE_NUMA_NODE=<node> \
  DENSE_SMT_SIBLING=<sibling>
```

结果默认写入新的时间戳目录
`results/exploratory_dense_ops_fp32_<timestamp>`。可以通过
`DENSE_RESULTS_DIR` 指定其他尚不存在的目录；测试脚本会拒绝覆盖已有目录。
五个测试项按顺序串行执行，不会并行运行。

Makefile 中的算子测试流程会执行一次绑定 NUMA 的密集测试。每个用例进行
7 次随机交错重复，最短测试时间为 0.25 秒。`scripts/ops_report.py --dense`
会校验每条曲线的 113 个数据点，并根据原始 JSON 生成 Markdown 稳定性表格
和 SVG 图表。2,938 个用例的纯内核时间下限约为 85 分 41 秒；考虑初始化和
确定性乱序过程，一次完整运行通常需要 2 至 4 小时。冻结的测试语义、
正确性阈值和执行规则见 `docs/test-plan.md`。
