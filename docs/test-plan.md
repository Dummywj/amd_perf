# AMD 长向量性能测试计划

## 文档状态与执行门禁

| 项目 | 值 |
| --- | --- |
| 状态 | **用户已审核通过，执行中** |
| 冻结草案日期 | 2026-07-14 |
| 用户批准日期 | 2026-07-14 |
| 第一次补充批准日期 | 2026-07-14（`stride17` correctness-only 适用条件） |
| 第二次补充批准日期 | 2026-07-14（可归因运行环境门禁和完整第三批重采） |
| 第三次补充批准日期 | 2026-07-14（采用既有第一批生成非正式探索性报告） |
| 第四次补充批准日期 | 2026-07-14（113 点 dense sweep 和连续 load/store 对照） |
| 第五次补充批准日期 | 2026-07-15（将两种 FMA 算术强度场景纳入 dense suite） |
| 本轮算子 | Softmax、Reduce、Gather、Scatter、FMA |
| 本轮数据类型 | FP32 |

第五次补充范围将 FMA 纳入同一 dense suite：`reuse` 每次加载后执行 64 轮 FMA，`once` 每个元素只执行一次 `a*b+c`。两条曲线均使用现有 113 点尺寸、7 次重复和相同 NUMA 绑核；FMA 的主要计算吞吐指标为 `flop/core_cycle`。

本文档曾以“待用户审核，禁止执行”状态冻结；用户于 2026-07-14 明确审核通过，执行门禁现已解除并进入执行阶段。执行期间发现 `stride17` 与两个 correctness-only 尺寸的唯一索引约束冲突，执行已按门禁暂停；用户批准本文件记录的 `N/A` 修订后恢复执行。随后，旧的“出现任何全局 swap 即停止”规则无法区分本轮进程污染和外部微量换入，执行再次按门禁暂停；用户于 2026-07-14 第二次补充批准本文件记录的可归因门禁和完整第三批重采后恢复执行。用户又于 2026-07-14 第三次补充批准：允许从完整第一批生成明确标注为非正式的探索性报告。该例外不改变第一批的正式失效状态，也不降低未来正式采集门禁。用户当前消息构成第四次补充批准：将新探索性 dense run 扩展为每条曲线 113 个尺寸，并为 Gather/Scatter 增加普通 AVX-512 load/store 对照；该范围已经批准，无需再次审核即可实施。未来正式采集门禁继续保留；后续若再修改范围或语义，仍须先更新本文档并重新获得批准。

## 背景

仓库已经使用 Google Benchmark 建立了 FP32 FMA 的测试链路，包括：

- `BM_Fp32FmaSmoke`：验证 Google Benchmark、AVX-512 编译和 core-cycle 计数链路。
- `BM_Fp32FmaRegisterPeak`：观察单核寄存器 FMA 吞吐上限。
- `BM_Fp32FmaLengthSweep` 和 `BM_Fp32FmaLengthSweepOnce`：观察高、低算术强度下工作集变化对吞吐的影响。
- 原始 JSON、Markdown 转换和 SVG 绘图脚本。

这些内容作为本轮实现风格和结果格式的背景保留。本轮不修改 FMA 语义、不重跑 FMA 全量结果，也不把 FMA 计入新的 case 数量。若公共计数链路发生变化，只允许使用现有 FMA smoke 做回归检查，并在报告中单独标明。

## 测试目标

本轮目标是测量 AMD EPYC 单核执行四类长向量 FP32 内核时的性能，并回答以下问题：

1. forced-scalar 基线和显式 AVX-512 实现之间的性能差异是多少。
2. 工作集从 L1/L2 扩展到 LLC 和内存后，吞吐如何变化。
3. Gather/Scatter 的顺序、固定步长、局部随机和全局随机索引分别产生什么影响。
4. Softmax 的完整稳定算法在包含向量 `exp` 后可以达到什么性能。
5. 性能结果是否在正确性、重复性、绑核和 NUMA 约束下成立。

核心输出是 `elem/core_cycle`，同时报告 `ns/element`、`items/s`、逻辑带宽和必要的硬件计数器诊断。

## 非目标

以下内容明确不属于首轮：

- BF16、FP16、FP64 或混合精度性能测试。
- 多线程、SMT 扩展、跨 NUMA、远端内存或双路扩展测试。
- oneDNN、PyTorch、ONNX Runtime 等生产库或框架对照。
- batched softmax、多轴 reduction、非连续 layout 或 stride tensor。
- Scatter-add、原子 Scatter、重复索引冲突和冲突顺序语义。
- Gather 的重复随机索引或带替换随机采样。
- NaN、正负无穷、subnormal 和有符号零的特殊值语义。
- 冷缓存延迟、首次缺页、内存分配或索引生成性能。
- FMA 结果复测或已有 FMA 代码的无关重构。

## 实现基线

### 公共约束

- 使用现有 Google Benchmark 框架和 C++17 构建方式。
- 使用现有 Release 编译基线：`-O3 -march=native`，不增加 `-ffast-math`。
- 所有被测 kernel 必须 `noinline`，并使用 `DoNotOptimize`/`ClobberMemory` 或等价机制防止删除和跨调用错误优化。
- scalar kernel 必须通过编译器属性或局部 pragma 禁止自动向量化；不得通过降低整个可执行文件的优化等级构造基线。
- AVX-512 kernel 使用显式 intrinsic，并对尾部使用 mask 或等价的边界安全处理。
- 构建后检查反汇编：scalar 不得出现向量化主体；AVX-512 版本必须出现预期的 AVX-512 指令。Gather/Scatter 分别应出现对应的 gather/scatter 指令。
- scalar 与 AVX-512 版本必须使用相同输入、相同算子语义、相同输出精度和相同逻辑 pass；不得为提高某一版本成绩而跳过必要步骤。
- 第四次补充批准新增的 contiguous kernel 必须使用显式 `_mm512_loadu_ps`/`_mm512_storeu_ps`；禁止替换为 `memcpy`、`std::copy`、non-temporal store 或保留但不读取的虚假 index 流。反汇编必须确认 contiguous 主体只有普通 AVX-512 load/store，不含 gather/scatter 或库 copy 调用。

### Softmax 的 SLEEF 基线

仓库已包含 SLEEF。为避免 scalar 和向量版本使用不同精度等级的指数函数，本轮统一使用 SLEEF `u10` 精度族：

- scalar softmax：forced-scalar 归约/归一化和 scalar `Sleef_expf_u10`。
- AVX-512 softmax：显式 AVX-512 归约/归一化和 `Sleef_expf16_u10avx512f`，或经构建验证后与其完全等价的 SLEEF AVX-512 `u10` 入口。
- double 参考实现：使用 `std::exp`，只用于非计时正确性校验。

