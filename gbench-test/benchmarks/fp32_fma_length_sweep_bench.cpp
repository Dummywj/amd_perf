#include <benchmark/benchmark.h>

#include "perf_counter.h"

#include <immintrin.h>

#include <cstddef>
#include <cstdint>
#include <cstdlib>
#include <new>
#include <string>

namespace {

constexpr std::int64_t kFp32LanesPerZmm = 16;
constexpr std::int64_t kIndependentAccumulators = 16;
constexpr std::int64_t kMemoryStreamsPerElement = 2;  // load and store data
constexpr std::int64_t kBytesPerFp32 = 4;
constexpr std::int64_t kMinElementsPerTimedIteration = 1 << 15;

#if defined(__GNUC__) || defined(__clang__)
#define AMD_PERF_NOINLINE __attribute__((noinline))
#else
#define AMD_PERF_NOINLINE
#endif

class AlignedFloatBuffer {
 public:
  explicit AlignedFloatBuffer(std::size_t count) : count_(count) {
    void* ptr = nullptr;
    if (posix_memalign(&ptr, 64, count_ * sizeof(float)) != 0) {
      throw std::bad_alloc();
    }
    data_ = static_cast<float*>(ptr);
  }

  AlignedFloatBuffer(const AlignedFloatBuffer&) = delete;
  AlignedFloatBuffer& operator=(const AlignedFloatBuffer&) = delete;

  ~AlignedFloatBuffer() { std::free(data_); }

  float* data() { return data_; }
  const float* data() const { return data_; }
  std::size_t size() const { return count_; }

