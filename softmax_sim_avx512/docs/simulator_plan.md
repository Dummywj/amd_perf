# 通用 Uop 事件驱动模拟器执行计划

> 状态：审核反馈已纳入；实现与首轮验证已完成，结果见 `simulator_result.md`。
> 本计划记录首轮 Zen 4 设计。XSAI 对齐已证明执行模型不能完全共用，当前多后端
> 边界以 `simulator_xsai.md` 和 `tutorial/simulator.md` 为准。

## 1. 目标

实现一个以通用 uop 为输入、默认乱序且可切换为顺序发射的事件驱动后端，并用当前 AMD Zen 4 profile 模拟 `kernel/softmax` 的周期数，再与同一份 kernel 在目标 EPYC 9684X 上测得的 core cycles 对比。

核心边界：

```text
x86/RVV 汇编
  -> ISA 前端：控制流展开、操作数解析、依赖和访存地址
  -> 动态通用 uop DAG
  -> profile 绑定：等效执行 uop、latency、resource、memory 参数
  -> ISA 无关的事件驱动后端
  -> 总周期、时间线和瓶颈统计
```

ISA 相关逻辑只能出现在汇编前端和 recipe 中；调度器、ROB、scheduler、执行资源、队列和内存模型不得判断 x86/RVV mnemonic。后续加入 RVV profile 时，应复用同一个后端。

## 2. 建模原则

1. `profiles/amd_zen4.yaml` 中现有向量、pipeline 和 memory 校准值在本任务中冻结，不以 softmax 周期误差为理由修改。
2. Softmax 是向量和 memory 参数的 hold-out 验证负载，不用于反推这些已有参数。经本次审核允许新增微架构相关的 `scalar_control_fit`；其训练点和保留验证点必须分离，不能为每个 N 设置独立系数。
3. exact physical uop 不可观测时允许等效分解，但必须说明依据，不宣称为硬件真实结构。
4. vector/memory recipe 缺失 latency、issue interval 或 resource binding 时严格报错；scalar/control 只有在 profile 明确启用拟合模型时才允许使用该模型，不使用代码内静默默认值。
5. 模拟结果是确定性的点估计；真机结果报告中位数、MAD 和分位数。比较时接受由操作系统和未建模机制产生的合理误差。
6. 首版不实现分支预测器、TLB、预取器、SMT、频率和复杂前端。相关影响必须在报告中列为未建模项。
7. 模拟器只预测时序，不重新计算 softmax 数值。功能正确性继续由 x86 correctness 和 Spike RVV 测试负责。

## 3. 当前缺口

现有内容还不能诚实地产生 softmax 总周期：

| 层次 | 已有内容 | 缺口 |
|---|---|---|
| 静态 trace | mnemonic、operand、宽度、通用 uop kind、源码行号 | 没有基本块、循环次数、动态实例和分支路径 |
| 依赖 | 汇编操作数字符串 | 没有寄存器 read/write、flags、RAW 依赖和内存依赖 |
| 访存 | `address_generation + load/store` | 没有访问字节数、抽象地址、cache line 和命中层次 |
| pipeline | dispatch/retire=6、ROB=320、vector scheduler=64、LQ=44、SQ=68 | 缺少将动态 macro-op 放入这些结构的执行状态 |
| resource | vector/AGU/load/store 等容量和宽度 | 缺少多数 opcode 的 latency、issue interval、occupancy 和等效分解 |
| opcode timing | 完整的 `vaddps:zmm,zmm,zmm` recipe | 当前 softmax 仅 1 条动态静态实例能命中完整 timing recipe |
| memory | L1/L2/L3/DRAM 的容量、延迟、带宽和并发数 | 缺少初始冷热状态、替换和写策略等模拟政策 |

因此首个执行阶段必须是 trace contract 和 profile coverage audit，不能直接给未建模 uop 填经验常数。

## 4. 计划目录

