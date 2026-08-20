# XSAI 模拟器对齐执行计划

> 状态：RTL 正式采集已完成，Zen 4 后端已冻结，XSAI-RVV 独立后端已建立；
> 当前结果不能宣称 XSAI 与模拟器已经完成周期对齐。

目标是以同一套 semantic uop 表达 x86 与 RVV，在保留 XSAI Core 实际结构约束的
前提下，对齐裸机 RTL 周期。目标 SoC 可以实例化 CUTE，但测试程序不得生成 CUTE/
矩阵指令，也不得向 CUTE 发起任务或数据事务；profile 和周期对齐范围只包括 XSAI
Core 的 RVV 执行路径。

## 1. 根据 XSAI 源码生成 XSAI Core RVV Profile

**目标配置。** 当前基线固定为
`~/project/xsai-env/XSAI` 的提交 `04909692a1cdc6b9165b95c7ea83b94bdc01ab39`，
使用 `xsai-env` 集成的单核 `DefaultMatrixConfig`，并保留其中实例化的 CUTE。构建脚本
记录 XSAI、NEMU、nexus-am 与当前项目提交，同时检查运行前后外部 tracked 源码没有
变化。

**已实现。** profile schema v5 已把原先的 Zen 4/ZMM 假设扩展为通用可选结构，现可
描述 VLEN/ELEN、scheduler partition、FU eligibility、向量 RF read/writeback domain、
前端 macro dispatch domain、dispatch/ROB 计数口径、标量/向量访存拓扑，以及按
LMUL/有效字节动态分解。`profiles/xsai.yaml` 已包含源码可证明的：

| 参数组 | 已记录内容 | 证据 |
|---|---|---|
| ISA 与前后端 | RV64GCV、VLEN=128、宽度、ROB、队列和物理寄存器 | 配置源码与生成配置 |
| 前端复杂指令入口 | RVV `isComplex` macro 共享单个 `DecodeUnitComp` 输入 | decode/uop-info 源码 |
| macro 计数口径 | dispatch 按 decoded/execution uop 较大值，ROB 按架构指令 | decode 展开与 ROB 接口 |
| 向量调度 | 三个 VF 分区、两个 VLSU 分区、scalar-prep 分区和 FU 资格 | scheduler/FU 连接关系 |
| 向量寄存器 | 128-bit 数据宽度、read domain、共享 writeback domain | RF 端口索引与连接关系 |
| 标量访存 | LDU0-2、STA0-1、STD0-1 的独立分区和执行资格 | scheduler/FU 连接关系 |
| 向量访存 | VLSU 数量、merge buffer、load/store pipeline 和 flow 上限 | memory 参数源码 |
| cache | L1D/L2/L3 几何与 L1D set 映射约束 | 配置源码和 ELF 布局审计 |

源码只能证明结构、不能证明端到端 timing 的字段继续显式标为 `measure`，包括部分
latency/issue interval、L1 服务时间以及非 L1 层级；没有借用 Zen 4 数值。2026-08-19
的正式 RTL 微基准已直接覆盖 vfalu/vfma/vfcvt/vialu、reduction、vset 以及 scalar
ALU/FP 的依赖和吞吐证据；scalar memory、branch/move、L1 物理服务延迟/带宽和非 L1
仍为 pending。profile 状态因此仍为 `draft`，只完成证据收口，不代表全 profile 已校准。
CUTE 不出现在资源拓扑中，反汇编审计和 timed-region HPM 共同验证其指令、执行和访存
路径均未被使用。

## 2. 明确 XSAI 裸机 RTL 仿真方法

`xsai/` 集成层已在当前项目内实现，未改动 `xsai-env` 源码。当前流程包括：

1. 直接编译现有 12 个 RVV kernel，生成裸机 ELF/BIN/反汇编和提交元数据。
2. 对 N=512/1024/2048 做 ELF L1 容量/set 映射检查及 RVV/CUTE 指令审计。
3. 先在 NEMU 完成 180 个 kernel 样本和 41 组微基准的功能验证；NEMU 周期不用于拟合。
4. 用单核 `DefaultMatrixConfig` 构建 RTL emulator，再以 NEMU difftest 运行正式周期矩阵。
5. kernel region 以 `mcycle` 计时并扣除空框架；每个样本另取 HPM 快照，CUTE 活动直接
   判为失败，L1D/DTLB miss 样本标为 contaminated 并排除拟合。

