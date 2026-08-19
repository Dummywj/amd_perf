  .section .text
  .align 2

  .macro XS_INIT_FULL_BODY
  vsetvli t0, zero, e32, m1, ta, ma
  vle32.v v16, (a0)
  addi t2, a0, 16
  vle32.v v17, (t2)
  addi a0, a0, 32
  slli a4, a2, 2
  .endm

  .macro XS_ADVANCE_FULL
  slli t1, t0, 2
  add a0, a0, t1
  add a1, a1, t1
  sub a4, a4, t0
  addi a2, a2, -1
  .endm

  .globl xsai_vg_regular_lfs
  .type xsai_vg_regular_lfs, @function
xsai_vg_regular_lfs:
  XS_INIT_FULL_BODY
  .p2align 4
1:
  vsetvli t0, a4, e32, m1, ta, ma
  vle32.v v8, (a0)
  vfmacc.vv v8, v16, v17
  vse32.v v8, (a1)
  XS_ADVANCE_FULL
  bnez a2, 1b
  ret
  .size xsai_vg_regular_lfs, .-xsai_vg_regular_lfs

  .globl xsai_vg_keep_vl_lfs
  .type xsai_vg_keep_vl_lfs, @function
xsai_vg_keep_vl_lfs:
  XS_INIT_FULL_BODY
  .p2align 4
1:
  vsetvli zero, zero, e32, m1, ta, ma
  vle32.v v8, (a0)
  vfmacc.vv v8, v16, v17
  vse32.v v8, (a1)
  XS_ADVANCE_FULL
  bnez a2, 1b
  ret
  .size xsai_vg_keep_vl_lfs, .-xsai_vg_keep_vl_lfs

  .globl xsai_vg_vlmax_lfs
  .type xsai_vg_vlmax_lfs, @function
xsai_vg_vlmax_lfs:
  XS_INIT_FULL_BODY
  .p2align 4
1:
  vsetvli t0, zero, e32, m1, ta, ma
  vle32.v v8, (a0)
  vfmacc.vv v8, v16, v17
  vse32.v v8, (a1)
  XS_ADVANCE_FULL
  bnez a2, 1b
  ret
  .size xsai_vg_vlmax_lfs, .-xsai_vg_vlmax_lfs

  .globl xsai_vg_outside_lfs
  .type xsai_vg_outside_lfs, @function
xsai_vg_outside_lfs:
  XS_INIT_FULL_BODY
  .p2align 4
1:
  vle32.v v8, (a0)
  vfmacc.vv v8, v16, v17
  vse32.v v8, (a1)
  XS_ADVANCE_FULL
  bnez a2, 1b
  ret
  .size xsai_vg_outside_lfs, .-xsai_vg_outside_lfs

  .globl xsai_vg_regular_load
  .type xsai_vg_regular_load, @function
xsai_vg_regular_load:
  vsetvli t0, zero, e32, m1, ta, ma
  addi a0, a0, 32
  addi t3, a1, 0
  slli a4, a2, 2
  .p2align 4
1:
  vsetvli t0, a4, e32, m1, ta, ma
  vle32.v v8, (a0)
  slli t1, t0, 2
  add a0, a0, t1
  sub a4, a4, t0
  addi a2, a2, -1
  bnez a2, 1b
  vse32.v v8, (t3)
  ret
  .size xsai_vg_regular_load, .-xsai_vg_regular_load

  .globl xsai_vg_regular_compute
  .type xsai_vg_regular_compute, @function
xsai_vg_regular_compute:
  XS_INIT_FULL_BODY
  vle32.v v8, (a0)
  .p2align 4
1:
  vsetvli t0, a4, e32, m1, ta, ma
  vfmacc.vv v8, v16, v17
  sub a4, a4, t0
  addi a2, a2, -1
  bnez a2, 1b
  vse32.v v8, (a1)
  ret
  .size xsai_vg_regular_compute, .-xsai_vg_regular_compute

  .globl xsai_vg_regular_store
  .type xsai_vg_regular_store, @function
xsai_vg_regular_store:
  vsetvli t0, zero, e32, m1, ta, ma
  vle32.v v8, (a0)
  slli a4, a2, 2
  .p2align 4
1:
  vsetvli t0, a4, e32, m1, ta, ma
  vse32.v v8, (a1)
  slli t1, t0, 2
  add a1, a1, t1
  sub a4, a4, t0
  addi a2, a2, -1
  bnez a2, 1b
  ret
  .size xsai_vg_regular_store, .-xsai_vg_regular_store
