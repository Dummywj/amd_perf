	.file	"fma_latency_avx512.cpp"
	.text
	.p2align 4
	.globl	fma_latency_avx512_f32
	.type	fma_latency_avx512_f32, @function
fma_latency_avx512_f32:
	testq	%rdx, %rdx
	je	.L8
	vbroadcastss	.LC1(%rip), %zmm2
	xorl	%eax, %eax
	vxorps	%xmm0, %xmm0, %xmm0
	vbroadcastss	.LC3(%rip), %zmm1
	.p2align 4,,10
	.p2align 3
.L3:
	vaddps	(%rdi,%rax,4), %zmm0, %zmm0
	vfmadd132ps	%zmm2, %zmm1, %zmm0
	vfmadd132ps	%zmm2, %zmm1, %zmm0
	vfmadd132ps	%zmm2, %zmm1, %zmm0
	vfmadd132ps	%zmm2, %zmm1, %zmm0
	vfmadd132ps	%zmm2, %zmm1, %zmm0
	vfmadd132ps	%zmm2, %zmm1, %zmm0
	vfmadd132ps	%zmm2, %zmm1, %zmm0
	vfmadd132ps	%zmm2, %zmm1, %zmm0
	vfmadd132ps	%zmm2, %zmm1, %zmm0
	vfmadd132ps	%zmm2, %zmm1, %zmm0
	vfmadd132ps	%zmm2, %zmm1, %zmm0
	vfmadd132ps	%zmm2, %zmm1, %zmm0
	vfmadd132ps	%zmm2, %zmm1, %zmm0
	vfmadd132ps	%zmm2, %zmm1, %zmm0
	vfmadd132ps	%zmm2, %zmm1, %zmm0
	vfmadd132ps	%zmm2, %zmm1, %zmm0
	vmovups	%zmm0, (%rsi,%rax,4)
	addq	$16, %rax
	cmpq	%rdx, %rax
	jb	.L3
	vzeroupper
.L8:
	ret
	.size	fma_latency_avx512_f32, .-fma_latency_avx512_f32
	.section	.rodata.cst4,"aM",@progbits,4
	.align 4
.LC1:
	.long	1065354055
	.align 4
.LC3:
	.long	966609234
	.ident	"GCC: (Ubuntu 13.3.0-6ubuntu2~24.04.1) 13.3.0"
	.section	.note.GNU-stack,"",@progbits
