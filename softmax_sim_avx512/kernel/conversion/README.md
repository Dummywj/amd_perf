# Conversion

- **语义**：将 FP32 向零截断为 INT32，再转换回 FP32。
- **输入布局**：`input[0:N]`，一个连续、处于 INT32 可表示范围内的 FP32 向量。
- **资源覆盖**：FP32-to-INT32 与 INT32-to-FP32 conversion 管线，以及首尾 load/store。
- **输出**：`output[0:N]`，保存转换回 FP32 的整数值。
