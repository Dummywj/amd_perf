	.file	"mixed_compute_avx512.cpp"
	.text
	.p2align 4
	.globl	mixed_compute_avx512_f32
	.type	mixed_compute_avx512_f32, @function
mixed_compute_avx512_f32:
	testq	%rdx, %rdx
	je	.L8
	movl	$17, %ecx
	xorl	%eax, %eax
	vbroadcastss	.LC2(%rip), %zmm2
	vpbroadcastd	%ecx, %zmm1
	.p2align 4,,10
	.p2align 3
.L3:
	vcvttps2dq	(%rdi,%rax,4), %zmm0
	vpaddd	%zmm1, %zmm0, %zmm0
	vpslld	$1, %zmm0, %zmm0
	vcvtdq2ps	%zmm0, %zmm0
	vfmadd213ps	(%rdi,%rax,4), %zmm2, %zmm0
	vmovups	%zmm0, (%rsi,%rax,4)
	addq	$16, %rax
	cmpq	%rdx, %rax
	jb	.L3
	vzeroupper
.L8:
	ret
	.size	mixed_compute_avx512_f32, .-mixed_compute_avx512_f32
	.section	.rodata.cst4,"aM",@progbits,4
	.align 4
.LC2:
	.long	1048576000
	.ident	"GCC: (Ubuntu 13.3.0-6ubuntu2~24.04.1) 13.3.0"
	.section	.note.GNU-stack,"",@progbits