如果固定的 SLEEF `u10` scalar 或 AVX-512 入口不能构建、链接或不能生成预期代码，必须停止 Softmax 实施并报告，不得静默切换到 `std::expf`、低精度近似或其他数学库。Softmax 的 scalar/AVX-512 speedup 表示完整实现包的差异，不解释为单独一条 SIMD 指令的加速比。

## 数据类型边界

首轮所有被测数据、输出和中间累加均为 FP32；Gather/Scatter 索引为 `uint32_t`。Reduce-sum 和 Softmax 的 double 计算只作为计时外参考值，不属于被测内核。

BF16 延后到第二阶段，原因如下：

1. Softmax 的 `exp`、累加和归一化通常仍需转换到 FP32，必须先定义 BF16 输入、输出和中间值边界。
2. AVX-512 BF16 主要提供点积能力，不直接提供逐 BF16 元素的 `exp`。
3. Gather/Scatter 没有与 FP32 gather/scatter 等价的原生逐 16-bit 元素语义；打包、扩展或读改写方案会改变实际访存量和原子性。
4. 在 FP32 的计时、正确性和报告链路稳定前加入 BF16，会混淆实现问题和数据类型问题。

第二阶段的候选语义是 BF16 存储、FP32 累加/`exp`/归一化，但必须另行形成测试计划并经用户批准。

## 算子精确定义

### Reduce

输入是一个长度为 `N` 的连续 FP32 向量，分别测试两个独立操作：

```text
reduce_sum(x) = FP32 reduction of x[0..N-1]
reduce_max(x) = max(x[0..N-1])
```

- `sum` 使用 FP32 累加。scalar 和 AVX-512 可以使用多个独立 accumulator 及不同的最终归约树，但不得使用 double accumulator。
- `max` 的输入只包含有限普通值，不测试 NaN 传播规则。
- 输出是一个 FP32 标量。
- `sum` 和 `max` 分开计时，不合并在同一个 kernel 中。

### Softmax

输入是一个长度为 `N` 的连续 FP32 向量，输出是另一个长度为 `N` 的连续 FP32 向量。首轮只测一个长 row、out-of-place、数值稳定的 softmax：

```text
m    = reduce_max(x)
e[i] = Sleef_u10_exp(x[i] - m)
s    = FP32 reduce_sum(e)
y[i] = e[i] / s
```

- `e` 直接存入输出缓冲区，归一化时原地改写输出缓冲区，不另设完整临时数组。
- `exp` 和 `sum(e)` 可在同一次遍历中完成，因此完整 kernel 是三个逻辑阶段：max、exp+sum、normalize。
- 输入由固定种子确定性生成，范围限制在 `[-10, 10]`，不含 NaN/Inf。
- `elements` 按输入长度 `N` 计算一次，不因内部三个阶段而乘 3。

### FMA

FMA 使用显式 AVX-512 FP32 FMA，固定两个算术强度场景，均使用同一套 113 点 `N`：

- `fma/reuse/avx512`：每个 256 元素 ZMM block 加载 16 个独立 accumulator，随后对每个元素执行 64 轮 `x = x * 0.99999994 + 0.000001`，最后一次写回。该场景通过元素复用提高算术强度，用于观察 FMA 计算峰值；working set 为 `4N`，logical bytes 为 `8N`。
- `fma/once/avx512`：读取 `a`、`b`、`c` 三个 FP32 输入并写入 `out`，每个元素只执行一次 `out[i] = a[i] * b[i] + c[i]`；working set 和 logical bytes 均为 `16N`。

FMA 不提供 scalar 对照；`elem/core_cycle` 表示 lane-wise FMA element operations/cycle，`flop/core_cycle` 为其两倍并作为主要计算吞吐指标。两条 FMA 内核必须在反汇编中出现 AVX-512 `vfmadd*ps`，并覆盖 mask tail 的正确性。

### BF16 FMA 补充范围

BF16 首轮只测试原生 FMA，不为 Reduce、Softmax、Gather 或 Scatter 增加 BF16 曲线。它作为独立的 `fma-bf16` payload，不计入五算子 FP32 dense suite 的 26 条曲线和 2,938 个 cases。

- 数据语义：A、B 各包含 `N` 个 BF16 元素，C 和输出各包含 `ceil(N/2)` 个 FP32 元素。每个输出执行 `acc += a[2i]*b[2i] + a[2i+1]*b[2i+1]`；仅 correctness 使用的奇数 tail 将缺失 lane 视为零，113 个性能尺寸均为偶数。
- `fma_bf16/reuse/avx512_bf16_dot`：以 8 个独立 FP32 ZMM accumulator 执行 64 轮 `_mm512_dpbf16_ps`，A/B/C 在这 64 轮中保持寄存器复用。
- `fma_bf16/once/avx512_bf16_dot`：每个 BF16 输入元素只参与一轮 `_mm512_dpbf16_ps`。
- 两条曲线均使用现有 113 点整数尺寸、7 次随机交错重复、0.25 秒最短用例时间；working set 与 logical bytes 均为 `8N`。
- `elem/core_cycle` 统计参与 dot product 的 BF16 input element operations；`flop/core_cycle=2*elem/core_cycle` 是主要指标，另报告 `dpbf16_instr/core_cycle`。
- 性能执行前必须通过 BF16 到 FP32 数值 oracle、奇偶 mask tail、226-case 注册完整性和反汇编 `vdpbf16ps` 门禁。CPU 缺少 `avx512_bf16` 时不得回退为 FP32 模拟。
- 完整输出固定为 `fma_bf16.json`、`fma_bf16.md` 和 `fma_bf16.svg`，完整性能采集由用户手动执行。

### Gather

输入包括长度为 `M` 的 FP32 `table` 和长度为 `K` 的 `uint32_t index`，输出为长度 `K` 的 FP32 向量：

```text
out[i] = table[index[i]], 0 <= i < K
```

- 所有索引满足 `0 <= index[i] < M`。
- 首轮固定 `K = M = N`。
- 所有实际执行的索引模式都必须生成一个置换，因此没有重复索引；这是为使 Gather/Scatter 的工作集和访问覆盖可比较。`stride17` 的 correctness-only 例外组合按下文明确标记为 `N/A`，不实际执行。

第四次补充批准将以下两个语义不同的曲线同时保留：

- `gather/sequential/avx512_vgather`：仍构造并读取 `index[i] = i`，主体必须使用 `_mm512_i32gather_ps`/`vgatherdps`。这是“连续索引下的强制 indexed gather”，不是普通连续 load。
- `gather/contiguous/avx512_load_store`：不分配、不构造、不读取 index，执行 `out[i] = table[i]`，主体使用普通 AVX-512 load/store。这是移除 index 流和间接寻址后的 cached copy 对照，不得称为 gather 的第三种等价实现。

