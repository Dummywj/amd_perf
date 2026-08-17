# Vector Triad

- **语义**：`output[i] = x[i] + 1.25 * y[i]`。
- **输入布局**：`input[0:N]` 为 `x`，`input[N:2N]` 为 `y`。
- **资源覆盖**：双 load、vector FMA 和 store，用于测试多访存与计算资源竞争。
- **输出**：`output[0:N]`。
