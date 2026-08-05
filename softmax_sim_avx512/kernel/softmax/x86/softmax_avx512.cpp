#include "common/softmax_interface.h"

#include <immintrin.h>

#include "common/softmax_constants.h"

namespace {

using namespace softmax_sim::kernel::softmax;

inline __m512 ExpApprox(__m512 value) {
  value = _mm512_max_ps(value, _mm512_set1_ps(kExpInputMin));
  value = _mm512_min_ps(value, _mm512_setzero_ps());

  const __m512 scaled = _mm512_mul_ps(value, _mm512_set1_ps(kLog2E));
  const __m512i exponent = _mm512_cvttps_epi32(scaled);
  const __m512 exponent_fp = _mm512_cvtepi32_ps(exponent);
  const __m512 reduced =
      _mm512_fnmadd_ps(exponent_fp, _mm512_set1_ps(kLn2), value);

  __m512 polynomial = _mm512_set1_ps(kExpC7);
  polynomial = _mm512_fmadd_ps(polynomial, reduced, _mm512_set1_ps(kExpC6));
  polynomial = _mm512_fmadd_ps(polynomial, reduced, _mm512_set1_ps(kExpC5));
  polynomial = _mm512_fmadd_ps(polynomial, reduced, _mm512_set1_ps(kExpC4));
  polynomial = _mm512_fmadd_ps(polynomial, reduced, _mm512_set1_ps(kExpC3));
  polynomial = _mm512_fmadd_ps(polynomial, reduced, _mm512_set1_ps(kExpC2));
  polynomial = _mm512_fmadd_ps(polynomial, reduced, _mm512_set1_ps(kExpC1));
  polynomial = _mm512_fmadd_ps(polynomial, reduced, _mm512_set1_ps(kExpC0));

  const __m512i exponent_bits =
      _mm512_slli_epi32(_mm512_add_epi32(exponent, _mm512_set1_epi32(127)),
                        23);
  return _mm512_mul_ps(polynomial, _mm512_castsi512_ps(exponent_bits));
}

}  // namespace

extern "C" __attribute__((noinline)) void softmax_avx512_f32(
    const float* input, float* output, std::size_t count) {
  __m512 vector_max = _mm512_set1_ps(-__builtin_inff());
  for (std::size_t index = 0; index < count; index += 16) {
    vector_max = _mm512_max_ps(vector_max, _mm512_loadu_ps(input + index));
  }
  const float maximum = _mm512_reduce_max_ps(vector_max);

  const __m512 maximum_vector = _mm512_set1_ps(maximum);
  __m512 vector_sum = _mm512_setzero_ps();
  for (std::size_t index = 0; index < count; index += 16) {
    const __m512 centered =
        _mm512_sub_ps(_mm512_loadu_ps(input + index), maximum_vector);
    const __m512 exponent = ExpApprox(centered);
    _mm512_storeu_ps(output + index, exponent);
    vector_sum = _mm512_add_ps(vector_sum, exponent);
  }

  const float inverse_sum = 1.0f / _mm512_reduce_add_ps(vector_sum);
  const __m512 inverse_sum_vector = _mm512_set1_ps(inverse_sum);
  for (std::size_t index = 0; index < count; index += 16) {
    const __m512 normalized = _mm512_mul_ps(
        _mm512_loadu_ps(output + index), inverse_sum_vector);
    _mm512_storeu_ps(output + index, normalized);
  }
}