其他 indexed pattern 的 AVX-512 实现名同样明确为 `avx512_vgather`；scalar 名保持 `scalar`。报告脚本可以兼容历史结果中的旧名 `avx512`，但新的 dense run 必须使用上述显式命名。

### Scatter

输入包括长度为 `K` 的 FP32 `src`、长度为 `K` 的 `uint32_t index` 和长度为 `M` 的 FP32 `dst`：

```text
dst[index[i]] = src[i], 0 <= i < K
```

- 首轮固定 `K = M = N`。
- 所有索引唯一，因此每个目标位置恰好写一次，不定义重复索引的先后覆盖语义。
- 不读取旧 `dst` 值，不执行加法，不使用原子操作。

第四次补充批准将以下两个语义不同的曲线同时保留：

- `scatter/sequential/avx512_vscatter`：仍构造并读取 `index[i] = i`，主体必须使用 `_mm512_i32scatter_ps`/`vscatterdps`。
- `scatter/contiguous/avx512_load_store`：不分配、不构造、不读取 index，执行 `dst[i] = src[i]`，主体使用普通 AVX-512 load/store。这是 cached copy 对照，不得称为 scatter 的等价实现。

其他 indexed pattern 的 AVX-512 实现名明确为 `avx512_vscatter`。

## 输入与索引构造

普通 FP32 数据使用确定性的伪随机或可复现周期数据生成。全局固定 seed 为：

```text
20260714
```

每个 `(operation, pattern, N)` 在生成前重新初始化确定性 PRNG；若需要派生流，只能将固定 seed 与稳定的操作/模式标识和 `N` 组合，组合方法必须写入最终报告，不能使用进程地址、系统时间或实现相关的随机哈希。

Gather/Scatter 主性能矩阵使用以下四种索引置换：

| 模式 | 精确定义 | 目的 |
| --- | --- | --- |
| `sequential` | `index[i] = i`，indexed AVX-512 路径仍强制执行 `vgatherdps`/`vscatterdps` | 连续索引下的间接访存上限，不等同于 contiguous load/store |
| `stride17` | `index[i] = (17 * i) mod M`，仅当 `gcd(17, M) = 1` 时适用 | 固定 17 元素步长；dense 尺寸表通过结构断言保证与 17 互素，因此是置换 |
| `block_random_4k` | 将 `[0, M)` 按最多 4096 个元素分块，只在各块内使用确定性 Fisher-Yates shuffle | 保留块局部性的随机访问 |
| `uniform_random` | 对完整 `[0, M)` 使用确定性 Fisher-Yates shuffle | 覆盖全工作集的随机置换 |

当 `M < 4096` 时，`block_random_4k` 只有一个部分块，仍执行块内 shuffle。索引生成和 shuffle 完全位于计时区间外。

生成 `stride17` 前必须先检查 `gcd(17, M) == 1`。若不互素，则不得生成索引、不得运行该组合、不得记录为 `PASS`，也不得静默改用其他 stride。所有其他实际执行的模式仍必须在运行前验证索引范围和置换唯一性。

## 尺寸矩阵与 case 数量

前三批使用的 sparse 矩阵为 9 个长度、198 个 case，仅作为历史结果说明。第四次补充批准的新 dense run 将每条性能曲线扩展为 113 个确定性长度。

### 113 点整数尺寸公式

基础模板为：

```text
base = {1024, 1136, 1248, 1376, 1520, 1680, 1856}
sizes = {base[j] << octave | octave = 0..15, j = 0..6} U {1 << 26}
```

实现必须按 `octave`、`j` 顺序生成前 112 个点，再追加 `1 << 26`，不得使用运行时浮点 `pow/exp2` 重新取整。`base` 是 `1024 * 2^(j/7)` 取到最接近 16 元素倍数后的固定整数模板；相邻点约为 `1.10x`，每个半开倍增区间有 7 个点，终点为 64M。

尺寸生成后必须在注册 benchmark 前断言：

- 数量恰好为 113，首点为 `1 << 10`，末点为 `1 << 26`。
- 严格递增且全部 unique。
- 每个 `N` 都满足 `N % 16 == 0`。
- `1K, 2K, 4K, ..., 64M` 的所有 2 次幂锚点都存在，原 9 个 sparse 锚点自然保留。
- 每个 `N` 都满足 `gcd(17, N) == 1`，因此 dense 主矩阵的 `stride17` 全部有效。

其中 `K`、`M`、`N` 均以元素个数表示，`1K = 1024`、`1M = 1024 * 1024`。按工作集计算，Reduce 为 `4N`、Softmax 为 `8N`、indexed Gather/Scatter 为 `12N`、contiguous 对照为 `8N`；每 octave 7 点用于提高 L1、L2、LLC 和内存过渡区附近的采样密度。

### Dense case 数量

| 算子 | 维度 | 实现数 | case 数 |
| --- | ---: | ---: | ---: |
| Reduce | sum/max * 113 个 N | scalar + AVX-512，共 4 条曲线 | `2 * 2 * 113 = 452` |
| Softmax | 113 个 N | scalar + AVX-512，共 2 条曲线 | `2 * 113 = 226` |
| Gather indexed | 4 种索引 * 113 个 N | scalar + `avx512_vgather`，共 8 条曲线 | `4 * 2 * 113 = 904` |
| Gather contiguous | 113 个 N | `avx512_load_store`，1 条曲线 | `113` |
| Scatter indexed | 4 种索引 * 113 个 N | scalar + `avx512_vscatter`，共 8 条曲线 | `4 * 2 * 113 = 904` |
| Scatter contiguous | 113 个 N | `avx512_load_store`，1 条曲线 | `113` |
| FMA | reuse/once * 113 个 N | AVX-512，共 2 条曲线 | `226` |
| **总计** | **26 条曲线** |  | **2,938** |

2,938 只统计 dense 主性能 case，不包括 correctness-only 尺寸、构建回归或失败运行。每个 case 运行 7 repetitions，因此应产生 `2,938 * 7 = 20,566` 条 raw repetition rows。

### Tail 正确性专用尺寸

以下长度只做正确性测试，不进入 dense 性能图表或 2,938 个 case：

```text
1, 7, 15, 17, 1003
```

这些尺寸覆盖空 mask 以外的短向量、16-lane AVX-512 边界两侧和非对齐长尾。长度 0 不属于本轮算子定义。

correctness-only 的索引模式适用规则为：

| Tail N | `sequential` | `stride17` | `block_random_4k` | `uniform_random` |
| ---: | --- | --- | --- | --- |
| 1、7、15 | 执行 | 执行 | 执行 | 执行 |
| 17、1003 | 执行 | **N/A**：`gcd(17, N) != 1` | 执行 | 执行 |

