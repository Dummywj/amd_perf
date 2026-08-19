  .section .text
  .align 2

  .macro XS_BEGIN
  vsetvli t0, zero, e32, m1, ta, ma
  vle32.v v16, (a0)
  vle32.v v17, (a0)
  .endm

  .macro XS_END
  vse32.v v0, (a1)
  ret
  .endm

  .globl xsai_mb_loop_baseline
  .type xsai_mb_loop_baseline, @function
xsai_mb_loop_baseline:
  .p2align 4
1:
  .rept 16
  nop
  .endr
  addi a2, a2, -1
  bnez a2, 1b
  ret
  .size xsai_mb_loop_baseline, .-xsai_mb_loop_baseline

  .globl xsai_mb_scalar_alu_dependency
  .type xsai_mb_scalar_alu_dependency, @function
xsai_mb_scalar_alu_dependency:
  li t0, 1
  .p2align 4
1:
  .rept 16
  addi t0, t0, 1
  .endr
  addi a2, a2, -1
  bnez a2, 1b
  sw t0, 0(a1)
  ret
  .size xsai_mb_scalar_alu_dependency, .-xsai_mb_scalar_alu_dependency

  .globl xsai_mb_scalar_alu_throughput
  .type xsai_mb_scalar_alu_throughput, @function
xsai_mb_scalar_alu_throughput:
  li t0, 1
  li t1, 2
  li t2, 3
  li t3, 4
  li t4, 5
  li t5, 6
  li t6, 7
  .p2align 4
1:
  addi t0, t0, 1
  addi t1, t1, 1
  addi t2, t2, 1
  addi t3, t3, 1
  addi t4, t4, 1
  addi t5, t5, 1
  addi t6, t6, 1
  addi a3, a3, 1
  addi t0, t0, 1
  addi t1, t1, 1
  addi t2, t2, 1
  addi t3, t3, 1
  addi t4, t4, 1
  addi t5, t5, 1
  addi t6, t6, 1
  addi a3, a3, 1
  addi a2, a2, -1
  bnez a2, 1b
  sw t0, 0(a1)
  ret
  .size xsai_mb_scalar_alu_throughput, .-xsai_mb_scalar_alu_throughput

  .globl xsai_mb_scalar_fp_add_dependency
  .type xsai_mb_scalar_fp_add_dependency, @function
xsai_mb_scalar_fp_add_dependency:
  flw ft0, 0(a0)
  flw ft1, 4(a0)
  .p2align 4
1:
  .rept 16
  fadd.s ft0, ft0, ft1
  .endr
  addi a2, a2, -1
  bnez a2, 1b
  fsw ft0, 0(a1)
  ret
  .size xsai_mb_scalar_fp_add_dependency, .-xsai_mb_scalar_fp_add_dependency

  .globl xsai_mb_scalar_fp_add_throughput
  .type xsai_mb_scalar_fp_add_throughput, @function
xsai_mb_scalar_fp_add_throughput:
  flw ft8, 0(a0)
  flw ft9, 4(a0)
  .p2align 4
1:
  fadd.s ft0, ft8, ft9
  fadd.s ft1, ft8, ft9
  fadd.s ft2, ft8, ft9
  fadd.s ft3, ft8, ft9
  fadd.s ft4, ft8, ft9
  fadd.s ft5, ft8, ft9
  fadd.s ft6, ft8, ft9
  fadd.s ft7, ft8, ft9
  fadd.s fa0, ft8, ft9
  fadd.s fa1, ft8, ft9
  fadd.s fa2, ft8, ft9
  fadd.s fa3, ft8, ft9
  fadd.s fa4, ft8, ft9
  fadd.s fa5, ft8, ft9
  fadd.s fa6, ft8, ft9
  fadd.s fa7, ft8, ft9
  addi a2, a2, -1
  bnez a2, 1b
  fsw ft0, 0(a1)
  ret
  .size xsai_mb_scalar_fp_add_throughput, .-xsai_mb_scalar_fp_add_throughput

  .globl xsai_mb_scalar_fp_div_dependency
  .type xsai_mb_scalar_fp_div_dependency, @function
xsai_mb_scalar_fp_div_dependency:
  flw ft0, 0(a0)
  flw ft1, 4(a0)
  .p2align 4
