#include <benchmark/benchmark.h>

#include "perf_counter.h"

#include <immintrin.h>

#include <cstddef>
#include <cstdint>
#include <string>

namespace {

constexpr int kFp32LanesPerZmm = 16;
constexpr int kIndependentAccumulators = 16;

#if defined(__GNUC__) || defined(__clang__)
#define AMD_PERF_NOINLINE __attribute__((noinline))
#else
#define AMD_PERF_NOINLINE
#endif

#define FMA_STEP(index) acc##index = _mm512_fmadd_ps(acc##index, mul, add)
#define KEEP_ACCUMULATORS_LIVE()                                             \
  do {                                                                        \
    asm volatile(""                                                           \
                 : "+v"(acc0), "+v"(acc1), "+v"(acc2), "+v"(acc3),           \
                   "+v"(acc4), "+v"(acc5), "+v"(acc6), "+v"(acc7));          \
    asm volatile(""                                                           \
                 : "+v"(acc8), "+v"(acc9), "+v"(acc10), "+v"(acc11),         \
                   "+v"(acc12), "+v"(acc13), "+v"(acc14), "+v"(acc15));      \
  } while (0)

AMD_PERF_NOINLINE float RunFp32FmaRegisterPeakKernel(int repeats) {
  const __m512 mul = _mm512_set1_ps(0.99999994f);
  const __m512 add = _mm512_set1_ps(0.000001f);

  __m512 acc0 = _mm512_set1_ps(1.00f);
  __m512 acc1 = _mm512_set1_ps(1.01f);
  __m512 acc2 = _mm512_set1_ps(1.02f);
  __m512 acc3 = _mm512_set1_ps(1.03f);
  __m512 acc4 = _mm512_set1_ps(1.04f);
  __m512 acc5 = _mm512_set1_ps(1.05f);
  __m512 acc6 = _mm512_set1_ps(1.06f);
  __m512 acc7 = _mm512_set1_ps(1.07f);
  __m512 acc8 = _mm512_set1_ps(1.08f);
  __m512 acc9 = _mm512_set1_ps(1.09f);
  __m512 acc10 = _mm512_set1_ps(1.10f);
  __m512 acc11 = _mm512_set1_ps(1.11f);
  __m512 acc12 = _mm512_set1_ps(1.12f);
  __m512 acc13 = _mm512_set1_ps(1.13f);
  __m512 acc14 = _mm512_set1_ps(1.14f);
  __m512 acc15 = _mm512_set1_ps(1.15f);

  for (int r = 0; r < repeats; ++r) {
    FMA_STEP(0);
    FMA_STEP(1);
    FMA_STEP(2);
    FMA_STEP(3);
    FMA_STEP(4);
    FMA_STEP(5);
    FMA_STEP(6);
    FMA_STEP(7);
    FMA_STEP(8);
    FMA_STEP(9);
    FMA_STEP(10);
    FMA_STEP(11);
    FMA_STEP(12);
    FMA_STEP(13);
    FMA_STEP(14);
    FMA_STEP(15);
    KEEP_ACCUMULATORS_LIVE();
  }

  __m512 sum0 = _mm512_add_ps(acc0, acc1);
  __m512 sum1 = _mm512_add_ps(acc2, acc3);
  __m512 sum2 = _mm512_add_ps(acc4, acc5);
  __m512 sum3 = _mm512_add_ps(acc6, acc7);
  __m512 sum4 = _mm512_add_ps(acc8, acc9);
  __m512 sum5 = _mm512_add_ps(acc10, acc11);
  __m512 sum6 = _mm512_add_ps(acc12, acc13);
  __m512 sum7 = _mm512_add_ps(acc14, acc15);
  sum0 = _mm512_add_ps(sum0, sum1);
  sum2 = _mm512_add_ps(sum2, sum3);
  sum4 = _mm512_add_ps(sum4, sum5);
  sum6 = _mm512_add_ps(sum6, sum7);
  sum0 = _mm512_add_ps(sum0, sum2);
  sum4 = _mm512_add_ps(sum4, sum6);
  sum0 = _mm512_add_ps(sum0, sum4);
  return _mm_cvtss_f32(_mm512_castps512_ps128(sum0));
}

static void BM_Fp32FmaRegisterPeak(benchmark::State& state) {
  const int repeats = static_cast<int>(state.range(0));

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

  float sink = 0.0f;
  for (auto _ : state) {
    sink += RunFp32FmaRegisterPeakKernel(repeats);
  }

  benchmark::DoNotOptimize(sink);

  std::uint64_t core_cycles = 0;
  if (!cycles.Stop(&core_cycles, &error)) {
    state.SkipWithError(error.c_str());
    return;
  }

  const auto vector_fmas =
      state.iterations() * static_cast<int64_t>(repeats) *
      kIndependentAccumulators;
  const auto elements = vector_fmas * kFp32LanesPerZmm;
  const auto flops = elements * 2;

  state.SetItemsProcessed(elements);
  state.counters["core_cycles"] =
      benchmark::Counter(static_cast<double>(core_cycles));
  state.counters["elem/core_cycle"] =
      static_cast<double>(elements) / static_cast<double>(core_cycles);
  state.counters["fma_instr/core_cycle"] =
      static_cast<double>(vector_fmas) / static_cast<double>(core_cycles);
  state.counters["flop/core_cycle"] =
      static_cast<double>(flops) / static_cast<double>(core_cycles);
}

#undef FMA_STEP
#undef KEEP_ACCUMULATORS_LIVE
#undef AMD_PERF_NOINLINE

}  // namespace

BENCHMARK(BM_Fp32FmaRegisterPeak)
    ->Arg(256)
    ->Arg(1024)
    ->Arg(4096);

BENCHMARK_MAIN();