因此 `(stride17, N=17)` 和 `(stride17, N=1003)` 不生成、不运行且不记为 `PASS`；正确性报告必须写为 `N/A (gcd(17, N) != 1)`。其余三种模式负责覆盖这两个尺寸的 AVX-512 tail 路径和边界安全。113 个 dense 主尺寸已由结构断言保证与 17 互素，仍完整执行四种 indexed 模式。

## Working Set 与逻辑字节

| 算子 | 首轮 working set | 每次算子的 logical bytes |
| --- | ---: | ---: |
| Reduce | `4N` | `4N + 4`，读取输入并写一个 FP32 标量 |
| Softmax | `8N` | `20N`：max 读 `4N`，exp+sum 读写 `8N`，normalize 读写 `8N` |
| Gather indexed | `4M + 4K + 4K`，本轮为 `12N` | `12K`：index 读、table 逻辑读、out 写 |
| Gather contiguous | `4N + 4N = 8N` | `8N`：table 连续读、out 连续写，不含 index |
| Scatter indexed | `4K + 4K + 4M`，本轮为 `12N` | `12K`：index 读、src 读、dst 写 |
| Scatter contiguous | `4N + 4N = 8N` | `8N`：src 连续读、dst 连续写，不含 index |
| FMA reuse | `4N` | `8N`：每个元素一次加载和一次写回，计算阶段执行 64 轮 FMA |
| FMA once | `16N` | `16N`：a、b、c 三路读取和 output 一路写回，每个元素一次 FMA |

`logical bytes` 是算子语义和已冻结 pass 结构产生的逻辑流量，不等于硬件总线流量；不额外估算 write-allocate、cache line 过取、页表访问或预取。最终报告不得把逻辑 GB/s 描述成实测 DRAM 带宽，也不得把 contiguous 虚计为 `12N`。indexed 和 contiguous 在相同 `N` 下的比值同时包含 index 流和指令语义差异，不能称为纯 SIMD speedup。

结果 counter ID 冻结如下：`implementation_id=0` 表示 scalar，`1` 表示 indexed AVX-512（Gather 为 `vgather`、Scatter 为 `vscatter`），`2` 表示 contiguous AVX-512 load/store；`pattern_id=0..3` 保持现有四种 indexed pattern，`pattern_id=4` 表示 contiguous，FMA `reuse/once` 使用 `pattern_id=0/1`。contiguous 必须使用独立 runner，不能复用会分配 index 的 indexed runner。

## 计时边界与指标

### 不计时内容

- 内存分配、释放和首次触页。
- 输入、输出和索引生成。
- 参考结果计算和正确性检查。
- benchmark 注册、case 选择和日志输出。
- 每个 case 的显式 warmup。

### 计时内容

- 仅被测 kernel 调用及不可避免的调用/循环控制开销。
- core-cycle 计数器在正式 Google Benchmark 循环前立即 reset/enable，在循环后立即 disable/read。
- 每个 case 在正式计时前至少执行一次完整的非计时 warmup；warmup 参数和次数写入结果元数据。

### Inner passes

为避免小尺寸被框架和函数调用开销主导，每个 Google Benchmark iteration 内重复执行：

```text
inner_passes = max(1, ceil(2^15 / logical_elements_per_operation))
```

Reduce/Softmax 的 `logical_elements_per_operation = N`，Gather/Scatter 为 `K`。同一 case 的 scalar 和 AVX-512 使用相同 `inner_passes`。Scatter 重复写相同的唯一目标集合，结果解释为稳态 kernel 吞吐，不解释为首次冷写延迟。

### 指标定义

设 `I` 为 Google Benchmark iterations，`P` 为 inner passes：

```text
processed_elements = I * P * N               # Reduce/Softmax
processed_elements = I * P * K               # Gather/Scatter
elem/core_cycle    = processed_elements / user_core_cycles
ns/element         = timed_wall_ns / processed_elements
logical_GB/s       = I * P * logical_bytes_per_operation / timed_wall_seconds / 1e9
```

- `Softmax processed_elements` 只按输入元素计一次，不按三个阶段重复计数。
- `core_cycles` 使用当前线程、用户态硬件 core cycles，不使用参考 TSC cycles 替代。
- `items/s` 使用 Google Benchmark 的 `SetItemsProcessed(processed_elements)`。
- 每条原始结果同时记录 `elements`、`working_set_bytes`、`inner_passes`、`logical_bytes`、`core_cycles`、实现和索引模式。
- 若 in-process core-cycle 计数不可用，则主测试停止；不能只用 wall time 伪造 `elem/core_cycle`。

## 运行环境、绑核与 NUMA

仓库中的 `docs/cpu-info.md` 记录的是先前环境，且历史结果来自 `node042`；审核本计划时的 shell 位于 `node041`。执行时不得复制旧环境元数据，必须在真正运行前重新采集：

- 日期、hostname、kernel、CPU 型号和 microcode（若可读）。
- socket/core/thread/NUMA/cache 拓扑和 CPU online 状态。
- compiler、CMake、Google Benchmark、SLEEF 版本及完整编译参数。
- CPU governor、boost 状态和可读的频率信息。
- git commit、submodule commit 和完整 `git status --short`。

首轮只使用 node 0 的物理 CPU 8，并确保其 SMT sibling CPU 200 不承担并发任务。执行前必须重新确认 CPU 8/200 的 core、socket 和 NUMA 关系没有变化。运行形式为：

```bash
numactl --physcpubind=8 --membind=0 <benchmark-command>
```

分配、初始化和首次触页必须发生在上述绑定生效后。最终报告记录 CPU 8、core、SMT sibling 200、NUMA node 和完整命令。首轮不修改系统频率、governor、boost 或 BIOS 设置；如环境噪声无法控制，应停止并报告，而不是做未授权的系统变更。

### 可归因运行环境门禁

下列门禁用于未来正式重采，并替代旧的“出现任何全局 swap 即停止”规则。监控必须覆盖每个正式 benchmark binary 的完整进程窗口；系统指标在进程前后采样，并在进程存活期间至少以 1 Hz 采样。每完成一个算子的正式 binary，必须先检查并记录全部门禁，再开始下一个算子。

#### 进程级门禁

每个 Softmax、Reduce、Gather、Scatter 正式 benchmark binary 都按以下顺序运行：

1. 在相同 CPU/NUMA 绑定下先运行一次不计入正式结果的 warm invocation。
2. 正式进程使用 `/usr/bin/time -v` 记录资源信息；必要时使用 `getrusage(RUSAGE_SELF)` 在正式计时区间前后补充进程内采样。
3. 将 `time -v` 原始输出和任何 `getrusage` 采样写入新的正式结果目录，不只保留汇总值。

