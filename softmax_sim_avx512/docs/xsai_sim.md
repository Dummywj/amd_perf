# XSAI 裸机 RTL 仿真

本文说明如何在不修改 `xsai-env` 源码的前提下，将本项目的 RVV kernel 编译为裸机
镜像，并在 NEMU 和单核 `DefaultMatrixConfig` RTL 上运行。所有接入源码位于
`softmax_sim_avx512/xsai/`，所有生成物位于
`softmax_sim_avx512/artifacts/xsai/`。

## 1. 固定环境

默认外部依赖为 `~/project/xsai-env`，可用 `XSAI_ENV_ROOT` 覆盖。脚本使用：

| 项目 | 固定值 |
|---|---|
| XSAI 配置 | 单核 `DefaultMatrixConfig` |
| 向量 ISA | `rv64gcv_zvl128b`，VLEN=128 |
| CUTE | 在 SoC 中实例化；应用不启用矩阵扩展、不包含 CUTE 指令 |
| L1D | 64 KiB、4-way、256 sets、64 B line |
| 测试规模 | N=512、1024、2048 |

构建和运行脚本会比较 XSAI、NEMU、nexus-am 在操作前后的 `git status`。已有用户修改
可以保留，但运行不得产生新的 tracked 或未忽略文件；外部仓库只允许产生正常的 ignored
build output。

## 2. 构建裸机镜像

```bash
cd softmax_sim_avx512
xsai/scripts/build_baremetal.sh
```

该脚本通过 nexus-am 的 `riscv64-xs` 启动代码和 klib 构建当前仓库中的 app。它直接
编译 `kernel/*/rvv/*.cpp`，不会复制 kernel 算法，也不会把 app 写入 nexus-am。输出为：

| 文件 | 内容 |
|---|---|
| `artifacts/xsai/build/*.elf` | 带符号的裸机 ELF |
| `artifacts/xsai/build/*.bin` | 从 `0x80000000` 加载的 RTL memory image |
| `artifacts/xsai/build/*.txt` | 完整反汇编 |
| `instruction_audit.json` | RVV 符号存在且无 CUTE/matrix mnemonic 的检查结果 |
| `l1_layout.json` | ELF 实际地址上的容量与 cache-set 占用检查 |
| `build_metadata.txt` | 源码提交、配置、ISA 和工具链 |

`MARCH` 不包含矩阵扩展，反汇编还必须包含全部 12 个 RVV kernel 符号和 RVV 指令，
且不能出现 `msettile*`、`mlae*`、`mfmacc*`、`macquire` 等 CUTE 指令。

## 3. 功能验证

RTL 之前必须先通过 NEMU：

```bash
xsai/scripts/run_nemu.sh
```

harness 对每个 kernel 的 N=512/1024/2048 做数值检查，并输出稳定的
`XSAI_META`、`XSAI_RESULT` 和 `XSAI_DONE` 标记。NEMU 的周期不是对齐数据，只用来
确认指令、裸机运行时和结果正确。它还执行 41 组 `XSAI_PARAM` 定向指令流，确认微基准
能运行，但同样不采用其 NEMU 周期。完整轻量验证可运行：

```bash
xsai/scripts/verify.sh
```

它依次执行结果解析/L1/指令审计单元测试、裸机构建和 NEMU 验证。

## 4. RTL 构建与运行

RTL 全量构建耗时较长，必须显式运行：

```bash
xsai/scripts/build_rtl.sh
```

该配置依赖 DRAMSim3 的 cosimulation 静态库。若 XSAI 已完成 RTL 生成、但最终链接
提示 `libdramsim3` 不存在，可在外部仓库的 ignored build 目录补齐依赖后重试；该操作
不会修改 `xsai-env` 的 tracked 源码：

```bash
xsai_dep_root=${XSAI_ENV_ROOT:-"$HOME/project/xsai-env"}
cmake -S "$xsai_dep_root/DRAMSim3" \
  -B "$xsai_dep_root/DRAMSim3/build" \
  -DCMAKE_BUILD_TYPE=Release -DCOSIM=ON
cmake --build "$xsai_dep_root/DRAMSim3/build" -j8
```

默认等价配置为：

```bash
make -C "$XSAI_ENV_ROOT/XSAI" emu -j8 \
  CONFIG=DefaultMatrixConfig NUM_CORES=1 \
  WITH_DRAMSIM3=1 WITH_CHISELDB=1 WITH_CONSTANTIN=0 EMU_THREADS=8
```

批量性能运行不启用波形，以免增加成本。已有 `build/emu` 后运行：

