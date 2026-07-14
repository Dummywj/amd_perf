#include "ops_common.h"

#include "perf_counter.h"

#include <immintrin.h>
#include <sleef.h>

#include <algorithm>
#include <array>
#include <cmath>
#include <cstdlib>
#include <cstring>
#include <limits>
#include <new>
#include <numeric>
#include <stdexcept>
#include <utility>

namespace ops {
namespace {

#if defined(__GNUC__) || defined(__clang__)
#define OPS_NOINLINE __attribute__((noinline))
#define OPS_SCALAR __attribute__((noinline, optimize("no-tree-vectorize")))
#else
#define OPS_NOINLINE
#define OPS_SCALAR
#endif

constexpr std::array<std::size_t, 9> kMainSizes = {
    1ULL << 10, 1ULL << 12, 1ULL << 14, 1ULL << 16, 1ULL << 18,
    1ULL << 20, 1ULL << 22, 1ULL << 24, 1ULL << 26};

class StableRng {
 public:
  explicit StableRng(std::uint64_t seed) : state_(seed ? seed : 1) {}

  std::uint64_t Next() {
    std::uint64_t x = state_;
    x ^= x >> 12;
    x ^= x << 25;
    x ^= x >> 27;
    state_ = x;
    return x * 2685821657736338717ULL;
  }

  float Uniform(float low, float high) {
    const std::uint32_t bits = static_cast<std::uint32_t>(Next() >> 40);
    const float unit = static_cast<float>(bits) * (1.0f / 16777216.0f);
    return low + (high - low) * unit;
  }

