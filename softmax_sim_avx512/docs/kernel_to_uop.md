# Softmax Kernel 到通用 Uop 的执行计划

> 状态：已审核，执行中。

## 1. 目标

建立一条可复现的转换链：

```text
同一 Softmax 算法
  -> x86 AVX-512 intrinsic / RISC-V RVV intrinsic
  -> 编译器生成的汇编
  -> ISA 指令解析与 recipe 映射
  -> 同一套通用 uop kind
  -> 微架构 profile 赋予时序和资源约束
```

汇编是模拟器唯一输入；本计划不包含二进制机器码解析，也不把二进制解码列为后续工作。

## 2. 范围与约束

- 数据类型只支持 FP32。
- 使用 numerically stable softmax：先求最大值，再计算 `exp(x-max)` 和总和，最后归一化。
- x86 主路径使用 AVX-512 intrinsic；RVV 主路径使用 `riscv_vector.h` intrinsic。
- 两个平台必须使用相同的指数近似算法、常量、输入和误差标准。
- 指数近似显式使用 FMA，使 kernel 覆盖 load、store、FP add/mul/FMA、conversion 和 reduce 等常见向量操作。
- 暂不支持 AVX-512 mask tail、gather/scatter、异常值的完整 IEEE 行为和复杂控制流。
- x86 测试长度要求是 16 个 FP32 元素的整数倍；RVV 源码使用 `vsetvl` 保持 VLEN-agnostic，首个模拟目标固定 VLEN=512。
- 通用 uop 不保存 latency、吞吐或物理 pipe。这些属于微架构 profile。
- 不新增 `schemas/uop.schema.json`；通用 uop 类型只在 `uops/uop_kinds.yaml` 定义一次。

## 3. 计划目录

```text
softmax_sim_avx512/
├── docs/
│   ├── kernel_to_uop.md
│   └── kernel_to_uop_result.md
├── kernel/
│   └── softmax/
│       ├── common/
│       │   ├── softmax_constants.h
│       │   ├── exp_approx.h
│       │   └── softmax_interface.h
│       ├── reference/
│       │   └── softmax_reference.cpp
│       ├── x86/
│       │   └── softmax_avx512.cpp
│       ├── rvv/
│       │   └── softmax_rvv.cpp
│       ├── tests/
│       │   ├── softmax_correctness.cpp
│       │   └── softmax_rvv_correctness.cpp
│       ├── scripts/
│       │   ├── build_assembly.sh
│       │   ├── build_riscv_tools.sh
│       │   ├── build_traces.sh
│       │   └── run_rvv_spike_test.sh
│       └── artifacts/
│           ├── x86/
│           │   ├── softmax_avx512.s
│           │   ├── softmax_uops.json
│           │   ├── softmax_uops_bound.json
│           │   └── build_metadata.txt
│           └── rvv/
│               ├── softmax_rvv.s
│               ├── softmax_uops.json
│               ├── spike_validation_metadata.txt
│               ├── spike_vlen128.txt
│               ├── spike_vlen512.txt
│               └── build_metadata.txt
├── uops/
│   └── uop_kinds.yaml
├── recipes/
│   ├── x86.yaml
│   └── rvv.yaml
└── utils/
    ├── asm_to_uop.py
    └── bind_uop_profile.py
```

`kernel/softmax/artifacts` 保存固定编译器版本生成的汇编和编译元数据；临时目标文件和 build 目录不提交。

## 4. Softmax Kernel 设计

### 4.1 公共算法

采用三遍实现：

1. Max pass：顺序 load 输入，向量求 max，最后做横向 max reduction。
2. Exp/sum pass：计算 `y[i] = exp_approx(x[i] - max)`，把 `y` 写入输出缓冲区，同时累加并做 sum reduction。
3. Normalize pass：计算 `inv_sum = 1/sum`，重新 load `y`，乘以 `inv_sum` 后 store。