```bash
xsai/scripts/run_rtl.sh
```

基线命令为：

```bash
build/emu -i xsai-kernel-bench-riscv64-xs.bin \
  --diff ready-to-run/riscv64-nemu-interpreter-so \
  -C 500000000 --force-dump-result
```

验收必须同时满足：程序输出 `XSAI_DONE status=PASS`，RTL 输出 `HIT GOOD TRAP`，
日志中没有 `HIT BAD TRAP`、`ABORT` 或 difftest `mismatch`。默认宿主机超时为 4 小时；
可用 `RTL_TIMEOUT_SECONDS`、`RTL_MAX_CYCLES` 调整宿主机超时和 DUT 最大周期。

只有定位问题时才另行构建 `EMU_TRACE=fst` 版本，并用 `-b/-e --dump-wave` 截取窄
周期窗口；带波形版本不用于正式周期矩阵。

RTL 运行先执行依赖链、独立链和固定比例混合微基准，再执行完整 kernel。微基准覆盖
scalar ALU/FP add/FP div、`vsetvli`、FMA、向量 FP add、integer、conversion、reduction、
conversion+integer、FMA+integer、三类混合、L1 load 吞吐、load-use 和 store 吞吐。
另有 `vfmacc.vf` 依赖/吞吐、FP scalar broadcast、integer scalar 和 immediate
broadcast 五组指令流，用于区分 I2V/F2V scalar-preparation 通路与真正的向量计算
资源。每组固定 64 次迭代、每次展开 8 或 16 个目标操作，另保留 16 个 `nop` 的循环
基线；结果必须结合反汇编和循环基线解释，不能把 `cycles/op` 直接等同于物理端口数。

为区分物理寄存器重命名与显式 RAW 依赖，新增三组相同逻辑目的寄存器测试：

| case | 每轮指令流 | 对照与可识别量 |
|---|---|---|
| `fp_add_same_vd` | 16 条 `vfadd.vv v0, v16, v17` | 对照 `fp_add_throughput` 与 `fp_add_dependency` |
| `conversion_same_vd` | 16 条 `vfcvt.rtz.x.f.v v0, v16` | 对照 `conversion_throughput` 与 `conversion_dependency` |
| `integer_same_vd` | 16 条 `vadd.vv v0, v16, v17` | 对照 `integer_throughput` 与 `integer_dependency` |

三组测试的源寄存器固定，`vd` 不作为源，因此不存在显式 RAW。若它们明显慢于 distinct-vd
吞吐流，只能说明目的重命名、写回或 admission 存在额外顺序约束，不能直接把差值解释为
执行单元 latency。反汇编审计会严格检查每组恰好包含 16 条预期指令且全部写 `v0`。

为定位 kernel 中 load/store 与跨迭代重叠过于乐观的问题，新增以下成对测试：

| case | 归一化单位 | 对照与可识别量 |
|---|---|---|
| `load_stream_throughput` | 1 次 load | 连续读取 2 KiB L1 区域，对照固定 64 B 区域的 `load_throughput` |
| `store_stream_throughput` | 1 次 store | 连续写入 2 KiB L1 区域，对照固定 64 B 区域的 `store_throughput` |
| `load_same_vd` | 1 次 load | 与 `load_throughput` 比较，识别同一架构 `vd` 重复写入是否引入额外顺序约束 |
| `load_alu_dependency` | 1 个 load+ALU pair | 识别 load 数据可用到 dependent vector integer ALU 的有效间隔 |
| `load_fma_dependency` | 1 个 load+FMA pair | 识别 load 数据可用到 dependent vector FMA 的有效间隔 |
| `load_fma_iteration` | 1 次逻辑迭代 | 给出每轮一个 load+FMA、紧随标量循环控制的跨迭代基线 |
| `load_fma_store_iteration` | 1 次逻辑迭代 | 与无 store 基线比较，估计 store 队列/完成规则对下一轮 admission 的增量约束 |
| `vset_rd_dependency` | 1 条 `vsetvli` | 与 `vset_throughput` 比较，识别 `rd` 被下一条 `vsetvli` 作为 AVL 使用时的依赖间隔 |