1:
  .rept 8
  fdiv.s ft0, ft0, ft1
  .endr
  addi a2, a2, -1
  bnez a2, 1b
  fsw ft0, 0(a1)
  ret
  .size xsai_mb_scalar_fp_div_dependency, .-xsai_mb_scalar_fp_div_dependency

  .globl xsai_mb_vset_throughput
  .type xsai_mb_vset_throughput, @function
xsai_mb_vset_throughput:
  .p2align 4
1:
  .rept 16
  vsetvli zero, zero, e32, m1, ta, ma
  .endr
  addi a2, a2, -1
  bnez a2, 1b
  ret
  .size xsai_mb_vset_throughput, .-xsai_mb_vset_throughput

  .globl xsai_mb_fma_dependency
  .type xsai_mb_fma_dependency, @function
xsai_mb_fma_dependency:
  XS_BEGIN
  vmv.v.v v0, v16
  .p2align 4
1:
  .rept 16
  vfmacc.vv v0, v16, v17
  .endr
  addi a2, a2, -1
  bnez a2, 1b
  XS_END
  .size xsai_mb_fma_dependency, .-xsai_mb_fma_dependency

  .globl xsai_mb_fma_throughput
  .type xsai_mb_fma_throughput, @function
xsai_mb_fma_throughput:
  XS_BEGIN
  vmv.v.v v0, v16
  vmv.v.v v1, v16
  vmv.v.v v2, v16
  vmv.v.v v3, v16
  vmv.v.v v4, v16
  vmv.v.v v5, v16
  vmv.v.v v6, v16
  vmv.v.v v7, v16
  vmv.v.v v8, v16
  vmv.v.v v9, v16
  vmv.v.v v10, v16
  vmv.v.v v11, v16
  vmv.v.v v12, v16
  vmv.v.v v13, v16
  vmv.v.v v14, v16
  vmv.v.v v15, v16
  .p2align 4
1:
  vfmacc.vv v8, v16, v17
  vfmacc.vv v9, v16, v17
  vfmacc.vv v10, v16, v17
  vfmacc.vv v11, v16, v17
  vfmacc.vv v12, v16, v17
  vfmacc.vv v13, v16, v17
  vfmacc.vv v14, v16, v17
  vfmacc.vv v15, v16, v17
  vfmacc.vv v0, v16, v17
  vfmacc.vv v1, v16, v17
  vfmacc.vv v2, v16, v17
  vfmacc.vv v3, v16, v17
  vfmacc.vv v4, v16, v17
  vfmacc.vv v5, v16, v17
  vfmacc.vv v6, v16, v17
  vfmacc.vv v7, v16, v17
  addi a2, a2, -1
  bnez a2, 1b
  XS_END
  .size xsai_mb_fma_throughput, .-xsai_mb_fma_throughput

  .globl xsai_mb_fp_add_dependency
  .type xsai_mb_fp_add_dependency, @function
xsai_mb_fp_add_dependency:
  XS_BEGIN
  vmv.v.v v0, v16
  .p2align 4
1:
  .rept 16
  vfadd.vv v0, v0, v17
  .endr
  addi a2, a2, -1
  bnez a2, 1b
  XS_END
  .size xsai_mb_fp_add_dependency, .-xsai_mb_fp_add_dependency

  .globl xsai_mb_fp_add_throughput
  .type xsai_mb_fp_add_throughput, @function
xsai_mb_fp_add_throughput:
  XS_BEGIN
  .p2align 4
1:
  vfadd.vv v0, v16, v17
  vfadd.vv v1, v16, v17
  vfadd.vv v2, v16, v17
  vfadd.vv v3, v16, v17
  vfadd.vv v4, v16, v17
  vfadd.vv v5, v16, v17
  vfadd.vv v6, v16, v17
  vfadd.vv v7, v16, v17
  vfadd.vv v8, v16, v17
  vfadd.vv v9, v16, v17
  vfadd.vv v10, v16, v17
  vfadd.vv v11, v16, v17
  vfadd.vv v12, v16, v17
  vfadd.vv v13, v16, v17
  vfadd.vv v14, v16, v17
  vfadd.vv v15, v16, v17
  addi a2, a2, -1
  bnez a2, 1b
  XS_END
  .size xsai_mb_fp_add_throughput, .-xsai_mb_fp_add_throughput

  .globl xsai_mb_fp_add_same_vd
  .type xsai_mb_fp_add_same_vd, @function
xsai_mb_fp_add_same_vd:
  XS_BEGIN
  .p2align 4
