# 设计与验证文档索引

`docs/` 保存项目设计、实验方案和验证结果。实际操作入门请先阅读
[`tutorial/`](../tutorial/README.md)。

| 文件 | 内容 |
|---|---|
| [`flashattention_algo.md`](flashattention_algo.md) | FlashAttention 算法、分块思路和向量化分析。 |
| [`kernel_test.md`](kernel_test.md) | 新增 kernel 的实现、真机测量、模拟和差异审核流程。 |
| [`kernel_result.md`](kernel_result.md) | 当前 kernel 的 Zen 4 真机周期、模拟周期和误差结果。 |
| [`kernel_to_uop.md`](kernel_to_uop.md) | x86/RVV kernel 到通用 semantic uop 的设计与执行计划。 |
| [`kernel_to_uop_result.md`](kernel_to_uop_result.md) | kernel、汇编和 semantic uop 映射的实现及验证结果。 |
| [`profile_param_test.md`](profile_param_test.md) | 微架构 profile 参数的测试原理、可观测边界和估计方法。 |
| [`semantic_uop.md`](semantic_uop.md) | 跨 ISA semantic uop 的语义、操作数、宽度、依赖和资源契约。 |
| [`simulator_plan.md`](simulator_plan.md) | 事件驱动顺序/乱序模拟器的实施计划与审核决策。 |
| [`simulator_resource.md`](simulator_resource.md) | 执行、访存、队列和共享 issue-domain 的资源模型。 |
| [`simulator_result.md`](simulator_result.md) | Softmax 首轮模拟实现、调度统计和真机对比记录。 |
