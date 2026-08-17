# Kernel 测试规范

本文规定在 `softmax_sim_avx512` 中新增和验证计算 kernel 的统一流程。目标是让
真机周期、模拟器周期和 uop 调度结果可以相互追溯，而不是只比较一个最终数字。

## 1. 添加 kernel test 的基本流程

### 1.1 先评估 uop 覆盖，再编写 kernel

新增 kernel 的第一步不是直接编写 C++，而是列出算子预计需要的语义动作：

```text
load / store / address_generation
vector_fp_add / vector_fp_mul / vector_fp_fma
vector_reduce_add / vector_reduce_max
vector_convert / vector_integer / vector_shift
vector_shuffle / vector_broadcast
```

然后按以下顺序检查：

1. `uops/uop_kinds.yaml` 是否已有对应的跨 ISA semantic uop；
2. `recipes/x86.yaml` 和 `recipes/rvv.yaml` 是否能把目标 ISA 指令映射到这些
   semantic uop；
3. `profiles/amd_zen4.yaml` 是否有对应 instruction recipe、execution resource、
   latency、issue interval、occupancy 和必要的 issue domain；
4. 当前前端是否能够解析该指令的操作数、寄存器依赖、内存依赖和控制流；
5. `src/simulator` 是否能用通用 uop 完成绑定、依赖检查和事件调度。

如果缺少语义能力，应先添加 `uops/uop_kinds.yaml` 条目；如果只是某个 ISA 的
指令表达方式缺失，应添加对应 `recipes/*.yaml` 条目；如果缺少 Zen 4 时序，才
添加 profile recipe 或待校准参数。不能把 ISA mnemonic 直接写进模拟器后端，也
不能为了让某一个 kernel 的周期吻合而修改已有 profile 参数。

例如，计划添加 conversion kernel 时，应先确认：

- `vector_convert` 已存在于 semantic catalog；
- x86 的 `vcvttps2dq`、`vcvtdq2ps` 或实际生成的其他 conversion 指令有 recipe；
- Zen 4 profile 有 `conversion` resource、容量和 issue domain；
- 512-bit conversion 的两个 256-bit part、依赖和 part gap 能被 binder 表达。

如果编译器生成了 catalog 或 recipe 尚未覆盖的指令，测试必须先停在“uop 覆盖缺口”
阶段，不能静默映射成普通 ALU 或使用未审核的默认延迟。

### 1.2 按现有 kernel 结构实现算子

每个 kernel 建议使用独立目录：

```text
kernel/<kernel_name>/
├── common/                 # ISA 共用接口、常量和必要的近似函数
├── reference/              # 高精度或标量参考实现
├── x86/                    # AVX-512 kernel
├── rvv/                    # RVV kernel
├── benchmarks/             # 真机周期 benchmark
├── tests/                  # 功能正确性测试
├── scripts/                # 编译、测量、trace 和比较脚本
├── workloads/              # N、数据布局和 cache 初始状态
└── artifacts/              # 汇编、trace、测量原始数据和元数据
```

x86 和 RVV 应保持相同的算法语义、数据类型、输入规模和误差口径。第一批纯向量
kernel 的统一 API 约束为 `count > 0` 且 `count % 16 == 0`；其他长度必须由调用方
补齐或由后续单独的 tail wrapper 处理。ISA 特定的向量宽度、VL、寄存器名和
lowering 细节放在各自实现及 recipe 中。

### 1.3 先做功能正确性验证

在周期测试前，分别验证：

- reference 与 x86 AVX-512 输出；
- reference 与 RVV 输出；
- 向量实现与同一近似算法 reference 的误差；
- 边界长度、对齐/非对齐地址和必要的尾部处理。

功能错误不能通过调整 profile 修正。只有功能正确且生成汇编稳定后，才进入周期
验证。

### 1.4 生成汇编和 semantic uop trace

模拟器当前以汇编为输入，不解析二进制机器码。应固定记录：

- 编译器名称和完整版本；
- 编译 flags、目标 ISA 和微架构选项；
- 汇编文件 hash；
- recipe 和 uop catalog hash；
- kernel 函数符号和动态展开规模。

典型流程是：

```text
kernel source
  -> x86/RVV compiler
  -> .s assembly
  -> ISA recipe parser
  -> semantic uop trace
  -> profile binding
  -> execution-uop DAG
```

缺少 recipe、未知 semantic kind、无法解析的操作数或无法建立依赖时应硬错误。

### 1.5 在真机 AVX-512 上测量

对 x86 kernel 使用与生成汇编相同的编译产物，在目标 AMD Zen 4 真机上运行：

