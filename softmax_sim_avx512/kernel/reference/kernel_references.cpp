#include "common/kernel_interface.h"

#include <algorithm>
#include <cmath>
#include <cstdint>
#include <cstring>
#include <limits>

namespace {
constexpr float kScale = 1.25f;
constexpr int kFmaRounds = 16;

std::uint32_t LoadBits(const float value) {
  std::uint32_t result;
  std::memcpy(&result, &value, sizeof(result));
  return result;
}

float StoreBits(const std::uint32_t value) {
  float result;
  std::memcpy(&result, &value, sizeof(result));
  return result;
}
}  // namespace

extern "C" void fma_throughput_reference_f32(const float* input, float* output,
                                               std::size_t count) {
  for (std::size_t index = 0; index < count; ++index) {
    float value = input[index];
    for (int round = 0; round < kFmaRounds; ++round) {
      value = std::fma(value, 1.0001f, 0.0003f);
    }
    output[index] = value;
  }
}

extern "C" void fma_latency_reference_f32(const float* input, float* output,
                                            std::size_t count) {
  float state[16] = {};
  for (std::size_t index = 0; index < count; index += 16) {
    for (std::size_t lane = 0; lane < 16; ++lane) {
      state[lane] += input[index + lane];
      for (int round = 0; round < kFmaRounds; ++round) {
        state[lane] = std::fma(state[lane], 1.0001f, 0.0003f);
      }
      output[index + lane] = state[lane];
    }
  }
}

extern "C" void axpy_reference_f32(const float* input, float* output,
                                     std::size_t count) {
  for (std::size_t index = 0; index < count; ++index) {
    output[index] = std::fma(kScale, input[index], input[count + index]);
  }
}

extern "C" void vector_copy_reference_f32(const float* input, float* output,
                                            std::size_t count) {
  std::copy_n(input, count, output);
}

extern "C" void vector_triad_reference_f32(const float* input, float* output,
                                             std::size_t count) {
  for (std::size_t index = 0; index < count; ++index) {
    output[index] = std::fma(kScale, input[count + index], input[index]);
  }
}

extern "C" void pointer_agu_reference_f32(const float* input, float* output,
                                            std::size_t count) {
  for (std::size_t index = 0; index < count; ++index) {
    output[index] = input[index] + input[count + index] + input[2 * count + index];
  }
}

extern "C" void dot_product_reference_f32(const float* input, float* output,
                                            std::size_t count) {
  float sum = 0.0f;
  for (std::size_t index = 0; index < count; ++index) {
    sum = std::fma(input[index], input[count + index], sum);
  }
  output[0] = sum;
}

extern "C" void vector_reduction_reference_f32(const float* input,
                                                 float* output,
                                                 std::size_t count) {
  float sum = 0.0f;
  float maximum = -std::numeric_limits<float>::infinity();
  for (std::size_t index = 0; index < count; ++index) {
    sum += input[index];
    maximum = std::max(maximum, input[index]);
  }
  output[0] = sum;
  output[1] = maximum;
}

extern "C" void conversion_reference_f32(const float* input, float* output,
                                           std::size_t count) {
  for (std::size_t index = 0; index < count; ++index) {
    output[index] = static_cast<float>(static_cast<std::int32_t>(input[index]));
  }
}

extern "C" void vector_integer_reference_f32(const float* input, float* output,
                                               std::size_t count) {
  for (std::size_t index = 0; index < count; ++index) {
    output[index] = StoreBits((LoadBits(input[index]) + 17U) << 1U);
  }
}

extern "C" void mixed_compute_reference_f32(const float* input, float* output,
                                              std::size_t count) {
  for (std::size_t index = 0; index < count; ++index) {
    const std::int32_t integer =
        (static_cast<std::int32_t>(input[index]) + 17) << 1;
    output[index] = std::fma(static_cast<float>(integer), 0.25f, input[index]);
  }
}
