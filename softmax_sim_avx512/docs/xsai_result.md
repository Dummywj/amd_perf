# XSAI 模拟器对齐结果

> 本文件由 `xsai/scripts/run_alignment.py` 生成。工具只比较结果，不自动修改 profile。

## 状态

- 模式：`simulate`
- RTL 汇总：`/nfs/home/yuweijie/project/amd_perf/softmax_sim_avx512/artifacts/xsai/rtl/summary.csv`
- RTL 点数：36，模拟点数：36，拟合有效点数：36
- Profile：`xsai-default-matrix-rvv`（`57c6a4ae5721a2b8afa80085ac6be72cf361610aadef37cd588406fdbdbead44`）
- 执行后端：`xsai-rvv`
- 执行模型：乱序、Hot-L1
- 缓存证据：clean=36，contaminated=0，unknown=0。后两类不进入拟合统计。

## 汇总

拟合有效点 MAPE 为 1.06%，最大绝对相对误差为 4.22%。

| Kernel | N | RTL cycles | Simulator cycles | Error | Cache | Fit |
|---|---:|---:|---:|---:|---|---|
| fma_throughput | 512 | 4548 | 4431 | -2.57% | clean | yes |
| fma_throughput | 1024 | 9065 | 8847 | -2.40% | clean | yes |
| fma_throughput | 2048 | 18086 | 17679 | -2.25% | clean | yes |
| fma_latency | 512 | 4341 | 4307 | -0.78% | clean | yes |
| fma_latency | 1024 | 8628 | 8595 | -0.38% | clean | yes |
| fma_latency | 2048 | 17206 | 17171 | -0.20% | clean | yes |
| axpy | 512 | 3148 | 3133 | -0.48% | clean | yes |
| axpy | 1024 | 6196 | 6269 | +1.18% | clean | yes |
| axpy | 2048 | 12352 | 12541 | +1.53% | clean | yes |
| vector_copy | 512 | 1276 | 1282 | +0.47% | clean | yes |
| vector_copy | 1024 | 2667 | 2562 | -3.94% | clean | yes |
| vector_copy | 2048 | 5162 | 5122 | -0.77% | clean | yes |
| vector_triad | 512 | 3148 | 3133 | -0.48% | clean | yes |
| vector_triad | 1024 | 6265 | 6269 | +0.06% | clean | yes |
| vector_triad | 2048 | 12503 | 12541 | +0.30% | clean | yes |
| pointer_agu | 512 | 3625 | 3645 | +0.55% | clean | yes |
| pointer_agu | 1024 | 7208 | 7293 | +1.18% | clean | yes |
| pointer_agu | 2048 | 14377 | 14589 | +1.47% | clean | yes |
| dot_product | 512 | 5414 | 5444 | +0.55% | clean | yes |
| dot_product | 1024 | 10802 | 10884 | +0.76% | clean | yes |
| dot_product | 2048 | 21580 | 21764 | +0.85% | clean | yes |
| vector_reduction | 512 | 4394 | 4391 | -0.07% | clean | yes |
| vector_reduction | 1024 | 8746 | 8775 | +0.33% | clean | yes |
| vector_reduction | 2048 | 17450 | 17543 | +0.53% | clean | yes |
| conversion | 512 | 3963 | 3960 | -0.08% | clean | yes |
| conversion | 1024 | 7902 | 7928 | +0.33% | clean | yes |
| conversion | 2048 | 15781 | 15864 | +0.53% | clean | yes |
| vector_integer | 512 | 3721 | 3704 | -0.46% | clean | yes |
| vector_integer | 1024 | 7422 | 7416 | -0.08% | clean | yes |
| vector_integer | 2048 | 14825 | 14840 | +0.10% | clean | yes |
| mixed_compute | 512 | 6534 | 6520 | -0.21% | clean | yes |
| mixed_compute | 1024 | 13041 | 13048 | +0.05% | clean | yes |
| mixed_compute | 2048 | 26055 | 26104 | +0.19% | clean | yes |
| softmax | 512 | 15649 | 16253 | +3.86% | clean | yes |
| softmax | 1024 | 31130 | 32445 | +4.22% | clean | yes |
| softmax | 2048 | 62388 | 64829 | +3.91% | clean | yes |

## 差距诊断

| RTL 微基准 | cycles/operation | 说明 |
|---|---:|---|
| `vset_throughput` | 4.991 | `x0,x0` keep-VL 形式的独立吞吐 |
| `vset_rd_dependency` | 5.003 | 标量 `rd` 到下一条 vset 的 RAW 链 |
| `load_same_vd` | 1.147 | 普通向量寄存器 `v8` 的重复 load |
| `load_alu_dependency` | 2.205 | 普通 `v8` load -> vector ALU |
| `load_fma_dependency` | 2.213 | 普通 `v8` load -> FMA |
| `load_fma_iteration` | 3.016 | vset 在循环外的 load/FMA 迭代 |
| `load_fma_store_iteration` | 4.016 | vset 在循环外的 load/FMA/store 迭代 |

普通 `v8` 的 load 与 load-use 结果不支持把所有向量 load 统一设为 16 cycle；该假设已排除。独立 XSAI-RVV 后端保留 LMUL/EMUL 展开的 scheduler slot，并用逐迭代 vector-state epoch 描述 `vsetvli` 到向量/VLSU consumer 的可见性。

当前 XSAI 专用策略按 semantic dataflow 区分 load-only、computed-store、reduction 和混合 epoch，并对 load service 设置独立 token；不按 kernel 名称、N 或 RVV mnemonic 添加补偿。load visibility 与 computed-store drain 由 clean 的 13-case 矩阵交叉检查；reduction overlap 与 mixed capacity 仍是低置信 kernel-fit 参数，尚无独立定向 holdout。这些等效约束不是对物理 VLSU pipe、merge buffer 或 replay 状态机的逐周期复刻。

尚未精确建模的部分主要是 DCache bank 仲裁、VLSU replay/merge buffer 占用和 redirect 恢复。它们在 aligned 多流定向 case 中仍可观察到，但当前 kernel 矩阵全部处于 ±5% 内，因此本轮不再增加无法独立辨识的参数。

## 判定规则

`cache-contaminated` 点保留在表格和机器可读文件中，但不参与拟合统计。缺少 L1/TLB HPM 证据的 `unknown` 点同样不参与拟合，避免把缓存影响误归因于执行后端。
