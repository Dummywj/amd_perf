# Semantic Uop 设计说明

## 1. 目的

x86 是 CISC 风格。一条指令可能同时完成地址生成、数据加载和向量计算，例如：

```asm
vmaxps (%rdi,%rax,4), %zmm0, %zmm0
```

如果只观察 profile 绑定后的 execution uop，会看到：

```text
address_generation + vector_load + max-part-0 + max-part-1
```

这适合模拟资源和周期，但不适合解释算法级数据流。Semantic uop 作为中间观察层，目标是：

1. 描述指令真正完成的语义动作；
2. 明确源操作数、目的操作数和数据宽度；
3. 指定需要哪一种抽象执行能力；
4. 保持 x86、RVV 和未来 ISA 的表示一致；
5. 允许将多个微架构 execution uop 聚合回一个可读的语义节点。

本文只定义设计和数据契约，不修改当前的 `uops/uop_kinds.yaml`、trace 格式或可视化程序。

## 2. 三个层次

模拟链路分为三个层次：

```text
ISA instruction
    |
    v
semantic uop
    |
    v
profile-bound execution uop
```

### 2.1 ISA instruction

ISA instruction 是汇编中可见的指令，例如：

```text
vmaxps, vfmadd132ps, vle32.v, vfredmax.vs
```

它携带编码、寄存器命名和 ISA 特定的寻址或向量状态规则。

### 2.2 Semantic uop

Semantic uop 表示一个跨 ISA 的基本语义动作，例如：

```text
vector_load
vector_fp_fma
vector_reduce_max
```

它不包含 Zen 4 的 latency、吞吐率、物理端口、资源容量或微架构名称。

### 2.3 Execution uop

Execution uop 是某个 profile 下的实际调度节点，包含：

- `latency_cycles`；
- `issue_interval_cycles`；
- `resource_occupancy_cycles`；
- `resource_choices`；
- `issue_domains`；
- 向量分解的 `part_index` 和 part 间隔；
- cache 层次产生的实际 load latency。

例如，一个 `vector_fp_max` semantic uop 在 Zen 4 profile 中可以绑定为两个 256 位 execution uop。两个层次必须通过 `semantic_parent_id` 关联，但不能混用其语义。

## 3. Semantic Uop 的数据契约

未来的语义 trace 建议将每个节点表示为：

```json
{
  "id": "i4.s2",
  "kind": "vector_fp_max",
  "parent_instruction_id": "i4",
  "source_operands": [
    {
      "id": "zmm0@v3",
      "kind": "vector",
      "data_type": "fp32",
      "element_bits": 32,
      "lane_count": 16,
      "width_bits": 512,
      "location": "zmm0"
    },
    {
      "id": "i4.s1.value",
      "kind": "temporary_vector",
      "data_type": "fp32",
      "element_bits": 32,
      "lane_count": 16,
      "width_bits": 512
    }
  ],
  "destination_operands": [
    {
      "id": "zmm0@v4",
      "kind": "vector",
      "data_type": "fp32",
      "element_bits": 32,
      "lane_count": 16,
      "width_bits": 512,
      "location": "zmm0"
    }
  ],
  "abstract_resource": "vector_fp",
  "dependencies": ["i3.s0", "i4.s1"],
  "effects": {
    "reads_memory": false,
    "writes_memory": false,
    "reads_flags": false,
    "writes_flags": false
  },
  "provenance": {
    "isa": "x86",
    "mnemonic": "vmaxps",
    "source_line": 14
  }
}
```

字段含义：

| 字段 | 含义 |
|---|---|
| `id` | 动态语义 uop 的稳定 ID；同一条指令的语义节点使用 `i4.s0`、`i4.s1` 等编号 |
| `kind` | `uops/uop_kinds.yaml` 中的公共语义类型 |
| `parent_instruction_id` | 所属动态 ISA 指令，用于从语义视图回溯汇编 |
| `source_operands` | 计算读取的 SSA 操作数或内存对象 |
| `destination_operands` | 计算产生的 SSA 操作数、地址 token、flags 或内存副作用 |
| `abstract_resource` | 所需的抽象能力，对应当前 catalog 的 `execution_class` |
| `dependencies` | 语义级 RAW、地址或内存顺序依赖 |
| `effects` | 内存、flags 和控制流副作用 |
| `provenance` | ISA、助记符和源代码位置等审计信息 |

