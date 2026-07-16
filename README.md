# AMD 向量算子性能测试

使用 Google Benchmark 测试 AMD CPU 上 Softmax、FMA、Reduce、Gather 和
Scatter 的 FP32/BF16 性能，主要输出 `elem/core_cycle`、
`flop/core_cycle` 和吞吐曲线。

## 首次下载与使用

### 1. 准备环境

需要 Linux x86-64、支持 AVX-512 的 AMD CPU，以及以下工具：

```text
Git、GCC/G++、CMake >= 3.20、Make、Python 3、numactl、binutils
```

BF16 FMA 还要求 CPU flags 中包含 `avx512_bf16`。性能计数依赖
`perf_event_open` 权限。

### 2. 下载代码和依赖

```bash
git clone --recurse-submodules https://github.com/Dummywj/amd_perf.git
cd amd_perf

git clone https://github.com/shibatch/sleef.git third_party/sleef
git -C third_party/sleef checkout 7623d6cfa2712462880fa63a4d0f0b5f775d1a83
git -C third_party/sleef submodule update --init --recursive
```

### 3. 冒烟验证

```bash
make
```

该命令编译并运行一个简短的 FP32 FMA 测试。构建产物和结果默认位于
`gbench-test/build` 与 `gbench-test/results`。

### 4. 构建全部算子

```bash
make -C gbench-test ops-build \
  BUILD_DIR=build-ops-release CONFIG=Release JOBS=16
```

### 5. 单独运行一个算子

先查看可用测试项：

```bash
make -C gbench-test list-payloads
```

然后指定算子、CPU、NUMA 节点和新的结果目录：

```bash
make -C gbench-test run \
  PAYLOAD=fma-bf16 \
  BUILD_DIR=build-ops-release JOBS=16 \
  CPU=8 NUMA_NODE=0 \
  RESULTS_DIR=results/fma_bf16_$(date +%Y%m%d-%H%M%S)
```

结果目录中会生成 JSON、Markdown 和 SVG。首次正式运行前请根据服务器的
`lscpu` 输出调整 `CPU` 和 `NUMA_NODE`，并尽量保持目标核心空闲。

完整测试配置、正确性门禁和其他运行方式见
[gbench-test/README.md](gbench-test/README.md)。