```text
softmax_sim_avx512/
├── docs/
│   ├── simulator_plan.md
│   └── simulator_result.md
├── src/
│   ├── frontends/
│   │   ├── common.py
│   │   ├── x86.py
│   │   └── rvv.py                 # 有 RVV profile 后启用时序验证
│   └── simulator/
│       ├── model.py               # ISA 无关的数据结构
│       ├── profile.py             # profile 加载、校验和绑定
│       ├── trace.py               # 动态 uop DAG 校验
│       ├── scheduler.py           # ROB/scheduler/queue/issue/retire
│       ├── memory.py              # cache/memory 有效模型
│       ├── engine.py              # 事件循环
│       ├── export.py              # 事件日志、Perfetto 和 DOT 导出
│       └── cli.py
├── tests/
│   └── simulator/
├── kernel/
│   └── softmax/
│       ├── benchmarks/
│       │   └── softmax_cycles.cpp
│       ├── workloads/
│       │   └── softmax.yaml       # N、buffer 和 cache 初始状态，不含时序
│       └── scripts/
│           ├── run_x86_cycles.sh
│           └── compare_cycles.py
└── artifacts/
    ├── schedules/
    └── reports/
```

`third_party/softmax_sim` 只作为历史参考，不直接作为新后端基础。它把指令硬编码成 RISC-V `REDUCE/FMA/LOAD/STORE/EXP2`，包含 BF16 和合成 bandwidth 假设，不能满足当前通用 uop/profile 边界。

## 5. 动态 Uop Trace

### 5.1 静态汇编前端

扩展当前 `asm_to_uop.py`，保留：

- function、基本块、label 和 branch target；
- canonical instruction form；
- 寄存器 read/write、flags read/write；
- memory operand 的 base/index/scale/displacement；
- memory access 类型和有效字节数；
- instruction 与 recipe、semantic uop 的对应关系。

操作数角色放在 ISA recipe 中，不写入模拟器核心。前端只支持当前编译器实际输出的 form；遇到未知 form、间接跳转或无法求值的地址时硬错误。

### 5.2 动态展开

对一次 `softmax(input, output, N)` 调用，从函数入口沿控制流生成动态 instruction occurrence。首版 x86 输入限定 `N > 0` 且 `N % 16 == 0`。

动态展开必须根据寄存器状态计算三个主循环次数，不能简单把静态函数清单执行一次。每个实例记录：

- 全局 sequence/instruction ID；
- 所属 basic block 和静态源码行；
- 抽象寄存器 operand；
- `input`/`output` buffer 加 byte offset 的抽象地址；
- width、active bytes 和访存 cache line；
- 一个或多个通用 semantic uop。

RVV 前端未来根据 `vsetvli`、AVL、profile VLEN 和 SEW/LMUL 生成动态迭代；后端本身不包含这一规则。

### 5.3 依赖构建

对动态指令流进行 rename 风格依赖分析：

- 用最近一次 register/flags writer 建立 RAW 依赖；WAR/WAW 由重命名消除；
- 规范化 x86 寄存器别名和 32 位写零扩展；
- 同一指令内的 address-generation、load-data、compute 和 store-data 依赖由 recipe 指定；
- 对同一抽象地址建立必要的 store -> load、store -> store 顺序；不同地址允许乱序；
- uop 必须带稳定 ID、parent instruction ID 和 dependency ID，不允许只靠列表顺序推断依赖。

动态 trace 仍使用 `uop_kinds.yaml` 的唯一 vocabulary，不新增 x86 专用 uop kind。

## 6. Profile 绑定与覆盖

### 6.1 两级 Uop

区分：

- semantic uop：跨 ISA 含义，如 `vector_fp_fma`、`vector_load`；
- execution uop：profile 给出的等效拆分、latency、issue interval、occupancy 和 resource choices。

profile binder 将一组 semantic uop 绑定为 execution uop，并保留 `semantic_parent_ids`。事件后端只消费 execution uop，不读取 mnemonic。

### 6.2 Zen 4 Recipe 补充规则

在不改变现有参数的前提下，先对 softmax 实际出现的 form 做 coverage audit。需要覆盖的主要类别为：

- ZMM load/store/broadcast；
- max/min/sub/mul/FMA；
- FP/int conversion、integer add/shift；
- extract/permute/shuffle reduction lowering；
- scalar add/div 和必要的 move；
- 循环 address/compare/branch 的最小控制开销。

