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

对于拆成两个 part 的 512-bit 指令，binder 会把 profile 中的 part interval 乘以
part 数。当前 profile 中的 `0.5 cycle * 2 parts` 因而成为每个 part stream 的
1-cycle 有效间隔；part 0 和 part 1 还必须保持 1-cycle `part_issue_gap`。

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

### 4.3 Cache 和 DRAM 参数

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

所有向量物理资源按 256-bit 宽度建模。多数 ZMM 操作会拆成两个 part，且 part 1
至少比 part 0 晚 1 cycle 发射。

### 5.1 资源容量

| 资源 | Capacity | 宽度 | 用途 |
|---|---:|---:|---|
| `vector-fp` | 4 | 256-bit | add/sub/mul/FMA/max、broadcast、move |
| `vector-integer` | 4 | 256-bit | integer、shift、integer broadcast、vector state |
| `shuffle` | 2 | 256-bit | extract、shuffle、reduction lowering |
| `conversion` | 2 | 256-bit | FP32/I32 conversion |

此外 `fp-add-fma-convert` issue domain 的 capacity 为 2。add、FMA 和 conversion
即使各自资源仍有空闲，合计也只能占用两个共享 issue-domain lane。该 domain 是
有效资格约束，不表示已确定两条真实物理 pipe。

### 5.2 计算时序

下表的 interval 是 recipe 中的值。标记为 ZMM 两 part 的项，在绑定后每个 part
stream 的有效 interval 为 1 cycle。

| 操作 | 分解 | Latency | Recipe interval | Occupancy | 是否流水化 |
|---|---|---:|---:|---:|---|
| ZMM add/sub/mul | 2 x 256-bit | 3 | 0.5 | 1 | 是 |
| ZMM FMA/FNMADD | 2 x 256-bit | 4 | 0.5 | 1 | 是 |
| ZMM max/min | 2 x 256-bit | 2 | 0.5 | 1 | 是 |
| XMM/YMM max | 1 uop | 2 | 0.5 | 1 | 是 |
| XMM/YMM add | 1 uop | 3 | 0.5 | 1 | 是 |
| FP32 -> I32 conversion | 2 x 256-bit | 4 | 0.5 | 1 | 是 |
| I32 -> FP32 conversion | 2 x 256-bit | 3 | 0.5 | 1 | 是 |
| ZMM integer add/shift | 2 x 256-bit | 1 | 0.5 | 1 | latency 等于 occupancy |
| Register/memory broadcast | 1 uop | 2 | 1 | 1 | 是 |
| Integer broadcast | 1 uop | 1 | 1 | 1 | latency 等于 occupancy |
| Eliminated vector move | 1 uop | 0 | 0.5 | 1 | 零结果延迟的等效模型 |
| `vextractf64x4` | 1 uop | 2 | 1 | 1 | 是 |
| `vextractf128` | 1 uop | 4 | 1 | 1 | 是 |
| XMM permute/shuffle | 1 uop | 1 | 0.5 | 1 | latency 等于 occupancy |

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
3. 同 scheduling class 的 issue interval 满足；
4. 至少一个候选资源 lane 空闲；
5. load/store 的带宽和 outstanding 限制满足；
6. 所属共享 issue domain 有空闲 lane。

发射后，资源 lane 在 `now + occupancy` 释放，结果在 `now + latency` 完成。这种分离
使模拟器能同时表达流水化执行、非完全流水化执行、多资源并行和长延迟访存。

## 8. 当前模型边界

- 计算资源 capacity 是聚合等效值，不保证每个 opcode 都能使用该资源的所有 lane；
- 不模拟精确物理 uop 数、端口融合、rename、frontend cache 和 decode queue；
- 没有独立的 execution issue width，issue 上限来自已列出的资源约束；
- branch 默认预测正确，不模拟错误预测 flush；
- cache/DRAM 是确定性有效模型，不包含操作系统干扰、SMT 竞争和动态频率；
- RVV 后续可以绑定到相同资源接口，但必须由相应微架构 profile 提供具体数值。