正式进程必须同时满足：

- `Major (requiring I/O) page faults = 0`。任何 major page fault 都使该正式 binary 的结果失效；minor page faults 仅记录，不设失败阈值。
- 进程 CPU 利用率 `(user_time + system_time) / elapsed_time >= 95%`。
- 记录 voluntary 和 involuntary context switches；若 CPU 利用率不达标或观察到 CPU 8/200 竞争，则停止当前正式 binary。Context-switch 数值本身用于诊断，不单独设置未经校准的硬阈值。

#### 系统级门禁

每个正式 binary 的监控窗口必须同时满足：

```text
delta_pswpout == 0
delta_memory_psi_full_total == 0
delta_memory_psi_some_total / window_elapsed_us <= 0.001
min_MemAvailable >= max(0.10 * MemTotal, 8 GiB)
start_MemAvailable - min_MemAvailable <= 0.05 * MemTotal
procs_running <= 4
```

- PSI 原始值读取 `/proc/pressure/memory`；`0.001` 对应窗口时间的 `0.1%`。
- `MemAvailable` 和 `MemTotal` 使用同一窗口内 `/proc/meminfo` 的值。
- `procs_running <= 4` 必须对每个 1 Hz 样本成立。
- 整机非 idle CPU 比例不得连续 5 个 1 Hz 样本高于 10%；短于 5 秒的尖峰保留记录，并结合进程 CPU 利用率和原 CV 规则判断。
- CPU 8 必须只运行本轮绑定进程和不可避免的内核工作，CPU 200 不得存在竞争性任务；监控中发现其他 runnable 用户任务占用 CPU 8/200 时，当前正式 binary 失效。

#### 全局 `pswpin` 记录与护栏

全局 `pswpin` 不再要求增量为 0。每个正式 binary 必须记录 `/proc/vmstat` 中 `pswpin` 的起始值、结束值、增量、系统 page size、换入字节数、窗口时长和平均速率：

```text
global_pswpin_rate = delta_pswpin * system_page_size / window_elapsed_seconds
global_pswpin_rate <= 1 MiB/s
```

若进程 major page faults 为 0 且其他全部硬门禁通过，非零的全局 `pswpin` 只在报告中标为 `advisory`，不使该 binary 失效。若平均速率超过 `1 MiB/s`，则视为持续系统分页噪声并停止当前正式 binary。若采样时间戳能证明增量发生时本项目 PID 不存在，应明确记录为外部活动，但仍保留原始计数。

### 已有批次处置与未来正式重采

- 第一批 `ops_fp32_20260714-152755` 完整包含 198 个主性能 case，但因 CPU 争用而正式失效，不作为正式性能结果。第三次补充批准只允许将它作为本次 `exploratory canonical` 数据源，不改变其正式失效状态。
- 第二批 `ops_fp32_20260714-155323` 不完整，并按旧的全局 swap 规则停止，只作诊断资料，不作为正式或探索性 canonical 数据源。
- 第三批 `ops_fp32_20260714-161522` 只作诊断资料，不作为正式或探索性 canonical 数据源。
- 第一、第二、第三批不得合并为更多 repetitions，不得逐 case 择优，也不得拼接成正式或探索性结果。
- 未来正式采集必须创建新的 `ops_fp32_<YYYYMMDD-HHMMSS>` 目录，按当前 dense 规格完整重采全部 2,938 个主性能 case。五个算子都必须重新采集，不复用上述三个批次的数据。
- 未来正式采集每完成一个算子，立即检查该 binary 的进程级、系统级和 `pswpin` 门禁。未通过的原始输出保留为诊断并明确标记 invalid；修复环境后重新采集该算子，只有五个算子都通过门禁后，该新批次才能作为正式结果。

### 第三次批准的 sparse 探索性输出例外

第三次补充批准允许直接使用 `ops_fp32_20260714-152755` 的既有 198 个 case 生成探索性 MD、SVG 和 summary，不要求为该输出重新运行 benchmark。此授权仅用于尽快观察已有测试的相对趋势，并遵守以下限制：

- 第一批仍为“正式失效”，但可作为本次唯一的 `exploratory canonical`；第二、第三批仍只作诊断。
- 已知第一批环境受到外部 Java/ZGC 活动和 CPU 争用干扰，也不满足后来冻结的完整运行门禁。因此探索性结果不得用于绝对性能、跨机器比较、性能回归、容量规划、硬件上限或正式验收结论。
- 允许讨论同一批内随尺寸/索引模式变化的相对趋势，以及 scalar/AVX-512 speedup；所有表格和相关结论必须同时给出 CV，`CV > 5%` 的 case 必须醒目标记为 `UNSTABLE`。
- 探索性模式下 `CV > 5%` 不触发重跑，只作不稳定标记；正式模式下原有 CV 门禁和一次重跑规则保持不变。
- 本次不要求补跑 `perf stat`，必须在 summary 中写明 `perf stat: skipped in exploratory mode`，不得用估算值填充硬件计数器。
- 不得从第二、第三批补缺或选择更好数值，也不得将多个批次合并。

所有探索性 MD 和 summary 的标题或首屏必须包含以下等价且醒目的声明，不得只放在脚注。SVG 根据当前用户批准的展示修订只保留简洁算子标题，风险声明由同目录 MD、summary、validation、commands 和 provenance 承担：

```text
EXPLORATORY / NON-FORMAL
数据来自正式失效的 ops_fp32_20260714-152755，环境受外部 Java/ZGC 和 CPU 争用干扰。
结果仅供相对趋势观察，不可用于绝对性能、跨机器比较或性能回归结论。
```

### 第四次批准的 dense 探索性运行

用户当前消息已经批准实现并运行 113 点 dense sweep，不需要再次审核。该运行使用新的时间戳目录和新生成的 2,712 个 case，不从前三批补数，也不覆盖第三次批准生成的 sparse 探索报告。

- 仍建议绑定 CPU 8/node 0，但本次明确不执行“可归因运行环境门禁”，不因外部 Java/ZGC、全局 swap、CPU 争用或 `CV > 5%` 停止 dense run。
- `CV > 5%` 不重跑，只在表格、图和 summary 中标记 `UNSTABLE`；所有 scalar/AVX-512 speedup 和相对趋势必须附带两侧 CV/不稳定状态。
- 本次不运行 `perf stat`，summary 固定记录 `perf stat: skipped in exploratory dense mode`。
- 语义门禁不豁免：113 尺寸结构断言、新 contiguous correctness、case/curve 完整性和反汇编指令检查必须通过，否则测量对象可能与批准语义不同。
- 所有 dense MD 和 summary 的标题或首屏必须标记 `EXPLORATORY / NON-FORMAL`，并声明环境可能受外部 Java/ZGC 和 CPU 争用干扰；不得用于绝对性能、跨机器、回归、容量、硬件上限或正式验收结论。SVG 只展示简洁算子标题，不重复环境警告或主机信息。

