# 通用 Uop 事件驱动模拟器

本文介绍 `softmax_sim_avx512` 模拟器的设计思想、核心数据结构、顺序/乱序执行模型、内存模型和结果可视化方法。

模拟器的目标不是复刻 Zen 4 的全部隐藏实现，而是在可解释、可校准的 profile 约束下，预测向量 kernel 的 core cycles，并让同一后端以后能够接收 RVV 等其他 ISA 的 uop。

## 1. 总体架构

完整数据流为：

```text
AVX-512 / RVV 汇编
        |
        v
ISA 前端：解析指令、展开控制流、计算地址、建立依赖
        |
        v
动态 semantic-uop trace
        |
        v
微架构 profile：recipe、latency、吞吐、资源和内存参数
        |
        v
动态 execution-uop DAG
        |
        v
ISA 无关事件驱动后端
        |
        +--> 总周期和瓶颈统计
        +--> JSONL 事件日志
        +--> Perfetto 调度时间线
        +--> Graphviz 依赖图
        +--> 文本时间线
```

这条边界最重要的约束是：ISA mnemonic 只允许出现在前端和 recipe 中。调度器不根据 `vmaxps`、`vfmacc.vv` 等指令名写特殊分支。

## 2. 为什么使用事件驱动模型

逐周期模拟会在每个周期扫描大量未变化的状态。事件驱动模拟只在以下时间点推进：

- 某个 uop 完成；
- 到达下一个 dispatch/retire 周期边界；
- 执行资源或 issue domain 释放；
- issue interval 到期；
- memory bandwidth 或 outstanding request 限制解除。

这样仍能保留周期级约束，但在长 latency 和大量动态指令下减少无效扫描。

profile 中存在 `issue_interval_cycles: 0.5`。为避免浮点累计误差，模拟器把时间转换为整数 tick：

```text
ticks_per_cycle = profile 中所有周期分数分母的最小公倍数
```

当前常见情况是一个周期包含两个 tick。

## 3. 输入模型

### 3.1 Macro-op

`MacroOp` 对应一个动态 ISA 指令实例，保存：

- 程序顺序和汇编文本；
- 绑定后包含的 execution uop ID；
- dispatch 和 retire 所占 macro-op 数；
- 是否占用 vector waiting window、load queue 或 store queue；
- dispatch、complete 和 retire 时间。

ROB 容量和 dispatch/retire 宽度按 macro-op 计数。

### 3.2 Semantic uop

semantic uop 描述跨 ISA 的含义，例如 `vector_fp_fma` 或 `vector_load`，不携带微架构时序。它由 `uops/uop_kinds.yaml` 统一定义。

### 3.3 Execution uop

`ExecutionUop` 是后端实际调度的节点，包含：

- `dependencies`：必须先完成的 producer；
- `latency_ticks`：发射后多久产生结果；
- `issue_interval_ticks`：同 scheduling class 两次发射的最小间隔；
- `occupancy_ticks`：执行资源被占用多久；
- `resource_choices`：允许使用的等效资源；
- `issue_domains`：跨资源共享的发射限制；
- 可选的 `part_index` 和 part 间隔；
- 可选的访存地址、访问宽度和 cache line。

latency、issue interval 和 occupancy 是三个不同概念。例如，一个 uop 可以 latency 为 4 周期，但执行资源只占用 1 周期，从而允许后续独立 uop 在结果尚未产生时进入流水线。

## 4. x86 动态前端

当前性能模拟入口实现了 x86 前端，代码位于 `src/frontends/x86.py`。

### 4.1 控制流展开

前端从 `softmax_avx512_f32` 入口开始解释当前支持的汇编形式，根据 `count` 和标量寄存器状态决定分支方向，生成一次函数调用的动态指令流。

这一步不能只读取静态指令列表。softmax 有三个循环，`N=16` 与 `N=4096` 的动态指令数量完全不同。

首版 x86 输入约束为：

```text
count > 0 且 count % 16 == 0
```

未知指令、未知 recipe、无法求值的地址或不支持的控制流都会直接报错。

### 4.2 寄存器依赖

前端维护“最近一次寄存器写者”，为每个动态指令建立 RAW 依赖：

```text
producer write register -> consumer read register
```

