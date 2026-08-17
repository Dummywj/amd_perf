# Raw benchmark summary

All values are computed from raw repetition rows, not Google Benchmark aggregate rows.

| Benchmark | Metric | Median | Min | Max | CV | PMU min running ratio |
|---|---|---:|---:|---:|---:|---:|
| `BM_VfmaddpsThroughputZmm/4096/iterations:5` | `issue_interval_cycles` | 1.00208 | 1.00124 | 1.01567 | 0.48% | 1.0000 |
| `BM_VpadddThroughputZmm/4096/iterations:5` | `issue_interval_cycles` | 0.501662 | 0.501171 | 0.502397 | 0.08% | 1.0000 |
| `BM_Vcvttps2dqThroughputZmm/4096/iterations:5` | `issue_interval_cycles` | 1.00204 | 1.00125 | 1.00335 | 0.07% | 1.0000 |
| `BM_ContentionZmmConvertInteger1To1/4096/iterations:5` | `mixed_instructions_per_cycle` | 1.99245 | 1.98657 | 1.99535 | 0.14% | 1.0000 |
| `BM_ContentionZmmFmaInteger1To1/4096/iterations:5` | `mixed_instructions_per_cycle` | 1.51607 | 1.47866 | 1.56346 | 1.73% | 1.0000 |
| `BM_ContentionZmmConvertFmaInteger1To1To2/4096/iterations:5` | `mixed_instructions_per_cycle` | 1.99277 | 1.99019 | 1.99547 | 0.09% | 1.0000 |

## ZMM contention comparison

`C:F:I` is the static conversion:FMA:integer instruction ratio. Each class cell is `observed IPC / standalone IPC utilization`. Aggregate normalized demand is the sum of those utilizations; a value above 1 means the classes made simultaneous progress beyond one fully shared standalone bottleneck.

| Benchmark | C:F:I | Total IPC | Conversion IPC / util | FMA IPC / util | Integer IPC / util | Aggregate normalized demand | Static source operands/cycle | Retired ZMM / target |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| `BM_ContentionZmmConvertInteger1To1/4096/iterations:5` | `1:0:1` | 1.99245 | 0.996227 / 99.83% | - | 0.996227 / 49.98% | 1.4980 | 2.98868 | 1.00001 |
| `BM_ContentionZmmFmaInteger1To1/4096/iterations:5` | `0:1:1` | 1.51607 | - | 0.758033 / 75.96% | 0.758033 / 38.03% | 1.1399 | 3.79017 | 1.00004 |
| `BM_ContentionZmmConvertFmaInteger1To1To2/4096/iterations:5` | `1:1:2` | 1.99277 | 0.498192 / 49.92% | 0.498192 / 49.92% | 0.996383 / 49.98% | 1.4983 | 3.98553 | 1.00002 |

## Stability gate

All primary metrics passed CV <= 3% and PMU running ratio >= 0.95; all ZMM mixes passed retired-ZMM/target in [0.98, 1.02] and have all standalone baselines.