1:
  .rept 16
  vfadd.vv v0, v16, v17
  .endr
  addi a2, a2, -1
  bnez a2, 1b
  XS_END
  .size xsai_mb_fp_add_same_vd, .-xsai_mb_fp_add_same_vd

  .globl xsai_mb_integer_dependency
  .type xsai_mb_integer_dependency, @function
xsai_mb_integer_dependency:
  XS_BEGIN
  vmv.v.v v0, v16
  .p2align 4
1:
  .rept 16
  vadd.vv v0, v0, v17
  .endr
  addi a2, a2, -1
  bnez a2, 1b
  XS_END
  .size xsai_mb_integer_dependency, .-xsai_mb_integer_dependency

  .globl xsai_mb_integer_throughput
  .type xsai_mb_integer_throughput, @function
xsai_mb_integer_throughput:
  XS_BEGIN
  .p2align 4
1:
  vadd.vv v0, v16, v17
  vadd.vv v1, v16, v17
  vadd.vv v2, v16, v17
  vadd.vv v3, v16, v17
  vadd.vv v4, v16, v17
  vadd.vv v5, v16, v17
  vadd.vv v6, v16, v17
  vadd.vv v7, v16, v17
  vadd.vv v8, v16, v17
  vadd.vv v9, v16, v17
  vadd.vv v10, v16, v17
  vadd.vv v11, v16, v17
  vadd.vv v12, v16, v17
  vadd.vv v13, v16, v17
  vadd.vv v14, v16, v17
  vadd.vv v15, v16, v17
  addi a2, a2, -1
  bnez a2, 1b
  XS_END
  .size xsai_mb_integer_throughput, .-xsai_mb_integer_throughput

  .globl xsai_mb_integer_same_vd
  .type xsai_mb_integer_same_vd, @function
xsai_mb_integer_same_vd:
  XS_BEGIN
  .p2align 4
1:
  .rept 16
  vadd.vv v0, v16, v17
  .endr
  addi a2, a2, -1
  bnez a2, 1b
  XS_END
  .size xsai_mb_integer_same_vd, .-xsai_mb_integer_same_vd

  .globl xsai_mb_conversion_dependency
  .type xsai_mb_conversion_dependency, @function
xsai_mb_conversion_dependency:
  XS_BEGIN
  vmv.v.v v0, v16
  .p2align 4
1:
  .rept 8
  vfcvt.rtz.x.f.v v1, v0
  vfcvt.f.x.v v0, v1
  .endr
  addi a2, a2, -1
  bnez a2, 1b
  XS_END
  .size xsai_mb_conversion_dependency, .-xsai_mb_conversion_dependency

  .globl xsai_mb_conversion_throughput
  .type xsai_mb_conversion_throughput, @function
xsai_mb_conversion_throughput:
  XS_BEGIN
  .p2align 4
1:
  vfcvt.rtz.x.f.v v0, v16
  vfcvt.rtz.x.f.v v1, v16
  vfcvt.rtz.x.f.v v2, v16
  vfcvt.rtz.x.f.v v3, v16
  vfcvt.rtz.x.f.v v4, v16
  vfcvt.rtz.x.f.v v5, v16
  vfcvt.rtz.x.f.v v6, v16
  vfcvt.rtz.x.f.v v7, v16
  vfcvt.rtz.x.f.v v8, v16
  vfcvt.rtz.x.f.v v9, v16
  vfcvt.rtz.x.f.v v10, v16
  vfcvt.rtz.x.f.v v11, v16
  vfcvt.rtz.x.f.v v12, v16
  vfcvt.rtz.x.f.v v13, v16
  vfcvt.rtz.x.f.v v14, v16
  vfcvt.rtz.x.f.v v15, v16
  addi a2, a2, -1
  bnez a2, 1b
  XS_END
  .size xsai_mb_conversion_throughput, .-xsai_mb_conversion_throughput

  .globl xsai_mb_conversion_same_vd
  .type xsai_mb_conversion_same_vd, @function
xsai_mb_conversion_same_vd:
  XS_BEGIN
  .p2align 4
1:
  .rept 16
  vfcvt.rtz.x.f.v v0, v16
  .endr
  addi a2, a2, -1
  bnez a2, 1b
  XS_END
  .size xsai_mb_conversion_same_vd, .-xsai_mb_conversion_same_vd

  .globl xsai_mb_conversion_integer
  .type xsai_mb_conversion_integer, @function
