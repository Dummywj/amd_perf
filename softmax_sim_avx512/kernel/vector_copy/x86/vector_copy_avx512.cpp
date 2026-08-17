#include "common/kernel_interface.h"

#include <immintrin.h>

extern "C" __attribute__((noinline)) void vector_copy_avx512_f32(
    const float* input, float* output, std::size_t count) {
  for (std::size_t index = 0; index < count; index += 16)
    _mm512_storeu_ps(output + index, _mm512_loadu_ps(input + index));
}
