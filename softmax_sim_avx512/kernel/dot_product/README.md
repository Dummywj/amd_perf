# Dot Product

- **语义**：`output[0] = sum(x[i] * y[i])`，向量主体使用 FMA 累加。
- **输入布局**：`input[0:N]` 为 `x`，`input[N:2N]` 为 `y`。
- **资源覆盖**：x86 使用双 load、vector FMA 依赖链和最终 reduce-add；RVV 当前使用
  `vfmul` 后按 VL 执行 `vfredusum`，因此只验证相同数学语义，不声称两种 ISA 的
  中间依赖结构相同。
- **输出**：`output[0]` 为点积结果。
