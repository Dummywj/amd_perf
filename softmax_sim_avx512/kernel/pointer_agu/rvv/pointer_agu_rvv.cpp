#include "common/kernel_interface.h"

#include <riscv_vector.h>

extern "C" __attribute__((noinline)) void pointer_agu_rvv_f32(
    const float* input, float* output, std::size_t count) {
  for (std::size_t index = 0; index < count;) {
    const std::size_t vl = __riscv_vsetvl_e32m1(count - index);
    const vfloat32m1_t x = __riscv_vle32_v_f32m1(input + index, vl);
    const vfloat32m1_t y = __riscv_vle32_v_f32m1(input + count + index, vl);
    const vfloat32m1_t z = __riscv_vle32_v_f32m1(input + 2 * count + index, vl);
    const vfloat32m1_t sum = __riscv_vfadd_vv_f32m1(
        __riscv_vfadd_vv_f32m1(x, y, vl), z, vl);
    __riscv_vse32_v_f32m1(output + index, sum, vl);
    index += vl;
  }
}
