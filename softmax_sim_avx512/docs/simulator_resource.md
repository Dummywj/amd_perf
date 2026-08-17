# 模拟器硬件资源模型

## 1. 文档范围

本文说明模拟器如何使用 [amd_zen4.yaml](../profiles/amd_zen4.yaml) 中的资源参数，
以及 [engine.py](../src/simulator/engine.py) 和
[memory.py](../src/simulator/memory.py) 如何实现这些约束。

这些资源是周期模拟所需的**等效资源**，不是对 Zen 4 隐藏物理 uop、端口编号或
内部连线的精确复刻。尤其是 512-bit 指令拆成两个 256-bit execution part，只用于
表达当前 profile 下的吞吐、延迟和依赖行为。

## 2. 四个时序参数

理解资源模型时必须区分以下概念：

| 参数 | 含义 |
|---|---|
| `capacity` | 同类资源包含多少个可独立占用的 lane |
| `latency_cycles` | uop 发射后，结果经过多少 cycle 才能被依赖者使用 |
| `resource_occupancy_cycles` | uop 发射后，所选资源 lane 被占用多少 cycle |
| `issue_interval_cycles` | 同一 scheduling class 的相邻 uop 最小发射间隔 |

如果 `latency > occupancy`，表示资源是流水化的。例如 FMA latency 为 4 cycle，
但 occupancy 为 1 cycle：当前 FMA 的结果要 4 cycle 后才可用，执行 lane 在 1 cycle
后即可接收另一个独立 uop。

`issue_interval_cycles` 不是整个资源的全局间隔。模拟器的 scheduling class 由
指令 form、recipe uop ID 和可选的 part index 组成；不同 class 仍会受到共享资源
capacity 和 issue domain 的限制。

`issue_domains` 指定一个 uop 还必须经过哪些共享域，`issue_domain_demands` 指定它在
各域一次消耗多少 token。未显式配置的需求默认为 1；属于多个域的 uop 必须同时通过
全部域的容量检查。

对于拆成两个 part 的 512-bit 指令，binder 默认把 profile 中的 part interval 乘以
part 数。当前多数 recipe 中的 `0.5 cycle * 2 parts` 因而成为每个 part stream 的
1-cycle 有效间隔；part 0 和 part 1 还必须保持 1-cycle `part_issue_gap`。若 recipe
显式设置 `scale_issue_interval_by_parts: false`，则保留原 interval；当前整数 add/shift
使用这一例外。

## 3. Pipeline 和窗口资源

| 资源 | 当前值 | 模拟行为 |
|---|---:|---|
| Dispatch width | 6 macro-ops/cycle | 只在整数 cycle 边界 dispatch |
| Retire width | 6 macro-ops/cycle | 按程序顺序 retire |
| ROB | 320 entries | 从 dispatch 占用到 retire |
| Vector waiting window | 64 entries | 含向量 uop 的指令从 dispatch 占用；该指令第一个向量 uop 发射时释放 |
| Load queue | 44 entries | 含 load 的指令从 dispatch 占用到 retire |
| Store queue | 68 entries | 含 store 的指令从 dispatch 占用到 retire |

乱序模式会按程序顺序扫描所有已 dispatch 且未发射的 execution uop，允许 younger
ready uop 越过被依赖或资源阻塞的 older uop。顺序模式只检查全局下一条 uop。

当前后端没有单独设置全局 execution-uop issue width。一个 tick 内能发射多少 uop，
由资源 capacity、occupancy、scheduling-class interval、issue domain、访存带宽和依赖
共同决定。Dispatch width 不能当作 execution issue width 使用。

## 4. Load 和 Store 模型

### 4.1 一条访存指令如何执行

访存指令通常拆成：

```text
address_generation -> load_data/store_data -> dependent compute
```

AGU 先产生有效地址，load/store data uop 再访问内存层次。AGU latency 为 0，事件后端
通过同 tick 的 fixed-point 迭代，允许依赖它的 data uop 在同一 tick 继续发射。

| 资源 | Capacity | 带宽 | 常用 latency | Interval | Occupancy |
|---|---:|---:|---:|---:|---:|
| Address generation | 3 | - | 0 | 1 | 1 |
| Load data | 2 | 62 B/cycle | 由命中层次决定 | 0.5 | 1 |
| Store data | 1 | 32 B/cycle | 1 | 1 | 2 |

`resources.load-data/store-data.bytes_per_cycle` 保存资源侧的校准值；当前真正参与
发射阻塞判断的是命中 memory level 的读/写带宽。L1D 的 62/32 B per cycle 与资源
侧数值一致，因此 hot-L1 下两组约束表达同一个已校准吞吐事实，而不是重复扣减两次。

