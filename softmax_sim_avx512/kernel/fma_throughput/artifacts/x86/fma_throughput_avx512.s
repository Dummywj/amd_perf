	.file	"fma_throughput_avx512.cpp"
	.text
	.p2align 4
	.globl	fma_throughput_avx512_f32
	.type	fma_throughput_avx512_f32, @function
fma_throughput_avx512_f32:
	movq	%rsi, %r8
	xorl	%eax, %eax
	movq	%rdx, %rsi
	cmpq	$127, %rdx
	jbe	.L3
	leaq	-128(%rsi), %rcx
	movq	%rdi, %rax
	movq	%r8, %rdx
	vbroadcastss	.LC1(%rip), %zmm1
	vbroadcastss	.LC3(%rip), %zmm0
	movq	%rcx, %r9
	shrq	$7, %r9
	vmovaps	%zmm1, %zmm5
	salq	$9, %r9
	vmovaps	%zmm0, %zmm4
	leaq	512(%rdi,%r9), %r9
.L6:
	vmovaps	%zmm1, %zmm11
	vmovaps	%zmm1, %zmm10
	vmovaps	%zmm1, %zmm9
	addq	$512, %rax
	vfmadd132ps	-512(%rax), %zmm0, %zmm11
	vmovaps	%zmm1, %zmm8
	vmovaps	%zmm1, %zmm7
	addq	$512, %rdx
	vfmadd132ps	-448(%rax), %zmm0, %zmm10
	vmovaps	%zmm1, %zmm6
	vmovaps	%zmm1, %zmm3
	vfmadd132ps	-384(%rax), %zmm0, %zmm9
	vmovaps	%zmm1, %zmm2
	vfmadd132ps	-128(%rax), %zmm0, %zmm3
	vfmadd132ps	-64(%rax), %zmm0, %zmm2
	vfmadd132ps	-320(%rax), %zmm0, %zmm8
	vfmadd132ps	-256(%rax), %zmm0, %zmm7
	vfmadd132ps	-192(%rax), %zmm0, %zmm6
	vfmadd132ps	%zmm1, %zmm0, %zmm11
	vfmadd132ps	%zmm1, %zmm0, %zmm10
	vfmadd132ps	%zmm1, %zmm0, %zmm9
	vfmadd132ps	%zmm1, %zmm0, %zmm3
	vfmadd132ps	%zmm1, %zmm0, %zmm2
	vfmadd132ps	%zmm1, %zmm0, %zmm8
	vfmadd132ps	%zmm1, %zmm0, %zmm7
	vfmadd132ps	%zmm1, %zmm0, %zmm6
	vfmadd132ps	%zmm1, %zmm0, %zmm11
	vfmadd132ps	%zmm1, %zmm0, %zmm10
	vfmadd132ps	%zmm1, %zmm0, %zmm9
	vfmadd132ps	%zmm1, %zmm0, %zmm3
	vfmadd132ps	%zmm1, %zmm0, %zmm2
	vfmadd132ps	%zmm1, %zmm0, %zmm8
	vfmadd132ps	%zmm1, %zmm0, %zmm7
	vfmadd132ps	%zmm1, %zmm0, %zmm6
	vfmadd132ps	%zmm1, %zmm0, %zmm11
	vfmadd132ps	%zmm1, %zmm0, %zmm10
	vfmadd132ps	%zmm1, %zmm0, %zmm9
	vfmadd132ps	%zmm1, %zmm0, %zmm3
	vfmadd132ps	%zmm1, %zmm0, %zmm2
	vfmadd132ps	%zmm1, %zmm0, %zmm8
	vfmadd132ps	%zmm1, %zmm0, %zmm7
	vfmadd132ps	%zmm1, %zmm0, %zmm6
	vfmadd132ps	%zmm1, %zmm0, %zmm11
	vfmadd132ps	%zmm1, %zmm0, %zmm10
	vfmadd132ps	%zmm1, %zmm0, %zmm9
	vfmadd132ps	%zmm1, %zmm0, %zmm3
	vfmadd132ps	%zmm1, %zmm0, %zmm2
	vfmadd132ps	%zmm1, %zmm0, %zmm8
	vfmadd132ps	%zmm1, %zmm0, %zmm7
	vfmadd132ps	%zmm1, %zmm0, %zmm6
	vfmadd132ps	%zmm1, %zmm0, %zmm11
	vfmadd132ps	%zmm1, %zmm0, %zmm10
	vfmadd132ps	%zmm1, %zmm0, %zmm9
	vfmadd132ps	%zmm1, %zmm0, %zmm3
	vfmadd132ps	%zmm1, %zmm0, %zmm2
	vfmadd132ps	%zmm1, %zmm0, %zmm8
	vfmadd132ps	%zmm1, %zmm0, %zmm7
	vfmadd132ps	%zmm1, %zmm0, %zmm6
	vfmadd132ps	%zmm1, %zmm0, %zmm11
	vfmadd132ps	%zmm1, %zmm0, %zmm10
	vfmadd132ps	%zmm1, %zmm0, %zmm9
	vfmadd132ps	%zmm1, %zmm0, %zmm3
	vfmadd132ps	%zmm1, %zmm0, %zmm2
	vfmadd132ps	%zmm1, %zmm0, %zmm8
	vfmadd132ps	%zmm1, %zmm0, %zmm7
	vfmadd132ps	%zmm1, %zmm0, %zmm6
	vfmadd132ps	%zmm1, %zmm0, %zmm11
	vfmadd132ps	%zmm1, %zmm0, %zmm10
	vfmadd132ps	%zmm1, %zmm0, %zmm9
	vfmadd132ps	%zmm1, %zmm0, %zmm3
	vfmadd132ps	%zmm1, %zmm0, %zmm2
	vfmadd132ps	%zmm1, %zmm0, %zmm8
	vfmadd132ps	%zmm1, %zmm0, %zmm7
	vfmadd132ps	%zmm1, %zmm0, %zmm6
	vfmadd132ps	%zmm1, %zmm0, %zmm11
	vfmadd132ps	%zmm1, %zmm0, %zmm10
	vfmadd132ps	%zmm1, %zmm0, %zmm9
	vfmadd132ps	%zmm1, %zmm0, %zmm3
	vfmadd132ps	%zmm1, %zmm0, %zmm2
	vfmadd132ps	%zmm1, %zmm0, %zmm8
	vfmadd132ps	%zmm1, %zmm0, %zmm7
	vfmadd132ps	%zmm1, %zmm0, %zmm6
	vfmadd132ps	%zmm1, %zmm0, %zmm11
	vfmadd132ps	%zmm1, %zmm0, %zmm10
	vfmadd132ps	%zmm1, %zmm0, %zmm9
	vfmadd132ps	%zmm1, %zmm0, %zmm3
	vfmadd132ps	%zmm1, %zmm0, %zmm2
	vfmadd132ps	%zmm1, %zmm0, %zmm8
	vfmadd132ps	%zmm1, %zmm0, %zmm7
	vfmadd132ps	%zmm1, %zmm0, %zmm6
	vfmadd132ps	%zmm1, %zmm0, %zmm11
	vfmadd132ps	%zmm1, %zmm0, %zmm10
	vfmadd132ps	%zmm1, %zmm0, %zmm9
	vfmadd132ps	%zmm1, %zmm0, %zmm3
	vfmadd132ps	%zmm1, %zmm0, %zmm2
	vfmadd132ps	%zmm1, %zmm0, %zmm8
	vfmadd132ps	%zmm1, %zmm0, %zmm7
	vfmadd132ps	%zmm1, %zmm0, %zmm6
	vfmadd132ps	%zmm1, %zmm0, %zmm11
	vfmadd132ps	%zmm1, %zmm0, %zmm10
	vfmadd132ps	%zmm1, %zmm0, %zmm9
	vfmadd132ps	%zmm1, %zmm0, %zmm3
	vfmadd132ps	%zmm1, %zmm0, %zmm2
	vfmadd132ps	%zmm1, %zmm0, %zmm8
	vfmadd132ps	%zmm1, %zmm0, %zmm7
	vfmadd132ps	%zmm1, %zmm0, %zmm6
	vfmadd132ps	%zmm1, %zmm0, %zmm11
	vfmadd132ps	%zmm1, %zmm0, %zmm10
	vfmadd132ps	%zmm1, %zmm0, %zmm9
	vfmadd132ps	%zmm1, %zmm0, %zmm3
	vfmadd132ps	%zmm1, %zmm0, %zmm2
	vfmadd132ps	%zmm1, %zmm0, %zmm8
	vfmadd132ps	%zmm1, %zmm0, %zmm7
	vfmadd132ps	%zmm1, %zmm0, %zmm6
	vfmadd132ps	%zmm1, %zmm0, %zmm11
	vfmadd132ps	%zmm1, %zmm0, %zmm10
	vfmadd132ps	%zmm1, %zmm0, %zmm9
	vfmadd132ps	%zmm1, %zmm0, %zmm3
	vfmadd132ps	%zmm1, %zmm0, %zmm2
	vfmadd132ps	%zmm1, %zmm0, %zmm8
	vfmadd132ps	%zmm1, %zmm0, %zmm7
	vfmadd132ps	%zmm1, %zmm0, %zmm6
	vfmadd132ps	%zmm1, %zmm0, %zmm11
	vfmadd132ps	%zmm1, %zmm0, %zmm10
	vfmadd132ps	%zmm1, %zmm0, %zmm9
	vfmadd132ps	%zmm1, %zmm0, %zmm3
	vfmadd132ps	%zmm1, %zmm0, %zmm2
	vfmadd132ps	%zmm1, %zmm0, %zmm8
	vfmadd132ps	%zmm1, %zmm0, %zmm7
	vfmadd132ps	%zmm1, %zmm0, %zmm6
	vfmadd132ps	%zmm1, %zmm0, %zmm11
	vfmadd132ps	%zmm1, %zmm0, %zmm10
	vfmadd132ps	%zmm1, %zmm0, %zmm9
	vfmadd132ps	%zmm5, %zmm4, %zmm3
	vfmadd132ps	%zmm5, %zmm4, %zmm2
	vfmadd132ps	%zmm1, %zmm0, %zmm8
	vfmadd132ps	%zmm5, %zmm4, %zmm7
	vmovaps	%zmm5, %zmm1
	vfmadd132ps	%zmm5, %zmm4, %zmm6
	vmovaps	%zmm4, %zmm0
	vmovups	%zmm11, -512(%rdx)
	vmovups	%zmm10, -448(%rdx)
	vmovups	%zmm9, -384(%rdx)
	vmovups	%zmm3, -128(%rdx)
	vmovups	%zmm8, -320(%rdx)
	vmovups	%zmm7, -256(%rdx)
	vmovups	%zmm6, -192(%rdx)
	vmovups	%zmm2, -64(%rdx)
	cmpq	%r9, %rax
	jne	.L6
	movq	%rcx, %rax
	andq	$-128, %rax
	subq	$-128, %rax
