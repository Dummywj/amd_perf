# Kernel 测试结果

本文汇总新增 kernel 的功能验证、Zen 4 真机周期和模拟器周期。真机以 7 次重复测量的净周期中位数为主，模拟器以乱序模型为主；顺序模型仅用于诊断乱序收益。

## 验证环境

- 真机：AMD EPYC 9684X（Zen 4），固定 CPU 8、NUMA node 0。
- x86：GCC 13.3，AVX-512/FMA，功能测试 56/56 通过。
- RVV：GCC 13.3 cross compiler，Spike VLEN=128/512 均 56/56 通过。
- 模拟器 profile：`amd-zen4-epyc-9684x`。
- Profile SHA-256：`c088e39a9153e1701cd38b28116b337fff06005de430cfa921fdd5d0761747f5`。
- `N=256/1024` 使用 `hot-l1`；`N=4096` 使用 `hot-capacity`。
- 第一批纯向量 kernel 的 API 约束为 `N > 0` 且 `N % 16 == 0`。
- 本轮未修改既有 profile 参数；新 memory-source timing 是基于既有 load/compute 参数的 provisional 等效分解，尚未单独校准。

## 周期对比

相对误差为 `(乱序模拟 - 真机中位数) / 真机中位数`。绝对值不超过 10%记为首轮通过，超过 10% 记为待分析。

| Kernel | N | Cache | 真机总周期 [p10, p90] | 真机周期/元素 | 乱序周期/元素 | 乱序总周期 | 顺序总周期 | 误差 | 结论 |
|---|---:|---|---:|---:|---:|---:|---:|---:|---|
| fma_throughput | 256 | hot-l1 | 273.11 [273.05, 273.19] | 1.0669 | 1.0859 | 278.00 | 385.00 | +1.8% | 通过 |
| fma_throughput | 1024 | hot-l1 | 1041.31 [1041.01, 1058.47] | 1.0169 | 1.0215 | 1046.00 | 1453.00 | +0.5% | 通过 |
| fma_throughput | 4096 | hot-capacity | 4251.44 [4235.06, 4254.81] | 1.0379 | 1.0083 | 4130.00 | 8320.00 | -2.9% | 通过 |
| fma_latency | 256 | hot-l1 | 1073.22 [1073.19, 1073.32] | 4.1923 | 4.2188 | 1080.00 | 1198.00 | +0.6% | 通过 |
| fma_latency | 1024 | hot-l1 | 4289.91 [4289.63, 4290.16] | 4.1894 | 4.1953 | 4296.00 | 4750.00 | +0.1% | 通过 |
| fma_latency | 4096 | hot-capacity | 17197.62 [17196.75, 17197.92] | 4.1986 | 4.1917 | 17169.00 | 21528.00 | -0.2% | 通过 |
| axpy | 256 | hot-l1 | 51.02 [50.94, 53.41] | 0.1993 | 0.1680 | 43.00 | 204.00 | -15.7% | 待分析 |
| axpy | 1024 | hot-l1 | 173.43 [171.87, 175.40] | 0.1694 | 0.1396 | 143.00 | 782.00 | -17.5% | 待分析 |
| axpy | 4096 | hot-capacity | 1486.06 [1484.92, 1487.37] | 0.3628 | 0.2773 | 1136.00 | 5909.00 | -23.6% | 待分析 |
| dot_product | 256 | hot-l1 | 90.01 [88.02, 90.90] | 0.3516 | 0.3633 | 93.00 | 158.00 | +3.3% | 通过 |
| dot_product | 1024 | hot-l1 | 282.04 [280.03, 285.25] | 0.2754 | 0.2783 | 285.00 | 544.00 | +1.0% | 通过 |
| dot_product | 4096 | hot-capacity | 1048.63 [1048.24, 1049.35] | 0.2560 | 0.2595 | 1063.00 | 4893.00 | +1.4% | 通过 |
| vector_copy | 256 | hot-l1 | 31.94 [31.01, 32.04] | 0.1248 | 0.1406 | 36.00 | 103.00 | +12.7% | 待分析 |
| vector_copy | 1024 | hot-l1 | 127.09 [127.07, 127.22] | 0.1241 | 0.1289 | 132.00 | 391.00 | +3.9% | 通过 |
| vector_copy | 4096 | hot-capacity | 521.67 [519.47, 521.82] | 0.1274 | 0.1260 | 516.00 | 1543.00 | -1.1% | 通过 |
| vector_triad | 256 | hot-l1 | 53.01 [51.02, 55.15] | 0.2071 | 0.1680 | 43.00 | 204.00 | -18.9% | 待分析 |
| vector_triad | 1024 | hot-l1 | 174.12 [172.33, 175.89] | 0.1700 | 0.1396 | 143.00 | 782.00 | -17.9% | 待分析 |
| vector_triad | 4096 | hot-capacity | 1488.12 [1487.85, 1488.67] | 0.3633 | 0.2773 | 1136.00 | 5909.00 | -23.7% | 待分析 |
| vector_reduction | 256 | hot-l1 | 73.82 [72.00, 78.04] | 0.2883 | 0.2969 | 76.00 | 235.00 | +3.0% | 通过 |
| vector_reduction | 1024 | hot-l1 | 233.00 [225.62, 235.83] | 0.2275 | 0.2148 | 220.00 | 811.00 | -5.6% | 通过 |
| vector_reduction | 4096 | hot-capacity | 877.28 [874.89, 879.88] | 0.2142 | 0.1943 | 796.00 | 3115.00 | -9.3% | 通过 |
| conversion | 256 | hot-l1 | 40.51 [40.01, 40.51] | 0.1582 | 0.1758 | 45.00 | 231.00 | +11.1% | 待分析 |
| conversion | 1024 | hot-l1 | 144.08 [144.06, 144.39] | 0.1407 | 0.1377 | 141.00 | 903.00 | -2.1% | 通过 |
| conversion | 4096 | hot-capacity | 543.21 [541.70, 547.80] | 0.1326 | 0.1282 | 525.00 | 3591.00 | -3.4% | 通过 |
| vector_integer | 256 | hot-l1 | 34.01 [34.00, 34.10] | 0.1328 | 0.1523 | 39.00 | 151.00 | +14.7% | 待分析 |
| vector_integer | 1024 | hot-l1 | 130.08 [129.90, 130.38] | 0.1270 | 0.1318 | 135.00 | 583.00 | +3.8% | 通过 |
| vector_integer | 4096 | hot-capacity | 532.48 [531.96, 532.87] | 0.1300 | 0.1267 | 519.00 | 2311.00 | -2.5% | 通过 |
| mixed_compute | 256 | hot-l1 | 66.01 [66.01, 71.95] | 0.2578 | 0.2617 | 67.00 | 362.00 | +1.5% | 通过 |
| mixed_compute | 1024 | hot-l1 | 223.08 [221.03, 250.01] | 0.2179 | 0.2070 | 212.00 | 1418.00 | -5.0% | 通过 |
| mixed_compute | 4096 | hot-capacity | 972.40 [962.07, 984.41] | 0.2374 | 0.2065 | 846.00 | 8212.00 | -13.0% | 待分析 |
| pointer_agu | 256 | hot-l1 | 66.02 [61.01, 68.92] | 0.2579 | 0.2422 | 62.00 | 265.00 | -6.1% | 通过 |
| pointer_agu | 1024 | hot-l1 | 226.60 [224.51, 227.89] | 0.2213 | 0.2061 | 211.00 | 1035.00 | -6.9% | 通过 |
| pointer_agu | 4096 | hot-capacity | 2021.45 [2020.97, 2023.21] | 0.4935 | 0.3796 | 1555.00 | 9480.00 | -23.1% | 待分析 |

