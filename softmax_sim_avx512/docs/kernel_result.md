# Kernel 测试结果

本文汇总新增 kernel 的功能验证、Zen 4 真机周期和模拟器周期。真机以 7 次重复测量的净周期中位数为主；乱序模型同时给出显式关闭 memory-source FMA overlap 限制的基线，以及按 Zen 4 profile 默认开启限制的修改后结果。

## 验证环境

- 真机：AMD EPYC 9684X（Zen 4），固定 CPU 8、NUMA node 0。
- x86：GCC 13.3，AVX-512/FMA，功能测试 34/34 通过。
- RVV：GCC 13.3 cross compiler，Spike VLEN=128/512 均 34/34 通过。
- 模拟器 profile：`amd-zen4-epyc-9684x`。
- Profile SHA-256：`375fef4b97795e5906b25dd1471204cf54268c0f55dbc06848d63aa922b2d5e2`。
- Zen 4 overlap 配置：默认开启，最多 2 个待发射组，仅匹配 `vector_fp_fma` semantic uop。
- 共享 issue domain：窄执行域 2 part-token/cycle、总执行域 4 part-token/cycle、加权寄存器源交付域 8 source-token/cycle。
- 报告仅覆盖 `N=512/1024/2048`，全部使用 `hot-l1`。
- 校验脚本只读取 profile，不会根据误差自动改参。

## 周期对比

相对误差为 `(模拟 - 真机中位数) / 真机中位数`。三个规模的绝对误差不超过 10% 记为通过。

