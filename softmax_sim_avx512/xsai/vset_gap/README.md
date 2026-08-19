# XSAI vset/VL/VLSU 定向微基准

该独立裸机镜像用于判断真实 RVV kernel 在每轮执行 `vsetvli` 时，VL 状态依赖与 VLSU
顺序规则产生的额外周期。它不修改 `xsai-env`，也不依赖 36 个 kernel 的全量镜像；默认
产物写入 `artifacts/xsai/vset_gap/`，不会覆盖 `artifacts/xsai/rtl/` 基线。

## Case

所有 case 固定 VLEN=128、SEW=32、LMUL=1、64 次迭代，每轮处理 4 个 FP32 元素，并使用
普通向量寄存器 `v8/v16/v17`，不使用特殊的 `v0` 路径。

| case | loop 内的 vset 形式 | vector consumer |
|---|---|---|
| `regular_lfs` | `vsetvli t0,a4` | load + FMA + store |
| `keep_vl_lfs` | `vsetvli zero,zero` | load + FMA + store |
| `vlmax_lfs` | `vsetvli t0,zero` | load + FMA + store |
| `outside_lfs` | 无，vset 只在 loop 外 | load + FMA + store |
| `regular_load` | `vsetvli t0,a4` | load only |
| `regular_compute` | `vsetvli t0,a4` | dependent FMA only |
| `regular_store` | `vsetvli t0,a4` | store only |

四个 `*_lfs` case 使用相同的递增 input/output pointer、相同的 `v8` load/FMA/store 和
相同的标量 VL consumer。`regular_lfs - outside_lfs` 主要暴露每轮普通 vset/VL 更新的
增量；`keep_vl_lfs` 与 `vlmax_lfs` 用于区分 X0/X0 特殊形式和写 rd 的 VLMax 形式。
三个拆分 case 用于定位额外约束首先出现于 load admission、向量计算还是 store/VLSU
顺序中。拆分结果不能直接相加，因为完整 loop 允许资源重叠。

计时值扣除相同边界下的空函数调用开销，CSV 统一输出 `cycles_per_iteration`。timed
working set 只有 2080 B，构建时还会按 ELF 最终地址检查 L1 set 占用；每个样本通过
HPM 要求 L1D/DTLB clean 且 CUTE active/retire/memory request 全为 0。

## 运行

先构建并用 NEMU 做功能验证：

```bash
cd softmax_sim_avx512
xsai/vset_gap/scripts/build.sh
xsai/vset_gap/scripts/run_nemu.sh
```

NEMU 周期不用于 profile。通过功能验证后，才显式运行短矩阵 RTL：

```bash
xsai/vset_gap/scripts/run_rtl.sh
```

RTL 入口复用现有单核 `DefaultMatrixConfig`、difftest 和日志 gate，但只运行 7x5 个样本。
结果目录包含原始日志、`samples.csv`、`summary.csv`、`result_metadata.json` 和固定版本信息。

## 通用模拟器对齐

`fixtures/vset_gap_expanded.s` 是供现有 RVV 前端解析的展开汇编。它保留已构建反汇编中的
7 个函数、vset 形式、向量指令数和对齐 NOP；只将 `bnez`、`mv` 写为前端已支持的等价
指令。对齐脚本固定 `count=64`、VLEN=128、OOO 和 hot-L1，并拒绝 case 缺失、非 64 轮、
cache 非 clean 或 fit 无效的 RTL 汇总：

```bash
cd softmax_sim_avx512
conda run -n ucagent python xsai/vset_gap/scripts/run_alignment.py
```

输出位于被 git 忽略的 `artifacts/xsai/vset_gap/alignment/`：`alignment.csv` 便于逐项检查，
`alignment.json` 额外记录输入 SHA-256、执行参数和汇总误差。当前基线结果如下；误差为
`(simulator - RTL) / RTL`，这里只诊断 capability gap，不据此自动修改 profile。

| case | RTL cycles | simulator cycles | error |
|---|---:|---:|---:|
| `regular_lfs` | 953 | 398 | -58.24% |
| `keep_vl_lfs` | 1001 | 335 | -66.53% |
| `vlmax_lfs` | 953 | 335 | -64.85% |
| `outside_lfs` | 301 | 204 | -32.23% |
| `regular_load` | 658 | 390 | -40.73% |
| `regular_compute` | 549 | 523 | -4.74% |
| `regular_store` | 350 | 390 | +11.43% |

7 case MAPE 为 39.82%。compute-only 已较接近，而 load-only 和 load/FMA/store 明显偏乐观，
因此这组数据支持继续检查普通 vector load admission、VLSU 排序/完成以及 vset-to-VLSU
状态可见性；它不支持单独增加 FMA latency 来拟合完整 loop。
