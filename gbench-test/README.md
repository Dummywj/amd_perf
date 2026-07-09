AMD 向量处理单元测试
测试框架：Google Benchmark

| Benchmark 名称 | 测试说明 |
| --- | --- |
| `BM_Fp32FmaSmoke` | FP32 FMA 冒烟测试，执行 `out[i] = a[i] * b[i] + c[i]`，用于验证 Google Benchmark、AVX-512 编译和 perf cycle 计数链路是否正常。 |
| `BM_Fp32FmaRegisterPeak` | FP32 AVX-512 FMA 寄存器峰值测试，使用 16 个独立 ZMM accumulator，尽量减少内存访问影响，观察单核 FMA 吞吐上限。 |
| `BM_Fp32FmaLengthSweep` | 高计算密度 FP32 FMA 长度扫描测试，单数组 load/store，每个元素在寄存器中执行多轮 FMA，用于观察较高算术强度下工作集增大对吞吐的影响。 |
| `BM_Fp32FmaLengthSweepOnce` | 单次 FMA stream 长度扫描测试，四数组 `out[i] = a[i] * b[i] + c[i]`，每个元素只做一次 FMA，用于观察 L1/L2/L3/内存层级对低计算密度 FMA 的影响。 |