三遍实现便于观察每类指令，也避免把在线 softmax 或分块算法的额外状态引入首版模型。

### 4.2 指数近似

不直接调用 `std::exp` 或编译器数学库，避免两个平台生成完全不同的库调用。计划使用共同的 FP32 range reduction 和低阶多项式：

```text
x = n * ln(2) + r
exp(x) ~= 2^n * P(r)
```

- `P(r)` 使用 Horner 形式并显式调用 FMA intrinsic。
- 输入在减去最大值后限制到约 `[-87, 0]`，避免下溢路径扩大范围。
- x86 和 RVV 共用常量的十六进制 FP32 表示，避免十进制解析差异。
- reference 同时提供高精度 `std::exp` 结果和相同 `exp_approx` 的标量结果，分别检查算法误差与向量实现错误。

多项式阶数和误差阈值在实现前单独审核；首版建议以最大绝对误差和最大相对误差均不超过 `1e-5` 为目标。

### 4.3 x86 AVX-512 实现

计划使用：

- `_mm512_loadu_ps`、`_mm512_storeu_ps`；
- `_mm512_max_ps`、`_mm512_add_ps`、`_mm512_mul_ps`、`_mm512_fmadd_ps`；
- `_mm512_reduce_max_ps`、`_mm512_reduce_add_ps`；
- 指数 range reduction 所需的 FP/int conversion 和整数 shift/logic intrinsic。

必须保存编译器实际生成的 reduction 序列。kernel 源码不主动使用 shuffle，但 x86 没有单条通用水平 reduce 指令，编译器可能生成 extract/shuffle 和标量/向量 add。只有实际汇编出现这些指令时，才在 P5 阶段加入对应通用 uop。

### 4.4 RVV 实现

RVV kernel 使用动态 `vl` 循环，计划覆盖：

- `vle32`、`vse32`；
- `vfmax`、`vfadd`、`vfmul`、`vfmacc/vfmadd`；
- `vfredmax`、`vfredusum` 或编译器对应 reduction intrinsic；
- FP/int conversion、integer shift/logic；
- `vsetvli/vsetivli` 产生的向量配置行为。

实现保持 VLEN-agnostic：源码不假定向量寄存器是 128、256 或 512 bit，而是每轮用 `vsetvl` 根据剩余元素数和目标机器 VLEN 决定处理元素数。同一份汇编可用于不同 VLEN；模拟时由 RVV profile 提供 VLEN，并据此确定循环次数。首个模拟目标固定 VLEN=512，使完整迭代与 AVX-512 一样处理 16 个 FP32 元素。RVV VLEN、ABI 和编译器配置必须记录在 artifact metadata 中。

## 5. 编译与汇编产物

### 5.1 编译原则

- 固定编译器名称、完整版本和全部 flags。
- 使用 `-O3`，允许 FMA contraction，但不允许编译器把自定义近似替换成外部数学库。
- 对 kernel 函数使用 `noinline` 并保留稳定的导出符号名。
- 只生成 `.s` 汇编和编译元数据；不生成供模拟器使用的二进制或反汇编。
- artifact 中只截取目标 kernel 及其直接 helper，避免运行库和测试框架指令进入模拟范围。

计划命令形态：

```bash
# x86，具体编译器和 march 在执行前根据目标机确认
c++ -O3 -mavx512f -mavx512dq -mavx512bw -mavx512vl \
  -mfma -S kernel/softmax/x86/softmax_avx512.cpp \
  -o kernel/softmax/artifacts/x86/softmax_avx512.s

# RVV，具体 toolchain 在执行前探测
riscv64-linux-gnu-g++ -O3 -march=rv64gcv -mabi=lp64d \
  -S kernel/softmax/rvv/softmax_rvv.cpp \
  -o kernel/softmax/artifacts/rvv/softmax_rvv.s
```

正式脚本不得静默回退到宿主默认 `-march`。