当前静态 trace 中的 `semantic_uops` 已经包含 `kind` 和父指令关系；上述操作数契约是后续扩展的目标格式。

## 4. 操作数设计

### 4.1 操作数不是裸寄存器字符串

语义 trace 不应只写 `%zmm0` 或 `v8`。同一个寄存器在不同时间可能代表不同版本。建议使用 SSA 形式：

```text
zmm0@v3 --read--> vmaxps --write--> zmm0@v4
```

`location` 仍然保存物理或 ISA 寄存器名，但 `id` 保存数据版本。这样可以准确表达 x86 的读写同一寄存器：

```asm
vmaxps (%rdi,%rax,4), %zmm0, %zmm0
```

语义上不是“一个 zmm0 节点覆盖自己”，而是：

```text
zmm0@old + loaded_vector -> zmm0@new
```

### 4.2 操作数种类

`kind` 建议使用以下集合：

| kind | 含义 |
|---|---|
| `scalar` | 标量整数或浮点值 |
| `vector` | 固定宽度或运行时宽度的向量 |
| `memory` | 内存中的数据对象 |
| `address` | AGU 产生的有效地址 token |
| `temporary_vector` | 同一条 ISA 指令拆分出的临时向量值 |
| `temporary_scalar` | 同一条指令或 reduction 产生的临时标量 |
| `flags` | 条件码或比较结果 |
| `vector_state` | RVV 的 VL、SEW、LMUL 等状态 |
| `control` | 分支目标、返回地址等控制流 token |
| `immediate` | 不需要读取寄存器的常量 |

### 4.3 操作数的最小属性

数据操作数建议包含：

```text
id           SSA 版本标识
kind         scalar/vector/memory/address/...
data_type    i32、i64、fp32、fp64、pointer、flags 等
element_bits 单个 lane 的位宽；指针和 flags 可为空
lane_count   标量为 1，RVV 可以是 runtime VL
width_bits   有效数据总宽度；地址使用独立的 pointer_bits
location     寄存器、内存区域或临时值
```

`source_operands` 和 `destination_operands` 中不重复写 `role`，数组位置已经表达读写方向；如果将来需要 read-modify-write，可以在同一对象中使用不同 SSA 版本明确区分。

## 5. 宽度规则

### 5.1 标量

标量的 `lane_count` 固定为 1：

```text
fp32 / i32  -> element_bits = 32, width_bits = 32
fp64 / i64  -> element_bits = 64, width_bits = 64
pointer     -> pointer_bits = 64
```

### 5.2 x86 AVX-512

x86 的向量宽度来自实际操作数：

| 寄存器 | `width_bits` | FP32 lane_count | FP32 内存字节数 |
|---|---:|---:|---:|
| `xmm` | 128 | 4 | 16 |
| `ymm` | 256 | 8 | 32 |
| `zmm` | 512 | 16 | 64 |

例如 `vaddps %zmm1, %zmm2, %zmm0` 的每个源和目的操作数都是 `fp32`、16 lanes、512 bits。

### 5.3 RVV

RVV 的宽度不能写成固定的 512 bits：

```text
element_bits = SEW
lane_count   = VL 或 runtime_vl
width_bits   = element_bits * lane_count
memory_bytes = element_bits / 8 * lane_count
```

当前 RVV softmax 使用 `SEW=32`、`LMUL=m1`，`VL` 由 `vsetvli` 和运行时 VLEN 决定。语义 uop 只记录有效 `VL`，不把某一个 VLEN 的物理寄存器宽度写死。

### 5.4 Reduction 的结果宽度

向量 reduction 的源和目的宽度可以不同：

```text
vector_reduce_max:
    source      vector<fp32, VL>
    destination scalar<fp32>
```

在 x86 中，`_mm512_reduce_max_ps` 最终被编译器 lowering 成 extract、shuffle、窄向量 max 和标量操作；这些是多个 semantic uop。RVV 的 `vfredmax.vs` 可以直接映射为一个 `vector_reduce_max`。

## 6. 抽象资源

Semantic uop 只能声明“需要哪类能力”，不能声明“占用 Zen 4 的哪一个物理 pipe”。当前 catalog 中的 `execution_class` 就是抽象资源类别：

