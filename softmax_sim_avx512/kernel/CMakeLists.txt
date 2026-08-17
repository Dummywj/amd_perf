cmake_minimum_required(VERSION 3.20)

project(vector_kernel_suite LANGUAGES CXX)

set(CMAKE_CXX_STANDARD 20)
set(CMAKE_CXX_STANDARD_REQUIRED ON)
set(CMAKE_CXX_EXTENSIONS OFF)

set(KERNEL_WARNING_FLAGS -Wall -Wextra -Wpedantic)
set(KERNEL_CODEGEN_FLAGS
  -fno-stack-protector
  -fno-asynchronous-unwind-tables
  -fno-unwind-tables
  -fno-exceptions
  -fno-rtti
  -fno-pie
  -fcf-protection=none)
set(KERNEL_AVX512_FLAGS
  -mavx512f
  -mavx512dq
  -mavx512bw
  -mavx512vl
  -mfma)

set(KERNEL_X86_SOURCES
  fma_throughput/x86/fma_throughput_avx512.cpp
  fma_latency/x86/fma_latency_avx512.cpp
  axpy/x86/axpy_avx512.cpp
  dot_product/x86/dot_product_avx512.cpp
  vector_copy/x86/vector_copy_avx512.cpp
  vector_triad/x86/vector_triad_avx512.cpp
  vector_reduction/x86/vector_reduction_avx512.cpp
  conversion/x86/conversion_avx512.cpp
  vector_integer/x86/vector_integer_avx512.cpp
  mixed_compute/x86/mixed_compute_avx512.cpp
  pointer_agu/x86/pointer_agu_avx512.cpp)

add_library(kernel_reference STATIC reference/kernel_references.cpp)
target_include_directories(kernel_reference PUBLIC ${CMAKE_CURRENT_SOURCE_DIR})
target_compile_options(kernel_reference PRIVATE ${KERNEL_WARNING_FLAGS})

add_library(kernel_avx512 STATIC ${KERNEL_X86_SOURCES})
target_include_directories(kernel_avx512 PUBLIC ${CMAKE_CURRENT_SOURCE_DIR})
target_compile_options(kernel_avx512 PRIVATE
  ${KERNEL_WARNING_FLAGS}
  ${KERNEL_CODEGEN_FLAGS}
  ${KERNEL_AVX512_FLAGS})

add_executable(kernel_correctness tests/kernel_correctness.cpp)
target_link_libraries(kernel_correctness PRIVATE kernel_reference kernel_avx512)
target_compile_options(kernel_correctness PRIVATE ${KERNEL_WARNING_FLAGS})

add_executable(kernel_cycles benchmarks/kernel_cycles.cpp)
target_link_libraries(kernel_cycles PRIVATE kernel_avx512 kernel_reference)
target_include_directories(kernel_cycles PRIVATE
  ${CMAKE_CURRENT_SOURCE_DIR}/../../amd_profile_benchmark/include)
target_compile_options(kernel_cycles PRIVATE
  -O3
  ${KERNEL_WARNING_FLAGS}
  ${KERNEL_AVX512_FLAGS})

add_subdirectory(softmax)

enable_testing()
add_test(NAME kernel_correctness COMMAND kernel_correctness)
