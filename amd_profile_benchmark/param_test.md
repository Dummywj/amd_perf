# AMD Profile Benchmark 参数测试说明

## 1. 测试范围

本目录标定 `softmax_sim_avx512/profiles/amd_zen4.yaml` 中的全部性能参数。测试对象为单个 Zen 4 物理核，SMT 同胞线程必须空闲，内存必须绑定到本地 NUMA 节点。

静态 CPU/ISA/cache 拓扑直接读取 CPUID、`lscpu` 和 sysfs；动态参数由 Google Benchmark 驱动固定工作量的微基准。无法观察的物理 uop 数、融合边界和内部 pipe 编号不作猜测，由模拟器 recipe 做等效分解。

## 2. 统一测量规则

- 正式命令固定 CPU 8、NUMA node 0，并检查 SMT sibling CPU 200 空闲。
- 测试 kernel 使用固定展开度；Google Benchmark 只负责参数枚举、重复和 JSON 输出。
- 核心周期使用 `perf_event_open` 的用户态 `CPU_CYCLES`，同时读取所需 AMD raw PMC。计数器结果按 `time_enabled/time_running` 校正。
- 指令测试必须保存反汇编；混合流还必须核对每类目标指令的静态配比和寄存器独立性。容量测试扫描阻塞指令数，使用性能曲线拐点给出区间。
- 可直接估计的参数报告中位数。只能确定上下界的参数报告 `[lower, upper]`、`midpoint=(lower+upper)/2` 和 `half_range=(upper-lower)/2`。
- midpoint 只是模拟器暂用值，不解释为已发现的物理结构真值。
- `frequency` 不属于 profile，但 governor、boost 和测试期间负载仍记录为实验条件。

## 3. 测试程序映射

### 3.1 Profile 字段、含义与判定方法

| Profile 字段 | 含义 | 判定方法 |
|---|---|---|
| `cpu.*` | 目标处理器身份 | CPUID 与 `/proc/cpuinfo` 交叉检查 |
| `isa.required_features`、`zmm_registers`、`max_vector_bits` | 模拟器允许解码的 ISA 和最大向量状态 | CPUID feature leaf 静态枚举 |
| `pipeline.dispatch_macro_ops_per_cycle` | 每周期可送入后端的 macro-op 数 | 无执行瓶颈指令流的 retired-op 吞吐给出有效下界，公开资料给出结构上界 |
| `pipeline.retire_macro_ops_per_cycle` | 每周期可提交的 macro-op 数 | retired macro-op PMC 饱和测试；只能得到持续有效值，不能分离瞬时峰值 |
| `pipeline.rob_entries` | 未退休 macro-op 的有效窗口容量 | 长 miss 阻塞退休，扫描其后可容纳的 filler 数 |
| `pipeline.vector_scheduler_entries` | 等待向量操作数的调度窗口容量 | 长 miss 产生未就绪向量源，扫描依赖向量指令数并检查 FP scheduler stall |
| `pipeline.load_queue_entries`、`store_queue_entries` | 未完成 load/store 的有效队列容量 | 扫描地址未就绪的 load/store 数并检查对应 stall PMC |
| `resources.*.kind` | recipe 与执行资源的类型连接 | schema 约定，不通过实验估计 |
| `resources.*.capacity` | 该等效资源每周期可接收的 256-bit 操作数 | 独立链吞吐；AGU 和数据通路另用 load/store/mixed 流 |
| `resources.*.width_bits` | 单个等效资源一次处理的向量位宽 | XMM/YMM/ZMM 吞吐对照与公开 datapath 信息 |
| `resources.*.bytes_per_cycle` | 单核每周期通过该数据资源的有效字节数 | L1 命中连续读写流，取实测中位数 |
| `recipes.*.decoded_macro_ops`、`retire_macro_ops` | 一条机器指令在前端/退休侧占用的 macro-op 数 | retired macro-op 与目标指令数对照；不能观测的 decode 细节保留公开值 |
| `recipes.*.vector_decomposition` | 宽向量在模拟器中的分块数、块宽和相邻块发射间隔 | XMM/YMM/ZMM 吞吐比例；它是等效分解，不声明物理 uop 数 |
| `recipes.*.uops[].latency_cycles` | 真依赖链上结果可用延迟 | 单指令依赖链 |
| `recipes.*.uops[].issue_interval_cycles` | 独立指令流中的最小发射间隔 | 多独立寄存器链 |
| `recipes.*.uops[].resource_choices` | opcode 可使用的等效资源集合 | A/B 混合流辨识资源共享；无法辨识物理 pipe 编号时只保留资源组 |
| `recipes.*.uops[].resource_occupancy_cycles` | 一个向量分块占据等效资源的周期数 | 吞吐、资源容量和分块数联合约束；不可唯一反演时标为等效值 |
| `memory.cache_line_bytes`、`levels.*` 的 size/ways/shared cores | cache 几何与共享范围 | sysfs cache topology |
| `memory.*.latency_cycles` | 单依赖访问对应层级的有效延迟 | 不同工作集大小的随机 pointer chase，并用 miss/fill PMC 验证落点 |
| `memory.*.read_bytes_per_cycle`、`write_bytes_per_cycle` | 指定访问形式的单核持续带宽 | 多独立连续 load/store 流 |
| `memory.*.max_outstanding_*` | 各层级路径达到吞吐平台所需的有效并发请求数 | 扫描独立 pointer-chase 链数，以上升段末端和平台起点形成区间 |
| `metadata`、`evidence` | 环境、命令、来源与置信度 | 随结果记录，不是性能参数 |