| 抽象资源 | Semantic uop 示例 | 说明 |
|---|---|---|
| `scalar_alu` | `scalar_alu`、`scalar_move` | 标量整数、地址算术或移动 |
| `load_data` | `scalar_load`、`vector_load` | 从 cache/memory 取数；地址生成单独建模 |
| `store_data` | `scalar_store`、`vector_store` | 向 store-data 通路写入 |
| `scalar_fp` | `scalar_fp_add`、`scalar_fp_div` | 标量浮点运算 |
| `branch` | `branch`、`return` | 预测正确的控制流有效成本 |
| `vector_config` | `vector_config` | 向量状态配置或状态清理 |
| `address_generation` | `address_generation` | 计算有效地址 |
| `vector_fp` | 各类 FP vector compute、broadcast、move、reduction | 向量 FP 数据通路的抽象能力 |
| `conversion` | `vector_convert` | FP/整数转换 |
| `vector_integer` | `vector_integer`、`vector_shift` | 向量整数运算和移位 |
| `shuffle` | `vector_shuffle` | extract、permute、shuffle |

profile 绑定阶段再把抽象资源映射到：

```yaml
resource_choices: [vector-fp]
resource_occupancy_cycles: 1
issue_domains: [fp-add-fma-convert]
```

这些字段不应进入 semantic uop catalog，因为容量、occupancy、issue interval 和共享 issue domain 都随微架构 profile 变化。

### 6.1 资源与复合动作

一个 semantic uop 只声明一个主要抽象能力。需要多个独立能力时拆成多个语义节点：

```text
address_generation -> vector_load -> vector_fp_max
```

这样可以观察每个阶段，同时让后端独立调度 AGU、load-data 和 vector-fp。不要在 `vector_fp_max` 中隐含一个未命名的 load。

## 7. 当前 Semantic Uop 词表

下表是 `uops/uop_kinds.yaml` 中 25 种公共类型的语义契约。表中的“资源”是抽象资源，不是具体 Zen 4 资源实例。

### 7.1 标量、控制与地址

| kind | 语义 | 源操作数 | 目的操作数/副作用 | 宽度 | 抽象资源 |
|---|---|---|---|---|---|
| `scalar_alu` | 标量整数加减、逻辑、比较或地址算术 | 标量寄存器、立即数 | 标量寄存器；比较类可写 `flags` | i32/i64，按指令 | `scalar_alu` |
| `scalar_load` | 加载一个标量值 | `address`、`memory` | 标量寄存器或临时标量 | 数据类型宽度；当前 FP32 为 32 | `load_data` |
| `scalar_store` | 存储一个标量值 | `address`、标量寄存器 | `memory` 写副作用 | 数据类型宽度 | `store_data` |
| `scalar_fp_add` | 标量 FP 加法/减法 | 1~2 个标量 FP | 标量 FP | 当前为 FP32 | `scalar_fp` |
| `scalar_fp_div` | 标量 FP 除法 | 2 个标量 FP | 标量 FP | 当前为 FP32 | `scalar_fp` |
| `scalar_move` | 标量寄存器、立即数或位表示移动 | 标量/立即数 | 标量寄存器 | i32/i64/FP32，按来源 | `scalar_alu` |
| `branch` | 条件或无条件控制流转移 | `flags`、比较值或控制 token | `control` 目标选择 | 不适用；比较值按标量宽度 | `branch` |
| `return` | 函数返回 | 返回地址/控制 token | 控制流结束 | 不适用 | `branch` |
| `address_generation` | 计算有效地址 | base、index、scale、displacement | `address` token | pointer_bits，当前为 64 | `address_generation` |

`branch` 的目标选择是语义副作用，不代表当前模型已经实现分支预测器。当前 profile 只拟合预测正确的控制开销。

### 7.2 向量状态与内存

| kind | 语义 | 源操作数 | 目的操作数/副作用 | 宽度 | 抽象资源 |
|---|---|---|---|---|---|
| `vector_config` | 设置或清理向量状态 | AVL、SEW、LMUL、VL 或状态 token | `vector_state` | 状态字段，不是数据宽度 | `vector_config` |
| `vector_load` | 读取活动向量元素 | `address`、`memory` | 向量寄存器或临时向量 | x86 按 XMM/YMM/ZMM；RVV 按 `VL*SEW` | `load_data` |
| `vector_store` | 写入活动向量元素 | `address`、向量 | `memory` 写副作用 | 同上 | `store_data` |
| `vector_broadcast` | 把一个标量值复制到各 lane | 标量或已加载标量 | 向量寄存器 | 目标向量宽度 | `vector_fp` |
| `vector_move` | 向量复制、清零或 lane 0 移动 | 向量、标量或立即数 | 向量或标量 | 源/目标宽度按具体 form | `vector_fp` |