xsai_mb_conversion_integer:
  XS_BEGIN
  .p2align 4
1:
  vfcvt.rtz.x.f.v v0, v16
  vadd.vv v8, v16, v17
  vfcvt.rtz.x.f.v v1, v16
  vadd.vv v9, v16, v17
  vfcvt.rtz.x.f.v v2, v16
  vadd.vv v10, v16, v17
  vfcvt.rtz.x.f.v v3, v16
  vadd.vv v11, v16, v17
  vfcvt.rtz.x.f.v v4, v16
  vadd.vv v12, v16, v17
  vfcvt.rtz.x.f.v v5, v16
  vadd.vv v13, v16, v17
  vfcvt.rtz.x.f.v v6, v16
  vadd.vv v14, v16, v17
  vfcvt.rtz.x.f.v v7, v16
  vadd.vv v15, v16, v17
  addi a2, a2, -1
  bnez a2, 1b
  XS_END
  .size xsai_mb_conversion_integer, .-xsai_mb_conversion_integer

  .globl xsai_mb_fma_integer
  .type xsai_mb_fma_integer, @function
xsai_mb_fma_integer:
  XS_BEGIN
  vmv.v.v v0, v16
  vmv.v.v v1, v16
  vmv.v.v v2, v16
  vmv.v.v v3, v16
  vmv.v.v v4, v16
  vmv.v.v v5, v16
  vmv.v.v v6, v16
  vmv.v.v v7, v16
  .p2align 4
1:
  vfmacc.vv v0, v16, v17
  vadd.vv v8, v16, v17
  vfmacc.vv v1, v16, v17
  vadd.vv v9, v16, v17
  vfmacc.vv v2, v16, v17
  vadd.vv v10, v16, v17
  vfmacc.vv v3, v16, v17
  vadd.vv v11, v16, v17
  vfmacc.vv v4, v16, v17
  vadd.vv v12, v16, v17
  vfmacc.vv v5, v16, v17
  vadd.vv v13, v16, v17
  vfmacc.vv v6, v16, v17
  vadd.vv v14, v16, v17
  vfmacc.vv v7, v16, v17
  vadd.vv v15, v16, v17
  addi a2, a2, -1
  bnez a2, 1b
  XS_END
  .size xsai_mb_fma_integer, .-xsai_mb_fma_integer

  .globl xsai_mb_conversion_fma_integer
  .type xsai_mb_conversion_fma_integer, @function
xsai_mb_conversion_fma_integer:
  XS_BEGIN
  vmv.v.v v0, v16
  vmv.v.v v1, v16
  vmv.v.v v2, v16
  vmv.v.v v3, v16
  .p2align 4
1:
  vfcvt.rtz.x.f.v v4, v16
  vfmacc.vv v0, v16, v17
  vadd.vv v8, v16, v17
  vadd.vv v9, v16, v17
  vfcvt.rtz.x.f.v v5, v16
  vfmacc.vv v1, v16, v17
  vadd.vv v10, v16, v17
  vadd.vv v11, v16, v17
  vfcvt.rtz.x.f.v v6, v16
  vfmacc.vv v2, v16, v17
  vadd.vv v12, v16, v17
  vadd.vv v13, v16, v17
  vfcvt.rtz.x.f.v v7, v16
  vfmacc.vv v3, v16, v17
  vadd.vv v14, v16, v17
  vadd.vv v15, v16, v17
  addi a2, a2, -1
  bnez a2, 1b
  XS_END
  .size xsai_mb_conversion_fma_integer, .-xsai_mb_conversion_fma_integer

  .globl xsai_mb_reduction_sum_dependency
  .type xsai_mb_reduction_sum_dependency, @function
xsai_mb_reduction_sum_dependency:
  XS_BEGIN
  vmv.v.v v0, v17
  .p2align 4
1:
  .rept 16
  vfredusum.vs v0, v16, v0
  .endr
  addi a2, a2, -1
  bnez a2, 1b
  XS_END
  .size xsai_mb_reduction_sum_dependency, .-xsai_mb_reduction_sum_dependency

  .globl xsai_mb_reduction_sum_throughput
  .type xsai_mb_reduction_sum_throughput, @function
xsai_mb_reduction_sum_throughput:
  XS_BEGIN
  .p2align 4