当前模型假设寄存器重命名消除了 WAR 和 WAW 假依赖，因此后端只保留真正影响结果就绪时间的 RAW 关系。x86 的 `eax/rax`、`xmm/ymm/zmm` 等别名会先规范化，flags 也有独立的 producer/consumer 关系。

### 4.3 访存依赖

前端计算抽象地址：

```text
base + index * scale + displacement
```

地址被归入 `input`、`output` 或常量区域，并转换成 cache line。对同一抽象地址建立必要的 store-to-load 和 store-to-store 顺序，不同地址可以乱序执行。

模型不读取或计算真实 softmax 数值；数值正确性由 kernel correctness 测试负责。

## 5. Profile 绑定

`src/simulator/profile.py` 负责将动态 semantic-uop trace 绑定成 execution-uop DAG。

### 5.1 精确 recipe 匹配

profile 使用如下 key 匹配指令：

```text
mnemonic:operand-class,operand-class,...
```

例如：

```text
vmaxps:memory,zmm,zmm
```

该 recipe 可以定义 AGU、load、两个 256 位 max part 以及它们之间的局部依赖。instruction-specific recipe 的优先级最高。

### 5.2 Scalar/control fallback

简单标量地址计算和分支若没有精确 recipe，可以使用 profile 中的 `scalar_control_fit`。fallback 仍生成正常 execution uop，参与依赖和资源竞争，而不是在最终周期上直接加一个常数。

只有 profile 明确允许的 semantic kind 才能使用 fallback。向量或 memory recipe 缺失时会报错，避免用未经验证的默认时序掩盖模型缺口。

### 5.3 等效向量分解

Zen 4 profile 将多数 512 位操作分解成两个 256 位 execution part，并规定 part 发射间隔。这个分解用于表达内部数据路径对吞吐和依赖的影响，不声称等于硬件真实物理 uop 数。

外部 RAW 依赖会尽量按相同 `part_index` 连接。例如前一条 ZMM 加法的 part 0 可以连接后一条操作的 part 0，从而避免把两个等效 part 错误串成完全串行。

## 6. 后端状态

AMD Zen 4 profile 当前提供的主要结构参数为：

| 状态 | 容量或宽度 | 模拟含义 |
|---|---:|---|
| Dispatch | 6 macro-op/cycle | 每周期最多进入后端的 macro-op |
| Retire | 6 macro-op/cycle | 每周期最多按程序序提交的 macro-op |
| ROB | 320 entries | 已 dispatch、尚未 retire 的 macro-op |
| Vector waiting window | 64 entries | 等待首次向量发射的指令 |
| Load queue | 44 entries | 尚未 retire 的 load 指令 |
| Store queue | 68 entries | 尚未 retire 的 store 指令 |
| Address generation | 3 slots | AGU 等效资源 |
| Load data | 2 slots，62 B/cycle | load-data 等效资源和带宽 |
| Store data | 1 slot，32 B/cycle | store-data 等效资源和带宽 |

此外还有 vector-fp、vector-integer、conversion、shuffle 资源和 `fp-add-fma-convert` 共享 issue domain。

这些资源是可校准的等效容量，不表示每种 opcode 都能使用资源组中的全部物理 pipe。

## 7. 一次事件循环

在时间 `now`，后端按固定顺序执行：

1. Complete：处理到期事件，将 producer 标为完成并唤醒依赖者。
2. Dispatch：若位于整数周期边界，按程序序最多 dispatch 6 个 macro-op；ROB 或队列满时停止。
3. Issue：寻找已 dispatch 且依赖满足的 execution uop，检查 issue interval、资源、issue domain 和 memory 限制。
4. Complete fixed point：处理零延迟或同 tick 可完成的动作，直到当前 tick 不再变化。
5. Retire：若位于整数周期边界，从 ROB 头部按程序序最多 retire 6 个 macro-op。
6. 跳转到下一个可能改变状态的 tick。

完成并不等于 retire。后面的指令可以先完成，但只有 ROB 头部完成后才能按程序序提交。

### 7.1 Dispatch 阻塞

常见原因包括：

- `rob_full`；
- `vector_scheduler_full`；
- `load_queue_full`；
- `store_queue_full`。