 private:
  std::uint64_t state_;
};

template <typename T>
T* AllocateAligned(std::size_t size) {
  if (size == 0) {
    return nullptr;
  }
  void* allocation = nullptr;
  if (posix_memalign(&allocation, 64, size * sizeof(T)) != 0) {
    throw std::bad_alloc();
  }
  return static_cast<T*>(allocation);
}

void ShuffleRange(std::uint32_t* index, std::size_t begin, std::size_t end,
                  StableRng* rng) {
  for (std::size_t i = end; i > begin + 1; --i) {
    const std::size_t j = begin + rng->Next() % (i - begin);
    std::swap(index[i - 1], index[j]);
  }
}

void SetCommonCounters(benchmark::State& state, std::size_t n,
                       std::int64_t inner_passes, std::int64_t working_set,
                       std::int64_t logical_bytes, std::uint64_t core_cycles,
                       int implementation_id, int pattern_id) {
  const auto processed = state.iterations() * inner_passes *
                         static_cast<std::int64_t>(n);
  state.SetItemsProcessed(processed);
  state.SetBytesProcessed(state.iterations() * inner_passes * logical_bytes);
  state.counters["elements"] = static_cast<double>(n);
  state.counters["working_set_bytes"] = static_cast<double>(working_set);
  state.counters["inner_passes"] = static_cast<double>(inner_passes);
  state.counters["logical_bytes"] = static_cast<double>(logical_bytes);
  state.counters["core_cycles"] = static_cast<double>(core_cycles);
  state.counters["elem/core_cycle"] =
      static_cast<double>(processed) / static_cast<double>(core_cycles);
  state.counters["implementation_id"] = implementation_id;
  state.counters["pattern_id"] = pattern_id;
  state.counters["warmup_calls"] = 1.0;
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

__m512 ReduceMaxVectors(__m512 a, __m512 b, __m512 c, __m512 d) {
  return _mm512_max_ps(_mm512_max_ps(a, b), _mm512_max_ps(c, d));
}

__m512 ReduceSumVectors(__m512 a, __m512 b, __m512 c, __m512 d) {
  return _mm512_add_ps(_mm512_add_ps(a, b), _mm512_add_ps(c, d));
}

}  // namespace

const char* PatternName(Pattern pattern) {
  switch (pattern) {
    case Pattern::kSequential:
      return "sequential";
    case Pattern::kStride17:
      return "stride17";
    case Pattern::kBlockRandom4k:
      return "block_random_4k";
    case Pattern::kUniformRandom:
      return "uniform_random";
  }
  return "unknown";
}

int InnerPasses(std::size_t elements) {
  const auto n = static_cast<std::int64_t>(elements);
  return static_cast<int>(std::max<std::int64_t>(
      1, (kMinElementsPerIteration + n - 1) / n));
}

std::uint64_t DeriveSeed(const char* operation, const char* pattern,
                         std::size_t n) {
  std::uint64_t hash = 1469598103934665603ULL ^ kGlobalSeed;
  const auto mix = [&hash](const char* text) {
    for (; *text != '\0'; ++text) {
      hash ^= static_cast<unsigned char>(*text);
      hash *= 1099511628211ULL;
    }
  };
  mix(operation);
  mix(pattern);
  for (int shift = 0; shift < 64; shift += 8) {
    hash ^= static_cast<std::uint8_t>(n >> shift);
    hash *= 1099511628211ULL;
  }
  return hash;
}

FloatBuffer::FloatBuffer(std::size_t size)
    : data_(AllocateAligned<float>(size)), size_(size) {}
FloatBuffer::~FloatBuffer() { std::free(data_); }
IndexBuffer::IndexBuffer(std::size_t size)
    : data_(AllocateAligned<std::uint32_t>(size)), size_(size) {}
IndexBuffer::~IndexBuffer() { std::free(data_); }

void FillInput(float* data, std::size_t n, std::uint64_t seed, float low,
               float high) {
  StableRng rng(seed);
  for (std::size_t i = 0; i < n; ++i) {
    data[i] = rng.Uniform(low, high);
  }
}

void FillSentinel(float* data, std::size_t n) {
  for (std::size_t i = 0; i < n; ++i) {
    data[i] = -1234.5f - static_cast<float>(i & 1023U) * 0.03125f;
  }
}

void BuildIndices(std::uint32_t* index, std::size_t n, Pattern pattern,
                  std::uint64_t seed) {
  for (std::size_t i = 0; i < n; ++i) {
    index[i] = static_cast<std::uint32_t>(i);
  }
  if (pattern == Pattern::kSequential) {
    return;
  }
  if (pattern == Pattern::kStride17) {
    if (std::gcd<std::size_t>(17, n) != 1) {
      throw std::invalid_argument("stride17 requires gcd(17, N) == 1");
    }
    for (std::size_t i = 0; i < n; ++i) {
      index[i] = static_cast<std::uint32_t>((17ULL * i) % n);
    }
    return;
  }
  StableRng rng(seed);
  if (pattern == Pattern::kBlockRandom4k) {
    constexpr std::size_t kBlock = 4096;
    for (std::size_t begin = 0; begin < n; begin += kBlock) {
      ShuffleRange(index, begin, std::min(n, begin + kBlock), &rng);
    }
    return;
  }
  ShuffleRange(index, 0, n, &rng);
}

bool ValidatePermutation(const std::uint32_t* index, std::size_t n,
                         std::string* error) {
  IndexBuffer seen(n);
  std::memset(seen.data(), 0, n * sizeof(std::uint32_t));
  for (std::size_t i = 0; i < n; ++i) {
    if (index[i] >= n) {
      *error = "index out of range at position " + std::to_string(i);
      return false;
    }
    if (seen.data()[index[i]] != 0) {
      *error = "duplicate index value " + std::to_string(index[i]);
      return false;
    }
    seen.data()[index[i]] = 1;
  }
  return true;
}

extern "C" OPS_SCALAR float reduce_sum_scalar(const float* input,
                                                std::size_t n) {
  float sums[16] = {};
  std::size_t i = 0;
  for (; i + 16 <= n; i += 16) {
    for (std::size_t lane = 0; lane < 16; ++lane) {
      sums[lane] += input[i + lane];
    }
  }
  for (; i < n; ++i) {
    sums[i & 15U] += input[i];
  }
  float result = 0.0f;
  for (float sum : sums) {
    result += sum;
  }
  return result;
}

extern "C" OPS_NOINLINE float reduce_sum_avx512(const float* input,
                                                  std::size_t n) {
  __m512 a = _mm512_setzero_ps();
  __m512 b = _mm512_setzero_ps();
  __m512 c = _mm512_setzero_ps();
  __m512 d = _mm512_setzero_ps();
  std::size_t i = 0;
  for (; i + 64 <= n; i += 64) {
    a = _mm512_add_ps(a, _mm512_loadu_ps(input + i));
    b = _mm512_add_ps(b, _mm512_loadu_ps(input + i + 16));
    c = _mm512_add_ps(c, _mm512_loadu_ps(input + i + 32));
    d = _mm512_add_ps(d, _mm512_loadu_ps(input + i + 48));
  }
  for (; i + 16 <= n; i += 16) {
    a = _mm512_add_ps(a, _mm512_loadu_ps(input + i));
  }
  if (i < n) {
    const __mmask16 mask = static_cast<__mmask16>((1U << (n - i)) - 1U);
    a = _mm512_add_ps(a, _mm512_maskz_loadu_ps(mask, input + i));
  }
  return _mm512_reduce_add_ps(ReduceSumVectors(a, b, c, d));
}

extern "C" OPS_SCALAR float reduce_max_scalar(const float* input,
                                                std::size_t n) {
  float result = -std::numeric_limits<float>::infinity();
  for (std::size_t i = 0; i < n; ++i) {
    result = std::max(result, input[i]);
  }
  return result;
}

extern "C" OPS_NOINLINE float reduce_max_avx512(const float* input,
                                                  std::size_t n) {
  const __m512 negative_inf =
      _mm512_set1_ps(-std::numeric_limits<float>::infinity());
  __m512 a = negative_inf;
  __m512 b = negative_inf;
  __m512 c = negative_inf;
  __m512 d = negative_inf;
  std::size_t i = 0;
  for (; i + 64 <= n; i += 64) {
    a = _mm512_max_ps(a, _mm512_loadu_ps(input + i));
    b = _mm512_max_ps(b, _mm512_loadu_ps(input + i + 16));
    c = _mm512_max_ps(c, _mm512_loadu_ps(input + i + 32));
    d = _mm512_max_ps(d, _mm512_loadu_ps(input + i + 48));
  }
  for (; i + 16 <= n; i += 16) {
    a = _mm512_max_ps(a, _mm512_loadu_ps(input + i));
  }
  if (i < n) {
    const __mmask16 mask = static_cast<__mmask16>((1U << (n - i)) - 1U);
    a = _mm512_max_ps(a, _mm512_mask_loadu_ps(negative_inf, mask, input + i));
  }
  return _mm512_reduce_max_ps(ReduceMaxVectors(a, b, c, d));
}

extern "C" OPS_SCALAR void gather_scalar(const float* table,
                                           const std::uint32_t* index,
                                           float* out, std::size_t n) {
  for (std::size_t i = 0; i < n; ++i) {
    out[i] = table[index[i]];
  }
}

extern "C" OPS_NOINLINE void gather_avx512(const float* table,
                                             const std::uint32_t* index,
                                             float* out, std::size_t n) {
  std::size_t i = 0;
  for (; i + 16 <= n; i += 16) {
    const __m512i indices = _mm512_loadu_si512(index + i);
    _mm512_storeu_ps(out + i, _mm512_i32gather_ps(indices, table, 4));
  }
  if (i < n) {
    const __mmask16 mask = static_cast<__mmask16>((1U << (n - i)) - 1U);
    const __m512i indices = _mm512_maskz_loadu_epi32(mask, index + i);
    const __m512 values =
        _mm512_mask_i32gather_ps(_mm512_setzero_ps(), mask, indices, table, 4);
    _mm512_mask_storeu_ps(out + i, mask, values);
  }
}

extern "C" OPS_SCALAR void scatter_scalar(const float* src,
                                            const std::uint32_t* index,
                                            float* dst, std::size_t n) {
  for (std::size_t i = 0; i < n; ++i) {
    dst[index[i]] = src[i];
  }
}

extern "C" OPS_NOINLINE void scatter_avx512(const float* src,
                                              const std::uint32_t* index,
                                              float* dst, std::size_t n) {
  std::size_t i = 0;
  for (; i + 16 <= n; i += 16) {
    const __m512i indices = _mm512_loadu_si512(index + i);
    const __m512 values = _mm512_loadu_ps(src + i);
    _mm512_i32scatter_ps(dst, indices, values, 4);
  }
  if (i < n) {
    const __mmask16 mask = static_cast<__mmask16>((1U << (n - i)) - 1U);
    const __m512i indices = _mm512_maskz_loadu_epi32(mask, index + i);
    const __m512 values = _mm512_maskz_loadu_ps(mask, src + i);
    _mm512_mask_i32scatter_ps(dst, mask, indices, values, 4);
  }
}

extern "C" OPS_SCALAR void softmax_scalar(const float* input, float* output,
                                            std::size_t n) {
  const float maximum = reduce_max_scalar(input, n);
  constexpr std::size_t kBlockElements = 4096;
  float outer_sums[16] = {};
  std::size_t block_index = 0;
  for (std::size_t begin = 0; begin < n;
       begin += kBlockElements, ++block_index) {
    float block_sums[16] = {};
    const std::size_t end = std::min(n, begin + kBlockElements);
    for (std::size_t i = begin; i < end; ++i) {
      const float value = Sleef_expf_u10(input[i] - maximum);
      output[i] = value;
      block_sums[(i - begin) & 15U] += value;
    }
    float block_sum = 0.0f;
    for (float value : block_sums) {
      block_sum += value;
    }
    outer_sums[block_index & 15U] += block_sum;
  }
  float sum = 0.0f;
  for (float value : outer_sums) {
    sum += value;
  }
  const float reciprocal = 1.0f / sum;
  for (std::size_t i = 0; i < n; ++i) {
    output[i] *= reciprocal;
  }
}

extern "C" OPS_NOINLINE void softmax_avx512(const float* input,
                                              float* output, std::size_t n) {
  const float maximum = reduce_max_avx512(input, n);
  const __m512 max_vector = _mm512_set1_ps(maximum);
  constexpr std::size_t kBlockElements = 4096;
  float outer_sums[16] = {};
  std::size_t block_index = 0;
  for (std::size_t begin = 0; begin < n;
       begin += kBlockElements, ++block_index) {
    __m512 sums[4] = {_mm512_setzero_ps(), _mm512_setzero_ps(),
                      _mm512_setzero_ps(), _mm512_setzero_ps()};
    const std::size_t end = std::min(n, begin + kBlockElements);
    std::size_t i = begin;
    std::size_t vector_index = 0;
    for (; i + 16 <= end; i += 16, ++vector_index) {
      const __m512 shifted =
          _mm512_sub_ps(_mm512_loadu_ps(input + i), max_vector);
      const __m512 value = Sleef_expf16_u10avx512f(shifted);
      _mm512_storeu_ps(output + i, value);
      sums[vector_index & 3U] = _mm512_add_ps(sums[vector_index & 3U], value);
    }
    if (i < end) {
      const __mmask16 mask =
          static_cast<__mmask16>((1U << (end - i)) - 1U);
      const __m512 shifted =
          _mm512_sub_ps(_mm512_maskz_loadu_ps(mask, input + i), max_vector);
      const __m512 value =
          _mm512_maskz_mov_ps(mask, Sleef_expf16_u10avx512f(shifted));
      _mm512_mask_storeu_ps(output + i, mask, value);
      sums[vector_index & 3U] = _mm512_add_ps(sums[vector_index & 3U], value);
    }
    outer_sums[block_index & 15U] += _mm512_reduce_add_ps(
        ReduceSumVectors(sums[0], sums[1], sums[2], sums[3]));
  }
  float sum = 0.0f;
  for (float value : outer_sums) {
    sum += value;
  }
  const __m512 reciprocal = _mm512_set1_ps(1.0f / sum);
  std::size_t i = 0;
  for (; i + 16 <= n; i += 16) {
    _mm512_storeu_ps(output + i,
                     _mm512_mul_ps(_mm512_loadu_ps(output + i), reciprocal));
  }
  if (i < n) {
    const __mmask16 mask = static_cast<__mmask16>((1U << (n - i)) - 1U);
    _mm512_mask_storeu_ps(
        output + i, mask,
        _mm512_mul_ps(_mm512_maskz_loadu_ps(mask, output + i), reciprocal));
  }
}

void RunReduceBenchmark(benchmark::State& state, bool use_avx512,
                        bool reduce_max) {
  const std::size_t n = static_cast<std::size_t>(state.range(0));
  const int passes = InnerPasses(n);
  FloatBuffer input(n);
  FillInput(input.data(), n,
            DeriveSeed(reduce_max ? "reduce_max" : "reduce_sum", "none", n));
  float result = reduce_max
                     ? (use_avx512 ? reduce_max_avx512(input.data(), n)
                                   : reduce_max_scalar(input.data(), n))
                     : (use_avx512 ? reduce_sum_avx512(input.data(), n)
                                   : reduce_sum_scalar(input.data(), n));
  benchmark::DoNotOptimize(result);
  std::uint64_t cycles = 0;
  if (!Measure(state,
               [&] {
                 for (int pass = 0; pass < passes; ++pass) {
                   result = reduce_max
                                ? (use_avx512
                                       ? reduce_max_avx512(input.data(), n)
                                       : reduce_max_scalar(input.data(), n))
                                : (use_avx512
                                       ? reduce_sum_avx512(input.data(), n)
                                       : reduce_sum_scalar(input.data(), n));
                   benchmark::DoNotOptimize(result);
                 }
               },
               &cycles)) {
    return;
  }
  SetCommonCounters(state, n, passes, 4LL * n, 4LL * n + 4, cycles,
                    use_avx512 ? 1 : 0, -1);
}

void RunGatherBenchmark(benchmark::State& state, bool use_avx512,
                        Pattern pattern) {
  const std::size_t n = static_cast<std::size_t>(state.range(0));
  const int passes = InnerPasses(n);
  FloatBuffer table(n), output(n);
  IndexBuffer index(n);
  FillInput(table.data(), n, DeriveSeed("gather", "table", n));
  BuildIndices(index.data(), n, pattern,
               DeriveSeed("gather", PatternName(pattern), n));
  (use_avx512 ? gather_avx512 : gather_scalar)(table.data(), index.data(),
                                               output.data(), n);
  benchmark::DoNotOptimize(output.data());
  std::uint64_t cycles = 0;
  if (!Measure(state,
               [&] {
                 for (int pass = 0; pass < passes; ++pass) {
                   (use_avx512 ? gather_avx512 : gather_scalar)(
                       table.data(), index.data(), output.data(), n);
                 }
                 benchmark::DoNotOptimize(output.data());
                 benchmark::ClobberMemory();
               },
               &cycles)) {
    return;
  }
  SetCommonCounters(state, n, passes, 12LL * n, 12LL * n, cycles,
                    use_avx512 ? 1 : 0, static_cast<int>(pattern));
}

void RunScatterBenchmark(benchmark::State& state, bool use_avx512,
                         Pattern pattern) {
  const std::size_t n = static_cast<std::size_t>(state.range(0));
  const int passes = InnerPasses(n);
  FloatBuffer source(n), destination(n);
  IndexBuffer index(n);
  FillInput(source.data(), n, DeriveSeed("scatter", "source", n));
  FillSentinel(destination.data(), n);
  BuildIndices(index.data(), n, pattern,
               DeriveSeed("scatter", PatternName(pattern), n));
  (use_avx512 ? scatter_avx512 : scatter_scalar)(
      source.data(), index.data(), destination.data(), n);
  benchmark::DoNotOptimize(destination.data());
  std::uint64_t cycles = 0;
  if (!Measure(state,
               [&] {
                 for (int pass = 0; pass < passes; ++pass) {
                   (use_avx512 ? scatter_avx512 : scatter_scalar)(
                       source.data(), index.data(), destination.data(), n);
                 }
                 benchmark::DoNotOptimize(destination.data());
                 benchmark::ClobberMemory();
               },
               &cycles)) {
    return;
  }
  SetCommonCounters(state, n, passes, 12LL * n, 12LL * n, cycles,
                    use_avx512 ? 1 : 0, static_cast<int>(pattern));
}

void RunSoftmaxBenchmark(benchmark::State& state, bool use_avx512) {
  const std::size_t n = static_cast<std::size_t>(state.range(0));
  const int passes = InnerPasses(n);
  FloatBuffer input(n), output(n);
  FillInput(input.data(), n, DeriveSeed("softmax", "input", n), -10.0f,
            10.0f);
  (use_avx512 ? softmax_avx512 : softmax_scalar)(input.data(), output.data(), n);
  benchmark::DoNotOptimize(output.data());
  std::uint64_t cycles = 0;
  if (!Measure(state,
               [&] {
                 for (int pass = 0; pass < passes; ++pass) {
                   (use_avx512 ? softmax_avx512 : softmax_scalar)(
                       input.data(), output.data(), n);
                 }
                 benchmark::DoNotOptimize(output.data());
                 benchmark::ClobberMemory();
               },
               &cycles)) {
    return;
  }
  SetCommonCounters(state, n, passes, 8LL * n, 20LL * n, cycles,
                    use_avx512 ? 1 : 0, -1);
}

void RegisterReduceBenchmarks() {
  for (const bool use_avx512 : {false, true}) {
    for (const bool reduce_max : {false, true}) {
      for (const std::size_t n : kMainSizes) {
        const std::string name = std::string("reduce/") +
                                 (reduce_max ? "max/" : "sum/") +
                                 (use_avx512 ? "avx512/" : "scalar/") +
                                 std::to_string(n);
        benchmark::RegisterBenchmark(name.c_str(), RunReduceBenchmark,
                                     use_avx512, reduce_max)
            ->Arg(static_cast<std::int64_t>(n));
      }
    }
  }
}

void RegisterGatherBenchmarks() {
  for (const bool use_avx512 : {false, true}) {
    for (const Pattern pattern : {Pattern::kSequential, Pattern::kStride17,
                                  Pattern::kBlockRandom4k,
                                  Pattern::kUniformRandom}) {
      for (const std::size_t n : kMainSizes) {
        const std::string name = std::string("gather/") + PatternName(pattern) +
                                 "/" + (use_avx512 ? "avx512/" : "scalar/") +
                                 std::to_string(n);
        benchmark::RegisterBenchmark(name.c_str(), RunGatherBenchmark,
                                     use_avx512, pattern)
            ->Arg(static_cast<std::int64_t>(n));
      }
    }
  }
}

void RegisterScatterBenchmarks() {
  for (const bool use_avx512 : {false, true}) {
    for (const Pattern pattern : {Pattern::kSequential, Pattern::kStride17,
                                  Pattern::kBlockRandom4k,
                                  Pattern::kUniformRandom}) {
      for (const std::size_t n : kMainSizes) {
        const std::string name = std::string("scatter/") + PatternName(pattern) +
                                 "/" + (use_avx512 ? "avx512/" : "scalar/") +
                                 std::to_string(n);
        benchmark::RegisterBenchmark(name.c_str(), RunScatterBenchmark,
                                     use_avx512, pattern)
            ->Arg(static_cast<std::int64_t>(n));
      }
    }
  }
}

void RegisterSoftmaxBenchmarks() {
  for (const bool use_avx512 : {false, true}) {
    for (const std::size_t n : kMainSizes) {
      const std::string name = std::string("softmax/") +
                               (use_avx512 ? "avx512/" : "scalar/") +
                               std::to_string(n);
      benchmark::RegisterBenchmark(name.c_str(), RunSoftmaxBenchmark,
                                   use_avx512)
          ->Arg(static_cast<std::int64_t>(n));
    }
  }
}

}  // namespace ops