所有生成物均写入当前项目的 `artifacts/xsai/`。可复现命令、DRAMSim3 构建前置、
超时处理、日志验收和 CSV 字段见 `docs/xsai_sim.md`。裸机/NEMU 门禁、RTL emulator
构建和正式无波形 difftest 均已通过；2026-08-19 的 41 个微基准 case（每 case 5 次）
与 12 个 kernel x 3 个 N 均为 clean，CUTE 活动和 L1D/DTLB miss 均为 0。另有 13 个
VSET/VL/VLSU 定向 case x 5 样本通过同样门禁，采集证据已
写入 profile，但后续模拟器差距分析仍在进行。

## 3. 完成 XSAI 微架构模拟

**Capability-gap 结论已经改变：XSAI-RVV 使用独立执行后端。** 36 点对齐中只有 FMA
类接近，而 load、conversion、integer、reduction 和组合 kernel 大量低估；继续向公共
调度器加入 XSAI 的 VL 物理状态、复杂指令 drain、VLSU split/merge/replay 会再次改变
Zen 4 行为。回归已确认这种污染实际发生过，因此不再扩展生产用通用后端。

当前代码边界为：

| 文件 | 职责 |
|---|---|
| `src/backend/zen4.py` | 冻结历史稳定 Zen 4 execution-uop 事件循环 |
| `src/backend/xsai.py` | XSAI backend-uop 展开、分区调度、RF/WB、rename、VLSU 与时序循环 |
| `src/simulator/engine.py` | 只按 profile 选择后端并保持旧 API |

semantic uop 仍是跨 ISA 的固定接口，但 backend uop 不是通用 ISA。XSAI 普通向量计算
按 LMUL 生成 scheduler uop；vector-scalar 生成 I2V/F2V prep 加 LMUL uop；向量访存
生成 prep 加 EMUL/128-bit flow；`vsetvli` 生成两个槽，e32/m1 reduction 生成三个串行
槽。每个槽与标量 uop 一样占用一个 scheduler entry，不能只把 decoded count 记在
macro 上而仍用一个 execution uop 调度。

首版 XSAI 时序循环复用了稳定的数据结构、memory hierarchy 和结果导出格式，但没有
继承或调用 Zen 4 `Engine`。未独立校准的内部槽只表达调度占用，聚合 latency 暂时仍由
最后一个槽承担，避免凭 kernel 误差虚构每级 latency。后续 VL/VTYPE、VLSU replay/
merge、物理寄存器释放等改动只进入 `xsai.py`，不得回写 `zen4.py`。

## 4. 使用现有 Kernel 进行 XSAI 与模拟器对齐

对齐按“单资源到组合资源”推进：先测 FMA latency/throughput、copy/load/store，再测
conversion、integer、reduction，随后测 AXPY、vector triad、dot product、mixed
compute、pointer AGU，最后才测 softmax。前一层不能解释时不进入后一层，防止用复杂
kernel 掩盖错误资源模型。

每个有效测试点比较 RTL kernel-region cycles、cycles/element、重复波动、模拟周期、
相对误差以及可用的 issue/queue/cache stall 计数。目标 `DefaultMatrixConfig` 继承的
L1D 为 64 KiB、4-way、256 sets、64 B cache line。按每个 kernel 在计时区实际访问的
FP32 数组计算，候选规模的工作集如下；
标量输出按占用一个 64 B cache line 计：

