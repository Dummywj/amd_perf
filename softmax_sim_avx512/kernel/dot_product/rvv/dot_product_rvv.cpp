#include "common/kernel_interface.h"

#include <riscv_vector.h>

extern "C" __attribute__((noinline)) void dot_product_rvv_f32(
    const float* input, float* output, std::size_t count) {
  float total = 0.0f;
  for (std::size_t index = 0; index < count;) {
    const std::size_t vl = __riscv_vsetvl_e32m1(count - index);
    const vfloat32m1_t x = __riscv_vle32_v_f32m1(input + index, vl);
    const vfloat32m1_t y = __riscv_vle32_v_f32m1(input + count + index, vl);
    const vfloat32m1_t product = __riscv_vfmul_vv_f32m1(x, y, vl);
    const vfloat32m1_t seed = __riscv_vfmv_v_f_f32m1(0.0f, vl);
    const vfloat32m1_t reduced =
        __riscv_vfredusum_vs_f32m1_f32m1(product, seed, vl);
    total += __riscv_vfmv_f_s_f32m1_f32(reduced);
    index += vl;
  }
  output[0] = total;
}