.L3:
	vbroadcastss	.LC1(%rip), %zmm1
	vbroadcastss	.LC3(%rip), %zmm0
	cmpq	%rsi, %rax
	jnb	.L13
.L4:
	vmovaps	%zmm1, %zmm2
	vfmadd132ps	(%rdi,%rax,4), %zmm0, %zmm2
	vfmadd132ps	%zmm1, %zmm0, %zmm2
	vfmadd132ps	%zmm1, %zmm0, %zmm2
	vfmadd132ps	%zmm1, %zmm0, %zmm2
	vfmadd132ps	%zmm1, %zmm0, %zmm2
	vfmadd132ps	%zmm1, %zmm0, %zmm2
	vfmadd132ps	%zmm1, %zmm0, %zmm2
	vfmadd132ps	%zmm1, %zmm0, %zmm2
	vfmadd132ps	%zmm1, %zmm0, %zmm2
	vfmadd132ps	%zmm1, %zmm0, %zmm2
	vfmadd132ps	%zmm1, %zmm0, %zmm2
	vfmadd132ps	%zmm1, %zmm0, %zmm2
	vfmadd132ps	%zmm1, %zmm0, %zmm2
	vfmadd132ps	%zmm1, %zmm0, %zmm2
	vfmadd132ps	%zmm1, %zmm0, %zmm2
	vfmadd132ps	%zmm1, %zmm0, %zmm2
	vmovups	%zmm2, (%r8,%rax,4)
	addq	$16, %rax
	cmpq	%rsi, %rax
	jb	.L4
.L13:
	vzeroupper
	ret
	.size	fma_throughput_avx512_f32, .-fma_throughput_avx512_f32
	.section	.rodata.cst4,"aM",@progbits,4
	.align 4
.LC1:
	.long	1065354055
	.align 4
.LC3:
	.long	966609234
	.ident	"GCC: (Ubuntu 13.3.0-6ubuntu2~24.04.1) 13.3.0"
	.section	.note.GNU-stack,"",@progbits
