# Raw benchmark summary

All values are computed from raw repetition rows, not Google Benchmark aggregate rows.

| Benchmark | Metric | Median | Min | Max | CV | PMU min running ratio |
|---|---|---:|---:|---:|---:|---:|
| `BM_StaticInventory/iterations:1` | `cpu_time` | 830 | 730 | 1220 | 17.96% | 1.0000 |
| `BM_PipelineWidth/4096/iterations:10` | `retired_ops_per_cycle` | 5.98575 | 5.8891 | 5.9873 | 0.56% | 1.0000 |
| `BM_VaddpsLatencyXmm/4096/iterations:5` | `latency_cycles` | 3.00196 | 3.00125 | 3.00271 | 0.02% | 1.0000 |
| `BM_VaddpsLatencyYmm/4096/iterations:5` | `latency_cycles` | 3.00191 | 3.00146 | 3.00391 | 0.02% | 1.0000 |
| `BM_VaddpsLatencyZmm/4096/iterations:5` | `latency_cycles` | 3.00162 | 3.00116 | 3.00335 | 0.02% | 1.0000 |
| `BM_VaddpsThroughputXmm/4096/iterations:5` | `issue_interval_cycles` | 0.501178 | 0.501071 | 0.502328 | 0.08% | 1.0000 |
| `BM_VaddpsThroughputYmm/4096/iterations:5` | `issue_interval_cycles` | 0.50129 | 0.500909 | 0.502427 | 0.11% | 1.0000 |
| `BM_VaddpsThroughputZmm/4096/iterations:5` | `issue_interval_cycles` | 1.00112 | 1.00099 | 1.00282 | 0.06% | 1.0000 |
| `BM_VfmaddpsThroughputYmm/4096/iterations:5` | `issue_interval_cycles` | 0.536853 | 0.536625 | 0.537524 | 0.06% | 1.0000 |
| `BM_VpadddThroughputYmm/4096/iterations:5` | `issue_interval_cycles` | 0.251118 | 0.250977 | 0.252538 | 0.20% | 1.0000 |
| `BM_VpermpsThroughputYmm/4096/iterations:5` | `issue_interval_cycles` | 0.50107 | 0.500903 | 0.502566 | 0.12% | 1.0000 |
| `BM_Vcvtps2dqThroughputYmm/4096/iterations:5` | `issue_interval_cycles` | 0.501191 | 0.500835 | 0.501799 | 0.06% | 1.0000 |
| `BM_ContentionAddFma/4096/iterations:5` | `mixed_instructions_per_cycle` | 1.99512 | 1.99119 | 1.99582 | 0.08% | 1.0000 |
| `BM_ContentionAddInteger/4096/iterations:5` | `mixed_instructions_per_cycle` | 2.58292 | 2.57077 | 2.5842 | 0.17% | 1.0000 |
| `BM_ContentionAddShuffle/4096/iterations:5` | `mixed_instructions_per_cycle` | 2.30582 | 2.26326 | 2.39171 | 2.27% | 1.0000 |
| `BM_ContentionAddConvert/4096/iterations:5` | `mixed_instructions_per_cycle` | 1.9958 | 1.99192 | 1.99687 | 0.08% | 1.0000 |
| `WindowCapacity/ROB/8/iterations:1` | `probe_tsc_cycles` | 342.642 | 335.723 | 389.673 | 4.95% | 1.0000 |
| `WindowCapacity/ROB/10/iterations:1` | `probe_tsc_cycles` | 351.702 | 348.71 | 353.163 | 0.40% | 1.0000 |
| `WindowCapacity/ROB/12/iterations:1` | `probe_tsc_cycles` | 354.63 | 348.275 | 440.355 | 8.32% | 1.0000 |
| `WindowCapacity/ROB/14/iterations:1` | `probe_tsc_cycles` | 355.022 | 352.28 | 406.007 | 4.93% | 1.0000 |
| `WindowCapacity/ROB/16/iterations:1` | `probe_tsc_cycles` | 359.85 | 354.022 | 367.767 | 1.39% | 1.0000 |
| `WindowCapacity/ROB/17/iterations:1` | `probe_tsc_cycles` | 362.887 | 354.06 | 370.96 | 1.50% | 1.0000 |
| `WindowCapacity/ROB/18/iterations:1` | `probe_tsc_cycles` | 367.188 | 363.19 | 368.423 | 0.56% | 1.0000 |
| `WindowCapacity/ROB/19/iterations:1` | `probe_tsc_cycles` | 563.107 | 557.23 | 589.237 | 1.78% | 1.0000 |
| `WindowCapacity/ROB/20/iterations:1` | `probe_tsc_cycles` | 568.192 | 563.883 | 621.04 | 3.29% | 1.0000 |
| `WindowCapacity/ROB/21/iterations:1` | `probe_tsc_cycles` | 568.077 | 563.685 | 604.66 | 2.29% | 1.0000 |
| `WindowCapacity/ROB/22/iterations:1` | `probe_tsc_cycles` | 574.062 | 561.51 | 580.497 | 0.99% | 1.0000 |
| `WindowCapacity/ROB/23/iterations:1` | `probe_tsc_cycles` | 576.288 | 570.955 | 614.928 | 2.45% | 1.0000 |
| `WindowCapacity/ROB/24/iterations:1` | `probe_tsc_cycles` | 582.99 | 573.692 | 617.225 | 2.30% | 1.0000 |
| `WindowCapacity/ROB/26/iterations:1` | `probe_tsc_cycles` | 580.178 | 566.16 | 584.918 | 1.03% | 1.0000 |
| `WindowCapacity/ROB/28/iterations:1` | `probe_tsc_cycles` | 579.185 | 570.245 | 631.825 | 3.37% | 1.0000 |
| `WindowCapacity/ROB/30/iterations:1` | `probe_tsc_cycles` | 583.64 | 582.49 | 628.71 | 2.66% | 1.0000 |
| `WindowCapacity/ROB/32/iterations:1` | `probe_tsc_cycles` | 592.88 | 586.735 | 634.077 | 2.50% | 1.0000 |
| `WindowCapacity/VectorScheduler/2/iterations:1` | `probe_tsc_cycles` | 324.618 | 318.483 | 686.465 | 33.95% | 1.0000 |
| `WindowCapacity/VectorScheduler/3/iterations:1` | `probe_tsc_cycles` | 327.875 | 314.605 | 333.32 | 1.84% | 1.0000 |
| `WindowCapacity/VectorScheduler/4/iterations:1` | `probe_tsc_cycles` | 323.283 | 305.738 | 330.36 | 2.33% | 1.0000 |
| `WindowCapacity/VectorScheduler/5/iterations:1` | `probe_tsc_cycles` | 334.788 | 327.923 | 349.103 | 1.83% | 1.0000 |
| `WindowCapacity/VectorScheduler/6/iterations:1` | `probe_tsc_cycles` | 342.805 | 340.535 | 349.293 | 0.85% | 1.0000 |
| `WindowCapacity/VectorScheduler/7/iterations:1` | `probe_tsc_cycles` | 341.335 | 338.262 | 348.652 | 1.07% | 1.0000 |
| `WindowCapacity/VectorScheduler/8/iterations:1` | `probe_tsc_cycles` | 353.423 | 343.15 | 378.887 | 3.04% | 1.0000 |
| `WindowCapacity/VectorScheduler/9/iterations:1` | `probe_tsc_cycles` | 352.723 | 349.022 | 360.335 | 1.04% | 1.0000 |
| `WindowCapacity/VectorScheduler/10/iterations:1` | `probe_tsc_cycles` | 355.812 | 349.32 | 360.07 | 0.86% | 1.0000 |
| `WindowCapacity/VectorScheduler/11/iterations:1` | `probe_tsc_cycles` | 354.762 | 349.975 | 359.928 | 1.14% | 1.0000 |
| `WindowCapacity/VectorScheduler/12/iterations:1` | `probe_tsc_cycles` | 362.483 | 357.37 | 406.165 | 4.32% | 1.0000 |
| `WindowCapacity/VectorScheduler/13/iterations:1` | `probe_tsc_cycles` | 361.562 | 357.368 | 399.86 | 3.82% | 1.0000 |
| `WindowCapacity/VectorScheduler/14/iterations:1` | `probe_tsc_cycles` | 363.647 | 362.04 | 370.382 | 0.76% | 1.0000 |
| `WindowCapacity/VectorScheduler/16/iterations:1` | `probe_tsc_cycles` | 565.225 | 560.215 | 602.925 | 2.44% | 1.0000 |
| `WindowCapacity/VectorScheduler/18/iterations:1` | `probe_tsc_cycles` | 580.56 | 564.133 | 768.375 | 11.22% | 1.0000 |
| `WindowCapacity/LoadQueue/2/iterations:1` | `probe_tsc_cycles` | 354.957 | 348.7 | 356.027 | 0.81% | 1.0000 |
| `WindowCapacity/LoadQueue/3/iterations:1` | `probe_tsc_cycles` | 355.087 | 348.467 | 358.962 | 0.95% | 1.0000 |
| `WindowCapacity/LoadQueue/4/iterations:1` | `probe_tsc_cycles` | 355.845 | 352.345 | 366.408 | 1.22% | 1.0000 |
| `WindowCapacity/LoadQueue/5/iterations:1` | `probe_tsc_cycles` | 358.582 | 355.43 | 360.96 | 0.50% | 1.0000 |
| `WindowCapacity/LoadQueue/6/iterations:1` | `probe_tsc_cycles` | 605.398 | 602.565 | 646.915 | 2.63% | 1.0000 |
| `WindowCapacity/LoadQueue/7/iterations:1` | `probe_tsc_cycles` | 604.595 | 601.63 | 647.322 | 2.47% | 1.0000 |
| `WindowCapacity/LoadQueue/8/iterations:1` | `probe_tsc_cycles` | 606.01 | 603.32 | 657.655 | 2.98% | 1.0000 |
| `WindowCapacity/LoadQueue/9/iterations:1` | `probe_tsc_cycles` | 607.41 | 604.87 | 652.433 | 2.63% | 1.0000 |
| `WindowCapacity/LoadQueue/10/iterations:1` | `probe_tsc_cycles` | 607.305 | 605.695 | 609.582 | 0.19% | 1.0000 |
| `WindowCapacity/LoadQueue/11/iterations:1` | `probe_tsc_cycles` | 607.058 | 602.125 | 608.617 | 0.34% | 1.0000 |
| `WindowCapacity/LoadQueue/12/iterations:1` | `probe_tsc_cycles` | 605.385 | 603.442 | 655.418 | 2.87% | 1.0000 |
| `WindowCapacity/LoadQueue/13/iterations:1` | `probe_tsc_cycles` | 606.14 | 602.615 | 656.43 | 2.92% | 1.0000 |
| `WindowCapacity/LoadQueue/14/iterations:1` | `probe_tsc_cycles` | 606.837 | 602.82 | 635.515 | 1.76% | 1.0000 |
| `WindowCapacity/LoadQueue/16/iterations:1` | `probe_tsc_cycles` | 606.33 | 602.525 | 654.077 | 2.77% | 1.0000 |
| `WindowCapacity/LoadQueue/18/iterations:1` | `probe_tsc_cycles` | 606.967 | 604.65 | 687.29 | 4.57% | 1.0000 |
| `WindowCapacity/StoreQueue/2/iterations:1` | `probe_tsc_cycles` | 353.865 | 350.377 | 409.39 | 5.47% | 1.0000 |
| `WindowCapacity/StoreQueue/3/iterations:1` | `probe_tsc_cycles` | 354.515 | 351.147 | 357.91 | 0.71% | 1.0000 |
| `WindowCapacity/StoreQueue/4/iterations:1` | `probe_tsc_cycles` | 356.712 | 351.485 | 361.777 | 0.90% | 1.0000 |
| `WindowCapacity/StoreQueue/5/iterations:1` | `probe_tsc_cycles` | 360.058 | 356.185 | 363.973 | 0.69% | 1.0000 |
| `WindowCapacity/StoreQueue/6/iterations:1` | `probe_tsc_cycles` | 359.595 | 356.46 | 397.632 | 3.75% | 1.0000 |
| `WindowCapacity/StoreQueue/7/iterations:1` | `probe_tsc_cycles` | 358.433 | 355.002 | 360.62 | 0.51% | 1.0000 |
| `WindowCapacity/StoreQueue/8/iterations:1` | `probe_tsc_cycles` | 364.483 | 357.41 | 370.312 | 1.09% | 1.0000 |
| `WindowCapacity/StoreQueue/9/iterations:1` | `probe_tsc_cycles` | 604.61 | 602.26 | 645.515 | 2.39% | 1.0000 |
| `WindowCapacity/StoreQueue/10/iterations:1` | `probe_tsc_cycles` | 604.283 | 603.253 | 665.695 | 3.49% | 1.0000 |
| `WindowCapacity/StoreQueue/11/iterations:1` | `probe_tsc_cycles` | 606.73 | 603.587 | 655.898 | 2.82% | 1.0000 |
| `WindowCapacity/StoreQueue/12/iterations:1` | `probe_tsc_cycles` | 607.217 | 603.895 | 664.27 | 3.29% | 1.0000 |
| `WindowCapacity/StoreQueue/13/iterations:1` | `probe_tsc_cycles` | 607.018 | 604.945 | 608.543 | 0.22% | 1.0000 |
| `WindowCapacity/StoreQueue/14/iterations:1` | `probe_tsc_cycles` | 605.495 | 602.247 | 662.79 | 3.29% | 1.0000 |
| `WindowCapacity/StoreQueue/16/iterations:1` | `probe_tsc_cycles` | 607.38 | 603.992 | 893.133 | 15.45% | 1.0000 |
| `WindowCapacity/StoreQueue/18/iterations:1` | `probe_tsc_cycles` | 604.965 | 603.56 | 611.72 | 0.43% | 1.0000 |
| `CacheLatency/L1D/16384/8388608/iterations:1` | `latency_cycles` | 4.00346 | 4.00227 | 4.00767 | 0.05% | 1.0000 |
| `CacheLatency/L2/262144/8388608/iterations:1` | `latency_cycles` | 14.1113 | 14.1043 | 14.1503 | 0.10% | 1.0000 |
| `CacheLatency/L3/4194304/2097152/iterations:1` | `latency_cycles` | 54.2378 | 53.4902 | 56.4881 | 1.64% | 1.0000 |
| `CacheLatency/DRAM/268435456/1048576/iterations:1` | `latency_cycles` | 373.105 | 369.241 | 381.705 | 1.04% | 1.0000 |
| `CacheBandwidth/Read/L1D/16384/131072/iterations:1` | `bytes_per_cycle` | 59.357 | 58.7401 | 59.7499 | 0.60% | 1.0000 |
| `CacheBandwidth/Write/L1D/16384/131072/iterations:1` | `bytes_per_cycle` | 31.9863 | 31.983 | 31.9899 | 0.01% | 1.0000 |
| `CacheBandwidth/Read/L2/262144/8192/iterations:1` | `bytes_per_cycle` | 31.9636 | 31.8279 | 31.9744 | 0.15% | 1.0000 |
| `CacheBandwidth/Write/L2/262144/8192/iterations:1` | `bytes_per_cycle` | 31.4033 | 31.3793 | 31.4443 | 0.07% | 1.0000 |
| `CacheBandwidth/Read/L3/16777216/128/iterations:1` | `bytes_per_cycle` | 24.1893 | 23.951 | 24.252 | 0.39% | 1.0000 |
| `CacheBandwidth/Write/L3/16777216/128/iterations:1` | `bytes_per_cycle` | 26.5254 | 26.2593 | 26.6748 | 0.48% | 1.0000 |
| `CacheBandwidth/Read/DRAM/268435456/4/iterations:1` | `bytes_per_cycle` | 9.27518 | 9.23597 | 9.32088 | 0.28% | 1.0000 |
| `CacheBandwidth/Write/DRAM/268435456/4/iterations:1` | `bytes_per_cycle` | 8.91668 | 8.84057 | 9.13167 | 0.96% | 1.0000 |
| `MemoryParallelism/L1D_miss_to_L2/262144/8388608/1/iterations:1` | `loads_per_cycle` | 0.0709127 | 0.0708825 | 0.0709844 | 0.05% | 1.0000 |
| `MemoryParallelism/L1D_miss_to_L2/262144/8388608/2/iterations:1` | `loads_per_cycle` | 0.140623 | 0.140548 | 0.140755 | 0.05% | 1.0000 |
| `MemoryParallelism/L1D_miss_to_L2/262144/8388608/4/iterations:1` | `loads_per_cycle` | 0.267248 | 0.266918 | 0.267576 | 0.07% | 1.0000 |
| `MemoryParallelism/L1D_miss_to_L2/262144/8388608/8/iterations:1` | `loads_per_cycle` | 0.472491 | 0.472394 | 0.473245 | 0.07% | 1.0000 |
| `MemoryParallelism/L1D_miss_to_L2/262144/8388608/12/iterations:1` | `loads_per_cycle` | 0.49118 | 0.490093 | 0.492266 | 0.14% | 1.0000 |
| `MemoryParallelism/L1D_miss_to_L2/262144/8388608/16/iterations:1` | `loads_per_cycle` | 0.496967 | 0.495717 | 0.497663 | 0.12% | 1.0000 |
| `MemoryParallelism/L1D_miss_to_L2/262144/8388608/24/iterations:1` | `loads_per_cycle` | 0.497079 | 0.495237 | 0.498161 | 0.19% | 1.0000 |
| `MemoryParallelism/L1D_miss_to_L2/262144/8388608/32/iterations:1` | `loads_per_cycle` | 0.497253 | 0.496568 | 0.499149 | 0.16% | 1.0000 |
| `MemoryParallelism/L1D_miss_to_L2/262144/8388608/48/iterations:1` | `loads_per_cycle` | 0.498337 | 0.497584 | 0.49871 | 0.08% | 1.0000 |
| `MemoryParallelism/L1D_miss_to_L2/262144/8388608/64/iterations:1` | `loads_per_cycle` | 0.497591 | 0.497024 | 0.498597 | 0.11% | 1.0000 |
| `MemoryParallelism/L2_miss_to_L3/4194304/2097152/1/iterations:1` | `loads_per_cycle` | 0.0175929 | 0.0174627 | 0.018195 | 1.56% | 1.0000 |
| `MemoryParallelism/L2_miss_to_L3/4194304/2097152/2/iterations:1` | `loads_per_cycle` | 0.0343228 | 0.0326101 | 0.0350302 | 2.13% | 1.0000 |
| `MemoryParallelism/L2_miss_to_L3/4194304/2097152/4/iterations:1` | `loads_per_cycle` | 0.0674121 | 0.0652098 | 0.0695803 | 2.16% | 1.0000 |
| `MemoryParallelism/L2_miss_to_L3/4194304/2097152/8/iterations:1` | `loads_per_cycle` | 0.129016 | 0.124295 | 0.131022 | 1.61% | 1.0000 |
| `MemoryParallelism/L2_miss_to_L3/4194304/2097152/12/iterations:1` | `loads_per_cycle` | 0.176677 | 0.168447 | 0.181585 | 2.41% | 1.0000 |
| `MemoryParallelism/L2_miss_to_L3/4194304/2097152/16/iterations:1` | `loads_per_cycle` | 0.229646 | 0.214279 | 0.233438 | 3.82% | 1.0000 |
| `MemoryParallelism/L2_miss_to_L3/4194304/2097152/24/iterations:1` | `loads_per_cycle` | 0.300089 | 0.271443 | 0.305435 | 3.71% | 1.0000 |
| `MemoryParallelism/L2_miss_to_L3/4194304/2097152/32/iterations:1` | `loads_per_cycle` | 0.304155 | 0.300595 | 0.307242 | 0.83% | 1.0000 |
| `MemoryParallelism/L2_miss_to_L3/4194304/2097152/48/iterations:1` | `loads_per_cycle` | 0.307677 | 0.282739 | 0.313109 | 3.69% | 1.0000 |
| `MemoryParallelism/L2_miss_to_L3/4194304/2097152/64/iterations:1` | `loads_per_cycle` | 0.306778 | 0.290059 | 0.314071 | 2.80% | 1.0000 |
| `MemoryParallelism/L3_miss_to_DRAM/268435456/1048576/1/iterations:1` | `loads_per_cycle` | 0.00268172 | 0.00263197 | 0.00279704 | 2.21% | 1.0000 |
| `MemoryParallelism/L3_miss_to_DRAM/268435456/1048576/2/iterations:1` | `loads_per_cycle` | 0.00582833 | 0.00555237 | 0.00589061 | 2.26% | 1.0000 |
| `MemoryParallelism/L3_miss_to_DRAM/268435456/1048576/4/iterations:1` | `loads_per_cycle` | 0.0108028 | 0.0105862 | 0.0109207 | 1.02% | 1.0000 |
| `MemoryParallelism/L3_miss_to_DRAM/268435456/1048576/8/iterations:1` | `loads_per_cycle` | 0.0204078 | 0.018524 | 0.0212463 | 4.21% | 1.0000 |
| `MemoryParallelism/L3_miss_to_DRAM/268435456/1048576/12/iterations:1` | `loads_per_cycle` | 0.0322245 | 0.0289834 | 0.0335175 | 4.39% | 1.0000 |
| `MemoryParallelism/L3_miss_to_DRAM/268435456/1048576/16/iterations:1` | `loads_per_cycle` | 0.0420109 | 0.0374386 | 0.0442341 | 5.63% | 1.0000 |
| `MemoryParallelism/L3_miss_to_DRAM/268435456/1048576/24/iterations:1` | `loads_per_cycle` | 0.0632191 | 0.0615007 | 0.065034 | 1.83% | 1.0000 |
| `MemoryParallelism/L3_miss_to_DRAM/268435456/1048576/32/iterations:1` | `loads_per_cycle` | 0.0730593 | 0.0574489 | 0.0753052 | 8.17% | 1.0000 |
| `MemoryParallelism/L3_miss_to_DRAM/268435456/1048576/48/iterations:1` | `loads_per_cycle` | 0.0717886 | 0.0631667 | 0.0784268 | 6.72% | 1.0000 |
| `MemoryParallelism/L3_miss_to_DRAM/268435456/1048576/64/iterations:1` | `loads_per_cycle` | 0.074158 | 0.0639709 | 0.0800568 | 9.12% | 1.0000 |