### 第五次批准的 FMA 扩展

用户随后批准将 FMA 纳入同一 dense suite，不改变前四个算子的既有语义和尺寸矩阵：

- 新增 `fma/reuse/avx512` 与 `fma/once/avx512` 两条 113 点曲线，分别使用 64 轮复用和单次 `a*b+c`。
- 新增 `fma_fp32.json`、`fma_fp32.md`、`fma_fp32.svg`，并纳入同一 `commands.log`、`summary.md`、`validation.md` 和 `provenance.json`。
- 完整 dense suite 变为 26 条曲线、2,938 cases、20,566 raw repetition rows；FMA 以 `flop/core_cycle` 作为主要计算吞吐指标。
- correctness 和反汇编门禁必须覆盖 FMA 两条内核；探索性运行仍不运行正式 runtime gate 或 `perf stat`。

## 重复次数与统计口径

主性能采集固定使用：

```text
--benchmark_min_time=0.25s
--benchmark_repetitions=7
--benchmark_enable_random_interleaving=true
```

- JSON 保留 7 次原始 repetition 和 Google Benchmark 聚合行。
- 正式结论使用 7 次 repetition 的 median。
- 同时报告 min、mean、standard deviation 和 `CV = stddev / mean`。
- scalar/AVX-512 speedup 使用对应 case 的 median 相除，不使用各自 min 拼接。
- `CV <= 5%` 视为稳定。若 `CV > 5%`，先检查绑核、系统负载和热状态，再完整重跑该 case 一次；第二轮仍超过 5% 时标记为 unstable，不给出确定 speedup 结论。
- 不因结果“不好看”删除 repetition；任何排除项必须在 summary 中列出原始值和排除理由。
- 上述重跑规则用于未来正式采集。本次已批准的探索性输出不重跑 `CV > 5%` case，只报告原始 CV 并标记 `UNSTABLE`。

## 代表性 `perf stat` 诊断

`perf stat` 只作为解释主结果的辅助信息，不替代 in-process core-cycle 指标。只诊断 AVX-512 实现，代表长度为：

```text
4K, 256K, 16M, 64M
```

诊断范围：

- Softmax：4 个尺寸。
- Reduce：sum/max 各 4 个尺寸。
- Gather：仅 `sequential` 和 `uniform_random`，各 4 个尺寸。
- Scatter：仅 `sequential` 和 `uniform_random`，各 4 个尺寸。

执行前先用 `perf list` 确认本机 AMD PMU 支持情况。候选事件包括：

- cycles、instructions 和 IPC。
- cache references/misses。
- L1 data cache loads/misses。
- LLC loads/misses。
- dTLB loads/misses。

事件按小组分开采集，避免过度 multiplex；每组使用 3 次重复并报告实际 `time enabled/time running`。不支持或无法授权的事件必须标记 unavailable，不得填 0。外部 `perf stat` 会包含少量进程设置开销，因此只作方向性诊断；代表 workload 应运行足够长，使设置开销相对可忽略，并在报告中保留这一限制。

以上 `perf stat` 方案保留给未来正式采集。第三次 sparse 探索输出不补跑 `perf stat`，summary 记录 `perf stat: skipped in exploratory mode`；第四次 dense run 同样不运行，记录 `perf stat: skipped in exploratory dense mode`。

## 正确性门禁

所有性能 case 在正式采集前必须通过相同语义的非计时正确性检查。参考输入固定且可复现。阈值不能根据性能结果临时放宽。

第四次 dense run 不对全部 113 个尺寸重复昂贵的 double correctness oracle。数值 correctness 继续覆盖现有 5 个 tail-only 尺寸和原 9 个 sparse 性能锚点；另行验证 113 尺寸表的数量、边界、顺序、唯一性、16 元素对齐、全部 2 次幂锚点及 `gcd(17,N)==1` 断言。Gather/Scatter correctness 必须在现有 correctness 尺寸上增加 contiguous kernel，并分别与 `out[i]=table[i]`、`dst[i]=src[i]` 参考结果做 FP32 bitwise 比较。反汇编门禁独立于数值准确性，第四次探索运行也必须执行。

### Reduce

- `max`：对当前有限普通值输入与 scalar 参考进行 FP32 精确比较。
- `sum`：double 顺序求和作为参考，同时计算 `sum_abs = sum(abs(x[i]))`。要求：

```text
abs(fp32_result - double_reference) / max(sum_abs, 1.0) <= 5e-6
```

最终报告同时给出绝对误差、相对参考值误差和上述归一化误差。若确定性输入导致参考值接近 0，不能只使用普通 relative error 判断。

### Softmax

double 稳定 softmax 作为参考。每个输出必须 finite 且非负，并同时满足：

```text
max_abs_error                  <= 2e-6
sum(abs(y - reference))        <= 5e-4
abs(double_sum(y) - 1.0)       <= 5e-4
```

报告三项实际最大值。以上阈值同时考虑 SLEEF `u10` 的逐元素误差和 FP32 归约顺序差异，不允许用低精度 `exp` 来换取性能。

### Gather

逐元素与 scalar 参考进行 FP32 bitwise 比较；所有 `index` 必须在范围内。任一元素错误即失败。

### Scatter

`dst` 预先填入确定性 sentinel。完成后对完整 `dst[0..M)` 与 scalar 参考做 FP32 bitwise 比较，同时验证索引唯一性和范围。任一元素错误、遗漏写或越界即失败。

### 阈值变更原则

若任何实现未通过阈值，先检查 tail、归约树、输入构造和参考实现。相关算子不得进入正式性能采集。若最终判断阈值或输入需要调整，必须更新本文档、说明数值依据并再次获得用户批准，不能在执行阶段静默修改。

## 输出目录和报告

每次正式运行创建独立目录，禁止覆盖已有结果：

```text
gbench-test/results/ops_fp32_<YYYYMMDD-HHMMSS>/
  environment.md
  commands.log
  correctness.md
  softmax_fp32.json
  softmax_fp32.md
  softmax_fp32.svg
  reduce_fp32.json
  reduce_fp32.md
  reduce_fp32.svg
  gather_fp32.json
  gather_fp32.md
  gather_fp32.svg
  scatter_fp32.json
  scatter_fp32.md
  scatter_fp32.svg
  runtime-gates/
  perf-stat/
  summary.md
```

本次探索性输出必须使用与正式目录名称明显不同的新目录，且不得修改或覆盖第一批原始数据：

