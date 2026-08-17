# 通用 Uop 事件驱动模拟器首轮结果

> 状态：实现完成，等待审核；本报告未将 softmax 误差反向写入既有校准参数。

## 1. 实现范围

当前实现形成如下执行链：

```text
x86 汇编
  -> 动态控制流展开、寄存器/flags/内存 RAW 依赖
  -> 跨 ISA semantic uop
  -> Zen 4 profile 等效 execution uop
  -> 顺序或乱序事件驱动后端
  -> 周期统计、事件日志、Perfetto、DOT、文本 timeline
```

模拟器核心只读取 `BoundTrace`、通用 uop、resource 和 profile 参数，不根据
x86/RVV mnemonic 做调度判断。当前只有 x86 动态前端；RVV 在获得具体微架构
profile 后可接入相同后端。

已实现：

- `--execution-model out_of_order|in_order`，默认乱序；
- dispatch/retire、ROB=320、vector scheduler=64、LQ=44、SQ=68；
- RAW DAG、oldest-ready issue、resource capacity/occupancy/interval 和 issue domain；
- 512-bit 到两个 256-bit execution part 的等效拆分；
- hot-L1、hot-capacity、cold 三种初始状态和确定性 set-associative LRU；
- L1/L2/L3/DRAM latency、分方向 bandwidth、miss 并发限制和同 line miss 合并；
- profile/schema/assembly/recipe 哈希、稳定 ID 和可复现事件输出。
- ISA recipe 引用的 semantic kind 必须存在于唯一的 `uops/uop_kinds.yaml`，未知
  kind 在动态展开前硬错误，trace 记录 catalog 哈希。

## 2. Profile 与 Recipe

本节记录首版实现时 `profile.schema.json` 升级到 version 3 的变更；当前 schema
已在加权 issue-domain 支持中升级到 version 4。当时新增：

- `issue_domains`：表达 add/FMA/conversion 的共享发射资格；
- `scalar_control_fit`：集中存放 scalar/control 有效时序，不在代码中放默认常数；
- recipe uop 的 `issue_domains` 绑定。

原有已审核数值参数保持不变，包括 ROB 320、vector scheduler 64、LQ 44、SQ 68、
store-data capacity 1/32 B per cycle、所有 memory 参数，以及原 `vaddps` recipe。
`vaddps` 仅新增 issue-domain 绑定，没有改变其 latency、interval、occupancy 或拆分值。

当前 softmax 在 `N=256` 有 44 种动态 opcode form：31 种向量/访存 form 使用显式
profile recipe，共 418 条动态指令；其余 13 种 form 共 155 条，仅属于
scalar/control fallback。fallback 数值来自 LLVM znver4 调度模型审计，标记为
provisional effective value，不宣称为物理 pipe 或物理 uop 结构。

## 3. 真机测量口径

- 平台：AMD EPYC 9684X，CPU 8，NUMA node 0；SMT sibling 为 CPU 200；
- 编译器：GCC 13.3，与汇编 artifact 使用同一 kernel 和 AVX-512 flags；
- PMU：user-only core cycles，并记录 instructions、branches、cache misses；
- 每个 N 随机交错运行 7 次，所有 PMU running ratio 均为 1.0；测量期间
  SMT sibling CPU 200 的 `/proc/stat` busy 比例为 1.064%，低于 5% 准入线；
- 主比较值：`LFENCE` 序列化调用减去同结构空函数基线后的 median cycles；
- profile SHA-256：`b23862505017f4ad7317a906ce6bcc1e191b8f11647620293787050a2dc73c31`。

原始测量、环境、反汇编和统计在
`kernel/softmax/artifacts/x86/cycles-20260805-final/`。

## 4. 周期对比

| N | cache 初态 | 分类 | 真机 | OOO 模拟 | 相对误差 | in-order 模拟 |
|---:|:---|:---|---:|---:|---:|---:|
| 16 | hot-L1 | 诊断 | 117.04 | 121 | +3.38% | 168 |
| 32 | hot-L1 | 诊断 | 122.36 | 128 | +4.61% | 243 |
| 64 | hot-L1 | 诊断 | 160.02 | 142 | -11.26% | 393 |
| 128 | hot-L1 | 稳态 | 224.20 | 208 | -7.23% | 693 |
| 256 | hot-L1 | 稳态 | 353.32 | 329 | -6.88% | 1293 |
| 512 | hot-L1 | 稳态 | 605.10 | 569 | -5.97% | 2493 |
| 1024 | hot-L1 | 稳态 | 1114.92 | 1049 | -5.91% | 4893 |
| 2048 | hot-L1 | 稳态 | 2137.69 | 2009 | -6.02% | 9693 |
| 4096 | hot-capacity | L1 边界 | 4201.33 | 3939 | -6.24% | 21873 |