## 模拟器诊断摘要（N=4096）

| Kernel | Macro-op | Execution uop | 关键路径 | Peak ROB/VS/LQ/SQ | 主要资源 issue |
|---|---:|---:|---:|---:|---|
| fma_throughput | 4825 | 9697 | 112.00 | 90/64/10/8 | address-generation=516, branch-fit=35, load-data=260, scalar-alu-fit=111, store-data=256, vector-fp=8518 |
| fma_latency | 5384 | 10508 | 17168.00 | 82/64/6/4 | address-generation=514, branch-fit=258, load-data=258, scalar-alu-fit=514, store-data=256, vector-fp=8707 |
| axpy | 1543 | 2825 | 275.00 | 136/21/44/23 | address-generation=769, branch-fit=258, load-data=513, scalar-alu-fit=515, store-data=256, vector-fp=513 |
| dot_product | 1297 | 2322 | 1060.00 | 121/29/44/1 | address-generation=513, branch-fit=258, load-data=512, scalar-alu-fit=515, shuffle=4, vector-fp=517 |
| vector_copy | 1285 | 1797 | 261.00 | 225/0/44/45 | address-generation=512, branch-fit=258, load-data=256, scalar-alu-fit=514, store-data=256 |
| vector_triad | 1543 | 2825 | 275.00 | 136/21/44/23 | address-generation=769, branch-fit=258, load-data=513, scalar-alu-fit=515, store-data=256, vector-fp=513 |
| vector_reduction | 1306 | 2845 | 795.00 | 126/40/44/1 | address-generation=514, branch-fit=258, load-data=513, scalar-alu-fit=514, shuffle=9, vector-fp=1034 |
| conversion | 1541 | 2821 | 268.00 | 216/64/36/36 | address-generation=512, branch-fit=258, conversion=1024, load-data=256, scalar-alu-fit=514, store-data=256 |
| vector_integer | 1543 | 2823 | 263.00 | 268/16/44/45 | address-generation=512, branch-fit=258, load-data=256, scalar-alu-fit=515, store-data=256, vector-integer=1026 |
| mixed_compute | 2312 | 4874 | 284.00 | 150/64/33/17 | address-generation=769, branch-fit=258, conversion=1024, load-data=513, scalar-alu-fit=515, store-data=256, vector-fp=513, vector-integer=1026 |
| pointer_agu | 1800 | 3848 | 277.00 | 105/29/44/15 | address-generation=1024, branch-fit=258, load-data=768, scalar-alu-fit=517, store-data=256, vector-fp=1024 |

## 审核结论

- 共 33 个周期点，22 个处于 ±10% 内；在 `N>=1024` 的 22 个稳态点中，16 个处于 ±10% 内。
- FMA throughput/latency、Dot、Copy、Reduction、Conversion、Integer 已能较好隔离对应资源，主要稳态点达到约 10% 误差范围。
- AXPY、Triad、Pointer/AGU 以及部分 Mixed Compute 点仍有明显偏差，优先检查 memory-source 指令的 load/compute 重叠、cache 初态和 AGU 竞争。
- `N=4096` 的多输入工作集超过 L1 容量，不应与 `hot-l1` 点混合拟合。
- 新 memory-source profile recipe 复用既有 load/compute timing，属于 provisional 等效假设；不能视为新的本地校准结果。
- 当前结果不足以授权修改 profile；后续参数变更仍需独立微基准和 hold-out kernel 共同验证。

原始 PMU 和模拟器 JSON 位于被 Git 忽略的 `artifacts/kernel_validation/`。
