# AMD Zen 4 Profile Benchmark 结果（已审核）

> 状态：**APPROVED / 已写入 calibrated profile**
> 测试日期：2026-08-05
> 审核日期：2026-08-05

## 1. 实验平台与结果入口

- CPU：AMD EPYC 9684X，Family `19h`、Model `11h`、Stepping `2`
- 拓扑：2 socket，96 core/socket，SMT2；测试固定 CPU 8，SMT sibling CPU 200 空闲
- NUMA：内存固定 node 0
- 驱动：仓库内 Google Benchmark v1.9.5；核心周期和 AMD raw PMC 由 `perf_event_open` 分组读取
- 重复：每个动态测试 7 次；容量曲线每个点含 400 个 trial
- 系统状态：未关闭 boost、CPU scaling 或 NMI watchdog，也未修改系统配置

可审核材料：

- [原始 JSON](results/zen4-20260805/raw.json)
- [自动统计](results/zen4-20260805/summary.md)
- [补充内存流 JSON](results/zen4-20260805/supplemental-memory.json)
- [补充内存流统计](results/zen4-20260805/supplemental-memory-summary.md)
- [实验环境](results/zen4-20260805/environment.txt)
- 2026-08-05 测试二进制完整反汇编：本地生成物，按仓库规则不纳入 Git
- [ZMM 资源竞争原始 JSON](results/zen4-zmm-contention-20260817/raw.json)
- [ZMM 资源竞争自动统计](results/zen4-zmm-contention-20260817/summary.md)
- [ZMM 资源竞争环境](results/zen4-zmm-contention-20260817/environment.txt)
- [ZMM 资源竞争聚焦反汇编](results/zen4-zmm-contention-20260817/disassembly_excerpt.txt)

主运行命令：

```bash
amd_profile_benchmark/scripts/run_all.sh \
  amd_profile_benchmark/results/zen4-20260805
```

补充 AGU 测试使用同一二进制、CPU、NUMA 和 7 次 repetition。所有正式 PMU 组的最小 `time_running/time_enabled` 均为 `1.0`，没有 multiplex 缩放损失。

## 2. 审核结论摘要

| 参数 | 实验观测 | 审核结果 | 置信度 |
|---|---:|---:|---|
| dispatch/retire 持续有效宽度 | 5.9858 macro-op/cycle | 6 | 高/中 |
| ROB 有效容量 | `[306, 323]`，midpoint 314.5 | 保留物理 ROB=320 | 高 |
| vector waiting window | `[112, 128]`，midpoint 120 | 保留物理 scheduler=64 | 高 |
| load queue | `[40, 48]`，midpoint 44 | 44 | 中 |
| store queue | `[64, 72]`，midpoint 68 | 68 | 中 |
| vector integer/shuffle/conversion 容量 | 3.982/1.996/1.995 op/cycle | 4/2/2 | 高 |
| AGU 有效容量 | 2.8156 memory-op/cycle | 3 | 高 |
| load/store 数据通路 | 1.9449/0.9996 个 YMM op/cycle | 2/1，62.23/32 B/cycle | 高 |
| `vaddps` latency | XMM/YMM/ZMM 均约 3.002 cycle | 3 | 高 |
| `vaddps` issue interval | YMM 0.5013，ZMM 1.0011 cycle | 0.5/1.0 | 高 |
| L1D/L2/L3/DRAM latency | 4.00/14.11/54.24/373.10 cycle | 4/14/54/373 | 高/中 |
| outstanding L1/L2/L3-DRAM | `[8,12]`/`[16,24]`/`[24,32]` | 10/20/28 | 高/中/低 |

这里的区间中点均按约定计算；采用中点的字段只把它作为模拟器暂用值，不解释为物理结构真值。

## 3. 静态 CPU、ISA 与 Cache

CPUID 验证 `avx2`、`fma`、`avx512f/dq/bw/vl`、`avx512_bf16`、`avx512_vnni` 全部存在，ZMM 寄存器数为 32，最大向量宽度为 512 bit。

| 层级 | Size | Ways | Line | 共享物理核数 | 候选处理 |
|---|---:|---:|---:|---:|---|
| L1D | 32 KiB | 8 | 64 B | 1 | 直接采用 |
| L2 | 1 MiB | 8 | 64 B | 1 | 直接采用 |
| L3/CCD | 96 MiB | 16 | 64 B | 8 | 直接采用 |