 private:
  float* data_ = nullptr;
  std::size_t count_ = 0;
};

void InitializeInput(AlignedFloatBuffer* data) {
  for (std::size_t i = 0; i < data->size(); ++i) {
    const float x = static_cast<float>((i & 127) + 1);
    data->data()[i] = 1.0f + x * 0.001f;
  }
}

void InitializeStreamInput(AlignedFloatBuffer* a, AlignedFloatBuffer* b,
                           AlignedFloatBuffer* c, AlignedFloatBuffer* out) {
  for (std::size_t i = 0; i < a->size(); ++i) {
    const float x = static_cast<float>((i & 127) + 1);
    a->data()[i] = 1.0f + x * 0.001f;
    b->data()[i] = 0.5f + x * 0.0001f;
    c->data()[i] = 0.25f + x * 0.00001f;
    out->data()[i] = 0.0f;
  }
}

#define LOAD_ACC(index) \
  __m512 acc##index = _mm512_load_ps(data + i + index * kFp32LanesPerZmm)
#define FMA_ACC(index) acc##index = _mm512_fmadd_ps(acc##index, mul, add)
#define STORE_ACC(index) \
  _mm512_store_ps(data + i + index * kFp32LanesPerZmm, acc##index)
#define FMA_ALL_ACCUMULATORS() \
  do {                         \
    FMA_ACC(0);                \
    FMA_ACC(1);                \
    FMA_ACC(2);                \
    FMA_ACC(3);                \
    FMA_ACC(4);                \
    FMA_ACC(5);                \
    FMA_ACC(6);                \
    FMA_ACC(7);                \
    FMA_ACC(8);                \
    FMA_ACC(9);                \
    FMA_ACC(10);               \
    FMA_ACC(11);               \
    FMA_ACC(12);               \
    FMA_ACC(13);               \
    FMA_ACC(14);               \
    FMA_ACC(15);               \
  } while (0)

template <int FmaRoundsPerLoad>
AMD_PERF_NOINLINE void RunFp32FmaLengthSweepKernel(float* data, std::size_t n,
                                                   int passes) {
  constexpr std::size_t kBlockElements =
      kFp32LanesPerZmm * kIndependentAccumulators;
  const __m512 mul = _mm512_set1_ps(0.99999994f);
  const __m512 add = _mm512_set1_ps(0.000001f);

  for (int pass = 0; pass < passes; ++pass) {
    std::size_t i = 0;
    for (; i + kBlockElements <= n; i += kBlockElements) {
      LOAD_ACC(0);
      LOAD_ACC(1);
      LOAD_ACC(2);
      LOAD_ACC(3);
      LOAD_ACC(4);
      LOAD_ACC(5);
      LOAD_ACC(6);
      LOAD_ACC(7);
      LOAD_ACC(8);
      LOAD_ACC(9);
      LOAD_ACC(10);
      LOAD_ACC(11);
      LOAD_ACC(12);
      LOAD_ACC(13);
      LOAD_ACC(14);
      LOAD_ACC(15);

      for (int round = 0; round < FmaRoundsPerLoad; ++round) {
        FMA_ALL_ACCUMULATORS();
      }

      STORE_ACC(0);
      STORE_ACC(1);
      STORE_ACC(2);
      STORE_ACC(3);
      STORE_ACC(4);
      STORE_ACC(5);
      STORE_ACC(6);
      STORE_ACC(7);
      STORE_ACC(8);
      STORE_ACC(9);
      STORE_ACC(10);
      STORE_ACC(11);
      STORE_ACC(12);
      STORE_ACC(13);
      STORE_ACC(14);
      STORE_ACC(15);
    }

    for (; i + kFp32LanesPerZmm <= n; i += kFp32LanesPerZmm) {
      __m512 acc = _mm512_load_ps(data + i);
      for (int round = 0; round < FmaRoundsPerLoad; ++round) {
        acc = _mm512_fmadd_ps(acc, mul, add);
      }
      _mm512_store_ps(data + i, acc);
    }

    for (; i < n; ++i) {
      float acc = data[i];
      for (int round = 0; round < FmaRoundsPerLoad; ++round) {
        acc = acc * 0.99999994f + 0.000001f;
      }
      data[i] = acc;
    }
  }
}

#undef LOAD_ACC
#undef FMA_ACC
#undef STORE_ACC
#undef FMA_ALL_ACCUMULATORS

AMD_PERF_NOINLINE void RunFp32FmaOnceStreamKernel(
    const float* a, const float* b, const float* c, float* out, std::size_t n,
    int passes) {
  constexpr std::size_t kUnroll = 4;
  constexpr std::size_t kBlockElements = kFp32LanesPerZmm * kUnroll;

  for (int pass = 0; pass < passes; ++pass) {
    std::size_t i = 0;
    for (; i + kBlockElements <= n; i += kBlockElements) {
      const __m512 a0 = _mm512_load_ps(a + i + 0 * kFp32LanesPerZmm);
      const __m512 b0 = _mm512_load_ps(b + i + 0 * kFp32LanesPerZmm);
      const __m512 c0 = _mm512_load_ps(c + i + 0 * kFp32LanesPerZmm);
      const __m512 r0 = _mm512_fmadd_ps(a0, b0, c0);

      const __m512 a1 = _mm512_load_ps(a + i + 1 * kFp32LanesPerZmm);
      const __m512 b1 = _mm512_load_ps(b + i + 1 * kFp32LanesPerZmm);
      const __m512 c1 = _mm512_load_ps(c + i + 1 * kFp32LanesPerZmm);
      const __m512 r1 = _mm512_fmadd_ps(a1, b1, c1);

      const __m512 a2 = _mm512_load_ps(a + i + 2 * kFp32LanesPerZmm);
      const __m512 b2 = _mm512_load_ps(b + i + 2 * kFp32LanesPerZmm);
      const __m512 c2 = _mm512_load_ps(c + i + 2 * kFp32LanesPerZmm);
      const __m512 r2 = _mm512_fmadd_ps(a2, b2, c2);

      const __m512 a3 = _mm512_load_ps(a + i + 3 * kFp32LanesPerZmm);
      const __m512 b3 = _mm512_load_ps(b + i + 3 * kFp32LanesPerZmm);
      const __m512 c3 = _mm512_load_ps(c + i + 3 * kFp32LanesPerZmm);
      const __m512 r3 = _mm512_fmadd_ps(a3, b3, c3);

      _mm512_store_ps(out + i + 0 * kFp32LanesPerZmm, r0);
      _mm512_store_ps(out + i + 1 * kFp32LanesPerZmm, r1);
      _mm512_store_ps(out + i + 2 * kFp32LanesPerZmm, r2);
      _mm512_store_ps(out + i + 3 * kFp32LanesPerZmm, r3);
    }

    for (; i + kFp32LanesPerZmm <= n; i += kFp32LanesPerZmm) {
      const __m512 av = _mm512_load_ps(a + i);
      const __m512 bv = _mm512_load_ps(b + i);
      const __m512 cv = _mm512_load_ps(c + i);
      _mm512_store_ps(out + i, _mm512_fmadd_ps(av, bv, cv));
    }

    for (; i < n; ++i) {
      out[i] = a[i] * b[i] + c[i];
    }
  }
}

int InnerPassesForLength(std::int64_t elements, std::int64_t fma_rounds) {
  const std::int64_t fma_elements = elements * fma_rounds;
  if (fma_elements >= kMinElementsPerTimedIteration) {
    return 1;
  }
  const std::int64_t passes =
      (kMinElementsPerTimedIteration + fma_elements - 1) / fma_elements;
  return static_cast<int>(passes);
}

template <int FmaRoundsPerLoad>
static void BM_Fp32FmaLengthSweepRounds(benchmark::State& state) {
  const auto n = static_cast<std::int64_t>(state.range(0));
  const int inner_passes = InnerPassesForLength(n, FmaRoundsPerLoad);

  AlignedFloatBuffer data(static_cast<std::size_t>(n));
  InitializeInput(&data);

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
    RunFp32FmaLengthSweepKernel<FmaRoundsPerLoad>(
        data.data(), static_cast<std::size_t>(n), inner_passes);
    benchmark::DoNotOptimize(data.data());
    benchmark::ClobberMemory();
  }

  std::uint64_t core_cycles = 0;
  if (!cycles.Stop(&core_cycles, &error)) {
    state.SkipWithError(error.c_str());
    return;
  }

  const auto unique_elements = n;
  const auto fma_elements =
      state.iterations() * n * inner_passes * FmaRoundsPerLoad;
  const auto vector_fmas = fma_elements / kFp32LanesPerZmm;
  const auto flops = fma_elements * 2;
  const auto working_set_bytes = n * kBytesPerFp32;
  const auto streamed_bytes =
      state.iterations() * n * inner_passes * kMemoryStreamsPerElement *
      kBytesPerFp32;
  const auto arithmetic_intensity =
      static_cast<double>(flops) / static_cast<double>(streamed_bytes);

  state.SetItemsProcessed(fma_elements);
  state.counters["elements"] =
      benchmark::Counter(static_cast<double>(unique_elements));
  state.counters["fma_rounds"] =
      benchmark::Counter(static_cast<double>(FmaRoundsPerLoad));
  state.counters["working_set_bytes"] =
      benchmark::Counter(static_cast<double>(working_set_bytes));
  state.counters["inner_passes"] =
      benchmark::Counter(static_cast<double>(inner_passes));
  state.counters["core_cycles"] =
      benchmark::Counter(static_cast<double>(core_cycles));
  state.counters["elem/core_cycle"] =
      static_cast<double>(fma_elements) / static_cast<double>(core_cycles);
  state.counters["fma_instr/core_cycle"] =
      static_cast<double>(vector_fmas) / static_cast<double>(core_cycles);
  state.counters["flop/core_cycle"] =
      static_cast<double>(flops) / static_cast<double>(core_cycles);
  state.counters["bytes/core_cycle"] =
      static_cast<double>(streamed_bytes) / static_cast<double>(core_cycles);
  state.counters["flop/byte"] = arithmetic_intensity;
}

static void BM_Fp32FmaLengthSweep(benchmark::State& state) {
  BM_Fp32FmaLengthSweepRounds<8>(state);
}

static void BM_Fp32FmaLengthSweepOnce(benchmark::State& state) {
  constexpr std::int64_t kFmaRoundsPerElement = 1;
  constexpr std::int64_t kStreamArrays = 4;  // a, b, c, out
  const auto n = static_cast<std::int64_t>(state.range(0));
  const int inner_passes = InnerPassesForLength(n, kFmaRoundsPerElement);

  AlignedFloatBuffer a(static_cast<std::size_t>(n));
  AlignedFloatBuffer b(static_cast<std::size_t>(n));
  AlignedFloatBuffer c(static_cast<std::size_t>(n));
  AlignedFloatBuffer out(static_cast<std::size_t>(n));
  InitializeStreamInput(&a, &b, &c, &out);

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
    RunFp32FmaOnceStreamKernel(a.data(), b.data(), c.data(), out.data(),
                               static_cast<std::size_t>(n), inner_passes);
    benchmark::DoNotOptimize(out.data());
    benchmark::ClobberMemory();
  }