### 3.2 源文件边界

| 源文件 | 统一测试方法 | 覆盖参数 |
|---|---|---|
| `src/static_inventory.cpp` | CPUID/sysfs 静态枚举 | `cpu`、`isa`、cache line/size/ways/shared cores |
| `src/pipeline_width.cpp` | 大规模可立即完成指令流 + retired-op PMC | dispatch 下界、retire 下界及 retire-token stall |
| `src/instruction_latency.cpp` | 真依赖链 | `vaddps` latency，128/256/512 位对照 |
| `src/instruction_throughput.cpp` | 多条独立寄存器链 | issue interval、512 位拆分、FP/整数/shuffle/conversion 的有效容量；为 ZMM 竞争流提供同宽度单流基线 |
| `src/resource_contention.cpp` | 固定配比混合流并与同宽度单流比较 | opcode 共享 issue domain、端口资格子集、有效 occupancy |
| `src/window_capacity.cpp` | 长延迟头部操作 + 可变数量阻塞项 + 独立探针 | ROB、vector scheduler、load queue、store queue 的容量区间 |
| `src/cache_latency.cpp` | 随机单依赖 pointer chase | L1D/L2/L3/DRAM 有效 latency |
| `src/cache_bandwidth.cpp` | 多独立流顺序 load/store | 各级 read/write bytes per cycle、load/store 数据通路吞吐 |
| `src/memory_parallelism.cpp` | 增加独立随机 pointer-chase 流数 | 各层 max outstanding misses/request 的有效区间 |

## 4. Pipeline 与窗口参数

### `dispatch_macro_ops_per_cycle`

用长展开的单字节 NOP 流使后端几乎不产生执行资源压力，以 `ex_ret_ops / core_cycles` 测可持续下界。Zen 4 可能特殊处理连续 NOP，因此静态 NOP 数只用于识别这种现象，不能直接当作 macro-op 数；最终结合 AMD dispatch-slot 定义验证 6 macro-op/cycle。

### `retire_macro_ops_per_cycle`

同一饱和流给出可持续退休下界，并读取 `ex_ret_ops`。由于 dispatch 可能先限制持续速率，测试无法单独证明瞬时退休峰值；结果以测得下界和公开上界形成区间，再计算 midpoint。

### `rob_entries`

先发出一个被 flush 的长延迟 load，在它后面插入可变数量的已完成 filler macro-op，再发出第二个独立 miss。当 filler 可装入 ROB 时两个 miss 重叠；超过容量后第二个 miss 被推迟，延迟曲线出现台阶。

### `vector_scheduler_entries`

先发出未命中的 vector load，然后插入 `K` 条依赖该 load 的 `vaddps`。这些指令等待操作数并占据 FP scheduler。独立探针 miss 从可重叠变为被推迟时，得到有效容量区间；同时读取 FP scheduler resource-stall PMC。

### `load_queue_entries` 与 `store_queue_entries`

先通过长延迟 load 获得地址，再发出 `K` 个依赖该地址的 load 或 store。扫描 `K` 并读取对应 dispatch resource-stall PMC。其他隐藏队列可能先成为瓶颈，因此只报告有效区间。

## 5. 指令 Recipe 与执行资源

### Latency

目标指令的输出直接作为下一条同指令输入。展开足够多次后，扣除同结构空循环基线，`cycles / instruction` 即依赖路径 latency。

### Issue interval

用 8 至 16 个独立目的寄存器消除依赖链限制。稳定后的 `cycles / instruction` 是 reciprocal throughput，并写入 `issue_interval_cycles` 的候选值。

### 512 位拆分

对同一 opcode 测 XMM、YMM、ZMM。比较吞吐、latency 和 128/256/512 retired-op PMC。ZMM 相对 YMM 的资源占用增加用于验证 `parts: 2`、`part_width_bits: 256` 和 `part_issue_gap_cycles`。

### 资源选择与 occupancy