1:
  vfredusum.vs v0, v16, v17
  vfredusum.vs v1, v16, v17
  vfredusum.vs v2, v16, v17
  vfredusum.vs v3, v16, v17
  vfredusum.vs v4, v16, v17
  vfredusum.vs v5, v16, v17
  vfredusum.vs v6, v16, v17
  vfredusum.vs v7, v16, v17
  vfredusum.vs v8, v16, v17
  vfredusum.vs v9, v16, v17
  vfredusum.vs v10, v16, v17
  vfredusum.vs v11, v16, v17
  vfredusum.vs v12, v16, v17
  vfredusum.vs v13, v16, v17
  vfredusum.vs v14, v16, v17
  vfredusum.vs v15, v16, v17
  addi a2, a2, -1
  bnez a2, 1b
  XS_END
  .size xsai_mb_reduction_sum_throughput, .-xsai_mb_reduction_sum_throughput

  .globl xsai_mb_reduction_max_dependency
  .type xsai_mb_reduction_max_dependency, @function
xsai_mb_reduction_max_dependency:
  XS_BEGIN
  vmv.v.v v0, v17
  .p2align 4
1:
  .rept 16
  vfredmax.vs v0, v16, v0
  .endr
  addi a2, a2, -1
  bnez a2, 1b
  XS_END
  .size xsai_mb_reduction_max_dependency, .-xsai_mb_reduction_max_dependency

  .globl xsai_mb_reduction_max_throughput
  .type xsai_mb_reduction_max_throughput, @function
xsai_mb_reduction_max_throughput:
  XS_BEGIN
  .p2align 4
1:
  vfredmax.vs v0, v16, v17
  vfredmax.vs v1, v16, v17
  vfredmax.vs v2, v16, v17
  vfredmax.vs v3, v16, v17
  vfredmax.vs v4, v16, v17
  vfredmax.vs v5, v16, v17
  vfredmax.vs v6, v16, v17
  vfredmax.vs v7, v16, v17
  vfredmax.vs v8, v16, v17
  vfredmax.vs v9, v16, v17
  vfredmax.vs v10, v16, v17
  vfredmax.vs v11, v16, v17
  vfredmax.vs v12, v16, v17
  vfredmax.vs v13, v16, v17
  vfredmax.vs v14, v16, v17
  vfredmax.vs v15, v16, v17
  addi a2, a2, -1
  bnez a2, 1b
  XS_END
  .size xsai_mb_reduction_max_throughput, .-xsai_mb_reduction_max_throughput

  .globl xsai_mb_fma_scalar_dependency
  .type xsai_mb_fma_scalar_dependency, @function
xsai_mb_fma_scalar_dependency:
  XS_BEGIN
  flw ft0, 0(a0)
  vmv.v.v v0, v16
  .p2align 4
1:
  .rept 16
  vfmacc.vf v0, ft0, v17
  .endr
  addi a2, a2, -1
  bnez a2, 1b
  XS_END
  .size xsai_mb_fma_scalar_dependency, .-xsai_mb_fma_scalar_dependency

  .globl xsai_mb_fma_scalar_throughput
  .type xsai_mb_fma_scalar_throughput, @function
xsai_mb_fma_scalar_throughput:
  XS_BEGIN
  flw ft0, 0(a0)
  vmv.v.v v0, v16
  vmv.v.v v1, v16
  vmv.v.v v2, v16
  vmv.v.v v3, v16
  vmv.v.v v4, v16
  vmv.v.v v5, v16
  vmv.v.v v6, v16
  vmv.v.v v7, v16
  vmv.v.v v8, v16
  vmv.v.v v9, v16
  vmv.v.v v10, v16
  vmv.v.v v11, v16
  vmv.v.v v12, v16
  vmv.v.v v13, v16
  vmv.v.v v14, v16
  vmv.v.v v15, v16
  .p2align 4
1:
  vfmacc.vf v8, ft0, v17
  vfmacc.vf v9, ft0, v17
  vfmacc.vf v10, ft0, v17
  vfmacc.vf v11, ft0, v17
  vfmacc.vf v12, ft0, v17
  vfmacc.vf v13, ft0, v17
  vfmacc.vf v14, ft0, v17
  vfmacc.vf v15, ft0, v17
  vfmacc.vf v0, ft0, v17
  vfmacc.vf v1, ft0, v17
  vfmacc.vf v2, ft0, v17
  vfmacc.vf v3, ft0, v17
  vfmacc.vf v4, ft0, v17
  vfmacc.vf v5, ft0, v17
  vfmacc.vf v6, ft0, v17
  vfmacc.vf v7, ft0, v17
  addi a2, a2, -1
  bnez a2, 1b
  XS_END
  .size xsai_mb_fma_scalar_throughput, .-xsai_mb_fma_scalar_throughput

  .globl xsai_mb_fp_broadcast_throughput
  .type xsai_mb_fp_broadcast_throughput, @function
