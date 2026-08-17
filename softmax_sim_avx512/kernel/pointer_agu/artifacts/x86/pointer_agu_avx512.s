	.file	"pointer_agu_avx512.cpp"
	.text
	.p2align 4
	.globl	pointer_agu_avx512_f32
	.type	pointer_agu_avx512_f32, @function
pointer_agu_avx512_f32:
	testq	%rdx, %rdx
	je	.L8
	leaq	0(,%rdx,4), %rcx
	xorl	%eax, %eax
	leaq	(%rdi,%rcx), %r8
	addq	%r8, %rcx
	.p2align 4,,10
	.p2align 3
.L3:
	vmovups	(%rdi,%rax,4), %zmm1
	vaddps	(%r8,%rax,4), %zmm1, %zmm0
	vaddps	(%rcx,%rax,4), %zmm0, %zmm0
	vmovups	%zmm0, (%rsi,%rax,4)
	addq	$16, %rax
	cmpq	%rdx, %rax
	jb	.L3
	vzeroupper
.L8:
	ret
	.size	pointer_agu_avx512_f32, .-pointer_agu_avx512_f32
	.ident	"GCC: (Ubuntu 13.3.0-6ubuntu2~24.04.1) 13.3.0"
	.section	.note.GNU-stack,"",@progbits
