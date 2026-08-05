# Raw benchmark summary

All values are computed from raw repetition rows, not Google Benchmark aggregate rows.

| Benchmark | Metric | Median | Min | Max | CV | PMU min running ratio |
|---|---|---:|---:|---:|---:|---:|
| `CacheBandwidth/ReadYmm/L1D/16384/131072/iterations:1` | `bytes_per_cycle` | 62.2338 | 61.2351 | 62.4955 | 0.68% | 1.0000 |
| `CacheBandwidth/WriteYmm/L1D/16384/131072/iterations:1` | `bytes_per_cycle` | 31.9868 | 31.4986 | 31.9886 | 0.53% | 1.0000 |
| `CacheBandwidth/MixedYmm/L1D/iterations:1` | `bytes_per_cycle` | 90.0984 | 88.9629 | 90.4861 | 0.56% | 1.0000 |

## Stability gate

All primary metrics passed CV <= 3% and PMU running ratio >= 0.95.
