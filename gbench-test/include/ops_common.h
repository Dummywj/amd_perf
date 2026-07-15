#pragma once

#include <benchmark/benchmark.h>

#include <array>
#include <cstddef>
#include <cstdint>
#include <string>

namespace ops {

constexpr std::uint64_t kGlobalSeed = 20260714ULL;
constexpr std::int64_t kMinElementsPerIteration = 1LL << 15;
constexpr std::size_t kDenseSizeCount = 113;
constexpr int kFmaReuseRounds = 64;
using DenseSizeArray = std::array<std::size_t, kDenseSizeCount>;

enum class Pattern : int {
  kSequential = 0,
  kStride17 = 1,
  kBlockRandom4k = 2,
  kUniformRandom = 3,
  kContiguous = 4,
};

const char* PatternName(Pattern pattern);
const DenseSizeArray& DenseSizes();
bool ValidateDenseSizes(std::string* error);
int InnerPasses(std::size_t elements);
std::uint64_t DeriveSeed(const char* operation, const char* pattern,
                         std::size_t n);

class FloatBuffer {
 public:
  explicit FloatBuffer(std::size_t size);
  ~FloatBuffer();
  FloatBuffer(const FloatBuffer&) = delete;
  FloatBuffer& operator=(const FloatBuffer&) = delete;
  float* data() { return data_; }
  const float* data() const { return data_; }
  std::size_t size() const { return size_; }

 private:
  float* data_ = nullptr;
  std::size_t size_ = 0;
};

class IndexBuffer {
 public:
  explicit IndexBuffer(std::size_t size);
  ~IndexBuffer();
  IndexBuffer(const IndexBuffer&) = delete;
  IndexBuffer& operator=(const IndexBuffer&) = delete;
  std::uint32_t* data() { return data_; }
  const std::uint32_t* data() const { return data_; }
  std::size_t size() const { return size_; }

 private:
  std::uint32_t* data_ = nullptr;
  std::size_t size_ = 0;
};

void FillInput(float* data, std::size_t n, std::uint64_t seed,
               float low = -1.0f, float high = 1.0f);
void FillSentinel(float* data, std::size_t n);
void BuildIndices(std::uint32_t* index, std::size_t n, Pattern pattern,
                  std::uint64_t seed);
bool ValidatePermutation(const std::uint32_t* index, std::size_t n,
                         std::string* error);

extern "C" {
float reduce_sum_scalar(const float* input, std::size_t n);
float reduce_sum_avx512(const float* input, std::size_t n);
float reduce_max_scalar(const float* input, std::size_t n);
float reduce_max_avx512(const float* input, std::size_t n);
void gather_scalar(const float* table, const std::uint32_t* index, float* out,
                   std::size_t n);
void gather_avx512_vgather(const float* table, const std::uint32_t* index,
                           float* out, std::size_t n);
void gather_avx512_load_store(const float* table, float* out, std::size_t n);
void scatter_scalar(const float* src, const std::uint32_t* index, float* dst,
                    std::size_t n);
void scatter_avx512_vscatter(const float* src, const std::uint32_t* index,
                             float* dst, std::size_t n);
void scatter_avx512_load_store(const float* src, float* dst, std::size_t n);
void softmax_scalar(const float* input, float* output, std::size_t n);
void softmax_avx512(const float* input, float* output, std::size_t n);
void fma_reuse_avx512(float* data, std::size_t n);
void fma_once_avx512(const float* a, const float* b, const float* c,
                     float* output, std::size_t n);
}

void RunReduceBenchmark(benchmark::State& state, bool use_avx512,
                        bool reduce_max);
void RunGatherBenchmark(benchmark::State& state, bool use_avx512,
                        Pattern pattern);
void RunGatherContiguousBenchmark(benchmark::State& state);
void RunScatterBenchmark(benchmark::State& state, bool use_avx512,
                         Pattern pattern);
void RunScatterContiguousBenchmark(benchmark::State& state);
void RunSoftmaxBenchmark(benchmark::State& state, bool use_avx512);
void RunFmaBenchmark(benchmark::State& state, bool reuse);

void RegisterReduceBenchmarks();
void RegisterGatherBenchmarks();
void RegisterScatterBenchmarks();
void RegisterSoftmaxBenchmarks();
void RegisterFmaBenchmarks();

}  // namespace ops
