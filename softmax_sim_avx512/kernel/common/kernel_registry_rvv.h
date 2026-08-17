#pragma once

#include <array>
#include <cstddef>
#include <string_view>

#include "common/kernel_interface.h"

struct RvvKernelSpec {
  std::string_view name;
  KernelF32 reference;
  KernelF32 rvv;
  std::size_t input_vectors;
  std::size_t output_count;
  float tolerance;
};

inline constexpr std::array<RvvKernelSpec, 11> kRvvKernelSpecs{{
    {"fma_throughput", fma_throughput_reference_f32,
     fma_throughput_rvv_f32, 1, 0, 2.0e-5f},
    {"fma_latency", fma_latency_reference_f32, fma_latency_rvv_f32, 1, 0,
     2.0e-5f},
    {"axpy", axpy_reference_f32, axpy_rvv_f32, 2, 0, 2.0e-6f},
    {"vector_copy", vector_copy_reference_f32, vector_copy_rvv_f32, 1, 0,
     0.0f},
    {"vector_triad", vector_triad_reference_f32, vector_triad_rvv_f32, 2, 0,
     2.0e-6f},
    {"pointer_agu", pointer_agu_reference_f32, pointer_agu_rvv_f32, 3, 0,
     2.0e-6f},
    {"dot_product", dot_product_reference_f32, dot_product_rvv_f32, 2, 1,
     1.0e-2f},
    {"vector_reduction", vector_reduction_reference_f32,
     vector_reduction_rvv_f32, 1, 2, 1.0e-2f},
    {"conversion", conversion_reference_f32, conversion_rvv_f32, 1, 0,
     0.0f},
    {"vector_integer", vector_integer_reference_f32, vector_integer_rvv_f32,
     1, 0, 0.0f},
    {"mixed_compute", mixed_compute_reference_f32, mixed_compute_rvv_f32, 1,
     0, 0.0f},
}};
