	.file	"vector_triad_rvv.cpp"
	.option nopic
	.attribute arch, "rv64i2p1_m2p0_a2p1_f2p2_d2p2_c2p0_v1p0_zicsr2p0_zifencei2p0_zve32f1p0_zve32x1p0_zve64d1p0_zve64f1p0_zve64x1p0_zvl128b1p0_zvl32b1p0_zvl64b1p0"
	.attribute unaligned_access, 0
	.attribute stack_align, 16
	.text
	.align	1
	.globl	vector_triad_rvv_f32
	.type	vector_triad_rvv_f32, @function
vector_triad_rvv_f32:
	beq	a2,zero,.L1
	lui	a5,%hi(.LC0)
	flw	fa5,%lo(.LC0)(a5)
	li	a4,0
.L3:
	add	a6,a2,a4
	slli	a3,a4,2
	slli	a6,a6,2
	sub	a5,a2,a4
	add	a7,a0,a3
	add	a6,a0,a6
	add	a3,a1,a3
	vsetvli	a5,a5,e32,m1,ta,ma
	vle32.v	v24,0(a7)
	vle32.v	v25,0(a6)
	add	a4,a4,a5
	vfmacc.vf	v24,fa5,v25
	vse32.v	v24,0(a3)
	bgtu	a2,a4,.L3
.L1:
	ret
	.size	vector_triad_rvv_f32, .-vector_triad_rvv_f32
	.section	.srodata.cst4,"aM",@progbits,4
	.align	2
.LC0:
	.word	1067450368
	.ident	"GCC: (Ubuntu 13.3.0-6ubuntu2~24.04) 13.3.0"
	.section	.note.GNU-stack,"",@progbits