内存源的 broadcast 必须由 `address_generation`、`vector_load` 和 `vector_broadcast` 三个语义节点表达，而不是把内存访问藏进 broadcast。

### 7.3 向量 FP 计算

| kind | 语义 | 源操作数 | 目的操作数 | 宽度 | 抽象资源 |
|---|---|---|---|---|---|
| `vector_fp_add` | 逐 lane FP 加/减的加法类动作 | 2 个向量 FP | 1 个向量 FP | `element_bits * lane_count` | `vector_fp` |
| `vector_fp_sub` | 逐 lane FP 减法 | 2 个向量 FP | 1 个向量 FP | 同上 | `vector_fp` |
| `vector_fp_mul` | 逐 lane FP 乘法 | 2 个向量 FP | 1 个向量 FP | 同上 | `vector_fp` |
| `vector_fp_fma` | 逐 lane `a*b+c` 或 `c-a*b`，一次舍入 | 3 个向量 FP；加数可能是目的旧版本 | 1 个向量 FP | 同上 | `vector_fp` |
| `vector_fp_max` | 逐 lane 取最大值；`min` 复用该类别 | 2 个向量 FP | 1 个向量 FP | 同上 | `vector_fp` |
| `vector_reduce_add` | 将向量 lane 求和 | 向量 FP，可能带标量 seed | 标量或 reduction accumulator | 源为向量，结果为元素宽度 | `vector_fp` |
| `vector_reduce_max` | 将向量 lane 求最大值 | 向量 FP，可能带标量 seed | 标量或 reduction accumulator | 源为向量，结果为元素宽度 | `vector_fp` |

FMA 使用 SSA 版本表示 read-modify-write。例如 `zmm0 = zmm1*zmm2 + zmm0` 应表示为 `zmm0@old` 和 `zmm0@new` 两个不同对象。

### 7.4 向量转换、整数和排列

| kind | 语义 | 源操作数 | 目的操作数 | 宽度 | 抽象资源 |
|---|---|---|---|---|---|
| `vector_convert` | FP 与整数向量之间转换 | 向量，源类型 | 向量，目的类型 | lane 数通常不变，元素宽度可变 | `conversion` |
| `vector_integer` | 逐 lane 整数算术或逻辑 | 2 个向量整数，或向量+标量 | 向量整数 | `element_bits * lane_count` | `vector_integer` |
| `vector_shift` | 逐 lane 左/右移 | 向量整数、立即数或向量移位量 | 向量整数 | 同上 | `vector_integer` |
| `vector_shuffle` | extract、permute 或 shuffle lane | 1~2 个向量和控制立即数/索引 | 向量 | 目标宽度按具体 form | `shuffle` |

`vector_shuffle` 当前主要用于 x86 reduction lowering；它不是对任意 gather、slide 或复杂 permutation 的承诺。

## 8. CISC 指令拆解示例

以：

```asm
vmaxps (%rdi,%rax,4), %zmm0, %zmm0
```

为例，AT&T 操作数的源和目的为：

```text
source:      memory[effective_address], zmm0@old
destination: zmm0@new
```

语义视图：

```text
i4.s0 address_generation
  sources:      rdi, rax, scale=4
  destination:  address@i4
  width:        pointer=64
  resource:     address_generation

i4.s1 vector_load
  sources:      address@i4, input memory
  destination:  temporary_vector@i4
  width:        fp32 x 16 = 512 bits
  resource:     load_data

i4.s2 vector_fp_max
  sources:      zmm0@old, temporary_vector@i4
  destination:  zmm0@new
  width:        fp32 x 16 = 512 bits
  resource:     vector_fp
```

对应的语义依赖为：

```text
address_generation -> vector_load -> vector_fp_max
zmm0@old -------------------------> vector_fp_max
```

Zen 4 profile 绑定后，只有最后一个语义节点发生 512 到两个 256 位 part 的 execution 分解。语义可视化应该把这两个 part 聚合回 `i4.s2`，而资源视图仍可显示两个 part 的实际 issue/complete 时间。

## 9. x86 与 RVV 对照