```text
gbench-test/results/exploratory_ops_fp32_20260714-152755_<YYYYMMDD-HHMMSS>/
```

第四次批准的 dense run 使用另一个全新目录，不得覆盖上述 sparse 探索目录、前三批原始目录或未来正式目录：

```text
gbench-test/results/exploratory_ops_fp32_dense_<YYYYMMDD-HHMMSS>/
```

`runtime-gates/` 保存五个正式 binary 的 warm/formal 标识、`time -v` 原始输出、进程 fault/context-switch 数据、1 Hz 系统采样、PSI、MemAvailable、CPU 竞争和 `pswpin/pswpout` 起止值。必要时可增加机器可读的 `environment.json` 和 `correctness.json`，但不得省略上述人类可读文件。`commands.log` 记录可重现的构建和运行命令，不记录密钥或无关环境变量。

`summary.md` 至少包含：

- 本计划版本和执行批准信息。
- 主机、CPU、NUMA、绑核、SMT sibling、编译器、flags、依赖版本和 git 状态。
- 第一批 `ops_fp32_20260714-152755` 因 CPU 争用正式失效但经第三次补充批准成为 exploratory canonical、第二批 `ops_fp32_20260714-155323` 不完整、第三批 `ops_fp32_20260714-161522` 仅诊断的处置；明确三个批次均未升级为正式结果且未合并。
- 未来正式批次每个 binary 的 warm 状态、major/minor faults、CPU 利用率、context switches、`pswpout`、memory PSI、MemAvailable、`procs_running`、整机 CPU、CPU 8/200 竞争检查以及全局 `pswpin` 起止值和速率。非零但通过门禁的 `pswpin` 标记为 advisory。
- 五个算子的精确定义、实现差异、输入构造、SLEEF `u10` 入口、FMA 轮数和正确性结果。
- 各 case 的 median、min、CV、`elem/core_cycle`、`ns/element`、logical GB/s 和 scalar/AVX-512 speedup。
- 按 working set 和索引模式绘制的曲线，以及可证据支持的 cache/内存拐点分析。
- `perf stat` 的可用事件、不可用事件、multiplex 情况和方向性解释。
- unstable、失败、跳过和重跑 case 的完整列表。
- logical bytes 与实测 DRAM bytes 的区别、外部 `perf stat` 设置开销等限制。

第三次批准的 sparse 探索性 summary 以对应例外中的三行声明开头，并额外包含：外部 Java/ZGC 和 CPU 争用干扰、绝对性能/跨机器/回归禁用范围、每个 case 的 CV 与 `UNSTABLE` 标记、仅使用第一批的证明，以及 `perf stat: skipped in exploratory mode`。探索性 MD 必须在标题或首屏显示 `EXPLORATORY / NON-FORMAL`；SVG 根据当前展示修订只保留简洁算子标题。

第四次 dense 报告还必须满足：

- 校验并报告 24 条曲线、每条 113 个 unique N、共 2,712 cases 和 18,984 raw repetition rows；缺失或重复时报告生成失败，不能静默画残缺曲线。
- Gather/Scatter 主图使用 `N` 的 log2 x 轴，以便在相同 N 比较 `12N` indexed 和 `8N` contiguous；表格继续列出每条曲线的真实 working set 和 logical GB/s。需要时可另绘 working-set 图，但不能用错位的 working-set x 轴读取同 N 比值。
- Gather/Scatter 以 pattern 区分颜色、implementation 区分线型；稳定点不额外绘制 marker，只绘制 `CV > 5%` 的空心 `UNSTABLE` 点，避免 9 条曲线、1,017 个点互相遮挡。
- scalar speedup 只配对同一 indexed variant 的 `scalar` 与 `avx512_vgather`/`avx512_vscatter`。contiguous 不显示“AVX speedup”；如报告其与 indexed SIMD 的比值，名称必须是 `contiguous/indexed-SIMD throughput ratio`，并注明它同时移除了 index 流且 logical bytes 为 `8N` 对 `12N`。
- summary 记录整数尺寸公式、ID 映射、indexed sequential 强制 gather/scatter、contiguous 普通 load/store、反汇编证据、各算子实际耗时、不稳定 case 数，以及 `perf stat: skipped in exploratory dense mode`。

第五次 FMA 扩展还必须满足：

- 校验并报告 26 条曲线、每条 113 个 unique N、共 2,938 cases 和 20,566 raw repetition rows。
- FMA 报告同时列出 `reuse`/`once` 的 FMA rounds、`elem/core_cycle` 和 `flop/core_cycle`；`flop/core_cycle` 为主要计算吞吐指标。
- FMA correctness 覆盖 tail 和代表性对齐尺寸，反汇编必须确认两条内核包含 AVX-512 `vfmadd*ps`。

## 预计资源开销

第四次 dense 主矩阵共 2,712 个 case。按 7 repetitions 和每次至少 0.25 秒计算，纯计时理论下限为：

```text
Reduce:  452 * 7 * 0.25s =  791.00s，约 13.2 分钟
Softmax: 226 * 7 * 0.25s =  395.50s，约  6.6 分钟
Gather: 1017 * 7 * 0.25s = 1779.75s，约 29.7 分钟
Scatter:1017 * 7 * 0.25s = 1779.75s，约 29.7 分钟
Total:  2712 * 7 * 0.25s = 4746.00s，即 79 分 06 秒
```

79 分 06 秒只是 kernel min-time 下限，不是完成时间。large case 的一次迭代可能超过 0.25 秒，而且每个 repetition 会重新分配、填充并为随机 pattern 执行 Fisher-Yates shuffle；外部 Java/ZGC/CPU 争用还可能增加 wall time。本次 dense 探索运行预计 2-4 小时，极端情况下可能更久。不得为了缩时擅自减少 repetitions、降低 min-time，或把 `uniform_random` 换成计算式伪置换，否则会改变已经批准的曲线语义和可比性。

64M FP32 或 `uint32_t` 数组各约 256 MiB。Scatter 完整参考校验以及 Softmax double 参考可能同时需要额外缓冲，计划峰值内存约 1-1.5 GiB。执行前必须检查可用内存和结果目录空间；不得依赖 swap 完成测试。

第五次扩展新增 FMA 的理论计时下限为 `226 * 7 * 0.25s = 395.50s`，即约 6 分 35 秒；完整五算子 dense suite 的理论下限约为 85 分 41 秒。FMA reuse 的高算术强度通常会使大尺寸迭代明显超过 min-time，实际运行仍预计 2-4 小时或更久。

## 实施顺序

### 第三次批准的 sparse 探索性输出

