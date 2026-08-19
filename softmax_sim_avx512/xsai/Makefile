NAME := xsai-kernel-bench
APP_DIR := $(abspath $(dir $(lastword $(MAKEFILE_LIST))))
KERNEL_DIR := $(abspath $(APP_DIR)/../kernel)

MARCH ?= rv64gcv_zvl128b
MCMODEL := -mcmodel=medany
SAMPLES ?= 5
CC_OPT := -O3
CPPFLAGS += -DXSAI_BENCH_SAMPLES=$(SAMPLES)
CPPFLAGS += -DXSAI_PROFILE_ITERATIONS=$(PROFILE_ITERATIONS)
PROFILE_ITERATIONS ?= 64
CXXFLAGS += -std=c++20 -O3
INC_DIR += $(KERNEL_DIR) $(KERNEL_DIR)/softmax

SRCS := \
  src/benchmark.cpp \
  src/perf_counters.cpp \
  src/profile_microbench.S \
  src/kernels/axpy.cpp \
  src/kernels/conversion.cpp \
  src/kernels/dot_product.cpp \
  src/kernels/fma_latency.cpp \
  src/kernels/fma_throughput.cpp \
  src/kernels/mixed_compute.cpp \
  src/kernels/pointer_agu.cpp \
  src/kernels/softmax.cpp \
  src/kernels/vector_copy.cpp \
  src/kernels/vector_integer.cpp \
  src/kernels/vector_reduction.cpp \
  src/kernels/vector_triad.cpp

include $(AM_HOME)/Makefile.app
