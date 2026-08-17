#include "common/kernel_interface.h"

#include <riscv_vector.h>

extern "C" __attribute__((noinline, optimize("no-tree-loop-optimize"))) void
fma_latency_rvv_f32(
    const float* input, float* output, std::size_t count) {
  constexpr std::size_t kLogicalLanes = 16;
  std::size_t requested_vl = kLogicalLanes;
  asm volatile("" : "+r"(requested_vl));
  const std::size_t vl = __riscv_vsetvl_e32m4(requested_vl);
  vfloat32m4_t state = __riscv_vfmv_v_f_f32m4(0.0f, vl);
  for (std::size_t index = 0; index < count;) {
    state = __riscv_vfadd_vv_f32m4(
        state, __riscv_vle32_v_f32m4(input + index, vl), vl);
    const vfloat32m4_t addend = __riscv_vfmv_v_f_f32m4(0.0003f, vl);
    for (int round = 0; round < 16; ++round)
      state = __riscv_vfmacc_vf_f32m4(addend, 1.0001f, state, vl);
    __riscv_vse32_v_f32m4(output + index, state, vl);
    index += vl;
  }
}