vector waiting window 在指令的第一个向量 execution uop 发射时释放；ROB、load queue 和 store queue 在 macro-op retire 时释放。

### 7.2 Issue 阻塞

常见原因包括：

- `dependency`：producer 尚未完成；
- `part_order` / `part_gap`：向量分解的前一 part 尚未发射或间隔未到；
- `issue_interval`：同类 uop 发射过快；
- `resource_busy`：所有候选资源均被占用；
- `issue_domain_busy`：共享发射域达到容量；
- `memory_bandwidth`：命中层次的读写带宽尚未释放；
- `memory_outstanding`：未完成 miss 数达到上限。

一个 uop 可能在多个 tick 遇到不同阻塞，结果中会同时保存最后阻塞原因和累计 blocker 观察值。

## 8. 顺序与乱序执行开关

两种模式使用同一份动态 trace、profile、资源和内存模型，差别只在 issue 选择策略：

| 行为 | `out_of_order` | `in_order` |
|---|---|---|
| Dispatch | 按程序序 | 按程序序 |
| Issue | 从已 dispatch uop 中按 oldest-ready 选择，可跳过阻塞项 | 只检查全局下一条 execution uop，阻塞时不能越过 |
| Complete | 可乱序 | 由顺序发射自然约束 |
| Retire | ROB 头部按程序序 | ROB 头部按程序序 |

乱序模式用来模拟真实 OoO 后端对独立 load 和计算的重叠。顺序模式是诊断基线，不代表 Zen 4 的真实性能。

如果两者周期非常接近，通常说明关键路径串行、并行度不足，或两者都被同一个吞吐资源限制。如果顺序模式明显更慢，则说明乱序窗口成功隐藏了部分 latency。

## 9. 内存层次

`src/simulator/memory.py` 实现确定性的 set-associative LRU 有效模型：

```text
L1D -> L2 -> L3 CCD -> DRAM
```

每层由 profile 给出：

- 容量、路数和 cache line 大小；
- load latency；
- 读写 bytes/cycle；
- 最大 outstanding miss/request 数。

同一 cache line 的 pending fill 可以被后续访问复用。cache fill 使用包含式的确定性替换规则，保证相同输入产生相同结果。

支持三种初始状态：

- `hot-l1`：整个工作集预置于 L1；若集合映射后无法容纳则报错；
- `hot-capacity`：预置于第一个能够容纳工作集的 cache 层；
- `cold`：所有 cache 初始为空。

当前 load latency 由实际命中层次替换，store 使用 profile 的等效 store recipe，同时受写带宽和 cache 状态约束。

## 10. 运行模拟器

先安装 Python 依赖：

```bash
python3 -m pip install -r softmax_sim_avx512/requirements.txt
```

生成汇编：

```bash
softmax_sim_avx512/kernel/softmax/scripts/build_assembly.sh
```

从 `softmax_sim_avx512` 目录运行一个 `N=256`、hot-L1、乱序模拟：

```bash
cd softmax_sim_avx512

python3 -m src.simulator.cli \
  --isa x86 \
  --assembly kernel/softmax/artifacts/x86/softmax_avx512.s \
  --function softmax_avx512_f32 \
  --recipe recipes/x86.yaml \
  --uop-kinds uops/uop_kinds.yaml \
  --profile profiles/amd_zen4.yaml \
  --schema schemas/profile.schema.json \
  --count 256 \
  --execution-model out_of_order \
  --cache-mode hot-l1 \
  --output-dir artifacts/simulator/tutorial-n256
```

切换成顺序发射只需修改：

```bash
--execution-model in_order
```

仿真输出位于 `artifacts/simulator/`，该目录属于可重复生成产物，已被 Git 忽略。

## 11. 输出与可视化

每次运行生成：

| 文件 | 用途 |
|---|---|
| `dynamic_trace.json` | ISA 前端生成的动态指令、semantic uop、地址和依赖 |
| `result.json` | 总周期、逐指令/逐 uop 时间戳和瓶颈摘要 |
| `schedule_events.jsonl` | dispatch、ready、issue、complete、retire 原始事件流 |
| `schedule_perfetto.json` | 可交互调度时间线 |
| `dependencies.dot` | execution-uop 依赖图 |
| `timeline.txt` | 小规模文本时间线 |

