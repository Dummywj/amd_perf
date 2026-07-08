# 当前运行环境 CPU 信息

生成时间：2026-07-08

## 基本信息

| 项目 | 值 |
| --- | --- |
| 架构 | x86_64 |
| CPU 厂商 | AuthenticAMD |
| CPU 型号 | AMD EPYC 9684X 96-Core Processor |
| Socket 数 | 2 |
| 每 Socket 核心数 | 96 |
| 每核心线程数 | 2 |
| 逻辑 CPU 总数 | 384 |
| 在线 CPU | 0-383 |
| NUMA 节点数 | 2 |
| 操作系统 | Linux node042.bosccluster.com 6.8.0-111-generic |

## 频率信息

| 项目 | 值 |
| --- | --- |
| Boost | enabled |
| 当前 scaling 比例 | 73% |
| 最高频率 | 3716.8860 MHz |
| 最低频率 | 1500.0000 MHz |
| BogoMIPS | 5100.35 |

## 缓存信息

| 缓存 | 容量 |
| --- | --- |
| L1d | 6 MiB，共 192 个实例 |
| L1i | 6 MiB，共 192 个实例 |
| L2 | 192 MiB，共 192 个实例 |
| L3 | 2.3 GiB，共 24 个实例 |

## NUMA 拓扑

| NUMA 节点 | CPU 列表 |
| --- | --- |
| node0 | 0-95,192-287 |
| node1 | 96-191,288-383 |

## 与本项目相关的指令集

本机支持以下与长向量和浮点测试相关的指令集：

- `fma`
- `avx`
- `avx2`
- `avx512f`
- `avx512dq`
- `avx512cd`
- `avx512bw`
- `avx512vl`
- `avx512_bf16`
- `avx512_vnni`
- `avx512vbmi`
- `avx512_vbmi2`
- `f16c`

结论：当前机器适合测试 FP32 长向量性能，也具备 BF16 指令支持，可优先考虑基于 AVX-512 BF16 的实现路径。