load recipe 中写出的 4-cycle latency 会在发射时被实际命中层次覆盖。load-data lane
只占用 1 cycle，load 结果则可能在 4、14、54 或 373 cycle 后完成。因此 load 单元
是流水化的，等待 cache/DRAM 的请求不会一直占着 load-data lane。

当前 64-byte ZMM store 使用一个 store-data lane，occupancy 为 2 cycle；这和
32 B/cycle 的 store 带宽一致。因此当前模型下，同一 store-data 资源不能每 cycle
开始一条 64-byte store。

### 4.2 是否支持多访存并行

**支持。**并行访存体现在以下几个层次：

- 两个 load-data lane 可以重叠执行两个 load uop；lane 释放后，早先 load 的 cache
  latency 仍可继续进行。
- Load queue 可保留最多 44 条含 load 的未 retire 指令，因此可以存在多条 in-flight
  load。
- Store queue 可保留最多 68 条含 store 的未 retire 指令。
- Load 和 store 使用独立 data 资源以及独立的读写带宽时间线，因此二者可以并行；
  但它们共享三个 AGU、ROB、依赖和 cache 容量状态。
- Cache miss 和 DRAM request 有独立 outstanding 上限，允许 memory-level
  parallelism，而不是等待一条 miss 完成后再发下一条。

并行不等于无限并行。同一 cache level、同一访问方向使用一条聚合带宽时间线。
例如 L1D 读取带宽为 62 B/cycle，64-byte load 会占用约 `64/62` cycle 的 L1 read
bandwidth。即使存在两个 load-data lane，连续 64-byte L1 load 仍会受到这条带宽约束。

Load 和 store 的带宽时间线彼此独立，所以 L1 read 62 B/cycle 和 write 32 B/cycle
可以同时推进。该模型表达的是等效聚合带宽，不模拟具体 load/store port 组合。

### 4.3 Memory-source FMA 跨迭代重叠限制

模拟器可以限制“load 已发射、但依赖它的 FMA execution uop 尚未全部发射”的复合组数量。
组的识别只依赖 semantic uop 类型和同一 macro-op 内的依赖图，不检查 x86 mnemonic，
因此其他 ISA 前端生成相同 semantic uop 后也可复用。

Zen 4 profile 默认开启该限制：`max_pending_groups: 2`，且只匹配
`vector_fp_fma`。它用于约束 memory-source FMA 被等效拆成 load 和 compute 后产生的
过度跨迭代重叠；普通 vector add、conversion 和 integer uop 不受影响。

CLI 可用 `--memory-compute-overlap-limit` 显式开启，或用
`--no-memory-compute-overlap-limit` 关闭。Python API 的
`memory_compute_overlap_limit=None` 表示跟随 profile，`False` 用于复现旧基线。
该数值是低置信度的等效调度约束，不代表 Zen 4 存在容量恰为 2 的物理队列。

### 4.4 Cache 和 DRAM 参数

| 层次 | 容量/相联度 | Latency | 读带宽 | 写带宽 | 最大 outstanding |
|---|---|---:|---:|---:|---:|
| L1D | 32 KiB / 8-way | 4 | 62 B/cycle | 32 B/cycle | 10 misses |
| L2 | 1 MiB / 8-way | 14 | 32 B/cycle | 31 B/cycle | 20 misses |
| L3 CCD | 96 MiB / 16-way | 54 | 24 B/cycle | 27 B/cycle | 28 misses |
| DRAM | NUMA-local effective model | 373 | 9 B/cycle | 9 B/cycle | 28 requests |

Cache line 为 64 bytes。Cache 使用确定性的 set-associative LRU 和 inclusive fill。
同一 cache line 已有 pending fill 时，后续访问会合并到同一完成时间，不再次占用
miss outstanding 名额或该层次带宽。

初始状态支持 `hot-l1`、`hot-capacity` 和 `cold`：

- `hot-l1`：工作集预置在 L1D，若实际装不下则报错；
- `hot-capacity`：预置到能够容纳整个工作集的最近 cache level；
- `cold`：cache 初始为空。

当前未模拟 TLB、硬件预取器、store-to-load forwarding、bank conflict、write-combining
和每个物理访存端口的精确资格集合。

## 5. 向量计算资源

所有向量执行资源按等效 256-bit 宽度建模。多数 ZMM 操作会拆成两个 part，且 part 1
至少比 part 0 晚 1 cycle 发射。

通常整条指令的 issue interval 会按 part 数折算到每个 part stream。`vpaddd` 的 ZMM
单流实测接近 2 instructions/cycle，因此它设置
`scale_issue_interval_by_parts: false`：两个 part stream 都保留 0.5-cycle interval，
避免分解过程把整数吞吐错误减半。这是等效计费规则，不是物理 uop 数结论。

