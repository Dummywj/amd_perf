# 面向 AVX-512 的 Softmax 微架构模拟器研究方案

## 1. 结论与推荐路线

不建议把 `softmax_sim` 中的 RISC-V 参数直接改名后继续使用。面向 AVX-512 的模拟器应定位为：**给定一段真实的 x86-64 Softmax 机器码、输入规模和一份具体 CPU 微架构配置，预测单核执行周期并解释瓶颈**。

推荐采用“真实指令流 + 可替换微架构 profile + 事件驱动乱序后端”的路线：

1. 以本项目已有的 FP32 三遍 Softmax 和 SLEEF `u10` 为第一个目标 kernel。
2. 从最终二进制反汇编得到真实指令，不手写一个抽象的 `EXP2` 指令流。
3. 将每条 x86 指令按目标 CPU profile 翻译成一个或多个微操作（μop）。
4. 用依赖、前端宽度、乱序窗口、执行流水线、load/store 和 cache 共同推进周期。
5. 第一份 profile 针对当前可实测的 AMD Zen 4 服务器；模型稳定后再增加 Zen 5、Intel Ice Lake Server 或 Sapphire Rapids，不能用一个“通用 AVX-512 吞吐”代表所有 CPU。

`softmax_sim` 适合用作事件循环、μop 时间线和配置化思路的原型参考，但其手工依赖、统一“计算宽度”以及抽象 `EXP2` 的方式不能直接作为 x86 性能模型。原项目入口见 [`softmax_simulator.py`](../third_party/softmax_sim/softmax_simulator.py)。

## 2. 目标和边界

### 2.1 第一阶段目标

- 对一个物理核心上的 FP32 AVX-512 Softmax 建模。
- 输入包括：ELF/机器码、函数符号、`N`、数组地址与对齐、kernel lowering、CPU profile。
- 输出包括：总 core cycles、每个 Softmax 阶段的周期、关键路径、各执行资源利用率、前端/后端/内存瓶颈、指令和 μop 时间线。
- 支持小尺寸精确逐周期模拟，以及大尺寸循环体压缩模拟，避免为 64M 元素展开数百万条动态指令。
- 结果是性能预测，不负责代替 Softmax 数值正确性测试。

### 2.2 暂不覆盖

- 完整 x86 功能模拟、异常处理、操作系统调度和虚拟化。
- 多核一致性、NUMA 竞争和其他进程造成的带宽抖动。
- 把 BF16 `exp` 当作原生指令。AVX-512 BF16 主要提供点积等能力；若测试 BF16 存储的 Softmax，应显式包含 BF16/FP32 转换和 FP32 `exp`。
- 未经校准就宣称跨 CPU 的绝对周期精度。

模拟周期默认指 **core cycle**。墙钟时间另按实测有效频率换算；TSC ticks、APERF/MPERF 和 core cycles 不应混为一个单位。

## 3. 与 `softmax_sim` 的对应关系

| `softmax_sim` 概念 | AVX-512 模型中的处理 |
| --- | --- |
| 用户手工标注指令依赖 | 从解码后的源/目标寄存器、mask、flags 和内存操作数自动建立依赖 |
| 全局 `register_width` | ZMM 架构宽度固定为 512 bit；每条指令另带 128/256/512 bit 的编码宽度 |
| 全局 `compute_unit_width` | 每个微架构 profile 中按指令 form 定义 μop 数、可用流水线、吞吐、延迟和占用时间 |
| instruction chaining | 由寄存器重命名、结果 wakeup/forwarding 和乱序调度自然产生；分片转发作为可选的微架构特性 |
| 抽象 `EXP2` 单元 | 对实际 SLEEF/多项式实现的指令序列建模，或使用由同一二进制校准出的函数 summary |
| 单一 cache bandwidth | 分离 load/store 数据通路、AGU、L1/L2/LLC/DRAM 带宽、延迟、未决请求和 TLB |
| in-order / out-of-order 开关 | 保留 in-order 作为调试基线；正式 x86 profile 使用有 ROB、scheduler 和按序退休的乱序模型 |
| 一条向量指令拆成等宽 μop | 拆分由“CPU 型号 + opcode/form + 向量宽度”决定，不能只用 `512 / compute_width` 推导 |

