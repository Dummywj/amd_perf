# 微架构 Profile 参数测试方案

## 1. 目标与边界

本方案只为大模型推理中的直线型向量 kernel 提供周期级参数。测试对象是单个物理核，SMT 同胞线程空闲，数据放在本地 NUMA 节点。

Profile v2 不建模以下内容：

- mask、gather/scatter、slide 类复杂向量语义；
- 分支预测、错误预测恢复和复杂控制流；
- 指令缓存、op cache、TLB 和预取器内部状态；
- 频率和功耗状态。

保留基本 shuffle/conversion，是因为 softmax 的归约、量化和数据类型转换仍可能使用它们。存储系统保留“有效延迟、有效带宽、有效并发数”，不尝试复原全部物理结构。

## 2. 已知初值

[AMD Zen 4 Software Optimization Guide](https://www.amd.com/content/dam/amd/en/documents/processor-tech-docs/software-optimization-guides/57647.zip) 给出 6 macro-op/cycle 分派、非 SMT 下 320 项重排序容量、两组 32 项浮点调度器及执行资源组织。[4th Gen AMD EPYC 架构白皮书](https://www.amd.com/content/dam/amd/en/documents/products/epyc/4th-gen-amd-epyc-processor-architecture-whitepaper.pdf) 给出每核 1 MiB L2、CCD 级 L3，以及 512 位 AVX 数据在内部 256 位数据通路上分两拍执行。目标机的 CPU 型号、ISA 和 cache 拓扑再由 `lscpu` 与 sysfs 核对。

这些值可直接作为 profile 初值，但仍要用微基准做一致性检查，防止 CPU stepping、SMT 状态或测试环境不匹配。

## 3. 公共测试规范

1. 用 `taskset` 固定到一个物理核，并保证同胞线程空闲；内存通过 `numactl` 放在该核所在节点。
2. 测试主体使用手写汇编或固定的 `.S` 模板。每次保存机器码、反汇编、CPU family/model/stepping、microcode 和内核版本。
3. 采用长展开的直线指令块；唯一循环分支的开销用空循环基线扣除。先预热，再至少重复 30 次，报告中位数和置信区间。
4. 主计数使用未暂停的核心周期和对应 PMC；指令延迟、cache/DRAM load 延迟用 AMD IBS 交叉验证。[AMD uProf 的 IBS 文档](https://docs.amd.com/r/en-US/57368-uProf-user-guide/7.9.3.2.4.-IBS-Derived-Events) 可提供 tag-to-retire、completion-to-retire 及 cache/DRAM load latency。
5. Profile 不保存频率，但测试期间仍需固定 governor、功耗状态和负载条件。频率变化会改变以“核心周期”表示的 DRAM 延迟，必须作为原始实验元数据保存。
6. 对容量类参数扫描指令数或并发流数，以分段回归寻找性能拐点；对吞吐类参数增加独立依赖链，直到结果不再受 latency 限制。

依赖链测 latency、独立链测 reciprocal throughput、混合指令测资源冲突的方法参考 [uops.info](https://arxiv.org/abs/1810.04610)；低开销 PMC 测量框架可参考 [nanoBench](https://arxiv.org/abs/1911.03282)。

## 4. Pipeline 参数

| Profile 参数 | 可获得程度 | 测试原理 | 测试方法 |
|---|---|---|---|
| `dispatch_macro_ops_per_cycle` | 可验证，初值 6 | 当后端不阻塞时，单位周期进入后端的 macro-op 数达到平台上限 | 用多种简单、互不依赖且分散执行资源的指令填满展开块；读取 dispatch-slot PMC，逐步增加每轮指令数。若后端先饱和，则以 AMD 文档值为准，测试只做一致性检查 |
| `retire_macro_ops_per_cycle` | 只能估计有效值 | 在 ROB 头部长延迟操作完成后，已完成指令会集中退休，排空斜率受退休宽度限制 | 用一条 cache-miss load 暂停 ROB 头，后接大量可提前完成的简单操作；重复“阻塞-排空”，结合 retired-op 与周期计数估计排空速率。没有逐周期退休跟踪时无法证明物理峰值 |
| `rob_entries` | 可估计，初值 320 | 两条独立长延迟链能否同时在飞，取决于二者之间的指令数是否超过窗口 | 构造两条互不相关的随机 pointer chase，中间插入 `K` 个不产生新寄存器结果的 filler；扫描 `K`，第二条 miss 不能再提前启动时出现延迟台阶。再换成产生结果的 filler，排除物理寄存器先耗尽。方法参考 [ROB 容量测试](https://blog.stuffedcow.net/2013/05/measuring-rob-capacity/) |
| `vector_scheduler_entries` | 可估计有效容量，初值 64 | 等待未就绪操作数的向量指令会占据 scheduler；达到容量后，后续独立探针不能分派 | 先制造一个长延迟 load，再放入 `K` 条依赖该 load 的向量操作，最后放独立探针；扫描 `K` 找停顿拐点。分别用 add/mul/shuffle/conversion，识别两组 32 项分区及 opcode 分配。Zen 4 调度器争用测试可参考[该研究](https://arxiv.org/abs/2404.07042) |
| `load_queue_entries` | 只能估计有效容量 | 大量未完成 load 会占用 load queue，满后前端或地址生成停顿 | 在 ROB 头设置长延迟依赖，随后发出 `K` 个不同 cache line 的独立 load；扫描 `K`，用 load-dispatch stall、总周期和 IBS 判断拐点。结果可能同时受 ROB、MSHR 限制，需用命中 L1 与未命中 L3 两组对照 |
| `store_queue_entries` | 只能估计有效容量 | 地址或数据未就绪的 store 会长期占据 store queue | 让 `K` 个 store 的地址依赖一条长延迟 load，数据和目标缓冲区彼此独立；扫描 `K` 并观察 dispatch stall 拐点。再改为“地址已知、数据未就绪”以区分地址队列和数据队列影响 |

容量测试得到的是当前 profile 所需的“有效可用项数”。如果多种隐藏队列在同一点先耗尽，仅靠总周期不能唯一反推出每个物理队列的大小。

## 5. 执行资源与 Recipe 参数

### 5.1 单条指令模板

对 kernel 实际出现的每种 canonical form 分别生成测试，例如寄存器版本与内存版本、XMM/YMM/ZMM 版本不能共用结果。

| Profile 参数 | 可获得程度 | 测试原理与方法 |
|---|---|---|
| `decoded_macro_ops`、`retire_macro_ops` | 架构指令数可确认；隐藏融合只能估计 | 用 retired-instruction/macro-op PMC 测单一 opcode 展开块，并与相同长度的基线比较。内存操作数版本再与“显式 load + 寄存器版本”做差分。PMC 若只报告架构指令，就不能证明内部融合或物理 uop 数 |
| `uops[].latency_cycles` | 可估计 | 构造目标操作的最短真依赖链，测 `cycles / N`，扣除循环与必要 move 的基线。对多输入指令逐一改变依赖的输入到输出路径 |
| `uops[].issue_interval_cycles` | 可估计 | 使用足够多的独立寄存器链隐藏 latency，增加展开度直到 `cycles / N` 稳定；该稳定值即 reciprocal throughput |
| `resource_choices` | 可推断等价资源组 | 先测 opcode A、B 各自吞吐，再按不同比例混合。若混合吞吐低于两个独立瓶颈之和，则二者争用资源。对全部 kernel opcode 形成 pairwise contention matrix，并用 FP pipe PMC 交叉验证 |
| `resource_occupancy_cycles` | 只能估计 | 结合单 opcode 吞吐、可用 pipe 数和混合争用结果拟合最小占用时间。若一个指令产生多个隐藏操作且 PMC 不逐 pipe 暴露，就只能得到等效占用 |
| `depends_on` | 可由 ISA 确定 | 从显式寄存器、flags 和内存地址依赖生成，不靠计时猜测；再用破坏依赖/保留依赖的 A/B 指令流验证是否存在隐含依赖 |

### 5.2 512 位拆分

对同一 opcode 分别运行 XMM、YMM、ZMM 的依赖链和独立链，并读取 FP pipe 计数：

- 若 ZMM 的资源占用约为 YMM 的两倍，并出现连续两拍占用，则支持 `parts: 2`、`part_width_bits: 256`、`part_issue_gap_cycles: 1`；
- 用交替 YMM/ZMM 流和不同 pipe 类 opcode 检查两半是否固定占用同类资源；
- 对 producer/consumer 的低半和高半分别构造链，只能测试“是否观察到分半转发”。重命名、唤醒和寄存器别名可能掩盖物理 ready 时刻，因此 v2 不保存 per-part ready policy。

### 5.3 资源容量

| Profile 资源 | 可获得程度 | 测试方法 |
|---|---|---|
| `vector-fp.capacity` | 可验证聚合值，初值 4 | 使用 add/mul/FMA 不同混合比例，结合 FP pipe PMC 建立 eligibility matrix。`capacity: 4` 只表示聚合 pipe 数，不表示每个 opcode 都能使用四条 pipe |
| `vector-integer.capacity` | 可估计 | 对整数 add/mul/logic 分别做独立流和两两混合；由饱和吞吐及争用关系拟合等效 pipe 数 |
| `shuffle.capacity` | 可估计 | 对 kernel 会用到的基本 permute/unpack/reduction 指令做单流与 FP/整数混合测试。复杂跨 lane 操作不纳入通用模型，必须单独 recipe |
| `conversion.capacity` | 可估计 | 对 FP32/BF16/INT8 转换做独立链与混合流，判断是否共享 FP、整数或专用资源 |
| `address-generation.capacity` | 可验证聚合值，初值 3 | 用地址彼此独立的 load/store 组合，固定数据端命中 L1；扫描每周期内存操作数并改变 load/store 比例，区分 AGU 与数据通路瓶颈 |
| `load-data.capacity/bytes_per_cycle` | 可估计有效值 | 使用 L1 命中的独立对齐 vector load，多累加器消费数据；逐步增加 load 数并用 L1 PMC 确认没有下层 miss |
| `store-data.capacity/bytes_per_cycle` | 可估计，容量初值 2 | 使用 L1 命中的独立对齐 vector store，目标循环覆盖固定小缓冲区；分别测普通 store 和 non-temporal store，profile 默认只采用 kernel 实际使用的类型 |

## 6. Cache 与 DRAM 参数

| Profile 参数 | 可获得程度 | 测试原理与方法 |
|---|---|---|
| `cache_line_bytes`、`size_bytes`、`ways`、`shared_by_cores` | 可直接读取并验证 | 先读 CPUID/sysfs。再用随机 pointer chase 扫 working-set size 和 stride，延迟台阶给出容量；构造同 set 地址并增加地址数，冲突台阶验证 ways。经典方法参考 [lmbench](https://lmbench.sourceforge.net/lmbench-usenix.pdf) |
| 各级 `latency_cycles` | 可估计分布 | 使用每一步依赖前一步的随机 pointer chase，使目标 working set 稳定驻留 L1/L2/L3；依赖链消除 memory-level parallelism，随机排列抑制预取。用 IBS hit-level 与 load latency 分桶 |
| 各级 `read_bytes_per_cycle` | 可估计有效值 | 多个独立对齐 load 流，working set 分别限制在目标层且大于上一层；用足够多累加器隐藏 load-use latency，按实际传输字节除以核心周期 |
| 各级 `write_bytes_per_cycle` | 可估计有效值 | 用独立 store 流并控制 working set；同时记录 write-allocate/read-for-ownership 流量。结果按 simulator 采用的“请求字节”或“总层间流量”统一口径，二者不能混用 |
| 各级 `max_outstanding_misses` | 只能估计有效上限 | 同时启动 `K` 条独立随机 miss 链，扫描 `K`；平均延迟不再被隐藏或带宽达到平台时的拐点给出有效 MLP 上限。LQ、ROB、fill buffer 与下层 fabric 都可能先成为瓶颈 |
| `dram.latency_cycles` | 可估计分布 | working set 大于 CCD L3，使用 NUMA-local、随机、单依赖 pointer chase；IBS 只保留 DRAM hit 样本，报告中位数及高分位数 |
| DRAM `read/write_bytes_per_cycle` | 可估计当前平台有效值 | 单核运行大于 LLC 的顺序多流 load/store，使用实际 kernel 的普通或 non-temporal 访问形式；由内存控制器/数据 fabric PMC 统计真实字节，再除以核心周期 |
| `dram.max_outstanding_requests` | 只能估计有效上限 | 增加独立随机流数量，直到 DRAM 带宽不再提升；拐点是单核可利用的有效并发数，不能唯一分解为 core MSHR、I/O die、内存控制器各自容量 |

## 7. 无法可靠反推的内容

以下内容仅靠用户态特殊指令流无法得到唯一物理答案：

- **精确物理 uop 数和融合边界**：AMD PMC 多数暴露 macro-op、退休操作或某类执行计数，512 位内部拆分不等于前端产生两个可独立调度的物理 uop。因此 recipe 的 `uops` 明确定义为模拟器等效分解。
- **所有 opcode 的精确 pipe 编号**：只有当 PMC 对目标操作提供可解释的逐 pipe 计数时才能定位；否则不同 pipe 拓扑可能产生相同的吞吐和争用结果，只能保存等价资源集合。
- **分区 scheduler、LQ/SQ 与 MSHR 的独立物理容量**：多个结构可能在同一测试中同时限制 dispatch。可以通过对照流减少歧义，但通常只能得到有效下界或上界。
- **cache 替换策略、预取器状态机和片上 fabric 仲裁**：它们依赖地址历史、其他核心和固件状态，且已超出 v2 的确定性 MVP；统一折算到有效 latency、bandwidth 和 outstanding limit。
- **频率引起的长期动态行为**：profile 只预测周期。测试可固定并记录运行条件，但不把温度、boost、功耗状态建成参数。

对上述内容不应填写猜测数字。若等效模型尚未通过至少两个不同指令流验证，YAML 保持 `measure`。

## 8. 实施顺序与验收

1. `P0-static`：采集 CPUID/sysfs，并核对 AMD 文档初值。
2. `P1-recipe`：只测 softmax/LLM kernel 反汇编中真实出现的 opcode form，得到 latency、throughput 和 512 位拆分。
3. `P2-contention`：建立这些 opcode 的资源争用矩阵，再填 pipe eligibility 与 occupancy。
4. `P3-window`：测 ROB、vector scheduler、LQ/SQ；这些参数只在长依赖或大量并发访存时重要。
5. `P4-memory`：测各级 cache 和 NUMA-local DRAM 的有效周期参数。
6. 用未参与拟合的 softmax/归一化/量化 kernel 做 hold-out 验证；按总周期、前端停顿、执行资源停顿和 memory stall 分项比较。

每个数值必须关联原始汇编、命令、计数器原始值、重复次数、置信区间和 profile 字段。测试结果跨两次独立运行不稳定，或无法排除另一个更早瓶颈时，该字段继续保留 `measure`。