1. 固定 CPU affinity 和 NUMA node；
2. 尽可能隔离 SMT sibling 和系统干扰；
3. 使用序列化计时，并减去同结构空函数基线；
4. 对每个规模重复多次，记录 median、p10/p90 和异常值；
5. 同时采集 instructions、branches、cache 访问等 PMU 信息；
6. 明确 cache 初态：`hot-l1`、`hot-capacity` 或 `cold`；
7. 保存环境、原始测量和汇总结果到 kernel artifact。

FMA throughput、FMA latency 等 microbenchmark 应用不同的指令依赖结构分别测量，
不能把独立累加器和单链累加器混成一个结果。

### 1.6 在模拟器上运行

模拟器使用与真机相同的汇编和 kernel 规模，通过 profile 绑定后的通用 execution
uop 调度：

```text
assembly
  -> dynamic semantic trace
  -> amd_zen4 profile binding
  -> out_of_order / in_order event backend
  -> cycles, events, resource and dependency reports
```

至少运行：

- `out_of_order`：当前主要模型；
- `in_order`：用于观察乱序调度收益和依赖瓶颈；
- 与真机相同的 cache 模式；
- 与真机相同的 N、数据布局和调用范围。

当前 simulator CLI 的周期入口是 x86；RVV 汇编可以先做功能/静态 trace 验证，
只有接入 RVV 动态前端和目标 RVV profile 后，才进行有意义的 RVV 周期比较。

### 1.7 比较周期和误差

比较不应只看总周期，还应对齐以下项目：

| 比较项 | 目的 |
|---|---|
| 总 cycles | 判断模型是否达到整体精度目标 |
| cycles/element | 消除不同 N 对绝对周期的影响 |
| instruction count | 检查编译器是否改变了 kernel 结构 |
| semantic/execution uop count | 检查 recipe 和 decomposition 是否一致 |
| dependency critical path | 区分依赖延迟和资源竞争 |
| resource issues | 检查资源分配是否符合预期 |
| cache hits/misses | 检查 cache 初态和访存工作集 |
| queue peak | 检查 ROB、vector scheduler、LQ、SQ 是否达到容量瓶颈 |

首轮验收建议使用稳态规模的相对周期误差作为主指标。当前 Softmax 首轮报告对
`N=128..2048` 使用 10% 量级阈值；小规模 kernel 应单独标记为诊断点，不能用启动、
dispatch 和 retire 固定开销直接推断稳态吞吐。

当前新增 kernel 的统一验证矩阵为 `N=512/1024/2048`，三档均使用
`hot-l1`。不使用 `N=256` 的固定开销诊断点，也不使用 `N=4096` 的
L1/L2 容量边界点。

### 1.8 偏差较大时的排查顺序

当真机和模拟器差异较大时，按以下顺序定位，不要直接修改 profile：

1. **汇编是否一致**：函数符号、指令数量、编译器 flags 和循环展开是否改变；
2. **semantic 映射是否正确**：每条 ISA 指令是否映射到正确的 semantic kind；
3. **execution decomposition 是否合理**：512-bit 指令 part 数、part gap 和内部依赖；
4. **寄存器/内存依赖是否正确**：是否错误地增加或遗漏 RAW、memory order、flags 依赖；
5. **latency 与 issue interval**：依赖链和独立累加器分别是否符合微基准；
6. **resource capacity/occupancy/domain**：是否出现错误的 lane 竞争或错误并行；
7. **cache、带宽和 outstanding**：是否使用了错误 cache 初态或错误工作集；
8. **front-end 和窗口**：ROB、vector waiting window、dispatch/retire 是否成为瓶颈；
9. **真机噪声**：SMT、OS 抢占、频率和测量序列化是否引入波动。

只有确认前端、uop、依赖和执行模型都正确后，才可以用独立微基准重新估计 profile
参数。新参数应同时通过训练 kernel 和 hold-out kernel 验证，不能只用产生偏差的
同一个 kernel 拟合。

### 1.9 保存结果和审核记录

每个 kernel 至少保存：

```text
kernel/<name>/artifacts/
├── x86/ 或 rvv/ 汇编
├── semantic uop trace
├── profile-bound trace（如有）
├── 真机原始测量和环境
├── simulator result/events
└── summary.md
```

`summary.md` 应明确写出：测试机器、编译器、N、cache 模式、真机统计、模拟周期、
相对误差、主要瓶颈、是否修改 profile，以及待审核的参数变更。既有 profile 数值
不能因单个 kernel 的结果自动覆盖。

## 2. 当前已经支持的 kernel

| Kernel | x86 AVX-512 功能/真机 | Zen 4 周期模拟 | RVV/Spike | 覆盖重点 |
|---|---|---|---|---|
| Softmax | 已完成 | 已完成首轮对比 | VLEN=128/512 功能已验证；周期待 RVV 前端和 profile | load/store、FMA、reduction、conversion、integer、shuffle |
| FMA throughput/latency | 已完成 | 已完成双模型对比 | VLEN=128/512 通过 | FMA 吞吐与依赖延迟 |
| AXPY、Triad、Copy、AGU | 已完成 | 已完成双模型对比 | VLEN=128/512 通过 | load/store、FMA、带宽、AGU |
| Dot、Reduction | 已完成 | 已完成双模型对比 | VLEN=128/512 通过 | FMA、sum/max reduction |
| Conversion、Integer、Mixed | 已完成 | 已完成双模型对比 | VLEN=128/512 通过 | conversion、integer/shift、共享 issue domain |

