#pragma once

#include <cstddef>

using KernelF32 = void (*)(const float*, float*, std::size_t);

// Vector kernel workloads require count > 0 and count % 16 == 0.

extern "C" void fma_throughput_reference_f32(const float*, float*, std::size_t);
extern "C" void fma_throughput_avx512_f32(const float*, float*, std::size_t);
extern "C" void fma_throughput_rvv_f32(const float*, float*, std::size_t);

extern "C" void fma_latency_reference_f32(const float*, float*, std::size_t);
extern "C" void fma_latency_avx512_f32(const float*, float*, std::size_t);
extern "C" void fma_latency_rvv_f32(const float*, float*, std::size_t);

extern "C" void axpy_reference_f32(const float*, float*, std::size_t);
extern "C" void axpy_avx512_f32(const float*, float*, std::size_t);
extern "C" void axpy_rvv_f32(const float*, float*, std::size_t);

extern "C" void vector_copy_reference_f32(const float*, float*, std::size_t);
extern "C" void vector_copy_avx512_f32(const float*, float*, std::size_t);
extern "C" void vector_copy_rvv_f32(const float*, float*, std::size_t);

extern "C" void vector_triad_reference_f32(const float*, float*, std::size_t);
extern "C" void vector_triad_avx512_f32(const float*, float*, std::size_t);
extern "C" void vector_triad_rvv_f32(const float*, float*, std::size_t);

extern "C" void pointer_agu_reference_f32(const float*, float*, std::size_t);
extern "C" void pointer_agu_avx512_f32(const float*, float*, std::size_t);
extern "C" void pointer_agu_rvv_f32(const float*, float*, std::size_t);

extern "C" void dot_product_reference_f32(const float*, float*, std::size_t);
extern "C" void dot_product_avx512_f32(const float*, float*, std::size_t);
extern "C" void dot_product_rvv_f32(const float*, float*, std::size_t);

extern "C" void vector_reduction_reference_f32(const float*, float*, std::size_t);
extern "C" void vector_reduction_avx512_f32(const float*, float*, std::size_t);
extern "C" void vector_reduction_rvv_f32(const float*, float*, std::size_t);

extern "C" void conversion_reference_f32(const float*, float*, std::size_t);
extern "C" void conversion_avx512_f32(const float*, float*, std::size_t);
extern "C" void conversion_rvv_f32(const float*, float*, std::size_t);

extern "C" void vector_integer_reference_f32(const float*, float*, std::size_t);
extern "C" void vector_integer_avx512_f32(const float*, float*, std::size_t);
extern "C" void vector_integer_rvv_f32(const float*, float*, std::size_t);

extern "C" void mixed_compute_reference_f32(const float*, float*, std::size_t);
extern "C" void mixed_compute_avx512_f32(const float*, float*, std::size_t);
extern "C" void mixed_compute_rvv_f32(const float*, float*, std::size_t);