新增 recipe 前，在 `amd_profile_benchmark` 中按依赖链测 latency、独立链测 reciprocal throughput、混合流测 resource contention。无法观测物理 uop 时使用有证据的等效分解。新增参数先形成候选报告，经审核后再写入 profile。

instruction-specific recipe 的优先级高于通用 scalar/control 拟合项，避免以后增加精确 recipe 时被重复计费。

### 6.3 Scalar/Control 拟合项

先修改 `schemas/profile.schema.json`，再修改 `profiles/amd_zen4.yaml`。该变更提升 `schema_version`，并新增顶层 `scalar_control_fit` 分组；禁止把拟合常数散落在模拟器代码中。计划字段为：

```yaml
scalar_control_fit:
  enabled: true
  resources:
    scalar-alu-fit:
      capacity: <integer-or-measure>
    scalar-fp-fit:
      capacity: <integer-or-measure>
    branch-fit:
      capacity: <integer-or-measure>
  uops:
    scalar_alu:
      latency_cycles: <integer-or-measure>
      issue_interval_cycles: <integer-0.5-or-measure>
      resource_occupancy_cycles: <integer-or-measure>
      resource_choices: [scalar-alu-fit]
    scalar_fp_div:
      latency_cycles: <integer-or-measure>
      issue_interval_cycles: <integer-0.5-or-measure>
      resource_occupancy_cycles: <integer-or-measure>
      resource_choices: [scalar-fp-fit]
    branch:
      latency_cycles: <integer-or-measure>
      issue_interval_cycles: <integer-0.5-or-measure>
      resource_occupancy_cycles: <integer-or-measure>
      resource_choices: [branch-fit]
  evidence: [<source-id>]
```

上面只展示代表项；schema 明确枚举允许 fallback 的通用 kind：`scalar_alu`、`scalar_fp_add`、`scalar_fp_div`、`scalar_move`、`branch` 和 `return`。每种 kind 独立配置 timing，但可以共享拟合资源以表达竞争。`scalar_load`/`scalar_store` 仍使用 AGU、load/store queue 和内存层次，不纳入此拟合分组。

语义如下：

- scalar/control 指令仍生成通用 uop，并在事件后端占用各自的等效拟合资源，不在总周期末尾直接加常数；因此它们会参与依赖、竞争和调度图。
- 仅没有 instruction-specific recipe 的 scalar/control uop 使用此 fallback。
- 先用独立 scalar/control 微基准给出初值，再以多个 softmax N 的训练子集拟合；使用未参与拟合的 N 验证，报告系数、目标函数、置信区间和残差。
- 已有 vector、pipeline、memory 参数在拟合时固定；参数保持整数，只有 `issue_interval_cycles: 0.5` 允许保留小数。
- 首版 control 表示预测正确的常规循环控制有效成本；分支误预测器和复杂控制流仍不在范围内。

### 6.4 Profile 冻结检查

每次模拟记录 profile 路径、git commit 和 SHA-256。对比报告列出 profile diff；已有字段发生变化时，验证流程默认失败。允许的变化只有另行审核通过的新增 recipe/evidence。

## 7. 事件驱动执行后端

内部时间使用整数 tick；根据 profile 中所有小数周期分母确定 `ticks_per_cycle`。当前 `issue_interval_cycles: 0.5` 对应每周期 2 tick，避免浮点累计误差。

### 7.1 状态

- 按程序序保存 macro-op 的 ROB，容量 320；
- vector waiting window，容量 64；
- load queue 44、store queue 68；
- profile 中每种 execution resource 的容量、宽度和占用日历；
- ready queue、dependency remaining count 和 completion event heap；
- cache tags、未完成 miss 和每层 bandwidth 使用量。

### 7.2 每个周期的行为

1. 处理到期 completion event，唤醒依赖者。
2. 按程序序 dispatch，最多 6 macro-op/cycle；ROB 或相应 queue 满时停止。
3. 从已就绪 uop 中按 oldest-ready 规则选择 resource，检查 capacity、occupancy、issue interval 和数据带宽后发射。
4. load latency 由命中层次决定；compute latency 来自绑定后的 profile recipe。
5. 完成的 macro-op 按程序序 retire，最多 6 macro-op/cycle，并释放 ROB/LQ/SQ。
6. 跳到下一个 completion、resource release 或整数 dispatch/retire 边界，避免无事件时逐 tick 空转。

