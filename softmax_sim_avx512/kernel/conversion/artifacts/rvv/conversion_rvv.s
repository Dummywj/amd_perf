	.file	"conversion_rvv.cpp"
	.option nopic
	.attribute arch, "rv64i2p1_m2p0_a2p1_f2p2_d2p2_c2p0_v1p0_zicsr2p0_zifencei2p0_zve32f1p0_zve32x1p0_zve64d1p0_zve64f1p0_zve64x1p0_zvl128b1p0_zvl32b1p0_zvl64b1p0"
	.attribute unaligned_access, 0
	.attribute stack_align, 16
	.text
	.align	1
	.globl	conversion_rvv_f32
	.type	conversion_rvv_f32, @function
conversion_rvv_f32:
	beq	a2,zero,.L1
	li	a3,0
.L3:
	slli	a4,a3,2
	sub	a5,a2,a3
	add	a6,a0,a4
	add	a4,a1,a4
	vsetvli	a5,a5,e32,m1,ta,ma
	vle32.v	v24,0(a6)
	add	a3,a3,a5
	vfcvt.rtz.x.f.v	v24,v24
	vfcvt.f.x.v	v24,v24
	vse32.v	v24,0(a4)
	bgtu	a2,a3,.L3
.L1:
	ret
	.size	conversion_rvv_f32, .-conversion_rvv_f32
	.ident	"GCC: (Ubuntu 13.3.0-6ubuntu2~24.04) 13.3.0"
	.section	.note.GNU-stack,"",@progbits
