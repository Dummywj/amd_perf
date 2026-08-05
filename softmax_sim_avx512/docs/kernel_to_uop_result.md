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

## 验证结果

在当前环境执行：

```bash
cmake -S softmax_sim_avx512/kernel/softmax \
  -B softmax_sim_avx512/kernel/softmax/build -DCMAKE_BUILD_TYPE=Release
cmake --build softmax_sim_avx512/kernel/softmax/build --parallel 2
ctest --test-dir softmax_sim_avx512/kernel/softmax/build --output-on-failure

PYTHON=/path/to/python \
  softmax_sim_avx512/kernel/softmax/scripts/build_traces.sh
```

结果：

- x86 correctness：16 组固定输入全部通过；向量实现相对标量近似的最大绝对误差为 `7.45e-9`，输出和误差在 `2e-5` 阈值内。
- x86 汇编：`softmax_avx512_f32` 解析为 78 条指令、108 个通用 uop；包含 load/store、FMA、conversion、integer、reduction lowering 和实际出现的 shuffle/extract 指令。
- RVV 汇编：`softmax_rvv_f32` 解析为 89 条指令、94 个通用 uop；包含 `vsetvli`、`vle32/vse32`、FMA、conversion 和两类 reduction。trace 记录最终 `SEW=32, LMUL=m1, VL=runtime (AVL=a5), tail=ta, mask=ma`。
- x86 trace 已绑定 `profiles/amd_zen4.yaml`；profile 中没有定义的 scalar/frontend/control timing 被显式标记为 `unmodeled_profile_class`，没有自动填充默认时序。
- 两份汇编均未发现 `call`、外部数学库调用或栈保护指令。

## 当前限制

当前环境有 RVV cross compiler，但没有 QEMU、Spike 或可运行的 RVV 主机。因此 RVV 已完成编译、汇编覆盖和 recipe/trace 验证，尚未完成运行时数值测试。后续获得 RVV 执行环境后，应使用与 x86 相同的输入集补充运行验证。

当前 Zen4 profile 只包含已校准的 `vaddps` opcode timing；绑定器对其他 uop 仅提供资源类别，不声称提供完整 opcode latency/throughput。模拟器接入时应继续使用 profile 的等效分解规则，并对未建模项保持显式失败或待校准状态。