同周期阶段顺序固定并由单元测试锁定，防止 off-by-one 周期漂移。

### 7.3 资源和调度规则

- resource capacity 表示同一 tick 可用的等效执行槽，不推断未声明的物理 pipe；
- `resource_choices` 多于一个时，选择最早可发射且预计最早完成的资源，稳定 ID 打破平局；
- `resource_occupancy_cycles` 控制资源释放，`latency_cycles` 控制结果就绪，两者分开；
- `issue_interval_cycles` 对同类 execution uop 的连续发射生效；
- profile 的 `vector_decomposition` 决定 512-bit 操作的 parts，不能仅凭 resource width 自动猜测隐藏 uop 数；
- ROB 按 macro-op 计数，waiting window/LQ/SQ 按绑定规则计数，并在报告中注明计数口径。

### 7.4 顺序/乱序执行开关

CLI 提供 `--execution-model out_of_order|in_order`，默认 `out_of_order`。该选项属于模拟实验配置，不属于微架构 profile；两种模式复用完全相同的动态 uop、profile、资源和内存模型。

- `out_of_order`：在 waiting window 中从所有 ready uop 选择最老者，允许绕过尚未就绪的更老 uop。
- `in_order`：按 `(macro_sequence, recipe_uop_index)` 严格选择；同周期可连续发射多个满足资源限制的 uop，但遇到第一个未就绪或资源冲突的 uop立即停止，年轻 uop 不得绕过。
- 两种模式均按程序序 dispatch 和 retire；开关只改变 issue 选择规则。
- 每份结果和调度 trace 必须记录 execution model。Zen 4 真机准确性只以 `out_of_order` 结果验收，`in_order` 用于对照依赖隐藏和乱序收益。

## 8. 调度时序可视化

模拟器先输出唯一的结构化 `schedule_events.jsonl`，每个动态 instruction/uop 记录 dispatch、ready、issue、complete、retire、resource、依赖和 stall reason。其他视图都从该事件日志转换，避免统计结果与图形不一致。

### 8.1 Perfetto 主视图

