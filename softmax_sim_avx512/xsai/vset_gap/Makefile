NAME := xsai-vset-gap
APP_DIR := $(abspath $(dir $(lastword $(MAKEFILE_LIST))))

MARCH ?= rv64gcv_zvl128b
MCMODEL := -mcmodel=medany
SAMPLES ?= 5
ITERATIONS ?= 64
CC_OPT := -O3
CPPFLAGS += -DXSAI_VSET_GAP_SAMPLES=$(SAMPLES)
CPPFLAGS += -DXSAI_VSET_GAP_ITERATIONS=$(ITERATIONS)
CXXFLAGS += -std=c++20 -O3
INC_DIR += $(APP_DIR)/../src

SRCS := \
  src/benchmark.cpp \
  src/perf_counters_bridge.cpp \
  src/vset_gap_microbench.S

include $(AM_HOME)/Makefile.app
