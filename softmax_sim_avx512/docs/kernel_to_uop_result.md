# Kernel 到 Uop 执行结果

状态：已完成首版执行链，等待模拟器接入审核。

## 已实现内容

- `kernel/softmax/common/`：公共 FP32 常量、指数近似和 C ABI 接口。
- `kernel/softmax/reference/`：高精度 reference 与标量近似 reference。
- `kernel/softmax/x86/softmax_avx512.cpp`：AVX-512 三遍 softmax。
- `kernel/softmax/rvv/softmax_rvv.cpp`：VLEN-agnostic RVV 三遍 softmax。
- `uops/uop_kinds.yaml`：x86/RVV 共用的语义 uop catalog。
- `recipes/x86.yaml`、`recipes/rvv.yaml`：当前编译器实际生成指令的 recipe。
- `utils/asm_to_uop.py`：汇编到通用 uop trace 的严格解析器；缺失 recipe 直接报错。
- `utils/bind_uop_profile.py`：将通用 trace 绑定到现有 profile 的资源类别。
- `kernel/softmax/scripts/build_assembly.sh`：生成 x86/RVV 汇编和编译元数据。
- `kernel/softmax/scripts/build_traces.sh`：一键生成汇编、trace 和 x86 Zen4 资源绑定结果。
- `kernel/softmax/scripts/build_riscv_tools.sh`：构建固定 submodule commit 的 Spike 和 proxy kernel。
- `kernel/softmax/scripts/run_rvv_spike_test.sh`：交叉编译静态 RVV 测试 ELF，并在多个 VLEN 下运行。

## 验证结果

在当前环境执行：

```bash
cmake -S softmax_sim_avx512/kernel/softmax \
  -B softmax_sim_avx512/kernel/softmax/build -DCMAKE_BUILD_TYPE=Release
cmake --build softmax_sim_avx512/kernel/softmax/build --parallel 2
ctest --test-dir softmax_sim_avx512/kernel/softmax/build --output-on-failure

PYTHON=/path/to/python \
  softmax_sim_avx512/kernel/softmax/scripts/build_traces.sh

softmax_sim_avx512/kernel/softmax/scripts/build_riscv_tools.sh
softmax_sim_avx512/kernel/softmax/scripts/run_rvv_spike_test.sh
```

结果：

- x86 correctness：16 组固定输入全部通过；向量实现相对标量近似的最大绝对误差为 `7.45e-9`，输出和误差在 `2e-5` 阈值内。
- x86 汇编：`softmax_avx512_f32` 解析为 78 条指令、108 个通用 uop；包含 load/store、FMA、conversion、integer、reduction lowering 和实际出现的 shuffle/extract 指令。
- RVV 汇编：`softmax_rvv_f32` 解析为 89 条指令、94 个通用 uop；包含 `vsetvli`、`vle32/vse32`、FMA、conversion 和两类 reduction。trace 记录最终 `SEW=32, LMUL=m1, VL=runtime (AVL=a5), tail=ta, mask=ma`。
- RVV runtime：Spike VLEN=128 和 VLEN=512 各运行 36 组固定输入，72 组全部通过。测试长度覆盖 `1, 3, 15, 16, 17, 31, 64, 255, 4096`，验证动态 `vl` 和尾部处理。相对标量近似的最大绝对误差为 `1.49e-8`，输出和误差满足 `2e-5` 阈值。
- RVV 验证原始输出和工具版本保存在 `kernel/softmax/artifacts/rvv/spike_vlen*.txt` 与 `spike_validation_metadata.txt`。
- x86 trace 已绑定 `profiles/amd_zen4.yaml`；profile 中没有定义的 scalar/frontend/control timing 被显式标记为 `unmodeled_profile_class`，没有自动填充默认时序。
- 两份汇编均未发现 `call`、外部数学库调用或栈保护指令。

## 当前限制

RVV 结果已通过 Spike ISA 功能模型验证，但尚未在真实 RVV 硬件上运行。Spike 验证指令语义和 VLEN-agnostic 行为，不代表任何具体 RISC-V 微架构的周期性能。

验证使用 `third_party/riscv-isa-sim` commit `3d8eb089`（Spike `1.1.1-dev`）和 `third_party/riscv-pk` commit `9c61d298`。新版 Spike 通过 ISA 字符串中的 `zvl128b`/`zvl512b` 选择 VLEN。

当前 Zen4 profile 只包含已校准的 `vaddps` opcode timing；绑定器对其他 uop 仅提供资源类别，不声称提供完整 opcode latency/throughput。模拟器接入时应继续使用 profile 的等效分解规则，并对未建模项保持显式失败或待校准状态。
