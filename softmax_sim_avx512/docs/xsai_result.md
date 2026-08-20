# XSAI 模拟器对齐结果

> 本文件由 `xsai/scripts/run_alignment.py` 生成。工具只比较结果，不自动修改 profile。

## 状态

- 模式：`simulate`
- RTL 汇总：`/nfs/home/yuweijie/project/amd_perf/softmax_sim_avx512/artifacts/xsai/rtl/summary.csv`
- RTL 点数：36，模拟点数：36，拟合有效点数：36
- Profile：`xsai-default-matrix-rvv`（`ac27c4119a89a4efc920802184a754bd1f98ede6377d2afe5aa9eeb2bee8eca3`）
- 执行后端：`xsai-rvv`
- 执行模型：乱序、Hot-L1
- 缓存证据：clean=36，contaminated=0，unknown=0。后两类不进入拟合统计。

## 汇总

拟合有效点 MAPE 为 47.03%，最大绝对相对误差为 83.21%。

| Kernel | N | RTL cycles | Simulator cycles | Error | Cache | Fit |
|---|---:|---:|---:|---:|---|---|
| fma_throughput | 512 | 4548 | 4430 | -2.59% | clean | yes |
| fma_throughput | 1024 | 9065 | 8846 | -2.42% | clean | yes |
| fma_throughput | 2048 | 18086 | 17678 | -2.26% | clean | yes |
| fma_latency | 512 | 4341 | 4305 | -0.83% | clean | yes |
| fma_latency | 1024 | 8628 | 8593 | -0.41% | clean | yes |
| fma_latency | 2048 | 17206 | 17169 | -0.22% | clean | yes |
| axpy | 512 | 3148 | 908 | -71.16% | clean | yes |
| axpy | 1024 | 6196 | 1804 | -70.88% | clean | yes |
| axpy | 2048 | 12352 | 3596 | -70.89% | clean | yes |
| vector_copy | 512 | 1276 | 898 | -29.62% | clean | yes |
| vector_copy | 1024 | 2667 | 1794 | -32.73% | clean | yes |
| vector_copy | 2048 | 5162 | 3586 | -30.53% | clean | yes |
| vector_triad | 512 | 3148 | 908 | -71.16% | clean | yes |
| vector_triad | 1024 | 6265 | 1804 | -71.21% | clean | yes |
| vector_triad | 2048 | 12503 | 3596 | -71.24% | clean | yes |
| pointer_agu | 512 | 3625 | 1039 | -71.34% | clean | yes |
| pointer_agu | 1024 | 7208 | 2063 | -71.38% | clean | yes |
| pointer_agu | 2048 | 14377 | 4111 | -71.41% | clean | yes |
| dot_product | 512 | 5414 | 935 | -82.73% | clean | yes |
| dot_product | 1024 | 10802 | 1831 | -83.05% | clean | yes |
| dot_product | 2048 | 21580 | 3623 | -83.21% | clean | yes |
| vector_reduction | 512 | 4394 | 3848 | -12.43% | clean | yes |
| vector_reduction | 1024 | 8746 | 7688 | -12.10% | clean | yes |
| vector_reduction | 2048 | 17450 | 15368 | -11.93% | clean | yes |
| conversion | 512 | 3963 | 1039 | -73.78% | clean | yes |
| conversion | 1024 | 7902 | 2063 | -73.89% | clean | yes |
| conversion | 2048 | 15781 | 4111 | -73.95% | clean | yes |
| vector_integer | 512 | 3721 | 910 | -75.54% | clean | yes |
| vector_integer | 1024 | 7422 | 1806 | -75.67% | clean | yes |
| vector_integer | 2048 | 14825 | 3598 | -75.73% | clean | yes |
| mixed_compute | 512 | 6534 | 3345 | -48.81% | clean | yes |
| mixed_compute | 1024 | 13041 | 6673 | -48.83% | clean | yes |
| mixed_compute | 2048 | 26055 | 13329 | -48.84% | clean | yes |
| softmax | 512 | 15649 | 11949 | -23.64% | clean | yes |
| softmax | 1024 | 31130 | 23871 | -23.32% | clean | yes |
| softmax | 2048 | 62388 | 47715 | -23.52% | clean | yes |

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

普通 `v8` 的 load 与 load-use 结果不支持把所有向量 load 统一设为 16 cycle；该假设已排除。现有两组 vset 测试分别覆盖特殊 keep-VL 形式和标量 `rd` RAW，但都没有覆盖真实 kernel 每轮 `vsetvli a5,a5` 后由向量/VLSU 消费 VL 的路径。

FMA kernel 的误差约为 0%--3%，而多数组合 kernel 仍明显偏乐观。当前最小未决缺口是 profile-driven 的 VL 写回可见性，以及 VLSU oldest/order、split/merge/replay 和完成路径；在定向 RTL 微基准完成前，报告不会用 kernel 误差反推一个统一延迟或串行屏障。

## 判定规则

`cache-contaminated` 点保留在表格和机器可读文件中，但不参与拟合统计。缺少 L1/TLB HPM 证据的 `unknown` 点同样不参与拟合，避免把缓存影响误归因于执行后端。