先测 conversion、FMA、integer 的 ZMM 单流，随后运行三组固定配比混合流：

| 混合流 | 每 block 指令数 | 设计目的 |
|---|---:|---|
| conversion + integer | `32 + 32`（1:1） | conversion 达到单流上限时，检查 integer 能否同时使用其他资格端口 |
| FMA + integer | `32 + 32`（1:1） | FMA 达到单流上限时，检查 integer 能否同时使用其他资格端口 |
| conversion + FMA + integer | `16 + 16 + 32`（1:1:2） | 让 conversion/FMA 联合施压共享域，并用双份 integer 填充候选的其余端口 |

每个 block 均为 64 条目标 ZMM 指令。FMA 使用独立累加寄存器链：两类 1:1 流使用 8 条链，1:1:2 流使用 4 条链；转换与整数指令使用分离的目的寄存器和只读源，不形成跨指令 RAW 依赖。反汇编必须验证循环体内目标指令数量、配比和寄存器集合。

混合 benchmark 除总 IPC 外，还输出各类静态目标指令数、占比和各类 IPC。汇总脚本将各类 IPC 除以对应 ZMM 单流 IPC，得到单流容量利用率，并求和为 aggregate normalized demand：

- 若两类只能共享同一个不可重叠的瓶颈，归一化需求和应接近 1；
- 若 conversion 或 FMA 接近 100% 单流吞吐时 integer 仍能前进，说明 integer 至少有一部分资格端口不属于该窄共享域；
- 三类流用于区分“conversion/FMA 的窄共享 issue domain”和“所有 vector opcode 共用一个总容量”两种模型。它只能约束等效资格集合，不把结果解释成已识别出的物理 pipe 编号。

报告还按 ISA 显式源操作数计数：conversion 为 1、`vpaddd` 为 2、FMA 为 3（包括 read-modify-write 目的操作数），输出 `static_source_operands_per_cycle`。该值用于检验共享寄存器读取/operand-delivery issue domain；它是静态需求，不声明每个 ISA 源一定对应一次物理寄存器文件读取。

正式聚焦运行使用：

```bash
BENCHMARK_FILTER='BM_(VfmaddpsThroughputZmm|VpadddThroughputZmm|Vcvttps2dqThroughputZmm|ContentionZmm.*)' \
  CPU=8 NUMA_NODE=0 REPETITIONS=7 \
  amd_profile_benchmark/scripts/run_all.sh \
  amd_profile_benchmark/results/zen4-zmm-contention-YYYYMMDD
```

覆盖的代表指令为：FP `vaddps`/`vfmadd231ps`、vector integer `vpaddd`、basic shuffle `vpermps`、conversion `vcvttps2dq`。反向的 `vcvtdq2ps` 只沿用 provisional scheduling 假设，不视为本组竞争微基准的直接证据。

## 6. 存储层级

### Cache/DRAM latency

每个 64-byte cache line 只保存一个 next 指针，以确定性随机排列连接成环。单依赖 pointer chase 消除 memory-level parallelism。工作集选择为：L1D 16 KiB、L2 256 KiB、L3 4 MiB、DRAM 256 MiB。L2/L3 使用远离容量边界的工作集，避免把替换压力误算成命中延迟。

### Read/write bandwidth

对齐的 AVX-512 多流顺序 load/store 分别运行在上述工作集。L1 额外测试 YMM load、YMM store 和 2-load+1-store 混合流，用于区分 AGU 数和 256-bit 数据通路。Cache 测试重复访问同一 working set；DRAM 测试使用大于单 CCD L3 的 working set。结果是当前 kernel 访问形式的有效 bytes/core-cycle，不等同于内存总线物理流量。

### Outstanding misses/requests

把固定总工作集拆成 `K` 条独立随机链，扫描 `K=1..64`。吞吐最后一次显著提升和首次稳定平台之间形成并发数区间。该值包含 ROB、LQ、fill buffer、fabric 等共同限制。

## 7. 结果准入

- 每个动态参数至少 7 次独立 repetition；容量曲线的每个扫描点保留原始值。
- 反汇编不包含目标指令、工作集未落入预期层级、PMU running ratio 低于 0.95 或重复结果 CV 超过 3% 时，结果标为不稳定。
- ZMM 竞争组还要求 conversion/FMA/integer 三个单流基线齐全，且每个混合流的 retired-ZMM/target 位于 `[0.98, 1.02]`。
- 任一门禁失败时，汇总脚本写出失败原因并返回非零状态，`run_all.sh` 不会把该轮结果声明为成功。
- 已知公开值与实测区间冲突时不覆盖数据，应在 `result.md` 中说明冲突和可能原因。
- 所有测试先写入 `amd_profile_benchmark/result.md`，经人工审核后才能修改正式 profile。
