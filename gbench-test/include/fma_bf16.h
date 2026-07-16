#pragma once

#include <benchmark/benchmark.h>

#include <cstddef>
#include <cstdint>

namespace bf16_fma {

using Bf16 = std::uint16_t;

constexpr int kReuseRounds = 64;

bool IsAvx512Bf16Supported();
Bf16 FloatToBf16Rne(float value);
float Bf16ToFloat(Bf16 value);
std::size_t OutputElements(std::size_t input_elements);

class Bf16Buffer {
 public:
  explicit Bf16Buffer(std::size_t size);
  ~Bf16Buffer();
  Bf16Buffer(const Bf16Buffer&) = delete;
  Bf16Buffer& operator=(const Bf16Buffer&) = delete;
  Bf16* data() { return data_; }
  const Bf16* data() const { return data_; }
  std::size_t size() const { return size_; }

 private:
  Bf16* data_ = nullptr;
  std::size_t size_ = 0;
};

void FillInput(Bf16* data, std::size_t n, std::uint64_t seed,
               float low = -0.5f, float high = 0.5f);

extern "C" {
void fma_bf16_reuse_avx512_dot(const Bf16* a, const Bf16* b,
                               const float* c, float* output, std::size_t n);
void fma_bf16_once_avx512_dot(const Bf16* a, const Bf16* b,
                              const float* c, float* output, std::size_t n);
}

void RunBenchmark(benchmark::State& state, bool reuse);
void RegisterBenchmarks();

}  // namespace bf16_fma
