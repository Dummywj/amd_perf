# Mixed Compute

- **语义**：`q = (trunc_i32(x) + 17) << 1`，随后计算 `output = 0.25 * float(q) + x`。
- **输入布局**：`input[0:N]`，一个处于 INT32 可表示范围内的 FP32 向量。
- **资源覆盖**：conversion、vector integer/shift 和 vector FMA 的共享 issue domain。
- **输出**：`output[0:N]`。