还应吸取原实现中的单位问题：新模型所有大小都必须携带单位，例如 `vector_bits`、`element_bits`、`memory_bytes` 和 `active_lanes`，不得用一个 `data_size` 同时表示 bit 和 byte。

可以直接保留的主要是工程形态：配置对象、instruction/μop 两级时间记录、周期事件循环、in-order/OOO 对照模式、ASCII 时间线和结构化结果。需要重写的是 ISA 类、依赖生成、instruction→μop recipe、chaining、资源仲裁、内存层级和 Softmax 指令流生成。特别是原实现的 `ready_elements` 只是按 elapsed latency 线性估计，consumer 实际仍等待 producer μop 完成；它不能作为 x86 part forwarding 的实现基础。原项目可以作为行为对照样例，不应成为新模拟器的基类。

## 4. 先分清 ISA 语义与微架构实现

### 4.1 属于 AVX-512 ISA 的规则

- 64 位模式下可使用 32 个 ZMM 寄存器；XMM、YMM 是相应 ZMM 的低 128/256 bit。另有 `k0`–`k7` opmask 寄存器。[Intel AVX-512 概览](https://www.intel.com/content/www/us/en/developer/articles/technical/intel-avx-512-instructions.html)
- AVX-512 不是 RISC-V Vector 那样由运行时 `vl` 寄存器控制的可变向量长度。对支持 AVX-512VL 的 instruction form，128、256 或 512 bit 宽度编码在具体指令中；某些 instruction form 只支持部分宽度。[Intel 指令扩展说明](https://www.intel.com/content/www/us/en/support/articles/000005779/processors.html)
- EVEX writemask 按元素控制写入。merge masking 在 mask=0 的 lane 保留旧目标值，因此旧目标是数据依赖；zero masking 的关闭 lane 写零，不需要旧目标值。
- 对 masked memory instruction，关闭的 lane 不产生相应的架构内存访问；但执行 μop 数和非内存算术延迟通常不能按有效 lane 比例缩短。mask 会改变哪些地址被访问，必须把“算术资源成本”和“有效内存字节”分开。[Intel Data Operand Independent Timing 指南](https://www.intel.com/content/www/us/en/developer/articles/technical/software-security-guidance/best-practices/data-operand-independent-timing-isa-guidance.html)
- AVX-512 是多个 CPUID feature 的集合。AVX512F、VL、DQ、BW、BF16、ER 等不能互相替代；解析每条指令时必须验证其 feature 集以及操作系统的 ZMM/opmask 保存状态。
- 主流 AVX512F 不能被抽象成“一条原生 `exp`”。`VEXP2PS` 属于可选的 AVX512ER feature；只有 profile 明确具有 AVX512ER 时才允许使用。普通服务器上的 SLEEF `exp` 是多条算术、转换、位操作和可能的访存组成的函数。[Intel 编译器 feature 定义](https://www.intel.com/content/www/us/en/docs/dpcpp-cpp-compiler/developer-guide-reference/2024-2/additional-predefined-macros.html)

指令的精确操作数、mask、舍入、异常和 upper-lane 规则以 [Intel SDM](https://www.intel.com/content/www/us/en/developer/articles/technical/intel-sdm.html) 或 [AMD64 Architecture Programmer's Manual Volume 4](https://docs.amd.com/v/u/en-US/26568_3.26_APM_Vol4) 为准。解码器优先复用 Intel 的开源 [XED](https://github.com/intelxed/xed)，不要自行维护不完整的 EVEX 解码表。

### 4.2 属于具体 CPU 的参数

下面这些都不是“AVX-512 官方统一值”，必须放在 microarchitecture profile 中：

- 一条指令解码成多少 μop，带 memory operand 时是否额外产生 load μop。
- μop 可去哪些执行端口/流水线、端口占用周期、发射间隔和结果延迟。
- 512-bit operation 是完整宽度执行，还是拆成 2 个 256-bit part，以及 part 是否能提前转发给消费者。
- fetch/decode/rename/dispatch/retire 宽度，ROB、scheduler、load queue 和 store queue 容量。
- L1D 每周期 load/store 数量、AGU 数量、cache/TLB 延迟、MSHR 和预取策略。
- 持续执行宽向量指令时的有效频率和进入/退出频率状态的延迟。

例如，AMD 官方说明 Zen 4 保留 512-bit register file，但内部用 256-bit data path 在连续时钟处理两个部分；Zen 5 则扩展到 512-bit data path，并可由平台策略选择顺序执行两个 256-bit 部分。这说明“同一条 ZMM 指令”必须按 CPU profile 建模，不能仅按 ISA 名称赋一个固定吞吐。[AMD Zen 4 白皮书](https://www.amd.com/content/dam/amd/en/documents/products/epyc/4th-gen-amd-epyc-processor-architecture-whitepaper.pdf)、[AMD Zen 5 白皮书](https://www.amd.com/content/dam/amd/en/documents/epyc-business-docs/white-papers/5th-gen-amd-epyc-processor-architecture-white-paper.pdf)

Intel 某些处理器也可能因功耗和散热降低 AVX 工作负载的频率，这同样属于具体产品和运行状态，而不是 ISA latency。[Intel AVX 频率说明](https://www.intel.com/content/www/us/en/support/articles/000090746/processors.html)

## 5. 指令和微操作模型

### 5.1 三层表示

建议使用三层 IR：

1. `StaticInstruction`：PC、机器码长度、mnemonic、ISA feature、寄存器/flags/mask 读写集合、memory addressing、vector width、element width、merge/zero mask。
2. `DynamicInstruction`：静态指令加本次迭代号、实际地址、实际 mask、分支方向和 Softmax phase。
3. `MicroOp`：输入/输出 token、可选执行资源、latency、resource occupancy、memory bytes、part index、是否参与退休。

一个 instruction recipe 必须按完整 form 匹配，例如 `VADDPS zmm,zmm,zmm`、`VADDPS zmm,zmm,m512` 和带 mask 的版本不能默认共用一个条目。memory form 通常应能展开为 address-generation、load 和 arithmetic μop；具体是否融合只影响前端/退休计数，执行资源仍分别占用。

### 5.2 延迟、吞吐和占用必须分开

- `latency`：输入就绪到输出可被依赖者使用的周期数。
- `issue_interval`：同类 operation 再次进入流水线的最小间隔。
- `resource_occupancy`：该 μop 占用某资源多少周期。
- `port_choices`：可以由哪些等价资源执行。
- `parts`：ZMM operation 的内部 part 数、part 宽度和 part 间距。

调度器每周期选择 ready μop 与可用资源的匹配，不能像原项目一样只累加“本周期 arithmetic bytes”。端口/流水线选择应采用 oldest-ready 优先并尽量保留稀缺资源；测试时再用穷举的小 trace 检查贪心策略是否产生不合理结果。

### 5.3 依赖与 forwarding

- rename 时为每个架构目标分配新的物理 token；源操作数绑定到当时的生产者。
- merge-masked instruction 增加旧目标依赖；zero-masked instruction 不增加。
- compare 产生 `k` 寄存器，masked consumer 必须等待该 mask token。
- reduction accumulator 有 loop-carried dependency，应支持多个 accumulator 展开来打断关键路径。
- store 的地址和数据分别就绪；load 是否被旧 store 阻塞由 memory-order 模型决定。
- 第一版以“整个目标寄存器完成后 wakeup”为保守规则。若硬件实验确认存在 256-bit part forwarding，再在相应 profile 启用 `part_ready`；不要照搬 RISC-V chaining 的“一一对应同数目 μop”假设。

### 5.4 reduction

`_mm512_reduce_max_ps` 和 `_mm512_reduce_add_ps` 是编译器 intrinsic，不应在模拟器里被当作一条通用的水平规约机器指令。必须对最终汇编中的 `vmaxps/vaddps`、extract、shuffle 和标量收尾逐条建模。

规约包含两种依赖：

- 遍历 row 时，多个 ZMM accumulator 各自形成 loop-carried chain；load 和不同 accumulator 可以重叠。
- 遍历完成后的水平 tree 必须等待所有 accumulator，并形成从向量到 scalar 的短关键路径。

模拟器应输出“流式遍历”和“水平收尾”各自周期，便于判断小 `N` 为 latency-bound 还是大 `N` 为 bandwidth-bound。

### 5.5 `exp`

首个模型固定对齐本项目的 `Sleef_expf16_u10avx512f`，并记录 SLEEF commit、编译器、flags 和最终函数机器码哈希。可采用两种模式：

- **展开模式**：进入 SLEEF 函数，逐条模拟 range reduction、整数转换、FMA/乘加、多项式、特殊值处理和 return。这是校准和研究的基准模式。
- **summary 模式**：用同一二进制展开模式或微基准得到 `exp16_u10` 的资源需求、latency 和寄存器接口，作为可复用 composite op。只用于长 row 加速，不能跨 SLEEF 版本复用。

如果 kernel 中保留真实 `call`，还要计入 ABI register、call/return 和前端影响；只有最终二进制确实内联时才能删除。比较不同 `exp` 方案时必须维持相同误差合同，否则“更快”可能只是降低精度。

## 6. 前端、乱序后端和内存

### 6.1 前端

profile 至少包括 instruction fetch bytes/cycle、decode macro-ops/cycle、decoded-op cache 是否存在及其带宽、rename/dispatch 宽度、分支吞吐和错误预测代价。实际 EVEX 指令长度来自机器码；循环是否驻留在 decoded-op cache 由代码 footprint 决定。

MVP 可先假设 loop branch 完全预测正确，但必须仍计入 branch μop 和前端带宽。随后通过只改变 unroll 的微基准校准前端模型。

### 6.2 乱序后端

每周期事件顺序固定并写入规范：

1. 完成本周期到期的 μop，发布结果并唤醒消费者。
2. 按前端和队列容量 fetch、decode、rename、allocate。
3. 从 scheduler 中选择 ready μop，匹配空闲端口/流水线并开始执行。
4. 推进 load/store 与 cache 请求。
5. 按程序顺序退休已完成 instruction，释放 ROB/queue 项。

需要记录 ROB、scheduler、LDQ、STQ 的峰值占用，以及“因依赖、无端口、前端空泡、队列满、cache miss”分别停顿多少周期。总周期之外，这些解释数据才是模拟器最有价值的输出。

### 6.3 load/store 和 cache

分阶段实现内存模型：

1. **L1-perfect 模式**：所有数据命中 L1，仅竞争 load/store data path 和 AGU，用于校准计算后端。
2. **层次 cache 模式**：set/way、64-byte cache line、L1/L2/LLC latency/bandwidth、line fill buffer/MSHR、写分配和 TLB。
3. **流式近似模式**：对大 row 使用按 cache line 聚合的请求和校准后的预取覆盖率，避免逐元素模拟。

必须处理 64-byte 对齐、跨 cache line、跨 4 KiB page、tail masked load/store，以及同一 `output` 在第二遍写入、第三遍读改写带来的复用。cache bandwidth 不能等价为一个 load/store 共用的全局 byte counter：load ports、store-data、store-address、fill bandwidth 可能分别成为瓶颈。

## 7. Softmax lowering

第一份可校准模型应与本项目当前 `softmax_avx512` 保持完全一致：

```text
阶段 A：m = horizontal_max(x)                    // 第一次读 input
阶段 B：e[i] = exp(x[i] - m)，写 output 并累加 s // 第二次读 input、第一次写 output
阶段 C：output[i] *= 1 / s                      // 读写 output
```

这三个阶段之间有两个全局 barrier：`m` 未产生前不能开始阶段 B，`s` 未产生前不能开始阶段 C。阶段内部则由实际 unroll 和 accumulator 数决定可用的指令级并行度。当前实现还包括 4096 元素 block、4 个向量 sum accumulator、16 个 outer scalar sum 槽以及 masked tail，trace 生成器必须从真实汇编确认这些结构，不能只从 C++ 推断。

需要支持的后续 lowering 变体包括：

- `exp` 结果写临时数组后再归一化，与重新计算 `exp` 以节省中间写入的取舍。
- 多个向量 accumulator 数和循环 unroll 数。
- masked tail 与 scalar tail。
- online/block softmax，用额外缩放换取更少的完整内存遍历。
- 精确除法、reciprocal 近似加 Newton refinement。

每个变体都应由独立 kernel binary 产生 trace，并通过同一数值正确性门禁；模拟器不应在内部凭空“优化”指令流。

对 FP32，ZMM 一次最多覆盖 16 个元素：

```text
lanes       = vector_bits / 32
vector_iters = N // lanes
tail_lanes   = N % lanes
```

但动态 instruction 数必须按反汇编中的 unroll、block 边界和函数调用计算，不能简单地把每阶段写成 `ceil(N / 16)` 条抽象指令。

## 8. 配置和数据结构

配置建议使用有 schema version 的 YAML；所有数字同时记录来源和可信度。下面只展示结构，`measure` 表示尚待实测，不能在发布 profile 中静默使用猜测值：

```yaml
schema_version: 1
cpu:
  vendor: AuthenticAMD
  family: "19h"
  model: "target-model"
  stepping: "*"
isa:
  required: [avx512f, avx512dq, avx512vl]
  zmm_registers: 32
  opmask_registers: 8
frontend:
  fetch_bytes_per_cycle: {value: measure, source: null, confidence: unknown}
  decode_ops_per_cycle:  {value: measure, source: null, confidence: unknown}
  dispatch_uops_per_cycle: {value: measure, source: null, confidence: unknown}
queues:
  rob_entries: {value: measure, source: null, confidence: unknown}
  scheduler_entries: {value: measure, source: null, confidence: unknown}
  load_queue_entries: {value: measure, source: null, confidence: unknown}
resources:
  fp256_0: {capacity: 1}
  fp256_1: {capacity: 1}
  load_data: {bytes_per_cycle: measure}
  store_data: {bytes_per_cycle: measure}
recipes:
  "vaddps:zmm,zmm,zmm":
    required_features: [avx512f]
    parts: 2
    part_width_bits: 256
    part_issue_gap: measure
    result_latency: measure
    resource_choices: [[fp256_0, fp256_1]]
    evidence: "official-doc-or-microbench-id"
memory:
  cache_line_bytes: 64
  levels:
    L1D: {size_bytes: measure, ways: measure, latency: measure}
    L2:  {size_bytes: measure, ways: measure, latency: measure}
frequency:
  mode: measured_trace
  avx_state_transition_cycles: measure
```

kernel manifest 独立保存：

```yaml
kernel:
  symbol: softmax_avx512
  binary_sha256: "..."
  compiler: "gcc-version-and-flags"
  dtype: fp32
  lowering: three_pass_store_exp
  exp_symbol: Sleef_expf16_u10avx512f
  exp_accuracy: u10
input:
  N: 4096
  input_alignment: 64
  output_alignment: 64
  cache_state: warm_L2
```

trace、profile 和结果都写入 JSON，并包含 simulator commit。缺少 recipe 时必须报错，不能自动退化为“1 μop、1 cycle”。

## 9. 模拟算法

对小 trace 使用事件驱动逐周期模拟：

```text
decode machine code -> static instructions -> expand loop/control flow
-> rename and allocate -> build producer tokens
-> enqueue ready/not-ready uops
-> each cycle schedule ready uops to eligible resources
-> complete/wakeup -> memory responses -> in-order retire
```

对长循环使用两级加速：

- 精确模拟 warm-up、稳态前若干迭代、block 边界和 tail。
- 当 ROB/queue/cache 状态进入周期性稳态后，识别重复状态并一次跳过多个 loop iteration；最后精确模拟退出与水平 reduction。

在任何情况下都同时计算以下理论下界，作为模拟器自检而不是最终预测：

```text
frontend_bound = total_frontend_uops / frontend_width
resource_bound[r] = total_occupancy_on_r / capacity[r]
dependency_bound = longest_dependency_path
memory_bound[level] = transferred_bytes[level] / bandwidth[level]
lower_bound = max(all bounds)
```

若预测周期小于该下界，说明 recipe、资源记账或 steady-state 跳转存在错误。

## 10. 分阶段实施

### 阶段 0：冻结合同和采集基线

- 固定 CPU family/model/stepping、BIOS 宽向量模式、编译器、SLEEF commit 和 flags。
- 保存 `softmax_avx512` 及 SLEEF callee 的反汇编、机器码哈希和 CPUID/XCR0。
- 定义 core cycles、输入 cache state、对齐和数值精度合同。

### 阶段 1：解码、trace 与 ISA 正确性

- 用 XED 建立静态指令 IR，正确处理 ZMM/YMM/XMM、k mask、merge/zero 和 memory lanes。
- 实现循环计数、函数调用和 `N` 对应的 tail mask。
- 先输出 instruction trace 和依赖图，不做性能预测。

### 阶段 2：L1-perfect 乱序后端 MVP

- 实现前端宽度、rename、ROB/scheduler、端口调度、延迟和退休。
- 建立 Zen 4 的核心 arithmetic、shuffle、convert、branch、load/store recipe。
- 支持 ASCII 小时间线和 JSON 统计。

### 阶段 3：reduction 与 SLEEF `exp`

- 逐条覆盖 max/sum 水平 reduction 的真实编译序列。
- 支持 SLEEF 展开模式，再生成同版本的 summary 模式。
- 校准 dependency chain、独立 instruction throughput 和混合端口竞争。

### 阶段 4：cache、TLB 与大 row

- 加入 cache hierarchy、未决 miss、预取和写分配。
- 加入循环稳态压缩，使 1K 到 64M 的 dense sweep 可在合理时间完成。

### 阶段 5：多微架构 profile

- 冻结 Zen 4 profile 后再实现 Zen 5 和至少一个 Intel server profile。
- 相同 ISA recipe 名称可以共享语义，但 μop recipe、端口、频率与 cache 参数必须独立。

## 11. 验证与校准

### 11.1 分层验证

1. **ISA 单元测试**：128/256/512 宽度、不同 element size、全 mask/稀疏 mask、merge/zero、masked tail、跨 cache line。
2. **调度器单元测试**：依赖链、相互独立 operation、两类 operation 争同一资源、ROB/queue 满、按序退休。
3. **微基准校准**：每类核心 instruction 分别测 latency chain 和 independent throughput；再测 arithmetic + load、shuffle + FMA 等混合序列。
4. **组件校准**：单独测 max reduction、sum reduction、SLEEF exp、normalize。
5. **端到端验证**：用与 trace 完全相同的 Softmax binary 比较不同 `N`、对齐和 cache residency。

校准工具各自承担不同角色：

| 工具/数据 | 用途 | 不能替代的内容 |
| --- | --- | --- |
| 手写 dependency chain / independent-chain 微基准 | 测单 instruction latency、reciprocal throughput 和宽度拆分 | 不能直接解释完整 Softmax 的前端、cache 和函数调用 |
| [`llvm-exegesis`](https://www.llvm.org/docs/CommandGuide/llvm-exegesis.html) | 自动生成串行/并行 instruction 测量，作为手写微基准的交叉检查 | 可用 opcode、计数器和结果质量仍受本机 LLVM/环境约束 |
| [`llvm-mca`](https://www.llvm.org/docs/CommandGuide/llvm-mca.html) | 对同一汇编给出 LLVM scheduling model 的 latency、吞吐和资源压力，检查 profile 是否明显偏离已有编译器模型 | 不是硬件真值；官方文档明确其默认不模拟 fetch/decode、branch prediction 和 cache hit/miss |
| `perf stat` / AMD uProf | 采集 core cycles、instructions、可用 μop、cache/TLB 和有效频率事件 | 事件含义和可用性依 CPU 型号而变，必须保存原始事件名与换算公式 |
| 本项目现有 Google Benchmark Softmax | 在相同二进制、`N`、repetition 和输入合同下做端到端对照 | wall time 不能代替逐层 μop/cache 归因，必须同时保留环境门禁和反汇编 |

硬件采集时应固定单核和 NUMA、确认 CPU 空闲、预热、保存反汇编，并同时采集 core cycles、instructions、可用的 dispatched/retired μop、cache/TLB miss 和有效频率。Intel 参数以官方 [Optimization Reference Manual](https://www.intel.com/content/www/us/en/developer/articles/technical/intel64-and-ia32-architectures-optimization.html) 为起点；AMD 参数以官方 Zen optimization guide 和实测为起点。文档没有给出的端口或 μop 数据必须标记 `measured`，不能包装成官方值。

### 11.2 防止过拟合

- calibration 集只包含单指令和部分组件尺寸；完整 Softmax 尺寸作为 holdout。
- 再保留一组不同 unroll、不同地址对齐作为最终验证集。
- 报告 signed error、absolute percentage error、按 cache 区间的误差和瓶颈分类是否一致，不只报告平均误差。
- 每条 profile 参数保存 `source`、采集命令、原始数据、置信区间和最后校准日期。

可把 MVP 的临时验收线定为：L1-resident 组件中位绝对误差不超过 10%，完整 L1/L2 Softmax 不超过 15%，内存区不超过 20%。这些是工程目标，不是对尚未实现模型的精度承诺；若达不到，应输出误差归因，不能用全局缩放因子掩盖。

## 12. 测试矩阵

| 维度 | 首轮覆盖 |
| --- | --- |
| CPU | AMD Zen 4 主 profile；随后 Zen 5、Intel Ice Lake Server/Sapphire Rapids 各自独立 profile |
| ISA feature | AVX512F + 当前二进制实际使用的 VL/DQ/BW；feature 缺失必须拒绝运行 |
| 数据类型 | FP32；BF16 存储路径以后单独增加转换模型 |
| `N` tail | `1..33` 全覆盖，重点 15/16/17、31/32/33 |
| `N` dense | 沿用项目的 1K–64M 113 个尺寸 |
| cache state | L1 hot、L2 hot、LLC hot、streaming DRAM |
| 对齐 | 64-byte aligned、偏移 4/32/60 byte、跨 4 KiB page |
| mask | 全开、只有 1 lane、半数 lane、典型 tail |
| lowering | 当前三遍 SLEEF `u10`；不同 accumulator/unroll；以后增加 online/recompute |
| 前后端压力 | 纯 latency chain、纯 throughput、load+ALU、shuffle+ALU、call-heavy exp |
| 频率 | 短 burst 与持续 AVX-512，分别记录有效频率 |

测试结果必须按 CPU profile 分目录，禁止把不同 CPU 的采样混合校准。

## 13. 预期交付物

建议最终目录如下：

```text
avx512-softmax-sim/
  README.md
  pyproject.toml
  src/
    decode.py
    trace.py
    isa.py
    frontend.py
    scheduler.py
    memory.py
    simulator.py
    report.py
  profiles/
    amd_zen4.yaml
    amd_zen5.yaml
    intel_icelake_server.yaml
    intel_sapphirerapids.yaml
  kernels/
    softmax_three_pass.yaml
  tests/
    unit/
    traces/
    calibration/
  schemas/
    profile.schema.json
    trace.schema.json
    result.schema.json
```

每次模拟至少生成：

- `result.json`：周期、资源利用率、stall 分类、cache traffic 和 provenance。
- `summary.md`：预测值、理论下界、瓶颈和适用范围。
- `timeline.txt`：小 trace 的 instruction/μop ASCII 时间线。
- `timeline.svg`：按 Softmax phase 和执行资源分轨的紧凑时间线。
- `validation.md`：相对硬件数据的逐 case 误差以及 calibration/holdout 标记。

完成标准不是“能打印一个总周期”，而是：同一份真实机器码在指定 CPU profile 上可复现、参数有来源、尾部与 mask 语义正确、预测不违反资源下界，并能解释 Softmax 在不同 `N` 下为何从 reduction/`exp` 受限转为 cache 或内存带宽受限。

## 14. 官方资料

- [Intel 64 and IA-32 Software Developer Manuals](https://www.intel.com/content/www/us/en/developer/articles/technical/intel-sdm.html)
- [Intel 64 and IA-32 Optimization Reference Manual](https://www.intel.com/content/www/us/en/developer/articles/technical/intel64-and-ia32-architectures-optimization.html)
- [Intel XED：x86 encoder/decoder](https://github.com/intelxed/xed)
- [LLVM `llvm-mca` 官方文档](https://www.llvm.org/docs/CommandGuide/llvm-mca.html)
- [LLVM `llvm-exegesis` 官方文档](https://www.llvm.org/docs/CommandGuide/llvm-exegesis.html)
- [AMD64 Architecture Programmer's Manual Volume 4](https://docs.amd.com/v/u/en-US/26568_3.26_APM_Vol4)
- [AMD Zen 4 EPYC Architecture White Paper](https://www.amd.com/content/dam/amd/en/documents/products/epyc/4th-gen-amd-epyc-processor-architecture-whitepaper.pdf)
- [AMD Zen 5 EPYC Architecture White Paper](https://www.amd.com/content/dam/amd/en/documents/epyc-business-docs/white-papers/5th-gen-amd-epyc-processor-architecture-white-paper.pdf)

资料版本和访问日期应随 profile 一并保存；本文调研日期为 2026-07-29。
