cmake_minimum_required(VERSION 3.20)

project(amd_perf_gbench_test LANGUAGES C CXX)

set(CMAKE_CXX_STANDARD 17)
set(CMAKE_CXX_STANDARD_REQUIRED ON)
set(CMAKE_CXX_EXTENSIONS OFF)

if(CMAKE_INSTALL_PREFIX_INITIALIZED_TO_DEFAULT OR
   CMAKE_INSTALL_PREFIX STREQUAL "/usr/local")
  set(CMAKE_INSTALL_PREFIX "${CMAKE_BINARY_DIR}/install" CACHE PATH "" FORCE)
endif()

get_filename_component(AMD_PERF_ROOT "${CMAKE_CURRENT_LIST_DIR}/.." ABSOLUTE)

set(BENCHMARK_ENABLE_TESTING OFF CACHE BOOL "" FORCE)
set(BENCHMARK_ENABLE_INSTALL OFF CACHE BOOL "" FORCE)
set(BENCHMARK_ENABLE_GTEST_TESTS OFF CACHE BOOL "" FORCE)

set(SLEEF_BUILD_TESTS OFF CACHE BOOL "" FORCE)
set(SLEEF_BUILD_DFT OFF CACHE BOOL "" FORCE)
set(SLEEF_BUILD_QUAD OFF CACHE BOOL "" FORCE)
set(SLEEF_BUILD_GNUABI_LIBS OFF CACHE BOOL "" FORCE)
set(SLEEF_BUILD_SHARED_LIBS OFF CACHE BOOL "" FORCE)
set(SLEEF_ENABLE_TLFLOAT ON CACHE BOOL "" FORCE)

add_subdirectory(
  "${AMD_PERF_ROOT}/third_party/google-benchmark"
  "${CMAKE_BINARY_DIR}/third_party/google-benchmark"
  EXCLUDE_FROM_ALL
)

add_subdirectory(
  "${AMD_PERF_ROOT}/third_party/sleef"
  "${CMAKE_BINARY_DIR}/third_party/sleef"
  EXCLUDE_FROM_ALL
)

add_library(tlfloat STATIC IMPORTED GLOBAL)
set_target_properties(tlfloat PROPERTIES
  IMPORTED_LOCATION "${CMAKE_INSTALL_PREFIX}/lib/libtlfloat.a"
)
add_dependencies(tlfloat ext_tlfloat)

function(add_gbench_target target_name source_file)
  add_executable(${target_name}
    ${source_file}
  )

  target_include_directories(${target_name} PRIVATE
    "${CMAKE_CURRENT_LIST_DIR}/include"
  )

  target_link_libraries(${target_name} PRIVATE benchmark::benchmark)

  target_compile_options(${target_name} PRIVATE
    $<$<CXX_COMPILER_ID:GNU,Clang>:-O3 -march=native -Wall -Wextra -Wpedantic>
  )
endfunction()

add_library(ops_common STATIC benchmarks/ops_common.cpp)
target_include_directories(ops_common PUBLIC
  "${CMAKE_CURRENT_LIST_DIR}/include"
  "${CMAKE_BINARY_DIR}/include"
)
target_link_libraries(ops_common PUBLIC
  benchmark::benchmark
  sleef
  tlfloat
)
target_compile_options(ops_common PRIVATE
  $<$<CXX_COMPILER_ID:GNU,Clang>:-O3 -march=native -Wall -Wextra -Wpedantic>
)
add_dependencies(ops_common headers ext_tlfloat)

function(add_ops_benchmark target_name source_file)
  add_executable(${target_name} ${source_file})
  target_link_libraries(${target_name} PRIVATE ops_common)
  target_compile_options(${target_name} PRIVATE
    $<$<CXX_COMPILER_ID:GNU,Clang>:-O3 -march=native -Wall -Wextra -Wpedantic>
  )
endfunction()

add_gbench_target(gbench_smoke benchmarks/smoke_bench.cpp)
add_gbench_target(fma_register_peak_bench benchmarks/fma_register_peak_bench.cpp)
add_gbench_target(fp32_fma_length_sweep_bench benchmarks/fp32_fma_length_sweep_bench.cpp)

add_ops_benchmark(reduce_fp32_bench benchmarks/reduce_bench.cpp)
add_ops_benchmark(gather_fp32_bench benchmarks/gather_bench.cpp)
add_ops_benchmark(scatter_fp32_bench benchmarks/scatter_bench.cpp)
add_ops_benchmark(softmax_fp32_bench benchmarks/softmax_bench.cpp)

add_executable(ops_fp32_correctness benchmarks/ops_correctness.cpp)
target_link_libraries(ops_fp32_correctness PRIVATE ops_common)
target_compile_options(ops_fp32_correctness PRIVATE
  $<$<CXX_COMPILER_ID:GNU,Clang>:-O3 -march=native -Wall -Wextra -Wpedantic>
)
