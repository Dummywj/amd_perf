  # Parser-friendly expansion of the seven functions in vset_gap_microbench.S.
  # The explicit addi-zero instructions preserve the padding NOPs observed in
  # artifacts/xsai/vset_gap/build/xsai-vset-gap-riscv64-xs.txt.
  .text

xsai_vg_regular_lfs:
  vsetvli t0, zero, e32, m1, ta, ma
  vle32.v v16, (a0)
  addi t2, a0, 16
  vle32.v v17, (t2)
  addi a0, a0, 32
  slli a4, a2, 2
  addi zero, zero, 0
  addi zero, zero, 0
.Lregular_lfs_loop:
  vsetvli t0, a4, e32, m1, ta, ma
  vle32.v v8, (a0)
  vfmacc.vv v8, v16, v17
  vse32.v v8, (a1)
  slli t1, t0, 2
  add a0, a0, t1
  add a1, a1, t1
  sub a4, a4, t0
  addi a2, a2, -1
  bgtu a2, zero, .Lregular_lfs_loop
  ret
  .size xsai_vg_regular_lfs, .-xsai_vg_regular_lfs

xsai_vg_keep_vl_lfs:
  vsetvli t0, zero, e32, m1, ta, ma
  vle32.v v16, (a0)
  addi t2, a0, 16
  vle32.v v17, (t2)
  addi a0, a0, 32
  slli a4, a2, 2
  addi zero, zero, 0
  addi zero, zero, 0
.Lkeep_vl_lfs_loop:
  vsetvli zero, zero, e32, m1, ta, ma
  vle32.v v8, (a0)
  vfmacc.vv v8, v16, v17
  vse32.v v8, (a1)
  slli t1, t0, 2
  add a0, a0, t1
  add a1, a1, t1
  sub a4, a4, t0
  addi a2, a2, -1
  bgtu a2, zero, .Lkeep_vl_lfs_loop
  ret
  .size xsai_vg_keep_vl_lfs, .-xsai_vg_keep_vl_lfs

xsai_vg_vlmax_lfs:
  vsetvli t0, zero, e32, m1, ta, ma
  vle32.v v16, (a0)
  addi t2, a0, 16
  vle32.v v17, (t2)
  addi a0, a0, 32
  slli a4, a2, 2
  addi zero, zero, 0
  addi zero, zero, 0
.Lvlmax_lfs_loop:
  vsetvli t0, zero, e32, m1, ta, ma
  vle32.v v8, (a0)
  vfmacc.vv v8, v16, v17
  vse32.v v8, (a1)
  slli t1, t0, 2
  add a0, a0, t1
  add a1, a1, t1
  sub a4, a4, t0
  addi a2, a2, -1
  bgtu a2, zero, .Lvlmax_lfs_loop
  ret
  .size xsai_vg_vlmax_lfs, .-xsai_vg_vlmax_lfs

xsai_vg_outside_lfs:
  vsetvli t0, zero, e32, m1, ta, ma
  vle32.v v16, (a0)
  addi t2, a0, 16
  vle32.v v17, (t2)
  addi a0, a0, 32
  slli a4, a2, 2
  addi zero, zero, 0
  addi zero, zero, 0
.Loutside_lfs_loop:
  vle32.v v8, (a0)
  vfmacc.vv v8, v16, v17
  vse32.v v8, (a1)
  slli t1, t0, 2
  add a0, a0, t1
  add a1, a1, t1
  sub a4, a4, t0
  addi a2, a2, -1
  bgtu a2, zero, .Loutside_lfs_loop
  ret
  .size xsai_vg_outside_lfs, .-xsai_vg_outside_lfs

xsai_vg_regular_load:
  vsetvli t0, zero, e32, m1, ta, ma
  addi a0, a0, 32
  addi t3, a1, 0
  slli a4, a2, 2
  addi zero, zero, 0
.Lregular_load_loop:
  vsetvli t0, a4, e32, m1, ta, ma
  vle32.v v8, (a0)
  slli t1, t0, 2
  add a0, a0, t1
  sub a4, a4, t0
  addi a2, a2, -1
  bgtu a2, zero, .Lregular_load_loop
  vse32.v v8, (t3)
  ret
  .size xsai_vg_regular_load, .-xsai_vg_regular_load

xsai_vg_regular_compute:
  vsetvli t0, zero, e32, m1, ta, ma
  vle32.v v16, (a0)
  addi t2, a0, 16
  vle32.v v17, (t2)
  addi a0, a0, 32
  slli a4, a2, 2
  vle32.v v8, (a0)
  addi zero, zero, 0
  addi zero, zero, 0
.Lregular_compute_loop:
  vsetvli t0, a4, e32, m1, ta, ma
  vfmacc.vv v8, v16, v17
  sub a4, a4, t0
  addi a2, a2, -1
  bgtu a2, zero, .Lregular_compute_loop
  vse32.v v8, (a1)
  ret
  .size xsai_vg_regular_compute, .-xsai_vg_regular_compute

xsai_vg_regular_store:
  vsetvli t0, zero, e32, m1, ta, ma
  vle32.v v8, (a0)
  slli a4, a2, 2
  addi zero, zero, 0
  addi zero, zero, 0
  addi zero, zero, 0
  addi zero, zero, 0
.Lregular_store_loop:
  vsetvli t0, a4, e32, m1, ta, ma
  vse32.v v8, (a1)
  slli t1, t0, 2
  add a1, a1, t1
  sub a4, a4, t0
  addi a2, a2, -1
  bgtu a2, zero, .Lregular_store_loop
  ret
  .size xsai_vg_regular_store, .-xsai_vg_regular_store