| 语义 | x86 示例 | RVV 示例 | Semantic uop |
|---|---|---|---|
| 向量加载 | `vmovups` | `vle32.v` | `address_generation` + `vector_load` |
| 向量存储 | `vmovups` | `vse32.v` | `address_generation` + `vector_store` |
| 标量广播 | `vbroadcastss` | `vfmv.v.f` | `vector_broadcast` |
| FP32 最大值 | `vmaxps` | `vfmax.vf` | `vector_fp_max` |
| FP32 FMA | `vfmadd132ps` | `vfmacc.vv` | `vector_fp_fma` |
| FP 到整数 | `vcvttps2dq` | `vfcvt.rtz.x.f.v` | `vector_convert` |
| 整数左移 | `vpslld` | `vsll.vi` | `vector_shift` |
| 最大值归约 | compiler lowering | `vfredmax.vs` | `vector_reduce_max` |

区别在于 ISA 前端如何得到操作数和动态 lane 数；相同 semantic kind 不意味着两种 ISA 使用相同数量或相同类型的 execution uop。

## 10. 语义级可视化设计

后续新增 semantic uop 可视化文件时，建议同时输出两种层次：

### 10.1 Semantic view

每个语义 uop 一个节点，字段包括：

```text
semantic_id
parent_instruction_id
kind
source_operands
destination_operands
abstract_resource
semantic_issue_cycle
semantic_complete_cycle
dependencies
```

对于一个 semantic uop 对应多个 execution uop：

```text
semantic_issue_cycle    = min(part.issue_cycle)
semantic_complete_cycle = max(part.complete_cycle)
```

资源字段显示抽象资源；可以附带 child execution uop ID，但不把 child 当作额外语义节点。

### 10.2 Execution view

保留当前 `result.json`、Perfetto 和 DOT 的 execution uop 明细，用于分析：

- 哪个 part 先发射；
- 哪个资源 lane 被占用；
- part gap、issue interval 和 memory bandwidth 如何产生阻塞。

两个视图通过 `semantic_id`、`parent_instruction_id` 和 `execution_uop_ids` 关联。

### 10.3 推荐的显示层

```text
instruction lane:  v4 vmaxps ... zmm0
semantic lane:     AGU -> LOAD -> FP_MAX
execution lanes:   AGU[0], load-data[1], vector-fp[0], vector-fp[1]
```

默认教学视图应显示 instruction 和 semantic lane；只有用户展开某个 semantic uop 时才显示 execution part，避免 CISC 拆解淹没算法数据流。

## 11. 校验规则

语义 uop 生成器应遵守以下检查：

1. `kind` 必须存在于 `uops/uop_kinds.yaml`。
2. 每个非控制语义 uop 都必须有明确的源和目的，除非它只有内存副作用。
3. `vector_load`、`vector_store` 必须绑定 `address` 和 `memory`；AGU 不应被隐含。
4. `width_bits` 必须等于 `element_bits * lane_count`，RVV runtime 宽度除外。
5. reduction 的结果宽度必须显式写为标量或 accumulator，不能继承整个向量宽度。
6. 同一物理寄存器的不同写入必须使用不同 SSA 版本。
7. `abstract_resource` 只能使用公共 execution class，不能写 `zen4-pipe-0` 之类的微架构资源。
8. semantic 依赖图必须无环；循环迭代之间的依赖通过动态实例 ID 区分。
9. 指令到 semantic uop 的映射必须保留 `provenance`，未知 instruction form 直接报错。
10. 一个 semantic uop 是否被拆成多个 execution uop 必须由 profile 决定，而不是由可视化层猜测。

## 12. 当前范围与后续扩展

当前范围：

- FP32 向量 load/store、add/sub/mul/FMA/max、conversion、integer、shift；
- x86 reduction lowering 所需的基础 extract/shuffle；
- RVV 的运行时 `VL` 宽度表达；
- 预测正确的 branch 和 scalar/control fallback。

暂不纳入：

- mask 作为独立语义操作数；
- gather/scatter、复杂 permutation 和 slide；
- 物理 uop 数量、真实端口编号和隐藏融合边界；
- 具体 cache、TLB 或预取状态；
- 直接在 semantic uop 中写入 latency、capacity 或 frequency。

后续如果加入 mask，应将其作为独立的 `mask` 操作数并增加 `active_lanes` 规则，而不是改变现有 vector 数据宽度语义。后续如果加入更复杂的 RVV reduction，也应保持 semantic kind 稳定，把 ISA 特定的拆分放在 recipe 和 profile 中。
