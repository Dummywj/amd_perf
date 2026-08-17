#include "common/kernel_interface.h"

#include <immintrin.h>

extern "C" __attribute__((noinline)) void dot_product_avx512_f32(
    const float* input, float* output, std::size_t count) {
  __m512 sum = _mm512_setzero_ps();
  for (std::size_t index = 0; index < count; index += 16) {
    sum = _mm512_fmadd_ps(_mm512_loadu_ps(input + index),
                          _mm512_loadu_ps(input + count + index), sum);
  }
  output[0] = _mm512_reduce_add_ps(sum);
}