这些字段来自 CPUID/sysfs，不需要微基准反演。

## 4. Pipeline 与窗口容量

### 4.1 Dispatch 与 retire

NOP 饱和流的 `retired_macro_ops/core_cycles` 中位数为 `5.9857509`。静态 NOP 数与 retired macro-op 数之比为 `1.99937`，说明 Zen 4 对该 NOP 流存在特殊压缩/处理，不能按静态 NOP 数计算宽度。

- `dispatch_macro_ops_per_cycle`：候选 `6`
- `retire_macro_ops_per_cycle`：持续有效候选 `6`

该测试能证明约 6 macro-op/cycle 的稳态值，但 dispatch 可能先成为瓶颈，不能单独证明瞬时退休峰值，因此 retire 置信度为中。

### 4.2 容量曲线

| 参数 | 台阶前 | 台阶后 | 区间 / midpoint / half-range | 处理建议 |
|---|---:|---:|---:|---|
| ROB | 306 entries，367.19 cycle，无 stall | 323 entries，563.11 cycle，stall 出现 | `[306,323]` / 314.5 / 8.5 | 审核决定保留物理值 320 |
| Vector waiting window | 112，363.65 cycle，无 stall | 128，565.23 cycle，FP scheduler stall | `[112,128]` / 120 / 8 | 审核决定保留物理 scheduler=64 |
| Load queue | 40，358.58 cycle，无 stall | 48，605.40 cycle，LQ stall | `[40,48]` / 44 / 4 | 候选 44 |
| Store queue | 64，364.48 cycle，轻微 stall | 72，604.61 cycle，显著 stall | `[64,72]` / 68 / 4 | 按中点规则候选 68；64 是明确 onset |

Vector 测试得到的 120 明显大于两个 32-entry scheduler 的合计 64，说明测试先碰到的可能是 scheduler 前后的合并 buffering/dispatch queue。审核决定 schema 字段表示物理 scheduler，因此采用 64；120 只保留为有效 waiting-window 观测值。

## 5. 执行资源与 VADDPS Recipe

### 5.1 独立流吞吐

| 指令（YMM） | issue interval | 吞吐 | 等效容量候选 |
|---|---:|---:|---:|
| `vaddps` | 0.50129 cycle | 1.99485 op/cycle | 2 个适用 FP datapath |
| `vfmadd231ps` | 0.53685 cycle | 1.86271 op/cycle | 结构候选 2，实测略低 |
| `vpaddd` | 0.25112 cycle | 3.98218 op/cycle | 4 |
| `vpermps` | 0.50107 cycle | 1.99573 op/cycle | 2 |
| `vcvtps2dq` | 0.50119 cycle | 1.99525 op/cycle | 2 |

混合流吞吐为：add+FMA `1.9951`、add+integer `2.5829`、add+shuffle `2.3058`、add+convert `1.9958` op/cycle。由此可确认 add 与 FMA/conversion 强共享，integer 基本独立，shuffle 部分共享；无法由这些总吞吐唯一反演物理 pipe 编号。

当前 `resources.vector-fp.capacity=4` 表示公开资料中的 FP/vector aggregate pipe 数，但 `vaddps` 只表现出 2 个 256-bit op/cycle 的有效吞吐。建议保留 aggregate 4，同时在 recipe/eligibility 中限制具体 opcode；若模拟器当前无法表达 eligibility，则对 `vaddps` 使用等效容量 2，不能直接让它使用全部 4 个 pipe。

### 5.2 ZMM conversion、FMA 与 integer 资源竞争补测

2026-08-17 在相同 CPU 8、NUMA node 0 上增加了三类 ZMM 单流基线和三组混合流，每点 7 次 repetition。三组循环体均含 64 条目标指令，反汇编确认其配比分别为 1:1、1:1 和 1:1:2；retired-ZMM/目标指令中位数为 `1.00001` 至 `1.00004`。

