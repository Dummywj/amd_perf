#include "common/kernel_interface.h"

#include <riscv_vector.h>

extern "C" __attribute__((noinline)) void fma_throughput_rvv_f32(
    const float* input, float* output, std::size_t count) {
  for (std::size_t index = 0; index < count;) {
    const std::size_t vl = __riscv_vsetvl_e32m1(count - index);
    if (count - index >= 8 * vl) {
      const vfloat32m1_t addend = __riscv_vfmv_v_f_f32m1(0.0003f, vl);
      vfloat32m1_t value0 = __riscv_vle32_v_f32m1(input + index, vl);
      vfloat32m1_t value1 = __riscv_vle32_v_f32m1(input + index + vl, vl);
      vfloat32m1_t value2 = __riscv_vle32_v_f32m1(input + index + 2 * vl, vl);
      vfloat32m1_t value3 = __riscv_vle32_v_f32m1(input + index + 3 * vl, vl);
      vfloat32m1_t value4 = __riscv_vle32_v_f32m1(input + index + 4 * vl, vl);
      vfloat32m1_t value5 = __riscv_vle32_v_f32m1(input + index + 5 * vl, vl);
      vfloat32m1_t value6 = __riscv_vle32_v_f32m1(input + index + 6 * vl, vl);
      vfloat32m1_t value7 = __riscv_vle32_v_f32m1(input + index + 7 * vl, vl);
      for (int round = 0; round < 16; ++round) {
        value0 = __riscv_vfmacc_vf_f32m1(addend, 1.0001f, value0, vl);
        value1 = __riscv_vfmacc_vf_f32m1(addend, 1.0001f, value1, vl);
        value2 = __riscv_vfmacc_vf_f32m1(addend, 1.0001f, value2, vl);
        value3 = __riscv_vfmacc_vf_f32m1(addend, 1.0001f, value3, vl);
        value4 = __riscv_vfmacc_vf_f32m1(addend, 1.0001f, value4, vl);
        value5 = __riscv_vfmacc_vf_f32m1(addend, 1.0001f, value5, vl);
        value6 = __riscv_vfmacc_vf_f32m1(addend, 1.0001f, value6, vl);
        value7 = __riscv_vfmacc_vf_f32m1(addend, 1.0001f, value7, vl);
      }
      __riscv_vse32_v_f32m1(output + index, value0, vl);
      __riscv_vse32_v_f32m1(output + index + vl, value1, vl);
      __riscv_vse32_v_f32m1(output + index + 2 * vl, value2, vl);
      __riscv_vse32_v_f32m1(output + index + 3 * vl, value3, vl);
      __riscv_vse32_v_f32m1(output + index + 4 * vl, value4, vl);
      __riscv_vse32_v_f32m1(output + index + 5 * vl, value5, vl);
      __riscv_vse32_v_f32m1(output + index + 6 * vl, value6, vl);
      __riscv_vse32_v_f32m1(output + index + 7 * vl, value7, vl);
      index += 8 * vl;
      continue;
    }
    vfloat32m1_t value = __riscv_vle32_v_f32m1(input + index, vl);
    const vfloat32m1_t addend = __riscv_vfmv_v_f_f32m1(0.0003f, vl);
    for (int round = 0; round < 16; ++round)
      value = __riscv_vfmacc_vf_f32m1(addend, 1.0001f, value, vl);
    __riscv_vse32_v_f32m1(output + index, value, vl);
    index += vl;
  }
}