### 5.2 汇编规范化

解析前只做无损规范化：

- 去除地址、字节编码、调试 directive 和注释；
- 保留 mnemonic、操作数、宽度、mask/tail policy 和基本块边界；
- x86 寄存器别名规范化为明确宽度；
- RVV 保留当前 SEW、LMUL、VL 和 tail/mask policy；
- 不把多条机器指令预先合并成一个高级 softmax 操作。

## 6. 通用 Uop 设计

### 6.1 单一 Catalog

`uops/uop_kinds.yaml` 是唯一的通用 uop 类型表，不为 x86 和 RVV 分别复制，也不新建 uop schema。首版候选类型如下，最终列表以两份汇编的指令并集为准：

```text
scalar_alu
branch
vector_config
address_generation
vector_load
vector_store
vector_fp_add
vector_fp_mul
vector_fp_fma
vector_fp_max
vector_reduce_add
vector_reduce_max
vector_convert
vector_integer
vector_shift
```

每个条目只包含稳定 ID、类别和简短语义说明。向量宽度、元素类型、操作数依赖和 part 信息属于具体 uop 实例；latency、issue interval、occupancy 和 resource choices 属于 profile。`vector_shuffle` 不作为预设类型，只有 x86 最终汇编确实包含 extract/shuffle 指令时才加入。

### 6.2 ISA Recipe

`recipes/x86.yaml` 和 `recipes/rvv.yaml` 不定义新的 uop 类型，只把 canonical instruction form 映射到 `uop_kinds.yaml` 中的 ID，并描述操作数绑定。例如：

```text
x86 vfmadd*    -> vector_fp_fma
RVV vfmacc.vv  -> vector_fp_fma
x86 vmovups load / RVV vle32.v -> address_generation + vector_load
x86 reduction helper -> 按实际 extract/shuffle/add 指令分别映射
RVV vfredusum.vs -> vector_reduce_add
```

x86 和 RVV 的 uop trace 不要求条目数相同。通用的含义是使用同一套 uop vocabulary，而不是强行把不同 ISA 的多条指令折叠成相同长度。

### 6.3 与 Profile 的边界

推荐把通用语义 `uop_kind` 和微架构执行资源 `resource_kind` 分开：

```text
uop_kind: vector_fp_fma        # 跨 ISA 语义
resource_kind: vector_fp       # profile 中的执行资源类别
```

当前 `profile.schema.json` 的 `uops[].kind` 更接近 `resource_kind`。实施时应保留其兼容性，先由 recipe 生成通用 `uop_kind`，再由 profile recipe 绑定到现有资源；不应直接把二者混为一个枚举。

## 7. 分阶段执行

### P0：冻结公共语义

- 确定三遍 softmax、指数多项式、输入范围和误差阈值。
- 确定汇编是唯一解析输入，不设计二进制解码路径。
- 确定 `uop_kind` 与 `resource_kind` 分层。

验收：算法说明和接口经审核，不产生平台代码。

### P1：Reference 与正确性框架

- 实现高精度 reference 和标量 `exp_approx` reference。
- 生成固定随机、全相等、大动态范围和极端负数输入。
- 检查输出非负、总和接近 1，并报告绝对/相对误差。

验收：reference 测试通过，固定输入和期望摘要可复现。

### P2：x86 AVX-512 Kernel

- 实现三遍 intrinsic kernel。
- 在目标 AMD Zen 4 主机运行正确性测试。
- 生成并审核 `.s`，确认主循环包含预期 load/store/FMA/reduction 序列且没有 libm 调用。

验收：正确性通过，目标符号汇编可定位，禁止标量化主循环。

### P3：RVV Kernel

- 探测已有 RVV cross compiler、intrinsic API 版本和可运行环境。
- 实现 VLEN-agnostic intrinsic kernel 并生成汇编。
- 使用现有 QEMU/Spike/真实 RVV 环境运行正确性测试；若只能编译，必须把运行验证标为未完成。