xsai_mb_fp_broadcast_throughput:
  XS_BEGIN
  flw ft0, 0(a0)
  .p2align 4
1:
  vfmv.v.f v0, ft0
  vfmv.v.f v1, ft0
  vfmv.v.f v2, ft0
  vfmv.v.f v3, ft0
  vfmv.v.f v4, ft0
  vfmv.v.f v5, ft0
  vfmv.v.f v6, ft0
  vfmv.v.f v7, ft0
  vfmv.v.f v8, ft0
  vfmv.v.f v9, ft0
  vfmv.v.f v10, ft0
  vfmv.v.f v11, ft0
  vfmv.v.f v12, ft0
  vfmv.v.f v13, ft0
  vfmv.v.f v14, ft0
  vfmv.v.f v15, ft0
  addi a2, a2, -1
  bnez a2, 1b
  XS_END
  .size xsai_mb_fp_broadcast_throughput, .-xsai_mb_fp_broadcast_throughput

  .globl xsai_mb_integer_scalar_throughput
  .type xsai_mb_integer_scalar_throughput, @function
xsai_mb_integer_scalar_throughput:
  XS_BEGIN
  li t1, 1
  .p2align 4
1:
  vadd.vx v0, v16, t1
  vadd.vx v1, v16, t1
  vadd.vx v2, v16, t1
  vadd.vx v3, v16, t1
  vadd.vx v4, v16, t1
  vadd.vx v5, v16, t1
  vadd.vx v6, v16, t1
  vadd.vx v7, v16, t1
  vadd.vx v8, v16, t1
  vadd.vx v9, v16, t1
  vadd.vx v10, v16, t1
  vadd.vx v11, v16, t1
  vadd.vx v12, v16, t1
  vadd.vx v13, v16, t1
  vadd.vx v14, v16, t1
  vadd.vx v15, v16, t1
  addi a2, a2, -1
  bnez a2, 1b
  XS_END
  .size xsai_mb_integer_scalar_throughput, .-xsai_mb_integer_scalar_throughput

  .globl xsai_mb_immediate_broadcast_throughput
  .type xsai_mb_immediate_broadcast_throughput, @function
xsai_mb_immediate_broadcast_throughput:
  XS_BEGIN
  .p2align 4
1:
  vmv.v.i v0, 1
  vmv.v.i v1, 1
  vmv.v.i v2, 1
  vmv.v.i v3, 1
  vmv.v.i v4, 1
  vmv.v.i v5, 1
  vmv.v.i v6, 1
  vmv.v.i v7, 1
  vmv.v.i v8, 1
  vmv.v.i v9, 1
  vmv.v.i v10, 1
  vmv.v.i v11, 1
  vmv.v.i v12, 1
  vmv.v.i v13, 1
  vmv.v.i v14, 1
  vmv.v.i v15, 1
  addi a2, a2, -1
  bnez a2, 1b
  XS_END
  .size xsai_mb_immediate_broadcast_throughput, .-xsai_mb_immediate_broadcast_throughput

  .globl xsai_mb_load_throughput
  .type xsai_mb_load_throughput, @function
xsai_mb_load_throughput:
  vsetvli t0, zero, e32, m1, ta, ma
  addi t0, a0, 0
  addi t1, a0, 16
  addi t2, a0, 32
  addi t3, a0, 48
  .p2align 4
1:
  vle32.v v0, (t0)
  vle32.v v1, (t1)
  vle32.v v2, (t2)
  vle32.v v3, (t3)
  vle32.v v4, (t0)
  vle32.v v5, (t1)
  vle32.v v6, (t2)
  vle32.v v7, (t3)
  vle32.v v8, (t0)
  vle32.v v9, (t1)
  vle32.v v10, (t2)
  vle32.v v11, (t3)
  vle32.v v12, (t0)
  vle32.v v13, (t1)
  vle32.v v14, (t2)
  vle32.v v15, (t3)
  addi a2, a2, -1
  bnez a2, 1b
  vse32.v v0, (a1)
  ret
  .size xsai_mb_load_throughput, .-xsai_mb_load_throughput

  .globl xsai_mb_load_stream_throughput
  .type xsai_mb_load_stream_throughput, @function
