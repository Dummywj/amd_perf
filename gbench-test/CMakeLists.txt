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

add_executable(gbench_smoke
  benchmarks/smoke_bench.cpp
)

target_include_directories(gbench_smoke PRIVATE
  "${CMAKE_CURRENT_LIST_DIR}/include"
)

target_link_libraries(gbench_smoke PRIVATE benchmark::benchmark)

target_compile_options(gbench_smoke PRIVATE
  $<$<CXX_COMPILER_ID:GNU,Clang>:-O3 -march=native -Wall -Wextra -Wpedantic>
)