| Kernel 类别 | 计时区数据 | N=512 | N=1024 | N=2048 |
|---|---:|---:|---:|---:|
| FMA throughput/latency、copy、conversion、integer、mixed、softmax | 1 input + 1 output = `8N` B | 4 KiB | 8 KiB | 16 KiB |
| AXPY、vector triad | 2 input + 1 output = `12N` B | 6 KiB | 12 KiB | 24 KiB |
| Pointer AGU | 3 input + 1 output = `16N` B | 8 KiB | 16 KiB | 32 KiB |
| Dot product | 2 input + 1 scalar line = `8N + 64` B | 4.06 KiB | 8.06 KiB | 16.06 KiB |
| Vector reduction | 1 input + 1 scalar line = `4N + 64` B | 2.06 KiB | 4.06 KiB | 8.06 KiB |

因此 `N=512/1024/2048` 都通过容量检查；最坏的 Pointer AGU 在 N=2048 时为 32 KiB，
占 L1D 的 50%，仍为裸机栈和少量运行时数据保留一半容量。通用 harness 即使始终分配并
预热最大 `3N` 输入和 `N` 输出，N=2048 的活跃数据也只有 32 KiB。

容量小于 64 KiB 仍不等于必然 L1 hit。实施时所有活跃 buffer 至少 64 B 对齐，生成
cache set 占用表，并保持现有接口的内存布局：所有输入向量拼接在一个连续 `3N` arena，
输出使用另一个连续 arena，不能把 x/y/z/output 分配成同一 cache color 的四个独立
buffer。每个 set 的测试数据最多占 3 个 way，为栈/运行时保留至少一个 way；功能
reference/golden buffer 与日志不得夹在 warmup 和 timed region 之间。

warmup 必须覆盖输入和输出 store line，随后立即计时，并固定、记录预取配置。以最终
RTL 导出的 L1D refill/miss 和 TLB miss 计数器为准，timed region 的 demand refill
必须为 0；否则标记为 `cache-contaminated`，不参与拟合。最终矩阵只保留
`N=512/1024/2048`，不恢复 N=256 或 N=4096。

参数调整遵循以下约束：

- 结构参数由源码和 elaboration 固定，不因 kernel 误差修改。
- latency、吞吐和资源共享先由对应微基准估计，再用于 kernel；不得添加按 kernel、按 N
  或按 ISA mnemonic 生效的补偿常数。
- 每次调整必须写明因果假设、RTL 证据、影响参数和跨 kernel 回归结果；训练样本与保留
  验证样本分开。
- RTL 波动先确定后再审核误差阈值。超过阈值但缺少可验证原因时保留偏差，不强行拟合。
- 所有报告绑定 profile、trace、汇编、RTL 和模拟器版本，未知参数及 fallback 必须显式
  列出。

执行顺序为：profile/schema 与来源固化 -> 裸机 RTL 流程复现 -> 后端 capability-gap
与策略设计 -> 单资源微基准校准 -> 组合 kernel 对齐 -> Softmax 保留集验证。各阶段由
自动测试和证据完整性门禁衔接。capability-gap 审核已经确认需要独立 XSAI 后端，且
方案已获批准；后续继续在该边界内执行。最终报告同时列出已解释偏差和未解释偏差，
不以单一平均误差掩盖失败测试点。

**当前执行状态（2026-08-20）。** profile/schema、bare-metal/NEMU 门禁、HPM 审计、
RVV 动态前端，以及独立 XSAI-RVV backend-uop 展开和事件循环已完成。正式无波形 RTL
difftest 采集与验收完成，形成 41 个微基准 case x 5
和 12 kernel x 3 N 的 clean 产物；另有 13-case VSET/VL/VLSU 矩阵，关键 hash 与门禁记录
在 profile measurement source 中。迁移前的 36 点通用后端基线 MAPE 为 **47.04%**，
13-case 定向矩阵为 **47.94%**；它们保留为独立后端的比较基线，不代表新后端已经完成
对齐。对齐流结果还受到 DCache bank 访问模式影响，不能用来唯一反演 flow
service 周期。普通 `v8` 的 directed load/load-use RTL 结果已经排除“统一 16-cycle vector
load”假设；下一步应补齐真实逐迭代 `vsetvli a5,a5 -> VL writeback -> vector/VLSU
consumer` 的状态可见性与 merge/replay 证据，再重新评估 36 点矩阵。该结果不是对齐完成声明；
profile 仍为 `draft`，不得用 kernel 误差反向修改已测参数。
