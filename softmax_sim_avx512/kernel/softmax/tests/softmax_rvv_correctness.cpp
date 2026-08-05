#include "common/softmax_interface.h"

#include <algorithm>
#include <cmath>
#include <cstddef>
#include <cstdint>
#include <cstdio>
#include <numeric>
#include <vector>

namespace {

enum class InputCase { kRandom, kEqual, kRamp, kExtreme };

const char* CaseName(InputCase input_case) {
  switch (input_case) {
    case InputCase::kRandom:
      return "random";
    case InputCase::kEqual:
      return "equal";
    case InputCase::kRamp:
      return "ramp";
    case InputCase::kExtreme:
      return "extreme";
  }
  return "unknown";
}

void FillInput(std::vector<float>* input, InputCase input_case) {
  std::uint32_t state = 0x12345678U;
  for (std::size_t index = 0; index < input->size(); ++index) {
    switch (input_case) {
      case InputCase::kRandom:
        state = state * 1664525U + 1013904223U;
        (*input)[index] =
            static_cast<float>(static_cast<std::int32_t>(state >> 8)) /
            static_cast<float>(1U << 23);
        break;
      case InputCase::kEqual:
        (*input)[index] = 3.25f;
        break;
      case InputCase::kRamp:
        (*input)[index] = static_cast<float>(index) * 0.125f - 32.0f;
        break;
      case InputCase::kExtreme:
        (*input)[index] = index % 17 == 0
                              ? 10.0f
                              : -100.0f - static_cast<float>(index % 31);
        break;
    }
  }
}

std::size_t ReadVlenBits() {
  std::size_t vlen_bytes = 0;
  asm volatile("csrr %0, vlenb" : "=r"(vlen_bytes));
  return vlen_bytes * 8;
}

bool CheckCase(std::size_t count, InputCase input_case) {
  std::vector<float> input(count);
  std::vector<float> reference(count);
  std::vector<float> approximate(count);
  std::vector<float> vectorized(count);
  FillInput(&input, input_case);

  softmax_reference_f32(input.data(), reference.data(), count);
  softmax_approx_reference_f32(input.data(), approximate.data(), count);
  softmax_rvv_f32(input.data(), vectorized.data(), count);

  float approximation_error = 0.0f;
  float vector_error = 0.0f;
  bool valid_output = true;
  for (std::size_t index = 0; index < count; ++index) {
    approximation_error =
        std::max(approximation_error,
                 std::abs(approximate[index] - reference[index]));
    vector_error =
        std::max(vector_error,
                 std::abs(vectorized[index] - approximate[index]));
    valid_output &= std::isfinite(vectorized[index]) && vectorized[index] >= 0;
  }
  const double output_sum =
      std::accumulate(vectorized.begin(), vectorized.end(), 0.0);

  const bool passed = valid_output && approximation_error <= 1.0e-5f &&
                      vector_error <= 2.0e-6f &&
                      std::abs(output_sum - 1.0) <= 2.0e-5;
  std::printf(
      "n=%zu case=%s approx_abs=%g rvv_abs=%g sum=%.9f %s\n", count,
      CaseName(input_case), approximation_error, vector_error, output_sum,
      passed ? "PASS" : "FAIL");
  return passed;
}

}  // namespace

int main() {
  std::printf("RVV VLEN=%zu bits\n", ReadVlenBits());

  bool passed = true;
  constexpr std::size_t kCounts[] = {1,  3,  15,  16, 17,
                                     31, 64, 255, 4096};
  constexpr InputCase kCases[] = {InputCase::kRandom, InputCase::kEqual,
                                  InputCase::kRamp, InputCase::kExtreme};
  for (std::size_t count : kCounts) {
    for (InputCase input_case : kCases) {
      passed &= CheckCase(count, input_case);
    }
  }
  return passed ? 0 : 1;
}