结论：`N=128..2048` 的稳态 hot-L1 点全部满足 10% 阈值，最大绝对误差
7.23%。`N=64` 是小规模诊断点，不纳入硬阈值。`N=4096` 的输入、输出和常量
共 32832 bytes，不能诚实地声明为 32 KiB L1 resident，因此使用
hot-capacity，初始驻留 L2；模拟命中统计为 L1 779、L2 513 个访问。

模拟点没有落入很窄的真机 p10-p90 区间。这是确定性有效模型与低波动 PMU
测量之间的预期差异；首轮验收依据是计划约定的相对误差阈值，而非亚周期置信区间。

## 5. 顺序与乱序对照

两种模式使用完全相同的 trace、profile、cache 和执行资源，只改变 issue policy。
以 `N=256` 为例，乱序为 329 cycles，严格顺序为 1293 cycles。差异来自乱序后端
允许 younger ready uop 绕过 dependency/resource 未就绪的 older uop，不是额外拟合项。

`N=256` 乱序模式的纯 RAW 关键路径为 193 cycles，峰值为 ROB 199、vector
scheduler 64、LQ 23、SQ 21；所有值均未
超过 profile 容量。该点最主要的 dispatch backpressure 是 vector scheduler full。
结果同时报告不含资源冲突的纯 RAW dependency critical path，便于区分依赖链与
resource/queue backpressure；它不是完整总周期分解。

## 6. 调度图

代表性双模式产物位于：

- `artifacts/schedules/zen4-n256-ooo/`
- `artifacts/schedules/zen4-n256-in-order/`

每个目录包含：

- `schedule_perfetto.json`：拖入 `https://ui.perfetto.dev/` 查看 instruction、resource、
  dependency flow 和 queue counter；
- `dependencies.dot`：使用 `dot -Tsvg dependencies.dot -o dependencies.svg`；
- `timeline.txt`：适合直接代码审核；
- `schedule_events.jsonl`：结构化事件流，包含 dispatch/ready/issue/complete/retire；
- `dynamic_trace.json` 和 `result.json`：完整依赖、绑定和统计结果。

当前机器未安装 Graphviz，因此已验证 DOT 内容但未在仓库生成 SVG；Perfetto JSON
已通过 JSON 解析和跨视图 ID 一致性测试。

## 7. 复现命令

```bash
python3 -m pip install -r softmax_sim_avx512/requirements.txt

softmax_sim_avx512/kernel/softmax/scripts/run_x86_cycles.sh \
  softmax_sim_avx512/kernel/softmax/artifacts/x86/cycles-20260805-final

python3 softmax_sim_avx512/kernel/softmax/scripts/compare_cycles.py \
  softmax_sim_avx512/kernel/softmax/workloads/softmax.yaml \
  softmax_sim_avx512/artifacts/reports/zen4-20260805-final

PYTHONPATH=softmax_sim_avx512 python3 -m unittest discover \
  -s softmax_sim_avx512/tests -v
```

系统 `/usr/bin/python3` 已具有 PyYAML/jsonschema；当前用户默认的 Miniforge
Python 未安装 PyYAML，需要按 requirements 安装或使用系统 Python。

## 8. 限制与下一阶段

- scalar/control fallback 仍是 provisional，后续应使用独立微基准训练，并保留
  softmax N 点作验证集；本轮没有用 softmax 误差修改这些数值。
- cache 模型是 deterministic inclusive LRU、write-allocate、无 TLB/预取器的有效模型；
  L2/L3/DRAM 尚未用独立 kernel 做周期精度验收，cold 结果只验证层级趋势。
- 不模拟 branch misprediction、frontend cache、SMT、操作系统抢占和频率。
- event blocker 统计是调度器观察次数，不是互斥的 stall-cycle 分解；总周期和资源
  时间线是主结果。
- RVV 已有功能/Spike 验证，但缺少目标 RVV 微架构 profile，因此本报告不输出 RVV
  性能周期。接入 RVV 时不应修改 `src/simulator` 的调度逻辑。
