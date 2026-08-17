#include "common/kernel_interface.h"

#include <riscv_vector.h>

extern "C" __attribute__((noinline)) void vector_copy_rvv_f32(
    const float* input, float* output, std::size_t count) {
  for (std::size_t index = 0; index < count;) {
    const std::size_t vl = __riscv_vsetvl_e32m1(count - index);
    const vfloat32m1_t value = __riscv_vle32_v_f32m1(input + index, vl);
    __riscv_vse32_v_f32m1(output + index, value, vl);
    index += vl;
  }
}
