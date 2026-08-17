	.file	"pointer_agu_rvv.cpp"
	.option nopic
	.attribute arch, "rv64i2p1_m2p0_a2p1_f2p2_d2p2_c2p0_v1p0_zicsr2p0_zifencei2p0_zve32f1p0_zve32x1p0_zve64d1p0_zve64f1p0_zve64x1p0_zvl128b1p0_zvl32b1p0_zvl64b1p0"
	.attribute unaligned_access, 0
	.attribute stack_align, 16
	.text
	.align	1
	.globl	pointer_agu_rvv_f32
	.type	pointer_agu_rvv_f32, @function
pointer_agu_rvv_f32:
	beq	a2,zero,.L1
	li	a3,0
.L3:
	add	a5,a2,a3
	add	a7,a5,a2
	slli	a6,a3,2
	slli	a4,a5,2
	slli	a7,a7,2
	sub	a5,a2,a3
	add	t1,a0,a6
	add	a4,a0,a4
	add	a7,a0,a7
	add	a6,a1,a6
	vsetvli	a5,a5,e32,m1,ta,ma
	vle32.v	v24,0(t1)
	vle32.v	v26,0(a4)
	vle32.v	v25,0(a7)
	vfadd.vv	v24,v24,v26
	add	a3,a3,a5
	vfadd.vv	v24,v24,v25
	vse32.v	v24,0(a6)
	bgtu	a2,a3,.L3
.L1:
	ret
	.size	pointer_agu_rvv_f32, .-pointer_agu_rvv_f32
	.ident	"GCC: (Ubuntu 13.3.0-6ubuntu2~24.04) 13.3.0"
	.section	.note.GNU-stack,"",@progbits