  std::uint64_t core_cycles = 0;
  if (!cycles.Stop(&core_cycles, &error)) {
    state.SkipWithError(error.c_str());
    return;
  }

  const auto unique_elements = n;
  const auto fma_elements =
      state.iterations() * n * inner_passes * kFmaRoundsPerElement;
  const auto vector_fmas = fma_elements / kFp32LanesPerZmm;
  const auto flops = fma_elements * 2;
  const auto working_set_bytes = n * kStreamArrays * kBytesPerFp32;
  const auto streamed_bytes =
      state.iterations() * n * inner_passes * kStreamArrays * kBytesPerFp32;
  const auto arithmetic_intensity =
      static_cast<double>(flops) / static_cast<double>(streamed_bytes);

  state.SetItemsProcessed(fma_elements);
  state.counters["elements"] =
      benchmark::Counter(static_cast<double>(unique_elements));
  state.counters["fma_rounds"] =
      benchmark::Counter(static_cast<double>(kFmaRoundsPerElement));
  state.counters["working_set_bytes"] =
      benchmark::Counter(static_cast<double>(working_set_bytes));
  state.counters["inner_passes"] =
      benchmark::Counter(static_cast<double>(inner_passes));
  state.counters["core_cycles"] =
      benchmark::Counter(static_cast<double>(core_cycles));
  state.counters["elem/core_cycle"] =
      static_cast<double>(fma_elements) / static_cast<double>(core_cycles);
  state.counters["fma_instr/core_cycle"] =
      static_cast<double>(vector_fmas) / static_cast<double>(core_cycles);
  state.counters["flop/core_cycle"] =
      static_cast<double>(flops) / static_cast<double>(core_cycles);
  state.counters["bytes/core_cycle"] =
      static_cast<double>(streamed_bytes) / static_cast<double>(core_cycles);
  state.counters["flop/byte"] = arithmetic_intensity;
}

