#include "common/kernel_interface.h"

#include <immintrin.h>

extern "C" __attribute__((noinline)) void axpy_avx512_f32(
    const float* input, float* output, std::size_t count) {
  const __m512 scale = _mm512_set1_ps(1.25f);
  for (std::size_t index = 0; index < count; index += 16) {
    const __m512 x = _mm512_loadu_ps(input + index);
    const __m512 y = _mm512_loadu_ps(input + count + index);
    _mm512_storeu_ps(output + index, _mm512_fmadd_ps(scale, x, y));
  }
}
