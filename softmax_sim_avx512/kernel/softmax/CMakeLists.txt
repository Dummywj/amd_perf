cmake_minimum_required(VERSION 3.20)

project(softmax_kernels LANGUAGES CXX)

set(CMAKE_CXX_STANDARD 20)
set(CMAKE_CXX_STANDARD_REQUIRED ON)
set(CMAKE_CXX_EXTENSIONS OFF)

add_library(softmax_reference STATIC reference/softmax_reference.cpp)
target_include_directories(softmax_reference PUBLIC ${CMAKE_CURRENT_SOURCE_DIR})
target_compile_options(softmax_reference PRIVATE -Wall -Wextra -Wpedantic)

add_library(softmax_avx512 STATIC x86/softmax_avx512.cpp)
target_include_directories(softmax_avx512 PUBLIC ${CMAKE_CURRENT_SOURCE_DIR})
target_compile_options(
  softmax_avx512 PRIVATE
  -Wall -Wextra -Wpedantic
  -fno-stack-protector -fno-asynchronous-unwind-tables
  -fno-unwind-tables -fno-exceptions -fno-rtti -fno-pie -fcf-protection=none
  -mavx512f -mavx512dq -mavx512bw -mavx512vl -mfma)

add_executable(
  softmax_correctness
  tests/softmax_correctness.cpp)
target_link_libraries(
  softmax_correctness PRIVATE softmax_reference softmax_avx512)
target_compile_options(softmax_correctness PRIVATE -Wall -Wextra -Wpedantic)

add_executable(softmax_cycles benchmarks/softmax_cycles.cpp)
target_link_libraries(softmax_cycles PRIVATE softmax_avx512)
target_include_directories(
  softmax_cycles PRIVATE ${CMAKE_CURRENT_SOURCE_DIR}/../../../amd_profile_benchmark/include)
target_compile_options(softmax_cycles PRIVATE -O3 -Wall -Wextra -Wpedantic)

enable_testing()
add_test(NAME softmax_correctness COMMAND softmax_correctness)
