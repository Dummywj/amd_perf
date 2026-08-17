#include "common/kernel_interface.h"

#include <immintrin.h>

extern "C" __attribute__((noinline)) void fma_throughput_avx512_f32(
    const float* input, float* output, std::size_t count) {
  const __m512 multiplier = _mm512_set1_ps(1.0001f);
  const __m512 addend = _mm512_set1_ps(0.0003f);
  std::size_t index = 0;
  for (; index + 128 <= count; index += 128) {
    __m512 values[8];
    for (int lane = 0; lane < 8; ++lane)
      values[lane] = _mm512_loadu_ps(input + index + lane * 16);
    for (int round = 0; round < 16; ++round) {
      for (int lane = 0; lane < 8; ++lane)
        values[lane] = _mm512_fmadd_ps(values[lane], multiplier, addend);
    }
    for (int lane = 0; lane < 8; ++lane)
      _mm512_storeu_ps(output + index + lane * 16, values[lane]);
  }
  for (; index < count; index += 16) {
    __m512 value = _mm512_loadu_ps(input + index);
    for (int round = 0; round < 16; ++round)
      value = _mm512_fmadd_ps(value, multiplier, addend);
    _mm512_storeu_ps(output + index, value);
  }
}