void Fp32FmaLengthSweepArgs(benchmark::Benchmark* benchmark) {
  for (std::int64_t n = 256; n <= (1LL << 25); n <<= 1) {
    benchmark->Arg(n);
  }
}

void AddUniqueArg(benchmark::Benchmark* benchmark, std::int64_t n,
                  std::int64_t* last) {
  if (n != *last) {
    benchmark->Arg(n);
    *last = n;
  }
}

std::int64_t RoundUpToMultiple(std::int64_t value, std::int64_t multiple) {
  return ((value + multiple - 1) / multiple) * multiple;
}

void Fp32FmaLengthSweepOnceDenseArgs(benchmark::Benchmark* benchmark) {
  std::int64_t last = 0;
  for (std::int64_t n : {16, 32, 48, 64, 96, 128, 192}) {
    AddUniqueArg(benchmark, n, &last);
  }

  constexpr std::int64_t kMaxElements = 1LL << 25;
  constexpr std::int64_t kVectorMultiple = kFp32LanesPerZmm;
  for (std::int64_t base = 256; base < kMaxElements; base <<= 1) {
    AddUniqueArg(benchmark, base, &last);
    AddUniqueArg(benchmark, RoundUpToMultiple(base * 5 / 4, kVectorMultiple),
                 &last);
    AddUniqueArg(benchmark, RoundUpToMultiple(base * 3 / 2, kVectorMultiple),
                 &last);
    AddUniqueArg(benchmark, RoundUpToMultiple(base * 7 / 4, kVectorMultiple),
                 &last);
  }
  AddUniqueArg(benchmark, kMaxElements, &last);
}

#undef AMD_PERF_NOINLINE

}  // namespace

BENCHMARK(BM_Fp32FmaLengthSweep)->Apply(Fp32FmaLengthSweepArgs);
BENCHMARK(BM_Fp32FmaLengthSweepOnce)->Apply(Fp32FmaLengthSweepOnceDenseArgs);

BENCHMARK_MAIN();