### 11.1 Perfetto

把 `schedule_perfetto.json` 拖入 `https://ui.perfetto.dev/`。视图包含：

- 每条 instruction 的 waiting、executing 和 retire-wait 区间；
- 每个执行资源 lane 上的 uop；
- producer 到 consumer 的 RAW flow arrow；
- ROB、vector scheduler、load queue 和 store queue occupancy。

大 trace 可以通过 `--visual-start` 和 `--visual-limit` 只导出感兴趣的动态指令区间。

### 11.2 Graphviz

若系统安装了 Graphviz：

```bash
dot -Tsvg artifacts/simulator/tutorial-n256/dependencies.dot \
  -o artifacts/simulator/tutorial-n256/dependencies.svg
```

DOT 图适合检查依赖是否正确，Perfetto 更适合检查资源竞争和时间重叠。

### 11.3 文本时间线

```bash
sed -n '1,100p' artifacts/simulator/tutorial-n256/timeline.txt
```

标记含义为：`D` dispatch、`I` first issue、`E` complete、`R` retire。同一周期多个状态重合时显示 `*`。

## 12. 如何分析结果

建议按以下顺序定位瓶颈：

1. 检查 `dependency_critical_path_cycles`，判断纯依赖链下界。
2. 查看 `resource_issues`，确认 execution uop 实际分配到哪些资源。
3. 查看 `issue_blocker_observations`，判断依赖、执行资源、issue domain 或 memory 是否主导。
4. 查看 `peak_rob` 和各队列峰值，确认窗口是否限制并行度。
5. 查看 `cache_line_accesses`，验证 cache mode 与工作集预期一致。
6. 对照 in-order 结果，估计乱序执行隐藏 latency 的收益。
7. 最后与真机的中位数、MAD 和 p10-p90 对比，而不是只对照一次测量。

总周期误差不能直接归因于某一个 profile 参数。应先确认动态路径、依赖、cache 初态和 recipe coverage，再决定是否需要独立微基准。

## 13. 校准与验证原则

项目采用以下约束避免过拟合：

1. pipeline、vector 和 memory 参数优先由独立 profile benchmark 测量。
2. exact physical uop 无法观测时，只声明等效分解。
3. scalar/control 拟合项放在 profile 中并参与正常调度，不散落在代码里。
4. softmax 用作综合 hold-out 负载，不能为了单个 N 的周期一致而任意修改 profile。
5. 真机报告使用序列化、baseline-subtracted core cycles，并记录中位数和波动区间。
6. 每次结果记录 profile SHA-256，使时序结果能够追溯到具体配置。

批量对比入口为：

```bash
python3 softmax_sim_avx512/kernel/softmax/scripts/compare_cycles.py \
  softmax_sim_avx512/kernel/softmax/workloads/softmax.yaml \
  softmax_sim_avx512/artifacts/simulator/comparison
```

## 14. 当前边界

首版模型有意不包含：

- 分支预测与误预测恢复；
- 详细取指、解码、uop cache 和 rename 前端；
- TLB、硬件预取器和 page walk；
- SMT 干扰；
- 频率、温度和操作系统调度；
- mask、gather/scatter 和复杂 permutation；
- store buffer forwarding、写合并等精细内存机制。

这些缺失机制解释了为什么模拟结果允许存在合理误差。新增机制时应先确认它对目标 kernel 有可观测影响，并通过 schema/profile 显式配置。

## 15. 扩展到 RVV

当前 CLI 的性能路径只启用了 x86；RVV kernel 已通过 Spike 做功能验证，但尚无目标 RVV 微架构 profile。

接入 RVV 周期模拟时需要新增：

1. RVV 动态前端：解释 `vsetvli`，根据 AVL、VLEN、SEW 和 LMUL 展开循环；
2. RVV profile：定义 pipeline、资源、memory 和 instruction recipe；
3. RVV 目标机器的独立参数 benchmark 与真机周期数据。

不需要修改事件驱动调度器的 ISA 规则。只要 RVV 前端生成相同 contract 的动态 semantic uop，profile binder 生成相同结构的 execution uop，后端就能复用。