## 3. 已实现的第一批 kernel

下表记录第一批已经实现的 kernel。后续扩展仍应优先选择能隔离单个资源或一条
依赖链的 kernel，再加入组合复杂度更高的 kernel。

| Kernel | 主要目的 | semantic uop | uop/recipe 状态 |
|---|---|---|---|
| FMA throughput | 独立累加器下测 FMA 吞吐 | `vector_fp_fma` | x86/RVV recipe 与 Zen 4 timing 已覆盖 |
| FMA latency | 单累加器依赖链测结果延迟 | `vector_fp_fma` | x86/RVV recipe 与依赖链已覆盖 |
| AXPY / Scale | load + FMA + store 的重叠 | `vector_load`、`vector_fp_fma`、`vector_store`、`address_generation` | memory-source FMA 已覆盖 |
| Dot product | 双 load、FMA 和 reduction | `vector_load`、`vector_fp_fma`、`vector_reduce_add` | x86 lowering 与 RVV reduction 已覆盖 |
| Vector copy | 纯 load/store 带宽 | `vector_load`、`vector_store`、`address_generation` | 访存、带宽和队列已覆盖 |
| Vector triad | 多 load + FMA + store | load/store、`vector_fp_fma` | memory-source FMA 已覆盖 |
| Vector reduction | 隔离 sum/max latency 和 lowering | `vector_reduce_add`、`vector_reduce_max`、`vector_shuffle` | extract/shuffle/scalar recipe 已覆盖 |
| Conversion | FP32 ↔ INT32 吞吐和延迟 | `vector_convert` | x86/RVV conversion form 已覆盖 |
| Vector integer/shift | 整数 ALU 和 shift 资源 | `vector_integer`、`vector_shift` | add/logic/shift recipe 已覆盖 |
| Mixed compute | FMA/conversion/integer 共享 issue domain | 多种 vector compute | `fp-add-fma-convert` domain 已覆盖 |
| Pointer/AGU | 地址生成和标量地址计算 | `address_generation`、`scalar_alu` | AGU 与标量地址更新已覆盖 |

### 3.1 FMA kernel 应拆成两个测试

建议分别创建：

```text
kernel/fma_throughput/
kernel/fma_latency/
```

`fma_throughput` 使用多个独立累加器，尽量隐藏 latency；`fma_latency` 使用前一条
FMA 的结果作为下一条 FMA 输入，避免通过增加累加器数量掩盖真实依赖延迟。两者使用
相同的算法语义，但不能合并成一个“通过参数切换”的模糊测试。

### 3.2 复杂 kernel 的添加顺序

建议顺序为：

```text
FMA throughput/latency
  -> vector copy / AXPY
  -> dot / vector reduction
  -> conversion / vector integer
  -> mixed compute / triad
  -> GEMM microkernel
  -> attention 或其他 LLM 组合 kernel
```

GEMM、Attention 等组合 kernel 应在基础资源 kernel 稳定后再添加。它们同时包含
tile 复用、多个访存流、FMA、reduction 和复杂寄存器依赖，不适合第一批用来反向
拟合 profile。

## 4. Kernel 测试的验收条件

新增 kernel 通过审核至少需要满足：

1. semantic uop 类型和 ISA recipe 已审核，未知指令不会静默降级；
2. x86 功能测试通过；若有 RVV，Spike/真机功能测试通过；
3. 汇编、trace、profile hash 和环境信息已保存；
4. 真机和模拟器使用相同 N、输入规模和 cache 口径；
5. 报告包含总周期、cycles/element、uop 数、关键路径、资源和 queue 统计；
6. 偏差已按第 1.8 节排查，不能只给出拟合后的最终周期；
7. profile 修改有独立微基准依据，并在至少一个 hold-out kernel 上复核；
8. 结果和待修改参数经过审核后，才写回正式 profile。

## 5. 当前明确不作为第一批测试的内容

以下内容需要更多 semantic uop、profile 或 microarchitecture 信息，暂不作为第一
批 kernel：

- gather/scatter；
- 复杂 mask 和 active-lane 行为；
- RVV slide、复杂 permutation；
- branch misprediction 和 frontend 压力专用 kernel；
- 依赖具体 cache prefetch、TLB 或 SMT 行为的 kernel。

这些测试不是永久排除，而是应在相应语义、recipe、profile 参数和验证方法准备好后
单独立项。