验收：汇编包含 RVV vector load/store/FMA/reduction 和明确 `vsetvl`；能运行时必须与 reference 对比。

### P4：指令清单与 Canonical Form

- 从两个目标 kernel 的汇编提取 mnemonic、operand form、数据宽度和出现次数。
- 区分寄存器/内存版本、不同 SEW/LMUL 和 reduction 形式。
- 只为 kernel 实际出现的 form 建 recipe，不提前扩展全 ISA。

验收：每条目标汇编指令都有清单项；编译器辅助指令没有遗漏。

### P5：通用 Uop Catalog

- 用两份指令清单的语义并集生成 `uops/uop_kinds.yaml`。
- 合并语义相同的 x86/RVV 操作，保留真正不同的语义。
- 不加入微架构 latency、资源编号或厂商名称。

验收：catalog 中不存在 `x86_*`、`rvv_*`、Zen 4 pipe 编号等 ISA/微架构耦合 ID。

### P6：ISA Recipe 与 Uop Trace

- 编写 x86/RVV recipe。
- 汇编解析器输出规范化 instruction trace 和通用 uop trace。
- 对每条 instruction 保存来源行号和对应 recipe，保证可追溯。

验收：两份汇编中的每条模拟范围内指令都能映射；未知指令必须硬错误，不能降级为默认 uop。

### P7：Profile 绑定与模拟准备

- 把通用 uop 实例绑定到 profile resource、latency 和吞吐参数。
- x86 使用已校准的 AMD Zen 4 profile；RVV profile 在目标微架构确定后另行建立。
- exact physical uop 数未知时继续使用等效分解，不把 recipe 宣称为硬件真值。

验收：通用 trace 不包含厂商时序；更换 profile 不需要重新编译 kernel 或重写 uop catalog。

## 8. 最终验收标准

1. 两个 kernel 实现同一算法并通过相同正确性输入。
2. x86 主循环确认使用 AVX-512，RVV 主循环确认使用 RVV，均无意外标量化或外部 `exp` 调用。
3. 编译命令、编译器版本和汇编可以一键复现。
4. 所有模拟范围内指令均有 ISA recipe，所有 recipe 只引用一个 `uop_kinds.yaml`。
5. uop catalog 不包含 ISA 名、物理 pipe、latency 或吞吐。
6. instruction -> recipe -> uop -> profile resource 的每一步均可追溯，未知项直接报错。
7. 不为迁就通用 trace 修改已经校准的 x86 profile 物理参数。

## 9. 审核结论

| 项目 | 结论 |
|---|---|
| 三遍 softmax 和显式多项式 `exp_approx` | 已通过 |
| 首版只处理 FP32，x86 长度为 16 的倍数 | 已通过 |
| RVV 使用 `rv64gcv/lp64d` 并保持 VLEN-agnostic；首个模拟目标 VLEN=512 | 已通过 |
| 汇编作为唯一模拟器输入，不做二进制解码 | 已通过 |
| 通用 `uop_kind` 与 profile `resource_kind` 分层 | 已通过 |

全部计划项已经审核通过。

## 10. 当前执行状态

- P0-P2 已完成：公共算法、reference、x86 AVX-512 kernel、正确性测试和汇编生成均已实现。
- P3 已完成：RVV kernel 保持 VLEN-agnostic，并已在 Spike 的 VLEN=128 和 VLEN=512 配置下通过数值运行验证。
- P4-P6 已完成：两份当前汇编的指令均有 recipe，解析器对未知指令硬错误，并输出可追溯的通用 uop trace。
- P7 已完成第一步：x86 trace 可绑定到已校准 Zen4 profile 的资源类别；完整 opcode timing 仍按 profile 现有覆盖范围提供。
- 详细命令、计数和环境限制见 `docs/kernel_to_uop_result.md`。
