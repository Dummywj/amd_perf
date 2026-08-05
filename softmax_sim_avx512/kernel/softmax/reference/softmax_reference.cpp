#include "common/softmax_interface.h"

#include <algorithm>
#include <cmath>
#include <limits>

#include "common/exp_approx.h"

extern "C" void softmax_reference_f32(const float* input, float* output,
                                      std::size_t count) {
  float maximum = -std::numeric_limits<float>::infinity();
  for (std::size_t index = 0; index < count; ++index) {
    maximum = std::max(maximum, input[index]);
  }

  double sum = 0.0;
  for (std::size_t index = 0; index < count; ++index) {
    const float value = std::exp(input[index] - maximum);
    output[index] = value;
    sum += value;
  }

  const float inverse_sum = 1.0f / static_cast<float>(sum);
  for (std::size_t index = 0; index < count; ++index) {
    output[index] *= inverse_sum;
  }
}

extern "C" void softmax_approx_reference_f32(const float* input,
                                             float* output,
                                             std::size_t count) {
  float maximum = -std::numeric_limits<float>::infinity();
  for (std::size_t index = 0; index < count; ++index) {
    maximum = std::max(maximum, input[index]);
  }

  float sum = 0.0f;
  for (std::size_t index = 0; index < count; ++index) {
    const float value = softmax_sim::kernel::softmax::ExpApproxScalar(
        input[index] - maximum);
    output[index] = value;
    sum += value;
  }

  const float inverse_sum = 1.0f / sum;
  for (std::size_t index = 0; index < count; ++index) {
    output[index] *= inverse_sum;
  }
}
