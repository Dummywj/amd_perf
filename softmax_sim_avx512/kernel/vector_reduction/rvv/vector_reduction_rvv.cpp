#include "common/kernel_interface.h"

#include <riscv_vector.h>

extern "C" __attribute__((noinline)) void vector_reduction_rvv_f32(
    const float* input, float* output, std::size_t count) {
  float total = 0.0f;
  float maximum = -__builtin_inff();
  for (std::size_t index = 0; index < count;) {
    const std::size_t vl = __riscv_vsetvl_e32m1(count - index);
    const vfloat32m1_t value = __riscv_vle32_v_f32m1(input + index, vl);
    const vfloat32m1_t sum_seed = __riscv_vfmv_v_f_f32m1(0.0f, vl);
    const vfloat32m1_t max_seed = __riscv_vfmv_v_f_f32m1(maximum, vl);
    total += __riscv_vfmv_f_s_f32m1_f32(
        __riscv_vfredusum_vs_f32m1_f32m1(value, sum_seed, vl));
    maximum = __riscv_vfmv_f_s_f32m1_f32(
        __riscv_vfredmax_vs_f32m1_f32m1(value, max_seed, vl));
    index += vl;
  }
  output[0] = total;
  output[1] = maximum;
}