## Stability gate

- UNSTABLE: `BM_StaticInventory/iterations:1` / `cpu_time`, CV=17.96%
- UNSTABLE: `WindowCapacity/ROB/8/iterations:1` / `probe_tsc_cycles`, CV=4.95%
- UNSTABLE: `WindowCapacity/ROB/12/iterations:1` / `probe_tsc_cycles`, CV=8.32%
- UNSTABLE: `WindowCapacity/ROB/14/iterations:1` / `probe_tsc_cycles`, CV=4.93%
- UNSTABLE: `WindowCapacity/ROB/20/iterations:1` / `probe_tsc_cycles`, CV=3.29%
- UNSTABLE: `WindowCapacity/ROB/28/iterations:1` / `probe_tsc_cycles`, CV=3.37%
- UNSTABLE: `WindowCapacity/VectorScheduler/2/iterations:1` / `probe_tsc_cycles`, CV=33.95%
- UNSTABLE: `WindowCapacity/VectorScheduler/8/iterations:1` / `probe_tsc_cycles`, CV=3.04%
- UNSTABLE: `WindowCapacity/VectorScheduler/12/iterations:1` / `probe_tsc_cycles`, CV=4.32%
- UNSTABLE: `WindowCapacity/VectorScheduler/13/iterations:1` / `probe_tsc_cycles`, CV=3.82%
- UNSTABLE: `WindowCapacity/VectorScheduler/18/iterations:1` / `probe_tsc_cycles`, CV=11.22%
- UNSTABLE: `WindowCapacity/LoadQueue/18/iterations:1` / `probe_tsc_cycles`, CV=4.57%
- UNSTABLE: `WindowCapacity/StoreQueue/2/iterations:1` / `probe_tsc_cycles`, CV=5.47%
- UNSTABLE: `WindowCapacity/StoreQueue/6/iterations:1` / `probe_tsc_cycles`, CV=3.75%
- UNSTABLE: `WindowCapacity/StoreQueue/10/iterations:1` / `probe_tsc_cycles`, CV=3.49%
- UNSTABLE: `WindowCapacity/StoreQueue/12/iterations:1` / `probe_tsc_cycles`, CV=3.29%
- UNSTABLE: `WindowCapacity/StoreQueue/14/iterations:1` / `probe_tsc_cycles`, CV=3.29%
- UNSTABLE: `WindowCapacity/StoreQueue/16/iterations:1` / `probe_tsc_cycles`, CV=15.45%
- UNSTABLE: `MemoryParallelism/L2_miss_to_L3/4194304/2097152/16/iterations:1` / `loads_per_cycle`, CV=3.82%
- UNSTABLE: `MemoryParallelism/L2_miss_to_L3/4194304/2097152/24/iterations:1` / `loads_per_cycle`, CV=3.71%
- UNSTABLE: `MemoryParallelism/L2_miss_to_L3/4194304/2097152/48/iterations:1` / `loads_per_cycle`, CV=3.69%
- UNSTABLE: `MemoryParallelism/L3_miss_to_DRAM/268435456/1048576/8/iterations:1` / `loads_per_cycle`, CV=4.21%
- UNSTABLE: `MemoryParallelism/L3_miss_to_DRAM/268435456/1048576/12/iterations:1` / `loads_per_cycle`, CV=4.39%
- UNSTABLE: `MemoryParallelism/L3_miss_to_DRAM/268435456/1048576/16/iterations:1` / `loads_per_cycle`, CV=5.63%
- UNSTABLE: `MemoryParallelism/L3_miss_to_DRAM/268435456/1048576/32/iterations:1` / `loads_per_cycle`, CV=8.17%
- UNSTABLE: `MemoryParallelism/L3_miss_to_DRAM/268435456/1048576/48/iterations:1` / `loads_per_cycle`, CV=6.72%
- UNSTABLE: `MemoryParallelism/L3_miss_to_DRAM/268435456/1048576/64/iterations:1` / `loads_per_cycle`, CV=9.12%
