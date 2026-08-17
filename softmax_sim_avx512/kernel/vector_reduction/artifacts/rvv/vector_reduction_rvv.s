	.file	"vector_reduction_rvv.cpp"
	.option nopic
	.attribute arch, "rv64i2p1_m2p0_a2p1_f2p2_d2p2_c2p0_v1p0_zicsr2p0_zifencei2p0_zve32f1p0_zve32x1p0_zve64d1p0_zve64f1p0_zve64x1p0_zvl128b1p0_zvl32b1p0_zvl64b1p0"
	.attribute unaligned_access, 0
	.attribute stack_align, 16
	.text
	.align	1
	.globl	vector_reduction_rvv_f32
	.type	vector_reduction_rvv_f32, @function
vector_reduction_rvv_f32:
	lui	a5,%hi(.LC0)
	flw	fa5,%lo(.LC0)(a5)
	fmv.s.x	fa4,zero
	beq	a2,zero,.L2
	li	a4,0
.L3:
	sub	a5,a2,a4
	slli	a3,a4,2
	vsetvli	a5,a5,e32,m1,ta,ma
	add	a3,a0,a3
	add	a4,a4,a5
	vle32.v	v24,0(a3)
	vfmv.v.f	v25,fa5
	vmv.v.i	v26,0
	vfredmax.vs	v25,v24,v25
	vfredusum.vs	v24,v24,v26
	vfmv.f.s	fa5,v25
	vfmv.f.s	fa3,v24
	fadd.s	fa4,fa4,fa3
	bgtu	a2,a4,.L3
.L2:
	fsw	fa4,0(a1)
	fsw	fa5,4(a1)
	ret
	.size	vector_reduction_rvv_f32, .-vector_reduction_rvv_f32
	.section	.srodata.cst4,"aM",@progbits,4
	.align	2
.LC0:
	.word	-8388608
	.ident	"GCC: (Ubuntu 13.3.0-6ubuntu2~24.04) 13.3.0"
	.section	.note.GNU-stack,"",@progbits