### 5.1 资源容量

| 资源 | Capacity | 宽度 | 用途 |
|---|---:|---:|---|
| `vector-fp` | 4 | 256-bit | add/sub/mul/FMA/max、broadcast、move |
| `vector-integer` | 4 | 256-bit | integer、shift、integer broadcast、vector state |
| `shuffle` | 2 | 256-bit | extract、shuffle、reduction lowering |
| `conversion` | 2 | 256-bit | FP32/I32 conversion |

资源 capacity 之外还有三组共享 issue domain：

| Issue domain | Capacity | 单位 | 适用约束 |
|---|---:|---|---|
| `fp-add-fma-convert` | 2 | 256-bit part-token/cycle | add、FMA、conversion 的共享发射资格 |
| `fma-convert-integer-total` | 4 | 256-bit part-token/cycle | FMA、conversion、integer 的总发射资格 |
| `zmm-register-source-delivery` | 8 | 256-bit source-token/cycle | ZMM 寄存器源操作数的加权交付能力 |

前两个域中每个 execution part 消耗一个 token。源交付域按每个 part 的显式寄存器源数
加权：寄存器源 add/conversion/FMA/integer 分别为 2/1/3/2；memory-source recipe 只计
仍来自寄存器的源。一个 uop 同时属于多个域时，必须在所有域中都有足够 token 才能
发射。例如 FMA part 即使 `vector-fp` lane 空闲，也可能因为源交付域不足 3 个 token
而等待。

这些 domain 是由吞吐竞争微基准得到的**有效资格约束**。它们不证明 Zen 4 存在对应
数量的真实物理 pipe、固定端口编号或 8 个寄存器文件读口。

### 5.2 ZMM 资源竞争微基准

新增微基准覆盖 conversion+integer、FMA+integer 和
conversion+FMA+integer 三种组合。每组混合流使用固定类别比例和互不依赖的寄存器链，
先用单类流归一化，再观察混合后各类吞吐是否下降。这样可以把共享资源竞争与 RAW
依赖链 latency 分开。

Zen 4 重复测量的中位数如下，单位为 ZMM instructions/cycle：

| 指令流 | 总速率 | Conversion | FMA | Integer |
|---|---:|---:|---:|---:|
| Conversion（独立基线） | 0.997966 | 0.997966 | - | - |
| FMA（独立基线） | 0.997923 | - | 0.997923 | - |
| Integer（独立基线） | 1.99337 | - | - | 1.99337 |
| Conversion + Integer，1:1 | 1.99245 | 0.996227 | - | 0.996227 |
| FMA + Integer，1:1 | 1.51607 | - | 0.758033 | 0.758033 |
| Conversion + FMA + Integer，1:1:2 | 1.99277 | 0.498192 | 0.498192 | 0.996383 |

FMA+integer 的总吞吐只有 1.51607，而 conversion+integer 和三类 1:1:2 混合流都接近
2。这组结果无法由各自独立资源 capacity 或单一不加权共享域同时解释。按每个
256-bit part 的寄存器源数计费后，FMA/integer/conversion 分别需要 3/2/1 个 token，
配合 8 source-token/cycle 和两个 part-token 域可以一致表达三组竞争关系。

每轮测试同时要求三个独立基线齐全，并检查目标 ZMM 退休数、PMU running ratio 和重复
样本 CV。准入阈值分别是 retired-ZMM/target 位于 `[0.98, 1.02]`、PMU running ratio
不低于 0.95、主指标 CV 不超过 3%。这里的数值是审核通过样本的中位数，
而不是单次最优值。实现与结果摘要见
[resource_contention.cpp](../../amd_profile_benchmark/src/resource_contention.cpp) 和
[summary.md](../../amd_profile_benchmark/results/zen4-zmm-contention-20260817/summary.md)。

Conversion 基准使用 kernel 对应的 `vcvttps2dq`；`vcvtdq2ps` 尚无直接竞争数据。三个
固定比例只能支持等效约束，不能唯一识别真实端口，所以新增两个 domain 的置信度为
medium，后续仍需 ratio sweep。

### 5.3 计算时序

下表同时列出 recipe interval 和绑定后的每个 part-stream interval。

