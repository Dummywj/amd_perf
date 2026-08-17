#include "common/kernel_interface.h"

#include <riscv_vector.h>

extern "C" __attribute__((noinline)) void mixed_compute_rvv_f32(
    const float* input, float* output, std::size_t count) {
  for (std::size_t index = 0; index < count;) {
    const std::size_t vl = __riscv_vsetvl_e32m1(count - index);
    const vfloat32m1_t value = __riscv_vle32_v_f32m1(input + index, vl);
    vint32m1_t integer = __riscv_vfcvt_rtz_x_f_v_i32m1(value, vl);
    integer = __riscv_vadd_vx_i32m1(integer, 17, vl);
    integer = __riscv_vsll_vx_i32m1(integer, 1, vl);
    const vfloat32m1_t converted = __riscv_vfcvt_f_x_v_f32m1(integer, vl);
    const vfloat32m1_t result =
        __riscv_vfmacc_vf_f32m1(value, 0.25f, converted, vl);
    __riscv_vse32_v_f32m1(output + index, result, vl);
    index += vl;
  }
}
