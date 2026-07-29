# `softmax_sim` 项目分析

## 1. 结论

[`softmax_sim`](https://github.com/shinezyy/softmax_sim) 实现的是一个面向 RISC-V Vector Softmax 的**高层依赖/吞吐时序原型**：它构造一组抽象的 `LOAD`、`REDUCE`、`FMA`、`EXP2`、`STORE` 指令，将每条指令拆成微操作（μop），再按依赖、每周期带宽预算和固定延迟逐周期推进，最终输出总周期以及 instruction/μop 时间线。

它适合研究以下问题：

- 寄存器宽度、计算单元宽度和 cache 带宽变化对该抽象模型的影响；
- 顺序与简化乱序调度的相对差异；
- 把整条指令依赖改成 μop 级 forwarding 后，重叠执行可能带来的收益；
- 有无专用 `EXP2` 单元时，两种手写 Softmax 依赖图的差异。

但它不是 RISC-V ISA/功能模拟器，也不是经过真实 CPU 校准的周期精确微架构模拟器：不解析机器码、不计算 Softmax 数值、不维护寄存器值或内存地址，也没有真实前端、执行端口、ROB、cache hierarchy 和 TLB。当前实现还有若干会直接改变结果的代码问题。因此，更准确的定位是“可配置的 Softmax 调度模型原型”，不宜直接用其周期数预测硬件性能。

本文基于子模块提交 `eec7e5f1d21fea03af0ed019860e4ba6a60a2f2c` 做静态分析，未启动模拟器或性能测试。核心实现位于 [`softmax_simulator.py`](../third_party/softmax_sim/softmax_simulator.py)，设计说明位于其 [`README.md`](../third_party/softmax_sim/README.md)。

## 2. 仓库组成

项目很小，主要包含三个文件：

| 文件 | 作用 |
| --- | --- |
| `softmax_simulator.py` | 全部模型、调度器、命令行入口和文本报告，约 1200 行 Python |
| `README.md` | 设计目标、参数和使用示例 |
| `prompts_used_in_cursor_for_softmax_sim.txt` | 创建项目时使用的需求提示，可用于追溯原始设计意图 |

代码只依赖 Python 标准库。其基本数据流为：

```text
命令行参数
  -> ProcessorConfig
  -> 手工生成 Softmax Instruction DAG
  -> InstructionExecutor 将 instruction 拆成 μop
  -> 修补 reduce / memory / chaining 依赖
  -> VectorProcessor 逐周期完成与发射 μop
  -> 汇总总周期、instruction/μop 时间并打印 ASCII timeline
```

## 3. 模型中的对象

### 3.1 配置

`ProcessorConfig` 暴露以下抽象参数：

| 参数 | CLI 默认值 | 可选值或含义 |
| --- | ---: | --- |
| register width | 2048 bit | 512、1024、2048、4096 bit |
| reduce compute width | 512 bit | 128、256、512、1024 bit |
| simple elementwise width | 512 bit | `FMA` 每周期宽度 |
| complex elementwise width | 512 bit | `EXP2` 每周期宽度 |
| cache bandwidth | 64 B/cycle | 32、64、128 B/cycle，load/store 共享 |
| execution mode | in-order | in-order 或 out-of-order |
| chaining | 开启 | CLI 当前无法关闭 |
| OOO window | 128 μop | 仅用于简化乱序扫描窗口 |
| number of heads | 8 | 构造多少份互相独立的 Softmax 图 |
| sequence chunk | 2048 bit | 512、1024、2048、4096、8192 bit |

固定默认延迟为：`REDUCE=7`、`FMA=4`、`LOAD=10`、`STORE=10`、`EXP2=20` cycles。这些数值是模型输入，不是从某款处理器测量或推导的结果。

代码把数据元素固定解释为 BF16，即每个元素 16 bit；并没有 FP32、元素类型或混合精度参数。

### 3.2 Instruction

模型支持五种抽象 instruction：

- `LOAD`：从抽象内存加载一个向量；
- `REDUCE`：代表 max reduction 或 sum reduction，类型上不区分两者；
- `FMA`：同时被用来代表减 max、指数多项式步骤以及最终除法/缩放；
- `EXP2`：代表可选的专用复合逐元素运算；
- `STORE`：把向量写回抽象内存。

每条 instruction 只有人工编号、类型、数据大小、依赖 instruction ID 和一个主要用于打印/构图的目标寄存器编号。模型不会读取或写入寄存器内容，因而也不会自动发现 RAW、WAR、WAW、mask 或 memory alias 依赖。

### 3.3 MicroOp

每个 μop 记录所属 instruction、局部编号、类型、数据量、依赖、固定 latency 以及开始/完成周期。全局 μop 数组的下标同时充当依赖 ID。

μop 拆分规则如下：

- `FMA` / `EXP2`：假定 BF16，每个 μop 最多处理 `compute_width / 16` 个元素；一条 instruction 最多覆盖 `register_width / 16` 个元素。
- `REDUCE`：先按 `reduce_width / 16` 个元素分组并行规约，再生成树状的后续规约 μop。
- `LOAD` / `STORE`：把 `data_size / 8` 当作字节数，再按 `cache_bandwidth` 拆分；各 memory μop 之间没有串行依赖。

每类 μop 的执行队列没有容量上限。模型只在**发射当周期**扣除对应 byte budget，所以它表达的是一个可全流水、允许无限在途操作的固定延迟单元，而不是有限数量的真实执行管线。

## 4. Softmax 指令图

`create_softmax_instruction_stream()` 按 head 和 sequence chunk 手工生成依赖图。默认 `sequence_chunk=register_width=2048 bit`，所以每个 head 只有一个 chunk。

### 4.1 无 `EXP2` 单元

每个 chunk 的逻辑图为：

```text
LOAD 0 -> REDUCE 1 (max)
                    |
                    v
LOAD 2 -> FMA 3 -> FMA 4 -> FMA 5 -> FMA 6 -> FMA 7 -> FMA 8 -> STORE 9
                                                           |
                                                           v
                                                       REDUCE 10 (sum)

STORE 9 -> LOAD 11 -----------------------------------+
所有 chunk 的 REDUCE 10 ------------------------------+-> FMA 12 -> STORE 13
```

六条串联 `FMA 3..8` 只是一个计算量占位：代码没有减法、指数系数、舍入或特殊值语义。最后的 `FMA 12` 同样只是用来代表 `exp / sum`。

默认配置下，每个 head 有 14 条 instruction、58 个 μop；8 个 heads 共 112 条 instruction、464 个 μop。

### 4.2 有 `EXP2` 单元

中间六条 FMA 被一条 `EXP2 8` 替换：

```text
LOAD 0 -> REDUCE 1 -> LOAD 2 -> EXP2 8 -> STORE 9
                                  |
                                  +-> REDUCE 10
STORE 9 -> LOAD 11，LOAD 11 + REDUCE 10 -> FMA 12 -> STORE 13
```

默认配置下，每个 head 有 9 条 instruction、38 个 μop。值得注意的是，这条路径没有单独表示 `x - max`，因此连抽象 Softmax DAG 都不完整。

### 4.3 多 chunk 的含义

后续阶段会等待所有 chunk 的局部 max 或局部 sum reduction，但代码没有生成“把多个局部 max/sum 再合并成一个全局结果”的 reduction。因此，多 chunk 模式表达的是全局 barrier，而不是数值与依赖均完整的分块 Softmax。

## 5. 周期调度方式

每个模拟周期依次执行：

1. 清零本周期 load/store、reduce、FMA、EXP2 的带宽计数；
2. 将到达 `start_cycle + latency` 的 μop 标记为完成；
3. 按执行模式寻找可发射 μop；
4. 更新 chaining 的展示信息；
5. 周期加一。

μop 只有在其 μop 依赖全部完成，且残留的 instruction 依赖也全部完成后才能发射。

两种调度模式的代码实际行为是：

- **in-order**：查看开头最多 10 个尚未完成的 μop，跳过被阻塞者，找到一个可发射 μop后停止。因此它每周期最多发射 1 个 μop，而且并非严格顺序。
- **out-of-order**：从第一个未发射 μop 开始向后扫描 `ooo_window_size` 项，每周期最多发射 2 个 μop。窗口不限制已发射但未完成的在途操作，也没有 ROB、scheduler 或 retirement capacity。

load 和 store 共用每周期 cache byte budget；`REDUCE`、`FMA`、`EXP2` 各有独立的计算 byte budget。这里没有执行端口冲突，也没有前端解码、寄存器端口和不同算术操作共享流水线的情况。

## 6. Chaining 的实际实现

当 producer 可以产生逐元素结果、consumer 可以消费逐元素结果，且二者原本有 instruction 依赖时，代码尝试把整条 instruction 依赖改成一一对应的 μop 依赖。它要求数据大小相同，并要求双方 μop 数相同；reduce consumer 则要求 producer μop 数等于 reduce 第一层 μop 数。

这个实现带来的效果是：consumer 的第 `i` 个 μop 可以在 producer 的第 `i` 个 μop **全部完成**后开始，而不必等待整条 producer instruction 完成。

代码虽然计算了执行中 μop 的 `ready_elements`，但发射判断从不读取它；`chaining_granularity` 也不参与拆分或就绪判断。因此当前 chaining 是“μop 完成粒度 forwarding”，不是 README 所描述的“部分元素完成后即可转发”。

μop 数相等的断言还让本应独立的配置参数发生耦合。对 load → elementwise 的整寄存器路径，常见可用组合基本要求：

```text
cache_bandwidth [B/cycle] = elementwise_compute_width [bit] / 8
```

例如 `(32 B, 256 bit)`、`(64 B, 512 bit)`、`(128 B, 1024 bit)`；许多其他合法 CLI 组合会在建立 chaining 时触发断言，而不是产生模拟结果。

## 7. 输出能力

程序输出：

- 配置与生成的 instruction 列表；
- 总模拟周期；
- 每条 instruction 的 issue/start/complete 周期；
- 每个 μop 的 start/complete 周期；
- instruction 和 μop 两级 ASCII 时间线；
- `instruction_count / total_cycles` 得到的抽象 instruction throughput。

结果只打印到标准输出，没有稳定的 JSON/CSV schema。所谓 throughput 也只是该手写 instruction 图中的“指令/周期”，不能直接换算成 Softmax 元素吞吐或真实 ISA IPC。

## 8. 当前实现的主要问题

| 优先级 | 问题 | 对结果的影响 |
| --- | --- | --- |
| P0 | `data_size` 单位冲突 | dataclass 与算术路径把它描述/使用为 byte，memory 路径却再除以 8；指令流又传入 bit 数。默认整寄存器情况被 `min()` 偶然掩盖，部分长度会失真。 |
| P0 | 多级 reduce 依赖被扁平化 | μop 生成时建立逐层树依赖，但 `_fix_reduce_dependencies()` 随后让所有非首层 μop 都只依赖第一层；需要三层以上时，中间层和最终层会错误并发。 |
| P0 | 多 chunk Softmax DAG 不完整 | 没有合并局部 max/sum 的跨 chunk reduction；`EXP2` 路径还缺少 `x-max`。模型并不表达完整 Softmax 算法。 |
| P0 | instruction ID 会冲突 | `head_id=h*1000`、`chunk_id=i*100`；当一个 head 有 16 chunks 时，head 0 的 chunk 10 与 head 1 的 chunk 0 使用相同 ID。字典构造会静默覆盖 instruction。 |
| P1 | chaining 不支持部分结果 | `ready_elements` 与 granularity 不参与调度，只能做到 μop 完成后的 forwarding。 |
| P1 | 合法参数并不正交 | chaining 对 μop 数的断言让许多通过参数校验的 cache/compute width 组合直接失败。 |
| P1 | CLI 存在失效参数 | `--all-compute-widths` 默认恒为 512，三个独立 compute width 参数永远不会生效；`--chaining` 使用 `store_true` 且默认已为 true，无法关闭；granularity 没有 CLI。 |
| P1 | 调度名称与行为不一致 | in-order 会越过阻塞项且只能单发射；OOO 固定 2-wide，window 不约束在途数量，均不是 README 暗示的真实顺序/乱序处理器。 |
| P2 | 周期口径有额外一拍 | 在周期 `c` 发射、latency 为 `L` 的 μop 于 `c+L` 完成，而循环在下一次条件检查后结束；单 μop 的 `total_cycles` 通常表现为 `L+1`。 |
| P2 | 状态与报告不完整 | `instruction.started` 没有正常维护；无结构化输出；大量无条件 debug 文本；仓库没有自动化测试。 |

此外，模型没有以下真实硬件要素：

- 指令编码、decode/rename/dispatch/retire；
- 物理寄存器、flags、mask、WAR/WAW 和 register renaming；
- 执行端口、共享流水线、队列容量和 backpressure；
- 真实地址、load/store queue、memory ordering 与 alias；
- L1/L2/LLC/DRAM、cache line、TLB、miss 和预取；
- 分支、循环、频率变化、功耗状态与多核竞争；
- 数值、舍入、异常值和 Softmax 正确性。

因此 README 中的 “cycle-accurate” 和 “realistic” 应理解为“相对于这组抽象规则逐周期推进”，不能理解为对某款 RISC-V Vector CPU 的硬件级准确复现。

## 9. 可复用价值与使用建议

如果把该项目当作后续模拟器的对标原型，可以保留：

- instruction/μop 两级表示；
- 配置对象和固定随机性之外的确定性事件循环；
- 依赖时间线、关键路径可视化的工程形式；
- in-order 基线与 OOO 模型做差分对照的思路。

在做任何绝对性能研究前，应至少先完成：

1. 统一 bit、byte、element 的类型与单位；
2. 用无冲突 ID 或显式对象引用重建依赖图；
3. 修复逐层 reduction，并补齐多 chunk Softmax 数学 DAG；
4. 明确 FMA/EXP2 所代表的实际算法和精度合同；
5. 让 chaining granularity 真正参与 producer/consumer 就绪；
6. 建立自动化单元测试和机器可读结果；
7. 选择一款具体处理器，用微基准校准 latency、throughput、资源和内存参数。

对本项目计划中的 AVX-512 版本，不应简单替换枚举名称和寄存器宽度。AVX-512 的真实性能由具体 CPU 的指令解码、μop 拆分、执行端口、乱序窗口以及 cache/memory 系统共同决定。相应的完整研究路线见 [`softmax_sim_for_avx512.md`](softmax_sim_for_avx512.md)。
