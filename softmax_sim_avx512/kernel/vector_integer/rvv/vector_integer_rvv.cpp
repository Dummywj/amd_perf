#include "common/kernel_interface.h"

#include <riscv_vector.h>

extern "C" __attribute__((noinline)) void vector_integer_rvv_f32(
    const float* input, float* output, std::size_t count) {
  for (std::size_t index = 0; index < count;) {
    const std::size_t vl = __riscv_vsetvl_e32m1(count - index);
    vuint32m1_t value = __riscv_vreinterpret_v_f32m1_u32m1(
        __riscv_vle32_v_f32m1(input + index, vl));
    value = __riscv_vadd_vx_u32m1(value, 17U, vl);
    value = __riscv_vsll_vx_u32m1(value, 1U, vl);
    __riscv_vse32_v_f32m1(
        output + index, __riscv_vreinterpret_v_u32m1_f32m1(value), vl);
    index += vl;
  }
}
