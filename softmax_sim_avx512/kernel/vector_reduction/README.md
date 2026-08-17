# Vector Reduction

- **语义**：同时计算输入元素的总和与最大值。
- **输入布局**：`input[0:N]`，一个连续 FP32 向量。
- **资源覆盖**：load、vector FP add/max，以及 reduce-add、reduce-max 的 extract/shuffle lowering。
- **输出**：`output[0]` 为总和，`output[1]` 为最大值。
