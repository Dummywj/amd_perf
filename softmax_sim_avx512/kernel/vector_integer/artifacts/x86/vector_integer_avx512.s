	.file	"vector_integer_avx512.cpp"
	.text
	.p2align 4
	.globl	vector_integer_avx512_f32
	.type	vector_integer_avx512_f32, @function
vector_integer_avx512_f32:
	testq	%rdx, %rdx
	je	.L8
	movl	$17, %ecx
	xorl	%eax, %eax
	vpbroadcastd	%ecx, %zmm1
	.p2align 4,,10
	.p2align 3
.L3:
	vpaddd	(%rdi,%rax,4), %zmm1, %zmm0
	vpslld	$1, %zmm0, %zmm0
	vmovdqu64	%zmm0, (%rsi,%rax,4)
	addq	$16, %rax
	cmpq	%rdx, %rax
	jb	.L3
	vzeroupper
.L8:
	ret
	.size	vector_integer_avx512_f32, .-vector_integer_avx512_f32
	.ident	"GCC: (Ubuntu 13.3.0-6ubuntu2~24.04.1) 13.3.0"
	.section	.note.GNU-stack,"",@progbits