xsai_mb_load_stream_throughput:
  vsetvli t3, zero, e32, m1, ta, ma
  li t0, 0
  li t2, 2047
  .p2align 4
1:
  add t1, a0, t0
  vle32.v v0, (t1)
  addi t1, t1, 16
  vle32.v v1, (t1)
  addi t1, t1, 16
  vle32.v v2, (t1)
  addi t1, t1, 16
  vle32.v v3, (t1)
  addi t1, t1, 16
  vle32.v v4, (t1)
  addi t1, t1, 16
  vle32.v v5, (t1)
  addi t1, t1, 16
  vle32.v v6, (t1)
  addi t1, t1, 16
  vle32.v v7, (t1)
  addi t1, t1, 16
  vle32.v v8, (t1)
  addi t1, t1, 16
  vle32.v v9, (t1)
  addi t1, t1, 16
  vle32.v v10, (t1)
  addi t1, t1, 16
  vle32.v v11, (t1)
  addi t1, t1, 16
  vle32.v v12, (t1)
  addi t1, t1, 16
  vle32.v v13, (t1)
  addi t1, t1, 16
  vle32.v v14, (t1)
  addi t1, t1, 16
  vle32.v v15, (t1)
  addi t0, t0, 256
  and t0, t0, t2
  addi a2, a2, -1
  bnez a2, 1b
  vse32.v v0, (a1)
  ret
  .size xsai_mb_load_stream_throughput, .-xsai_mb_load_stream_throughput

  .globl xsai_mb_load_same_vd
  .type xsai_mb_load_same_vd, @function
xsai_mb_load_same_vd:
  vsetvli t0, zero, e32, m1, ta, ma
  .p2align 4
1:
  .rept 16
  vle32.v v8, (a0)
  .endr
  addi a2, a2, -1
  bnez a2, 1b
  vse32.v v8, (a1)
  ret
  .size xsai_mb_load_same_vd, .-xsai_mb_load_same_vd

  .globl xsai_mb_load_use
  .type xsai_mb_load_use, @function
xsai_mb_load_use:
  vsetvli t0, zero, e32, m1, ta, ma
  vle32.v v16, (a0)
  .p2align 4
1:
  vle32.v v0, (a0)
  vfadd.vv v8, v0, v16
  vle32.v v1, (a0)
  vfadd.vv v9, v1, v16
  vle32.v v2, (a0)
  vfadd.vv v10, v2, v16
  vle32.v v3, (a0)
  vfadd.vv v11, v3, v16
  vle32.v v4, (a0)
  vfadd.vv v12, v4, v16
  vle32.v v5, (a0)
  vfadd.vv v13, v5, v16
  vle32.v v6, (a0)
  vfadd.vv v14, v6, v16
  vle32.v v7, (a0)
  vfadd.vv v15, v7, v16
  addi a2, a2, -1
  bnez a2, 1b
  vse32.v v8, (a1)
  ret
  .size xsai_mb_load_use, .-xsai_mb_load_use

  .globl xsai_mb_load_alu_dependency
  .type xsai_mb_load_alu_dependency, @function
xsai_mb_load_alu_dependency:
  vsetvli t0, zero, e32, m1, ta, ma
  vle32.v v16, (a0)
  .p2align 4
1:
  .rept 8
  vle32.v v8, (a0)
  vadd.vv v8, v8, v16
  .endr
  addi a2, a2, -1
  bnez a2, 1b
  vse32.v v8, (a1)
  ret
  .size xsai_mb_load_alu_dependency, .-xsai_mb_load_alu_dependency

  .globl xsai_mb_load_fma_dependency
  .type xsai_mb_load_fma_dependency, @function
xsai_mb_load_fma_dependency:
  vsetvli t0, zero, e32, m1, ta, ma
  vle32.v v16, (a0)
  vle32.v v17, (a0)
  .p2align 4
1:
  .rept 8
  vle32.v v8, (a0)
  vfmacc.vv v8, v16, v17
  .endr
  addi a2, a2, -1
  bnez a2, 1b
  vse32.v v8, (a1)
  ret
  .size xsai_mb_load_fma_dependency, .-xsai_mb_load_fma_dependency

  .globl xsai_mb_store_throughput
  .type xsai_mb_store_throughput, @function
