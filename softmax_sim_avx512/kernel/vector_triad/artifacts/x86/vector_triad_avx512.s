	.file	"vector_triad_avx512.cpp"
	.text
	.p2align 4
	.globl	vector_triad_avx512_f32
	.type	vector_triad_avx512_f32, @function
vector_triad_avx512_f32:
	testq	%rdx, %rdx
	je	.L8
	vbroadcastss	.LC1(%rip), %zmm1
	leaq	(%rdi,%rdx,4), %rcx
	xorl	%eax, %eax
	.p2align 4,,10
	.p2align 3
.L3:
	vmovups	(%rcx,%rax,4), %zmm0
	vfmadd213ps	(%rdi,%rax,4), %zmm1, %zmm0
	vmovups	%zmm0, (%rsi,%rax,4)
	addq	$16, %rax
	cmpq	%rdx, %rax
	jb	.L3
	vzeroupper
.L8:
	ret
	.size	vector_triad_avx512_f32, .-vector_triad_avx512_f32
	.section	.rodata.cst4,"aM",@progbits,4
	.align 4
.LC1:
	.long	1067450368
	.ident	"GCC: (Ubuntu 13.3.0-6ubuntu2~24.04.1) 13.3.0"
	.section	.note.GNU-stack,"",@progbits