导出 Chrome Trace Event JSON，可直接拖入 [Perfetto UI](https://ui.perfetto.dev/)：

- instruction 视图：每条动态指令一行，显示 dispatch、waiting、executing 和 retire-wait；只导出用户指定的 instruction/cycle 窗口，避免长循环产生数千条轨道。
- resource 视图：按 vector FP、AGU、load/store 和 scalar/control fit resource 分轨，显示每个 uop 的占用时间。
- dependency flow：用箭头连接 producer completion 和 consumer issue。
- counter 轨道：显示 ROB、waiting window、LQ、SQ 占用量和每类 stall 数。
- 所有事件附带精确 tick/cycle、instruction ID、uop kind、汇编文本和 parent ID；UI 时间轴只作为显示载体，精确周期以事件字段为准。

Perfetto 支持时间片、flow arrow、counter、筛选和缩放，适合交互式查看大 trace。首版使用容易生成的 Chrome JSON；需要 SQL 分析或更大 trace 时再升级为原生 TrackEvent protobuf。

### 8.2 辅助视图

- 导出 `dependencies.dot`，用 [Graphviz](https://graphviz.org/) 生成 SVG，查看 uop 依赖 DAG、关键路径和跨指令依赖；它不是时间轴。
- 导出 llvm-mca 风格的 `timeline.txt`，用于小 trace、代码评审和 golden test。
- 可运行 [`llvm-mca -timeline`](https://llvm.org/docs/CommandGuide/llvm-mca.html) 作为外部参考，但不把它作为本模拟器的渲染器或真值，因为它使用 LLVM 自己的 target scheduling model，且不覆盖本项目完整 cache/profile 语义。

## 9. 内存模型

首版分两阶段：

### 9.1 Hot-L1 验证

先把输入、输出和常量所需 cache line 标为 L1 resident，只使用 profile 的 L1 latency、load/store/AGU capacity 和 bytes per cycle。这一阶段主要验证依赖和执行资源，避免 cache policy 不确定性掩盖调度错误。

### 9.2 容量层次验证

再实现确定性的 set-associative LRU 有效模型：

- 使用 profile 的 line size、size、ways、latency、bandwidth 和 outstanding limit；
- workload 显式选择 `hot-l1`、`hot-capacity` 或 `cold` 初始状态；
- 连续 load/store 按 cache line 合并传输，但每条 uop 的依赖保持；
- 缺失的 inclusivity、write-allocate、prefetch/TLB 政策不写回 profile，作为 simulator policy 明示并做敏感性分析。

L1 模型稳定前不使用 L2/L3/DRAM 结果评价执行后端。

## 10. 真机周期测量

新增 benchmark 必须直接调用 `kernel/softmax/x86/softmax_avx512.cpp` 的同一导出函数，不能使用 `gbench-test` 中另一套 SLEEF softmax。

测量要求：

- 与汇编 artifact 使用同一编译器和 flags，记录源码、汇编、对象及 profile hash；
- `perf_event_open(PERF_COUNT_HW_CPU_CYCLES)` 只计 user cycles；同时采集 instructions、branches 和 cache miss 作为诊断量；
- 固定 CPU、NUMA node，确认 SMT sibling 空闲；预热后批量调用，降低 perf ioctl 和 timer 开销；
- 报告每次 kernel invocation 的 cycles，至少 7 次随机交错重复，并给出 median、MAD、p10/p90；
- 分开报告 harness/call 基线，不把该基线当作 profile 参数；
- Hot-L1 大小建议先覆盖 `N=16..2048`；`N=4096` 时 input/output 合计恰好为 32 KiB，受常量、栈和组相联冲突影响，作为 L1 容量边界点单独报告；
- 正确性测试必须先通过，PMU running ratio 异常的样本作废。

模拟范围定义为函数入口到 `ret`。真机报告同时给 raw call cycles 和扣除独立 harness 基线的 body cycles，比较口径在报告中固定。

## 11. 对比与误差处理

每个 N 输出：

- simulated cycles、measured median cycles、绝对和相对误差；
- 真机波动区间及模拟值是否落入区间；
- simulated dispatch/retire/critical-path/memory/resource stall 分解；
- ROB、scheduler、LQ、SQ 峰值；
- profile coverage 和未建模 uop 列表。

建议首轮验收阈值：

- Hot-L1 稳态区间（首轮 `N<=2048`）：中位相对误差不超过 10%；
- L2/L3：不超过 15%；
- DRAM：不超过 25%；
- 小 N 受固定调用和未建模分支影响，只报告，不作为首轮硬门槛；
- 不能只让一个 N 命中，必须同时保持跨 N 趋势和 hold-out 点。

误差超限时按以下顺序排查：trace/循环次数 -> 依赖 -> profile coverage -> benchmark 口径 -> cache 状态 -> 未建模结构。只有独立微基准证明参数不正确时，才提出 profile 变更；禁止直接最小化 softmax 周期误差。

## 12. 测试

### 12.1 单元测试

- 单依赖链：总周期等于 latency 累加；
- 多条独立 uop：验证 throughput/capacity；
- `0.5` cycle issue interval：验证整数 tick；
- 多 resource choice 和 occupancy；
- ROB、scheduler、LQ、SQ backpressure；
- 完成乱序、retire 顺序；
- 同一 trace 在 `in_order` 下不可绕过阻塞项，在 `out_of_order` 下可以绕过；
- 两种 execution model 的资源和完成事件口径一致；
- load hit/miss、带宽和 outstanding limit；
- store -> load alias 与非 alias；
- 缺失 recipe、未知 uop、环形依赖必须硬错误。

### 12.2 集成测试

- 小型手写通用 uop DAG 的逐周期 golden timeline；
- x86 softmax 动态循环次数、访存字节和 uop 数公式；
- 同一 semantic uop DAG 使用两个 synthetic profile 得到不同周期；
- x86/RVV 前端生成等价 DAG 时，同一 synthetic profile 的后端结果一致，证明核心无 ISA 分支；
- 固定 artifact/profile 输入的结果可复现。
- 事件日志、Perfetto JSON、DOT 和统计摘要引用相同的 instruction/uop ID 与周期。

## 13. 分阶段执行

### P0：冻结基线和 Contract

- 保存当前 profile hash 和 Spike/RVV 验证提交。
- 定义 versioned dynamic instruction/uop trace contract。
- 先扩展 `profile.schema.json` 的 `scalar_control_fit` 规范并提升 schema version，再向 Zen 4 profile 添加待测字段和 evidence 入口。
- 输出 Zen4 opcode coverage audit，不修改 profile。

验收：当前 softmax 每条动态 form 都被分类为 `timed` 或 `missing`，不存在隐式默认值。

### P1：真机 Benchmark

- 建立 exact-kernel cycle benchmark、固定运行脚本和原始结果格式。
- 完成 Hot-L1 N sweep、`N=4096` L1 容量边界测试和统计摘要。

验收：正确性、CPU/NUMA/SMT、PMU running ratio、compiler/flags 均可审核。

### P2：动态 Trace 与依赖

- 扩展 x86 静态前端，生成基本块和 operand role。
- 对给定 N 展开三个循环，生成地址和通用 uop DAG。

验收：动态 instruction/uop 数和 20*N 逻辑访存量可由独立公式核对；未知项硬错误。

### P3：Opcode Recipe 补充

- 为缺失 form 建独立微基准和候选 timing/effective decomposition 报告。
- 测量并拟合通用 scalar/control fallback，明确训练 N、hold-out N 和残差。
- 审核通过后仅新增 recipe/evidence，不改已有校准字段。

验收：Hot-L1 路径没有缺失 timing；softmax 测量不参与 recipe 数值选择。

### P4：事件驱动核心

- 实现 profile loader、binder、ROB、waiting window、queue、resource 和 completion event。
- 实现 `in_order/out_of_order` issue policy 开关和共享事件日志。
- 实现 Perfetto、Graphviz 和文本 timeline 导出。
- 完成纯 synthetic trace 单元测试。

验收：`src/simulator` 不含 x86/RVV mnemonic 判断，两种执行模式的逐周期 golden tests 通过，调度图与事件日志一致。

### P5：Hot-L1 对比

- 接入动态 softmax trace，输出总周期和瓶颈分解。
- 同时输出两种 execution model 的调度 trace；仅以 `out_of_order` 对比 Zen 4 真机周期，报告二者差值作为乱序收益。
- 生成第一版真机/模拟对比报告。

验收：满足 Hot-L1 阈值或给出可复现、未篡改 profile 的误差归因。

### P6：Cache 层次

- 加入 L2/L3/DRAM 有效模型和明确初始状态。
- 扩展容量边界 N sweep，做 policy 敏感性分析。

验收：不同工作集的命中层次和周期趋势正确，未建模政策的影响有边界。

### P7：跨 ISA 验收

- 保留后端对 RVV 的零特判。
- RVV profile 建立后，由 RVV 前端生成同一 trace contract 并运行后端。

验收：增加 RVV 不修改 scheduler/engine；没有 RVV profile 时只做功能和 trace 验证，不输出虚假性能周期。

## 14. 审核结论

1. 已同意首轮以 Hot-L1 `N=16..2048` 为重点，`N=4096` 作为 L1 容量边界，小 N 仅诊断。
2. 已同意 Hot-L1/L2-L3/DRAM 的误差阈值 `10%/15%/25%`。
3. 已同意缺失 opcode recipe 先生成独立候选报告，审核后才追加到 Zen 4 profile。
4. 已改为专门的微架构相关 scalar/control 拟合分组；实施顺序必须是 schema、Zen 4 profile、模拟器，且保留训练/验证隔离。
5. 历史结论：RVV 在没有具体微架构 profile 前只验证通用后端接口，不宣称周期准确性；
   XSAI profile 建立后已改用独立 `xsai-rvv` 执行后端，Zen4 通用后端保持冻结。
