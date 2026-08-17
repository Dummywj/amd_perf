	.file	"dot_product_rvv.cpp"
	.option nopic
	.attribute arch, "rv64i2p1_m2p0_a2p1_f2p2_d2p2_c2p0_v1p0_zicsr2p0_zifencei2p0_zve32f1p0_zve32x1p0_zve64d1p0_zve64f1p0_zve64x1p0_zvl128b1p0_zvl32b1p0_zvl64b1p0"
	.attribute unaligned_access, 0
	.attribute stack_align, 16
	.text
	.align	1
	.globl	dot_product_rvv_f32
	.type	dot_product_rvv_f32, @function
dot_product_rvv_f32:
	fmv.s.x	fa5,zero
	beq	a2,zero,.L2
	li	a4,0
.L3:
	add	a3,a2,a4
	sub	a5,a2,a4
	slli	a6,a4,2
	slli	a3,a3,2
	vsetvli	a5,a5,e32,m1,ta,ma
	add	a6,a0,a6
	add	a3,a0,a3
	add	a4,a4,a5
	vle32.v	v24,0(a6)
	vle32.v	v26,0(a3)
	vmv.v.i	v25,0
	vfmul.vv	v24,v24,v26
	vfredusum.vs	v24,v24,v25
	vfmv.f.s	fa4,v24
	fadd.s	fa5,fa5,fa4
	bgtu	a2,a4,.L3
.L2:
	fsw	fa5,0(a1)
	ret
	.size	dot_product_rvv_f32, .-dot_product_rvv_f32
	.ident	"GCC: (Ubuntu 13.3.0-6ubuntu2~24.04) 13.3.0"
	.section	.note.GNU-stack,"",@progbits
