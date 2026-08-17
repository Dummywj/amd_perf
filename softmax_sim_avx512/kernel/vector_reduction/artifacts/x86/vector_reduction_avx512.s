	.file	"vector_reduction_avx512.cpp"
	.text
	.p2align 4
	.globl	vector_reduction_avx512_f32
	.type	vector_reduction_avx512_f32, @function
vector_reduction_avx512_f32:
	testq	%rdx, %rdx
	je	.L4
	vbroadcastss	.LC1(%rip), %zmm0
	xorl	%eax, %eax
	vxorps	%xmm1, %xmm1, %xmm1
	.p2align 4,,10
	.p2align 3
.L3:
	vaddps	(%rdi,%rax,4), %zmm1, %zmm1
	vmaxps	(%rdi,%rax,4), %zmm0, %zmm0
	addq	$16, %rax
	cmpq	%rdx, %rax
	jb	.L3
.L2:
	vextractf64x4	$0x1, %zmm1, %ymm2
	vaddps	%ymm1, %ymm2, %ymm1
	vextractf128	$0x1, %ymm1, %xmm2
	vaddps	%xmm1, %xmm2, %xmm2
	vpermilps	$78, %xmm2, %xmm1
	vaddps	%xmm2, %xmm1, %xmm1
	vextractf64x4	$0x1, %zmm0, %ymm2
	vmaxps	%ymm0, %ymm2, %ymm2
	vextractf128	$0x1, %ymm2, %xmm0
	vmaxps	%xmm2, %xmm0, %xmm0
	vpermilps	$78, %xmm0, %xmm2
	vmaxps	%xmm2, %xmm0, %xmm0
	vpermilps	$17, %xmm0, %xmm2
	vmaxps	%xmm2, %xmm0, %xmm0
	vmovaps	%xmm1, %xmm2
	vshufps	$85, %xmm1, %xmm1, %xmm1
	vaddss	%xmm1, %xmm2, %xmm2
	vunpcklps	%xmm0, %xmm2, %xmm0
	vmovlps	%xmm0, (%rsi)
	vzeroupper
	ret
	.p2align 4,,10
	.p2align 3
.L4:
	vbroadcastsd	.LC3(%rip), %zmm0
	vxorpd	%xmm1, %xmm1, %xmm1
	jmp	.L2
	.size	vector_reduction_avx512_f32, .-vector_reduction_avx512_f32
	.set	.LC1,.LC3
	.section	.rodata.cst8,"aM",@progbits,8
	.align 8
.LC3:
	.long	-8388608
	.long	-8388608
	.ident	"GCC: (Ubuntu 13.3.0-6ubuntu2~24.04.1) 13.3.0"
	.section	.note.GNU-stack,"",@progbits