xsai_mb_store_throughput:
  vsetvli t0, zero, e32, m1, ta, ma
  vle32.v v0, (a0)
  addi t0, a1, 0
  addi t1, a1, 16
  addi t2, a1, 32
  addi t3, a1, 48
  .p2align 4
1:
  vse32.v v0, (t0)
  vse32.v v0, (t1)
  vse32.v v0, (t2)
  vse32.v v0, (t3)
  vse32.v v0, (t0)
  vse32.v v0, (t1)
  vse32.v v0, (t2)
  vse32.v v0, (t3)
  vse32.v v0, (t0)
  vse32.v v0, (t1)
  vse32.v v0, (t2)
  vse32.v v0, (t3)
  vse32.v v0, (t0)
  vse32.v v0, (t1)
  vse32.v v0, (t2)
  vse32.v v0, (t3)
  addi a2, a2, -1
  bnez a2, 1b
  ret
  .size xsai_mb_store_throughput, .-xsai_mb_store_throughput

  .globl xsai_mb_store_stream_throughput
  .type xsai_mb_store_stream_throughput, @function
xsai_mb_store_stream_throughput:
  vsetvli t3, zero, e32, m1, ta, ma
  vle32.v v0, (a0)
  li t0, 0
  li t2, 2047
  .p2align 4
1:
  add t1, a1, t0
  vse32.v v0, (t1)
  addi t1, t1, 16
  vse32.v v0, (t1)
  addi t1, t1, 16
  vse32.v v0, (t1)
  addi t1, t1, 16
  vse32.v v0, (t1)
  addi t1, t1, 16
  vse32.v v0, (t1)
  addi t1, t1, 16
  vse32.v v0, (t1)
  addi t1, t1, 16
  vse32.v v0, (t1)
  addi t1, t1, 16
  vse32.v v0, (t1)
  addi t1, t1, 16
  vse32.v v0, (t1)
  addi t1, t1, 16
  vse32.v v0, (t1)
  addi t1, t1, 16
  vse32.v v0, (t1)
  addi t1, t1, 16
  vse32.v v0, (t1)
  addi t1, t1, 16
  vse32.v v0, (t1)
  addi t1, t1, 16
  vse32.v v0, (t1)
  addi t1, t1, 16
  vse32.v v0, (t1)
  addi t1, t1, 16
  vse32.v v0, (t1)
  addi t0, t0, 256
  and t0, t0, t2
  addi a2, a2, -1
  bnez a2, 1b
  ret
  .size xsai_mb_store_stream_throughput, .-xsai_mb_store_stream_throughput

  .globl xsai_mb_load_fma_iteration
  .type xsai_mb_load_fma_iteration, @function
xsai_mb_load_fma_iteration:
  vsetvli t0, zero, e32, m1, ta, ma
  vle32.v v16, (a0)
  vle32.v v17, (a0)
  .p2align 4
1:
  vle32.v v8, (a0)
  vfmacc.vv v8, v16, v17
  addi a2, a2, -1
  bnez a2, 1b
  vse32.v v8, (a1)
  ret
  .size xsai_mb_load_fma_iteration, .-xsai_mb_load_fma_iteration

  .globl xsai_mb_load_fma_store_iteration
  .type xsai_mb_load_fma_store_iteration, @function
xsai_mb_load_fma_store_iteration:
  vsetvli t0, zero, e32, m1, ta, ma
  vle32.v v16, (a0)
  vle32.v v17, (a0)
  .p2align 4
1:
  vle32.v v8, (a0)
  vfmacc.vv v8, v16, v17
  vse32.v v8, (a1)
  addi a2, a2, -1
  bnez a2, 1b
  ret
  .size xsai_mb_load_fma_store_iteration, .-xsai_mb_load_fma_store_iteration

  .globl xsai_mb_vset_rd_dependency
  .type xsai_mb_vset_rd_dependency, @function
xsai_mb_vset_rd_dependency:
  li t0, 4
  .p2align 4
1:
  .rept 16
  vsetvli t0, t0, e32, m1, ta, ma
  .endr
  addi a2, a2, -1
  bnez a2, 1b
  sw t0, 0(a1)
  ret
  .size xsai_mb_vset_rd_dependency, .-xsai_mb_vset_rd_dependency
