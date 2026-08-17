# Pointer / AGU

- **语义**：`output[i] = x[i] + y[i] + z[i]`。
- **输入布局**：`input[0:N]` 为 `x`，`input[N:2N]` 为 `y`，`input[2N:3N]` 为 `z`。
- **资源覆盖**：每个向量三次 load、一次 store、地址生成和循环标量地址更新；FP add 仅用于消费数据。
- **输出**：`output[0:N]`。
