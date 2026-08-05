#pragma once

#include <cstddef>

// The AVX-512 kernel requires count >= 16 and count % 16 == 0. The reference
// and VLEN-agnostic RVV kernels accept any positive count.
extern "C" void softmax_reference_f32(const float* input, float* output,
                                      std::size_t count);
extern "C" void softmax_approx_reference_f32(const float* input,
                                             float* output,
                                             std::size_t count);
extern "C" void softmax_avx512_f32(const float* input, float* output,
                                   std::size_t count);
extern "C" void softmax_rvv_f32(const float* input, float* output,
                                std::size_t count);
