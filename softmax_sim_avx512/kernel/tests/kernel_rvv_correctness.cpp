#include "common/kernel_registry_rvv.h"

#include <algorithm>
#include <cmath>
#include <cstddef>
#include <cstdint>
#include <cstdio>
#include <cstring>
#include <vector>

namespace {

void FillInput(std::vector<float>* input, std::size_t count,
               std::size_t vectors, bool bit_pattern) {
  std::uint32_t state = 0x12345678U;
  for (std::size_t index = 0; index < count * vectors; ++index) {
    state = state * 1664525U + 1013904223U;
    if (bit_pattern) {
      const std::int32_t value = static_cast<std::int32_t>(state & 0x000fffffU);
      std::memcpy(&(*input)[index], &value, sizeof(value));
    } else {
      const std::int32_t signed_value =
          static_cast<std::int32_t>(state >> 8) - (1 << 23);
      (*input)[index] =
          static_cast<float>(signed_value) / static_cast<float>(1U << 20);
    }
  }
}

bool Check(const RvvKernelSpec& spec, std::size_t count) {
  const std::size_t output_count = spec.output_count ? spec.output_count : count;
  std::vector<float> input(count * spec.input_vectors);
  std::vector<float> reference(output_count);
  std::vector<float> actual(output_count);
  FillInput(&input, count, spec.input_vectors, spec.name == "vector_integer");
  spec.reference(input.data(), reference.data(), count);
  spec.rvv(input.data(), actual.data(), count);

  float maximum_error = 0.0f;
  bool bit_equal = true;
  for (std::size_t index = 0; index < output_count; ++index) {
    if (!std::isfinite(actual[index]) || !std::isfinite(reference[index])) {
      maximum_error = __builtin_inff();
    } else {
      maximum_error =
          std::max(maximum_error, std::abs(actual[index] - reference[index]));
    }
    bit_equal &=
        std::memcmp(&actual[index], &reference[index], sizeof(float)) == 0;
  }
  const bool passed = spec.tolerance == 0.0f ? bit_equal
                                             : maximum_error <= spec.tolerance;
  std::printf("kernel=%.*s n=%zu max_abs=%g %s\n",
              static_cast<int>(spec.name.size()), spec.name.data(), count,
              maximum_error, passed ? "PASS" : "FAIL");
  return passed;
}

bool CheckFmaLatencyCarriesState() {
  constexpr std::size_t count = 32;
  std::vector<float> input(count, 0.0f);
  std::vector<float> reference(count);
  std::vector<float> actual(count);
  input[0] = 1.0f;
  fma_latency_reference_f32(input.data(), reference.data(), count);
  fma_latency_rvv_f32(input.data(), actual.data(), count);
  const bool carries_state = reference[16] > reference[0];
  const bool bit_equal =
      std::memcmp(actual.data(), reference.data(), count * sizeof(float)) == 0;
  std::printf("kernel=fma_latency cross_block_dependency %s\n",
              carries_state && bit_equal ? "PASS" : "FAIL");
  return carries_state && bit_equal;
}

}  // namespace

int main() {
  bool passed = true;
  for (const RvvKernelSpec& spec : kRvvKernelSpecs) {
    for (std::size_t count : {512U, 1024U, 2048U}) {
      passed &= Check(spec, count);
    }
  }
  passed &= CheckFmaLatencyCarriesState();
  return passed ? 0 : 1;
}
