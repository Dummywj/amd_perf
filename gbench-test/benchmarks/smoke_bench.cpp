#include <benchmark/benchmark.h>

#include "perf_counter.h"

#include <cstdint>
#include <cstddef>
#include <vector>

static void BM_Fp32FmaSmoke(benchmark::State& state) {
  const std::size_t n = static_cast<std::size_t>(state.range(0));
  std::vector<float> a(n, 1.25f);
  std::vector<float> b(n, 2.0f);
  std::vector<float> c(n, 0.5f);
  std::vector<float> out(n);

  auto cycles = PerfCounter::OpenUserCoreCycles();
  if (!cycles.ok()) {
    state.SkipWithError(cycles.error().c_str());
    return;
  }

  std::string error;
  if (!cycles.Start(&error)) {
    state.SkipWithError(error.c_str());
    return;
  }

  for (auto _ : state) {
    for (std::size_t i = 0; i < n; ++i) {
      out[i] = a[i] * b[i] + c[i];
    }
    benchmark::DoNotOptimize(out.data());
    benchmark::ClobberMemory();
  }

  std::uint64_t core_cycles = 0;
  if (!cycles.Stop(&core_cycles, &error)) {
    state.SkipWithError(error.c_str());
    return;
  }

  const auto elements = state.iterations() * static_cast<int64_t>(n);
  state.SetItemsProcessed(elements);
  state.counters["core_cycles"] =
      benchmark::Counter(static_cast<double>(core_cycles));
  state.counters["elem/core_cycle"] =
      static_cast<double>(elements) / static_cast<double>(core_cycles);
}

BENCHMARK(BM_Fp32FmaSmoke)
    ->Arg(1024)
    ->Arg(16384)
    ->Arg(262144);

BENCHMARK_MAIN();
