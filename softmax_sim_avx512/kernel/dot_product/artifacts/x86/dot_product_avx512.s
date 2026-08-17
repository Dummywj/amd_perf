	.file	"dot_product_avx512.cpp"
	.text
	.p2align 4
	.globl	dot_product_avx512_f32
	.type	dot_product_avx512_f32, @function
dot_product_avx512_f32:
	testq	%rdx, %rdx
	je	.L4
	leaq	(%rdi,%rdx,4), %rcx
	xorl	%eax, %eax
	vxorps	%xmm0, %xmm0, %xmm0
	.p2align 4,,10
	.p2align 3
.L3:
	vmovups	(%rdi,%rax,4), %zmm2
	vfmadd231ps	(%rcx,%rax,4), %zmm2, %zmm0
	addq	$16, %rax
	cmpq	%rdx, %rax
	jb	.L3
.L2:
	vextractf64x4	$0x1, %zmm0, %ymm1
	vaddps	%ymm0, %ymm1, %ymm0
	vextractf128	$0x1, %ymm0, %xmm1
	vaddps	%xmm0, %xmm1, %xmm1
	vpermilps	$78, %xmm1, %xmm0
	vaddps	%xmm1, %xmm0, %xmm0
	vmovaps	%xmm0, %xmm1
	vshufps	$85, %xmm0, %xmm0, %xmm0
	vaddss	%xmm0, %xmm1, %xmm1
	vmovss	%xmm1, (%rsi)
	vzeroupper
	ret
	.p2align 4,,10
	.p2align 3
.L4:
	vxorpd	%xmm0, %xmm0, %xmm0
	jmp	.L2
	.size	dot_product_avx512_f32, .-dot_product_avx512_f32
	.ident	"GCC: (Ubuntu 13.3.0-6ubuntu2~24.04.1) 13.3.0"
	.section	.note.GNU-stack,"",@progbits