| Kernel | N | Cache | 真机净周期 [p10, p90] | 限制前周期 | 限制前误差 | 限制后周期 | 限制后误差 | 绝对误差改善 | 结论 |
|---|---:|---|---:|---:|---:|---:|---:|---:|---|
| fma_throughput | 512 | hot-l1 | 529.15 [529.09, 536.51] | 534.00 | +0.9% | 541.00 | +2.2% | -1.3 pp | 通过 |
| fma_throughput | 1024 | hot-l1 | 1041.30 [1041.01, 1067.54] | 1046.00 | +0.5% | 1061.00 | +1.9% | -1.4 pp | 通过 |
| fma_throughput | 2048 | hot-l1 | 2068.54 [2065.63, 2089.04] | 2070.00 | +0.1% | 2101.00 | +1.6% | -1.5 pp | 通过 |
| fma_latency | 512 | hot-l1 | 2145.48 [2145.29, 2145.72] | 2152.00 | +0.3% | 2152.00 | +0.3% | +0.0 pp | 通过 |
| fma_latency | 1024 | hot-l1 | 4289.58 [4289.25, 4290.58] | 4296.00 | +0.1% | 4296.00 | +0.1% | +0.0 pp | 通过 |
| fma_latency | 2048 | hot-l1 | 8579.38 [8578.15, 8584.12] | 8584.00 | +0.1% | 8584.00 | +0.1% | +0.0 pp | 通过 |
| axpy | 512 | hot-l1 | 95.27 [91.64, 98.87] | 77.00 | -19.2% | 91.00 | -4.5% | +14.7 pp | 通过 |
| axpy | 1024 | hot-l1 | 172.61 [171.73, 174.02] | 143.00 | -17.2% | 173.00 | +0.2% | +16.9 pp | 通过 |
| axpy | 2048 | hot-l1 | 333.87 [333.45, 334.96] | 275.00 | -17.6% | 340.00 | +1.8% | +15.8 pp | 通过 |
| dot_product | 512 | hot-l1 | 152.04 [152.02, 154.01] | 157.00 | +3.3% | 157.00 | +3.3% | +0.0 pp | 通过 |
| dot_product | 1024 | hot-l1 | 280.05 [280.03, 281.99] | 285.00 | +1.8% | 285.00 | +1.8% | +0.0 pp | 通过 |
| dot_product | 2048 | hot-l1 | 536.12 [536.08, 538.83] | 541.00 | +0.9% | 541.00 | +0.9% | +0.0 pp | 通过 |
| vector_copy | 512 | hot-l1 | 63.02 [62.97, 63.12] | 68.00 | +7.9% | 68.00 | +7.9% | +0.0 pp | 通过 |
| vector_copy | 1024 | hot-l1 | 127.08 [127.06, 127.25] | 132.00 | +3.9% | 132.00 | +3.9% | +0.0 pp | 通过 |
| vector_copy | 2048 | hot-l1 | 255.31 [255.29, 255.70] | 260.00 | +1.8% | 260.00 | +1.8% | +0.0 pp | 通过 |
| vector_triad | 512 | hot-l1 | 92.54 [91.64, 94.35] | 77.00 | -16.8% | 91.00 | -1.7% | +15.1 pp | 通过 |
| vector_triad | 1024 | hot-l1 | 171.88 [170.76, 176.03] | 143.00 | -16.8% | 173.00 | +0.6% | +16.2 pp | 通过 |
| vector_triad | 2048 | hot-l1 | 333.86 [332.21, 334.68] | 275.00 | -17.6% | 340.00 | +1.8% | +15.8 pp | 通过 |
| vector_reduction | 512 | hot-l1 | 127.17 [120.52, 130.38] | 124.00 | -2.5% | 124.00 | -2.5% | +0.0 pp | 通过 |
| vector_reduction | 1024 | hot-l1 | 233.53 [229.92, 237.83] | 220.00 | -5.8% | 220.00 | -5.8% | +0.0 pp | 通过 |
| vector_reduction | 2048 | hot-l1 | 448.77 [443.07, 453.66] | 412.00 | -8.2% | 412.00 | -8.2% | +0.0 pp | 通过 |
| conversion | 512 | hot-l1 | 75.52 [75.47, 75.92] | 77.00 | +2.0% | 77.00 | +2.0% | +0.0 pp | 通过 |
| conversion | 1024 | hot-l1 | 144.07 [144.05, 144.19] | 141.00 | -2.1% | 141.00 | -2.1% | +0.0 pp | 通过 |
| conversion | 2048 | hot-l1 | 271.27 [271.26, 271.53] | 269.00 | -0.8% | 269.00 | -0.8% | +0.0 pp | 通过 |
| vector_integer | 512 | hot-l1 | 66.03 [65.91, 66.06] | 71.00 | +7.5% | 71.00 | +7.5% | +0.0 pp | 通过 |
| vector_integer | 1024 | hot-l1 | 130.10 [130.07, 130.90] | 135.00 | +3.8% | 135.00 | +3.8% | +0.0 pp | 通过 |
| vector_integer | 2048 | hot-l1 | 258.28 [258.25, 258.56] | 263.00 | +1.8% | 263.00 | +1.8% | +0.0 pp | 通过 |
| mixed_compute | 512 | hot-l1 | 122.01 [118.59, 123.21] | 119.00 | -2.5% | 117.00 | -4.1% | -1.6 pp | 通过 |
| mixed_compute | 1024 | hot-l1 | 242.03 [236.76, 250.02] | 226.00 | -6.6% | 220.00 | -9.1% | -2.5 pp | 通过 |
| mixed_compute | 2048 | hot-l1 | 498.04 [479.07, 506.20] | 443.00 | -11.1% | 429.00 | -13.9% | -2.8 pp | 待分析 |
| pointer_agu | 512 | hot-l1 | 120.56 [116.46, 125.51] | 111.00 | -7.9% | 111.00 | -7.9% | +0.0 pp | 通过 |
| pointer_agu | 1024 | hot-l1 | 227.24 [224.03, 228.30] | 211.00 | -7.1% | 211.00 | -7.1% | +0.0 pp | 通过 |
| pointer_agu | 2048 | hot-l1 | 444.55 [444.22, 446.22] | 409.00 | -8.0% | 409.00 | -8.0% | +0.0 pp | 通过 |

## 顺序模型诊断（N=2048）

顺序模型仅用于观察乱序调度收益，不参与通过判定。

