	.file	"softmax_rvv.cpp"
	.option nopic
	.attribute arch, "rv64i2p1_m2p0_a2p1_f2p2_d2p2_c2p0_v1p0_zicsr2p0_zifencei2p0_zve32f1p0_zve32x1p0_zve64d1p0_zve64f1p0_zve64x1p0_zvl128b1p0_zvl32b1p0_zvl64b1p0"
	.attribute unaligned_access, 0
	.attribute stack_align, 16
	.text
	.align	1
	.globl	softmax_rvv_f32
	.type	softmax_rvv_f32, @function
softmax_rvv_f32:
	beq	a2,zero,.L1
	lui	a5,%hi(.LC0)
	flw	fa5,%lo(.LC0)(a5)
	li	a4,0
.L2:
	sub	a5,a2,a4
	slli	a3,a4,2
	vsetvli	a5,a5,e32,m1,ta,ma
	add	a3,a0,a3
	add	a4,a4,a5
	vfmv.v.f	v25,fa5
	vle32.v	v24,0(a3)
	vfredmax.vs	v24,v24,v25
	vfmv.f.s	fa5,v24
	bgtu	a2,a4,.L2
	lui	a5,%hi(.LC1)
	flw	ft7,%lo(.LC1)(a5)
	lui	a5,%hi(.LC2)
	flw	ft5,%lo(.LC2)(a5)
	lui	a5,%hi(.LC3)
	flw	ft4,%lo(.LC3)(a5)
	lui	a5,%hi(.LC4)
	flw	ft3,%lo(.LC4)(a5)
	lui	a5,%hi(.LC5)
	flw	ft2,%lo(.LC5)(a5)
	lui	a5,%hi(.LC6)
	flw	ft1,%lo(.LC6)(a5)
	lui	a5,%hi(.LC7)
	fmv.s.x	fa3,zero
	flw	ft0,%lo(.LC7)(a5)
	lui	a5,%hi(.LC8)
	flw	fa0,%lo(.LC8)(a5)
	lui	a5,%hi(.LC9)
	flw	fa1,%lo(.LC9)(a5)
	lui	a5,%hi(.LC10)
	fmv.s	ft6,fa3
	flw	fa4,%lo(.LC10)(a5)
	li	a3,0
	li	a7,127
.L3:
	slli	a4,a3,2
	sub	a5,a2,a3
	add	a6,a0,a4
	vsetvli	a5,a5,e32,m1,ta,ma
	add	a4,a1,a4
	vle32.v	v24,0(a6)
	vfmv.v.f	v9,ft3
	vfsub.vf	v24,v24,fa5
	vfmv.v.f	v31,ft2
	vfmax.vf	v24,v24,ft7
	vfmv.v.f	v30,ft1
	vfmin.vf	v24,v24,ft6
	vfmv.v.f	v29,ft0
	vfmul.vf	v26,v24,ft5
	vfmv.v.f	v28,fa0
	vfcvt.rtz.x.f.v	v26,v26
	vfcvt.f.x.v	v8,v26
	vfmul.vf	v8,v8,ft4
	vfsub.vv	v24,v24,v8
	vfmacc.vv	v31,v9,v24
	vfmacc.vv	v30,v31,v24
	vfmacc.vv	v29,v30,v24
	vfmacc.vv	v28,v29,v24
	vfmv.v.f	v25,fa4
	vfmv.v.f	v27,fa1
	vadd.vx	v26,v26,a7
	vfmacc.vv	v27,v28,v24
	vsll.vi	v26,v26,23
	vmv.v.v	v28,v25
	vfmacc.vv	v28,v27,v24
	add	a3,a3,a5
	vfmacc.vv	v25,v28,v24
	vfmul.vv	v25,v25,v26
	vse32.v	v25,0(a4)
	vmv.v.i	v24,0
	vfredusum.vs	v25,v25,v24
	vfmv.f.s	fa2,v25
	fadd.s	fa3,fa3,fa2
	bgtu	a2,a3,.L3
	fdiv.s	fa4,fa4,fa3
	li	a3,0
.L4:
	slli	a4,a3,2
	sub	a5,a2,a3
	add	a4,a1,a4
	vsetvli	a5,a5,e32,m1,ta,ma
	vle32.v	v24,0(a4)
	add	a3,a3,a5
	vfmul.vf	v24,v24,fa4
	vse32.v	v24,0(a4)
	bgtu	a2,a3,.L4
.L1:
	ret
	.size	softmax_rvv_f32, .-softmax_rvv_f32
	.section	.srodata.cst4,"aM",@progbits,4
	.align	2
.LC0:
	.word	-8388608
	.align	2
.LC1:
	.word	-1028784128
	.align	2
.LC2:
	.word	1069066811
	.align	2
.LC3:
	.word	1060205080
	.align	2
.LC4:
	.word	961547521
	.align	2
.LC5:
	.word	985008993
	.align	2
.LC6:
	.word	1007192201
	.align	2
.LC7:
	.word	1026206379
	.align	2
.LC8:
	.word	1042983595
	.align	2
.LC9:
	.word	1056964608
	.align	2
.LC10:
	.word	1065353216
	.ident	"GCC: (Ubuntu 13.3.0-6ubuntu2~24.04) 13.3.0"
	.section	.note.GNU-stack,"",@progbits
