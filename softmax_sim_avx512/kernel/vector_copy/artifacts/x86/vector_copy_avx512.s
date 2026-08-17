	.file	"vector_copy_avx512.cpp"
	.text
	.p2align 4
	.globl	vector_copy_avx512_f32
	.type	vector_copy_avx512_f32, @function
vector_copy_avx512_f32:
	testq	%rdx, %rdx
	je	.L8
	xorl	%eax, %eax
	.p2align 4,,10
	.p2align 3
.L3:
	vmovups	(%rdi,%rax,4), %zmm0
	vmovups	%zmm0, (%rsi,%rax,4)
	addq	$16, %rax
	cmpq	%rdx, %rax
	jb	.L3
	vzeroupper
.L8:
	ret
	.size	vector_copy_avx512_f32, .-vector_copy_avx512_f32
	.ident	"GCC: (Ubuntu 13.3.0-6ubuntu2~24.04.1) 13.3.0"
	.section	.note.GNU-stack,"",@progbits