| 操作 | 分解 | Latency | Recipe interval | Bound interval | Occupancy | 是否流水化 |
|---|---|---:|---:|---:|---:|---|
| ZMM add/sub/mul | 2 x 256-bit | 3 | 0.5 | 1 | 1 | 是 |
| ZMM FMA/FNMADD | 2 x 256-bit | 4 | 0.5 | 1 | 1 | 是 |
| ZMM max/min | 2 x 256-bit | 2 | 0.5 | 1 | 1 | 是 |
| XMM/YMM max | 1 uop | 2 | 0.5 | 0.5 | 1 | 是 |
| XMM/YMM add | 1 uop | 3 | 0.5 | 0.5 | 1 | 是 |
| FP32 -> I32 conversion | 2 x 256-bit | 4 | 0.5 | 1 | 1 | 是 |
| I32 -> FP32 conversion | 2 x 256-bit | 3 | 0.5 | 1 | 1 | 是 |
| ZMM integer add/shift | 2 x 256-bit | 1 | 0.5 | 0.5 | 1 | latency 等于 occupancy |
| Register/memory broadcast | 1 uop | 2 | 1 | 1 | 1 | 是 |
| Integer broadcast | 1 uop | 1 | 1 | 1 | 1 | latency 等于 occupancy |
| Eliminated vector move | 1 uop | 0 | 0.5 | 0.5 | 1 | 零结果延迟的等效模型 |
| `vextractf64x4` | 1 uop | 2 | 1 | 1 | 1 | 是 |
| `vextractf128` | 1 uop | 4 | 1 | 1 | 1 | 是 |
| XMM permute/shuffle | 1 uop | 1 | 0.5 | 0.5 | 1 | latency 等于 occupancy |

以 ZMM FMA 为例：每个 256-bit part 的结果 latency 为 4 cycle，但资源 occupancy
只有 1 cycle，因此是流水线执行。独立 FMA part 可以继续进入执行资源；只有读取该
FMA 结果的依赖 uop 必须等待结果完成。ZMM 内部两个 part 还要遵守 part order 和
1-cycle part gap。

## 6. Scalar 和 Control 等效资源

Scalar/control 尚未完成独立微基准校准，下面是与微架构关联的 provisional fit，
不能解释为精确物理端口结构。

| 资源/操作 | Capacity | Latency | Interval | Occupancy | 执行方式 |
|---|---:|---:|---:|---:|---|
| Scalar ALU / move | 4 | 1 | 0.5 | 1 | 同一 form 最多 2 uop/cycle；不同 form 共享 4 lanes |
| Scalar FP add | 2 | 3 | 0.5 | 1 | 流水化 |
| Scalar FP divide | 1 | 11 | 3 | 3 | 部分流水化，每 3 cycle 可接收一个独立 uop |
| Predicted branch | 2 | 1 | 0.5 | 1 | 不含错误预测代价 |
| Return | 2 | 5 | 0.5 | 1 | 流水化的有效 fit，不是 RAS 精确模型 |

Scalar divide 不会把资源锁住完整的 11 cycle。它占用唯一 divide lane 3 cycle，
结果在第 11 cycle 可用，因此独立除法可以每 3 cycle 开始一次；依赖链仍必须等待
完整 11-cycle latency。

## 7. 资源约束的组合顺序

一个 execution uop 发射前依次受到以下条件约束：

1. 所有 RAW、地址、flags 或内存依赖已经完成；
2. ZMM part order 和 part gap 满足；
3. memory-source FMA 的跨迭代待发射组限制满足；
4. 同 scheduling class 的 issue interval 满足；
5. 至少一个候选资源 lane 空闲；
6. load/store 的带宽和 outstanding 限制满足；
7. 所属每个共享 issue domain 都有足够 token 满足 `issue_domain_demands`。

发射后，资源 lane 在 `now + occupancy` 释放，结果在 `now + latency` 完成。这种分离
使模拟器能同时表达流水化执行、非完全流水化执行、多资源并行和长延迟访存。

共享域也按 occupancy 保留 token。对于某个域需求为 `d` 的 uop，后端检查该域第 `d`
个最早可用 token；若其释放时间晚于当前 tick，则该 uop 以 `issue_domain_busy` 阻塞。
发射时会同时占用最早可用的 `d` 个 token。多个域的检查取交集，任何一域不满足都不能
发射。

## 8. 当前模型边界

- 计算资源 capacity 是聚合等效值，不保证每个 opcode 都能使用该资源的所有 lane；
- 不模拟精确物理 uop 数、端口融合、rename、frontend cache 和 decode queue；
- 没有独立的 execution issue width，issue 上限来自已列出的资源约束；
- branch 默认预测正确，不模拟错误预测 flush；
- cache/DRAM 是确定性有效模型，不包含操作系统干扰、SMT 竞争和动态频率；
- RVV 后续可以绑定到相同资源接口，但必须由相应微架构 profile 提供具体数值。