| 测试 | 总 IPC 中位数 | 各类 IPC | 相对 ZMM 单流利用率 | 静态源操作数/cycle |
|---|---:|---|---|---:|
| conversion 单流 | 0.99797 | conversion 0.99797 | 100% | - |
| FMA 单流 | 0.99792 | FMA 0.99792 | 100% | - |
| integer 单流 | 1.99337 | integer 1.99337 | 100% | - |
| conversion + integer，1:1 | 1.99245 | 0.99623 / 0.99623 | 99.83% / 49.98% | 2.98868 |
| FMA + integer，1:1 | 1.51607 | 0.75803 / 0.75803 | 75.96% / 38.03% | 3.79017 |
| conversion + FMA + integer，1:1:2 | 1.99277 | 0.49819 / 0.49819 / 0.99638 | 49.92% / 49.92% / 49.98% | 3.98553 |

接受轮次的所有主指标 CV 不超过 1.73%，PMU running ratio 均为 1.0。首轮精确
`vcvttps2dq` 测量中 FMA+integer 的 CV 为 3.09%，已按门禁拒绝并完整重跑。结果给出以下
等效模型约束：

- conversion 在保持约 100% 单流吞吐时，integer 仍达到约 1 ZMM instruction/cycle，因此二者不能放入一个完全共享、不可并行的窄 issue domain；integer 必须有额外资格容量。
- 三类 1:1:2 流中，conversion+FMA 合计约 0.997 ZMM instruction/cycle，同时 integer 约 0.997，支持 conversion/FMA 的窄共享域与 integer 的并发资格分开表达。
- FMA+integer 1:1 只达到 1.516 IPC，明显低于 conversion+integer。按显式 ISA 源操作数计数，FMA、integer、conversion 的需求权重分别为 3、2、1；后两组混合流达到约 3.79 和 3.99 个 ZMM 源操作数/cycle。这支持增加一个约 4 个 ZMM 源操作数/cycle、即 8 个 256-bit source-token/cycle 的加权 operand-delivery issue domain 候选，但它仍需与 opcode 端口资格联合使用。

这里的源操作数是 ISA 静态需求，不等同于已观测到的物理寄存器文件读取。微基准只能约束共享域、权重和资格集合，不能唯一反演物理 pipe 编号。

本轮 conversion 指令使用 kernel 对应的截断转换 `vcvttps2dq`。反向转换
`vcvtdq2ps` 未被本组实验直接覆盖，其 recipe 继续标记为 provisional。当前只有三个固定
配比点，因此新增的 4 part-token/cycle 和 8 source-token/cycle 均为中等置信度等效约束；
还需 ratio sweep 才能判断是否存在同样符合现有数据的其他约束组合。

### 5.3 地址与数据通路

| L1 测试 | 中位数 |
|---|---:|
| YMM load | 1.94486 op/cycle，62.2338 B/cycle |
| YMM store | 0.99962 op/cycle，31.9868 B/cycle |
| 2-load + 1-store 混合 | 2.81557 memory-op/cycle，90.0984 B/cycle |

候选值：

- `address-generation.capacity = 3`
- `load-data.capacity = 2`，`bytes_per_cycle = 62.23`；结构上限可取 64
- `store-data.capacity = 1`，`bytes_per_cycle = 32`

物理 store 相关 pipe/AGU 数可能为 2，但地址生成已经由独立资源描述。审核决定 `store-data` 表示真正的数据写入吞吐，因此采用每周期一个 256-bit store，即 capacity 1、32 B/cycle。

### 5.4 `vaddps:zmm,zmm,zmm`

| Recipe 字段 | 观测 | 候选 |
|---|---:|---:|
| `decoded_macro_ops` | 无法直接观察；一条机器指令 | 保留 1 |
| `retire_macro_ops` | 扣除循环控制后约 1/instruction | 1 |
| `parts` / `part_width_bits` | ZMM 吞吐是 YMM 的约 1/2 | 2 / 256 |
| `part_issue_gap_cycles` | YMM interval 0.5013，ZMM 1.0011 | 1 |
| `latency_cycles` | XMM 3.00196、YMM 3.00191、ZMM 3.00162 | 3 |
| `issue_interval_cycles` | 每个 256-bit add 约 0.5；整条 ZMM 约 1.0 | part 0.5 / instruction 1.0 |
| `resource_occupancy_cycles` | 吞吐与两个适用 datapath 相符 | 等效值 1 |
| `resource_choices` | 只能确认 FP 资源组 | `[vector-fp]`，不填物理 pipe 编号 |

