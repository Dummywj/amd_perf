# Vector Copy

- **语义**：`output[i] = input[i]`。
- **输入布局**：`input[0:N]`，一个连续 FP32 向量。
- **资源覆盖**：纯 vector load/store、AGU、L1 数据通路和 load/store queue，不包含向量计算。
- **输出**：`output[0:N]`。
