#include "common/kernel_interface.h"

#include <immintrin.h>

extern "C" __attribute__((noinline)) void mixed_compute_avx512_f32(
    const float* input, float* output, std::size_t count) {
  const __m512i addend = _mm512_set1_epi32(17);
  const __m512 scale = _mm512_set1_ps(0.25f);
  for (std::size_t index = 0; index < count; index += 16) {
    const __m512 value = _mm512_loadu_ps(input + index);
    __m512i integer = _mm512_cvttps_epi32(value);
    integer = _mm512_slli_epi32(_mm512_add_epi32(integer, addend), 1);
    const __m512 converted = _mm512_cvtepi32_ps(integer);
    _mm512_storeu_ps(output + index,
                     _mm512_fmadd_ps(converted, scale, value));
  }
}
