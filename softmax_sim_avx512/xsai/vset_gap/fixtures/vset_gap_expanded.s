  # Parser-friendly expansion of the functions in vset_gap_microbench.S.
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

xsai_vg_outside_load:
  vsetvli t0, zero, e32, m1, ta, ma
  addi a0, a0, 32
  addi t3, a1, 0
  slli a4, a2, 2
.Loutside_load_loop:
  vle32.v v8, (a0)
  slli t1, t0, 2
  add a0, a0, t1
  sub a4, a4, t0
  addi a2, a2, -1
  bgtu a2, zero, .Loutside_load_loop
  vse32.v v8, (t3)
  ret
  .size xsai_vg_outside_load, .-xsai_vg_outside_load

xsai_vg_load_stream_1:
  vsetvli t0, zero, e32, m1, ta, ma
  addi a0, a0, 32
  slli a4, a2, 2
.Lload_stream_1_loop:
  vsetvli t0, a4, e32, m1, ta, ma
  vle32.v v8, (a0)
  slli t1, t0, 2
  add a0, a0, t1
  sub a4, a4, t0
  addi a2, a2, -1
  bgtu a2, zero, .Lload_stream_1_loop
  vse32.v v8, (a1)
  ret
  .size xsai_vg_load_stream_1, .-xsai_vg_load_stream_1

xsai_vg_load_stream_2:
  vsetvli t0, zero, e32, m1, ta, ma
  addi a0, a0, 32
  addi a3, a0, 4
  addi a4, a1, 16
  slli a5, a2, 2
.Lload_stream_2_loop:
  vsetvli t0, a5, e32, m1, ta, ma
  vle32.v v8, (a0)
  vle32.v v9, (a3)
  slli t1, t0, 2
  add a0, a0, t1
  add a3, a3, t1
  sub a5, a5, t0
  addi a2, a2, -1
  bgtu a2, zero, .Lload_stream_2_loop
  vse32.v v8, (a1)
  vse32.v v9, (a4)
  ret
  .size xsai_vg_load_stream_2, .-xsai_vg_load_stream_2

xsai_vg_load_stream_4:
  vsetvli t0, zero, e32, m1, ta, ma
  addi a0, a0, 32
  addi a3, a0, 4
  addi a4, a0, 8
  addi a5, a0, 12
  slli t2, a2, 2
  addi t3, a1, 16
  addi t4, a1, 32
  addi t5, a1, 48
.Lload_stream_4_loop:
  vsetvli t0, t2, e32, m1, ta, ma
  vle32.v v8, (a0)
  vle32.v v9, (a3)
  vle32.v v10, (a4)
  vle32.v v11, (a5)
  slli t1, t0, 2
  add a0, a0, t1
  add a3, a3, t1
  add a4, a4, t1
  add a5, a5, t1
  sub t2, t2, t0
  addi a2, a2, -1
  bgtu a2, zero, .Lload_stream_4_loop
  vse32.v v8, (a1)
  vse32.v v9, (t3)
  vse32.v v10, (t4)
  vse32.v v11, (t5)
  ret
  .size xsai_vg_load_stream_4, .-xsai_vg_load_stream_4

xsai_vg_aligned_load_stream_2:
  vsetvli t0, zero, e32, m1, ta, ma
  addi a0, a0, 32
  slli t1, a2, 4
  add a3, a0, t1
  addi a4, a1, 16
  slli a5, a2, 2
.Laligned_load_stream_2_loop:
  vsetvli t0, a5, e32, m1, ta, ma
  vle32.v v8, (a0)
  vle32.v v9, (a3)
  slli t1, t0, 2
  add a0, a0, t1
  add a3, a3, t1
  sub a5, a5, t0
  addi a2, a2, -1
  bgtu a2, zero, .Laligned_load_stream_2_loop
  vse32.v v8, (a1)
  vse32.v v9, (a4)
  ret
  .size xsai_vg_aligned_load_stream_2, .-xsai_vg_aligned_load_stream_2

xsai_vg_aligned_load_stream_4:
  vsetvli t0, zero, e32, m1, ta, ma
  addi a0, a0, 32
  slli t1, a2, 4
  add a3, a0, t1
  add a4, a3, t1
  add a5, a4, t1
  slli t2, a2, 2
  addi t3, a1, 16
  addi t4, a1, 32
  addi t5, a1, 48
.Laligned_load_stream_4_loop:
  vsetvli t0, t2, e32, m1, ta, ma
  vle32.v v8, (a0)
  vle32.v v9, (a3)
  vle32.v v10, (a4)
  vle32.v v11, (a5)
  slli t1, t0, 2
  add a0, a0, t1
  add a3, a3, t1
  add a4, a4, t1
  add a5, a5, t1
  sub t2, t2, t0
  addi a2, a2, -1
  bgtu a2, zero, .Laligned_load_stream_4_loop
  vse32.v v8, (a1)
  vse32.v v9, (t3)
  vse32.v v10, (t4)
  vse32.v v11, (t5)
  ret
  .size xsai_vg_aligned_load_stream_4, .-xsai_vg_aligned_load_stream_4

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
