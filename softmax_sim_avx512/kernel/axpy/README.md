# AXPY

- **语义**：`output[i] = 1.25 * x[i] + y[i]`。
- **输入布局**：`input[0:N]` 为 `x`，`input[N:2N]` 为 `y`。
- **资源覆盖**：每个向量包含两次 load、一次 vector FMA 和一次 store，用于观察计算与访存重叠。
- **输出**：`output[0:N]`。
