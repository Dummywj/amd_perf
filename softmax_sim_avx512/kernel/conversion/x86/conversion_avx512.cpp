#include "common/kernel_interface.h"

#include <immintrin.h>

extern "C" __attribute__((noinline)) void conversion_avx512_f32(
    const float* input, float* output, std::size_t count) {
  for (std::size_t index = 0; index < count; index += 16) {
    const __m512 value = _mm512_loadu_ps(input + index);
    const __m512i integer = _mm512_cvttps_epi32(value);
    _mm512_storeu_ps(output + index, _mm512_cvtepi32_ps(integer));
  }
}