1. 确认第三次补充批准已记录，只读取 `ops_fp32_20260714-152755` 的既有 198 个 case。
2. 在新的 `exploratory_ops_fp32_20260714-152755_<YYYYMMDD-HHMMSS>` 目录生成 MD、SVG 和 summary，不重新运行 benchmark 或 `perf stat`。
3. 为 MD、summary、validation、commands 和 provenance 加入 `EXPLORATORY / NON-FORMAL`、Java/ZGC/CPU 干扰和禁用范围声明；SVG 只保留简洁算子标题；报告 CV，并将 `CV > 5%` 标为 `UNSTABLE`。
4. 验证没有使用第二、第三批数据，没有覆盖任何正式或原始结果目录。

### 第四次批准的 dense 探索性运行

1. 当前用户消息即为执行批准；先更新实现和 `gbench-test/README.md`，无需再次请求审核。
2. 用固定整数模板生成并断言 113 个尺寸，增加两个独立 contiguous runner/kernel、明确 implementation/pattern ID，并扩展现有 correctness。
3. 构建后检查 indexed sequential 强制 `vgatherdps`/`vscatterdps`，contiguous 为普通 AVX-512 load/store 且没有 copy 库调用。
4. 在新的 `exploratory_ops_fp32_dense_<YYYYMMDD-HHMMSS>` 目录按 7 repetitions、0.25 秒 min-time 运行全部 2,712 cases；不运行正式 runtime gate 或 `perf stat`，不中途因环境噪声/CV 停止。
5. 生成适配 24 条 dense 曲线的 MD、SVG 和 summary，校验 18,984 raw repetition rows，标记所有 `CV > 5%` case 为 `UNSTABLE`；非正式环境声明保留在 MD、summary、validation、commands 和 provenance 中，SVG 只展示简洁算子标题。
6. 验证新目录没有覆盖 sparse 探索结果、前三批原始结果或未来正式目录。

### 第五次批准的 FMA 扩展

1. 在现有 `ops_common` 公共框架中注册 `fma/reuse/avx512` 和 `fma/once/avx512` 两条 113 点曲线。
2. 执行 FMA correctness、反汇编和 dense benchmark-list 门禁，并将 FMA 纳入同一串行采集脚本。
3. 在同一结果目录生成 `fma_fp32.json`、`fma_fp32.md`、`fma_fp32.svg`，更新综合 summary、validation、commands 和 provenance。

### 未来正式采集

1. 保留并执行本文“可归因运行环境门禁”，记录初始 git/submodule 状态和当前主机环境，确认 node 0 CPU 8 及其 SMT sibling CPU 200。
2. 检查反汇编、计数公式、正确性、绑核、NUMA first-touch 和一个代表 case 的 smoke 结果。
3. 新建正式时间戳目录；对每个 benchmark binary 先 warm，再以 `/usr/bin/time -v` 和 1 Hz 系统监控按当前 dense 规格完整重采 2,712 个主性能 case，并在每个算子后立即检查运行环境门禁。
4. 对通过门禁的正式结果分析 repetition 稳定性，并按原 CV 规则处理一次必要重跑。
5. 对代表 AVX-512 case 运行分组 `perf stat` 诊断。
6. 生成不覆盖历史结果的 JSON、Markdown、SVG、运行门禁日志和正式总览报告，由规划/审核方复核语义与结论。

## 失败与停止条件

以下条件适用于未来正式采集，并继续完整保留。第三、第四次补充批准只对各自的探索性报告/运行豁免已知 CPU 争用、swap/PSI 记录、`CV > 5%` 重跑和探索模式明确跳过的 `perf stat`，不得据此把探索性结果改称正式结果。第四次 dense run 仍必须通过尺寸结构、correctness、反汇编和 case 完整性语义门禁。正式采集满足任一条件时按下述规则停止，不得用未记录的替代方案继续：

- 用户尚未再次明确批准：不得开始任何实现或执行。
- scalar/AVX-512 反汇编不符合基线：停止相关算子，修正后重新做正确性。
- SLEEF 固定 `u10` 入口不可用：停止 Softmax，不切换数学实现。
- in-process user core cycles 不可用：停止主性能测试。
- 绑核、SMT 隔离或本地 NUMA 内存绑定无法确认：停止正式采集。
- 正确性失败：停止相关算子的性能采集；阈值变更需要重新审批。
- `CV > 5%`：环境检查后只允许自动完整重跑一次；仍不稳定则标记 unstable 并停止对该 case 下确定结论。
- `perf stat` 事件不支持或权限不足：主性能结果可继续，但跳过对应辅助事件并明确记录，不得伪造数值。
- 正式 benchmark binary 未先 warm，或未保存 `/usr/bin/time -v`/必要的 `getrusage` 和系统监控原始记录：该 binary 不得作为正式结果。
- 进程 major page faults 非 0，或进程 CPU 利用率低于 95%：停止当前 binary 并标记其结果 invalid；minor faults 仅记录。
- `delta_pswpout != 0`、memory PSI `delta_full_total != 0`，或 `delta_some_total / window_elapsed_us > 0.001`：停止当前 binary。
- 最小 `MemAvailable` 低于 `max(10% MemTotal, 8 GiB)`，或相对起点下降超过 `5% MemTotal`：停止当前 binary。
- 任一 1 Hz 样本 `procs_running > 4`、整机非 idle CPU 连续 5 秒高于 10%，或 CPU 8/200 存在竞争性任务：停止当前 binary。
- 全局 `pswpin` 平均速率超过 `1 MiB/s`：停止当前 binary；速率未超限且其他硬门禁通过时，非零增量只记 advisory，不得单独判失败。
- 出现 thermal/frequency 异常或内存不足：停止受影响的正式运行并保留诊断信息。
- 第一、第二、第三批及第四次 dense 探索结果均不得升级为正式结果；未来正式批次未按当前 dense 规格完整重采 2,712 个 case，或任一算子未通过上述门禁：不得发布正式性能结论。

## Dirty Worktree 保留原则

当前 worktree 已存在与本计划无关的 `third_party/onednn` 修改。该修改视为用户资产，执行过程中必须：

- 在开始和结束时记录 `git status --short` 及相关 submodule 状态。
- 不执行 `git reset --hard`、`git checkout --`、`git clean` 或其他回退/清理命令。
- 不修改、还原或覆盖 `third_party/onednn` 的现有状态。
- 不覆盖已有 `gbench-test/results` 文件，正式输出使用带时间戳的新目录。
- 若后续发现用户改动与本轮必须修改的文件重叠，先停止并请求用户决定，不自行合并或丢弃改动。

本文档获批后，执行 Agent 的授权范围仍仅限本轮所需 benchmark、公共辅助代码、构建入口、结果转换/绘图以及新的时间戳结果目录；无关重构不在授权范围内。
