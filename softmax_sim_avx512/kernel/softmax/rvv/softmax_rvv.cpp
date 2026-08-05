#include "common/softmax_interface.h"

#include <riscv_vector.h>

#include "common/softmax_constants.h"

namespace {

using namespace softmax_sim::kernel::softmax;

inline vfloat32m1_t ExpApprox(vfloat32m1_t value, std::size_t vl) {
  value = __riscv_vfmax_vf_f32m1(value, kExpInputMin, vl);
  value = __riscv_vfmin_vf_f32m1(value, 0.0f, vl);

  const vfloat32m1_t scaled =
      __riscv_vfmul_vf_f32m1(value, kLog2E, vl);
  const vint32m1_t exponent =
      __riscv_vfcvt_rtz_x_f_v_i32m1(scaled, vl);
  const vfloat32m1_t exponent_fp =
      __riscv_vfcvt_f_x_v_f32m1(exponent, vl);
  const vfloat32m1_t reduced = __riscv_vfsub_vv_f32m1(
      value, __riscv_vfmul_vf_f32m1(exponent_fp, kLn2, vl), vl);

  vfloat32m1_t polynomial = __riscv_vfmv_v_f_f32m1(kExpC7, vl);
  polynomial = __riscv_vfmacc_vv_f32m1(
      __riscv_vfmv_v_f_f32m1(kExpC6, vl), polynomial, reduced, vl);
  polynomial = __riscv_vfmacc_vv_f32m1(
      __riscv_vfmv_v_f_f32m1(kExpC5, vl), polynomial, reduced, vl);
  polynomial = __riscv_vfmacc_vv_f32m1(
      __riscv_vfmv_v_f_f32m1(kExpC4, vl), polynomial, reduced, vl);
  polynomial = __riscv_vfmacc_vv_f32m1(
      __riscv_vfmv_v_f_f32m1(kExpC3, vl), polynomial, reduced, vl);
  polynomial = __riscv_vfmacc_vv_f32m1(
      __riscv_vfmv_v_f_f32m1(kExpC2, vl), polynomial, reduced, vl);
  polynomial = __riscv_vfmacc_vv_f32m1(
      __riscv_vfmv_v_f_f32m1(kExpC1, vl), polynomial, reduced, vl);
  polynomial = __riscv_vfmacc_vv_f32m1(
      __riscv_vfmv_v_f_f32m1(kExpC0, vl), polynomial, reduced, vl);

  const vint32m1_t exponent_bits = __riscv_vsll_vx_i32m1(
      __riscv_vadd_vx_i32m1(exponent, 127, vl), 23, vl);
  return __riscv_vfmul_vv_f32m1(
      polynomial, __riscv_vreinterpret_v_i32m1_f32m1(exponent_bits), vl);
}

float ReduceMax(vfloat32m1_t value, float seed, std::size_t vl) {
  const vfloat32m1_t seed_vector = __riscv_vfmv_v_f_f32m1(seed, vl);
  const vfloat32m1_t reduced =
      __riscv_vfredmax_vs_f32m1_f32m1(value, seed_vector, vl);
  return __riscv_vfmv_f_s_f32m1_f32(reduced);
}

float ReduceSum(vfloat32m1_t value, std::size_t vl) {
  const vfloat32m1_t zero = __riscv_vfmv_v_f_f32m1(0.0f, vl);
  const vfloat32m1_t reduced =
      __riscv_vfredusum_vs_f32m1_f32m1(value, zero, vl);
  return __riscv_vfmv_f_s_f32m1_f32(reduced);
}

}  // namespace

extern "C" __attribute__((noinline)) void softmax_rvv_f32(
    const float* input, float* output, std::size_t count) {
  float maximum = -__builtin_inff();
  for (std::size_t index = 0; index < count;) {
    const std::size_t vl = __riscv_vsetvl_e32m1(count - index);
    const vfloat32m1_t value =
        __riscv_vle32_v_f32m1(input + index, vl);
    maximum = ReduceMax(value, maximum, vl);
    index += vl;
  }

  float sum = 0.0f;
  for (std::size_t index = 0; index < count;) {
    const std::size_t vl = __riscv_vsetvl_e32m1(count - index);
    const vfloat32m1_t value =
        __riscv_vle32_v_f32m1(input + index, vl);
    const vfloat32m1_t centered =
        __riscv_vfsub_vf_f32m1(value, maximum, vl);
    const vfloat32m1_t exponent = ExpApprox(centered, vl);
    __riscv_vse32_v_f32m1(output + index, exponent, vl);
    sum += ReduceSum(exponent, vl);
    index += vl;
  }

  const float inverse_sum = 1.0f / sum;
  for (std::size_t index = 0; index < count;) {
    const std::size_t vl = __riscv_vsetvl_e32m1(count - index);
    const vfloat32m1_t value =
        __riscv_vle32_v_f32m1(output + index, vl);
    __riscv_vse32_v_f32m1(
        output + index,
        __riscv_vfmul_vf_f32m1(value, inverse_sum, vl), vl);
    index += vl;
  }
}
