	.file	"softmax_avx512.cpp"
	.text
	.p2align 4
	.globl	softmax_avx512_f32
	.type	softmax_avx512_f32, @function
softmax_avx512_f32:
	testq	%rdx, %rdx
	je	.L12
	vbroadcastss	.LC1(%rip), %zmm0
	xorl	%eax, %eax
	.p2align 4,,10
	.p2align 3
.L3:
	vmaxps	(%rdi,%rax,4), %zmm0, %zmm0
	addq	$16, %rax
	cmpq	%rdx, %rax
	jb	.L3
	vextractf64x4	$0x1, %zmm0, %ymm1
	vxorps	%xmm3, %xmm3, %xmm3
	xorl	%eax, %eax
	movl	$127, %ecx
	vmaxps	%ymm0, %ymm1, %ymm0
	vmovaps	%zmm3, %zmm7
	vbroadcastss	.LC3(%rip), %zmm16
	vbroadcastss	.LC5(%rip), %zmm15
	vbroadcastss	.LC7(%rip), %zmm14
	vpbroadcastd	%ecx, %zmm6
	vbroadcastss	.LC9(%rip), %zmm13
	vbroadcastss	.LC11(%rip), %zmm12
	vbroadcastss	.LC13(%rip), %zmm11
	vbroadcastss	.LC15(%rip), %zmm10
	vextractf128	$0x1, %ymm0, %xmm4
	vbroadcastss	.LC17(%rip), %zmm9
	vbroadcastss	.LC19(%rip), %zmm8
	vmaxps	%xmm0, %xmm4, %xmm4
	vbroadcastss	.LC21(%rip), %zmm5
	vpermilps	$78, %xmm4, %xmm0
	vmaxps	%xmm0, %xmm4, %xmm4
	vpermilps	$17, %xmm4, %xmm0
	vmaxps	%xmm0, %xmm4, %xmm4
	vbroadcastss	%xmm4, %zmm4
	.p2align 4,,10
	.p2align 3
.L4:
	vmovups	(%rdi,%rax,4), %zmm2
	vsubps	%zmm4, %zmm2, %zmm0
	vmaxps	%zmm16, %zmm0, %zmm0
	vminps	%zmm7, %zmm0, %zmm0
	vmulps	%zmm15, %zmm0, %zmm2
	vcvttps2dq	%zmm2, %zmm2
	vcvtdq2ps	%zmm2, %zmm1
	vfnmadd132ps	%zmm14, %zmm0, %zmm1
	vmovaps	%zmm13, %zmm0
	vpaddd	%zmm6, %zmm2, %zmm2
	vpslld	$23, %zmm2, %zmm2
	vfmadd132ps	%zmm1, %zmm12, %zmm0
	vfmadd132ps	%zmm1, %zmm11, %zmm0
	vfmadd132ps	%zmm1, %zmm10, %zmm0
	vfmadd132ps	%zmm1, %zmm9, %zmm0
	vfmadd132ps	%zmm1, %zmm8, %zmm0
	vfmadd132ps	%zmm1, %zmm5, %zmm0
	vfmadd132ps	%zmm1, %zmm5, %zmm0
	vmulps	%zmm2, %zmm0, %zmm0
	vmovups	%zmm0, (%rsi,%rax,4)
	addq	$16, %rax
	vaddps	%zmm0, %zmm3, %zmm3
	cmpq	%rdx, %rax
	jb	.L4
	vextractf64x4	$0x1, %zmm3, %ymm0
	leaq	-4(,%rdx,4), %rax
	vaddps	%ymm0, %ymm3, %ymm3
	andq	$-64, %rax
	leaq	64(%rsi,%rax), %rax
	vextractf128	$0x1, %ymm3, %xmm1
	vaddps	%xmm3, %xmm1, %xmm1
	vpermilps	$78, %xmm1, %xmm0
	vaddps	%xmm1, %xmm0, %xmm0
	vmovaps	%xmm0, %xmm1
	vshufps	$85, %xmm0, %xmm0, %xmm0
	vaddss	%xmm0, %xmm1, %xmm0
	vmovss	.LC21(%rip), %xmm1
	vdivss	%xmm0, %xmm1, %xmm1
	vbroadcastss	%xmm1, %zmm1
	.p2align 4,,10
	.p2align 3
.L5:
	vmulps	(%rsi), %zmm1, %zmm0
	addq	$64, %rsi
	vmovups	%zmm0, -64(%rsi)
	cmpq	%rsi, %rax
	jne	.L5
	vzeroupper
.L12:
	ret
	.size	softmax_avx512_f32, .-softmax_avx512_f32
	.section	.rodata.cst4,"aM",@progbits,4
	.align 4
.LC1:
	.long	-8388608
	.align 4
.LC3:
	.long	-1028784128
	.align 4
.LC5:
	.long	1069066811
	.align 4
.LC7:
	.long	1060205080
	.align 4
.LC9:
	.long	961547521
	.align 4
.LC11:
	.long	985008993
	.align 4
.LC13:
	.long	1007192201
	.align 4
.LC15:
	.long	1026206379
	.align 4
.LC17:
	.long	1042983595
	.align 4
.LC19:
	.long	1056964608
	.align 4
.LC21:
	.long	1065353216
	.ident	"GCC: (Ubuntu 13.3.0-6ubuntu2~24.04.1) 13.3.0"
	.section	.note.GNU-stack,"",@progbits
