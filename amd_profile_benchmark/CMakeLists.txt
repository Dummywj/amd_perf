cmake_minimum_required(VERSION 3.20)

project(amd_profile_benchmark LANGUAGES CXX)

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

add_executable(amd_profile_benchmark
  src/main.cpp
  src/static_inventory.cpp
  src/pipeline_width.cpp
  src/instruction_latency.cpp
  src/instruction_throughput.cpp
  src/resource_contention.cpp
  src/window_capacity.cpp
  src/cache_latency.cpp
  src/cache_bandwidth.cpp
  src/memory_parallelism.cpp
)

target_include_directories(amd_profile_benchmark PRIVATE
  "${CMAKE_CURRENT_LIST_DIR}/include"
)

target_link_libraries(amd_profile_benchmark PRIVATE benchmark::benchmark)

target_compile_options(amd_profile_benchmark PRIVATE
  $<$<CXX_COMPILER_ID:GNU,Clang>:
    -O3
    -march=znver4
    -mavx512f
    -mavx512dq
    -mavx512bw
    -mavx512vl
    -Wall
    -Wextra
    -Wpedantic
  >
)

target_compile_definitions(amd_profile_benchmark PRIVATE
  AMD_PROFILE_SOURCE_DIR="${CMAKE_CURRENT_LIST_DIR}"
)
