# Vector Integer

- **语义**：按 INT32 位模式计算 `output_bits[i] = (input_bits[i] + 17) << 1`。
- **输入布局**：`input[0:N]` 的存储类型为 FP32，内容按 INT32 位模式解释。
- **资源覆盖**：vector integer add、vector shift、整数 vector load/store。
- **输出**：`output[0:N]` 的存储类型为 FP32，内容为结果 INT32 位模式。