两段 256-bit uop 只是模拟器等效分解。基准无法证明 exact physical uop count，也无法证明隐藏融合边界。

## 6. Memory 参数

### 6.1 Latency

| 层级 | 中位数 cycle | 落点验证 | 候选 |
|---|---:|---|---:|
| L1D | 4.00346 | L2 miss/load 近 0 | 4 |
| L2 | 14.11132 | L2 miss/load 近 0 | 14 |
| L3 | 54.23776 | L2 miss/load 0.864，DRAM fill/load 0.005 | 54 |
| DRAM | 373.10479 | L2 miss/load 0.998，local DRAM fill/load 0.881 | 373 |

这些值是随机单依赖 pointer chase 的有效 load-to-use 延迟，包含层级访问路径开销。

### 6.2 持续带宽

| 层级 | Read B/cycle | Write B/cycle | 候选 |
|---|---:|---:|---|
| L1D，ZMM 流 | 59.3570 | 31.9863 | L1 read 采用更高的 YMM 实测 62.2338；write 31.9868 |
| L2 | 31.9636 | 31.4033 | 原值写入 |
| L3 | 24.1893 | 26.5254 | 原值写入 |
| DRAM | 9.27518 | 8.91668 | 原值写入 |

这些值是单核、NUMA-local、当前顺序 kernel 的逻辑字节/周期，不等于 Data Fabric 或 DIMM 的物理总带宽。

### 6.3 Outstanding misses/requests

| 路径 | 上升段末端 | 平台起点 | 区间 / midpoint / half-range | 候选 |
|---|---:|---:|---:|---:|
| L1D miss -> L2 | K=8: 0.4725 load/cycle | K=12: 0.4912 | `[8,12]` / 10 / 2 | 10 |
| L2 miss -> L3 | K=16: 0.2296 | K=24: 0.3001 | `[16,24]` / 20 / 4 | 20 |
| L3 miss -> DRAM | K=24: 0.0632 | K=32: 0.0731 | `[24,32]` / 28 / 4 | 28 |

因此 `l1d.max_outstanding_misses=10`、`l2.max_outstanding_misses=20`、`l3-ccd.max_outstanding_misses=28`、`dram.max_outstanding_requests=28` 可作为初始等效值。DRAM 的 K=32/48/64 CV 为 8.17%/6.72%/9.12%，平台存在但候选 28 只给低置信度。

## 7. 无法由本测试唯一获取的参数

- exact physical uop count：公开 PMC 只给退休/宽度类别，无法观察内部裂分；使用 simulator effective decomposition。
- macro/micro fusion 边界：需要专门覆盖大量相邻指令组合，且没有逐融合事件；当前直线向量范围不把它写成物理事实。
- opcode 的精确物理 pipe eligibility：混合吞吐只能识别共享关系，无法唯一反演 pipe 编号。
- 各内部 queue 的独立物理容量：容量拐点可能被前后级 buffering 先限制，只能得到有效上下界。
- 瞬时 retire 峰值：稳态流可能先受 dispatch 限制，当前只给持续有效值。

以上项目交给模拟器的等效资源和 recipe 表达，不虚构硬件真值。

## 8. 稳定性与审核结论

- 延迟、指令吞吐、带宽和补充 AGU 测试的主要指标 CV 均不超过 3%。
- 容量扫描的少数非拐点存在大于 3% 的 CV，但 ROB/LQ/SQ/FP scheduler 的台阶同时得到延迟和对应 stall PMC 支持。
- L2/L3 并发测试部分点略高于 3%；DRAM 高并发点为低置信度。
- 测试期间 host 总负载较高且 CPU scaling 开启；固定核及其 SMT sibling 已检查空闲。若审核要求发布级 profile，建议隔离核、关闭 watchdog 后复测低置信度项。

人工审核结论：

1. `vector_scheduler_entries` 表示物理 scheduler，取 64；waiting-window 120 不写入该字段。
2. `store-data` 表示等效数据写入通路，取 capacity 1、32 B/cycle。
3. ROB 使用实验区间验证公开值，保留 320。
4. 其余候选值全部通过。

上述结果已写入 `softmax_sim_avx512/profiles/amd_zen4.yaml`，profile 状态更新为 `calibrated`。
