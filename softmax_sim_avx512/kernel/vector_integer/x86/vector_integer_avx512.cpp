#include "common/kernel_interface.h"

#include <immintrin.h>

extern "C" __attribute__((noinline)) void vector_integer_avx512_f32(
    const float* input, float* output, std::size_t count) {
  const __m512i addend = _mm512_set1_epi32(17);
  for (std::size_t index = 0; index < count; index += 16) {
    const __m512i value = _mm512_loadu_si512(input + index);
    const __m512i result = _mm512_slli_epi32(_mm512_add_epi32(value, addend), 1);
    _mm512_storeu_si512(output + index, result);
  }
}
