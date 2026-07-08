cmake_minimum_required(VERSION 3.20)

project(amd_perf_gbench_test LANGUAGES CXX)

set(CMAKE_CXX_STANDARD 17)
set(CMAKE_CXX_STANDARD_REQUIRED ON)
set(CMAKE_CXX_EXTENSIONS OFF)

get_filename_component(AMD_PERF_ROOT "${CMAKE_CURRENT_LIST_DIR}/.." ABSOLUTE)

set(BENCHMARK_ENABLE_TESTING OFF CACHE BOOL "" FORCE)
set(BENCHMARK_ENABLE_INSTALL OFF CACHE BOOL "" FORCE)
set(BENCHMARK_ENABLE_GTEST_TESTS OFF CACHE BOOL "" FORCE)

add_subdirectory(
  "${AMD_PERF_ROOT}/third_party/google-benchmark"
  "${CMAKE_BINARY_DIR}/third_party/google-benchmark"
  EXCLUDE_FROM_ALL
)

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

add_gbench_target(gbench_smoke benchmarks/smoke_bench.cpp)
add_gbench_target(fma_register_peak_bench benchmarks/fma_register_peak_bench.cpp)
