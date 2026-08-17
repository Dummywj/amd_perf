#include "common/kernel_interface.h"

#include <immintrin.h>

extern "C" __attribute__((noinline)) void fma_latency_avx512_f32(
    const float* input, float* output, std::size_t count) {
  const __m512 multiplier = _mm512_set1_ps(1.0001f);
  const __m512 addend = _mm512_set1_ps(0.0003f);
  __m512 state = _mm512_setzero_ps();
  for (std::size_t index = 0; index < count; index += 16) {
    state = _mm512_add_ps(state, _mm512_loadu_ps(input + index));
    for (int round = 0; round < 16; ++round)
      state = _mm512_fmadd_ps(state, multiplier, addend);
    _mm512_storeu_ps(output + index, state);
  }
}