| Kernel | 顺序周期 | 乱序（默认限制）周期 |
|---|---:|---:|
| fma_throughput | 2877.00 | 2101.00 |
| fma_latency | 9486.00 | 8584.00 |
| axpy | 1552.00 | 340.00 |
| dot_product | 1058.00 | 541.00 |
| vector_copy | 775.00 | 260.00 |
| vector_triad | 1552.00 | 340.00 |
| vector_reduction | 1579.00 | 412.00 |
| conversion | 1799.00 | 269.00 |
| vector_integer | 1159.00 | 263.00 |
| mixed_compute | 2826.00 | 429.00 |
| pointer_agu | 2061.00 | 409.00 |

## 模拟器诊断摘要（N=2048）

| Kernel | Macro-op | Execution uop | 关键路径 | Peak ROB/VS/LQ/SQ | 主要资源 issue |
|---|---:|---:|---:|---:|---|
| fma_throughput | 2425 | 4865 | 86.00 | 90/64/10/8 | address-generation=260, branch-fit=19, load-data=132, scalar-alu-fit=63, store-data=128, vector-fp=4262 |
| fma_latency | 2696 | 5260 | 8582.00 | 83/64/4/4 | address-generation=258, branch-fit=130, load-data=130, scalar-alu-fit=258, store-data=128, vector-fp=4355 |
| axpy | 775 | 1417 | 137.00 | 133/20/44/22 | address-generation=385, branch-fit=130, load-data=257, scalar-alu-fit=259, store-data=128, vector-fp=257 |
| dot_product | 657 | 1170 | 538.00 | 121/29/44/1 | address-generation=257, branch-fit=130, load-data=256, scalar-alu-fit=259, shuffle=4, vector-fp=261 |
| vector_copy | 645 | 901 | 133.00 | 225/0/44/45 | address-generation=256, branch-fit=130, load-data=128, scalar-alu-fit=258, store-data=128 |
| vector_triad | 775 | 1417 | 137.00 | 133/20/44/22 | address-generation=385, branch-fit=130, load-data=257, scalar-alu-fit=259, store-data=128, vector-fp=257 |
| vector_reduction | 666 | 1437 | 411.00 | 126/40/44/1 | address-generation=258, branch-fit=130, load-data=257, scalar-alu-fit=258, shuffle=9, vector-fp=522 |
| conversion | 773 | 1413 | 140.00 | 216/64/36/36 | address-generation=256, branch-fit=130, conversion=512, load-data=128, scalar-alu-fit=258, store-data=128 |
| vector_integer | 775 | 1415 | 135.00 | 268/16/44/45 | address-generation=256, branch-fit=130, load-data=128, scalar-alu-fit=259, store-data=128, vector-integer=514 |
| mixed_compute | 1160 | 2442 | 146.00 | 150/64/34/17 | address-generation=385, branch-fit=130, conversion=512, load-data=257, scalar-alu-fit=259, store-data=128, vector-fp=257, vector-integer=514 |
| pointer_agu | 904 | 1928 | 139.00 | 105/27/44/15 | address-generation=512, branch-fit=130, load-data=384, scalar-alu-fit=261, store-data=128, vector-fp=512 |

## 审核结论

- 有真机数据且参与审核的周期点共 33 个，32 个处于 ±10% 内。
- overlap 限制实际改变了 12 个参审点；全部参审点的平均绝对误差由 6.2% 变为 3.7%，三个稳态规模则由 6.2% 变为 3.7%，总体改善。
- `N=512/1024/2048`：AXPY/Triad 最大绝对误差由 19.2% 降至 4.5%；Pointer/AGU 保持不变且不超过 8.0%；Mixed Compute 仍为 4.1% 到 13.9%。
- 稳态点仍需分析的 kernel：mixed_compute。
- 容量边界与 L2 初始状态不在本轮报告范围内。
- overlap 限制是微架构相关的等效调度约束，不应被解读为精确的物理队列容量。
- 后续 profile 变更仍需独立微基准和 hold-out kernel 共同验证。

原始 PMU 和模拟器 JSON 位于被 Git 忽略的 `artifacts/kernel_validation/`。
