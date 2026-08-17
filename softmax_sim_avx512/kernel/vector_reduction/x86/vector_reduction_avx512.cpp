#include "common/kernel_interface.h"

#include <immintrin.h>

extern "C" __attribute__((noinline)) void vector_reduction_avx512_f32(
    const float* input, float* output, std::size_t count) {
  __m512 sum = _mm512_setzero_ps();
  __m512 maximum = _mm512_set1_ps(-__builtin_inff());
  for (std::size_t index = 0; index < count; index += 16) {
    const __m512 value = _mm512_loadu_ps(input + index);
    sum = _mm512_add_ps(sum, value);
    maximum = _mm512_max_ps(maximum, value);
  }
  output[0] = _mm512_reduce_add_ps(sum);
  output[1] = _mm512_reduce_max_ps(maximum);
}
