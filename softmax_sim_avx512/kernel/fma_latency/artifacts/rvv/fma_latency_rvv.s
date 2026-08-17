	.file	"fma_latency_rvv.cpp"
	.option nopic
	.attribute arch, "rv64i2p1_m2p0_a2p1_f2p2_d2p2_c2p0_v1p0_zicsr2p0_zifencei2p0_zve32f1p0_zve32x1p0_zve64d1p0_zve64f1p0_zve64x1p0_zvl128b1p0_zvl32b1p0_zvl64b1p0"
	.attribute unaligned_access, 0
	.attribute stack_align, 16
	.text
	.align	1
	.globl	fma_latency_rvv_f32
	.type	fma_latency_rvv_f32, @function
fma_latency_rvv_f32:
	li	a5,16
	vsetvli	a5,a5,e32,m4,ta,ma
	vmv.v.i	v28,0
	beq	a2,zero,.L1
	lui	a4,%hi(.LC1)
	flw	fa5,%lo(.LC1)(a4)
	lui	a4,%hi(.LC0)
	flw	fa4,%lo(.LC0)(a4)
	li	a3,0
	vfmv.v.f	v24,fa4
.L3:
	slli	a4,a3,2
	add	a6,a0,a4
	vle32.v	v8,0(a6)
	vfadd.vv	v28,v28,v8
	vmv.v.v	v8,v24
	vfmacc.vf	v8,fa5,v28
	vmv.v.v	v28,v24
	vfmacc.vf	v28,fa5,v8
	vmv.v.v	v8,v24
	vfmacc.vf	v8,fa5,v28
	vmv.v.v	v28,v24
	vfmacc.vf	v28,fa5,v8
	vmv.v.v	v8,v24
	vfmacc.vf	v8,fa5,v28
	vmv.v.v	v28,v24
	vfmacc.vf	v28,fa5,v8
	vmv.v.v	v8,v24
	vfmacc.vf	v8,fa5,v28
	vmv.v.v	v28,v24
	vfmacc.vf	v28,fa5,v8
	vmv.v.v	v8,v24
	vfmacc.vf	v8,fa5,v28
	vmv.v.v	v28,v24
	vfmacc.vf	v28,fa5,v8
	vmv.v.v	v8,v24
	vfmacc.vf	v8,fa5,v28
	vmv.v.v	v28,v24
	vfmacc.vf	v28,fa5,v8
	add	a4,a1,a4
	vmv.v.v	v8,v24
	vfmacc.vf	v8,fa5,v28
	vmv.v.v	v28,v24
	vfmacc.vf	v28,fa5,v8
	add	a3,a3,a5
	vmv.v.v	v8,v24
	vfmacc.vf	v8,fa5,v28
	vmv.v.v	v28,v24
	vfmacc.vf	v28,fa5,v8
	vse32.v	v28,0(a4)
	bgtu	a2,a3,.L3
.L1:
	ret
	.size	fma_latency_rvv_f32, .-fma_latency_rvv_f32
	.section	.srodata.cst4,"aM",@progbits,4
	.align	2
.LC0:
	.word	966609234
	.align	2
.LC1:
	.word	1065354055
	.ident	"GCC: (Ubuntu 13.3.0-6ubuntu2~24.04) 13.3.0"
	.section	.note.GNU-stack,"",@progbits
