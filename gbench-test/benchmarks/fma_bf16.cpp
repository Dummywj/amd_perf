#include "fma_bf16.h"

#include "ops_common.h"
#include "perf_counter.h"

#include <immintrin.h>

#include <algorithm>
#include <cstdlib>
#include <cstring>
#include <new>
#include <string>

namespace bf16_fma {
namespace {

#if defined(__GNUC__) || defined(__clang__)
#define BF16_NOINLINE __attribute__((noinline))
#else
#define BF16_NOINLINE
#endif

class StableRng {
 public:
  explicit StableRng(std::uint64_t seed) : state_(seed ? seed : 1) {}

  float Uniform(float low, float high) {
    const std::uint32_t bits = static_cast<std::uint32_t>(Next() >> 40);
    const float unit = static_cast<float>(bits) * (1.0f / 16777216.0f);
    return low + (high - low) * unit;
  }

 private:
  std::uint64_t Next() {
    std::uint64_t x = state_;
    x ^= x >> 12;
    x ^= x << 25;
    x ^= x >> 27;
    state_ = x;
    return x * 2685821657736338717ULL;
  }

  std::uint64_t state_;
};

__mmask32 Mask32(std::size_t lanes) {
  return lanes == 32 ? static_cast<__mmask32>(~0U)
                     : static_cast<__mmask32>((1U << lanes) - 1U);
}

__mmask16 Mask16(std::size_t lanes) {
  return lanes == 16 ? static_cast<__mmask16>(~0U)
                     : static_cast<__mmask16>((1U << lanes) - 1U);
}

__m512bh LoadBf16(const Bf16* input) {
  return (__m512bh)_mm512_loadu_si512(static_cast<const void*>(input));
}

__m512bh MaskLoadBf16(const Bf16* input, std::size_t lanes) {
  return (__m512bh)_mm512_maskz_loadu_epi16(Mask32(lanes), input);
}

int InnerPasses(std::size_t n, int rounds) {
  const auto operations = static_cast<std::int64_t>(n) * rounds;
  return static_cast<int>(std::max<std::int64_t>(
      1, (ops::kMinElementsPerIteration + operations - 1) / operations));
}

template <typename Callback>
bool Measure(benchmark::State& state, Callback callback,
             std::uint64_t* core_cycles) {
  auto cycles = PerfCounter::OpenUserCoreCycles();
  if (!cycles.ok()) {
    state.SkipWithError(cycles.error().c_str());
    return false;
  }
  std::string error;
  if (!cycles.Start(&error)) {
    state.SkipWithError(error.c_str());
    return false;
  }
  for (auto _ : state) {
    (void)_;
    callback();
  }
  if (!cycles.Stop(core_cycles, &error)) {
    state.SkipWithError(error.c_str());
    return false;
  }
  return true;
}

void SetCounters(benchmark::State& state, std::size_t n,
                 std::int64_t inner_passes, std::int64_t rounds,
                 std::uint64_t core_cycles, int pattern_id) {
  const auto iterations = static_cast<std::int64_t>(state.iterations());
  const auto bf16_elements =
      iterations * inner_passes * static_cast<std::int64_t>(n) * rounds;
  const auto dot_instructions =
      iterations * inner_passes *
      static_cast<std::int64_t>((n + 31) / 32) * rounds;
  const auto logical_bytes = static_cast<std::int64_t>(8 * n);
  state.SetItemsProcessed(bf16_elements);
  state.SetBytesProcessed(iterations * inner_passes * logical_bytes);
  state.counters["elements"] = static_cast<double>(n);
  state.counters["fma_rounds"] = static_cast<double>(rounds);
  state.counters["working_set_bytes"] = static_cast<double>(8 * n);
  state.counters["inner_passes"] = static_cast<double>(inner_passes);
  state.counters["logical_bytes"] = static_cast<double>(logical_bytes);
  state.counters["core_cycles"] = static_cast<double>(core_cycles);
  state.counters["elem/core_cycle"] =
      static_cast<double>(bf16_elements) / static_cast<double>(core_cycles);
  state.counters["dpbf16_instr/core_cycle"] =
      static_cast<double>(dot_instructions) / static_cast<double>(core_cycles);
  state.counters["flop/core_cycle"] =
      2.0 * static_cast<double>(bf16_elements) /
      static_cast<double>(core_cycles);
  state.counters["implementation_id"] = 1;
  state.counters["pattern_id"] = pattern_id;
  state.counters["warmup_calls"] = 1.0;
}

}  // namespace

bool IsAvx512Bf16Supported() {
#if (defined(__x86_64__) || defined(__i386__)) && \
    (defined(__GNUC__) || defined(__clang__))
  __builtin_cpu_init();
  return __builtin_cpu_supports("avx512bf16");
#else
  return false;
#endif
}

Bf16 FloatToBf16Rne(float value) {
  std::uint32_t bits = 0;
  std::memcpy(&bits, &value, sizeof(bits));
  const std::uint32_t rounding_bias = 0x7fffU + ((bits >> 16) & 1U);
  return static_cast<Bf16>((bits + rounding_bias) >> 16);
}

float Bf16ToFloat(Bf16 value) {
  const std::uint32_t bits = static_cast<std::uint32_t>(value) << 16;
  float result = 0.0f;
  std::memcpy(&result, &bits, sizeof(result));
  return result;
}

std::size_t OutputElements(std::size_t input_elements) {
  return (input_elements + 1) / 2;
}

Bf16Buffer::Bf16Buffer(std::size_t size) : size_(size) {
  if (size == 0) {
    return;
  }
  void* allocation = nullptr;
  if (posix_memalign(&allocation, 64, size * sizeof(Bf16)) != 0) {
    throw std::bad_alloc();
  }
  data_ = static_cast<Bf16*>(allocation);
}

Bf16Buffer::~Bf16Buffer() { std::free(data_); }

void FillInput(Bf16* data, std::size_t n, std::uint64_t seed, float low,
               float high) {
  StableRng rng(seed);
  for (std::size_t i = 0; i < n; ++i) {
    data[i] = FloatToBf16Rne(rng.Uniform(low, high));
  }
}

#define BF16_REUSE_LOAD(index)                                             \
  const __m512bh av##index = LoadBf16(a + i + 32 * (index));               \
  const __m512bh bv##index = LoadBf16(b + i + 32 * (index));               \
  __m512 acc##index = _mm512_loadu_ps(c + i / 2 + 16 * (index))

#define BF16_REUSE_STEP(index) \
  acc##index = _mm512_dpbf16_ps(acc##index, av##index, bv##index)

#define BF16_REUSE_STORE(index) \
  _mm512_storeu_ps(output + i / 2 + 16 * (index), acc##index)

#define BF16_REUSE_ALL()  \
  do {                    \
    BF16_REUSE_STEP(0);   \
    BF16_REUSE_STEP(1);   \
    BF16_REUSE_STEP(2);   \
    BF16_REUSE_STEP(3);   \
    BF16_REUSE_STEP(4);   \
    BF16_REUSE_STEP(5);   \
    BF16_REUSE_STEP(6);   \
    BF16_REUSE_STEP(7);   \
  } while (0)

extern "C" BF16_NOINLINE void fma_bf16_reuse_avx512_dot(
    const Bf16* a, const Bf16* b, const float* c, float* output,
    std::size_t n) {
  constexpr std::size_t kBlockElements = 8 * 32;
  std::size_t i = 0;
  for (; i + kBlockElements <= n; i += kBlockElements) {
    BF16_REUSE_LOAD(0);
    BF16_REUSE_LOAD(1);
    BF16_REUSE_LOAD(2);
    BF16_REUSE_LOAD(3);
    BF16_REUSE_LOAD(4);
    BF16_REUSE_LOAD(5);
    BF16_REUSE_LOAD(6);
    BF16_REUSE_LOAD(7);
    for (int round = 0; round < kReuseRounds; round += 4) {
      BF16_REUSE_ALL();
      BF16_REUSE_ALL();
      BF16_REUSE_ALL();
      BF16_REUSE_ALL();
    }
    BF16_REUSE_STORE(0);
    BF16_REUSE_STORE(1);
    BF16_REUSE_STORE(2);
    BF16_REUSE_STORE(3);
    BF16_REUSE_STORE(4);
    BF16_REUSE_STORE(5);
    BF16_REUSE_STORE(6);
    BF16_REUSE_STORE(7);
  }
  for (; i + 32 <= n; i += 32) {
    const __m512bh av = LoadBf16(a + i);
    const __m512bh bv = LoadBf16(b + i);
    __m512 acc = _mm512_loadu_ps(c + i / 2);
    for (int round = 0; round < kReuseRounds; ++round) {
      acc = _mm512_dpbf16_ps(acc, av, bv);
    }
    _mm512_storeu_ps(output + i / 2, acc);
  }
  if (i < n) {
    const std::size_t lanes = n - i;
    const std::size_t output_lanes = OutputElements(lanes);
    const __m512bh av = MaskLoadBf16(a + i, lanes);
    const __m512bh bv = MaskLoadBf16(b + i, lanes);
    __m512 acc = _mm512_maskz_loadu_ps(Mask16(output_lanes), c + i / 2);
    for (int round = 0; round < kReuseRounds; ++round) {
      acc = _mm512_dpbf16_ps(acc, av, bv);
    }
    _mm512_mask_storeu_ps(output + i / 2, Mask16(output_lanes), acc);
  }
}

#undef BF16_REUSE_LOAD
#undef BF16_REUSE_STEP
#undef BF16_REUSE_STORE
#undef BF16_REUSE_ALL

extern "C" BF16_NOINLINE void fma_bf16_once_avx512_dot(
    const Bf16* a, const Bf16* b, const float* c, float* output,
    std::size_t n) {
  std::size_t i = 0;
  for (; i + 32 <= n; i += 32) {
    const __m512bh av = LoadBf16(a + i);
    const __m512bh bv = LoadBf16(b + i);
    const __m512 acc = _mm512_loadu_ps(c + i / 2);
    _mm512_storeu_ps(output + i / 2, _mm512_dpbf16_ps(acc, av, bv));
  }
  if (i < n) {
    const std::size_t lanes = n - i;
    const std::size_t output_lanes = OutputElements(lanes);
    const __m512bh av = MaskLoadBf16(a + i, lanes);
    const __m512bh bv = MaskLoadBf16(b + i, lanes);
    const __m512 acc =
        _mm512_maskz_loadu_ps(Mask16(output_lanes), c + i / 2);
    _mm512_mask_storeu_ps(output + i / 2, Mask16(output_lanes),
                          _mm512_dpbf16_ps(acc, av, bv));
  }
}

void RunBenchmark(benchmark::State& state, bool reuse) {
  if (!IsAvx512Bf16Supported()) {
    state.SkipWithError("CPU does not support AVX-512 BF16");
    return;
  }
  const std::size_t n = static_cast<std::size_t>(state.range(0));
  const std::size_t output_elements = OutputElements(n);
  const int rounds = reuse ? kReuseRounds : 1;
  const int passes = InnerPasses(n, rounds);
  Bf16Buffer a(n), b(n);
  ops::FloatBuffer c(output_elements), output(output_elements);
  FillInput(a.data(), n, ops::DeriveSeed("fma_bf16", "a", n));
  FillInput(b.data(), n, ops::DeriveSeed("fma_bf16", "b", n));
  ops::FillInput(c.data(), output_elements,
                 ops::DeriveSeed("fma_bf16", "c", n), -0.5f, 0.5f);
  const auto kernel =
      reuse ? fma_bf16_reuse_avx512_dot : fma_bf16_once_avx512_dot;
  kernel(a.data(), b.data(), c.data(), output.data(), n);
  benchmark::DoNotOptimize(output.data());

  std::uint64_t cycles = 0;
  if (!Measure(state,
               [&] {
                 for (int pass = 0; pass < passes; ++pass) {
                   kernel(a.data(), b.data(), c.data(), output.data(), n);
                 }
                 benchmark::DoNotOptimize(output.data());
                 benchmark::ClobberMemory();
               },
               &cycles)) {
    return;
  }
  SetCounters(state, n, passes, rounds, cycles, reuse ? 0 : 1);
}

void RegisterBenchmarks() {
  for (const bool reuse : {true, false}) {
    for (const std::size_t n : ops::DenseSizes()) {
      const std::string name = std::string("fma_bf16/") +
                               (reuse ? "reuse/" : "once/") +
                               "avx512_bf16_dot/" + std::to_string(n);
      benchmark::RegisterBenchmark(name.c_str(), RunBenchmark, reuse)
          ->Arg(static_cast<std::int64_t>(n));
    }
  }
}

}  // namespace bf16_fma