五组 memory-dependency 流统一使用普通向量目的寄存器 `v8`；不使用 `v0`，因为 XSAI
对 `v0` 有独立的 mask/V0 寄存器通路，不能把该特殊路径的延迟外推到普通向量算术。
两组 stream case 每轮顺序访问 16 个 16 B chunk，覆盖 256 B；下一轮 offset 加 256 后
与 2047 按位与，在已预热的 2 KiB 区域中轮转。它们用于暴露 cache line/set 轮转时的
VLSU 吞吐，不能用 NEMU 周期校准。`load_same_vd` 和两组 load dependency case 在循环
内分别展开 16 或 8 个归一化单位；两组 iteration case 则有意每轮只保留一个逻辑迭代，
以暴露分支边界上的重叠行为。解析器按 case 契约检查 category、unit、iterations 和
operations，避免把 pair 或 iteration 误当成单条指令。iteration 两组的差值是有效
store/下一轮约束，不等同于单个 store 的物理完成延迟。

## 5. 计时和 L1 约束

每个 case 先执行一次 kernel 预热输入、输出、指令和分支状态，再连续采集 5 个样本。
计时区只包含一次 kernel 调用，边界使用 `fence rw,rw` 和 `mcycle`；同样边界下的空
函数周期作为计时开销并从 raw cycles 中扣除。整段 RTL 的 `cycleCnt` 包含启动、打印
和验证，只用于运行完整性检查，不能替代 kernel-region cycles。

每个 kernel 和微基准样本还在 timed region 前后读取 HPM。当前审计汇总三个 load
pipe 的 L1D load miss、三个 load pipe 的 DTLB load miss，并检查 CUTE active
cycle、CUTE retire 和 CUTE memory request 均为 0。HPM 快照位于 `mcycle` 计时之外，
避免计数器读取本身进入 kernel 周期；任一 CUTE 指标非零时，解析器拒绝整次运行。

输入使用一个连续、64 B 对齐的 `3N` arena，输出使用一个连续、64 B 对齐的 `N`
arena。最坏的 Pointer AGU/N=2048 为 3 个输入加 1 个输出，共 32 KiB，占 L1D 的
50%。构建阶段按 ELF 最终地址检查每个 cache set 最多使用 3 个 way，为栈和运行时
保留至少一个 way。因此 N=512/1024/2048 均可进入 L1 对齐；若后续 RTL 的 timed
region 出现 demand refill 或 TLB miss，则该样本仍须标为 `cache-contaminated`，不能
用于拟合。

## 6. 结果文件

`run_nemu.sh` 和 `run_rtl.sh` 调用同一解析器，分别在 `artifacts/xsai/nemu/` 和
`artifacts/xsai/rtl/` 生成：

| 文件 | 内容 |
|---|---|
| `*.log` | 不裁剪的原始输出 |
| `samples.csv` | raw、空框架、扣除后周期、checksum、正确性和逐样本 HPM |
| `summary.csv` | 每个 kernel/N 的 clean 样本数、中位数、范围、cycles/element 和拟合资格 |
| `profile_samples.csv` | 每组参数微基准的原始/扣除后周期和逐样本 HPM |
| `profile_summary.csv` | 微基准 clean 样本统计、cycles/op、op/cycle 和拟合资格 |
| `result_metadata.json` | harness 格式、ISA、VLEN、样本数和结束状态 |
| `run_metadata.txt` | XSAI、NEMU、nexus-am、本项目提交和运行配置 |

正式对齐以 `summary.csv` 的中位数为主，同时保留所有 raw samples。出现偏差时先查看
反汇编、difftest、L1 miss/refill 和执行资源 stall 证据，不能直接增加按 kernel 或 N
生效的补偿常数。只要一组中存在 clean 样本，中位数和范围只使用 clean 样本；若整组
均被污染，则仍输出仅供诊断的统计值，并以 `fit_status=CACHE_CONTAMINATED` 排除拟合。

## 7. 常见失败

| 现象 | 处理 |
|---|---|
| 找不到 RVV 工具链 | 设置 `RVV_TOOLCHAIN_PREFIX`；默认使用 `riscv64-linux-gnu-` |
| 找不到外部仓库 | 设置 `XSAI_ENV_ROOT`，或分别设置 `AM_HOME/NOOP_HOME/NEMU_HOME` |
| 缺少 `libdramsim3` | 按第 4 节在 ignored `DRAMSim3/build` 中启用 `COSIM` 构建依赖，再重试 |
| 指令审计失败 | 检查 `MARCH` 和反汇编；不得通过忽略规则绕过 CUTE 指令 |
| NEMU illegal instruction | 先确认 mstatus.VS、`rv64gcv_zvl128b` 和 NEMU RVV 配置 |
| RTL 超时 | 先确认日志仍在提交，再调整 timeout/max cycles；不要直接关闭 difftest |
| 外部目录变化 | 恢复或审核运行中新产生的源码文件；ignored build output 不触发此检查 |
| 数值失败 | 在 NEMU 修复后再运行 RTL，不能把功能错误当作性能误差 |
